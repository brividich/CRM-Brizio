"""Task django-q del glossario: proposte AI per un batch di candidati (< 90 s)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_glossario_proposte_ai(candidati: list[str], **kwargs) -> dict:
    """Un batch di candidati -> proposte AI in attesa di decisione. Fail-safe."""
    try:
        from .services import proponi_con_ai

        return {"ok": True, "proposte": proponi_con_ai(list(candidati or []))}
    except Exception:
        logger.exception("run_glossario_proposte_ai: errore inatteso")
        return {"ok": False, "proposte": 0}
