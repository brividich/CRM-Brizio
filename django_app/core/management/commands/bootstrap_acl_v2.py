from __future__ import annotations

import re
from dataclasses import dataclass

from django.core.management.base import BaseCommand
from django.db import DatabaseError, transaction
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils.text import slugify

from core.acl_v2 import (
    normalize_binding_path_pattern,
    normalize_permission_code,
    validate_permission_code,
)
from core.legacy_models import Permesso, Pulsante
from core.models import PermissionDefinition, RolePermissionGrant, RoutePermissionBinding


_DYNAMIC_SEGMENT_RE = re.compile(r"<[^>]+>")


@dataclass
class RouteRow:
    route_name: str
    route_pattern: str
    sample_path: str


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
                rows.append(
                    RouteRow(
                        route_name=route_name,
                        route_pattern=route_pattern,
                        sample_path=normalize_binding_path_pattern(sample_path or "/"),
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
    rows.sort(key=lambda row: row.route_name)
    return rows


def _infer_source_app(route_name: str, path: str) -> str:
    if ":" in route_name:
        return route_name.split(":", 1)[0]
    parts = [p for p in path.split("/") if p]
    if parts:
        return parts[0]
    return "core"


def _suggest_permission_code(route_name: str, sample_path: str) -> str:
    if route_name:
        base = route_name.replace(":", ".")
    else:
        pieces = [p for p in sample_path.split("/") if p]
        base = ".".join(pieces[:3]) if pieces else "root"
    code = normalize_permission_code(base)
    if not code:
        code = "route.generated"
    if not code.endswith(".view"):
        code = normalize_permission_code(f"{code}.view")
    is_valid, _ = validate_permission_code(code)
    if not is_valid:
        fallback = normalize_permission_code(f"{_infer_source_app(route_name, sample_path)}.route.view")
        is_fallback_valid, _ = validate_permission_code(fallback)
        if is_fallback_valid:
            return fallback
        return "core.route.view"
    return code


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


def _canonical_catalog() -> tuple[set[str], list[RoutePermissionBinding]]:
    try:
        route_names = {
            str(name).strip()
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
            "--import-legacy",
            action="store_true",
            help="Importa da pulsanti/permessi legacy creando binding e grant canonici equivalenti.",
        )
        parser.add_argument(
            "--activate-generated-bindings",
            action="store_true",
            help="I binding generati dalla scansione route vengono creati attivi (default: inattivi per sicurezza).",
        )

    def handle(self, *args, **options):
        do_apply = bool(options.get("apply"))
        do_import_legacy = bool(options.get("import_legacy"))
        activate_generated = bool(options.get("activate_generated_bindings"))

        all_routes = _collect_named_routes()
        routes = [row for row in all_routes if not row.route_name.startswith("admin:")]
        self.stdout.write(
            self.style.NOTICE(
                f"Route nominate trovate: {len(routes)} (filtrate: escluse route Django admin interne: {len(all_routes) - len(routes)})"
            )
        )

        created_permissions = 0
        created_bindings = 0
        imported_legacy_bindings = 0
        imported_legacy_grants = 0

        if do_import_legacy:
            (
                created_permissions,
                imported_legacy_bindings,
                imported_legacy_grants,
            ) = self._import_legacy_into_canonical()

        route_names_active, path_bindings_active = _canonical_catalog()
        suggested: list[tuple[RouteRow, str, str]] = []

        for row in routes:
            if row.route_name in route_names_active:
                continue
            if _match_path_binding(row.sample_path, path_bindings_active):
                continue
            suggested_code = _suggest_permission_code(row.route_name, row.sample_path)
            source_app = _infer_source_app(row.route_name, row.sample_path)
            suggested.append((row, suggested_code, source_app))

        if do_apply and suggested:
            created_bindings = self._apply_route_suggestions(
                suggested=suggested,
                activate_generated=activate_generated,
            )

        route_names_active, path_bindings_active = _canonical_catalog()
        legacy_route_names, legacy_paths, _ = _legacy_catalog()

        with_canonical: list[RouteRow] = []
        only_legacy: list[RouteRow] = []
        no_coverage: list[RouteRow] = []

        for row in routes:
            has_canonical = row.route_name in route_names_active or _match_path_binding(row.sample_path, path_bindings_active)
            if has_canonical:
                with_canonical.append(row)
                continue

            has_legacy = row.route_name in legacy_route_names
            if not has_legacy:
                for pattern in legacy_paths:
                    if row.sample_path == pattern or row.sample_path.startswith(pattern + "/"):
                        has_legacy = True
                        break
            if has_legacy:
                only_legacy.append(row)
            else:
                no_coverage.append(row)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Report bootstrap ACL v2"))
        self.stdout.write(f"- {len(with_canonical)} route classificate CANONICAL_BOUND")
        self.stdout.write(f"- {len(only_legacy)} route classificate LEGACY_FALLBACK")
        self.stdout.write(f"- {len(no_coverage)} route classificate UNBOUND")
        self.stdout.write(f"- Route con proposta nuova: {len(suggested)}")
        self.stdout.write(f"- Permission create/aggiornate da import legacy: {created_permissions}")
        self.stdout.write(f"- Binding importati da legacy: {imported_legacy_bindings}")
        self.stdout.write(f"- Grant ruolo importati da legacy: {imported_legacy_grants}")
        self.stdout.write(f"- Binding generati da scansione route: {created_bindings}")

        if suggested:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Prime 25 proposte route -> permission_code"))
            for row, permission_code, source_app in suggested[:25]:
                self.stdout.write(
                    f"  - {row.route_name} [{row.sample_path}] -> {permission_code} (source_app={source_app})"
                )

        if only_legacy:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Prime 25 route LEGACY_FALLBACK"))
            for row in only_legacy[:25]:
                self.stdout.write(f"  - {row.route_name} [{row.sample_path}]")

        if no_coverage:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR("Prime 25 route UNBOUND"))
            for row in no_coverage[:25]:
                self.stdout.write(f"  - {row.route_name} [{row.sample_path}]")

        if do_apply:
            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(
                    "Bootstrap ACL v2 completato in modalità APPLY."
                    if created_bindings or imported_legacy_bindings or imported_legacy_grants
                    else "Nessuna modifica da applicare."
                )
            )
        else:
            self.stdout.write("")
            self.stdout.write(
                self.style.NOTICE(
                    "Modalità dry-run: nessuna modifica. Usa --apply per creare permission/binding."
                )
            )

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
                        "note": f"Import automatico da pulsanti.id={button.id}",
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
                        "note": "Import automatico da tabella legacy permessi",
                    },
                )
                if created_grant:
                    created_grants += 1

        return created_permissions, created_bindings, created_grants

    def _apply_route_suggestions(self, *, suggested: list[tuple[RouteRow, str, str]], activate_generated: bool) -> int:
        created_bindings = 0
        with transaction.atomic():
            for row, permission_code, source_app in suggested:
                label = row.route_name.replace(":", " / ")
                permission, _ = PermissionDefinition.objects.get_or_create(
                    code=permission_code,
                    defaults={
                        "label": label,
                        "module": source_app,
                        "description": f"Bootstrap route scan: {row.route_name}",
                        "is_active": True,
                    },
                )
                _, created = RoutePermissionBinding.objects.get_or_create(
                    route_name=row.route_name,
                    path_pattern="",
                    defaults={
                        "match_strategy": RoutePermissionBinding.MATCH_EXACT,
                        "permission_id": permission.code,
                        "source_app": source_app,
                        "note": "Bootstrap automatico da scansione URL Django",
                        "priority": 200,
                        "is_active": bool(activate_generated),
                    },
                )
                if created:
                    created_bindings += 1
        return created_bindings
