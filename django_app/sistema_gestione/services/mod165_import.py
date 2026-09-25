"""Import della «Control Matrix» dal PDF del MOD.165 - RAR Risk Assessment And Register.

Il PDF è l'export dell'Excel aziendale: pagine ruotate, una riga per controllo
con il codice «ISO 27002:2022 - X.Y» in fondo alla cella. Si leggono le parole
con le coordinate (PyMuPDF), si riportano nel verso di lettura e si assegnano
alle colonne in base alla posizione delle intestazioni.

Il contenuto del MOD.165 resta nel database: il PDF viene letto al momento
dell'import e mai copiato nel repository.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_CODICE_RE = re.compile(r"^\d\.\d{1,2}$")
_REQUIRED_RE = re.compile(r"\(\s*Required\s+by\s*:\s*([^)]*)\)?", re.IGNORECASE)
_OBBLIGHI = {
    "legislative": "obbligo_legislativo",
    "normative": "obbligo_normativo",
    "regulatory": "obbligo_regolatorio",
    "customer": "obbligo_cliente",
    "best practice": "buona_pratica",
}


class Mod165FormatoNonRiconosciuto(ValueError):
    pass


@dataclass
class RigaMod165:
    codice: str
    livello: int | None
    vulnerabilita: int | None
    riferimenti: str
    giustificazione: str
    obblighi: dict[str, bool] = field(default_factory=dict)


def _intero(testo: str) -> int | None:
    numeri = re.findall(r"(?<![\d.])([0-4])(?![\d.])", (testo or "").replace("(0-4)", ""))
    return int(numeri[0]) if numeri else None


def _pulisci(testo: str) -> str:
    return re.sub(r"\s+", " ", testo or "").strip()


def _separa_obblighi(testo: str) -> tuple[str, dict[str, bool]]:
    obblighi = {campo: False for campo in _OBBLIGHI.values()}
    match = _REQUIRED_RE.search(testo)
    if not match:
        return _pulisci(testo), obblighi
    for parte in match.group(1).split(","):
        chiave = parte.strip().lower()
        if chiave in _OBBLIGHI:
            obblighi[_OBBLIGHI[chiave]] = True
    return _pulisci(testo[: match.start()] + testo[match.end():]), obblighi


def leggi_control_matrix(sorgente) -> list[RigaMod165]:
    """``sorgente``: percorso del PDF o bytes."""
    import fitz  # PyMuPDF

    doc = fitz.open(stream=sorgente, filetype="pdf") if isinstance(sorgente, (bytes, bytearray)) else fitz.open(sorgente)
    righe: list[RigaMod165] = []
    visti: set[str] = set()
    try:
        for pagina in doc:
            parole = pagina.get_text("words")
            if not any(p[4] == "Justification" for p in parole):
                continue
            matrice = pagina.rotation_matrix
            ws = []
            for p in parole:
                r = fitz.Rect(p[:4]) * matrice
                ws.append((r.x0, r.y0, r.x1, r.y1, p[4]))

            def x_di(etichetta: str, lato: int = 0) -> float:
                return next(w[2 if lato else 0] for w in ws if w[4] == etichetta)

            try:
                x_app, x_vul, x_ref, x_jus = x_di("APPLIED?"), x_di("VULNERABILITY"), x_di("References"), x_di("Justification")
                x_vul_fine = x_di("VULNERABILITY", lato=1)
                x_obj = x_di("OBJECTIVE")
                testata = next(w[3] for w in ws if w[4] == "References")
            except StopIteration as exc:
                raise Mod165FormatoNonRiconosciuto("Intestazioni della Control Matrix non trovate.") from exc

            # Confini di colonna ricavati dalle intestazioni.
            b_app = x_app - 20
            b_vul = (x_app + x_vul) / 2 + 20
            b_ref = x_vul_fine + 2
            b_jus = x_jus - 15
            b_obj = x_jus + (x_obj - x_jus) / 2 - 60

            ancore = sorted(
                (w[1], w[4]) for w in ws if _CODICE_RE.match(w[4]) and w[0] < b_app and w[1] > testata
            )
            precedente = testata + 2
            for y, codice in ancore:
                banda = [w for w in ws if precedente < (w[1] + w[3]) / 2 <= y + 8]

                def colonna(x0: float, x1: float) -> str:
                    sel = sorted((w for w in banda if x0 <= w[0] < x1), key=lambda w: (round(w[1]), w[0]))
                    return " ".join(w[4] for w in sel)

                precedente = y + 8
                if codice in visti:
                    continue
                visti.add(codice)
                giustificazione, obblighi = _separa_obblighi(colonna(b_jus, b_obj))
                righe.append(RigaMod165(
                    codice=codice,
                    livello=_intero(colonna(b_app, b_vul)),
                    vulnerabilita=_intero(colonna(b_vul, b_ref)),
                    riferimenti=_pulisci(colonna(b_ref, b_jus)),
                    giustificazione=giustificazione,
                    obblighi=obblighi,
                ))
    finally:
        doc.close()
    if not righe:
        raise Mod165FormatoNonRiconosciuto("Nessuna riga della Control Matrix trovata nel PDF.")
    return righe
