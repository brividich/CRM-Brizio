"""Prova di ripristino automatica (BUILD_SPEC R2 §4.3).

1. piano: ultimo FULL verificato + LOG fino al più recente (o ``stopat``);
2. spazio: se ``spazio del DB × 1,1`` supera il libero in staging, non parte (WARNING);
3. ``RESTORE DATABASE <db>_drill … WITH MOVE, NORECOVERY, CHECKSUM``, log in sequenza,
   ``RECOVERY`` finale (con ``STOPAT``);
4. controlli sulla copia, con connessione separata (mai la ``default``): ``DBCC CHECKDB``,
   migrazioni uguali al manifest, conteggi delle tabelle chiave entro tolleranza;
5. dal backup dei file: N campioni per radice privata decifrati in memoria con la chiave
   corrente (nessuna scrittura in chiaro);
6. ``DROP DATABASE <db>_drill`` sempre, in ``finally``; staging ripulito;
7. ``RestoreDrill`` con RTO della parte DB ed esito di ogni controllo.

Guardie: il nome di prova finisce sempre con ``_drill``; si rifiuta un nome senza
suffisso; mai ``WITH REPLACE``.
"""
from __future__ import annotations

import json
import logging
import random
import shutil
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from . import files as files_mod
from .config import BackupConfig
from .restore_plan import PlanError, build_plan
from .sqlserver import SqlError, SqlServer, quote_literal, quote_name
from .transfer import TransferError, copy_verified

logger = logging.getLogger(__name__)
SUFFIX = "_drill"


class DrillRefused(RuntimeError):
    pass


def drill_name(db: str) -> str:
    name = f"{db}{SUFFIX}"
    if not name.endswith(SUFFIX):
        raise DrillRefused("Nome di prova senza suffisso _drill")
    return name


def _free_mb(path: Path) -> int | None:
    try:
        return int(shutil.disk_usage(path).free / 1048576)
    except OSError:
        return None


def _decrypt_samples(cfg: BackupConfig, plan: dict, n: int, rng: random.Random) -> dict:
    """Decifra in memoria N file per radice privata dallo snapshot dei file del piano."""
    from core.encrypted_storage import decrypt_bytes, is_encrypted

    if not plan.get("files_index"):
        return {"status": "warning", "message": "nessun backup dei file"}
    index = json.loads((cfg.env_root / plan["files_index"]).read_text(encoding="utf-8-sig"))
    out: dict = {"roots": {}}
    status = "ok"
    for label, root in sorted(index.items()):
        if label == "media":
            continue
        entries = [(rel, e) for rel, e in (root.get("files") or {}).items()]
        sample = rng.sample(entries, min(n, len(entries))) if entries else []
        res = {"files": len(entries), "checked": 0, "encrypted": 0, "decrypted": 0, "errors": []}
        for rel, e in sample:
            obj = files_mod.object_path(cfg.objects_root, e["sha256"])
            try:
                data = obj.read_bytes()
                res["checked"] += 1
                if is_encrypted(data):
                    res["encrypted"] += 1
                    decrypt_bytes(data)          # solo in memoria, il risultato non viene scritto
                    res["decrypted"] += 1
            except Exception as exc:
                res["errors"].append(f"{rel}: {exc.__class__.__name__}")
                status = "failed"
        out["roots"][label] = res
    out["status"] = status
    return out


def _check_rows(expected: dict, actual: dict, tolerance_pct: float) -> tuple[bool, dict]:
    detail, ok = {}, True
    for table, exp in expected.items():
        act = actual.get(table)
        if act is None:
            detail[table] = {"expected": exp, "actual": None, "ok": False}
            ok = False
            continue
        allowed = max(1, round(exp * tolerance_pct / 100))
        good = abs(act - exp) <= allowed
        detail[table] = {"expected": exp, "actual": act, "ok": good}
        ok = ok and good
    return ok, detail


def run_drill(cfg: BackupConfig, *, stopat: datetime | None = None, sql: SqlServer | None = None,
              samples: int | None = None, seed: int | None = None, record: bool = True, keep: bool = False) -> dict:
    """``keep=True`` (recupero selettivo dopo una cancellazione per errore) lascia la copia
    ``<db>_drill`` sull'istanza: va eliminata a mano quando i dati sono stati recuperati."""
    started = timezone.now()
    result: dict = {"status": "running", "checks": {}, "error": "", "full_set_id": "", "last_log_set_id": "",
                    "rto_seconds": None, "point_in_time": stopat.isoformat() if stopat else None}
    staging = cfg.staging / cfg.env / "drill"
    created_dbs: list[str] = []
    sql_client = None
    try:
        plan = build_plan(cfg.env_root, stopat)
        result["full_set_id"] = plan["full_set_id"]
        result["last_log_set_id"] = plan["last_log_set_id"] or ""
        result["checks"]["plan"] = {"status": "ok", "restore_point": plan["restore_point"], "warnings": plan["warnings"]}
        hub_db = str(connection.settings_dict.get("NAME") or "")
        staging.mkdir(parents=True, exist_ok=True)

        # spazio
        full_manifest = json.loads((cfg.env_root / plan["full_set_id"] / "manifest.json").read_text(encoding="utf-8-sig"))
        need_mb = sum(int(d.get("allocated_mb") or 0) for d in full_manifest.get("databases", []))
        need_mb += sum(int(a["size"] / 1048576) for a in full_manifest.get("artifacts", []))
        free = _free_mb(staging)
        if free is not None and need_mb * 1.1 > free:
            result["status"] = "warning"
            result["error"] = f"Spazio insufficiente per la prova: servono ~{int(need_mb * 1.1)} MB, liberi {free} MB."
            return result

        t_db = time.monotonic()
        if connection.vendor == "microsoft":
            sql_client = sql or SqlServer.from_settings(cfg.sql_timeout_s)
            existing = {r[0] for r in sql_client.run("SELECT name FROM sys.databases")}
            for db, entry in plan["databases"].items():
                name = drill_name(db)
                if name in existing:
                    # residuo di una prova interrotta: è nostro (suffisso) e si può eliminare
                    sql_client.run(f"ALTER DATABASE {quote_name(name)} SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
                                   f"DROP DATABASE {quote_name(name)}")
                local_full = staging / Path(entry["full"]["path"]).name
                copy_verified(cfg.env_root / entry["full"]["path"], local_full, expected_sha256=entry["full"]["sha256"])
                filelist = sql_client.filelist(local_full)
                moves = []
                for i, f in enumerate(filelist):
                    ext = ".ldf" if f["type"] == "L" else (".mdf" if i == 0 else f"_{i}.ndf")
                    moves.append(f"MOVE {quote_literal(f['logical'])} TO {quote_literal(str(staging / f'{name}{ext}'))}")
                created_dbs.append(name)
                sql_client.run(f"RESTORE DATABASE {quote_name(name)} FROM DISK = {quote_literal(str(local_full))} "
                               f"WITH {', '.join(moves)}, NORECOVERY, CHECKSUM")
                local_full.unlink(missing_ok=True)
                for i, log in enumerate(entry["logs"]):
                    local_log = staging / Path(log["path"]).name
                    copy_verified(cfg.env_root / log["path"], local_log, expected_sha256=log["sha256"])
                    last = i == len(entry["logs"]) - 1
                    stop = f", STOPAT = {quote_literal(plan['stopat'])}" if (last and plan["stopat"]) else ""
                    sql_client.run(f"RESTORE LOG {quote_name(name)} FROM DISK = {quote_literal(str(local_log))} "
                                   f"WITH NORECOVERY, CHECKSUM{stop}")
                    local_log.unlink(missing_ok=True)
                sql_client.run(f"RESTORE DATABASE {quote_name(name)} WITH RECOVERY")
            result["rto_seconds"] = int(time.monotonic() - t_db)
            hub_name = drill_name(hub_db)
            mode = "PHYSICAL_ONLY" if str(getattr(settings, "BACKUP_DRILL_CHECKDB_MODE", "physical")) != "full" else "ALL_ERRORMSGS"
            for name in created_dbs:
                sql_client.run(f"DBCC CHECKDB ({quote_name(name)}) WITH NO_INFOMSGS, {mode}")
            result["checks"]["checkdb"] = {"status": "ok", "mode": mode, "databases": created_dbs}
            if hub_db in plan["databases"]:
                migr = sql_client.applied_migrations(hub_name)
                counts = sql_client.row_counts(hub_name, list(plan["row_counts"]))
            else:
                migr, counts = {}, {}
        else:
            entry = next(iter(plan["databases"].values()))
            local = staging / Path(entry["full"]["path"]).name
            copy_verified(cfg.env_root / entry["full"]["path"], local, expected_sha256=entry["full"]["sha256"])
            with closing(sqlite3.connect(str(local))) as c:
                integrity = c.execute("PRAGMA integrity_check").fetchone()[0]
                migr = {a: n for a, n in c.execute("SELECT app, MAX(name) FROM django_migrations GROUP BY app")}
                names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                counts = {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in plan["row_counts"] if t in names}
            local.unlink(missing_ok=True)
            result["rto_seconds"] = int(time.monotonic() - t_db)
            result["checks"]["checkdb"] = {"status": "ok" if integrity == "ok" else "failed", "mode": "sqlite integrity_check"}

        expected_migr = plan.get("migrations") or {}
        diff = {app: {"backup": expected_migr.get(app), "ripristino": migr.get(app)}
                for app in set(expected_migr) | set(migr) if expected_migr.get(app) != migr.get(app)}
        result["checks"]["migrations"] = {"status": "ok" if not diff else "failed", "differences": diff}
        ok_rows, rows = _check_rows(plan.get("row_counts") or {}, counts,
                                    float(getattr(settings, "BACKUP_DRILL_ROW_TOLERANCE_PCT", 5)))
        result["checks"]["row_counts"] = {"status": "ok" if ok_rows else "failed", "tables": rows}
        n = samples if samples is not None else int(getattr(settings, "BACKUP_DRILL_DECRYPT_SAMPLES", 5))
        result["checks"]["decrypt"] = _decrypt_samples(cfg, plan, n, random.Random(seed))

        states = [c.get("status") for c in result["checks"].values()]
        result["status"] = "failed" if "failed" in states else ("warning" if "warning" in states or plan["warnings"] else "ok")
    except (PlanError, DrillRefused, SqlError, TransferError, OSError, ValueError) as exc:
        result["status"] = "failed"
        result["error"] = f"{exc.__class__.__name__}: {exc}"
    finally:
        if keep and created_dbs:
            result["kept_databases"] = list(created_dbs)
        elif sql_client is not None:
            for name in created_dbs:
                if not name.endswith(SUFFIX):
                    continue
                try:
                    sql_client.run(f"IF DB_ID({quote_literal(name)}) IS NOT NULL BEGIN "
                                   f"ALTER DATABASE {quote_name(name)} SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
                                   f"DROP DATABASE {quote_name(name)} END")
                except SqlError as exc:
                    logger.error("drill: DROP di %s non riuscito: %s", name, exc)
                    result.setdefault("cleanup_errors", []).append(f"{name}: {exc}")
        shutil.rmtree(staging, ignore_errors=True)
        result["started_at"] = started.isoformat()
        result["finished_at"] = timezone.now().isoformat()
        if record:
            _record(cfg, result, started)
    return result


def _aware(iso: str | None):
    if not iso:
        return None
    dt = datetime.fromisoformat(iso)
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def _record(cfg: BackupConfig, result: dict, started) -> None:
    try:
        from monitoring.models import RestoreDrill

        RestoreDrill.objects.create(
            env=cfg.env, started_at=started, finished_at=timezone.now(), status=result["status"],
            full_set_id=result.get("full_set_id", ""), last_log_set_id=result.get("last_log_set_id", ""),
            point_in_time=_aware(result.get("point_in_time")),
            rto_seconds=result.get("rto_seconds"), checks=result.get("checks", {}), error=result.get("error", "")[:4000],
        )
    except Exception:
        logger.warning("RestoreDrill non registrato", exc_info=True)
