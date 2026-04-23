from __future__ import annotations

import hashlib
import logging
import socket

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connections
from werkzeug.security import check_password_hash

from core.legacy_models import Ruolo, UtenteLegacy
from core.legacy_utils import (
    canonicalize_ldap_upn,
    extract_identity_alias,
    legacy_auth_enabled,
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
            return User.objects.filter(pk=user_id).first()
        except Exception:
            return None


class LDAPBackend:
    def authenticate(self, request, username=None, password=None, **kwargs):
        ident = (username or "").strip()
        password = (password or "").strip()
        if not legacy_auth_enabled() or not getattr(settings, "LDAP_ENABLED", False):
            return None
        if not ident or not password:
            return None

        try:
            from ldap3 import Connection, NONE, NTLM, SIMPLE, Server
            from ldap3.core.exceptions import LDAPException, LDAPSocketOpenError
        except Exception as exc:
            logger.warning("ldap3 unavailable: %s", exc)
            return None

        server_url = getattr(settings, "LDAP_SERVER", "") or ""
        domain = getattr(settings, "LDAP_DOMAIN", "") or ""
        upn_suffix = getattr(settings, "LDAP_UPN_SUFFIX", "") or ""
        timeout = int(getattr(settings, "LDAP_TIMEOUT", 5) or 5)
        if not server_url:
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
            server = Server(server_url, connect_timeout=timeout, get_info=NONE)
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
            conn = None
            for bind_user, authentication in attempts:
                try:
                    candidate = Connection(
                        server,
                        user=bind_user,
                        password=password,
                        authentication=authentication,
                        auto_bind=False,
                        auto_referrals=False,
                        raise_exceptions=False,
                    )
                    ok = candidate.bind()
                except Exception as exc:
                    # Fail closed on any LDAP bind error: invalid credentials must not become HTTP 500.
                    logger.warning("LDAP bind skipped for %s (%s): %s", bind_user, authentication, exc)
                    ok = False
                    continue
                if ok:
                    conn = candidate
                    break
                try:
                    candidate.unbind()
                except Exception:
                    pass
            if conn is None:
                return None
            try:
                resolved_upn, resolved_full_name = resolve_ldap_identity(alias=alias, upn_hint=upn, conn=conn)
            finally:
                try:
                    conn.unbind()
                except Exception:
                    pass
        except (LDAPSocketOpenError, LDAPException, socket.error, OSError, ValueError) as exc:
            logger.warning("LDAP auth failed/unavailable: %s", exc)
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
            return User.objects.filter(pk=user_id).first()
        except Exception:
            return None
