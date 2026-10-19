"""Task pianificati (django-q) del modulo dashboard."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_scadenze_digest() -> dict:
    """Riepilogo mattutino personale delle scadenze (``dashboard.scadenze_digest``).

    No-op finché nessun utente lo attiva in Notifiche → Impostazioni: parte solo
    verso chi l'ha chiesto, mai verso liste o amministratori."""
    from .scadenze_digest import invia_digest_scadenze

    try:
        return {"ok": True, **invia_digest_scadenze()}
    except Exception:
        logger.exception("run_scadenze_digest fallito")
        return {"ok": False}


def run_scadenze_outlook() -> dict:
    """Allinea il calendario «Scadenze NOVICROM HUB» di chi l'ha scelto (``dashboard.scadenze_calendario``)."""
    from dashboard.scadenze_calendario import sincronizza_tutti

    return sincronizza_tutti()
