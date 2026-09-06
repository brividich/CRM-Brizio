from __future__ import annotations

from pathlib import Path


DEFAULT_APP_VERSION = "1.4.0"

# Keep insertion order stable for deterministic .env generation.
MODULE_ENV_KEYS_BY_CODE: dict[str, str] = {
    "core": "APP_VERSION_CORE",
    "dashboard": "APP_VERSION_DASHBOARD",
    "ai_assistant": "APP_VERSION_AI_ASSISTANT",
    "assenze": "APP_VERSION_ASSENZE",
    "anomalie": "APP_VERSION_ANOMALIE",
    "assets": "APP_VERSION_ASSETS",
    "tasks": "APP_VERSION_TASKS",
    "admin_portale": "APP_VERSION_ADMIN_PORTALE",
    "notizie": "APP_VERSION_NOTIZIE",
    "anagrafica": "APP_VERSION_ANAGRAFICA",
    "tickets": "APP_VERSION_TICKETS",
    "dpi": "APP_VERSION_DPI",
    "procedure_refresh": "APP_VERSION_PROCEDURE_REFRESH",
}
MODULE_VERSION_ENV_KEYS: tuple[str, ...] = tuple(MODULE_ENV_KEYS_BY_CODE.values())


def _normalize(value: str, default: str) -> str:
    # `strip()` NON rimuove il BOM (U+FEFF non e' whitespace): un file VERSION
    # salvato in UTF-8-with-BOM (lo fanno Notepad e PowerShell) produrrebbe la
    # versione "﻿1.3.0", con un carattere invisibile in testa. Quella stringa
    # finisce nel footer del portale, nelle chiavi di versione scritte nel .env e
    # nei confronti di versione, e fa fallire la serializzazione su stdout cp1252
    # (UnicodeEncodeError in `validate_deployment --format json`).
    parsed = str(value or "").lstrip("﻿").strip()
    return parsed or default


def project_root() -> Path:
    # config/app_version.py -> config -> django_app -> repo root
    return Path(__file__).resolve().parents[2]


def version_file_path() -> Path:
    return project_root() / "VERSION"


def load_app_version(default: str = DEFAULT_APP_VERSION) -> str:
    path = version_file_path()
    try:
        # utf-8-sig: consuma l'eventuale BOM invece di trascinarlo nel valore.
        first_line = path.read_text(encoding="utf-8-sig").splitlines()[0]
    except Exception:
        return default
    return _normalize(first_line, default)


def build_module_version_env_block(app_version: str) -> str:
    version = _normalize(app_version, load_app_version())
    return "\n".join(f"{env_key}={version}" for env_key in MODULE_VERSION_ENV_KEYS)
