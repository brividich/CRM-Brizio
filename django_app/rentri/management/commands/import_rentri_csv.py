"""
Management command: importa registrazioni RENTRI da file CSV.

Uso:
    python manage.py import_rentri_csv <percorso_csv>

Opzioni:
    --dry-run   Simula senza scrivere sul DB
    --clear     Cancella tutti i record esistenti prima di importare
"""
import csv
import json
import re
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from rentri.models import RegistroRifiuti

TIPO_MAP = {
    "C - Carico": "C",
    "O - Scarico originario": "O",
    "M - Scarico effettivo": "M",
    "R - Rettifica scarico": "R",
}

# Indici colonne CSV (0-based)
COL_DATA = 0
COL_ID_REG = 1
COL_CODICE = 2
COL_PERIC = 3
COL_QUANTITA = 4
COL_RETTIFICA = 5
COL_TIPO = 6
COL_NOTE = 7
COL_RENTRI = 8
COL_ARRIVO_FIR = 9
COL_MODIFICATO = 10
COL_RIF_OP = 11


def _parse_number(raw: str):
    """Converte numero italiano (1.234 = 1234) in float, o None se vuoto."""
    s = raw.strip().replace(".", "").replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in ("vero", "true", "1", "yes", "si")


def _parse_pericolosita(raw: str) -> str:
    """Estrae i codici HP (es. HP04, HP05) come stringa compatta max 100 char."""
    raw = raw.strip()
    if not raw:
        return ""
    try:
        items = json.loads(raw)
        codes = []
        for item in items:
            m = re.match(r"(HP\d+)", str(item))
            if m:
                codes.append(m.group(1))
        return ", ".join(codes)[:100]
    except Exception:
        return raw[:100]


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
            help="Cancella tutti i record esistenti prima di importare",
        )

    def handle(self, *args, **options):
        csv_path = Path(options["csv_file"])
        if not csv_path.exists():
            raise CommandError(f"File non trovato: {csv_path}")

        dry_run = options["dry_run"]
        do_clear = options["clear"]

        if dry_run:
            self.stdout.write(self.style.WARNING("=== DRY RUN: nessuna scrittura sul DB ==="))

        if do_clear and not dry_run:
            count, _ = RegistroRifiuti.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Eliminati {count} record esistenti."))

        created = 0
        skipped = 0
        errors = []

        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)  # salta intestazione
            self.stdout.write(f"Colonne trovate: {len(header)}")

            for line_no, row in enumerate(reader, start=2):
                if not any(cell.strip() for cell in row):
                    continue  # riga vuota

                try:
                    # --- Data ---
                    data_raw = row[COL_DATA].strip()
                    try:
                        data = datetime.strptime(data_raw, "%d/%m/%Y").date()
                    except ValueError:
                        errors.append(f"Riga {line_no}: data non valida '{data_raw}'")
                        skipped += 1
                        continue

                    # --- Tipo ---
                    tipo_raw = row[COL_TIPO].strip()
                    tipo = TIPO_MAP.get(tipo_raw)
                    if not tipo:
                        errors.append(f"Riga {line_no}: tipo non riconosciuto '{tipo_raw}'")
                        skipped += 1
                        continue

                    # --- ID Registrazione ---
                    id_reg = row[COL_ID_REG].strip()

                    # --- Duplicate check ---
                    if RegistroRifiuti.objects.filter(
                        id_registrazione=id_reg, tipo=tipo
                    ).exists():
                        self.stdout.write(f"  Skip (già presente): {id_reg} [{tipo}]")
                        skipped += 1
                        continue

                    # --- Codice (strip tab e spazi extra) ---
                    codice = " ".join(row[COL_CODICE].split())[:100]

                    # --- Quantità / Rettifica ---
                    quantita = _parse_number(row[COL_QUANTITA])
                    rettifica = _parse_number(row[COL_RETTIFICA])

                    # --- Pericolosità ---
                    pericolosita = _parse_pericolosita(row[COL_PERIC])

                    # --- Booleans / stringhe ---
                    rentri_si_no = _parse_bool(row[COL_RENTRI])
                    arrivo_fir = row[COL_ARRIVO_FIR].strip()
                    note_rentri = row[COL_NOTE].strip()
                    inserito_da = row[COL_MODIFICATO].strip()
                    rif_op = row[COL_RIF_OP].strip()

                    registro = RegistroRifiuti(
                        tipo=tipo,
                        data=data,
                        id_registrazione=id_reg,
                        codice=codice,
                        quantita=quantita,
                        rettifica_scarico=rettifica,
                        carico_scarico=tipo,
                        rentri_si_no=rentri_si_no,
                        note_rentri=note_rentri,
                        pericolosita=pericolosita,
                        arrivo_fir=arrivo_fir,
                        rif_op=rif_op,
                        inserito_da=inserito_da,
                    )

                    if not dry_run:
                        # Bypassa l'auto-generazione id_registrazione in save()
                        # impostando il valore prima della chiamata
                        registro.save()
                        # Forza l'id_registrazione corretto (save() lo rispetta se già impostato)
                        if registro.id_registrazione != id_reg:
                            RegistroRifiuti.objects.filter(pk=registro.pk).update(
                                id_registrazione=id_reg
                            )

                    self.stdout.write(f"  + {id_reg} [{tipo}] {data} — {codice[:40]}")
                    created += 1

                except IndexError as exc:
                    errors.append(f"Riga {line_no}: colonne insufficienti ({exc})")
                    skipped += 1
                except Exception as exc:
                    errors.append(f"Riga {line_no}: {exc}")
                    skipped += 1

        # --- Riepilogo ---
        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING(f"DRY RUN — da importare: {created}, da saltare: {skipped}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Importati: {created} | Saltati: {skipped}"))

        if errors:
            self.stdout.write(self.style.WARNING(f"\nErrori ({len(errors)}):"))
            for e in errors:
                self.stdout.write(self.style.WARNING(f"  {e}"))
