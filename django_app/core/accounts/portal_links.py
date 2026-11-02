"""Link «Apri nel portale» per le mail interne, con accesso Windows automatico.

Il link punta all'indirizzo interno del portale (``SITE_URL``), mai a pagine
pubbliche a token. Se l'accesso Windows è attivo, passa da ``/login/windows/``:
sui PC del dominio il browser entra da solo con l'utente Windows e arriva alla
pagina indicata; altrove (telefono, PC fuori dominio) si apre il login normale
che riporta comunque alla pagina dopo l'accesso. Nella mail non c'è nessuna
credenziale: un inoltro non dà accesso a nessuno.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)


def site_url() -> str:
    return str(getattr(settings, "SITE_URL", "") or "").strip().rstrip("/")


def accesso_windows_attivo() -> bool:
    """Stessa regola del pulsante «Accedi con credenziali Windows» del login."""
    if not getattr(settings, "LDAP_ENABLED", False):
        return False
    try:
        from core.models import SiteConfig
        return SiteConfig.get_many({"login_sso_visibile": "1"})["login_sso_visibile"] == "1"
    except Exception:
        logger.warning("portal_links: impostazione login_sso_visibile non leggibile", exc_info=True)
        return False


def portal_link(path: str, *, base: str | None = None) -> str:
    """URL assoluto per aprire ``path`` nel portale; "" se ``SITE_URL`` manca."""
    base = (base if base is not None else site_url()).strip().rstrip("/")
    path = str(path or "").strip() or "/"
    if not base:
        return ""
    if not path.startswith("/") or path.startswith("//"):
        path = "/" + path.lstrip("/")
    if accesso_windows_attivo():
        return f"{base}{reverse('windows_sso')}?next={quote(path, safe='')}"
    return f"{base}{path}"
