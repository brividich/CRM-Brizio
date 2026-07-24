"""ACL canonico del modulo Assistente AI.

Il modulo non registrava alcun permesso: la gestione della knowledge base era
riservata a superuser/staff/admin legacy, e `is_legacy_admin()` e' vero solo per
i ruoli il cui nome sta in ``PORTAL_ADMIN_ROLE_NAMES`` (default ``{"admin"}``,
mai valorizzato in alcun settings). Nessun altro ruolo poteva quindi essere
abilitato dal modulo permessi.

Permesso "solo definizione", senza RoutePermissionBinding: con
``ACL_STRICT_CANONICAL=True`` un binding di route negherebbe le pagine a tutti i
ruoli privi di grant esplicito. Il cancello resta in-view e additivo.
"""
from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import DatabaseError, transaction

logger = logging.getLogger(__name__)

_BOOTSTRAP_CACHE_KEY = "ai_assistant_acl_bootstrap_v1"
_BOOTSTRAP_TTL = 3600

MODULE = "ai_assistant"
PERM_KNOWLEDGE_MANAGE = "ai_assistant.knowledge.manage"

_CANONICAL = {
    PERM_KNOWLEDGE_MANAGE: {
        "label": "Assistente AI - Gestione knowledge base",
        "description": (
            "Gestione delle FAQ/knowledge dell'assistente e revisione dei "
            "feedback (approvazione/scarto)."
        ),
    },
}

# Grant di default create-only: solo "admin", che passa comunque dal bypass.
_ROLE_GRANTS = {"admin": {PERM_KNOWLEDGE_MANAGE}}


def bootstrap_ai_assistant_acl_endpoints(force: bool = False) -> None:
    """Registra i permessi canonici del modulo (idempotente, cache-guarded)."""
    from core.acl_bootstrap_base import should_skip_runtime_bootstrap

    # Stessa guardia di `run_bootstrap`: niente query al DB durante test,
    # migrate, check & co. (Django sconsiglia l'accesso al DB in ready()).
    if should_skip_runtime_bootstrap(force=force):
        return
    if not force and cache.get(_BOOTSTRAP_CACHE_KEY):
        return
    try:
        _bootstrap_canonical()
    except DatabaseError:
        # Migrazioni non ancora applicate (es. primo `migrate`): riprova al giro dopo.
        return
    except Exception:
        logger.exception("Bootstrap ACL ai_assistant fallito")
        return
    cache.set(_BOOTSTRAP_CACHE_KEY, True, timeout=_BOOTSTRAP_TTL)


def _bootstrap_canonical() -> bool:
    from core.legacy_models import Ruolo
    from core.models import PermissionDefinition, RolePermissionGrant

    changed = False
    with transaction.atomic():
        for code, payload in _CANONICAL.items():
            _, created = PermissionDefinition.objects.get_or_create(
                code=code,
                defaults={"module": MODULE, "label": payload["label"],
                          "description": payload["description"], "is_active": True},
            )
            changed = changed or created

        for rid, rname in {int(r.id): (r.nome or "").strip().lower()
                           for r in Ruolo.objects.all()}.items():
            grants = _ROLE_GRANTS.get(rname, set())
            for code in _CANONICAL:
                _, created = RolePermissionGrant.objects.get_or_create(
                    legacy_role_id=rid, permission_id=code,
                    defaults={"enabled": code in grants, "note": "[AI_BOOTSTRAP] default"},
                )
                changed = changed or created
    return changed
