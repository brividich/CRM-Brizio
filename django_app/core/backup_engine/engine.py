"""Orchestrazione dei backup set: FULL, LOG, FILES, HOST, RETENTION e verifica.

Ogni set è una cartella ``<target>/<env>/<YYYYMMDD_HHMMSS>_<tipo>/`` con
``manifest.json`` scritto per ultimo: una cartella senza manifest è un set
incompleto e non conta. Il database (``BackupRun``) riceve l'esito se raggiungibile,
altrimenti resta in ``status.json`` e viene riconciliato al run successivo.
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from . import files as files_mod
from . import host_manifest
from . import manifest as mf
from . import retention, status
from .config import BackupConfig
from .sqlserver import LogBackupNotPossible, SqlError, SqlServer
from .transfer import TransferError, copy_verified, sha256_file, write_bytes_verified

logger = logging.getLogger(__name__)

EXIT = {"ok": 0, "warning": 1, "failed": 2}
DEFAULT_KEY_TABLES = ["utenti", "anagrafica_dipendenti", "assets_asset", "tickets_ticket", "anagrafica_visitamedica"]


def key_tables() -> list[str]:
    return list(getattr(settings, "BACKUP_DRILL_TABLES", None) or DEFAULT_KEY_TABLES)


def is_mssql() -> bool:
    return connection.vendor == "microsoft"


def hub_database() -> str:
    return str(connection.settings_dict.get("NAME") or "")


@dataclass
class RunResult:
    kind: str
    status: str = "ok"
    set_id: str = ""
    database: str = ""
    bytes: int = 0
    sha256: str = ""
    verify_status: str = ""
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    manifest: dict = field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""

    @property
    def exit_code(self) -> int:
        return EXIT.get(self.status, 2)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        if self.status == "ok":
            self.status = "warning"


# ── registrazione ────────────────────────────────────────────────────────────

def _db_record(cfg: BackupConfig, res: RunResult) -> bool:
    try:
        from monitoring.models import BackupRun

        BackupRun.objects.create(
            env=cfg.env, kind=res.kind, database=res.database[:128], status=res.status,
            started_at=datetime.fromisoformat(res.started_at) if res.started_at else timezone.now(),
            finished_at=datetime.fromisoformat(res.finished_at) if res.finished_at else timezone.now(),
            set_id=res.set_id, target=str(cfg.env_root)[:500], bytes=res.bytes, sha256=res.sha256,
            verify_status=res.verify_status, error=(res.error or "; ".join(res.warnings))[:4000],
            manifest=_summary(res.manifest), host=res.manifest.get("host", "")[:128] if res.manifest else "",
        )
        return True
    except Exception:
        logger.warning("BackupRun non registrato (DB non raggiungibile?)", exc_info=True)
        return False


def _summary(manifest: dict) -> dict:
    """Manifest ridotto per il DB: niente elenco variabili né indici, solo percorsi relativi."""
    if not manifest:
        return {}
    keep = ("schema_version", "set_id", "type", "env", "status", "created_at", "app", "artifacts", "chain",
            "files", "duration_s", "warnings", "row_counts", "release_ref", "host_manifest_ref")
    out = {k: manifest.get(k) for k in keep if k in manifest}
    if isinstance(out.get("app"), dict):
        out["app"] = {k: v for k, v in out["app"].items() if k != "migrations"}
    return out


def reconcile_pending(cfg: BackupConfig) -> int:
    pending = status.take_pending(cfg)
    done = 0
    for run in pending:
        res = RunResult(**{k: v for k, v in run.items() if k in RunResult.__dataclass_fields__})
        if not _db_record(cfg, res):
            break
        done += 1
    if done:
        status.clear_pending(cfg, done)
    return done


def finish(cfg: BackupConfig, res: RunResult) -> RunResult:
    res.finished_at = timezone.localtime().isoformat()
    if res.warnings and not res.error and res.status == "ok":
        res.status = "warning"
    in_db = _db_record(cfg, res)
    payload = {k: getattr(res, k) for k in RunResult.__dataclass_fields__ if k != "manifest"}
    payload["manifest"] = _summary(res.manifest)
    errs = status.record(cfg, payload, recorded_in_db=in_db)
    for e in errs:
        logger.warning("stato backup non scritto: %s", e)
    return res


# ── utilità set ──────────────────────────────────────────────────────────────

def new_set_id(kind: str, now: datetime | None = None) -> str:
    return f"{(now or timezone.localtime()).strftime('%Y%m%d_%H%M%S')}_{kind}"


def list_sets(cfg: BackupConfig, root: Path | None = None) -> list[retention.SetInfo]:
    root = root or cfg.env_root
    out: list[retention.SetInfo] = []
    if not root.exists():
        return out
    for d in root.iterdir():
        parsed = retention.parse_set_id(d.name) if d.is_dir() else None
        if not parsed or not (d / mf.MANIFEST_NAME).exists():
            continue
        try:
            data = json.loads((d / mf.MANIFEST_NAME).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        verified = all(a.get("verify_status") in ("ok", "not_applicable") for a in data.get("artifacts", []))
        out.append(retention.SetInfo(
            set_id=d.name, kind=parsed[1], created=parsed[0], status=data.get("status", "ok"),
            verified=verified, chain_base=(data.get("chain") or {}).get("full_set_id"), path=d,
        ))
    return sorted(out, key=lambda s: s.created)


def latest_set(cfg: BackupConfig, kind: str, ok_only: bool = True, database: str | None = None) -> retention.SetInfo | None:
    for s in reversed(list_sets(cfg)):
        if s.kind != kind or (ok_only and s.status == "failed"):
            continue
        if database:
            data = mf.load(s.path)
            if not any(a.get("database") == database for a in data.get("artifacts", [])):
                continue
        return s
    return None


def _write_manifest(set_dir: Path, data: dict, secondary: Path | None) -> None:
    payload = mf.dumps(data)
    write_bytes_verified(payload, set_dir / mf.MANIFEST_NAME)
    if secondary:
        write_bytes_verified(payload, secondary / mf.MANIFEST_NAME)


def _secondary_dir(cfg: BackupConfig, set_id: str) -> Path | None:
    return (cfg.target_secondary / cfg.env / set_id) if cfg.target_secondary else None


def _place(cfg: BackupConfig, res: RunResult, src: Path, set_dir: Path, rel: str, kind: str,
           database: str = "", verify_status: str = "not_applicable") -> dict:
    sha = copy_verified(src, set_dir / rel)
    sec = _secondary_dir(cfg, set_dir.name)
    if sec:
        try:
            copy_verified(src, sec / rel, expected_sha256=sha)
        except TransferError as exc:
            res.warn(f"destinazione secondaria: {exc}")
    size = (set_dir / rel).stat().st_size
    res.bytes += size
    return {"path": rel.replace("\\", "/"), "sha256": sha, "size": size, "kind": kind,
            "database": database, "verify_status": verify_status}


def _base_manifest(cfg: BackupConfig, set_id: str, kind: str) -> dict:
    data = mf.new_manifest(set_id, kind, cfg.env)
    data["app"] = mf.app_section()
    data["keys"] = mf.keys_section()
    last_host = latest_set(cfg, "host")
    data["host_manifest_ref"] = last_host.set_id if last_host else None
    return data


# ── FULL ─────────────────────────────────────────────────────────────────────

def _sqlite_backup(dst: Path) -> None:
    src_path = Path(connection.settings_dict["NAME"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    # closing(): il context manager di sqlite3 non chiude la connessione (file bloccato su Windows)
    with closing(sqlite3.connect(str(src_path))) as src, closing(sqlite3.connect(str(dst))) as out:
        src.backup(out)
    with closing(sqlite3.connect(str(dst))) as chk:
        result = chk.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise SqlError(f"integrity_check sulla copia SQLite: {result}")


def _sqlite_counts(path: Path, tables: list[str]) -> dict[str, int]:
    counts = {}
    with closing(sqlite3.connect(str(path))) as c:
        existing = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in tables:
            if t in existing:
                counts[t] = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    return counts


def _sqlite_migrations(path: Path) -> dict[str, str]:
    with closing(sqlite3.connect(str(path))) as c:
        return {app: name for app, name in c.execute("SELECT app, MAX(name) FROM django_migrations GROUP BY app")}


def run_full(cfg: BackupConfig, *, sql: SqlServer | None = None, dry_run: bool = False,
             databases: list[str] | None = None) -> RunResult:
    res = RunResult(kind="full", started_at=timezone.localtime().isoformat())
    t0 = time.monotonic()
    set_id = new_set_id("full")
    res.set_id = set_id
    set_dir = cfg.env_root / set_id
    data = _base_manifest(cfg, set_id, "full")
    hub_db = hub_database()
    targets = databases or ([hub_db] + [d for d in cfg.extra_databases if d != hub_db])
    res.database = ",".join(Path(d).name if not is_mssql() else d for d in targets)
    if dry_run:
        res.manifest = data
        res.warnings.append(f"dry-run: verrebbero salvati {targets} in {set_dir}")
        res.status = "ok"
        return res
    staging = cfg.staging / cfg.env
    staging.mkdir(parents=True, exist_ok=True)
    try:
        if is_mssql():
            sql = sql or SqlServer.from_settings(cfg.sql_timeout_s)
            data["sql"] = sql.server_info()
            for db in targets:
                safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in db)
                bak = staging / f"{safe}_FULL_{set_id[:15]}.bak"
                try:
                    info = sql.database_info(db)
                    sql.backup_full(db, bak)
                    sql.verify(bak)
                    head = sql.header(bak)
                    art = _place(cfg, res, bak, set_dir, f"db/{bak.name}", "full", db, "ok")
                    art["lsn"] = {"first": head["first_lsn"], "last": head["last_lsn"],
                                  "checkpoint": head["checkpoint_lsn"]}
                    data["artifacts"].append(art)
                    entry = {**info, "header": head}
                    if db == hub_db:
                        data["app"]["migrations"] = sql.applied_migrations(db)
                        data["row_counts"] = sql.row_counts(db, key_tables())
                    data["databases"].append(entry)
                    bak.unlink(missing_ok=True)   # solo dopo la copia verificata
                except (SqlError, TransferError, OSError) as exc:
                    res.status = "failed"
                    res.error = f"{db}: {exc}"
                    data["warnings"].append(res.error)
                    if db == hub_db:
                        break
        else:
            dbname = Path(hub_db).name or "db.sqlite3"
            copy = staging / f"{Path(dbname).stem}_FULL_{set_id[:15]}.sqlite3"
            _sqlite_backup(copy)
            data["app"]["migrations"] = _sqlite_migrations(copy)
            data["row_counts"] = _sqlite_counts(copy, key_tables())
            data["artifacts"].append(_place(cfg, res, copy, set_dir, f"db/{copy.name}", "full", dbname, "ok"))
            data["databases"].append({"name": dbname, "engine": "sqlite", "recovery_model": "n/a"})
            copy.unlink(missing_ok=True)
    except (SqlError, TransferError, OSError) as exc:
        res.status = "failed"
        res.error = str(exc)
    return _close_set(cfg, res, data, set_dir, t0)


def _close_set(cfg: BackupConfig, res: RunResult, data: dict, set_dir: Path, t0: float) -> RunResult:
    data["warnings"] = list(dict.fromkeys(data.get("warnings", []) + res.warnings + list(cfg.warnings)))
    if cfg.warnings and res.status == "ok":
        res.status = "warning"
    data["status"] = res.status
    data["duration_s"] = round(time.monotonic() - t0, 1)
    if data["artifacts"]:
        res.sha256 = data["artifacts"][0]["sha256"]
        res.verify_status = "ok" if all(a["verify_status"] in ("ok", "not_applicable") for a in data["artifacts"]) else "failed"
    try:
        set_dir.mkdir(parents=True, exist_ok=True)
        _write_manifest(set_dir, data, _secondary_dir(cfg, set_dir.name))
    except (OSError, mf.ManifestError, TransferError) as exc:
        res.status = "failed"
        res.error = (res.error + "; " if res.error else "") + f"manifest: {exc}"
    res.manifest = data
    return finish(cfg, res)


# ── LOG ──────────────────────────────────────────────────────────────────────

def _lsn(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return -1


def run_log(cfg: BackupConfig, *, sql: SqlServer | None = None, dry_run: bool = False, force: bool = False,
            now: datetime | None = None) -> RunResult:
    res = RunResult(kind="log", started_at=timezone.localtime().isoformat())
    now = now or timezone.localtime()
    if not force and not cfg.in_log_window(now.hour):
        res.warnings.append(f"fuori dalla finestra {cfg.log_window[0]:02d}-{cfg.log_window[1]:02d}: nessun backup del log")
        res.status = "ok"
        return res   # nessun set, nessuna registrazione: è il comportamento atteso
    if not is_mssql():
        res.status = "warning"
        res.error = "backup del log disponibile solo su SQL Server"
        return res
    t0 = time.monotonic()
    set_id = new_set_id("log", now)
    res.set_id = set_id
    set_dir = cfg.env_root / set_id
    data = _base_manifest(cfg, set_id, "log")
    sql = sql or SqlServer.from_settings(cfg.sql_timeout_s)
    hub_db = hub_database()
    targets = [hub_db] + [d for d in cfg.extra_databases if d != hub_db]
    res.database = ",".join(targets)
    if dry_run:
        res.manifest = data
        return res
    staging = cfg.staging / cfg.env
    staging.mkdir(parents=True, exist_ok=True)
    data["chain"] = {"databases": {}}
    done = 0
    for db in targets:
        base = latest_set(cfg, "full", database=db)
        if base is None:
            res.warn(f"{db}: nessun FULL di riferimento, backup del log saltato")
            continue
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in db)
        trn = staging / f"{safe}_LOG_{set_id[:15]}.trn"
        try:
            sql.backup_log(db, trn)
            sql.verify(trn)
            head = sql.header(trn)
            art = _place(cfg, res, trn, set_dir, f"db/{trn.name}", "log", db, "ok")
            art["lsn"] = {"first": head["first_lsn"], "last": head["last_lsn"]}
            data["artifacts"].append(art)
            prev_last = _previous_log_last_lsn(cfg, db, base.set_id)
            continuous = prev_last is None or _lsn(head["first_lsn"]) == prev_last
            if prev_last is None:
                # primo log dopo il FULL: deve coprire il LastLSN del FULL (FirstLSN <= LastLSN del FULL)
                full_last = _full_last_lsn(base, db)
                continuous = full_last is None or _lsn(head["first_lsn"]) <= full_last
            data["chain"]["databases"][db] = {
                "full_set_id": base.set_id, "first_lsn": head["first_lsn"], "last_lsn": head["last_lsn"],
                "previous_last_lsn": prev_last, "continuous": continuous,
            }
            data["chain"]["full_set_id"] = data["chain"].get("full_set_id") or base.set_id
            if not continuous:
                res.status = "failed"
                res.error = f"{db}: catena dei log interrotta (FirstLSN {head['first_lsn']} ≠ LastLSN precedente {prev_last})"
            trn.unlink(missing_ok=True)
            done += 1
        except LogBackupNotPossible as exc:
            res.warn(str(exc))
        except (SqlError, TransferError, OSError) as exc:
            res.status = "failed"
            res.error = f"{db}: {exc}"
    if done == 0:
        res.set_id = ""          # nessun set scritto
        res.manifest = {}
        if res.status != "failed":
            res.status = "warning"
        return finish(cfg, res)
    return _close_set(cfg, res, data, set_dir, t0)


def _log_sets_for(cfg: BackupConfig, full_set_id: str) -> list[retention.SetInfo]:
    return [s for s in list_sets(cfg) if s.kind == "log" and s.chain_base == full_set_id and s.status != "failed"]


def _previous_log_last_lsn(cfg: BackupConfig, db: str, full_set_id: str) -> int | None:
    for s in reversed(_log_sets_for(cfg, full_set_id)):
        chain = (mf.load(s.path).get("chain") or {}).get("databases", {}).get(db)
        if chain:
            return _lsn(chain["last_lsn"])
    return None


def _full_last_lsn(full_set: retention.SetInfo, db: str) -> int | None:
    for a in mf.load(full_set.path).get("artifacts", []):
        if a.get("database") == db and a.get("lsn"):
            return _lsn(a["lsn"].get("last"))
    return None


# ── FILES ────────────────────────────────────────────────────────────────────

def run_files(cfg: BackupConfig, *, dry_run: bool = False, roots: dict | None = None) -> RunResult:
    res = RunResult(kind="files", started_at=timezone.localtime().isoformat())
    t0 = time.monotonic()
    set_id = new_set_id("files")
    res.set_id = set_id
    set_dir = cfg.env_root / set_id
    data = _base_manifest(cfg, set_id, "files")
    prev = latest_set(cfg, "files")
    prev_index = files_mod.load_index(prev.path) if prev else {}
    fr = files_mod.backup_files(cfg.objects_root, prev_index, roots=roots, dry_run=dry_run)
    data["files"] = {"roots": {k: v["path"] for k, v in fr.index.items()}, "count": fr.files,
                     "new_objects": fr.new_objects, "new_bytes": fr.new_bytes, "total_bytes": fr.total_bytes,
                     "previous_set_id": prev.set_id if prev else None}
    for e in fr.errors[:50]:
        res.warn(e)
    if len(fr.errors) > 50:
        res.warn(f"... altri {len(fr.errors) - 50} file non salvati")
    if dry_run:
        res.manifest = data
        return res
    index_bytes = json.dumps(fr.index, ensure_ascii=False, indent=1).encode("utf-8")
    sha = write_bytes_verified(index_bytes, set_dir / "files" / "index.json")
    data["artifacts"].append({"path": "files/index.json", "sha256": sha, "size": len(index_bytes),
                              "kind": "files_index", "verify_status": "not_applicable"})
    res.bytes = fr.new_bytes
    sec = _secondary_dir(cfg, set_id)
    if sec:
        try:
            write_bytes_verified(index_bytes, sec / "files" / "index.json")
            sec_objects = cfg.target_secondary / cfg.env / "_objects"
            for root in fr.index.values():
                for entry in root["files"].values():
                    dst = files_mod.object_path(sec_objects, entry["sha256"])
                    if not dst.exists():
                        copy_verified(files_mod.object_path(cfg.objects_root, entry["sha256"]), dst,
                                      expected_sha256=entry["sha256"])
        except (OSError, TransferError) as exc:
            res.warn(f"destinazione secondaria: {exc}")
    return _close_set(cfg, res, data, set_dir, t0)


# ── HOST ─────────────────────────────────────────────────────────────────────

def _copy_env_separately(cfg: BackupConfig, set_id: str, res: RunResult) -> None:
    """Audit M10: il .env completo solo in BACKUP_ENV_DIR, mai accanto ai dati."""
    if not cfg.env_dir:
        res.warn("BACKUP_ENV_DIR non configurata: .env completo non copiato (Recovery Kit obbligatorio)")
        return
    env_dir = Path(cfg.env_dir)
    try:
        if str(env_dir.resolve()).lower().startswith(str(cfg.target.resolve()).lower()):
            res.warn("BACKUP_ENV_DIR è dentro BACKUP_TARGET: .env non copiato")
            return
    except OSError:
        pass
    for candidate in (Path(settings.BASE_DIR).parent / "config" / ".env", Path(settings.BASE_DIR) / ".env"):
        if candidate.exists():
            try:
                copy_verified(candidate, env_dir / cfg.env / set_id / ".env")
            except (OSError, TransferError) as exc:
                res.warn(f"copia .env in BACKUP_ENV_DIR: {exc}")
            return


def run_host(cfg: BackupConfig, *, dry_run: bool = False) -> RunResult:
    res = RunResult(kind="host", started_at=timezone.localtime().isoformat())
    t0 = time.monotonic()
    set_id = new_set_id("host")
    res.set_id = set_id
    set_dir = cfg.env_root / set_id
    data = _base_manifest(cfg, set_id, "host")
    if dry_run:
        res.manifest = data
        return res
    work = cfg.staging / cfg.env / f"host_{set_id}"
    try:
        host_data, warns = host_manifest.collect(cfg.env, work)
        for w in warns:
            res.warn(w)
        for path in sorted(p for p in work.rglob("*") if p.is_file()):
            rel = "host/" + path.relative_to(work).as_posix()
            data["artifacts"].append(_place(cfg, res, path, set_dir, rel, "host"))
        from core.build_info import read_build_info

        zp = host_manifest.find_release_zip(read_build_info() or {})
        if zp:
            dst = cfg.env_root / "_releases" / zp.name
            if not dst.exists():
                copy_verified(zp, dst)
            data["release_ref"] = f"_releases/{zp.name}"
        else:
            res.warn("zip della release attiva non trovato in shared\\packages (sviluppo o pacchetto rimosso)")
        _copy_env_separately(cfg, set_id, res)
        for h in host_data.get("public_hostnames", []):
            if not h.get("points_here"):
                res.warn(f"{h['name']}: il DNS non punta a questa macchina")
    except (OSError, TransferError) as exc:
        res.status = "failed"
        res.error = str(exc)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return _close_set(cfg, res, data, set_dir, t0)


# ── RETENTION ────────────────────────────────────────────────────────────────

def drill_protected_sets() -> set[str]:
    try:
        from monitoring.models import RestoreDrill

        last = RestoreDrill.objects.filter(status="ok").order_by("-started_at").first()
        return {s for s in (last.full_set_id, last.last_log_set_id) if s} if last else set()
    except Exception:
        return set()


def run_retention(cfg: BackupConfig, *, dry_run: bool = True, now: datetime | None = None, log=print) -> RunResult:
    res = RunResult(kind="retention", started_at=timezone.localtime().isoformat())
    now = (now or timezone.localtime()).replace(tzinfo=None)
    sets = list_sets(cfg)
    plan_ = retention.plan(sets, now, keep_daily=cfg.keep_daily, keep_weekly=cfg.keep_weekly,
                           keep_monthly=cfg.keep_monthly, keep_log_days=cfg.keep_log_days,
                           protected=drill_protected_sets())
    for sid, why in sorted(plan_.delete.items()):
        log(f"{'[dry-run] ' if dry_run else ''}da eliminare: {sid} ({why})")
    removed = 0
    if not dry_run:
        removed = retention.apply(plan_, sets, log=log)
        if cfg.target_secondary:
            sec_sets = list_sets(cfg, cfg.target_secondary / cfg.env)
            retention.apply(retention.RetentionPlan(delete={s.set_id: plan_.delete[s.set_id] for s in sec_sets
                                                            if s.set_id in plan_.delete}), sec_sets, log=log)
        # set incompleti (senza manifest) più vecchi di 2 giorni
        limit = now - timedelta(days=2)
        for d in cfg.env_root.iterdir() if cfg.env_root.exists() else []:
            parsed = retention.parse_set_id(d.name) if d.is_dir() else None
            if parsed and not (d / mf.MANIFEST_NAME).exists() and parsed[0] < limit:
                shutil.rmtree(d, ignore_errors=True)
                log(f"eliminato set incompleto {d.name}")
    kept_files = [s for s in list_sets(cfg) if s.kind == "files"] if not dry_run else \
        [s for s in sets if s.kind == "files" and s.set_id in plan_.keep]
    refs = files_mod.referenced_objects([files_mod.load_index(s.path) for s in kept_files])
    gc_n, gc_bytes = retention.gc_objects(cfg.objects_root, refs, dry_run=dry_run)
    res.manifest = {"keep": plan_.keep, "delete": plan_.delete, "removed": removed,
                    "gc_objects": gc_n, "gc_bytes": gc_bytes, "dry_run": dry_run}
    res.bytes = gc_bytes
    log(f"retention: {len(plan_.keep)} set conservati, {len(plan_.delete)} da eliminare, "
        f"{gc_n} oggetti file non referenziati ({gc_bytes // 1048576} MB){' — dry-run' if dry_run else ''}")
    if dry_run:
        return res
    return finish(cfg, res)


# ── VERIFICA ─────────────────────────────────────────────────────────────────

def verify_set(cfg: BackupConfig, set_dir: Path, *, sql: SqlServer | None = None) -> RunResult:
    res = RunResult(kind="verify", started_at=timezone.localtime().isoformat(), set_id=set_dir.name)
    try:
        data = mf.load(set_dir)
    except mf.ManifestError as exc:
        res.status = "failed"
        res.error = str(exc)
        return finish(cfg, res)
    staging = cfg.staging / cfg.env / "verify"
    for art in data.get("artifacts", []):
        p = set_dir / art["path"]
        if not p.exists():
            res.status = "failed"
            res.error = f"artefatto mancante: {art['path']}"
            continue
        if sha256_file(p) != art["sha256"]:
            res.status = "failed"
            res.error = f"hash diverso: {art['path']}"
            continue
        res.bytes += art["size"]
        if art.get("kind") in ("full", "log") and is_mssql():
            local = staging / p.name
            try:
                copy_verified(p, local, expected_sha256=art["sha256"])
                (sql or SqlServer.from_settings(cfg.sql_timeout_s)).verify(local)
            except (SqlError, TransferError, OSError) as exc:
                res.status = "failed"
                res.error = f"VERIFYONLY {art['path']}: {exc}"
            finally:
                local.unlink(missing_ok=True)
    if data["type"] == "log":
        for db, chain in ((data.get("chain") or {}).get("databases") or {}).items():
            if not chain.get("continuous", True):
                res.status = "failed"
                res.error = f"{db}: catena log interrotta in questo set"
        if not (set_dir.parent / (data.get("chain") or {}).get("full_set_id", "-")).exists():
            res.warn("il FULL di riferimento di questo log non è più nel target")
    res.verify_status = "ok" if res.status != "failed" else "failed"
    res.manifest = {"set_id": set_dir.name, "type": data["type"], "artifacts": len(data.get("artifacts", []))}
    return finish(cfg, res)
