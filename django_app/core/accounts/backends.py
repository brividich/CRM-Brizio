from __future__ import annotations

import hashlib
import logging
import socket

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connections
from werkzeug.security import check_password_hash

from core.ldap_conn import (
    LDAPUnreachable,
    ad_bind_subcode,
    get_ldap_server,
    ldap_bind,
    ldap_breaker_open,
    ldap_result_description,
    ldap_service_bind,
)
from core.legacy_models import UtenteLegacy
from core.legacy_utils import (
    canonicalize_ldap_upn,
    extract_identity_alias,
    legacy_auth_enabled,
    ldap_login_group_allowed,
    provision_legacy_user,
    resolve_ldap_identity,
    sync_django_user_from_legacy,
)

logger = logging.getLogger(__name__)


def _md4_supported() -> bool:
    try:
        hashlib.new("md4")
    except Exception:
        return False
    return True


def _extract_alias(ident: str) -> str:
    return extract_identity_alias(ident)


def _resolve_legacy_user_by_alias(alias: str):
    """Risoluzione offline: alias -> UtenteLegacy via email local-part o anagrafica_dipendenti."""
    if not alias:
        return None
    try:
        by_local = UtenteLegacy.objects.filter(email__istartswith=f"{alias}@").order_by("id").first()
        if by_local:
            return by_local
    except DatabaseError:
        return None

    try:
        with connections["default"].cursor() as cursor:
            vendor = connections["default"].vendor
            if vendor == "sqlite":
                cursor.execute(
                    """
                    SELECT email
                    FROM anagrafica_dipendenti
                    WHERE UPPER(COALESCE(aliasusername,'')) = UPPER(?)
                      AND COALESCE(email,'') <> ''
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    [alias],
                )
            else:
                cursor.execute(
                    """
                    SELECT TOP 1 email
                    FROM anagrafica_dipendenti
                    WHERE UPPER(COALESCE(aliasusername,'')) = UPPER(%s)
                      AND COALESCE(email,'') <> ''
                    ORDER BY id DESC
                    """,
                    [alias],
                )
            row = cursor.fetchone()
            if row and row[0]:
                return UtenteLegacy.objects.filter(email__iexact=str(row[0]).strip()).first()
    except DatabaseError:
        return None
    return None


class SQLServerLegacyBackend:
    def authenticate(self, request, username=None, password=None, **kwargs):
        ident = (username or kwargs.get("email") or "").strip()
        password = (password or "").strip()
        if not legacy_auth_enabled() or not ident or not password:
            return None

        try:
            # 1) Match diretto email
            legacy_user = UtenteLegacy.objects.filter(email__iexact=ident).first()
            # 2) Match tramite alias username (supporta alias, dominio\alias, alias@dominio)
            if not legacy_user:
                alias = _extract_alias(ident)
                legacy_user = _resolve_legacy_user_by_alias(alias)
            # 3) Fallback storico per compatibilita'
            if not legacy_user:
                legacy_user = UtenteLegacy.objects.filter(nome__iexact=ident).first()
        except DatabaseError as exc:
            logger.warning("Legacy auth query failed: %s", exc)
            return None

        if not legacy_user:
            return None
        if not bool(legacy_user.attivo):
            return None

        legacy_pwd = (legacy_user.password or "").strip()
        if legacy_pwd == "*AD_MANAGED*":
            return None

        try:
            if not check_password_hash(legacy_pwd, password):
                return None
        except Exception as exc:
            logger.warning("Legacy hash verification failed for user_id=%s: %s", legacy_user.id, exc)
            return None

        return sync_django_user_from_legacy(legacy_user)

    def get_user(self, user_id):
        User = get_user_model()
        try:
            user = User.objects.filter(pk=user_id).first()
        except Exception:
            return None
        # SEC (audit M4): un utente disattivato perde subito le sessioni aperte.
        if user is not None and not user.is_active:
            return None
        return user


def _account_ad_esiste(bind_user: str) -> bool | None:
    """L'account del bind esiste in AD? ``None`` = non verificabile (manca l'account di servizio o errore)."""
    search_base = str(getattr(settings, "LDAP_BASE_DN", "") or "").strip()
    if not search_base or not getattr(settings, "LDAP_SERVICE_USER", "") or not getattr(settings, "LDAP_SERVICE_PASSWORD", ""):
        return None
    try:
        from ldap3.utils.conv import escape_filter_chars

        if "@" in bind_user:
            filtro = f"(userPrincipalName={escape_filter_chars(bind_user)})"
        else:
            filtro = f"(sAMAccountName={escape_filter_chars(bind_user.split(chr(92))[-1])})"
        conn, _result = ldap_service_bind(read_only=True)
        if conn is None:
            return None
        try:
            ok = conn.search(search_base=search_base, search_filter=filtro, attributes=["sAMAccountName"], size_limit=1)
            if not ok and ldap_result_description(conn.result) not in ("", "success"):
                return None
            return bool(conn.entries)
        finally:
            try:
                conn.unbind()
            except Exception:
                logger.debug("LDAP: unbind fallito", exc_info=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("LDAP: verifica esistenza account non riuscita: %s", exc)
        return None


def _prosegui_dopo_bind_rifiutato(bind_user: str, _authentication, result) -> bool:
    """Dopo un bind rifiutato si prova il metodo successivo solo se non conta come altra password errata.

    AD conta ogni bind con password sbagliata: UPN e poi DOMINIO\\alias facevano due
    tentativi falliti a ogni errore di battitura (blocco account a metà soglia).
    - ``strongerAuthRequired`` o utente inesistente (``525``) ⇒ si prova il successivo;
    - ``invalidCredentials`` ``52e`` ⇒ ci si ferma, salvo che l'account usato nel bind
      non esista in AD (UPN diverso da alias@suffisso): allora si prova il successivo;
    - altri codici AD (bloccato, scaduto, disabilitato...) ⇒ ci si ferma.
    """
    description = ldap_result_description(result)
    if description != "invalidCredentials":
        return True
    code = ad_bind_subcode(result)
    if not code or code == "525":
        return True
    if code == "52e":
        if "@" not in bind_user and "\\" not in bind_user:
            # Bind SIMPLE con il solo alias: forma non sempre accettata da AD, esito non affidabile.
            return True
        return _account_ad_esiste(bind_user) is False
    return False


class LDAPBackend:
    def authenticate(self, request, username=None, password=None, **kwargs):
        ident = (username or "").strip()
        password = (password or "").strip()
        if not legacy_auth_enabled() or not getattr(settings, "LDAP_ENABLED", False):
            return None
        if not ident or not password:
            return None

        try:
            from ldap3 import NTLM, SIMPLE
            from ldap3.core.exceptions import LDAPException
        except Exception as exc:
            logger.warning("ldap3 unavailable: %s", exc)
            return None

        server_url = getattr(settings, "LDAP_SERVER", "") or ""
        domain = getattr(settings, "LDAP_DOMAIN", "") or ""
        upn_suffix = getattr(settings, "LDAP_UPN_SUFFIX", "") or ""
        timeout = int(getattr(settings, "LDAP_TIMEOUT", 5) or 5)
        if not server_url:
            return None

        if ldap_breaker_open():
            # Il DC non rispondeva pochi secondi fa: niente timeout a ogni login.
            # Il form mostra il messaggio generico; qui resta traccia del motivo vero.
            logger.warning(
                "LDAP: login di %s non verificato su AD: servizio di autenticazione non raggiungibile (breaker attivo)",
                _extract_alias(ident),
            )
            return None

        alias = _extract_alias(ident)
        if "@" in ident:
            upn = canonicalize_ldap_upn(alias, ident.lower())
            bind_dn = ident.lower()
        else:
            suffix = upn_suffix.lstrip("@") if upn_suffix else ""
            bind_dn = f"{alias}@{suffix}" if suffix else alias
            upn = canonicalize_ldap_upn(alias, bind_dn)

        resolved_upn = upn
        resolved_full_name = ""

        try:
            server = get_ldap_server(server_url, timeout)
            supports_ntlm = _md4_supported()
            if "\\" in ident:
                if supports_ntlm:
                    attempts = [(ident, NTLM)]
                else:
                    attempts = [(bind_dn, SIMPLE)]
                    if bind_dn != alias:
                        attempts.append((alias, SIMPLE))
            elif "@" in ident:
                attempts = [(bind_dn, SIMPLE)]
            else:
                attempts = [(bind_dn, SIMPLE)]
                if bind_dn != alias:
                    attempts.append((alias, SIMPLE))
                if domain and supports_ntlm:
                    attempts.append((f"{domain}\\{alias}", NTLM))
            conn, _last = ldap_bind(
                attempts, password, server=server, server_url=server_url, should_continue=_prosegui_dopo_bind_rifiutato
            )
            if conn is None:
                return None
            groups: list[str] = []
            try:
                resolved_upn, resolved_full_name = resolve_ldap_identity(
                    alias=alias, upn_hint=upn, conn=conn, groups_out=groups
                )
            finally:
                try:
                    conn.unbind()
                except Exception:
                    logger.debug("LDAP: unbind fallito", exc_info=True)
        except LDAPUnreachable as exc:
            logger.warning(
                "LDAP: login di %s non verificato: servizio di autenticazione non raggiungibile (%s)", alias, exc
            )
            return None
        except (LDAPException, socket.error, OSError, ValueError) as exc:
            logger.warning("LDAP auth failed/unavailable: %s", exc)
            return None

        if not ldap_login_group_allowed(groups):
            logger.warning("LDAP login negato per %s: nessun gruppo in LDAP_GROUP_ALLOWLIST", alias)
            return None

        legacy_user = provision_legacy_user(
            resolved_upn or upn,
            full_name=resolved_full_name,
            alias=alias,
        )
        if legacy_user is None:
            return None

        return sync_django_user_from_legacy(legacy_user)

    def get_user(self, user_id):
        User = get_user_model()
        try:
            user = User.objects.filter(pk=user_id).first()
        except Exception:
            return None
        # SEC (audit M4): un utente disattivato perde subito le sessioni aperte.
        if user is not None and not user.is_active:
            return None
        return user
