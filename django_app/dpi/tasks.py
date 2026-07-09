"""Task periodici django-q2 del modulo dpi.

Registrati in modo idempotente da ``automazioni.schedules`` /
``setup_q_schedules``. Non avviare task qui: usare il management command.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_dpi_expiry_reminders() -> dict:
    """Promemoria email per i DPI scaduti o in scadenza (+ notifica in-app).

    Wrappa il management command ``send_dpi_expiry_reminders``. I destinatari sono
    ricavati dalle impostazioni DPI / SiteConfig con fallback su ADMINS/superuser:
    NON è un no-op puro, quindi da attivare dove si vogliono davvero i promemoria DPI.
    """
    from django.core.management import call_command

    try:
        call_command("send_dpi_expiry_reminders", verbosity=0)
        return {"ok": True}
    except Exception:
        logger.exception("run_dpi_expiry_reminders: eccezione inattesa")
        raise
