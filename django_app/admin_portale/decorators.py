from __future__ import annotations

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.shortcuts import render

from core.legacy_utils import get_legacy_user, is_legacy_admin


def legacy_admin_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())

        legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
        request.legacy_user = legacy_user

        if legacy_user and is_legacy_admin(legacy_user):
            return view_func(request, *args, **kwargs)

        return render(request, "core/pages/forbidden.html", status=403)

    return _wrapped
