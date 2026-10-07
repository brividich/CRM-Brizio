"""Redirect di ritorno (``next``/``back``) senza open redirect.

``startswith("/")`` non basta: ``/\\evil.example`` viene normalizzato dai browser
in ``//evil.example``. Si usa il controllo di Django sull'host della richiesta.
"""
from __future__ import annotations

from django.utils.http import url_has_allowed_host_and_scheme


def safe_next(request, candidate: str | None, fallback: str) -> str:
    url = str(candidate or "").strip()
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return fallback
