"""Dati strutturati che il controllore aggiunge a un'anomalia (facoltativi).

Accanto alla descrizione libera, che resta sempre, il controllore sceglie che cosa
ha trovato e compila solo i campi di quel caso:

* ``misura``: una o piu' misure fuori tolleranza (caratteristica, nominale,
  tolleranza, rilevato, dove);
* ``difetto``: un difetto sul pezzo (bava, testimone di fusione, graffio...) con
  zona e dimensioni;
* ``documenti``: marcatura o documenti che non coincidono (atteso / trovato).

In tutti i casi c'e' il riferimento (disegno, sezione, fase del ciclo). I dati stanno
nella scheda qualita' (``AnomaliaSchedaQualita.dettaglio_controllo``); da qui escono
le frasi uniformi («Ø 131.345/131.360 rilevato 131.330 (−0.015)») e il tipo di
difetto proposto. Unica fonte per pagina del controllore, gestione e report.
"""
from __future__ import annotations

import re

TIPI = ("misura", "difetto", "documenti")
MAX_MISURE = 20

# Caratteristiche delle misure: codice -> (simbolo, etichetta, famiglia per il tipo difetto).
CARATTERISTICHE = {
    "diametro": ("Ø", "Diametro", "fuori-tolleranza"),
    "quota": ("", "Quota", "fuori-tolleranza"),
    "lunghezza": ("", "Lunghezza", "fuori-tolleranza"),
    "spessore": ("", "Spessore", "fuori-tolleranza"),
    "raggio": ("R", "Raggio", "fuori-tolleranza"),
    "angolo": ("∠", "Angolo", "fuori-tolleranza"),
    "smusso": ("", "Smusso", "fuori-tolleranza"),
    "profondita": ("", "Profondità", "fuori-tolleranza"),
    "concentricita": ("◎", "Concentricità", "geometria"),
    "posizione": ("⌖", "Posizione", "geometria"),
    "simmetria": ("⌯", "Simmetria", "geometria"),
    "planarita": ("⏥", "Planarità", "geometria"),
    "perpendicolarita": ("⊥", "Perpendicolarità", "geometria"),
    "parallelismo": ("∥", "Parallelismo", "geometria"),
    "circolarita": ("○", "Circolarità", "geometria"),
    "oscillazione": ("↗", "Oscillazione", "geometria"),
    "profilo": ("⌒", "Profilo", "geometria"),
    "filettatura": ("", "Filettatura", "filettatura"),
    "rugosita": ("Ra", "Rugosità", "rugosita"),
    "altro": ("", "Altra misura", "fuori-tolleranza"),
}
MODI_TOLLERANZA = ("minmax", "pm", "max")

# Generi di difetto sul pezzo -> (etichetta, codice del tipo difetto).
GENERI_DIFETTO = {
    "bava": ("Bava / spigolo vivo", "bave-spigoli"),
    "fusione": ("Testimone di fusione / porosità", "difetto-superficiale"),
    "graffio": ("Graffio / ammaccatura / impronta", "difetto-superficiale"),
    "lavorazione": ("Lavorazione mancante o errata", "lavorazione-mancante"),
    "trattamento": ("Difetto di trattamento / finitura", "trattamento"),
    "movimentazione": ("Danno da movimentazione", "movimentazione"),
    "altro": ("Altro difetto", "altro"),
}
DOCUMENTI = ("OP", "DDT", "Cartellino", "Disegno", "Certificato")


def _txt(value, max_len: int = 120) -> str:
    return " ".join(str(value or "").split())[:max_len]


def _numero(value) -> float | None:
    testo = str(value or "").strip().replace(",", ".").replace("−", "-").replace("±", "")
    if not testo:
        return None
    try:
        return float(testo)
    except ValueError:
        return None


def _fmt(valore: float) -> str:
    testo = f"{valore:.4f}".rstrip("0").rstrip(".")
    return "0" if testo in ("-0", "") else testo


def normalizza(raw) -> dict:
    """Dizionario pulito (solo i campi noti); ``{}`` se non c'e' nulla di utile."""
    if not isinstance(raw, dict):
        return {}
    tipo = raw.get("tipo") if raw.get("tipo") in TIPI else ""
    out: dict = {}
    if tipo:
        out["tipo"] = tipo
    if tipo == "misura":
        misure = []
        for m in (raw.get("misure") or [])[:MAX_MISURE]:
            if not isinstance(m, dict):
                continue
            riga = {
                "car": m.get("car") if m.get("car") in CARATTERISTICHE else "altro",
                "nome": _txt(m.get("nome"), 60),
                "modo": m.get("modo") if m.get("modo") in MODI_TOLLERANZA else "minmax",
                "nom": _txt(m.get("nom"), 20),
                "a": _txt(m.get("a"), 20),
                "b": _txt(m.get("b"), 20),
                "ril": _txt(m.get("ril"), 20),
                "dove": _txt(m.get("dove"), 120),
            }
            if any(riga[k] for k in ("nom", "a", "b", "ril", "dove", "nome")):
                misure.append(riga)
        if misure:
            out["misure"] = misure
    elif tipo == "difetto":
        d = raw.get("difetto") if isinstance(raw.get("difetto"), dict) else {}
        difetto = {
            "genere": d.get("genere") if d.get("genere") in GENERI_DIFETTO else "",
            "dove": _txt(d.get("dove"), 160),
            "lung": _txt(d.get("lung"), 20),
            "larg": _txt(d.get("larg"), 20),
            "prof": _txt(d.get("prof"), 20),
            "est": _txt(d.get("est"), 20),
        }
        if any(difetto.values()):
            out["difetto"] = difetto
    elif tipo == "documenti":
        d = raw.get("documenti") if isinstance(raw.get("documenti"), dict) else {}
        documenti = {
            "atteso": _txt(d.get("atteso"), 120),
            "trovato": _txt(d.get("trovato"), 120),
            "docs": [x for x in DOCUMENTI if x in (d.get("docs") or [])],
        }
        if any(documenti.values()):
            out["documenti"] = documenti
    r = raw.get("rif") if isinstance(raw.get("rif"), dict) else {}
    rif = {k: _txt(r.get(k), 80) for k in ("disegno", "sezione", "fase")}
    if any(rif.values()):
        out["rif"] = rif
    return out


def esito_misura(m: dict) -> dict:
    """``{"fuori": bool|None, "scarto": float|None}``: di quanto il rilevato esce dai limiti."""
    ril = _numero(m.get("ril"))
    nom = _numero(m.get("nom"))
    a, b = _numero(m.get("a")), _numero(m.get("b"))
    modo = m.get("modo") or "minmax"
    lo = hi = None
    if modo == "minmax":
        lo, hi = a, b
        if lo is not None and hi is not None and lo > hi:
            lo, hi = hi, lo
    elif modo == "pm" and nom is not None and a is not None:
        lo, hi = nom - abs(a), nom + abs(b if b is not None else a)
    elif modo == "max":
        hi = a
    if ril is None or (lo is None and hi is None):
        return {"fuori": None, "scarto": None}
    if hi is not None and ril > hi:
        return {"fuori": True, "scarto": round(ril - hi, 4)}
    if lo is not None and ril < lo:
        return {"fuori": True, "scarto": round(ril - lo, 4)}
    return {"fuori": False, "scarto": 0.0}


def frase_misura(m: dict) -> str:
    simbolo, etichetta, _fam = CARATTERISTICHE.get(m.get("car") or "altro", CARATTERISTICHE["altro"])
    nome = m.get("nome") or etichetta
    # Ø e R bastano da soli («Ø 12.000/12.018»); gli altri simboli accompagnano il nome.
    testa = simbolo if simbolo in ("Ø", "R") and not m.get("nome") else f"{simbolo} {nome}".strip()
    modo = m.get("modo") or "minmax"
    if modo == "minmax":
        tol = f"{m.get('a') or '?'}/{m.get('b') or '?'}"
    elif modo == "pm":
        tol = f"{m.get('nom') or '?'} ±{m.get('a') or '?'}" if not m.get("b") or m.get("b") == m.get("a") \
            else f"{m.get('nom') or '?'} −{m.get('a')}/+{m.get('b')}"
    else:
        tol = f"max {m.get('a') or '?'}"
    parti = [f"{testa} {tol}".strip()]
    if m.get("ril"):
        parti.append(f"rilevato {m['ril']}")
    esito = esito_misura(m)
    if esito["fuori"]:
        parti.append(f"({'+' if esito['scarto'] > 0 else '−'}{_fmt(abs(esito['scarto']))})")
    frase = " ".join(parti)
    if m.get("dove"):
        frase += f" · {m['dove']}"
    return frase


def frasi(dettaglio: dict) -> list[str]:
    """Frasi leggibili dei dati strutturati, nell'ordine in cui il controllore li ha scritti."""
    if not isinstance(dettaglio, dict) or not dettaglio:
        return []
    out: list[str] = []
    tipo = dettaglio.get("tipo")
    if tipo == "misura":
        out += [frase_misura(m) for m in dettaglio.get("misure") or []]
    elif tipo == "difetto" and dettaglio.get("difetto"):
        d = dettaglio["difetto"]
        testa = GENERI_DIFETTO.get(d.get("genere"), ("Difetto", ""))[0]
        dim = [f"{lab} {d[k]}" for k, lab in (("lung", "lunghezza"), ("larg", "larghezza/altezza"),
                                              ("prof", "profondità"), ("est", "estensione")) if d.get(k)]
        out.append(testa + (f" · {d['dove']}" if d.get("dove") else "") + (f" · {', '.join(dim)}" if dim else ""))
    elif tipo == "documenti" and dettaglio.get("documenti"):
        d = dettaglio["documenti"]
        parti = []
        if d.get("trovato"):
            parti.append(f"sul pezzo {d['trovato']}")
        if d.get("atteso"):
            parti.append(f"atteso {d['atteso']}")
        if d.get("docs"):
            parti.append(f"documenti: {', '.join(d['docs'])}")
        out.append("Marcatura/documenti non coincidenti" + (f" · {' · '.join(parti)}" if parti else ""))
    rif = dettaglio.get("rif") or {}
    pezzi = [v for v in (rif.get("disegno"), f"sez. {rif['sezione']}" if rif.get("sezione") else "",
                         rif.get("fase")) if v]
    if pezzi:
        out.append("Rif.: " + " · ".join(pezzi))
    return out


_PAROLE = (
    (re.compile(r"\bbav[ae]\b|spigol", re.I), "bave-spigoli"),
    (re.compile(r"marcat|ddt|cartellino", re.I), "marcatura-documenti"),
    (re.compile(r"concentricit|simmetri|posizione|planarit|perpendicolar|parallelis|circolarit|oscillazion", re.I), "geometria"),
    (re.compile(r"filett", re.I), "filettatura"),
    (re.compile(r"rugosit|\bRa\b", re.I), "rugosita"),
    (re.compile(r"testimone|porosit|fusione|graff|ammacc|impront", re.I), "difetto-superficiale"),
    (re.compile(r"Ø|diametr|quota|lunghezz|smusso|\bOT\b|fuori toll|rilevat|risulta", re.I), "fuori-tolleranza"),
)


def tipo_difetto_suggerito(dettaglio: dict, testo: str = "") -> str:
    """Codice del tipo difetto proposto: dai dati strutturati, altrimenti dalle parole del testo."""
    tipo = (dettaglio or {}).get("tipo")
    if tipo == "misura":
        famiglie = [CARATTERISTICHE.get(m.get("car"), CARATTERISTICHE["altro"])[2] for m in dettaglio.get("misure") or []]
        return famiglie[0] if famiglie else "fuori-tolleranza"
    if tipo == "difetto":
        genere = ((dettaglio.get("difetto") or {}).get("genere")) or ""
        return GENERI_DIFETTO.get(genere, ("", "difetto-superficiale"))[1] or "difetto-superficiale"
    if tipo == "documenti":
        return "marcatura-documenti"
    for regex, codice in _PAROLE:
        if regex.search(testo or ""):
            return codice
    return ""


def catalogo_per_pagina() -> dict:
    """Scelte per la pagina del controllore (caratteristiche, generi, documenti, tipi difetto)."""
    from .quality_models import AnomaliaTipoDifetto

    try:
        tipi = [{"id": t.pk, "codice": t.codice, "nome": t.nome}
                for t in AnomaliaTipoDifetto.objects.filter(attivo=True).order_by("ordine", "nome")]
    except Exception:
        tipi = []
    return {
        "caratteristiche": [{"codice": k, "simbolo": v[0], "nome": v[1], "famiglia": v[2]}
                            for k, v in CARATTERISTICHE.items()],
        "generi": [{"codice": k, "nome": v[0], "famiglia": v[1]} for k, v in GENERI_DIFETTO.items()],
        "documenti": list(DOCUMENTI),
        "tipi_difetto": tipi,
    }


def salva_su_scheda(local_id: int, dettaglio_raw, tipo_difetto_id, testo: str, *, dove_pezzi=None) -> None:
    """Scrive dettaglio e tipo difetto nella scheda qualita' dell'anomalia (mai bloccante).

    Tipo difetto: quello scelto dal controllore se valido; altrimenti, se la scheda non
    ne ha ancora uno, quello proposto. Una scelta gia' fatta a mano in Qualita' resta.
    """
    import logging

    from .quality_models import AnomaliaSchedaQualita, AnomaliaTipoDifetto

    try:
        scheda = AnomaliaSchedaQualita.objects.filter(anomalia_id=local_id).first()
        if scheda is None:
            return
        dettaglio = normalizza(dettaglio_raw)
        campi = []
        if dove_pezzi is not None and _txt(dove_pezzi, 200) != (scheda.dove_pezzi or ""):
            scheda.dove_pezzi = _txt(dove_pezzi, 200)
            campi.append("dove_pezzi")
        if dettaglio != (scheda.dettaglio_controllo or {}):
            scheda.dettaglio_controllo = dettaglio
            campi.append("dettaglio_controllo")
        scelto = None
        if str(tipo_difetto_id or "").isdigit():
            scelto = AnomaliaTipoDifetto.objects.filter(pk=int(tipo_difetto_id), attivo=True).first()
        if scelto is None and scheda.tipo_difetto_id is None:
            codice = tipo_difetto_suggerito(dettaglio, testo)
            scelto = AnomaliaTipoDifetto.objects.filter(codice=codice, attivo=True).first() if codice else None
        if scelto is not None and scelto.pk != scheda.tipo_difetto_id:
            scheda.tipo_difetto = scelto
            campi.append("tipo_difetto")
        if campi:
            scheda.save(update_fields=[*campi, "updated_at"])
    except Exception:
        logging.getLogger(__name__).warning("dettaglio controllo non salvato id=%s", local_id, exc_info=True)
