"""Report runtime dell'uso del fallback ACL legacy.

Incrocia le route scoperte da `bootstrap_acl_v2` (CANONICAL_BOUND / LEGACY_FALLBACK
/ UNBOUND) con i binding canonici attualmente configurati in DB, per capire:

- quante route sono ancora scoperte da RoutePermissionBinding
- quante hanno binding ma non permission attiva
- quali app concentrano il debito residuo della migrazione ACL v2

Usa solo stato del codice e del DB — non ha bisogno di accedere ai file di log,
che su IIS sono per-worker e non aggregabili in modo affidabile.

Esempi:
    python manage.py acl_fallback_report
    python manage.py acl_fallback_report --app assenze
    python manage.py acl_fallback_report --format json
"""
from __future__ import annotations

import json
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.urls import get_resolver

from core.models import PermissionDefinition, RoutePermissionBinding


def is_django_admin_route(pattern: str) -> bool:
    """True se la route appartiene al Django admin contrib (montato su 'admin/').

    Le route del Django admin sono protette dal suo stesso gate (is_staff /
    is_superuser) e sono fuori dal perimetro ACL applicativo: non vanno
    migrate a RoutePermissionBinding. Il discriminante affidabile e' il pattern
    URL (inizia con 'admin/'), non il nome: route applicative legittime possono
    avere 'admin' nel nome o suffissi come '_add'/'_change' (es.
    'dipendente_qualifica_add', 'wo_checklist_add'). Nota: 'admin-portale/' NON
    e' Django admin.
    """
    p = (pattern or "").lstrip("^/").strip()
    return p == "admin/" or p.startswith("admin/")


class Command(BaseCommand):
    help = "Report route ACL v2: coverage binding canonico vs fallback legacy."

    def add_arguments(self, parser):
        parser.add_argument("--app", help="Limita al prefisso app (es. 'assenze').")
        parser.add_argument(
            "--format", choices=("text", "json"), default="text",
            help="Formato output (default: text).",
        )
        parser.add_argument(
            "--only-unbound", action="store_true",
            help="Mostra solo le route senza binding canonico.",
        )
        parser.add_argument(
            "--include-admin", action="store_true",
            help=(
                "Includi anche le route del Django admin (montato su 'admin/'). "
                "Di default sono escluse perche' fuori dal perimetro ACL "
                "applicativo (protette da is_staff/is_superuser)."
            ),
        )

    def handle(self, *args, **opts):
        app_filter = (opts.get("app") or "").strip().lower()
        only_unbound = bool(opts.get("only_unbound"))
        include_admin = bool(opts.get("include_admin"))
        fmt = opts.get("format") or "text"

        bindings = {
            (b.route_name or "").strip(): b
            for b in RoutePermissionBinding.objects.select_related("permission").all()
            if (b.route_name or "").strip()
        }
        permissions = {
            p.code: p for p in PermissionDefinition.objects.all()
        }

        resolver = get_resolver()
        routes: list[dict] = []
        self._walk(resolver.url_patterns, prefix="", out=routes)

        by_app: dict[str, list[dict]] = defaultdict(list)
        excluded_admin = 0
        for r in routes:
            name = r["name"] or ""
            if not include_admin and is_django_admin_route(r["pattern"]):
                excluded_admin += 1
                continue
            app = name.split(":")[0] if ":" in name else "_"
            if app_filter and app_filter not in app:
                continue
            binding = bindings.get(name)
            status = "UNBOUND"
            perm_code = ""
            perm_active = None
            if binding is not None:
                perm_code = (binding.permission.code if binding.permission_id else "") or ""
                perm_active = bool(binding.permission.is_active) if binding.permission_id else False
                status = "BOUND_ACTIVE" if perm_active else "BOUND_INACTIVE"
            if only_unbound and status != "UNBOUND":
                continue
            by_app[app].append({
                "name": name, "pattern": r["pattern"], "status": status,
                "permission_code": perm_code, "permission_active": perm_active,
            })

        summary = {
            "total_routes": sum(len(v) for v in by_app.values()),
            "total_permissions": len(permissions),
            "total_bindings": len(bindings),
            "excluded_django_admin": excluded_admin,
            "by_app": {},
        }
        for app, entries in sorted(by_app.items()):
            counters = defaultdict(int)
            for e in entries:
                counters[e["status"]] += 1
            summary["by_app"][app] = dict(counters)

        if fmt == "json":
            self.stdout.write(json.dumps(
                {"summary": summary, "routes": sum(by_app.values(), [])},
                indent=2, default=str,
            ))
            return

        self.stdout.write(self.style.MIGRATE_HEADING("ACL v2 — Route coverage report"))
        self.stdout.write(f"Route totali analizzate : {summary['total_routes']}")
        self.stdout.write(f"Permission definitions  : {summary['total_permissions']}")
        self.stdout.write(f"Route bindings attivi   : {summary['total_bindings']}")
        if not include_admin:
            self.stdout.write(
                f"Route Django admin escl.: {summary['excluded_django_admin']} "
                f"(fuori perimetro ACL; usa --include-admin per mostrarle)"
            )
        self.stdout.write("")
        for app, counters in sorted(summary["by_app"].items()):
            bound_active = counters.get("BOUND_ACTIVE", 0)
            bound_inactive = counters.get("BOUND_INACTIVE", 0)
            unbound = counters.get("UNBOUND", 0)
            total = bound_active + bound_inactive + unbound
            self.stdout.write(
                f"  {app:<30} total={total:>4}  "
                f"bound={bound_active:>3}  inactive={bound_inactive:>2}  "
                f"unbound={unbound:>3}"
            )
        self.stdout.write("")
        if only_unbound:
            self.stdout.write(self.style.WARNING("Route senza binding (candidate al fallback legacy):"))
            for app, entries in sorted(by_app.items()):
                for e in entries:
                    self.stdout.write(f"  [{app}] {e['name']}  {e['pattern']}")

    def _walk(self, patterns, prefix, out):
        for p in patterns:
            pattern_str = str(getattr(p, "pattern", "") or "")
            full = prefix + pattern_str
            if hasattr(p, "url_patterns"):
                nested_prefix = full
                inner_ns = getattr(p, "namespace", "") or ""
                self._walk(p.url_patterns, nested_prefix, out)
                if inner_ns:
                    # Le route nested con namespace verranno riprodotte dai figli.
                    continue
            else:
                name = getattr(p, "name", "") or ""
                if not name:
                    continue
                out.append({"name": name, "pattern": full})
