"""Import dei saldi cedolini dal file XLSX pubblicato su SharePoint.

Il file è indicato da un **link di condivisione** SharePoint/OneDrive salvato in
``SiteConfig`` (chiave ``cedolini_sharepoint_url``): Graph lo risolve con
l'endpoint ``/shares/{id}/driveItem`` senza bisogno di conoscere sito, raccolta
o percorso. Il contenuto scaricato passa dallo stesso import del caricamento
manuale, quindi storico importazioni e upsert su (CF, mese) restano identici.

Usato dal pulsante "Importa da SharePoint" e dal task mensile
``anagrafica.tasks.run_import_cedolini_sharepoint``.
"""
from __future__ import annotations

import base64
import io
import logging
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

CONFIG_KEY = "cedolini_sharepoint_url"
CONFIG_DESCRIZIONE = "Link di condivisione SharePoint del file XLSX cedolini (import mensile ratei)"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
FILE_NOME_PREFIX = "SharePoint · "


def get_share_url() -> str:
    from core.models import SiteConfig

    return (SiteConfig.get(CONFIG_KEY, "") or "").strip()


def set_share_url(url: str) -> None:
    from core.models import SiteConfig

    SiteConfig.set(CONFIG_KEY, (url or "").strip(), CONFIG_DESCRIZIONE)


def encode_share_id(url: str) -> str:
    """Codifica un link di condivisione nel formato ``u!<base64url>`` di Graph."""
    encoded = base64.urlsafe_b64encode(url.strip().encode("utf-8")).decode("ascii")
    return "u!" + encoded.rstrip("=")


def _graph_headers() -> dict[str, str]:
    from config.env_config import get_first_env_value
    from core.graph_utils import acquire_graph_token, is_placeholder_value

    tenant_id = get_first_env_value("GRAPH_TENANT_ID", "AZURE_TENANT_ID")
    client_id = get_first_env_value("GRAPH_CLIENT_ID", "AZURE_CLIENT_ID")
    client_secret = get_first_env_value("GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET")
    if any(is_placeholder_value(v) for v in (tenant_id, client_id, client_secret)):
        raise ValueError("Credenziali Microsoft Graph non configurate sul server.")
    token = acquire_graph_token(tenant_id, client_id, client_secret)
    return {"Authorization": f"Bearer {token}"}


def _candidati(url: str) -> list[str]:
    """Il link così com'è e, se ha una query string (es. ``?e=xxx``), senza."""
    parts = urlsplit(url)
    candidati = [url]
    if parts.query:
        candidati.append(urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")))
    return candidati


def scarica_file(url: str, timeout: int = 60) -> tuple[bytes, str]:
    """Scarica il file indicato dal link di condivisione. Ritorna (contenuto, nome)."""
    import requests

    if not url:
        raise ValueError("Link SharePoint del file cedolini non configurato.")
    headers = _graph_headers()

    ultimo_errore = ""
    for candidato in _candidati(url):
        share_id = encode_share_id(candidato)
        meta = requests.get(
            f"{GRAPH_BASE}/shares/{share_id}/driveItem",
            headers={**headers, "Prefer": "redeemSharingLink"},
            timeout=timeout,
        )
        if not meta.ok:
            ultimo_errore = f"Graph {meta.status_code} sulla risoluzione del link"
            continue
        nome = (meta.json() or {}).get("name") or "cedolini.xlsx"
        contenuto = requests.get(
            f"{GRAPH_BASE}/shares/{share_id}/driveItem/content",
            headers=headers,
            timeout=timeout,
        )
        if not contenuto.ok:
            raise ValueError(f"Download del file da SharePoint fallito (Graph {contenuto.status_code}).")
        return contenuto.content, nome
    raise ValueError(
        f"Il link SharePoint non è accessibile dall'applicazione Graph del portale ({ultimo_errore})."
    )


def importa_da_sharepoint(user=None, url: str | None = None):
    """Scarica il file cedolini da SharePoint e lo importa. Ritorna l'ultima ImportazioneCedolini."""
    from anagrafica.views import _import_xlsx_cedolini

    url = (url if url is not None else get_share_url()).strip()
    contenuto, nome = scarica_file(url)
    return _import_xlsx_cedolini(io.BytesIO(contenuto), user, (FILE_NOME_PREFIX + nome)[:255])
