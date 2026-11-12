"""Codice leggibile dell'anomalia: «AN-00123».

Viene dall'id della riga legacy ``anomalie``: univoco, stabile, senza contatori né
migrazioni. Lo mostrano pagina, link via email e mail; la ricerca accetta sia il
codice sia il numero.
"""
from __future__ import annotations

import re

PREFISSO = "AN-"
_RE = re.compile(r"^\s*(?:AN-?|#)?\s*0*(\d+)\s*$", re.IGNORECASE)


def codice_anomalia(anomalia_id) -> str:
    """``123`` → ``AN-00123``; vuoto se l'id manca."""
    try:
        n = int(str(anomalia_id).split(":")[-1])
    except (TypeError, ValueError):
        return ""
    return f"{PREFISSO}{n:05d}" if n > 0 else ""


def id_da_codice(testo) -> int | None:
    """``AN-00123``, ``an123``, ``#123`` o ``123`` → ``123``."""
    m = _RE.match(str(testo or ""))
    return int(m.group(1)) if m else None
