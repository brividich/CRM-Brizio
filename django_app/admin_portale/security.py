from __future__ import annotations

import json
import logging
from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse
from django.shortcuts import render

from core.audit import log_action
from core.legacy_utils import get_legacy_user


logger = logging.getLogger("admin_portale.security")

SENSITIVE_AUDIT_ACTION = "admin_sensitive_operation_attempt"


def _is_json_request(request) -> bool:
    accept = (request.headers.get("Accept") or "").lower()
    content_type = (request.headers.get("Content-Type") or "").lower()
    requested_with = (request.headers.get("X-Requested-With") or "").lower()
    path = request.path or ""
    return (
        "application/json" in accept
        or "application/json" in content_type
        or requested_with == "xmlhttprequest"
        or "/api/" in path
    )


def _normalize_role_name(value: object) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def _allowed_role_names() -> set[str]:
    configured = getattr(settings, "ADMIN_PORTALE_SENSITIVE_ALLOWED_ROLE_NAMES", None)
    if not configured:
        return set()
    if isinstance(configured, str):
        configured = (configured,)
    return {_normalize_role_name(name) for name in configured if _normalize_role_name(name)}


def _allowed_role_ids() -> set[int]:
    configured = getattr(settings, "ADMIN_PORTALE_SENSITIVE_ALLOWED_ROLE_IDS", None)
    if not configured:
        return set()
    if isinstance(configured, (str, int)):
        configured = (configured,)
    ids: set[int] = set()
    for value in tuple(configured or ()):
        try:
            ids.add(int(value))
        except (TypeError, ValueError):
            continue
    return ids


def _request_role_candidates(request, legacy_user) -> tuple[set[str], set[int]]:
    names: set[str] = set()
    ids: set[int] = set()
    try:
        profile = request.user.profile
    except Exception:
        profile = None

    for source in (legacy_user, profile):
        role_name = _normalize_role_name(getattr(source, "ruolo", None) or getattr(source, "legacy_ruolo", None))
        if role_name:
            names.add(role_name)
        role_id = getattr(source, "ruolo_id", None) or getattr(source, "legacy_ruolo_id", None)
        if role_id is not None:
            try:
                ids.add(int(role_id))
            except (TypeError, ValueError):
                pass

    try:
        group_names = request.user.groups.values_list("name", flat=True)
    except Exception:
        group_names = []
    names.update(_normalize_role_name(name) for name in group_names if _normalize_role_name(name))
    return names, ids


def is_sensitive_admin_allowed(request) -> tuple[bool, dict]:
    user = getattr(request, "user", None)
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(user)
    request.legacy_user = legacy_user

    if bool(getattr(user, "is_superuser", False)):
        return True, {"reason": "superuser", "legacy_user": legacy_user}

    role_names, role_ids = _request_role_candidates(request, legacy_user)
    allowed_names = _allowed_role_names()
    allowed_ids = _allowed_role_ids()
    if not allowed_names and not allowed_ids:
        return False, {
            "reason": "not_authorized",
            "legacy_user": legacy_user,
            "role_names": sorted(role_names),
            "role_ids": sorted(role_ids),
        }

    matched_names = sorted(role_names & allowed_names)
    matched_ids = sorted(role_ids & allowed_ids)
    if matched_names or matched_ids:
        return True, {
            "reason": "technical_role",
            "legacy_user": legacy_user,
            "matched_role_names": matched_names,
            "matched_role_ids": matched_ids,
        }

    return False, {
        "reason": "not_authorized",
        "legacy_user": legacy_user,
        "role_names": sorted(role_names),
        "role_ids": sorted(role_ids),
    }


def _audit_sensitive_attempt(request, *, operation: str, module: str, outcome: str, reason: str, detail: dict) -> None:
    payload = {
        "operation": operation,
        "outcome": outcome,
        "reason": reason,
        "method": request.method,
        "path": request.path,
        "user_id": getattr(getattr(request, "user", None), "id", None),
        "username": getattr(getattr(request, "user", None), "get_username", lambda: "")(),
        "legacy_user_id": getattr(getattr(request, "legacy_user", None), "id", None),
    }
    payload.update({key: value for key, value in detail.items() if key != "legacy_user"})

    try:
        log_action(request, SENSITIVE_AUDIT_ACTION, module, payload)
    except Exception:
        # TODO: quando l'audit DB diventera' vincolante, gestire qui un fallback persistente dedicato.
        logger.exception("admin sensitive audit db fallback")
    logger.info("admin_sensitive_operation_attempt %s", json.dumps(payload, sort_keys=True, default=str))


def _forbidden_response(request):
    if _is_json_request(request):
        return JsonResponse(
            {
                "ok": False,
                "error": "Operazione non autorizzata.",
                "reason": "forbidden",
            },
            status=403,
        )
    return render(request, "core/pages/forbidden.html", status=403)


def sensitive_admin_operation_required(
    operation: str,
    *,
    module: str = "admin_portale",
):
    """Protegge operazioni admin ad alto rischio e ne traccia il tentativo.

    La lista ruoli ammessi e' configurabile tramite:
    - ADMIN_PORTALE_SENSITIVE_ALLOWED_ROLE_NAMES
    - ADMIN_PORTALE_SENSITIVE_ALLOWED_ROLE_IDS
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                login_redirect = redirect_to_login(request.get_full_path())
                if _is_json_request(request):
                    return JsonResponse(
                        {
                            "ok": False,
                            "error": "Autenticazione richiesta.",
                            "reason": "unauthenticated",
                            "login_url": login_redirect.url,
                        },
                        status=401,
                    )
                return login_redirect

            allowed, detail = is_sensitive_admin_allowed(request)
            outcome = "allowed" if allowed else "denied"
            _audit_sensitive_attempt(
                request,
                operation=operation,
                module=module,
                outcome=outcome,
                reason=str(detail.get("reason") or ""),
                detail=detail,
            )
            if not allowed:
                return _forbidden_response(request)
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator
