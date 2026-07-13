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


def meeting_url(meeting) -> str:
    """URL assoluto del dettaglio incontro sul portale, o '' se SITE_URL non è configurato."""
    from django.conf import settings
    from django.urls import reverse

    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    if not base:
        return ""
    try:
        path = reverse(
            "tasks:project_meeting_detail",
            kwargs={"project_id": meeting.project_id, "meeting_id": meeting.pk},
        )
    except Exception:
        return ""
    return f"{base}{path}"


def _facts(meeting) -> list[tuple[str, str]]:
    kickoff = getattr(meeting.project, "kickoff_number", "") or ""
    titolo = (meeting.titolo or "").strip()
    return [
        ("KICK-OFF", str(kickoff)),
        ("Incontro n.", str(meeting.numero)),
        ("Titolo", titolo or "—"),
        ("Data", _fmt_data(meeting) or "—"),
        ("Luogo", (meeting.luogo or "—").strip() or "—"),
    ]


def _sections_html_text(meeting, sections: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    html_parts: list[str] = []
    text_parts: list[str] = []
    for label, value in sections:
        value = (value or "").strip()
        if not value:
            continue
        html_parts.append(f"<h3 style='margin:18px 0 6px'>{label}</h3>")
        html_parts.append(text_to_html(value))
        text_parts.append(f"\n{label}\n{value}")
    return html_parts, text_parts


def _cta(meeting, label: str) -> str:
    url = meeting_url(meeting) or "#"
    return email_cta(label, url, note="Accedi al portale per i dettagli.")


def build_minute_email(meeting) -> tuple[str, str, str]:
    """Compone (subject, body_text, body_html_fragment) della minuta incontro."""
    kickoff = getattr(meeting.project, "kickoff_number", "") or ""
    titolo = (meeting.titolo or "").strip()
    subject = f"Minuta incontro — KICK-OFF {kickoff}"
    if titolo:
        subject += f": {titolo}"

    facts = _facts(meeting)
    sections = [
        ("Ordine del giorno", meeting.ordine_del_giorno),
        ("Verbale / Note", meeting.note),
        ("Problemi aperti", meeting.problemi_aperti),
        ("Next steps", meeting.next_steps),
    ]

    html_parts = [email_facts_table(facts)]
    text_parts = [f"{k}: {v}" for k, v in facts]
    sec_html, sec_text = _sections_html_text(meeting, sections)
    html_parts += sec_html
    text_parts += sec_text
    html_parts.append(_cta(meeting, "Apri incontro sul portale"))

    return subject, "\n".join(text_parts), "".join(html_parts)


def build_invite_email(meeting) -> tuple[str, str, str]:
    """Compone la CONVOCAZIONE (ordine del giorno, prima dell'incontro), senza verbale."""
    kickoff = getattr(meeting.project, "kickoff_number", "") or ""
    titolo = (meeting.titolo or "").strip()
    subject = f"Convocazione incontro — KICK-OFF {kickoff}"
    if titolo:
        subject += f": {titolo}"

    facts = _facts(meeting)
    sections = [("Ordine del giorno", meeting.ordine_del_giorno)]

    html_parts = [
        "<p>Sei convocato/a al seguente incontro di avvio commessa.</p>",
        email_facts_table(facts),
    ]
    text_parts = ["Sei convocato/a al seguente incontro."] + [f"{k}: {v}" for k, v in facts]
    sec_html, sec_text = _sections_html_text(meeting, sections)
    html_parts += sec_html
    text_parts += sec_text
    html_parts.append(_cta(meeting, "Apri incontro sul portale"))

    return subject, "\n".join(text_parts), "".join(html_parts)


def build_minute_pdf(meeting) -> bytes:
    """Genera un PDF A4 della minuta con reportlab (già in requirements)."""
    import io

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title="Minuta incontro KICK-OFF",
    )
    styles = getSampleStyleSheet()
    h_style = ParagraphStyle("H", parent=styles["Heading2"], spaceBefore=10, spaceAfter=4)
    body_style = ParagraphStyle("B", parent=styles["BodyText"], alignment=TA_LEFT, leading=14)

    kickoff = getattr(meeting.project, "kickoff_number", "") or ""
    story = [Paragraph(f"Minuta incontro — KICK-OFF {kickoff}", styles["Title"]), Spacer(1, 6)]

    fact_rows = [[k, v] for k, v in _facts(meeting)]
    table = Table(fact_rows, colWidths=[40 * mm, 130 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story += [table, Spacer(1, 8)]

    for label, value in [
        ("Ordine del giorno", meeting.ordine_del_giorno),
        ("Verbale / Note", meeting.note),
        ("Problemi aperti", meeting.problemi_aperti),
        ("Next steps", meeting.next_steps),
    ]:
        value = (value or "").strip()
        if not value:
            continue
        story.append(Paragraph(label, h_style))
        for line in value.splitlines() or [value]:
            safe = (line or " ").replace("&", "&amp;").replace("<", "&lt;")
            story.append(Paragraph(safe, body_style))

    doc.build(story)
    return buffer.getvalue()


def build_meeting_ics(meeting) -> bytes:
    """Genera un invito calendario .ics (VEVENT) per l'incontro."""
    from datetime import datetime, timedelta

    from django.utils import timezone

    def _dt(value) -> datetime | None:
        if isinstance(value, datetime):
            return value
        return None

    # DTSTART/DTEND: se c'è l'ora → evento a orario, altrimenti giornata intera (VALUE=DATE)
    data = meeting.data
    ora = meeting.ora
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//NOVICROM HUB//KICK-OFF//IT",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:kickoff-meeting-{meeting.pk}@novicrom-hub",
        f"DTSTAMP:{timezone.now().strftime('%Y%m%dT%H%M%SZ')}",
    ]
    if ora is not None and hasattr(data, "strftime"):
        start = f"{data.strftime('%Y%m%d')}T{ora.strftime('%H%M%S')}"
        try:
            end_dt = datetime.combine(data, ora) + timedelta(hours=1)
            end = end_dt.strftime("%Y%m%dT%H%M%S")
        except Exception:
            end = start
        lines += [f"DTSTART:{start}", f"DTEND:{end}"]
    elif hasattr(data, "strftime"):
        lines += [f"DTSTART;VALUE=DATE:{data.strftime('%Y%m%d')}"]
    else:
        lines += [f"DTSTART;VALUE=DATE:{str(data).replace('-', '')}"]

    kickoff = getattr(meeting.project, "kickoff_number", "") or ""
    summary = f"KICK-OFF {kickoff} — Incontro {meeting.numero}"
    if (meeting.titolo or "").strip():
        summary += f": {meeting.titolo.strip()}"
    lines += [
        f"SUMMARY:{summary}",
        f"LOCATION:{(meeting.luogo or '').strip()}",
        f"DESCRIPTION:{(meeting.ordine_del_giorno or '').strip().replace(chr(10), ' ')}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def _cc_management(meeting, exclude: list[str]) -> list[str]:
    """Email di PM e capo commessa del progetto, escludendo chi è già destinatario."""
    cc: list[str] = []
    project = meeting.project
    for user in (getattr(project, "project_manager", None), getattr(project, "capo_commessa", None)):
        if user is None:
            continue
        email = (getattr(user, "email", "") or "").strip()
        if email and email not in exclude and email not in cc:
            cc.append(email)
    return cc


def send_meeting_minute(meeting, *, sent_by=None, with_pdf: bool = True) -> dict:
    """Invia la minuta a tutti i partecipanti (CC a PM/capo commessa, PDF allegato).

    Ritorna esito senza sollevare per casi previsti.
    """
    recipients = meeting.get_all_attendee_emails()
    if not recipients:
        return {"sent": False, "recipients": [], "cc": [], "reason": "no_recipients"}

    from core.email_utils import send_hub_mail

    subject, body_text, body_html = build_minute_email(meeting)
    cc = _cc_management(meeting, exclude=recipients)
    attachments = None
    if with_pdf:
        try:
            pdf = build_minute_pdf(meeting)
            fname = f"minuta-kickoff-{getattr(meeting.project, 'kickoff_number', '') or meeting.pk}-inc{meeting.numero}.pdf"
            attachments = [(fname, pdf, "application/pdf")]
        except Exception:
            attachments = None  # PDF opzionale: un errore non blocca l'invio della mail

    sent_count = send_hub_mail(
        subject,
        body_text,
        recipients,
        cc=cc,
        title=f"Minuta incontro KICK-OFF {getattr(meeting.project, 'kickoff_number', '') or ''}",
        email_type="VRF - KICK-OFF",
        body_html_fragment=body_html,
        attachments=attachments,
        fail_silently=False,
    )
    if not sent_count:
        return {"sent": False, "recipients": recipients, "cc": cc, "reason": "send_error"}
    return {"sent": True, "recipients": recipients, "cc": cc, "reason": ""}


def send_meeting_invite(meeting, *, sent_by=None) -> dict:
    """Invia la convocazione (ordine del giorno) ai partecipanti."""
    recipients = meeting.get_all_attendee_emails()
    if not recipients:
        return {"sent": False, "recipients": [], "cc": [], "reason": "no_recipients"}

    from core.email_utils import send_hub_mail

    subject, body_text, body_html = build_invite_email(meeting)
    cc = _cc_management(meeting, exclude=recipients)
    attachments = None
    try:
        ics = build_meeting_ics(meeting)
        attachments = [("convocazione-incontro.ics", ics, "text/calendar")]
    except Exception:
        attachments = None  # .ics opzionale: un errore non blocca l'invio
    sent_count = send_hub_mail(
        subject,
        body_text,
        recipients,
        cc=cc,
        title=f"Convocazione incontro KICK-OFF {getattr(meeting.project, 'kickoff_number', '') or ''}",
        email_type="VRF - KICK-OFF",
        body_html_fragment=body_html,
        attachments=attachments,
        fail_silently=False,
    )
    if not sent_count:
        return {"sent": False, "recipients": recipients, "cc": cc, "reason": "send_error"}
    return {"sent": True, "recipients": recipients, "cc": cc, "reason": ""}


def create_tasks_from_next_steps(meeting) -> int:
    """Crea un task KICK-OFF per ogni riga non vuota dei next steps (dedup per titolo+incontro)."""
    from tasks.models import Task, TaskPriority, TaskStatus

    creator = getattr(meeting, "created_by", None)
    if creator is None:
        return 0

    marker = f"#{meeting.numero}"
    created = 0
    for raw in (meeting.next_steps or "").splitlines():
        title = raw.strip()[:200]
        if not title:
            continue
        already = Task.objects.filter(
            project=meeting.project, title=title, description__contains=marker
        ).exists()
        if already:
            continue
        Task.objects.create(
            title=title,
            project=meeting.project,
            priority=TaskPriority.MEDIUM,
            status=TaskStatus.TODO,
            created_by=creator,
            description=f"Dall'incontro {marker} ({_fmt(meeting.data, '%d-%m-%Y')})",
        )
        created += 1
    return created
