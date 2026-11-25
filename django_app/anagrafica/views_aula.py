"""Sessioni in aula, gestione: presenze in un tocco, QR d'aula, test, chiusura, Da chiudere, efficacia.

La logica sta in ``services.formazione_aula``; qui solo permessi, form e messaggi.
"""
from __future__ import annotations

import io
import logging
from datetime import time

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models_formazione import TrainingEfficacia, TrainingEnrollment, TrainingLesson, TrainingSession
from .services import formazione_aula as aula
from .views import _helpers

logger = logging.getLogger(__name__)


def _puo(request) -> bool:
    return _helpers._can_edit_formazione(request)


def _blocco(request, sessione) -> str:
    from .services.formazione_integrita import motivo_blocco_edizione
    return motivo_blocco_edizione(sessione)


def _ora(valore):
    try:
        h, m = str(valore or "").strip().split(":")[:2]
        return time(int(h), int(m))
    except (ValueError, TypeError):
        return None


def _url_presenze(sessione_id, lezione_id):
    return reverse("anagrafica:formazione_lezione_presenze", args=[sessione_id, lezione_id])


# ── Presenze in un tocco ───────────────────────────────────────────────────

@login_required
@require_POST
def presenze_tutti(request, sessione_id: int, lezione_id: int):
    lezione = get_object_or_404(TrainingLesson.objects.select_related("sessione"), pk=lezione_id, sessione_id=sessione_id)
    if not _puo(request) or _blocco(request, lezione.sessione):
        messages.error(request, "Non puoi modificare le presenze di questa edizione.")
        return redirect(_url_presenze(sessione_id, lezione_id))
    try:
        n = aula.tutti_presenti(lezione, request.user)
        messages.success(request, f"{n} presenti registrati: ora tocca solo chi manca o è arrivato in ritardo." if n
                         else "Tutti gli attesi avevano già una presenza registrata.")
    except aula.AulaError as exc:
        messages.error(request, str(exc))
    return redirect(_url_presenze(sessione_id, lezione_id) + "#lezione-registro")


@login_required
@require_POST
def presenza_rapida(request, sessione_id: int, lezione_id: int):
    lezione = get_object_or_404(TrainingLesson.objects.select_related("sessione"), pk=lezione_id, sessione_id=sessione_id)
    if not _puo(request) or _blocco(request, lezione.sessione):
        messages.error(request, "Non puoi modificare le presenze di questa edizione.")
        return redirect(_url_presenze(sessione_id, lezione_id))
    enr = get_object_or_404(TrainingEnrollment, sessione_id=sessione_id,
                            legacy_anagrafica_id=request.POST.get("legacy_anagrafica_id") or 0)
    try:
        aula.segna(lezione, enr, request.POST.get("stato") or "", request.user,
                   _ora(request.POST.get("ingresso")), _ora(request.POST.get("uscita")))
    except aula.AulaError as exc:
        messages.error(request, str(exc))
    return redirect(_url_presenze(sessione_id, lezione_id) + "#lezione-registro")


# ── QR d'aula e test ───────────────────────────────────────────────────────

def _url_qr(request, sessione) -> str:
    from django.conf import settings
    path = reverse("corso_aperto:aula", args=[aula.token(sessione)])
    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    if base:
        return base + path
    return request.build_absolute_uri(path)


@login_required
def qr(request, sessione_id: int):
    sessione = get_object_or_404(TrainingSession.objects.select_related("corso"), pk=sessione_id)
    if not _puo(request):
        messages.error(request, "Non hai i permessi per gestire la sessione.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
    lezione = aula.lezione_di_oggi(sessione)
    presenze = []
    if lezione is not None:
        nomi = _helpers._build_nomi_map()
        for p in lezione.presenze.filter(firma_ingresso=True).order_by("ora_ingresso"):
            presenze.append({"nome": nomi.get(p.legacy_anagrafica_id, f"#{p.legacy_anagrafica_id}"),
                             "ingresso": p.ora_ingresso, "uscita": p.ora_uscita})
    from .services.sessione_online import config, domande_valide
    cfg = config(sessione)
    ctx = {
        "sessione": sessione, "lezione": lezione, "aperta": aula.lezione_aperta(sessione) is not None,
        "url": _url_qr(request, sessione), "presenze": presenze,
        "n_iscritti": sessione.iscrizioni.exclude(stato="RITIRATO").count(),
        "test_aperto": bool(cfg and cfg.test_in_aula), "n_domande": len(domande_valide(sessione)) if cfg else 0,
        "bloccata": bool(_blocco(request, sessione)),
    }
    if request.headers.get("HX-Request"):
        return render(request, "anagrafica/components/_aula_qr_presenze.html", ctx)
    return render(request, "anagrafica/pages/formazione_aula_qr.html", ctx)


@login_required
def qr_png(request, sessione_id: int):
    import qrcode

    sessione = get_object_or_404(TrainingSession, pk=sessione_id)
    if not _puo(request):
        return HttpResponse(status=403)
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=14, border=2)
    code.add_data(_url_qr(request, sessione))
    code.make(fit=True)
    buf = io.BytesIO()
    code.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    resp = HttpResponse(buf.getvalue(), content_type="image/png")
    resp["Cache-Control"] = "private, no-store"
    return resp


@login_required
@require_POST
def test_aula(request, sessione_id: int):
    sessione = get_object_or_404(TrainingSession.objects.select_related("corso"), pk=sessione_id)
    if not _puo(request) or _blocco(request, sessione):
        messages.error(request, "Non puoi aprire il test di questa edizione.")
    else:
        try:
            aperto = request.POST.get("aperto") == "1"
            aula.apri_chiudi_test(sessione, aperto)
            messages.success(request, "Test aperto: si fa dal telefono con lo stesso QR." if aperto else "Test chiuso.")
        except aula.AulaError as exc:
            messages.error(request, str(exc))
    nxt = request.POST.get("next") or ""
    if nxt.startswith("/anagrafica/") and "//" not in nxt:
        return redirect(nxt)
    return redirect("anagrafica:formazione_aula_qr", sessione_id=sessione_id)


# ── Chiudi l'edizione ──────────────────────────────────────────────────────

@login_required
def chiudi(request, sessione_id: int):
    sessione = get_object_or_404(TrainingSession.objects.select_related("corso"), pk=sessione_id)
    if not _puo(request):
        messages.error(request, "Non hai i permessi per chiudere l'edizione.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
    if request.method == "POST":
        if sessione.is_approvata:
            messages.error(request, "L'edizione è già approvata: per cambiarla va riaperta.")
            return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
        esiti = {int(k[6:]): v for k, v in request.POST.items() if k.startswith("esito_") and k[6:].isdigit()}
        carta = {int(k[6:]): v for k, v in request.POST.items() if k.startswith("carta_") and k[6:].isdigit()}
        try:
            out = aula.chiudi(sessione, request.user, esiti, carta)
        except aula.AulaError as exc:
            messages.error(request, str(exc))
            return redirect("anagrafica:formazione_aula_chiudi", sessione_id=sessione_id)
        for b in out.bloccati[:8]:
            messages.warning(request, f"Non completato: {b}")
        if out.chiusa:
            messages.success(request, f"Edizione chiusa: {out.completati} completament{'o' if out.completati == 1 else 'i'} "
                                      "registrati sulle schede. L'approvazione MOD.040 è tra le attività di MSM/MSO.")
            return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
        messages.info(request, f"Salvato. Restano {out.aperti} person{'a' if out.aperti == 1 else 'e'} senza esito: "
                               "l'edizione si chiude quando tutti ne hanno uno.")
        return redirect("anagrafica:formazione_aula_chiudi", sessione_id=sessione_id)
    righe = aula.proposta(sessione)
    soglia_pres, esame, soglia_test = aula._soglie(sessione)
    from .services.formazione_efficacia import aggiungi_mesi, mesi_efficacia_richiesti

    class _R:  # record fittizio per sapere se ci sarà l'efficacia
        sessione_id = sessione.pk
    _R.sessione = sessione
    mesi_eff = mesi_efficacia_richiesti(sessione.corso, _R)
    return render(request, "anagrafica/pages/formazione_aula_chiudi.html", {
        "sessione": sessione, "righe": righe, "ESITI": aula.ESITI_SCELTA,
        "soglia_pres": soglia_pres, "esame": esame, "soglia_test": soglia_test,
        "n_completati": sum(1 for r in righe if r.proposto == "COMPLETATO" and not r.finale),
        "n_da_decidere": sum(1 for r in righe if not r.proposto),
        "mesi_eff": mesi_eff,
        "data_eff": aggiungi_mesi(min(sessione.data_fine, _oggi()), mesi_eff) if mesi_eff and sessione.data_fine else None,
        "approvata": sessione.is_approvata,
    })


def _oggi():
    from django.utils import timezone
    return timezone.localdate()


# ── Da chiudere: azioni in blocco dall'elenco Sessioni ─────────────────────

@login_required
@require_POST
def da_chiudere_azione(request):
    torna = reverse("anagrafica:formazione_sessioni_list") + "?da_chiudere=1"
    if not _puo(request):
        messages.error(request, "Non hai i permessi per chiudere le sessioni.")
        return redirect(torna)
    ids = [int(x) for x in request.POST.getlist("sel") if str(x).isdigit()]
    azione = request.POST.get("azione")
    sessioni = list(aula.da_chiudere().filter(pk__in=ids))
    if not sessioni:
        messages.info(request, "Seleziona almeno una sessione.")
        return redirect(torna)
    chiuse, parziali, annullate, errori = 0, 0, 0, []
    for s in sessioni:
        try:
            if azione == "annulla":
                aula.annulla(s)
                annullate += 1
            else:
                out = aula.chiudi_con_proposta(s, request.user)
                chiuse += out.chiusa
                parziali += not out.chiusa
        except aula.AulaError as exc:
            errori.append(str(exc))
        except Exception:
            logger.exception("Chiusura in blocco: sessione %s", s.pk)
            errori.append(f"{s.codice_sessione}: errore imprevisto, aprila e chiudila a mano.")
    if azione == "annulla":
        messages.success(request, f"{annullate} sessioni annullate.")
    else:
        messages.success(request, f"{chiuse} sessioni chiuse." + (
            f" {parziali} restano aperte perché qualcuno non ha un esito proponibile: aprile e decidi." if parziali else ""))
    for e in errori[:8]:
        messages.warning(request, e)
    return redirect(torna)


# ── Efficacia (MT CN 06 §9.5) ──────────────────────────────────────────────

@login_required
def efficacia(request):
    from .services.formazione_aula import METODI_EFFICACIA, efficacie_da_valutare
    tutte = _helpers._can_view_formazione(request) and request.GET.get("mie") != "1"
    mio = _helpers_legacy_id(request)
    if request.method == "POST":
        v = get_object_or_404(TrainingEfficacia, pk=request.POST.get("id") or 0, valutata_il__isnull=True)
        visibili = {x.pk for x in efficacie_da_valutare(mio, tutte=_helpers._can_edit_formazione(request))}
        if v.pk not in visibili:
            messages.error(request, "Questa valutazione non è tra le tue.")
        else:
            try:
                aula.salva_efficacia(v, request.POST.get("esito") or "", request.user,
                                     request.POST.get("metodo") or "", request.POST.get("azione") or "",
                                     request.POST.get("note") or "")
                messages.success(request, "Valutazione salvata.")
            except aula.AulaError as exc:
                messages.error(request, str(exc))
        return redirect(request.get_full_path())
    elenco = efficacie_da_valutare(mio, tutte=tutte)
    nomi = _helpers._build_nomi_map()
    for v in elenco:
        v.nome = nomi.get(v.legacy_anagrafica_id, f"#{v.legacy_anagrafica_id}")
        v.dovuta = v.attesa_dal <= _oggi()
    fatte = []
    if tutte:
        fatte = list(TrainingEfficacia.objects.filter(valutata_il__isnull=False).select_related("record", "record__corso")
                     .order_by("-valutata_il", "-id")[:30])
        for v in fatte:
            v.nome = nomi.get(v.legacy_anagrafica_id, f"#{v.legacy_anagrafica_id}")
    return render(request, "anagrafica/pages/formazione_efficacia.html", {
        "elenco": elenco, "fatte": fatte, "tutte": tutte, "METODI": METODI_EFFICACIA,
        "ESITI": TrainingEfficacia.ESITO_CHOICES, "puo_tutte": _helpers._can_view_formazione(request),
    })


def _helpers_legacy_id(request) -> int | None:
    """legacy_anagrafica_id dell'utente collegato (None se non collegato)."""
    try:
        from .views_elearning import _ctx_utente
        legacy_id, _ = _ctx_utente(request)
        return legacy_id
    except Exception:
        return None
