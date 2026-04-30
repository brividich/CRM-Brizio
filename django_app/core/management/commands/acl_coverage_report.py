from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import NoReverseMatch, URLPattern, URLResolver, get_resolver, reverse

from core.acl import normalize_acl_path
from core.acl_v2 import normalize_binding_path_pattern
from core.models import PermissionDefinition, RoutePermissionBinding


@dataclass(frozen=True)
class RouteInfo:
    name: str
    pattern: str
    path: str
    namespace: str
    app: str
    status: str
    reason: str
    permission_code: str
    permission_active: bool | None
    binding_id: int | None
    matched_by: str
    is_dynamic: bool
    is_reversible: bool


def _normalize_pattern_path(raw_pattern: str) -> str:
    value = str(raw_pattern or "").strip()
    value = value.lstrip("^").rstrip("$")
    value = re.sub(r"\(\?P<[^>]+>[^)]*\)", "<dynamic>", value)
    if not value.startswith("/"):
        value = f"/{value}"
    return normalize_acl_path(value)


def _path_matches_prefix(path: str, prefix: str) -> bool:
    path_norm = normalize_acl_path(path)
    prefix_norm = normalize_acl_path(prefix)
    if prefix_norm == "/":
        return True
    return path_norm == prefix_norm or path_norm.startswith(prefix_norm + "/")


def _binding_matches_path(binding: RoutePermissionBinding, path: str) -> bool:
    strategy = (binding.match_strategy or RoutePermissionBinding.MATCH_EXACT).lower()
    path_norm = normalize_acl_path(path)
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


def _route_app(route_name: str, path: str) -> str:
    if ":" in route_name:
        return route_name.split(":", 1)[0] or "_"
    first_segment = normalize_acl_path(path).strip("/").split("/", 1)[0]
    return first_segment or "_root"


def _route_is_dynamic(pattern: str) -> bool:
    return "<" in pattern or ">" in pattern or "(?P<" in pattern


def _reverse_route(route_name: str) -> tuple[str, bool]:
    if not route_name:
        return "", False
    try:
        return normalize_acl_path(reverse(route_name)), True
    except NoReverseMatch:
        return "", False
    except Exception:
        return "", False


def _walk_urlpatterns(
    patterns,
    *,
    prefix: str = "",
    namespace: str = "",
    out: list[dict],
    errors: list[dict],
) -> None:
    for pattern in patterns:
        pattern_text = str(getattr(pattern, "pattern", "") or "")
        full_pattern = f"{prefix}{pattern_text}"

        if isinstance(pattern, URLResolver):
            child_namespace = getattr(pattern, "namespace", "") or ""
            next_namespace = namespace
            if child_namespace:
                next_namespace = f"{namespace}:{child_namespace}" if namespace else child_namespace
            try:
                _walk_urlpatterns(
                    pattern.url_patterns,
                    prefix=full_pattern,
                    namespace=next_namespace,
                    out=out,
                    errors=errors,
                )
            except Exception as exc:
                errors.append(
                    {
                        "pattern": full_pattern,
                        "namespace": next_namespace,
                        "error": f"{exc.__class__.__name__}: {exc}",
                    }
                )
            continue

        if not isinstance(pattern, URLPattern):
            continue

        raw_name = getattr(pattern, "name", "") or ""
        route_name = f"{namespace}:{raw_name}" if namespace and raw_name else raw_name
        out.append(
            {
                "name": route_name,
                "pattern": full_pattern,
                "path": _normalize_pattern_path(full_pattern),
                "namespace": namespace,
            }
        )


def _binding_payload(binding: RoutePermissionBinding | None, matched_by: str) -> tuple[str, bool | None, int | None, str]:
    if binding is None:
        return "", None, None, ""
    permission = getattr(binding, "permission", None)
    permission_active = bool(permission.is_active) if permission is not None else False
    return binding.permission_id or "", permission_active, int(binding.id), matched_by


def _find_binding(
    route: dict,
    route_bindings: dict[str, RoutePermissionBinding],
    path_bindings: list[RoutePermissionBinding],
) -> tuple[RoutePermissionBinding | None, str]:
    route_name = (route.get("name") or "").strip()
    if route_name:
        binding = route_bindings.get(route_name.lower())
        if binding is not None:
            return binding, "route_name"

    path = route.get("path") or ""
    matching_path_bindings = [
        binding for binding in path_bindings
        if _binding_matches_path(binding, path)
    ]
    if matching_path_bindings:
        matching_path_bindings.sort(
            key=lambda item: (
                int(item.priority or 0),
                0 if item.match_strategy == RoutePermissionBinding.MATCH_EXACT else 1,
                -len(item.path_pattern or ""),
                int(item.id or 0),
            )
        )
        return matching_path_bindings[0], "path_pattern"
    return None, ""


def _is_excluded_route(route: dict, *, include_admin: bool) -> tuple[bool, str]:
    path = route.get("path") or "/"
    route_name = route.get("name") or ""

    if not include_admin and (route_name.startswith("admin:") or _path_matches_prefix(path, "/admin/")):
        return True, "django_admin"

    for prefix in getattr(settings, "MIDDLEWARE_EXEMPT_PREFIXES", ()):
        if _path_matches_prefix(path, str(prefix)):
            return True, f"settings.MIDDLEWARE_EXEMPT_PREFIXES:{prefix}"

    return False, ""


def build_acl_coverage(*, include_admin: bool = False) -> dict:
    routes: list[dict] = []
    errors: list[dict] = []
    resolver = get_resolver()
    _walk_urlpatterns(resolver.url_patterns, out=routes, errors=errors)

    bindings = list(
        RoutePermissionBinding.objects.filter(is_active=True)
        .select_related("permission")
        .order_by("priority", "id")
    )
    route_bindings = {
        binding.route_name.strip().lower(): binding
        for binding in bindings
        if binding.route_name.strip()
    }
    path_bindings = [binding for binding in bindings if binding.path_pattern.strip()]
    permission_count = PermissionDefinition.objects.count()

    classified: list[RouteInfo] = []
    for route in routes:
        route_name = route.get("name") or ""
        pattern = route.get("pattern") or ""
        path = route.get("path") or "/"
        namespace = route.get("namespace") or ""
        reversed_path, is_reversible = _reverse_route(route_name)
        inspection_path = reversed_path or path
        is_dynamic = _route_is_dynamic(pattern)
        app = _route_app(route_name, path)

        excluded, reason = _is_excluded_route({**route, "path": inspection_path}, include_admin=include_admin)
        if excluded:
            classified.append(
                RouteInfo(
                    name=route_name,
                    pattern=pattern,
                    path=inspection_path,
                    namespace=namespace,
                    app=app,
                    status="excluded",
                    reason=reason,
                    permission_code="",
                    permission_active=None,
                    binding_id=None,
                    matched_by="",
                    is_dynamic=is_dynamic,
                    is_reversible=is_reversible,
                )
            )
            continue

        binding, matched_by = _find_binding({**route, "path": inspection_path}, route_bindings, path_bindings)
        permission_code, permission_active, binding_id, matched_by = _binding_payload(binding, matched_by)
        if binding is None:
            status = "missing"
            reason = "no_active_canonical_route_binding"
        elif permission_active:
            status = "bound"
            reason = "active_canonical_binding"
        else:
            status = "bound_inactive_permission"
            reason = "binding_permission_inactive"

        classified.append(
            RouteInfo(
                name=route_name,
                pattern=pattern,
                path=inspection_path,
                namespace=namespace,
                app=app,
                status=status,
                reason=reason,
                permission_code=permission_code,
                permission_active=permission_active,
                binding_id=binding_id,
                matched_by=matched_by,
                is_dynamic=is_dynamic,
                is_reversible=is_reversible,
            )
        )

    counters = Counter(route.status for route in classified)
    by_app: dict[str, dict[str, int]] = defaultdict(dict)
    for app in sorted({route.app for route in classified}):
        app_counts = Counter(route.status for route in classified if route.app == app)
        by_app[app] = dict(sorted(app_counts.items()))

    return {
        "summary": {
            "total_routes": len(classified),
            "bound": counters.get("bound", 0),
            "bound_inactive_permission": counters.get("bound_inactive_permission", 0),
            "missing": counters.get("missing", 0),
            "excluded": counters.get("excluded", 0),
            "dynamic": sum(1 for route in classified if route.is_dynamic),
            "not_reversible": sum(1 for route in classified if not route.is_reversible),
            "permission_definitions": permission_count,
            "active_route_bindings": len(bindings),
            "resolver_errors": len(errors),
            "by_app": dict(by_app),
        },
        "routes": [asdict(route) for route in classified],
        "resolver_errors": errors,
    }


class Command(BaseCommand):
    help = "Report copertura ACL canonica v2 per le route Django registrate."

    def add_arguments(self, parser):
        parser.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            help="Formato output (default: text).",
        )
        parser.add_argument(
            "--fail-on-missing",
            action="store_true",
            help="Esce con codice non-zero se esistono route applicative senza binding canonico attivo.",
        )
        parser.add_argument(
            "--max-missing",
            type=int,
            default=None,
            metavar="N",
            help="Esce con codice non-zero se le route senza binding canonico superano N.",
        )
        parser.add_argument(
            "--include-admin",
            action="store_true",
            help="Include anche le route del Django admin nativo.",
        )

    def handle(self, *args, **options):
        report = build_acl_coverage(include_admin=bool(options["include_admin"]))

        if options["format"] == "json":
            self.stdout.write(json.dumps(report, indent=2, default=str))
        else:
            self._write_text_report(report)

        missing_count = int(report["summary"]["missing"])
        if options["fail_on_missing"] and missing_count:
            raise CommandError(f"ACL coverage check failed: {missing_count} route applicative senza binding canonico.")
        max_missing = options.get("max_missing")
        if max_missing is not None and missing_count > int(max_missing):
            raise CommandError(
                f"ACL coverage check failed: {missing_count} route applicative senza binding canonico "
                f"(soglia: {max_missing})."
            )

    def _write_text_report(self, report: dict) -> None:
        summary = report["summary"]
        self.stdout.write(self.style.MIGRATE_HEADING("ACL v2 - Route coverage report"))
        self.stdout.write(f"Route totali          : {summary['total_routes']}")
        self.stdout.write(f"Bound canoniche       : {summary['bound']}")
        self.stdout.write(f"Permesso inattivo     : {summary['bound_inactive_permission']}")
        self.stdout.write(f"Senza binding         : {summary['missing']}")
        self.stdout.write(f"Escluse/pubbliche     : {summary['excluded']}")
        self.stdout.write(f"Dinamiche             : {summary['dynamic']}")
        self.stdout.write(f"Non reversibili       : {summary['not_reversible']}")
        self.stdout.write(f"PermissionDefinition  : {summary['permission_definitions']}")
        self.stdout.write(f"Binding attivi        : {summary['active_route_bindings']}")

        if report["resolver_errors"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Resolver complessi/non ispezionabili:"))
            for item in report["resolver_errors"]:
                self.stdout.write(f"  {item['pattern']} - {item['error']}")

        self.stdout.write("")
        self.stdout.write("Riepilogo per app:")
        for app, counters in sorted(summary["by_app"].items()):
            self.stdout.write(
                f"  {app:<28} bound={counters.get('bound', 0):>3}  "
                f"missing={counters.get('missing', 0):>3}  "
                f"excluded={counters.get('excluded', 0):>3}  "
                f"inactive={counters.get('bound_inactive_permission', 0):>2}"
            )

        missing_routes = [route for route in report["routes"] if route["status"] == "missing"]
        if missing_routes:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Route applicative senza binding canonico:"))
            for route in missing_routes:
                marker = " dynamic" if route["is_dynamic"] else ""
                route_name = route["name"] or "<unnamed>"
                reversible = "" if route["is_reversible"] else " non-reversible"
                self.stdout.write(
                    f"  [{route['app']}] {route_name}{marker}{reversible}  "
                    f"{route['path']}  ({route['pattern']})"
                )
