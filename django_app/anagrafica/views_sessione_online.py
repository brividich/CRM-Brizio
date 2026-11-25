"""Lezione online di una sessione (slide + test): preparazione, gestione e pagine del partecipante.

Gestione (chi gestisce la formazione): ``/anagrafica/formazione/sessioni/<id>/online/…``.
Partecipante (iscritti alla sessione): ``/anagrafica/formazione/corsi-online/sessione/<id>/…``,
sotto il prefisso dell'area discente: il controllo vero è in ogni view (iscrizione
alla sessione, lezione pubblicata, sequenza delle slide, tentativi).
"""
from __future__ import annotations

import csv
import logging
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models_formazione import TrainingEnrollment, TrainingSession
from .models_sessione_online import TrainingSessionAttempt, TrainingSessionQuestion, TrainingSessionSlide
from .services import elearning_markdown
from .services import sessione_online as so
from .views import _helpers

logger = logging.getLogger(__name__)
MODULE = "anagrafica"
PASSI = ("slide", "test", "invio")


# ─────────────────────────────────────────────────────────────────────────────
# Utilità
# ─────────────────────────────────────────────────────────────────────────────

def _sessione(sessione_id: int) -> TrainingSession:
    return get_object_or_404(TrainingSession.objects.select_related("corso"), pk=sessione_id)


def _torna(request, sessione_id: int, passo: str = ""):
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure()):
        return redirect(nxt)
    url = reverse("anagrafica:sessione_online_prepara", args=[sessione_id])
    return redirect(f"{url}?passo={passo}" if passo else url)


def _blocco_gestione(request, sessione_id: int):
    """Redirect se l'utente non gestisce la formazione o l'edizione è approvata."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per gestire la formazione.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
    from .views.formazione import _redirect_se_edizione_chiusa
    return _redirect_se_edizione_chiusa(request, sessione_id, "detail", livello="approvata")


def _audit(request, azione: str, sessione, **dati):
    try:
        log_action(request, f"sessione_online_{azione}", MODULE, {"sessione": sessione.pk, **dati}, oggetto=sessione)
    except Exception:
        logger.exception("Audit lezione online non registrato (%s)", azione)


def _data(valore: str):
    try:
        return date.fromisoformat((valore or "").strip()) if (valore or "").strip() else None
    except ValueError:
        return None


def _intero(valore, default: int, minimo: int = 0, massimo: int = 1000) -> int:
    try:
        return max(minimo, min(massimo, int(str(valore).strip())))
    except (TypeError, ValueError):
        return default


def contesto_gestione(request, sessione, *, completo: bool = True) -> dict | None:
    """Dati della lezione online per la pagina della sessione e per la preparazione."""
    cfg = so.config(sessione)
    if cfg is None and sessione.modalita != "ONLINE":
        return None
    elenco_slide = so.slides(sessione)
    elenco_domande = so.domande(sessione)
    for d in elenco_domande:
        d.problema = so.problema_domanda(d)
        d.lista_opzioni = list(d.opzioni.all())
        d.multipla = sum(1 for o in d.lista_opzioni if o.corretta) > 1
        n_righe = min(so.MAX_RISPOSTE, max(4, len(d.lista_opzioni) + 1))
        d.righe = [(i, d.lista_opzioni[i].testo if i < len(d.lista_opzioni) else "",
                    i < len(d.lista_opzioni) and d.lista_opzioni[i].corretta) for i in range(n_righe)]
    ctx = {
        "righe_nuova": list(range(4)),
        "cfg": cfg,
        "slides": elenco_slide,
        "n_slide": len(elenco_slide),
        "domande": elenco_domande,
        "n_domande": len(elenco_domande),
        "n_domande_ko": sum(1 for d in elenco_domande if d.problema),
        "manca": so.cosa_manca(sessione, cfg) if cfg else ["lezione non ancora preparata"],
        "slide_corso": sessione.corso.slides.filter(is_active=True).count(),
        "domande_corso": sessione.corso.quiz_domande.filter(is_active=True).count(),
        "scaduta": so.scaduta(cfg),
    }
    if completo and cfg:
        righe = so.righe_gestione(sessione, cfg, len(elenco_slide))
        ctx.update({
            "righe": righe,
            "numeri": so.numeri(righe, cfg),
            "difficili": so.domande_difficili(sessione),
            "minuti_previsti": round(len(elenco_slide) * (cfg.secondi_minimi_slide or 0) / 60),
        })
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Preparazione (3 passi)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def sessione_online_prepara(request, sessione_id: int):
    sessione = _sessione(sessione_id)
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per preparare la lezione online.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
    if sessione.is_approvata:
        messages.error(request, "L'edizione è approvata: la lezione online non si modifica più.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
    so.config(sessione, crea=True)
    passo = request.GET.get("passo") if request.GET.get("passo") in PASSI else "slide"
    ctx = contesto_gestione(request, sessione, completo=(passo == "invio"))
    return render(request, "anagrafica/pages/sessione_online_prepara.html", {
        "sessione": sessione, "passo": passo, "passi": PASSI, **ctx, "online": ctx,
        "qui": f"{request.path}?passo={passo}",
    })


@login_required
@require_POST
def sessione_online_impostazioni(request, sessione_id: int):
    if (b := _blocco_gestione(request, sessione_id)) is not None:
        return b
    sessione = _sessione(sessione_id)
    cfg = so.config(sessione, crea=True)
    p = request.POST
    cfg.soglia_pct = _intero(p.get("soglia_pct"), cfg.soglia_pct, 1, 100)
    cfg.max_tentativi = _intero(p.get("max_tentativi"), cfg.max_tentativi, 0, 20)
    cfg.secondi_minimi_slide = _intero(p.get("secondi_minimi_slide"), cfg.secondi_minimi_slide, 0, 600)
    cfg.promemoria_giorni = _intero(p.get("promemoria_giorni"), cfg.promemoria_giorni, 0, 60)
    if "disponibile_dal" in p:
        cfg.disponibile_dal = _data(p.get("disponibile_dal"))
    if "scadenza" in p:
        cfg.scadenza = _data(p.get("scadenza"))
    if "mostra_correzioni_presente" in p:
        cfg.mostra_correzioni = p.get("mostra_correzioni") == "1"
    if cfg.disponibile_dal and cfg.scadenza and cfg.scadenza < cfg.disponibile_dal:
        messages.error(request, "La scadenza non può essere prima della data di apertura.")
        return _torna(request, sessione_id)
    cfg.save()
    _audit(request, "impostazioni", sessione, soglia=cfg.soglia_pct, tentativi=cfg.max_tentativi,
           scadenza=str(cfg.scadenza or ""))
    messages.success(request, "Impostazioni salvate.")
    return _torna(request, sessione_id)


@login_required
@require_POST
def sessione_online_slide_importa(request, sessione_id: int):
    if (b := _blocco_gestione(request, sessione_id)) is not None:
        return b
    sessione = _sessione(sessione_id)
    so.config(sessione, crea=True)
    file = request.FILES.get("file")
    if not file:
        messages.error(request, "Scegli il PowerPoint o il PDF da caricare.")
        return _torna(request, sessione_id, "slide")
    try:
        n = so.importa_file(sessione, file, request.user)
    except so.LezioneOnlineError as exc:
        messages.error(request, str(exc))
        return _torna(request, sessione_id, "slide")
    except Exception:
        logger.exception("Import slide lezione online fallito (sessione %s)", sessione_id)
        messages.error(request, "Il file non si è potuto convertire in slide. Prova a salvarlo in PDF.")
        return _torna(request, sessione_id, "slide")
    _audit(request, "slide_importate", sessione, n=n, file=file.name[:120])
    messages.success(request, f"{n} slide aggiunte da «{file.name}».")
    return _torna(request, sessione_id, "slide")


@login_required
@require_POST
def sessione_online_slide_corso(request, sessione_id: int):
    if (b := _blocco_gestione(request, sessione_id)) is not None:
        return b
    sessione = _sessione(sessione_id)
    so.config(sessione, crea=True)
    copiate, saltate = so.copia_slide_dal_corso(sessione, request.user)
    _audit(request, "slide_dal_corso", sessione, n=copiate)
    if copiate:
        messages.success(request, f"{copiate} slide copiate dal corso"
                         + (f" ({saltate} video o vuote saltate)." if saltate else "."))
    else:
        messages.info(request, "Il corso non ha slide da copiare.")
    return _torna(request, sessione_id, "slide")


@login_required
@require_POST
def sessione_online_slide_azione(request, sessione_id: int):
    if (b := _blocco_gestione(request, sessione_id)) is not None:
        return b
    sessione = _sessione(sessione_id)
    azione = request.POST.get("azione")
    if azione == "svuota":
        n = TrainingSessionSlide.objects.filter(sessione=sessione).count()
        for s in TrainingSessionSlide.objects.filter(sessione=sessione):
            s.delete()
        _audit(request, "slide_svuotate", sessione, n=n)
        messages.success(request, f"{n} slide tolte.")
        return _torna(request, sessione_id, "slide")
    slide = get_object_or_404(TrainingSessionSlide, pk=request.POST.get("slide_id") or 0, sessione=sessione)
    if azione in ("su", "giu"):
        so.sposta_slide(slide, azione)
    elif azione == "elimina":
        slide.delete()
        so.rinumera(so.slides(sessione))
        _audit(request, "slide_eliminata", sessione, slide=slide.pk)
        messages.success(request, "Slide tolta.")
    return _torna(request, sessione_id, "slide")


@login_required
@require_POST
def sessione_online_domanda_salva(request, sessione_id: int):
    if (b := _blocco_gestione(request, sessione_id)) is not None:
        return b
    sessione = _sessione(sessione_id)
    so.config(sessione, crea=True)
    risposte = [request.POST.get(f"risposta_{i}", "") for i in range(so.MAX_RISPOSTE)]
    giuste = {int(v) for v in request.POST.getlist("giusta") if str(v).isdigit()}
    try:
        d = so.salva_domanda(sessione, domanda_id=request.POST.get("domanda_id") or None,
                             testo=request.POST.get("testo", ""), risposte=risposte, giuste=giuste)
    except TrainingSessionQuestion.DoesNotExist:
        messages.error(request, "Domanda non trovata.")
        return _torna(request, sessione_id, "test")
    except so.LezioneOnlineError as exc:
        messages.error(request, str(exc))
        return _torna(request, sessione_id, "test")
    _audit(request, "domanda_salvata", sessione, domanda=d.pk)
    messages.success(request, "Domanda salvata.")
    return _torna(request, sessione_id, "test")


@login_required
@require_POST
def sessione_online_domanda_azione(request, sessione_id: int):
    if (b := _blocco_gestione(request, sessione_id)) is not None:
        return b
    sessione = _sessione(sessione_id)
    azione = request.POST.get("azione")
    if azione == "svuota":
        n = TrainingSessionQuestion.objects.filter(sessione=sessione).count()
        TrainingSessionQuestion.objects.filter(sessione=sessione).delete()
        _audit(request, "domande_svuotate", sessione, n=n)
        messages.success(request, f"{n} domande tolte.")
        return _torna(request, sessione_id, "test")
    d = get_object_or_404(TrainingSessionQuestion, pk=request.POST.get("domanda_id") or 0, sessione=sessione)
    if azione in ("su", "giu"):
        elenco = so.domande(sessione)
        idx = next(i for i, x in enumerate(elenco) if x.pk == d.pk)
        j = idx - 1 if azione == "su" else idx + 1
        if 0 <= j < len(elenco):
            elenco[idx], elenco[j] = elenco[j], elenco[idx]
        so.rinumera(elenco)
    elif azione == "elimina":
        d.delete()
        so.rinumera(so.domande(sessione))
        _audit(request, "domanda_eliminata", sessione, domanda=d.pk)
        messages.success(request, "Domanda tolta.")
    return _torna(request, sessione_id, "test")


@login_required
@require_POST
def sessione_online_domande_importa(request, sessione_id: int):
    """Domande dal corso, da testo incollato o da Excel (campo ``origine``)."""
    if (b := _blocco_gestione(request, sessione_id)) is not None:
        return b
    sessione = _sessione(sessione_id)
    so.config(sessione, crea=True)
    origine = request.POST.get("origine")
    try:
        if origine == "corso":
            n = so.copia_domande_dal_corso(sessione)
        elif origine == "testo":
            n = so.incolla_domande(sessione, request.POST.get("testo", ""))
        elif origine == "excel" and request.FILES.get("file"):
            n = so.importa_domande_excel(sessione, request.FILES["file"])
        else:
            messages.error(request, "Niente da importare.")
            return _torna(request, sessione_id, "test")
    except so.LezioneOnlineError as exc:
        messages.error(request, str(exc))
        return _torna(request, sessione_id, "test")
    _audit(request, "domande_importate", sessione, origine=origine, n=n)
    if n:
        messages.success(request, f"{n} domande aggiunte.")
    else:
        messages.info(request, "Nessuna domanda valida da aggiungere.")
    return _torna(request, sessione_id, "test")


# ─────────────────────────────────────────────────────────────────────────────
# Pubblicazione e gestione degli iscritti
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def sessione_online_pubblica(request, sessione_id: int):
    if (b := _blocco_gestione(request, sessione_id)) is not None:
        return b
    sessione = _sessione(sessione_id)
    cfg = so.config(sessione, crea=True)
    if request.POST.get("azione") == "sospendi":
        so.sospendi(cfg)
        _audit(request, "sospesa", sessione)
        messages.info(request, "Lezione sospesa: gli iscritti non la vedono finché non la ripubblichi.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
    try:
        esito = so.pubblica(sessione, cfg, request.user, invia=request.POST.get("invia", "1") == "1")
    except so.LezioneOnlineError as exc:
        messages.error(request, str(exc))
        return _torna(request, sessione_id, "invio")
    _audit(request, "pubblicata", sessione, **esito)
    if esito["persone"]:
        messages.success(request, f"Lezione pubblicata: notifica nel portale a {esito['notifiche']} persone"
                                  + (f"; {esito.get('senza_utente', 0)} senza utente del portale vanno avvisate da voi." if esito.get('senza_utente', 0) else ".")
                                  + " Nessuna email inviata.")
    else:
        messages.success(request, "Lezione pubblicata.")
    return redirect(reverse("anagrafica:formazione_sessione_detail", args=[sessione_id]) + "#lezione-online")


@login_required
@require_POST
def sessione_online_iscritto(request, sessione_id: int):
    """Azioni sugli iscritti: solleciti, tentativo in più, azzera, registra completamenti."""
    if (b := _blocco_gestione(request, sessione_id)) is not None:
        return b
    sessione = _sessione(sessione_id)
    cfg = so.config(sessione, crea=True)
    azione = request.POST.get("azione")
    ids = [int(x) for x in request.POST.getlist("enrollment_id") if str(x).isdigit()]
    torna = reverse("anagrafica:formazione_sessione_detail", args=[sessione_id]) + "#lezione-online"

    if azione == "sollecita":
        if not cfg.pubblicata:
            messages.error(request, "Pubblica la lezione prima di mandare solleciti.")
            return redirect(torna)
        persone = so.da_sollecitare(sessione, cfg)
        if ids:
            persone = [e for e in persone if e.pk in ids]
        if not persone:
            messages.info(request, "Nessuno da sollecitare.")
            return redirect(torna)
        esito = so.invia_link(sessione, cfg, persone, sollecito=True)
        _audit(request, "sollecito", sessione, **esito)
        messages.success(request, f"Sollecito nel portale a {esito['notifiche']} persone"
                                  + (f" ({esito.get('senza_utente', 0)} senza utente)." if esito.get('senza_utente', 0) else ".")
                                  + " Nessuna email.")
    elif azione == "invia_link":
        persone = list(so.iscrizioni(sessione).filter(pk__in=ids)) if ids else []
        if not cfg.pubblicata or not persone:
            messages.error(request, "Pubblica la lezione e scegli a chi mandare il link.")
            return redirect(torna)
        esito = so.invia_link(sessione, cfg, persone)
        _audit(request, "link_reinviato", sessione, **esito)
        messages.success(request, f"Notifica nel portale a {esito['notifiche']} persone. Nessuna email.")
    elif azione in ("tentativo", "azzera"):
        e = get_object_or_404(TrainingEnrollment, pk=ids[0] if ids else 0, sessione=sessione)
        try:
            so.concedi_tentativo(e) if azione == "tentativo" else so.azzera_avanzamento(e)
        except so.LezioneOnlineError as exc:
            messages.error(request, str(exc))
            return redirect(torna)
        _audit(request, azione, sessione, enrollment=e.pk)
        messages.success(request, "Tentativo in più concesso." if azione == "tentativo"
                         else "Avanzamento azzerato: la persona riparte dalla prima slide.")
    elif azione == "registra":
        fatti, bloccati = so.registra_completamenti(sessione, request.user, enrollment_ids=ids or None)
        _audit(request, "completamenti", sessione, fatti=fatti, bloccati=len(bloccati))
        if fatti:
            messages.success(request, f"{fatti} completament{'o' if fatti == 1 else 'i'} registrat"
                                      f"{'o' if fatti == 1 else 'i'} a libretto.")
        for motivo in bloccati[:10]:
            messages.error(request, "Non registrato " + motivo)
        if not fatti and not bloccati:
            messages.info(request, "Nessun completamento da registrare.")
    else:
        messages.error(request, "Azione non riconosciuta.")
    return redirect(torna)


@login_required
def sessione_online_export(request, sessione_id: int):
    if not _helpers._can_view_formazione(request):
        return HttpResponse(status=403)
    sessione = _sessione(sessione_id)
    cfg = so.config(sessione)
    if cfg is None:
        return HttpResponse("Lezione online non preparata.", status=404)
    righe = so.righe_gestione(sessione, cfg, TrainingSessionSlide.objects.filter(sessione=sessione).count())
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="lezione_online_{sessione.codice_sessione}.csv"'
    resp.write("﻿")
    w = csv.writer(resp, delimiter=";")
    w.writerow(["Partecipante", "Reparto", "Stato", "Slide viste", "Minuti", "Tentativi",
                "Miglior punteggio %", "Ultimo esito", "Ultimo accesso", "Link inviato", "Solleciti"])
    for r in righe:
        ult = r["ultimo"]
        w.writerow([
            r["nome"], r["reparto"], r["stato_label"], r["slide_viste"], r["minuti"], r["n_tentativi"],
            r["miglior_pct"] if r["miglior_pct"] is not None else "",
            ("Superato" if ult.superato else "Non superato") if ult else "",
            timezone.localtime(r["ultimo_accesso"]).strftime("%d-%m-%Y %H:%M") if r["ultimo_accesso"] else "",
            timezone.localtime(r["link_inviato"]).strftime("%d-%m-%Y") if r["link_inviato"] else "",
            r["solleciti"],
        ])
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# Partecipante
# ─────────────────────────────────────────────────────────────────────────────

def _accesso(request, sessione):
    """(cfg, enrollment, anteprima, motivo)."""
    legacy_id = _helpers._current_legacy_anagrafica_id(request)
    is_editor = _helpers._can_edit_formazione(request)
    cfg = so.config(sessione)
    enrollment = None
    if legacy_id:
        enrollment = TrainingEnrollment.objects.filter(sessione=sessione, legacy_anagrafica_id=legacy_id).first()
    anteprima = is_editor and (enrollment is None or request.GET.get("anteprima") == "1")
    motivo = so.motivo_accesso_negato(sessione, cfg, enrollment, anteprima=anteprima)
    return cfg, enrollment, anteprima, motivo


def _nega(request, motivo: str):
    messages.error(request, motivo)
    return redirect("anagrafica:formazione_online_catalog")


@login_required
def sessione_online_player(request, sessione_id: int):
    sessione = _sessione(sessione_id)
    cfg, enrollment, anteprima, motivo = _accesso(request, sessione)
    if motivo:
        return _nega(request, motivo)
    cfg = cfg or so.config(sessione, crea=True)
    elenco = so.slides(sessione)
    n = len(elenco)
    if not n:
        return _nega(request, "La lezione non ha ancora slide.")
    prog = None if anteprima else so.avanzamento(enrollment)
    if prog and prog.superata_il and "n" not in request.GET:
        return redirect("anagrafica:sessione_online_esito", sessione_id=sessione_id)
    massimo = n if anteprima else min(n, prog.slide_viste + 1)
    default = 1 if anteprima else min(n, prog.slide_viste + 1)
    ordine = _intero(request.GET.get("n"), default, 1, n)
    if ordine > massimo:
        ordine = massimo
    if prog and not so.scaduta(cfg):
        so.apri_slide(prog, ordine, n)
    slide = elenco[ordine - 1]
    attesa = so.secondi_da_attendere(prog, ordine, cfg) if prog and not so.scaduta(cfg) else 0
    test_pronto = anteprima or (prog and prog.slide_viste >= n)
    return render(request, "anagrafica/pages/sessione_online_player.html", {
        "sessione": sessione, "cfg": cfg, "slide": slide, "ordine": ordine, "n_slide": n,
        "slides": elenco, "massimo": massimo, "prog": prog, "anteprima": anteprima,
        "attesa": attesa, "test_pronto": test_pronto, "scaduta": so.scaduta(cfg),
        "pct": int(100 * ((prog.slide_viste if prog else ordine)) / n),
        "testo_html": elearning_markdown.render_markdown(slide.testo) if slide.testo and not slide.immagine else "",
        "n_domande": len(so.domande_valide(sessione)),
        "rimasti": so.tentativi_rimasti(cfg, prog) if prog else None,
    })


@login_required
@require_POST
def sessione_online_avanti(request, sessione_id: int):
    sessione = _sessione(sessione_id)
    cfg, enrollment, anteprima, motivo = _accesso(request, sessione)
    if motivo:
        return _nega(request, motivo)
    url = reverse("anagrafica:sessione_online_player", args=[sessione_id])
    ordine = _intero(request.POST.get("ordine"), 1, 1, 10000)
    n = TrainingSessionSlide.objects.filter(sessione=sessione).count()
    if anteprima:
        return redirect(f"{url}?n={min(n, ordine + 1)}&anteprima=1") if ordine < n \
            else redirect(reverse("anagrafica:sessione_online_test", args=[sessione_id]) + "?anteprima=1")
    if so.scaduta(cfg):
        messages.error(request, f"La lezione è scaduta il {cfg.scadenza:%d-%m-%Y}: chiedi al responsabile.")
        return redirect(f"{url}?n={ordine}")
    prog = so.avanzamento(enrollment)
    attesa = so.completa_slide(prog, ordine, cfg)
    if attesa:
        messages.info(request, f"Resta ancora un po' su questa slide: mancano {attesa} secondi.")
        return redirect(f"{url}?n={ordine}")
    if ordine < n:
        return redirect(f"{url}?n={ordine + 1}")
    return redirect("anagrafica:sessione_online_test", sessione_id=sessione_id)


@login_required
def sessione_online_test(request, sessione_id: int):
    sessione = _sessione(sessione_id)
    cfg, enrollment, anteprima, motivo = _accesso(request, sessione)
    if motivo:
        return _nega(request, motivo)
    cfg = cfg or so.config(sessione, crea=True)
    elenco = so.domande_valide(sessione)
    n_slide = TrainingSessionSlide.objects.filter(sessione=sessione).count()
    prog = None if anteprima else so.avanzamento(enrollment)
    if prog:
        if chiuso := so.motivo_test_chiuso(cfg, prog, n_slide):
            messages.info(request, chiuso)
            if prog.superata_il or prog.n_tentativi:
                return redirect("anagrafica:sessione_online_esito", sessione_id=sessione_id)
            return redirect("anagrafica:sessione_online_player", sessione_id=sessione_id)
        if so.scaduta(cfg):
            return _nega(request, f"La lezione è scaduta il {cfg.scadenza:%d-%m-%Y}: chiedi al responsabile.")

    if request.method == "POST":
        if anteprima:
            messages.info(request, "Anteprima: il test non si consegna e non viene registrato.")
            return redirect(reverse("anagrafica:sessione_online_test", args=[sessione_id]) + "?anteprima=1")
        scelte = {d.pk: {int(v) for v in request.POST.getlist(f"d{d.pk}") if str(v).isdigit()} for d in elenco}
        mancanti = [i for i, d in enumerate(elenco, start=1) if not scelte.get(d.pk)]
        if mancanti:
            messages.error(request, "Rispondi a tutte le domande (mancano: "
                           + ", ".join(str(m) for m in mancanti[:12]) + ").")
        else:
            try:
                t = so.correggi(enrollment, cfg, scelte, user=request.user)
            except so.LezioneOnlineError as exc:
                messages.error(request, str(exc))
                return redirect("anagrafica:sessione_online_player", sessione_id=sessione_id)
            _audit(request, "test_consegnato", sessione, enrollment=enrollment.pk,
                   pct=str(t.punteggio_pct), superato=t.superato)
            return redirect("anagrafica:sessione_online_esito", sessione_id=sessione_id)
    for d in elenco:
        d.lista_opzioni = list(d.opzioni.all())
        d.multipla = sum(1 for o in d.lista_opzioni if o.corretta) > 1
        d.scelte = {int(v) for v in request.POST.getlist(f"d{d.pk}") if str(v).isdigit()} \
            if request.method == "POST" else set()
    return render(request, "anagrafica/pages/sessione_online_test.html", {
        "sessione": sessione, "cfg": cfg, "domande": elenco, "prog": prog, "anteprima": anteprima,
        "tentativo_n": (prog.n_tentativi + 1) if prog else 1,
        "tentativi_max": so.tentativi_massimi(cfg, prog) if prog else (cfg.max_tentativi or None),
    })


@login_required
def sessione_online_esito(request, sessione_id: int):
    sessione = _sessione(sessione_id)
    cfg, enrollment, anteprima, motivo = _accesso(request, sessione)
    if motivo or anteprima:
        return _nega(request, motivo or "Anteprima: nessun esito da mostrare.")
    prog = so.avanzamento(enrollment)
    ultimo = TrainingSessionAttempt.objects.filter(enrollment=enrollment).order_by("-inviato_il").first()
    if ultimo is None:
        return redirect("anagrafica:sessione_online_player", sessione_id=sessione_id)
    sbagliate = [v for v in (ultimo.risposte_json or []) if not v.get("ok")]
    return render(request, "anagrafica/pages/sessione_online_esito.html", {
        "sessione": sessione, "cfg": cfg, "prog": prog, "ultimo": ultimo,
        "sbagliate": sbagliate if cfg.mostra_correzioni else [],
        "n_sbagliate": len(sbagliate),
        "rimasti": so.tentativi_rimasti(cfg, prog),
        "completata": enrollment.stato == "COMPLETATO",
    })


@login_required
def sessione_online_slide_img(request, slide_id: int):
    slide = get_object_or_404(TrainingSessionSlide.objects.select_related("sessione"), pk=slide_id)
    if not _helpers._can_view_formazione(request):
        _cfg, _enr, _ant, motivo = _accesso(request, slide.sessione)
        if motivo:
            return HttpResponse(status=403)
    if not slide.immagine:
        return HttpResponse(status=404)
    try:
        fh = slide.immagine.open("rb")
    except FileNotFoundError:
        return HttpResponse(status=404)
    resp = FileResponse(fh, content_type="image/png")
    resp["Content-Disposition"] = f'inline; filename="slide_{slide.pk}.png"'
    resp["Cache-Control"] = "private, max-age=300"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp
