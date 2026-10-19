"""Letture applicative da Microsoft Graph (Microsoft 365 Business Premium).

Un solo punto per credenziali, token e paginazione delle integrazioni in sola
lettura (account Entra, audit di Entra, e in seguito Intune, servizi, licenze).
Le credenziali sono quelle già usate dal portale (``GRAPH_TENANT_ID`` /
``GRAPH_CLIENT_ID`` / ``GRAPH_CLIENT_SECRET``), cercate nello stesso ordine
ovunque: impostazioni Django, variabili d'ambiente (il ``.env`` di produzione),
impostazioni del SOC.

Ogni chiamata dichiara il permesso che le serve: un 403 diventa un messaggio
che dice quale permesso aggiungere all'app in Entra.
"""
from __future__ import annotations

import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
# API di Microsoft Defender for Endpoint (inventario software, vulnerabilità): non è Graph,
# vuole un token con la sua risorsa e i permessi dell'app «WindowsDefenderATP».
DEFENDER_API = "https://api.securitycenter.microsoft.com/api"
_SCOPE_DEFENDER = "https://api.securitycenter.microsoft.com/.default"
_HOST_AMMESSI = ("https://graph.microsoft.com/", "https://api.securitycenter.microsoft.com/",
                 "https://api.security.microsoft.com/")
TIMEOUT = 30
MAX_PAGES = 50

_NOMI = {
    "tenant_id": ("GRAPH_TENANT_ID", "AZURE_TENANT_ID"),
    "client_id": ("GRAPH_CLIENT_ID", "AZURE_CLIENT_ID"),
    "client_secret": ("GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET"),
}


class GraphError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def _valore(nome: str) -> str:
    valore = str(getattr(settings, nome, "") or "").strip() or os.getenv(nome, "").strip()
    if valore:
        return valore
    try:
        from security.services.configuration import get_setting

        return str(get_setting(nome, "") or "").strip()
    except Exception:  # noqa: BLE001 - SOC non installato o DB non pronto
        return ""


def credenziali() -> dict[str, str]:
    out = {}
    for chiave, nomi in _NOMI.items():
        out[chiave] = next((v for v in (_valore(n) for n in nomi) if v), "")
    return out


def configurato() -> bool:
    from core.graph_utils import is_placeholder_value

    return all(v and not is_placeholder_value(v) for v in credenziali().values())


def token() -> str:
    from core.graph_utils import acquire_graph_token

    cfg = credenziali()
    if not configurato():
        raise GraphError("Credenziali Graph non configurate (GRAPH_TENANT_ID/CLIENT_ID/CLIENT_SECRET).")
    return acquire_graph_token(cfg["tenant_id"], cfg["client_id"], cfg["client_secret"])


def token_defender() -> str:
    """Token per l'API di Defender for Endpoint (cache in memoria fino a 5 minuti dalla scadenza)."""
    import time

    import msal

    cfg = credenziali()
    if not configurato():
        raise GraphError("Credenziali Graph non configurate (GRAPH_TENANT_ID/CLIENT_ID/CLIENT_SECRET).")
    chiave = (cfg["tenant_id"], cfg["client_id"])
    salvato = _TOKEN_DEFENDER.get(chiave)
    if salvato and salvato[1] - 300 > time.time():
        return salvato[0]
    app = msal.ConfidentialClientApplication(
        cfg["client_id"], authority=f"https://login.microsoftonline.com/{cfg['tenant_id']}",
        client_credential=cfg["client_secret"],
    )
    risultato = app.acquire_token_for_client(scopes=[_SCOPE_DEFENDER])
    tok = risultato.get("access_token")
    if not tok:
        raise GraphError(f"Token per Defender for Endpoint non ottenuto: {risultato.get('error') or 'errore'}.")
    _TOKEN_DEFENDER[chiave] = (tok, time.time() + int(risultato.get("expires_in", 3600)))
    return tok


_TOKEN_DEFENDER: dict = {}


def _token_per(url: str) -> str:
    return token() if url.startswith("https://graph.microsoft.com/") else token_defender()


def _invalida_token() -> None:
    try:
        from core.graph_utils import invalidate_graph_token_cache

        cfg = credenziali()
        invalidate_graph_token_cache(cfg["tenant_id"], cfg["client_id"], cfg["client_secret"])
    except Exception:  # noqa: BLE001
        pass


def get(url: str, *, permesso: str, params: dict | None = None, tok: str | None = None) -> dict:
    import requests

    if not url.startswith(_HOST_AMMESSI):
        raise GraphError("Indirizzo Graph non ammesso.")
    resp = requests.get(
        url, params=params, timeout=TIMEOUT,
        headers={"Authorization": f"Bearer {tok or _token_per(url)}", "Accept": "application/json"},
    )
    if resp.status_code in (401, 403):
        if url.startswith("https://graph.microsoft.com/"):
            _invalida_token()
        else:
            _TOKEN_DEFENDER.clear()
        raise GraphError(
            f"Graph ha risposto {resp.status_code}: manca il permesso «{permesso}» (applicazione, con consenso "
            "amministratore) sull'app del portale, oppure le credenziali non sono valide.",
            resp.status_code,
        )
    if resp.status_code >= 400:
        codice = ""
        try:
            codice = str((resp.json().get("error") or {}).get("code") or "")
        except Exception:  # noqa: BLE001
            pass
        raise GraphError(f"Graph ha risposto {resp.status_code} ({codice or 'errore'}).", resp.status_code)
    return resp.json()


def get_all(url: str, *, permesso: str, params: dict | None = None, max_pages: int = MAX_PAGES) -> list[dict]:
    """Tutte le pagine di una collezione (``value`` + ``@odata.nextLink``)."""
    tok = _token_per(url)
    out: list[dict] = []
    for _ in range(max_pages):
        data = get(url, permesso=permesso, params=params, tok=tok)
        out.extend(v for v in data.get("value") or [] if isinstance(v, dict))
        url = data.get("@odata.nextLink") or ""
        params = None  # il nextLink contiene già filtro e paginazione
        if not url:
            break
    return out
