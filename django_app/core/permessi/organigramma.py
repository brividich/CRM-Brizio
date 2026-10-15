"""Ruoli del portale che arrivano dall'organigramma.

Ogni ruolo d'organigramma (``anagrafica.RuoloOperativo``) puo' indicare i ruoli
del portale (``core.AccessGroup``) che concede: chi lo ricopre oggi li riceve in
automatico, accanto a quelli assegnati a mano dalla scheda «Persone». Tolta
l'assegnazione dall'organigramma, il ruolo del portale sparisce con essa.

Regole:

- conta lo stato attuale dell'organigramma: le stesse assegnazioni che danno il
  team (``core.permessi.team``), quindi ruolo attivo e assegnazione in corso;
- un ruolo del portale ``amministratore`` non arriva mai dall'organigramma,
  anche se collegato: si assegna solo a mano;
- in caso di errore non arriva nulla (si nega, non si allarga).

Gli id sono ``utenti.id``, lo stesso spazio di ``AccessGroupMembership``.
"""
from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import DatabaseError

logger = logging.getLogger(__name__)

_CACHE_TTL = 120


def _profili_per_ruolo(ruolo_ids) -> dict[int, set[int]]:
    """{ruolo d'organigramma: {AccessGroup concessi}}, solo ruoli del portale ammessi."""
    from anagrafica.models import RuoloOperativo

    ids = [int(r) for r in ruolo_ids or [] if r]
    if not ids:
        return {}
    through = RuoloOperativo.profili_permessi.through
    mappa: dict[int, set[int]] = {}
    for ruolo_id, gruppo_id in through.objects.filter(
        ruolooperativo_id__in=ids,
        accessgroup__is_active=True,
        accessgroup__amministratore=False,
    ).values_list("ruolooperativo_id", "accessgroup_id"):
        mappa.setdefault(int(ruolo_id), set()).add(int(gruppo_id))
    return mappa


def provenienze_per_utenti(utenti_ids) -> dict[int, dict[int, list[str]]]:
    """Per ogni ``utenti.id``: {AccessGroup id: [nomi dei ruoli d'organigramma che lo danno]}.

    Lettura in blocco (tre query), per gli elenchi della pagina «Ruoli e permessi».
    """
    from core.legacy_models import AnagraficaDipendente
    from core.permessi.team import _assegnazioni_attive

    ids = [int(u) for u in utenti_ids or [] if u]
    if not ids:
        return {}
    try:
        anagrafica_utente = dict(
            AnagraficaDipendente.objects.filter(utente_id__in=ids).values_list("id", "utente_id")
        )
        if not anagrafica_utente:
            return {}
        assegnazioni = list(
            _assegnazioni_attive()
            .filter(legacy_anagrafica_id__in=list(anagrafica_utente))
            .values_list("legacy_anagrafica_id", "ruolo_id", "ruolo__nome")
        )
        profili = _profili_per_ruolo({r for _a, r, _n in assegnazioni})
    except DatabaseError:
        logger.warning("permessi.organigramma: lettura fallita", exc_info=True)
        return {}
    esito: dict[int, dict[int, list[str]]] = {}
    for anagrafica_id, ruolo_id, nome in assegnazioni:
        utente = anagrafica_utente.get(anagrafica_id)
        if not utente:
            continue
        for gruppo_id in profili.get(int(ruolo_id), ()):
            nomi = esito.setdefault(int(utente), {}).setdefault(gruppo_id, [])
            if nome not in nomi:
                nomi.append(nome)
    return esito


def profili_da_organigramma(legacy_user_id: int | None) -> list[int]:
    """Id degli AccessGroup che la persona riceve oggi dall'organigramma (in cache)."""
    if not legacy_user_id:
        return []
    from core.permessi.cache import versione_permessi

    chiave = f"permessi:organigramma:v{versione_permessi()}:{int(legacy_user_id)}"
    try:
        cached = cache.get(chiave)
    except Exception:
        cached = None
    if cached is not None:
        return list(cached)
    ids = sorted(provenienze_per_utenti([legacy_user_id]).get(int(legacy_user_id), {}))
    try:
        cache.set(chiave, ids, _CACHE_TTL)
    except Exception:
        pass
    return ids
