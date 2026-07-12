from __future__ import annotations

from core.email_utils import (
    email_cta,
    email_facts_table,
    text_to_html,
)


def _fmt(value, fmt: str) -> str:
    """Formatta un date/time; se il valore è già stringa (o None) lo restituisce grezzo."""
    if not value:
        return ""
    strftime = getattr(value, "strftime", None)
    return strftime(fmt) if callable(strftime) else str(value)


def _fmt_data(meeting) -> str:
    parts = [_fmt(meeting.data, "%d/%m/%Y")]
    if meeting.ora:
        parts.append(_fmt(meeting.ora, "%H:%M"))
    return " ".join(p for p in parts if p).strip()


def build_minute_email(meeting) -> tuple[str, str, str]:
    """Compone (subject, body_text, body_html_fragment) della minuta incontro."""
    kickoff = getattr(meeting.project, "kickoff_number", "") or ""
    titolo = (meeting.titolo or "").strip()
    subject = f"Minuta incontro — KICK-OFF {kickoff}"
    if titolo:
        subject += f": {titolo}"

    facts = [
        ("KICK-OFF", str(kickoff)),
        ("Incontro n.", str(meeting.numero)),
        ("Titolo", titolo or "—"),
        ("Data", _fmt_data(meeting) or "—"),
        ("Luogo", (meeting.luogo or "—").strip() or "—"),
    ]

    sections: list[tuple[str, str]] = [
        ("Ordine del giorno", meeting.ordine_del_giorno),
        ("Verbale / Note", meeting.note),
        ("Problemi aperti", meeting.problemi_aperti),
        ("Next steps", meeting.next_steps),
    ]

    html_parts = [email_facts_table(facts)]
    text_parts = [f"{k}: {v}" for k, v in facts]
    for label, value in sections:
        value = (value or "").strip()
        if not value:
            continue
        html_parts.append(f"<h3 style='margin:18px 0 6px'>{label}</h3>")
        html_parts.append(text_to_html(value))
        text_parts.append(f"\n{label}\n{value}")

    html_parts.append(
        email_cta("Apri incontro sul portale", "#", note="Accedi al portale per i dettagli.")
    )

    body_html = "".join(html_parts)
    body_text = "\n".join(text_parts)
    return subject, body_text, body_html


def send_meeting_minute(meeting, *, sent_by=None) -> dict:
    """Invia la minuta a tutti i partecipanti. Ritorna esito senza sollevare per casi previsti."""
    recipients = meeting.get_all_attendee_emails()
    if not recipients:
        return {"sent": False, "recipients": [], "reason": "no_recipients"}

    from core.email_utils import send_hub_mail

    subject, body_text, body_html = build_minute_email(meeting)
    sent_count = send_hub_mail(
        subject,
        body_text,
        recipients,
        title=f"Minuta incontro KICK-OFF {getattr(meeting.project, 'kickoff_number', '') or ''}",
        email_type="VRF - KICK-OFF",
        body_html_fragment=body_html,
        fail_silently=False,
    )
    if not sent_count:
        return {"sent": False, "recipients": recipients, "reason": "send_error"}
    return {"sent": True, "recipients": recipients, "reason": ""}
