"""F5 — Sincronizza le sospensioni da continuità operativa.

Sospende le abilitazioni con continuità **persa** e riattiva quelle recuperate
(unica regola bloccante, MT CN 65 §3.7). ``--dry-run`` calcola solo il piano.

NB: opera su ``ContinuitaOperativa.ultima_esecuzione`` già presente; il
popolamento di tale data dalla produzione reale è un passo successivo (gate F5).

Esempi:
    python manage.py skm_continuita_sync --dry-run
    python manage.py skm_continuita_sync
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from anagrafica.services.skillmatrix_continuita import applica_sospensioni


class Command(BaseCommand):
    help = "F5: sospende/riattiva le abilitazioni in base alla continuità operativa."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Non scrive, stampa solo il piano.")

    def handle(self, *args, **opts):
        stats = applica_sospensioni(apply=not opts["dry_run"])
        prefix = "[DRY-RUN] " if opts["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}Continuità persa: {stats['persa']} | "
            f"sospensioni: {stats['da_sospendere']} (eseguite {stats['sospese']}) | "
            f"riattivazioni: {stats['da_riattivare']} (eseguite {stats['riattivate']})."
        ))
