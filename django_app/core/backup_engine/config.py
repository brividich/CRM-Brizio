"""Configurazione del motore di backup, letta da settings/.env e validata."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

_ENV_RE = re.compile(r"^[a-z][a-z0-9_-]{0,19}$")
_WINDOW_RE = re.compile(r"^(\d{1,2})-(\d{1,2})$")


def default_env_name() -> str:
    explicit = str(getattr(settings, "BACKUP_ENV_NAME", "") or "").strip().lower()
    if explicit:
        return explicit
    module = (os.environ.get("DJANGO_SETTINGS_MODULE") or "").lower()
    if module.endswith(".prod"):
        return "prod"
    if module.endswith(".test"):
        return "test"
    return "dev"


def parse_window(text: str) -> tuple[int, int]:
    m = _WINDOW_RE.match((text or "").strip())
    if not m:
        raise ValueError(f"BACKUP_LOG_WINDOW non valida: {text!r} (atteso es. 07-21)")
    start, end = int(m.group(1)), int(m.group(2))
    if not (0 <= start < 24 and 0 < end <= 24 and start < end):
        raise ValueError(f"BACKUP_LOG_WINDOW fuori intervallo: {text!r}")
    return start, end


@dataclass(frozen=True)
class BackupConfig:
    env: str
    target: Path
    target_secondary: Path | None
    staging: Path
    sql_timeout_s: int
    log_window: tuple[int, int]
    keep_daily: int
    keep_weekly: int
    keep_monthly: int
    keep_log_days: int
    extra_databases: tuple[str, ...]
    env_dir: str
    status_dir: Path
    warnings: tuple[str, ...] = field(default=())

    @property
    def env_root(self) -> Path:
        return self.target / self.env

    @property
    def objects_root(self) -> Path:
        """Store content-addressed dei file, condiviso fra i set (dedup tra run)."""
        return self.env_root / "_objects"

    def in_log_window(self, hour: int) -> bool:
        return self.log_window[0] <= hour < self.log_window[1]


def load_config(env: str | None = None, target: str | None = None) -> BackupConfig:
    env_name = (env or default_env_name()).strip().lower()
    if not _ENV_RE.match(env_name):
        raise ValueError(f"Nome ambiente non valido: {env_name!r}")
    target_text = (target or str(getattr(settings, "BACKUP_TARGET", "") or "")).strip()
    if not target_text:
        raise ValueError("BACKUP_TARGET non configurato.")
    secondary = str(getattr(settings, "BACKUP_TARGET_SECONDARY", "") or "").strip()
    warnings: list[str] = []
    for name in ("BACKUP_KEEP_DAILY", "BACKUP_KEEP_WEEKLY", "BACKUP_KEEP_MONTHLY", "BACKUP_KEEP_LOG_DAYS"):
        if int(getattr(settings, name, 1) or 0) < 1:
            raise ValueError(f"{name} deve essere almeno 1.")
    if env_name == "prod" and not target_text.startswith("\\\\"):
        warnings.append("BACKUP_TARGET in produzione è locale: i backup stanno sulla stessa macchina dei dati.")
    if secondary and Path(secondary) == Path(target_text):
        warnings.append("BACKUP_TARGET_SECONDARY coincide con BACKUP_TARGET: ignorata.")
        secondary = ""
    extra = tuple(
        d for d in (str(x).strip() for x in getattr(settings, "BACKUP_EXTRA_DATABASES", []) or []) if d
    )
    return BackupConfig(
        env=env_name,
        target=Path(target_text),
        target_secondary=Path(secondary) if secondary else None,
        staging=Path(str(getattr(settings, "BACKUP_STAGING_DIR", "") or Path(settings.BASE_DIR).parent / "backup-staging")),
        sql_timeout_s=max(60, int(getattr(settings, "BACKUP_SQL_TIMEOUT_S", 3600) or 3600)),
        log_window=parse_window(str(getattr(settings, "BACKUP_LOG_WINDOW", "07-21") or "07-21")),
        keep_daily=int(getattr(settings, "BACKUP_KEEP_DAILY", 14)),
        keep_weekly=int(getattr(settings, "BACKUP_KEEP_WEEKLY", 8)),
        keep_monthly=int(getattr(settings, "BACKUP_KEEP_MONTHLY", 12)),
        keep_log_days=int(getattr(settings, "BACKUP_KEEP_LOG_DAYS", 14)),
        extra_databases=extra,
        env_dir=str(getattr(settings, "BACKUP_ENV_DIR", "") or os.environ.get("BACKUP_ENV_DIR", "")).strip(),
        status_dir=Path(getattr(settings, "LOG_DIR", Path(settings.BASE_DIR) / "logs")),
        warnings=tuple(warnings),
    )
