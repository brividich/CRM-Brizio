"""Motore di backup verificabile (BUILD_SPEC R1). Lanciato da Task Scheduler, non da qcluster.

  manage.py hub_backup --type full        # DB (HUB + BACKUP_EXTRA_DATABASES) WITH CHECKSUM + VERIFYONLY
  manage.py hub_backup --type log         # log delle transazioni (solo recovery FULL, nella finestra)
  manage.py hub_backup --type files       # media + radici private, incrementale
  manage.py hub_backup --type host        # fotografia della macchina + zip della release
  manage.py hub_backup --type retention [--apply]   # GFS (dry-run senza --apply)
  manage.py hub_backup --type all         # full + files + host
  opzioni: --env prod --target \\\\nas\\hub-backup --dry-run --force (log fuori finestra)

Exit code per Task Scheduler: 0 = OK, 1 = con avvisi, 2 = fallito.
"""
from __future__ import annotations

import sys

from django.core.management.base import BaseCommand, CommandError

from core.backup_engine import engine
from core.backup_engine.config import load_config


class Command(BaseCommand):
    help = "Esegue un backup verificabile (full/log/files/host/retention/all) con manifest e stato."

    def add_arguments(self, parser):
        parser.add_argument("--type", required=True, choices=["full", "log", "files", "host", "retention", "all"])
        parser.add_argument("--env", default=None, help="Ambiente nei percorsi (prod/test); default dai settings.")
        parser.add_argument("--target", default=None, help="Sovrascrive BACKUP_TARGET.")
        parser.add_argument("--dry-run", action="store_true", help="Mostra cosa farebbe, senza scrivere.")
        parser.add_argument("--apply", action="store_true", help="Solo retention: elimina davvero.")
        parser.add_argument("--force", action="store_true", help="Solo log: anche fuori dalla finestra oraria.")
        parser.add_argument("--no-exit-code", action="store_true", help="Non terminare con exit code (uso da altri comandi).")

    def handle(self, *args, **opts):
        try:
            cfg = load_config(opts["env"], opts["target"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        for w in cfg.warnings:
            self.stdout.write(self.style.WARNING(f"! {w}"))
        if not opts["dry_run"]:
            n = engine.reconcile_pending(cfg)
            if n:
                self.stdout.write(f"Riconciliati {n} esiti rimasti in status.json.")
        kinds = ["full", "files", "host"] if opts["type"] == "all" else [opts["type"]]
        worst = 0
        for kind in kinds:
            self.stdout.write(self.style.MIGRATE_HEADING(f"== {kind} · ambiente {cfg.env} · {cfg.env_root}"))
            if kind == "full":
                res = engine.run_full(cfg, dry_run=opts["dry_run"])
            elif kind == "log":
                res = engine.run_log(cfg, dry_run=opts["dry_run"], force=opts["force"])
            elif kind == "files":
                res = engine.run_files(cfg, dry_run=opts["dry_run"])
            elif kind == "host":
                res = engine.run_host(cfg, dry_run=opts["dry_run"])
            else:
                res = engine.run_retention(cfg, dry_run=not opts["apply"] or opts["dry_run"],
                                           log=lambda m: self.stdout.write(f"  {m}"))
            self._report(res)
            worst = max(worst, res.exit_code)
        if worst and not opts["no_exit_code"]:
            sys.exit(worst)

    def _report(self, res) -> None:
        style = {"ok": self.style.SUCCESS, "warning": self.style.WARNING}.get(res.status, self.style.ERROR)
        line = f"  esito: {res.status.upper()}"
        if res.set_id:
            line += f" · set {res.set_id}"
        if res.bytes:
            line += f" · {res.bytes / 1048576:.1f} MB"
        if res.verify_status:
            line += f" · verifica {res.verify_status}"
        self.stdout.write(style(line))
        if res.error:
            self.stdout.write(self.style.ERROR(f"  errore: {res.error}"))
        for w in res.warnings:
            self.stdout.write(self.style.WARNING(f"  avviso: {w}"))
