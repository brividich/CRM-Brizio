"""Richieste di spostamento delle date: decisione del capocommessa e annullamento del richiedente."""
from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from core.audit import log_action

from ..access import scoped_tasks_queryset, task_permissions_required
from ..models import SpostamentoStato, TaskSpostamento
from ..services import spostamenti as svc


def _data(valore):
    testo = (valore or "").strip()
    return date.fromisoformat(testo) if testo else None


@require_POST
@task_permissions_required("tasks_view")
def spostamento_decidi(request, sp_id: int):
    sp = get_object_or_404(
        TaskSpostamento.objects.select_related("task__project"), pk=sp_id, task__in=scoped_tasks_queryset(request),
    )
    approva = request.POST.get("decisione") == "approva"
    try:
        inizio = _data(request.POST.get("inizio")) if request.POST.get("inizio") else None
        fine = _data(request.POST.get("fine")) if request.POST.get("fine") else None
        svc.decidi(request, sp, approva=approva, nota=request.POST.get("nota", ""), inizio=inizio, fine=fine)
    except ValueError as exc:
        messages.error(request, str(exc) or "Data non valida.")
        return redirect(request.POST.get("next") or f"/tasks/{sp.task_id}/")
    log_action(request, "kickoff_spostamento_decidi", "tasks", {"id": sp.pk, "task_id": sp.task_id, "approva": approva})
    messages.success(request, "Spostamento approvato: date aggiornate e coinvolti avvisati." if approva else "Spostamento rifiutato: il richiedente è avvisato.")
    return redirect(request.POST.get("next") or f"/tasks/{sp.task_id}/")


@require_POST
@task_permissions_required("tasks_view")
def spostamento_annulla(request, sp_id: int):
    sp = get_object_or_404(TaskSpostamento, pk=sp_id, task__in=scoped_tasks_queryset(request))
    if sp.richiesto_da_id != request.user.pk or not sp.in_attesa:
        messages.error(request, "Puoi ritirare solo una tua richiesta ancora in attesa.")
    else:
        sp.stato = SpostamentoStato.ANNULLATA
        sp.nota_decisione = "Ritirata dal richiedente."
        sp.save(update_fields=["stato", "nota_decisione"])
        log_action(request, "kickoff_spostamento_annulla", "tasks", {"id": sp.pk, "task_id": sp.task_id})
        messages.info(request, "Richiesta ritirata.")
    return redirect(f"/tasks/{sp.task_id}/")
