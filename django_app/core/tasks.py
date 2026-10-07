"""Task periodici django-q2 trasversali (modulo core).

Registrati in modo idempotente da ``automazioni.schedules`` /
``setup_q_schedules``. Non avviare task qui: usare il management command.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_caporeparto_morning_digest() -> dict:
    """Digest mattutino per caporeparto (DPI in attesa + incidenti aperti del reparto).

    Wrappa ``send_caporeparto_morning_digest``. **Fail-safe**: no-op se non ci sono
    caporeparto assegnati o voci in sospeso; salta i capi senza ``email_notifica``.
    """
    from django.core.management import call_command

    try:
        call_command("send_caporeparto_morning_digest", verbosity=0)
        return {"ok": True}
    except Exception:
        logger.exception("run_caporeparto_morning_digest: eccezione inattesa")
        raise


def run_notifiche_archivio() -> dict:
    """Archivia le notifiche in-app scadute ed elimina le archiviate oltre soglia.

    Soglie da ``core.notifiche_archivio.get_politica`` (SiteConfig)."""
    from core.notifiche_archivio import archivia_scadute

    try:
        return {"ok": True, **archivia_scadute()}
    except Exception:
        logger.exception("run_notifiche_archivio: eccezione inattesa")
        raise
