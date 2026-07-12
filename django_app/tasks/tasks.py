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


@system_job_run("tasks_meeting_issue_reminders")
def run_meeting_issue_reminders(**kwargs) -> dict:
    """Promemoria per i «problemi aperti» degli incontri KICK-OFF scaduti.

    Per ogni `MeetingIssue` OPEN con scadenza passata e un responsabile assegnato,
    invia al responsabile una email di sollecito (raggruppata per persona) + una
    notifica in-app best-effort. Idempotente per giro (si basa sullo stato corrente:
    un problema chiuso o senza scadenza non produce solleciti).
    """
    from collections import defaultdict

    from django.utils import timezone

    from core.email_utils import send_hub_mail
    from tasks.models import MeetingIssue, MeetingIssueStatus

    today = timezone.localdate()
    qs = (
        MeetingIssue.objects.filter(
            status=MeetingIssueStatus.OPEN,
            due_date__isnull=False,
            due_date__lt=today,
            assigned_to__isnull=False,
        )
        .select_related("assigned_to", "project")
    )

    by_email: dict[str, list] = defaultdict(list)
    for issue in qs:
        email = (getattr(issue.assigned_to, "email", "") or "").strip()
        if email:
            by_email[email].append(issue)

    sent = 0
    for email, issues in by_email.items():
        rows = [
            f"- {i.title} (KICK-OFF {getattr(i.project, 'kickoff_number', '') or ''}, "
            f"scadenza {i.due_date:%d/%m/%Y})"
            for i in issues
        ]
        body = "Problemi aperti scaduti a te assegnati:\n" + "\n".join(rows)
        try:
            n = send_hub_mail(
                f"Problemi aperti KICK-OFF scaduti ({len(issues)})",
                body,
                [email],
                title="Problemi aperti scaduti",
                email_type="VRF - KICK-OFF",
                fail_silently=True,
            )
            if n:
                sent += 1
        except Exception:
            logger.exception("run_meeting_issue_reminders: invio fallito per %s", email)

        # Notifica in-app best-effort (mappa email → utenti legacy)
        try:
            from core.notifiche import invia_notifica, legacy_user_ids_for_email

            for luid in legacy_user_ids_for_email(email):
                invia_notifica(
                    luid,
                    "generico",
                    f"Hai {len(issues)} problema/i aperto/i scaduto/i su incontri KICK-OFF.",
                )
        except Exception:
            logger.exception("run_meeting_issue_reminders: notifica in-app fallita per %s", email)

    return {"reminders": sent, "issues": qs.count()}
