"""«Chi ha in carico l'anomalia»: tabella configurabile «quando succede → passa a».

Configurazione anomalie → Qualità → «Chi ha in carico l'anomalia». Una riga per
evento (fase, avanzamento, avanzamento qualità, flag); per ognuna si sceglie il
ruolo o una persona precisa. Vale la prima riga che corrisponde, dall'alto; una
riga lasciata «di serie» usa la regola di sempre (vedi ``REGOLA_DI_SERIE``).

Restano fissi: anomalia chiusa = nessuno; richiesta di informazioni aperta = chi
deve rispondere; CAR segnalati = sempre anche loro. L'incaricato affidato a mano
(``incaricati.py``) sostituisce chi ha il ruolo.

Salvato in ``SiteConfig["anomalie_regole_carico"]``::

    {"regole": {"<evento>": "ruolo:qualita" | "persona:42"}, "nomi": {"42": "ROSSI MARIO"}}

Una persona come destinazione entra nei ruoli come ``"p:<utenti.id>"``.
"""
from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)
# Letta per ogni anomalia dell'elenco: copia in memoria per pochi secondi.
_CACHE: dict = {"t": 0.0, "v": None}
_TTL = 10.0

KEY = "anomalie_regole_carico"
RUOLI_DESTINAZIONE = [("cc", "Capocommessa dell'OP"), ("qualita", "Qualità (referenti RDC)"),
                      ("controllore", "Controllore (chi l'ha inserita)"), ("car_op", "CAR dell'OP"),
                      ("segnalatore", "Chi ha fatto la segnalazione")]
REGOLA_DI_SERIE = {
    "fase:da_decidere": "ruolo:cc",
    "fase:info_richieste": "ruolo:cc",
    "fase:attesa_cliente": "ruolo:segnalatore",
    "fase:attesa_terzista": "ruolo:segnalatore",
    "altre": "ruolo:qualita",
}


def _norm(v) -> str:
    return " ".join(str(v or "").split()).lower()


def eventi() -> list[dict]:
    """Righe della tabella, nell'ordine in cui si valutano."""
    from .decisione_qualita import avanzamenti_qualita
    from .views import _load_anomalie_lists

    out = [
        {"chiave": "fase:da_decidere", "gruppo": "Fase", "etichetta": "Da decidere (nessuna decisione del capocommessa)"},
        {"chiave": "fase:info_richieste", "gruppo": "Fase", "etichetta": "Rimandata con «In attesa di ulteriori informazioni»"},
        {"chiave": "fase:attesa_cliente", "gruppo": "Fase", "etichetta": "In attesa della risposta del cliente"},
        {"chiave": "fase:attesa_terzista", "gruppo": "Fase", "etichetta": "In attesa della risposta del terzista"},
    ]
    for v in avanzamenti_qualita():
        out.append({"chiave": f"qualita:{v}", "gruppo": "Avanzamento qualità", "etichetta": v})
    out += [
        {"chiave": "flag:rdc", "gruppo": "Decisione", "etichetta": "«Aprire RDC» senza numero RDC"},
        {"chiave": "flag:cliente", "gruppo": "Decisione", "etichetta": "«Segnalare al cliente»"},
        {"chiave": "flag:terzista", "gruppo": "Decisione", "etichetta": "«Segnala a terzista»"},
    ]
    try:
        avanzamenti = _load_anomalie_lists().get("avanzamenti") or []
    except Exception:
        avanzamenti = []
    for v in avanzamenti:
        v = str(v or "").strip()
        if v and _norm(v) not in {"in attesa", ""}:
            out.append({"chiave": f"avanzamento:{v}", "gruppo": "Avanzamento", "etichetta": v})
    out.append({"chiave": "altre", "gruppo": "Altrimenti", "etichetta": "Tutte le altre anomalie aperte (già decise)"})
    return out


def carica() -> dict:
    if _CACHE["v"] is not None and time.monotonic() - _CACHE["t"] < _TTL:
        return _CACHE["v"]
    _CACHE["v"] = _leggi()
    _CACHE["t"] = time.monotonic()
    return _CACHE["v"]


def _leggi() -> dict:
    try:
        from core.models import SiteConfig

        raw = SiteConfig.get(KEY, "") or ""
        dati = json.loads(raw) if raw else {}
    except Exception:
        dati = {}
    regole = dati.get("regole") if isinstance(dati.get("regole"), dict) else {}
    nomi = dati.get("nomi") if isinstance(dati.get("nomi"), dict) else {}
    return {"regole": {str(k): str(v) for k, v in regole.items() if _valida(str(v))},
            "nomi": {str(k): str(v) for k, v in nomi.items()}}


def _valida(dest: str) -> bool:
    if dest.startswith("ruolo:"):
        return dest[6:] in {r for r, _l in RUOLI_DESTINAZIONE}
    if dest.startswith("persona:"):
        return dest[8:].isdigit()
    return False


def salva(regole: dict, nomi: dict) -> None:
    from core.models import SiteConfig

    pulite = {k: v for k, v in regole.items() if v and _valida(v)}
    usati = {v[8:] for v in pulite.values() if v.startswith("persona:")}
    SiteConfig.set(KEY, json.dumps({"regole": pulite, "nomi": {k: v for k, v in nomi.items() if k in usati}},
                                   ensure_ascii=False),
                   "Anomalie: chi ha in carico l'anomalia secondo la fase e le decisioni.")
    _CACHE["v"] = None


def _corrisponde(chiave: str, row: dict, info: dict) -> bool:
    from .controllo_service import riga_gestita
    from .segnalato_service import AVANZAMENTO_RISPOSTA_CLIENTE, AVANZAMENTO_RISPOSTA_TERZISTA
    from .views import AVANZAMENTO_INFO_RICHIESTE

    av = _norm(row.get("avanzamento"))
    if chiave == "fase:da_decidere":
        return not riga_gestita(row)
    if chiave == "fase:info_richieste":
        return av == _norm(AVANZAMENTO_INFO_RICHIESTE)
    if chiave == "fase:attesa_cliente":
        return av == _norm(AVANZAMENTO_RISPOSTA_CLIENTE)
    if chiave == "fase:attesa_terzista":
        return av == _norm(AVANZAMENTO_RISPOSTA_TERZISTA)
    if chiave.startswith("qualita:"):
        return bool(info.get("avanzamento_qualita")) and _norm(info.get("avanzamento_qualita")) == _norm(chiave[8:])
    if chiave == "flag:rdc":
        return bool(row.get("aprire_rdc")) and not str(row.get("numero_rdc") or "").strip()
    if chiave == "flag:cliente":
        return bool(row.get("segnalare_cliente"))
    if chiave == "flag:terzista":
        return bool(info.get("segnala_terzista"))
    if chiave.startswith("avanzamento:"):
        return av == _norm(chiave[12:])
    return chiave == "altre"


def destinazione(row: dict, info: dict, regole: dict | None = None) -> set[str]:
    """Ruoli (o ``p:<id>``) che hanno in carico un'anomalia aperta, senza richieste aperte.

    Fasi «di serie» non configurate: capocommessa per da decidere / ulteriori
    informazioni, chi ha segnalato per l'attesa della risposta, qualità per il resto.
    """
    regole = carica()["regole"] if regole is None else regole
    for ev in _chiavi_ordinate(row, info, regole):
        dest = regole.get(ev) or REGOLA_DI_SERIE.get(ev)
        if not dest:
            continue
        return {_ruolo_da(dest, ev, info)}
    return {"qualita"}


def _chiavi_ordinate(row, info, regole):
    """Chiavi che corrispondono, nell'ordine della tabella (senza rileggere le liste
    di Configurazione se non servono: fasi e flag sono fissi)."""
    fisse_prima = ["fase:da_decidere", "fase:info_richieste", "fase:attesa_cliente", "fase:attesa_terzista"]
    for k in fisse_prima:
        if _corrisponde(k, row, info):
            yield k
    q = str(info.get("avanzamento_qualita") or "").strip()
    if q:
        yield f"qualita:{_cerca(regole, 'qualita:', q) or q}"
    for k in ("flag:rdc", "flag:cliente", "flag:terzista"):
        if _corrisponde(k, row, info):
            yield k
    av = str(row.get("avanzamento") or "").strip()
    if av:
        yield f"avanzamento:{_cerca(regole, 'avanzamento:', av) or av}"
    yield "altre"


def _cerca(regole: dict, prefisso: str, valore: str) -> str:
    """Valore come scritto nella regola (maiuscole/spazi possono differire)."""
    for k in regole:
        if k.startswith(prefisso) and _norm(k[len(prefisso):]) == _norm(valore):
            return k[len(prefisso):]
    return ""


def _ruolo_da(dest: str, evento: str, info: dict) -> str:
    if dest.startswith("persona:"):
        return f"p:{dest[8:]}"
    ruolo = dest[6:]
    if ruolo == "segnalatore":
        if evento == "fase:attesa_terzista":
            return info.get("segnalato_terzista_ruolo") or "cc"
        return info.get("segnalato_cliente_ruolo") or info.get("segnalato_terzista_ruolo") or "cc"
    return ruolo


def persone_destinazione(regole: dict | None = None) -> set[int]:
    regole = carica()["regole"] if regole is None else regole
    return {int(v[8:]) for v in regole.values() if v.startswith("persona:")}


def nomi_persone() -> dict[str, str]:
    return carica()["nomi"]
