"""Catalogo MOD.073 VRF «Scheda valutazione rischi e fornitura» (rev. 10).

Unica sorgente di verita' per la struttura della scheda e per la mappatura
celle nel template Excel. Usato da:

- view compilazione online: rende la scheda nel template
- generatore xlsx: scrive i valori nelle celle corrette del template
- upload / copia kickoff: legge e scrive l'intestazione del file
- test: verifica coerenza tra dato salvato e foglio generato

Struttura del modulo (template `vrf_template/MOD_073_VRF.xlsx`):

- 9 rischi R1..R9; per ognuno si sceglie la Probabilita' P (1-3, oppure 0 se
  il rischio non si applica). La Gravita' D e' fissata dal modulo per ogni
  rischio (3 o 2). Rischio R = P x D.
- Totale Rischio TR = somma delle R. Basso <= 35; Medio tra 35 e 50;
  Alto >= 50 -> coinvolgimento CEO.
- La checklist a-i di ogni rischio e' la guida per decidere P (pagina 2/2 del
  modulo): non ha un punteggio proprio.
- Azioni correttive / Risk Action Report (4 righe) e firme IN1 / EM con data.

Il modulo precedente (3 fasi P/I/C, 45 sotto-parametri con K) resta leggibile
solo per i dati gia' salvati: vedi `is_legacy()` e `LEGACY_HEADER_CELLS`.
"""
from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 2

TEMPLATE_FILENAME = "MOD_073_VRF.xlsx"
TEMPLATE_SHEET = "Foglio1"

# Celle di intestazione del modulo attuale (campi in grigio nel template).
HEADER_CELLS: dict[str, str] = {
    "vrf_quote_number": "J2",
    "versione":         "R2",
    "part_number":      "C3",
    "vrf_description":  "F3",
    "vrf_esp":          "H3",
    "client_name":      "N3",
}

# Modulo precedente (foglio «VRF», 3 fasi): solo per leggere/copiare file vecchi.
LEGACY_SHEET = "VRF"
LEGACY_HEADER_CELLS: dict[str, str] = {
    "vrf_quote_number": "O2",
    "versione":         "P2",
    "part_number":      "B3",
    "vrf_description":  "I3",
    "vrf_esp":          "P3",
    "client_name":      "B4",
}

P_COL = "Q"
D_COL = "R"
R_COL = "S"
TR_CELL = "S16"
AZIONI_CELLS = ("A26", "A27", "A28", "A29")
FIRMA_CELLS = {"in1": "C30", "em": "F30", "in1_data": "C32", "em_data": "F32"}

# Probabilita': 0 = non applicabile, poi 1-3 come nella matrice del modulo.
P_CHOICES: list[tuple[int, str]] = [
    (0, "N/A"),
    (1, "1 · Bassa"),
    (2, "2 · Media"),
    (3, "3 · Alta"),
]
P_RANGE = (0, 3)

# Soglie del Totale Rischio scritte sul modulo.
TR_BASSO_MAX = 35   # TR <= 35  -> Basso
TR_ALTO_MIN = 50    # TR >= 50  -> Alto, coinvolgimento CEO

RISKS: list[dict[str, Any]] = [
    {
        "code": "R1", "row": 7, "d": 3,
        "title": "Rischio di Mancata comprensione dei Requisiti di Fornitura",
        "checklist": [
            ("a", "Idoneità, Complessità e Comprensione della Documentazione Tecnica (Disegni 2D, DBT, Modelli 3D, Cicli e Fogli Operativi del Cliente)"),
            ("b", "Idoneità e Comprensione Condizioni di Fornitura (incluso/escluso Materie Prime, Normaleria, Attrezzature, Strumenti di Collaudo, Utensili)"),
            ("c", "Idoneità e Comprensione Specifiche e Norme richiamate, Lista Fornitori/Terzisti qualificati dal Cliente"),
            ("d", "Idoneità e Comprensione dei Requisiti Validazione Tecnologica per Prima fornitura (o per passaggio da Proto a Serie)"),
            ("e", "Idoneità e Comprensione dei Requisiti di Collaudo per Forniture Successive (PDC, Quote Critiche, Evidenze Fotografiche…)"),
            ("f", "Idoneità e Comprensione di Informazioni inerenti REACH o Conflict Minerals"),
            ("g", "Disponibilità e Comprensione Piani di Consegna (quantità e numerosità dei lotti, schedulazione date di consegna, deadline…)"),
            ("h", "Disponibilità e Comprensione Eventuale Target Economico"),
            ("i", "Disponibilità e Comprensione norme applicative di eventuali penali (addebito scarto fusioni, sanzioni ritardo consegne…)"),
        ],
    },
    {
        "code": "R2", "row": 8, "d": 3,
        "title": "Rischio Sicurezza dei Lavoratori e Ambiente",
        "checklist": [
            ("a", "Difficoltà Movimentazione causa Dimensioni e Peso del particolare"),
            ("b", "Criticità di lavorazione del materiale e necessità di eventuali accorgimenti (Infiammabilità, Esalazioni…)"),
            ("c", "Utilizzo di Sostanze Chimiche"),
        ],
    },
    {
        "code": "R3", "row": 9, "d": 3,
        "title": "Rischio di Fattibilità dei processi di trasformazione, conservazione e collaudo",
        "checklist": [
            ("a", "Difficoltà di Lavorazione, Collaudo, Movimentazione e/o Stoccaggio legate a Fattori Dimensionali (Ingombro, Peso, Forma…)"),
            ("b", "Lavorabilità Materiale di Partenza (durezza, surriscaldamento, necessità utensili speciali…)"),
            ("c", "Particolare soggetto a deformazioni (presenza di spessori sottili, instabilità del pezzo, deformazioni dovute a trattamenti…)"),
            ("d", "Fattibilità di Lavorazione e Collaudo di eventuali Tolleranze e/o Lavorazioni Critiche (necessità di utensili o strumenti di misura speciali)"),
            ("e", "Conoscenza e Fattibilità Metodo di Mantenimento / Conservazione"),
            ("f", "Possibilità di verificare Commesse analoghe (metodo e tempi di lavoro, lessons learned…)"),
        ],
    },
    {
        "code": "R4", "row": 10, "d": 2,
        "title": "Rischio di Inadeguatezza tecnica e tecnologica dei mezzi di produzione e collaudo",
        "checklist": [
            ("a", "Disponibilità e Manutenzione Impianti di Produzione e Collaudo"),
            ("b", "Disponibilità e Manutenzione Attrezzature di Produzione (divisore, lunetta o altre attrezzature specifiche)"),
            ("c", "Disponibilità e Taratura Apparecchiature di Collaudo (tastatori speciali o altri apparecchi di misura specifici)"),
            ("d", "Disponibilità e Manutenzione idonei strumenti di movimentazione e aree di stoccaggio"),
            ("e", "Disponibilità e Numero di Risorse con Idonea Esperienza (Skill Matrix)"),
        ],
    },
    {
        "code": "R5", "row": 11, "d": 2,
        "title": "Rischio di Errata Pianificazione delle attività interne",
        "checklist": [
            ("a", "Disponibilità Risorse per Industrializzazione nel periodo richiesto (verifica carichi ingegneria e programmatori)"),
            ("b", "Disponibilità Mezzi di Produzione e Collaudo nel periodo richiesto (verifica carichi macchina previsti e disponibilità personale)"),
            ("c", "Criticità di bilanciamento tra Fasi / Reparti / Impianti (Colli di Bottiglia)"),
            ("d", "Disponibilità di Metodologie Produttive alternative (metodi alternativi di costruzione, spostamento fasi su altri reparti o presso terzisti)"),
        ],
    },
    {
        "code": "R6", "row": 12, "d": 2,
        "title": "Rischio connesso all'Approvvigionamento materiali di partenza e/o assemblaggio",
        "checklist": [
            ("a", "Difficile reperibilità e/o criticità dei tempi di approvvigionamento della materia prima (materiale disponibile a stock, numero fornitori alternativi, attendibilità consegne…)"),
            ("b", "Difficile reperibilità e/o criticità dei tempi di approvvigionamento di normaleria (componenti disponibili a stock, numero fornitori alternativi, attendibilità consegne…)"),
            ("c", "Disponibilità strumenti e criteri di accettazione materiali/normaleria"),
            ("d", "Incidenza elevata di eventuali MOQ su valore economico del singolo prodotto"),
            ("e", "Elevata esposizione finanziaria complessiva derivante da acquisto materiali/normaleria"),
        ],
    },
    {
        "code": "R7", "row": 13, "d": 2,
        "title": "Rischio connesso alla Gestione fasi di trasformazione esterne",
        "checklist": [
            ("a", "Difficile reperibilità e/o criticità dei lead time di processo (tempi di attrezzaggio fornitore, numero fornitori alternativi, attendibilità consegne…)"),
            ("b", "Disponibilità strumenti e criteri di accettazione materiali processati"),
            ("c", "Incidenza elevata del processo su valore economico del singolo prodotto (costo processo, attrezzaggio, minimo fatturabile)"),
        ],
    },
    {
        "code": "R8", "row": 14, "d": 3,
        "title": "Rischio connesso alla gestione dei Processi Speciali",
        "checklist": [
            ("a", "Idoneità e Comprensione informazioni su processi speciali richiesti da cliente"),
            ("b", "Disponibilità e Manutenzione Impianti appositamente qualificati"),
            ("c", "Disponibilità e Numero di Risorse con Idonea Qualifica (Skill Matrix)"),
            ("d", "Disponibilità strumenti e criteri di accettazione materiali processati"),
            ("e", "Verifica validità della qualifica fornitore da parte del cliente"),
        ],
    },
    {
        "code": "R9", "row": 15, "d": 3,
        "title": "Rischio Economico - Finanziario",
        "checklist": [
            ("a", "Disponibilità Risorse Finanziarie adeguate all'attività"),
            ("b", "Situazione Crediti verso Cliente"),
            ("c", "Probabilità di variazione significativa del costo di Fornitori/Terzisti"),
            ("d", "Complessità di Gestione Clienti/Fornitori Esteri (Normative, Costi di Dogana)"),
            ("e", "Onerosità di eventuali addebiti del cliente per non conformità o ritardi di consegna"),
        ],
    },
]

TR_MAX = 3 * sum(r["d"] for r in RISKS)


def is_legacy(data: dict[str, Any] | None) -> bool:
    """True se `data` e' una valutazione del modulo precedente (3 fasi)."""
    if not data:
        return False
    if data.get("schema") == SCHEMA_VERSION:
        return False
    risks = data.get("risks") or {}
    return any(isinstance(v, dict) and ("subs" in v or "k" in v) for v in risks.values())


def default_scores() -> dict[str, Any]:
    """Scheda vuota allineata al catalogo (nessuna P scelta)."""
    return {
        "schema": SCHEMA_VERSION,
        "risks": {r["code"]: {"p": None} for r in RISKS},
        "azioni": ["" for _ in AZIONI_CELLS],
        "firme": {"in1": "", "in1_data": "", "em": "", "em_data": ""},
    }


def clamp_p(raw: Any) -> int | None:
    """Converte un valore di P (form o cella Excel) in 0-3, None se vuoto/non valido."""
    if raw is None or raw == "":
        return None
    try:
        v = int(float(raw))
    except (TypeError, ValueError):
        return None
    return max(P_RANGE[0], min(P_RANGE[1], v))


def risk_level(r_value: int | None) -> str:
    """Colore della singola R come nella matrice P x D del modulo."""
    if r_value is None:
        return ""
    if r_value == 0:
        return "na"
    if r_value >= 6:
        return "high"
    if r_value >= 4:
        return "med"
    return "low"


def tr_level(tr: float) -> dict[str, str]:
    """Fascia del Totale Rischio secondo le soglie del modulo."""
    if tr >= TR_ALTO_MIN:
        return {"key": "alto", "label": "Alto", "note": "Coinvolgimento CEO"}
    if tr > TR_BASSO_MAX:
        return {"key": "medio", "label": "Medio", "note": ""}
    return {"key": "basso", "label": "Basso", "note": ""}


def compute_totals(data: dict[str, Any] | None) -> dict[str, Any]:
    """R = P x D per rischio, TR, fascia, completezza.

    Restituisce: {per_risk: {R1: {p, d, r, level}}, tr, level, ceo_required,
    compiled, missing: [codici senza P]}
    """
    risks_data = {} if is_legacy(data) else ((data or {}).get("risks") or {})
    per_risk: dict[str, dict[str, Any]] = {}
    tr = 0
    missing: list[str] = []
    for risk in RISKS:
        p = clamp_p((risks_data.get(risk["code"]) or {}).get("p"))
        r = None if p is None else p * risk["d"]
        if r is None:
            missing.append(risk["code"])
        else:
            tr += r
        per_risk[risk["code"]] = {"p": p, "d": risk["d"], "r": r, "level": risk_level(r)}
    level = tr_level(tr)
    return {
        "per_risk": per_risk,
        "tr": tr,
        "level": level,
        "ceo_required": level["key"] == "alto",
        "compiled": not missing,
        "missing": missing,
    }
