"""Helper per integrare i Task con Outlook Calendar e il sistema di promemoria portale.

Chiamati da `task_create` / `task_edit` dopo il salvataggio del Task. Gli errori
non sono bloccanti: una creazione evento Outlook fallita produce solo un warning
`messages.warning`, il task resta salvato. Il promemoria portale si basa su
`TaskImpostazioni.giorni_preavviso` e viene materializzato come `core.Notifica`
dal management command `send_task_reminders`.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from uuid import uuid5, NAMESPACE_URL

from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

from core.outlook_calendar import (
    build_event_payload,
    create_event,
    delete_event,
    graph_ready,
    update_event,
)

from .models import Task, TaskCalendarEvent, TaskImpostazioni, TaskReminder

logger = logging.getLogger(__name__)


def _source_key(task: Task) -> str:
    return f"tasks.task:{task.id}:due"


def _transaction_id(task: Task) -> str:
    return str(uuid5(NAMESPACE_URL, f"https://novicrom.local/tasks/{task.id}/calendar"))


def _task_body_html(request, task: Task) -> str:
    detail_url = request.build_absolute_uri(reverse("tasks:detail", args=[task.id])) if request else ""
    project_label = ""
    if task.project_id and task.project:
        project_label = task.project.name or f"Kickoff #{task.project_id}"
    assignee_label = ""
    if task.assigned_to_id and task.assigned_to:
        assignee_label = task.assigned_to.get_full_name() or task.assigned_to.username
    lines = [
        f"<p><strong>Task kickoff:</strong> {task.title}</p>",
    ]
    if project_label:
        lines.append(f"<p><strong>Kickoff:</strong> {project_label}</p>")
    if assignee_label:
        lines.append(f"<p><strong>Assegnatario:</strong> {assignee_label}</p>")
    if task.due_date:
        lines.append(f"<p><strong>Scadenza:</strong> {task.due_date:%d-%m-%Y}</p>")
    if detail_url:
        lines.append(f'<p><a href="{detail_url}">Apri dettaglio attivita</a></p>')
    if task.description:
        desc = str(task.description).replace("\n", "<br>")
        lines.append(f"<p>{desc}</p>")
    return "\n".join(lines)


def _resolve_target_email(task: Task, explicit_email: str) -> str:
    email = (explicit_email or "").strip()
    if email:
        return email
    user = task.assigned_to
    if user and getattr(user, "email", ""):
        return user.email.strip()
    return ""


def _looks_like_local_mailbox_identity(target_email: str) -> bool:
    email = (target_email or "").strip().lower()
    if "@" not in email:
        return False
    domain = email.split("@", 1)[1]
    return domain.endswith(".local")


def _outlook_override_hint(target_email: str) -> str:
    if _looks_like_local_mailbox_identity(target_email):
        return (
            " L'indirizzo selezionato sembra un account interno '.local': nel campo "
            "'Email calendario Outlook' usa la mailbox Microsoft 365 reale dell'utente."
        )
    return (
        " Se serve, usa il campo 'Email calendario Outlook' per indicare la mailbox "
        "Microsoft 365 corretta dell'utente."
    )


def sync_task_outlook_event(
    *,
    request,
    task: Task,
    requested: bool,
    explicit_email: str,
) -> tuple[str, str]:
    """Crea/aggiorna/elimina l'evento Outlook per il task secondo la UI.

    Ritorna una tupla (level, message) con level in {"success","info","warning","error",""}.
    Level "" significa 'nessuna azione richiesta'.
    """
    existing = task.calendar_events.first()

    if not requested:
        if existing:
            try:
                if graph_ready() and existing.graph_event_id and existing.target_email:
                    delete_event(target_email=existing.target_email, event_id=existing.graph_event_id)
            except Exception as exc:
                logger.warning("Task outlook delete fallita (task=%s): %s", task.id, exc)
            existing.delete()
            return ("info", "Evento Outlook rimosso per questa attivita.")
        return ("", "")

    if not task.due_date:
        return ("warning", "Nessuna data fine impostata: impossibile creare l'evento Outlook.")

    if not graph_ready():
        return ("warning", "Integrazione Outlook non configurata sul server (GRAPH_* mancanti).")

    target_email = _resolve_target_email(task, explicit_email)
    if not target_email:
        return ("warning", "Nessuna email disponibile per il calendario Outlook (assegnatario o campo override).")

    subject = f"Task kickoff - {task.title}"
    body_html = _task_body_html(request, task)
    location = task.project.name if task.project_id else "Kickoff"
    transaction_id = _transaction_id(task)
    payload = build_event_payload(
        subject=subject,
        body_html=body_html,
        location_label=location,
        due_date=task.due_date,
        transaction_id=transaction_id,
        reminder_minutes_before_start=15,
    )

    try:
        if existing and existing.graph_event_id and existing.target_email == target_email:
            graph_event = update_event(
                target_email=target_email,
                event_id=existing.graph_event_id,
                payload=payload,
            )
            existing.due_date = task.due_date
            existing.subject = subject
            existing.graph_event_web_link = str(graph_event.get("webLink") or existing.graph_event_web_link)
            existing.save()
            return ("success", "Evento Outlook aggiornato.")

        if existing:
            # target email cambiato: elimina vecchio evento sul vecchio calendario
            try:
                if existing.graph_event_id and existing.target_email:
                    delete_event(target_email=existing.target_email, event_id=existing.graph_event_id)
            except Exception as exc:
                logger.warning("Task outlook delete su cambio target fallita (task=%s): %s", task.id, exc)
            existing.delete()

        graph_event = create_event(target_email=target_email, payload=payload)
        assignee_name = ""
        if task.assigned_to_id and task.assigned_to:
            assignee_name = task.assigned_to.get_full_name() or task.assigned_to.username
        try:
            TaskCalendarEvent.objects.create(
                task=task,
                source_key=_source_key(task),
                target_email=target_email,
                target_display_name=assignee_name,
                due_date=task.due_date,
                subject=subject,
                transaction_id=transaction_id,
                graph_event_id=str(graph_event.get("id") or ""),
                graph_event_web_link=str(graph_event.get("webLink") or ""),
                created_by=request.user if request and getattr(request.user, "is_authenticated", False) else None,
            )
        except IntegrityError:
            # race condition su source_key: aggiorna il record esistente
            rec = TaskCalendarEvent.objects.get(source_key=_source_key(task))
            rec.target_email = target_email
            rec.due_date = task.due_date
            rec.subject = subject
            rec.graph_event_id = str(graph_event.get("id") or "")
            rec.graph_event_web_link = str(graph_event.get("webLink") or "")
            rec.save()
        return ("success", f"Evento Outlook creato sul calendario di {target_email}.")
    except Exception as exc:
        logger.warning("Task outlook sync fallita (task=%s): %s", task.id, exc)
        exc_text = str(exc)
        low = exc_text.lower()
        if "is invalid" in low or "resourcenotfound" in low or "user not found" in low:
            return (
                "warning",
                (
                    f"Outlook: la mailbox '{target_email}' non e' un utente valido nel tenant Microsoft 365 "
                    "(alias, gruppo di distribuzione o mailbox condivisa non abilitata via Graph). "
                    "Imposta nel form un indirizzo di una cassetta personale con licenza, "
                    "oppure disattiva la sincronizzazione Outlook per questa attivita'."
                    f"{_outlook_override_hint(target_email)}"
                ),
            )
        if (
            "forbidden" in low
            or "accessdenied" in low
            or "access is denied" in low
            or "403" in low
        ):
            return (
                "warning",
                (
                    f"Outlook: l'app non riesce a scrivere sul calendario di '{target_email}'. "
                    "Verifica in Entra ID che Calendars.ReadWrite sia concesso come permesso "
                    "Application e che Exchange/Microsoft 365 non stia limitando quella mailbox "
                    "tramite policy o RBAC."
                    f"{_outlook_override_hint(target_email)}"
                ),
            )
        return ("warning", f"Outlook: {exc_text}")


def sync_task_portal_reminder(*, task: Task) -> None:
    """Allinea TaskReminder al valore corrente di task.reminder_portal_enabled e due_date.

    Rigenera il record se la data di fine o l'assegnatario sono cambiati. Non crea
    notifiche immediate: la materializzazione avviene via `send_task_reminders`.
    """
    # Rimuovi reminder passati non ancora fired se task cambia stato/date
    existing = task.portal_reminders.filter(fired=False)

    if not task.reminder_portal_enabled or not task.due_date or not task.assigned_to_id:
        existing.delete()
        return

    cfg = TaskImpostazioni.get_singleton()
    if not cfg.notifiche_scadenza_attive:
        existing.delete()
        return

    legacy_id = 0
    try:
        profile = task.assigned_to.profile
        legacy_id = int(profile.legacy_user_id or 0)
    except Exception:
        legacy_id = 0
    if not legacy_id:
        existing.delete()
        return

    days_preavviso = max(0, int(cfg.giorni_preavviso or 0))
    fire_at = task.due_date - timedelta(days=days_preavviso) if days_preavviso else task.due_date

    # rigenera se diverso dalle impostazioni correnti
    match = existing.filter(legacy_user_id=legacy_id, fire_at=fire_at).first()
    if match is None:
        existing.delete()
        TaskReminder.objects.create(
            task=task,
            legacy_user_id=legacy_id,
            fire_at=fire_at,
        )
