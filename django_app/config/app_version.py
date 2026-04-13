from __future__ import annotations

from pathlib import Path


DEFAULT_APP_VERSION = "0.9.15"

# Keep insertion order stable for deterministic .env generation.
MODULE_ENV_KEYS_BY_CODE: dict[str, str] = {
    "core": "APP_VERSION_CORE",
    "dashboard": "APP_VERSION_DASHBOARD",
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
    parsed = str(value or "").strip()
    return parsed or default


def project_root() -> Path:
    # config/app_version.py -> config -> django_app -> repo root
    return Path(__file__).resolve().parents[2]


def version_file_path() -> Path:
    return project_root() / "VERSION"


def load_app_version(default: str = DEFAULT_APP_VERSION) -> str:
    path = version_file_path()
    try:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
    except Exception:
        return default
    return _normalize(first_line, default)


def build_module_version_env_block(app_version: str) -> str:
    version = _normalize(app_version, load_app_version())
    return "\n".join(f"{env_key}={version}" for env_key in MODULE_VERSION_ENV_KEYS)

