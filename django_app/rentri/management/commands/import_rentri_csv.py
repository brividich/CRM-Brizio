"""
Management command: importa registrazioni RENTRI da file CSV.

Uso:
    python manage.py import_rentri_csv <percorso_csv>

Opzioni:
    --dry-run   Simula senza scrivere sul DB
    --clear     Cancella tutti i record esistenti prima di importare
                (prima ne scrive una copia CSV, vedi --backup)

Stesso parser e stesse regole dell'import dalla pagina (``rentri.importazione``):
l'import è tutto o niente.
"""
import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from rentri.importazione import (
    ImportAnnullato,
    _detect_csv_delimiter,
    _parse_csv_rows,
    _parse_num_it,
    _parse_pericolosita_csv,
    _parse_rif_op_csv,
    _split_sp_multivalue_csv,
    importa_righe,
)
from rentri.models import RegistroRifiuti

# Alias storici dei helper (prima duplicati qui, ora unici in rentri.importazione).
_parse_number = _parse_num_it
_split_sp_multivalue = _split_sp_multivalue_csv
_parse_pericolosita = _parse_pericolosita_csv
_parse_rif_op = _parse_rif_op_csv


def _detect_delimiter(header_line: str) -> str:
    """Rileva il delimitatore (';' o ',') dalla riga di intestazione del CSV."""
    return _detect_csv_delimiter(header_line)


_CAMPI_BACKUP = [
    "id", "tipo", "data", "id_registrazione", "rif_op", "codice", "quantita", "unita",
    "rettifica_scarico", "carico_scarico", "rentri_si_no", "salva", "note_rentri",
    "pericolosita", "arrivo_fir", "inserito_da", "origine", "annullato", "motivo_annullamento",
    "sharepoint_item_id", "created_at",
]


def _scrivi_backup(percorso: Path) -> int:
    n = 0
    with open(percorso, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(_CAMPI_BACKUP)
        for r in RegistroRifiuti.objects.order_by("id").values_list(*_CAMPI_BACKUP):
            writer.writerow(["" if v is None else v for v in r])
            n += 1
    return n


class Command(BaseCommand):
    help = "Importa registrazioni RENTRI da file CSV esportato da SharePoint"

    def add_arguments(self, parser):
        parser.add_argument("csv_file", type=str, help="Percorso al file CSV")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simula l'importazione senza scrivere sul database",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Cancella tutti i record esistenti prima di importare (dopo averne scritto una copia CSV)",
        )
        parser.add_argument(
            "--backup",
            type=str,
            default="",
            help="Percorso della copia CSV scritta prima di --clear (default: rentri_backup_<data_ora>.csv)",
        )

    def handle(self, *args, **options):
        csv_path = Path(options["csv_file"])
        if not csv_path.exists():
            raise CommandError(f"File non trovato: {csv_path}")

        dry_run = options["dry_run"]
        do_clear = options["clear"]

        if dry_run:
            self.stdout.write(self.style.WARNING("=== DRY RUN: nessuna scrittura sul DB ==="))

        content = csv_path.read_text(encoding="utf-8-sig")
        rows, parse_errors = _parse_csv_rows(content)
        for e in parse_errors:
            self.stdout.write(self.style.WARNING(f"Riga {e['riga']}: {e['msg']}"))
        if parse_errors:
            raise CommandError(f"{len(parse_errors)} righe non valide: correggile, non è stato importato nulla.")

        try:
            with transaction.atomic():
                if do_clear and not dry_run:
                    backup = Path(options["backup"] or f"rentri_backup_{timezone.localtime():%Y%m%d_%H%M%S}.csv")
                    n = _scrivi_backup(backup)
                    self.stdout.write(self.style.WARNING(f"Copia di {n} record scritta in {backup.resolve()}"))
                    count, _ = RegistroRifiuti.objects.all().delete()
                    self.stdout.write(self.style.WARNING(f"Eliminati {count} record esistenti."))
                    rows, _ = _parse_csv_rows(content)  # "esiste" va ricalcolato dopo la pulizia
                esito = importa_righe(rows, dry_run=dry_run)
        except ImportAnnullato as exc:
            for e in exc.errori:
                self.stdout.write(self.style.WARNING(f"Riga {e['riga']}: {e['msg']}"))
            raise CommandError("Import annullato: nessuna riga scritta (e nessuna cancellazione).") from None

        for a in esito["avvisi"]:
            self.stdout.write(self.style.WARNING(f"Riga {a['riga']}: {a['msg']}"))
        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"DRY RUN — da importare: {esito['created']}, da saltare: {esito['skipped']}"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(f"Importati: {esito['created']} | Saltati: {esito['skipped']}"))
