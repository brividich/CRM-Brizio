"""Task periodici django-q2 del modulo assets.

Registrati in modo idempotente da ``automazioni.schedules`` /
``setup_q_schedules``. Non avviare task qui: usare il management command.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_generate_maintenance_occurrences() -> dict:
    """Crea le occorrenze di manutenzione dovute dai piani attivi.

    Sostituisce ``run_generate_scheduled_workorders``: lo scheduler non apre più un
    OdL per ogni asset. Genera le *manutenzioni dovute*; raggrupparle in ordini di
    lavoro — anche massivi — resta una decisione umana. Va schedulato PRIMA di
    ``run_maintenance_reminders`` così le nuove scadenze entrano nella mail del giorno.
    """
    from django.core.management import call_command

    try:
        call_command("generate_maintenance_occurrences", verbosity=0)
        return {"ok": True}
    except Exception:
        logger.exception("run_generate_maintenance_occurrences: eccezione inattesa")
        raise


def run_maintenance_reminders() -> dict:
    """Promemoria email scadenze manutenzione/verifiche periodiche + OdL scaduti.

    Wrappa il management command ``send_maintenance_reminders``. I destinatari sono
    ``SiteConfig.assets_reminder_emails`` con fallback su ADMINS/superuser: NON è un
    no-op puro, quindi da attivare solo dove si vogliono davvero i promemoria assets.
    """
    from django.core.management import call_command

    try:
        call_command("send_maintenance_reminders", verbosity=0)
        return {"ok": True}
    except Exception:
        logger.exception("run_maintenance_reminders: eccezione inattesa")
        raise
