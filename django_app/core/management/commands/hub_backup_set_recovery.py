"""Cambio del recovery model del database dell'HUB (BUILD_SPEC R1 §3.4, S1.4).

  manage.py hub_backup_set_recovery --full              # dry-run: stato e cosa farebbe
  manage.py hub_backup_set_recovery --full --confirm    # FULL + backup FULL immediato (avvia la catena)
  manage.py hub_backup_set_recovery --simple --confirm  # ritorno a SIMPLE (rollback)

Solo il DB dell'HUB: i DB di BACKUP_EXTRA_DATABASES mantengono il loro recovery model.
In produzione lo esegue solo Brizio, DOPO audit_archive --run e la migrazione a SQL 2025.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from core.backup_engine import engine
from core.backup_engine.config import load_config
from core.backup_engine.sqlserver import SqlServer, quote_name


class Command(BaseCommand):
    help = "Imposta il recovery model del DB dell'HUB (FULL avvia subito un backup FULL)."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--full", action="store_true")
        mode.add_argument("--simple", action="store_true")
        parser.add_argument("--confirm", action="store_true", help="Esegue davvero (senza: dry-run).")
        parser.add_argument("--env", default=None)

    def handle(self, *args, **opts):
        if connection.vendor != "microsoft":
            raise CommandError("Disponibile solo su SQL Server.")
        cfg = load_config(opts["env"])
        db = engine.hub_database()
        sql = SqlServer.from_settings(cfg.sql_timeout_s)
        info = sql.database_info(db)
        wanted = "FULL" if opts["full"] else "SIMPLE"
        self.stdout.write(f"{db}: recovery model attuale {info['recovery_model']}, richiesto {wanted}.")
        if info["recovery_model"].upper() == wanted:
            self.stdout.write("Già impostato: nessuna modifica.")
            return
        if not opts["confirm"]:
            self.stdout.write(f"Dry-run. Con --confirm: ALTER DATABASE {quote_name(db)} SET RECOVERY {wanted}"
                              + (" e backup FULL immediato." if wanted == "FULL" else "."))
            return
        sql.run(f"ALTER DATABASE {quote_name(db)} SET RECOVERY {wanted}")
        self.stdout.write(self.style.SUCCESS(f"Recovery model impostato a {wanted}."))
        if wanted == "FULL":
            self.stdout.write("Backup FULL immediato per avviare la catena dei log...")
            res = engine.run_full(cfg, sql=sql, databases=[db])
            if res.status == "failed":
                raise CommandError(f"Backup FULL fallito: {res.error}. Finché non riesce i log non sono "
                                   "ripristinabili: rilanciare manage.py hub_backup --type full.")
            self.stdout.write(self.style.SUCCESS(f"Catena avviata dal set {res.set_id}. Ora registrare il task "
                                                 "del log orario (register-backup-tasks.ps1)."))
