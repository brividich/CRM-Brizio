"""Corso e-learning dal link aperto (``/corso-aperto/<token>/``): senza login.

Prefisso in ``MIDDLEWARE_EXEMPT_PREFIXES``, view in ``PUBLIC_VIEWS``. Pensato anche per
internet (Entra Application Proxy, come ``/richiesta-visita/``). Protezioni:

- token lungo per corso, che l'HR spegne o rigenera; corso non pubblicato o link scaduto = 404;
- slide servite solo in ordine e dopo i secondi minimi della slide precedente; immagini e
  video solo delle slide già aperte in questa sessione del browser;
- quiz solo dopo l'ultima slide e il tempo minimo del corso, entrambi misurati dal server;
- limite di invii per IP e globale, campo trappola, nome e cognome obbligatori;
- la pagina non mostra mai l'elenco dei dipendenti né a chi è stato abbinato il quiz.

La logica (correzione, abbinamento, completamento) è in ``services/elearning_link_aperto.py``.
"""
from __future__ import annotations

import random
import time
from datetime import datetime

from django.core.cache import cache
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
from .services.elearning_regole import Regola, regola_corso, secondi_richiesti_slide

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


def _stato(request, link) -> dict:
    stato = request.session.get(_chiave(link))
    if not isinstance(stato, dict):
        stato = {"avvio": time.time(), "viste": {}}
    return stato


def _salva(request, link, stato: dict) -> None:
    request.session[_chiave(link)] = stato
    request.session.modified = True


def _slides(corso) -> list:
    return list(corso.slides.filter(is_active=True).order_by("ordine", "pk"))


def _secondi_mancanti(stato, slide, regola) -> int:
    vista = stato["viste"].get(str(slide.ordine))
    richiesti = secondi_richiesti_slide(slide, regola)
    if vista is None or not richiesti:
        return 0
    return max(int(richiesti - (time.time() - vista)), 0)


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


@require_GET
@risposta_pubblica
def corso(request, token: str):
    link = _link(token)
    corso_obj = link.corso
    slides = _slides(corso_obj)
    if not slides:
        raise Http404
    regola = regola_corso(corso_obj)
    stato = _stato(request, link)
    try:
        pos = max(min(int(request.GET.get("s") or 1), len(slides)), 1) - 1
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
    from .services.elearning_markdown import render_markdown
    ultima = pos == len(slides) - 1
    return render(request, "anagrafica/corso_aperto/slide.html", {
        "link": link, "corso": corso_obj, "slide": slide, "indice": pos + 1, "n_slide": len(slides),
        "contenuto_html": render_markdown(slide.contenuto) if not slide.is_immagine and slide.tipo != "VIDEO" else "",
        "prec": pos if pos > 0 else None, "succ": pos + 2 if not ultima else None, "ultima": ultima,
        "secondi_mancanti": _secondi_mancanti(stato, slide, regola),
        "progress_pct": round((pos + 1) / len(slides) * 100),
        "ha_quiz": bool(quiz.domande_valide(corso_obj)),
    })


def _slide_vista(request, token: str, slide_id: int, tipo_ok) -> TrainingSlide:
    link = _link(token)
    slide = TrainingSlide.objects.filter(pk=slide_id, corso=link.corso, is_active=True).first()
    if slide is None or not tipo_ok(slide) or str(slide.ordine) not in _stato(request, link)["viste"]:
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


def _testo(valore, massimo: int) -> str:
    return " ".join(str(valore or "").split())[:massimo]


@require_http_methods(["GET", "POST"])
@risposta_pubblica_con_form
def quiz_finale(request, token: str):
    link = _link(token)
    corso_obj = link.corso
    slides = _slides(corso_obj)
    regola = regola_corso(corso_obj)
    stato = _stato(request, link)
    url_corso = reverse("corso_aperto:corso", args=[token])
    blocco = _blocco_quiz(stato, slides, regola) if slides else "Il corso non ha slide."
    if blocco:
        return render(request, "anagrafica/corso_aperto/esito.html",
                      {"link": link, "corso": corso_obj, "titolo": "Quiz non ancora disponibile", "testo": blocco,
                       "torna": url_corso}, status=409)

    if request.method == "GET":
        domande = _domande_da_servire(corso_obj, regola)
        if not domande:
            raise Http404
        stato["quiz"] = [d.id for d in domande]
        stato["quiz_il"] = time.time()
        _salva(request, link, stato)
        return render(request, "anagrafica/corso_aperto/quiz.html",
                      {"link": link, "corso": corso_obj, "domande": domande, "dati": {}, "errori": []})

    ip = client_ip(request) or ""
    if _troppe(ip):
        return render(request, "anagrafica/corso_aperto/esito.html",
                      {"link": link, "corso": corso_obj, "titolo": "Troppi invii",
                       "testo": "Abbiamo ricevuto troppi quiz in poco tempo. Riprova tra un'ora."}, status=429)
    domande_ids = [int(i) for i in stato.get("quiz") or [] if str(i).isdigit()]
    if not domande_ids:
        return redirect("corso_aperto:quiz", token=token)
    if request.POST.get("sito_web"):
        # Campo trappola compilato: un programma automatico. Finto esito, nessun salvataggio.
        stato.pop("quiz", None)
        _salva(request, link, stato)
        return render(request, "anagrafica/corso_aperto/esito.html",
                      {"link": link, "corso": corso_obj, "titolo": "Quiz inviato", "testo": ""})
    dati = {"nome": _testo(request.POST.get("nome"), 100), "cognome": _testo(request.POST.get("cognome"), 100)}
    risposte = {}
    for chiave in request.POST:
        if chiave.startswith("q_") and chiave[2:].isdigit():
            risposte[int(chiave[2:])] = {int(x) for x in request.POST.getlist(chiave) if str(x).isdigit()}
    errori = []
    if not dati["nome"] or not dati["cognome"]:
        errori.append("Scrivi nome e cognome: servono a registrare il corso sulla tua scheda.")
    if errori:
        # Stesse domande, stesso ordine: si ricostruiscono da quelle servite.
        per_id = {d.id: d for d in _domande_da_servire(corso_obj, Regola(mescola=False))}
        domande = [per_id[i] for i in domande_ids if i in per_id]
        for d in domande:
            d.scelte = risposte.get(d.id, set())
        return render(request, "anagrafica/corso_aperto/quiz.html",
                      {"link": link, "corso": corso_obj, "domande": domande, "dati": dati, "errori": errori},
                      status=400)

    esito = servizio.correggi(corso_obj, domande_ids, risposte, regola.soglia_pct)
    avvio = stato.get("avvio")
    risposta = servizio.registra(
        corso_obj, nome=dati["nome"], cognome=dati["cognome"], esito=esito,
        avviato_il=timezone.make_aware(datetime.fromtimestamp(avvio)) if avvio else None,
        ip=ip if ip not in _LOOPBACK else "", user_agent=request.headers.get("User-Agent", "")[:500],
    )
    stato.pop("quiz", None)
    _salva(request, link, stato)
    return render(request, "anagrafica/corso_aperto/esito.html", {
        "link": link, "corso": corso_obj, "superato": risposta.superato, "inviato": True,
        "titolo": "Corso completato" if risposta.superato else "Quiz non superato",
        "punteggio": risposta.punteggio_pct, "n_corrette": risposta.n_corrette, "n_totali": risposta.n_totali,
        "minimo": regola.soglia_pct, "nominativo": f"{risposta.nome} {risposta.cognome}",
        "torna": url_corso, "quiz_url": reverse("corso_aperto:quiz", args=[token]),
    })

