"""Task periodici django-q2 per il modulo anomalie.

Registrati via automazioni.schedules + setup_q_schedules.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("anomalie.tasks")


def run_anomalie_pending_notifications(threshold_minutes: int = 5) -> dict:
    """Invia le mail di conferma per gli OP con modifiche ferme da > threshold_minutes.

    Fallback al tasto 'Salva e notifica': se l'operatore dimentica di notificare,
    la mail di riepilogo parte comunque dopo la soglia di inattività.
    """
    from anomalie.mail_action_service import flush_pending_update_notifications

    try:
        result = flush_pending_update_notifications(threshold_minutes=threshold_minutes)
        if result.get("sent"):
            logger.info(
                "run_anomalie_pending_notifications: inviate=%s controllate=%s",
                result.get("sent"),
                result.get("checked"),
            )
        return result
    except Exception:
        logger.exception("run_anomalie_pending_notifications: eccezione inattesa")
        raise
