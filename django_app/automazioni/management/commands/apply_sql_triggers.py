"""
Management command: apply_sql_triggers
Esegue (nell'ordine):
  1. Creazione idempotente della tabella dbo.automation_event_queue (DDL da sql/automation_event_queue.sql)
  2. DROP + CREATE dei trigger SQL Server in automazioni/migrations/trg_*.sql

- Idempotente: usa IF OBJECT_ID ... IS NULL per la tabella; DROP TRIGGER IF EXISTS per i trigger.
- Silenzioso su SQLite (dev): salta l'esecuzione senza errori.
- Auto-discovery: trova tutti i file trg_*.sql in automazioni/migrations/.
- Da chiamare in deploy-release.ps1 subito dopo migrate.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection

logger = logging.getLogger(__name__)

# DDL della tabella di supporto: due livelli su da __file__ -> django_app/ -> sql/
_SQL_DIR = Path(__file__).resolve().parents[4] / "sql"
_QUEUE_TABLE_DDL = _SQL_DIR / "automation_event_queue.sql"

# Directory dove vivono i file trigger
_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def _split_go_batches(sql: str) -> list[str]:
    """Divide uno script SQL con separatori GO in batch singoli eseguibili via pyodbc."""
    batches = re.split(r"^\s*GO\s*$", sql, flags=re.IGNORECASE | re.MULTILINE)
    return [b.strip() for b in batches if b.strip()]


def apply_queue_table_ddl(*, dry_run: bool = False) -> dict:
    """Crea (idempotente) la tabella dbo.automation_event_queue leggendo sql/automation_event_queue.sql."""
    if not _QUEUE_TABLE_DDL.exists():
        return {"status": "skip", "message": f"File DDL non trovato: {_QUEUE_TABLE_DDL}"}

    sql_content = _QUEUE_TABLE_DDL.read_text(encoding="utf-8")
    batches = _split_go_batches(sql_content)

    if dry_run:
        return {"status": "dry-run", "batches": len(batches)}

    try:
        with connection.cursor() as cursor:
            for batch in batches:
                cursor.execute(batch)
        return {"status": "ok", "batches": len(batches)}
    except Exception as exc:
        logger.error("apply_queue_table_ddl: errore: %s", exc)
        return {"status": "error", "message": str(exc)}


def _is_sql_server() -> bool:
    vendor = getattr(connection, "vendor", "")
    return vendor == "microsoft" or "mssql" in vendor.lower()


def _trigger_name_from_sql(sql: str) -> str | None:
    """Estrae il nome del trigger dalla prima riga CREATE TRIGGER."""
    for line in sql.splitlines():
        line = line.strip()
        if line.upper().startswith("CREATE TRIGGER"):
            parts = line.split()
            if len(parts) >= 3:
                # Rimuove eventuali [dbo]. e parentesi quadre
                name = parts[2].strip("[]")
                if "." in name:
                    name = name.split(".")[-1].strip("[]")
                return name
    return None


def apply_trigger(sql_path: Path, *, dry_run: bool = False) -> dict:
    sql = sql_path.read_text(encoding="utf-8").strip()
    trigger_name = _trigger_name_from_sql(sql)

    if not trigger_name:
        return {"file": sql_path.name, "status": "error", "message": "Nome trigger non trovato nel file SQL."}

    drop_sql = f"DROP TRIGGER IF EXISTS [dbo].[{trigger_name}];"

    if dry_run:
        return {"file": sql_path.name, "status": "dry-run", "trigger": trigger_name}

    try:
        with connection.cursor() as cursor:
            cursor.execute(drop_sql)
            cursor.execute(sql)
        return {"file": sql_path.name, "status": "ok", "trigger": trigger_name}
    except Exception as exc:
        logger.error("apply_sql_triggers: errore su %s: %s", sql_path.name, exc)
        return {"file": sql_path.name, "status": "error", "trigger": trigger_name, "message": str(exc)}


class Command(BaseCommand):
    help = "Applica (DROP + CREATE) i trigger SQL Server in automazioni/migrations/trg_*.sql. Idempotente."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra i file che verrebbero applicati senza eseguirli.",
        )
        parser.add_argument(
            "--file",
            dest="files",
            action="append",
            metavar="FILENAME",
            help="Applica solo questo file (nome, es. trg_tickets_automation.sql). Ripetibile.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        filter_files = options.get("files") or []

        if not _is_sql_server():
            self.stdout.write(
                self.style.WARNING(
                    f"apply_sql_triggers: database vendor '{connection.vendor}' non è SQL Server — skip."
                )
            )
            return

        errors = 0

        # Step 1: crea la tabella automation_event_queue se non esiste
        ddl_result = apply_queue_table_ddl(dry_run=dry_run)
        ddl_status = ddl_result["status"]
        if ddl_status == "ok":
            self.stdout.write(self.style.SUCCESS(f"  [OK]      automation_event_queue DDL ({ddl_result['batches']} batch)"))
        elif ddl_status == "dry-run":
            self.stdout.write(f"  [dry-run] automation_event_queue DDL ({ddl_result['batches']} batch)")
        elif ddl_status == "skip":
            self.stdout.write(self.style.WARNING(f"  [SKIP]    automation_event_queue DDL: {ddl_result['message']}"))
        else:
            errors += 1
            self.stdout.write(self.style.ERROR(f"  [ERRORE]  automation_event_queue DDL: {ddl_result['message']}"))

        # Step 2: applica i trigger
        sql_files = sorted(_MIGRATIONS_DIR.glob("trg_*.sql"))
        if not sql_files:
            self.stdout.write(self.style.WARNING("Nessun file trg_*.sql trovato in migrations/."))
            return

        if filter_files:
            sql_files = [f for f in sql_files if f.name in filter_files]
            if not sql_files:
                self.stdout.write(self.style.ERROR(f"Nessun file corrispondente a: {filter_files}"))
                return

        mode = "dry-run" if dry_run else "apply"
        self.stdout.write(f"apply_sql_triggers [{mode}] — {len(sql_files)} file trovati in {_MIGRATIONS_DIR}")

        for sql_path in sql_files:
            result = apply_trigger(sql_path, dry_run=dry_run)
            status = result["status"]
            trigger = result.get("trigger", "?")
            message = result.get("message", "")

            if status == "ok":
                self.stdout.write(self.style.SUCCESS(f"  [OK]      {sql_path.name}  ({trigger})"))
            elif status == "dry-run":
                self.stdout.write(f"  [dry-run] {sql_path.name}  ({trigger})")
            else:
                errors += 1
                self.stdout.write(self.style.ERROR(f"  [ERRORE]  {sql_path.name}  ({trigger}): {message}"))

        if errors:
            raise SystemExit(f"apply_sql_triggers: {errors} trigger non applicati.")

        if not dry_run:
            self.stdout.write(self.style.SUCCESS("Trigger SQL applicati con successo."))
