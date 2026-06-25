"""Sincronizza il catalogo competenze MOD.187 (CompetenzaSkm) dagli asset live.

Idempotente. NON scrive baseline (nessuna AbilitazioneMacchina): popola solo il
catalogo + il match competenza→asset, preservando le conferme manuali. È il passo
che alimenta lo "specchietto" di validazione nel portale
(``anagrafica:skm_match_validazione``).

Esempi:
    python manage.py skm_seed_catalogo --dry-run
    python manage.py skm_seed_catalogo
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from anagrafica.services.skillmatrix_seed import sincronizza_catalogo


class Command(BaseCommand):
    help = "Sincronizza il catalogo competenze MOD.187 (CompetenzaSkm) dagli asset live."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Non scrive, stampa solo il piano.")

    def handle(self, *args, **opts):
        stats = sincronizza_catalogo(dry_run=opts["dry_run"])
        prefix = "[DRY-RUN] " if opts["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}Catalogo: creati {stats['creati']}, aggiornati {stats['aggiornati']}."
        ))
        self.stdout.write(
            f"Macchine {stats['macchine']} → esatti {stats['esatti']}, parziali {stats['parziali']}, "
            f"assenti {stats['assenti']} (confermati {stats['confermati']}). "
            f"Processi {stats['processi']} (collegati a qualifica {stats['processi_collegati']}), "
            f"contatori {stats['contatori']}."
        )
