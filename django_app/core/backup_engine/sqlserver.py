"""Operazioni SQL Server via sqlcmd (backup, verifica, header) per il motore di backup.

Sempre ``-b`` (exit code ≠ 0 su errore) e timeout configurabile. Autenticazione:
Windows (``-E``) se ``DB_USER`` è vuoto, altrimenti utente SQL con la password
passata nella variabile d'ambiente ``SQLCMDPASSWORD`` (mai sulla riga di comando).
Il runner è iniettabile: i test simulano sqlcmd con output sintetici.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from django.conf import settings

SEP = "\x1f"

_SQLCMD_CANDIDATES = (
    r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\180\Tools\Binn\SQLCMD.EXE",
    r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\SQLCMD.EXE",
    r"C:\Program Files\Microsoft SQL Server\170\Tools\Binn\SQLCMD.EXE",
    r"C:\Program Files\Microsoft SQL Server\160\Tools\Binn\SQLCMD.EXE",
    r"C:\Program Files\Microsoft SQL Server\150\Tools\Binn\SQLCMD.EXE",
)


class SqlError(RuntimeError):
    pass


class LogBackupNotPossible(SqlError):
    """Backup del log richiesto su un DB in recovery SIMPLE."""


def find_sqlcmd() -> str:
    for candidate in _SQLCMD_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    found = shutil.which("sqlcmd")
    if found:
        return found
    raise SqlError("sqlcmd non trovato: installare gli strumenti da riga di comando di SQL Server.")


def quote_name(name: str) -> str:
    return "[" + str(name).replace("]", "]]") + "]"


def quote_literal(value: str) -> str:
    return "N'" + str(value).replace("'", "''") + "'"


Runner = Callable[[list[str], int, dict], subprocess.CompletedProcess]


def _default_runner(args: list[str], timeout: int, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, env=env)


@dataclass
class SqlServer:
    host: str
    user: str = ""
    password: str = ""
    timeout_s: int = 3600
    runner: Runner | None = None
    sqlcmd: str | None = None

    @classmethod
    def from_settings(cls, timeout_s: int = 3600, runner: Runner | None = None) -> "SqlServer":
        db = settings.DATABASES.get("default", {})
        return cls(host=str(db.get("HOST") or "localhost"), user=str(db.get("USER") or ""),
                   password=str(db.get("PASSWORD") or ""), timeout_s=timeout_s, runner=runner)

    # ── esecuzione ───────────────────────────────────────────────────────────

    def _base_args(self, database: str) -> tuple[list[str], dict]:
        exe = self.sqlcmd or (find_sqlcmd() if self.runner is None else "sqlcmd")
        args = [exe, "-S", self.host, "-d", database, "-b", "-C", "-t", str(self.timeout_s)]
        env = dict(os.environ)
        if self.user:
            args += ["-U", self.user]
            env["SQLCMDPASSWORD"] = self.password
        else:
            args += ["-E"]
        return args, env

    def run(self, sql: str, database: str = "master", headers: bool = False) -> list[list[str]]:
        args, env = self._base_args(database)
        # -h -1: nessuna intestazione. Con intestazioni si lascia il default (una volta sola):
        # "-h 1" la ripeterebbe a ogni riga.
        args += ["-W", "-s", SEP] + ([] if headers else ["-h", "-1"]) + ["-Q", f"SET NOCOUNT ON; {sql}"]
        try:
            proc = (self.runner or _default_runner)(args, self.timeout_s + 30, env)
        except subprocess.TimeoutExpired as exc:
            raise SqlError(f"Timeout sqlcmd dopo {self.timeout_s} s") from exc
        except FileNotFoundError as exc:
            raise SqlError("sqlcmd non trovato") from exc
        out = (proc.stdout or "")
        if proc.returncode != 0:
            msg = (proc.stderr or out).strip()
            raise SqlError(_first_error(msg) or f"sqlcmd exit {proc.returncode}")
        rows = []
        for line in out.splitlines():
            if not line.strip():
                continue
            rows.append([c.strip() for c in line.split(SEP)])
        return rows

    def run_dicts(self, sql: str, database: str = "master") -> list[dict]:
        """Esegue con intestazioni e restituisce dict per colonna (per RESTORE HEADERONLY/FILELISTONLY)."""
        rows = self.run(sql, database, headers=True)
        if not rows:
            return []
        header = rows[0]
        data = [r for r in rows[1:] if not all(set(c) <= {"-"} for c in r) and r != header]
        return [dict(zip(header, r)) for r in data]

    # ── informazioni ─────────────────────────────────────────────────────────

    def server_info(self) -> dict:
        r = self.run(
            "SELECT CAST(SERVERPROPERTY('ProductVersion') AS NVARCHAR(64)), "
            "CAST(SERVERPROPERTY('Edition') AS NVARCHAR(128)), "
            "CAST(SERVERPROPERTY('Collation') AS NVARCHAR(128)), "
            "CAST(SERVERPROPERTY('ServerName') AS NVARCHAR(256))"
        )[0]
        return {"product_version": r[0], "edition": r[1], "collation": r[2], "server_name": r[3]}

    def database_info(self, db: str) -> dict:
        rows = self.run(
            "SELECT d.recovery_model_desc, CAST(DATABASEPROPERTYEX(d.name, 'Collation') AS NVARCHAR(128)), "
            "d.compatibility_level, d.log_reuse_wait_desc, d.state_desc "
            f"FROM sys.databases d WHERE d.name = {quote_literal(db)}"
        )
        if not rows:
            raise SqlError(f"Database {db!r} non trovato.")
        recovery, collation, compat, log_wait, state = rows[0]
        files = self.run(
            "SELECT name, physical_name, type_desc, CAST(size AS BIGINT) * 8 / 1024, "
            "CAST(FILEPROPERTY(name, 'SpaceUsed') AS BIGINT) * 8 / 1024 FROM sys.database_files",
            database=db,
        )
        lsn = self.run(
            "SELECT TOP 1 CAST(last_lsn AS NVARCHAR(40)) FROM msdb.dbo.backupset "
            f"WHERE database_name = {quote_literal(db)} ORDER BY backup_finish_date DESC"
        )
        return {
            "name": db, "recovery_model": recovery, "collation": collation, "compatibility_level": int(compat),
            "log_reuse_wait": log_wait, "state": state,
            "files": [{"logical": f[0], "physical": f[1], "type": f[2],
                       "allocated_mb": int(f[3] or 0), "used_mb": int(f[4] or 0) if f[4] not in ("", "NULL") else None}
                      for f in files],
            "allocated_mb": sum(int(f[3] or 0) for f in files),
            "last_backup_lsn": lsn[0][0] if lsn else None,
        }

    def row_counts(self, db: str, tables: list[str]) -> dict[str, int]:
        if not tables:
            return {}
        names = ", ".join(quote_literal(t) for t in tables)
        rows = self.run(
            "SELECT t.name, SUM(p.row_count) FROM sys.dm_db_partition_stats p "
            "JOIN sys.tables t ON t.object_id = p.object_id "
            f"WHERE p.index_id IN (0,1) AND t.name IN ({names}) GROUP BY t.name",
            database=db,
        )
        return {r[0]: int(r[1] or 0) for r in rows}

    def applied_migrations(self, db: str) -> dict[str, str]:
        """Ultima migrazione applicata per app (da django_migrations)."""
        rows = self.run(
            "SELECT app, MAX(name) FROM django_migrations GROUP BY app", database=db,
        )
        return {r[0]: r[1] for r in rows}

    # ── backup e verifica ────────────────────────────────────────────────────

    def backup_full(self, db: str, path: Path) -> None:
        # Express non supporta COMPRESSION.
        self.run(f"BACKUP DATABASE {quote_name(db)} TO DISK = {quote_literal(str(path))} "
                 "WITH CHECKSUM, INIT, FORMAT, STATS = 10")

    def backup_log(self, db: str, path: Path) -> None:
        info = self.run(f"SELECT recovery_model_desc FROM sys.databases WHERE name = {quote_literal(db)}")
        if not info:
            raise SqlError(f"Database {db!r} non trovato.")
        if info[0][0].upper() == "SIMPLE":
            raise LogBackupNotPossible(
                f"{db}: recovery model SIMPLE, backup del log impossibile "
                "(passaggio a FULL: manage.py hub_backup_set_recovery --full --confirm)."
            )
        self.run(f"BACKUP LOG {quote_name(db)} TO DISK = {quote_literal(str(path))} WITH CHECKSUM, INIT, FORMAT")

    def verify(self, path: Path) -> None:
        self.run(f"RESTORE VERIFYONLY FROM DISK = {quote_literal(str(path))} WITH CHECKSUM")

    def header(self, path: Path) -> dict:
        rows = self.run_dicts(f"RESTORE HEADERONLY FROM DISK = {quote_literal(str(path))}")
        if not rows:
            raise SqlError(f"HEADERONLY vuoto per {path}")
        h = rows[0]
        return {
            "backup_type": int(h.get("BackupType") or 0),       # 1 = database, 2 = log
            "database_name": h.get("DatabaseName", ""),
            "first_lsn": h.get("FirstLSN", ""),
            "last_lsn": h.get("LastLSN", ""),
            "checkpoint_lsn": h.get("CheckpointLSN", ""),
            "database_backup_lsn": h.get("DatabaseBackupLSN", ""),
            "backup_finish_date": h.get("BackupFinishDate", ""),
            "has_checksums": h.get("HasBackupChecksums", "") in ("1", "True"),
            "compatibility_level": h.get("CompatibilityLevel", ""),
            "collation": h.get("Collation", ""),
            "software_version_major": h.get("SoftwareVersionMajor", ""),
            "recovery_model": h.get("RecoveryModel", ""),
        }

    def filelist(self, path: Path) -> list[dict]:
        rows = self.run_dicts(f"RESTORE FILELISTONLY FROM DISK = {quote_literal(str(path))}")
        return [{"logical": r.get("LogicalName", ""), "physical": r.get("PhysicalName", ""),
                 "type": r.get("Type", ""), "size": r.get("Size", "")} for r in rows]


def _first_error(text: str) -> str:
    """Prima riga «Msg N, Level…» con il testo che la segue (formato sqlcmd)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        if line.startswith(("Msg ", "Messaggio ")):    # sqlcmd localizzato
            detail = lines[i + 1] if i + 1 < len(lines) else ""
            return f"{line} {detail}".strip()[:400]
    for line in lines:
        if "Error" in line or "Errore" in line:
            return line[:400]
    return text.strip()[:400]
