"""Permessi interni dello scadenzario generale.

- **Pannello di gestione**: amministratori del portale e chi ha una regola sulla
  voce «Chi gestisce il pannello».
- **Scadenze generiche**: vede chi ha una regola «Vede» (o «Vede e gestisce") sulla
  fonte, sulla categoria o sull'attività, oltre al responsabile dell'attività;
  inserisce, modifica e rinnova chi ha «Vede e gestisce» sulla fonte o sulla
  categoria. Gli amministratori del pannello fanno tutto.
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
    conf = vis.configurazione_di(request)
    chiavi = chiavi_di(SOURCE, chiave_categoria(scadenza.categoria_id), chiave_attivita(scadenza.pk))
    return conf.attiva(chiavi) and conf.concede(vis.identita_di(request), chiavi)


def categorie_visibili(request) -> set[int] | None:
    """Id delle categorie di cui la persona vede almeno qualcosa; None = tutte."""
    from .models import CategoriaScadenza

    if puo_gestire_pannello(request):
        return None
    conf, ident = vis.configurazione_di(request), vis.identita_di(request)
    esito = set()
    for cat_id in CategoriaScadenza.objects.values_list("pk", flat=True):
        chiave_cat = _chiavi_categoria(cat_id)[-1]
        if conf.concede(ident, _chiavi_categoria(cat_id)):
            esito.add(cat_id)
            continue
        # Regola su una singola attività della categoria.
        if any(c.startswith(chiave_cat + "|") and conf.concede(ident, [c]) for c in conf.regole):
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
