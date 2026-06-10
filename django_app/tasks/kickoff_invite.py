"""Integrazione Outlook Calendar per la creazione di un kickoff (Project).

Invia un invito calendario ai membri del team (PM, Capocommessa, Programmatore)
al momento della creazione del kickoff. L'invio è non-bloccante: errori Graph
producono un warning ma non impediscono il salvataggio del progetto.
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
    graph_ready,
)

logger = logging.getLogger(__name__)

DEFAULT_DURATION_MINUTES = 60
DEFAULT_START_HOUR = 9


def _transaction_id(project) -> str:
    return str(uuid5(NAMESPACE_URL, f"https://novicrom.local/tasks/kickoff/{project.id}/invite"))


def _collect_team_emails(project) -> list[str]:
    """Raccoglie le email dei membri del team di progetto."""
    emails: list[str] = []
    for user in (project.project_manager, project.capo_commessa, project.programmer):
        if user is not None:
            email = (user.email or "").strip()
            if email and email not in emails:
                emails.append(email)
    return emails


def _resolve_organizer_email(project, request) -> str:
    """Email organizzatore: utente che crea → created_by → primo membro team."""
    if request and getattr(request, "user", None) and request.user.is_authenticated:
        email = (request.user.email or "").strip()
        if email:
            return email
    if project.created_by_id and project.created_by:
        email = (project.created_by.email or "").strip()
        if email:
            return email
    team_emails = _collect_team_emails(project)
    return team_emails[0] if team_emails else ""


def _build_attendees(project) -> list[dict]:
    return [
        {
            "emailAddress": {"address": email, "name": email},
            "type": "required",
        }
        for email in _collect_team_emails(project)
    ]


def _kickoff_body_html(request, project, kickoff_date, kickoff_location: str) -> str:
    try:
        gantt_url = request.build_absolute_uri(
            reverse("tasks:project_gantt", args=[project.id])
        ) if request else ""
    except Exception:
        gantt_url = ""

    lines = [
        f"<p><strong>Kickoff:</strong> {escape(project.name)}</p>",
    ]
    if project.client_name:
        lines.append(f"<p><strong>Cliente:</strong> {escape(project.client_name)}</p>")
    if project.part_number:
        pn = escape(project.part_number)
        if project.revisione:
            pn += f" Rev. {escape(project.revisione)}"
        if project.versione:
            pn += f" Ver. {escape(project.versione)}"
        lines.append(f"<p><strong>P/N:</strong> {pn}</p>")
    if project.description:
        desc = str(project.description).replace("\n", "<br>")
        lines.append(f"<p><strong>Descrizione:</strong><br>{desc}</p>")

    team_parts = []
    if project.project_manager:
        team_parts.append(f"PM: {escape(project.project_manager.get_full_name() or project.project_manager.username)}")
    if project.capo_commessa:
        team_parts.append(f"Capocommessa: {escape(project.capo_commessa.get_full_name() or project.capo_commessa.username)}")
    if project.programmer:
        team_parts.append(f"Programmatore: {escape(project.programmer.get_full_name() or project.programmer.username)}")
    if team_parts:
        lines.append("<p><strong>Team:</strong> " + " — ".join(team_parts) + "</p>")

    if kickoff_location:
        lines.append(f"<p><strong>Luogo:</strong> {escape(kickoff_location)}</p>")

    if gantt_url:
        lines.append(f'<p><a href="{gantt_url}">Apri kickoff sul portale</a></p>')
    return "\n".join(lines)


def sync_kickoff_calendar_invite(
    *,
    request,
    project,
    kickoff_date,
    kickoff_time=None,
    kickoff_location: str = "",
    organizer_email_override: str = "",
) -> tuple[str, str]:
    """Invia un invito Outlook Calendar al team al momento della creazione del kickoff.

    Parametri:
        kickoff_date: data della riunione di kickoff (date)
        kickoff_time: ora della riunione (time, opzionale — default 09:00)
        kickoff_location: luogo della riunione
        organizer_email_override: email organizzatore override (opzionale)

    Ritorna (level, message) con level in {"success","info","warning","error",""}.
    """
    if not graph_ready():
        return ("warning", "Integrazione Outlook non configurata sul server (GRAPH_* mancanti).")

    # Risolvi organizzatore
    organizer_email = (organizer_email_override or "").strip()
    if not organizer_email:
        organizer_email = _resolve_organizer_email(project, request)
    if not organizer_email:
        return (
            "warning",
            "Nessuna email disponibile per l'organizzatore: imposta un'email sull'account utente.",
        )

    # Costruisci start/end
    ora: time = kickoff_time or time(DEFAULT_START_HOUR, 0)
    start = datetime.combine(kickoff_date, ora)
    end = start + timedelta(minutes=DEFAULT_DURATION_MINUTES)

    subject = f"KICK-OFF {project.name}"
    if project.client_name:
        subject = f"{subject} — {project.client_name}"

    body_html = _kickoff_body_html(request, project, kickoff_date, kickoff_location)
    location = kickoff_location or project.client_name or project.name
    transaction_id = _transaction_id(project)

    payload = build_event_payload(
        subject=subject,
        body_html=body_html,
        location_label=location,
        due_date=kickoff_date,
        transaction_id=transaction_id,
        reminder_minutes_before_start=15,
        start_hour=start.hour,
        duration_minutes=DEFAULT_DURATION_MINUTES,
    )
    tz = "W. Europe Standard Time"
    payload["start"] = {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tz}
    payload["end"]   = {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"),   "timeZone": tz}
    payload["isOnlineMeeting"] = False

    attendees = _build_attendees(project)
    if attendees:
        payload["attendees"] = attendees

    try:
        create_event(target_email=organizer_email, payload=payload)
        n_att = len(attendees)
        return ("success", f"Invito kickoff inviato su Outlook ({n_att} partecipanti).")
    except Exception as exc:
        logger.warning("Kickoff calendar invite fallita (project=%s): %s", project.id, exc)
        exc_text = str(exc)
        low = exc_text.lower()
        if "is invalid" in low or "resourcenotfound" in low or "user not found" in low:
            return (
                "warning",
                f"Outlook: la mailbox '{organizer_email}' non è valida nel tenant M365. "
                "Verifica che l'email dell'organizzatore sia una casella personale con licenza.",
            )
        if "forbidden" in low or "accessdenied" in low or "403" in low:
            return (
                "warning",
                f"Outlook: l'app non ha accesso al calendario di '{organizer_email}'. "
                "Verifica che Calendars.ReadWrite sia abilitato come Application permission in Entra ID.",
            )
        return ("warning", f"Outlook: {exc_text}")
