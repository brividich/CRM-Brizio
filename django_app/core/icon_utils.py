from __future__ import annotations

import re
import unicodedata

from django.conf import settings
from django.templatetags.static import static
from django.utils.html import format_html
from django.utils.safestring import mark_safe


_IMAGE_ICON_EXTENSIONS = (".ico", ".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif")

_SEMANTIC_ICON_SVGS = {
    "home": """
        <path d="M4 11.5 12 5l8 6.5"/>
        <path d="M6 10.5V19h12v-8.5"/>
        <path d="M10 19v-4.5h4V19"/>
    """,
    "layout-dashboard": """
        <rect x="3" y="3" width="7" height="7" rx="1.5"/>
        <rect x="14" y="3" width="7" height="5" rx="1.5"/>
        <rect x="14" y="12" width="7" height="9" rx="1.5"/>
        <rect x="3" y="14" width="7" height="7" rx="1.5"/>
    """,
    "calendar": """
        <rect x="3" y="5" width="18" height="16" rx="2"/>
        <path d="M8 3v4M16 3v4M3 10h18"/>
    """,
    "calendar-x": """
        <rect x="3" y="5" width="18" height="16" rx="2"/>
        <path d="M8 3v4M16 3v4M3 10h18"/>
        <path d="m10 13 4 4m0-4-4 4"/>
    """,
    "user": """
        <circle cx="12" cy="8" r="4"/>
        <path d="M5 20a7 7 0 0 1 14 0"/>
    """,
    "users": """
        <circle cx="9" cy="8" r="4"/>
        <path d="M3.5 20a6.5 6.5 0 0 1 11 0"/>
        <path d="M16.5 4.5a4 4 0 0 1 0 7"/>
        <path d="M18.5 20a5 5 0 0 0-3.5-4.8"/>
    """,
    "shield": """
        <path d="M12 3 19 6v6c0 5-3.2 8.2-7 9-3.8-.8-7-4-7-9V6z"/>
    """,
    "shield-check": """
        <path d="M12 3 19 6v6c0 5-3.2 8.2-7 9-3.8-.8-7-4-7-9V6z"/>
        <path d="m9 12.5 2 2 4-4"/>
    """,
    "lock": """
        <rect x="5" y="11" width="14" height="10" rx="2"/>
        <path d="M8 11V8a4 4 0 0 1 8 0v3"/>
    """,
    "settings": """
        <circle cx="12" cy="12" r="3"/>
        <path d="M12 2v3M12 19v3M4.93 4.93l2.12 2.12M16.95 16.95l2.12 2.12M2 12h3M19 12h3M4.93 19.07l2.12-2.12M16.95 7.05l2.12-2.12"/>
    """,
    "list": """
        <path d="M8 6h12M8 12h12M8 18h12"/>
        <path d="M4 6h.01M4 12h.01M4 18h.01"/>
    """,
    "list-todo": """
        <path d="M9 6h11M9 12h11M9 18h11"/>
        <path d="m4 6 1.2 1.2L7.8 4.6M4 12l1.2 1.2L7.8 10.6M4 18l1.2 1.2 2.6-2.6"/>
    """,
    "triangle-alert": """
        <path d="M12 4 21 20H3z"/>
        <path d="M12 10v4"/>
        <path d="M12 17h.01"/>
    """,
    "octagon-alert": """
        <path d="M8 3h8l5 5v8l-5 5H8l-5-5V8z"/>
        <path d="M12 8v5"/>
        <path d="M12 16h.01"/>
    """,
    "package": """
        <path d="m12 3 8 4-8 4-8-4 8-4z"/>
        <path d="M4 7v10l8 4 8-4V7"/>
        <path d="M12 11v10"/>
    """,
    "check-circle": """
        <circle cx="12" cy="12" r="9"/>
        <path d="m8.5 12.5 2.3 2.3 4.7-4.8"/>
    """,
    "workflow": """
        <rect x="3" y="4" width="6" height="6" rx="1.5"/>
        <rect x="15" y="4" width="6" height="6" rx="1.5"/>
        <rect x="15" y="14" width="6" height="6" rx="1.5"/>
        <path d="M9 7h4a2 2 0 0 1 2 2v5"/>
    """,
    "ticket": """
        <path d="M4 9a2 2 0 1 0 0 4v5h16v-5a2 2 0 1 0 0-4V6H4z"/>
        <path d="M12 6v12"/>
    """,
    "recycle": """
        <path d="M7 7H3V3"/>
        <path d="M17 17h4v4"/>
        <path d="M20 7a8 8 0 0 0-13.7-4.7L3 5"/>
        <path d="M4 17a8 8 0 0 0 13.7 4.7L21 19"/>
    """,
    "book-open": """
        <path d="M4 6.5C4 5.1 5.1 4 6.5 4H12v15H6.5A2.5 2.5 0 0 0 4 21.5z"/>
        <path d="M20 6.5C20 5.1 18.9 4 17.5 4H12v15h5.5a2.5 2.5 0 0 1 2.5 2.5z"/>
    """,
    "clipboard-list": """
        <rect x="6" y="4" width="12" height="17" rx="2"/>
        <path d="M9 4.5h6a1 1 0 0 1 1 1V7H8V5.5a1 1 0 0 1 1-1z"/>
        <path d="M10 12h5M10 16h5"/>
        <path d="M8 12h.01M8 16h.01"/>
    """,
    "newspaper": """
        <rect x="4" y="5" width="16" height="14" rx="2"/>
        <rect x="6.5" y="8.5" width="3" height="3" rx=".5"/>
        <path d="M11 9h6M11 13h6M6.5 17H14"/>
    """,
    "scan": """
        <path d="M4 7V5a1 1 0 0 1 1-1h2M20 7V5a1 1 0 0 0-1-1h-2M4 17v2a1 1 0 0 0 1 1h2M20 17v2a1 1 0 0 1-1 1h-2"/>
        <path d="M7 12h10M8 9h8M8 15h8"/>
    """,
    "id-card": """
        <rect x="3" y="5" width="18" height="14" rx="2"/>
        <circle cx="9" cy="11.5" r="2"/>
        <path d="M6.5 16a3 3 0 0 1 5 0M14 10h4M14 14h4"/>
    """,
    "file-text": """
        <path d="M14 3H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V9z"/>
        <path d="M14 3v6h6M9 13h6M9 17h6"/>
    """,
    "file-check": """
        <path d="M14 3H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V9z"/>
        <path d="M14 3v6h6"/>
        <path d="m9 16 2 2 4-4"/>
    """,
    "briefcase": """
        <rect x="3" y="7" width="18" height="12" rx="2"/>
        <path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M3 12h18"/>
    """,
    "clock": """
        <circle cx="12" cy="12" r="8"/>
        <path d="M12 8v5l3 2"/>
    """,
    "wrench": """
        <path d="M21 7.5a4.5 4.5 0 0 1-6.1 4.2L8 18.5 5.5 16l6.8-6.9A4.5 4.5 0 0 1 16.5 3L14 5.5 18.5 10z"/>
    """,
    "siren": """
        <path d="M8 15v-2a4 4 0 0 1 8 0v2"/>
        <path d="M7 15h10v4H7z"/>
        <path d="M12 3v3M5 7l2 1.5M19 7l-2 1.5"/>
    """,
    "key-round": """
        <circle cx="8.5" cy="12" r="3.5"/>
        <path d="M12 12h8M17 12v3M19 12v2"/>
    """,
    "map": """
        <path d="m4 6 5-2 6 2 5-2v14l-5 2-6-2-5 2z"/>
        <path d="M9 4v16M15 6v16"/>
    """,
}

_SEMANTIC_ICON_ALIASES = {
    "acl": "shield",
    "alert": "triangle-alert",
    "alert-triangle": "triangle-alert",
    "book": "book-open",
    "box": "package",
    "check": "check-circle",
    "dashboard": "layout-dashboard",
    "file-check": "file-check",
    "file-text": "file-text",
    "flow": "workflow",
    "home": "home",
    "layout-dashboard": "layout-dashboard",
    "list": "list",
    "list-todo": "list-todo",
    "map": "map",
    "newspaper": "newspaper",
    "octagon-alert": "octagon-alert",
    "package": "package",
    "recycle": "recycle",
    "scan": "scan",
    "settings": "settings",
    "shield": "shield",
    "shield-check": "shield-check",
    "ticket": "ticket",
    "triangle-alert": "triangle-alert",
    "user": "user",
    "users": "users",
    "users-round": "users",
    "workflow": "workflow",
    "id-card": "id-card",
    "briefcase": "briefcase",
    "clock": "clock",
    "clipboard-list": "clipboard-list",
    "file-check-circle": "file-check",
    "key-round": "key-round",
    "lock": "lock",
    "news": "newspaper",
    "notebook": "clipboard-list",
    "siren": "siren",
    "wrench": "wrench",
}

_LABEL_ICON_ALIASES = {
    "accessi-azienda": "key-round",
    "anagrafica": "id-card",
    "anomalie": "octagon-alert",
    "assets": "package",
    "assenze": "calendar-x",
    "dashboard": "layout-dashboard",
    "diario-preposto": "clipboard-list",
    "dipendenti": "id-card",
    "dpi": "shield-check",
    "fornitori": "briefcase",
    "gestione-anomalie": "octagon-alert",
    "hr": "users",
    "manutenzione": "wrench",
    "notizie": "newspaper",
    "presa-visione": "file-check",
    "procedure": "file-check",
    "procedure-refresh": "file-check",
    "rentri": "recycle",
    "rientri": "recycle",
    "rilevazione-incidenti": "triangle-alert",
    "segnalazioni-sicurezza": "siren",
    "sicurezza": "shield-check",
    "task": "list-todo",
    "tasks": "list-todo",
    "ticket": "ticket",
    "tickets": "ticket",
    "timbri": "scan",
    "timbrature": "scan",
}


def _strip_query_and_fragment(value: str) -> str:
    base = str(value or "").strip()
    if not base:
        return ""
    return base.split("#", 1)[0].split("?", 1)[0]


def _normalize_icon_token(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def _looks_like_placeholder_text(value) -> bool:
    token = _normalize_icon_token(value)
    if not token:
        return True
    if token in _SEMANTIC_ICON_SVGS or token in _SEMANTIC_ICON_ALIASES:
        return False
    return len(token) <= 3


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


def resolve_semantic_icon_name(value, fallback: str = "") -> str:
    token = _normalize_icon_token(value)
    if token in _SEMANTIC_ICON_SVGS:
        return token
    if token in _SEMANTIC_ICON_ALIASES:
        return _SEMANTIC_ICON_ALIASES[token]

    if not _looks_like_placeholder_text(value):
        return ""

    fallback_token = _normalize_icon_token(fallback)
    if fallback_token in _LABEL_ICON_ALIASES:
        return _LABEL_ICON_ALIASES[fallback_token]
    if fallback_token in _SEMANTIC_ICON_ALIASES:
        return _SEMANTIC_ICON_ALIASES[fallback_token]
    if fallback_token in _SEMANTIC_ICON_SVGS:
        return fallback_token
    return ""


def render_semantic_icon(icon_name: str, svg_class: str = "ui-icon-svg"):
    body = _SEMANTIC_ICON_SVGS.get(str(icon_name or "").strip())
    if not body:
        return ""
    return format_html(
        '<svg viewBox="0 0 24 24" class="{}" aria-hidden="true" focusable="false" fill="none" '
        'stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">{}</svg>',
        svg_class,
        mark_safe(body),
    )


def icon_text_or_fallback(value, fallback: str = "") -> str:
    text = str(value or "").strip()
    if text:
        return text
    fallback_text = str(fallback or "").strip()
    return fallback_text[:1].upper() if fallback_text else ""
