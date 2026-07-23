from __future__ import annotations

import re
from urllib.parse import urlsplit

from django.db import DatabaseError, transaction
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

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
    UserPermissionOverride,
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


def apply_role_grants(role_id, permissions, enabled_codes) -> tuple[int, int]:
    """Allinea i RolePermissionGrant di un ruolo su un insieme (scope) di permessi.

    Stessa semantica del ramo ``role_grants_save`` di
    ``admin_portale.acl_v2_views.acl_canonico``, ma riusabile: per ogni permesso in
    ``permissions`` (iterable di ``PermissionDefinition``) il grant viene
    creato/aggiornato a ``enabled = (code in enabled_codes)``. I permessi fuori dallo
    scope non vengono toccati. Scrive sulle stesse tabelle di ACL v2 canonico
    (``legacy_role_id`` + ``permission_code``), quindi il dato è condiviso.
    Ritorna ``(created, updated)``.
    """
    enabled_set = {normalize_permission_code(c) for c in (enabled_codes or [])}
    perms = list(permissions)
    existing = {
        g.permission_id: g
        for g in RolePermissionGrant.objects.filter(
            legacy_role_id=int(role_id),
            permission_id__in=[p.code for p in perms],
        )
    }
    created = updated = 0
    with transaction.atomic():
        for p in perms:
            desired = p.code in enabled_set
            current = existing.get(p.code)
            if current is None:
                RolePermissionGrant.objects.create(
                    legacy_role_id=int(role_id), permission_id=p.code, enabled=desired,
                )
                created += 1
            elif bool(current.enabled) != desired:
                current.enabled = desired
                current.save(update_fields=["enabled", "updated_at"])
                updated += 1
    return created, updated


def apply_user_overrides(user_id, permissions, allow_codes, deny_codes, note: str = "") -> int:
    """Allinea gli UserPermissionGrant (override per-utente) su uno scope di permessi.

    Stessa semantica del ramo ``user_overrides_bulk_save`` di ``acl_canonico``: per
    ogni permesso in ``permissions`` → ``allow`` (enabled=True) / ``deny``
    (enabled=False) / altrimenti l'override viene rimosso (eredita dal ruolo).
    Scrive sulle stesse tabelle di ACL v2 canonico. Ritorna il numero di record
    modificati.
    """
    allow = {normalize_permission_code(c) for c in (allow_codes or [])}
    deny = {normalize_permission_code(c) for c in (deny_codes or [])}
    perms = list(permissions)
    changed = 0
    with transaction.atomic():
        for p in perms:
            if p.code in allow:
                UserPermissionGrant.objects.update_or_create(
                    legacy_user_id=int(user_id), permission_id=p.code,
                    defaults={"enabled": True, "note": note},
                )
                changed += 1
            elif p.code in deny:
                UserPermissionGrant.objects.update_or_create(
                    legacy_user_id=int(user_id), permission_id=p.code,
                    defaults={"enabled": False, "note": note},
                )
                changed += 1
            else:
                deleted, _ = UserPermissionGrant.objects.filter(
                    legacy_user_id=int(user_id), permission_id=p.code,
                ).delete()
                if deleted:
                    changed += 1
    return changed


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


def _legacy_permission_parts(permission_code: str) -> tuple[str, str] | None:
    parts = normalize_permission_code(permission_code).split(".")
    if len(parts) != 3 or parts[0] != "legacy":
        return None
    modulo = parts[1].strip()
    azione = parts[2].strip()
    if not modulo or not azione:
        return None
    return modulo, azione


def evaluate_legacy_permission_code_compat(
    *,
    permission_code: str,
    legacy_role_id: int | None = None,
    legacy_user_id: int | None = None,
    legacy_user=None,
) -> dict | None:
    """Compat bridge for imported `legacy.<modulo>.<azione>` permission codes.

    Canonical grants remain authoritative when present. This helper is used only
    when a canonical role grant is absent, so old `permessi` rows can still back
    legacy-imported route bindings during the migration window.
    """
    parts = _legacy_permission_parts(permission_code)
    if parts is None:
        return None
    modulo, azione = parts
    if legacy_role_id is None and legacy_user is not None:
        legacy_role_id = getattr(legacy_user, "ruolo_id", None)
    if legacy_user_id is None and legacy_user is not None:
        legacy_user_id = getattr(legacy_user, "id", None)
    if not legacy_role_id:
        return {
            "exists": False,
            "enabled": None,
            "source": "legacy_permesso",
            "reason": "Ruolo legacy mancante: compat permessi non applicabile.",
            "modulo": modulo,
            "azione": azione,
        }

    try:
        if legacy_user_id:
            override = UserPermissionOverride.objects.filter(
                legacy_user_id=int(legacy_user_id),
                modulo__iexact=modulo,
                azione__iexact=azione,
            ).first()
            if override is not None and override.can_view is not None:
                return {
                    "exists": True,
                    "enabled": bool(override.can_view),
                    "source": "legacy_user_override",
                    "reason": (
                        "Override utente legacy consente accesso."
                        if override.can_view
                        else "Override utente legacy nega accesso."
                    ),
                    "modulo": modulo,
                    "azione": azione,
                    "legacy_user_id": int(legacy_user_id),
                }

        from core.legacy_models import Permesso

        perm = (
            Permesso.objects.filter(
                ruolo_id=int(legacy_role_id),
                modulo__iexact=modulo,
                azione__iexact=azione,
            )
            .order_by("-id")
            .first()
        )
    except DatabaseError as exc:
        return {
            "exists": False,
            "enabled": None,
            "source": "legacy_permesso",
            "reason": f"Errore DB durante compat permessi legacy: {exc}",
            "modulo": modulo,
            "azione": azione,
            "db_error": str(exc),
        }

    if perm is None:
        return {
            "exists": False,
            "enabled": None,
            "source": "legacy_permesso",
            "reason": "Nessun record legacy permessi compatibile trovato.",
            "modulo": modulo,
            "azione": azione,
            "legacy_role_id": int(legacy_role_id),
        }

    enabled = bool(getattr(perm, "can_view", None)) or bool(getattr(perm, "consentito", None))
    return {
        "exists": True,
        "enabled": enabled,
        "source": "legacy_permesso",
        "reason": (
            "Permesso legacy compatibile consente accesso."
            if enabled
            else "Permesso legacy compatibile trovato ma non abilita can_view/consentito."
        ),
        "modulo": modulo,
        "azione": azione,
        "legacy_role_id": int(legacy_role_id),
        "permesso_id": int(perm.id),
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


def _binding_path_sort_key(binding: RoutePermissionBinding) -> tuple[int, int, int, int]:
    strategy = (binding.match_strategy or RoutePermissionBinding.MATCH_EXACT).lower()
    if strategy == RoutePermissionBinding.MATCH_EXACT:
        strategy_rank = 0
        pattern = normalize_binding_path_pattern(binding.path_pattern, for_regex=False)
    elif strategy == RoutePermissionBinding.MATCH_PREFIX:
        strategy_rank = 1
        pattern = normalize_binding_path_pattern(binding.path_pattern, for_regex=False)
    else:
        strategy_rank = 2
        pattern = str(binding.path_pattern or "")
    return (
        int(getattr(binding, "priority", 0) or 0),
        strategy_rank,
        -len(pattern),
        int(getattr(binding, "id", 0) or 0),
    )


def _find_canonical_binding(
    *,
    route_name: str,
    path_norm: str,
    bindings: list[RoutePermissionBinding] | None = None,
) -> tuple[RoutePermissionBinding | None, str]:
    """Risolve il binding canonico effettivo per route_name/path.

    Se ``bindings`` è fornito (lista di binding gia caricati in memoria, es. da
    una vista che deve risolvere molte route) la risoluzione avviene senza query:
    stessa logica di selezione, zero round-trip al DB. La logica di matching e di
    priorita resta unica per evitare divergenze di comportamento tra i due rami.
    Il chiamante deve passare binding con ``permission`` gia in select_related.
    """
    if bindings is None:
        by_route = None

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
        path_matches: list[RoutePermissionBinding] = []
        for candidate in path_candidates:
            if _binding_matches_path(candidate, path_norm):
                path_matches.append(candidate)
        by_path = min(path_matches, key=_binding_path_sort_key) if path_matches else None
        if by_path is not None:
            return by_path, "path_pattern"
        return None, ""

    # Ramo in-memory: stessa semantica del ramo DB, ma sul set pre-caricato.
    route_name_lower = str(route_name or "").lower()
    if route_name_lower:
        route_matches = [
            binding
            for binding in bindings
            if getattr(binding, "is_active", True)
            and str(binding.route_name or "").lower() == route_name_lower
        ]
        if route_matches:
            by_route = min(
                route_matches,
                key=lambda binding: (
                    int(getattr(binding, "priority", 0) or 0),
                    int(getattr(binding, "id", 0) or 0),
                ),
            )
            return by_route, "route_name"

    path_matches = [
        binding
        for binding in bindings
        if getattr(binding, "is_active", True)
        and str(binding.path_pattern or "").strip()
        and _binding_matches_path(binding, path_norm)
    ]
    if path_matches:
        return min(path_matches, key=_binding_path_sort_key), "path_pattern"
    return None, ""


def evaluate_permission_code_access(
    *,
    permission_code: str,
    legacy_role_id: int | None = None,
    legacy_user_id: int | None = None,
    legacy_user=None,
    django_user=None,
    allow_superuser: bool = True,
    allow_legacy_admin: bool = True,
) -> dict:
    permission_code = normalize_permission_code(permission_code)
    result = {
        "allowed": False,
        "permission_code": permission_code,
        "decision_source": "deny",
        "reason": "",
        "permission": None,
        "role_grant": None,
        "user_override": None,
        "legacy_compat": None,
        "effective_level": None,
    }
    if not permission_code:
        result["reason"] = "Permission code mancante."
        return result

    if allow_superuser and bool(getattr(django_user, "is_superuser", False)):
        result["allowed"] = True
        result["decision_source"] = "superuser_bypass"
        result["reason"] = "Utente Django superuser: bypass ACL."
        result["effective_level"] = "superuser_bypass"
        return result

    if allow_legacy_admin and legacy_user and is_legacy_admin(legacy_user):
        result["allowed"] = True
        result["decision_source"] = "legacy_admin_bypass"
        result["reason"] = "Utente riconosciuto come admin legacy: bypass ACL."
        result["effective_level"] = "legacy_admin_bypass"
        return result

    if legacy_role_id is None and legacy_user is not None:
        legacy_role_id = getattr(legacy_user, "ruolo_id", None)
    if legacy_user_id is None and legacy_user is not None:
        legacy_user_id = getattr(legacy_user, "id", None)

    permission = PermissionDefinition.objects.filter(code=permission_code).first()
    if permission is None:
        result["decision_source"] = "permission_missing"
        result["reason"] = f"Permission '{permission_code}' non trovata."
        return result

    result["permission"] = _serialize_permission(permission)
    if not bool(permission.is_active):
        result["decision_source"] = "permission_inactive"
        result["reason"] = f"Permission '{permission.code}' trovata ma disattiva."
        return result

    role_allowed = False
    if legacy_role_id:
        role_grant = (
            RolePermissionGrant.objects.filter(
                legacy_role_id=int(legacy_role_id),
                permission_id=permission.code,
            )
            .order_by("-id")
            .first()
        )
        if role_grant is None:
            result["role_grant"] = {"exists": False, "enabled": None}
        else:
            role_allowed = bool(role_grant.enabled)
            result["role_grant"] = {
                "exists": True,
                "id": int(role_grant.id),
                "enabled": bool(role_grant.enabled),
                "legacy_role_id": int(role_grant.legacy_role_id),
                "note": role_grant.note or "",
            }
    else:
        result["role_grant"] = {"exists": False, "enabled": None}

    if legacy_user_id:
        user_grant = (
            UserPermissionGrant.objects.filter(
                legacy_user_id=int(legacy_user_id),
                permission_id=permission.code,
            )
            .order_by("-id")
            .first()
        )
    else:
        user_grant = None

    if user_grant is None:
        result["user_override"] = {"exists": False, "enabled": None}
        if not role_allowed and result["role_grant"].get("exists") is False:
            legacy_compat = evaluate_legacy_permission_code_compat(
                permission_code=permission.code,
                legacy_role_id=legacy_role_id,
                legacy_user_id=legacy_user_id,
                legacy_user=legacy_user,
            )
            if legacy_compat is not None:
                result["legacy_compat"] = legacy_compat
                result["allowed"] = bool(legacy_compat.get("enabled", False))
                result["decision_source"] = "canonical_permission"
                result["effective_level"] = str(legacy_compat.get("source") or "legacy_compat")
                result["reason"] = str(legacy_compat.get("reason") or "")
                return result
        result["allowed"] = bool(role_allowed)
        result["decision_source"] = "canonical_permission"
        result["effective_level"] = "role_grant"
        result["reason"] = (
            f"Grant ruolo su '{permission.code}' consente accesso."
            if role_allowed
            else f"Grant ruolo su '{permission.code}' nega accesso (o assente)."
        )
        return result

    result["user_override"] = {
        "exists": True,
        "id": int(user_grant.id),
        "enabled": bool(user_grant.enabled),
        "legacy_user_id": int(user_grant.legacy_user_id),
        "note": user_grant.note or "",
    }
    result["allowed"] = bool(user_grant.enabled)
    result["decision_source"] = "canonical_permission"
    result["effective_level"] = "user_override"
    result["reason"] = (
        f"Override utente canonico su '{permission.code}' consente accesso."
        if user_grant.enabled
        else f"Override utente canonico su '{permission.code}' nega accesso."
    )
    return result


def resolve_canonical_target(
    *,
    path: str | None = None,
    route_name: str | None = None,
    request=None,
    bindings: list[RoutePermissionBinding] | None = None,
) -> dict:
    resolved_route_name = str(route_name or "").strip()
    path_input = str(path or "").strip()
    if not path_input and resolved_route_name:
        try:
            path_input = reverse(resolved_route_name)
        except NoReverseMatch:
            path_input = "/"
    if not path_input:
        path_input = "/"
    path_norm = normalize_acl_path(path_input)
    if not resolved_route_name:
        resolved_route_name = resolve_route_name(path_norm, request=request)
    binding, matched_by = _find_canonical_binding(
        route_name=resolved_route_name, path_norm=path_norm, bindings=bindings
    )
    permission = binding.permission if binding is not None else None
    return {
        "path_input": path_input,
        "path_normalized": path_norm,
        "route_name": resolved_route_name,
        "binding_found": binding is not None,
        "binding": _serialize_binding(binding, matched_by=matched_by),
        "permission": _serialize_permission(permission),
    }


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
            "legacy_compat": None,
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
            legacy_compat = None
            if not role_allowed and role_grant is None:
                legacy_compat = evaluate_legacy_permission_code_compat(
                    permission_code=permission.code,
                    legacy_role_id=ruolo_id,
                    legacy_user_id=getattr(legacy_user, "id", None),
                    legacy_user=legacy_user,
                )
            if legacy_compat is not None:
                result["canonical"]["legacy_compat"] = legacy_compat
                allowed = bool(legacy_compat.get("enabled", False))
                level = str(legacy_compat.get("source") or "legacy_compat")
                reason = str(legacy_compat.get("reason") or "")
            else:
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
