"""Export **sola lettura** dei codici asset per la validazione Skill Matrix MOD.187.

NON scrive nulla nel DB. Esporta SOLO i metadati asset
(``id``, ``asset_tag``, ``internal_number``, ``name``, ``asset_type``) — **nessun
dato personale** — in un CSV portabile. Serve a "prendere i codici degli asset
dall'ambiente target" (es. prod) per poi rigiocare il match **offline** con
``skm_asset_match_report --assets-csv ...`` su una macchina di sviluppo, senza
collegare il DB di prod.

Eseguire nell'ambiente target:
    python manage.py skm_export_assets --settings=config.settings.prod
    python manage.py skm_export_assets --output C:\\percorso\\assets_prod.csv
"""
from __future__ import annotations

import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

COLONNE = ["id", "asset_tag", "internal_number", "name", "asset_type"]


def _repo_root() -> Path:
    # settings.BASE_DIR == django_app/ ; la repo root è il suo parent.
    return Path(settings.BASE_DIR).parent


class Command(BaseCommand):
    help = "Export sola lettura dei codici asset (tag/nome/tipo) per la validazione Skill Matrix MOD.187."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output", default="",
            help="CSV di output (default: docs/skill-matrix/assets_export.csv).",
        )

    def handle(self, *args, **opts):
        # Import locale: non legare il modulo all'app assets al caricamento.
        from assets.models import Asset

        output = Path(opts["output"]) if opts["output"] else (
            _repo_root() / "docs" / "skill-matrix" / "assets_export.csv"
        )
        righe = list(
            Asset.objects.all()
            .only("id", "asset_tag", "internal_number", "name", "asset_type")
            .order_by("asset_tag")
        )

        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLONNE, delimiter=";")
            writer.writeheader()
            for a in righe:
                writer.writerow({
                    "id": a.id,
                    "asset_tag": a.asset_tag or "",
                    "internal_number": a.internal_number or "",
                    "name": a.name or "",
                    "asset_type": a.asset_type or "",
                })

        self.stdout.write(self.style.SUCCESS(f"Esportati {len(righe)} asset in: {output}"))
        self.stdout.write(
            "Nessun dato personale nel file (solo metadati asset). "
            "Rigiocare il match con: python manage.py skm_asset_match_report "
            f"--assets-csv {output}"
        )
