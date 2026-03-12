"""
core/graph_utils.py — Utility condivise per Azure Graph API.

Centralizza l'acquisizione del token MSAL e la cache thread-safe,
evitando duplicazione tra i moduli assenze e anomalie.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from threading import Lock

logger = logging.getLogger(__name__)

# Cache condivisa tra tutti i moduli (stesse credenziali Azure)
_TOKEN_LOCK = Lock()
_TOKEN_CACHE: dict = {"token": None, "expires_at": None}

# Anticipo di scadenza: rinnova il token 60s prima della scadenza effettiva
_TOKEN_BUFFER_SECONDS = 60


def acquire_graph_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    """Acquisisce o restituisce il token Azure Graph dalla cache (thread-safe).

    Raises:
        RuntimeError: se msal non è disponibile o il token non viene ottenuto.
    """
    try:
        import msal  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(f"Libreria msal non disponibile: {exc}") from exc

    with _TOKEN_LOCK:
        now = datetime.now(dt_timezone.utc)
        cached = _TOKEN_CACHE.get("token")
        exp = _TOKEN_CACHE.get("expires_at")
        if cached and isinstance(exp, datetime) and now < exp:
            return str(cached)

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
        buffer = max(_TOKEN_BUFFER_SECONDS, ttl - _TOKEN_BUFFER_SECONDS)
        _TOKEN_CACHE["token"] = token
        _TOKEN_CACHE["expires_at"] = datetime.now(dt_timezone.utc) + timedelta(seconds=buffer)
        logger.debug("Token Graph rinnovato, scade in %ds (buffer %ds)", ttl, buffer)
        return str(token)


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
