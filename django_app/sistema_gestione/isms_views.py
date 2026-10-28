"""Viste fail-closed della Fase 3: audit ISMS (MT CN 276, MOD.171 e MOD.168)."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.audit import log_action

from .acl_bootstrap import PERM_AUDIT_EDIT, PERM_AUDIT_VIEW, PERM_SOA_EDIT
from .audit_forms import (
    AuditIsmsControlloForm,
    AuditIsmsPianoForm,
    AuditIsmsRapportoForm,
    AuditIsmsRequisitoForm,
)
from .audit_views import _assigned_executor, _deny, _rapporto_modificabile
from .models import Audit, AuditIsmsControllo, AuditIsmsRequisito
from .services import audit as service
from .services import audit_isms as isms_service
from .views import MODULE, _has_perm


def _isms_url(audit: Audit, anchor: str = "") -> str:
    url = reverse("sistema_gestione:audit_isms", kwargs={"pk": audit.pk})
    return f"{url}#{anchor}" if anchor else url


def _audit_isms(pk: int, *, lock: bool = False) -> Audit:
    qs = Audit.objects.select_for_update() if lock else Audit.objects.all()
    audit = get_object_or_404(qs, pk=pk)
    if not audit.is_isms:
        raise Http404
    return audit


def _puo_compilare(request, audit: Audit) -> bool:
    return _assigned_executor(request, audit) and _rapporto_modificabile(audit)


def _riga_context(request, audit, riga, form=None, tipo="ctrl"):
    form_class = AuditIsmsControlloForm if tipo == "ctrl" else AuditIsmsRequisitoForm
    return {
        "audit": audit, "riga": riga, "tipo": tipo,
        "form": form or form_class(instance=riga, prefix=f"{tipo}{riga.pk}"),
        "puo_compilare": _puo_compilare(request, audit),
    }


@login_required
def audit_isms(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _deny(request)
    audit = _audit_isms(pk)
    if audit.stato != Audit.STATO_ANNULLATO:
        isms_service.assicura_isms(audit)
    dati = getattr(audit, "isms", None)
    if dati is None:
        raise Http404
    puo_compilare = _puo_compilare(request, audit)
    controlli = list(audit.isms_controlli.select_related("controllo", "ofi"))
    temi = []
    for riga in controlli:
        if not temi or temi[-1]["tema"] != riga.controllo.tema:
            temi.append({"tema": riga.controllo.tema, "label": riga.controllo.get_tema_display(), "righe": []})
        temi[-1]["righe"].append(_riga_context(request, audit, riga))
    return render(request, "sistema_gestione/pages/audit_isms.html", {
        "page_title": f"Audit ISMS {audit.numero}",
        "audit": audit, "dati": dati,
        "requisiti": [_riga_context(request, audit, r, tipo="req") for r in audit.isms_requisiti.select_related("ofi")],
        "temi": temi,
        "contatori": isms_service.contatori_isms(audit),
        "problemi": isms_service.problemi_rapporto_isms(audit) if audit.stato in {Audit.STATO_IN_CORSO, Audit.STATO_RAPPORTO} else [],
        "azioni": isms_service.azioni_correttive(audit),
        "form_piano": AuditIsmsPianoForm(instance=dati),
        "form_testata": AuditIsmsRapportoForm(instance=dati),
        "puo_modificare_piano": _has_perm(request, PERM_AUDIT_EDIT) and audit.stato == Audit.STATO_PIANIFICATO,
        "puo_compilare": puo_compilare,
        "puo_proporre_soa": (_has_perm(request, PERM_SOA_EDIT) and audit.stato == Audit.STATO_CHIUSO
                             and not dati.soa_proposta_id),
    })


@login_required
@require_POST
@transaction.atomic
def audit_isms_piano(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    audit = _audit_isms(pk, lock=True)
    if audit.stato != Audit.STATO_PIANIFICATO:
        messages.error(request, "Il piano non è più modificabile.")
        return redirect(_isms_url(audit, "isms-piano"))
    dati = isms_service.assicura_isms(audit)
    form = AuditIsmsPianoForm(request.POST, instance=dati)
    if form.is_valid():
        form.save()
        service.invalida_approvazione_piano(audit)
        log_action(request, "audit_isms_piano_salvato", MODULE, {}, oggetto=audit)
        messages.success(request, "Siti oggetto di audit salvati (MOD.171).")
    else:
        messages.error(request, "Dati del sito non validi: " + " ".join(sum(form.errors.values(), [])))
    return redirect(_isms_url(audit, "isms-piano"))


@login_required
@require_POST
@transaction.atomic
def audit_isms_testata(request, pk: int):
    audit = _audit_isms(pk, lock=True)
    if not _puo_compilare(request, audit):
        return _deny(request)
    form = AuditIsmsRapportoForm(request.POST, instance=isms_service.assicura_isms(audit))
    if form.is_valid():
        form.save()
        Audit.objects.filter(pk=audit.pk).update(riepilogo_generato="")
        log_action(request, "audit_isms_testata_salvata", MODULE, {}, oggetto=audit)
        messages.success(request, "Dati del rapporto MOD.168 salvati.")
    else:
        messages.error(request, "Dati non validi: " + " ".join(sum(form.errors.values(), [])))
    return redirect(_isms_url(audit, "isms-testata"))


def _salva_riga(request, pk: int, riga_pk: int, tipo: str):
    audit = _audit_isms(pk, lock=True)
    if not _puo_compilare(request, audit):
        return _deny(request)
    modello, form_class = ((AuditIsmsControllo, AuditIsmsControlloForm) if tipo == "ctrl"
                           else (AuditIsmsRequisito, AuditIsmsRequisitoForm))
    riga = get_object_or_404(modello.objects.select_related("ofi"), pk=riga_pk, audit=audit)
    form = form_class(request.POST, instance=riga, prefix=f"{tipo}{riga.pk}")
    errore = ""
    if form.is_valid():
        try:
            riga = isms_service.salva_riga(form.save(commit=False), utente=request.user)
        except ValidationError as exc:
            errore = "; ".join(exc.messages)
            riga.refresh_from_db()
            form = form_class(instance=riga, prefix=f"{tipo}{riga.pk}")
        else:
            log_action(request, "audit_isms_riga_salvata", MODULE, {
                "riga": riga.riferimento, "rilievo": riga.rilievo,
                **({"livello": riga.livello} if tipo == "ctrl" else {}),
            }, oggetto=audit)
            form = None
    else:
        errore = "Correggi i campi evidenziati."
    if getattr(request, "htmx", False):
        contesto = _riga_context(request, audit, riga, form=form, tipo=tipo)
        contesto["errore"] = errore
        contesto["salvato"] = not errore
        return render(request, "sistema_gestione/components/_isms_riga.html", contesto)
    if errore:
        messages.error(request, f"{riga.riferimento}: {errore}")
    else:
        messages.success(request, f"{riga.riferimento} salvato.")
    return redirect(_isms_url(audit, f"isms-{tipo}-{riga.pk}"))


@login_required
@require_POST
@transaction.atomic
def audit_isms_requisito(request, pk: int, riga_pk: int):
    return _salva_riga(request, pk, riga_pk, "req")


@login_required
@require_POST
@transaction.atomic
def audit_isms_controllo(request, pk: int, riga_pk: int):
    return _salva_riga(request, pk, riga_pk, "ctrl")


@login_required
@require_POST
@transaction.atomic
def audit_isms_proponi_soa(request, pk: int):
    if not (_has_perm(request, PERM_SOA_EDIT) and _has_perm(request, PERM_AUDIT_VIEW)):
        return _deny(request)
    audit = _audit_isms(pk, lock=True)
    from .services.soa import TransizioneNonAmmessa

    try:
        revisione, variazioni = isms_service.proponi_aggiornamento_soa(audit, utente=request.user)
    except TransizioneNonAmmessa as exc:
        messages.error(request, str(exc))
        return redirect(_isms_url(audit, "isms-soa"))
    log_action(request, "audit_isms_proposta_soa", MODULE, {"revisione": revisione.numero, "variazioni": variazioni}, oggetto=audit)
    messages.success(request, f"Aperta la revisione {revisione.numero} della SoA in bozza con {variazioni} livelli aggiornati: verificala e proponila alla Direzione.")
    return redirect("sistema_gestione:soa_revisione", numero=revisione.numero)
