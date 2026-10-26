"""Certificazioni e audit esterni (enti di certificazione, clienti, autorità)."""
from __future__ import annotations

import hashlib

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.audit import log_action

from .acl_bootstrap import PERM_AUDIT_EDIT, PERM_AUDIT_VIEW
from .esterni_forms import AuditEsternoForm, CertificazioneForm, RapportoEsternoForm, RilievoEsternoForm
from .models import AuditEsterno, Certificazione
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


@login_required
def audit_dettaglio(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _deny(request)
    audit = get_object_or_404(AuditEsterno.objects.select_related("certificazione"), pk=pk)
    puo = _has_perm(request, PERM_AUDIT_EDIT)
    return render(request, "sistema_gestione/pages/esterni_audit_dettaglio.html", {
        "page_title": str(audit), "audit": audit, "rilievi": service.rilievi(audit),
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
