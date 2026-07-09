"""Task django-q per Suggestion Corner (§3)."""
from __future__ import annotations

import logging

from django.core.management import call_command

logger = logging.getLogger(__name__)


def run_suggestion_corner_reminders():
    """Wrapper fail-safe per lo scheduler: solleciti/escalation giornalieri."""
    try:
        call_command("send_suggestion_corner_reminders")
    except Exception:
        logger.exception("send_suggestion_corner_reminders fallito")
