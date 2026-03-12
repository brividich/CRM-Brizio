from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import redirect
from django.urls import reverse

from core.legacy_utils import get_legacy_user

logger = logging.getLogger(__name__)

_PENDING_CACHE_PREFIX = "notizie:pending_mandatory:user:"
_PENDING_CACHE_TTL = 60  # secondi


def _pending_cache_key(legacy_user_id: int) -> str:
    return f"{_PENDING_CACHE_PREFIX}{legacy_user_id}"


def _has_pending_mandatory(legacy_user_id: int, force_check: bool = False) -> bool:
    """Verifica se l'utente ha notizie obbligatorie non confermate.

    Usa cache con TTL di 60s. `force_check=True` bypassa la cache.
    """
    if not force_check:
        cached = cache.get(_pending_cache_key(legacy_user_id))
        if cached is not None:
            return bool(cached)

    try:
        from notizie.models import (
            COMPLIANCE_CONFORME,
            STATO_PUBBLICATA,
            Notizia,
            get_compliance_status,
            is_visible_to_user,
        )
        from core.models import Profile

        try:
            profile = Profile.objects.filter(legacy_user_id=legacy_user_id).first()
        except Exception:
            return False

        role_id = profile.legacy_ruolo_id if profile else None

        has_pending = False
        for notizia in Notizia.objects.filter(stato=STATO_PUBBLICATA, obbligatoria=True):
            if not is_visible_to_user(notizia, role_id):
                continue
            if get_compliance_status(notizia, legacy_user_id) != COMPLIANCE_CONFORME:
                has_pending = True
                break
    except Exception as exc:
        logger.debug("notizie mandatory check error: %s", exc)
        return False

    cache.set(_pending_cache_key(legacy_user_id), has_pending, timeout=_PENDING_CACHE_TTL)
    return has_pending


def invalidate_pending_mandatory_cache(legacy_user_id: int) -> None:
    """Invalida la cache after una conferma di lettura."""
    cache.delete(_pending_cache_key(legacy_user_id))


class NotizieMandatoryMiddleware:
    """Blocca l'accesso al portale se l'utente ha notizie obbligatorie non confermate.

    Posizionato dopo ACLMiddleware nel stack.
    Tutta l'app /notizie/ è safe (altrimenti l'utente non potrebbe confermare).
    """

    SAFE_PATHS_EXTRA = ("/notizie/",)

    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt_prefixes = getattr(settings, "MIDDLEWARE_EXEMPT_PREFIXES", ())

    def __call__(self, request):
        if not getattr(request.user, "is_authenticated", False):
            return self.get_response(request)

        path = request.path or "/"
        all_safe = self.exempt_prefixes + self.SAFE_PATHS_EXTRA
        if any(path.startswith(p) for p in all_safe):
            return self.get_response(request)

        legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
        if legacy_user is not None:
            try:
                if _has_pending_mandatory(int(legacy_user.id)):
                    return redirect(reverse("notizie_obbligatorie"))
            except Exception as exc:
                logger.debug("NotizieMandatoryMiddleware check failed: %s", exc)

        return self.get_response(request)
