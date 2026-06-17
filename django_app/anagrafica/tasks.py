"""Task periodici django-q2 del modulo anagrafica.

Registrati in modo idempotente da ``automazioni.schedules`` /
``setup_q_schedules``. Non avviare task qui: usare il management command.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_idoneita_digest(only_ko: bool = False) -> dict:
    """Digest "idoneità alla mansione" (non idonei / con riserve) per RSPP /
    medico competente / HR.

    Wrappa il management command ``send_idoneita_digest``. È **fail-safe**: se non
    ci sono destinatari configurati (``SiteConfig.idoneita_reminder_emails``) il
    comando non invia nulla e lo schedule resta un no-op, quindi è sicuro tenerlo
    sempre attivo. Privacy: nessun dato clinico (vedi il management command).
    """
    from django.core.management import call_command

    try:
        call_command("send_idoneita_digest", only_ko=only_ko, verbosity=0)
        return {"ok": True, "only_ko": bool(only_ko)}
    except Exception:
        logger.exception("run_idoneita_digest: eccezione inattesa")
        raise
