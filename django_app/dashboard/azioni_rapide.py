"""Azioni rapide della home: catalogo, liste predefinite e scelte personali.

Una voce ha una chiave stabile:

- ``a:<code>`` azione del catalogo ``_AZIONI_RAPIDE`` (es. «Segnala anomalia»);
- ``m:<id>`` tessera del catalogo moduli ``_MODULE_CATALOG`` (apre il modulo).

Da dove arriva la lista di una persona, in ordine di precedenza:

1. la sua lista personale (``UserUiPreference.home_prefs["azioni"]``), scelta da
   lei in «⚙ Personalizza» o impostata da un amministratore;
2. la lista predefinita del suo ruolo legacy (``SiteConfig`` ``home_azioni_ruolo_<id>``);
3. la lista predefinita per tutti (``SiteConfig`` ``home_azioni_predefinite``);
4. lo standard del portale: le prime ``HOME_AZIONI_MAX`` azioni del catalogo.

Il server filtra SEMPRE per permessi al momento di mostrare la home: una voce
che la persona non può aprire non compare, qualunque lista la contenga.
"""
from __future__ import annotations

import json
import logging

from core.models import SiteConfig

logger = logging.getLogger(__name__)

CHIAVE_PREDEFINITE = "home_azioni_predefinite"
CHIAVE_RUOLO = "home_azioni_ruolo_{}"
AZIONI_MAX = 12

FONTE_UTENTE = "utente"
FONTE_ADMIN = "admin"

FONTI_LABEL = {
    "utente": "Scelte da te",
    "admin": "Impostate dall'amministratore",
    "ruolo": "Predefinite del tuo ruolo",
    "predefinite": "Predefinite del portale",
    "standard": "Standard del portale",
}


def catalogo() -> list[dict]:
    """Tutte le voci proponibili, senza filtro permessi (per la pagina admin)."""
    from dashboard.views_home_portale import _AZIONI_RAPIDE, _MODULE_CATALOG

    out = [
        {"key": f"a:{spec['code']}", "label": spec["label"], "gruppo": "Azioni"}
        for spec in _AZIONI_RAPIDE
    ]
    visti: set[str] = set()
    for spec in _MODULE_CATALOG:
        if spec.get("url_name") in (None, "", "#") or spec["id"] in visti:
            continue
        visti.add(spec["id"])
        out.append({"key": f"m:{spec['id']}", "label": spec["label"], "gruppo": "Moduli"})
    return out


def chiavi_valide() -> set[str]:
    return {v["key"] for v in catalogo()}


def pulisci(raw, valide: set[str] | None = None) -> list[str]:
    """Lista di chiavi note, senza doppioni, al massimo ``AZIONI_MAX``."""
    valide = chiavi_valide() if valide is None else valide
    out: list[str] = []
    for x in raw or []:
        k = str(x).strip()[:60] if isinstance(x, (str, int)) else ""
        if k in valide and k not in out:
            out.append(k)
    return out[:AZIONI_MAX]


def _leggi(chiave: str) -> list[str] | None:
    raw = SiteConfig.get(chiave, "")
    if not raw:
        return None
    try:
        dati = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return pulisci(dati) if isinstance(dati, list) else None


def _scrivi(chiave: str, keys: list[str] | None, descrizione: str) -> None:
    if keys is None:
        SiteConfig.objects.filter(chiave=chiave).delete()
        return
    SiteConfig.set(chiave, json.dumps(pulisci(keys)), descrizione)


def leggi_predefinite() -> list[str] | None:
    return _leggi(CHIAVE_PREDEFINITE)


def salva_predefinite(keys: list[str] | None) -> None:
    _scrivi(CHIAVE_PREDEFINITE, keys, "Azioni rapide della home predefinite per tutti")


def leggi_ruolo(role_id) -> list[str] | None:
    if role_id in (None, ""):
        return None
    return _leggi(CHIAVE_RUOLO.format(int(role_id)))


def salva_ruolo(role_id, keys: list[str] | None) -> None:
    _scrivi(CHIAVE_RUOLO.format(int(role_id)), keys, f"Azioni rapide della home predefinite per il ruolo {int(role_id)}")


def ruoli_personalizzati() -> set[int]:
    prefisso = CHIAVE_RUOLO.format("")
    out: set[int] = set()
    for chiave in SiteConfig.objects.filter(chiave__startswith=prefisso).values_list("chiave", flat=True):
        coda = chiave[len(prefisso):]
        if coda.isdigit():
            out.add(int(coda))
    return out


def standard() -> list[str]:
    from dashboard.views_home_portale import _AZIONI_RAPIDE

    return [f"a:{spec['code']}" for spec in _AZIONI_RAPIDE]


def lista_effettiva(prefs: dict, role_id) -> tuple[list[str], str, int | None]:
    """(chiavi, fonte, limite). Il limite vale solo per lo standard (prime N consentite)."""
    from dashboard.views_home_portale import HOME_AZIONI_MAX

    personali = prefs.get("azioni")
    if isinstance(personali, list):
        fonte = FONTE_ADMIN if prefs.get("azioni_fonte") == FONTE_ADMIN else FONTE_UTENTE
        return personali, fonte, None
    di_ruolo = leggi_ruolo(role_id)
    if di_ruolo is not None:
        return di_ruolo, "ruolo", None
    predefinite = leggi_predefinite()
    if predefinite is not None:
        return predefinite, "predefinite", None
    return standard(), "standard", HOME_AZIONI_MAX


def voci_consentite(request, is_admin: bool, groups: list[dict]) -> list[dict]:
    """Voci che QUESTA persona può aprire, con l'indirizzo già risolto.

    ``groups`` sono i gruppi moduli della home, già filtrati per permessi.
    """
    from dashboard.views_home_portale import (
        _AZIONI_RAPIDE,
        _azione_consentita,
        _safe_url,
        _sistema_ruoli_attivo,
        moduli_visibili,
    )

    da_ruoli = _sistema_ruoli_attivo()
    visibili = None if (da_ruoli or is_admin) else moduli_visibili(request, is_admin)
    out: list[dict] = []
    for spec in _AZIONI_RAPIDE:
        href = _safe_url(spec["url_name"])
        if href == "#":
            continue
        try:
            ok = _azione_consentita(request, spec, is_admin, da_ruoli, visibili)
        except Exception:
            logger.exception("Home: azione rapida %s non valutata", spec["label"])
            ok = False
        if ok:
            out.append({"key": f"a:{spec['code']}", "label": spec["label"], "href": href, "gruppo": "Azioni"})
    visti: set[str] = set()
    for grp in groups:
        for mod in grp.get("modules", []):
            if not mod.get("accessible") or not mod.get("url") or mod["url"] == "#" or mod["id"] in visti:
                continue
            visti.add(mod["id"])
            out.append({"key": f"m:{mod['id']}", "label": mod["label"], "href": mod["url"], "gruppo": "Moduli"})
    return out


def azioni_home(prefs: dict, role_id, consentite: list[dict]) -> dict:
    """Azioni da mostrare nella colonna di sinistra + dati per «Personalizza»."""
    keys, fonte, limite = lista_effettiva(prefs, role_id)
    per_key = {v["key"]: v for v in consentite}
    scelte = [per_key[k] for k in keys if k in per_key]
    if limite:
        scelte = scelte[:limite]
    azioni = [
        {"label": v["label"], "href": v["href"], "variant": "primary" if i == 0 else "ghost"}
        for i, v in enumerate(scelte)
    ]
    return {
        "azioni": azioni,
        "scelte": scelte,
        "offerte": consentite,
        "fonte": fonte,
        "fonte_label": FONTI_LABEL.get(fonte, ""),
    }
