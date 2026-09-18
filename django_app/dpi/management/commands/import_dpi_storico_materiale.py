"""Import storico DPI dal foglio "STORICO" di MATERIALE ANTINFORTUNISTICO.xlsx.

A differenza di import_dpi_storico.py (formato a righe con codice fiscale),
qui il foglio è "a cascata": una riga per dipendente, poi colonne evento
1°..N° con testo libero tipo "GUANTO A MIS.9 20/01/2021", "SCARPE 26/01/2017".

Classifica ogni evento per famiglia DPI tramite parola chiave (CategoriaDPI),
estrae la data (tollerante a formati 2/4 cifre e a trattini), abbina il
dipendente per nome/cognome contro AnagraficaDipendente e crea
RichiestaDPI (stato=CONSEGNATA) + ConsegnaDPI per ogni evento riconosciuto.

Ogni evento non classificabile, senza data, multi-item o con dipendente
non abbinato viene SALTATO e riportato in un'eccezione — mai indovinato.

Usage:
    python manage.py import_dpi_storico_materiale --file "MATERIALE ANTINFORTUNISTICO.xlsx"
    python manage.py import_dpi_storico_materiale --file ... --dry-run
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from dpi.models import CategoriaDPI, ConsegnaDPI, RichiestaDPI, StatoRichiesta

NOTE_MARKER = "[IMPORT storico MATERIALE ANTINFORTUNISTICO]"

# ---------------------------------------------------------------------------
# Classificazione per famiglia (keyword -> nome CategoriaDPI)
# ---------------------------------------------------------------------------

# I nomi qui devono coincidere ESATTAMENTE con CategoriaDPI già esistenti in catalogo
# (Protezione udito / Protezione occhi e viso / Abbigliamento protettivo sono categorie
# uniche condivise tra sotto-famiglie: cuffie, inserti/auricolari e tappi sono tutte
# "Protezione udito"; grembiule e tuta sono entrambe "Abbigliamento protettivo").
KEYWORDS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bSCARP", re.I), "Calzature di sicurezza"),
    (re.compile(r"\bGU[AO]N[NT]", re.I), "Guanti di protezione"),
    (re.compile(r"\bCUFFI", re.I), "Protezione udito"),
    (re.compile(r"\bOCCHIAL|SOPRAOCCHIAL", re.I), "Protezione occhi e viso"),
    (re.compile(r"\bSEMI ?MASCHER|\bMASCHER|\bMASCHERIN", re.I), "Protezione vie respiratorie"),
    (
        re.compile(r"\bAURICOL|\bARCHETTO|\bINS\.?\s*(RIC\.?)?\s*AURIC|\bINSERTI", re.I),
        "Protezione udito",
    ),
    (re.compile(r"\bTAPPI\b", re.I), "Protezione udito"),
    (re.compile(r"\bGREMBIUL", re.I), "Abbigliamento protettivo"),
    (re.compile(r"\bTUTA\b", re.I), "Abbigliamento protettivo"),
]

DATE_RE_4 = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
DATE_RE_2 = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2})\b")
MODEL_CODE_RE = re.compile(r"\b(?:A|AP|G)\d{2,4}\b")


def _excel_serial_to_date(n: int) -> date | None:
    try:
        return date(1899, 12, 30) + timedelta(days=int(n))
    except (ValueError, OverflowError):
        return None


def _parse_evento_data(cell_text: str) -> date | None:
    if re.fullmatch(r"\d{5}", cell_text):
        return _excel_serial_to_date(cell_text)
    m = DATE_RE_4.search(cell_text)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    m = DATE_RE_2.search(cell_text)
    if m:
        d, mo, y2 = (int(x) for x in m.groups())
        y = 2000 + y2
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def _is_multi_item(cell_text: str) -> bool:
    distinct_cats = {cat for rx, cat in KEYWORDS if rx.search(cell_text)}
    n_dates = len(DATE_RE_4.findall(cell_text)) + len(DATE_RE_2.findall(cell_text))
    n_model_codes = len(set(MODEL_CODE_RE.findall(cell_text.upper())))
    return len(distinct_cats) >= 2 or n_dates >= 2 or n_model_codes >= 2 or "," in cell_text


def _classify(cell_text: str) -> str | None:
    for rx, categoria in KEYWORDS:
        if rx.search(cell_text):
            return categoria
    return None


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().upper())


class Command(BaseCommand):
    help = "Importa lo storico DPI dal foglio STORICO di MATERIALE ANTINFORTUNISTICO.xlsx."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Percorso al file Excel da importare.")
        parser.add_argument("--sheet", default="STORICO", help="Nome del foglio (default: STORICO).")
        parser.add_argument("--dry-run", action="store_true", help="Simula senza salvare nulla.")
        parser.add_argument(
            "--delete-storico",
            action="store_true",
            help=f"Elimina i record con note_gestione='{NOTE_MARKER}' prima di importare.",
        )

    def handle(self, *args, **options):
        try:
            import openpyxl
        except ImportError:
            raise CommandError("openpyxl non è installato. Esegui: pip install openpyxl")

        from core.legacy_models import AnagraficaDipendente

        file_path = Path(options["file"])
        if not file_path.exists():
            raise CommandError(f"File non trovato: {file_path}")

        dry_run: bool = bool(options["dry_run"])
        delete_storico: bool = bool(options["delete_storico"])

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] Nessuna modifica verrà salvata.\n"))

        if delete_storico:
            qs = RichiestaDPI.objects.filter(note_gestione__startswith=NOTE_MARKER)
            count = qs.count()
            if not dry_run:
                qs.delete()
                self.stdout.write(self.style.WARNING(f"Eliminati {count} record {NOTE_MARKER}.\n"))
            else:
                self.stdout.write(self.style.WARNING(f"[DRY-RUN] Verrebbero eliminati {count} record.\n"))

        wb = openpyxl.load_workbook(file_path, data_only=True)
        ws = wb[options["sheet"]]
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        self.stdout.write(f"Righe dipendente: {len(rows)}\n")

        # Precarica lookup nome+cognome -> legacy_id (solo dipendenti con nome/cognome valorizzati).
        lookup: dict[str, list[int]] = {}
        anag_info: dict[int, tuple[str, str, str]] = {}
        for ad in AnagraficaDipendente.objects.all():
            nome, cognome = _norm(ad.nome), _norm(ad.cognome)
            if not nome and not cognome:
                continue
            lookup.setdefault(f"{cognome} {nome}", []).append(ad.pk)
            lookup.setdefault(f"{nome} {cognome}", []).append(ad.pk)
            anag_info[ad.pk] = (
                f"{ad.nome or ''} {ad.cognome or ''}".strip(),
                str(ad.email_notifica or ad.email or "").strip(),
                str(ad.reparto or "").strip(),
            )

        categoria_cache: dict[str, CategoriaDPI] = {}

        def get_categoria(nome_cat: str) -> CategoriaDPI:
            if nome_cat in categoria_cache:
                return categoria_cache[nome_cat]
            if dry_run:
                cat = CategoriaDPI.objects.filter(nome=nome_cat).first() or CategoriaDPI(nome=nome_cat)
            else:
                cat, _ = CategoriaDPI.objects.get_or_create(
                    nome=nome_cat, defaults={"is_active": True, "order_index": 0}
                )
            categoria_cache[nome_cat] = cat
            return cat

        n_creati = n_saltati = n_errori = 0
        eccezioni: list[str] = []

        for i, row in enumerate(rows, start=2):
            if not any(row):
                continue
            dipendente_nome = str(row[1] or "").strip()
            if not dipendente_nome:
                continue

            legacy_ids = lookup.get(_norm(dipendente_nome), [])
            if len(legacy_ids) == 1:
                legacy_id = legacy_ids[0]
                nome_r, email_r, reparto_r = anag_info[legacy_id]
            else:
                legacy_id = None
                nome_r, email_r, reparto_r = dipendente_nome.title(), "", ""
                if not legacy_ids:
                    eccezioni.append(f"  Riga {i} ({dipendente_nome}): nessun dipendente corrispondente in anagrafica.")
                else:
                    eccezioni.append(f"  Riga {i} ({dipendente_nome}): match ambiguo ({len(legacy_ids)} corrispondenze).")

            for col_idx, cell in enumerate(row[6:], start=7):
                if cell is None:
                    continue
                cell_text = str(cell).strip()
                if not cell_text:
                    continue

                if _is_multi_item(cell_text):
                    eccezioni.append(f"  Riga {i} col {col_idx} ({dipendente_nome}): multi-item — '{cell_text}'.")
                    n_saltati += 1
                    continue

                categoria_nome = _classify(cell_text)
                if not categoria_nome:
                    eccezioni.append(f"  Riga {i} col {col_idx} ({dipendente_nome}): non classificato — '{cell_text}'.")
                    n_saltati += 1
                    continue

                data_evento = _parse_evento_data(cell_text)
                if not data_evento:
                    eccezioni.append(f"  Riga {i} col {col_idx} ({dipendente_nome}): data non riconosciuta — '{cell_text}'.")
                    n_saltati += 1
                    continue

                if legacy_id is None:
                    # Dipendente non abbinato: nessun dato creato, già segnalato sopra per la riga.
                    n_saltati += 1
                    continue

                categoria = get_categoria(categoria_nome)

                if not dry_run:
                    gia_presente = ConsegnaDPI.objects.filter(
                        data_consegna=data_evento,
                        richiesta__categoria=categoria,
                        richiesta__richiedente_legacy_id=legacy_id,
                    ).exists()
                    if gia_presente:
                        n_saltati += 1
                        continue

                    try:
                        with transaction.atomic():
                            richiesta = RichiestaDPI.objects.create(
                                categoria=categoria,
                                quantita=1,
                                motivazione="",
                                stato=StatoRichiesta.CONSEGNATA,
                                richiedente_legacy_id=legacy_id,
                                richiedente_nome=nome_r,
                                richiedente_email=email_r,
                                richiedente_reparto=reparto_r,
                                note_gestione=f"{NOTE_MARKER} {cell_text}",
                            )
                            ts = datetime.combine(data_evento, datetime.min.time(), tzinfo=dt_timezone.utc)
                            RichiestaDPI.objects.filter(pk=richiesta.pk).update(created_at=ts)
                            ConsegnaDPI.objects.create(
                                richiesta=richiesta,
                                data_consegna=data_evento,
                                consegnato_da_nome="Import storico",
                                note_consegna=cell_text,
                                firmato_ricevuta=False,
                                data_scadenza_stimata=None,
                            )
                        n_creati += 1
                    except Exception as exc:
                        eccezioni.append(f"  Riga {i} col {col_idx} ({dipendente_nome}): ERRORE — {exc}")
                        n_errori += 1
                else:
                    n_creati += 1

        self.stdout.write("")
        if eccezioni:
            self.stdout.write(self.style.WARNING(f"Eccezioni ({len(eccezioni)}):"))
            for msg in eccezioni:
                self.stdout.write(msg)
            self.stdout.write("")

        style = self.style.SUCCESS if n_errori == 0 else self.style.WARNING
        self.stdout.write(style(
            f"{'[DRY-RUN] ' if dry_run else ''}Completato: "
            f"{n_creati} creati, {n_saltati} saltati (eccezione), {n_errori} errori."
        ))
