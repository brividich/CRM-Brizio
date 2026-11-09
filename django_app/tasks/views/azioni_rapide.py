"""Azioni rapide su un incarico (menu «⋯»): date, responsabile, priorità, annulla, riapri.

Stesse regole della scheda: chi ha pieni poteri cambia tutto; l'incaricato chiede lo
spostamento delle date; ogni modifica finisce nello Storico e avvisa i coinvolti.
"""
from __future__ import annotations

from datetime import date

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from core.audit import log_action

from ..access import (
    can_manage_task,
    can_set_task_priority,
    ha_pieni_poteri,
    puo_spostare_subito,
    scoped_tasks_queryset,
    task_permissions_required,
)
from ..models import TaskComment, TaskPriority, TaskStatus
from ..services.spostamenti import SpostamentoNonValido, intercetta
from ._shared import _log_task_update_events, _task_snapshot, _utenti_riga_rapida


def _data(valore):
    testo = (valore or "").strip()
    return date.fromisoformat(testo) if testo else None


def _permessi(request, task) -> dict:
    poteri = ha_pieni_poteri(request, task.project) if task.project_id else can_manage_task(request, task)
    incaricato = task.assigned_to_id == getattr(request.user, "id", None)
    gestisce = can_manage_task(request, task)
    return {
        "date": gestisce or incaricato,
        "date_subito": puo_spostare_subito(request, task) and (gestisce or incaricato),
        "responsabile": poteri,
        "priorita": can_set_task_priority(request, task),
        "annulla": poteri and task.status != TaskStatus.CANCELED,
        "riapri": poteri and task.status in (TaskStatus.CANCELED, TaskStatus.DONE),
    }


def _stato(task, request) -> dict:
    utenti = _utenti_riga_rapida(task.project) if task.project_id else {"team": [], "altri": []}
    from datetime import timedelta

    from django.utils import timezone

    from ..services.tappe import carico

    inizio = task.next_step_due or timezone.localdate()
    fine = task.due_date or inizio + timedelta(days=14)
    impegni = carico([pk for g in ("team", "altri") for pk, _n in utenti.get(g, [])], min(inizio, fine), max(inizio, fine))
    return {
        "ok": True,
        "id": task.pk,
        "titolo": task.title,
        "inizio": task.next_step_due.isoformat() if task.next_step_due else "",
        "fine": task.due_date.isoformat() if task.due_date else "",
        "responsabile": task.assigned_to_id or "",
        "priorita": task.priority,
        "stato": task.status,
        "priorita_scelte": TaskPriority.choices,
        "utenti": [
            {"gruppo": g, "id": pk, "nome": nome, "carico": impegni.get(pk, 0)}
            for g in ("team", "altri") for pk, nome in utenti.get(g, [])
        ],
        "permessi": _permessi(request, task),
        "spostamento_aperto": task.spostamenti.filter(stato="IN_ATTESA").exists(),
    }


@require_http_methods(["GET", "POST"])
@task_permissions_required("tasks_view", api=True)
def task_azione_rapida(request, task_id: int):
    task = get_object_or_404(scoped_tasks_queryset(request).select_related("project", "assigned_to"), pk=task_id)
    if request.method == "GET":
        return JsonResponse(_stato(task, request))

    permessi = _permessi(request, task)
    azione = (request.POST.get("azione") or "").strip()
    before = _task_snapshot(task)
    messaggio = ""
    try:
        if azione == "date" and permessi["date"]:
            task.next_step_due = _data(request.POST.get("inizio"))
            task.due_date = _data(request.POST.get("fine"))
            if task.next_step_due and task.due_date and task.due_date < task.next_step_due:
                return JsonResponse({"ok": False, "reason": "La fine non può venire prima dell'inizio."}, status=400)
            richiesta = intercetta(request, task, before, motivo=request.POST.get("motivo", ""))
            if richiesta is not None:
                messaggio = "Richiesta di spostamento inviata al capocommessa."
            else:
                messaggio = "Date aggiornate."
        elif azione == "responsabile" and permessi["responsabile"]:
            raw = (request.POST.get("responsabile") or "").strip()
            from ..forms import task_active_users_queryset

            nuovo = task_active_users_queryset().filter(pk=int(raw)).first() if raw.isdigit() else None
            if raw and nuovo is None:
                return JsonResponse({"ok": False, "reason": "Responsabile non valido."}, status=400)
            task.assigned_to = nuovo
            messaggio = "Responsabile cambiato."
        elif azione == "priorita" and permessi["priorita"]:
            valore = (request.POST.get("priorita") or "").strip()
            if valore not in TaskPriority.values:
                return JsonResponse({"ok": False, "reason": "Priorità non valida."}, status=400)
            task.priority = valore
            messaggio = "Priorità aggiornata."
        elif azione == "annulla" and permessi["annulla"]:
            motivo = (request.POST.get("motivo") or "").strip()
            if not motivo:
                return JsonResponse({"ok": False, "reason": "Scrivi il motivo dell'annullamento."}, status=400)
            task.status = TaskStatus.CANCELED
            TaskComment.objects.create(task=task, author=request.user, body=f"Attività annullata: {motivo}")
            messaggio = "Attività annullata."
        elif azione == "riapri" and permessi["riapri"]:
            task.status = TaskStatus.TODO
            messaggio = "Attività riaperta."
        else:
            return JsonResponse({"ok": False, "reason": "Questa modifica la decide il capocommessa."}, status=403)
    except (ValueError, SpostamentoNonValido) as exc:
        return JsonResponse({"ok": False, "reason": str(exc) or "Dati non validi."}, status=400)

    task.save()
    _log_task_update_events(task, request.user, before)
    if before.get("assigned_to_id") != task.assigned_to_id:
        from ..services.meeting_tasks import notify_task_assignment

        notify_task_assignment(task, actor=request.user)
    log_action(request, "kickoff_azione_rapida", "tasks", {"task_id": task.pk, "azione": azione})
    return JsonResponse({**_stato(task, request), "messaggio": messaggio})
