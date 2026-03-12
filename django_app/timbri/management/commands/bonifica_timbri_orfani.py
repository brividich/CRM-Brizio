from __future__ import annotations

from django.core.management.base import BaseCommand

from timbri.views import cleanup_orphan_operatori


class Command(BaseCommand):
    help = "Bonifica gli operatori timbri orfani riallineandoli all'anagrafica centrale quando possibile."

    def handle(self, *args, **options):
        result = cleanup_orphan_operatori()
        self.stdout.write(
            self.style.SUCCESS(
                "Bonifica completata. "
                f"Orfani={result['orphans']} "
                f"Riallineati={result['relinked_operatori']} "
                f"Record spostati={result['records_relinked']} "
                f"Vuoti eliminati={result['deleted_empty']} "
                f"Non agganciati con record={result['unmatched_with_records']}"
            )
        )
