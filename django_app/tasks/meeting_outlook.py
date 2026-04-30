"""Integrazione Outlook Calendar per KickoffMeeting.

Crea/aggiorna/elimina l'evento calendario sul profilo dell'organizzatore
e aggiunge tutti i partecipanti (utenti portale + email extra) come attendees.
Gli errori Graph non sono bloccanti: l'incontro resta salvato con un warning.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from uuid import uuid5, NAMESPACE_URL

from django.urls import reverse
from django.utils.html import escape

from core.outlook_calendar import (
    build_event_payload,
    create_event,
    delete_event,
    graph_ready,
    update_event,
)

logger = logging.getLogger(__name__)

DEFAULT_DURATION_MINUTES = 60
DEFAULT_START_HOUR = 9


def _transaction_id(meeting) -> str:
    return str(uuid5(NAMESPACE_URL, f"https://novicrom.local/tasks/meetings/{meeting.id}/calendar"))


def _resolve_organizer_email(meeting, request) -> str:
    """Email sull'organizzatore: campo override → utente che salva → created_by."""
    explicit = (meeting.outlook_organizer_email or "").strip()
    if explicit:
        return explicit
    if request and getattr(request, "user", None) and request.user.is_authenticated:
        email = (request.user.email or "").strip()
        if email:
            return email
    if meeting.created_by_id and meeting.created_by:
        email = (meeting.created_by.email or "").strip()
        if email:
            return email
    return ""


def _build_attendees(meeting) -> list[dict]:
    return [
        {
            "emailAddress": {"address": email, "name": email},
            "type": "required",
        }
        for email in meeting.get_all_attendee_emails()
    ]


def _agenda_items_html(meeting) -> str:
    items = meeting.agenda_items or []
    if not isinstance(items, list):
        return ""

    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("titolo", "")).strip()
        if not title:
            continue

        parts = [f"<strong>{escape(title)}</strong>"]
        if item.get("issue_id"):
            parts.append(" <em>(problema aperto)</em>")
        task_label = str(item.get("task_label", "")).strip()
        if task_label:
            parts.append(f" <em>({escape(task_label)})</em>")

        nota = str(item.get("nota", "")).strip()
        if nota:
            parts.append("<br>" + escape(nota).replace("\n", "<br>"))

        custom_fields = item.get("custom_fields") or []
        if isinstance(custom_fields, list):
            custom_rows = []
            for field in custom_fields:
                if not isinstance(field, dict):
                    continue
                label = str(field.get("label", "")).strip()
                value = str(field.get("value", "")).strip()
                if label and value:
                    custom_rows.append(
                        f"<li><strong>{escape(label)}:</strong> {escape(value)}</li>"
                    )
            if custom_rows:
                parts.append("<ul>" + "".join(custom_rows) + "</ul>")

        rows.append("<li>" + "".join(parts) + "</li>")

    if not rows:
        return ""
    return "<ol>" + "".join(rows) + "</ol>"


def _meeting_body_html(request, meeting) -> str:
    try:
        detail_url = request.build_absolute_uri(
            reverse("tasks:project_meeting_detail", args=[meeting.project_id, meeting.id])
        ) if request else ""
    except Exception:
        detail_url = ""

    lines = [
        f"<p><strong>Kickoff:</strong> {meeting.project.name}</p>",
        f"<p><strong>Incontro:</strong> {meeting.numero}"
        + (f" — {meeting.titolo}" if meeting.titolo else "") + "</p>",
    ]
    if meeting.luogo:
        lines.append(f"<p><strong>Luogo:</strong> {meeting.luogo}</p>")
    agenda_html = _agenda_items_html(meeting)
    if agenda_html:
        lines.append(f"<p><strong>Ordine del giorno:</strong></p>{agenda_html}")
    if meeting.ordine_del_giorno:
        odg = str(meeting.ordine_del_giorno).replace("\n", "<br>")
        label = "Note aggiuntive ordine del giorno" if agenda_html else "Ordine del giorno"
        lines.append(f"<p><strong>{label}:</strong><br>{odg}</p>")
    if detail_url:
        lines.append(f'<p><a href="{detail_url}">Apri verbale incontro sul portale</a></p>')
    return "\n".join(lines)


def _meeting_start_end(meeting) -> tuple[datetime, datetime]:
    ora: time = meeting.ora or time(DEFAULT_START_HOUR, 0)
    start = datetime.combine(meeting.data, ora)
    end = start + timedelta(minutes=DEFAULT_DURATION_MINUTES)
    return start, end


def sync_meeting_outlook_event(*, request, meeting) -> tuple[str, str]:
    """Crea/aggiorna/elimina l'evento Outlook per l'incontro.

    Ritorna (level, message) con level in {"success","info","warning","error",""}.
    """
    from .models import KickoffMeeting  # import locale per evitare circolari

    # ── cancella evento esistente se sync disattivato ──────────────────────
    if not meeting.sync_outlook:
        if meeting.outlook_event_id:
            organizer = (meeting.outlook_organizer_email or "").strip()
            if not organizer and meeting.created_by_id and meeting.created_by:
                organizer = (meeting.created_by.email or "").strip()
            try:
                if graph_ready() and organizer:
                    delete_event(target_email=organizer, event_id=meeting.outlook_event_id)
            except Exception as exc:
                logger.warning("Meeting outlook delete fallita (meeting=%s): %s", meeting.id, exc)
            KickoffMeeting.objects.filter(pk=meeting.pk).update(
                outlook_event_id="", outlook_event_web_link=""
            )
            return ("info", "Evento Outlook rimosso per questo incontro.")
        return ("", "")

    # ── pre-requisiti ──────────────────────────────────────────────────────
    if not graph_ready():
        return ("warning", "Integrazione Outlook non configurata sul server (GRAPH_* mancanti).")

    organizer_email = _resolve_organizer_email(meeting, request)
    if not organizer_email:
        return (
            "warning",
            "Nessuna email disponibile per l'organizzatore: imposta un'email sull'account utente "
            "o usa il campo 'Email organizzatore' nel form.",
        )

    # ── costruisci payload ─────────────────────────────────────────────────
    start, end = _meeting_start_end(meeting)
    subject = f"Incontro {meeting.numero} — {meeting.project.name}"
    if meeting.titolo:
        subject = f"{subject}: {meeting.titolo}"
    body_html = _meeting_body_html(request, meeting)
    location = meeting.luogo or meeting.project.name
    transaction_id = _transaction_id(meeting)

    payload = build_event_payload(
        subject=subject,
        body_html=body_html,
        location_label=location,
        due_date=meeting.data,
        transaction_id=transaction_id,
        reminder_minutes_before_start=15,
        start_hour=start.hour,
        duration_minutes=DEFAULT_DURATION_MINUTES,
    )
    # Sovrascrive start/end con l'ora esatta dell'incontro
    tz = "W. Europe Standard Time"
    payload["start"] = {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tz}
    payload["end"]   = {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"),   "timeZone": tz}
    payload["isOnlineMeeting"] = False

    attendees = _build_attendees(meeting)
    if attendees:
        payload["attendees"] = attendees

    # ── crea o aggiorna ────────────────────────────────────────────────────
    try:
        existing_id = meeting.outlook_event_id
        if existing_id:
            graph_event = update_event(
                target_email=organizer_email,
                event_id=existing_id,
                payload=payload,
            )
            web_link = str(graph_event.get("webLink") or meeting.outlook_event_web_link)
            KickoffMeeting.objects.filter(pk=meeting.pk).update(
                outlook_event_web_link=web_link,
                outlook_organizer_email=organizer_email,
            )
            meeting.outlook_event_web_link = web_link
            n_att = len(attendees)
            return ("success", f"Evento Outlook aggiornato ({n_att} partecipanti).")

        graph_event = create_event(target_email=organizer_email, payload=payload)
        event_id = str(graph_event.get("id") or "")
        web_link = str(graph_event.get("webLink") or "")
        KickoffMeeting.objects.filter(pk=meeting.pk).update(
            outlook_event_id=event_id,
            outlook_event_web_link=web_link,
            outlook_organizer_email=organizer_email,
        )
        meeting.outlook_event_id = event_id
        meeting.outlook_event_web_link = web_link
        n_att = len(attendees)
        return ("success", f"Evento Outlook creato sul calendario di {organizer_email} ({n_att} partecipanti).")

    except Exception as exc:
        logger.warning("Meeting outlook sync fallita (meeting=%s): %s", meeting.id, exc)
        exc_text = str(exc)
        low = exc_text.lower()
        if "is invalid" in low or "resourcenotfound" in low or "user not found" in low:
            return (
                "warning",
                f"Outlook: la mailbox '{organizer_email}' non è valida nel tenant M365. "
                "Usa il campo 'Email organizzatore' per specificare una casella personale con licenza.",
            )
        if "forbidden" in low or "accessdenied" in low or "403" in low:
            return (
                "warning",
                f"Outlook: l'app non ha accesso al calendario di '{organizer_email}'. "
                "Verifica che Calendars.ReadWrite sia abilitato come Application permission in Entra ID.",
            )
        return ("warning", f"Outlook: {exc_text}")
