"""Piano di ripristino a un punto nel tempo (BUILD_SPEC R3 §5.2), dai soli manifest del target.

  manage.py hub_restore_plan                                   # punto più recente
  manage.py hub_restore_plan --target-time "2026-10-16 14:30" --out restore-plan.json

Fallisce (exit 2) se la catena dei log ha buchi. Lo stesso calcolo è in
``core/backup_engine/restore_plan.py``, senza dipendenze da Django, per il tool di ripristino.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.backup_engine.config import load_config
from core.backup_engine.restore_plan import PlanError, build_plan


class Command(BaseCommand):
    help = "Calcola il piano di ripristino (FULL, LOG con STOPAT, file, release, chiavi attese)."

    def add_arguments(self, parser):
        parser.add_argument("--target-time", default=None, help="YYYY-MM-DD HH:MM (ora locale).")
        parser.add_argument("--env", default=None)
        parser.add_argument("--target", default=None)
        parser.add_argument("--out", default=None, help="File JSON da scrivere (default: stampa).")

    def handle(self, *args, **opts):
        cfg = load_config(opts["env"], opts["target"])
        when = None
        if opts["target_time"]:
            try:
                when = datetime.strptime(opts["target_time"], "%Y-%m-%d %H:%M")
            except ValueError as exc:
                raise CommandError("--target-time atteso nel formato YYYY-MM-DD HH:MM") from exc
        try:
            plan = build_plan(cfg.env_root, when)
        except PlanError as exc:
            self.stderr.write(self.style.ERROR(f"Piano non costruibile: {exc}"))
            sys.exit(2)
        text = json.dumps(plan, ensure_ascii=False, indent=2)
        if opts["out"]:
            Path(opts["out"]).write_text(text, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Piano scritto in {opts['out']} · punto di ripristino {plan['restore_point']}"))
        else:
            self.stdout.write(text)
        for w in plan["warnings"]:
            self.stderr.write(self.style.WARNING(f"avviso: {w}"))
