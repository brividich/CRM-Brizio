"""
Helper condivisi per caricare cassette e marcare test live.
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from typing import Any

CASSETTES_DIR = Path(__file__).resolve().parent / "cassettes"


def load_cassette(name: str) -> dict[str, Any]:
    """Carica una cassetta JSON dalla cartella cassettes/."""
    path = CASSETTES_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Cassetta non trovata: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def live_integration_enabled() -> bool:
    """True se l'utente ha optato per i test live."""
    return os.environ.get("RUN_LIVE_INTEGRATION_TESTS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def skip_unless_live(reason: str = "Test live: opt-in via RUN_LIVE_INTEGRATION_TESTS=1"):
    """Decorator skip per i test che richiedono integrazione live."""
    return unittest.skipUnless(live_integration_enabled(), reason)
