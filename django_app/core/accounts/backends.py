from __future__ import annotations

import logging
import socket

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connections
from werkzeug.security import check_password_hash

from core.legacy_models import Ruolo, UtenteLegacy
from core.legacy_utils import legacy_auth_enabled, provision_legacy_user, sync_django_user_from_legacy

logger = logging.getLogger(__name__)


def _extract_alias(ident: str) -> str:
    alias = str(ident or "").strip().lower()
    if not alias:
        return ""
    if "\\" in alias:
        alias = alias.split("\\")[-1]
    if "@" in alias:
        alias = alias.split("@", 1)[0]
    return alias.strip()


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
            from ldap3 import AUTO_BIND_NO_TLS, Connection, NONE, NTLM, SIMPLE, Server
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

        if "@" in ident:
            upn = ident.lower()
            bind_dn = upn
        else:
            suffix = upn_suffix.lstrip("@") if upn_suffix else ""
            upn = f"{ident.lower()}@{suffix}" if suffix else ident.lower()
            bind_dn = upn

        try:
            server = Server(server_url, connect_timeout=timeout, get_info=NONE)
            conn = Connection(
                server,
                user=bind_dn,
                password=password,
                authentication=SIMPLE,
                auto_bind=AUTO_BIND_NO_TLS,
                raise_exceptions=False,
            )
            ok = conn.bind()
            if ok:
                conn.unbind()
            elif "@" not in ident and domain:
                conn2 = Connection(
                    server,
                    user=f"{domain}\\{ident}",
                    password=password,
                    authentication=NTLM,
                    auto_bind=AUTO_BIND_NO_TLS,
                    raise_exceptions=False,
                )
                ok = conn2.bind()
                if ok:
                    conn2.unbind()
            if not ok:
                return None
        except (LDAPSocketOpenError, LDAPException, socket.error, OSError) as exc:
            logger.warning("LDAP auth failed/unavailable: %s", exc)
            return None

        legacy_user = provision_legacy_user(upn)
        if legacy_user is None:
            return None

        return sync_django_user_from_legacy(legacy_user)

    def get_user(self, user_id):
        User = get_user_model()
        try:
            return User.objects.filter(pk=user_id).first()
        except Exception:
            return None
