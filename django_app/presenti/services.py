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
from datetime import date

from django.core.cache import cache
from django.utils import timezone

from . import solari

logger = logging.getLogger(__name__)

DURATA_CACHE = 60  # secondi
_CHIAVE = "presenti:stato:v1"

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


def _calcola() -> dict:
    adesso = timezone.localtime()
    try:
        persone = solari.leggi_presenti(adesso.date())
    except solari.SolariNonConfigurato as exc:
        return {"aggiornato_il": adesso, "presenti": [], "errore": str(exc), "configurato": False}
    except Exception as exc:  # rete, login, driver: la pagina mostra l'avviso e riprova
        logger.warning("Lettura presenze Solari fallita: %s", exc)
        return {"aggiornato_il": adesso, "presenti": [], "configurato": True,
                "errore": "Il database delle timbrature non risponde. Nuovo tentativo al prossimo aggiornamento."}
    for p in persone:
        # In cache vanno solo tipi serializzabili da tutte le cache (anche database).
        p["entrata"] = p["entrata"].strftime("%H:%M") if p.get("entrata") else ""
    collega_anagrafica(persone, adesso.date())
    return {"aggiornato_il": adesso, "presenti": persone, "errore": "", "configurato": True}


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


def ids_presenti() -> set[int] | None:
    """Legacy id delle persone in azienda; ``None`` se lo stato non è disponibile."""
    s = stato()
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
                              p.get("mansione", "")]).lower()
            if q not in testo:
                continue
        risultato.append(p)
    return risultato
