from __future__ import annotations

import time
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse


class SessionIdleTimeoutMiddleware:
    SESSION_KEY = "_last_activity_ts"

    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt_prefixes = getattr(settings, "MIDDLEWARE_EXEMPT_PREFIXES", ())

    def __call__(self, request):
        path = request.path or "/"
        timeout_seconds = int(getattr(settings, "SESSION_IDLE_TIMEOUT_SECONDS", 0) or 0)
        is_exempt = any(path.startswith(prefix) for prefix in self.exempt_prefixes)
        is_login_post = path.startswith("/login") and request.method == "POST"

        if timeout_seconds > 0 and request.user.is_authenticated and not is_exempt:
            now_ts = int(time.time())
            last_activity = request.session.get(self.SESSION_KEY)
            if last_activity is not None:
                try:
                    idle_for = now_ts - int(last_activity)
                except (TypeError, ValueError):
                    idle_for = 0
                if idle_for > timeout_seconds:
                    logout(request)
                    login_url = reverse("login")
                    query = urlencode({"reason": "expired", "next": request.get_full_path()})
                    return redirect(f"{login_url}?{query}")
        response = self.get_response(request)

        should_refresh_activity = request.user.is_authenticated and not is_exempt
        login_post_succeeded = is_login_post and request.user.is_authenticated
        if should_refresh_activity or login_post_succeeded:
            request.session[self.SESSION_KEY] = int(time.time())
        return response
