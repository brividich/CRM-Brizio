"""
Management command: importa_rilevazioni_csv

Importa rilevazioni sicurezza da un file CSV esportato da SharePoint/Power Apps.

Uso:
    python manage.py importa_rilevazioni_csv /percorso/al/file.csv
    python manage.py importa_rilevazioni_csv /percorso/al/file.csv --clear
    python manage.py importa_rilevazioni_csv /percorso/al/file.csv --skip-existing
"""
from __future__ import annotations

import csv
import os
from datetime import date, datetime

from django.utils import timezone

from django.core.management.base import BaseCommand, CommandError

# Intestazioni CSV originali (con eventuali spazi e typo)
_CSV_COLUMNS = {
    "nominativo": "Nominativo",
    "tipologia": "Tipologia scheda",
    "reparto": "Reparto",
    "reparto_txt": "Reparto_txt",
    "data_segnalazione": "Data segnalazione",
    "descr_attivita": "Descrizione attività che venivano svolte durante l'accaduto",
    "descr_avvenimento": "Descrizione avvenimento ",          # trailing space intenzionale
    "usa_macchina": "Incidenti causato da uso macchina",
    "nome_macchina": "Nome macchina/attrezzatura e utilizoz",  # typo originale
    "buono_stato": "Buono stato macchina/attrezzatura",
    "utilizzo_dpi": "Utilizo DPI previsti",                   # typo originale
    "prima_volta": "Prima volta quasi incidente",
    "persone_coinvolte": "Persone coinvolte ",                 # trailing space intenzionale
    "causa_evento": "Causa che ha determinato l'evento",
    "altre_cause": "Altre cause",
    "misure_tecniche": "Misure tecniche, organizzative o procedurali per evitare che possa riaccedere questo genere di evento",
    "quali_misure": "Quali misure adottare",
    "approvazione_rls": "Approvazione RLS",
    "note_preposto": "Note preposto",
    "note_rspp": "Note RSPP / ASPP",
    "data_approvazione_rls": "Data approvazione RLS",
    "chiusura_rspp": "Chiusura RSPP",
    "data_chiusura_rspp": "Data chiusura RSPP",
    "id_originale": "ID",
    "contatore": "Contatore",
    "partecipanti": "Partecipanti",
    "why_1": "1 WHY",
    "why_2": "2 WHY",
    "why_3": "3 WHY",
    "why_4": "4 WHY",
    "why_5": "5 WHY",
}

_TIPO_NORMALIZATION = {
    "unsafe action": "Unsafe Act",
    "unsafe act": "Unsafe Act",
    "unsafe condition": "Unsafe Condition",
    "near miss": "Near Miss",
    "accident": "Accident",
}


def _col(row: dict, key: str) -> str:
    """Legge una colonna per nome e restituisce stringa stripped."""
    return str(row.get(_CSV_COLUMNS[key], "") or "").strip()


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("vero", "true", "1", "si", "sì", "yes")


def _parse_datetime(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(value, fmt)
            return timezone.make_aware(naive)
        except ValueError:
            continue
    return None


def _parse_date(value: str) -> date | None:
    dt = _parse_datetime(value)
    return dt.date() if dt else None


def _normalize_tipologia(value: str) -> str:
    return _TIPO_NORMALIZATION.get(value.strip().lower(), value.strip())


class Command(BaseCommand):
    help = "Importa rilevazioni sicurezza da file CSV esportato da SharePoint/Power Apps"

    def add_arguments(self, parser):
        parser.add_argument("csv_file", type=str, help="Percorso al file CSV da importare")
        parser.add_argument(
            "--clear",
            action="store_true",
            default=False,
            help="Elimina tutti i record esistenti prima dell'importazione",
        )
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            default=False,
            help="Salta le righe il cui ID originale è già presente nel database",
        )

    def handle(self, *args, **options):
        from rilevazione_incidenti.models import RilevazioneIncidente

        csv_path = options["csv_file"]
        if not os.path.exists(csv_path):
            raise CommandError(f"File non trovato: {csv_path}")

        if options["clear"]:
            count = RilevazioneIncidente.objects.count()
            RilevazioneIncidente.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Eliminati {count} record esistenti."))

        existing_ids: set[int] = set()
        if options["skip_existing"]:
            existing_ids = set(
                RilevazioneIncidente.objects.filter(id_originale__isnull=False)
                .values_list("id_originale", flat=True)
            )

        created = 0
        skipped = 0
        errors = 0

        with open(csv_path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for line_num, row in enumerate(reader, start=2):  # riga 1 = header
                try:
                    # ID originale
                    raw_id = _col(row, "id_originale")
                    id_orig = int(raw_id) if raw_id.isdigit() else None

                    if options["skip_existing"] and id_orig and id_orig in existing_ids:
                        skipped += 1
                        continue

                    # Reparto: preferisce reparto_txt se valorizzato
                    reparto_txt = _col(row, "reparto_txt")
                    reparto = reparto_txt if reparto_txt else _col(row, "reparto")

                    # Contatore
                    raw_cnt = _col(row, "contatore")
                    contatore = int(raw_cnt) if raw_cnt.isdigit() else 0

                    inst = RilevazioneIncidente(
                        nominativo=_col(row, "nominativo"),
                        tipologia_scheda=_normalize_tipologia(_col(row, "tipologia")),
                        reparto=reparto,
                        data_segnalazione=_parse_datetime(_col(row, "data_segnalazione")),
                        descrizione_attivita=_col(row, "descr_attivita"),
                        descrizione_avvenimento=_col(row, "descr_avvenimento"),
                        usa_macchina=_parse_bool(_col(row, "usa_macchina")),
                        nome_macchina=_col(row, "nome_macchina"),
                        buono_stato_macchina=_parse_bool(_col(row, "buono_stato")),
                        utilizzo_dpi=_parse_bool(_col(row, "utilizzo_dpi")),
                        prima_volta=_parse_bool(_col(row, "prima_volta")),
                        persone_coinvolte=_col(row, "persone_coinvolte"),
                        causa_evento=_col(row, "causa_evento"),
                        altre_cause=_col(row, "altre_cause"),
                        misure_tecniche=_parse_bool(_col(row, "misure_tecniche")),
                        quali_misure=_col(row, "quali_misure"),
                        approvazione_rls=_col(row, "approvazione_rls"),
                        note_preposto=_col(row, "note_preposto"),
                        note_rspp=_col(row, "note_rspp"),
                        data_approvazione_rls=_parse_date(_col(row, "data_approvazione_rls")),
                        chiusura_rspp=_parse_bool(_col(row, "chiusura_rspp")),
                        data_chiusura_rspp=_parse_date(_col(row, "data_chiusura_rspp")),
                        why_1=_col(row, "why_1"),
                        why_2=_col(row, "why_2"),
                        why_3=_col(row, "why_3"),
                        why_4=_col(row, "why_4"),
                        why_5=_col(row, "why_5"),
                        partecipanti=_col(row, "partecipanti"),
                        contatore=contatore,
                        id_originale=id_orig,
                    )
                    inst.save()
                    created += 1

                except Exception as exc:
                    errors += 1
                    self.stderr.write(f"  Riga {line_num}: errore – {exc}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Importazione completata: {created} creati, {skipped} saltati, {errors} errori."
            )
        )
