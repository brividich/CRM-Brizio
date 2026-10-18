"""Stato dei backup su file, leggibile anche con il database spento.

Due copie: ``<target>/<env>/status.json`` (accanto ai backup) e
``<LOG_DIR>/backup-status.json`` (sulla macchina). Se il DB non era raggiungibile
durante un run, l'esito resta in ``pending_db`` e viene riconciliato in
``BackupRun`` al run successivo.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from django.utils import timezone

from .config import BackupConfig
from .transfer import write_bytes_verified

logger = logging.getLogger(__name__)
LOCAL_NAME = "backup-status.json"
TARGET_NAME = "status.json"


def _paths(cfg: BackupConfig) -> list[Path]:
    return [cfg.status_dir / LOCAL_NAME, cfg.env_root / TARGET_NAME]


def read(cfg: BackupConfig) -> dict:
    for p in _paths(cfg):
        try:
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            logger.warning("stato backup illeggibile: %s", p)
    return {"env": cfg.env, "last": {}, "pending_db": []}


def write(cfg: BackupConfig, data: dict) -> list[str]:
    data["updated_at"] = timezone.localtime().isoformat()
    payload = json.dumps(data, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    errors = []
    for p in _paths(cfg):
        try:
            write_bytes_verified(payload, p)
        except OSError as exc:
            errors.append(f"{p}: {exc}")
    return errors


def record(cfg: BackupConfig, run: dict, recorded_in_db: bool) -> list[str]:
    data = read(cfg)
    data.setdefault("last", {})[run["kind"]] = {
        k: run.get(k) for k in ("status", "set_id", "started_at", "finished_at", "bytes", "error", "verify_status")
    }
    if run.get("status") in ("ok", "warning"):
        data["last"][run["kind"]]["last_ok_at"] = run.get("finished_at")
        data["last"][run["kind"]]["last_ok_set_id"] = run.get("set_id")
    else:
        prev = read(cfg).get("last", {}).get(run["kind"], {})
        for k in ("last_ok_at", "last_ok_set_id"):
            if prev.get(k):
                data["last"][run["kind"]][k] = prev[k]
    if not recorded_in_db:
        data.setdefault("pending_db", []).append(run)
    return write(cfg, data)


def take_pending(cfg: BackupConfig) -> list[dict]:
    data = read(cfg)
    pending = data.get("pending_db") or []
    return pending


def clear_pending(cfg: BackupConfig, count: int) -> None:
    data = read(cfg)
    data["pending_db"] = (data.get("pending_db") or [])[count:]
    write(cfg, data)
