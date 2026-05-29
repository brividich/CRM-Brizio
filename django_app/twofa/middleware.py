"""Middleware 2FA: blocca sessioni autenticate non ancora verificate."""
from __future__ import annotations

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse


_TWOFA_EXEMPT = ("/2fa/", "/login", "/logout", "/static/", "/media/", "/favicon")


def _is_exempt(path: str) -> bool:
    exempt = tuple(_TWOFA_EXEMPT) + tuple(getattr(settings, "MIDDLEWARE_EXEMPT_PREFIXES", ()))
    return any(path.startswith(p) for p in exempt)


def _is_non_navigation(request) -> bool:
    """True per richieste HTMX, SSE, JSON API o qualsiasi richiesta non-navigazione browser."""
    if getattr(request, "htmx", None):
        return True
    accept = request.META.get("HTTP_ACCEPT", "")
    if "text/html" not in accept and "application/json" in accept:
        return True
    # Polling / EventSource (notifiche live, SSE)
    if request.META.get("HTTP_ACCEPT") == "text/event-stream":
        return True
    # Prefissi API interni
    path = request.path_info
    api_prefixes = ("/api/", "/admin-portale/api/")
    if any(path.startswith(p) for p in api_prefixes):
        return True
    return False


class TwoFactorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.user.is_authenticated
            and not _is_exempt(request.path_info)
            and request.session.get("twofa_pending")
        ):
            from twofa.utils import is_2fa_verified, should_require_2fa

            if should_require_2fa(request, request.user) and not is_2fa_verified(request):
                verify_url = reverse("twofa:verify")
                if not request.path_info.startswith(verify_url):
                    if _is_non_navigation(request):
                        return JsonResponse(
                            {"ok": False, "error": "2fa_required", "redirect": verify_url},
                            status=403,
                        )
                    return redirect(verify_url)

        return self.get_response(request)
