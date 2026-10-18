"""Prova di ripristino automatica (BUILD_SPEC R2 §4.3). Lanciata da Task Scheduler la domenica.

  manage.py hub_restore_drill                         # ultimo FULL verificato + tutti i LOG
  manage.py hub_restore_drill --stopat "2026-10-16 14:30"
  manage.py hub_restore_drill --samples 10 --json

Ripristina su ``<db>_drill`` (mai sul DB vero, mai WITH REPLACE), controlla integrità,
migrazioni, conteggi e decifratura di campioni, poi elimina sempre la copia.
Exit code: 0 = OK, 1 = avvisi (es. spazio insufficiente), 2 = fallita.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from core.backup_engine.config import load_config
from core.backup_engine.drill import run_drill


class Command(BaseCommand):
    help = "Prova di ripristino su copia _drill con controlli di integrità e RTO misurato."

    def add_arguments(self, parser):
        parser.add_argument("--env", default=None)
        parser.add_argument("--target", default=None)
        parser.add_argument("--stopat", default=None, help="Punto nel tempo (YYYY-MM-DD HH:MM).")
        parser.add_argument("--samples", type=int, default=None, help="File privati da decifrare per radice.")
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--no-exit-code", action="store_true")
        parser.add_argument("--keep", action="store_true",
                            help="Recupero selettivo: lascia la copia <db>_drill (da eliminare a mano dopo).")

    def handle(self, *args, **opts):
        cfg = load_config(opts["env"], opts["target"])
        stopat = None
        if opts["stopat"]:
            try:
                stopat = datetime.strptime(opts["stopat"], "%Y-%m-%d %H:%M")
            except ValueError as exc:
                raise CommandError("--stopat atteso nel formato YYYY-MM-DD HH:MM") from exc
        res = run_drill(cfg, stopat=stopat, samples=opts["samples"], keep=opts["keep"])
        for name in res.get("kept_databases", []):
            self.stdout.write(self.style.WARNING(
                f"Copia {name} lasciata sull'istanza per il recupero selettivo: eliminarla a mano "
                f"(ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [{name}])."))
        if opts["json"]:
            self.stdout.write(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        else:
            style = {"ok": self.style.SUCCESS, "warning": self.style.WARNING}.get(res["status"], self.style.ERROR)
            self.stdout.write(style(f"Prova di ripristino: {res['status'].upper()} · FULL {res['full_set_id'] or '-'}"
                                    f" · ultimo log {res['last_log_set_id'] or '-'} · RTO DB {res['rto_seconds']} s"))
            for name, check in res["checks"].items():
                self.stdout.write(f"  {name}: {str(check.get('status', '')).upper()}")
            if res["error"]:
                self.stdout.write(self.style.ERROR(f"  errore: {res['error']}"))
            for err in res.get("cleanup_errors", []):
                self.stdout.write(self.style.ERROR(f"  pulizia: {err}"))
        code = {"ok": 0, "warning": 1}.get(res["status"], 2)
        if code and not opts["no_exit_code"]:
            sys.exit(code)
