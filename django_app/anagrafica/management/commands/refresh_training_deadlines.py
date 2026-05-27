"""Ricalcola la cache delle scadenze formazione (TrainingDeadline).

Uso:
    python manage.py refresh_training_deadlines --all
    python manage.py refresh_training_deadlines --legacy-id 42
    python manage.py refresh_training_deadlines --corso-id 7
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Ricalcola TrainingDeadline per tutti i dipendenti o per un sottoinsieme."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--legacy-id", type=int, default=None, dest="legacy_id",
            help="Ricalcola solo questo legacy_anagrafica_id.",
        )
        parser.add_argument(
            "--corso-id", type=int, default=None, dest="corso_id",
            help="Ricalcola solo per questo corso_id.",
        )
        parser.add_argument(
            "--all", action="store_true", default=False, dest="all",
            help="Ricalcola tutti i record (obbligatorio se non si passa --legacy-id o --corso-id).",
        )

    def handle(self, *args, **options) -> None:
        legacy_id: int | None = options["legacy_id"]
        corso_id: int | None = options["corso_id"]
        run_all: bool = options["all"]

        if not run_all and legacy_id is None and corso_id is None:
            raise CommandError(
                "Specificare --all, --legacy-id o --corso-id. "
                "Usare --all per ricalcolare tutti i record."
            )

        from anagrafica.services.training_deadline_service import refresh_deadlines  # noqa: PLC0415

        self.stdout.write("Avvio ricalcolo scadenze formazione…")
        n = refresh_deadlines(legacy_id=legacy_id, corso_id=corso_id)
        self.stdout.write(
            self.style.SUCCESS(f"refresh_training_deadlines: {n} record aggiornati/creati.")
        )
