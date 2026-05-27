from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from assets.models import Asset


TAG_COLUMN_CANDIDATES = (
    "asset_tag",
    "asset tag",
    "tag",
    "asset_id",
    "asset id",
    "id asset",
    "codice asset",
    "codice",
)

NEW_NAME_COLUMN_CANDIDATES = (
    "new_name",
    "new name",
    "nuovo_nome",
    "nuovo nome",
    "nuovo nome asset",
    "nome nuovo",
    "nome corretto",
    "rinomina",
)


@dataclass(frozen=True)
class CsvRow:
    row_number: int
    asset_tag: str
    new_name: str


@dataclass(frozen=True)
class PlannedRename:
    row_number: int
    asset: Asset
    new_name: str


def normalize_spaces(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\r", " ").replace("\n", " ")).strip()


def normalize_header(value: Any) -> str:
    text = normalize_spaces(value).casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact_header(value: Any) -> str:
    return normalize_header(value).replace(" ", "")


class Command(BaseCommand):
    help = (
        "Aggiorna solo il campo Asset.name da CSV con asset_tag e nuovo nome. "
        "Dry-run di default; usare --commit per scrivere."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "file",
            nargs="?",
            help="CSV con colonne asset_tag e new_name/nuovo_nome. Non richiesto con --export-template.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Simula senza salvare (default).")
        parser.add_argument("--commit", action="store_true", help="Salva le rinomine in transaction.atomic().")
        parser.add_argument("--tag-column", default="", help="Nome colonna CSV da usare come asset tag.")
        parser.add_argument("--name-column", default="", help="Nome colonna CSV da usare come nuovo nome.")
        parser.add_argument(
            "--export-template",
            default="",
            help="Scrive un CSV template con asset_tag,current_name,new_name e termina.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Con --export-template sovrascrive il file esistente.",
        )

    def handle(self, *args, **options):
        if options["dry_run"] and options["commit"]:
            raise CommandError("Usare solo una tra --dry-run e --commit.")

        export_path = normalize_spaces(options.get("export_template"))
        if export_path:
            self._export_template(Path(export_path).expanduser(), force=bool(options["force"]))
            return

        file_value = normalize_spaces(options.get("file"))
        if not file_value:
            raise CommandError("Indicare un CSV oppure usare --export-template.")

        dry_run = not bool(options["commit"])
        file_path = Path(file_value).expanduser()
        rows = self._load_csv(
            file_path,
            tag_column=normalize_spaces(options.get("tag_column")),
            name_column=normalize_spaces(options.get("name_column")),
        )
        planned, unchanged, errors = self._plan(rows)

        mode = "DRY-RUN" if dry_run else "COMMIT"
        self.stdout.write(f"Modalita: {mode}")
        self.stdout.write(
            "Conteggi | "
            f"righe lette={len(rows)}, "
            f"da aggiornare={len(planned)}, "
            f"invariati={unchanged}, "
            f"errori={len(errors)}"
        )

        if errors:
            self.stdout.write(self.style.ERROR("Errori riga per riga:"))
            for error in errors:
                self.stdout.write(self.style.ERROR(f"- {error}"))
            raise CommandError("Rinomina annullata: correggere gli errori e rilanciare.")

        if planned:
            self.stdout.write("Rinomine previste:")
            for item in planned:
                self.stdout.write(
                    f"- riga {item.row_number}: {item.asset.asset_tag} | "
                    f"{item.asset.name!r} -> {item.new_name!r}"
                )

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN: nessuna modifica e stata salvata nel database."))
            return

        with transaction.atomic():
            for item in planned:
                item.asset.name = item.new_name
                item.asset.save(update_fields=["name", "updated_at"])
        self.stdout.write(self.style.SUCCESS("Rinomina asset completata."))

    def _export_template(self, path: Path, *, force: bool) -> None:
        if path.exists() and not force:
            raise CommandError(f"File gia esistente: {path}. Usa --force per sovrascrivere.")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["asset_tag", "current_name", "new_name"])
            for asset in Asset.objects.only("asset_tag", "name").order_by("asset_tag", "id"):
                writer.writerow([asset.asset_tag or "", asset.name or "", asset.name or ""])
        self.stdout.write(self.style.SUCCESS(f"Template esportato: {path}"))

    def _load_csv(self, path: Path, *, tag_column: str, name_column: str) -> list[CsvRow]:
        if not path.exists():
            raise CommandError(f"File non trovato: {path}")
        text = self._read_csv_text(path)
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,")
        except csv.Error:
            dialect = csv.excel
            dialect.delimiter = ";"

        reader = csv.DictReader(text.splitlines(), dialect=dialect)
        headers = [header for header in (reader.fieldnames or []) if header]
        if not headers:
            raise CommandError("CSV senza intestazioni.")

        resolved_tag_column = self._resolve_column(headers, tag_column, TAG_COLUMN_CANDIDATES, "asset tag")
        resolved_name_column = self._resolve_column(headers, name_column, NEW_NAME_COLUMN_CANDIDATES, "nuovo nome")

        rows: list[CsvRow] = []
        errors: list[str] = []
        seen_tags: set[str] = set()
        for row_number, raw_row in enumerate(reader, start=2):
            if all(not normalize_spaces(value) for value in raw_row.values()):
                continue
            asset_tag = normalize_spaces(raw_row.get(resolved_tag_column)).upper()
            new_name = normalize_spaces(raw_row.get(resolved_name_column))
            row_errors = []
            if not asset_tag:
                row_errors.append("asset_tag mancante")
            if not new_name:
                row_errors.append("nuovo nome mancante")
            if len(new_name) > 255:
                row_errors.append("nuovo nome oltre 255 caratteri")
            tag_key = asset_tag.casefold()
            if asset_tag and tag_key in seen_tags:
                row_errors.append(f"asset_tag duplicato nel CSV: {asset_tag}")
            if row_errors:
                errors.append(f"riga {row_number}: {', '.join(row_errors)}")
                continue
            seen_tags.add(tag_key)
            rows.append(CsvRow(row_number=row_number, asset_tag=asset_tag, new_name=new_name))

        if errors:
            for error in errors:
                self.stdout.write(self.style.ERROR(f"- {error}"))
            raise CommandError("CSV non valido: correggere gli errori e rilanciare.")
        return rows

    def _read_csv_text(self, path: Path) -> str:
        raw = path.read_bytes()
        for encoding in ("utf-8-sig", "utf-8", "cp1252"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise CommandError("Encoding CSV non riconosciuto: provati UTF-8 e cp1252.")

    def _resolve_column(self, headers: list[str], explicit: str, candidates: tuple[str, ...], label: str) -> str:
        headers_by_compact = {compact_header(header): header for header in headers}
        if explicit:
            key = compact_header(explicit)
            if key in headers_by_compact:
                return headers_by_compact[key]
            raise CommandError(f"Colonna {label} non trovata: {explicit}")
        for candidate in candidates:
            key = compact_header(candidate)
            if key in headers_by_compact:
                return headers_by_compact[key]
        raise CommandError(
            f"Colonna {label} non trovata. Usa --tag-column/--name-column oppure intestazioni riconosciute."
        )

    def _plan(self, rows: list[CsvRow]) -> tuple[list[PlannedRename], int, list[str]]:
        planned: list[PlannedRename] = []
        errors: list[str] = []
        unchanged = 0
        for row in rows:
            matches = list(Asset.objects.filter(asset_tag__iexact=row.asset_tag).only("id", "asset_tag", "name")[:2])
            if not matches:
                errors.append(f"riga {row.row_number}: asset non trovato per tag {row.asset_tag}")
                continue
            if len(matches) > 1:
                errors.append(f"riga {row.row_number}: asset tag ambiguo {row.asset_tag}")
                continue
            asset = matches[0]
            if asset.name == row.new_name:
                unchanged += 1
                continue
            planned.append(PlannedRename(row_number=row.row_number, asset=asset, new_name=row.new_name))
        return planned, unchanged, errors
