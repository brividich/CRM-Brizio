"""Permessi della reportistica: decisione sempre server-side, fail-closed."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PERM_REPORTISTICA_VIEW = "anagrafica.reportistica.view"
PERM_REPORTISTICA_MANAGE = "anagrafica.reportistica.manage"


def has_perm(request, code: str) -> bool:
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    try:
        from core.acl_v2 import evaluate_permission_code_access
        from core.legacy_utils import get_legacy_user

        legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(user)
        return bool(evaluate_permission_code_access(
            permission_code=code, legacy_user=legacy_user, django_user=user,
        ).get("allowed"))
    except Exception:
        logger.warning("reportistica: valutazione permesso %s fallita", code, exc_info=True)
        return False


def can_view(request) -> bool:
    return has_perm(request, PERM_REPORTISTICA_VIEW)


def can_manage(request) -> bool:
    return has_perm(request, PERM_REPORTISTICA_MANAGE)


def perm_check(code: str):
    """Gate riusabile per le sezioni che richiedono un permesso ulteriore."""

    def _check(request) -> bool:
        return has_perm(request, code)

    return _check
