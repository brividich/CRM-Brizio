"""Rimuove dalla categoria "Prodotti chimici" gli asset che non sono chimici veri.

La categoria chimica (risolta come Asset.default_chemical_category()) deve
restare un raccoglitore SOLO per gli asset creati dal modulo "Prodotto
chimico"/Schede di sicurezza (asset_type=PRODOTTO_CHIMICO). Prima di questo
comando, il form Assets generico permetteva di assegnare quella categoria
anche ad asset "normali" (es. Altro): l'asset prendeva il trattamento da
asset di produzione (numero interno, manutenzione, contratti) invece della
scheda dedicata SDS — comportamento sbagliato per un prodotto chimico.

Questo comando NON tocca asset_type, manutenzione, contratti o qualsiasi
altro campo dell'asset: azzera solo asset_category, cosi' l'asset esce dalla
categoria chimica (torna "senza categoria", come un asset "Altro" qualsiasi)
senza perdere nessun dato.

Eseguire sempre prima con --dry-run.

Uso:
    python manage.py declassify_generic_assets_from_chemical_category --dry-run
    python manage.py declassify_generic_assets_from_chemical_category
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from assets.models import Asset


class Command(BaseCommand):
    help = 'Rimuove dalla categoria "Prodotti chimici" gli asset non di tipo Prodotto chimico.'

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra quali asset verrebbero scategorizzati, senza salvare nulla.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        category = Asset.default_chemical_category()
        if category is None:
            self.stdout.write(self.style.WARNING(
                'Nessuna categoria chimica riconoscibile: niente da fare.'
            ))
            return

        qs = Asset.objects.filter(asset_category=category).exclude(asset_type=Asset.TYPE_CHEMICAL)
        count = qs.count()

        self.stdout.write(f'Categoria: "{category.label}" (id={category.id}).')
        self.stdout.write(f'Asset non chimici attualmente in quella categoria: {count}.')

        if count == 0:
            self.stdout.write(self.style.SUCCESS("Niente da aggiornare."))
            return

        for tag, name, asset_type in qs.values_list("asset_tag", "name", "asset_type")[:50]:
            self.stdout.write(f"  {tag} - {name} (tipo: {asset_type})")
        if count > 50:
            self.stdout.write(f"  ... e altri {count - 50}.")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN: nessuna modifica salvata."))
            return

        updated = qs.update(asset_category=None, updated_at=timezone.now())
        self.stdout.write(self.style.SUCCESS(
            f'Scategorizzati {updated} asset (restano "Altro"/ecc., solo senza la categoria "{category.label}").'
        ))
