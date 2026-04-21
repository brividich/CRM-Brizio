from __future__ import annotations

from functools import wraps

from django.http import JsonResponse
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import render

from core.legacy_utils import get_legacy_user, is_legacy_admin


LEGACY_ADMIN_BYPASS_ATTR = "_legacy_admin_bypass"


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


def is_legacy_admin_bypass_view(view_func) -> bool:
    return bool(getattr(view_func, LEGACY_ADMIN_BYPASS_ATTR, False))


def legacy_admin_required(view_func):
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

        legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
        request.legacy_user = legacy_user

        if bool(getattr(request.user, "is_superuser", False)):
            return view_func(request, *args, **kwargs)

        if legacy_user and is_legacy_admin(legacy_user):
            return view_func(request, *args, **kwargs)

        if _is_json_request(request):
            return JsonResponse(
                {
                    "ok": False,
                    "error": "Permessi insufficienti.",
                    "reason": "forbidden",
                },
                status=403,
            )
        return render(request, "core/pages/forbidden.html", status=403)

    setattr(_wrapped, LEGACY_ADMIN_BYPASS_ATTR, True)
    return _wrapped
