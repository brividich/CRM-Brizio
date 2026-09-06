"""Genera le occorrenze di manutenzione entrate nella finestra di preavviso.

Sostituisce ``generate_scheduled_workorders``: lo scheduler non apre piu' un OdL
per ogni asset. Crea le *manutenzioni dovute* (occorrenze); il raggruppamento in
OdL — anche massivi, anche distribuiti su piu' giorni — resta una decisione umana,
presa dalla pagina "Da fare".

Schedulare quotidianamente, prima di ``send_maintenance_reminders``:

    python manage.py generate_maintenance_occurrences

Il comando e' idempotente: la coppia (piano, asset, scadenza) e' unica a DB e una
coppia con un'occorrenza gia' aperta viene saltata.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from assets.models import Asset
from assets.services.maintenance_domain import generate_occurrences


class Command(BaseCommand):
    help = "Crea le occorrenze di manutenzione dovute dai piani attivi."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Non crea nulla, elenca solo cosa verrebbe creato.",
        )
        parser.add_argument(
            "--plan",
            type=int,
            default=0,
            help="Limita a un singolo piano (ID). 0 = tutti.",
        )
        parser.add_argument(
            "--horizon-days",
            type=int,
            default=None,
            help="Allarga la finestra oltre il preavviso configurato (utile per il primo popolamento).",
        )
        parser.add_argument(
            "--include-out-of-service",
            action="store_true",
            help="Include gli asset non in uso (di default si generano solo per gli asset in uso).",
        )

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))
        plan_id = int(options.get("plan") or 0)
        horizon_days = options.get("horizon_days")

        asset_queryset = Asset.objects.all()
        if not options.get("include_out_of_service"):
            asset_queryset = asset_queryset.filter(status=Asset.STATUS_IN_USE)

        result = generate_occurrences(
            today=timezone.localdate(),
            plan_ids=[plan_id] if plan_id else None,
            asset_queryset=asset_queryset,
            dry_run=dry_run,
            horizon_days=horizon_days,
        )

        for row in result["rows"]:
            prefix = "[DRY] " if dry_run else "  "
            self.stdout.write(
                f"{prefix}{row['plan']} — {row['asset']} — scadenza {row['due_date']:%d-%m-%Y} "
                f"(preavviso {row['warning_days']}gg)"
            )

        summary = (
            f"Create={result['created']} "
            f"GiaAperte={result['skipped_open']} "
            f"NonInPreavviso={result['skipped_not_due']} "
            f"Conflitti={result['conflicts']} "
            f"Escluse={result['excluded']}"
        )
        if result["conflicts"]:
            self.stdout.write(
                self.style.WARNING(
                    f"{result['conflicts']} coppie piano/asset in conflitto: nessuna occorrenza creata, "
                    "vanno risolte personalizzando l'asset."
                )
            )
        if dry_run:
            self.stdout.write(self.style.WARNING(f"[DRY-RUN] {summary}"))
        else:
            self.stdout.write(self.style.SUCCESS(summary))
