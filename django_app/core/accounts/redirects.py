from __future__ import annotations

from django.utils.http import url_has_allowed_host_and_scheme


def get_safe_redirect_target(request, candidate_url: str | None) -> str | None:
    """Restituisce il target solo se relativo o sullo stesso host della request."""
    target = (candidate_url or "").strip()
    if not target:
        return None
    try:
        allowed_hosts = {request.get_host()}
    except Exception:
        return None
    if url_has_allowed_host_and_scheme(
        target,
        allowed_hosts=allowed_hosts,
        require_https=request.is_secure(),
    ):
        return target
    return None
