"""Previsione del carico per le prossime settimane, con colli di bottiglia (reparti >100%).

Uso: python manage.py previsioni_carico [--settimane 8] [--start AAAA-MM-GG]
Usa ore reali o stimate (Fase 1), così il carico futuro è realistico.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand

from ...previsioni import carico_settimanale


class Command(BaseCommand):
    help = "Previsione carico settimanale per reparto + colli di bottiglia."

    def add_arguments(self, parser):
        parser.add_argument("--settimane", type=int, default=8)
        parser.add_argument("--start", default="")

    def handle(self, *args, **opts):
        if opts["start"]:
            try:
                start = date.fromisoformat(opts["start"])
            except ValueError:
                start = date.today()
        else:
            start = date.today()
        start = start - timedelta(days=start.weekday())  # lunedi'

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Previsione carico — {opts['settimane']} settimane da {start}"
        ))
        for wk in carico_settimanale(start, max(1, opts["settimane"])):
            tot = wk["totale"]["perc"]
            colli = sorted(
                (cat for cat, v in wk["per_reparto"].items() if v["perc"] > 100),
                key=lambda c: -wk["per_reparto"][c]["perc"],
            )
            flag = "  <-- COLLO DI BOTTIGLIA" if colli else ""
            self.stdout.write(f"  {wk['settimana']}  totale {tot:>5.0f}%{flag}")
            for cat in colli:
                self.stdout.write(f"        {cat}: {wk['per_reparto'][cat]['perc']:.0f}%")
