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
    try:
        return acquire_graph_token(cfg["tenant_id"], cfg["client_id"], cfg["client_secret"])
    except RuntimeError as exc:  # token non ottenuto: i chiamanti gestiscono solo GraphError
        raise GraphError(str(exc)) from exc


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
        client_credential=cfg["client_secret"], timeout=(5, 20),
    )
    risultato = app.acquire_token_for_client(scopes=[_SCOPE_DEFENDER])
    tok = risultato.get("access_token")
    if not tok:
        from core.graph_utils import descrivi_errore_token

        raise GraphError(f"Token per Defender for Endpoint non ottenuto: {descrivi_errore_token(risultato)}.")
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


class ElencoGraph(list):
    """Elenco letto da Graph/Defender. ``troncata`` è vero se dopo ``max_pages`` restava un
    ``@odata.nextLink``: l'elenco è parziale e chi cancella o segna gli assenti deve fermarsi."""

    troncata: bool = False
    prossimo_link: str = ""


# Una sessione per processo: riusa le connessioni TLS verso Graph/Defender invece di aprirne
# una a chiamata. Sono servizi internet: il proxy di sistema (HTTPS_PROXY) resta valido.
_SESSION = None
RETRY_STATI = (429, 503, 504)
RETRY_MAX = 3
RETRY_ATTESA_MAX = 10.0


def _sessione():
    global _SESSION
    if _SESSION is None:
        import requests

        _SESSION = requests.Session()
    return _SESSION


def _servizio(url: str) -> str:
    """Chi risponde, per i messaggi: Graph oppure l'API di Defender for Endpoint (che non è Graph)."""
    return "Graph" if str(url).startswith("https://graph.microsoft.com/") else "L'API di Defender for Endpoint"


def _host(url: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(str(url)).netloc or str(url)[:60]


def _chi_risponde(resp, url: str) -> str:
    """Se a rispondere non è il servizio Microsoft (proxy, pagina HTML), lo dice: Graph risponde in JSON."""
    headers = getattr(resp, "headers", None)
    if not hasattr(headers, "get"):
        return ""
    tipo = str(headers.get("Content-Type") or "")
    server = str(headers.get("Server") or "")[:60]
    if not tipo or "json" in tipo.lower():
        return ""
    return (f" La risposta non arriva da {_host(url)}"
            + (f" (server «{server}»)" if server else "")
            + ": risponde un proxy o un altro servizio.")


def _codice_errore(resp) -> str:
    try:
        errore = resp.json().get("error")
    except Exception:  # noqa: BLE001 - corpo non JSON
        return ""
    if isinstance(errore, dict):
        return str(errore.get("code") or "")[:80]
    return str(errore or "")[:80]


def _attesa_retry(resp, tentativo: int) -> float:
    headers = getattr(resp, "headers", None)
    valore = str(headers.get("Retry-After") or "").strip() if hasattr(headers, "get") else ""
    try:
        attesa = float(valore) if valore else float(2 ** tentativo)
    except ValueError:
        attesa = float(2 ** tentativo)
    return max(0.0, min(attesa, RETRY_ATTESA_MAX))


def _dormi(secondi: float) -> None:
    import time

    time.sleep(secondi)


def _errore_http(resp, url: str, permesso: str) -> GraphError:
    """Messaggio per una risposta 4xx/5xx: 401 = token, 403 = permesso, gli altri con il codice di errore."""
    servizio = _servizio(url)
    codice = _codice_errore(resp)
    dettaglio = f" (codice «{codice}»)" if codice else ""
    stato = resp.status_code
    if stato == 401:
        testo = (f"{servizio} ha risposto 401{dettaglio}: token non accettato. Controlla il segreto dell'app "
                 "(scaduto o sbagliato), l'ID tenant/app e l'orologio del server.")
    elif stato == 403:
        testo = (f"{servizio} ha risposto 403{dettaglio}: manca il permesso «{permesso}» (applicazione, con "
                 "consenso amministratore) sull'app del portale.")
    else:
        testo = f"{servizio} ha risposto {stato}{dettaglio or ' (errore)'}."
    return GraphError(testo + _chi_risponde(resp, url), stato)


def get(url: str, *, permesso: str, params: dict | None = None, tok: str | None = None) -> dict:
    import requests

    if not url.startswith(_HOST_AMMESSI):
        raise GraphError("Indirizzo Graph non ammesso.")
    headers = {"Authorization": f"Bearer {tok or _token_per(url)}", "Accept": "application/json"}
    for tentativo in range(RETRY_MAX + 1):
        try:
            resp = _sessione().get(url, params=params, timeout=TIMEOUT, headers=headers)
        except requests.RequestException as exc:
            raise GraphError(f"{_host(url)} non raggiungibile ({type(exc).__name__}).") from exc
        if resp.status_code in RETRY_STATI and tentativo < RETRY_MAX:
            _dormi(_attesa_retry(resp, tentativo))
            continue
        break
    if resp.status_code in (401, 403):
        if url.startswith("https://graph.microsoft.com/"):
            _invalida_token()
        else:
            _TOKEN_DEFENDER.clear()
    if resp.status_code >= 400:
        raise _errore_http(resp, url, permesso)
    try:
        return resp.json()
    except ValueError as exc:
        raise GraphError(f"{_host(url)} ha risposto {resp.status_code} senza JSON leggibile."
                         + _chi_risponde(resp, url), resp.status_code) from exc


def get_all(url: str, *, permesso: str, params: dict | None = None, max_pages: int = MAX_PAGES) -> ElencoGraph:
    """Tutte le pagine di una collezione (``value`` + ``@odata.nextLink``).

    Se dopo ``max_pages`` resta un ``@odata.nextLink`` l'elenco è parziale: ``troncata`` è vero e
    ``prossimo_link`` dice da dove riprendere. Chi cancella o segna gli assenti deve controllarlo
    (``troncata(elenco)``) e saltare la parte distruttiva.
    """
    tok = _token_per(url)
    out = ElencoGraph()
    for _ in range(max_pages):
        data = get(url, permesso=permesso, params=params, tok=tok)
        out.extend(v for v in data.get("value") or [] if isinstance(v, dict))
        url = data.get("@odata.nextLink") or ""
        params = None  # il nextLink contiene già filtro e paginazione
        if not url:
            break
    if url:
        out.troncata = True
        out.prossimo_link = url
        logger.warning("Lettura troncata dopo %s pagine (%s righe) da %s", max_pages, len(out), _host(url))
    return out


def troncata(elenco) -> bool:
    """Vero se l'elenco viene da ``get_all`` ed è parziale (una lista qualunque vale come completa)."""
    return bool(getattr(elenco, "troncata", False))


def scrivi(metodo: str, url: str, *, permesso: str, json: dict | None = None) -> tuple[int, dict]:
    """POST/PATCH/DELETE su Graph. Ritorna ``(stato HTTP, corpo)``; 404 non è un errore
    (l'oggetto non c'è più: lo decide il chiamante), 401/403 e gli altri 4xx/5xx sì."""
    import requests

    if not url.startswith("https://graph.microsoft.com/"):
        raise GraphError("Indirizzo Graph non ammesso.")
    headers = {"Authorization": f"Bearer {token()}", "Accept": "application/json"}
    for tentativo in range(RETRY_MAX + 1):
        try:
            resp = _sessione().request(metodo, url, json=json, timeout=TIMEOUT, headers=headers)
        except requests.RequestException as exc:
            raise GraphError(f"{_host(url)} non raggiungibile ({type(exc).__name__}).") from exc
        # Solo 429 si ripete: la richiesta non è stata eseguita (con 503/504 una scrittura potrebbe esserlo).
        if resp.status_code == 429 and tentativo < RETRY_MAX:
            _dormi(_attesa_retry(resp, tentativo))
            continue
        break
    if resp.status_code in (401, 403):
        _invalida_token()
    if resp.status_code == 404:
        return 404, {}
    if resp.status_code >= 400:
        raise _errore_http(resp, url, permesso)
    try:
        return resp.status_code, (resp.json() if resp.content else {})
    except ValueError:
        return resp.status_code, {}
