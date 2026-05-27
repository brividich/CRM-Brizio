from __future__ import annotations

import logging
import re
import socket
from functools import lru_cache
from typing import Iterable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import DatabaseError, IntegrityError, connections, transaction

from core.legacy_models import Ruolo, UtenteLegacy
from core.models import Profile

logger = logging.getLogger(__name__)
_USERNAME_ALLOWED_RE = re.compile(r"[^\w.@+-]+")
ALLOWED_LEGACY_TABLES = frozenset(
    {
        "anagrafica_dipendenti",
        "anomalie",
        "assenze",
        "capi_reparto",
        "dipendenti",
        "ordini_produzione",
        "permessi",
        "pulsanti",
        "ruoli",
        "utenti",
    }
)


def legacy_auth_enabled() -> bool:
    return bool(getattr(settings, "LEGACY_AUTH_ENABLED", False))


def extract_identity_alias(ident: str) -> str:
    alias = str(ident or "").strip().lower()
    if not alias:
        return ""
    if "\\" in alias:
        alias = alias.split("\\")[-1]
    if "@" in alias:
        alias = alias.split("@", 1)[0]
    return alias.strip()


def canonicalize_ldap_upn(alias_or_ident: str, fallback_upn: str = "") -> str:
    alias = extract_identity_alias(alias_or_ident)
    fallback = str(fallback_upn or "").strip().lower()
    suffix = str(getattr(settings, "LDAP_UPN_SUFFIX", "") or "").strip().lstrip("@").lower()
    if alias and suffix:
        return f"{alias}@{suffix}"
    if fallback and "@" in fallback:
        return fallback
    if alias:
        domain = str(getattr(settings, "LDAP_DOMAIN", "") or "").strip().lower()
        if domain:
            return f"{alias}@{domain}"
        return alias
    return fallback


def normalize_windows_principal_to_upn(principal: str) -> str:
    normalized = str(principal or "").strip().lower()
    if not normalized:
        return ""
    if "\\" in normalized:
        domain, username = normalized.split("\\", 1)
        return canonicalize_ldap_upn(username, f"{username}@{domain}")
    return canonicalize_ldap_upn(normalized, normalized)


def _ldap_escape_filter(value: str) -> str:
    escaped = str(value or "")
    escaped = escaped.replace("\\", r"\5c")
    escaped = escaped.replace("*", r"\2a")
    escaped = escaped.replace("(", r"\28")
    escaped = escaped.replace(")", r"\29")
    escaped = escaped.replace("\x00", r"\00")
    return escaped


def _as_ldap_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [text]


def _ldap_entry_first(entry_dict: dict, key: str, default: str = "") -> str:
    values = _as_ldap_list(entry_dict.get(key))
    if not values:
        return default
    return values[0]


def resolve_ldap_identity(alias: str, upn_hint: str = "", *, conn=None) -> tuple[str, str]:
    alias_norm = extract_identity_alias(alias or upn_hint)
    preferred_upn = canonicalize_ldap_upn(alias_norm or alias, upn_hint)
    full_name = ""

    if not bool(getattr(settings, "LDAP_ENABLED", False)):
        return preferred_upn, full_name

    search_base = str(getattr(settings, "LDAP_BASE_DN", "") or "").strip()
    user_filter = str(getattr(settings, "LDAP_USER_FILTER", "") or "").strip()
    if not search_base or not user_filter:
        return preferred_upn, full_name

    cleanup_conn = False
    active_conn = conn

    if active_conn is None:
        server_url = str(getattr(settings, "LDAP_SERVER", "") or "").strip()
        timeout = int(getattr(settings, "LDAP_TIMEOUT", 5) or 5)
        service_user = str(getattr(settings, "LDAP_SERVICE_USER", "") or "").strip()
        service_password = str(getattr(settings, "LDAP_SERVICE_PASSWORD", "") or "").strip()
        domain = str(getattr(settings, "LDAP_DOMAIN", "") or "").strip()
        suffix = str(getattr(settings, "LDAP_UPN_SUFFIX", "") or "").strip().lstrip("@")

        if not server_url or not service_user or not service_password:
            return preferred_upn, full_name

        try:
            from ldap3 import Connection, NONE, NTLM, SIMPLE, Server
            from ldap3.core.exceptions import LDAPException, LDAPSocketOpenError
        except Exception as exc:
            logger.warning("resolve_ldap_identity: ldap3 unavailable: %s", exc)
            return preferred_upn, full_name

        try:
            server = Server(server_url, connect_timeout=timeout, get_info=NONE)
            if "\\" in service_user:
                bind_attempts = [(service_user, NTLM)]
            elif "@" in service_user:
                bind_attempts = [(service_user, SIMPLE)]
            else:
                bind_attempts = []
                if suffix:
                    bind_attempts.append((f"{service_user}@{suffix}", SIMPLE))
                bind_attempts.append((service_user, SIMPLE))
                if domain:
                    bind_attempts.append((f"{domain}\\{service_user}", NTLM))

            last_error = None
            for bind_user, authentication in bind_attempts:
                candidate = Connection(
                    server,
                    user=bind_user,
                    password=service_password,
                    authentication=authentication,
                    auto_bind=False,
                    auto_referrals=False,
                    raise_exceptions=False,
                )
                ok = candidate.bind()
                if ok:
                    active_conn = candidate
                    cleanup_conn = True
                    break
                last_error = candidate.result
                try:
                    candidate.unbind()
                except Exception:
                    pass
            if active_conn is None:
                logger.warning("resolve_ldap_identity: LDAP service bind failed: %s", last_error)
                return preferred_upn, full_name
        except (LDAPSocketOpenError, LDAPException, socket.error, OSError, ValueError) as exc:
            logger.warning("resolve_ldap_identity: LDAP service connection failed: %s", exc)
            return preferred_upn, full_name

    lookup_keys = []
    if alias_norm:
        lookup_keys.append(f"(sAMAccountName={_ldap_escape_filter(alias_norm)})")
    for candidate in (upn_hint, preferred_upn):
        upn_candidate = str(candidate or "").strip().lower()
        if upn_candidate and "@" in upn_candidate:
            lookup_keys.append(f"(userPrincipalName={_ldap_escape_filter(upn_candidate)})")
            lookup_keys.append(f"(mail={_ldap_escape_filter(upn_candidate)})")

    if not lookup_keys:
        if cleanup_conn and active_conn is not None:
            try:
                active_conn.unbind()
            except Exception:
                pass
        return preferred_upn, full_name

    identity_filter = "".join(dict.fromkeys(lookup_keys))
    search_filter = f"(&{user_filter}(|{identity_filter}))"
    attrs = ["displayName", "givenName", "sn", "mail", "userPrincipalName", "sAMAccountName"]

    try:
        ok = active_conn.search(
            search_base=search_base,
            search_filter=search_filter,
            attributes=attrs,
            size_limit=1,
        )
        if ok and getattr(active_conn, "entries", None):
            entry = active_conn.entries[0]
            data = entry.entry_attributes_as_dict if hasattr(entry, "entry_attributes_as_dict") else {}
            sam = _ldap_entry_first(data, "sAMAccountName").strip().lower()
            ldap_upn = _ldap_entry_first(data, "userPrincipalName").strip().lower()
            ldap_mail = _ldap_entry_first(data, "mail").strip().lower()
            given = _ldap_entry_first(data, "givenName").strip()
            sn = _ldap_entry_first(data, "sn").strip()
            display = _ldap_entry_first(data, "displayName").strip()

            resolved_alias = extract_identity_alias(sam or alias_norm)
            resolved_upn = canonicalize_ldap_upn(resolved_alias, ldap_upn or preferred_upn or ldap_mail)
            full_name = display or " ".join([p for p in [given, sn] if p]).strip()
            if not full_name and resolved_alias:
                full_name = resolved_alias.replace(".", " ").title()
            return resolved_upn, full_name
    except Exception as exc:
        logger.warning("resolve_ldap_identity: LDAP search failed for alias=%s: %s", alias_norm, exc)
    finally:
        if cleanup_conn and active_conn is not None:
            try:
                active_conn.unbind()
            except Exception:
                pass

    return preferred_upn, full_name


def _split_name(full_name: str) -> tuple[str, str]:
    parts = [p for p in (full_name or "").strip().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _safe_username_candidates(legacy_user: UtenteLegacy) -> Iterable[str]:
    email = (legacy_user.email or "").strip().lower()
    nome = (legacy_user.nome or "").strip()
    if email:
        yield email
    if nome:
        yield nome
    if email and "@" in email:
        yield email.split("@", 1)[0]
    yield f"legacy_{legacy_user.id}"


def _username_max_length(User) -> int:
    try:
        return int(User._meta.get_field("username").max_length)
    except Exception:
        return 150


def _sanitize_username(raw_value: str, fallback: str, max_length: int) -> str:
    value = re.sub(r"\s+", ".", (raw_value or "").strip().lower())
    value = _USERNAME_ALLOWED_RE.sub("", value).strip("._-")
    if not value:
        value = fallback
    value = value[:max_length].strip("._-")
    if not value:
        return fallback[:max_length]
    return value


def _with_suffix(base_value: str, index: int, max_length: int) -> str:
    suffix = f"_{index}"
    base_len = max(1, max_length - len(suffix))
    return f"{base_value[:base_len]}{suffix}"


def _profile_for_user(user) -> Profile | None:
    if not getattr(user, "pk", None):
        return None
    return Profile.objects.select_for_update().filter(user=user).first()


def _pick_candidate_user(User, legacy_user: UtenteLegacy):
    legacy_id = int(legacy_user.id)
    max_len = _username_max_length(User)
    fallback_base = _sanitize_username(f"legacy_{legacy_id}", f"legacy_{legacy_id}", max_len)
    seen: set[str] = set()

    for raw_candidate in _safe_username_candidates(legacy_user):
        base_candidate = _sanitize_username(raw_candidate, fallback_base, max_len)
        if not base_candidate:
            continue
        for idx in range(0, 30):
            candidate = base_candidate if idx == 0 else _with_suffix(base_candidate, idx + 1, max_len)
            if candidate in seen:
                continue
            seen.add(candidate)
            existing_user = User.objects.filter(username__iexact=candidate).first()
            if existing_user is None:
                new_user = User(username=candidate)
                new_user.set_unusable_password()
                return new_user
            existing_profile = _profile_for_user(existing_user)
            if existing_profile and int(existing_profile.legacy_user_id) != legacy_id:
                logger.warning(
                    "sync_django_user_from_legacy: skip username=%s user_id=%s legacy_conflict=%s requested_legacy=%s",
                    candidate,
                    existing_user.id,
                    existing_profile.legacy_user_id,
                    legacy_id,
                )
                continue
            return existing_user

    fallback_user = User(username=fallback_base)
    fallback_user.set_unusable_password()
    return fallback_user


def _sync_django_user_fields(django_user, legacy_user: UtenteLegacy) -> None:
    django_user.email = (legacy_user.email or "").strip().lower()
    first_name, last_name = _split_name(legacy_user.nome or "")
    django_user.first_name = first_name
    django_user.last_name = last_name
    django_user.is_active = bool(legacy_user.attivo)


def sync_django_user_from_legacy(legacy_user: UtenteLegacy):
    User = get_user_model()
    legacy_id = int(legacy_user.id)

    with transaction.atomic():
        profile_for_legacy = (
            Profile.objects.select_for_update().select_related("user").filter(legacy_user_id=legacy_id).first()
        )
        django_user = profile_for_legacy.user if profile_for_legacy else _pick_candidate_user(User, legacy_user)

        user_profile = _profile_for_user(django_user)
        if user_profile and int(user_profile.legacy_user_id) != legacy_id:
            logger.error(
                "sync_django_user_from_legacy: blocked remap user_id=%s from legacy=%s to legacy=%s",
                django_user.id,
                user_profile.legacy_user_id,
                legacy_id,
            )
            if profile_for_legacy:
                django_user = profile_for_legacy.user
                user_profile = profile_for_legacy
            else:
                django_user = _pick_candidate_user(User, legacy_user)
                user_profile = _profile_for_user(django_user)

        _sync_django_user_fields(django_user, legacy_user)
        try:
            django_user.save()
        except IntegrityError:
            django_user = _pick_candidate_user(User, legacy_user)
            _sync_django_user_fields(django_user, legacy_user)
            django_user.save()
            user_profile = _profile_for_user(django_user)

        if user_profile is None:
            try:
                user_profile = Profile.objects.create(
                    user=django_user,
                    legacy_user_id=legacy_id,
                    legacy_ruolo_id=legacy_user.ruolo_id,
                    legacy_ruolo=(legacy_user.ruolo or "").strip(),
                )
            except IntegrityError:
                existing_profile = (
                    Profile.objects.select_for_update().select_related("user").filter(legacy_user_id=legacy_id).first()
                )
                if existing_profile and existing_profile.user_id != django_user.id:
                    logger.error(
                        "sync_django_user_from_legacy: profile collision legacy=%s existing_user=%s requested_user=%s",
                        legacy_id,
                        existing_profile.user_id,
                        django_user.id,
                    )
                    django_user = existing_profile.user
                    user_profile = existing_profile
                    _sync_django_user_fields(django_user, legacy_user)
                    django_user.save()
                else:
                    raise
        elif int(user_profile.legacy_user_id) != legacy_id:
            logger.error(
                "sync_django_user_from_legacy: user already linked user_id=%s legacy=%s requested_legacy=%s",
                django_user.id,
                user_profile.legacy_user_id,
                legacy_id,
            )
            return user_profile.user

        profile_updates = []
        if user_profile.legacy_ruolo_id != legacy_user.ruolo_id:
            user_profile.legacy_ruolo_id = legacy_user.ruolo_id
            profile_updates.append("legacy_ruolo_id")
        legacy_ruolo_value = (legacy_user.ruolo or "").strip()
        if user_profile.legacy_ruolo != legacy_ruolo_value:
            user_profile.legacy_ruolo = legacy_ruolo_value
            profile_updates.append("legacy_ruolo")
        if profile_updates:
            user_profile.save(update_fields=profile_updates)

        return django_user


def provision_legacy_user(upn: str, *, full_name: str = "", alias: str = "") -> "UtenteLegacy | None":
    """Recupera o crea un UtenteLegacy per un UPN AD/SSO (usato da LDAPBackend e windows_sso).

    Restituisce None se l'utente è disabilitato o in caso di errore DB.
    """
    upn = str(upn or "").strip().lower()
    alias_norm = extract_identity_alias(alias or upn)
    try:
        legacy_user = UtenteLegacy.objects.filter(email__iexact=upn).first()
        if legacy_user is None and alias_norm:
            # Compat: riallinea utenti AD esistenti quando cambia il dominio UPN.
            legacy_user = UtenteLegacy.objects.filter(email__istartswith=f"{alias_norm}@").order_by("id").first()
        if legacy_user is None:
            ruolo_utente = Ruolo.objects.filter(nome__iexact="utente").first()
            ruolo_id = ruolo_utente.id if ruolo_utente else None
            display_name = (full_name or "").strip() or upn.split("@", 1)[0].replace(".", " ").title()
            model_fields = {f.name for f in UtenteLegacy._meta.fields}
            create_kwargs = {
                "nome": display_name,
                "email": upn,
                "password": "*AD_MANAGED*",
                "ruolo": "utente",
                "attivo": True,
                "deve_cambiare_password": False,
                "ruoli": '["utente"]',
                "ruolo_id": ruolo_id,
            }
            legacy_user = UtenteLegacy.objects.create(
                **{k: v for k, v in create_kwargs.items() if k in model_fields}
            )
        else:
            changed_fields = []
            if upn and (legacy_user.email or "").strip().lower() != upn:
                legacy_user.email = upn
                changed_fields.append("email")
            if full_name and (legacy_user.nome or "").strip() != full_name.strip():
                legacy_user.nome = full_name.strip()
                changed_fields.append("nome")
            if changed_fields:
                legacy_user.save(update_fields=changed_fields)
        if not bool(legacy_user.attivo):
            return None
        return legacy_user
    except DatabaseError as exc:
        logger.warning("provision_legacy_user fallito per %s: %s", upn, exc)
        return None


def get_legacy_user(django_user):
    if not getattr(django_user, "is_authenticated", False):
        return None
    try:
        profile = django_user.profile
    except Profile.DoesNotExist:
        return None
    try:
        return UtenteLegacy.objects.filter(id=profile.legacy_user_id).first()
    except DatabaseError:
        return None


@lru_cache(maxsize=32)
def legacy_table_columns(table_name: str) -> set[str]:
    normalized_table = str(table_name or "").strip().lower()
    if normalized_table not in ALLOWED_LEGACY_TABLES:
        return set()
    try:
        with connections["default"].cursor() as cursor:
            vendor = connections["default"].vendor
            if vendor == "sqlite":
                cursor.execute(f'PRAGMA table_info("{normalized_table}")')
                return {str(row[1]).lower() for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT LOWER(COLUMN_NAME)
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = %s
                """,
                [normalized_table],
            )
            return {str(row[0]).lower() for row in cursor.fetchall()}
    except Exception:
        return set()


def legacy_table_has_column(table_name: str, column_name: str) -> bool:
    return column_name.lower() in legacy_table_columns(table_name)


_ADMIN_ROLE_IDS_CACHE_KEY = "legacy_acl:admin_role_ids"
_ADMIN_ROLE_IDS_TTL = 120  # secondi — stessa finestra dell'ACL cache


def _get_admin_role_names() -> frozenset[str]:
    """Nomi ruolo considerati admin, configurabili via PORTAL_ADMIN_ROLE_NAMES.

    Default: {"admin"} per compatibilità legacy.
    """
    from django.conf import settings as _settings
    names = getattr(_settings, "PORTAL_ADMIN_ROLE_NAMES", None)
    if names and isinstance(names, (list, tuple, set, frozenset)):
        result = {str(n).strip().lower() for n in names if str(n).strip()}
        if result:
            return frozenset(result)
    return frozenset({"admin"})


def get_admin_role_ids() -> set[int]:
    """Restituisce gli ID dei ruoli admin (da PORTAL_ADMIN_ROLE_NAMES).

    Usa Django cache (invalidabile via bump_legacy_cache_version) invece di
    lru_cache Python in-process, che non veniva mai resettata a runtime.
    TTL 120s allineato all'ACL cache TTL.
    """
    cached = cache.get(_ADMIN_ROLE_IDS_CACHE_KEY)
    if cached is not None:
        return cached
    try:
        admin_names = _get_admin_role_names()
        ids = {int(r.id) for r in Ruolo.objects.all() if (r.nome or "").strip().lower() in admin_names}
    except DatabaseError:
        ids = set()
    cache.set(_ADMIN_ROLE_IDS_CACHE_KEY, ids, timeout=_ADMIN_ROLE_IDS_TTL)
    return ids


def is_legacy_admin(legacy_user: UtenteLegacy | None) -> bool:
    if not legacy_user:
        return False
    admin_names = _get_admin_role_names()
    if str(legacy_user.ruolo or "").strip().lower() in admin_names:
        return True
    if legacy_user.ruolo_id is None:
        return False
    return int(legacy_user.ruolo_id) in get_admin_role_ids()
