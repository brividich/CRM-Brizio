"""Riallinea cartelle e metadati SharePoint per gli asset gia esistenti.

Per ogni asset con una cartella SharePoint configurata (``sharepoint_folder_path``)
la procedura richiama lo stesso ``_ensure_asset_sharepoint_folder`` usato al
salvataggio dell'asset: crea/verifica la cartella ``ASSET CN/<tag>`` e le tre
sottocartelle, e ri-applica le colonne metadato indicizzabili (``AssetTag``,
categoria, produttore, modello, matricola, stato, reparto, tipo cartella).

Serve come backfill per gli asset le cui cartelle erano state create prima del
supporto ai metadati, o che non sono stati piu risalvati da allora.

Esempi:

    python manage.py assets_ensure_sharepoint_metadata --dry-run
    python manage.py assets_ensure_sharepoint_metadata --apply
    python manage.py assets_ensure_sharepoint_metadata --apply --asset ML-000123

Opzioni:
  --asset <tag>   limita l'operazione a un singolo asset_tag.
  --dry-run       elenca gli asset interessati senza chiamare Graph (default).
  --apply         applica davvero (crea/verifica cartelle e scrive i metadati).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from assets import views as asset_views
from assets.models import Asset


class Command(BaseCommand):
    help = "Crea/verifica le cartelle asset su SharePoint e ne ri-applica le colonne metadato."

    def add_arguments(self, parser):
        parser.add_argument("--asset", type=str, default="", help="Limita a un singolo asset_tag.")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Elenca gli asset senza chiamare Graph (default).")
        mode.add_argument("--apply", action="store_true", help="Applica: crea/verifica cartelle e scrive i metadati.")

    def handle(self, *args, **options):
        apply = bool(options["apply"])
        asset_tag = (options.get("asset") or "").strip()

        queryset = Asset.objects.exclude(sharepoint_folder_path="").order_by("asset_tag", "id")
        if asset_tag:
            queryset = queryset.filter(asset_tag=asset_tag)
            if not queryset.exists():
                raise CommandError(f"Asset non trovato o senza cartella SharePoint: {asset_tag}")

        if not queryset.exists():
            self.stdout.write(self.style.WARNING("Nessun asset con cartella SharePoint configurata."))
            return

        mode = "APPLY" if apply else "DRY-RUN"
        self.stdout.write(f"Allineamento metadati cartelle SharePoint asset | modalita: {mode}")

        totals = {"processed": 0, "with_warnings": 0}
        for asset in queryset.iterator():
            if not apply:
                self.stdout.write(f"  {asset.asset_tag}: {asset.sharepoint_folder_path}")
                totals["processed"] += 1
                continue
            warnings = asset_views._ensure_asset_sharepoint_folder(asset)
            totals["processed"] += 1
            if warnings:
                totals["with_warnings"] += 1
                for warning in warnings:
                    self.stdout.write(self.style.WARNING(f"  ! {asset.asset_tag}: {warning}"))
            else:
                self.stdout.write(f"  {asset.asset_tag}: metadati applicati.")

        summary = (
            f"Completato | asset elaborati={totals['processed']}, con avvisi={totals['with_warnings']}"
        )
        self.stdout.write(self.style.SUCCESS(summary))
