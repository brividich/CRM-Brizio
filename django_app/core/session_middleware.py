from __future__ import annotations

import time
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse


class SessionIdleTimeoutMiddleware:
    SESSION_KEY = "_last_activity_ts"
    DEFAULT_ACTIVITY_WRITE_THROTTLE_SECONDS = 30

    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt_prefixes = getattr(settings, "MIDDLEWARE_EXEMPT_PREFIXES", ())
        self.activity_throttle = max(0, int(
            getattr(settings, "SESSION_ACTIVITY_WRITE_THROTTLE_SECONDS",
                    self.DEFAULT_ACTIVITY_WRITE_THROTTLE_SECONDS) or 0
        ))

    def _should_write_activity(self, request, now_ts: int) -> bool:
        """True se il timestamp di attività va riscritto, rispettando il throttle.

        Riscrivere a OGNI richiesta marca la sessione come modificata e ne forza
        il ``save()`` nel ``SessionMiddleware``: sotto concorrenza (es. una
        richiesta lenta che termina dopo un logout/cycle_key concorrente) questo
        amplifica la race ``SessionInterrupted`` e aggiunge carico DB inutile.
        Con il throttle si riscrive solo quando il valore precedente manca o è
        più vecchio di ``activity_throttle`` secondi: il timeout di inattività
        può quindi scattare al più con ``activity_throttle`` secondi di anticipo
        sul valore reale — direzione *fail-safe* (mai oltre il timeout),
        trascurabile rispetto a un timeout di minuti/ore.
        """
        if self.activity_throttle <= 0:
            return True
        prev = request.session.get(self.SESSION_KEY)
        try:
            prev_ts = int(prev)
        except (TypeError, ValueError):
            return True
        return (now_ts - prev_ts) >= self.activity_throttle

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

        now_ts = int(time.time())
        should_refresh_activity = request.user.is_authenticated and not is_exempt
        login_post_succeeded = is_login_post and request.user.is_authenticated
        if login_post_succeeded:
            # Sul login riuscito ancoriamo sempre il timestamp (mai throttle).
            request.session[self.SESSION_KEY] = now_ts
        elif should_refresh_activity and self._should_write_activity(request, now_ts):
            request.session[self.SESSION_KEY] = now_ts
        return response
