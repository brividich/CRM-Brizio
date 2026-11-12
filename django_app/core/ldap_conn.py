"""Connessioni LDAP del portale: TLS verificato, timeout, server condivisi e breaker.

SEC (audit A10/S7):
- con ``ldaps://`` il certificato del DC viene verificato (``CERT_REQUIRED``),
  usando ``LDAP_CA_CERT_FILE`` se indicato, altrimenti lo store di sistema;
- con ``LDAP_START_TLS=1`` (di serie spenta) le connessioni ``ldap://`` passano a
  TLS con ``start_tls()`` prima del bind, con la stessa verifica del certificato;
- ogni ``Connection`` ha anche un ``receive_timeout``: un DC che accetta la
  connessione ma non risponde non blocca più un thread Waitress.
``ldap://`` senza StartTLS resta possibile (password in chiaro sulla LAN) ma è
segnalato da ``ldap_transport_is_insecure`` e dal controllo di deploy.

Affidabilità:
- ``get_ldap_server`` restituisce un ``ServerPool`` creato una volta per processo
  (strategia FIRST, controllo dei server attivi, un DC giù resta escluso 60 s);
  ``LDAP_SERVER`` può elencare più DC separati da virgola o spazio;
- ``ldap_bind`` è il ciclo di bind unico: se il DC non si raggiunge interrompe i
  tentativi, solleva ``LDAPUnreachable`` e arma un breaker in cache
  («AD non raggiungibile») che fa saltare subito il login LDAP per
  ``LDAP_BREAKER_SECONDS`` secondi invece di pagare i timeout a ogni login;
- ``ldap_paged_search`` legge tutte le pagine e segnala una lettura incompleta.
"""
from __future__ import annotations

import importlib
import logging
import os
import re
import socket
import threading

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

LDAP_BREAKER_KEY = "core:ldap:ad_non_raggiungibile"
LDAP_BREAKER_SECONDS = 45
LDAP_POOL_EXHAUST_SECONDS = 60

MESSAGGIO_STRONGER_AUTH = (
    "Il domain controller richiede la firma/cifratura LDAP (strongerAuthRequired): "
    "usa ldaps:// in LDAP_SERVER oppure attiva LDAP_START_TLS=1."
)

_TRUE_VALUES = {"1", "true", "yes", "on", "si", "sì"}
_SERVER_CACHE: dict[tuple, object] = {}
_SERVER_LOCK = threading.Lock()
_AD_SUBCODE_RE = re.compile(r"\bdata\s+([0-9a-f]{3,4})\b", re.IGNORECASE)


class LDAPUnreachable(OSError):
    """Il domain controller non risponde (rete, porta chiusa, timeout)."""


class LDAPIncompleteRead(RuntimeError):
    """Una ricerca paginata non è arrivata in fondo: i dati letti sono parziali."""


def ldap_receive_timeout() -> int:
    try:
        value = int(getattr(settings, "LDAP_RECEIVE_TIMEOUT", 0) or 0)
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        value = int(getattr(settings, "LDAP_TIMEOUT", 5) or 5) * 2
    return max(1, value)


def ldap_start_tls_enabled() -> bool:
    """``LDAP_START_TLS`` dai settings, altrimenti dall'ambiente (.env). Di serie spenta."""
    value = getattr(settings, "LDAP_START_TLS", None)
    if value is None:
        value = os.environ.get("LDAP_START_TLS", "")
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in _TRUE_VALUES


def ldap_server_urls(server_url: str | None = None) -> list[str]:
    raw = str(server_url if server_url is not None else getattr(settings, "LDAP_SERVER", "") or "")
    return [part for part in re.split(r"[\s,;]+", raw.strip()) if part]


def ldap_transport_is_insecure(server_url: str | None = None) -> bool:
    urls = [u.lower() for u in ldap_server_urls(server_url)]
    if not urls:
        return False
    if ldap_start_tls_enabled():
        return False
    return any(not u.startswith("ldaps://") for u in urls)


def _tls_verificato():
    import ssl

    from ldap3 import Tls

    ca_file = str(getattr(settings, "LDAP_CA_CERT_FILE", "") or "").strip() or None
    return Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=ca_file)


def build_ldap_server(server_url: str, timeout: int):
    """``ldap3.Server`` con TLS verificato per ``ldaps://`` (e per StartTLS se attivo)."""
    from ldap3 import NONE, Server

    url = str(server_url or "").strip()
    if url.lower().startswith("ldaps://"):
        return Server(url, use_ssl=True, tls=_tls_verificato(), connect_timeout=timeout, get_info=NONE)
    if ldap_start_tls_enabled():
        # Senza un Tls esplicito start_tls() di ldap3 non verificherebbe il certificato.
        return Server(url, tls=_tls_verificato(), connect_timeout=timeout, get_info=NONE)
    return Server(url, connect_timeout=timeout, get_info=NONE)


def get_ldap_server(server_url: str | None = None, timeout: int | None = None):
    """Server/pool LDAP condiviso dal processo (un oggetto per configurazione).

    ``ServerPool`` FIRST con controllo dei server attivi: un DC che non risponde resta
    escluso per ``LDAP_POOL_EXHAUST_SECONDS`` e si passa al successivo. ``active=1``
    (un solo giro) e non ``True``: con ``True`` ldap3 riprova all'infinito quando
    tutti i DC sono giù, bloccando il thread.
    """
    urls = ldap_server_urls(server_url)
    if not urls:
        raise ValueError("LDAP_SERVER non configurato")
    timeout = int(timeout if timeout is not None else (getattr(settings, "LDAP_TIMEOUT", 5) or 5))
    key = (
        tuple(urls),
        timeout,
        ldap_start_tls_enabled(),
        str(getattr(settings, "LDAP_CA_CERT_FILE", "") or "").strip(),
    )
    cached = _SERVER_CACHE.get(key)
    if cached is not None:
        return cached
    with _SERVER_LOCK:
        cached = _SERVER_CACHE.get(key)
        if cached is not None:
            return cached
        servers = [build_ldap_server(url, timeout) for url in urls]
        try:
            from ldap3 import FIRST, ServerPool, set_config_parameter

            # Fra un giro e l'altro del pool ldap3 dorme POOLING_LOOP_TIMEOUT (10 s):
            # con un solo giro quell'attesa è solo tempo perso prima dell'errore.
            set_config_parameter("POOLING_LOOP_TIMEOUT", 0)
            server = ServerPool(servers, FIRST, active=1, exhaust=LDAP_POOL_EXHAUST_SECONDS)
        except (ImportError, AttributeError):
            server = servers[0]
        _SERVER_CACHE[key] = server
        return server


def reset_ldap_servers() -> None:
    with _SERVER_LOCK:
        _SERVER_CACHE.clear()


# --- breaker «AD non raggiungibile» -------------------------------------------------

def ldap_breaker_open() -> bool:
    try:
        return bool(cache.get(LDAP_BREAKER_KEY))
    except Exception:  # noqa: BLE001 - la cache non deve mai bloccare il login
        return False


def ldap_breaker_trip(reason: str = "") -> None:
    logger.warning(
        "LDAP: Active Directory non raggiungibile (%s): login LDAP sospeso per %s s",
        reason or "nessun dettaglio",
        LDAP_BREAKER_SECONDS,
    )
    try:
        cache.set(LDAP_BREAKER_KEY, 1, LDAP_BREAKER_SECONDS)
    except Exception:  # noqa: BLE001
        logger.debug("LDAP: impossibile armare il breaker in cache", exc_info=True)


def ldap_breaker_reset() -> None:
    try:
        cache.delete(LDAP_BREAKER_KEY)
    except Exception:  # noqa: BLE001
        pass


# --- esiti del bind ----------------------------------------------------------------

def ldap_result_description(result) -> str:
    if isinstance(result, dict):
        return str(result.get("description") or "").strip()
    return ""


def ad_bind_subcode(result) -> str:
    """Codice AD del bind fallito (``data 52e`` = password errata, ``525`` = utente inesistente...)."""
    message = str(result.get("message") or "") if isinstance(result, dict) else str(result or "")
    match = _AD_SUBCODE_RE.search(message)
    return match.group(1).lower() if match else ""


def describe_bind_failure(result) -> str:
    if ldap_result_description(result) == "strongerAuthRequired":
        return f"Bind LDAP fallito: {MESSAGGIO_STRONGER_AUTH}"
    return f"Bind LDAP fallito: {result}"


def _exceptions():
    """Eccezioni ldap3 per categoria (tollerante verso moduli finti nei test)."""
    mod = importlib.import_module("ldap3.core.exceptions")
    names = ("LDAPSocketOpenError", "LDAPServerPoolExhaustedError", "LDAPSocketReceiveError", "LDAPSessionTerminatedByServerError")
    unreachable = tuple(getattr(mod, n) for n in names if isinstance(getattr(mod, n, None), type))
    start_tls = getattr(mod, "LDAPStartTLSError", None)
    base = getattr(mod, "LDAPException", Exception)
    return unreachable + (socket.timeout, ConnectionError), start_tls if isinstance(start_tls, type) else None, base


def service_bind_attempts(user: str, *, domain: str = "", upn_suffix: str = "") -> list[tuple[str, object]]:
    """Tentativi di bind per l'account di servizio (UPN, nome semplice, DOMINIO\\nome)."""
    from ldap3 import NTLM, SIMPLE

    user = str(user or "").strip()
    if "\\" in user:
        return [(user, NTLM)]
    if "@" in user:
        return [(user, SIMPLE)]
    attempts: list[tuple[str, object]] = []
    suffix = str(upn_suffix or "").strip().lstrip("@")
    if suffix:
        attempts.append((f"{user}@{suffix}", SIMPLE))
    attempts.append((user, SIMPLE))
    if domain:
        attempts.append((f"{domain}\\{user}", NTLM))
    return attempts


def _chiudi(conn) -> None:
    if conn is None:
        return
    try:
        conn.unbind()
    except Exception:  # noqa: BLE001
        logger.debug("LDAP: unbind fallito", exc_info=True)


def ldap_bind(
    attempts,
    password: str,
    *,
    server=None,
    server_url: str | None = None,
    timeout: int | None = None,
    read_only: bool = False,
    should_continue=None,
):
    """Ciclo di bind unico. Restituisce ``(connessione, ultimo_result)``; connessione ``None`` se nessun bind riesce.

    - DC non raggiungibile ⇒ chiude, arma il breaker e solleva ``LDAPUnreachable``
      (i tentativi successivi pagherebbero lo stesso timeout);
    - ``should_continue(utente, metodo, result)`` decide se dopo un bind rifiutato si
      prova il metodo successivo (di serie sì);
    - con ``LDAP_START_TLS`` attivo apre la connessione e fa ``start_tls()`` prima del bind;
    - ogni connessione di un bind fallito viene chiusa (``unbind``).
    """
    from ldap3 import Connection

    unreachable_exc, start_tls_exc, base_exc = _exceptions()
    if server is None:
        server = get_ldap_server(server_url, timeout)
    use_start_tls = ldap_start_tls_enabled() and not all(
        u.lower().startswith("ldaps://") for u in ldap_server_urls(server_url)
    )
    last_result = None
    for bind_user, authentication in attempts:
        conn = None
        try:
            kwargs = dict(
                user=bind_user,
                password=password,
                authentication=authentication,
                auto_bind=False,
                auto_referrals=False,
                raise_exceptions=False,
                receive_timeout=ldap_receive_timeout(),
            )
            if read_only:
                kwargs["read_only"] = True
            conn = Connection(server, **kwargs)
            if use_start_tls:
                conn.open()
                if not conn.start_tls(read_server_info=False):
                    last_result = getattr(conn, "result", None)
                    logger.error("LDAP: StartTLS non riuscito (%s): bind annullato", last_result)
                    _chiudi(conn)
                    return None, last_result
            ok = conn.bind()
        except unreachable_exc as exc:
            _chiudi(conn)
            ldap_breaker_trip(f"{type(exc).__name__}: {exc}")
            raise LDAPUnreachable(str(exc) or type(exc).__name__) from exc
        except OSError as exc:
            _chiudi(conn)
            ldap_breaker_trip(f"{type(exc).__name__}: {exc}")
            raise LDAPUnreachable(str(exc) or type(exc).__name__) from exc
        except Exception as exc:  # noqa: BLE001 - un bind fallito non deve mai diventare un 500
            _chiudi(conn)
            if start_tls_exc is not None and isinstance(exc, start_tls_exc):
                logger.error("LDAP: StartTLS fallito, certificato del DC non verificato: %s", exc)
                return None, {"description": "startTLSFailed", "message": str(exc)}
            if not isinstance(exc, base_exc):
                logger.warning("LDAP: bind di %s (%s) fallito con errore inatteso: %s", bind_user, authentication, exc)
            else:
                logger.warning("LDAP: bind di %s (%s) fallito: %s", bind_user, authentication, exc)
            last_result = None
            if should_continue is not None and not should_continue(bind_user, authentication, None):
                break
            continue
        if ok:
            return conn, getattr(conn, "result", None)
        last_result = getattr(conn, "result", None)
        _chiudi(conn)
        if ldap_result_description(last_result) == "strongerAuthRequired":
            logger.warning("LDAP: bind di %s rifiutato. %s", bind_user, MESSAGGIO_STRONGER_AUTH)
        if should_continue is not None and not should_continue(bind_user, authentication, last_result):
            break
    return None, last_result


def ldap_service_bind(*, server_url: str | None = None, timeout: int | None = None, user: str | None = None,
                      password: str | None = None, domain: str | None = None, upn_suffix: str | None = None,
                      read_only: bool = False):
    """Bind con l'account di servizio configurato (o con i valori passati)."""
    user = str(user if user is not None else getattr(settings, "LDAP_SERVICE_USER", "") or "").strip()
    password = str(password if password is not None else getattr(settings, "LDAP_SERVICE_PASSWORD", "") or "").strip()
    domain = str(domain if domain is not None else getattr(settings, "LDAP_DOMAIN", "") or "").strip()
    upn_suffix = str(upn_suffix if upn_suffix is not None else getattr(settings, "LDAP_UPN_SUFFIX", "") or "")
    return ldap_bind(
        service_bind_attempts(user, domain=domain, upn_suffix=upn_suffix),
        password,
        server_url=server_url,
        timeout=timeout,
        read_only=read_only,
    )


def ldap_paged_search(conn, *, search_base: str, search_filter: str, attributes, paged_size: int = 500,
                      search_scope=None) -> list[dict]:
    """Tutte le pagine di una ricerca: lista di dict ``{"dn", "attributes"}``.

    Con ``raise_exceptions=False`` ldap3 smette in silenzio di produrre risultati se una
    pagina fallisce: qui l'esito dell'ultima pagina viene controllato e una lettura
    incompleta solleva ``LDAPIncompleteRead`` (mai dati parziali presentati come completi).
    """
    if search_scope is None:
        from ldap3 import SUBTREE

        search_scope = SUBTREE
    rows = []
    for item in conn.extend.standard.paged_search(
        search_base=search_base,
        search_filter=search_filter,
        search_scope=search_scope,
        attributes=attributes,
        paged_size=int(paged_size or 500),
        generator=True,
    ):
        if isinstance(item, dict) and item.get("type") == "searchResEntry":
            rows.append({"dn": item.get("dn") or "", "attributes": dict(item.get("attributes") or {})})
    result = getattr(conn, "result", None)
    code = result.get("result") if isinstance(result, dict) else None
    if code != 0:
        raise LDAPIncompleteRead(result if isinstance(result, dict) else {"description": str(result)})
    return rows
