"""Helper comuni alle viste KICK-OFF: shell, timeline, eventi, rollup."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import F

from core.acl import user_can_modulo_action

from ..models import (
    Project,
    SubTask,
    Task,
    TaskEvent,
    TaskEventType,
    TaskImpostazioni,
    TaskPriority,
    TaskStatus,
    VRFDocStatus,
)
from ..access import (
    has_task_permission,
)
from ..services.absences import (
    _task_date_absence_conflicts,
)

logger = logging.getLogger(__name__)
User = get_user_model()
OPEN_STATUSES = {TaskStatus.TODO, TaskStatus.IN_PROGRESS}
KEY_EDIT_FIELDS = ("title", "priority", "due_date", "next_step_text", "next_step_due", "tags", "project_id")
TASK_EVENT_TONE_BY_TYPE = {
    TaskEventType.STATUS_CHANGE: "blue",
    TaskEventType.ASSIGNMENT_CHANGE: "amber",
    TaskEventType.EDIT: "slate",
    TaskEventType.COMMENT_ADDED: "teal",
    TaskEventType.SUBTASK_ADDED: "green",
    TaskEventType.SUBTASK_STATUS_CHANGE: "purple",
    TaskEventType.ATTACHMENT_ADDED: "indigo",
}
TASK_EVENT_TITLE_BY_TYPE = {
    TaskEventType.STATUS_CHANGE: "Stato aggiornato",
    TaskEventType.ASSIGNMENT_CHANGE: "Assegnazione aggiornata",
    TaskEventType.EDIT: "Scheda attivita modificata",
    TaskEventType.COMMENT_ADDED: "Commento aggiunto",
    TaskEventType.SUBTASK_ADDED: "Subtask creata",
    TaskEventType.SUBTASK_STATUS_CHANGE: "Subtask aggiornata",
    TaskEventType.ATTACHMENT_ADDED: "Allegato caricato",
}
TASK_EVENT_DESCRIPTION_BY_TYPE = {
    TaskEventType.STATUS_CHANGE: "Lo stato operativo dell'attivita e cambiato.",
    TaskEventType.ASSIGNMENT_CHANGE: "La responsabilita dell'attivita e stata aggiornata.",
    TaskEventType.EDIT: "Sono stati modificati dati principali dell'attivita.",
    TaskEventType.COMMENT_ADDED: "E stato registrato un nuovo commento nella conversazione.",
    TaskEventType.SUBTASK_ADDED: "E stata aggiunta una nuova sotto-attivita operativa.",
    TaskEventType.SUBTASK_STATUS_CHANGE: "Lo stato di una subtask e stato aggiornato.",
    TaskEventType.ATTACHMENT_ADDED: "E stato caricato un documento collegato all'attivita.",
}
TASK_FIELD_LABELS = {
    "title": "Titolo",
    "priority": "Priorita",
    "due_date": "Data fine",
    "next_step_text": "Prossima azione",
    "next_step_due": "Data inizio",
    "tags": "Tag",
    "project_id": "Kickoff",
}
TASK_STATUS_LABELS_IT = {
    TaskStatus.TODO: "Da fare",
    TaskStatus.IN_PROGRESS: "In corso",
    TaskStatus.DONE: "Completata",
    TaskStatus.CANCELED: "Annullata",
}
TASK_PRIORITY_LABELS_IT = {
    TaskPriority.LOW: "Bassa",
    TaskPriority.MEDIUM: "Media",
    TaskPriority.HIGH: "Alta",
}


def _coerce_positive_int(value, *, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        parsed = default
    return max(minimum, parsed)


def _vrf_status_detail(project, cfg: "TaskImpostazioni") -> dict:
    """Calcola lo stato del documento VRF per un kickoff.

    Restituisce dict con:
      status: 'ok' | 'na' | 'pending' | 'warning' | 'blocked'
      label: str (messaggio utente)
      is_blocked: bool
      days_pending: int | None
      show_upload_cta: bool
    """
    from django.utils import timezone as tz

    vrf_status = project.vrf_status

    if vrf_status == VRFDocStatus.UPLOADED:
        return {
            "status": "ok",
            "label": "Documento VRF caricato.",
            "is_blocked": False,
            "days_pending": None,
            "show_upload_cta": False,
        }

    if vrf_status == VRFDocStatus.NOT_REQUIRED:
        return {
            "status": "na",
            "label": "Documento VRF non richiesto per questo kickoff.",
            "is_blocked": False,
            "days_pending": None,
            "show_upload_cta": False,
        }

    # PENDING
    today = tz.localdate()
    created_date = project.created_at.date() if project.created_at else today
    days = (today - created_date).days

    if days >= cfg.vrf_blocking_days:
        return {
            "status": "blocked",
            "label": (
                f"Kickoff BLOCCATO: documento VRF non caricato da {days} giorni "
                f"(soglia blocco: {cfg.vrf_blocking_days} giorni). "
                "Non e possibile aggiungere o modificare attivita kickoff finche il documento non viene caricato."
            ),
            "is_blocked": True,
            "days_pending": days,
            "show_upload_cta": True,
        }

    if days >= cfg.vrf_reminder_days:
        return {
            "status": "warning",
            "label": (
                f"Attenzione: documento VRF non ancora caricato ({days} giorni dalla creazione del kickoff). "
                f"Il kickoff sara bloccato dopo {cfg.vrf_blocking_days} giorni."
            ),
            "is_blocked": False,
            "days_pending": days,
            "show_upload_cta": True,
        }

    return {
        "status": "pending",
        "label": f"Documento VRF non ancora caricato ({days} giorni dalla creazione del kickoff).",
        "is_blocked": False,
        "days_pending": days,
        "show_upload_cta": True,
    }


def _apply_default_ordering(qs):
    return qs.order_by(
        F("next_step_due").asc(nulls_last=True),
        F("due_date").asc(nulls_last=True),
        "-updated_at",
    )


def _tasks_shell_context(
    request,
    *,
    active: str,
    task: Task | None = None,
    project: Project | None = None,
    action_count: int | None = None,
) -> dict:
    current_project = project
    if current_project is None and task is not None and getattr(task, "project_id", None):
        current_project = task.project
    if current_project is not None and action_count is None:
        from ..action_register import count_project_open_actions

        action_count = count_project_open_actions(current_project)
    return {
        "tasks_shell_active": active,
        "tasks_shell_task": task,
        "tasks_shell_project": current_project,
        "tasks_shell_open_action_count": action_count or 0,
        "tasks_shell_can_create": has_task_permission(request, "tasks_create"),
        "tasks_shell_can_admin": user_can_modulo_action(request, "tasks", "admin_tasks"),
        "tasks_shell_is_scope_admin": has_task_permission(request, "tasks_admin"),
    }


def _json_safe(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _log_event(task: Task, actor, event_type: str, payload: dict | None = None) -> None:
    TaskEvent.objects.create(
        task=task,
        actor=actor,
        type=event_type,
        payload=payload or {},
    )


def _task_snapshot(task: Task) -> dict:
    return {
        "status": task.status,
        "assigned_to_id": task.assigned_to_id,
        "title": task.title,
        "priority": task.priority,
        "due_date": task.due_date,
        "next_step_text": task.next_step_text,
        "next_step_due": task.next_step_due,
        "tags": task.tags,
        "project_id": task.project_id,
    }


def _display_user(user) -> str:
    if not user:
        return "Sistema"
    full_name = user.get_full_name()
    return full_name or user.username


def _looks_like_iso_date(value) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _display_event_value(field_name: str, value, *, users_by_id: dict[int, object], projects_by_id: dict[int, Project]) -> str:
    if value in (None, ""):
        return "non impostato"
    if isinstance(value, date):
        return value.strftime("%d-%m-%Y")
    if field_name in {"due_date", "next_step_due"} and _looks_like_iso_date(value):
        return date.fromisoformat(value).strftime("%d-%m-%Y")
    if field_name in {"status", "from", "to"} and value in TASK_STATUS_LABELS_IT:
        return TASK_STATUS_LABELS_IT[value]
    if field_name == "priority" and value in TASK_PRIORITY_LABELS_IT:
        return TASK_PRIORITY_LABELS_IT[value]
    if field_name in {"assigned_to_id", "from_user_id", "to_user_id", "target_user_id"}:
        try:
            user_id = int(value)
        except (TypeError, ValueError):
            return str(value)
        return _display_user(users_by_id.get(user_id)) if user_id else "non assegnato"
    if field_name == "project_id":
        try:
            project_id = int(value)
        except (TypeError, ValueError):
            return str(value)
        project = projects_by_id.get(project_id)
        return project.name if project else f"Kickoff #{project_id}"
    return str(value)


def _safe_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _collect_timeline_lookup_ids(events: list[TaskEvent]) -> tuple[set[int], set[int], set[int]]:
    user_ids: set[int] = set()
    project_ids: set[int] = set()
    subtask_ids: set[int] = set()

    for event in events:
        payload = event.payload or {}
        for key in ("from_user_id", "to_user_id", "target_user_id"):
            user_id = _safe_int(payload.get(key))
            if user_id:
                user_ids.add(user_id)

        subtask_id = _safe_int(payload.get("subtask_id"))
        if subtask_id:
            subtask_ids.add(subtask_id)

        project_change = (payload.get("changes") or {}).get("project_id") or {}
        if isinstance(project_change, dict):
            for raw_project_id in (project_change.get("from"), project_change.get("to")):
                project_id = _safe_int(raw_project_id)
                if project_id:
                    project_ids.add(project_id)

    return user_ids, project_ids, subtask_ids


def _timeline_detail(label: str, before: str | None = None, after: str | None = None, note: str | None = None) -> dict:
    return {
        "label": label,
        "before": before,
        "after": after,
        "note": note,
    }


def _build_task_timeline_events(task: Task) -> list[dict]:
    events = list(task.events.all())
    user_ids, project_ids, subtask_ids = _collect_timeline_lookup_ids(events)
    users_by_id = User.objects.in_bulk(user_ids) if user_ids else {}
    projects_by_id = Project.objects.in_bulk(project_ids) if project_ids else {}
    subtasks_by_id = SubTask.objects.in_bulk(subtask_ids) if subtask_ids else {}

    timeline = []
    for event in events:
        payload = event.payload or {}
        title = TASK_EVENT_TITLE_BY_TYPE.get(event.type, event.get_type_display())
        description = TASK_EVENT_DESCRIPTION_BY_TYPE.get(event.type, "Evento registrato dal sistema.")
        details: list[dict] = []

        if event.type == TaskEventType.STATUS_CHANGE:
            details.append(
                _timeline_detail(
                    "Stato",
                    _display_event_value("status", payload.get("from"), users_by_id=users_by_id, projects_by_id=projects_by_id),
                    _display_event_value("status", payload.get("to"), users_by_id=users_by_id, projects_by_id=projects_by_id),
                )
            )
            if payload.get("source") == "subtask_rollup":
                description = "Stato riallineato automaticamente in base alle subtask."

        elif event.type == TaskEventType.ASSIGNMENT_CHANGE:
            details.append(
                _timeline_detail(
                    "Assegnatario",
                    _display_event_value("from_user_id", payload.get("from_user_id"), users_by_id=users_by_id, projects_by_id=projects_by_id),
                    _display_event_value("to_user_id", payload.get("to_user_id"), users_by_id=users_by_id, projects_by_id=projects_by_id),
                )
            )

        elif event.type == TaskEventType.EDIT:
            changes = payload.get("changes") or {}
            changed_labels = []
            for field_name, change in changes.items():
                if not isinstance(change, dict):
                    continue
                label = TASK_FIELD_LABELS.get(field_name, field_name.replace("_", " ").title())
                changed_labels.append(label.lower())
                details.append(
                    _timeline_detail(
                        label,
                        _display_event_value(field_name, change.get("from"), users_by_id=users_by_id, projects_by_id=projects_by_id),
                        _display_event_value(field_name, change.get("to"), users_by_id=users_by_id, projects_by_id=projects_by_id),
                    )
                )
            if changed_labels:
                description = "Campi aggiornati: " + ", ".join(changed_labels) + "."

        elif event.type == TaskEventType.COMMENT_ADDED:
            if payload.get("target_user_id"):
                details.append(
                    _timeline_detail(
                        "Notifica",
                        note=_display_event_value("target_user_id", payload.get("target_user_id"), users_by_id=users_by_id, projects_by_id=projects_by_id),
                    )
                )

        elif event.type == TaskEventType.SUBTASK_ADDED:
            details.append(_timeline_detail("Subtask", note=payload.get("title") or f"Subtask #{payload.get('subtask_id')}"))
            if payload.get("status"):
                details.append(
                    _timeline_detail(
                        "Stato iniziale",
                        note=_display_event_value("status", payload.get("status"), users_by_id=users_by_id, projects_by_id=projects_by_id),
                    )
                )

        elif event.type == TaskEventType.SUBTASK_STATUS_CHANGE:
            subtask = subtasks_by_id.get(_safe_int(payload.get("subtask_id")))
            details.append(_timeline_detail("Subtask", note=subtask.title if subtask else f"Subtask #{payload.get('subtask_id')}"))
            details.append(
                _timeline_detail(
                    "Stato",
                    _display_event_value("status", payload.get("from"), users_by_id=users_by_id, projects_by_id=projects_by_id),
                    _display_event_value("status", payload.get("to"), users_by_id=users_by_id, projects_by_id=projects_by_id),
                )
            )

        elif event.type == TaskEventType.ATTACHMENT_ADDED:
            target = "Kickoff" if payload.get("target") == "project" else "Attivita"
            details.append(_timeline_detail("Documento", note=payload.get("file_name") or f"Allegato #{payload.get('attachment_id')}"))
            details.append(_timeline_detail("Collegato a", note=target))

        timeline.append(
            {
                "event": event,
                "title": title,
                "description": description,
                "details": details,
                "tone": TASK_EVENT_TONE_BY_TYPE.get(event.type, "slate"),
                "actor_name": _display_user(event.actor),
                "technical_payload": json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) if payload else "",
            }
        )
    return timeline


def _add_task_absence_warnings(request, task: Task) -> None:
    conflicts = _task_date_absence_conflicts(task)
    if not conflicts or not task.assigned_to_id:
        return

    assignee_name = task.assigned_to.get_full_name() or task.assigned_to.get_username()
    field_labels = {
        "due_date": "data prevista conclusione",
        "next_step_due": "data obiettivo prossima azione",
    }
    for field_name in ("next_step_due", "due_date"):
        if field_name not in conflicts:
            continue
        target_date = getattr(task, field_name, None)
        if not target_date:
            continue
        unique_labels: list[str] = []
        for entry in conflicts[field_name]:
            label = f"{entry['tipo']} ({entry['status']})"
            if label not in unique_labels:
                unique_labels.append(label)
        label_text = ", ".join(unique_labels[:2])
        if len(unique_labels) > 2:
            label_text += ", ..."
        messages.warning(
            request,
            (
                f"Conflitto assenze: {field_labels[field_name]} del {target_date.strftime('%d-%m-%Y')} "
                f"coincide con assenza di {assignee_name} ({label_text})."
            ),
        )


def _sync_task_integrations(request, task: Task, form, *, action: str) -> None:
    """Dopo save: allinea evento Outlook + reminder portale secondo il form submit.

    `action` e' "create" o "edit" - controlla solo messages che vogliamo mostrare.
    Non blocca mai il flusso: errori Graph producono messages.warning ma il task resta salvato.
    """
    from ..outlook_reminder import sync_task_outlook_event, sync_task_portal_reminder

    requested = bool(form.cleaned_data.get("add_to_outlook"))
    explicit_email = form.cleaned_data.get("outlook_target_email") or ""
    try:
        level, msg = sync_task_outlook_event(
            request=request, task=task, requested=requested, explicit_email=str(explicit_email),
        )
        if msg:
            if level == "success":
                messages.success(request, msg)
            elif level == "info":
                messages.info(request, msg)
            elif level == "warning":
                messages.warning(request, msg)
            elif level == "error":
                messages.error(request, msg)
    except Exception as exc:
        messages.warning(request, f"Integrazione Outlook non disponibile: {exc}")

    try:
        sync_task_portal_reminder(task=task)
    except Exception as exc:
        # Fire-and-forget: non bloccare il save del task
        logger.warning("Task reminder sync fallita (task=%s): %s", task.id, exc)

    # Integrazione Carichi Macchina (non bloccante): se l'attività è "lavoro
    # macchina" su un asset con profilo Macchina, allinea/crea la pianificazione
    # collegata; altrimenti rimuove quella eventualmente generata.
    try:
        from gestione_carichi_macchina.integrations import sync_kickoff_task_to_pianificazione

        outcome, _pian = sync_kickoff_task_to_pianificazione(task, user=getattr(request, "user", None))
        if outcome == "created":
            messages.info(request, "Attività sincronizzata nei Carichi Macchina (pianificazione creata).")
        elif outcome == "updated":
            messages.info(request, "Pianificazione Carichi Macchina aggiornata da questa attività.")
        elif outcome == "removed":
            messages.info(request, "Pianificazione Carichi Macchina collegata rimossa.")
    except Exception as exc:
        logger.warning("Sync Carichi Macchina fallita (task=%s): %s", task.id, exc)


def _compute_rollup_status(task: Task) -> str | None:
    subtask_statuses = list(task.subtasks.values_list("status", flat=True))
    if not subtask_statuses:
        return None
    if all(status == TaskStatus.DONE for status in subtask_statuses):
        return TaskStatus.DONE
    if all(status == TaskStatus.CANCELED for status in subtask_statuses):
        return TaskStatus.CANCELED
    if any(status == TaskStatus.IN_PROGRESS for status in subtask_statuses):
        return TaskStatus.IN_PROGRESS
    has_done = any(status == TaskStatus.DONE for status in subtask_statuses)
    has_todo = any(status == TaskStatus.TODO for status in subtask_statuses)
    if has_done and has_todo:
        return TaskStatus.IN_PROGRESS
    return TaskStatus.TODO


def _apply_subtask_rollup(task: Task, actor) -> None:
    next_status = _compute_rollup_status(task)
    if not next_status or next_status == task.status:
        return
    old_status = task.status
    task.status = next_status
    task.save(update_fields=["status", "updated_at"])
    _log_event(
        task,
        actor,
        TaskEventType.STATUS_CHANGE,
        {"from": old_status, "to": next_status, "source": "subtask_rollup"},
    )


def _log_task_update_events(task: Task, actor, before: dict) -> None:
    if before.get("status") != task.status:
        _log_event(
            task,
            actor,
            TaskEventType.STATUS_CHANGE,
            {"from": before.get("status"), "to": task.status},
        )

    if before.get("assigned_to_id") != task.assigned_to_id:
        _log_event(
            task,
            actor,
            TaskEventType.ASSIGNMENT_CHANGE,
            {"from_user_id": before.get("assigned_to_id"), "to_user_id": task.assigned_to_id},
        )

    key_changes = {}
    for field_name in KEY_EDIT_FIELDS:
        old_value = before.get(field_name)
        new_value = getattr(task, field_name)
        if old_value != new_value:
            key_changes[field_name] = {
                "from": _json_safe(old_value),
                "to": _json_safe(new_value),
            }
    if key_changes:
        _log_event(
            task,
            actor,
            TaskEventType.EDIT,
            {"changes": key_changes},
        )
