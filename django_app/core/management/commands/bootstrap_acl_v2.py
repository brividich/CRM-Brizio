from __future__ import annotations

import importlib
import re
from collections import defaultdict
from dataclasses import dataclass

from django.core.management.base import BaseCommand
from django.db import DatabaseError, transaction
from django.urls import URLPattern, URLResolver, get_resolver
from core.acl_v2 import (
    normalize_binding_path_pattern,
    normalize_permission_code,
    validate_permission_code,
)
from core.legacy_models import Permesso, Pulsante
from core.models import LegacyRedirect, PermissionDefinition, RolePermissionGrant, RoutePermissionBinding


_DYNAMIC_SEGMENT_RE = re.compile(r"<[^>]+>")
_COMING_ROUTE_RE = re.compile(r"(^|:)coming[_-]", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[^a-z0-9]+")

STATUS_CANONICAL_BOUND = "CANONICAL_BOUND"
STATUS_LEGACY_FALLBACK = "LEGACY_FALLBACK"
STATUS_UNBOUND = "UNBOUND"
STATUS_COMING_SOON_EXCLUDED = "COMING_SOON_EXCLUDED"
STATUS_REDIRECT_ONLY = "REDIRECT_ONLY"

MIGRATION_NOTE_MARKER = "[ACL_V2_BOOTSTRAP]"

_ACTION_ALIASES = {
    "view": "view",
    "list": "view",
    "lista": "view",
    "elenco": "view",
    "index": "view",
    "home": "view",
    "dashboard": "view",
    "detail": "view",
    "dettaglio": "view",
    "menu": "view",
    "mappa": "view",
    "new": "create",
    "nuova": "create",
    "nuovo": "create",
    "create": "create",
    "add": "create",
    "edit": "edit",
    "modifica": "edit",
    "update": "edit",
    "set": "edit",
    "delete": "delete",
    "elimina": "delete",
    "remove": "delete",
    "rimuovi": "delete",
    "annulla": "delete",
    "toggle": "manage",
    "gestione": "manage",
    "manage": "manage",
    "configurazione": "manage",
    "impostazioni": "manage",
    "wizard": "manage",
    "bulk": "manage",
    "assign": "manage",
    "assegna": "manage",
    "retry": "run",
    "reset": "run",
    "sync": "run",
    "run": "run",
    "test": "run",
    "parse": "run",
    "process": "run",
    "export": "export",
    "download": "export",
    "report": "export",
    "pdf": "export",
    "csv": "export",
    "import": "import",
    "upload": "import",
    "approva": "approve",
    "approve": "approve",
    "rifiuta": "approve",
    "consegna": "approve",
}
_GENERIC_RESOURCE_TOKENS = {
    "api",
    "legacy",
    "route",
    "page",
    "view",
    "admin",
    "portale",
    "django",
}
_BOOTSTRAP_CACHE: dict[str, list[tuple[str, str, str]]] = {}


@dataclass
class RouteRow:
    route_name: str
    route_pattern: str
    sample_path: str
    app_label: str


@dataclass(frozen=True)
class RouteCoverageRow:
    route_name: str
    sample_path: str
    app_label: str
    status: str


@dataclass(frozen=True)
class RouteSuggestion:
    route_name: str
    sample_path: str
    app_label: str
    permission_code: str
    source_app: str
    status_before: str
    from_bootstrap: bool


def _normalize_segment(raw_value: str, *, fallback: str = "core") -> str:
    normalized = normalize_permission_code(str(raw_value or "").replace("-", "_"))
    normalized = normalized.replace(".", "_")
    normalized = _TOKEN_RE.sub("_", normalized).strip("_")
    return normalized or fallback


def _tokenize(raw_value: str) -> list[str]:
    value = normalize_permission_code(raw_value).replace(".", "_").replace(":", "_").replace("-", "_")
    return [token for token in _TOKEN_RE.split(value) if token]


def _collect_named_routes() -> list[RouteRow]:
    resolver = get_resolver()
    rows: list[RouteRow] = []

    def walk(patterns, prefix: str = "", namespace_prefix: str = ""):
        for pattern in patterns:
            if isinstance(pattern, URLPattern):
                name = getattr(pattern, "name", None)
                if not name:
                    continue
                route_name = f"{namespace_prefix}:{name}" if namespace_prefix else str(name)
                route_pattern = prefix + str(pattern.pattern)
                sample_path = "/" + route_pattern.lstrip("/")
                sample_path = _DYNAMIC_SEGMENT_RE.sub("1", sample_path)
                sample_path = re.sub(r"/+", "/", sample_path)
                if sample_path != "/":
                    sample_path = sample_path.rstrip("/")
                sample_path = normalize_binding_path_pattern(sample_path or "/")
                app_label = _infer_source_app(route_name, sample_path)
                rows.append(
                    RouteRow(
                        route_name=route_name,
                        route_pattern=route_pattern,
                        sample_path=sample_path,
                        app_label=app_label,
                    )
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
    rows.sort(key=lambda row: (row.app_label, row.route_name, row.sample_path))
    return rows


def _infer_source_app(route_name: str, path: str) -> str:
    route_name = str(route_name or "").strip()
    if ":" in route_name:
        return _normalize_segment(route_name.split(":", 1)[0], fallback="core")
    parts = [p for p in path.split("/") if p]
    if parts:
        return _normalize_segment(parts[0], fallback="core")
    return "core"


def _load_app_bootstrap_definitions(app_label: str) -> list[tuple[str, str, str]]:
    app_label_norm = _normalize_segment(app_label, fallback="")
    if not app_label_norm:
        return []
    if app_label_norm in _BOOTSTRAP_CACHE:
        return _BOOTSTRAP_CACHE[app_label_norm]
    try:
        module = importlib.import_module(f"{app_label_norm}.acl_bootstrap")
    except Exception:
        _BOOTSTRAP_CACHE[app_label_norm] = []
        return []

    definitions = getattr(module, "_PULSANTI_DEFINITIONS", None)
    rows: list[tuple[str, str, str]] = []
    if isinstance(definitions, list):
        for item in definitions:
            if not isinstance(item, dict):
                continue
            raw_url = str(item.get("url") or "").strip()
            modulo = _normalize_segment(str(item.get("modulo") or app_label_norm), fallback=app_label_norm)
            codice = _normalize_segment(str(item.get("codice") or ""), fallback="")
            path = normalize_binding_path_pattern(raw_url)
            if not path or not codice:
                continue
            rows.append((path, modulo, codice))
    rows.sort(key=lambda row: len(row[0]), reverse=True)
    _BOOTSTRAP_CACHE[app_label_norm] = rows
    return rows


def _infer_action(tokens: list[str], *, default: str = "view") -> str:
    for token in reversed(tokens):
        mapped = _ACTION_ALIASES.get(token)
        if mapped:
            return mapped
    return default


def _infer_resource(tokens: list[str], *, action: str, app_label: str) -> str:
    if not tokens:
        return "route"
    filtered: list[str] = []
    for token in tokens:
        if _ACTION_ALIASES.get(token) == action:
            continue
        if token in _GENERIC_RESOURCE_TOKENS:
            continue
        filtered.append(token)
    if not filtered:
        filtered = [token for token in tokens if token not in _GENERIC_RESOURCE_TOKENS]
    if not filtered:
        fallback = _normalize_segment(app_label, fallback="route")
        if fallback in {"admin_portale", "core"}:
            return "route"
        return fallback
    return "_".join(filtered[:2])


def _canonical_code_from_legacy_button(modulo: str, codice: str) -> str:
    module_token = _normalize_segment(modulo, fallback="core")
    tokens = _tokenize(codice)
    if tokens and tokens[0] == module_token:
        tokens = tokens[1:]
    action = _infer_action(tokens, default="view")
    resource = _infer_resource(tokens, action=action, app_label=module_token)
    candidate = normalize_permission_code(f"{module_token}.{resource}.{action}")
    is_valid, _ = validate_permission_code(candidate)
    if is_valid:
        return candidate
    fallback = normalize_permission_code(f"{module_token}.route.view")
    return fallback if validate_permission_code(fallback)[0] else "core.route.view"


def _suggest_permission_code(route_name: str, sample_path: str, app_label: str) -> tuple[str, bool]:
    app_token = _normalize_segment(app_label, fallback="core")
    bootstrap_defs = _load_app_bootstrap_definitions(app_token)
    for path_prefix, modulo, codice in bootstrap_defs:
        if sample_path == path_prefix or sample_path.startswith(path_prefix + "/"):
            return _canonical_code_from_legacy_button(modulo, codice), True

    local_name = route_name.split(":", 1)[1] if ":" in route_name else route_name
    tokens = _tokenize(local_name)
    if not tokens:
        path_tokens = [_normalize_segment(piece, fallback="") for piece in sample_path.split("/") if piece]
        tokens = [token for token in path_tokens if token and not token.isdigit()]
    default_action = "manage" if ("api" in tokens or "/api/" in sample_path) else "view"
    action = _infer_action(tokens, default=default_action)
    resource = _infer_resource(tokens, action=action, app_label=app_token)

    candidate = normalize_permission_code(f"{app_token}.{resource}.{action}")
    is_valid, _ = validate_permission_code(candidate)
    if is_valid:
        return candidate, False

    fallback = normalize_permission_code(f"{app_token}.route.{action}")
    if validate_permission_code(fallback)[0]:
        return fallback, False
    return "core.route.view", False


def _legacy_catalog() -> tuple[set[str], set[str], dict[tuple[str, str], str]]:
    legacy_route_names: set[str] = set()
    legacy_paths: set[str] = set()
    mapping: dict[tuple[str, str], str] = {}
    try:
        pulsanti = list(Pulsante.objects.all().order_by("id"))
    except DatabaseError:
        return legacy_route_names, legacy_paths, mapping

    for button in pulsanti:
        modulo = str(button.modulo or "").strip().lower()
        azione = str(button.codice or "").strip().lower()
        if not modulo or not azione:
            continue
        permission_code = normalize_permission_code(f"legacy.{modulo}.{azione}") or f"legacy.button_{button.id}"
        mapping[(modulo, azione)] = permission_code

        raw_url = str(button.url or "").strip()
        lower_url = raw_url.lower()
        if lower_url.startswith("route:") or lower_url.startswith("django:"):
            _, route_name = raw_url.split(":", 1)
            if route_name.strip():
                legacy_route_names.add(route_name.strip())
        else:
            path = normalize_binding_path_pattern(raw_url)
            if path:
                legacy_paths.add(path)

    return legacy_route_names, legacy_paths, mapping


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


def _canonical_catalog() -> tuple[set[str], list[RoutePermissionBinding]]:
    try:
        route_names = {
            str(name).strip().lower()
            for name in RoutePermissionBinding.objects.filter(is_active=True)
            .exclude(route_name="")
            .values_list("route_name", flat=True)
        }
        path_bindings = list(
            RoutePermissionBinding.objects.filter(is_active=True)
            .exclude(path_pattern="")
            .order_by("priority", "id")
        )
    except DatabaseError:
        return set(), []
    return route_names, path_bindings


def _match_path_binding(path: str, bindings: list[RoutePermissionBinding]) -> bool:
    for binding in bindings:
        strategy = (binding.match_strategy or RoutePermissionBinding.MATCH_EXACT).lower()
        pattern = normalize_binding_path_pattern(
            binding.path_pattern,
            for_regex=(strategy == RoutePermissionBinding.MATCH_REGEX),
        )
        if not pattern:
            continue
        if strategy == RoutePermissionBinding.MATCH_REGEX:
            try:
                if re.search(pattern, path):
                    return True
            except re.error:
                continue
            continue
        if strategy == RoutePermissionBinding.MATCH_PREFIX:
            if path == pattern or path.startswith(pattern + "/"):
                return True
            continue
        if path == pattern:
            return True
    return False


def _is_coming_or_excluded_route(route_name: str, path_norm: str) -> bool:
    route_name_norm = str(route_name or "").strip()
    if _COMING_ROUTE_RE.search(route_name_norm):
        return True
    excluded_route_prefixes = (
        "admin:",
        "django_prometheus:",
        "silk:",
        "debug_toolbar:",
        "admin_portale:api_",
    )
    if any(route_name_norm.startswith(prefix) for prefix in excluded_route_prefixes):
        return True
    if route_name_norm in {"login", "logout", "password_change", "password_reset"}:
        return True
    if path_norm in {"/health", "/health/", "/admin-portale/health", "/admin-portale/health/"}:
        return True
    return False


def _route_has_legacy_coverage(route_name: str, path_norm: str, legacy_route_names: set[str], legacy_paths: set[str]) -> bool:
    if route_name and route_name in legacy_route_names:
        return True
    for legacy_path in legacy_paths:
        if path_norm == legacy_path:
            return True
        if legacy_path and legacy_path != "/" and path_norm.startswith(legacy_path + "/"):
            return True
    return False


def _collect_route_coverage() -> list[RouteCoverageRow]:
    routes = _collect_named_routes()
    route_names_active, path_bindings_active = _canonical_catalog()
    legacy_route_names, legacy_paths, _ = _legacy_catalog()
    redirect_routes, redirect_paths = _redirect_target_catalog()

    rows: list[RouteCoverageRow] = []
    for route in routes:
        route_name = route.route_name
        sample_path = route.sample_path

        if _is_coming_or_excluded_route(route_name, sample_path):
            status = STATUS_COMING_SOON_EXCLUDED
        elif route_name.strip().lower() in route_names_active or _match_path_binding(sample_path, path_bindings_active):
            status = STATUS_CANONICAL_BOUND
        elif _route_has_legacy_coverage(route_name, sample_path, legacy_route_names, legacy_paths):
            status = STATUS_LEGACY_FALLBACK
        elif (
            (route_name and route_name in redirect_routes)
            or (sample_path and sample_path in redirect_paths)
        ):
            status = STATUS_REDIRECT_ONLY
        else:
            status = STATUS_UNBOUND

        rows.append(
            RouteCoverageRow(
                route_name=route_name,
                sample_path=sample_path,
                app_label=route.app_label,
                status=status,
            )
        )
    rows.sort(key=lambda row: (row.app_label, row.route_name, row.sample_path))
    return rows


def _build_suggestions(
    *,
    coverage_rows: list[RouteCoverageRow],
    target_apps: set[str],
) -> list[RouteSuggestion]:
    suggestions: list[RouteSuggestion] = []
    seen_keys: set[str] = set()
    for row in coverage_rows:
        if row.status not in {STATUS_LEGACY_FALLBACK, STATUS_UNBOUND}:
            continue
        app_label_norm = _normalize_segment(row.app_label, fallback="core")
        if target_apps and app_label_norm not in target_apps:
            continue
        dedupe_key = row.route_name.strip().lower() or row.sample_path
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        permission_code, from_bootstrap = _suggest_permission_code(
            route_name=row.route_name,
            sample_path=row.sample_path,
            app_label=app_label_norm,
        )
        suggestions.append(
            RouteSuggestion(
                route_name=row.route_name,
                sample_path=row.sample_path,
                app_label=app_label_norm,
                permission_code=permission_code,
                source_app=app_label_norm,
                status_before=row.status,
                from_bootstrap=from_bootstrap,
            )
        )
    suggestions.sort(key=lambda row: (row.app_label, row.route_name, row.sample_path))
    return suggestions


def _legacy_acl_indexes() -> tuple[dict[str, list[tuple[str, str]]], list[tuple[str, str, str]], dict[tuple[str, str], dict[int, bool]]]:
    route_index: dict[str, list[tuple[str, str]]] = defaultdict(list)
    path_index: list[tuple[str, str, str]] = []
    grants_index: dict[tuple[str, str], dict[int, bool]] = defaultdict(dict)

    try:
        buttons = list(Pulsante.objects.all().values("modulo", "codice", "url"))
        perms = list(Permesso.objects.all().values("modulo", "azione", "ruolo_id", "can_view", "consentito"))
    except DatabaseError:
        return {}, [], {}

    for button in buttons:
        modulo = str(button.get("modulo") or "").strip().lower()
        codice = str(button.get("codice") or "").strip().lower()
        raw_url = str(button.get("url") or "").strip()
        if not modulo or not codice or not raw_url:
            continue
        lower_url = raw_url.lower()
        if lower_url.startswith("route:") or lower_url.startswith("django:"):
            _, route_name = raw_url.split(":", 1)
            route_name = route_name.strip()
            if route_name:
                route_index[route_name].append((modulo, codice))
            continue
        path = normalize_binding_path_pattern(raw_url)
        if path:
            path_index.append((path, modulo, codice))

    path_index.sort(key=lambda row: len(row[0]), reverse=True)

    for perm in perms:
        modulo = str(perm.get("modulo") or "").strip().lower()
        azione = str(perm.get("azione") or "").strip().lower()
        role_id = int(perm.get("ruolo_id") or 0)
        if not modulo or not azione or not role_id:
            continue
        enabled = bool(perm.get("can_view")) or bool(perm.get("consentito"))
        key = (modulo, azione)
        previous = grants_index[key].get(role_id, False)
        grants_index[key][role_id] = bool(previous or enabled)

    return route_index, path_index, grants_index


class Command(BaseCommand):
    help = (
        "Bootstrap ACL canonico v2: scansiona route Django, propone permission code "
        "e crea binding/grant in modo progressivo e compatibile col fallback legacy."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Applica su DB PermissionDefinition/RoutePermissionBinding proposte dalla scansione route.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Alias esplicito: nessuna modifica DB (default senza --apply).",
        )
        parser.add_argument(
            "--apps",
            default="",
            help="Elenco app separato da virgola (es. assets,automazioni). Vuoto = tutte.",
        )
        parser.add_argument(
            "--import-legacy",
            action="store_true",
            help="Importa da pulsanti/permessi legacy creando binding e grant canonici equivalenti.",
        )
        parser.add_argument(
            "--activate-generated-bindings",
            action="store_true",
            help="Compat: mantenuto per backward compatibility.",
        )

    def handle(self, *args, **options):
        do_apply = bool(options.get("apply"))
        _ = bool(options.get("dry_run"))
        do_import_legacy = bool(options.get("import_legacy"))
        apps_raw = str(options.get("apps") or "").strip()
        target_apps = {
            _normalize_segment(item, fallback="")
            for item in [chunk.strip() for chunk in apps_raw.split(",")]
            if item.strip()
        }
        target_apps.discard("")

        imported_permissions = 0
        imported_legacy_bindings = 0
        imported_legacy_grants = 0

        if do_import_legacy:
            (
                imported_permissions,
                imported_legacy_bindings,
                imported_legacy_grants,
            ) = self._import_legacy_into_canonical()

        coverage_before = _collect_route_coverage()
        suggestions = _build_suggestions(coverage_rows=coverage_before, target_apps=target_apps)

        created_permissions = 0
        created_bindings = 0
        updated_bindings = 0
        reused_bindings = 0
        conflicts = 0
        created_role_grants = 0
        updated_role_grants = 0
        if do_apply and suggestions:
            (
                created_permissions,
                created_bindings,
                updated_bindings,
                reused_bindings,
                conflicts,
                created_role_grants,
                updated_role_grants,
            ) = self._apply_route_suggestions(suggestions=suggestions)

        coverage_after = _collect_route_coverage()
        self._print_report(
            coverage_before=coverage_before,
            coverage_after=coverage_after,
            suggestions=suggestions,
            target_apps=target_apps,
            do_apply=do_apply,
            imported_permissions=imported_permissions,
            imported_legacy_bindings=imported_legacy_bindings,
            imported_legacy_grants=imported_legacy_grants,
            created_permissions=created_permissions,
            created_bindings=created_bindings,
            updated_bindings=updated_bindings,
            reused_bindings=reused_bindings,
            conflicts=conflicts,
            created_role_grants=created_role_grants,
            updated_role_grants=updated_role_grants,
        )

    def _print_report(
        self,
        *,
        coverage_before: list[RouteCoverageRow],
        coverage_after: list[RouteCoverageRow],
        suggestions: list[RouteSuggestion],
        target_apps: set[str],
        do_apply: bool,
        imported_permissions: int,
        imported_legacy_bindings: int,
        imported_legacy_grants: int,
        created_permissions: int,
        created_bindings: int,
        updated_bindings: int,
        reused_bindings: int,
        conflicts: int,
        created_role_grants: int,
        updated_role_grants: int,
    ):
        def summarize(rows: list[RouteCoverageRow]) -> dict[str, int]:
            return {
                STATUS_CANONICAL_BOUND: sum(1 for row in rows if row.status == STATUS_CANONICAL_BOUND),
                STATUS_LEGACY_FALLBACK: sum(1 for row in rows if row.status == STATUS_LEGACY_FALLBACK),
                STATUS_UNBOUND: sum(1 for row in rows if row.status == STATUS_UNBOUND),
                STATUS_COMING_SOON_EXCLUDED: sum(1 for row in rows if row.status == STATUS_COMING_SOON_EXCLUDED),
                STATUS_REDIRECT_ONLY: sum(1 for row in rows if row.status == STATUS_REDIRECT_ONLY),
                "TOTAL": len(rows),
            }

        def app_rows(rows: list[RouteCoverageRow]) -> dict[str, list[RouteCoverageRow]]:
            grouped: dict[str, list[RouteCoverageRow]] = defaultdict(list)
            for row in rows:
                app_label = _normalize_segment(row.app_label, fallback="core")
                if target_apps and app_label not in target_apps:
                    continue
                grouped[app_label].append(row)
            return grouped

        summary_before = summarize(coverage_before)
        summary_after = summarize(coverage_after)
        grouped_before = app_rows(coverage_before)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Report bootstrap ACL v2"))
        if target_apps:
            self.stdout.write(f"- Scope app: {', '.join(sorted(target_apps))}")
        else:
            self.stdout.write("- Scope app: tutte")
        self.stdout.write(f"- Route totali: {summary_after['TOTAL']}")
        self.stdout.write(
            f"- BEFORE => CANONICAL_BOUND={summary_before[STATUS_CANONICAL_BOUND]} "
            f"LEGACY_FALLBACK={summary_before[STATUS_LEGACY_FALLBACK]} UNBOUND={summary_before[STATUS_UNBOUND]} "
            f"COMING_SOON_EXCLUDED={summary_before[STATUS_COMING_SOON_EXCLUDED]} REDIRECT_ONLY={summary_before[STATUS_REDIRECT_ONLY]}"
        )
        self.stdout.write(
            f"- AFTER  => CANONICAL_BOUND={summary_after[STATUS_CANONICAL_BOUND]} "
            f"LEGACY_FALLBACK={summary_after[STATUS_LEGACY_FALLBACK]} UNBOUND={summary_after[STATUS_UNBOUND]} "
            f"COMING_SOON_EXCLUDED={summary_after[STATUS_COMING_SOON_EXCLUDED]} REDIRECT_ONLY={summary_after[STATUS_REDIRECT_ONLY]}"
        )
        self.stdout.write(f"- Proposte route->permission: {len(suggestions)}")
        self.stdout.write(f"- Import legacy permission: {imported_permissions}")
        self.stdout.write(f"- Import legacy binding: {imported_legacy_bindings}")
        self.stdout.write(f"- Import legacy grant: {imported_legacy_grants}")
        self.stdout.write(f"- Permission create/update migration: {created_permissions}")
        self.stdout.write(f"- Binding create migration: {created_bindings}")
        self.stdout.write(f"- Binding update migration: {updated_bindings}")
        self.stdout.write(f"- Binding reuse migration: {reused_bindings}")
        self.stdout.write(f"- Binding conflict migration: {conflicts}")
        self.stdout.write(f"- Role grant create migration: {created_role_grants}")
        self.stdout.write(f"- Role grant update migration: {updated_role_grants}")

        if grouped_before:
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE("Route LEGACY_FALLBACK / UNBOUND raggruppate per app"))
            for app_label in sorted(grouped_before):
                rows = grouped_before[app_label]
                legacy_rows = [row for row in rows if row.status == STATUS_LEGACY_FALLBACK]
                unbound_rows = [row for row in rows if row.status == STATUS_UNBOUND]
                if not legacy_rows and not unbound_rows:
                    continue
                self.stdout.write(f"- {app_label}: LEGACY_FALLBACK={len(legacy_rows)} UNBOUND={len(unbound_rows)}")

        if suggestions:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Prime 50 proposte route -> permission_code"))
            for row in suggestions[:50]:
                bootstrap_hint = " bootstrap_acl" if row.from_bootstrap else ""
                self.stdout.write(
                    f"  - {row.route_name} [{row.sample_path}] -> {row.permission_code} "
                    f"(app={row.app_label}, status={row.status_before}{bootstrap_hint})"
                )

        self.stdout.write("")
        if do_apply:
            self.stdout.write(
                self.style.SUCCESS("Bootstrap ACL v2 completato in modalita APPLY.")
                if (created_bindings or updated_bindings or imported_legacy_bindings)
                else self.style.SUCCESS("Nessuna modifica da applicare.")
            )
        else:
            self.stdout.write(self.style.NOTICE("Modalita dry-run: nessuna modifica. Usa --apply per creare/aggiornare."))

    def _import_legacy_into_canonical(self) -> tuple[int, int, int]:
        created_permissions = 0
        created_bindings = 0
        created_grants = 0

        try:
            buttons = list(Pulsante.objects.all().order_by("id"))
            perms = list(Permesso.objects.all().order_by("-id"))
        except DatabaseError as exc:
            self.stdout.write(self.style.ERROR(f"Import legacy saltato: {exc}"))
            return 0, 0, 0

        button_map: dict[tuple[str, str], tuple[str, str, str, str]] = {}
        with transaction.atomic():
            for button in buttons:
                modulo = str(button.modulo or "").strip().lower()
                azione = str(button.codice or "").strip().lower()
                if not modulo or not azione:
                    continue
                permission_code = normalize_permission_code(f"legacy.{modulo}.{azione}") or f"legacy.button_{button.id}"
                label = str(button.nome_visibile or button.codice or permission_code).strip()
                permission, created = PermissionDefinition.objects.get_or_create(
                    code=permission_code,
                    defaults={
                        "label": label,
                        "module": modulo or "legacy",
                        "description": f"Import legacy da pulsanti.id={button.id}",
                        "is_active": True,
                    },
                )
                if created:
                    created_permissions += 1
                button_map[(modulo, azione)] = (permission.code, modulo, azione, str(button.url or "").strip())

                route_name = ""
                path_pattern = ""
                raw_url = str(button.url or "").strip()
                lower_url = raw_url.lower()
                if lower_url.startswith("route:") or lower_url.startswith("django:"):
                    _, route_name = raw_url.split(":", 1)
                    route_name = route_name.strip()
                else:
                    path_pattern = normalize_binding_path_pattern(raw_url)

                if not route_name and not path_pattern:
                    continue

                binding, created_binding = RoutePermissionBinding.objects.get_or_create(
                    route_name=route_name,
                    path_pattern=path_pattern,
                    defaults={
                        "match_strategy": (
                            RoutePermissionBinding.MATCH_PREFIX
                            if path_pattern
                            else RoutePermissionBinding.MATCH_EXACT
                        ),
                        "permission_id": permission.code,
                        "source_app": modulo or "legacy",
                        "note": f"{MIGRATION_NOTE_MARKER} import automatico da pulsanti.id={button.id}",
                        "priority": 100,
                        "is_active": True,
                    },
                )
                if not created_binding and binding.permission_id != permission.code:
                    binding.permission_id = permission.code
                    binding.save(update_fields=["permission"])
                if created_binding:
                    created_bindings += 1

            seen_role_permission: set[tuple[int, str]] = set()
            for perm in perms:
                modulo = str(perm.modulo or "").strip().lower()
                azione = str(perm.azione or "").strip().lower()
                role_id = int(getattr(perm, "ruolo_id", 0) or 0)
                if not modulo or not azione or not role_id:
                    continue
                payload = button_map.get((modulo, azione))
                if payload is None:
                    continue
                permission_code = payload[0]
                key = (role_id, permission_code)
                if key in seen_role_permission:
                    continue
                seen_role_permission.add(key)
                enabled = bool(getattr(perm, "can_view", 0)) or bool(getattr(perm, "consentito", 0))
                _, created_grant = RolePermissionGrant.objects.update_or_create(
                    legacy_role_id=role_id,
                    permission_id=permission_code,
                    defaults={
                        "enabled": enabled,
                        "note": f"{MIGRATION_NOTE_MARKER} import automatico da tabella legacy permessi",
                    },
                )
                if created_grant:
                    created_grants += 1

        return created_permissions, created_bindings, created_grants

    def _apply_route_suggestions(
        self,
        *,
        suggestions: list[RouteSuggestion],
    ) -> tuple[int, int, int, int, int, int, int]:
        created_permissions = 0
        created_bindings = 0
        updated_bindings = 0
        reused_bindings = 0
        conflicts = 0
        created_role_grants = 0
        updated_role_grants = 0

        route_index, path_index, grants_index = _legacy_acl_indexes()

        with transaction.atomic():
            for row in suggestions:
                label = row.route_name.replace(":", " / ") or row.sample_path
                permission, permission_created = PermissionDefinition.objects.get_or_create(
                    code=row.permission_code,
                    defaults={
                        "label": label,
                        "module": row.source_app,
                        "description": f"{MIGRATION_NOTE_MARKER} bootstrap route {row.route_name}",
                        "is_active": True,
                    },
                )
                if permission_created:
                    created_permissions += 1

                existing = (
                    RoutePermissionBinding.objects.filter(route_name=row.route_name, path_pattern="")
                    .order_by("-is_active", "priority", "id")
                    .first()
                )
                conflict = False
                if existing is None:
                    RoutePermissionBinding.objects.create(
                        route_name=row.route_name,
                        path_pattern="",
                        match_strategy=RoutePermissionBinding.MATCH_EXACT,
                        permission_id=permission.code,
                        source_app=row.source_app,
                        note=f"{MIGRATION_NOTE_MARKER} bootstrap route migration",
                        priority=120,
                        is_active=True,
                    )
                    created_bindings += 1
                else:
                    updates: list[str] = []
                    conflict = existing.permission_id != permission.code and MIGRATION_NOTE_MARKER not in str(existing.note or "")
                    if conflict:
                        conflicts += 1
                    else:
                        if existing.permission_id != permission.code:
                            existing.permission_id = permission.code
                            updates.append("permission")
                    if (existing.match_strategy or RoutePermissionBinding.MATCH_EXACT) != RoutePermissionBinding.MATCH_EXACT:
                        existing.match_strategy = RoutePermissionBinding.MATCH_EXACT
                        updates.append("match_strategy")
                    if str(existing.source_app or "").strip() != row.source_app:
                        existing.source_app = row.source_app
                        updates.append("source_app")
                    if int(existing.priority or 0) != 120:
                        existing.priority = 120
                        updates.append("priority")
                    if not bool(existing.is_active):
                        existing.is_active = True
                        updates.append("is_active")
                    note = str(existing.note or "")
                    if MIGRATION_NOTE_MARKER not in note:
                        existing.note = f"{note} {MIGRATION_NOTE_MARKER} bootstrap route migration".strip()
                        updates.append("note")
                    if updates:
                        updates.append("updated_at")
                        existing.save(update_fields=updates)
                        updated_bindings += 1
                    else:
                        reused_bindings += 1

                if row.status_before != STATUS_LEGACY_FALLBACK:
                    continue
                if conflict:
                    continue

                legacy_pairs: list[tuple[str, str]] = []
                route_matches = route_index.get(row.route_name, [])
                if route_matches:
                    legacy_pairs.extend(route_matches)
                for path_prefix, modulo, azione in path_index:
                    if row.sample_path == path_prefix or row.sample_path.startswith(path_prefix + "/"):
                        legacy_pairs.append((modulo, azione))
                seen_pairs: set[tuple[str, str]] = set()
                for modulo, azione in legacy_pairs:
                    key = (str(modulo or "").strip().lower(), str(azione or "").strip().lower())
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    role_grants = grants_index.get(key, {})
                    for legacy_role_id, enabled in role_grants.items():
                        grant, grant_created = RolePermissionGrant.objects.get_or_create(
                            legacy_role_id=int(legacy_role_id),
                            permission_id=permission.code,
                            defaults={
                                "enabled": bool(enabled),
                                "note": f"{MIGRATION_NOTE_MARKER} legacy grant sync {modulo}.{azione}",
                            },
                        )
                        if grant_created:
                            created_role_grants += 1
                            continue
                        grant_note = str(grant.note or "")
                        if MIGRATION_NOTE_MARKER not in grant_note:
                            continue
                        if bool(grant.enabled) != bool(enabled):
                            grant.enabled = bool(enabled)
                            grant.note = f"{MIGRATION_NOTE_MARKER} legacy grant sync {modulo}.{azione}"
                            grant.save(update_fields=["enabled", "note", "updated_at"])
                            updated_role_grants += 1

        return (
            created_permissions,
            created_bindings,
            updated_bindings,
            reused_bindings,
            conflicts,
            created_role_grants,
            updated_role_grants,
        )
