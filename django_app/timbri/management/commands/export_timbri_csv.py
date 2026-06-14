from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from timbri.models import RegistroTimbro


# Mappa tipo_timbro interno -> etichetta "Tipo timbro" riconosciuta da
# import_timbri_csv (_tipo_from_text). Il round-trip deve preservare il tipo.
_TIPO_TO_LABEL = {
    RegistroTimbro.TIPO_FISICO: "Fisico",
    RegistroTimbro.TIPO_DIGITALE: "Digitale",
    RegistroTimbro.TIPO_FISICO_E_DIGITALE: "Fisico e digitale",
    RegistroTimbro.TIPO_ALTRO: "Altro",
    # SOLO_FIRMA / SOLO_SIGLA non hanno una resa testuale in _tipo_from_text:
    # vengono mappati su "Altro" per non perdere il record. Le varianti
    # firma/sigla restano comunque nel campo FIRMA del CSV.
    RegistroTimbro.TIPO_SOLO_FIRMA: "Altro",
    RegistroTimbro.TIPO_SOLO_SIGLA: "Altro",
}

# Header allineati a import_timbri_csv._row_to_payload (export -> import simmetrico).
_FIELDNAMES = [
    "ID",
    "Operatore",
    "Operatore: Matricola",
    "Operatore: Reparto",
    "TIMBRO",
    "QUALIFICA",
    "Tipo timbro",
    "Consegna Timbro",
    "Data ritiro timbro",
    "FIRMA",
    "NOTE",
    "Attivo",
]


def _date(value) -> str:
    return value.strftime("%Y-%m-%d") if value else ""


class Command(BaseCommand):
    help = (
        "Esporta i RegistroTimbro in un CSV compatibile con import_timbri_csv. "
        "Pensato per rigenerare il file sorgente (es. da dev verso prod). "
        "Il matching operatore viene rifatto in import sull'anagrafica di destinazione."
    )

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Percorso del file CSV da generare.")
        parser.add_argument(
            "--only-active",
            action="store_true",
            help="Esporta solo i timbri attivi (is_attivo=True).",
        )
        parser.add_argument(
            "--encoding",
            default="utf-8-sig",
            help="Encoding CSV (default: utf-8-sig, come l'export SharePoint).",
        )

    def handle(self, *args, **options):
        csv_path = Path(str(options["csv_path"])).expanduser()
        if csv_path.exists() and not csv_path.is_file():
            raise CommandError(f"Percorso non valido (non e' un file): {csv_path}")
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        qs = RegistroTimbro.objects.select_related("operatore").order_by("id")
        if options.get("only_active"):
            qs = qs.filter(is_attivo=True)

        encoding = str(options.get("encoding") or "utf-8-sig")
        written = 0
        skipped_no_id = 0

        with csv_path.open("w", encoding=encoding, newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_FIELDNAMES)
            writer.writeheader()
            for r in qs.iterator():
                if not (r.sharepoint_item_id or "").strip():
                    # Senza ID l'import scarterebbe la riga (skipped_invalid).
                    skipped_no_id += 1
                    continue
                op = r.operatore
                writer.writerow(
                    {
                        "ID": r.sharepoint_item_id,
                        "Operatore": op.full_name if op else "",
                        "Operatore: Matricola": (op.matricola if op else "") or "",
                        "Operatore: Reparto": (op.reparto if op else "") or "",
                        "TIMBRO": r.codice_timbro or "",
                        "QUALIFICA": r.qualifica or "",
                        "Tipo timbro": _TIPO_TO_LABEL.get(r.tipo_timbro, "Altro"),
                        "Consegna Timbro": _date(r.data_consegna),
                        "Data ritiro timbro": _date(r.data_ritiro),
                        "FIRMA": r.firma_testo or "",
                        "NOTE": r.note or "",
                        "Attivo": "1" if r.is_attivo else "0",
                    }
                )
                written += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Export completato: %s righe -> %s (skipped_no_id=%s)"
                % (written, csv_path, skipped_no_id)
            )
        )
