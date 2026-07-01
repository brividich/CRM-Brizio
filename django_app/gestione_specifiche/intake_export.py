"""Intake: export del gestionale (listoni Excel) → CSV template `import_specifiche_storico`.

Adattatore tra i due "listoni" reali e il CSV F8:
- **SPTE** (`OK SPTE ... .xls`, gestionale): Specifiche Tecniche → `fonte=generica`.
  Il percorso UNC del PDF è nella colonna `tform_ddocm` (per il futuro bulk-attach).
- **Specifiche Cliente** (`MOD.097 ... .xlsx`, foglio `Registro`) → `fonte=cliente`.

Qui SOLO le funzioni **pure** (mappatura riga + parsing date), così sono testabili senza
file Excel. La lettura dei file e la scrittura CSV stanno nel management command
`converti_export_gestionale`.

Regole "In validità" (decisione F0 #5 — si importano solo le attive):
- SPTE: scarta codice vuoto/"0"; di **default** esclude le righe con `fvali` valorizzato
  (sospese/superate: hanno date di nota e annotazioni "SOSP."). Override: `escludi_fvali=False`.
- Cliente: tiene le righe con `SOSP.=NO` e `sospese/superate != 'S'`.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from .import_storico import EXPECTED_COLUMNS  # noqa: F401  (riusato dal command)

# Epoca seriale Excel (Windows): il giorno 0 è 1899-12-30.
_EXCEL_EPOCH = datetime(1899, 12, 30)


def _s(v) -> str:
    return "" if v is None else str(v).replace("\n", " ").strip()


def serial_to_iso(v) -> str:
    """Serial Excel (numero) o datetime → 'YYYY-MM-DD'. Stringa vuota se non convertibile."""
    if v is None or v == "":
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    if f <= 0:
        return ""
    try:
        return (_EXCEL_EPOCH + timedelta(days=int(f))).date().isoformat()
    except (OverflowError, ValueError):
        return ""


def _riga_vuota(**kw) -> dict:
    base = {c: "" for c in EXPECTED_COLUMNS}
    base.update(tipo="specifica", stato="in_validita")
    base.update(kw)
    return base


def mappa_spte(rec: dict, *, escludi_fvali: bool = True) -> dict:
    """Mappa una riga del gestionale SPTE → riga template.

    `rec` usa i nomi-colonna del gestionale (cdocm, crevi_ddocm, fvali, tdocm,
    tspec_ddocm, dregi_ddocm, daggi_ddocm, tform_ddocm).
    Ritorna ``{"riga": dict|None, "path": str, "scarto": str}``.
    """
    codice = _s(rec.get("cdocm"))
    if not codice or codice == "0":
        return {"riga": None, "path": "", "scarto": "codice vuoto/0"}
    fvali = _s(rec.get("fvali"))
    if fvali and escludi_fvali:
        return {"riga": None, "path": "", "scarto": "fvali valorizzato (sospesa/superata)"}
    rev = _s(rec.get("crevi_ddocm")) or "0"
    titolo = _s(rec.get("tdocm")) or _s(rec.get("tspec_ddocm")) or codice
    data_ins = serial_to_iso(rec.get("dregi_ddocm")) or serial_to_iso(rec.get("daggi_ddocm"))
    path = _s(rec.get("tform_ddocm"))
    riga = _riga_vuota(
        codice=codice, revisione=rev, titolo=titolo[:300],
        fonte="generica", data_inserimento=data_ins,
    )
    return {"riga": riga, "path": path if path.startswith("\\\\") else "", "scarto": ""}


def mappa_cliente(rec: dict) -> dict:
    """Mappa una riga del Registro Specifiche Cliente → riga template.

    `rec`: cliente, codice (N° Documento), revisione, dataric (Data Ricevuto),
    sosp (SOSP.), sup (sospese/superate). Il Registro NON ha un titolo: si usa il
    codice come titolo (obbligatorio nel template).
    Ritorna ``{"riga": dict|None, "scarto": str}``.
    """
    codice = _s(rec.get("codice"))
    if not codice:
        return {"riga": None, "scarto": "N° Documento vuoto"}
    if _s(rec.get("sosp")).upper() == "SI" or _s(rec.get("sup")).upper() == "S":
        return {"riga": None, "scarto": "sospesa/superata"}
    rev = _s(rec.get("revisione"))
    if rev.upper() in ("N/A", "NA"):
        rev = ""
    rev = rev or "0"
    dataric = _s(rec.get("dataric"))
    data_ins = "" if dataric.upper() in ("N/A", "NA", "") else serial_to_iso(rec.get("dataric"))
    riga = _riga_vuota(
        codice=codice, revisione=rev, titolo=codice,
        fonte="cliente", cliente=_s(rec.get("cliente")), data_inserimento=data_ins,
    )
    return {"riga": riga, "scarto": ""}


# --- Bulk-attach: PDF dalla share UNC → Specifica.allegato ---------------------
def attacca_pdf(spec, path, *, forza: bool = False, apply: bool = False) -> str:
    """Attacca il PDF in `path` alla `spec`. Ritorna un esito:

    'gia_allegato' (già presente e non forzato) | 'file_mancante' (path assente) |
    'da_allegare' (dry-run: attaccabile) | 'allegato' (scritto con --apply).

    Idempotente: salta le specifiche che hanno già un allegato salvo `forza=True`.
    Lo storage (`Specifica.allegato`) cifra at-rest in modo trasparente.
    """
    from django.core.files.base import ContentFile

    if getattr(spec, "allegato", None) and spec.allegato.name and not forza:
        return "gia_allegato"
    if not path or not os.path.isfile(path):
        return "file_mancante"
    if not apply:
        return "da_allegare"
    with open(path, "rb") as fh:
        data = fh.read()
    spec.allegato.save(os.path.basename(path), ContentFile(data), save=True)
    return "allegato"
