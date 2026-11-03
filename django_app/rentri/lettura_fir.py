"""Lettura del formulario (FIR): propone i campi dello scarico, non salva niente.

Prima le regole (etichette e formati del modello di formulario): numero, data,
codice EER, quantità e unità, destinatario. Se mancano codice o quantità e
l'AI locale (Ollama del portale) è configurata, le chiede solo i campi mancanti;
quei valori tornano marcati ``fonte = "ai"`` e il modulo li mostra da
controllare. Il testo del documento non lascia il server.
"""
from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, InvalidOperation

from core import lettura_documenti as ld

from .catalogo import esteso, normalizza

logger = logging.getLogger(__name__)

_MAX_TESTO_AI = 4000

_NUMERO_RE = re.compile(
    r"(?:FORMULARIO|FIR)\s*(?:DI\s+IDENTIFICAZIONE\s*(?:DEL\s+)?(?:RIFIUTO)?\s*)?"
    r"(?:N(?:UMERO|R)?\.?|N°|NO\.?)\s*[:°.]?\s*([A-Z]{2,6}[\s\-]?\d{3,8}(?:\s*/\s*\d{2,4})?|[A-Z0-9][A-Z0-9\-/]{6,24})"
)
_EER_RE = re.compile(r"(?<!\d)(\d{2})[ .]?(\d{2})[ .]?(\d{2})\s?(\*)?(?!\d)")
_ETICHETTA_EER_RE = re.compile(r"\b(?:CODICE\s+)?(?:EER|C\.?E\.?R\.?)\b")
_QTA_RE = re.compile(
    r"(?<![\d,.])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(KG|KILOGRAMMI|LT|LITRI|L|M3|MC|M³|T|TON|TONNELLATE)\b"
)
_UNITA = {"KG": "kg", "KILOGRAMMI": "kg", "LT": "l", "LITRI": "l", "L": "l", "M3": "m3", "MC": "m3", "M³": "m3",
          "T": "t", "TON": "t", "TONNELLATE": "t"}


def _numero_it(raw: str) -> Decimal | None:
    raw = raw.strip()
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", raw):
        raw = raw.replace(".", "")  # 1.234 = milleduecentotrentaquattro
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _campo(valore, fonte: str = "regola", contesto: str = "") -> dict:
    return {"valore": valore, "fonte": fonte, "contesto": contesto}


def _codice_eer(norm: str) -> dict | None:
    candidati = []
    for m in _EER_RE.finditer(norm):
        sei = m.group(1) + m.group(2) + m.group(3)
        if not ("01" <= sei[:2] <= "20"):
            continue  # i capitoli dell'elenco vanno da 01 a 20: il resto sono date, CAP, partite IVA
        vicino = _ETICHETTA_EER_RE.search(norm[max(0, m.start() - 60):m.start()])
        candidati.append((0 if vicino else 1, m.start(), esteso(sei, bool(m.group(4)))))
    if not candidati:
        return None
    _, pos, codice = min(candidati)
    return _campo(codice, contesto=ld.contesto(norm, pos))


def _quantita(norm: str, tipo: str) -> dict | None:
    trovate = []
    for m in _QTA_RE.finditer(norm):
        q = _numero_it(m.group(1))
        if q is None or q <= 0:
            continue
        prima = norm[max(0, m.start() - 80):m.start()]
        peso = 3
        if "DESTINO" in prima or "VERIFICAT" in prima:
            peso = 0 if tipo == "M" else 2  # nello scarico effettivo conta il peso a destino
        elif "QUANTIT" in prima:
            peso = 1
        trovate.append((peso, m.start(), q, _UNITA[m.group(2)]))
    if not trovate:
        return None
    _, pos, q, unita = min(trovate)
    return {"quantita": _campo(format(q, "f"), contesto=ld.contesto(norm, pos)), "unita": _campo(unita)}


def _destinatario(testo: str) -> dict | None:
    m = re.search(r"(?im)destinatario[^\n]*\n?\s*(?:denominazione|ragione sociale)?[^\n:]*[:\-]?\s*([^\n]{4,80})", testo)
    if not m:
        return None
    nome = " ".join(m.group(1).split()).strip(" :-")
    if not nome or normalizza(nome) is not None:
        return None
    return _campo(nome[:80])


def _con_regole(lettura: ld.Lettura, tipo: str) -> dict:
    norm = lettura.normalizzato
    campi: dict[str, dict] = {}
    m = _NUMERO_RE.search(norm)
    if m:
        campi["numero_fir"] = _campo(" ".join(m.group(1).split()), contesto=ld.contesto(norm, m.start()))
    d = ld.data_dopo_etichetta(norm, (r"DATA\s+(?:DI\s+)?EMISSIONE", r"DATA\s+INIZIO\s+TRASPORTO", r"DATA\s+E\s+ORA", r"\bDATA\b"))
    if d:
        campi["data"] = _campo(d.isoformat())
    eer = _codice_eer(norm)
    if eer:
        campi["codice"] = eer
    qta = _quantita(norm, tipo)
    if qta:
        campi.update(qta)
    dest = _destinatario(lettura.testo)
    if dest:
        campi["destinatario"] = dest
    return campi


_ISTRUZIONI_AI = (
    "Leggi il testo di un formulario di identificazione rifiuti (FIR) italiano e rispondi SOLO con JSON con le chiavi "
    "richieste: \"codice_eer\" (sei cifre come 15 01 06, con * se pericoloso), \"quantita\" (numero col punto decimale), "
    "\"unita\" (kg, t, l oppure m3), \"numero_fir\", \"data\" (AAAA-MM-GG). Usa null per ciò che non trovi. "
    "Non inventare: copia solo valori presenti nel testo."
)


def _con_ai(testo: str, mancanti: list[str]) -> dict:
    try:
        from ai_assistant.services import chat_with_ollama

        contesto = f"Chiavi richieste: {', '.join(mancanti)}\n\nTesto del formulario:\n{testo[:_MAX_TESTO_AI]}"
        raw = getattr(chat_with_ollama(_ISTRUZIONI_AI, runtime_context=contesto, timeout=60), "content", "") or ""
    except Exception as exc:  # noqa: BLE001
        logger.info("Lettura FIR: AI non disponibile (%s)", exc)
        return {}
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        dati = json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}
    campi: dict[str, dict] = {}
    norm_testo = ld.normalizza(testo)
    codice = str(dati.get("codice_eer") or "").strip()
    n = normalizza(codice)
    if "codice_eer" in mancanti and n and n[0] in re.sub(r"\D", "", norm_testo):
        campi["codice"] = _campo(esteso(*n), "ai")
    try:
        q = Decimal(str(dati.get("quantita"))) if dati.get("quantita") is not None else None
    except InvalidOperation:
        q = None
    unita = str(dati.get("unita") or "").strip().lower()
    if "quantita" in mancanti and q is not None and q > 0 and unita in {"kg", "t", "l", "m3"}:
        campi["quantita"] = _campo(format(q, "f"), "ai")
        campi["unita"] = _campo(unita, "ai")
    numero = " ".join(str(dati.get("numero_fir") or "").split())
    if "numero_fir" in mancanti and numero and ld.normalizza(numero) in norm_testo:
        campi["numero_fir"] = _campo(numero[:40], "ai")
    return campi


def leggi_fir(contenuto: bytes, *, tipo: str = "O", usa_ai: bool = True) -> dict:
    """Campi proposti dal formulario. Solleva ``ld.DocumentoNonLeggibile`` se il file non si apre."""
    lettura = ld.leggi(contenuto)
    campi = _con_regole(lettura, tipo) if lettura.testo.strip() else {}
    mancanti = [k for k, chiave in (("codice_eer", "codice"), ("quantita", "quantita"), ("numero_fir", "numero_fir"))
                if chiave not in campi]
    ai_usata = False
    if usa_ai and lettura.testo.strip() and ("codice_eer" in mancanti or "quantita" in mancanti):
        extra = _con_ai(lettura.testo, mancanti)
        ai_usata = bool(extra)
        for k, v in extra.items():
            campi.setdefault(k, v)
    return {
        "campi": campi,
        "ocr": lettura.ocr,
        "pagine": lettura.pagine,
        "ai": ai_usata,
        "avvisi": lettura.avvisi,
    }
