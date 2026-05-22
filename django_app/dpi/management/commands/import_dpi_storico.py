"""Import storico DPI da file Excel.

Crea automaticamente CategoriaDPI / TipoDPI / ModelloDPI / TagliaDPI mancanti,
risolve la persona tramite DipendenteAnagraficaCivile.codice_fiscale e registra
ogni riga come RichiestaDPI (stato=CONSEGNATA) + ConsegnaDPI.

Usage:
    python manage.py import_dpi_storico --file dpis-people.xlsx
    python manage.py import_dpi_storico --file dpis-people.xlsx --dry-run
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from dpi.models import (
    CategoriaDPI,
    ConsegnaDPI,
    ModelloDPI,
    RichiestaDPI,
    StatoRichiesta,
    TagliaDPI,
    TipoDPI,
)

# ---------------------------------------------------------------------------
# Catalogo: nome_excel → (categoria, tipo, codice_modello, nome_display)
# nome_display è il nome pulito che viene salvato su ModelloDPI.nome
# ---------------------------------------------------------------------------

CATALOG_MAP: dict[str, tuple[str, str, str, str]] = {
    "SCARPE S3 SRC (OPERATORI MACCHINE)": (
        "Calzature di sicurezza", "Scarpe S3 SRC", "SCARPE-S3-SRC", "Scarpe S3 SRC",
    ),
    "SCARPE S1 SRC (IMPIEGATI E TECNICI)": (
        "Calzature di sicurezza", "Scarpe S1 SRC", "SCARPE-S1-SRC", "Scarpe S1 SRC",
    ),
    "GUANTO A351 - Dermiflex Plus": (
        "Guanti di protezione", "Guanti meccanici/antitaglio", "GUANTO-A351", "Guanto A351 - Dermiflex Plus",
    ),
    "GUANTO AP50 - Aqua Cut Pro": (
        "Guanti di protezione", "Guanti meccanici/antitaglio", "GUANTO-AP50", "Guanto AP50 - Aqua Cut Pro",
    ),
    "GUANTO CUT 34-8743": (
        "Guanti di protezione", "Guanti meccanici/antitaglio", "GUANTO-CUT-34-8743", "Guanto CUT 34-8743",
    ),
    "GUANTO A810 - Protezione chimica": (
        "Guanti di protezione", "Guanti protezione chimica", "GUANTO-A810", "Guanto A810 - Protezione chimica",
    ),
    "GUANTO A302 - Nitrile ricoperto": (
        "Guanti di protezione", "Guanti protezione chimica", "GUANTO-A302", "Guanto A302 - Nitrile ricoperto",
    ),
    "CUFFIA PLUS PW48 SNR 23": (
        "Protezione udito", "Cuffie antirumore", "CUFFIA-PW48", "Cuffia PW48 SNR 23",
    ),
    "MASCHERA P301 ANTIPOLVERE FFP3": (
        "Protezione vie respiratorie", "Maschere antipolvere", "MASCHERA-P301", "Maschera P301 - FFP3",
    ),
    "OCCHIALI PROTEZIONE INCOLORE": (
        "Protezione occhi e viso", "Occhiali di protezione", "OCCHIALI-INCOLORE", "Occhiali di protezione incolore",
    ),
    "GREMBIULE IN PVC CON PETTORINA": (
        "Abbigliamento protettivo", "Grembiuli", "GREMBIULE-PVC", "Grembiule in PVC con pettorina",
    ),
    "TUTA PROTEZIONE Tipo 5 Tipo 6": (
        "Abbigliamento protettivo", "Tute di protezione", "TUTA-TIPO5-6", "Tuta di protezione Tipo 5/6",
    ),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(raw) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    raw_str = str(raw).strip()
    if not raw_str:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw_str, fmt).date()
        except ValueError:
            continue
    return None


def _parse_taglia(id1) -> str | None:
    if not id1:
        return None
    raw = str(id1).strip()
    if raw.lower().startswith("taglia:"):
        return raw[7:].strip()
    return raw or None


def _get_or_create_catalog(
    nome_dpi: str,
    dry_run: bool,
) -> tuple[CategoriaDPI, TipoDPI, ModelloDPI] | None:
    entry = CATALOG_MAP.get(nome_dpi)
    if not entry:
        return None
    cat_nome, tipo_nome, modello_codice, modello_nome = entry
    if dry_run:
        cat = CategoriaDPI.objects.filter(nome=cat_nome).first() or CategoriaDPI(nome=cat_nome)
        tipo = TipoDPI.objects.filter(categoria=cat, nome=tipo_nome).first() if cat.pk else None
        tipo = tipo or TipoDPI(nome=tipo_nome)
        modello = ModelloDPI.objects.filter(codice=modello_codice).first() or ModelloDPI(nome=modello_nome)
        return cat, tipo, modello

    categoria, _ = CategoriaDPI.objects.get_or_create(
        nome=cat_nome,
        defaults={"is_active": True, "order_index": 0},
    )
    tipo, _ = TipoDPI.objects.get_or_create(
        categoria=categoria,
        nome=tipo_nome,
        defaults={"is_active": True, "ordine": 0},
    )
    modello, _ = ModelloDPI.objects.get_or_create(
        codice=modello_codice,
        defaults={"tipo": tipo, "nome": modello_nome, "is_active": True},
    )
    return categoria, tipo, modello


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = "Importa lo storico DPI da file Excel (180 righe, 12 tipi)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help="Percorso al file Excel da importare.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simula l'import senza salvare nulla sul database.",
        )
        parser.add_argument(
            "--delete-storico",
            action="store_true",
            help="Elimina tutti i record con note_gestione='[IMPORT storico]' prima di importare.",
        )

    def handle(self, *args, **options):
        try:
            import openpyxl
        except ImportError:
            raise CommandError("openpyxl non è installato. Esegui: pip install openpyxl")

        from anagrafica.models import DipendenteAnagraficaCivile
        from core.legacy_models import AnagraficaDipendente

        file_path = Path(options["file"])
        if not file_path.exists():
            raise CommandError(f"File non trovato: {file_path}")

        dry_run: bool = bool(options["dry_run"])
        delete_storico: bool = bool(options["delete_storico"])

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] Nessuna modifica verrà salvata.\n"))

        if delete_storico:
            qs = RichiestaDPI.objects.filter(note_gestione="[IMPORT storico]")
            count = qs.count()
            if not dry_run:
                qs.delete()
                self.stdout.write(self.style.WARNING(
                    f"Eliminati {count} record [IMPORT storico] (RichiestaDPI + ConsegnaDPI a cascata).\n"
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f"[DRY-RUN] Verrebbero eliminati {count} record [IMPORT storico].\n"
                ))

        wb = openpyxl.load_workbook(file_path)
        ws = wb.active
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        self.stdout.write(f"Righe dati: {len(rows)}\n")

        # Precarica CF → legacy_anagrafica_id
        cf_set = {str(r[2]).strip().upper() for r in rows if r[2]}
        cf_to_legacy: dict[str, int] = {
            (c["codice_fiscale"] or "").strip().upper(): c["legacy_anagrafica_id"]
            for c in DipendenteAnagraficaCivile.objects.filter(
                codice_fiscale__in=cf_set
            ).values("codice_fiscale", "legacy_anagrafica_id")
            if c["codice_fiscale"]
        }

        # Precarica legacy_id → (nome, email, reparto)
        legacy_ids = list(set(cf_to_legacy.values()))
        anag_info: dict[int, tuple[str, str, str]] = {}
        for ad in AnagraficaDipendente.objects.filter(pk__in=legacy_ids):
            nome = f"{ad.nome or ''} {ad.cognome or ''}".strip()
            email = str(ad.email_notifica or ad.email or "").strip()
            reparto = str(ad.reparto or "").strip()
            anag_info[ad.pk] = (nome, email, reparto)

        n_creati = n_saltati = n_errori = 0
        avvisi: list[str] = []

        for i, row in enumerate(rows, start=2):
            row_p = list(row) + [None] * max(0, 16 - len(row))
            nome_excel    = row_p[1]
            cf_raw        = row_p[2]
            nome_dpi      = row_p[3]
            id1           = row_p[4]
            data_c_raw    = row_p[7]
            quantita_raw  = row_p[10]

            cf = str(cf_raw or "").strip().upper()
            nome_dpi = str(nome_dpi or "").strip()

            # Validazione campi obbligatori
            if not cf or not nome_dpi:
                avvisi.append(f"  Riga {i}: CF o nome DPI mancante — saltata.")
                n_saltati += 1
                continue

            data_consegna = _parse_date(data_c_raw)
            if not data_consegna:
                avvisi.append(
                    f"  Riga {i} ({nome_excel}): data consegna non valida '{data_c_raw}' — saltata."
                )
                n_saltati += 1
                continue

            catalog = _get_or_create_catalog(nome_dpi, dry_run)
            if not catalog:
                avvisi.append(
                    f"  Riga {i} ({nome_excel}): DPI '{nome_dpi}' non in catalogo — saltata."
                )
                n_saltati += 1
                continue

            categoria, tipo_dpi, modello_dpi = catalog

            # Taglia
            taglia_valore = _parse_taglia(id1)
            taglia_obj = None
            if taglia_valore and not dry_run and modello_dpi.pk:
                taglia_obj, _ = TagliaDPI.objects.get_or_create(
                    modello=modello_dpi,
                    valore=taglia_valore,
                    defaults={"is_active": True, "ordine": 0},
                )

            # Persona
            legacy_id = cf_to_legacy.get(cf)
            if legacy_id:
                nome_r, email_r, reparto_r = anag_info.get(legacy_id, ("", "", ""))
                if not nome_r:
                    nome_r = str(nome_excel or "").strip().title()
            else:
                avvisi.append(
                    f"  Riga {i} ({nome_excel}, {cf}): CF non in DipendenteAnagraficaCivile"
                    " — richiedente_legacy_id=None."
                )
                nome_r = str(nome_excel or "").strip().title()
                email_r = reparto_r = ""

            try:
                quantita = max(1, int(quantita_raw or 1))
            except (TypeError, ValueError):
                quantita = 1

            # Controllo duplicato
            if not dry_run:
                gia_presente = ConsegnaDPI.objects.filter(
                    data_consegna=data_consegna,
                    richiesta__categoria=categoria if categoria.pk else None,
                    **({
                        "richiesta__richiedente_legacy_id": legacy_id
                    } if legacy_id else {
                        "richiesta__richiedente_nome__iexact": nome_r
                    }),
                ).exists()
                if gia_presente:
                    avvisi.append(f"  Riga {i} ({nome_excel}): record già presente — saltata.")
                    n_saltati += 1
                    continue

            taglia_display = f" taglia {taglia_valore}" if taglia_valore else ""
            self.stdout.write(
                f"  {'[DRY] ' if dry_run else ''}Riga {i}: {nome_excel} — "
                f"{categoria.nome} / {modello_dpi.nome}{taglia_display}"
                f" ({data_consegna:%d/%m/%Y})"
            )

            if not dry_run:
                try:
                    with transaction.atomic():
                        richiesta = RichiestaDPI.objects.create(
                            categoria=categoria,
                            tipo_dpi=tipo_dpi,
                            modello_dpi=modello_dpi,
                            taglia_dpi=taglia_obj,
                            quantita=quantita,
                            motivazione="",
                            stato=StatoRichiesta.CONSEGNATA,
                            richiedente_legacy_id=legacy_id,
                            richiedente_nome=nome_r,
                            richiedente_email=email_r,
                            richiedente_reparto=reparto_r,
                            note_gestione="[IMPORT storico]",
                        )
                        # Riporta created_at alla data reale di consegna,
                        # bypassando auto_now_add tramite update().
                        from datetime import datetime as dt, timezone as tz
                        ts = dt.combine(data_consegna, dt.min.time()).replace(tzinfo=tz.utc)
                        RichiestaDPI.objects.filter(pk=richiesta.pk).update(created_at=ts)
                        ConsegnaDPI.objects.create(
                            richiesta=richiesta,
                            data_consegna=data_consegna,
                            consegnato_da_nome="Import storico",
                            note_consegna="",
                            firmato_ricevuta=False,
                            data_scadenza_stimata=None,
                        )
                    n_creati += 1
                except Exception as exc:
                    avvisi.append(f"  Riga {i} ({nome_excel}): ERRORE — {exc}")
                    n_errori += 1
            else:
                n_creati += 1

        # Report finale
        self.stdout.write("")
        if avvisi:
            self.stdout.write(self.style.WARNING("Avvisi:"))
            for msg in avvisi:
                self.stdout.write(msg)
            self.stdout.write("")

        style = self.style.SUCCESS if n_errori == 0 else self.style.WARNING
        self.stdout.write(style(
            f"{'[DRY-RUN] ' if dry_run else ''}Completato: "
            f"{n_creati} creati, {n_saltati} saltati, {n_errori} errori."
        ))
