"""
core/graph_utils.py — Utility condivise per Azure Graph API.

Centralizza l'acquisizione del token MSAL. La cache è condivisa tra i worker
IIS tramite il backend Django `cache` (in prod: DatabaseCache su SQL Server).
In dev con LocMemCache la cache è per-processo ma comunque thread-safe grazie
al lock in-process aggiuntivo.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from threading import Lock

from django.core.cache import cache

logger = logging.getLogger(__name__)

# Lock in-process: evita doppia acquisizione dallo stesso worker quando più
# thread chiedono il token contemporaneamente. La sincronizzazione tra worker
# diversi è garantita dal backend cache condiviso (DatabaseCache in prod).
_TOKEN_LOCK = Lock()

# Anticipo di scadenza: rinnova il token 60s prima della scadenza effettiva.
_TOKEN_BUFFER_SECONDS = 60

# Prefisso chiave cache: include un digest delle credenziali per isolare tenant
# diversi senza mai scrivere il client_secret in chiaro nella cache.
_CACHE_KEY_PREFIX = "graph:token:"


def _cache_key(tenant_id: str, client_id: str, client_secret: str) -> str:
    digest = hashlib.sha256(
        f"{tenant_id}|{client_id}|{client_secret}".encode("utf-8")
    ).hexdigest()[:32]
    return f"{_CACHE_KEY_PREFIX}{digest}"


def acquire_graph_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    """Acquisisce o restituisce il token Azure Graph dalla cache condivisa.

    Raises:
        RuntimeError: se msal non è disponibile o il token non viene ottenuto.
    """
    try:
        import msal  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(f"Libreria msal non disponibile: {exc}") from exc

    key = _cache_key(tenant_id, client_id, client_secret)

    # Fast path: lettura senza lock, cache hit più comune a regime.
    cached = cache.get(key)
    if cached and isinstance(cached, str):
        return cached

    # Slow path: serializza l'acquisizione nel worker corrente per evitare
    # storm di richieste MSAL quando la cache è fredda. Gli altri worker
    # vedranno il token subito dopo grazie al backend condiviso.
    with _TOKEN_LOCK:
        cached = cache.get(key)
        if cached and isinstance(cached, str):
            return cached

        app = msal.ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=client_secret,
        )
        result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        token = result.get("access_token")
        if not token:
            raise RuntimeError(f"Token Graph non ottenuto: {result}")

        ttl = int(result.get("expires_in", 3600))
        # Scade in cache prima della scadenza reale, per garantire rinnovo
        # proattivo senza mai servire un token scaduto.
        cache_ttl = max(60, ttl - _TOKEN_BUFFER_SECONDS)
        try:
            cache.set(key, str(token), cache_ttl)
        except Exception as exc:  # pragma: no cover — fallback difensivo
            logger.warning("Impossibile scrivere token Graph in cache: %s", exc)
        logger.debug("Token Graph rinnovato, scade in %ds (cache %ds)", ttl, cache_ttl)
        return str(token)


def invalidate_graph_token_cache(tenant_id: str, client_id: str, client_secret: str) -> None:
    """Invalida il token cached, utile se il backend ha restituito 401/403."""
    try:
        cache.delete(_cache_key(tenant_id, client_id, client_secret))
    except Exception as exc:  # pragma: no cover
        logger.warning("Impossibile invalidare cache token Graph: %s", exc)


def is_placeholder_value(value: str) -> bool:
    """Restituisce True se il valore è vuoto o un placeholder non configurato."""
    text = str(value or "").strip()
    if not text:
        return True
    lower = text.lower()
    return (
        (lower.startswith("<") and lower.endswith(">"))
        or "change_me" in lower
        or lower in {"your_tenant", "your_client_id", "your_client_secret"}
    )
