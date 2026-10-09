"""Stato del setup: unica regola per middleware e view del wizard.

Legge ``SETUP_COMPLETED`` dagli stessi file .env del runtime e con la stessa
precedenza (``config.env_config.iter_runtime_env_paths``): in TEST/PROD vince il
.env persistente ``ENV/config/.env``, non la copia dentro la release. Prima il
wizard guardava solo ``django_app/.env``: se la copia mancava o non aveva il flag,
gli endpoint anonimi ``/setup/api/*`` (salva .env, crea admin) tornavano attivi.
"""
from __future__ import annotations

from pathlib import Path

from config.env_config import iter_runtime_env_paths, primary_runtime_env_path

_APP_DIR = Path(__file__).resolve().parent.parent  # django_app/


def runtime_env_path() -> Path:
    """File .env su cui il wizard scrive: quello primario del runtime."""
    return primary_runtime_env_path(_APP_DIR)


def _read_flag(path: Path) -> str | None:
    try:
        content = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith("SETUP_COMPLETED="):
            return line.split("=", 1)[1].strip().strip("'\"").lower()
    return None


def _running_with_prod_settings() -> bool:
    import os

    from django.conf import settings

    module = str(getattr(settings, "SETTINGS_MODULE", "") or os.environ.get("DJANGO_SETTINGS_MODULE", "")).lower()
    return module.endswith(".prod")


def setup_needed() -> bool:
    """True se il setup non risulta completato in nessun .env del runtime.

    SEC (audit M9): con i settings di produzione il wizard web è sempre chiuso.
    In produzione il portale parte solo con un .env completo (prod.py blocca
    l'avvio altrimenti): un ``SETUP_COMPLETED`` mancante o perso non deve
    riaprire gli endpoint anonimi ``/setup/api/*`` (salva .env, crea admin).
    L'installazione passa dal Setup Wizard desktop.
    """
    if _running_with_prod_settings():
        return False
    for path in iter_runtime_env_paths(_APP_DIR):
        if not path.exists():
            continue
        flag = _read_flag(path)
        if flag is not None:
            return flag not in ("1", "true", "yes")
    return True
