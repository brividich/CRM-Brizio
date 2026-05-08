from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from assets.services.asset_catalog_import import AssetCatalogImporter, ImportPreview


class Command(BaseCommand):
    help = "Importa catalogo asset da CSV/XLSX con preview dry-run e commit atomico."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Path file .csv o .xlsx da importare.")
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true", help="Simula import senza scrivere su DB.")
        mode.add_argument("--commit", action="store_true", help="Esegue import reale in transaction.atomic().")

    def handle(self, *args, **options):
        file_path = Path(str(options["file"])).expanduser()
        if not file_path.exists():
            raise CommandError(f"File non trovato: {file_path}")

        importer = AssetCatalogImporter()
        try:
            preview = importer.preview(file_path) if options["dry_run"] else importer.commit(file_path)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self._write_report(preview, dry_run=bool(options["dry_run"]))

        if options["commit"] and preview.has_blocking_errors:
            raise CommandError("Import annullato: correggere gli errori bloccanti e rilanciare.")

    def _write_report(self, preview: ImportPreview, *, dry_run: bool) -> None:
        mode = "DRY-RUN" if dry_run else "COMMIT"
        stats = preview.stats
        self.stdout.write(f"Modalita: {mode}")
        self.stdout.write(
            "Conteggi | "
            f"righe lette={stats.rows_seen}, "
            f"valide={stats.rows_valid}, "
            f"categorie padre da creare={stats.parent_categories_to_create}, "
            f"sottocategorie da creare={stats.subcategories_to_create}, "
            f"asset da creare={stats.assets_to_create}, "
            f"asset da aggiornare={stats.assets_to_update}, "
            f"asset invariati={stats.assets_unchanged}, "
            f"errori={len(preview.errors)}"
        )

        if preview.errors:
            self.stdout.write(self.style.ERROR("Errori riga per riga:"))
            for error in preview.errors:
                self.stdout.write(self.style.ERROR(f"- Riga {error.row_number}: {error.message}"))
        elif dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN: nessuna modifica e stata salvata nel database."))
        else:
            self.stdout.write(self.style.SUCCESS("Import completato."))
