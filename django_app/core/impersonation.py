from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.utils import timezone

from core.legacy_models import UtenteLegacy
from core.legacy_utils import get_legacy_user, is_legacy_admin, sync_django_user_from_legacy


IMPERSONATION_SESSION_KEY = "_impersonation_state"
IMPERSONATION_STOP_PATHS = {"/impersonation/stop", "/impersonation/stop/"}


def _clean_state(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def get_impersonation_state(request) -> dict[str, Any]:
    return _clean_state(getattr(request, "session", {}).get(IMPERSONATION_SESSION_KEY))


def clear_impersonation_state(request) -> None:
    if not hasattr(request, "session"):
        return
    request.session.pop(IMPERSONATION_SESSION_KEY, None)
    request.session.modified = True


def is_impersonation_stop_path(path: str) -> bool:
    normalized = str(path or "").strip()
    if not normalized:
        return False
    return normalized in IMPERSONATION_STOP_PATHS


def display_name_for_user(*, django_user=None, legacy_user: UtenteLegacy | None = None) -> str:
    if legacy_user is not None:
        value = str(getattr(legacy_user, "nome", "") or getattr(legacy_user, "email", "") or "").strip()
        if value:
            return value
    if django_user is not None:
        value = str(django_user.get_full_name() or django_user.get_username() or "").strip()
        if value:
            return value
    return ""


def resolve_impersonation_context(request, authenticated_user=None) -> dict[str, Any] | None:
    state = get_impersonation_state(request)
    if not state:
        return None

    auth_user = authenticated_user or getattr(request, "user", None)
    if not getattr(auth_user, "is_authenticated", False):
        clear_impersonation_state(request)
        return None

    try:
        original_user_id = int(state.get("original_user_id"))
        target_user_id = int(state.get("target_user_id"))
        target_legacy_user_id = int(state.get("target_legacy_user_id"))
    except (TypeError, ValueError):
        clear_impersonation_state(request)
        return None

    if int(getattr(auth_user, "id", 0) or 0) != original_user_id:
        clear_impersonation_state(request)
        return None

    original_legacy_user = get_legacy_user(auth_user)
    if not (bool(getattr(auth_user, "is_superuser", False)) or is_legacy_admin(original_legacy_user)):
        clear_impersonation_state(request)
        return None

    User = get_user_model()
    try:
        target_user = User.objects.filter(pk=target_user_id).first()
    except Exception:
        target_user = None

    try:
        target_legacy_user = UtenteLegacy.objects.filter(id=target_legacy_user_id).first()
    except DatabaseError:
        target_legacy_user = None

    if target_legacy_user is None or not bool(getattr(target_legacy_user, "attivo", False)):
        clear_impersonation_state(request)
        return None

    if target_user is None:
        target_user = sync_django_user_from_legacy(target_legacy_user)
    if target_user is None:
        clear_impersonation_state(request)
        return None

    return {
        "state": state,
        "original_user": auth_user,
        "original_legacy_user": original_legacy_user,
        "target_user": target_user,
        "target_legacy_user": target_legacy_user,
    }


def start_impersonation(request, target_legacy_user: UtenteLegacy) -> dict[str, Any] | None:
    if not getattr(request.user, "is_authenticated", False):
        return None

    original_legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    target_user = sync_django_user_from_legacy(target_legacy_user)
    if target_user is None:
        return None

    request.session[IMPERSONATION_SESSION_KEY] = {
        "original_user_id": int(request.user.id),
        "original_legacy_user_id": int(original_legacy_user.id) if original_legacy_user else None,
        "target_user_id": int(target_user.id),
        "target_legacy_user_id": int(target_legacy_user.id),
        "started_at": timezone.now().isoformat(),
    }
    request.session.modified = True
    return {
        "original_user": request.user,
        "original_legacy_user": original_legacy_user,
        "target_user": target_user,
        "target_legacy_user": target_legacy_user,
    }
