from __future__ import annotations

from dataclasses import dataclass, field
import logging
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, connections
from django.urls import NoReverseMatch, reverse

from core.branding import get_portal_branding
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
from core.navigation_registry import (
    get_admin_subnav_nodes,
    get_sidebar_children_map,
    get_subnav_nodes,
    get_topbar_nodes,
)
from core.versioning import get_changelog_entries, get_current_release, get_module_versions

_NAV_LOG_ONCE_TTL_SECONDS = 300
logger = logging.getLogger(__name__)

# ── UI Preferences helpers ──────────────────────────────────────────────────
_UI_PREFS_SESSION_KEY = "_ui_prefs_v2"
_UI_PREFS_DEFAULTS: dict = {
    "nav_mode": "top",
    "theme_mode": "light",
    "font_scale": "normal",
    "sidebar_collapsed": False,
}
_SIDEBAR_FOOTER_ACTION_CATALOG: tuple[dict[str, str], ...] = (
    {
        "key": "car",
        "label": "CAR",
        "icon": "⚠",
        "hint": "Collegamento alle richieste CAR. Compare solo se ci sono elementi in attesa.",
    },
    {
        "key": "notifications",
        "label": "Notifiche",
        "icon": "🔔",
        "hint": "Centro notifiche con badge dei messaggi non letti.",
    },
    {
        "key": "user_panel_preferences",
        "label": "Preferenze",
        "icon": "⚙",
        "hint": "Apre la pagina delle preferenze interfaccia.",
    },
    {
        "key": "user_panel_profile",
        "label": "Profilo",
        "icon": "👤",
        "hint": "Accesso rapido al profilo utente.",
    },
    {
        "key": "user_panel_logout",
        "label": "Esci",
        "icon": "🚪",
        "hint": "Disconnessione rapida dal portale.",
    },
)
_SIDEBAR_FOOTER_ACTION_KEYS = {
    item["key"] for item in _SIDEBAR_FOOTER_ACTION_CATALOG if not item["key"].startswith("user_panel_")
}
_SIDEBAR_FOOTER_DEFAULT_ORDER = ("notifications",)


def _log_nav_once(level: str, cache_key: str, message: str, **extra) -> None:
    throttle_key = f"context_nav:{level}:{cache_key}"
    try:
        if not cache.add(throttle_key, 1, timeout=_NAV_LOG_ONCE_TTL_SECONDS):
            return
    except Exception:
        pass
    log_fn = getattr(logger, level, logger.info)
    log_fn(message, extra=extra)


def get_sidebar_footer_catalog() -> list[dict[str, str]]:
    return [dict(item) for item in _SIDEBAR_FOOTER_ACTION_CATALOG if not item["key"].startswith("user_panel_")]


def get_default_sidebar_footer_actions() -> list[str]:
    return list(_SIDEBAR_FOOTER_DEFAULT_ORDER)


def normalize_sidebar_footer_actions(raw_value, *, fallback_to_default: bool = True) -> list[str]:
    if raw_value is None:
        return get_default_sidebar_footer_actions() if fallback_to_default else []

    if isinstance(raw_value, str):
        values = [part.strip() for part in raw_value.split(",")]
    elif isinstance(raw_value, (list, tuple, set)):
        values = list(raw_value)
    else:
        return get_default_sidebar_footer_actions() if fallback_to_default else []

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = str(value or "").strip().lower()
        if not key or key not in _SIDEBAR_FOOTER_ACTION_KEYS or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def compact_sidebar_footer_actions(raw_value) -> list[str] | None:
    normalized = normalize_sidebar_footer_actions(raw_value, fallback_to_default=False)
    if normalized == get_default_sidebar_footer_actions():
        return None
    return normalized


def _get_ui_prefs(request) -> dict:
    """Legge le preferenze UI dalla cache di sessione; se assente le carica dal DB
    (solo se il record esiste già) oppure usa i default.
    NON crea mai record UserUiPreference: la creazione avviene solo al salvataggio esplicito."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {
            **_UI_PREFS_DEFAULTS,
            "sidebar_footer_actions": get_default_sidebar_footer_actions(),
        }

    cached = request.session.get(_UI_PREFS_SESSION_KEY)
    if cached and isinstance(cached, dict) and "nav_mode" in cached and "font_scale" in cached:
        data = {
            "nav_mode": cached.get("nav_mode") or _UI_PREFS_DEFAULTS["nav_mode"],
            "theme_mode": cached.get("theme_mode") or _UI_PREFS_DEFAULTS["theme_mode"],
            "font_scale": cached.get("font_scale") or _UI_PREFS_DEFAULTS["font_scale"],
            "sidebar_collapsed": bool(cached.get("sidebar_collapsed")),
            "sidebar_footer_actions": normalize_sidebar_footer_actions(
                cached.get("sidebar_footer_actions"), fallback_to_default=True
            ),
        }
        if data != cached:
            try:
                request.session[_UI_PREFS_SESSION_KEY] = data
            except Exception:
                pass
        return data

    try:
        from core.models import UserUiPreference
        prefs = UserUiPreference.objects.filter(user=request.user).first()
        if prefs:
            data = {
                "nav_mode": prefs.nav_mode,
                "theme_mode": getattr(prefs, "theme_mode", _UI_PREFS_DEFAULTS["theme_mode"]),
                "font_scale": prefs.font_scale,
                "sidebar_collapsed": prefs.sidebar_collapsed,
                "sidebar_footer_actions": normalize_sidebar_footer_actions(
                    getattr(prefs, "sidebar_footer_actions", None), fallback_to_default=True
                ),
            }
        else:
            data = {
                **_UI_PREFS_DEFAULTS,
                "sidebar_footer_actions": get_default_sidebar_footer_actions(),
            }
        try:
            request.session[_UI_PREFS_SESSION_KEY] = data
        except Exception:
            pass
        return data
    except Exception:
        return {
            **_UI_PREFS_DEFAULTS,
            "sidebar_footer_actions": get_default_sidebar_footer_actions(),
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
    icon: str = ""
    group: str = ""
    order_hint: int | None = None
    category_color: str = ""
    category_key: str = ""
    category_label: str = ""
    category_icon: str = ""
    category_order: int = 0
    children: list = field(default_factory=list)


def _group_nav_items(items: list) -> list[dict]:
    """Raggruppa le voci topbar per categoria.

    Ritorna una lista ordinata di dict:
    - type='category': {key, label, color, order, active, items: [NavItem, ...]}
    - type='item':     {item: NavItem, order: int}
    """
    cat_map: dict[str, dict] = {}
    direct: list[dict] = []
    for item in items:
        if item.category_key:
            if item.category_key not in cat_map:
                cat_map[item.category_key] = {
                    "type": "category",
                    "key": item.category_key,
                    "label": item.category_label,
                    "icon": item.category_icon,
                    "color": item.category_color,
                    "order": item.category_order,
                    "active": False,
                    "items": [],
                }
            grp = cat_map[item.category_key]
            grp["items"].append(item)
            if item.active:
                grp["active"] = True
        else:
            direct.append({"type": "item", "item": item, "order": item.order_hint or 100})
    merged = list(cat_map.values()) + direct
    merged.sort(key=lambda x: x["order"])
    return merged


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
                    _log_nav_once(
                        level="warning",
                        cache_key=f"legacy-pulsante-route-missing:{pulsante.get('id')}:{route_name}",
                        message="Legacy pulsante con route non risolvibile: fallback mappa legacy.",
                        pulsante_id=pulsante.get("id"),
                        modulo=pulsante.get("modulo"),
                        codice=pulsante.get("codice"),
                        route_name=route_name,
                    )
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


def _nav_order_value(item: NavItem) -> int:
    if item.order_hint is None:
        return 999999
    try:
        return int(item.order_hint)
    except Exception:
        return 999999


def _legacy_nav_dedupe_key(item: NavItem) -> str:
    module_key = str(item.modulo or "").strip().lower()
    if module_key:
        return f"module:{module_key}"
    label_key = str(item.label or "").strip().lower()
    if label_key:
        return f"label:{label_key}"
    target = str(item.legacy_url or "").strip() or str(item.href or "").strip()
    return f"target:{_normalize_path(urlsplit(target).path or target or '/')}"


def _legacy_nav_rank(item: NavItem) -> tuple[int, int, str, str]:
    return (
        1 if item.coming else 0,
        _nav_order_value(item),
        str(item.label or "").strip().lower(),
        str(item.codice or "").strip().lower(),
    )


def _dedupe_legacy_nav_items(items: list[NavItem]) -> list[NavItem]:
    """Riduce il fallback legacy a una sola voce topbar/sidebar per modulo.

    Le tabelle legacy possono avere piu pulsanti operativi per lo stesso modulo
    (lista, crea, gestione, ecc.). In modalita sidebar/topbar questi non devono
    diventare duplicati visivi del modulo.
    """
    chosen: dict[str, NavItem] = {}
    order: list[str] = []
    duplicate_count = 0
    for item in items:
        key = _legacy_nav_dedupe_key(item)
        if key not in chosen:
            chosen[key] = item
            order.append(key)
            continue
        duplicate_count += 1
        if _legacy_nav_rank(item) < _legacy_nav_rank(chosen[key]):
            chosen[key] = item
    if duplicate_count:
        _log_nav_once(
            level="warning",
            cache_key=f"legacy-dedup:{duplicate_count}",
            message="Navigation fallback legacy: voci duplicate per modulo nascoste nel menu principale.",
            duplicate_count=duplicate_count,
        )
    return [chosen[key] for key in order]


def _build_sidebar_children(child_nodes: list, request) -> tuple[list[NavItem], bool]:
    """Costruisce le NavItem figlie (3° livello) con stato attivo calcolato dal path.

    Match ESATTO su path+query, con fallback al solo path (coerente con _load_subnav_items).
    Ritorna (figli, almeno_uno_attivo).
    """
    if not child_nodes:
        return [], False
    current_variants = _path_variants(request.path)
    try:
        current_full = request.get_full_path()
    except Exception:
        current_full = request.path
    has_exact = any(n.href == current_full for n in child_nodes)
    children: list[NavItem] = []
    any_active = False
    for n in child_nodes:
        if has_exact:
            active = (n.href == current_full)
        else:
            href_path = _normalize_path(urlsplit(n.href).path or "/")
            active = bool(current_variants.intersection({href_path}))
        any_active = any_active or active
        children.append(
            NavItem(
                label=n.label,
                legacy_url=n.legacy_url,
                href=n.href,
                active=active,
                coming=n.coming,
                modulo=n.modulo,
                codice=n.codice,
                icon=n.icon,
                group=n.group,
                order_hint=n.order_hint,
            )
        )
    return children, any_active


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

    legacy_user_id_for_override = None
    if legacy_user and getattr(legacy_user, "id", None):
        try:
            legacy_user_id_for_override = int(legacy_user.id)
        except Exception:
            pass
    nodes = get_topbar_nodes(
        current_path=request.path,
        role_id=role_id,
        is_admin=is_admin,
        legacy_user_id=legacy_user_id_for_override,
    )
    if not nodes:
        return []
    child_map = get_sidebar_children_map(
        role_id=role_id,
        is_admin=is_admin,
        legacy_user_id=legacy_user_id_for_override,
    )
    items: list[NavItem] = []
    for node in nodes:
        children, child_active = _build_sidebar_children(child_map.get(node.codice, []), request)
        items.append(
            NavItem(
                label=node.label,
                legacy_url=node.legacy_url,
                href=node.href,
                active=bool(node.active or child_active),
                coming=node.coming,
                modulo=node.modulo,
                codice=node.codice,
                icon=node.icon,
                group=node.group,
                order_hint=node.order_hint,
                category_color=node.category_color,
                category_key=node.category_key,
                category_label=node.category_label,
                category_icon=node.category_icon,
                category_order=node.category_order,
                children=children,
            )
        )
    return items


_CAR_PENDING_ALLOWED_CLAUSES = frozenset({
    "a.capo_reparto_id = %s",
    "UPPER(COALESCE(cr.indirizzo_email,'')) = UPPER(%s)",
    "UPPER(COALESCE(cr.nome,'')) = UPPER(%s)",
    "UPPER(COALESCE(cr.title,'')) = UPPER(%s)",
})
_CAR_PENDING_ALLOWED_JOINS = frozenset({
    "",
    "LEFT JOIN capi_reparto cr ON cr.id = a.capo_reparto_id",
})


def _count_car_pending(legacy_user_id: int | None, legacy_user=None) -> int:
    """Conta le assenze in attesa del personale gestito da un CAR (per il badge topbar)."""
    manager_name = str(getattr(legacy_user, "nome", "") or "").strip() if legacy_user else ""
    manager_email = str(getattr(legacy_user, "email", "") or "").strip() if legacy_user else ""

    clauses: list[str] = []
    params: list = []
    if legacy_user_id is not None:
        clauses.append("a.capo_reparto_id = %s")
        params.append(int(legacy_user_id))
    has_capi_reparto = legacy_table_has_column("capi_reparto", "id")
    if has_capi_reparto:
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

    # Defense-in-depth: ogni frammento SQL iniettato deve essere nell'allowlist.
    # I valori passano sempre via bind %s; questa è una barriera contro regressioni
    # future che introducessero predicati dinamici non letterali.
    if not all(c in _CAR_PENDING_ALLOWED_CLAUSES for c in clauses):
        logger.error("_count_car_pending: clausola non autorizzata, abort")
        return 0
    join_sql = "LEFT JOIN capi_reparto cr ON cr.id = a.capo_reparto_id" if has_capi_reparto else ""
    if join_sql not in _CAR_PENDING_ALLOWED_JOINS:
        logger.error("_count_car_pending: join non autorizzato, abort")
        return 0

    sql = (
        "SELECT COUNT(*) FROM assenze a "
        + (join_sql + " " if join_sql else "")
        + "WHERE (" + " OR ".join(clauses) + ") "
        + "AND COALESCE(a.moderation_status, 2) = 2"
    )
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute(sql, params)
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


def _load_admin_subnav_items(request, legacy_user) -> list:
    """Carica le voci della subnav interna all'admin portale (section='admin_subnav')."""
    if not _navigation_registry_enabled():
        return []
    is_admin = bool(getattr(request.user, "is_superuser", False))
    if legacy_user:
        is_admin = bool(is_admin or is_legacy_admin(legacy_user))
    if not is_admin:
        return []
    try:
        current_view_name = getattr(request.resolver_match, "view_name", "") or ""
        return get_admin_subnav_nodes(current_view_name=current_view_name)
    except Exception:
        return []


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
    legacy_user_id_sub: int | None = None
    if legacy_user and getattr(legacy_user, "id", None):
        try:
            legacy_user_id_sub = int(legacy_user.id)
        except Exception:
            pass
    parent_code = _detect_subnav_parent_code(request)
    try:
        nodes = get_subnav_nodes(
            parent_code=parent_code,
            role_id=role_id,
            is_admin=is_admin,
            legacy_user_id=legacy_user_id_sub,
        )
    except Exception:
        return []
    if not nodes:
        return []
    current_variants = _path_variants(request.path)
    from urllib.parse import urlsplit as _urlsplit
    # Stato attivo: match ESATTO su path+query (le viste filtrate condividono lo
    # stesso path, es. ?stato=...); fallback al match per solo path se nessuna
    # voce combacia esattamente (retro-compatibile con le subnav esistenti).
    try:
        current_full = request.get_full_path()
    except Exception:
        current_full = request.path
    has_exact = any(node.href == current_full for node in nodes)
    result = []
    for node in nodes:
        if has_exact:
            active = (node.href == current_full)
        else:
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
            icon=node.icon,
            group=node.group,
            order_hint=node.order_hint,
        ))
    return result


def legacy_nav(request):
    result = {
        "nav_items": [],
        "topbar_groups": [],
        "legacy_user": None,
        "car_pending_count": 0,
        "notifiche_count": 0,
        "subnav_items": [],
        "admin_subnav_items": [],
        "command_palette_items": [],
        "topbar_color": "",
        "impersonation_active": False,
        "impersonator_display": "",
        "impersonated_display": "",
        "impersonation_stop_url": "",
        "ui_prefs": _get_ui_prefs(request),
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
            result["notifiche_popup"] = list(
                Notifica.objects.filter(
                    legacy_user_id=int(legacy_user_id),
                    letta=False,
                    popup_shown=False,
                ).order_by("-created_at")[:5]
            )
        except Exception:
            pass

    if _navigation_registry_enabled():
        try:
            registry_items = _load_registry_nav_items(request, legacy_user)
        except Exception:
            registry_items = []
        has_registry_items = bool(registry_items)
        if has_registry_items or not _navigation_legacy_fallback_enabled():
            if not has_registry_items:
                _log_nav_once(
                    level="warning",
                    cache_key=f"registry-empty-no-fallback:{_normalize_path(request.path)}",
                    message="Navigation Registry attivo ma vuoto e fallback legacy disabilitato.",
                    path=_normalize_path(request.path),
                    legacy_user_id=getattr(legacy_user, "id", None),
                    ruolo_id=getattr(legacy_user, "ruolo_id", None),
                )
            registry_items = _ensure_dashboard_nav(registry_items, current_variants)
            registry_items.sort(key=lambda x: ((x.order_hint if x.order_hint is not None else 999999), x.label.lower()))
            result["nav_items"] = registry_items
            result["topbar_groups"] = _group_nav_items(registry_items)
            result["topbar_color"] = next(
                (item.category_color for item in registry_items if item.active and item.category_color),
                "",
            )
            result["subnav_items"] = _load_subnav_items(request, legacy_user)
            result["admin_subnav_items"] = _load_admin_subnav_items(request, legacy_user)
            return result
        _log_nav_once(
            level="info",
            cache_key=f"registry-to-legacy:{_normalize_path(request.path)}:{getattr(legacy_user, 'ruolo_id', None)}",
            message="Navigation fallback attivo: nessuna voce registry, uso menu legacy.",
            path=_normalize_path(request.path),
            legacy_user_id=getattr(legacy_user, "id", None),
            ruolo_id=getattr(legacy_user, "ruolo_id", None),
        )

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
                    icon=(puls.get("icon") or ""),
                    order_hint=(ui_order_hint if ui_order_hint is not None else order_map.get(pulsante_id)),
                )
            )

        items.sort(key=lambda x: ((x.order_hint if x.order_hint is not None else 999999), x.label.lower()))
        items = _dedupe_legacy_nav_items(items)
        items = _ensure_dashboard_nav(items, current_variants)
        items.sort(key=lambda x: ((x.order_hint if x.order_hint is not None else 999999), x.label.lower()))
        result["nav_items"] = items
    except DatabaseError:
        pass

    result["admin_subnav_items"] = _load_admin_subnav_items(request, legacy_user)

    # Indice piatto per la command palette (Ctrl+K): label -> url, ACL-filtrato,
    # niente voci "in arrivo" (coming) o placeholder (#). Difensivo su NavItem/dict.
    palette: list[dict] = []
    seen_urls: set[str] = set()

    def _palette_add(it) -> None:
        is_dict = isinstance(it, dict)
        href = (it.get("href") if is_dict else getattr(it, "href", "")) or ""
        label = (it.get("label") if is_dict else getattr(it, "label", "")) or ""
        coming = (it.get("coming") if is_dict else getattr(it, "coming", False)) or False
        group = (
            (it.get("group") or it.get("category_label") if is_dict else "")
            or (getattr(it, "category_label", "") or getattr(it, "group", ""))
        )
        href = str(href).strip()
        label = str(label).strip()
        if not href or not label or coming or href in ("#",) or href in seen_urls:
            return
        seen_urls.add(href)
        palette.append({"l": label, "u": href, "g": str(group or "")})

    for _it in result.get("nav_items", []) or []:
        _palette_add(_it)
    for _key in ("subnav_items", "admin_subnav_items"):
        for _it in result.get(_key, []) or []:
            _palette_add(_it)
    result["command_palette_items"] = palette

    return result


def ui_prefs_context(request):
    """Espone le preferenze UI come variabili piatte nel contesto template.

    Riusa la cache di sessione di _get_ui_prefs: nessun hit DB aggiuntivo se
    legacy_nav è già stato eseguito nello stesso request. Funziona anche per
    utenti non autenticati (restituisce i valori di default).
    """
    prefs = _get_ui_prefs(request)
    return {
        "ui_font_scale": prefs["font_scale"],
        "ui_theme_mode": prefs.get("theme_mode", _UI_PREFS_DEFAULTS["theme_mode"]),
        "ui_sidebar_collapsed": prefs["sidebar_collapsed"],
        "ui_sidebar_footer_actions": prefs.get("sidebar_footer_actions", get_default_sidebar_footer_actions()),
    }


def dev_git_badge(_request):
    """Badge di sviluppo: quanto lavoro non e' committato, e quanto non e' in release.

    Attivo solo con DEBUG=True: in produzione ritorna sempre {} e non esegue git.
    """
    if not settings.DEBUG:
        return {}
    from core.build_info import get_dev_git_state

    state = get_dev_git_state()
    return {"dev_git": state} if state else {}


def app_meta(_request):
    current_release = get_current_release()
    return {
        "portal_branding": get_portal_branding(),
        "instance_name": str(getattr(settings, "INSTANCE_NAME", "") or "").strip(),
        "app_version": str(getattr(settings, "APP_VERSION", "") or "").strip(),
        "module_versions": get_module_versions(),
        "current_release": current_release,
        "release_notes_preview": list(current_release.get("items") or [])[:6],
        "recent_releases": get_changelog_entries(limit=3),
    }
