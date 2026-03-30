from __future__ import annotations

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
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
        if any(path.startswith(prefix) for prefix in self.exempt_prefixes):
            return self.get_response(request)

        if not request.user.is_authenticated:
            login_url = reverse("login")
            query = urlencode({"next": request.get_full_path()})
            return redirect(f"{login_url}?{query}")

        if getattr(request, "impersonation_active", False) and is_impersonation_stop_path(path):
            return self.get_response(request)

        if not legacy_auth_enabled():
            return self.get_response(request)

        if getattr(request.user, "is_superuser", False):
            return self.get_response(request)

        legacy_user = get_legacy_user(request.user)
        request.legacy_user = legacy_user
        request.acl_decision = None

        gate_target = path
        for prefix, mapped_path in API_ACL_GATE_PATHS.items():
            if path.startswith(prefix):
                gate_target = mapped_path
                break

        decision = resolve_acl_access(
            path=gate_target,
            legacy_user=legacy_user,
            django_user=request.user,
            request=request,
            include_legacy_diagnostic=True,
        )
        request.acl_decision = decision
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
