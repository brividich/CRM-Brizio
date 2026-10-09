"""Connessioni LDAP del portale: TLS verificato e timeout di lettura.

SEC (audit A10/S7):
- con ``ldaps://`` il certificato del DC viene verificato (``CERT_REQUIRED``),
  usando ``LDAP_CA_CERT_FILE`` se indicato, altrimenti lo store di sistema;
- ogni ``Connection`` ha anche un ``receive_timeout``: un DC che accetta la
  connessione ma non risponde non blocca più un thread Waitress.
``ldap://`` resta possibile (password in chiaro sulla LAN) ma è segnalato da
``ldap_transport_is_insecure`` e dal controllo di deploy.
"""
from __future__ import annotations

from django.conf import settings


def ldap_receive_timeout() -> int:
    try:
        value = int(getattr(settings, "LDAP_RECEIVE_TIMEOUT", 0) or 0)
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        value = int(getattr(settings, "LDAP_TIMEOUT", 5) or 5) * 2
    return max(1, value)


def ldap_transport_is_insecure(server_url: str | None = None) -> bool:
    url = str(server_url if server_url is not None else getattr(settings, "LDAP_SERVER", "") or "").strip().lower()
    return bool(url) and not url.startswith("ldaps://")


def build_ldap_server(server_url: str, timeout: int):
    """``ldap3.Server`` con TLS verificato per ``ldaps://``."""
    from ldap3 import NONE, Server

    url = str(server_url or "").strip()
    if url.lower().startswith("ldaps://"):
        import ssl

        from ldap3 import Tls

        ca_file = str(getattr(settings, "LDAP_CA_CERT_FILE", "") or "").strip() or None
        tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=ca_file)
        return Server(url, use_ssl=True, tls=tls, connect_timeout=timeout, get_info=NONE)
    return Server(url, connect_timeout=timeout, get_info=NONE)
