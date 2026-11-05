"""Task pianificati (django-q) dello scadenzario generale."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_avvisi_attivita() -> dict:
    from .avvisi import invia_avvisi_attivita

    try:
        return {"ok": True, **invia_avvisi_attivita()}
    except Exception:
        logger.exception("scadenzario: avvisi attività falliti")
        return {"ok": False}


def run_foto_giornaliera() -> dict:
    from .calendario import scatta_foto

    try:
        return {"ok": True, **scatta_foto()}
    except Exception:
        logger.exception("scadenzario: fotografia giornaliera fallita")
        return {"ok": False}


def run_riepiloghi_categorie() -> dict:
    from .avvisi import invia_riepiloghi_categorie

    try:
        return {"ok": True, **invia_riepiloghi_categorie()}
    except Exception:
        logger.exception("scadenzario: riepiloghi categorie falliti")
        return {"ok": False}
