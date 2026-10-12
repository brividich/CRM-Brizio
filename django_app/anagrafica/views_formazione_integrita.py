"""Formazione d'aula: chiusura e approvazione dell'edizione (MOD.040), riapertura
motivata, verifica NC a 6 mesi, annullamento dei completamenti, integrità dati
e guida in-app. Le regole stanno in ``services.formazione_integrita``."""
from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models_formazione import TrainingEmployeeRecord, TrainingExportLog, TrainingSession
from .services import formazione_integrita as fi
from .views import (
    _audit_formazione,
    _can_approve_formazione,
    _can_edit_formazione,
    _can_view_formazione,
)

logger = logging.getLogger(__name__)


def _al_dettaglio(sessione_id: int):
    return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)


@login_required
@require_POST
def formazione_sessione_approva(request, sessione_id: int):
    if not _can_approve_formazione(request):
        messages.error(request, "L'approvazione del MOD.040 è riservata a MSM/MSO "
                                "(permesso «Formazione (approva MOD.040)»).")
        return _al_dettaglio(sessione_id)
    sessione = get_object_or_404(TrainingSession.objects.select_related("corso"), pk=sessione_id)
    try:
        validati = fi.approva_edizione(sessione, request.user, request.POST.get("note", ""))
    except ValueError as exc:
        messages.error(request, str(exc))
        return _al_dettaglio(sessione_id)
    _audit_formazione(request, "edizione_approvata", {
        "sessione_id": sessione.pk, "codice_sessione": sessione.codice_sessione,
        "completamenti_validati": validati,
    })
    messages.success(request, f"MOD.040 dell'edizione «{sessione.codice_sessione}» approvato"
                              + (f": {validati} completamenti validati." if validati else "."))
    return _al_dettaglio(sessione_id)


@login_required
@require_POST
def formazione_sessione_riapri(request, sessione_id: int):
    sessione = get_object_or_404(TrainingSession, pk=sessione_id)
    if not _can_edit_formazione(request) or (sessione.is_approvata and not _can_approve_formazione(request)):
        messages.error(request, "Non hai i permessi per riaprire questa edizione"
                                + (" (è approvata: serve MSM/MSO)." if sessione.is_approvata else "."))
        return _al_dettaglio(sessione_id)
    try:
        traccia = fi.riapri_edizione(sessione, request.user, request.POST.get("motivo", ""))
    except ValueError as exc:
        messages.error(request, str(exc))
        return _al_dettaglio(sessione_id)
    _audit_formazione(request, "edizione_riaperta", {
        "sessione_id": sessione.pk, "codice_sessione": sessione.codice_sessione, **traccia,
    })
    messages.success(request, f"Edizione «{sessione.codice_sessione}» riaperta: ora è «In corso». "
                              "Corretto il dato, riportala a «Completata».")
    return _al_dettaglio(sessione_id)


@login_required
@require_POST
def formazione_sessione_verifica_nc(request, sessione_id: int):
    if not _can_approve_formazione(request):
        messages.error(request, "La verifica NC del MOD.040 la registra MSM/MSO.")
        return _al_dettaglio(sessione_id)
    sessione = get_object_or_404(TrainingSession, pk=sessione_id)
    if not sessione.is_approvata:
        messages.error(request, "Approva prima il MOD.040 dell'edizione.")
        return _al_dettaglio(sessione_id)
    try:
        fi.registra_verifica_nc(sessione, request.user, request.POST.get("esito", ""), request.POST.get("note", ""))
    except ValueError as exc:
        messages.error(request, str(exc))
        return _al_dettaglio(sessione_id)
    _audit_formazione(request, "edizione_verifica_nc", {
        "sessione_id": sessione.pk, "esito": sessione.verifica_nc_esito,
    })
    messages.success(request, "Verifica «assenza NC nei 6 mesi» registrata.")
    return _al_dettaglio(sessione_id)


@login_required
def formazione_sessione_mod040(request, sessione_id: int):
    if not _can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")
    sessione = get_object_or_404(
        TrainingSession.objects.select_related("corso", "docente", "docente_ente", "corso__ente_formativo"),
        pk=sessione_id,
    )
    from .services.mod040_pdf import build_mod040_pdf_bytes

    pdf = build_mod040_pdf_bytes(sessione)
    try:
        TrainingExportLog.objects.create(
            tipo="MOD040", filtri_json={"sessione_id": sessione.pk},
            righe_esportate=sessione.iscrizioni.count(), generato_da=request.user,
            ip_address=request.META.get("REMOTE_ADDR") or None,
        )
    except Exception:
        logger.exception("Log export MOD.040 non scritto (sessione %s)", sessione_id)
    nome = f"MOD040_{sessione.codice_sessione}.pdf".replace("/", "-").replace(" ", "_")
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{nome}"'
    return resp


@login_required
@require_POST
def formazione_record_annulla(request, record_id: int):
    record = get_object_or_404(TrainingEmployeeRecord.tutti.select_related("corso", "sessione"), pk=record_id)
    prossima = request.POST.get("next") or ""
    if not url_has_allowed_host_and_scheme(prossima, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
        prossima = ""
    indietro = redirect(prossima) if prossima else (
        redirect("anagrafica:formazione_sessione_iscritti", sessione_id=record.sessione_id)
        if record.sessione_id else redirect("anagrafica:formazione_dashboard")
    )
    if not _can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per annullare un completamento.")
        return indietro
    try:
        riepilogo = fi.annulla_record(record, request.user, request.POST.get("motivo", ""))
    except (ValueError, fi.EdizioneChiusa) as exc:
        messages.error(request, str(exc))
        return indietro
    _audit_formazione(request, "completamento_annullato", riepilogo)
    testo = "Completamento annullato: non conta più per requisiti e scadenze."
    if riepilogo.get("qualifica"):
        testo += f" Qualifica {riepilogo['qualifica']}."
    messages.success(request, testo)
    return indietro


@login_required
def formazione_integrita(request):
    if not _can_edit_formazione(request):
        messages.error(request, "La pagina «Integrità dati» è riservata a chi gestisce la formazione.")
        return redirect("anagrafica:formazione_dashboard")
    if request.method == "POST" and request.POST.get("azione") == "correggi":
        fatti = fi.correggi()
        _audit_formazione(request, "integrita_correzioni_automatiche", fatti)
        totale = sum(v for k, v in fatti.items() if k != "iscrizioni_ricalcolate")
        messages.success(request, f"Correzioni automatiche applicate: {totale} "
                                  f"({fatti['iscrizioni_ricalcolate']} iscrizioni ricalcolate).")
        return redirect("anagrafica:formazione_integrita")
    controlli = fi.controlli_integrita()
    return render(request, "anagrafica/pages/formazione_integrita.html", {
        "page_title": "Integrità dati formazione",
        "controlli": controlli,
        "n_anomalie": sum(c.n for c in controlli),
        "n_correggibili": sum(c.n for c in controlli if c.correggibile),
        "annullati": TrainingEmployeeRecord.tutti.filter(annullato_il__isnull=False)
                     .select_related("corso").order_by("-annullato_il")[:50],
    })


@login_required
def formazione_guida(request):
    if not _can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")
    return render(request, "anagrafica/pages/formazione_guida.html", {
        "page_title": "Guida formazione d'aula",
        "is_editor": _can_edit_formazione(request),
        "can_approve": _can_approve_formazione(request),
    })
