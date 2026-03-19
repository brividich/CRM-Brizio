from __future__ import annotations

from django.conf import settings
from django.templatetags.static import static


_IMAGE_ICON_EXTENSIONS = (".ico", ".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif")


def _strip_query_and_fragment(value: str) -> str:
    base = str(value or "").strip()
    if not base:
        return ""
    return base.split("#", 1)[0].split("?", 1)[0]


def icon_looks_like_image(value) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False

    lower = raw.lower()
    if lower.startswith(("data:image/", "http://", "https://", "static:", "media:")):
        return True

    normalized = _strip_query_and_fragment(raw).lower()
    return any(normalized.endswith(ext) for ext in _IMAGE_ICON_EXTENSIONS)


def resolve_icon_src(value) -> str:
    raw = str(value or "").strip()
    if not raw or not icon_looks_like_image(raw):
        return ""

    lower = raw.lower()
    if lower.startswith("static:"):
        return static(raw.split(":", 1)[1].lstrip("/"))
    if lower.startswith("media:"):
        media_url = str(getattr(settings, "MEDIA_URL", "/media/") or "/media/")
        if not media_url.endswith("/"):
            media_url += "/"
        return media_url + raw.split(":", 1)[1].lstrip("/")
    return raw


def icon_text_or_fallback(value, fallback: str = "") -> str:
    text = str(value or "").strip()
    if text:
        return text
    fallback_text = str(fallback or "").strip()
    return fallback_text[:1].upper() if fallback_text else ""
