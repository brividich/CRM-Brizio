"""Riepilogo AI del giorno preparato di notte per chi lo usa.

Prima il brief si generava alla prima apertura della home: 20-25 s di Ollama per
persona, ogni mattina. Il cluster django-q lo prepara all'alba
(``tasks.run_daily_brief_notturno``) per chi lo ha aperto negli ultimi
``OLLAMA_DAILY_BRIEF_NOTTURNO_GIORNI`` giorni e lo mette nella stessa cache della
pagina: alla prima apertura è già pronto. Stessi dati e stessi permessi della persona
(richiesta costruita col suo utente); chi non è in elenco lo genera come prima.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)


def persone_recenti(giorni: int) -> list:
    """Utenti Django attivi che hanno aperto il brief negli ultimi ``giorni`` giorni."""
    from django.contrib.auth import get_user_model

    from core.models import AuditLog, Profile

    da = timezone.now() - timedelta(days=max(1, int(giorni)))
    legacy_ids = set(
        AuditLog.objects.filter(azione="ai_daily_brief", created_at__gte=da, legacy_user_id__isnull=False)
        .values_list("legacy_user_id", flat=True)
        .distinct()
    )
    if not legacy_ids:
        return []
    user_ids = set(Profile.objects.filter(legacy_user_id__in=legacy_ids).values_list("user_id", flat=True))
    return list(get_user_model().objects.filter(pk__in=user_ids, is_active=True).order_by("pk"))


def _richiesta_per(user):
    """Richiesta GET minima a nome della persona: i tool del brief leggono utente e permessi da qui."""
    from django.contrib.sessions.backends.signed_cookies import SessionStore
    from django.test import RequestFactory

    from core.legacy_utils import get_legacy_user

    # Host fra quelli ammessi: i tool che costruiscono link non devono incappare in DisallowedHost.
    host = next((h.lstrip(".") for h in getattr(settings, "ALLOWED_HOSTS", []) if h and h != "*"), "localhost")
    request = RequestFactory().get("/hub/home/", HTTP_HOST=host)
    request.user = user
    request.legacy_user = get_legacy_user(user)
    request.session = SessionStore()
    return request


def pregenera(giorni: int | None = None, limite: int | None = None) -> dict:
    """Prepara il brief di oggi per le persone recenti. Non solleva: riporta l'esito."""
    from core.acl_resolver import memo_permessi

    from .views import _seconds_until_end_of_day, daily_brief_cache_key, genera_daily_brief

    esito = {"persone": 0, "preparati": 0, "gia_pronti": 0, "errori": 0, "elapsed_ms": 0}
    if not bool(getattr(settings, "OLLAMA_DAILY_BRIEF_ENABLED", True)) or not bool(
        getattr(settings, "OLLAMA_CHAT_ENABLED", True)
    ):
        esito["saltato"] = "brief AI disattivato"
        return esito
    giorni = int(giorni or getattr(settings, "OLLAMA_DAILY_BRIEF_NOTTURNO_GIORNI", 14) or 14)
    limite = int(limite or getattr(settings, "OLLAMA_DAILY_BRIEF_NOTTURNO_MAX", 150) or 150)
    inizio = time.monotonic()
    persone = persone_recenti(giorni)[:limite]
    esito["persone"] = len(persone)
    for user in persone:
        chiave = daily_brief_cache_key(user.pk)
        try:
            if isinstance(cache.get(chiave), dict):
                esito["gia_pronti"] += 1
                continue
            with memo_permessi():
                dati, _info = genera_daily_brief(_richiesta_per(user))
            cache.set(chiave, dati, timeout=_seconds_until_end_of_day())
            esito["preparati"] += 1
        except Exception:
            esito["errori"] += 1
            logger.exception("Brief notturno non preparato per l'utente %s", user.pk)
    esito["elapsed_ms"] = int((time.monotonic() - inizio) * 1000)
    return esito
