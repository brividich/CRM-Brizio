from __future__ import annotations

from django.db import DatabaseError, transaction

from core.legacy_models import Ruolo, UtenteLegacy
from core.models import Profile


def resolve_caporeparto_legacy_user(
    raw_value: str | None = None,
    *,
    legacy_user_id: int | None = None,
) -> UtenteLegacy | None:
    if legacy_user_id is not None:
        try:
            user = UtenteLegacy.objects.filter(id=int(legacy_user_id)).order_by("id").first()
        except (TypeError, ValueError, DatabaseError):
            user = None
        if user is not None:
            return user

    value = str(raw_value or "").strip()
    if not value:
        return None

    try:
        numeric_id = int(value)
    except (TypeError, ValueError):
        numeric_id = None
    if numeric_id is not None:
        try:
            user = UtenteLegacy.objects.filter(id=numeric_id).order_by("id").first()
        except DatabaseError:
            user = None
        if user is not None:
            return user

    try:
        legacy_user = UtenteLegacy.objects.filter(email__iexact=value).order_by("id").first()
        if legacy_user:
            return legacy_user
        legacy_user = UtenteLegacy.objects.filter(nome__iexact=value).order_by("id").first()
        if legacy_user:
            return legacy_user
        if "@" in value:
            local_part = value.split("@", 1)[0].strip()
            if local_part:
                legacy_user = UtenteLegacy.objects.filter(email__istartswith=f"{local_part}@").order_by("id").first()
                if legacy_user:
                    return legacy_user
    except DatabaseError:
        return None
    return None


def canonical_caporeparto_value(
    raw_value: str | None = None,
    *,
    legacy_user_id: int | None = None,
) -> str:
    legacy_user = resolve_caporeparto_legacy_user(raw_value, legacy_user_id=legacy_user_id)
    if legacy_user is None:
        return str(raw_value or "").strip()
    email = str(getattr(legacy_user, "email", "") or "").strip().lower()
    if email:
        return email
    name = str(getattr(legacy_user, "nome", "") or "").strip()
    if name:
        return name
    return str(raw_value or "").strip()


def format_caporeparto_label(
    raw_value: str | None = None,
    *,
    legacy_user_id: int | None = None,
    include_role: bool = False,
) -> str:
    legacy_user = resolve_caporeparto_legacy_user(raw_value, legacy_user_id=legacy_user_id)
    if legacy_user is None:
        return str(raw_value or "").strip()

    name = str(getattr(legacy_user, "nome", "") or "").strip()
    email = str(getattr(legacy_user, "email", "") or "").strip().lower()
    role = str(getattr(legacy_user, "ruolo", "") or "").strip()

    if name and email:
        label = f"{name} - {email}"
    else:
        label = email or name or str(raw_value or "").strip()
    if include_role and role:
        label = f"{label} ({role})"
    return label


def ensure_caporeparto_role(legacy_user_id: int | None) -> dict[str, object]:
    result: dict[str, object] = {
        "ok": False,
        "changed": False,
        "legacy_user_id": legacy_user_id,
        "role_name": "",
        "reason": "",
    }
    if legacy_user_id is None:
        result["reason"] = "legacy_user_id mancante"
        return result

    try:
        caporeparto_role = Ruolo.objects.filter(nome__iexact="caporeparto").order_by("id").first()
        utente_role = Ruolo.objects.filter(nome__iexact="utente").order_by("id").first()
        legacy_user = UtenteLegacy.objects.filter(id=int(legacy_user_id)).first()
    except DatabaseError as exc:
        result["reason"] = str(exc)
        return result

    if legacy_user is None:
        result["reason"] = "utente non trovato"
        return result
    if caporeparto_role is None:
        result["reason"] = "ruolo caporeparto non trovato"
        return result

    target_role_name = str(caporeparto_role.nome or "").strip()
    result["role_name"] = target_role_name

    current_role_id = getattr(legacy_user, "ruolo_id", None)
    current_role_name = str(getattr(legacy_user, "ruolo", "") or "").strip().lower()
    if current_role_id == caporeparto_role.id or current_role_name == target_role_name.lower():
        result["ok"] = True
        result["reason"] = "utente già caporeparto"
        return result

    utente_role_id = int(utente_role.id) if utente_role else None
    if current_role_id not in {None, utente_role_id} and current_role_name not in {"", "utente"}:
        result["ok"] = True
        result["reason"] = "ruolo attuale mantenuto"
        return result

    try:
        with transaction.atomic():
            legacy_user.ruolo_id = int(caporeparto_role.id)
            legacy_user.ruolo = target_role_name
            legacy_user.save(update_fields=["ruolo_id", "ruolo"])
            Profile.objects.filter(legacy_user_id=int(legacy_user.id)).update(
                legacy_ruolo_id=int(caporeparto_role.id),
                legacy_ruolo=target_role_name,
            )
    except DatabaseError as exc:
        result["reason"] = str(exc)
        return result

    result["ok"] = True
    result["changed"] = True
    result["reason"] = "ruolo aggiornato a caporeparto"
    return result


def normalize_caporeparto_option(
    raw_value: str | None = None,
    *,
    legacy_user_id: int | None = None,
    promote_role: bool = False,
) -> dict[str, object]:
    legacy_user = resolve_caporeparto_legacy_user(raw_value, legacy_user_id=legacy_user_id)
    if legacy_user is None:
        return {
            "ok": False,
            "error": "Il caporeparto deve corrispondere a un utente esistente.",
        }

    normalized = {
        "ok": True,
        "legacy_user_id": int(legacy_user.id),
        "value": canonical_caporeparto_value(raw_value, legacy_user_id=int(legacy_user.id)),
        "label": format_caporeparto_label(raw_value, legacy_user_id=int(legacy_user.id)),
        "role_sync": {"ok": True, "changed": False, "reason": "skip"},
    }
    if promote_role:
        normalized["role_sync"] = ensure_caporeparto_role(int(legacy_user.id))
    return normalized
