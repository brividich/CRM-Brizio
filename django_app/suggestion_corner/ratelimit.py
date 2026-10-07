"""Rate limiting cache-based per il form pubblico (§5, Δ3).

Nessuna dipendenza esterna (django-ratelimit non installato): si usa la cache
già configurata (DatabaseCache in prod, LocMem in dev). Fail-open in caso di
errore cache — meglio accettare una segnalazione in più che perderla.

Due limiti: per IP (5 invii / 10 minuti) e globale (50 invii / ora). Il globale
regge anche se l'IP venisse falsificato: protegge il team SMS dalle valanghe di mail.
L'IP arriva da ``core.net.client_ip`` (X-Forwarded-For solo da proxy fidati).
"""
from __future__ import annotations

from django.core.cache import cache

# Limiti di default: 5 invii per finestra di 10 minuti per IP.
DEFAULT_LIMIT = 5
DEFAULT_WINDOW = 600
GLOBAL_LIMIT = 50
GLOBAL_WINDOW = 3600


def client_ip(request) -> str:
    from core.net import client_ip as _client_ip

    return _client_ip(request) or "unknown"


def _hit(key: str, limit: int, window: int) -> bool:
    """Incrementa il contatore (atomico) e dice se il limite e' superato."""
    cache.add(key, 0, timeout=window)
    try:
        count = cache.incr(key)
    except ValueError:  # chiave scaduta fra add e incr
        cache.set(key, 1, timeout=window)
        count = 1
    return count > limit


_LOOPBACK = {"127.0.0.1", "::1", "unknown"}


def is_rate_limited(request, *, limit: int = DEFAULT_LIMIT, window: int = DEFAULT_WINDOW) -> bool:
    """True se l'IP ha superato `limit` invii nella finestra `window`, o il limite globale.

    Dietro IIS senza ``TRUSTED_PROXY_IPS`` ogni richiesta arriva da 127.0.0.1: un
    limite per IP diventerebbe un limite unico per tutta l'azienda. In quel caso
    vale solo il limite globale.
    """
    try:
        ip = client_ip(request)
        if ip not in _LOOPBACK and _hit(f"sc_pub_rl:{ip}", limit, window):
            return True
        return _hit("sc_pub_rl:__global__", GLOBAL_LIMIT, GLOBAL_WINDOW)
    except Exception:
        return False  # fail-open
