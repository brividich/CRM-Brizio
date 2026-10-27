"""Import dell'analisi del rischio dal PDF del MOD.165 (RAR Risk Assessment And Register).

Si leggono quattro fogli dell'export dell'Excel aziendale:

* «Threat Risk»: per ogni minaccia gruppo, agente, rischio inerente, vulnerabilità massima e rischio residuo;
* «Threats vs Controls»: la matrice minaccia × controllo ISO/IEC 27002 (una «x» dove il controllo mitiga);
* «Threat Monitoring»: per controllo il livello di vulnerabilità futuro atteso dopo le azioni;
* «OT Treatment Plan»: scenari di rischio OT con misure, rischio inerente/atteso e piano d'azione.

Come per la Control Matrix, le parole si leggono con le coordinate (PyMuPDF), riportate nel verso di
lettura, e si assegnano alle colonne in base alle intestazioni. Il contenuto resta nel database: il PDF
viene letto al momento dell'import e mai copiato nel repository.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .mod165_import import Mod165FormatoNonRiconosciuto

_CODICE_CTRL_RE = re.compile(r"^\d\.\d{1,2}$")
_OT_RE = re.compile(r"^OT-\d{2,3}$")
_DATA_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


@dataclass
class MinacciaImportata:
    gruppo: str
    agente: str
    minaccia: str
    rischio_inerente: int | None
    vulnerabilita: int | None = None
    residuo: int | None = None
    controlli: list[str] = field(default_factory=list)


@dataclass
class ScenarioOTImportato:
    codice: str
    scenario: str = ""
    minacce: str = ""
    controlli: str = ""
    misure: str = ""
    rischio_inerente: int | None = None
    vulnerabilita_attesa: int | None = None
    rischio_atteso: int | None = None
    azioni: str = ""
    opzione: str = ""
    responsabile: str = ""
    scadenza: str = ""
    stato: str = ""
    riferimenti: str = ""


@dataclass
class AnalisiRischioImportata:
    minacce: list[MinacciaImportata]
    vulnerabilita_attese: dict[str, int]
    scenari_ot: list[ScenarioOTImportato]
    soglia: int | None


def _pulisci(testo: str) -> str:
    return re.sub(r"\s+", " ", testo or "").strip()


def _numero(testo: str) -> int | None:
    trovati = re.findall(r"(?<![\d.,/])(\d{1,3})(?![\d.,/])", testo or "")
    return int(trovati[0]) if trovati else None


def _parole(pagina):
    import fitz

    matrice = pagina.rotation_matrix
    out = []
    for p in pagina.get_text("words"):
        r = fitz.Rect(p[:4]) * matrice
        out.append((r.x0, r.y0, r.x1, r.y1, p[4]))
    return out


def _testo_pagina(ws) -> str:
    return " ".join(w[4] for w in ws)


def _righe(ws, *, y_min: float, tolleranza: float = 2.5):
    """Raggruppa le parole in righe visive (stessa linea di base)."""
    righe: list[list] = []
    for w in sorted((w for w in ws if w[1] > y_min), key=lambda w: (w[1], w[0])):
        if righe and abs(righe[-1][0][1] - w[1]) <= tolleranza:
            righe[-1].append(w)
        else:
            righe.append([w])
    return righe


def _colonna(parole, x0: float, x1: float) -> str:
    return _pulisci(" ".join(w[4] for w in sorted(parole, key=lambda w: (round(w[1]), w[0])) if x0 <= (w[0] + w[2]) / 2 < x1))


def _x(ws, etichetta: str, *, dopo_y: float = -1) -> tuple[float, float, float]:
    for w in ws:
        if w[4] == etichetta and w[1] > dopo_y:
            return w[0], w[1], w[2]
    raise Mod165FormatoNonRiconosciuto(f"Intestazione «{etichetta}» non trovata.")


def _intestazione(ws, etichetta: str, y_rif: float, *, tolleranza: float = 8) -> tuple[float, float, float, float]:
    cand = sorted((w for w in ws if w[4] == etichetta and abs(w[1] - y_rif) <= tolleranza), key=lambda w: w[0])
    if not cand:
        raise Mod165FormatoNonRiconosciuto(f"Intestazione «{etichetta}» non trovata.")
    return cand[0][:4]


def _inizio_colonna(ws, x_da: float, x_a: float, y_min: float) -> float:
    """Bordo sinistro di una colonna allineata a sinistra: l'ascissa di partenza più frequente."""
    from collections import Counter

    conteggio = Counter(round(w[0]) for w in ws if x_da < w[0] < x_a and w[1] > y_min)
    if not conteggio:
        raise Mod165FormatoNonRiconosciuto("Colonna della minaccia non trovata.")
    return conteggio.most_common(1)[0][0]


def _bande(ancore: list[float], y_fine_testata: float) -> list[tuple[float, float, float]]:
    """Per ogni riga (ancora y) la banda verticale: dai punti medi con le righe vicine."""
    out = []
    for i, y in enumerate(ancore):
        su = (ancore[i - 1] + y) / 2 if i else y_fine_testata
        giu = (y + ancore[i + 1]) / 2 if i + 1 < len(ancore) else y + 30
        out.append((y, su, giu))
    return out


def _in_banda(ws, su: float, giu: float):
    return [w for w in ws if su <= (w[1] + w[3]) / 2 < giu]


def _leggi_threat_risk(ws) -> tuple[list[MinacciaImportata], int | None]:
    gruppo = _x(ws, "Group")
    y_head = gruppo[1]
    x_agente = _intestazione(ws, "agent", y_head)[0] - 25
    x_inerente = _intestazione(ws, "Inherent", y_head)[0]
    x_vuln = _intestazione(ws, "MAX", y_head)[0]
    x_residuo = _intestazione(ws, "Residual", y_head)[0]
    x_acc = _intestazione(ws, "Acceptability", y_head)[0]
    y_fine_testata = max(w[3] for w in ws if abs(w[1] - y_head) <= 8)
    x_minaccia = _inizio_colonna(ws, x_agente + 30, x_inerente - 10, y_fine_testata) - 3
    soglia = None
    livello = next((w for w in ws if w[4] == "Level" and w[1] < y_head), None)
    if livello:
        numeri = sorted(int(v[4]) for v in ws if v[4].isdigit() and livello[1] < v[1] < livello[1] + 14
                        and abs(v[0] - livello[0]) < 40)
        soglia = numeri[-1] if numeri else None
    ancore = sorted(w[1] for w in ws if w[4] in {"SI", "NO", "SÌ", "Si", "No"} and x_acc - 5 <= w[0] < x_acc + 80
                    and w[1] > y_fine_testata)
    minacce = []
    for _y, su, giu in _bande(ancore, y_fine_testata):
        banda = _in_banda(ws, su, giu)
        minacce.append(MinacciaImportata(
            gruppo=_colonna(banda, 0, x_agente),
            agente=_colonna(banda, x_agente, x_minaccia),
            minaccia=_colonna(banda, x_minaccia, x_inerente - 10),
            rischio_inerente=_numero(_colonna(banda, x_inerente - 10, x_vuln - 5)),
            vulnerabilita=_numero(_colonna(banda, x_vuln - 5, x_residuo - 5)),
            residuo=_numero(_colonna(banda, x_residuo - 5, x_acc - 5)),
        ))
    return minacce, soglia


def _leggi_matrice(ws) -> list[tuple[str, list[str]]]:
    """Righe della matrice «Threats vs Controls»: (testo della minaccia, codici dei controlli marcati)."""
    colonne = sorted(
        ((w[0] + w[2]) / 2, w[4]) for w in ws
        if _CODICE_CTRL_RE.match(w[4]) and any(v[4] == "27002:2022" and abs(v[0] - w[0]) < 3 for v in ws)
    )
    if not colonne:
        raise Mod165FormatoNonRiconosciuto("Colonne dei controlli della matrice minacce × controlli non trovate.")
    x_primo = colonne[0][0] - 6
    passo = (colonne[-1][0] - colonne[0][0]) / max(len(colonne) - 1, 1)
    gruppo = _x(ws, "Group")
    y_head = gruppo[1]
    x_agente = _intestazione(ws, "agent", y_head)[0] - 15
    x_inerente = _intestazione(ws, "Inherent", y_head)[0]
    x_applicabili = _intestazione(ws, "Applicable", y_head)[0]
    y_fine_testata = max(w[3] for w in ws if abs(w[1] - y_head) <= 8)
    x_minaccia = _inizio_colonna(ws, x_agente + 30, x_inerente - 5, y_fine_testata) - 3
    # Ogni riga ha il numero dei controlli applicabili: è l'ancora della riga.
    ancore = sorted(w[1] for w in ws if x_applicabili - 5 <= w[0] < x_primo - 2 and w[1] > y_fine_testata
                    and (w[4].isdigit() or w[4] == "-"))
    out = []
    for _y, su, giu in _bande(ancore, y_fine_testata):
        banda = _in_banda(ws, su, giu)
        codici = []
        for w in banda:
            if w[4] not in {"x", "X"} or w[0] < x_primo:
                continue
            centro = (w[0] + w[2]) / 2
            vicino = min(colonne, key=lambda c: abs(c[0] - centro))
            if abs(vicino[0] - centro) <= passo / 2 + 1:
                codici.append(vicino[1])
        out.append((_colonna(banda, x_minaccia, x_inerente - 5), sorted(set(codici), key=lambda c: [int(n) for n in c.split(".")])))
    return out


def _leggi_monitoraggio(ws) -> dict[str, int]:
    """Vulnerabilità futura attesa per controllo (colonna «Expected Future Vulnerability Level»).

    Il codice del controllo sta in fondo alla cella (come nella Control Matrix): la riga va dalla
    riga precedente fino al codice."""
    intest = [w for w in ws if w[4] == "Vulnerability"]
    if not intest or not any(w[4] == "Future" for w in ws):
        return {}
    colonna = max(intest, key=lambda w: w[0])
    x0, x1 = colonna[0] - 8, colonna[2] + 22
    y_head = max(w[3] for w in ws if abs(w[1] - colonna[1]) < 14)
    ancore = sorted((w[1], w[4]) for w in ws if _CODICE_CTRL_RE.match(w[4]) and w[0] < 120 and w[1] > y_head)
    out = {}
    precedente = y_head
    for y, codice in ancore:
        banda = [w for w in ws if precedente < (w[1] + w[3]) / 2 <= y + 6]
        precedente = y + 6
        valore = _numero(_colonna(banda, x0, x1))
        if valore is not None and valore <= 4:
            out[codice] = valore
    return out


def _leggi_ot(ws) -> list[ScenarioOTImportato]:
    try:
        _x0, y_head, _x1 = _x(ws, "Scenario")
    except Mod165FormatoNonRiconosciuto:
        return []
    prima_riga = min((w[1] for w in ws if _OT_RE.match(w[4]) and w[1] > y_head), default=None)
    if prima_riga is None:
        return []
    dati = [w for w in ws if w[1] > prima_riga - 6]
    testata = [w for w in ws if abs(w[1] - y_head) < 25 and w not in dati]

    def xh(etichetta: str, *, dopo: float = -1) -> float:
        cand = [w for w in testata if w[4] == etichetta and w[0] > dopo]
        if not cand:
            raise Mod165FormatoNonRiconosciuto(f"Intestazione OT «{etichetta}» non trovata.")
        return min(cand, key=lambda w: w[0])[0]

    ultimo = [0.0]

    def bordo(x_testata: float) -> float:
        """Bordo sinistro della colonna di testo: l'inizio di riga più frequente poco prima dell'intestazione,
        dopo il bordo della colonna precedente (le colonne si leggono da sinistra a destra)."""
        from collections import Counter

        da = max(x_testata - 90, ultimo[0] + 15)
        conteggio = Counter(round(w[0]) for w in dati if da <= w[0] <= x_testata + 5)
        frequenti = [x for x, n in conteggio.most_common() if n >= 3]
        ultimo[0] = (frequenti[0] if frequenti else x_testata) - 2
        return ultimo[0]

    x_scen = bordo(xh("OT"))
    x_rel = bordo(xh("Related"))
    x_ctrl = xh("Annex") - 25
    x_mis = bordo(xh("Existing"))
    x_iner = xh("Inherent") - 15
    ultimo[0] = x_iner
    x_vul = xh("Vulnerability") - 5
    x_att = xh("Residual", dopo=x_vul + 30) - 8
    x_acc = xh("Acceptability") - 5
    ultimo[0] = x_acc + 30
    x_az = bordo(xh("Actions"))
    x_opz = bordo(xh("Treatment"))
    x_resp = bordo(xh("Accountable"))
    x_scad = bordo(xh("Due"))
    x_stato = bordo(xh("Status"))
    x_rif = bordo(xh("References"))
    ancore = sorted((w[1], w[4]) for w in ws if _OT_RE.match(w[4]) and w[0] < x_scen)
    out = []
    for i, (y, codice) in enumerate(ancore):
        y_fine = ancore[i + 1][0] if i + 1 < len(ancore) else 10_000
        banda = [w for w in dati if y - 5 <= w[1] < y_fine - 5 and w[4] != codice]
        codici = [w for w in banda if _CODICE_CTRL_RE.match(w[4]) and x_ctrl <= w[0] < x_mis + 2]
        out.append(ScenarioOTImportato(
            codice=codice,
            scenario=_colonna(banda, x_scen, x_rel),
            minacce=_colonna(banda, x_rel, x_ctrl),
            controlli=" ".join(w[4] for w in sorted(codici, key=lambda w: w[1])),
            misure=_colonna([w for w in banda if w not in codici], x_mis, x_iner),
            rischio_inerente=_numero(_colonna(banda, x_iner, x_vul)),
            vulnerabilita_attesa=_numero(_colonna(banda, x_vul, x_att)),
            rischio_atteso=_numero(_colonna(banda, x_att, x_acc)),
            azioni=_colonna(banda, x_az, x_opz),
            opzione=_colonna(banda, x_opz, x_resp),
            responsabile=_colonna(banda, x_resp, x_scad),
            scadenza=_colonna(banda, x_scad, x_stato),
            stato=_colonna(banda, x_stato, x_rif),
            riferimenti=_colonna(banda, x_rif, 10_000),
        ))
    for scenario in out:
        match = re.search(r"\d{2}/\d{2}/\d{4}", scenario.scadenza)
        if match:
            resto = _pulisci(scenario.scadenza.replace(match.group(0), ""))
            scenario.scadenza = match.group(0)
            scenario.stato = _pulisci(f"{resto} {scenario.stato}")
    return out


def leggi_analisi_rischio(sorgente) -> AnalisiRischioImportata:
    """``sorgente``: percorso del PDF o bytes."""
    import fitz

    doc = fitz.open(stream=sorgente, filetype="pdf") if isinstance(sorgente, (bytes, bytearray)) else fitz.open(sorgente)
    minacce: list[MinacciaImportata] = []
    matrice: list[tuple[str, list[str]]] = []
    attese: dict[str, int] = {}
    scenari: list[ScenarioOTImportato] = []
    soglia = None
    try:
        for pagina in doc:
            ws = _parole(pagina)
            testo = _testo_pagina(ws)
            if "Threats vs Controls" in testo:
                matrice = _leggi_matrice(ws)
            elif "Threat Risk" in testo and "Residual" in testo and "Monitoring" not in testo:
                minacce, soglia = _leggi_threat_risk(ws)
            elif "Threat Monitoring" in testo:
                attese = _leggi_monitoraggio(ws)
            elif "OT Treatment Plan" in testo:
                scenari = _leggi_ot(ws)
    finally:
        doc.close()
    if not minacce:
        raise Mod165FormatoNonRiconosciuto("Foglio «Threat Risk» non trovato nel PDF.")
    # Abbinamento per testo della minaccia; se il numero di righe coincide vale anche l'ordine.
    chiave = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())  # noqa: E731
    per_testo = {}
    for testo, codici in matrice:
        per_testo.setdefault(chiave(testo), codici)
    stesso_ordine = len(matrice) == len(minacce)
    for i, m in enumerate(minacce):
        trovati = per_testo.get(chiave(m.minaccia))
        if trovati is None and stesso_ordine:
            trovati = matrice[i][1]
        m.controlli = list(trovati or [])
    return AnalisiRischioImportata(minacce=minacce, vulnerabilita_attese=attese, scenari_ot=scenari, soglia=soglia)
