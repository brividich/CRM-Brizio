from __future__ import annotations

import logging
from functools import lru_cache
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from core.impersonation import is_impersonation_stop_path, resolve_impersonation_context
from core.acl_v2 import resolve_acl_access
from core.legacy_utils import get_legacy_user, legacy_auth_enabled

API_ACL_GATE_PATHS = {
    "/api/anomalie/": "/gestione-anomalie",
}
_ACL_MIDDLEWARE_LOG_TTL_SECONDS = 300
logger = logging.getLogger(__name__)

_ACL_ONBOARDING_SHARED_ROUTE_NAMES = (
    "onboarding_wizard",
    "notifiche",
    "api_onboarding_email_save",
)
_ACL_ONBOARDING_SHARED_PREFIXES = (
    "/api/notifiche/",
)
_ACL_SHARED_ROUTE_NAMES = _ACL_ONBOARDING_SHARED_ROUTE_NAMES + (
    "root",
    "profilo",
    "gestione_reparto",
    "rubrica",
    "organigramma",
    "ui_prefs_page",
    "ui_prefs_api_save",
    "ui_sidebar_save",
    "api_global_search",
    "stop_impersonation",
    "employee_board",
    "api_employee_board_layout",
    "api_employee_board_widget_config",
    "api_employee_board_reset",
    "api_employee_board_admin_template",
    "api_employee_board_data",
    "employee_board_pdf",
    "api_debug_ui_meta",
    "assets:api_dashboard_save_config",
    "legacy_modifica_capo",
    "legacy_modifica_info_completa",
    "legacy_flask_check",
)
_ACL_SHARED_PREFIXES = _ACL_ONBOARDING_SHARED_PREFIXES + (
    "/api/onboarding/",
    "/api/gestione-reparto/",
    "/api/employee-board/widget/",
    "/gestione_utenti/modifica/",
    "/diario-preposto/allegato/",
)


def _normalize_acl_runtime_path(path: str) -> str:
    value = str(path or "/").split("?", 1)[0].strip()
    if not value:
        return "/"
    if not value.startswith("/"):
        value = "/" + value
    if value != "/":
        value = value.rstrip("/")
    return value or "/"


def _path_matches_prefixes(path: str, prefixes: tuple[str, ...]) -> bool:
    path_norm = _normalize_acl_runtime_path(path)
    for prefix in prefixes:
        prefix_norm = _normalize_acl_runtime_path(prefix)
        if prefix_norm == "/":
            return True
        if path_norm == prefix_norm or path_norm.startswith(prefix_norm + "/"):
            return True
    return False


def _route_names_to_paths(route_names: tuple[str, ...]) -> frozenset[str]:
    paths: set[str] = set()
    for route_name in route_names:
        try:
            path = reverse(route_name)
        except Exception:
            continue
        paths.add(_normalize_acl_runtime_path(path))
    return frozenset(paths)


def is_acl_exempt_path(path: str, prefixes: tuple[str, ...] | None = None) -> bool:
    configured_prefixes = prefixes if prefixes is not None else tuple(getattr(settings, "MIDDLEWARE_EXEMPT_PREFIXES", ()))
    return _path_matches_prefixes(path, tuple(configured_prefixes))


def is_acl_onboarding_shared_path(path: str) -> bool:
    path_norm = _normalize_acl_runtime_path(path)
    if path_norm in _route_names_to_paths(_ACL_ONBOARDING_SHARED_ROUTE_NAMES):
        return True
    return _path_matches_prefixes(path_norm, _ACL_ONBOARDING_SHARED_PREFIXES)


def is_acl_shared_path(path: str) -> bool:
    path_norm = _normalize_acl_runtime_path(path)
    if path_norm in _route_names_to_paths(_ACL_SHARED_ROUTE_NAMES):
        return True
    return _path_matches_prefixes(path_norm, _ACL_SHARED_PREFIXES)


def resolve_acl_gate_target_path(path: str) -> str:
    path_norm = _normalize_acl_runtime_path(path)
    for prefix, mapped_path in API_ACL_GATE_PATHS.items():
        if _path_matches_prefixes(path_norm, (prefix,)):
            return _normalize_acl_runtime_path(mapped_path)
    return path_norm


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


def _log_acl_once(level: str, cache_key: str, message: str, **extra) -> None:
    throttle_key = f"acl_middleware:log:{level}:{cache_key}"
    try:
        if not cache.add(throttle_key, 1, timeout=_ACL_MIDDLEWARE_LOG_TTL_SECONDS):
            return
    except Exception:
        pass
    log_fn = getattr(logger, level, logger.info)
    log_fn(message, extra=extra)


class AdaptiveSecureCookieMiddleware:
    """Downgrade CSRF/session cookies on plain HTTP when HTTPS is not in use."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.csrf_cookie_name = getattr(settings, "CSRF_COOKIE_NAME", "csrftoken")
        self.session_cookie_name = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")

    def __call__(self, request):
        response = self.get_response(request)
        if request.is_secure():
            return response

        for cookie_name in (self.csrf_cookie_name, self.session_cookie_name):
            morsel = response.cookies.get(cookie_name)
            if morsel is not None:
                morsel["secure"] = ""
        return response


class ACLMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt_prefixes = getattr(settings, "MIDDLEWARE_EXEMPT_PREFIXES", ())

    def __call__(self, request):
        path = request.path or "/"
        onboarding_path = reverse("onboarding_wizard")
        is_onboarding_shared_path = is_acl_onboarding_shared_path(path)
        is_shared_acl_path = is_acl_shared_path(path)
        if is_acl_exempt_path(path, self.exempt_prefixes):
            return self.get_response(request)

        if not request.user.is_authenticated:
            login_url = reverse("login")
            query = urlencode({"next": request.get_full_path()})
            target = f"{login_url}?{query}"
            if _is_json_request(request):
                return JsonResponse(
                    {
                        "ok": False,
                        "error": "Autenticazione richiesta.",
                        "reason": "unauthenticated",
                        "login_url": target,
                    },
                    status=401,
                )
            return redirect(target)

        if getattr(request, "impersonation_active", False) and is_impersonation_stop_path(path):
            return self.get_response(request)

        # Onboarding wizard: reindirizza l'utente se non ha ancora completato il wizard
        # (solo utenti non-superuser; /onboarding/ stesso è sempre permesso)
        if not getattr(request.user, "is_superuser", False) and not is_onboarding_shared_path:
            try:
                from core.models import UserOnboarding
                onboarding = UserOnboarding.objects.filter(user=request.user).first()
                if onboarding is None or not onboarding.is_done():
                    if _is_json_request(request):
                        return JsonResponse(
                            {"ok": False, "reason": "onboarding_required", "redirect": onboarding_path},
                            status=403,
                        )
                    return redirect(onboarding_path)
            except Exception:
                pass  # non bloccare l'accesso in caso di errore DB

        if not legacy_auth_enabled():
            return self.get_response(request)

        if getattr(request.user, "is_superuser", False):
            return self.get_response(request)

        if is_shared_acl_path:
            return self.get_response(request)

        legacy_user = get_legacy_user(request.user)
        request.legacy_user = legacy_user
        request.acl_decision = None

        gate_target = resolve_acl_gate_target_path(path)

        decision = resolve_acl_access(
            path=gate_target,
            legacy_user=legacy_user,
            django_user=request.user,
            request=request,
            include_legacy_diagnostic=True,
        )
        request.acl_decision = decision

        # Governance migrazione ACL v2: osserva e/o blocca il fallback legacy.
        # Vedi settings ACL_STRICT_CANONICAL e ACL_LOG_LEGACY_FALLBACK.
        if decision.get("decision_source") == "legacy_fallback":
            path_norm = decision.get("path_normalized")
            route_name = decision.get("route_name") or ""
            if getattr(settings, "ACL_LOG_LEGACY_FALLBACK", True):
                _log_acl_once(
                    level="info" if decision.get("allowed") else "warning",
                    cache_key=f"fallback:{'allow' if decision.get('allowed') else 'deny'}:{path_norm}",
                    message=(
                        "ACL legacy fallback in uso: la route non ha un "
                        "RoutePermissionBinding canonico."
                    ),
                    path=path_norm,
                    route_name=route_name,
                    allowed=bool(decision.get("allowed")),
                    user_id=getattr(getattr(request, "user", None), "id", None),
                    legacy_user_id=(decision.get("legacy_user") or {}).get("id"),
                )
            if getattr(settings, "ACL_STRICT_CANONICAL", False) and bool(decision.get("allowed")):
                # In strict-mode neghiamo anche se il fallback legacy consentirebbe:
                # forziamo la migrazione delle route residue a binding canonico.
                decision["allowed"] = False
                decision["decision_source"] = "legacy_fallback_denied_by_strict"
                decision["decision_kind"] = "deny"
                decision["reason"] = (
                    "ACL_STRICT_CANONICAL attivo: route senza RoutePermissionBinding "
                    "canonico — creane uno in /admin-portale/acl-canonico/."
                )
                _log_acl_once(
                    level="warning",
                    cache_key=f"strict_deny:{path_norm}",
                    message="ACL strict: deny su route in fallback legacy.",
                    path=path_norm,
                    route_name=route_name,
                )

        if bool(decision.get("allowed", False)):
            return self.get_response(request)

        legacy_diag = decision.get("legacy_fallback") or {}
        reason_code = str(legacy_diag.get("reason_code") or "").strip().lower()
        if decision.get("decision_source") == "legacy_fallback" and reason_code == "no_pulsante_match":
            _log_acl_once(
                level="warning",
                cache_key=f"no_pulsante:{decision.get('path_normalized')}",
                message="ACL deny: path protetto senza binding canonico e senza pulsante legacy matchato.",
                path=decision.get("path_normalized"),
                route_name=decision.get("route_name"),
                user_id=getattr(getattr(request, "user", None), "id", None),
                legacy_user_id=(decision.get("legacy_user") or {}).get("id"),
                decision_source=decision.get("decision_source"),
                decision_reason=decision.get("reason"),
            )
        elif decision.get("decision_source") == "legacy_fallback" and reason_code == "db_error":
            _log_acl_once(
                level="warning",
                cache_key=f"db_error:{decision.get('path_normalized')}",
                message="ACL deny: errore DB durante fallback legacy ACL.",
                path=decision.get("path_normalized"),
                route_name=decision.get("route_name"),
                user_id=getattr(getattr(request, "user", None), "id", None),
                legacy_user_id=(decision.get("legacy_user") or {}).get("id"),
                db_error=legacy_diag.get("db_error"),
                decision_source=decision.get("decision_source"),
                decision_reason=decision.get("reason"),
            )

        if _is_json_request(request):
            return JsonResponse(
                {
                    "ok": False,
                    "error": "Permessi insufficienti.",
                    "reason": "forbidden",
                },
                status=403,
            )

        return render(
            request,
            "core/pages/forbidden.html",
            {"page_title": "Accesso negato", "acl_decision": decision},
            status=403,
        )


class ImpersonationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.impersonation_active = False
        request.impersonation_state = {}
        request.impersonator_user = None
        request.impersonator_legacy_user = None
        request.impersonated_user = None
        request.impersonated_legacy_user = None

        context = resolve_impersonation_context(request, authenticated_user=getattr(request, "user", None))
        if context:
            request.impersonation_active = True
            request.impersonation_state = context["state"]
            request.impersonator_user = context["original_user"]
            request.impersonator_legacy_user = context["original_legacy_user"]
            request.impersonated_user = context["target_user"]
            request.impersonated_legacy_user = context["target_legacy_user"]
            request.user = context["target_user"]
            request.legacy_user = context["target_legacy_user"]

        return self.get_response(request)
