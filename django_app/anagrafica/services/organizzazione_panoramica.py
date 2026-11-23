"""Pagina d'ingresso della sezione «Organizzazione»: numeri, collegamenti diretti, cose da fare.

Non calcola niente di suo: ogni numero viene dalla stessa funzione della pagina a cui porta,
così il numero e l'elenco non possono divergere.

- numeri e struttura: ``struttura_vista`` (la pagina «Struttura organizzativa»), solo per chi
  la può vedere;
- richieste: ``richieste.da_fare`` (la pagina «Da fare»);
- collegamenti: una tessera per pagina della sezione, mostrata solo a chi la può aprire.
"""
from __future__ import annotations

import logging

from django.urls import reverse

from ..models import CentroDiCosto, VoceMacchinaCatalogo
from ..models_richieste import RichiestaCompetenze
from . import capo_team, competenze_catalogo, richieste
from .esplora_struttura import _quanti
from . import struttura_revisioni as rev
from . import struttura_vista as vista

logger = logging.getLogger(__name__)
RESPONSABILE = "Reparti senza ruolo responsabile"


def _puo_aprire(request, url: str) -> bool:
    from core.middleware import acl_allows_path

    try:
        return bool(acl_allows_path(url.split("?")[0].split("#")[0], django_user=request.user,
                                    legacy_user=getattr(request, "legacy_user", None), request=None))
    except Exception:
        logger.warning("Organizzazione: verifica ACL fallita per %s", url, exc_info=True)
        return False


def _struttura() -> dict:
    """Numeri della struttura, con le stesse funzioni delle pagine a cui portano."""
    mansioni = vista._mansioni()
    alb, procs, rls = vista.albero(mansioni), vista.processi(mansioni), vista.ruoli(mansioni)
    kpi = vista.kpi(alb, procs, rls, mansioni)
    ultima = rev.ultima()
    modifiche = rev.confronto(ultima.dati, rev.fotografia()) if ultima else None
    ids = [m.pk for m in mansioni]
    con_competenze = set(VoceMacchinaCatalogo.objects.filter(mansione_id__in=ids, attiva=True)
                         .values_list("mansione_id", flat=True))
    return {
        "kpi": kpi,
        "centri": CentroDiCosto.objects.filter(is_active=True).count(),
        "competenze": len(competenze_catalogo.elenco()),
        "persone": len(capo_team.mappa_capi_in_cache()),
        "senza_competenze": len(ids) - len(con_competenze),
        "da_completare": vista.da_completare(mansioni),
        "ultima": ultima,
        "n_modifiche": sum(len(s["aggiunte"]) + len(s["tolte"]) + len(s["cambiate"]) for s in modifiche or []),
    }


def _numeri(s: dict) -> list[dict]:
    k = s["kpi"]
    return [
        {"n": s["centri"], "nome": "Centri di costo", "url": reverse("anagrafica:centri_costo")},
        {"n": k["reparti"], "nome": "Reparti", "url": reverse("anagrafica:aree_list")},
        {"n": k["aree"], "nome": "Aree", "url": reverse("anagrafica:aree_list")},
        {"n": k["ruoli"], "nome": "Ruoli", "url": reverse("anagrafica:struttura_org") + "#ruoli"},
        {"n": k["mansioni"], "nome": "Mansioni", "url": reverse("anagrafica:mansionario")},
        {"n": s["competenze"], "nome": "Competenze", "url": reverse("anagrafica:mansionario_catalogo")},
        {"n": s["persone"], "nome": "Persone in forza", "url": reverse("anagrafica:dipendenti_list")},
    ]


def _da_fare(dati_richieste: dict, s: dict | None) -> list[dict]:
    """Solo ciò che aspetta qualcuno: le righe a zero non compaiono."""
    url_da_fare = reverse("anagrafica:richieste_da_fare")
    righe = [
        {"titolo": "Richieste da approvare", "sotto": "Tocca a te decidere", "n": len(dati_richieste["da_approvare"]),
         "url": url_da_fare, "azione": "Decidi", "urgente": True},
        {"titolo": "Le mie richieste in attesa di altri", "sotto": "Aspettano l'approvazione o la sessione formativa",
         "n": len(dati_richieste["in_attesa"]), "url": url_da_fare, "azione": "Apri", "urgente": False},
    ]
    if s is not None:
        completare = {x["titolo"]: len(x["voci"]) for x in s["da_completare"]}
        url_completare = reverse("anagrafica:struttura_org") + "#completare"
        righe += [
            {"titolo": "Mansioni senza competenze", "sotto": "Nessuna competenza richiesta è ancora caricata",
             "n": s["senza_competenze"], "url": reverse("anagrafica:mansionario"), "azione": "Apri", "urgente": False},
            {"titolo": "Reparti senza responsabile", "sotto": "Manca il ruolo responsabile del reparto",
             "n": completare.pop(RESPONSABILE, 0), "url": url_completare, "azione": "Apri", "urgente": False},
            {"titolo": "Rischi da confermare", "sotto": "Mansioni di rischio proposte dal portale",
             "n": s["kpi"]["rischi_da_confermare"], "url": reverse("anagrafica:struttura_rischi"), "azione": "Conferma",
             "urgente": False},
            {"titolo": "Altro da completare nella struttura", "sotto": "Aree, processi, ruoli e capi ancora da indicare",
             "n": sum(completare.values()), "url": url_completare, "azione": "Apri", "urgente": False},
        ]
    return [r for r in righe if r["n"]]


def _collegamenti(request, s: dict | None, attore, dati_richieste: dict) -> list[dict]:
    k = s["kpi"] if s is not None else None
    aperte = richieste.visibili(attore).filter(stato__in=RichiestaCompetenze.STATI_APERTI).count()
    revisione = ""
    if s is not None:
        if s["n_modifiche"]:
            revisione = f"{s['n_modifiche']} modific{'a' if s['n_modifiche'] == 1 else 'he'} non emess{'a' if s['n_modifiche'] == 1 else 'e'}"
        elif s["ultima"] is not None:
            revisione = f"Rev. {s['ultima'].numero} in vigore"
        else:
            revisione = "Nessuna revisione emessa"
    tessere = [
        {"nome": "Esplora la struttura", "icona": "grid", "url": reverse("anagrafica:esplora_struttura"),
         "spiega": "Dal centro di costo alla mansione: che cosa richiede e chi ce l'ha.",
         "etichetta": _quanti(s["centri"], "centro di costo", "centri di costo") if s else ""},
        {"nome": "Mansioni", "icona": "clipboard", "url": reverse("anagrafica:mansionario"),
         "spiega": "Le mansioni, le competenze richieste e le persone.",
         "etichetta": _quanti(k["mansioni"], "mansione", "mansioni") if k else ""},
        {"nome": "Richieste", "icona": "edit", "url": reverse("anagrafica:richieste"),
         "spiega": "Assegnare, sospendere o rimuovere una mansione; acquisire una competenza.",
         "etichetta": f"{aperte} apert{'a' if aperte == 1 else 'e'}", "attesa": len(dati_richieste["da_approvare"])},
        {"nome": "Reparti e capi", "icona": "users", "url": reverse("anagrafica:aree_list"),
         "spiega": "Reparti, aree e responsabili.",
         "etichetta": f"{_quanti(k['reparti'], 'reparto', 'reparti')} · {_quanti(k['aree'], 'area', 'aree')}" if k else ""},
        {"nome": "Centri di costo", "icona": "coins", "url": reverse("anagrafica:centri_costo"),
         "spiega": "Quali reparti stanno in quale centro di costo.",
         "etichetta": _quanti(s["centri"], "centro", "centri") if s else ""},
        {"nome": "Organigramma", "icona": "building", "url": reverse("anagrafica:organigramma"),
         "spiega": "Chi riporta a chi.", "etichetta": ""},
        {"nome": "Prova un cambiamento", "icona": "refresh", "url": reverse("anagrafica:prospetti"),
         "spiega": "Confronta oggi e dopo, prima di spostare persone o ruoli.", "etichetta": ""},
        {"nome": "Struttura e revisioni", "icona": "doc", "url": reverse("anagrafica:struttura_org"),
         "spiega": "La struttura approvata dalla Qualità e le sue emissioni.", "etichetta": revisione},
    ]
    return [t for t in tessere if _puo_aprire(request, t["url"])]


def costruisci(request) -> dict:
    from ..views_mansionario import _puo_vedere

    attore = richieste.attore(request)
    dati_richieste = richieste.da_fare(attore)
    s = _struttura() if _puo_vedere(request) else None
    nota = ""
    if s is not None:
        if s["ultima"] is None:
            nota = "La struttura è ancora una bozza: nessuna revisione è stata emessa."
        elif s["n_modifiche"]:
            nota = (f"In vigore la revisione {s['ultima'].numero} del {s['ultima'].emessa_il:%d/%m/%Y}; "
                    f"la bozza ha {s['n_modifiche']} modifiche non ancora emesse.")
        else:
            nota = f"La struttura coincide con la revisione {s['ultima'].numero} del {s['ultima'].emessa_il:%d/%m/%Y}."
    return {
        "numeri": _numeri(s) if s is not None else [],
        "da_fare": _da_fare(dati_richieste, s),
        "collegamenti": _collegamenti(request, s, attore, dati_richieste),
        "nota": nota,
        "puo_chiedere": bool(richieste.tipi_ammessi(attore)),
    }
