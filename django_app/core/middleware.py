from __future__ import annotations

from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect, render
from django.urls import reverse

from core.impersonation import is_impersonation_stop_path, resolve_impersonation_context
from core.acl import check_permesso
from core.legacy_utils import get_legacy_user, legacy_auth_enabled

API_ACL_GATE_PATHS = {
    "/api/anomalie/": "/gestione-anomalie",
}


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
        for prefix, gate_path in API_ACL_GATE_PATHS.items():
            if path.startswith(prefix) and legacy_user and check_permesso(legacy_user, gate_path):
                return self.get_response(request)
        if legacy_user and check_permesso(legacy_user, path):
            return self.get_response(request)

        return render(
            request,
            "core/pages/forbidden.html",
            {"page_title": "Accesso negato"},
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
