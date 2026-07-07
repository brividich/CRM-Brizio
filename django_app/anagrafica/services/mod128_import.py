"""MOD.128 MPQ — parser di import del modulo cartaceo.

Funzioni **pure** (nessun DB, nessuna PII cablata) per interpretare le celle del
MOD.128 estratte dal PDF: scadenze eterogenee, certificati individuali inline,
ruoli posizionali SI/NO, celle organizzative (non nominali), multi-cliente e
multi-reparto, regime del processo. Il caricamento a DB e la risoluzione delle
persone vivono nel management command ``import_mod128`` che riusa queste funzioni.

I vocabolari clienti/reparti sono **nomi di aziende/enti e reparti** (non PII
personale) ricavati dal modulo; sono override-abili dal chiamante.
"""
from __future__ import annotations

import re
from datetime import date

from ..models_mpq import ProcessoQualificato

# Vocabolari noti (aziende/enti + reparti). Non contengono PII personale.
CLIENTI_NOTI = [
    "Leonardo Helicopter", "NADCAP", "GE Avio",
    "Piaggio Aerospace", "PiaggioAerospace",
]
REPARTI_NOTI = ["Cleanliness Check", "Aggiustaggio", "CND PT"]

_DATE_RE = re.compile(r"(\d{1,2})[.\/](\d{1,2})[.\/](\d{4})")
_MESI_RE = re.compile(r"(\d+)\s*mes", re.I)
_ANNI_RE = re.compile(r"(\d+)\s*ann", re.I)
_DASH_RE = re.compile(r"[–\-—]")
_ORG_KEYWORDS = [
    "elenco personale", "rif.", "dichiarazione",
    "attestato di riconoscimento", "attestato di qualifica",
]


def parse_data(text: str):
    """Prima data ``dd.mm.yyyy`` (o ``dd/mm/yyyy``) valida nel testo, o None."""
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mth, d)
    except ValueError:
        return None


def parse_scadenza(text: str) -> dict:
    """Interpreta la cella SCADENZE → tipo_validita/data/durata/stato/motivo."""
    t = (text or "").strip()
    low = t.lower()
    base = {
        "tipo_validita": ProcessoQualificato.VALIDITA_DATA,
        "data_scadenza": None, "durata_mesi": None,
        "stato": ProcessoQualificato.STATO_ATTIVO, "motivo": "",
    }
    if not t:
        return base
    if "non più rinnovato" in low or "non piu rinnovato" in low:
        base["stato"] = ProcessoQualificato.STATO_NON_RINNOVATO
        base["motivo"] = t[:255]
        return base
    if "illimitat" in low:
        base["tipo_validita"] = ProcessoQualificato.VALIDITA_ILLIMITATA
        return base
    base["data_scadenza"] = parse_data(t)
    mm = _MESI_RE.search(t)
    if mm:
        base["durata_mesi"] = int(mm.group(1))
    else:
        ay = _ANNI_RE.search(t)
        if ay:
            base["durata_mesi"] = int(ay.group(1)) * 12
    return base


def _normalizza_cliente(nome: str) -> str:
    return "Piaggio Aerospace" if nome == "PiaggioAerospace" else nome


def split_clienti(text: str):
    """Da una cella CLIENTE (anche multi-ente) → (principale, [addizionali])."""
    t = (text or "").strip()
    if not t:
        return ("", [])
    trovati = []
    for c in sorted(CLIENTI_NOTI, key=len, reverse=True):
        idx = t.find(c)
        if idx >= 0:
            trovati.append((idx, _normalizza_cliente(c)))
    trovati.sort()
    nomi = []
    for _, n in trovati:
        if n not in nomi:
            nomi.append(n)
    if not nomi:
        return (t, [])
    return (nomi[0], nomi[1:])


def split_reparti(text: str):
    """Da una cella DISTRIBUZIONE A REPARTO (anche multipla) → lista reparti."""
    t = (text or "").strip()
    if not t:
        return []
    remaining = t
    trovati = []
    for r in sorted(REPARTI_NOTI, key=len, reverse=True):
        if r in remaining:
            trovati.append((t.find(r), r))
            remaining = remaining.replace(r, "", 1)
    trovati.sort()
    result = [r for _, r in trovati]
    leftover = remaining.strip()
    if leftover and not result:
        result = [leftover]
    return result


def infer_regime(cliente: str, processo_text: str) -> str:
    """Regime del processo: Part 145 / NADCAP / cliente-specifico."""
    txt = f"{cliente} {processo_text}".lower()
    if "part 145" in txt or "part145" in txt:
        return ProcessoQualificato.REGIME_PART145
    if "nadcap" in (cliente or "").lower():
        return ProcessoQualificato.REGIME_NADCAP
    return ProcessoQualificato.REGIME_CLIENTE


def is_organizzativo(text: str) -> bool:
    """True se la cella PERSONALE è un rimando (dichiarazione/attestato) non nominale."""
    low = (text or "").strip().lower()
    if not low:
        return False
    return any(k in low for k in _ORG_KEYWORDS)


def _parse_cert_chunk(chunk: str):
    """Un blocco certificato (es. 'ITA – 938/2 – Scad. 31.10.2028') → dict."""
    s = (chunk or "").strip()
    if not s:
        return None
    data = parse_data(s)
    parts = [p.strip() for p in _DASH_RE.split(s) if p.strip()]
    schema = parts[0] if parts else ""
    numero = ""
    for p in parts[1:]:
        if re.search(r"scad", p, re.I):
            num = re.sub(r"scad.*", "", p, flags=re.I).strip()
            if num and not numero:
                numero = num
            continue
        if not numero:
            numero = p
    schema = _DATE_RE.sub("", schema).strip()
    numero = re.sub(r"scad\.?", "", _DATE_RE.sub("", numero), flags=re.I).strip()
    if not schema and not numero and not data:
        return None
    return {"schema": schema[:60], "numero": numero[:120], "livello": "", "data_scadenza": data}


def _split_names(chunk: str):
    """Spezza un frammento di testo in nomi 'Cognome Nome'."""
    s = (chunk or "").strip().strip(".").strip()
    s = re.sub(r"certificat[oi]\s*:.*$", "", s, flags=re.I).strip()
    if not s:
        return []
    if "," in s:
        return [p.strip().strip(".") for p in s.split(",") if p.strip().strip(".")]
    tokens = s.split()
    nomi = []
    for i in range(0, len(tokens) - 1, 2):
        nomi.append(f"{tokens[i]} {tokens[i + 1]}")
    if len(tokens) % 2 == 1:
        if nomi:
            nomi[-1] = f"{nomi[-1]} {tokens[-1]}"
        else:
            nomi.append(tokens[-1])
    return nomi


def split_personale(text: str):
    """Cella PERSONALE nominale → [{'nome': str, 'certs': [dict, ...]}].

    Estrae i certificati inline tra parentesi e li associa alla persona che li
    precede. Ritorna [] per le celle organizzative (non nominali).
    """
    t = (text or "").strip()
    if not t or is_organizzativo(t):
        return []
    persone = []
    idx = 0
    for m in re.finditer(r"\(([^)]*)\)", t):
        for nm in _split_names(t[idx:m.start()]):
            persone.append({"nome": nm, "certs": []})
        cert = _parse_cert_chunk(m.group(1))
        if cert and persone:
            persone[-1]["certs"].append(cert)
        idx = m.end()
    for nm in _split_names(t[idx:]):
        persone.append({"nome": nm, "certs": []})
    return persone


def _flags(s: str):
    return [tok.upper() == "SI" for tok in (s or "").split()]


def allinea_ruoli(persone, addetto="", controllore="", part145=""):
    """Assegna posizionalmente i ruoli SI/NO alle persone (tutte qualificate)."""
    a, c, p = _flags(addetto), _flags(controllore), _flags(part145)
    out = []
    for i, per in enumerate(persone):
        out.append({
            **per,
            "is_qualificato": True,
            "is_addetto": a[i] if i < len(a) else False,
            "is_controllore": c[i] if i < len(c) else False,
            "is_part145": p[i] if i < len(p) else False,
        })
    return out
