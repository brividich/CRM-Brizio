"""Assegna la categoria "Prodotti chimici" agli asset PRODOTTO_CHIMICO senza categoria.

Gli asset di tipo "Prodotto chimico" creati prima del fix di
Asset.default_chemical_category() (o mentre la categoria non era ancora
riconosciuta per base_asset_type ne' per nome) sono rimasti con
asset_category vuota: category_label ricade quindi sulla label del tipo
("Prodotto chimico", singolare) invece della vera AssetCategory.

Eseguire sempre prima con --dry-run.

Uso:
    python manage.py backfill_chemical_asset_category --dry-run
    python manage.py backfill_chemical_asset_category
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from assets.models import Asset


class Command(BaseCommand):
    help = "Assegna la categoria chimica di default agli asset PRODOTTO_CHIMICO senza categoria."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra quanti asset verrebbero aggiornati, senza salvare nulla.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        category = Asset.default_chemical_category()
        if category is None:
            raise CommandError(
                "Nessuna AssetCategory attiva riconoscibile come categoria chimica "
                "(ne' per base_asset_type=PRODOTTO_CHIMICO ne' per nome contenente "
                "\"chimic\"). Creala o attivala in Impostazioni asset prima di rilanciare."
            )

        qs = Asset.objects.filter(asset_type=Asset.TYPE_CHEMICAL, asset_category__isnull=True)
        count = qs.count()

        self.stdout.write(
            f"Categoria target: \"{category.label}\" (id={category.id}, "
            f"base_asset_type={category.base_asset_type})."
        )
        self.stdout.write(f"Asset PRODOTTO_CHIMICO senza categoria: {count}.")

        if count == 0:
            self.stdout.write(self.style.SUCCESS("Niente da aggiornare."))
            return

        if dry_run:
            for tag, name in qs.values_list("asset_tag", "name")[:50]:
                self.stdout.write(f"  {tag} - {name}")
            if count > 50:
                self.stdout.write(f"  ... e altri {count - 50}.")
            self.stdout.write(self.style.WARNING("DRY-RUN: nessuna modifica salvata."))
            return

        updated = qs.update(asset_category=category, updated_at=timezone.now())
        self.stdout.write(self.style.SUCCESS(f"Aggiornati {updated} asset."))
