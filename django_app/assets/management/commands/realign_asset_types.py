"""Riallinea il tipo asset (asset_type) a partire dalla categoria asset.

Da quando "Categoria asset" e "Tipo bene" sono stati unificati, asset_type e'
derivato dalla categoria (AssetCategory.base_asset_type). Questo command:

  1. (opzionale) ri-deduce base_asset_type delle categorie dal loro nome con
     l'euristica a parole chiave condivisa con l'import del catalogo;
  2. allinea asset_type di ogni asset al base_asset_type della sua categoria.

Tipico caso d'uso: asset importati prima della classificazione corretta che
risultano tutti come "Altro" (TYPE_OTHER) e popolano in modo errato la pagina
"Dispositivi IT".

Eseguire sempre prima con --dry-run.

Uso:
    python manage.py realign_asset_types --dry-run
    python manage.py realign_asset_types
    python manage.py realign_asset_types --skip-categories
    python manage.py realign_asset_types --include-classified --dry-run

Note:
  - le categorie non vengono mai "declassate" a Altro: l'euristica aggiorna solo
    verso un tipo concreto;
  - di default vengono ri-dedotte solo le categorie ancora su "Altro"; con
    --include-classified vengono rivalutate anche quelle gia' tipizzate;
  - gli asset senza categoria non vengono toccati (non c'e' una sorgente da cui
    derivare il tipo).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from assets.models import Asset, AssetCategory
from assets.services.asset_catalog_import import classify_asset_type


class Command(BaseCommand):
    help = "Riallinea asset_type degli asset a partire dalla categoria asset."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra le modifiche previste senza salvare nulla.",
        )
        parser.add_argument(
            "--skip-categories",
            action="store_true",
            help="Non ricalcolare base_asset_type delle categorie: allinea solo gli asset.",
        )
        parser.add_argument(
            "--include-classified",
            action="store_true",
            help="Rivaluta base_asset_type anche delle categorie gia' diverse da 'Altro' "
            "(default: solo quelle ancora su 'Altro').",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        skip_categories = options["skip_categories"]
        include_classified = options["include_classified"]
        type_label = dict(Asset.TYPE_CHOICES)

        if dry_run:
            self.stdout.write(self.style.WARNING("== DRY-RUN: nessuna modifica verra' salvata =="))

        # --- Fase 1: categorie ------------------------------------------------
        categories = list(AssetCategory.objects.all().order_by("parent_id", "label", "id"))
        category_changes: list[tuple[AssetCategory, str, str]] = []

        if not skip_categories:
            for category in categories:
                guess = classify_asset_type(category.label)
                if guess == Asset.TYPE_OTHER:
                    continue  # mai declassare a "Altro"
                if guess == category.base_asset_type:
                    continue
                if category.base_asset_type != Asset.TYPE_OTHER and not include_classified:
                    continue  # categoria gia' tipizzata: serve --include-classified
                category_changes.append((category, category.base_asset_type, guess))
                category.base_asset_type = guess  # applicata in memoria per la fase 2

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"Categorie aggiornate: {len(category_changes)}"))
        for category, old, new in category_changes:
            self.stdout.write(
                f"  [{category.id}] {category.label}: "
                f"{type_label.get(old, old)} -> {type_label.get(new, new)}"
            )

        # --- Fase 2: asset ----------------------------------------------------
        category_map = {c.id: c for c in categories}
        assets = list(Asset.objects.all().only("id", "asset_tag", "asset_type", "asset_category_id"))
        asset_changes: list[tuple[Asset, str, str]] = []
        without_category = 0

        for asset in assets:
            category = category_map.get(asset.asset_category_id)
            if category is None:
                without_category += 1
                continue
            target = category.base_asset_type
            if asset.asset_type != target:
                asset_changes.append((asset, asset.asset_type, target))
                asset.asset_type = target

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"Asset riallineati: {len(asset_changes)}"))
        per_type: dict[tuple[str, str], int] = {}
        for asset, old, new in asset_changes:
            per_type[(old, new)] = per_type.get((old, new), 0) + 1
        for (old, new), count in sorted(per_type.items()):
            self.stdout.write(
                f"  {type_label.get(old, old)} -> {type_label.get(new, new)}: {count}"
            )
        if without_category:
            self.stdout.write(
                self.style.WARNING(f"  Asset senza categoria (non toccati): {without_category}")
            )

        # --- Salvataggio ------------------------------------------------------
        if dry_run:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("DRY-RUN: nessuna modifica salvata."))
            return

        if not category_changes and not asset_changes:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Niente da aggiornare: dati gia' allineati."))
            return

        now = timezone.now()
        with transaction.atomic():
            for category, _old, _new in category_changes:
                category.save(update_fields=["base_asset_type"])
            for asset, _old, _new in asset_changes:
                asset.updated_at = now
                asset.save(update_fields=["asset_type", "updated_at"])

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Completato: {len(category_changes)} categorie e {len(asset_changes)} asset aggiornati."
            )
        )
