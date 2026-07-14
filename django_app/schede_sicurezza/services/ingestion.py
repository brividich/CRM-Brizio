"""Estrazione section-aware delle schede dati di sicurezza (SDS/SDS) via PyMuPDF.

Best-effort per costruzione (BUILD_SPEC §4): nessuna eccezione deve propagare
fuori da `estrai_sds`. Se una sezione non è individuabile i campi curati
restano vuoti e `estrazione_stato` riflette l'esito parziale/fallito — la
scheda resta comunque utilizzabile con inserimento manuale.

Nessuna dipendenza da servizi esterni/AI in questa fase.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Struttura standard SDS a 16 sezioni (Reg. UE 2020/878). Solo le sezioni 2/4/8/10
# alimentano campi curati in Fase 1; le altre restano nell'estratto grezzo per
# tracciabilità.
SEZIONI_STANDARD = {
    1: "Identificazione della sostanza/miscela e della società/impresa",
    2: "Identificazione dei pericoli",
    3: "Composizione/informazioni sugli ingredienti",
    4: "Misure di primo soccorso",
    5: "Misure antincendio",
    6: "Misure in caso di rilascio accidentale",
    7: "Manipolazione e immagazzinamento",
    8: "Controllo dell'esposizione/protezione individuale",
    9: "Proprietà fisiche e chimiche",
    10: "Stabilità e reattività",
    11: "Informazioni tossicologiche",
    12: "Informazioni ecologiche",
    13: "Considerazioni sullo smaltimento",
    14: "Informazioni sul trasporto",
    15: "Informazioni sulla regolamentazione",
    16: "Altre informazioni",
}

# Header sezione tollerante a maiuscole/minuscole, spazi multipli e separatori
# diversi ("SEZIONE 2:", "Sezione 2 -", "SEZIONE  2."). Ancorato a inizio riga.
_HEADER_RE = re.compile(r"^\s*SEZIONE\s+(\d{1,2})\b\s*[:.\-–]?\s*(.*)$", re.IGNORECASE)

_GHS_RE = re.compile(r"\bGHS0[1-9]\b", re.IGNORECASE)
_EUH_PHRASE_RE = re.compile(r"\bEUH\d{3}\b", re.IGNORECASE)
_H_PHRASE_RE = re.compile(r"\bH\d{3}[A-Za-z]{0,2}\b", re.IGNORECASE)
_P_PHRASE_RE = re.compile(r"\bP\d{3}(?:\s*\+\s*P\d{3}){0,3}\b", re.IGNORECASE)


def _extract_pdf_text(source: Any) -> str:
    """Estrae il testo da un PDF (FieldFile, path o bytes) con PyMuPDF.

    Fail-safe: pymupdf assente, file mancante o PDF corrotto -> stringa vuota,
    mai un'eccezione propagata (pattern replicato da
    ``ai_assistant.services._extract_pdf_text``).
    """
    if not source:
        return ""
    try:
        import fitz  # pymupdf
    except Exception:
        logger.warning("PyMuPDF (fitz) non disponibile: estrazione SDS saltata.")
        return ""
    try:
        if isinstance(source, (bytes, bytearray)):
            data = bytes(source)
        elif hasattr(source, "open"):  # Django FieldFile
            with source.open("rb") as fh:
                data = fh.read()
        elif isinstance(source, (str, Path)):
            data = Path(source).read_bytes()
        else:
            return ""
        if not data:
            return ""
        with fitz.open(stream=data, filetype="pdf") as doc:
            return "\n".join(page.get_text() for page in doc)
    except Exception:
        logger.exception("Estrazione testo PDF SDS fallita")
        return ""


def _split_sections(text: str) -> dict[int, str]:
    """Segmenta il testo nelle sezioni standard SDS 1-16.

    Ritorna una mappa {numero_sezione: testo_sezione}. Sezioni non individuate
    sono semplicemente assenti dalla mappa: nessuna eccezione, l'estrazione è
    best-effort.
    """
    lines = text.splitlines()
    matches: list[tuple[int, int]] = []
    for idx, line in enumerate(lines):
        m = _HEADER_RE.match(line.strip())
        if not m:
            continue
        try:
            num = int(m.group(1))
        except ValueError:
            continue
        if 1 <= num <= 16:
            matches.append((idx, num))
    if not matches:
        return {}

    sections: dict[int, str] = {}
    for i, (idx, num) in enumerate(matches):
        end = matches[i + 1][0] if i + 1 < len(matches) else len(lines)
        body = "\n".join(lines[idx:end]).strip()
        # Se il numero ricompare (rumore/duplicati OCR), tieni il testo più lungo.
        if num not in sections or len(body) > len(sections[num]):
            sections[num] = body
    return sections


def _extract_pittogrammi(section2_text: str) -> list[str]:
    return sorted({m.upper() for m in _GHS_RE.findall(section2_text)})


def _extract_frasi_h(section2_text: str) -> list[str]:
    found = {m.upper() for m in _H_PHRASE_RE.findall(section2_text)}
    found |= {m.upper() for m in _EUH_PHRASE_RE.findall(section2_text)}
    return sorted(found)


def _extract_frasi_p(section2_text: str) -> list[str]:
    normalized = {re.sub(r"\s+", "", m).upper() for m in _P_PHRASE_RE.findall(section2_text)}
    return sorted(normalized)


def estrai_sds(scheda) -> None:
    """Esegue l'estrazione section-aware sul PDF di ``scheda`` e salva i campi curati.

    Best-effort per costruzione: qualunque errore imprevisto porta a
    ``estrazione_stato=fallita`` senza sollevare eccezioni.
    """
    from ..models import EstrazioneStato

    try:
        text = _extract_pdf_text(scheda.pdf)
    except Exception:
        logger.exception("Estrazione SDS: errore inatteso per scheda %s", scheda.pk)
        text = ""

    if not text.strip():
        scheda.estratto_grezzo = {}
        scheda.estrazione_stato = EstrazioneStato.FALLITA
        scheda.save(update_fields=["estratto_grezzo", "estrazione_stato"])
        return

    try:
        sections = _split_sections(text)
    except Exception:
        logger.exception("Estrazione SDS: segmentazione fallita per scheda %s", scheda.pk)
        sections = {}

    scheda.estratto_grezzo = {str(k): v for k, v in sections.items()}

    sec2 = sections.get(2, "")
    sec4 = sections.get(4, "")
    sec8 = sections.get(8, "")
    sec10 = sections.get(10, "")

    try:
        scheda.pittogrammi = _extract_pittogrammi(sec2)
        scheda.frasi_h = _extract_frasi_h(sec2)
        scheda.frasi_p = _extract_frasi_p(sec2)
    except Exception:
        logger.exception("Estrazione SDS: parsing pittogrammi/frasi fallito per scheda %s", scheda.pk)
        scheda.pittogrammi = []
        scheda.frasi_h = []
        scheda.frasi_p = []

    scheda.classificazione_clp = sec2.strip()
    scheda.primo_soccorso = sec4.strip()
    scheda.dpi_testo = sec8.strip()
    scheda.incompatibilita = sec10.strip()

    campi_chiave = (sec2, sec4, sec8, sec10)
    trovate = sum(1 for v in campi_chiave if v.strip())
    if trovate == len(campi_chiave):
        scheda.estrazione_stato = EstrazioneStato.OK
    elif trovate > 0:
        scheda.estrazione_stato = EstrazioneStato.PARZIALE
    else:
        scheda.estrazione_stato = EstrazioneStato.FALLITA

    scheda.save(update_fields=[
        "estratto_grezzo", "pittogrammi", "frasi_h", "frasi_p", "classificazione_clp",
        "primo_soccorso", "dpi_testo", "incompatibilita", "estrazione_stato",
    ])
