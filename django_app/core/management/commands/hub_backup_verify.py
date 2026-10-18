"""Verifica di un backup set: hash degli artefatti, RESTORE VERIFYONLY, catena dei log.

  manage.py hub_backup_verify --latest            # ultimo FULL e i suoi LOG
  manage.py hub_backup_verify --set 20261017_020000_full
  manage.py hub_backup_verify --chain             # catena LSN di tutti i LOG dell'ultimo FULL

Exit code: 0 = OK, 1 = avvisi, 2 = fallito.
"""
from __future__ import annotations

import sys

from django.core.management.base import BaseCommand, CommandError

from core.backup_engine import engine
from core.backup_engine import manifest as mf
from core.backup_engine.config import load_config


def check_chain(cfg, full_set) -> list[str]:
    """Catena LSN dei log dopo un FULL: ogni FirstLSN deve essere il LastLSN precedente."""
    problems: list[str] = []
    last_by_db: dict[str, int] = {}
    for a in mf.load(full_set.path).get("artifacts", []):
        if a.get("lsn"):
            last_by_db[a["database"]] = engine._lsn(a["lsn"].get("last"))
    first_seen: set[str] = set()
    for s in engine._log_sets_for(cfg, full_set.set_id):
        chain = (mf.load(s.path).get("chain") or {}).get("databases", {})
        for db, c in chain.items():
            first, last = engine._lsn(c["first_lsn"]), engine._lsn(c["last_lsn"])
            prev = last_by_db.get(db)
            if db not in first_seen:
                if prev is not None and first > prev:
                    problems.append(f"{s.set_id} {db}: primo log non copre il FULL (FirstLSN {first} > {prev})")
                first_seen.add(db)
            elif prev is not None and first != prev:
                problems.append(f"{s.set_id} {db}: buco nella catena (FirstLSN {first} ≠ LastLSN precedente {prev})")
            last_by_db[db] = last
    return problems


class Command(BaseCommand):
    help = "Verifica hash, VERIFYONLY e catena dei log di un backup set."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--set", dest="set_id")
        group.add_argument("--latest", action="store_true")
        group.add_argument("--chain", action="store_true")
        parser.add_argument("--env", default=None)
        parser.add_argument("--target", default=None)

    def handle(self, *args, **opts):
        cfg = load_config(opts["env"], opts["target"])
        worst = 0
        if opts["set_id"]:
            set_dir = cfg.env_root / opts["set_id"]
            if not set_dir.exists():
                raise CommandError(f"Set non trovato: {set_dir}")
            sets = [set_dir]
        else:
            full = engine.latest_set(cfg, "full")
            if full is None:
                raise CommandError("Nessun FULL nel target.")
            sets = [full.path] if opts["latest"] else []
            if opts["latest"]:
                sets += [s.path for s in engine._log_sets_for(cfg, full.set_id)]
            problems = check_chain(cfg, full)
            if problems:
                worst = 2
                for p in problems:
                    self.stdout.write(self.style.ERROR(f"catena: {p}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"catena log dopo {full.set_id}: continua"))
        for set_dir in sets:
            res = engine.verify_set(cfg, set_dir)
            style = self.style.SUCCESS if res.status == "ok" else (
                self.style.WARNING if res.status == "warning" else self.style.ERROR)
            self.stdout.write(style(f"{set_dir.name}: {res.status.upper()} {res.error}".rstrip()))
            for w in res.warnings:
                self.stdout.write(self.style.WARNING(f"  avviso: {w}"))
            worst = max(worst, res.exit_code)
        if worst:
            sys.exit(worst)
