from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from admin_portale.decorators import legacy_admin_required
from core.acl_v2 import (
    PERMISSION_CODE_FORMAT_HINT,
    normalize_binding_path_pattern,
    normalize_permission_code,
    permission_code_naming_warning,
    validate_permission_code,
)
from core.legacy_models import AnagraficaDipendente, Pulsante, Ruolo, UtenteLegacy
from core.models import (
    LegacyRedirect,
    NavigationItem,
    NavigationRoleAccess,
    PermissionDefinition,
    RolePermissionGrant,
    RoutePermissionBinding,
    UserNavigationOverride,
    UserPermissionGrant,
)

STATUS_CANONICAL_BOUND = "CANONICAL_BOUND"
STATUS_LEGACY_FALLBACK = "LEGACY_FALLBACK"
STATUS_UNBOUND = "UNBOUND"
STATUS_COMING_SOON_EXCLUDED = "COMING_SOON_EXCLUDED"
STATUS_REDIRECT_ONLY = "REDIRECT_ONLY"
ROUTE_STATUS_CHOICES = (
    STATUS_CANONICAL_BOUND,
    STATUS_LEGACY_FALLBACK,
    STATUS_UNBOUND,
    STATUS_COMING_SOON_EXCLUDED,
    STATUS_REDIRECT_ONLY,
)
ROUTE_STATUS_LABELS = {
    STATUS_CANONICAL_BOUND: "Canonical Bound",
    STATUS_LEGACY_FALLBACK: "Legacy Fallback",
    STATUS_UNBOUND: "Unbound",
    STATUS_COMING_SOON_EXCLUDED: "Coming Soon / Excluded",
    STATUS_REDIRECT_ONLY: "Redirect Only",
}
_COMING_ROUTE_RE = re.compile(r"(^|:)coming[_-]", re.IGNORECASE)


def _int_or_none(value) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _selected_role_id(request, roles: list[dict]) -> int | None:
    source = request.POST if request.method == "POST" else request.GET
    requested = _int_or_none(source.get("role_id"))
    valid_ids = {int(r["id"]) for r in roles}
    if requested in valid_ids:
        return requested
    return int(roles[0]["id"]) if roles else None


def _redirect_to_acl_canonico(role_id: int | None, *, tab: str = "", selected_user_id: int | None = None):
    base = reverse("admin_portale:acl_canonico")
    params: dict[str, str] = {}
    if role_id is not None:
        params["role_id"] = str(role_id)
    if tab:
        params["tab"] = tab
    if selected_user_id is not None:
        params["selected_user_id"] = str(selected_user_id)
    if not params:
        return redirect(base)
    query = "&".join([f"{key}={value}" for key, value in params.items()])
    return redirect(f"{base}?{query}")


def _build_user_override_rows(
    permissions: list,
    role_grants: dict[str, bool],
    user_grants: dict[str, bool],
) -> list[dict]:
    """Costruisce righe per la griglia override utente (stile flag-toggle 4 stati)."""
    rows = []
    for perm in permissions:
        role_allowed = role_grants.get(perm.code)  # True/False/None
        override = user_grants.get(perm.code)       # True/False/None (None = no override)
        if override is None:
            state = "role-on" if role_allowed else "role-off"
        elif override:
            state = "ov-on"
        else:
            state = "ov-off"
        rows.append({
            "permission": perm,
            "role_allowed": role_allowed,
            "override": override,
            "state": state,
        })
    return rows


def _route_catalog() -> list[dict]:
    resolver = get_resolver()
    rows: list[dict] = []

    def walk(patterns, prefix: str = "", namespace_prefix: str = ""):
        for pattern in patterns:
            if isinstance(pattern, URLPattern):
                route = prefix + str(pattern.pattern)
                view_name = getattr(pattern, "name", None)
                if not view_name:
                    continue
                if namespace_prefix:
                    full_view_name = f"{namespace_prefix}:{view_name}"
                else:
                    full_view_name = str(view_name)
                route_display = "/" + route.lstrip("/")
                if route_display != "/":
                    route_display = route_display.rstrip("/")
                rows.append(
                    {
                        "view_name": full_view_name,
                        "route": route_display or "/",
                    }
                )
            elif isinstance(pattern, URLResolver):
                ns = getattr(pattern, "namespace", None)
                next_ns = namespace_prefix
                if ns:
                    next_ns = f"{namespace_prefix}:{ns}" if namespace_prefix else str(ns)
                walk(
                    pattern.url_patterns,
                    prefix=prefix + str(pattern.pattern),
                    namespace_prefix=next_ns,
                )

    walk(resolver.url_patterns)
    rows.sort(key=lambda row: (row["view_name"], row["route"]))
    return rows


def _permissions_for_role(role_id: int | None) -> dict[str, bool]:
    if role_id is None:
        return {}
    rows = RolePermissionGrant.objects.filter(legacy_role_id=role_id).values_list("permission_id", "enabled")
    return {str(code): bool(enabled) for code, enabled in rows}


def _normalize_app_label(route_name: str, path: str) -> str:
    route_name = str(route_name or "").strip()
    if ":" in route_name:
        return route_name.split(":", 1)[0].strip() or "core"
    pieces = [p for p in str(path or "").split("/") if p]
    if pieces:
        return pieces[0]
    return "core"


def _binding_matches_path(binding: RoutePermissionBinding, path_norm: str) -> bool:
    strategy = (binding.match_strategy or RoutePermissionBinding.MATCH_EXACT).lower()
    if strategy == RoutePermissionBinding.MATCH_REGEX:
        try:
            return re.search(binding.path_pattern or "", path_norm) is not None
        except re.error:
            return False
    pattern = normalize_binding_path_pattern(
        binding.path_pattern,
        for_regex=(strategy == RoutePermissionBinding.MATCH_REGEX),
    )
    if not pattern:
        return False
    if strategy == RoutePermissionBinding.MATCH_PREFIX:
        return path_norm == pattern or path_norm.startswith(pattern + "/")
    return path_norm == pattern


def _legacy_acl_catalog() -> tuple[set[str], list[str]]:
    route_names: set[str] = set()
    path_patterns: set[str] = set()
    try:
        rows = list(Pulsante.objects.all().values("url"))
    except DatabaseError:
        return route_names, []
    for row in rows:
        raw_url = str(row.get("url") or "").strip()
        lower_url = raw_url.lower()
        if lower_url.startswith("route:") or lower_url.startswith("django:"):
            _, route_name = raw_url.split(":", 1)
            route_name = route_name.strip()
            if route_name:
                route_names.add(route_name)
            continue
        path = normalize_binding_path_pattern(raw_url)
        if path:
            path_patterns.add(path)
    return route_names, sorted(path_patterns, key=len, reverse=True)


def _redirect_target_catalog() -> tuple[set[str], set[str]]:
    route_targets: set[str] = set()
    path_targets: set[str] = set()
    try:
        redirects = list(LegacyRedirect.objects.filter(is_enabled=True).values("target_route_name", "target_url_path"))
    except DatabaseError:
        return route_targets, path_targets
    for row in redirects:
        route_name = str(row.get("target_route_name") or "").strip()
        url_path = str(row.get("target_url_path") or "").strip()
        if route_name:
            route_targets.add(route_name)
        if url_path.startswith("/"):
            path_targets.add(normalize_binding_path_pattern(url_path))
    return route_targets, path_targets


def _is_coming_or_excluded_route(route_name: str, path_norm: str) -> tuple[bool, str]:
    route_name_norm = str(route_name or "").strip()
    if _COMING_ROUTE_RE.search(route_name_norm):
        return True, "COMING_SOON_ROUTE"
    excluded_route_prefixes = (
        "admin:",
        "django_prometheus:",
        "silk:",
        "debug_toolbar:",
        "admin_portale:api_",
    )
    if any(route_name_norm.startswith(prefix) for prefix in excluded_route_prefixes):
        return True, "EXCLUDED_INTERNAL_ROUTE"
    if route_name_norm in {"login", "logout", "password_change", "password_reset"}:
        return True, "EXCLUDED_AUTH_ROUTE"
    if path_norm in {"/health", "/health/", "/admin-portale/health", "/admin-portale/health/"}:
        return True, "EXCLUDED_HEALTHCHECK_ROUTE"
    return False, ""


def _route_has_legacy_coverage(route_name: str, path_norm: str, legacy_route_names: set[str], legacy_paths: list[str]) -> bool:
    if route_name and route_name in legacy_route_names:
        return True
    for legacy_path in legacy_paths:
        if path_norm == legacy_path:
            return True
        if legacy_path and legacy_path != "/" and path_norm.startswith(legacy_path + "/"):
            return True
    return False


def _collect_route_coverage_rows() -> tuple[list[dict], dict]:
    catalog = _route_catalog()
    legacy_route_names, legacy_paths = _legacy_acl_catalog()
    redirect_route_targets, redirect_path_targets = _redirect_target_catalog()

    try:
        active_bindings = list(
            RoutePermissionBinding.objects.filter(is_active=True)
            .select_related("permission")
            .order_by("priority", "id")
        )
    except DatabaseError:
        active_bindings = []
    route_bindings_map: dict[str, list[RoutePermissionBinding]] = defaultdict(list)
    path_bindings: list[RoutePermissionBinding] = []
    for binding in active_bindings:
        route_name = str(binding.route_name or "").strip().lower()
        if route_name:
            route_bindings_map[route_name].append(binding)
        if str(binding.path_pattern or "").strip():
            path_bindings.append(binding)

    try:
        enabled_permission_codes = set(
            RolePermissionGrant.objects.filter(enabled=True).values_list("permission_id", flat=True)
        )
    except DatabaseError:
        enabled_permission_codes = set()

    rows: list[dict] = []
    for route in catalog:
        route_name = str(route["view_name"] or "").strip()
        path_norm = normalize_binding_path_pattern(str(route["route"] or "/"))
        app_label = _normalize_app_label(route_name, path_norm)
        canonical_matches: list[RoutePermissionBinding] = []
        canonical_matches.extend(route_bindings_map.get(route_name.lower(), []))
        for candidate in path_bindings:
            if _binding_matches_path(candidate, path_norm):
                canonical_matches.append(candidate)
        canonical_binding_ids = sorted({int(binding.id) for binding in canonical_matches})
        canonical_permissions = sorted({str(binding.permission_id) for binding in canonical_matches if binding.permission_id})
        canonical_missing_grant = any(code not in enabled_permission_codes for code in canonical_permissions)
        has_legacy = _route_has_legacy_coverage(route_name, path_norm, legacy_route_names, legacy_paths)
        has_redirect = bool(
            (route_name and route_name in redirect_route_targets) or (path_norm and path_norm in redirect_path_targets)
        )
        is_excluded, excluded_reason = _is_coming_or_excluded_route(route_name, path_norm)

        if is_excluded:
            status = STATUS_COMING_SOON_EXCLUDED
        elif canonical_binding_ids:
            status = STATUS_CANONICAL_BOUND
        elif has_legacy:
            status = STATUS_LEGACY_FALLBACK
        elif has_redirect:
            status = STATUS_REDIRECT_ONLY
        else:
            status = STATUS_UNBOUND

        warnings: list[str] = []
        if canonical_missing_grant:
            warnings.append("BINDING_WITHOUT_ENABLED_ROLE_GRANT")
        if len(canonical_binding_ids) > 1:
            warnings.append("AMBIGUOUS_CANONICAL_BINDING")

        rows.append(
            {
                "route_name": route_name,
                "path_normalized": path_norm,
                "app_label": app_label,
                "status": status,
                "status_label": ROUTE_STATUS_LABELS[status],
                "canonical_binding_ids": canonical_binding_ids,
                "canonical_binding_count": len(canonical_binding_ids),
                "canonical_permissions": canonical_permissions,
                "canonical_missing_grant": canonical_missing_grant,
                "has_legacy": has_legacy,
                "has_redirect": has_redirect,
                "is_excluded": is_excluded,
                "excluded_reason": excluded_reason,
                "warnings": warnings,
            }
        )

    path_counter = Counter(row["path_normalized"] for row in rows)
    for row in rows:
        duplicate_count = int(path_counter.get(row["path_normalized"], 0))
        row["duplicate_path_count"] = duplicate_count
        row["has_duplicate_path"] = duplicate_count > 1
        if row["has_duplicate_path"]:
            row["warnings"].append("DUPLICATE_ROUTE_PATH")

    rows.sort(key=lambda row: (row["app_label"], row["route_name"], row["path_normalized"]))
    summary = {
        "total": len(rows),
        "canonical_bound": sum(1 for row in rows if row["status"] == STATUS_CANONICAL_BOUND),
        "legacy_fallback": sum(1 for row in rows if row["status"] == STATUS_LEGACY_FALLBACK),
        "unbound": sum(1 for row in rows if row["status"] == STATUS_UNBOUND),
        "coming_or_excluded": sum(1 for row in rows if row["status"] == STATUS_COMING_SOON_EXCLUDED),
        "redirect_only": sum(1 for row in rows if row["status"] == STATUS_REDIRECT_ONLY),
        "ambiguous": sum(1 for row in rows if "AMBIGUOUS_CANONICAL_BINDING" in row["warnings"]),
        "duplicate_path": sum(1 for row in rows if row["has_duplicate_path"]),
        "missing_grant": sum(1 for row in rows if row["canonical_missing_grant"]),
    }
    return rows, summary


def _filter_route_coverage_rows(
    *,
    rows: list[dict],
    status_filter: str,
    app_filter: str,
    q_filter: str,
    only_warnings: bool,
) -> list[dict]:
    status_filter_norm = str(status_filter or "all").strip().upper()
    app_filter_norm = str(app_filter or "").strip().lower()
    q_norm = str(q_filter or "").strip().lower()
    filtered: list[dict] = []
    for row in rows:
        if status_filter_norm != "ALL" and row["status"] != status_filter_norm:
            continue
        if app_filter_norm and row["app_label"].lower() != app_filter_norm:
            continue
        if only_warnings and not row["warnings"]:
            continue
        if q_norm:
            blob = " ".join(
                [
                    row["route_name"],
                    row["path_normalized"],
                    row["app_label"],
                    row["status"],
                    " ".join(row["canonical_permissions"]),
                    " ".join(row["warnings"]),
                ]
            ).lower()
            if q_norm not in blob:
                continue
        filtered.append(row)
    return filtered


def _permission_grant_stats() -> tuple[dict[str, int], dict[str, int]]:
    enabled_counts: dict[str, int] = defaultdict(int)
    total_counts: dict[str, int] = defaultdict(int)
    rows = RolePermissionGrant.objects.all().values_list("permission_id", "enabled")
    for permission_code, enabled in rows:
        permission_code = str(permission_code)
        total_counts[permission_code] += 1
        if bool(enabled):
            enabled_counts[permission_code] += 1
    return dict(enabled_counts), dict(total_counts)


def _group_permission_rows_by_module(permission_rows: list) -> list[dict]:
    """Raggruppa permission_rows per modulo, calcola stato aggregato per la card header."""
    grouped: dict[str, list] = defaultdict(list)
    for row in permission_rows:
        module = row["permission"].module or "—"
        grouped[module].append(row)
    result = []
    for module, rows in sorted(grouped.items()):
        granted_count = sum(1 for r in rows if r["granted"])
        all_granted = granted_count == len(rows)
        any_granted = granted_count > 0
        result.append({
            "module": module,
            "rows": rows,
            "granted_count": granted_count,
            "total_count": len(rows),
            "all_granted": all_granted,
            "partial": any_granted and not all_granted,
            "any_granted": any_granted,
        })
    return result


@legacy_admin_required
@require_http_methods(["GET", "POST"])
def acl_canonico(request):
    try:
        roles = list(Ruolo.objects.all().order_by("nome").values("id", "nome"))
    except DatabaseError:
        roles = []
    selected_role_id = _selected_role_id(request, roles)

    if request.method == "POST":
        action = str(request.POST.get("action") or "").strip()
        tab = str(request.POST.get("tab") or "").strip()

        if action == "permission_upsert":
            code_raw = str(request.POST.get("code") or "").strip()
            code = normalize_permission_code(code_raw)
            label = str(request.POST.get("label") or "").strip()
            module = str(request.POST.get("module") or "").strip().lower()
            description = str(request.POST.get("description") or "").strip()
            is_active = str(request.POST.get("is_active") or "1").strip() != "0"

            is_valid_code, validation_message = validate_permission_code(code)
            if not is_valid_code:
                messages.error(request, validation_message)
                return _redirect_to_acl_canonico(selected_role_id, tab=tab)
            if not label:
                messages.error(request, "Compila la label del permission code.")
                return _redirect_to_acl_canonico(selected_role_id, tab=tab)
            if not module:
                module = code.split(".", 1)[0]

            try:
                instance = PermissionDefinition.objects.filter(code=code).first()
                if instance is None:
                    instance = PermissionDefinition(code=code)
                instance.label = label
                instance.module = module
                instance.description = description
                instance.is_active = is_active
                instance.full_clean()
                instance.save()
            except ValidationError as exc:
                messages.error(request, f"Permission code non valido: {exc}")
                return _redirect_to_acl_canonico(selected_role_id, tab=tab)
            naming_warning = permission_code_naming_warning(code)
            if naming_warning:
                messages.warning(request, naming_warning)
            messages.success(request, f"Permesso canonico salvato: {code}.")
            return _redirect_to_acl_canonico(selected_role_id, tab=tab)

        if action == "binding_upsert":
            binding_id = _int_or_none(request.POST.get("binding_id"))
            permission_code = normalize_permission_code(str(request.POST.get("permission_code") or "").strip())
            route_name = str(request.POST.get("route_name") or "").strip()
            path_pattern_raw = str(request.POST.get("path_pattern") or "").strip()
            match_strategy = str(request.POST.get("match_strategy") or RoutePermissionBinding.MATCH_EXACT).strip().lower()
            if match_strategy not in {
                RoutePermissionBinding.MATCH_EXACT,
                RoutePermissionBinding.MATCH_PREFIX,
                RoutePermissionBinding.MATCH_REGEX,
            }:
                match_strategy = RoutePermissionBinding.MATCH_EXACT
            path_pattern = normalize_binding_path_pattern(
                path_pattern_raw,
                for_regex=(match_strategy == RoutePermissionBinding.MATCH_REGEX),
            )
            source_app = str(request.POST.get("source_app") or "").strip()
            note = str(request.POST.get("note") or "").strip()
            priority = _int_or_none(request.POST.get("priority"))
            is_active = str(request.POST.get("is_active") or "1").strip() != "0"

            is_valid_code, validation_message = validate_permission_code(permission_code)
            if not is_valid_code:
                messages.error(request, validation_message)
                return _redirect_to_acl_canonico(selected_role_id, tab=tab)
            if not PermissionDefinition.objects.filter(code=permission_code).exists():
                messages.error(request, f"Permission code non trovato: {permission_code}.")
                return _redirect_to_acl_canonico(selected_role_id, tab=tab)
            if not route_name and not path_pattern:
                messages.error(request, "Specifica almeno route_name o path_pattern.")
                return _redirect_to_acl_canonico(selected_role_id, tab=tab)
            if not source_app:
                source_app = route_name.split(":", 1)[0] if ":" in route_name else (route_name or "legacy")

            payload = {
                "permission_id": permission_code,
                "route_name": route_name,
                "path_pattern": path_pattern,
                "match_strategy": match_strategy,
                "source_app": source_app,
                "note": note,
                "priority": priority if priority is not None else 100,
                "is_active": is_active,
            }

            try:
                if binding_id is None:
                    instance = RoutePermissionBinding(**payload)
                else:
                    instance = get_object_or_404(RoutePermissionBinding, id=binding_id)
                    for key, value in payload.items():
                        setattr(instance, key, value)
                instance.full_clean()
                instance.save()
                if binding_id is None:
                    messages.success(request, "Binding route/path -> permission creato.")
                else:
                    messages.success(request, f"Binding #{binding_id} aggiornato.")
            except Exception as exc:
                messages.error(request, f"Errore salvataggio binding: {exc}")
            return _redirect_to_acl_canonico(selected_role_id, tab=tab)

        if action == "binding_delete":
            binding_id = _int_or_none(request.POST.get("binding_id"))
            if binding_id is None:
                messages.error(request, "ID binding mancante.")
                return _redirect_to_acl_canonico(selected_role_id, tab=tab)
            deleted, _ = RoutePermissionBinding.objects.filter(id=binding_id).delete()
            if deleted:
                messages.success(request, f"Binding #{binding_id} eliminato.")
            else:
                messages.warning(request, f"Binding #{binding_id} non trovato.")
            return _redirect_to_acl_canonico(selected_role_id, tab=tab)

        if action == "role_grants_save":
            role_id = _int_or_none(request.POST.get("role_id"))
            if role_id is None:
                messages.error(request, "Ruolo non valido.")
                return _redirect_to_acl_canonico(selected_role_id, tab=tab)
            selected_codes = {normalize_permission_code(code) for code in request.POST.getlist("grants")}
            permissions = list(PermissionDefinition.objects.all().order_by("module", "code"))
            existing = {
                grant.permission_id: grant
                for grant in RolePermissionGrant.objects.filter(
                    legacy_role_id=role_id,
                    permission_id__in=[p.code for p in permissions],
                )
            }
            created = 0
            updated = 0
            with transaction.atomic():
                for permission in permissions:
                    desired = permission.code in selected_codes
                    current = existing.get(permission.code)
                    if current is None:
                        RolePermissionGrant.objects.create(
                            legacy_role_id=role_id,
                            permission_id=permission.code,
                            enabled=desired,
                        )
                        created += 1
                    elif bool(current.enabled) != desired:
                        current.enabled = desired
                        current.save(update_fields=["enabled", "updated_at"])
                        updated += 1
            messages.success(
                request,
                f"Grant ruolo aggiornati (role_id={role_id}): creati {created}, modificati {updated}.",
            )
            return _redirect_to_acl_canonico(role_id, tab=tab)

        if action == "user_override_upsert":
            legacy_user_id = _int_or_none(request.POST.get("legacy_user_id"))
            permission_code = normalize_permission_code(str(request.POST.get("permission_code") or "").strip())
            enabled = str(request.POST.get("enabled") or "1").strip() != "0"
            note = str(request.POST.get("note") or "").strip()
            is_valid_code, validation_message = validate_permission_code(permission_code)
            if legacy_user_id is None or not is_valid_code:
                messages.error(request, validation_message or "Compila legacy_user_id e permission_code.")
                return _redirect_to_acl_canonico(selected_role_id, tab=tab)
            if not PermissionDefinition.objects.filter(code=permission_code).exists():
                messages.error(request, f"Permission code non trovato: {permission_code}.")
                return _redirect_to_acl_canonico(selected_role_id, tab=tab)
            UserPermissionGrant.objects.update_or_create(
                legacy_user_id=legacy_user_id,
                permission_id=permission_code,
                defaults={"enabled": enabled, "note": note},
            )
            messages.success(
                request,
                f"Override utente salvato: user={legacy_user_id}, permission={permission_code}.",
            )
            return _redirect_to_acl_canonico(selected_role_id, tab=tab)

        if action == "user_override_delete":
            override_id = _int_or_none(request.POST.get("override_id"))
            if override_id is None:
                messages.error(request, "ID override mancante.")
                return _redirect_to_acl_canonico(selected_role_id, tab=tab)
            deleted, _ = UserPermissionGrant.objects.filter(id=override_id).delete()
            if deleted:
                messages.success(request, f"Override #{override_id} eliminato.")
            else:
                messages.warning(request, f"Override #{override_id} non trovato.")
            return _redirect_to_acl_canonico(selected_role_id, tab=tab)

        if action == "user_overrides_bulk_save":
            legacy_user_id = _int_or_none(request.POST.get("legacy_user_id"))
            note = str(request.POST.get("note") or "").strip()
            if legacy_user_id is None:
                messages.error(request, "Utente non valido.")
                return _redirect_to_acl_canonico(selected_role_id, tab=tab, selected_user_id=None)
            allow_codes = set(request.POST.getlist("ov_allow"))
            deny_codes = set(request.POST.getlist("ov_deny"))
            all_permissions = list(PermissionDefinition.objects.filter(is_active=True))
            changed = 0
            with transaction.atomic():
                for perm in all_permissions:
                    if perm.code in allow_codes:
                        _, created = UserPermissionGrant.objects.update_or_create(
                            legacy_user_id=legacy_user_id,
                            permission_id=perm.code,
                            defaults={"enabled": True, "note": note},
                        )
                        changed += 1
                    elif perm.code in deny_codes:
                        _, created = UserPermissionGrant.objects.update_or_create(
                            legacy_user_id=legacy_user_id,
                            permission_id=perm.code,
                            defaults={"enabled": False, "note": note},
                        )
                        changed += 1
                    else:
                        deleted_count, _ = UserPermissionGrant.objects.filter(
                            legacy_user_id=legacy_user_id,
                            permission_id=perm.code,
                        ).delete()
                        if deleted_count:
                            changed += 1
            messages.success(request, f"Override utente aggiornati: {changed} permessi modificati.")
            return _redirect_to_acl_canonico(selected_role_id, tab=tab, selected_user_id=legacy_user_id)

        if action == "user_overrides_clear":
            legacy_user_id = _int_or_none(request.POST.get("legacy_user_id"))
            if legacy_user_id is None:
                messages.error(request, "Utente non valido.")
                return _redirect_to_acl_canonico(selected_role_id, tab=tab)
            deleted, _ = UserPermissionGrant.objects.filter(legacy_user_id=legacy_user_id).delete()
            messages.success(request, f"Rimossi tutti gli override per utente #{legacy_user_id} ({deleted} record).")
            return _redirect_to_acl_canonico(selected_role_id, tab=tab, selected_user_id=legacy_user_id)

        if action == "nav_overrides_clear":
            legacy_user_id = _int_or_none(request.POST.get("legacy_user_id"))
            if legacy_user_id is None:
                messages.error(request, "Utente non valido.")
                return _redirect_to_acl_canonico(selected_role_id, tab="nav-overrides")
            from core.navigation_registry import bump_navigation_registry_version
            deleted, _ = UserNavigationOverride.objects.filter(legacy_user_id=legacy_user_id).delete()
            bump_navigation_registry_version()
            messages.success(request, f"Rimossi tutti gli override navigazione per utente #{legacy_user_id} ({deleted} record).")
            return _redirect_to_acl_canonico(selected_role_id, tab="nav-overrides", selected_user_id=legacy_user_id)

        messages.warning(request, "Azione non riconosciuta.")
        return _redirect_to_acl_canonico(selected_role_id, tab=tab)

    q_filter = str(request.GET.get("q") or "").strip()
    module_filter = str(request.GET.get("module") or "").strip().lower()
    permission_state = str(request.GET.get("permission_state") or "all").strip().lower()
    binding_state = str(request.GET.get("binding_state") or "all").strip().lower()
    active_tab = str(request.GET.get("tab") or "permissions").strip().lower()
    if active_tab not in {"permissions", "bindings", "grants", "overrides", "nav-overrides"}:
        active_tab = "permissions"

    permission_qs = PermissionDefinition.objects.all().order_by("module", "code")
    if module_filter:
        permission_qs = permission_qs.filter(module__iexact=module_filter)
    if q_filter:
        permission_qs = permission_qs.filter(
            Q(code__icontains=q_filter)
            | Q(label__icontains=q_filter)
            | Q(module__icontains=q_filter)
            | Q(description__icontains=q_filter)
        )
    if permission_state == "active":
        permission_qs = permission_qs.filter(is_active=True)
    elif permission_state == "inactive":
        permission_qs = permission_qs.filter(is_active=False)
    permissions = list(permission_qs)

    enabled_grants_count, total_grants_count = _permission_grant_stats()
    binding_count_rows = RoutePermissionBinding.objects.all().values_list("permission_id")
    binding_counts: dict[str, int] = defaultdict(int)
    for permission_code, in binding_count_rows:
        binding_counts[str(permission_code)] += 1

    role_grants_map = _permissions_for_role(selected_role_id)
    permission_rows = []
    for permission in permissions:
        enabled_count = int(enabled_grants_count.get(permission.code, 0))
        total_count = int(total_grants_count.get(permission.code, 0))
        bind_count = int(binding_counts.get(permission.code, 0))
        is_unassigned = enabled_count == 0
        row = {
            "permission": permission,
            "granted": bool(role_grants_map.get(permission.code, False)),
            "enabled_roles_count": enabled_count,
            "grants_total_count": total_count,
            "bindings_count": bind_count,
            "warning_unassigned": is_unassigned,
            "warning_missing_binding": bind_count == 0,
        }
        if permission_state == "unassigned" and not row["warning_unassigned"]:
            continue
        if permission_state == "no_binding" and not row["warning_missing_binding"]:
            continue
        permission_rows.append(row)

    bindings_qs = (
        RoutePermissionBinding.objects.select_related("permission")
        .all()
        .order_by("priority", "route_name", "path_pattern", "id")
    )
    if module_filter:
        bindings_qs = bindings_qs.filter(permission__module__iexact=module_filter)
    if q_filter:
        bindings_qs = bindings_qs.filter(
            Q(route_name__icontains=q_filter)
            | Q(path_pattern__icontains=q_filter)
            | Q(permission_id__icontains=q_filter)
            | Q(source_app__icontains=q_filter)
            | Q(note__icontains=q_filter)
        )
    bindings = []
    for binding in bindings_qs:
        has_any_enabled_grant = int(enabled_grants_count.get(binding.permission_id, 0)) > 0
        selected_role_enabled = bool(role_grants_map.get(binding.permission_id, False))
        row = {
            "binding": binding,
            "warning_missing_any_grant": not has_any_enabled_grant,
            "warning_missing_selected_role_grant": selected_role_id is not None and not selected_role_enabled,
            "selected_role_enabled": selected_role_enabled,
        }
        if binding_state == "active" and not binding.is_active:
            continue
        if binding_state == "inactive" and binding.is_active:
            continue
        if binding_state == "missing_grant" and not row["warning_missing_any_grant"]:
            continue
        if binding_state == "selected_role_missing" and not row["warning_missing_selected_role_grant"]:
            continue
        bindings.append(row)

    # ── Override tab: utente selezionato e griglia toggle ──────────────────────
    selected_user_id = _int_or_none(request.GET.get("selected_user_id"))
    selected_user = None
    selected_user_label = ""
    user_override_rows: list[dict] = []
    all_legacy_users: list = []
    try:
        all_legacy_users = list(
            UtenteLegacy.objects.filter(attivo=True).order_by("nome", "id").values("id", "nome", "email", "ruolo_id")
        )
        # Arricchisci con cognome da anagrafica
        anag_map = {
            a.utente_id: a
            for a in AnagraficaDipendente.objects.filter(utente_id__in=[u["id"] for u in all_legacy_users]).only(
                "utente_id", "cognome", "nome"
            )
        }
        for u in all_legacy_users:
            anag = anag_map.get(u["id"])
            if anag and anag.cognome:
                u["display"] = f"{anag.cognome} {anag.nome or ''}".strip() + f" — {u['email'] or ''}"
            else:
                u["display"] = f"{u['nome']} — {u['email'] or ''}"
    except DatabaseError:
        all_legacy_users = []

    if selected_user_id is not None:
        try:
            selected_user = UtenteLegacy.objects.filter(id=selected_user_id).first()
        except DatabaseError:
            selected_user = None
        if selected_user is not None:
            # display label
            try:
                anag = AnagraficaDipendente.objects.filter(utente_id=selected_user_id).first()
                if anag and anag.cognome:
                    selected_user_label = f"{anag.cognome} {anag.nome or ''}".strip()
                else:
                    selected_user_label = selected_user.nome or selected_user.email or f"#{selected_user_id}"
            except DatabaseError:
                selected_user_label = selected_user.nome or f"#{selected_user_id}"
            # Carica role grants per il ruolo dell'utente
            user_role_grants = _permissions_for_role(selected_user.ruolo_id) if selected_user.ruolo_id else {}
            # Carica override canonici per l'utente
            user_grants_qs = UserPermissionGrant.objects.filter(legacy_user_id=selected_user_id).values_list(
                "permission_id", "enabled"
            )
            user_grants_map: dict[str, bool] = {str(code): bool(enabled) for code, enabled in user_grants_qs}
            # Costruisce righe per tutti i permessi attivi
            all_active_perms = list(PermissionDefinition.objects.filter(is_active=True).order_by("module", "code"))
            user_override_rows = _build_user_override_rows(all_active_perms, user_role_grants, user_grants_map)

    # ── Nav Override tab: visibilità navigazione per-utente ────────────────────
    nav_ov_user_id = _int_or_none(request.GET.get("nav_ov_user_id"))
    nav_ov_user = None
    nav_ov_user_label = ""
    nav_ov_rows: list[dict] = []
    nav_ov_by_section: dict[str, list] = {}
    if nav_ov_user_id is not None:
        try:
            nav_ov_user = UtenteLegacy.objects.filter(id=nav_ov_user_id).first()
        except DatabaseError:
            nav_ov_user = None
        if nav_ov_user is not None:
            try:
                anag = AnagraficaDipendente.objects.filter(utente_id=nav_ov_user_id).first()
                if anag and anag.cognome:
                    nav_ov_user_label = f"{anag.cognome} {anag.nome or ''}".strip()
                else:
                    nav_ov_user_label = nav_ov_user.nome or nav_ov_user.email or f"#{nav_ov_user_id}"
            except DatabaseError:
                nav_ov_user_label = nav_ov_user.nome or f"#{nav_ov_user_id}"
            user_nav_grants = {
                int(ov.item_id): bool(ov.enabled)
                for ov in UserNavigationOverride.objects.filter(legacy_user_id=nav_ov_user_id)
            }
            role_id_for_nav_ov = None
            if getattr(nav_ov_user, "ruolo_id", None):
                try:
                    role_id_for_nav_ov = int(nav_ov_user.ruolo_id)
                except Exception:
                    pass
            role_nav_items: set[int] = set()
            if role_id_for_nav_ov is not None:
                for row in NavigationRoleAccess.objects.filter(legacy_role_id=role_id_for_nav_ov, can_view=True):
                    role_nav_items.add(int(row.item_id))
            nav_sections_order = ["topbar", "subnav", "sidebar", "page"]
            nav_ov_by_section = {s: [] for s in nav_sections_order}
            for ni in NavigationItem.objects.filter(
                is_visible=True, is_enabled=True, section__in=nav_sections_order
            ).order_by("section", "order", "label"):
                iid = int(ni.id)
                role_allowed = iid in role_nav_items
                override = user_nav_grants.get(iid)
                if override is True:
                    state = "ov-show"
                elif override is False:
                    state = "ov-hide"
                elif role_allowed:
                    state = "role-show"
                else:
                    state = "role-hide"
                row_data = {
                    "item_id": iid,
                    "item_code": ni.code,
                    "item_label": ni.label,
                    "item_section": ni.section,
                    "item_icon": ni.icon or "",
                    "role_allowed": role_allowed,
                    "override": override,
                    "state": state,
                }
                nav_ov_rows.append(row_data)
                s = ni.section
                if s in nav_ov_by_section:
                    nav_ov_by_section[s].append(row_data)

    user_override_qs = UserPermissionGrant.objects.select_related("permission").all().order_by("-updated_at", "-id")
    if q_filter:
        user_override_qs = user_override_qs.filter(
            Q(permission_id__icontains=q_filter)
            | Q(note__icontains=q_filter)
            | Q(legacy_user_id__icontains=q_filter)
        )
    if selected_user_id is not None and active_tab == "overrides":
        user_override_qs = user_override_qs.filter(legacy_user_id=selected_user_id)
    user_overrides = list(user_override_qs[:150])

    coverage_rows, coverage_summary = _collect_route_coverage_rows()
    legacy_only_routes = [row for row in coverage_rows if row["status"] == STATUS_LEGACY_FALLBACK][:8]
    unbound_routes = [row for row in coverage_rows if row["status"] == STATUS_UNBOUND][:8]

    module_choices = list(
        PermissionDefinition.objects.exclude(module="").values_list("module", flat=True).distinct().order_by("module")
    )
    summary = {
        "permissions_total": PermissionDefinition.objects.count(),
        "permissions_active": PermissionDefinition.objects.filter(is_active=True).count(),
        "permissions_unassigned": sum(1 for value in enabled_grants_count.values() if int(value) == 0)
        + sum(1 for permission in PermissionDefinition.objects.all() if permission.code not in enabled_grants_count),
        "bindings_total": RoutePermissionBinding.objects.count(),
        "bindings_missing_grant": sum(1 for row in bindings if row["warning_missing_any_grant"]),
        "overrides_total": UserPermissionGrant.objects.count(),
        "legacy_only_routes": int(coverage_summary["legacy_fallback"]),
        "unbound_routes": int(coverage_summary["unbound"]),
    }

    context = {
        "permissions": permissions,
        "permission_rows": permission_rows,
        "bindings": bindings,
        "roles": roles,
        "selected_role_id": selected_role_id,
        "route_catalog": _route_catalog(),
        "user_overrides": user_overrides,
        "summary": summary,
        "filters": {
            "q": q_filter,
            "module": module_filter,
            "permission_state": permission_state,
            "binding_state": binding_state,
            "tab": active_tab,
        },
        "module_choices": module_choices,
        "permission_code_format_hint": PERMISSION_CODE_FORMAT_HINT,
        "active_tab": active_tab,
        "coverage_summary": coverage_summary,
        "legacy_only_routes_sample": legacy_only_routes,
        "unbound_routes_sample": unbound_routes,
        # Override tab — utente selezionato
        "all_legacy_users": all_legacy_users,
        "selected_user_id": selected_user_id,
        "selected_user": selected_user,
        "selected_user_label": selected_user_label,
        "user_override_rows": user_override_rows,
        # Step 3: permission rows raggruppati per modulo (per card grid)
        "permission_rows_by_module": _group_permission_rows_by_module(permission_rows),
        # Step 5: nav override per-utente
        "nav_ov_user_id": nav_ov_user_id,
        "nav_ov_user": nav_ov_user,
        "nav_ov_user_label": nav_ov_user_label,
        "nav_ov_rows": nav_ov_rows,
        "nav_ov_by_section": nav_ov_by_section,
    }
    return render(request, "admin_portale/pages/acl_canonico.html", context)


@legacy_admin_required
@require_GET
def acl_route_coverage(request):
    status_filter = str(request.GET.get("status") or "all").strip().upper()
    app_filter = str(request.GET.get("app") or "").strip()
    q_filter = str(request.GET.get("q") or "").strip()
    only_warnings = str(request.GET.get("only_warnings") or "0").strip() == "1"

    if status_filter not in {"ALL", *ROUTE_STATUS_CHOICES}:
        status_filter = "ALL"
    rows, summary = _collect_route_coverage_rows()
    filtered_rows = _filter_route_coverage_rows(
        rows=rows,
        status_filter=status_filter,
        app_filter=app_filter,
        q_filter=q_filter,
        only_warnings=only_warnings,
    )
    filtered_summary = {
        "total": len(filtered_rows),
        "canonical_bound": sum(1 for row in filtered_rows if row["status"] == STATUS_CANONICAL_BOUND),
        "legacy_fallback": sum(1 for row in filtered_rows if row["status"] == STATUS_LEGACY_FALLBACK),
        "unbound": sum(1 for row in filtered_rows if row["status"] == STATUS_UNBOUND),
        "coming_or_excluded": sum(1 for row in filtered_rows if row["status"] == STATUS_COMING_SOON_EXCLUDED),
        "redirect_only": sum(1 for row in filtered_rows if row["status"] == STATUS_REDIRECT_ONLY),
        "warnings": sum(1 for row in filtered_rows if row["warnings"]),
    }

    export_format = str(request.GET.get("export") or "").strip().lower()
    if export_format == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="acl_route_coverage.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "status",
                "app_label",
                "route_name",
                "path_normalized",
                "canonical_permissions",
                "canonical_binding_count",
                "has_legacy",
                "has_redirect",
                "warnings",
                "excluded_reason",
            ]
        )
        for row in filtered_rows:
            writer.writerow(
                [
                    row["status"],
                    row["app_label"],
                    row["route_name"],
                    row["path_normalized"],
                    ", ".join(row["canonical_permissions"]),
                    row["canonical_binding_count"],
                    "1" if row["has_legacy"] else "0",
                    "1" if row["has_redirect"] else "0",
                    ", ".join(row["warnings"]),
                    row["excluded_reason"],
                ]
            )
        return response

    app_choices = sorted({row["app_label"] for row in rows if row["app_label"]})
    return render(
        request,
        "admin_portale/pages/acl_route_coverage.html",
        {
            "rows": filtered_rows,
            "summary": summary,
            "filtered_summary": filtered_summary,
            "status_labels": ROUTE_STATUS_LABELS,
            "status_choices": ROUTE_STATUS_CHOICES,
            "filters": {
                "status": status_filter,
                "app": app_filter,
                "q": q_filter,
                "only_warnings": only_warnings,
            },
            "app_choices": app_choices,
        },
    )


@legacy_admin_required
@require_GET
def api_acl_legacy_user_search(request):
    """JSON: cerca utenti legacy per nome/cognome/email. ?q=rossi → {results: [{id, display, email, ruolo_id}]}"""
    q = str(request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse({"results": []})
    try:
        qs = list(
            UtenteLegacy.objects.filter(
                Q(nome__icontains=q) | Q(email__icontains=q)
            ).order_by("nome", "id")[:30]
        )
        user_ids = [u.id for u in qs]
        anag_map = {
            a.utente_id: a
            for a in AnagraficaDipendente.objects.filter(utente_id__in=user_ids).only(
                "utente_id", "cognome", "nome"
            )
        }
        results = []
        for u in qs:
            anag = anag_map.get(u.id)
            if anag and anag.cognome:
                nome_display = f"{anag.cognome} {anag.nome or ''}".strip()
            else:
                nome_display = u.nome or ""
            results.append({
                "id": u.id,
                "display": f"{nome_display} — {u.email or ''}".strip(" —"),
                "email": u.email or "",
                "ruolo_id": u.ruolo_id,
            })
    except DatabaseError as exc:
        return JsonResponse({"results": [], "error": str(exc)})
    return JsonResponse({"results": results})

