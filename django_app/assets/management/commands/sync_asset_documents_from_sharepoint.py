"""Sync inverso dei documenti asset: da SharePoint verso il portale.

Schedulare come task Windows (suggerito ogni ora o piu volte al giorno):

    python manage.py sync_asset_documents_from_sharepoint

Per ogni asset con una cartella SharePoint configurata (``sharepoint_folder_path``)
la procedura allinea il portale alle modifiche applicate direttamente su SharePoint:

  - file nuovi caricati su SharePoint -> crea un AssetDocument di riferimento
    (con ``sharepoint_url``/``sharepoint_path``, senza copia locale);
  - file rimossi da SharePoint -> elimina l'AssetDocument sincronizzato corrispondente
    (record + eventuale copia locale);
  - file ancora presenti -> aggiorna ``sharepoint_url`` se cambiato.

I documenti solo-locali (caricati nel portale senza sync SharePoint) non vengono
mai toccati. Il command e idempotente.

Opzioni:
  --asset <tag>   limita il sync a un singolo asset_tag.
  --dry-run       calcola le modifiche senza applicarle.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from assets import views as asset_views
from assets.models import Asset


class Command(BaseCommand):
    help = "Sincronizza i documenti asset da SharePoint verso il portale (sync inverso)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--asset",
            type=str,
            default="",
            help="Limita il sync a un singolo asset_tag.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra le modifiche senza applicarle.",
        )

    def handle(self, *args, **options):
        apply = not options["dry_run"]
        asset_tag = (options.get("asset") or "").strip()

        queryset = Asset.objects.exclude(sharepoint_folder_path="").order_by("asset_tag")
        if asset_tag:
            queryset = queryset.filter(asset_tag=asset_tag)

        if not queryset.exists():
            self.stdout.write(self.style.WARNING("Nessun asset con cartella SharePoint configurata."))
            return

        mode = "DRY-RUN" if not apply else "APPLY"
        self.stdout.write(f"Sync inverso documenti SharePoint -> portale | modalita: {mode}")

        totals = {"created": 0, "deleted": 0, "updated": 0, "assets": 0, "skipped": 0}
        for asset in queryset.iterator():
            result = asset_views._sync_asset_documents_from_sharepoint(asset, apply=apply)
            if result["skipped"]:
                totals["skipped"] += 1
            else:
                totals["assets"] += 1
            totals["created"] += result["created"]
            totals["deleted"] += result["deleted"]
            totals["updated"] += result["updated"]
            for warning in result["warnings"]:
                self.stdout.write(self.style.WARNING(f"  ! {warning}"))
            if result["created"] or result["deleted"] or result["updated"]:
                self.stdout.write(
                    f"  {asset.asset_tag}: nuovi={result['created']} "
                    f"rimossi={result['deleted']} aggiornati={result['updated']}"
                )

        summary = (
            f"Completato | asset elaborati={totals['assets']}, saltati={totals['skipped']}, "
            f"nuovi={totals['created']}, rimossi={totals['deleted']}, aggiornati={totals['updated']}"
        )
        self.stdout.write(self.style.SUCCESS(summary))
