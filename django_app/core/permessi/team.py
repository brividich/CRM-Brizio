"""Il team di una persona, ricavato dall'organigramma per ruolo.

Fonte unica: il catalogo ``anagrafica.RuoloOperativo`` con la sua gerarchia
(``riporta_a``) e le assegnazioni ``DipendenteRuoloOperativo``. La gerarchia e'
fra RUOLI, non fra persone: il team di chi ricopre un ruolo sono tutte le
persone che ricoprono un ruolo che gli riporta, direttamente o attraverso
altri ruoli.

Esempio: «Responsabile produzione» <- «Capo reparto fresatura» <- «Operatore
fresa». Chi e' Responsabile produzione ha nel team capi reparto e operatori; il
capo reparto ha nel team solo gli operatori. Chi ricopre lo stesso ruolo e' un
collega, non un membro del team.

Gli id restituiti sono ``utenti.id`` (``UtenteLegacy``), lo stesso spazio di
``AccessGroupMembership.legacy_user_id``. Le assegnazioni concluse
(``data_fine`` nel passato) non contano. In caso di errore il team e' vuoto:
si nega, non si allarga.
"""
from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import DatabaseError
from django.utils import timezone

logger = logging.getLogger(__name__)

_CACHE_TTL = 120
_CACHE_VERSION_KEY = "permessi:team:version"


def _versione() -> int:
    try:
        value = cache.get(_CACHE_VERSION_KEY)
        if value is None:
            value = 1
            cache.set(_CACHE_VERSION_KEY, value, None)
        return int(value)
    except Exception:
        return 1


def invalida_cache_team() -> None:
    """Da chiamare quando cambia l'organigramma (ruoli o assegnazioni)."""
    try:
        cache.set(_CACHE_VERSION_KEY, _versione() + 1, None)
    except Exception:
        logger.warning("permessi.team: impossibile invalidare la cache dei team", exc_info=True)


def _assegnazioni_attive():
    from django.db.models import Q

    from anagrafica.models import DipendenteRuoloOperativo

    oggi = timezone.localdate()
    return DipendenteRuoloOperativo.objects.filter(
        Q(data_fine__isnull=True) | Q(data_fine__gte=oggi),
        ruolo__is_active=True,
    )


def _anagrafica_ids_di(legacy_user_id: int) -> list[int]:
    from core.legacy_models import AnagraficaDipendente

    return list(
        AnagraficaDipendente.objects.filter(utente_id=int(legacy_user_id)).values_list("id", flat=True)
    )


def ruoli_organigramma_di(legacy_user_id: int | None) -> list[int]:
    """Id dei ruoli d'organigramma ricoperti oggi dalla persona."""
    if not legacy_user_id:
        return []
    try:
        anagrafica_ids = _anagrafica_ids_di(int(legacy_user_id))
        if not anagrafica_ids:
            return []
        return sorted(
            set(
                _assegnazioni_attive()
                .filter(legacy_anagrafica_id__in=anagrafica_ids)
                .values_list("ruolo_id", flat=True)
            )
        )
    except DatabaseError:
        logger.warning("permessi.team: ruoli non leggibili per utente %s", legacy_user_id, exc_info=True)
        return []


def ruoli_sottoposti(ruolo_ids) -> set[int]:
    """Tutti i ruoli che riportano (anche indirettamente) ai ruoli dati."""
    from anagrafica.models import RuoloOperativo

    radici = {int(r) for r in ruolo_ids or []}
    if not radici:
        return set()
    figli: dict[int, list[int]] = {}
    for ruolo_id, padre_id in RuoloOperativo.objects.filter(is_active=True).values_list("id", "riporta_a_id"):
        if padre_id:
            figli.setdefault(int(padre_id), []).append(int(ruolo_id))

    visti: set[int] = set()
    da_visitare = list(radici)
    while da_visitare:
        corrente = da_visitare.pop()
        for figlio in figli.get(corrente, []):
            if figlio not in visti:
                visti.add(figlio)
                da_visitare.append(figlio)
    # Un ciclo nell'organigramma riporterebbe i ruoli di partenza: non sono team.
    return visti - radici


def _team_regola_unica(legacy_user_id: int) -> set[int] | None:
    """Team dalla regola unica capo/team (reparto/area + organigramma), se accesa.

    ``None`` = regola spenta: vale la gerarchia dei soli ruoli qui sotto.
    """
    try:
        from anagrafica.services import capo_team
    except Exception:
        return None
    if not capo_team.regola_unica_attiva():
        return None
    team: set[int] = set()
    for anagrafica_id in _anagrafica_ids_di(legacy_user_id):
        team |= capo_team.team_anagrafica(anagrafica_id)
    return team


def _calcola_team(legacy_user_id: int) -> frozenset[int]:
    from core.legacy_models import AnagraficaDipendente, UtenteLegacy

    anagrafica_ids = _team_regola_unica(legacy_user_id)
    if anagrafica_ids is None:
        sottoposti = ruoli_sottoposti(ruoli_organigramma_di(legacy_user_id))
        if not sottoposti:
            return frozenset()
        anagrafica_ids = set(
            _assegnazioni_attive().filter(ruolo_id__in=sottoposti).values_list("legacy_anagrafica_id", flat=True)
        )
    if not anagrafica_ids:
        return frozenset()
    utenti = set(
        AnagraficaDipendente.objects.filter(id__in=anagrafica_ids, utente_id__isnull=False).values_list(
            "utente_id", flat=True
        )
    )
    attivi = set(UtenteLegacy.objects.filter(id__in=utenti, attivo=True).values_list("id", flat=True))
    attivi.discard(int(legacy_user_id))
    return frozenset(int(u) for u in attivi)


def team_di(legacy_user_id: int | None) -> frozenset[int]:
    """``utenti.id`` delle persone del team (esclusa la persona stessa)."""
    if not legacy_user_id:
        return frozenset()
    chiave = f"permessi:team:v{_versione()}:{int(legacy_user_id)}"
    try:
        cached = cache.get(chiave)
    except Exception:
        cached = None
    if cached is not None:
        return frozenset(cached)
    try:
        team = _calcola_team(int(legacy_user_id))
    except DatabaseError:
        logger.warning("permessi.team: calcolo fallito per utente %s", legacy_user_id, exc_info=True)
        return frozenset()
    try:
        cache.set(chiave, sorted(team), _CACHE_TTL)
    except Exception:
        logger.debug("permessi.team: cache non scrivibile", exc_info=True)
    return team
