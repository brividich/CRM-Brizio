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
