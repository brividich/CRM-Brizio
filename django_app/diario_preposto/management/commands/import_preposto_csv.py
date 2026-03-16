from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from diario_preposto.models import SegnalazionePreposto

CSV_HEADERS = (
    "Chi segnala",
    "Data segnalazione",
    "Nominativo Segnalato",
    "Descrizione della segnalazione",
)


def _clean_single_line(raw: str) -> str:
    return " ".join(str(raw or "").replace("\ufeff", "").split()).strip()


def _clean_multiline(raw: str) -> str:
    lines = [line.strip() for line in str(raw or "").replace("\ufeff", "").splitlines()]
    chunks = [line for line in lines if line]
    return "\n".join(chunks).strip()


def _parse_local_datetime(raw: str):
    value = _clean_single_line(raw)
    if not value:
        raise ValueError("data segnalazione vuota")
    naive = datetime.strptime(value, "%d/%m/%Y %H:%M")
    return timezone.make_aware(naive, timezone.get_current_timezone())


class Command(BaseCommand):
    help = (
        "Importa segnalazioni CSV nel modulo Diario Preposto. "
        "Mapping: Nominativo Segnalato -> titolo, Chi segnala -> preposto/chi_segnala."
    )

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Percorso del file CSV da importare.")
        parser.add_argument("--dry-run", action="store_true", help="Esegue il parsing ma non salva modifiche.")
        parser.add_argument("--delimiter", default=",", help="Separatore CSV (default: ',').")
        parser.add_argument(
            "--encoding",
            default="utf-8-sig",
            help="Encoding del CSV (default: utf-8-sig).",
        )
        parser.add_argument("--limit", type=int, default=0, help="Numero massimo di righe da processare.")
        parser.add_argument(
            "--created-by",
            default="",
            help="Username Django da associare a `creato_da` per i nuovi record.",
        )

    def handle(self, *args, **options):
        csv_path = Path(str(options["csv_path"])).expanduser()
        if not csv_path.exists():
            raise CommandError(f"CSV non trovato: {csv_path}")
        if not csv_path.is_file():
            raise CommandError(f"Percorso non valido (non e' un file): {csv_path}")

        delimiter = str(options.get("delimiter") or ",")
        encoding = str(options.get("encoding") or "utf-8-sig")
        dry_run = bool(options.get("dry_run"))
        limit = max(0, int(options.get("limit") or 0))
        created_by = self._resolve_user(str(options.get("created_by") or "").strip())

        rows = self._load_rows(csv_path, delimiter=delimiter, encoding=encoding)
        if not rows:
            self.stdout.write(self.style.WARNING("CSV vuoto: nessuna riga da importare."))
            return

        stats = {
            "rows": 0,
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "skipped": 0,
        }

        with transaction.atomic():
            for index, row in enumerate(rows, start=2):
                if limit and stats["rows"] >= limit:
                    break

                stats["rows"] += 1

                try:
                    payload = self._row_to_payload(row)
                except Exception as exc:
                    stats["skipped"] += 1
                    self.stdout.write(self.style.WARNING(f"Riga {index} saltata: {exc}"))
                    continue

                qs = SegnalazionePreposto.objects.filter(
                    data_segnalazione=payload["data_segnalazione"],
                    titolo=payload["titolo"],
                    chi_segnala=payload["chi_segnala"],
                ).order_by("pk")

                match_count = qs.count()
                if match_count > 1:
                    stats["skipped"] += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Riga {index} saltata: trovati {match_count} record esistenti con stessa chiave naturale."
                        )
                    )
                    continue

                if match_count == 0:
                    SegnalazionePreposto.objects.create(
                        **payload,
                        creato_da=created_by,
                    )
                    stats["inserted"] += 1
                    continue

                segnalazione = qs.first()
                changed = False
                for field in ("descrizione", "preposto"):
                    new_value = payload[field]
                    if getattr(segnalazione, field) != new_value:
                        setattr(segnalazione, field, new_value)
                        changed = True

                if created_by and segnalazione.creato_da_id is None:
                    segnalazione.creato_da = created_by
                    changed = True

                if changed:
                    segnalazione.save(update_fields=["descrizione", "preposto", "creato_da", "updated_at"])
                    stats["updated"] += 1
                else:
                    stats["unchanged"] += 1

            if dry_run:
                transaction.set_rollback(True)

        dry_suffix = " [DRY-RUN]" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                "Import completato%s rows=%s inserted=%s updated=%s unchanged=%s skipped=%s"
                % (
                    dry_suffix,
                    stats["rows"],
                    stats["inserted"],
                    stats["updated"],
                    stats["unchanged"],
                    stats["skipped"],
                )
            )
        )

    def _load_rows(self, csv_path: Path, *, delimiter: str, encoding: str) -> list[dict[str, str]]:
        with csv_path.open("r", encoding=encoding, newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            headers = tuple(reader.fieldnames or ())
            missing = [header for header in CSV_HEADERS if header not in headers]
            if missing:
                raise CommandError(
                    "CSV incompatibile: mancano le colonne richieste: %s" % ", ".join(missing)
                )
            return list(reader)

    def _resolve_user(self, username: str):
        if not username:
            return None
        UserModel = get_user_model()
        user = UserModel.objects.filter(username=username).first()
        if not user:
            raise CommandError(f"Utente Django non trovato: {username}")
        return user

    def _row_to_payload(self, row: dict[str, str]) -> dict[str, object]:
        reporter = _clean_single_line(row.get("Chi segnala", ""))
        data_segnalazione = _parse_local_datetime(row.get("Data segnalazione", ""))
        titolo = _clean_single_line(row.get("Nominativo Segnalato", ""))
        descrizione = _clean_multiline(row.get("Descrizione della segnalazione", ""))

        if not reporter:
            raise ValueError("campo 'Chi segnala' vuoto")
        if not titolo:
            raise ValueError("campo 'Nominativo Segnalato' vuoto")
        if not descrizione:
            raise ValueError("campo 'Descrizione della segnalazione' vuoto")

        return {
            "data_segnalazione": data_segnalazione,
            "titolo": titolo,
            "descrizione": descrizione,
            "preposto": reporter,
            "chi_segnala": reporter,
        }
