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


MODULE_DEFINITIONS: dict[str, ModuleDefinition] = {
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
}


def get_registered_modules() -> dict[str, ModuleDefinition]:
    return dict(MODULE_DEFINITIONS)


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

        site_display = str(site_values.get(config_keys.get("display_label", ""), "") or "").strip()
        site_short = str(site_values.get(config_keys.get("short_label", ""), "") or "").strip()
        site_menu = str(site_values.get(config_keys.get("menu_label", ""), "") or "").strip()
        site_dashboard = str(site_values.get(config_keys.get("dashboard_label", ""), "") or "").strip()

        if site_display:
            display_label = site_display
        if site_short:
            short_label = site_short
        if site_menu:
            menu_label = site_menu
        if site_dashboard:
            dashboard_label = site_dashboard

        brandings[module_key] = ModuleBranding(
            key=module_key,
            default_label=definition.default_label,
            display_label=display_label or definition.default_label,
            short_label=short_label or default_short,
            menu_label=menu_label or display_label or default_menu,
            dashboard_label=dashboard_label or display_label or default_dashboard,
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
