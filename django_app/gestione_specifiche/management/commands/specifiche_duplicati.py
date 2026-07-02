"""Report READ-ONLY dei duplicati (codice, revisione) tra le Specifiche.

Prerequisito per applicare il vincolo DB `UniqueConstraint(codice, revisione)` (M1): prima di
aggiungere il constraint in prod occorre deduplicare il pregresso, altrimenti la migrazione
fallisce. Questo comando NON scrive nulla: elenca solo i gruppi duplicati con i loro pk.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Count

from gestione_specifiche.models import Specifica


def _ascii(s) -> str:
    return str(s or "").encode("ascii", "replace").decode("ascii")


class Command(BaseCommand):
    help = "Elenca READ-ONLY i (codice, revisione) duplicati tra le Specifiche (pre-UniqueConstraint)."

    def handle(self, *args, **opts):
        gruppi = list(
            Specifica.objects.values("codice", "revisione")
            .annotate(n=Count("id")).filter(n__gt=1).order_by("-n", "codice")
        )
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Duplicati (codice, revisione): {len(gruppi)} gruppi"
        ))
        for g in gruppi:
            pks = list(
                Specifica.objects.filter(codice=g["codice"], revisione=g["revisione"])
                .order_by("pk").values_list("id", flat=True)
            )
            self.stdout.write(
                f"  {g['n']}x  {_ascii(g['codice'])} rev {_ascii(g['revisione'] or '-')}  pk={pks}"
            )
        if not gruppi:
            self.stdout.write(self.style.SUCCESS(
                "  nessun duplicato: si puo' applicare UniqueConstraint(codice, revisione)."
            ))
