from __future__ import annotations

from django.conf import settings
from django.middleware.csrf import get_token


class EnsureCSRFCookieMiddleware:
    """Pre-generate CSRF cookie for interactive HTML pages.

    Some views post via JS and read `csrftoken` from cookies without rendering
    `{% csrf_token %}` in the template body. Seeding the token here avoids
    intermittent "CSRF cookie not set" errors.
    """

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

    def __init__(self, get_response):
        self.get_response = get_response
        self.static_url = str(getattr(settings, "STATIC_URL", "/static/") or "/static/")
        self.media_url = str(getattr(settings, "MEDIA_URL", "/media/") or "/media/")

    def __call__(self, request):
        if self._should_seed_cookie(request):
            get_token(request)
        return self.get_response(request)

    def _should_seed_cookie(self, request) -> bool:
        if request.method not in self.SAFE_METHODS:
            return False

        path = request.path or "/"
        if path.startswith(self.static_url) or path.startswith(self.media_url):
            return False

        accept = request.headers.get("Accept", "")
        if not accept:
            return True
        return "text/html" in accept or "*/*" in accept
