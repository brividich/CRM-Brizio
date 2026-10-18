"""Lettura dei documenti in ingresso: dal file al testo, poi date, numeri, nomi.

Base comune per le letture che **propongono** i campi di un modulo da un
documento ricevuto (attestati degli enti di formazione, DDT dei DPI…). Niente
qui salva qualcosa: chi chiama mostra la proposta e una persona conferma.

- PDF: testo nativo di ogni pagina; le pagine senza testo (scansioni) passano
  dall'OCR con lo stesso Tesseract dei referti medici
  (``anagrafica.services.referti_ocr``), 200 dpi e ``--psm 6``.
- Immagini (JPG, PNG, WEBP — foto dal telefono): OCR diretto.
- Al massimo :data:`MAX_PAGINE` pagine: un attestato o un DDT stanno in poche
  pagine, e l'OCR di un fascicolo intero bloccherebbe la richiesta.

Nessuna AI generativa: le proposte nascono da regole verificabili (etichette,
formati, corrispondenze esatte con anagrafiche del portale).
"""
from __future__ import annotations

import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

logger = logging.getLogger(__name__)

MAX_PAGINE = 4
MAX_BYTES = 15 * 1024 * 1024
MIN_TESTO_NATIVO = 40  # sotto: la pagina è una scansione


class DocumentoNonLeggibile(Exception):
    """Il file non si legge, con un motivo dicibile a una persona."""


@dataclass
class Lettura:
    testo: str
    pagine: int = 0
    ocr: bool = False
    avvisi: list[str] = field(default_factory=list)

    @property
    def normalizzato(self) -> str:
        return normalizza(self.testo)


# ── Testo ────────────────────────────────────────────────────────────────────

def _ocr_png(png: bytes) -> str:
    from anagrafica.services.referti_ocr import ErroreLettura, disponibile, ocr_immagine

    if not disponibile():
        return ""
    try:
        return ocr_immagine(png)
    except ErroreLettura as exc:
        logger.info("Lettura documento: OCR non riuscito (%s)", exc)
        return ""


def _ocr_disponibile() -> bool:
    try:
        from anagrafica.services.referti_ocr import disponibile

        return disponibile()
    except Exception:  # noqa: BLE001
        return False


def _leggi_pdf(contenuto: bytes) -> Lettura:
    import fitz

    from anagrafica.services.referti_ocr import ErroreLettura, rasterizza_pagina

    try:
        doc = fitz.open(stream=bytes(contenuto), filetype="pdf")
    except Exception as exc:
        raise DocumentoNonLeggibile("Il file non è un PDF leggibile.") from exc
    parti, ocr, avvisi = [], False, []
    try:
        totale = doc.page_count
        nativi = [(doc[i].get_text() or "").strip() for i in range(min(totale, MAX_PAGINE))]
    finally:
        doc.close()
    for i, nativo in enumerate(nativi):
        if len(nativo) >= MIN_TESTO_NATIVO:
            parti.append(nativo)
            continue
        try:
            letto = _ocr_png(rasterizza_pagina(contenuto, i))
        except ErroreLettura:
            letto = ""
        if letto.strip():
            ocr = True
        parti.append("\n".join(p for p in (letto, nativo) if p.strip()))
    if totale > MAX_PAGINE:
        avvisi.append(f"Lette solo le prime {MAX_PAGINE} pagine su {totale}.")
    return Lettura("\n".join(parti), pagine=totale, ocr=ocr, avvisi=avvisi)


def _leggi_immagine(contenuto: bytes) -> Lettura:
    from PIL import Image, ImageOps

    try:
        img = Image.open(io.BytesIO(contenuto))
        img = ImageOps.exif_transpose(img).convert("L")  # foto dal telefono: orientamento e grigi
    except Exception as exc:
        raise DocumentoNonLeggibile("Il file non è un'immagine leggibile.") from exc
    lato = max(img.size)
    if lato > 3000:
        img.thumbnail((3000, 3000))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    testo = _ocr_png(buf.getvalue())
    return Lettura(testo, pagine=1, ocr=bool(testo.strip()))


def leggi(contenuto: bytes) -> Lettura:
    """Testo del documento. Solleva :class:`DocumentoNonLeggibile` solo per file
    non apribili; un documento senza testo torna vuoto con un avviso."""
    if not contenuto:
        raise DocumentoNonLeggibile("Il file è vuoto.")
    if len(contenuto) > MAX_BYTES:
        raise DocumentoNonLeggibile(f"Il file supera {MAX_BYTES // (1024 * 1024)} MB.")
    lettura = _leggi_pdf(contenuto) if contenuto[:5] == b"%PDF-" else _leggi_immagine(contenuto)
    if not lettura.testo.strip():
        lettura.avvisi.append(
            "Nessun testo riconosciuto: la scansione potrebbe essere sbiadita o storta."
            if _ocr_disponibile() else
            "Il documento è una scansione e il riconoscimento del testo (Tesseract) non è installato su questo server."
        )
    return lettura


# ── Normalizzazione e ricerca ────────────────────────────────────────────────

def normalizza(testo: str) -> str:
    """Maiuscolo, senza accenti, spazi singoli: per confronti tolleranti."""
    senza = unicodedata.normalize("NFKD", testo or "")
    senza = "".join(c for c in senza if not unicodedata.combining(c))
    return re.sub(r"[ \t ]+", " ", senza.upper())


_MESI = {
    "GENNAIO": 1, "FEBBRAIO": 2, "MARZO": 3, "APRILE": 4, "MAGGIO": 5, "GIUGNO": 6,
    "LUGLIO": 7, "AGOSTO": 8, "SETTEMBRE": 9, "OTTOBRE": 10, "NOVEMBRE": 11, "DICEMBRE": 12,
}
_DATA_NUM_RE = re.compile(r"\b(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4}|\d{2})\b")
_DATA_TESTO_RE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(_MESI) + r")\s+(\d{4})\b")


def _data(g: int, m: int, a: int) -> date | None:
    if a < 100:
        a += 2000
    try:
        d = date(a, m, g)
    except ValueError:
        return None
    return d if 1990 <= d.year <= 2100 else None


def date_nel_testo(testo_norm: str) -> list[tuple[int, date]]:
    """(posizione, data) di tutte le date: 12/03/2026, 12-3-26, 12.03.2026, 12 MARZO 2026."""
    trovate = []
    for m in _DATA_NUM_RE.finditer(testo_norm):
        d = _data(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            trovate.append((m.start(), d))
    for m in _DATA_TESTO_RE.finditer(testo_norm):
        d = _data(int(m.group(1)), _MESI[m.group(2)], int(m.group(3)))
        if d:
            trovate.append((m.start(), d))
    return sorted(trovate)


def data_dopo_etichetta(testo_norm: str, etichette: tuple[str, ...], finestra: int = 60) -> date | None:
    """La prima data entro ``finestra`` caratteri dopo una delle etichette (in ordine di priorità)."""
    date_pos = date_nel_testo(testo_norm)
    for etichetta in etichette:
        for m in re.finditer(etichetta, testo_norm):
            for pos, d in date_pos:
                if m.end() <= pos <= m.end() + finestra:
                    return d
    return None


def contiene_parola(testo_norm: str, frase: str) -> bool:
    """``frase`` (normalizzata) compare come parola intera nel testo."""
    frase = normalizza(frase).strip()
    if len(frase) < 2:
        return False
    return re.search(r"(?<![A-Z0-9])" + re.escape(frase) + r"(?![A-Z0-9])", testo_norm) is not None


def contesto(testo: str, indice: int, raggio: int = 60) -> str:
    inizio, fine = max(0, indice - raggio), min(len(testo), indice + raggio)
    return re.sub(r"\s+", " ", testo[inizio:fine]).strip()
