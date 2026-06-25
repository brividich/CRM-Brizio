"""Grammatica di parsing delle celle a testo libero del foglio Carichi_macchina.

Funzioni pure (nessuna dipendenza da Django) -> facilmente testabili in isolamento.
Esempi di celle reali: "8 gimbal 6F (33h)", "2 koala fin", "5 musetti 109 sgr",
"ass (op3+4)", "6 Bas Inf Yamaha (op2)".

Grammatica (validata, copertura attesa su ~8.800 voci: famiglia ~76%, ore ~14%,
op ~4%, stato ~22%):
- qta      = intero iniziale seguito da parola;
- ore      = (\\d+)\\s*h\\b;
- op       = op\\s?(\\d) e op\\d\\s*\\+\\s*(\\d);
- fase     = sgr->sgrossatura, fin->finitura, rip->ripresa, ass->assemblaggio;
- ferma    = guast|manuten|ferm -> stato macchina (NON un lavoro);
- famiglia = vocabolario a due passate (vedi build_vocabolario/scegli_famiglia).
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

# Marker di processo e stopword da escludere dal vocabolario famiglia.
_MARKER = {"op", "sgr", "fin", "rip", "ass", "guast", "manuten", "ferm"}
_STOPWORD_PROCESSO = {
    "serie", "setter", "prova", "fresatura", "riordino", "assieme", "lotto",
    "finte", "smontaggio", "coni", "notturno", "week", "weekend", "turno",
    "pezzi", "pezzo", "cad", "ore", "rip", "ass", "sgr", "fin",
}

# Pezzi (NON ore): priorita' a "4pz", poi "N°5"/"N.5", poi il numero iniziale
# SOLO se non e' subito un marcatore di operazione (es. "2°op" = 2a operazione).
_RE_PEZZI_PZ = re.compile(r"(\d+)\s*pz\b", re.IGNORECASE)
_RE_PEZZI_N = re.compile(r"\bn[°.]\s*(\d+)", re.IGNORECASE)
_RE_PEZZI_LEAD = re.compile(r"^\s*(\d+)(?!\s*°?\s*op\b)", re.IGNORECASE)
_RE_ORE = re.compile(r"(\d+)\s*h\b", re.IGNORECASE)
_RE_OP = re.compile(r"op\s?(\d)", re.IGNORECASE)
_RE_OP_PLUS = re.compile(r"op\d\s*\+\s*(\d)", re.IGNORECASE)
_RE_OP_PRE = re.compile(r"(\d)\s*°?\s*op\b", re.IGNORECASE)  # "4°OP", "2°op"
_RE_FASE = re.compile(r"\b(sgr|fin|rip|ass)\b", re.IGNORECASE)
_RE_FERMA = re.compile(r"(guast|manuten|ferm)", re.IGNORECASE)
_RE_TOKEN = re.compile(r"[a-zàèéìòùA-ZÀÈÉÌÒÙ]+")

_FASE_MAP = {"sgr": "sgr", "fin": "fin", "rip": "rip", "ass": "ass"}


@dataclass
class CellParse:
    testo: str
    qta: int | None = None
    ore: int | None = None
    operazioni: list[int] = field(default_factory=list)
    fase: str = ""          # "" | sgr | fin | rip | ass
    macchina_ferma: bool = False
    tokens: list[str] = field(default_factory=list)  # token alfabetici len>=4, lowercase
    famiglia: str | None = None  # assegnata dal secondo passaggio


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _alpha_tokens(testo: str) -> list[str]:
    """Token alfabetici (len>=4), lowercase, esclusi marker/stopword."""
    out: list[str] = []
    for raw in _RE_TOKEN.findall(testo):
        tok = _strip_accents(raw).lower()
        if len(tok) < 4:
            continue
        if tok in _MARKER or tok in _STOPWORD_PROCESSO:
            continue
        out.append(tok)
    return out


def parse_cell(testo: str) -> CellParse:
    """Estrae i campi strutturati da una cella (famiglia assegnata dopo, col vocabolario)."""
    testo = (testo or "").strip()
    res = CellParse(testo=testo)
    if not testo:
        return res

    if _RE_FERMA.search(testo):
        res.macchina_ferma = True
        # una macchina ferma non e' un lavoro: non estraiamo qta/famiglia
        return res

    # qta = PEZZI (non ore): 4pz -> N°5 -> numero iniziale (se non e' un'operazione)
    for rx, leading in ((_RE_PEZZI_PZ, False), (_RE_PEZZI_N, False), (_RE_PEZZI_LEAD, True)):
        m = rx.match(testo) if leading else rx.search(testo)
        if m:
            res.qta = int(m.group(1))
            break

    m = _RE_ORE.search(testo)
    if m:
        res.ore = int(m.group(1))

    ops: set[int] = set()
    for mm in _RE_OP.finditer(testo):       # "op2"
        ops.add(int(mm.group(1)))
    for mm in _RE_OP_PLUS.finditer(testo):  # "op3+4"
        ops.add(int(mm.group(1)))
    for mm in _RE_OP_PRE.finditer(testo):   # "4°OP", "2°op"
        ops.add(int(mm.group(1)))
    res.operazioni = sorted(ops)

    mf = _RE_FASE.search(testo)
    if mf:
        res.fase = _FASE_MAP[mf.group(1).lower()]

    res.tokens = _alpha_tokens(testo)
    return res


def build_vocabolario(celle: list[str], min_freq: int = 4) -> tuple[set[str], Counter]:
    """Primo passaggio: frequenza dei token alfabetici su tutte le celle.

    Ritorna (set 'noto' = token con freq>=min_freq, Counter completo).
    """
    freq: Counter = Counter()
    for testo in celle:
        if _RE_FERMA.search(testo or ""):
            continue
        freq.update(_alpha_tokens(testo or ""))
    noti = {tok for tok, n in freq.items() if n >= min_freq}
    return noti, freq


# --- CICLI (routing in coda al foglio) ------------------------------------
# Es: "CICLI APRILIA:" / "* BAS SUP" / "op4 DM10 (MK3) = 750 cent/cad"
RE_CICLI_HDR = re.compile(r"^\s*cicli\b\s*(.*?):?\s*$", re.IGNORECASE)
_RE_CICLI_PEZZO = re.compile(r"^\s*\*\s*(.+?)\s*$")
_RE_CICLI_OP = re.compile(r"^\s*op\s*(\d+)\s+(.+?)\s*=\s*(\d+)\s*cent", re.IGNORECASE)
_RE_CICLI_OP_MAC = re.compile(r"^\s*([A-Za-z0-9]+)\s*(?:\((.*)\))?")


def parse_cicli(lines: list[str]) -> list[dict]:
    """Parsa le righe della sezione CICLI -> lista di cicli.

    Ogni ciclo: {cliente, pezzo, operazioni: [{seq, macchina, regola, tempo}], note: [...]}.
    'op4 DM10 (MK3) = 750 cent/cad' -> seq=4, macchina=DM10, regola='MK3', tempo=750.
    """
    cicli: list[dict] = []
    cliente = ""
    cur: dict | None = None
    for raw in lines:
        t = (raw or "").strip()
        if not t:
            continue
        m = RE_CICLI_HDR.match(t)
        if m:
            cliente = m.group(1).strip().rstrip(":").strip()
            continue
        m = _RE_CICLI_PEZZO.match(t)
        if m:
            cur = {"cliente": cliente, "pezzo": m.group(1).strip(), "operazioni": [], "note": []}
            cicli.append(cur)
            continue
        m = _RE_CICLI_OP.match(t)
        if m and cur is not None:
            body = m.group(2).strip()
            mac_m = _RE_CICLI_OP_MAC.match(body)
            cur["operazioni"].append({
                "seq": int(m.group(1)),
                "macchina": (mac_m.group(1) if mac_m else "").strip(),
                "regola": ((mac_m.group(2) or "").strip() if mac_m else ""),
                "tempo": int(m.group(3)),
            })
            continue
        if cur is not None and "=" in t:  # step ausiliario (MG/PP/lapidello/GILARDONI...)
            cur["note"].append(t)
    return cicli


def scegli_famiglia(parse: CellParse, noti: set[str], freq: Counter) -> str | None:
    """Secondo passaggio: token noto a frequenza massima; fallback al primo token."""
    if parse.macchina_ferma or not parse.tokens:
        return None
    candidati = [t for t in parse.tokens if t in noti]
    if candidati:
        # max frequenza, a parita' il primo che compare nella cella
        return max(candidati, key=lambda t: (freq[t], -parse.tokens.index(t)))
    return parse.tokens[0]
