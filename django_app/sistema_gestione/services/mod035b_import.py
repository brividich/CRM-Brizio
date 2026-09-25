"""Parser del Folder B EN 9100 dal PDF MOD.035B.

Il contenuto aziendale resta fuori dal repository: il parser usa le tabelle del
PDF a runtime e restituisce solo strutture da salvare nel database.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


class Mod035BFormatoNonRiconosciuto(ValueError):
    pass


@dataclass
class DomandaImportata:
    punti: str
    testo: str


@dataclass
class SezioneImportata:
    codice: str
    titolo: str
    criteri: str
    domande: list[DomandaImportata] = field(default_factory=list)


_SEZIONE_RE = re.compile(r"^(§[\d.]+)\s*[–-]\s*(.*?)\s+Criteri:\s*(.*)$", re.IGNORECASE)
_PUNTI_RE = re.compile(r"^\s*(?:§?\d+(?:\.\d+)*(?:\s+|$))+", re.IGNORECASE)


def _pulito(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def leggi_folder_b(sorgente) -> list[SezioneImportata]:
    import fitz

    doc = fitz.open(stream=sorgente, filetype="pdf") if isinstance(sorgente, (bytes, bytearray)) else fitz.open(sorgente)
    sezioni: list[SezioneImportata] = []
    corrente: SezioneImportata | None = None
    try:
        for pagina in doc:
            for tabella in pagina.find_tables().tables:
                for riga in tabella.extract():
                    if not riga:
                        continue
                    prima = _pulito(riga[0] if len(riga) else "")
                    seconda = _pulito(riga[1] if len(riga) > 1 else "")
                    match = _SEZIONE_RE.match(prima)
                    if match:
                        corrente = SezioneImportata(
                            codice=match.group(1), titolo=match.group(2), criteri=match.group(3),
                        )
                        sezioni.append(corrente)
                        continue
                    if corrente and seconda and _PUNTI_RE.match(prima) and not prima.startswith("CAR"):
                        corrente.domande.append(DomandaImportata(punti=prima, testo=seconda))
    finally:
        doc.close()
    sezioni = [s for s in sezioni if s.domande]
    if not sezioni or sum(len(s.domande) for s in sezioni) < 5:
        raise Mod035BFormatoNonRiconosciuto("Folder B EN 9100 non riconosciuto nel MOD.035B.")
    return sezioni
