"""Versione delle cache dei permessi: una modifica a ruoli o matrice le azzera tutte."""
from __future__ import annotations

import logging
from django.core.cache import cache

logger = logging.getLogger(__name__)

_VERSION_KEY = "permessi:version"
_ADMIN_TTL = 120


def versione_permessi() -> int:
    try:
        value = cache.get(_VERSION_KEY)
        if value is None:
            value = 1
            cache.set(_VERSION_KEY, value, None)
        return int(value)
    except Exception:
        return 1


def invalida_permessi() -> None:
    """Dopo ogni modifica a ruoli, appartenenze o matrice: menu e cache ripartono."""
    try:
        cache.set(_VERSION_KEY, versione_permessi() + 1, None)
    except Exception:
        logger.warning("permessi: impossibile aggiornare la versione in cache", exc_info=True)
    try:
        from core.navigation_registry import bump_navigation_registry_version

        bump_navigation_registry_version()
    except Exception:
        logger.warning("permessi: impossibile invalidare il registro di navigazione", exc_info=True)
    try:
        from core.permessi.team import invalida_cache_team

        invalida_cache_team()
    except Exception:
        logger.warning("permessi: impossibile invalidare la cache dei team", exc_info=True)


def utenti_amministratori_da_ruolo() -> frozenset[int]:
    """``utenti.id`` di chi ha un ruolo con ``amministratore=True`` (in cache)."""
    chiave = f"permessi:admin_ids:v{versione_permessi()}"
    try:
        cached = cache.get(chiave)
    except Exception:
        cached = None
    if cached is not None:
        return frozenset(cached)
    from django.db import DatabaseError

    from core.models import AccessGroupMembership
    from core.permessi.scadenze import q_appartenenze_valide

    try:
        ids = sorted(
            set(
                AccessGroupMembership.objects.filter(
                    q_appartenenze_valide(), group__is_active=True, group__amministratore=True
                ).values_list("legacy_user_id", flat=True)
            )
        )
    except DatabaseError:
        return frozenset()
    try:
        cache.set(chiave, ids, _ADMIN_TTL)
    except Exception:
        logger.debug("permessi: cache non scrivibile (amministratori)", exc_info=True)
    return frozenset(int(i) for i in ids)
