"""Programma basato sul rischio (prompt 08): ciclo triennale, calendario, impostazioni, rifiuto e deroghe."""
from __future__ import annotations

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from .acl_bootstrap import PERM_AUDIT_APPROVA, PERM_AUDIT_EDIT, PERM_AUDIT_VIEW
from .models import Audit, AuditPersona, CicloAudit, ProgrammaAudit
from .services import audit as service
from .services import programma as programma_service
from .views import MODULE, _has_perm, _nega


class CicloForm(forms.ModelForm):
    class Meta:
        model = CicloAudit
        fields = ["nome", "anno_inizio", "anno_fine", "note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}
        help_texts = {"nome": "Es. Ciclo di certificazione EN 9100 2026-2028"}


class ImpostazioniForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for chiave, (label, _default, tipo) in programma_service.IMPOSTAZIONI.items():
            nome = chiave.replace(".", "__")
            valore = programma_service.impostazione(chiave)
            if tipo == "bool":
                self.fields[nome] = forms.BooleanField(label=label, required=False, initial=programma_service.impostazione_attiva(chiave))
            elif tipo == "int":
                self.fields[nome] = forms.IntegerField(label=label, min_value=1, max_value=365, initial=int(valore or 0) or None)
            else:
                self.fields[nome] = forms.CharField(label=label, required=False, max_length=500, initial=valore)

    def valori(self) -> dict[str, str]:
        out = {}
        for chiave, (_label, _default, tipo) in programma_service.IMPOSTAZIONI.items():
            valore = self.cleaned_data[chiave.replace(".", "__")]
            out[chiave] = ("1" if valore else "0") if tipo == "bool" else str(valore if valore is not None else "")
        return out


@login_required
def cicli(request):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _nega(request, "Non puoi consultare il programma audit.")
    puo_modificare = _has_perm(request, PERM_AUDIT_EDIT)
    form = CicloForm(request.POST or None, initial={"anno_inizio": timezone.localdate().year, "anno_fine": timezone.localdate().year + 2})
    if request.method == "POST":
        if not puo_modificare:
            return _nega(request, "Non puoi gestire i cicli di audit.")
        if form.is_valid():
            ciclo = form.save(commit=False)
            ciclo.created_by = request.user
            ciclo.full_clean()
            ciclo.save()
            log_action(request, "audit_ciclo_creato", MODULE, {"ciclo": str(ciclo)}, oggetto=ciclo)
            return redirect("sistema_gestione:programma_ciclo", pk=ciclo.pk)
    return render(request, "sistema_gestione/pages/audit_cicli.html", {
        "page_title": "Cicli di audit", "cicli": CicloAudit.objects.all(), "form": form, "puo_modificare": puo_modificare,
    })


@login_required
def ciclo_dettaglio(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _nega(request, "Non puoi consultare il programma audit.")
    ciclo = get_object_or_404(CicloAudit, pk=pk)
    return render(request, "sistema_gestione/pages/audit_ciclo.html", {
        "page_title": str(ciclo), "ciclo": ciclo, "copertura": programma_service.copertura_ciclo(ciclo),
    })


@login_required
def calendario(request):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _nega(request, "Non puoi consultare il programma audit.")
    oggi = timezone.localdate()
    try:
        anno = int(request.GET.get("anno") or oggi.year)
        mese = int(request.GET.get("mese") or oggi.month)
        if not (2000 <= anno <= 2100 and 1 <= mese <= 12):
            raise ValueError
    except (TypeError, ValueError):
        anno, mese = oggi.year, oggi.month
    return render(request, "sistema_gestione/pages/audit_calendario.html", {
        "page_title": "Calendario audit", "cal": programma_service.calendario_mese(anno, mese), "oggi": oggi,
    })


@login_required
def impostazioni(request):
    if not _has_perm(request, PERM_AUDIT_APPROVA):
        return _nega(request, "Le impostazioni degli audit sono riservate a RSGI/Direzione.")
    form = ImpostazioniForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        from core.models import SiteConfig

        prima = {k: programma_service.impostazione(k) for k in programma_service.IMPOSTAZIONI}
        dopo = form.valori()
        for chiave, valore in dopo.items():
            SiteConfig.set(chiave, valore, programma_service.IMPOSTAZIONI[chiave][0][:300])
        cambiate = {k: {"da": prima[k], "a": v} for k, v in dopo.items() if prima[k] != v}
        log_action(request, "audit_impostazioni", MODULE, {"cambiate": cambiate})
        messages.success(request, "Impostazioni degli audit salvate.")
        return redirect("sistema_gestione:audit_impostazioni")
    return render(request, "sistema_gestione/pages/audit_form.html", {
        "page_title": "Impostazioni degli audit interni", "form": form,
        "indietro": reverse("sistema_gestione:audit_index"),
    })


@login_required
@require_POST
@transaction.atomic
def programma_rifiuta(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_APPROVA):
        return _nega(request, "Respingere il programma spetta alla Direzione.")
    programma = get_object_or_404(ProgrammaAudit.objects.select_for_update(), pk=pk)
    try:
        service.rifiuta_programma(programma, motivo=request.POST.get("motivo", ""), utente=request.user)
    except service.TransizioneNonAmmessa as exc:
        messages.error(request, str(exc))
    else:
        log_action(request, "programma_respinto", MODULE, {"motivo": programma.motivo_rifiuto}, oggetto=programma)
        messages.success(request, "Programma riportato in bozza con il motivo indicato.")
    return redirect("sistema_gestione:programma_dettaglio", pk=pk)


@login_required
@require_POST
@transaction.atomic
def audit_approva_deroga(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_APPROVA):
        return _nega(request, "La deroga all'indipendenza la approva l'RDD.")
    audit = get_object_or_404(Audit.objects.select_for_update().select_related("lead_auditor"), pk=pk)
    team = {a.user_id for a in [audit.lead_auditor, *audit.auditor.all()] if a.user_id}
    if not programma_service.deroga_imparzialita_ammessa():
        messages.error(request, "Le impostazioni non ammettono deroghe all'indipendenza.")
    elif audit.stato != Audit.STATO_PIANIFICATO or not audit.imparzialita_deroga_motivo.strip():
        messages.error(request, "Serve un piano in bozza con la deroga motivata.")
    elif request.user.pk in team:
        messages.error(request, "Chi fa parte del team di audit non può approvare la propria deroga.")
    else:
        audit.imparzialita_deroga_approvata_da = request.user
        audit.imparzialita_deroga_approvata_il = timezone.now()
        audit.save(update_fields=["imparzialita_deroga_approvata_da", "imparzialita_deroga_approvata_il", "updated_at"])
        log_action(request, "audit_deroga_imparzialita_approvata", MODULE,
                   {"motivo": audit.imparzialita_deroga_motivo}, oggetto=audit)
        messages.success(request, "Deroga all'indipendenza approvata e tracciata.")
    return redirect(reverse("sistema_gestione:audit_dettaglio", kwargs={"pk": pk}) + "#approvazioni")


@login_required
@require_POST
def audit_annulla(request, pk: int):
    """Annulla un audit non ancora avviato: motivo obbligatorio, la cella del programma torna libera."""
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _nega(request, "Non puoi annullare gli audit.")
    motivo = (request.POST.get("motivo") or "").strip()
    with transaction.atomic():
        audit = get_object_or_404(Audit.objects.select_for_update(), pk=pk)
        if audit.stato not in {Audit.STATO_PIANIFICATO, Audit.STATO_PIANO_APPROVATO}:
            messages.error(request, "Si annulla solo un audit non ancora avviato.")
            return redirect("sistema_gestione:audit_dettaglio", pk=pk)
        if not motivo:
            messages.error(request, "Indica il motivo dell'annullamento.")
            return redirect("sistema_gestione:audit_dettaglio", pk=pk)
        audit.stato = Audit.STATO_ANNULLATO
        audit.motivo_annullamento = motivo[:500]
        audit.annullato_da = request.user
        audit.annullato_il = timezone.now()
        audit.save(update_fields=["stato", "motivo_annullamento", "annullato_da", "annullato_il", "updated_at"])
        celle = list(audit.celle_programma.values_list("pk", flat=True))
        audit.celle_programma.update(audit=None)
    from .services import audit_outlook

    try:
        audit_outlook.annulla_invito(audit)
    except Exception as exc:  # noqa: BLE001 - l'audit resta annullato; l'invito si cancella a mano
        messages.warning(request, f"Audit annullato, ma l'invito Outlook non è stato cancellato: {exc}")
    log_action(request, "audit_annullato", MODULE, {"motivo": audit.motivo_annullamento, "celle_liberate": celle}, oggetto=audit)
    messages.success(request, "Audit annullato: la verifica del programma torna da pianificare.")
    return redirect("sistema_gestione:audit_dettaglio", pk=pk)


@login_required
@require_POST
def audit_conferme_aggiorna(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _nega(request, "Non puoi aggiornare le conferme.")
    audit = get_object_or_404(Audit, pk=pk)
    from .services import audit_outlook

    try:
        conteggio = audit_outlook.aggiorna_conferme(audit)
    except Exception as exc:  # noqa: BLE001 - errore Graph spiegato all'utente
        messages.error(request, f"Conferme non aggiornate: {exc}")
    else:
        sintesi = ", ".join(f"{dict(AuditPersona.CONFERMA_CHOICES).get(k, k)}: {v}" for k, v in sorted(conteggio.items())) or "nessuna risposta"
        log_action(request, "audit_conferme_aggiornate", MODULE, conteggio, oggetto=audit)
        messages.success(request, f"Conferme aggiornate da Outlook ({sintesi}).")
    return redirect(reverse("sistema_gestione:audit_dettaglio", kwargs={"pk": pk}) + "#comunicazione")
