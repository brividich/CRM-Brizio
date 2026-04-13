from __future__ import annotations

import re
from urllib.parse import urlsplit

from django.db import DatabaseError
from django.urls import Resolver404, resolve

from core.acl import (
    check_permesso,
    diagnose_permesso,
    evaluate_modulo_action_access,
    normalize_acl_path,
)
from core.legacy_utils import is_legacy_admin
from core.models import (
    PermissionDefinition,
    RolePermissionGrant,
    RoutePermissionBinding,
    UserPermissionGrant,
)

_PERMISSION_CODE_SANITIZE_RE = re.compile(r"[^a-z0-9._:-]+")
_PERMISSION_CODE_CANONICAL_RE = re.compile(
    r"^[a-z0-9]+(?:_[a-z0-9]+)*(?:\.[a-z0-9]+(?:_[a-z0-9]+)*){2,}$"
)
_STANDARD_PERMISSION_ACTIONS = {
    "view",
    "manage",
    "create",
    "edit",
    "delete",
    "approve",
    "export",
    "import",
    "run",
}
_ANOMALIE_MENU_COMPAT_ACTIONS = (
    ("anomalie", "anomalie_aperte"),
    ("anomalie", "inserimento_anomalie"),
)
PERMISSION_CODE_FORMAT_HINT = (
    "Formato richiesto: modulo.risorsa.azione (solo lowercase e underscore). "
    "Esempi validi: admin_portale.users.view, assets.work_orders.manage."
)


def normalize_permission_code(raw_value: str) -> str:
    value = _PERMISSION_CODE_SANITIZE_RE.sub(".", str(raw_value or "").strip().lower())
    while ".." in value:
        value = value.replace("..", ".")
    return value.strip("._:-")


def validate_permission_code(code: str) -> tuple[bool, str]:
    normalized = normalize_permission_code(code)
    if not normalized:
        return False, PERMISSION_CODE_FORMAT_HINT
    if not _PERMISSION_CODE_CANONICAL_RE.match(normalized):
        return False, PERMISSION_CODE_FORMAT_HINT
    return True, ""


def permission_code_naming_warning(code: str) -> str:
    normalized = normalize_permission_code(code)
    if not normalized:
        return ""
    parts = normalized.split(".")
    if len(parts) < 3:
        return ""
    action = parts[-1]
    if action not in _STANDARD_PERMISSION_ACTIONS:
        return (
            f"Azione '{action}' fuori convenzione consigliata ({', '.join(sorted(_STANDARD_PERMISSION_ACTIONS))}). "
            "Valuta un alias piu esplicito."
        )
    return ""


def normalize_binding_path_pattern(raw_value: str, *, for_regex: bool = False) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return ""
    if for_regex:
        return value
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        value = parsed.path or "/"
    return normalize_acl_path(value)


def resolve_route_name(path: str, request=None) -> str:
    target_path = normalize_acl_path(path)
    if request is not None:
        resolver_match = getattr(request, "resolver_match", None)
        request_path = normalize_acl_path(getattr(request, "path", "") or "/")
        if resolver_match and request_path == target_path:
            route_name = (
                (resolver_match.view_name or "").strip()
                or (resolver_match.url_name or "").strip()
            )
            if route_name:
                return route_name
    candidates: list[str] = []
    raw_path = urlsplit(str(path or "/")).path or "/"
    for candidate in (raw_path, target_path):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
        if candidate and candidate != "/" and not candidate.endswith("/"):
            slash_candidate = f"{candidate}/"
            if slash_candidate not in candidates:
                candidates.append(slash_candidate)
    for candidate in candidates:
        try:
            resolver_match = resolve(candidate)
        except Resolver404:
            continue
        route_name = ((resolver_match.view_name or "").strip() or (resolver_match.url_name or "").strip())
        if route_name:
            return route_name
    return ""


def _serialize_permission(permission: PermissionDefinition | None) -> dict | None:
    if permission is None:
        return None
    return {
        "code": permission.code,
        "label": permission.label,
        "module": permission.module,
        "description": permission.description,
        "is_active": bool(permission.is_active),
    }


def _serialize_binding(binding: RoutePermissionBinding | None, *, matched_by: str = "") -> dict | None:
    if binding is None:
        return None
    return {
        "id": int(binding.id),
        "route_name": binding.route_name,
        "path_pattern": binding.path_pattern,
        "match_strategy": binding.match_strategy,
        "permission_code": binding.permission_id,
        "source_app": binding.source_app or "",
        "note": binding.note or "",
        "priority": int(binding.priority),
        "is_active": bool(binding.is_active),
        "matched_by": matched_by or "",
    }


def _serialize_legacy_user(legacy_user) -> dict | None:
    if not legacy_user:
        return None
    return {
        "id": int(getattr(legacy_user, "id", 0) or 0),
        "nome": (getattr(legacy_user, "nome", "") or "").strip(),
        "email": (getattr(legacy_user, "email", "") or "").strip(),
        "ruolo": (getattr(legacy_user, "ruolo", "") or "").strip(),
        "ruolo_id": getattr(legacy_user, "ruolo_id", None),
        "attivo": bool(getattr(legacy_user, "attivo", False)),
    }


def _binding_matches_path(binding: RoutePermissionBinding, path_norm: str) -> bool:
    strategy = (binding.match_strategy or RoutePermissionBinding.MATCH_EXACT).lower()
    if strategy == RoutePermissionBinding.MATCH_REGEX:
        try:
            return re.search(binding.path_pattern or "", path_norm) is not None
        except re.error:
            return False

    pattern = normalize_binding_path_pattern(binding.path_pattern, for_regex=False)
    if not pattern:
        return False
    if strategy == RoutePermissionBinding.MATCH_PREFIX:
        return path_norm == pattern or path_norm.startswith(pattern + "/")
    return path_norm == pattern


def _find_canonical_binding(*, route_name: str, path_norm: str) -> tuple[RoutePermissionBinding | None, str]:
    by_route = None
    by_path = None

    if route_name:
        by_route = (
            RoutePermissionBinding.objects.filter(is_active=True, route_name__iexact=route_name)
            .select_related("permission")
            .order_by("priority", "id")
            .first()
        )
        if by_route is not None:
            return by_route, "route_name"

    path_candidates = (
        RoutePermissionBinding.objects.filter(is_active=True)
        .exclude(path_pattern="")
        .select_related("permission")
        .order_by("priority", "id")
    )
    for candidate in path_candidates:
        if _binding_matches_path(candidate, path_norm):
            by_path = candidate
            break
    if by_path is not None:
        return by_path, "path_pattern"
    return None, ""


def _resolve_anomalie_menu_compat_access(*, path_norm: str, legacy_user) -> dict | None:
    if path_norm != "/anomalie-menu" or legacy_user is None:
        return None

    matched_actions: list[dict] = []
    for modulo, azione in _ANOMALIE_MENU_COMPAT_ACTIONS:
        action_result = evaluate_modulo_action_access(
            legacy_user=legacy_user,
            modulo=modulo,
            azione=azione,
        )
        if not bool(action_result.get("allowed", False)):
            continue
        matched_actions.append(
            {
                "modulo": modulo,
                "azione": azione,
                "source": str(action_result.get("source") or ""),
            }
        )

    if not matched_actions:
        return None

    action_labels = ", ".join(str(item["azione"]) for item in matched_actions)
    return {
        "matched_actions": matched_actions,
        "reason": (
            "Landing '/anomalie-menu' consentita in compatibilita perche il ruolo "
            f"ha almeno un permesso operativo sul modulo anomalie ({action_labels})."
        ),
    }


def resolve_acl_access(
    *,
    path: str,
    legacy_user,
    django_user=None,
    request=None,
    include_legacy_diagnostic: bool = True,
) -> dict:
    path_input = path or "/"
    path_norm = normalize_acl_path(path_input)
    route_name = resolve_route_name(path_norm, request=request)
    trace: list[dict] = []

    result = {
        "allowed": False,
        "path_input": path_input,
        "path_normalized": path_norm,
        "route_name": route_name,
        "decision_source": "deny",
        "decision_kind": "deny",
        "reason": "",
        "legacy_user": _serialize_legacy_user(legacy_user),
        "is_superuser": bool(getattr(django_user, "is_superuser", False)),
        "is_legacy_admin": False,
        "trace": trace,
        "canonical": {
            "binding_found": False,
            "binding": None,
            "permission": None,
            "role_grant": None,
            "user_override": None,
            "effective_level": None,
            "error": "",
        },
        "compat": None,
        "legacy_fallback": None,
    }

    if bool(getattr(django_user, "is_superuser", False)):
        result["allowed"] = True
        result["decision_source"] = "superuser_bypass"
        result["decision_kind"] = "bypass"
        result["reason"] = "Utente Django superuser: bypass ACL."
        trace.append({"step": "bypass", "result": "allow", "detail": "django_superuser"})
        return result

    if legacy_user and is_legacy_admin(legacy_user):
        result["allowed"] = True
        result["is_legacy_admin"] = True
        result["decision_source"] = "legacy_admin_bypass"
        result["decision_kind"] = "bypass"
        result["reason"] = "Utente riconosciuto come admin legacy: bypass ACL."
        trace.append({"step": "bypass", "result": "allow", "detail": "legacy_admin"})
        return result

    if legacy_user is None:
        result["decision_source"] = "deny_missing_legacy_user"
        result["decision_kind"] = "deny"
        result["reason"] = "Nessun utente legacy associato all'utente autenticato."
        trace.append({"step": "legacy_user", "result": "deny", "detail": "missing_legacy_user"})
        return result

    ruolo_id = getattr(legacy_user, "ruolo_id", None)
    if not ruolo_id:
        result["decision_source"] = "deny_missing_role"
        result["decision_kind"] = "deny"
        result["reason"] = "Utente legacy senza ruolo_id: accesso negato."
        trace.append({"step": "legacy_role", "result": "deny", "detail": "missing_role_id"})
        return result

    try:
        binding, matched_by = _find_canonical_binding(route_name=route_name, path_norm=path_norm)
    except DatabaseError as exc:
        result["canonical"]["error"] = str(exc)
        trace.append({"step": "canonical_binding", "result": "error", "detail": str(exc)})
        binding = None
        matched_by = ""

    compat_result = _resolve_anomalie_menu_compat_access(path_norm=path_norm, legacy_user=legacy_user)

    if binding is not None:
        permission = binding.permission
        result["canonical"]["binding_found"] = True
        result["canonical"]["binding"] = _serialize_binding(binding, matched_by=matched_by)
        result["canonical"]["permission"] = _serialize_permission(permission)
        trace.append(
            {
                "step": "canonical_binding",
                "result": "found",
                "detail": f"{matched_by}:{binding.route_name or binding.path_pattern}",
            }
        )

    if compat_result is not None:
        result["allowed"] = True
        result["decision_source"] = "compat_anomalie_menu"
        result["decision_kind"] = "compat"
        result["reason"] = str(compat_result.get("reason") or "")
        result["compat"] = compat_result
        trace.append(
            {
                "step": "compat_anomalie_menu",
                "result": "allow",
                "detail": ", ".join(
                    str(item.get("azione") or "")
                    for item in (compat_result.get("matched_actions") or [])
                ),
            }
        )
        return result

    if binding is not None:
        if not bool(permission.is_active):
            result["decision_source"] = "canonical_permission_inactive"
            result["decision_kind"] = "canonical"
            result["reason"] = f"Permission '{permission.code}' trovata ma disattiva."
            trace.append(
                {"step": "canonical_permission", "result": "deny", "detail": "permission_inactive"}
            )
            return result

        role_grant = (
            RolePermissionGrant.objects.filter(
                legacy_role_id=int(ruolo_id),
                permission_id=permission.code,
            )
            .order_by("-id")
            .first()
        )
        if role_grant is None:
            role_allowed = False
            result["canonical"]["role_grant"] = {"exists": False, "enabled": None}
        else:
            role_allowed = bool(role_grant.enabled)
            result["canonical"]["role_grant"] = {
                "exists": True,
                "id": int(role_grant.id),
                "enabled": bool(role_grant.enabled),
                "legacy_role_id": int(role_grant.legacy_role_id),
                "note": role_grant.note or "",
            }
        trace.append(
            {
                "step": "role_grant",
                "result": "allow" if role_allowed else "deny",
                "detail": permission.code,
            }
        )

        user_grant = (
            UserPermissionGrant.objects.filter(
                legacy_user_id=int(legacy_user.id),
                permission_id=permission.code,
            )
            .order_by("-id")
            .first()
        )
        if user_grant is None:
            result["canonical"]["user_override"] = {"exists": False, "enabled": None}
            allowed = role_allowed
            level = "role_grant"
            reason = (
                f"Grant ruolo su '{permission.code}' consente accesso."
                if role_allowed
                else f"Grant ruolo su '{permission.code}' nega accesso (o assente)."
            )
        else:
            allowed = bool(user_grant.enabled)
            level = "user_override"
            result["canonical"]["user_override"] = {
                "exists": True,
                "id": int(user_grant.id),
                "enabled": bool(user_grant.enabled),
                "legacy_user_id": int(user_grant.legacy_user_id),
                "note": user_grant.note or "",
            }
            reason = (
                f"Override utente canonico su '{permission.code}' consente accesso."
                if allowed
                else f"Override utente canonico su '{permission.code}' nega accesso."
            )
        trace.append(
            {"step": "user_override", "result": "allow" if allowed else "deny", "detail": level}
        )

        result["allowed"] = allowed
        result["decision_source"] = "canonical"
        result["decision_kind"] = "canonical"
        result["reason"] = reason
        result["canonical"]["effective_level"] = level
        return result

    trace.append({"step": "canonical_binding", "result": "missing", "detail": "fallback_legacy"})
    result["decision_source"] = "legacy_fallback"
    result["decision_kind"] = "legacy_fallback"
    legacy_diag = diagnose_permesso(legacy_user, path_norm) if include_legacy_diagnostic else None
    if legacy_diag is None:
        allowed = check_permesso(legacy_user, path_norm)
        legacy_diag = {"allowed": bool(allowed), "reason": "Fallback legacy senza diagnostica estesa."}
    else:
        allowed = bool(legacy_diag.get("allowed", False))
    result["allowed"] = bool(allowed)
    result["legacy_fallback"] = legacy_diag
    result["reason"] = (
        f"Fallback legacy: {legacy_diag.get('reason') or 'accesso consentito'}"
        if allowed
        else f"Fallback legacy: {legacy_diag.get('reason') or 'accesso negato'}"
    )
    trace.append({"step": "legacy_fallback", "result": "allow" if allowed else "deny", "detail": ""})
    return result


def check_acl_access_v2(*, path: str, legacy_user, django_user=None, request=None) -> bool:
    decision = resolve_acl_access(
        path=path,
        legacy_user=legacy_user,
        django_user=django_user,
        request=request,
        include_legacy_diagnostic=False,
    )
    return bool(decision.get("allowed", False))


def diagnose_acl_access(*, path: str, legacy_user, django_user=None, request=None) -> dict:
    return resolve_acl_access(
        path=path,
        legacy_user=legacy_user,
        django_user=django_user,
        request=request,
        include_legacy_diagnostic=True,
    )
