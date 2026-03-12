from __future__ import annotations

import base64
import logging
import uuid

from django.conf import settings
from django.contrib.auth import login
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from core.legacy_utils import provision_legacy_user, sync_django_user_from_legacy

logger = logging.getLogger(__name__)

# Cache in-process dei contesti SPNEGO in corso (NTLM è multi-step).
# Chiave: ctx_id (uuid), Valore: oggetto spnego context.
# Vengono rimossi al completamento o alla scadenza implicita (max 60s).
_SPNEGO_CONTEXTS: dict[str, object] = {}


def _normalize_principal(principal: str) -> str:
    """Normalizza un principal Windows in UPN minuscolo (es. DOMAIN\\user → user@domain)."""
    upn = principal.lower()
    if "\\" in upn:
        domain, username = upn.split("\\", 1)
        upn = f"{username}@{domain}"
    return upn


@csrf_exempt
def windows_sso_view(request):
    """
    View per il login SSO con credenziali Windows (NTLM/Kerberos via SPNEGO).

    Flusso:
      1. GET senza Authorization  → 401 + WWW-Authenticate: Negotiate
      2. Browser rimanda con token SPNEGO (Kerberos: 1 step; NTLM: 2 step)
      3. Autenticazione completata → login e redirect
    """
    if not getattr(settings, "LDAP_ENABLED", False):
        messages.error(request, "SSO Windows non abilitato (LDAP_ENABLED=0).")
        return redirect("login")

    try:
        import spnego
    except ImportError:
        messages.error(request, "Modulo pyspnego non installato.")
        return redirect("login")

    next_url = request.GET.get("next") or reverse("dashboard_home")
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")

    if not auth_header:
        # Passo 1: sfida il browser
        ctx_id = str(uuid.uuid4())
        _SPNEGO_CONTEXTS[ctx_id] = spnego.server(protocol="negotiate")
        response = HttpResponse(status=401)
        response["WWW-Authenticate"] = "Negotiate"
        response.set_cookie("_sso_ctx", ctx_id, max_age=60, httponly=True, samesite="Lax")
        return response

    scheme, _, token_b64 = auth_header.partition(" ")
    if scheme.lower() not in ("negotiate", "ntlm"):
        messages.error(request, "Schema di autenticazione non supportato.")
        return redirect("login")

    ctx_id = request.COOKIES.get("_sso_ctx", "")
    ctx = _SPNEGO_CONTEXTS.get(ctx_id)
    if ctx is None:
        # Contesto scaduto o mancante: ricomincia
        ctx = spnego.server(protocol="negotiate")

    try:
        in_token = base64.b64decode(token_b64)
        out_token = ctx.step(in_token)
    except Exception as exc:
        logger.warning("Windows SSO: SPNEGO step fallito: %s", exc)
        _SPNEGO_CONTEXTS.pop(ctx_id, None)
        messages.error(request, "Autenticazione Windows fallita. Riprova.")
        return redirect("login")

    if not ctx.complete:
        # NTLM richiede un altro round: invia il challenge
        response = HttpResponse(status=401)
        challenge_b64 = base64.b64encode(out_token).decode() if out_token else ""
        response["WWW-Authenticate"] = f"Negotiate {challenge_b64}"
        return response

    # Autenticazione completata
    _SPNEGO_CONTEXTS.pop(ctx_id, None)

    principal = getattr(ctx, "client_principal", None) or ""
    if not principal:
        logger.warning("Windows SSO: principal vuoto dopo autenticazione")
        messages.error(request, "Impossibile determinare l'utente Windows. Riprova.")
        return redirect("login")

    logger.info("Windows SSO: autenticato %s", principal)

    legacy_user = provision_legacy_user(_normalize_principal(principal))
    if legacy_user is None:
        messages.error(request, f"Utente {principal} non autorizzato o disabilitato.")
        return redirect("login")

    django_user = sync_django_user_from_legacy(legacy_user)
    if django_user is None:
        messages.error(request, "Errore sincronizzazione utente. Contatta l'amministratore.")
        return redirect("login")

    login(request, django_user, backend="core.accounts.backends.LDAPBackend")
    response = redirect(next_url)
    response.delete_cookie("_sso_ctx")
    return response
