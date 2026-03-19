from __future__ import annotations

from dataclasses import dataclass

from core.models import SiteConfig


PORTAL_BRANDING_DEFAULTS: dict[str, str] = {
    "portal_name": "Portale Novicrom",
    "portal_subtitle": "",
    "brand_logo_full": "",
    "brand_logo_compact": "",
    "brand_favicon": "",
}


@dataclass(frozen=True)
class PortalBranding:
    portal_name: str
    portal_subtitle: str
    brand_logo_full: str
    brand_logo_compact: str
    brand_favicon: str
    monogram: str


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
    return PortalBranding(
        portal_name=portal_name,
        portal_subtitle=portal_subtitle,
        brand_logo_full=brand_logo_full,
        brand_logo_compact=brand_logo_compact,
        brand_favicon=brand_favicon,
        monogram=_build_monogram(portal_name),
    )
