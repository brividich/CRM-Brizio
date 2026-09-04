"""Task periodici django-q2 per il modulo tasks / KICK-OFF.

Registrati via automazioni.schedules + setup_q_schedules.
"""
from __future__ import annotations

import logging

from automazioni.system_runlog import system_job_run

logger = logging.getLogger("tasks.tasks")


@system_job_run("tasks_send_reminders")
def run_send_task_reminders(*, limit: int = 0) -> dict:
    """Materializza i TaskReminder in scadenza come notifiche portale.

    Wrapper schedulabile del management command `send_task_reminders`: porta i
    promemoria di scadenza KICK-OFF nello scheduler django-q centralizzato (con
    run-log e monitoraggio uniformi) invece di dipendere da un Task di Windows
    separato. Idempotente a livello di comando (un TaskReminder già `fired` non
    viene rielaborato). Ritorna {"limit", "output"} per il run-log.
    """
    from io import StringIO

    from django.core.management import call_command

    buf = StringIO()
    call_command("send_task_reminders", limit=limit, stdout=buf)
    out = buf.getvalue().strip()
    if out:
        logger.info("run_send_task_reminders: %s", out.replace("\n", " | "))
    return {"limit": limit, "output": out[:500]}


@system_job_run("tasks_meetings_digest")
def run_meetings_digest(**kwargs) -> dict:
    """Digest giornaliero unico per gli incontri KICK-OFF.

    Sostituisce i due job separati "domani hai un incontro" e "problemi aperti
    scaduti": quando ricorrono lo stesso giorno per la stessa persona, li unisce
    in una sola email invece di due. Il promemoria incontro gira ogni giorno
    (copre il caso `sync_outlook` spento, che non ha un proprio promemoria
    calendario); il sollecito problemi scaduti resta al lunedi, la stessa
    cadenza del vecchio job settimanale che sostituisce — spostarlo a ogni
    giorno risollecerebbe la stessa persona 7 volte più spesso. Le notifiche
    in-app restano una per evento (l'inbox del portale le aggrega già).
    Idempotente sugli incontri (`reminder_sent_at`); il sollecito problemi si
    basa sullo stato corrente (nessun flag: un problema chiuso non è più
    sollecitato).
    """
    from collections import defaultdict
    from datetime import timedelta

    from django.utils import timezone

    from core.email_utils import send_hub_mail
    from core.notifiche import invia_notifica, legacy_user_ids_for_email
    from tasks.minute_email import meeting_url
    from tasks.models import (
        KickoffMeeting,
        MeetingActionItem,
        MeetingActionStatus,
        MeetingIssue,
        MeetingIssueStatus,
        MeetingStatus,
    )

    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)
    include_overdue_issues = today.weekday() == 0  # lunedi

    by_email: dict[str, dict] = defaultdict(lambda: {"meetings": [], "issues": [], "actions": []})

    meetings = list(
        KickoffMeeting.objects.filter(
            stato=MeetingStatus.PIANIFICATO,
            data=tomorrow,
            reminder_sent_at__isnull=True,
        )
        .select_related("project")
        .prefetch_related("partecipanti_utenti")
    )
    for meeting in meetings:
        label = meeting.titolo or f"Incontro {meeting.numero}"
        recipients: set[str] = set()
        for user in meeting.partecipanti_utenti.all():
            profile = getattr(user, "profile", None)
            legacy_id = getattr(profile, "legacy_user_id", None) if profile else None
            if legacy_id:
                try:
                    invia_notifica(
                        int(legacy_id),
                        "generico",
                        f'Domani hai l\'incontro "{label}" [{getattr(meeting.project, "name", "")}].'[:500],
                        meeting_url(meeting),
                    )
                except (TypeError, ValueError):
                    logger.exception("run_meetings_digest: legacy_id non valido per user=%s", user.pk)
            email = (getattr(user, "email", "") or "").strip()
            if email:
                recipients.add(email)
        for line in (meeting.partecipanti_email_extra or "").splitlines():
            email = line.strip()
            if email:
                recipients.add(email)
        for email in recipients:
            by_email[email]["meetings"].append(meeting)

    issues: list = []
    if include_overdue_issues:
        issues = list(
            MeetingIssue.objects.filter(
                status=MeetingIssueStatus.OPEN,
                due_date__isnull=False,
                due_date__lt=today,
                assigned_to__isnull=False,
            ).select_related("assigned_to", "project")
        )
        by_issue_email: dict[str, list] = defaultdict(list)
        for issue in issues:
            email = (getattr(issue.assigned_to, "email", "") or "").strip()
            if email:
                by_issue_email[email].append(issue)
                by_email[email]["issues"].append(issue)
        # Le azioni scadute seguono la stessa cadenza dei problemi: sono lo
        # stesso genere di sollecito, e finiscono nella stessa email.
        actions = list(
            MeetingActionItem.objects.filter(
                status=MeetingActionStatus.OPEN,
                due_date__isnull=False,
                due_date__lt=today,
                assigned_to__isnull=False,
            ).select_related("assigned_to", "project")
        )
        for action in actions:
            email = (getattr(action.assigned_to, "email", "") or "").strip()
            if email:
                by_email[email]["actions"].append(action)

        for email, issue_list in by_issue_email.items():
            try:
                for luid in legacy_user_ids_for_email(email):
                    invia_notifica(
                        luid,
                        "generico",
                        f"Hai {len(issue_list)} problema/i aperto/i scaduto/i su incontri KICK-OFF.",
                    )
            except Exception:
                logger.exception("run_meetings_digest: notifica in-app problemi fallita per %s", email)

    sent = 0
    for email, data in by_email.items():
        parts = []
        if data["meetings"]:
            rows = []
            for m in data["meetings"]:
                when = m.data.strftime("%d/%m/%Y")
                if m.ora:
                    when += f" alle {m.ora.strftime('%H:%M')}"
                m_label = m.titolo or f"Incontro {m.numero}"
                rows.append(f"- {m_label} [{getattr(m.project, 'name', '')}] — {when}")
            parts.append("Incontri KICK-OFF di domani:\n" + "\n".join(rows))
        if data["issues"]:
            rows = [
                f"- {i.title} (KICK-OFF {getattr(i.project, 'kickoff_number', '') or ''}, "
                f"scadenza {i.due_date:%d/%m/%Y})"
                for i in data["issues"]
            ]
            parts.append("Problemi aperti scaduti a te assegnati:\n" + "\n".join(rows))
        if data["actions"]:
            rows = [
                f"- {a.title} (KICK-OFF {getattr(a.project, 'kickoff_number', '') or ''}, "
                f"scadenza {a.due_date:%d/%m/%Y})"
                for a in data["actions"]
            ]
            parts.append("Azioni scadute a te assegnate:\n" + "\n".join(rows))
        if not parts:
            continue

        if data["meetings"] and (data["issues"] or data["actions"]):
            subject = "Promemoria KICK-OFF: incontro domani e scadenze aperte"
        elif data["meetings"]:
            first_label = data["meetings"][0].titolo or f"Incontro {data['meetings'][0].numero}"
            subject = f"Promemoria incontro domani — {first_label}"
        else:
            scaduti = len(data["issues"]) + len(data["actions"])
            subject = f"Scadenze KICK-OFF aperte ({scaduti})"

        try:
            n = send_hub_mail(
                subject,
                "\n\n".join(parts),
                [email],
                title="Promemoria KICK-OFF",
                email_type="VRF - KICK-OFF",
                fail_silently=True,
            )
            if n:
                sent += 1
        except Exception:
            logger.exception("run_meetings_digest: invio email fallito per %s", email)

    for meeting in meetings:
        meeting.reminder_sent_at = timezone.now()
        meeting.save(update_fields=["reminder_sent_at"])

    return {"reminders": sent, "meetings": len(meetings), "issues": len(issues)}
