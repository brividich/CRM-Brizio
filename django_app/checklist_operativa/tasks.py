"""Task periodici django-q2 del modulo checklist_operativa.

Registrati in modo idempotente da ``automazioni.schedules`` /
``setup_q_schedules``. Non avviare task qui: usare il management command.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_checklist_chiusura_reminders() -> dict:
    """Promemoria (in-app) ai responsabili con task non confermati prima di una chiusura.

    Wrappa il management command ``send_checklist_chiusura_reminders``.
    """
    from django.core.management import call_command

    try:
        call_command("send_checklist_chiusura_reminders", verbosity=0)
        return {"ok": True}
    except Exception:
        logger.exception("run_checklist_chiusura_reminders: eccezione inattesa")
        raise
