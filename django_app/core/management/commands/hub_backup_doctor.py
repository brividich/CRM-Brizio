"""Diagnostica non distruttiva per backup e capacità del database.

Sezioni: capacità del DB rispetto al limite dell'edizione, top tabelle, crescita
dell'audit e previsione di saturazione, versione della politica di audit, cache su
DB (R0); motore di backup: target/staging scrivibili, destinazione secondaria,
BACKUP_ENV_DIR, recovery model, freschezza dei set, prova di ripristino, task
pianificati, nomi del portale (ALLOWED_HOSTS, CSRF, DNS, SPN) (R1).
Exit code: 0 = tutto ok, 1 = avvisi, 2 = almeno un controllo critico.
"""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from core import db_diagnostics
from core.backup_engine.config import load_config
from core.backup_engine.doctor import run_checks


class Command(BaseCommand):
    help = "Diagnostica (solo lettura) di capacità DB, crescita dell'audit e cache."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Output JSON.")
        parser.add_argument("--days", type=int, default=7)
        parser.add_argument("--env", default=None)
        parser.add_argument("--offline", action="store_true", help="Salta DNS/SPN e task pianificati.")
        parser.add_argument("--no-exit-code", action="store_true")

    def handle(self, *args, **opts):
        capacity = db_diagnostics.server_capacity()
        growth = db_diagnostics.audit_growth(days=opts["days"])
        forecast = db_diagnostics.saturation_forecast(capacity, growth)
        level, message = db_diagnostics.audit_growth_status(capacity, growth)
        try:
            cfg = load_config(opts["env"])
            backup = run_checks(cfg, with_tasks=not opts["offline"], with_network=not opts["offline"])
        except ValueError as exc:
            backup = [{"check": "config", "level": "critical", "message": str(exc)}]
        report = {
            "capacity": capacity,
            "top_tables": db_diagnostics.top_tables(),
            "audit": {**growth, **forecast, "level": level, "message": message},
            "cache": db_diagnostics.cache_diagnostics(),
            "backup": backup,
        }
        levels = {c["level"] for c in backup} | {level}
        exit_code = 2 if "critical" in levels else 1 if "warning" in levels else 0
        if opts["json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        else:
            self._print(report, level, message)
        if exit_code and not opts["no_exit_code"]:
            sys.exit(exit_code)

    def _print(self, report, level, message):
        capacity = report["capacity"]
        w = self.stdout.write
        w("== Capacità database ==")
        if capacity.get("supported"):
            w(f"  {capacity['database']} · {capacity['edition']} {capacity['product_version']} · "
              f"recovery {capacity['recovery_model']} · log_reuse_wait {capacity['log_reuse_wait']}")
            lim = f"{capacity['limit_mb']} MB" if capacity["limit_mb"] else "nessun limite di edizione"
            w(f"  dati: usati {capacity['data_used_mb']} / allocati {capacity['data_allocated_mb']} MB · "
              f"limite {lim} · {capacity['used_pct']}% [{capacity['level']}]")
            w(f"  log: usati {capacity['log_used_mb']} / allocati {capacity['log_allocated_mb']} MB")
        else:
            w("  non SQL Server: sezione non disponibile")
        if report["top_tables"]:
            w("== Top tabelle per spazio ==")
            for t in report["top_tables"]:
                w(f"  {t['tabella']:<50} {t['righe']:>12} righe {t['mb']:>10} MB")
        a = report["audit"]
        w(f"== Audit (politica v{a['policy_version']}) ==")
        w(f"  righe totali {a['total_rows']} · tabella {a['table_mb']} MB · ultimi {a['days']} giorni: "
          f"{a['recent_rows']} righe, {a['recent_mb']} MB · proiezione {a['monthly_projection_mb']} MB/mese")
        w(f"  saturazione prevista: {a['days_to_limit'] if a['days_to_limit'] is not None else 'n/d'} giorni "
          f"[{level}] {message}")
        for m in a["monthly"]:
            w(f"  {m['mese']}: {m['righe']} righe, {m['mb_stimati']} MB")
        if a["top_models"]:
            w("  Top modelli ultimi giorni:")
            for t in a["top_models"]:
                w(f"    {t['modulo']:<16} {t['azione']:<12} {t['modello']:<30} {t['righe']:>9} {t['mb']:>8} MB ({t['classe']})")
        c = report["cache"]
        w("== Cache su database ==")
        if c.get("supported") and "rows" in c:
            w(f"  {c['table']}: {c['rows']} righe ({c['expired_rows']} scadute) · valore medio "
              f"{c['avg_value_bytes']} B, massimo {c['max_value_bytes']} B")
            for p in c["top_prefixes"]:
                w(f"    {p['prefisso']:<40} {p['righe']:>8} righe {p['mb']:>8} MB")
        else:
            w(f"  non disponibile ({c.get('backend') or c.get('error', '')})")
        w("== Backup e ripristino ==")
        icons = {"ok": "OK  ", "info": "info", "warning": "WARN", "critical": "CRIT"}
        for c in report["backup"]:
            style = {"warning": self.style.WARNING, "critical": self.style.ERROR}.get(c["level"], str)
            w(style(f"  [{icons.get(c['level'], c['level'])}] {c['check']}: {c['message']}"))
