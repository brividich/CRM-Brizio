from __future__ import annotations

import re
from dataclasses import dataclass

from core.models import SiteConfig


PORTAL_BRANDING_DEFAULTS: dict[str, str] = {
    "portal_name": "Portale Novicrom",
    "portal_subtitle": "",
    "brand_logo_full": "",
    "brand_logo_compact": "",
    "brand_favicon": "",
    "brand_primary_color": "#1e3a5f",
    "brand_accent_color": "#f97316",
    "brand_background_color": "#eef0f5",
}

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class PortalBranding:
    portal_name: str
    portal_subtitle: str
    brand_logo_full: str
    brand_logo_compact: str
    brand_favicon: str
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


def _build_monogram(value: str) -> str:
    words = [chunk for chunk in str(value or "").replace("-", " ").split() if chunk]
    if not words:
        return "PN"
    if len(words) == 1:
        return words[0][:2].upper()
    return f"{words[0][:1]}{words[1][:1]}".upper()


def get_portal_branding() -> PortalBranding:
    values = SiteConfig.get_many(PORTAL_BRANDING_DEFAULTS)
    portal_name = str(values.get("portal_name") or "").strip() or PORTAL_BRANDING_DEFAULTS["portal_name"]
    portal_subtitle = str(values.get("portal_subtitle") or "").strip()
    brand_logo_full = str(values.get("brand_logo_full") or "").strip()
    brand_logo_compact = str(values.get("brand_logo_compact") or "").strip()
    brand_favicon = str(values.get("brand_favicon") or "").strip()
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
        brand_primary_color=brand_primary_color,
        brand_primary_mid_color=_mix_hex_color(brand_primary_color, "#ffffff", 0.14),
        brand_accent_color=brand_accent_color,
        brand_accent_light_color=_mix_hex_color(brand_accent_color, "#ffffff", 0.9),
        brand_background_color=brand_background_color,
        monogram=_build_monogram(portal_name),
    )
