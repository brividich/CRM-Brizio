"""Permessi interni dello scadenzario generale.

- **Pannello di gestione**: amministratori del portale e chi ha una regola sulla
  voce «Chi gestisce il pannello».
- **Scadenze generiche**: vede chi ha una regola «Vede» (o «Vede e gestisce") sulla
  fonte, sulla categoria o sull'attività, oltre al responsabile dell'attività;
  inserisce, modifica e rinnova chi ha «Vede e gestisce» sulla fonte o sulla
  categoria. Gli amministratori del pannello fanno tutto. Una regola «Propri» o
  «Propri e del team» fa vedere solo le attività del responsabile che rientra
  nell'ambito e non dà mai la gestione (la gestione vale per tutta la categoria).
"""
from __future__ import annotations

from .fonte import SOURCE, chiave_attivita, chiave_categoria
from . import visibilita as vis
from .visibilita import chiavi_di


def puo_gestire_pannello(request) -> bool:
    return vis.puo_gestire_pannello(request)


def _chiavi_categoria(categoria_id: int) -> list[str]:
    return chiavi_di(SOURCE, chiave_categoria(categoria_id))


def puo_gestire_categoria(request, categoria_id: int) -> bool:
    if puo_gestire_pannello(request):
        return True
    return vis.configurazione_di(request).concede(vis.identita_di(request), _chiavi_categoria(categoria_id), gestione=True)


def puo_vedere_scadenza(request, scadenza) -> bool:
    if puo_gestire_pannello(request):
        return True
    if scadenza.responsabile_id and scadenza.responsabile_id == getattr(request.user, "id", None):
        return True
    conf, ident = vis.configurazione_di(request), vis.identita_di(request)
    chiavi = chiavi_di(SOURCE, chiave_categoria(scadenza.categoria_id), chiave_attivita(scadenza.pk))
    if not conf.attiva(chiavi):
        return False
    if conf.concede(ident, chiavi):
        return True
    if not scadenza.responsabile_id or not conf.ha_ambiti_limitati(ident):
        return False
    return conf.concede(ident, chiavi, proprietari=_proprietari_scadenza(ident, scadenza.responsabile_id))


def _proprietari_scadenza(ident, responsabile_id: int) -> frozenset[int]:
    """utenti.id del responsabile, ricordato per la richiesta (l'elenco lo chiede riga per riga)."""
    gia = ident.__dict__.setdefault("_responsabili", {})
    if responsabile_id not in gia:
        legacy = vis._legacy_da_utenti([responsabile_id]).get(int(responsabile_id))
        gia[responsabile_id] = frozenset({legacy}) if legacy else frozenset()
    return gia[responsabile_id]


def categorie_visibili(request, *, solo_intere: bool = False) -> set[int] | None:
    """Id delle categorie di cui la persona vede almeno qualcosa; None = tutte.

    ``solo_intere``: non contano le regole «Propri»/«Propri e del team», per le pagine
    che mostrano la categoria senza guardare le singole attività (Avvisi).
    """
    from .models import CategoriaScadenza

    if puo_gestire_pannello(request):
        return None
    conf, ident = vis.configurazione_di(request), vis.identita_di(request)
    ignora = not solo_intere
    esito = set()
    for cat_id in CategoriaScadenza.objects.values_list("pk", flat=True):
        chiave_cat = _chiavi_categoria(cat_id)[-1]
        if conf.concede(ident, _chiavi_categoria(cat_id), ignora_ambito=ignora):
            esito.add(cat_id)
            continue
        # Regola su una singola attività della categoria.
        if any(c.startswith(chiave_cat + "|") and conf.concede(ident, [c], ignora_ambito=ignora) for c in conf.regole):
            esito.add(cat_id)
    return esito


def categorie_gestibili(request) -> set[int] | None:
    from .models import CategoriaScadenza

    if puo_gestire_pannello(request):
        return None
    return {c for c in CategoriaScadenza.objects.values_list("pk", flat=True) if puo_gestire_categoria(request, c)}


def puo_usare_modulo(request) -> bool:
    """Vede almeno una parte delle scadenze generiche (voce di menu e pagine)."""
    from .models import ScadenzaGenerica

    visibili = categorie_visibili(request)
    if visibili is None or visibili:
        return True
    user_id = getattr(request.user, "id", None)
    return bool(user_id and ScadenzaGenerica.objects.filter(responsabile_id=user_id).exists())
