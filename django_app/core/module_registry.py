from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from core.models import SiteConfig


MODULE_BRANDING_PREFIX = "module_branding."
MODULE_BRANDING_FIELDS = (
    "display_label",
    "menu_label",
    "short_label",
    "dashboard_label",
    "logo_url",
)


@dataclass(frozen=True)
class ModuleDefinition:
    key: str
    default_label: str
    icon: str = ""
    order: int = 100
    route_name: str = ""
    route_namespace: str = ""
    permission_namespace: str = ""
    navigation_codes: tuple[str, ...] = ()
    dashboard_widget_ids: tuple[str, ...] = ()
    feature_flags: tuple[str, ...] = ()
    enabled_by_default: bool = True
    # audience: chi può vedere/usare questo modulo
    #   "user"   — utenti normali (default)
    #   "admin"  — solo is_legacy_admin() (admin_portale, hub_tools)
    #   "system" — infrastruttura non in navigazione (monitoring, setup_wizard)
    audience: str = "user"
    default_short_label: str = ""
    default_menu_label: str = ""
    default_dashboard_label: str = ""


@dataclass(frozen=True)
class ModuleBranding:
    key: str
    default_label: str
    display_label: str
    short_label: str
    menu_label: str
    dashboard_label: str
    logo_url: str = ""


MODULE_DEFINITIONS: dict[str, ModuleDefinition] = {
    # -------------------------------------------------------------------------
    # Core navigation modules — ordine rispecchia la topbar di default
    # navigation_codes deve combaciare con NavigationItem.code in DB
    # -------------------------------------------------------------------------
    "dashboard": ModuleDefinition(
        key="dashboard",
        default_label="Dashboard",
        icon="layout-dashboard",
        order=10,
        route_name="dashboard_home",
        route_namespace="",
        permission_namespace="dashboard",
        navigation_codes=("dashboard",),
        default_short_label="Home",
        default_menu_label="Dashboard",
        default_dashboard_label="Dashboard",
    ),
    "assenze": ModuleDefinition(
        key="assenze",
        default_label="Assenze",
        icon="calendar-off",
        order=20,
        route_name="assenze_menu",
        route_namespace="",
        permission_namespace="assenze",
        navigation_codes=("assenze",),
        default_short_label="Assenze",
        default_menu_label="Assenze",
        default_dashboard_label="Assenze",
    ),
    "anomalie": ModuleDefinition(
        key="anomalie",
        default_label="Anomalie",
        icon="alert-triangle",
        order=25,
        route_name="gestione_anomalie_page",
        route_namespace="",
        permission_namespace="anomalie",
        navigation_codes=("anomalie",),
        default_short_label="Anomalie",
        default_menu_label="Anomalie",
        default_dashboard_label="Anomalie",
    ),
    "assets": ModuleDefinition(
        key="assets",
        default_label="Assets",
        icon="box",
        order=35,
        route_name="assets:asset_list",
        route_namespace="assets",
        permission_namespace="assets",
        navigation_codes=("assets",),
        default_short_label="Assets",
        default_menu_label="Assets",
        default_dashboard_label="Assets",
    ),
    "tasks": ModuleDefinition(
        key="tasks",
        default_label="Task",
        icon="checklist",
        order=40,
        route_name="tasks:list",
        route_namespace="tasks",
        permission_namespace="tasks",
        navigation_codes=("tasks",),
        default_short_label="Task",
        default_menu_label="Task",
        default_dashboard_label="Task",
    ),
    "tickets": ModuleDefinition(
        key="tickets",
        default_label="Ticket",
        icon="ticket",
        order=45,
        route_name="tickets:dashboard",
        route_namespace="tickets",
        permission_namespace="tickets",
        navigation_codes=("tickets",),
        default_short_label="Ticket",
        default_menu_label="Ticket",
        default_dashboard_label="Ticket",
    ),
    "notizie": ModuleDefinition(
        key="notizie",
        default_label="Notizie",
        icon="news",
        order=50,
        route_name="notizie_lista",
        route_namespace="",
        permission_namespace="notizie",
        navigation_codes=("notizie",),
        default_short_label="Notizie",
        default_menu_label="Notizie",
        default_dashboard_label="Notizie",
    ),
    "anagrafica": ModuleDefinition(
        key="anagrafica",
        default_label="Anagrafica",
        icon="users",
        order=55,
        route_name="anagrafica:index",
        route_namespace="anagrafica",
        permission_namespace="anagrafica",
        navigation_codes=("anagrafica",),
        default_short_label="Anagrafica",
        default_menu_label="Anagrafica",
        default_dashboard_label="Anagrafica",
    ),
    "timbri": ModuleDefinition(
        key="timbri",
        default_label="Timbri",
        icon="clock",
        order=60,
        route_name="timbri:index",
        route_namespace="timbri",
        permission_namespace="timbri",
        navigation_codes=("timbri",),
        default_short_label="Timbri",
        default_menu_label="Registro Timbri",
        default_dashboard_label="Timbri",
    ),
    "planimetria": ModuleDefinition(
        key="planimetria",
        default_label="Planimetria",
        icon="map",
        order=65,
        route_name="planimetria:mappa",
        route_namespace="planimetria",
        permission_namespace="planimetria",
        navigation_codes=("planimetria",),
        default_short_label="Planimetria",
        default_menu_label="Planimetria Aziendale",
        default_dashboard_label="Planimetria",
    ),
    "automazioni": ModuleDefinition(
        key="automazioni",
        default_label="Automazioni",
        icon="settings-automation",
        order=70,
        route_name="automazioni:automazioni_rule_list",
        route_namespace="automazioni",
        permission_namespace="automazioni",
        navigation_codes=("automazioni",),
        audience="admin",
        enabled_by_default=False,
        default_short_label="Automazioni",
        default_menu_label="Automazioni",
        default_dashboard_label="Automazioni",
    ),
    "rentri": ModuleDefinition(
        key="rentri",
        default_label="RENTRI",
        icon="recycle",
        order=75,
        route_name="rentri_menu",
        route_namespace="",
        permission_namespace="rentri",
        navigation_codes=("rentri",),
        default_short_label="RENTRI",
        default_menu_label="RENTRI",
        default_dashboard_label="RENTRI",
    ),
    # -------------------------------------------------------------------------
    # Moduli sicurezza — TODO: verificare navigation_codes reali su DB prod
    # -------------------------------------------------------------------------
    "diario_preposto": ModuleDefinition(
        key="diario_preposto",
        default_label="Diario Preposto",
        icon="clipboard-check",
        order=80,
        route_name="diario_preposto:lista",
        route_namespace="diario_preposto",
        permission_namespace="diario_preposto",
        navigation_codes=("diario_preposto",),
        default_short_label="Diario",
        default_menu_label="Diario Preposto",
        default_dashboard_label="Diario Preposto",
    ),
    "rilevazione_incidenti": ModuleDefinition(
        key="rilevazione_incidenti",
        default_label="Rilevazione Incidenti",
        icon="shield-exclamation",
        order=85,
        route_name="rilevazione_incidenti:lista",
        route_namespace="rilevazione_incidenti",
        permission_namespace="rilevazione_incidenti",
        navigation_codes=("rilevazione_incidenti",),
        default_short_label="Incidenti",
        default_menu_label="Rilevazione Incidenti",
        default_dashboard_label="Incidenti",
    ),
    "procedure_refresh": ModuleDefinition(
        key="procedure_refresh",
        default_label="Procedure Refresh",
        icon="file-check",
        order=90,
        route_name="procedure_refresh:my_assignments",
        route_namespace="procedure_refresh",
        permission_namespace="procedure_refresh",
        navigation_codes=("procedure_refresh",),
        default_short_label="Procedure",
        default_menu_label="Procedure",
        default_dashboard_label="Procedure",
    ),
    # -------------------------------------------------------------------------
    # Moduli admin — richiede is_legacy_admin(), non visibili agli utenti normali
    # -------------------------------------------------------------------------
    "admin_portale": ModuleDefinition(
        key="admin_portale",
        default_label="Admin Portale",
        icon="shield-cog",
        order=200,
        route_name="admin_portale:index",
        route_namespace="admin_portale",
        permission_namespace="admin_portale",
        navigation_codes=("admin_portale",),
        audience="admin",
        enabled_by_default=False,
        default_short_label="Admin",
        default_menu_label="Admin Portale",
        default_dashboard_label="Admin",
    ),
    "hub_tools": ModuleDefinition(
        key="hub_tools",
        default_label="BrizioHUB",
        icon="tool",
        order=210,
        route_name="hub_tools:hub_moduli",
        route_namespace="hub_tools",
        permission_namespace="hub_tools",
        navigation_codes=("hub_tools",),
        audience="admin",
        enabled_by_default=False,
        default_short_label="HUB",
        default_menu_label="BrizioHUB",
        default_dashboard_label="HUB",
    ),
    # -------------------------------------------------------------------------
    # Moduli di sistema — infrastruttura, non in navigazione utente/admin
    # -------------------------------------------------------------------------
    "monitoring": ModuleDefinition(
        key="monitoring",
        default_label="Monitoring",
        icon="activity",
        order=300,
        route_name="monitoring:report_problem",
        route_namespace="monitoring",
        permission_namespace="monitoring",
        navigation_codes=("monitoring",),
        audience="system",
        enabled_by_default=False,
        default_short_label="Monitor",
        default_menu_label="Monitoring",
        default_dashboard_label="Monitoring",
    ),
}


def get_registered_modules() -> dict[str, ModuleDefinition]:
    return dict(MODULE_DEFINITIONS)


def get_modules_by_audience(audience: str) -> dict[str, ModuleDefinition]:
    """Restituisce i moduli filtrati per audience ("user", "admin", "system")."""
    return {k: v for k, v in MODULE_DEFINITIONS.items() if v.audience == audience}


def get_module_definition(module_key: str) -> ModuleDefinition | None:
    return MODULE_DEFINITIONS.get(str(module_key or "").strip().lower())


def _branding_siteconfig_key(module_key: str, field_name: str) -> str:
    return f"{MODULE_BRANDING_PREFIX}{module_key}.{field_name}"


def module_branding_siteconfig_keys(module_key: str) -> dict[str, str]:
    key = str(module_key or "").strip().lower()
    if not key:
        return {}
    return {field_name: _branding_siteconfig_key(key, field_name) for field_name in MODULE_BRANDING_FIELDS}


def is_module_branding_siteconfig_key(config_key: str) -> bool:
    raw = str(config_key or "").strip()
    if not raw.startswith(MODULE_BRANDING_PREFIX):
        return False
    remainder = raw[len(MODULE_BRANDING_PREFIX):]
    module_key, separator, field_name = remainder.partition(".")
    return bool(module_key and separator and field_name in MODULE_BRANDING_FIELDS)


def get_module_brandings() -> dict[str, ModuleBranding]:
    # Precedenza branding:
    # 1. SiteConfig: module_branding.<module_key>.<field>
    # 2. settings.MODULE_BRANDING
    # 3. default dichiarati nel registry modulo
    settings_overrides = getattr(settings, "MODULE_BRANDING", {}) or {}
    site_defaults: dict[str, str] = {}

    for module_key in MODULE_DEFINITIONS:
        for field_name, config_key in module_branding_siteconfig_keys(module_key).items():
            _ = field_name
            site_defaults[config_key] = ""

    site_values = SiteConfig.get_many(site_defaults) if site_defaults else {}
    brandings: dict[str, ModuleBranding] = {}

    for module_key, definition in MODULE_DEFINITIONS.items():
        override = settings_overrides.get(module_key, {}) or {}
        config_keys = module_branding_siteconfig_keys(module_key)

        default_short = definition.default_short_label or definition.default_label
        default_menu = definition.default_menu_label or definition.default_label
        default_dashboard = definition.default_dashboard_label or definition.default_label

        display_label = str(override.get("display_label") or "").strip() or definition.default_label
        short_label = str(override.get("short_label") or "").strip() or default_short
        menu_label = str(override.get("menu_label") or "").strip() or display_label or default_menu
        dashboard_label = str(override.get("dashboard_label") or "").strip() or display_label or default_dashboard
        logo_url = str(override.get("logo_url") or "").strip()

        site_display = str(site_values.get(config_keys.get("display_label", ""), "") or "").strip()
        site_short = str(site_values.get(config_keys.get("short_label", ""), "") or "").strip()
        site_menu = str(site_values.get(config_keys.get("menu_label", ""), "") or "").strip()
        site_dashboard = str(site_values.get(config_keys.get("dashboard_label", ""), "") or "").strip()
        site_logo = str(site_values.get(config_keys.get("logo_url", ""), "") or "").strip()

        if site_display:
            display_label = site_display
        if site_short:
            short_label = site_short
        if site_menu:
            menu_label = site_menu
        if site_dashboard:
            dashboard_label = site_dashboard
        if site_logo:
            logo_url = site_logo

        brandings[module_key] = ModuleBranding(
            key=module_key,
            default_label=definition.default_label,
            display_label=display_label or definition.default_label,
            short_label=short_label or default_short,
            menu_label=menu_label or display_label or default_menu,
            dashboard_label=dashboard_label or display_label or default_dashboard,
            logo_url=logo_url,
        )

    return brandings


def get_module_branding(module_key: str) -> ModuleBranding | None:
    key = str(module_key or "").strip().lower()
    if not key:
        return None
    return get_module_brandings().get(key)


def resolve_module_label(module_key: str, *, fallback: str, surface: str = "display") -> str:
    branding = get_module_branding(module_key)
    if branding is None:
        return fallback

    field_name = {
        "display": "display_label",
        "short": "short_label",
        "menu": "menu_label",
        "dashboard": "dashboard_label",
    }.get(surface, "display_label")
    value = str(getattr(branding, field_name, "") or "").strip()
    return value or fallback


def navigation_code_label_map(*, surface: str = "menu") -> dict[str, str]:
    brandings = get_module_brandings()
    result: dict[str, str] = {}

    for module_key, definition in MODULE_DEFINITIONS.items():
        branding = brandings.get(module_key)
        if branding is None:
            continue
        label = resolve_module_label(module_key, fallback=definition.default_label, surface=surface)
        for code in definition.navigation_codes:
            normalized_code = str(code or "").strip().lower()
            if normalized_code:
                result[normalized_code] = label

    return result
