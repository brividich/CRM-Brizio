from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings
from django.db import DatabaseError, connections
from django.urls import NoReverseMatch, reverse

from core.acl import check_permesso
from core.impersonation import display_name_for_user
from core.legacy_utils import get_legacy_user, is_legacy_admin, legacy_auth_enabled, legacy_table_has_column
from core.legacy_cache import (
    get_cached_perm_map,
    get_cached_pulsanti_catalog,
    get_cached_pulsanti_order_map,
    get_cached_ui_meta_map,
    normalize_legacy_path,
)
from core.module_registry import resolve_module_label
from core.navigation_registry import get_subnav_nodes, get_topbar_nodes
from core.versioning import get_changelog_entries, get_current_release, get_module_versions

NAV_REGISTRY_ACL_GATES: dict[str, str] = {
    "tasks": "/tasks/",
}


@dataclass
class NavItem:
    label: str
    legacy_url: str
    href: str
    active: bool
    coming: bool
    modulo: str
    codice: str
    order_hint: int | None = None


def _normalize_path(path: str) -> str:
    return normalize_legacy_path(path)


def _path_variants(path: str) -> set[str]:
    norm = _normalize_path(path)
    variants = {norm}
    if norm == "/":
        variants.add("/dashboard")
    elif norm == "/dashboard":
        variants.add("/")
    return variants


def _route_name_for_legacy_item(modulo: str, codice: str, legacy_url: str) -> tuple[str, bool]:
    path = _normalize_path(legacy_url)
    modulo_l = (modulo or "").strip().lower()
    codice_l = (codice or "").strip().lower()
    explicit_admin_map = {
        "pannello_admin": "admin_portale:index",
        "gestione_utenti": "admin_portale:utenti_list",
        "gestione_permessi": "admin_portale:permessi",
        "gestione_ruoli": "admin_portale:permessi",
        "gestione_pulsanti": "admin_portale:pulsanti",
    }
    if codice_l in explicit_admin_map:
        return explicit_admin_map[codice_l], False
    if path in {"/", "/dashboard"} or "dashboard" in codice_l:
        return "dashboard", False
    if path.startswith("/assenze") or modulo_l == "assenze":
        return "assenze_menu", False
    if "anom" in path or "anom" in codice_l or "anom" in modulo_l:
        return "gestione_anomalie_page", False
    if path in {"/admin/gestione_utenti", "/admin/anagrafica"}:
        return "admin_portale:utenti_list", False
    if path in {"/admin/gestione_ruoli", "/admin/permessi"}:
        return "admin_portale:permessi", False
    if path in {"/admin/gestione_pulsanti"}:
        return "admin_portale:pulsanti", False
    if path in {"/admin/log-audit", "/admin/force_migrations"}:
        return "admin_portale:schema_dati", False
    if path in {"/admin/anagrafica/sync_ad"}:
        return "admin_portale:ldap_diagnostica", False
    if path.startswith("/admin") or modulo_l == "admin":
        return "admin_portale:index", False
    return "coming_admin", True


def _resolve_nav_href_from_pulsante(pulsante: dict) -> tuple[str, bool]:
    raw_url = (pulsante.get("url") or "").strip()
    lower = raw_url.lower()
    for prefix in ("route:", "django:"):
        if lower.startswith(prefix):
            route_name = raw_url[len(prefix):].strip()
            if route_name:
                try:
                    return reverse(route_name), False
                except NoReverseMatch:
                    break
    if lower.startswith(("http://", "https://")):
        return raw_url, False
    route_name, coming = _route_name_for_legacy_item(
        pulsante.get("modulo") or "",
        pulsante.get("codice") or "",
        pulsante.get("url") or "",
    )
    return reverse(route_name), coming


def _navigation_registry_enabled() -> bool:
    value = getattr(settings, "NAVIGATION_REGISTRY_ENABLED", True)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _navigation_legacy_fallback_enabled() -> bool:
    value = getattr(settings, "NAVIGATION_LEGACY_FALLBACK_ENABLED", True)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _ensure_dashboard_nav(items: list[NavItem], current_variants: set[str]) -> list[NavItem]:
    has_dashboard = False
    for item in items:
        href_path = _normalize_path(urlsplit(item.href).path or "/")
        if href_path in {"/", "/dashboard"} or item.legacy_url in {"/", "/dashboard"}:
            has_dashboard = True
            break

    if has_dashboard:
        return items

    try:
        dash_href = reverse("dashboard_home")
    except NoReverseMatch:
        dash_href = reverse("dashboard")
    items.append(
        NavItem(
            label="Dashboard",
            legacy_url="/dashboard",
            href=dash_href,
            active=bool(current_variants.intersection({"/", "/dashboard"})),
            coming=False,
            modulo="core",
            codice="dashboard",
            order_hint=-1000,
        )
    )
    return items


def _load_registry_nav_items(request, legacy_user) -> list[NavItem]:
    if not _navigation_registry_enabled():
        return []
    is_admin = bool(getattr(request.user, "is_superuser", False))
    if legacy_user:
        is_admin = bool(is_admin or is_legacy_admin(legacy_user))
    role_id = None
    if legacy_user and getattr(legacy_user, "ruolo_id", None):
        try:
            role_id = int(legacy_user.ruolo_id)
        except Exception:
            role_id = None

    nodes = get_topbar_nodes(current_path=request.path, role_id=role_id, is_admin=is_admin)
    filtered_nodes = []
    for node in nodes:
        gate_path = NAV_REGISTRY_ACL_GATES.get((node.codice or "").strip().lower())
        if gate_path is None:
            filtered_nodes.append(node)
            continue
        if is_admin:
            filtered_nodes.append(node)
            continue
        if legacy_user and check_permesso(legacy_user, gate_path):
            filtered_nodes.append(node)
    nodes = filtered_nodes
    if not nodes:
        return []
    return [
        NavItem(
            label=node.label,
            legacy_url=node.legacy_url,
            href=node.href,
            active=node.active,
            coming=node.coming,
            modulo=node.modulo,
            codice=node.codice,
            order_hint=node.order_hint,
        )
        for node in nodes
    ]


def _count_car_pending(legacy_user_id: int | None, legacy_user=None) -> int:
    """Conta le assenze in attesa del personale gestito da un CAR (per il badge topbar)."""
    manager_name = str(getattr(legacy_user, "nome", "") or "").strip() if legacy_user else ""
    manager_email = str(getattr(legacy_user, "email", "") or "").strip() if legacy_user else ""

    clauses = []
    params = []
    if legacy_user_id is not None:
        clauses.append("a.capo_reparto_id = %s")
        params.append(int(legacy_user_id))
    if legacy_table_has_column("capi_reparto", "id"):
        if manager_email:
            clauses.append("UPPER(COALESCE(cr.indirizzo_email,'')) = UPPER(%s)")
            params.append(manager_email)
        if manager_name:
            clauses.append("UPPER(COALESCE(cr.nome,'')) = UPPER(%s)")
            params.append(manager_name)
            clauses.append("UPPER(COALESCE(cr.title,'')) = UPPER(%s)")
            params.append(manager_name)

    if not clauses:
        return 0
    try:
        join_sql = "LEFT JOIN capi_reparto cr ON cr.id = a.capo_reparto_id" if legacy_table_has_column("capi_reparto", "id") else ""
        with connections["default"].cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM assenze a
                {join_sql}
                WHERE ({' OR '.join(clauses)})
                  AND COALESCE(a.moderation_status, 2) = 2
                """,
                params,
            )
            row = cursor.fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


def _detect_subnav_parent_code(request) -> str:
    """Determina il parent_code della subnav dalla namespace dell'app corrente."""
    try:
        app_name = getattr(request.resolver_match, "app_name", "") or ""
        # "" o "dashboard" → gruppo "dashboard"
        return app_name if app_name else "dashboard"
    except Exception:
        return "dashboard"


def _load_subnav_items(request, legacy_user) -> list:
    """Carica le voci subnav per la sezione corrente dal Navigation Registry."""
    if not _navigation_registry_enabled():
        return []
    is_admin = bool(getattr(request.user, "is_superuser", False))
    if legacy_user:
        is_admin = bool(is_admin or is_legacy_admin(legacy_user))
    role_id = None
    if legacy_user and getattr(legacy_user, "ruolo_id", None):
        try:
            role_id = int(legacy_user.ruolo_id)
        except Exception:
            role_id = None
    parent_code = _detect_subnav_parent_code(request)
    try:
        nodes = get_subnav_nodes(parent_code=parent_code, role_id=role_id, is_admin=is_admin)
    except Exception:
        return []
    if not nodes:
        return []
    current_variants = _path_variants(request.path)
    result = []
    for node in nodes:
        from urllib.parse import urlsplit as _urlsplit
        href_path = _normalize_path(_urlsplit(node.href).path or "/")
        active = bool(current_variants.intersection({href_path}))
        result.append(NavItem(
            label=node.label,
            legacy_url=node.legacy_url,
            href=node.href,
            active=active,
            coming=node.coming,
            modulo="navigation",
            codice=node.codice,
            order_hint=node.order_hint,
        ))
    return result


def legacy_nav(request):
    result = {
        "nav_items": [],
        "legacy_user": None,
        "car_pending_count": 0,
        "notifiche_count": 0,
        "subnav_items": [],
        "impersonation_active": False,
        "impersonator_display": "",
        "impersonated_display": "",
        "impersonation_stop_url": "",
    }
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return result

    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    result["legacy_user"] = legacy_user
    if getattr(request, "impersonation_active", False):
        result["impersonation_active"] = True
        result["impersonator_display"] = display_name_for_user(
            django_user=getattr(request, "impersonator_user", None),
            legacy_user=getattr(request, "impersonator_legacy_user", None),
        )
        result["impersonated_display"] = display_name_for_user(
            django_user=getattr(request, "impersonated_user", None) or getattr(request, "user", None),
            legacy_user=getattr(request, "impersonated_legacy_user", None) or legacy_user,
        )
        try:
            result["impersonation_stop_url"] = reverse("stop_impersonation")
        except NoReverseMatch:
            result["impersonation_stop_url"] = ""
    current_variants = _path_variants(request.path)

    # Badge pending CAR + contatore notifiche
    legacy_user_id = getattr(legacy_user, "id", None) if legacy_user else None
    if legacy_user_id:
        try:
            result["car_pending_count"] = _count_car_pending(int(legacy_user_id), legacy_user=legacy_user)
        except Exception:
            pass
        try:
            from core.models import Notifica
            result["notifiche_count"] = Notifica.objects.filter(
                legacy_user_id=int(legacy_user_id), letta=False
            ).count()
        except Exception:
            pass

    if _navigation_registry_enabled():
        try:
            registry_items = _load_registry_nav_items(request, legacy_user)
        except Exception:
            registry_items = []
        has_registry_items = bool(registry_items)
        if has_registry_items or not _navigation_legacy_fallback_enabled():
            registry_items = _ensure_dashboard_nav(registry_items, current_variants)
            registry_items.sort(key=lambda x: ((x.order_hint if x.order_hint is not None else 999999), x.label.lower()))
            result["nav_items"] = registry_items
            result["subnav_items"] = _load_subnav_items(request, legacy_user)
            return result

    if not legacy_auth_enabled() or not legacy_user or not legacy_user.ruolo_id:
        return result

    try:
        perm_map = get_cached_perm_map(int(legacy_user.ruolo_id))
        order_map = get_cached_pulsanti_order_map()
        ui_meta_map = get_cached_ui_meta_map()
        items: list[NavItem] = []
        is_admin = is_legacy_admin(legacy_user)
        for puls in get_cached_pulsanti_catalog():
            pulsante_id = int(puls["id"])
            meta = ui_meta_map.get(pulsante_id, {})
            if meta and not bool(meta.get("enabled", True)):
                continue
            if meta and not bool(meta.get("visible_topbar", True)):
                continue
            if meta and meta.get("ui_slot") and meta.get("ui_slot") not in {"topbar", "toolbar"}:
                continue
            key = ((puls.get("modulo_norm") or "").strip(), (puls.get("codice_norm") or "").strip())
            if not is_admin and not perm_map.get(key, False):
                continue
            href, coming = _resolve_nav_href_from_pulsante(puls)
            legacy_url = _normalize_path(puls.get("url") or "/")
            href_path = _normalize_path(urlsplit(href).path or "/")
            active = bool(current_variants.intersection({href_path, legacy_url}))
            ui_order_hint = meta.get("ui_order") if isinstance(meta, dict) else None
            modulo_key = str(puls.get("modulo") or "").strip().lower()
            label_value = str(puls.get("label", "N/D") or "N/D")
            if modulo_key:
                label_value = resolve_module_label(modulo_key, fallback=label_value, surface="menu")
            items.append(
                NavItem(
                    label=label_value,
                    legacy_url=legacy_url,
                    href=href,
                    active=active,
                    coming=coming,
                    modulo=(puls.get("modulo") or ""),
                    codice=(puls.get("codice") or ""),
                    order_hint=(ui_order_hint if ui_order_hint is not None else order_map.get(pulsante_id)),
                )
            )

        items = _ensure_dashboard_nav(items, current_variants)

        items.sort(key=lambda x: ((x.order_hint if x.order_hint is not None else 999999), x.label.lower()))
        result["nav_items"] = items
    except DatabaseError:
        pass

    return result


def app_meta(_request):
    current_release = get_current_release()
    return {
        "app_version": str(getattr(settings, "APP_VERSION", "") or "").strip(),
        "module_versions": get_module_versions(),
        "current_release": current_release,
        "release_notes_preview": list(current_release.get("items") or [])[:6],
        "recent_releases": get_changelog_entries(limit=3),
    }
