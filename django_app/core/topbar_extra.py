"""Topbar: descrizioni delle voci, griglia «Moduli», tendina «Preferiti», scorciatoie di Anagrafica.

Tutto nasce da ``topbar_groups``, già filtrato per permessi: qui non si aggiunge nessuna voce che
la persona non veda già. I calcoli che fanno query sono pigri e partono solo se la topbar viene
disegnata, non a ogni frammento HTMX.

I preferiti sono quelli della home (``UserUiPreference.home_prefs``). Un modulo presente nel
catalogo della home usa il suo id, così la stella è la stessa nei due posti; le altre voci usano
``nav:<codice>``, che la home ignora.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from urllib.parse import urlsplit

from django.urls import NoReverseMatch, reverse
from django.utils.functional import SimpleLazyObject

logger = logging.getLogger(__name__)

# Una riga sotto l'etichetta, nei pannelli delle aree. Una voce senza descrizione mostra solo il nome.
DESCRIZIONI = {
    "procedure_refresh": "Procedure da leggere e confermare",
    "per-me-kickoff-da-gestire": "Le attività assegnate a te",
    "assenze": "Le tue richieste e i tuoi saldi",
    "per-me-richiedi-assenza": "Ferie, permessi, malattia",
    "per-me-richiedi-dpi": "Nuova richiesta di DPI",
    "notizie": "Comunicazioni aziendali",
    "tasks": "Commesse, programmi, attività",
    "vrf-kick-off": "Commesse, programmi, attività",
    "carichi-macchina": "Carichi di lavoro delle macchine",
    "checklist_operativa": "Checklist di chiusura aziendale",
    "assets": "Macchine, ordini di lavoro, scadenze",
    "gestione-attrezzatura": "Attrezzature e loro stato",
    "anagrafica": "Dipendenti, competenze, salute e sicurezza",
    "presenti": "Chi c'è ora, appello di evacuazione",
    "persone-assenze-hr": "Richieste, saldi, calendario",
    "timbri": "Timbri, firme e sigle",
    "persone-campagne-presa-visione": "Procedure da far leggere",
    "diario_preposto": "Giornale di sicurezza",
    "segnalazionisicurezza": "Near miss e infortuni",
    "dpi": "Consegne e firma",
    "schede-sicurezza": "Prodotti chimici e schede",
    "rentri": "Tracciamento rifiuti",
    "gestione_anomalie": "Non conformità sugli ordini",
    "gestione-specifiche": "Specifiche cliente e MOD.133",
    "ofi_registro": "Opportunità di miglioramento e NC",
    "report-conformita": "Report di conformità",
    "sistema-gestione": "Audit, riesame, certificazioni",
    "glossario-tecnico": "Termini tecnici",
    "security_center": "Alert, ticket, KPI sicurezza",
    "contatori": "Stampanti, letture, consumabili",
    "accessi": "Utenti e permessi",
}

CODICE_ANAGRAFICA = "anagrafica"
CODICE_ICONA = "suggestion-corner"
DENTRO_ANAGRAFICA = (
    ("Elenco dipendenti", "anagrafica:dipendenti_list"),
    ("Organigramma", "anagrafica:organigramma"),
    ("Formazione", "anagrafica:formazione_dashboard"),
    ("Scadenzario HR", "anagrafica:scadenzario"),
)


@lru_cache(maxsize=1)
def _id_modulo_per_percorso() -> dict[str, str]:
    from dashboard.views_home_portale import _MODULE_CATALOG

    out: dict[str, str] = {}
    for spec in _MODULE_CATALOG:
        if spec.get("url_name") in (None, "", "#"):
            continue
        try:
            out.setdefault(reverse(spec["url_name"]), spec["id"])
        except NoReverseMatch:
            continue
    return out


def id_preferito(item) -> str:
    percorso = urlsplit(getattr(item, "href", "") or "").path
    return _id_modulo_per_percorso().get(percorso) or f"nav:{item.codice}"[:40]


def _preferiti_salvati(user) -> list[str]:
    from core.models import UserUiPreference
    from dashboard.views_home_portale import _pulisci_home_prefs

    riga = UserUiPreference.objects.filter(user=user).values_list("home_prefs", flat=True).first()
    return _pulisci_home_prefs(riga or {})["preferiti"]


def _dentro_anagrafica(request) -> list[dict]:
    """Scorciatoie nel pannello dell'area: solo le pagine che la persona può aprire."""
    from anagrafica.subnav_gates import section_gate_allows
    from core.middleware import acl_allows_path

    voci = []
    for label, nome in DENTRO_ANAGRAFICA:
        try:
            url = reverse(nome)
            if acl_allows_path(url, django_user=request.user, legacy_user=getattr(request, "legacy_user", None),
                               request=None) and section_gate_allows(request, url):
                voci.append({"label": label, "href": url})
        except Exception:
            logger.warning("Topbar: scorciatoia %s non verificata", nome, exc_info=True)
    return voci


def _griglia(request, gruppi: list[dict]) -> dict:
    try:
        salvati = _preferiti_salvati(request.user)
    except Exception:
        logger.warning("Topbar: preferiti non disponibili", exc_info=True)
        salvati = []
    per_id: dict[str, dict] = {}

    def voce(item) -> dict:
        v = {"label": item.label, "href": item.href, "active": item.active, "star": id_preferito(item)}
        v["preferito"] = v["star"] in salvati
        per_id.setdefault(v["star"], v)
        return v

    aree, dirette = [], []
    for grp in gruppi:
        if grp["type"] == "category":
            aree.append({"label": grp["label"], "icon": grp.get("icon") or "", "voci": [voce(i) for i in grp["items"]]})
        elif not grp.get("is_home") and not getattr(grp["item"], "coming", False):
            dirette.append(voce(grp["item"]))
    return {"aree": aree, "dirette": dirette, "preferiti": [per_id[i] for i in salvati if i in per_id]}


def arricchisci_topbar(request, result: dict) -> None:
    gruppi = result.get("topbar_groups") or []
    if not gruppi:
        return
    for grp in gruppi:
        if grp["type"] == "category":
            for item in grp["items"]:
                item.descrizione = DESCRIZIONI.get(item.codice, "")
            if any(i.codice == CODICE_ANAGRAFICA for i in grp["items"]):
                grp["dentro_anagrafica"] = SimpleLazyObject(lambda: _dentro_anagrafica(request))
                grp["cols_totali"] = grp["cols"] + 1
        elif grp["item"].codice == CODICE_ICONA:
            grp["in_icona"] = True
            result["topbar_icona_suggerimenti"] = grp["item"]
    griglia = SimpleLazyObject(lambda: _griglia(request, gruppi))
    result["topbar_griglia"] = griglia
    try:
        result["topbar_preferito_url"] = reverse("home_portale:index")
    except NoReverseMatch:
        result["topbar_preferito_url"] = ""
