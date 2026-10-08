"""Importa termini nel glossario da un CSV (separatore ``;``, UTF-8).

Colonne: termine;termine_en;categoria;definizione;simbolo;norma_rif;varianti
Varianti separate da ``|`` nel formato ``tipo:testo`` (es. ``traduzione:spot face|simbolo:⌴``).
Pensato per un export IATE filtrato a mano. Le righe importate entrano in «bozza».

Esempi:
    python manage.py glossario_import_csv --file termini.csv --dry-run
    python manage.py glossario_import_csv --file termini.csv
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from glossario_tecnico.services import importa_csv


class Command(BaseCommand):
    help = "Importa termini del glossario da CSV (righe in bozza)."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Percorso del CSV (UTF-8, separatore ';').")
        parser.add_argument("--dry-run", action="store_true", dest="dry_run", help="Verifica senza salvare.")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.is_file():
            raise CommandError(f"File non trovato: {path}")
        try:
            contenuto = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise CommandError("Il file deve essere in UTF-8.") from exc
        esito = importa_csv(contenuto, dry_run=bool(options.get("dry_run")))
        modo = "DRY-RUN" if options.get("dry_run") else "IMPORT"
        self.stdout.write(
            f"{modo}: righe={esito.righe} importate={esito.importati} già presenti={esito.saltati} "
            f"con errori={len(esito.errori)}"
        )
        for errore in esito.errori[:50]:
            self.stdout.write(self.style.WARNING(f"  - {errore}"))
        if options.get("dry_run"):
            self.stdout.write("Dry-run: nulla salvato.")
