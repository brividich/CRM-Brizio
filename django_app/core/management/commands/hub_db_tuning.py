"""Tuning del database SQL Server: limite del Query Store (BUILD_SPEC R0.2.7).

  manage.py hub_db_tuning                         # dry-run: stato attuale e comando previsto
  manage.py hub_db_tuning --query-store-max-mb 100 --apply
  manage.py hub_db_tuning --compatibility-level 170 [--apply]   # S1.4: solo dopo 2 settimane su SQL 2025

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
        parser.add_argument("--enable", action="store_true",
                            help="Se il Query Store è spento, lo accende (solo insieme ad --apply).")
        parser.add_argument("--compatibility-level", type=int, default=None,
                            help="Imposta il compatibility level del DB (es. 170 dopo 2 settimane su SQL 2025; "
                                 "il valore precedente per tornare indietro). Solo con --apply modifica.")
        parser.add_argument("--json", action="store_true")

    def _compatibility(self, opts) -> None:
        """Compatibility level: separato dal Query Store, mai implicito (BUILD_SPEC S1.4)."""
        wanted = opts["compatibility_level"]
        with connection.cursor() as cur:
            cur.execute(
                "SELECT compatibility_level, CAST(SERVERPROPERTY('ProductMajorVersion') AS INT) "
                "FROM sys.databases WHERE name = DB_NAME()"
            )
            current, major = cur.fetchone()
        massimo = int(major) * 10
        if wanted not in (100, 110, 120, 130, 140, 150, 160, 170) or wanted > massimo:
            raise CommandError(f"Compatibility level {wanted} non ammesso su questo server (massimo {massimo}).")
        sql = f"ALTER DATABASE CURRENT SET COMPATIBILITY_LEVEL = {int(wanted)}"
        payload = {"apply": opts["apply"], "current": current, "wanted": wanted, "server_max": massimo, "sql": sql}
        if int(current) == wanted:
            payload["skipped"] = "already_set"
        elif opts["apply"]:
            with connection.cursor() as cur:
                cur.execute(sql)
            payload["after"] = wanted
        if opts["json"]:
            self.stdout.write(json.dumps(payload, default=str, indent=2))
            return
        self.stdout.write(f"Compatibility level attuale: {current} (massimo del server: {massimo}).")
        if payload.get("skipped"):
            self.stdout.write("Già impostato: nessuna modifica.")
        elif opts["apply"]:
            self.stdout.write(self.style.SUCCESS(
                f"Applicato: {current} → {wanted}. Per tornare indietro: --compatibility-level {current} --apply. "
                "Annotarlo nel CHANGELOG."))
        else:
            self.stdout.write(f"Dry-run. Con --apply verrebbe eseguito:\n  {sql}\n"
                              f"(per tornare indietro: --compatibility-level {current} --apply)")

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
        if opts["compatibility_level"] is not None:
            return self._compatibility(opts)
        max_mb = opts["query_store_max_mb"]
        if not 10 <= max_mb <= 10240:
            raise CommandError("--query-store-max-mb fuori intervallo (10–10240).")
        sql = (
            "ALTER DATABASE CURRENT SET QUERY_STORE (OPERATION_MODE = READ_WRITE, "
            f"MAX_STORAGE_SIZE_MB = {int(max_mb)}, SIZE_BASED_CLEANUP_MODE = AUTO, QUERY_CAPTURE_MODE = AUTO)"
        )
        before = self._state()
        after = None
        spento = str(before.get("actual_state", "")).upper() == "OFF"
        if spento and not opts["enable"]:
            # Non si cambia lo stato del Query Store senza una scelta esplicita.
            self.stdout.write("Query Store spento su questo database: nessuna modifica "
                              "(usare --enable insieme ad --apply per accenderlo con il limite).")
            if opts["json"]:
                self.stdout.write(json.dumps({"apply": False, "before": before, "skipped": "query_store_off"}, default=str))
            return
        if opts["apply"]:
            with connection.cursor() as cur:
                if spento:
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
