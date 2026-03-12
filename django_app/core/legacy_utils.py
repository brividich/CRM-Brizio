from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Iterable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, connections, transaction

from core.legacy_models import Ruolo, UtenteLegacy
from core.models import Profile

logger = logging.getLogger(__name__)
_USERNAME_ALLOWED_RE = re.compile(r"[^\w.@+-]+")


def legacy_auth_enabled() -> bool:
    return bool(getattr(settings, "LEGACY_AUTH_ENABLED", False))


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


def provision_legacy_user(upn: str) -> "UtenteLegacy | None":
    """Recupera o crea un UtenteLegacy per un UPN AD/SSO (usato da LDAPBackend e windows_sso).

    Restituisce None se l'utente è disabilitato o in caso di errore DB.
    """
    upn = upn.lower()
    try:
        legacy_user = UtenteLegacy.objects.filter(email__iexact=upn).first()
        if legacy_user is None:
            ruolo_utente = Ruolo.objects.filter(nome__iexact="utente").first()
            ruolo_id = ruolo_utente.id if ruolo_utente else None
            display_name = upn.split("@", 1)[0].replace(".", " ").title()
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
    try:
        with connections["default"].cursor() as cursor:
            vendor = connections["default"].vendor
            if vendor == "sqlite":
                cursor.execute(f"PRAGMA table_info({table_name})")
                return {str(row[1]).lower() for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT LOWER(COLUMN_NAME)
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = %s
                """,
                [table_name],
            )
            return {str(row[0]).lower() for row in cursor.fetchall()}
    except Exception:
        return set()


def legacy_table_has_column(table_name: str, column_name: str) -> bool:
    return column_name.lower() in legacy_table_columns(table_name)


@lru_cache(maxsize=1)
def get_admin_role_ids() -> set[int]:
    try:
        return {int(r.id) for r in Ruolo.objects.filter(nome__iexact="admin")}
    except DatabaseError:
        return set()


def is_legacy_admin(legacy_user: UtenteLegacy | None) -> bool:
    if not legacy_user:
        return False
    if str(legacy_user.ruolo or "").strip().lower() == "admin":
        return True
    if legacy_user.ruolo_id is None:
        return False
    return int(legacy_user.ruolo_id) in get_admin_role_ids()
