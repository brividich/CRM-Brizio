from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from timbri.models import RegistroTimbro, TimbriImportIssue
from timbri.views import _resolve_operatore, _tipo_from_text


def _text(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _parse_bool(raw: str) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "vero", "yes", "si", "s", "x"}


def _parse_date(raw: str):
    value = str(raw or "").strip()
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:10], fmt).date()
        except ValueError:
            continue
    return None


class Command(BaseCommand):
    help = (
        "Importa il registro timbri da CSV SharePoint senza scaricare immagini. "
        "I record vengono agganciati solo ai dipendenti trovati nell'anagrafica centrale."
    )

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Percorso del file CSV da importare.")
        parser.add_argument("--dry-run", action="store_true", help="Esegue il parsing ma non salva modifiche.")
        parser.add_argument("--encoding", default="utf-8-sig", help="Encoding CSV (default: utf-8-sig).")
        parser.add_argument("--limit", type=int, default=0, help="Numero massimo di righe da processare.")

    def handle(self, *args, **options):
        csv_path = Path(str(options["csv_path"])).expanduser()
        if not csv_path.exists():
            raise CommandError(f"CSV non trovato: {csv_path}")
        if not csv_path.is_file():
            raise CommandError(f"Percorso non valido (non e' un file): {csv_path}")

        rows = self._load_rows(csv_path, encoding=str(options.get("encoding") or "utf-8-sig"))
        if not rows:
            self.stdout.write(self.style.WARNING("CSV vuoto: nessuna riga da importare."))
            return

        dry_run = bool(options.get("dry_run"))
        limit = max(0, int(options.get("limit") or 0))
        now = timezone.now()
        source_file = csv_path.name

        stats = {
            "rows": 0,
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "skipped_lookup": 0,
            "skipped_edited": 0,
            "skipped_invalid": 0,
        }
        errors: list[str] = []

        with transaction.atomic():
            for line_no, row in enumerate(rows, start=2):
                if limit and stats["rows"] >= limit:
                    break

                stats["rows"] += 1

                payload = self._row_to_payload(row)
                sharepoint_item_id = payload["sharepoint_item_id"]
                if not sharepoint_item_id:
                    stats["skipped_invalid"] += 1
                    msg = "colonna 'ID' mancante."
                    errors.append(f"Riga {line_no}: {msg}")
                    self._upsert_issue(source_file, line_no, row, payload, msg)
                    continue

                try:
                    operatore = self._resolve_operatore_from_payload(payload)
                except Exception as exc:
                    stats["skipped_lookup"] += 1
                    errors.append(f"Riga {line_no}: {exc}")
                    self._upsert_issue(source_file, line_no, row, payload, str(exc))
                    continue

                existing = (
                    RegistroTimbro.objects.filter(sharepoint_item_id=sharepoint_item_id)
                    .order_by("-id")
                    .first()
                )
                if existing and existing.edited_in_portal:
                    stats["skipped_edited"] += 1
                    self._upsert_issue(
                        source_file,
                        line_no,
                        row,
                        payload,
                        "Record saltato: modificato manualmente nel portale.",
                    )
                    continue

                registro = existing or RegistroTimbro(operatore=operatore, sharepoint_item_id=sharepoint_item_id)
                registro.operatore = operatore
                registro.codice_timbro = payload["codice_timbro"]
                registro.qualifica = payload["qualifica"]
                registro.tipo_timbro = payload["tipo_timbro"]
                registro.data_consegna = payload["data_consegna"]
                registro.data_ritiro = payload["data_ritiro"]
                registro.note = payload["note"]
                registro.firma_testo = payload["firma_testo"]
                registro.is_attivo = payload["is_attivo"]
                registro.is_archived = payload["is_archived"]
                registro.edited_in_portal = False
                if not existing:
                    registro.imported_at = now
                    registro.last_import_at = now

                if existing is None:
                    registro.save()
                    self._mark_issue_resolved(source_file, line_no, sharepoint_item_id)
                    stats["created"] += 1
                    continue

                changed_fields = self._changed_fields(existing, registro)
                if changed_fields:
                    registro.last_import_at = now
                    registro.save(update_fields=changed_fields + ["last_import_at", "updated_at"])
                    self._mark_issue_resolved(source_file, line_no, sharepoint_item_id)
                    stats["updated"] += 1
                else:
                    self._mark_issue_resolved(source_file, line_no, sharepoint_item_id)
                    stats["unchanged"] += 1

            if dry_run:
                transaction.set_rollback(True)

        suffix = " [DRY-RUN]" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                "Import completato%s rows=%s created=%s updated=%s unchanged=%s skipped_lookup=%s skipped_edited=%s skipped_invalid=%s"
                % (
                    suffix,
                    stats["rows"],
                    stats["created"],
                    stats["updated"],
                    stats["unchanged"],
                    stats["skipped_lookup"],
                    stats["skipped_edited"],
                    stats["skipped_invalid"],
                )
            )
        )
        if errors:
            self.stdout.write(self.style.WARNING(f"Dettaglio scarti ({len(errors)}):"))
            for error in errors[:50]:
                self.stdout.write(self.style.WARNING(f"  {error}"))
            if len(errors) > 50:
                self.stdout.write(self.style.WARNING(f"  ... altri {len(errors) - 50}"))

    def _load_rows(self, csv_path: Path, *, encoding: str) -> list[dict[str, str]]:
        with csv_path.open("r", encoding=encoding, newline="") as handle:
            reader = csv.DictReader(handle)
            headers = {str(h or "").strip() for h in (reader.fieldnames or [])}
            required = {"ID", "Tipo timbro", "Attivo"}
            missing = sorted(required - headers)
            if missing:
                raise CommandError("CSV incompatibile: mancano le colonne richieste: %s" % ", ".join(missing))
            return list(reader)

    def _row_to_payload(self, row: dict[str, str]) -> dict[str, object]:
        operatore_label = _text(row, "Operatore", "OPERATORE CONTROLLORE")
        matricola = _text(row, "Operatore: Matricola")
        reparto = _text(row, "Operatore: Reparto")
        codice_timbro = _text(row, "TIMBRO")[:120]
        qualifica_csv = _text(row, "QUALIFICA")
        qualifica = qualifica_csv[:200]
        data_consegna = _parse_date(_text(row, "Consegna Timbro"))
        data_ritiro = _parse_date(_text(row, "Data ritiro timbro"))
        firma_testo = _text(row, "FIRMA")
        note = _text(row, "NOTE")
        is_attivo = _parse_bool(_text(row, "Attivo"))
        is_archived = (not is_attivo) and bool(data_ritiro)

        return {
            "sharepoint_item_id": _text(row, "ID"),
            "operatore_label": operatore_label,
            "operatore_label_alt": _text(row, "OPERATORE CONTROLLORE"),
            "matricola": matricola,
            "reparto": reparto,
            "codice_timbro": codice_timbro,
            "qualifica_csv": qualifica_csv,
            "qualifica": qualifica,
            "tipo_timbro": _tipo_from_text(_text(row, "Tipo timbro")),
            "data_consegna": data_consegna,
            "data_ritiro": data_ritiro,
            "firma_testo": firma_testo,
            "note": note,
            "is_attivo": is_attivo,
            "is_archived": is_archived,
        }

    def _resolve_operatore_from_payload(self, payload: dict[str, object]):
        labels: list[str] = []
        for key in ["operatore_label", "operatore_label_alt"]:
            value = str(payload.get(key) or "").strip()
            if value and value not in labels:
                labels.append(value)
        if not labels:
            labels.append("")

        last_exc: Exception | None = None
        for label in labels:
            try:
                return _resolve_operatore(
                    "",
                    label,
                    str(payload.get("matricola") or ""),
                    str(payload.get("reparto") or ""),
                    str(payload.get("qualifica_csv") or ""),
                )
            except Exception as exc:
                last_exc = exc
        if last_exc:
            raise last_exc
        raise LookupError("Operatore non trovato nell'anagrafica centrale.")

    def _upsert_issue(
        self,
        source_file: str,
        line_no: int,
        row: dict[str, str],
        payload: dict[str, object],
        reason: str,
    ) -> None:
        TimbriImportIssue.objects.update_or_create(
            source_file=source_file,
            csv_row_number=line_no,
            defaults={
                "sharepoint_item_id": str(payload.get("sharepoint_item_id") or "")[:100],
                "operatore_label": str(payload.get("operatore_label") or "")[:200],
                "operatore_label_alt": str(payload.get("operatore_label_alt") or "")[:200],
                "matricola": str(payload.get("matricola") or "")[:100],
                "reparto": str(payload.get("reparto") or "")[:200],
                "qualifica": str(payload.get("qualifica_csv") or "")[:200],
                "codice_timbro": str(payload.get("codice_timbro") or "")[:120],
                "tipo_timbro_raw": _text(row, "Tipo timbro")[:100],
                "attivo_raw": _text(row, "Attivo")[:20],
                "motivo_scarto": reason,
                "raw_payload": json.dumps(row, ensure_ascii=False, sort_keys=True),
                "is_resolved": False,
            },
        )

    def _mark_issue_resolved(self, source_file: str, line_no: int, sharepoint_item_id: str) -> None:
        TimbriImportIssue.objects.filter(
            Q(source_file=source_file, csv_row_number=line_no)
            | Q(sharepoint_item_id=sharepoint_item_id)
        ).update(is_resolved=True, motivo_scarto="")

    def _changed_fields(self, existing: RegistroTimbro, incoming: RegistroTimbro) -> list[str]:
        changed: list[str] = []
        for field in [
            "operatore",
            "codice_timbro",
            "qualifica",
            "tipo_timbro",
            "data_consegna",
            "data_ritiro",
            "note",
            "firma_testo",
            "is_attivo",
            "is_archived",
            "edited_in_portal",
        ]:
            current = getattr(existing, f"{field}_id") if field == "operatore" else getattr(existing, field)
            new_value = getattr(incoming, f"{field}_id") if field == "operatore" else getattr(incoming, field)
            if current != new_value:
                changed.append(field)
        return changed
