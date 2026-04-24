from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.db import DatabaseError
from core.models import SiteConfig


PORTAL_BRANDING_DEFAULTS: dict[str, str] = {
    "portal_name": "Portale Novicrom",
    "portal_subtitle": "",
    "brand_logo_full": "",
    "brand_logo_compact": "",
    "brand_favicon": "",
    "brand_logo_full_height": "40",
    "brand_logo_full_max_width": "140",
    "brand_logo_compact_size": "32",
    "brand_sidebar_logo_scale": "100",
    "brand_logo_remove_white_bg": "0",
    "brand_landing_image": "",
    "brand_landing_fit_mode": "cover",
    "brand_login_form_x": "78",
    "brand_login_form_y": "50",
    "brand_primary_color": "#002b5c",
    "brand_accent_color": "#ff6b00",
    "brand_background_color": "#f2f5f8",
}

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_LANDING_FIT_MODES = {"cover", "contain", "stretch", "center"}


@dataclass(frozen=True)
class PortalBranding:
    portal_name: str
    portal_subtitle: str
    brand_logo_full: str
    brand_logo_compact: str
    brand_favicon: str
    brand_logo_full_height: int
    brand_logo_full_max_width: int
    brand_logo_compact_size: int
    brand_sidebar_logo_scale: int
    brand_logo_remove_white_bg: bool
    brand_landing_image: str
    brand_landing_fit_mode: str
    brand_login_form_x: int
    brand_login_form_y: int
    brand_primary_color: str
    brand_primary_mid_color: str
    brand_accent_color: str
    brand_accent_light_color: str
    brand_background_color: str
    monogram: str


def _normalize_hex_color(value: str, default: str) -> str:
    cleaned = str(value or "").strip()
    if _HEX_COLOR_RE.match(cleaned):
        return cleaned.lower()
    return default


def _mix_hex_color(color: str, target: str, weight: float) -> str:
    color = _normalize_hex_color(color, "#000000").lstrip("#")
    target = _normalize_hex_color(target, "#ffffff").lstrip("#")
    weight = max(0.0, min(1.0, weight))
    rgb = []
    for idx in range(0, 6, 2):
        base_value = int(color[idx : idx + 2], 16)
        target_value = int(target[idx : idx + 2], 16)
        mixed = round(base_value * (1 - weight) + target_value * weight)
        rgb.append(f"{mixed:02x}")
    return f"#{''.join(rgb)}"


def _normalize_int(value: str | int, default: int, *, min_value: int, max_value: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, parsed))


def _build_monogram(value: str) -> str:
    words = [chunk for chunk in str(value or "").replace("-", " ").split() if chunk]
    if not words:
        return "PN"
    if len(words) == 1:
        return words[0][:2].upper()
    return f"{words[0][:1]}{words[1][:1]}".upper()


def _normalize_landing_fit_mode(value: str, default: str) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in _LANDING_FIT_MODES:
        return cleaned
    return default


def _normalize_bool(value: str | int | bool, default: bool = False) -> bool:
    cleaned = str(value).strip().lower()
    if cleaned in {"1", "true", "yes", "on"}:
        return True
    if cleaned in {"0", "false", "no", "off"}:
        return False
    return default


def _append_asset_cache_bust(url: str, version_token: str) -> str:
    cleaned = str(url or "").strip()
    token = str(version_token or "").strip()
    if not cleaned or not token:
        return cleaned
    parsed = urlsplit(cleaned)
    is_local_media = cleaned.startswith("/media/") or parsed.path.startswith("/media/")
    if not is_local_media:
        return cleaned
    separator = "&" if "?" in cleaned else "?"
    return f"{cleaned}{separator}v={token}"


def get_portal_branding() -> PortalBranding:
    values = dict(PORTAL_BRANDING_DEFAULTS)
    asset_versions: dict[str, str] = {}
    try:
        rows = list(
            SiteConfig.objects.filter(chiave__in=list(values.keys())).values_list("chiave", "valore", "updated_at")
        )
    except DatabaseError:
        rows = []
    for chiave, valore, updated_at in rows:
        values[chiave] = valore
        if updated_at is not None:
            asset_versions[chiave] = str(int(updated_at.timestamp()))
    portal_name = str(values.get("portal_name") or "").strip()
    portal_subtitle = str(values.get("portal_subtitle") or "").strip()
    brand_logo_full = _append_asset_cache_bust(
        str(values.get("brand_logo_full") or "").strip(),
        asset_versions.get("brand_logo_full", ""),
    )
    brand_logo_compact = _append_asset_cache_bust(
        str(values.get("brand_logo_compact") or "").strip(),
        asset_versions.get("brand_logo_compact", ""),
    )
    brand_favicon = _append_asset_cache_bust(
        str(values.get("brand_favicon") or "").strip(),
        asset_versions.get("brand_favicon", ""),
    )
    brand_logo_full_height = _normalize_int(
        values.get("brand_logo_full_height", PORTAL_BRANDING_DEFAULTS["brand_logo_full_height"]),
        40,
        min_value=28,
        max_value=96,
    )
    brand_logo_full_max_width = _normalize_int(
        values.get("brand_logo_full_max_width", PORTAL_BRANDING_DEFAULTS["brand_logo_full_max_width"]),
        140,
        min_value=80,
        max_value=360,
    )
    brand_logo_compact_size = _normalize_int(
        values.get("brand_logo_compact_size", PORTAL_BRANDING_DEFAULTS["brand_logo_compact_size"]),
        32,
        min_value=24,
        max_value=80,
    )
    brand_sidebar_logo_scale = _normalize_int(
        values.get("brand_sidebar_logo_scale", PORTAL_BRANDING_DEFAULTS["brand_sidebar_logo_scale"]),
        100,
        min_value=60,
        max_value=260,
    )
    brand_logo_remove_white_bg = _normalize_bool(
        values.get("brand_logo_remove_white_bg", PORTAL_BRANDING_DEFAULTS["brand_logo_remove_white_bg"]),
        False,
    )
    brand_landing_image = _append_asset_cache_bust(
        str(values.get("brand_landing_image") or "").strip(),
        asset_versions.get("brand_landing_image", ""),
    )
    brand_landing_fit_mode = _normalize_landing_fit_mode(
        str(values.get("brand_landing_fit_mode") or ""),
        PORTAL_BRANDING_DEFAULTS["brand_landing_fit_mode"],
    )
    brand_login_form_x = _normalize_int(
        values.get("brand_login_form_x", PORTAL_BRANDING_DEFAULTS["brand_login_form_x"]),
        78,
        min_value=0,
        max_value=100,
    )
    brand_login_form_y = _normalize_int(
        values.get("brand_login_form_y", PORTAL_BRANDING_DEFAULTS["brand_login_form_y"]),
        50,
        min_value=0,
        max_value=100,
    )
    brand_primary_color = _normalize_hex_color(
        str(values.get("brand_primary_color") or ""),
        PORTAL_BRANDING_DEFAULTS["brand_primary_color"],
    )
    brand_accent_color = _normalize_hex_color(
        str(values.get("brand_accent_color") or ""),
        PORTAL_BRANDING_DEFAULTS["brand_accent_color"],
    )
    brand_background_color = _normalize_hex_color(
        str(values.get("brand_background_color") or ""),
        PORTAL_BRANDING_DEFAULTS["brand_background_color"],
    )
    return PortalBranding(
        portal_name=portal_name,
        portal_subtitle=portal_subtitle,
        brand_logo_full=brand_logo_full,
        brand_logo_compact=brand_logo_compact,
        brand_favicon=brand_favicon,
        brand_logo_full_height=brand_logo_full_height,
        brand_logo_full_max_width=brand_logo_full_max_width,
        brand_logo_compact_size=brand_logo_compact_size,
        brand_sidebar_logo_scale=brand_sidebar_logo_scale,
        brand_logo_remove_white_bg=brand_logo_remove_white_bg,
        brand_landing_image=brand_landing_image,
        brand_landing_fit_mode=brand_landing_fit_mode,
        brand_login_form_x=brand_login_form_x,
        brand_login_form_y=brand_login_form_y,
        brand_primary_color=brand_primary_color,
        brand_primary_mid_color=_mix_hex_color(brand_primary_color, "#ffffff", 0.14),
        brand_accent_color=brand_accent_color,
        brand_accent_light_color=_mix_hex_color(brand_accent_color, "#ffffff", 0.9),
        brand_background_color=brand_background_color,
        monogram=_build_monogram(portal_name),
    )
