"""Corso e-learning dal link aperto (``/corso-aperto/<token>/``): senza login.

Prefisso in ``MIDDLEWARE_EXEMPT_PREFIXES``, view in ``PUBLIC_VIEWS``. Pensato anche per
internet (Entra Application Proxy, come ``/richiesta-visita/``). Protezioni:

- token lungo per corso, che l'HR spegne o rigenera; corso non pubblicato o link scaduto = 404;
- slide servite solo in ordine e dopo i secondi minimi della slide precedente; immagini e
  video solo delle slide già aperte in questa sessione del browser;
- quiz solo dopo l'ultima slide e il tempo minimo del corso, entrambi misurati dal server;
- prima di iniziare la persona si registra (nome, cognome, matricola): il tempo parte da lì;
  chi è registrato può consultare liberamente tutto il materiale, ma il quiz si apre solo
  dopo il percorso guidato;
- limite di invii per IP e globale, campo trappola;
- la pagina non mostra mai l'elenco dei dipendenti né a chi è stato abbinato il quiz.

La logica (correzione, abbinamento, completamento) è in ``services/elearning_link_aperto.py``.
"""
from __future__ import annotations

import random
import secrets
import time
from datetime import datetime

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from core.net import client_ip
from core.public_headers import risposta_pubblica, risposta_pubblica_con_form

from .models_formazione import TrainingSlide
from .services import elearning_link_aperto as servizio
from .services import elearning_quiz as quiz
from .services.elearning_regole import regola_corso, secondi_richiesti_slide

LIMITE_IP, FINESTRA_IP = 60, 3600          # in officina molti telefoni escono dallo stesso IP
LIMITE_GLOBALE, FINESTRA_GLOBALE = 400, 3600
_LOOPBACK = {"127.0.0.1", "::1", ""}


def _link(token: str):
    link = servizio.link_valido(token)
    if link is None:
        raise Http404
    return link


def _chiave(link) -> str:
    return f"corso_aperto:{link.pk}:{link.token[:12]}"


COOKIE_GIORNI = 30
_SALE_COOKIE = "corso_aperto.ripresa"


def _cookie_nome(link) -> str:
    return f"pn_corso_{link.pk}"


def _stato_da_partecipazione(p) -> dict:
    """Stato del browser ricostruito dal server: slide viste, secondi di video, tempo dalla registrazione."""
    return {"avvio": p.registrato_il.timestamp(), "viste": dict(p.slide_viste or {}),
            "chi": {"nome": p.nome, "cognome": p.cognome, "matricola": p.matricola}, "pid": p.pk,
            "percorso": p.percorso or "",
            "video": {str(k): [int(v or 0), 0] for k, v in (p.video_visti or {}).items()}}


def _stato(request, link) -> dict:
    stato = request.session.get(_chiave(link))
    if isinstance(stato, dict):
        return stato
    # Sessione del browser scaduta (o chiusa): lo stesso telefono riprende dal cookie firmato.
    from .models_elearning import TrainingElearningPartecipazioneAperta as P
    try:
        pid = int(request.get_signed_cookie(_cookie_nome(link), default="0", salt=_SALE_COOKIE,
                                            max_age=COOKIE_GIORNI * 86400) or 0)
    except (TypeError, ValueError):
        pid = 0
    p = P.objects.filter(pk=pid, corso=link.corso).first() if pid else None
    if p is not None:
        stato = _stato_da_partecipazione(p)
        request.session[_chiave(link)] = stato
        request.session.modified = True
        return stato
    return {"avvio": time.time(), "viste": {}}


def _ricorda(response, link, stato):
    """Il telefono ricorda la partecipazione per 30 giorni (cookie firmato, solo l'id)."""
    if stato.get("pid"):
        response.set_signed_cookie(_cookie_nome(link), str(stato["pid"]), salt=_SALE_COOKIE,
                                   max_age=COOKIE_GIORNI * 86400, httponly=True, samesite="Lax", path="/corso-aperto/",
                                   secure=settings.SESSION_COOKIE_SECURE)
    return response


def _punto_di_ripresa(stato, slides) -> int:
    """Indice (da 0) della prima slide del percorso non ancora aperta; l'ultima se le ha viste tutte."""
    viste = stato.get("viste") or {}
    for i, s in enumerate(slides):
        if str(s.ordine) not in viste:
            return i
    return len(slides) - 1


CREDITO_MAX_SECONDI = 120  # oltre, la pagina è rimasta aperta senza nessuno davanti


def _salva(request, link, stato: dict) -> None:
    request.session[_chiave(link)] = stato
    request.session.modified = True
    _sincronizza(stato)


def _partecipazione(stato):
    from .models_elearning import TrainingElearningPartecipazioneAperta as P
    pid = stato.get("pid")
    return P.objects.filter(pk=pid).first() if pid else None


def _sincronizza(stato) -> None:
    """Copia sul server avanzamento e tempo effettivo della partecipazione (se registrata)."""
    p = _partecipazione(stato)
    if p is None:
        return
    adesso = timezone.now()
    campi = ["slide_viste", "ultimo_accesso_il"]
    if p.ultimo_accesso_il:
        delta = (adesso - p.ultimo_accesso_il).total_seconds()
        if 0 < delta:
            p.secondi = (p.secondi or 0) + int(min(delta, CREDITO_MAX_SECONDI))
            campi.append("secondi")
    p.slide_viste = dict(stato.get("viste") or {})
    p.ultimo_accesso_il = adesso
    p.save(update_fields=campi)


def _slides(corso, stato=None) -> list:
    """Slide del percorso guidato (moduli «Nel percorso» e slide senza modulo; con video o slide a
    scelta, solo i moduli del percorso scelto)."""
    from .services.elearning_fruizione import slides_percorso
    return list(slides_percorso(corso, (stato or {}).get("percorso", "")))


def _deve_scegliere(corso, stato) -> bool:
    from .services.elearning_fruizione import percorsi_a_scelta
    return percorsi_a_scelta(corso) and stato.get("percorso") not in ("VIDEO", "SLIDE")


def _slides_tutte(corso) -> list:
    return list(corso.slides.filter(is_active=True).select_related("modulo").order_by("ordine", "pk"))


def _video_mancante(stato, slide) -> int:
    from .services.elearning_fruizione import video_mancante
    visto = (stato.get("video") or {}).get(str(slide.pk)) or [0, 0]
    return video_mancante(slide, visto[0], visto[1])


def _secondi_mancanti(stato, slide, regola) -> int:
    vista = stato["viste"].get(str(slide.ordine))
    richiesti = secondi_richiesti_slide(slide, regola)
    video = _video_mancante(stato, slide) if vista is not None else 0
    if vista is None or not richiesti:
        return video
    return max(int(richiesti - (time.time() - vista)), video, 0)


def _tempo_mancante(stato, regola) -> int:
    """Secondi che mancano al tempo minimo del corso (dal primo accesso in questo browser)."""
    if not regola.tempo_minimo_minuti:
        return 0
    return max(int(regola.tempo_minimo_minuti * 60 - (time.time() - stato["avvio"])), 0)


def _slide_ammessa(stato, slides, pos: int, regola) -> bool:
    """La prima sempre; le altre se la precedente è stata aperta e ha avuto i suoi secondi."""
    if pos == 0 or str(slides[pos].ordine) in stato["viste"]:
        return True
    prec = slides[pos - 1]
    return str(prec.ordine) in stato["viste"] and _secondi_mancanti(stato, prec, regola) == 0


def _registrato(stato) -> bool:
    return isinstance(stato.get("chi"), dict) and bool(stato["chi"].get("cognome"))


@require_http_methods(["GET", "POST"])
@risposta_pubblica_con_form
def registrati(request, token: str):
    """Prima di iniziare: nome, cognome e matricola. Il tempo del corso parte da qui."""
    link = _link(token)
    corso_obj = link.corso
    stato = _stato(request, link)
    if request.method == "GET" and _registrato(stato) and request.GET.get("cambia") != "1":
        return redirect("corso_aperto:corso", token=token)
    dati, errori = {"nome": "", "cognome": "", "matricola": ""}, []
    reparto = _testo(request.GET.get("rep") or request.POST.get("rep"), 120)
    if request.method == "POST":
        if request.POST.get("sito_web"):
            raise Http404
        codice = _testo(request.POST.get("codice"), 12).upper().replace(" ", "")
        if codice:
            # Ripresa da un altro telefono: codice + cognome.
            from .models_elearning import TrainingElearningPartecipazioneAperta as P
            from core.naming import chiave_testo
            p = P.objects.filter(corso=corso_obj, codice=codice).first()
            if p is None or chiave_testo(p.cognome) != chiave_testo(request.POST.get("cognome_ripresa")):
                errori.append("Codice o cognome non corretti.")
            else:
                stato = _stato_da_partecipazione(p)
                stato["ripresa"] = True
                _salva(request, link, stato)
                return _ricorda(redirect("corso_aperto:pronto", token=token), link, stato)
        else:
            dati = {"nome": _testo(request.POST.get("nome"), 100), "cognome": _testo(request.POST.get("cognome"), 100),
                    "matricola": _testo(request.POST.get("matricola"), 40)}
            if not dati["nome"] or not dati["cognome"]:
                errori.append("Scrivi nome e cognome.")
            if not servizio.norm_matricola(dati["matricola"]):
                errori.append("Scrivi la tua matricola (per esempio T138, A012, CNO 1234).")
            if not errori:
                errore_pin = servizio.controlla_pin(link, dati, request.POST.get("pin"))
                if errore_pin:
                    errori.append(errore_pin)
            if not errori:
                p = servizio.partecipazione_da_riprendere(corso_obj, dati)
                if p is not None:
                    # Stessa persona, corso non finito: riprende da dove era rimasta.
                    stato = _stato_da_partecipazione(p)
                    stato["ripresa"] = True
                else:
                    p = servizio.nuova_partecipazione(link, dati, reparto=reparto, ip=client_ip(request) or "")
                    stato = {"avvio": time.time(), "viste": {}, "chi": dati, "pid": p.pk}
                    email = servizio.email_persona(p.legacy_anagrafica_id)
                    if email:
                        servizio.accoda_email_codice(
                            p.pk, request.build_absolute_uri(reverse("corso_aperto:registrati", args=[token])))
                        stato["email"] = servizio.email_mascherata(email)
                _salva(request, link, stato)
                return _ricorda(redirect("corso_aperto:pronto", token=token), link, stato)
    return render(request, "anagrafica/corso_aperto/registrati.html",
                  {"link": link, "corso": corso_obj, "dati": dati, "errori": errori, "reparto": reparto,
                   "chiede_pin": servizio.chiede_pin(link),
                   "n_slide": len(_slides(corso_obj, stato))}, status=400 if errori else 200)


@require_http_methods(["GET", "POST"])
@risposta_pubblica_con_form
def pronto(request, token: str):
    """Dopo la registrazione: il codice per riprendere, ben in vista, prima di iniziare; con video o
    slide a scelta, qui si sceglie (e si cambia finché non si è aperta nessuna slide del percorso)."""
    from .services.elearning_fruizione import info_percorsi, percorsi_a_scelta
    link = _link(token)
    stato = _stato(request, link)
    if not _registrato(stato):
        return redirect("corso_aperto:registrati", token=token)
    a_scelta = percorsi_a_scelta(link.corso)
    slides = _slides(link.corso, stato)
    p = _partecipazione(stato)
    n_viste = sum(1 for s in slides if str(s.ordine) in (stato.get("viste") or {}))
    if request.method == "POST":
        scelta = request.POST.get("percorso") or ""
        if a_scelta and scelta in ("VIDEO", "SLIDE") and (not stato.get("percorso") or not n_viste):
            stato["percorso"] = scelta
            _salva(request, link, stato)
            if p is not None:
                type(p).objects.filter(pk=p.pk).update(percorso=scelta)
        return _ricorda(redirect("corso_aperto:corso", token=token), link, stato)
    scegliere = a_scelta and (not stato.get("percorso") or (request.GET.get("cambia") == "1" and not n_viste))
    fatto_il = _completato_il(link, p)
    return _ricorda(render(request, "anagrafica/corso_aperto/pronto.html", {
        "link": link, "corso": link.corso, "chi": stato["chi"], "codice": getattr(p, "codice", ""),
        "email": stato.get("email", ""), "ripresa": bool(stato.get("ripresa")) and n_viste > 0 and not fatto_il,
        "n_viste": n_viste, "n_slide": len(slides),
        "da_slide": _punto_di_ripresa(stato, slides) + 1 if slides else 1,
        "scegliere": scegliere and not fatto_il,
        "info": info_percorsi(link.corso) if scegliere else {},
        "completata_il": fatto_il,
        "percorso": stato.get("percorso", "") if a_scelta else "", "puo_cambiare": a_scelta and not n_viste,
    }), link, stato)


@require_GET
@risposta_pubblica
def materiale(request, token: str):
    """Indice del materiale (presentazioni e video) da consultare liberamente dopo la registrazione."""
    link = _link(token)
    stato = _stato(request, link)
    if not _registrato(stato):
        return redirect("corso_aperto:registrati", token=token)
    slides = _slides_tutte(link.corso)
    gruppi, attuale = [], None
    for pos, s in enumerate(slides, start=1):
        titolo = s.modulo.titolo if s.modulo_id else "Materiale del corso"
        if attuale is None or attuale["titolo"] != titolo:
            attuale = {"titolo": titolo, "voci": []}
            gruppi.append(attuale)
        attuale["voci"].append({"pos": pos, "slide": s, "vista": str(s.ordine) in stato["viste"]})
    return render(request, "anagrafica/corso_aperto/materiale.html", {
        "link": link, "corso": link.corso, "gruppi": gruppi, "chi": stato["chi"],
        "n_viste": sum(1 for s in slides if str(s.ordine) in stato["viste"]), "n_slide": len(slides),
    })


@require_GET
@risposta_pubblica
def corso(request, token: str):
    link = _link(token)
    corso_obj = link.corso
    stato = _stato(request, link)
    slides = _slides(corso_obj, stato)
    if not slides:
        raise Http404
    regola = regola_corso(corso_obj)
    if _registrato(stato) and not request.GET.get("c") and (
            _deve_scegliere(corso_obj, stato) or _completato_il(link, _partecipazione(stato))):
        # Corso già fatto: niente percorso da riprendere, solo il materiale da consultare.
        return redirect("corso_aperto:pronto", token=token)
    if not _registrato(stato):
        url = reverse("corso_aperto:registrati", args=[token])
        if request.GET.get("rep"):
            from urllib.parse import quote
            url += "?rep=" + quote(_testo(request.GET.get("rep"), 120))
        return redirect(url)
    from .services.elearning_markdown import render_markdown
    if request.GET.get("c"):
        # Consultazione libera: nessun tempo minimo, non conta per il percorso del quiz.
        slides = _slides_tutte(corso_obj)
        try:
            pos = max(min(int(request.GET.get("c")), len(slides)), 1) - 1
        except ValueError:
            pos = 0
        slide = slides[pos]
        return render(request, "anagrafica/corso_aperto/slide.html", {
            "link": link, "corso": corso_obj, "slide": slide, "indice": pos + 1, "n_slide": len(slides),
            "contenuto_html": render_markdown(slide.contenuto) if not slide.is_immagine and slide.tipo != "VIDEO" else "",
            "consulta": True, "prec": pos if pos > 0 else None, "succ": pos + 2 if pos < len(slides) - 1 else None,
            "progress_pct": round((pos + 1) / len(slides) * 100), "chi": stato["chi"],
        })
    try:
        if request.GET.get("s"):
            pos = max(min(int(request.GET.get("s")), len(slides)), 1) - 1
        else:
            pos = _punto_di_ripresa(stato, slides)  # riprende dalla prima slide non vista
    except ValueError:
        pos = 0
    if not _slide_ammessa(stato, slides, pos, regola):
        # Torna alla prima slide non ancora sbloccata.
        pos = next((i for i in range(len(slides)) if not _slide_ammessa(stato, slides, i + 1, regola)), 0) \
            if len(slides) > 1 else 0
        pos = min(pos, len(slides) - 1)
    slide = slides[pos]
    stato["viste"].setdefault(str(slide.ordine), time.time())
    _salva(request, link, stato)
    ultima = pos == len(slides) - 1
    return _ricorda(render(request, "anagrafica/corso_aperto/slide.html", {
        "link": link, "corso": corso_obj, "slide": slide, "indice": pos + 1, "n_slide": len(slides),
        "contenuto_html": render_markdown(slide.contenuto) if not slide.is_immagine and slide.tipo != "VIDEO" else "",
        "prec": pos if pos > 0 else None, "succ": pos + 2 if not ultima else None, "ultima": ultima,
        "secondi_mancanti": _secondi_mancanti(stato, slide, regola),
        "video_fino": bool(slide.tipo == "VIDEO" and slide.video_fino_in_fondo and _video_mancante(stato, slide)),
        "progress_pct": round((pos + 1) / len(slides) * 100),
        "ha_quiz": bool(quiz.domande_valide(corso_obj)), "chi": stato["chi"],
        "senza_quiz": not regola.richiede_quiz,
        "codice": getattr(_partecipazione(stato), "codice", ""),
        "video_da": int(((stato.get("video") or {}).get(str(slide.pk)) or [0])[0] or 0),
    }), link, stato)


def _slide_vista(request, token: str, slide_id: int, tipo_ok) -> TrainingSlide:
    link = _link(token)
    slide = TrainingSlide.objects.filter(pk=slide_id, corso=link.corso, is_active=True).first()
    stato = _stato(request, link)
    # (le slide fuori percorso si aprono solo in consultazione, quindi da registrati)
    # Chi si è registrato può consultare tutto il materiale; altrimenti solo le slide già aperte.
    if slide is None or not tipo_ok(slide) or not (_registrato(stato) or str(slide.ordine) in stato["viste"]):
        raise Http404
    return slide


@require_GET
@risposta_pubblica
def immagine(request, token: str, slide_id: int):
    from django.http import FileResponse
    slide = _slide_vista(request, token, slide_id, lambda s: bool(s.immagine))
    try:
        fh = slide.immagine.open("rb")
    except FileNotFoundError:
        raise Http404
    resp = FileResponse(fh, content_type="image/png")
    resp["Content-Disposition"] = "inline"
    resp["Cache-Control"] = "private, max-age=300"
    return resp


@require_http_methods(["POST"])
@risposta_pubblica_con_form
def video_avanz(request, token: str):
    """Secondi di video guardati (JSON): per i video «da guardare fino in fondo»."""
    from django.http import JsonResponse
    link = _link(token)
    stato = _stato(request, link)
    if not _registrato(stato):
        return JsonResponse({"ok": False}, status=403)
    slide = TrainingSlide.objects.filter(pk=request.POST.get("slide_id") or 0, corso=link.corso, is_active=True).first()
    if slide is None or slide.tipo != TrainingSlide.TIPO_VIDEO:
        return JsonResponse({"ok": False}, status=404)
    try:
        secondi = max(int(float(request.POST.get("secondi") or 0)), 0)
        durata = max(int(float(request.POST.get("durata") or 0)), 0)
    except ValueError:
        return JsonResponse({"ok": False}, status=400)
    tetto = int(slide.video_durata_secondi or durata or 0) or 36000
    video = stato.setdefault("video", {})
    prima = video.get(str(slide.pk)) or [0, 0]
    video[str(slide.pk)] = [max(prima[0], min(secondi, tetto)), prima[1] or min(durata, 36000)]
    _salva(request, link, stato)
    p = _partecipazione(stato)
    if p is not None:
        vv = dict(p.video_visti or {})
        vv[str(slide.pk)] = video[str(slide.pk)][0]
        type(p).objects.filter(pk=p.pk).update(video_visti=vv)
    return JsonResponse({"ok": True, "mancano": _video_mancante(stato, slide)})


@require_GET
@risposta_pubblica
def video(request, token: str, slide_id: int):
    from .views_elearning import _risposta_range
    slide = _slide_vista(request, token, slide_id, lambda s: s.tipo == TrainingSlide.TIPO_VIDEO and bool(s.video))
    return _risposta_range(request, slide.video, "video/mp4")


def _conta(chiave: str, limite: int, finestra: int) -> bool:
    cache.add(chiave, 0, timeout=finestra)
    try:
        return cache.incr(chiave) > limite
    except ValueError:
        cache.set(chiave, 1, timeout=finestra)
        return False


def _troppe(ip: str) -> bool:
    try:
        if ip not in _LOOPBACK and _conta(f"corso_aperto:{ip}", LIMITE_IP, FINESTRA_IP):
            return True
        return _conta("corso_aperto:__tutti__", LIMITE_GLOBALE, FINESTRA_GLOBALE)
    except Exception:  # noqa: BLE001 - cache giù: meglio un invio in più che il quiz fermo
        return False


def _blocco_quiz(stato, slides, regola) -> str:
    viste = stato["viste"]
    if any(str(s.ordine) not in viste for s in slides):
        return "Prima guarda tutte le slide del corso, poi fai il quiz."
    if _secondi_mancanti(stato, slides[-1], regola):
        return "Resta ancora un po' sull'ultima slide, poi fai il quiz."
    mancano = _tempo_mancante(stato, regola)
    if mancano:
        return f"Il corso dura almeno {regola.tempo_minimo_minuti} minuti: il quiz si apre tra circa {mancano // 60 + 1} minuti."
    return ""


def _domande_da_servire(corso, regola) -> list:
    domande = quiz.domande_valide(corso)
    rnd = random.SystemRandom()
    if regola.domande_estratte and regola.domande_estratte < len(domande):
        domande = rnd.sample(domande, regola.domande_estratte)
    elif regola.mescola:
        rnd.shuffle(domande)
    servite = []
    for d in domande:
        opzioni = [(o.pk, o.testo) for o in d.opzioni.all()]
        if regola.mescola and d.tipo != "VERO_FALSO":
            rnd.shuffle(opzioni)
        servita = quiz.DomandaServita(d.pk, d.testo, opzioni, d.tipo)
        servita.scelte = set()
        servite.append(servita)
    return servite


def _prima_consegna(link, token: str) -> bool:
    """True una sola volta per gettone: un doppio clic, una pagina ricaricata o un'altra scheda
    non consegnano lo stesso quiz due volte (``cache.add`` è atomico, anche sulla cache su DB)."""
    try:
        return bool(cache.add(f"corso_aperto:consegna:{link.pk}:{token}", 1, timeout=86400))
    except Exception:  # noqa: BLE001 - cache giù: resta il blocco sulla partecipazione
        return True


def _completato_il(link, p):
    """Data del completamento, se la persona ha già fatto il corso: la partecipazione completata
    oppure un completamento riusabile della persona abbinata, da qualunque strada (aula, portale,
    una prova precedente). None se il corso è da fare, anche come rinnovo: assegnazione aperta
    dopo il completamento o scadenza entro il preavviso (``completamento_riusabile``).

    La data serve solo a decidere: la pagina pubblica non la mostra (l'abbinamento per matricola
    e cognome non prova chi sta usando il telefono)."""
    if p is None:
        return None
    if p.completata_il:
        return timezone.localtime(p.completata_il).date()
    if p.legacy_anagrafica_id:
        from .services.formazione_completamento import completamento_riusabile
        rec = completamento_riusabile(link.corso, p.legacy_anagrafica_id)
        if rec is not None:
            return rec.data_completamento
    return None


MESSAGGIO_GIA_COMPLETATO = ("Risulta che questo corso è già completato: il quiz non si ripete. "
                            "Il materiale resta da consultare.")


def _gia_completato(request, link, quando=None):
    url = reverse("corso_aperto:materiale", args=[link.token])
    return render(request, "anagrafica/corso_aperto/esito.html", {
        "link": link, "corso": link.corso, "titolo": "Corso già completato",
        "testo": MESSAGGIO_GIA_COMPLETATO, "torna": url}, status=409)


def _blocco_tentativi(p, regola) -> str:
    """Regola del corso sulla partecipazione dal link aperto: tentativi massimi e attesa tra un
    tentativo e l'altro (come il quiz con login). Stringa vuota = il quiz si può fare."""
    if p is None or not (regola.max_tentativi or regola.attesa_minuti):
        return ""
    fatti = p.risposte.filter(superato=False)
    if regola.max_tentativi and fatti.count() >= regola.max_tentativi:
        return "Hai esaurito i tentativi disponibili per il quiz: rivolgiti all'ufficio HR."
    if regola.attesa_minuti:
        from datetime import timedelta
        ultimo = fatti.order_by("-inviato_il").values_list("inviato_il", flat=True).first()
        adesso = timezone.now()
        if ultimo and adesso < ultimo + timedelta(minutes=regola.attesa_minuti):
            minuti = int((ultimo + timedelta(minutes=regola.attesa_minuti) - adesso).total_seconds() // 60) + 1
            return f"Puoi riprovare il quiz fra {minuti} minuti."
    return ""


def _fuori_tempo(stato, regola) -> bool:
    """Quiz consegnato oltre il tempo della regola (30 secondi di tolleranza per la rete)."""
    if not regola.tempo_quiz_minuti or not stato.get("quiz_il"):
        return False
    return time.time() - float(stato["quiz_il"]) > regola.tempo_quiz_minuti * 60 + 30


def _testo(valore, massimo: int) -> str:
    return " ".join(str(valore or "").split())[:massimo]


def _concludi_senza_quiz(request, link, stato, url_corso):
    """Corso senza quiz obbligatorio (regola del corso), come ``_completa_senza_quiz`` del portale:
    finito il percorso e passato il tempo minimo, «Concludi il corso» registra il completamento
    passando dalla stessa strada del quiz (risposta senza domande, abbinamento, completamento)."""
    corso_obj = link.corso
    if request.method == "GET":
        return render(request, "anagrafica/corso_aperto/esito.html", {
            "link": link, "corso": corso_obj, "titolo": "Fine del corso", "concludi": True,
            "testo": "Hai seguito tutto il corso. Conferma per registrarlo sulla tua scheda.", "torna": url_corso})
    if request.POST.get("sito_web"):
        raise Http404
    ip = client_ip(request) or ""
    if _troppe(ip):
        return render(request, "anagrafica/corso_aperto/esito.html",
                      {"link": link, "corso": corso_obj, "titolo": "Troppi invii",
                       "testo": "Abbiamo ricevuto troppe richieste in poco tempo. Riprova tra un'ora."}, status=429)
    dati = dict(stato["chi"])
    avvio = stato.get("avvio")
    from decimal import Decimal

    from .models_elearning import TrainingElearningPartecipazioneAperta as P
    esito = {"n_corrette": 0, "n_totali": 0, "punteggio_pct": Decimal("0"), "superato": True, "risposte": []}
    with transaction.atomic():
        p_lock = P.objects.select_for_update().filter(pk=stato.get("pid")).first() if stato.get("pid") else None
        if _completato_il(link, p_lock):
            return _gia_completato(request, link)
        risposta = servizio.registra(
            corso_obj, nome=dati["nome"], cognome=dati["cognome"], matricola=dati.get("matricola", ""), esito=esito,
            partecipazione=p_lock,
            avviato_il=timezone.make_aware(datetime.fromtimestamp(avvio)) if avvio else None,
            ip=ip if ip not in _LOOPBACK else "", user_agent=request.headers.get("User-Agent", "")[:500],
        )
    registrato = bool(risposta.record_id)
    return render(request, "anagrafica/corso_aperto/esito.html", {
        "link": link, "corso": corso_obj,
        "titolo": ("Corso completato" if registrato
                   else "Corso concluso: l'ufficio HR verifica i tuoi dati e registra il corso"),
        "testo": ("Il corso è registrato sulla tua scheda." if registrato else
                  "L'ufficio HR controlla nome e matricola e registra il corso sulla tua scheda: non devi rifarlo."),
        "torna": reverse("corso_aperto:materiale", args=[link.token])})


@require_http_methods(["GET", "POST"])
@risposta_pubblica_con_form
def quiz_finale(request, token: str):
    link = _link(token)
    corso_obj = link.corso
    stato = _stato(request, link)
    slides = _slides(corso_obj, stato)
    regola = regola_corso(corso_obj)
    if not _registrato(stato):
        return redirect("corso_aperto:registrati", token=token)
    if _deve_scegliere(corso_obj, stato):
        return redirect("corso_aperto:pronto", token=token)
    url_corso = reverse("corso_aperto:corso", args=[token])
    fatto_il = _completato_il(link, _partecipazione(stato))
    if fatto_il:
        return _gia_completato(request, link, fatto_il)
    blocco = _blocco_quiz(stato, slides, regola) if slides else "Il corso non ha slide."
    senza_quiz = not regola.richiede_quiz
    if not blocco and not senza_quiz:
        blocco = _blocco_tentativi(_partecipazione(stato), regola)
    if blocco:
        return render(request, "anagrafica/corso_aperto/esito.html",
                      {"link": link, "corso": corso_obj,
                       "titolo": "Corso non ancora concluso" if senza_quiz else "Quiz non ancora disponibile",
                       "testo": blocco.replace("poi fai il quiz", "poi concludi il corso") if senza_quiz else blocco,
                       "torna": url_corso}, status=409)
    if senza_quiz:
        return _concludi_senza_quiz(request, link, stato, url_corso)

    if request.method == "GET":
        domande = _domande_da_servire(corso_obj, regola)
        if not domande:
            raise Http404
        stato["quiz"] = [d.id for d in domande]
        stato["quiz_il"] = time.time()
        stato["quiz_token"] = secrets.token_urlsafe(18)  # una consegna per ogni quiz servito
        _salva(request, link, stato)
        return render(request, "anagrafica/corso_aperto/quiz.html",
                      {"link": link, "corso": corso_obj, "domande": domande, "dati": {}, "errori": [],
                       "consegna": stato["quiz_token"], "tempo_quiz_minuti": regola.tempo_quiz_minuti})

    ip = client_ip(request) or ""
    if _troppe(ip):
        return render(request, "anagrafica/corso_aperto/esito.html",
                      {"link": link, "corso": corso_obj, "titolo": "Troppi invii",
                       "testo": "Abbiamo ricevuto troppi quiz in poco tempo. Riprova tra un'ora."}, status=429)
    consegna = request.POST.get("consegna") or ""
    if not consegna or not stato.get("quiz_token") or not secrets.compare_digest(consegna, stato["quiz_token"]) \
            or not _prima_consegna(link, consegna):
        return render(request, "anagrafica/corso_aperto/esito.html", {
            "link": link, "corso": corso_obj, "titolo": "Quiz già consegnato",
            "testo": "Questo quiz è già stato inviato (doppio clic, pagina ricaricata o un'altra scheda). "
                     "Se devi riprovare, apri di nuovo il quiz dal corso.",
            "torna": url_corso}, status=409)
    domande_ids = [int(i) for i in stato.get("quiz") or [] if str(i).isdigit()]
    if not domande_ids:
        return redirect("corso_aperto:quiz", token=token)
    if request.POST.get("sito_web"):
        # Campo trappola compilato: un programma automatico. Finto esito, nessun salvataggio.
        stato.pop("quiz", None)
        stato.pop("quiz_token", None)
        _salva(request, link, stato)
        return render(request, "anagrafica/corso_aperto/esito.html",
                      {"link": link, "corso": corso_obj, "titolo": "Quiz inviato", "testo": ""})
    dati = dict(stato["chi"])
    risposte = {}
    for chiave in request.POST:
        if chiave.startswith("q_") and chiave[2:].isdigit():
            risposte[int(chiave[2:])] = {int(x) for x in request.POST.getlist(chiave) if str(x).isdigit()}

    esito = servizio.correggi(corso_obj, domande_ids, risposte, regola.soglia_pct)
    fuori_tempo = _fuori_tempo(stato, regola)
    if fuori_tempo:
        esito["superato"] = False  # come il quiz con login: il tentativo scaduto conta e non supera
    avvio = stato.get("avvio")
    from .models_elearning import TrainingElearningPartecipazioneAperta as P
    with transaction.atomic():
        # Blocco sulla partecipazione: due consegne in parallelo passano una alla volta e la
        # seconda trova il corso già completato.
        p_lock = P.objects.select_for_update().filter(pk=stato.get("pid")).first() if stato.get("pid") else None
        if _completato_il(link, p_lock):
            return _gia_completato(request, link)
        risposta = servizio.registra(
            corso_obj, nome=dati["nome"], cognome=dati["cognome"], matricola=dati.get("matricola", ""), esito=esito,
            partecipazione=p_lock,
            avviato_il=timezone.make_aware(datetime.fromtimestamp(avvio)) if avvio else None,
            ip=ip if ip not in _LOOPBACK else "", user_agent=request.headers.get("User-Agent", "")[:500],
        )
        if fuori_tempo:
            nota = f"Consegnato oltre il tempo del quiz ({regola.tempo_quiz_minuti} minuti)."
            type(risposta).objects.filter(pk=risposta.pk).update(
                nota=(((risposta.nota + " ") if risposta.nota else "") + nota)[:300])
    stato.pop("quiz", None)
    stato.pop("quiz_token", None)
    _salva(request, link, stato)
    # «Corso completato» solo se il completamento è a libretto: quiz superato ma persona non
    # abbinata (nome non trovato o omonimi) = nessun record, lo registra l'HR dopo il controllo.
    registrato = bool(risposta.superato and risposta.record_id)
    if registrato:
        titolo = "Corso completato"
    elif fuori_tempo:
        titolo = "Tempo del quiz scaduto"
    elif risposta.superato:
        titolo = "Quiz superato: l'ufficio HR verifica i tuoi dati e registra il corso"
    else:
        titolo = "Quiz non superato"
    return render(request, "anagrafica/corso_aperto/esito.html", {
        "link": link, "corso": corso_obj, "superato": risposta.superato, "inviato": True,
        "registrato": registrato, "titolo": titolo,
        "punteggio": risposta.punteggio_pct, "n_corrette": risposta.n_corrette, "n_totali": risposta.n_totali,
        "minimo": regola.soglia_pct, "nominativo": f"{risposta.nome} {risposta.cognome}",
        "torna": url_corso, "quiz_url": reverse("corso_aperto:quiz", args=[token]),
    })

