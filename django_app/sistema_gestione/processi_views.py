"""Catalogo processi revisionato; permessi del modulo audit, nessuna cancellazione."""
from calendar import monthrange

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Max, Count
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone

from core.audit import log_action
from .acl_bootstrap import PERM_AUDIT_EDIT, PERM_AUDIT_VIEW
from .audit_forms import ProcessoForm
from .models import Audit, Processo, ProcessoRevisione
from .views import MODULE, _has_perm, _nega


@login_required
def catalogo(request):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _nega(request, "Non hai accesso al catalogo processi.")
    query = request.GET.get("q", "").strip()[:200]
    stato = request.GET.get("stato", "attivi")
    processi = Processo.objects.select_related("responsabile").annotate(
        ultimo_audit=Max("audit__data_inizio", filter=Q(audit__stato=Audit.STATO_CHIUSO)),
        audit_totali=Count("audit", distinct=True),
    )
    if stato != "tutti":
        processi = processi.filter(attivo=stato != "archiviati")
    if query:
        processi = processi.filter(Q(codice__icontains=query) | Q(nome__icontains=query) | Q(enti__icontains=query))
    righe = list(processi)
    oggi = timezone.localdate()
    for processo in righe:
        processo.prossimo_audit = None
        if processo.ultimo_audit:
            mesi = processo.ultimo_audit.year * 12 + processo.ultimo_audit.month - 1 + processo.frequenza_mesi
            anno, mese = divmod(mesi, 12)
            mese += 1
            processo.prossimo_audit = processo.ultimo_audit.replace(year=anno, month=mese,
                day=min(processo.ultimo_audit.day, monthrange(anno, mese)[1]))
        processo.da_pianificare = not processo.prossimo_audit or processo.prossimo_audit <= oggi
    return render(request, "sistema_gestione/pages/processi_catalogo.html", {
        "processi": righe, "q": query, "stato": stato,
        "puo_modificare": _has_perm(request, PERM_AUDIT_EDIT),
    })


@login_required
@transaction.atomic
def modifica(request, pk=None):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _nega(request, "Non hai il permesso di gestire il catalogo processi.")
    processo = get_object_or_404(Processo.objects.select_for_update(), pk=pk) if pk else Processo()
    form = ProcessoForm(request.POST or None, instance=processo)
    if request.method == "POST" and form.is_valid():
        processo = form.save(commit=False)
        if pk:
            processo.revisione += 1
        processo.save()
        ProcessoRevisione.objects.create(processo=processo, numero=processo.revisione,
            dati=processo.snapshot(), motivo=form.cleaned_data["motivo"], autore=request.user)
        log_action(request, "processo_revisionato", MODULE,
                   {"codice": processo.codice, "revisione": processo.revisione, "campi": form.changed_data}, oggetto=processo)
        messages.success(request, "Scheda processo salvata. Gli audit esistenti conservano la loro copia.")
        return redirect("sistema_gestione:processo_dettaglio", pk=processo.pk)
    return render(request, "sistema_gestione/pages/audit_form.html", {
        "page_title": f"Modifica {processo}" if pk else "Nuovo processo",
        "form": form, "indietro": reverse("sistema_gestione:processi_catalogo"),
    })


@login_required
def dettaglio(request, pk):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _nega(request, "Non hai accesso al catalogo processi.")
    processo = get_object_or_404(Processo.objects.select_related("responsabile"), pk=pk)
    return render(request, "sistema_gestione/pages/processo_dettaglio.html", {
        "processo": processo, "revisioni": processo.revisioni.select_related("autore"),
        "audit_list": processo.audit.select_related("lead_auditor"),
        "puo_modificare": _has_perm(request, PERM_AUDIT_EDIT),
    })
