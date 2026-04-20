"""Catalogo rischi MOD.073 VRF Rev.10.

Unica sorgente di verita' per la struttura della matrice rischi (9 rischi, 45
sub-parametri) e per la mappatura celle nel template Excel. Usato da:

- view compilazione online: rende la matrice nel template
- generatore xlsx: scrive i punteggi nelle celle corrette del template
- test: verifica coerenza tra dato salvato e foglio generato

Non modificare senza verificare che 'MOD.073 - VRF Rev.10 NEW.xlsx' (template
distribuito) abbia la stessa struttura.
"""
from __future__ import annotations

from typing import Any

TEMPLATE_FILENAME = "MOD_073_VRF_Rev10.xlsx"
TEMPLATE_SHEET = "VRF"

HEADER_CELLS: dict[str, str] = {
    "vrf_quote_number": "O2",
    "versione":         "P2",
    "part_number":      "B3",
    "vrf_description":  "I3",
    "vrf_esp":          "P3",
    "client_name":      "B4",
}

PHASES: list[dict[str, str]] = [
    {"key": "p", "label": "Preventivazione",     "input_col": "U",  "k_col": "Y",  "kr_col": "Z"},
    {"key": "i", "label": "Industrializzazione", "input_col": "AB", "k_col": "AF", "kr_col": "AG"},
    {"key": "c", "label": "Produzione",          "input_col": "AI", "k_col": "AM", "kr_col": "AN"},
]

TR_CELLS: dict[str, str] = {"p": "Z61", "i": "AG61", "c": "AN61"}

DIG_THRESHOLD = 46
K_RANGE = (1, 5)
R_RANGE = (0, 3)

RISKS: list[dict[str, Any]] = [
    {
        "code": "R1", "row": 7,
        "title": "Rischio di Mancata comprensione dei Requisiti di Fornitura",
        "k_default": {"p": 3, "i": 3, "c": 3},
        "sub_parameters": [
            {"code": "a", "row": 8,  "label": "Idoneita', Complessita' e Comprensione della Documentazione Tecnica (Disegni 2D, DBT, Modelli 3D, Cicli e Fogli Operativi)"},
            {"code": "b", "row": 9,  "label": "Idoneita' e Comprensione Condizioni di Fornitura (Materie Prime, Normaleria, Attrezzature, Strumenti di Collaudo, Utensili)"},
            {"code": "c", "row": 10, "label": "Idoneita' e Comprensione Specifiche e Norme richiamate, Lista Fornitori/Terzisti qualificati dal Cliente"},
            {"code": "d", "row": 11, "label": "Idoneita' e Comprensione dei Requisiti Validazione Tecnologica per Prima fornitura"},
            {"code": "e", "row": 12, "label": "Idoneita' e Comprensione dei Requisiti di Collaudo per Forniture Successive (PDC, Quote Critiche, Evidenze Fotografiche)"},
            {"code": "f", "row": 13, "label": "Idoneita' e Comprensione di Informazioni inerenti REACH o Conflict Minerals"},
            {"code": "g", "row": 14, "label": "Disponibilita' e Comprensione Piani di Consegna (quantita', lotti, schedulazione, deadlines)"},
            {"code": "h", "row": 15, "label": "Disponibilita' e Comprensione Eventuale Target Economico"},
            {"code": "i", "row": 16, "label": "Disponibilita' e Comprensione norme applicative di eventuali penali (scarto fusioni, ritardo consegne)"},
        ],
    },
    {
        "code": "R2", "row": 17,
        "title": "Rischio Sicurezza dei Lavoratori e Ambiente",
        "k_default": {"p": 3, "i": 3, "c": 5},
        "sub_parameters": [
            {"code": "a", "row": 18, "label": "Difficolta' Movimentazione causa Dimensioni e Peso del particolare"},
            {"code": "b", "row": 19, "label": "Criticita' di lavorazione del materiale (Infiammabilita', Esalazioni)"},
            {"code": "c", "row": 20, "label": "Utilizzo di Sostanze Chimiche"},
        ],
    },
    {
        "code": "R3", "row": 21,
        "title": "Rischio di Fattibilita' dei processi di trasformazione, conservazione e collaudo",
        "k_default": {"p": 3, "i": 3, "c": 3},
        "sub_parameters": [
            {"code": "a", "row": 22, "label": "Difficolta' di Lavorazione, Collaudo, Movimentazione/Stoccaggio (Ingombro, Peso, Forma)"},
            {"code": "b", "row": 23, "label": "Lavorabilita' Materiale di Partenza (durezza, surriscaldamento, utensili speciali)"},
            {"code": "c", "row": 24, "label": "Particolare soggetto a deformazioni (spessori sottili, trattamenti, instabilita')"},
            {"code": "d", "row": 25, "label": "Fattibilita' Lavorazione/Collaudo di Tolleranze e Lavorazioni Critiche (utensili/strumenti speciali)"},
            {"code": "e", "row": 26, "label": "Conoscenza e Fattibilita' Metodo di Mantenimento / Conservazione"},
            {"code": "f", "row": 27, "label": "Possibilita' di verificare Commesse analoghe (lessons learned, metodo e tempi)"},
        ],
    },
    {
        "code": "R4", "row": 28,
        "title": "Rischio di Inadeguatezza tecnica e tecnologica dei mezzi di produzione e collaudo",
        "k_default": {"p": 2, "i": 2, "c": 3},
        "sub_parameters": [
            {"code": "a", "row": 29, "label": "Disponibilita' e Manutenzione Impianti di Produzione e Collaudo"},
            {"code": "b", "row": 30, "label": "Disponibilita' e Manutenzione Attrezzature di Produzione (divisore, lunetta, specifiche)"},
            {"code": "c", "row": 31, "label": "Disponibilita' e Taratura Apparecchiature di Collaudo (tastatori, misura specifica)"},
            {"code": "d", "row": 32, "label": "Disponibilita' e Manutenzione idonei strumenti di movimentazione e aree di stoccaggio"},
            {"code": "e", "row": 33, "label": "Disponibilita' e Numero di Risorse con Idonea Esperienza (Skill Matrix)"},
        ],
    },
    {
        "code": "R5", "row": 34,
        "title": "Rischio di Errata Pianificazione delle attivita' interne",
        "k_default": {"p": 2, "i": 2, "c": 3},
        "sub_parameters": [
            {"code": "a", "row": 35, "label": "Disponibilita' Risorse per Industrializzazione (carichi ingegneria e programmatori)"},
            {"code": "b", "row": 36, "label": "Disponibilita' Mezzi di Produzione e Collaudo (carichi macchina, disponibilita' personale)"},
            {"code": "c", "row": 37, "label": "Criticita' di bilanciamento tra Fasi/Reparti/Impianti (Colli di Bottiglia)"},
            {"code": "d", "row": 38, "label": "Disponibilita' di Metodologie Produttive alternative (spostamento fasi, terzisti)"},
        ],
    },
    {
        "code": "R6", "row": 39,
        "title": "Rischio connesso all'Approvvigionamento materiali di partenza e/o assemblaggio",
        "k_default": {"p": 2, "i": 2, "c": 3},
        "sub_parameters": [
            {"code": "a", "row": 40, "label": "Difficile reperibilita' e/o criticita' tempi di approvvigionamento materia prima"},
            {"code": "b", "row": 41, "label": "Difficile reperibilita' e/o criticita' tempi di approvvigionamento normaleria"},
            {"code": "c", "row": 42, "label": "Disponibilita' strumenti e criteri di accettazione materiali/normaleria"},
            {"code": "d", "row": 43, "label": "Incidenza elevata di eventuali MOQ su valore economico del singolo prodotto"},
            {"code": "e", "row": 44, "label": "Elevata esposizione finanziaria complessiva da acquisto materiali/normaleria"},
        ],
    },
    {
        "code": "R7", "row": 45,
        "title": "Rischio connesso alla Gestione fasi di trasformazione esterne",
        "k_default": {"p": 2, "i": 2, "c": 3},
        "sub_parameters": [
            {"code": "a", "row": 46, "label": "Difficile reperibilita' e/o criticita' lead time di processo (attrezzaggio, fornitori alternativi)"},
            {"code": "b", "row": 47, "label": "Disponibilita' strumenti e criteri di accettazione materiali processati"},
            {"code": "c", "row": 48, "label": "Incidenza elevata del processo su valore economico del singolo prodotto (attrezzaggio, minimo fatturabile)"},
        ],
    },
    {
        "code": "R8", "row": 49,
        "title": "Rischio connesso alla gestione dei Processi Speciali",
        "k_default": {"p": 3, "i": 3, "c": 3},
        "sub_parameters": [
            {"code": "a", "row": 50, "label": "Idoneita' e Comprensione informazioni su processi speciali richiesti da cliente"},
            {"code": "b", "row": 51, "label": "Disponibilita' e Manutenzione Impianti appositamente qualificati"},
            {"code": "c", "row": 52, "label": "Disponibilita' e Numero di Risorse con Idonea Qualifica (Skill Matrix)"},
            {"code": "d", "row": 53, "label": "Disponibilita' strumenti e criteri di accettazione materiali processati"},
            {"code": "e", "row": 54, "label": "Verifica validita' della qualifica fornitore da parte del cliente"},
        ],
    },
    {
        "code": "R9", "row": 55,
        "title": "Rischio Economico - Finanziario",
        "k_default": {"p": 3, "i": 3, "c": 3},
        "sub_parameters": [
            {"code": "a", "row": 56, "label": "Disponibilita' Risorse Finanziarie adeguate all'attivita'"},
            {"code": "b", "row": 57, "label": "Situazione Crediti verso Cliente"},
            {"code": "c", "row": 58, "label": "Probabilita' di variazione significativa del costo di Fornitori/Terzisti"},
            {"code": "d", "row": 59, "label": "Complessita' di Gestione Clienti/Fornitori Esteri (Dogana, Normative)"},
            {"code": "e", "row": 60, "label": "Onerosita' di eventuali addebiti del cliente per non conformita' o ritardi"},
        ],
    },
]


def iter_sub_parameters():
    """Yield (risk, sub) per ogni sub-parametro del catalogo."""
    for risk in RISKS:
        for sub in risk["sub_parameters"]:
            yield risk, sub


def default_scores() -> dict[str, Any]:
    """Struttura vuota allineata al catalogo (tutti i punteggi None).

    Shape: {risks: {R1: {k: {p:3,i:3,c:3}, subs: {a: {p:None,i:None,c:None}, ...}}}}
    """
    out: dict[str, Any] = {"risks": {}}
    for risk in RISKS:
        out["risks"][risk["code"]] = {
            "k": dict(risk["k_default"]),
            "subs": {
                sub["code"]: {ph["key"]: None for ph in PHASES}
                for sub in risk["sub_parameters"]
            },
        }
    return out


def compute_totals(data: dict[str, Any]) -> dict[str, Any]:
    """Calcola medie per rischio, K*Rmedio, e TR per fase partendo da 'risks' dict.

    Restituisce: {per_risk: {R1: {p: {avg, kr}, ...}}, totals: {p, i, c}, max_total}
    """
    per_risk: dict[str, dict[str, dict[str, float | None]]] = {}
    totals = {ph["key"]: 0.0 for ph in PHASES}
    risks_data = (data or {}).get("risks") or {}
    for risk in RISKS:
        r_code = risk["code"]
        r_info = risks_data.get(r_code) or {}
        k_vals = r_info.get("k") or risk["k_default"]
        subs = r_info.get("subs") or {}
        per_risk[r_code] = {}
        for ph in PHASES:
            ph_key = ph["key"]
            scores = []
            for sub in risk["sub_parameters"]:
                v = (subs.get(sub["code"]) or {}).get(ph_key)
                if v is None or v == "":
                    continue
                try:
                    scores.append(float(v))
                except (TypeError, ValueError):
                    continue
            avg = (sum(scores) / len(scores)) if scores else None
            try:
                k = float(k_vals.get(ph_key, risk["k_default"][ph_key]))
            except (TypeError, ValueError):
                k = float(risk["k_default"][ph_key])
            kr = (avg * k) if avg is not None else None
            per_risk[r_code][ph_key] = {"avg": avg, "k": k, "kr": kr}
            if kr is not None:
                totals[ph_key] += kr
    return {
        "per_risk": per_risk,
        "totals": totals,
        "max_total": max(totals.values()) if totals else 0.0,
        "dig_triggered": any(v >= DIG_THRESHOLD for v in totals.values()),
    }
