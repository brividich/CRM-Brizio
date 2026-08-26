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
        ("Stato", meeting.get_stato_display()),
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


def _agenda_text(meeting) -> str:
    """Ordine del giorno strutturato reso come testo.

    I punti vivono in `agenda_items` (JSON) dal redesign dell'agenda: senza
    questa resa la minuta inviata ai partecipanti conteneva solo il vecchio
    campo testo libero, quasi sempre vuoto.
    """
    items = meeting.agenda_items or []
    if not isinstance(items, list):
        return ""
    lines: list[str] = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        titolo = str(item.get("titolo", "")).strip()
        if not titolo:
            continue
        marker = "[x]" if item.get("done") else "[ ]"
        lines.append(f"{idx}. {marker} {titolo}")
        nota = str(item.get("nota", "")).strip()
        if nota:
            lines.append(f"    {nota}")
        for custom_field in item.get("custom_fields") or []:
            if not isinstance(custom_field, dict):
                continue
            label = str(custom_field.get("label", "")).strip()
            value = str(custom_field.get("value", "")).strip()
            if label and value:
                lines.append(f"    {label}: {value}")
    return "\n".join(lines)


def _issues_text(meeting) -> str:
    """Problemi sollevati o chiusi in questo incontro, resi come testo."""
    from django.db.models import Q

    from tasks.models import MeetingIssue

    qs = (
        MeetingIssue.objects.filter(
            Q(source_meeting=meeting) | Q(resolution_meeting=meeting)
        )
        .select_related("assigned_to")
        .distinct()
        .order_by("status", "due_date", "id")
    )
    lines: list[str] = []
    for issue in qs:
        parts = [issue.get_status_display()]
        if issue.assigned_to_id:
            owner = issue.assigned_to.get_full_name() or issue.assigned_to.username
            parts.append(owner)
        if issue.due_date:
            parts.append(f"scadenza {_fmt(issue.due_date, '%d/%m/%Y')}")
        lines.append(f"- {issue.title} ({', '.join(parts)})")
        if issue.description:
            lines.append(f"    {issue.description.strip()}")
        if issue.resolution_note:
            lines.append(f"    Risoluzione: {issue.resolution_note.strip()}")
    return "\n".join(lines)


def _partecipanti_text(meeting) -> str:
    """Elenco dei partecipanti (utenti portale + email esterne)."""
    names = [
        (user.get_full_name() or user.username)
        for user in meeting.partecipanti_utenti.all()
    ]
    extra = [
        line.strip()
        for line in (meeting.partecipanti_email_extra or "").splitlines()
        if line.strip()
    ]
    lines = [f"- {n}" for n in names] + [f"- {e}" for e in extra]
    note = (meeting.partecipanti_testo or "").strip()
    if note:
        lines.append(note)
    return "\n".join(lines)


def _minute_sections(meeting) -> list[tuple[str, str]]:
    """Sezioni della minuta, sorgente unica per email e PDF (evita che divergano)."""
    return [
        ("Partecipanti", _partecipanti_text(meeting)),
        ("Ordine del giorno", _agenda_text(meeting) or meeting.ordine_del_giorno),
        ("Verbale / Note", meeting.note),
        ("Problemi", _issues_text(meeting) or meeting.problemi_aperti),
        ("Next steps", meeting.next_steps),
    ]


def _invite_sections(meeting) -> list[tuple[str, str]]:
    """Sezioni della convocazione: ordine del giorno e invitati, nessun verbale."""
    return [
        ("Partecipanti convocati", _partecipanti_text(meeting)),
        ("Ordine del giorno", _agenda_text(meeting) or meeting.ordine_del_giorno),
    ]


def build_minute_email(meeting) -> tuple[str, str, str]:
    """Compone (subject, body_text, body_html_fragment) della minuta incontro."""
    kickoff = getattr(meeting.project, "kickoff_number", "") or ""
    titolo = (meeting.titolo or "").strip()
    subject = f"Minuta incontro — KICK-OFF {kickoff}"
    if titolo:
        subject += f": {titolo}"

    facts = _facts(meeting)
    sections = _minute_sections(meeting)

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
    sections = _invite_sections(meeting)

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
    """Genera un PDF A4 della minuta col template PDF standard del portale."""
    import io
    from html import escape

    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    from core.pdf import (
        PdfTheme,
        build_styles,
        data_table,
        header_footer_callback,
        make_document,
        section_heading,
    )

    theme = PdfTheme.from_branding()
    styles = build_styles(theme)
    buffer = io.BytesIO()

    kickoff = str(getattr(meeting.project, "kickoff_number", "") or "").strip()
    doc = make_document(buffer, title=f"Minuta incontro KICK-OFF {kickoff}".strip())
    content_width = doc.pagesize[0] - doc.leftMargin - doc.rightMargin

    story: list = [
        Paragraph(f"Minuta incontro — KICK-OFF {kickoff}".strip(" —"), styles["title"]),
        Spacer(1, 3 * mm),
    ]

    fact_rows = [
        [
            Paragraph(escape(str(k)), styles["label"]),
            Paragraph(escape(str(v)).replace("\n", "<br/>"), styles["value"]),
        ]
        for k, v in _facts(meeting)
    ]
    if fact_rows:
        story.append(
            data_table(
                fact_rows,
                theme,
                col_widths=[45 * mm, content_width - 45 * mm],
                header=False,
                extra_style=[("VALIGN", (0, 0), (-1, -1), "TOP")],
            )
        )
        story.append(Spacer(1, 5 * mm))

    for label, value in _minute_sections(meeting):
        value = (value or "").strip()
        if not value:
            continue
        story.extend(section_heading(label, theme, styles))
        for line in value.splitlines() or [value]:
            story.append(Paragraph(escape(line or " "), styles["body"]))

    draw = header_footer_callback(
        theme, title="MINUTA INCONTRO", subtitle=f"KICK-OFF {kickoff}".strip(),
    )
    doc.build(story, onFirstPage=draw, onLaterPages=draw)
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
        f"DESCRIPTION:{(_agenda_text(meeting) or meeting.ordine_del_giorno or '').strip().replace(chr(10), ' ')}",
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
