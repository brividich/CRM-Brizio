"""Certificazioni e audit esterni (enti di certificazione, clienti, autorità)."""
from __future__ import annotations

import hashlib
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.excel_export import make_xlsx_response

from .acl_bootstrap import PERM_AUDIT_EDIT, PERM_AUDIT_VIEW
from .esterni_forms import AuditEsternoForm, CertificazioneForm, RapportoEsternoForm, RilievoEsternoForm
from .models import AuditEsterno, Certificazione, Processo
from .services import audit_esterni as service
from .views import MODULE, _has_perm, _nega


def _deny(request):
    return _nega(request, "Non hai i permessi richiesti per le certificazioni e gli audit esterni.")


@login_required
def elenco(request):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _deny(request)
    audit_list = list(AuditEsterno.objects.select_related("certificazione"))
    for a in audit_list:
        a.n_rilievi = service.rilievi(a).count()
        a.n_nc_aperte = service.nc_aperte(a)
    return render(request, "sistema_gestione/pages/esterni_elenco.html", {
        "page_title": "Certificazioni e audit esterni",
        "certificazioni": Certificazione.objects.all(),
        "audit_list": audit_list,
        "scadenze": service.scadenze(),
        "puo_modificare": _has_perm(request, PERM_AUDIT_EDIT),
    })


@login_required
def certificazione_modifica(request, pk: int | None = None):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    oggetto = get_object_or_404(Certificazione, pk=pk) if pk else None
    form = CertificazioneForm(request.POST or None, instance=oggetto)
    if request.method == "POST" and form.is_valid():
        cert = form.save(commit=False)
        cert.aggiornata_da = request.user
        cert.save()
        log_action(request, "certificazione_salvata", MODULE, {"id": cert.pk}, oggetto=cert)
        messages.success(request, f"Certificazione «{cert}» salvata.")
        return redirect("sistema_gestione:esterni_elenco")
    return render(request, "sistema_gestione/pages/esterni_certificazione_form.html", {
        "page_title": "Certificazione", "form": form, "oggetto": oggetto})


@login_required
def audit_modifica(request, pk: int | None = None):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    oggetto = get_object_or_404(AuditEsterno, pk=pk) if pk else None
    iniziale = {}
    if oggetto is None and request.GET.get("certificazione", "").isdigit():
        cert = Certificazione.objects.filter(pk=int(request.GET["certificazione"])).first()
        if cert:
            iniziale = {"certificazione": cert, "ente": cert.ente, "tipo": "SORVEGLIANZA",
                        "data_inizio": cert.prossima_sorveglianza,
                        **{campo: True for campo, norma in (("en9100", "EN9100"), ("iso45001", "ISO45001"),
                                                            ("iso14001", "ISO14001"), ("iso27001", "ISO27001"),
                                                            ("pdr125", "PDR125")) if cert.norma == norma}}
    form = AuditEsternoForm(request.POST or None, instance=oggetto, initial=iniziale)
    if request.method == "POST" and form.is_valid():
        audit = form.save(commit=False)
        if audit.pk is None:
            audit.creato_da = request.user
        audit.save()
        log_action(request, "audit_esterno_salvato", MODULE, {"id": audit.pk}, oggetto=audit)
        messages.success(request, "Audit esterno salvato.")
        return redirect("sistema_gestione:esterni_audit", pk=audit.pk)
    return render(request, "sistema_gestione/pages/esterni_audit_form.html", {
        "page_title": "Audit esterno", "form": form, "oggetto": oggetto})


def _url_controllo(link: str) -> str:
    if not link:
        return ""
    if link.startswith("precedente:"):
        return reverse("sistema_gestione:esterni_audit", args=[int(link.split(":", 1)[1])])
    return reverse(link)


@login_required
def audit_dettaglio(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _deny(request)
    audit = get_object_or_404(AuditEsterno.objects.select_related("certificazione", "piano_inviato_da"), pk=pk)
    puo = _has_perm(request, PERM_AUDIT_EDIT)
    controlli = service.preparazione(audit) if audit.stato == AuditEsterno.STATO_PIANIFICATO else []
    for c in controlli:
        c["url"] = _url_controllo(c["link"])
    return render(request, "sistema_gestione/pages/esterni_audit_dettaglio.html", {
        "page_title": str(audit), "audit": audit, "rilievi": service.rilievi(audit),
        "controlli": controlli, "esito_preparazione": service.esito_preparazione(controlli) if controlli else "",
        "piano_da_inviare": service.piano_da_inviare(audit), "oggi": timezone.localdate(),
        "processi_catalogo": Processo.objects.filter(attivo=True).order_by("codice"),
        "puo_modificare": puo and audit.stato != AuditEsterno.STATO_CHIUSO,
        "problemi_chiusura": service.problemi_chiusura(audit),
        "rilievo_form": RilievoEsternoForm(initial={"data_richiesta": audit.risposta_entro}),
        "rapporto_form": RapportoEsternoForm(),
    })


@login_required
@require_POST
@transaction.atomic
def rilievo_aggiungi(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    audit = get_object_or_404(AuditEsterno.objects.select_for_update(), pk=pk)
    if audit.stato == AuditEsterno.STATO_CHIUSO:
        messages.error(request, "L'audit è chiuso: non si aggiungono rilievi.")
        return redirect("sistema_gestione:esterni_audit", pk=pk)
    form = RilievoEsternoForm(request.POST)
    if not form.is_valid():
        for errori in form.errors.values():
            for e in errori:
                messages.error(request, e)
        return redirect("sistema_gestione:esterni_audit", pk=pk)
    voce = service.crea_rilievo(audit, utente=request.user, **form.cleaned_data)
    log_action(request, "audit_esterno_rilievo", MODULE, {"audit": audit.pk, "ofi": voce.numero}, oggetto=audit)
    messages.success(request, f"Rilievo registrato nel Registro OFI con il n. {voce.numero}.")
    return redirect("sistema_gestione:esterni_audit", pk=pk)


@login_required
@require_POST
def rapporto_carica(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    audit = get_object_or_404(AuditEsterno, pk=pk)
    if audit.stato == AuditEsterno.STATO_CHIUSO:
        messages.error(request, "L'audit è chiuso: il rapporto non si sostituisce.")
        return redirect("sistema_gestione:esterni_audit", pk=pk)
    form = RapportoEsternoForm(request.POST, request.FILES)
    if not form.is_valid():
        for e in form.errors.get("file", []):
            messages.error(request, e)
        return redirect("sistema_gestione:esterni_audit", pk=pk)
    caricato = form.cleaned_data["file"]
    digest = hashlib.sha256()
    for blocco in caricato.chunks():
        digest.update(blocco)
    caricato.seek(0)
    audit.rapporto.save(caricato.name, caricato, save=False)
    audit.rapporto_nome = caricato.name[:200]
    audit.rapporto_sha256 = digest.hexdigest()
    audit.save(update_fields=["rapporto", "rapporto_nome", "rapporto_sha256", "aggiornato_il"])
    log_action(request, "audit_esterno_rapporto", MODULE, {"audit": audit.pk, "sha256": audit.rapporto_sha256},
               oggetto=audit)
    messages.success(request, "Rapporto caricato.")
    return redirect("sistema_gestione:esterni_audit", pk=pk)


@login_required
def rapporto_scarica(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _deny(request)
    audit = get_object_or_404(AuditEsterno, pk=pk)
    if not audit.rapporto:
        raise Http404("Rapporto non presente")
    try:
        fh = audit.rapporto.open("rb")
    except FileNotFoundError as exc:
        raise Http404("File non trovato") from exc
    log_action(request, "audit_esterno_rapporto_download", MODULE, {"audit": audit.pk}, oggetto=audit)
    return FileResponse(fh, as_attachment=True, filename=audit.rapporto_nome or "rapporto.pdf")


@login_required
@require_POST
@transaction.atomic
def audit_chiudi(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    audit = get_object_or_404(AuditEsterno.objects.select_for_update(), pk=pk)
    problemi = service.problemi_chiusura(audit)
    if problemi:
        messages.error(request, " ".join(problemi))
    else:
        audit.stato = AuditEsterno.STATO_CHIUSO
        audit.save(update_fields=["stato", "aggiornato_il"])
        log_action(request, "audit_esterno_chiuso", MODULE, {"audit": audit.pk}, oggetto=audit)
        messages.success(request, "Audit esterno chiuso.")
    return redirect("sistema_gestione:esterni_audit", pk=pk)


@login_required
def preparazione_export(request, pk: int):
    """Pacchetto di preparazione all'audit dell'ente: i controlli e le voci da sistemare in xlsx."""
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _deny(request)
    audit = get_object_or_404(AuditEsterno.objects.select_related("certificazione"), pk=pk)
    controlli = service.preparazione(audit)
    righe = service.righe_preparazione(controlli)
    log_action(request, "audit_esterno_preparazione_export", MODULE, {"audit": audit.pk, "righe": len(righe)},
               oggetto=audit)
    return make_xlsx_response(
        filename=f"preparazione_audit_esterno_{audit.data_inizio:%Y%m%d}.xlsx", columns=service.COLONNE_PREPARAZIONE,
        rows=righe, sheet_title="Preparazione", title=f"Preparazione all'audit: {audit}",
        subtitle=f"Estratto il {timezone.localtime():%d/%m/%Y %H:%M}",
        filters_label=", ".join(audit.norme_sigle) or audit.ente,
    )


@login_required
def piano_export(request, pk: int):
    """Piano azioni da inviare all'ente, dai testi PDCA delle voci MOD.174 dei rilievi."""
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _deny(request)
    audit = get_object_or_404(AuditEsterno, pk=pk)
    righe = service.righe_piano_azioni(audit)
    log_action(request, "audit_esterno_piano_export", MODULE, {"audit": audit.pk, "righe": len(righe)}, oggetto=audit)
    return make_xlsx_response(
        filename=f"piano_azioni_{audit.data_inizio:%Y%m%d}.xlsx", columns=service.COLONNE_PIANO, rows=righe,
        sheet_title="Piano azioni", title=f"Piano azioni: {audit}",
        subtitle=f"Estratto il {timezone.localtime():%d/%m/%Y %H:%M}", filters_label=audit.ente,
    )


@login_required
@require_POST
@transaction.atomic
def piano_inviato(request, pk: int):
    """Registra la data di invio del piano azioni all'ente: ferma il promemoria di risposta."""
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    audit = get_object_or_404(AuditEsterno.objects.select_for_update(), pk=pk)
    oggi = timezone.localdate()
    try:
        inviato = date.fromisoformat(request.POST.get("inviato_il") or oggi.isoformat())
    except ValueError:
        messages.error(request, "Data di invio non valida.")
        return redirect("sistema_gestione:esterni_audit", pk=pk)
    if inviato > oggi or inviato < audit.data_inizio:
        messages.error(request, "La data di invio deve essere tra l'inizio dell'audit e oggi.")
        return redirect("sistema_gestione:esterni_audit", pk=pk)
    audit.piano_inviato_il = inviato
    audit.piano_inviato_da = request.user
    audit.save(update_fields=["piano_inviato_il", "piano_inviato_da", "aggiornato_il"])
    log_action(request, "audit_esterno_piano_inviato", MODULE, {"audit": audit.pk, "il": inviato.isoformat()},
               oggetto=audit)
    messages.success(request, f"Invio del piano azioni registrato al {inviato:%d/%m/%Y}.")
    return redirect("sistema_gestione:esterni_audit", pk=pk)
