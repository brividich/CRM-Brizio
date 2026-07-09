"""Rate limiting cache-based per il form pubblico (§5, Δ3).

Nessuna dipendenza esterna (django-ratelimit non installato): si usa la cache
già configurata (DatabaseCache in prod, LocMem in dev). Fail-open in caso di
errore cache — meglio accettare una segnalazione in più che perderla.
"""
from __future__ import annotations

from django.core.cache import cache

# Limiti di default: 5 invii per finestra di 10 minuti per IP.
DEFAULT_LIMIT = 5
DEFAULT_WINDOW = 600


def client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def is_rate_limited(request, *, limit: int = DEFAULT_LIMIT, window: int = DEFAULT_WINDOW) -> bool:
    """True se l'IP ha superato `limit` invii nella finestra `window` (secondi)."""
    ip = client_ip(request)
    key = f"sc_pub_rl:{ip}"
    try:
        count = cache.get(key, 0)
        if count >= limit:
            return True
        cache.set(key, count + 1, timeout=window)
        return False
    except Exception:
        return False  # fail-open
