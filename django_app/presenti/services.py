"""Stato delle presenze: una sola lettura di Solari al minuto per tutto il server.

``stato()`` legge le timbrature (``solari.leggi_presenti``), aggancia ogni persona
all'anagrafica del portale per **codice fiscale** e aggiunge reparto, mansione e
incarichi di sicurezza (ruoli dell'ambito ISO 45001 dell'organigramma). Il
risultato sta nella cache condivisa per ``DURATA_CACHE`` secondi: la lista live,
il pallino «In azienda» e l'appello leggono tutti la stessa fotografia, quindi il
database Solari riceve al massimo una query al minuto qualunque sia il numero di
utenti collegati.
"""
from __future__ import annotations

import logging
import threading
from datetime import date

from django.core.cache import cache
from django.utils import timezone

from . import solari

logger = logging.getLogger(__name__)

DURATA_CACHE = 60  # secondi
_CHIAVE = "presenti:stato:v2"

# Ambito dell'organigramma da cui vengono gli incarichi di sicurezza.
AMBITO_SICUREZZA = "45001"

# Colore del bollino per incarico (per nome, senza maiuscole). Gli altri ruoli
# dell'ambito usano il colore del ruolo stesso.
_COLORI_INCARICO = {
    "preposto": "#1d4ed8",
    "squadra antincendio": "#c2410c",
    "addetto antincendio": "#c2410c",
    "addetto primo soccorso": "#15803d",
    "primo soccorso": "#15803d",
    "rls": "#7c3aed",
    "aspp": "#0e7490",
    "rspp": "#0e7490",
}


def _incarichi_per_persona(oggi: date) -> dict[int, list[dict]]:
    """{legacy_anagrafica_id: [{nome, colore}]} dei ruoli 45001 in essere oggi."""
    from django.db.models import Q

    from anagrafica.models import DipendenteRuoloOperativo

    righe = (
        DipendenteRuoloOperativo.objects
        .filter(ruolo__ambito__nome__icontains=AMBITO_SICUREZZA, ruolo__is_active=True)
        .filter(Q(data_fine__isnull=True) | Q(data_fine__gte=oggi))
        .filter(Q(data_inizio__isnull=True) | Q(data_inizio__lte=oggi))
        .values_list("legacy_anagrafica_id", "ruolo__nome", "ruolo__colore")
        .order_by("ruolo__nome")
    )
    mappa: dict[int, list[dict]] = {}
    for lid, nome, colore in righe:
        voci = mappa.setdefault(int(lid), [])
        if any(v["nome"] == nome for v in voci):
            continue
        voci.append({
            "nome": nome,
            "colore": _COLORI_INCARICO.get(nome.strip().lower()) or colore or "#475569",
        })
    return mappa


def _anagrafica_per_cf(codici: set[str]) -> dict[str, dict]:
    """{codice fiscale: {legacy_id, reparto, mansione}} delle persone del portale."""
    from anagrafica.models import DipendenteAnagraficaCivile
    from core.legacy_models import AnagraficaDipendente

    if not codici:
        return {}
    per_cf: dict[str, int] = {}
    for cf, lid in DipendenteAnagraficaCivile.objects.exclude(codice_fiscale="").values_list(
        "codice_fiscale", "legacy_anagrafica_id"
    ):
        chiave = (cf or "").strip().upper()
        if chiave in codici:
            per_cf[chiave] = int(lid)
    dati = {
        int(d["id"]): d
        for d in AnagraficaDipendente.objects.filter(id__in=per_cf.values()).values("id", "reparto", "mansione")
    }
    return {
        cf: {"legacy_id": lid, "reparto": (dati.get(lid, {}).get("reparto") or "").strip(),
             "mansione": (dati.get(lid, {}).get("mansione") or "").strip()}
        for cf, lid in per_cf.items()
    }


def collega_anagrafica(persone: list[dict], oggi: date | None = None) -> list[dict]:
    """Aggiunge ``legacy_id``, ``reparto``, ``mansione`` e ``incarichi`` alle righe Solari."""
    oggi = oggi or timezone.localdate()
    agganci = _anagrafica_per_cf({p["codice_fiscale"] for p in persone if p.get("codice_fiscale")})
    incarichi = _incarichi_per_persona(oggi)
    for p in persone:
        a = agganci.get(p.get("codice_fiscale") or "")
        p["legacy_id"] = a["legacy_id"] if a else None
        p["reparto"] = a["reparto"] if a else ""
        p["mansione"] = a["mansione"] if a else ""
        p["incarichi"] = incarichi.get(a["legacy_id"], []) if a else []
    return persone


def leggi_esterni() -> tuple[list[dict], str]:
    """Esterni in azienda adesso (visitatori, ditte, docenti) dal GuestPortal: ``(righe, errore)``.

    Ogni riga ha la stessa forma di quelle Solari, così lista, appello e PDF li trattano
    insieme: ``solari_id`` è l'id della visita col segno meno (non si scontra mai con un
    dipendente), ``esterno=True``, ``cognome`` = nome completo come registrato all'ingresso.
    """
    try:
        from fornitori import guestportal
    except Exception:  # pragma: no cover - app sempre installata
        return [], ""
    if not guestportal.db_configurato():
        return [], ("GuestPortal non collegato: gli esterni (visitatori e ditte) non sono in elenco. "
                    "Vanno contati a parte dal registro della portineria.")
    try:
        accessi = guestportal.presenti_ora()
    except Exception as exc:
        logger.warning("Lettura esterni GuestPortal fallita: %s", type(exc).__name__)
        return [], ("Il GuestPortal non risponde: gli esterni (visitatori e ditte) non sono in elenco. "
                    "Vanno contati a parte dal registro della portineria.")
    # Ditta → scheda fornitore HUB → requisiti di sicurezza (art. 26): avviso in lista, mai bloccante.
    stati = {}
    try:
        from fornitori.requisiti import abbina_fornitori, stati_per_fornitori

        abbina_fornitori(accessi)
        stati = stati_per_fornitori([a.fornitore_id for a in accessi if getattr(a, "fornitore_id", None)])
    except Exception:
        logger.exception("Requisiti fornitori non calcolati per gli esterni")
    righe = []
    for a in accessi:
        if not a.visita_id:
            continue
        req = stati.get(getattr(a, "fornitore_id", None))
        righe.append({
            "solari_id": -int(a.visita_id),
            "esterno": True,
            "legacy_id": None,
            "cognome": a.nome,
            "nome": "",
            "matricola": "",
            "turno": "",
            "reparto": "",
            "mansione": "",
            "incarichi": [],
            "azienda": a.azienda,
            "referente": a.referente,
            "tipo": a.tipo_label,
            "badge": a.badge,
            "entrata": a.ingresso.strftime("%H:%M") if a.ingresso else "",
            "fornitore_id": getattr(a, "fornitore_id", None),
            "requisiti_esito": req.esito if req else "",
            "requisiti_etichetta": req.etichetta if req else "",
            "requisiti_testo": req.riassunto if req else "",
        })
    righe.sort(key=lambda r: (r["azienda"].lower(), r["cognome"].lower()))
    return righe, ""


def _calcola() -> dict:
    adesso = timezone.localtime()
    # Gli esterni si leggono comunque: in un'evacuazione servono anche se Solari è giù.
    esterni, errore_esterni = leggi_esterni()
    base = {"aggiornato_il": adesso, "esterni": esterni, "errore_esterni": errore_esterni}
    try:
        persone = solari.leggi_presenti(adesso.date())
    except solari.SolariNonConfigurato as exc:
        return {**base, "presenti": [], "errore": str(exc), "configurato": False}
    except Exception as exc:  # rete, login, driver: la pagina mostra l'avviso e riprova
        logger.warning("Lettura presenze Solari fallita: %s", exc)
        return {**base, "presenti": [], "configurato": True,
                "errore": "Il database delle timbrature non risponde. Nuovo tentativo al prossimo aggiornamento."}
    for p in persone:
        # In cache vanno solo tipi serializzabili da tutte le cache (anche database).
        p["entrata"] = p["entrata"].strftime("%H:%M") if p.get("entrata") else ""
    collega_anagrafica(persone, adesso.date())
    return {**base, "presenti": persone, "errore": "", "configurato": True}


def stato(*, forza: bool = False) -> dict:
    """Fotografia condivisa delle presenze (al massimo ``DURATA_CACHE`` secondi)."""
    if not forza:
        valore = cache.get(_CHIAVE)
        if valore is not None:
            return valore
    valore = _calcola()
    # Un errore resta in cache meno a lungo: il prossimo utente riprova prima.
    cache.set(_CHIAVE, valore, DURATA_CACHE if not valore["errore"] else 20)
    return valore


_aggiornamento_in_corso = threading.Lock()


def _aggiorna_in_background() -> None:
    """Ricalcola lo stato in un thread: chi chiama non aspetta Solari (fino a 10 s se non risponde)."""
    if not _aggiornamento_in_corso.acquire(blocking=False):
        return

    def _lavoro():
        try:
            stato(forza=True)
        except Exception:
            logger.exception("Aggiornamento presenze in background fallito")
        finally:
            from django.db import connections

            connections.close_all()
            _aggiornamento_in_corso.release()

    threading.Thread(target=_lavoro, name="presenti-aggiorna", daemon=True).start()


def ids_presenti(*, attendi: bool = True) -> set[int] | None:
    """Legacy id delle persone in azienda; ``None`` se lo stato non è disponibile.

    ``attendi=False`` (ricerca Ctrl+K): usa solo la fotografia in cache; se è scaduta la
    ricalcola in background e intanto restituisce ``None`` (nessun pallino, ricerca veloce).
    """
    if attendi:
        s = stato()
    else:
        s = cache.get(_CHIAVE)
        if s is None:
            _aggiorna_in_background()
            return None
    if s["errore"]:
        return None
    return {p["legacy_id"] for p in s["presenti"] if p.get("legacy_id")}


def riepilogo(presenti: list[dict]) -> dict:
    """Contatori per la testata: totale, per incarico, non collegati all'anagrafica."""
    per_incarico: dict[str, dict] = {}
    for p in presenti:
        for inc in p.get("incarichi", []):
            voce = per_incarico.setdefault(inc["nome"], {"nome": inc["nome"], "colore": inc["colore"], "n": 0})
            voce["n"] += 1
    return {
        "totale": len(presenti),
        "incarichi": sorted(per_incarico.values(), key=lambda v: (-v["n"], v["nome"])),
        "non_collegati": sum(1 for p in presenti if not p.get("legacy_id")),
    }


def filtra(presenti: list[dict], *, q: str = "", reparto: str = "", incarico: str = "") -> list[dict]:
    q = (q or "").strip().lower()
    risultato = []
    for p in presenti:
        if reparto and p.get("reparto") != reparto:
            continue
        if incarico and incarico not in {i["nome"] for i in p.get("incarichi", [])}:
            continue
        if q:
            testo = " ".join([p["cognome"], p["nome"], p["matricola"], p.get("reparto", ""),
                              p.get("mansione", ""),
                              p.get("azienda", ""), p.get("referente", "")]).lower()
            if q not in testo:
                continue
        risultato.append(p)
    return risultato


# ── Andamento per reparto (cruscotto) ─────────────────────────────────────────

_CHIAVE_ANDAMENTO = "presenti:andamento:v1"
DURATA_ANDAMENTO = 300  # secondi: il cruscotto non è live come la lista
ORE_CRUSCOTTO = range(5, 23)  # dalle 5 alle 22


def _dentro_alle(seq: list[tuple], istante) -> bool:
    """Dentro a quell'ora: ultima timbratura prima dell'istante in entrata."""
    stato = False
    for quando, verso in seq:
        if quando > istante:
            break
        stato = verso == "E"
    return stato


def andamento(*, forza: bool = False) -> dict:
    """Persone in azienda ora per ora, per reparto, oggi. Solo numeri, nessun nome.

    ``{"aggiornato_il", "errore", "ore": [5..22], "righe": [{reparto, celle: [n|None], adesso}],
    "totale": {celle, adesso}, "massimo"}``; ``None`` nelle ore future.
    """
    if not forza:
        valore = cache.get(_CHIAVE_ANDAMENTO)
        if valore is not None:
            return valore
    from datetime import datetime as _dt

    adesso = timezone.localtime()
    base = {"aggiornato_il": adesso, "ore": list(ORE_CRUSCOTTO), "righe": [], "totale": None,
            "massimo": 0, "errore": ""}
    try:
        persone = solari.leggi_timbrature_giorno(adesso.date())
    except solari.SolariNonConfigurato as exc:
        valore = {**base, "errore": str(exc)}
        cache.set(_CHIAVE_ANDAMENTO, valore, 20)
        return valore
    except Exception as exc:
        logger.warning("Andamento presenze: lettura Solari fallita: %s", exc)
        valore = {**base, "errore": "Il database delle timbrature non risponde. Riprova tra poco."}
        cache.set(_CHIAVE_ANDAMENTO, valore, 20)
        return valore

    agganci = _anagrafica_per_cf({p["codice_fiscale"] for p in persone.values() if p["codice_fiscale"]})
    ora_naive = adesso.replace(tzinfo=None)
    istanti = [_dt.combine(adesso.date(), _dt.min.time()).replace(hour=h) for h in ORE_CRUSCOTTO]
    per_reparto: dict[str, dict] = {}
    for p in persone.values():
        a = agganci.get(p["codice_fiscale"])
        reparto = (a or {}).get("reparto") or ("Reparto non indicato" if a else "Non collegati all'anagrafica")
        voce = per_reparto.setdefault(reparto, {"reparto": reparto, "celle": [0] * len(istanti), "adesso": 0})
        for k, ist in enumerate(istanti):
            if ist <= ora_naive and _dentro_alle(p["seq"], ist):
                voce["celle"][k] += 1
    # «Adesso» = stessa regola e stessa fotografia della lista live (una sola definizione di presente).
    s = stato()
    for p in s["presenti"]:
        reparto = p.get("reparto") or ("Reparto non indicato" if p.get("legacy_id") else "Non collegati all'anagrafica")
        per_reparto.setdefault(reparto, {"reparto": reparto, "celle": [0] * len(istanti), "adesso": 0})["adesso"] += 1
    righe = sorted(per_reparto.values(), key=lambda v: (-v["adesso"], -max(v["celle"] or [0]), v["reparto"]))
    for v in righe:
        v["celle"] = [n if ist <= ora_naive else None for n, ist in zip(v["celle"], istanti)]
    totale = {
        "celle": [None if ist > ora_naive else sum(v["celle"][k] or 0 for v in righe) for k, ist in enumerate(istanti)],
        "adesso": sum(v["adesso"] for v in righe),
    }
    massimo = max([n for v in righe for n in v["celle"] if n] or [0])
    valore = {**base, "righe": righe, "totale": totale, "massimo": massimo}
    cache.set(_CHIAVE_ANDAMENTO, valore, DURATA_ANDAMENTO)
    return valore
