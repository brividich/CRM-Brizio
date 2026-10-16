"""Tuning del database SQL Server: limite del Query Store (BUILD_SPEC R0.2.7).

  manage.py hub_db_tuning                         # dry-run: stato attuale e comando previsto
  manage.py hub_db_tuning --query-store-max-mb 100 --apply

Il Query Store non viene disattivato: si limita la dimensione e si attiva la
pulizia automatica. In produzione ``--apply`` lo esegue solo Brizio (dopo S1).
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Mostra (o con --apply imposta) il limite del Query Store del database corrente."

    def add_arguments(self, parser):
        parser.add_argument("--query-store-max-mb", type=int, default=100)
        parser.add_argument("--apply", action="store_true", help="Esegue l'ALTER DATABASE (default: dry-run).")
        parser.add_argument("--json", action="store_true")

    def _state(self) -> dict:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT actual_state_desc, desired_state_desc, current_storage_size_mb, max_storage_size_mb, "
                "size_based_cleanup_mode_desc, query_capture_mode_desc FROM sys.database_query_store_options"
            )
            row = cur.fetchone()
        keys = ("actual_state", "desired_state", "current_storage_mb", "max_storage_mb",
                "size_based_cleanup", "query_capture_mode")
        return dict(zip(keys, row)) if row else {}

    def handle(self, *args, **opts):
        if connection.vendor != "microsoft":
            self.stdout.write("hub_db_tuning: supportato solo su SQL Server (database corrente: "
                              f"{connection.vendor}). Nessuna azione.")
            return
        max_mb = opts["query_store_max_mb"]
        if not 10 <= max_mb <= 10240:
            raise CommandError("--query-store-max-mb fuori intervallo (10–10240).")
        sql = (
            "ALTER DATABASE CURRENT SET QUERY_STORE (OPERATION_MODE = READ_WRITE, "
            f"MAX_STORAGE_SIZE_MB = {int(max_mb)}, SIZE_BASED_CLEANUP_MODE = AUTO, QUERY_CAPTURE_MODE = AUTO)"
        )
        before = self._state()
        after = None
        if opts["apply"]:
            with connection.cursor() as cur:
                cur.execute("ALTER DATABASE CURRENT SET QUERY_STORE = ON")
                cur.execute(sql)
            after = self._state()
        payload = {"apply": opts["apply"], "sql": sql, "before": before, "after": after}
        if opts["json"]:
            self.stdout.write(json.dumps(payload, default=str, indent=2))
            return
        self.stdout.write(f"Query Store attuale: {before or 'non disponibile'}")
        if opts["apply"]:
            self.stdout.write(self.style.SUCCESS(f"Applicato. Stato: {after}"))
        else:
            self.stdout.write(f"Dry-run. Con --apply verrebbe eseguito:\n  {sql}")
