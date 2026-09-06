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
    "bell": """
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
        <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
    """,
    "bell-off": """
        <path d="M8.7 3A6 6 0 0 1 18 8a21.3 21.3 0 0 1 .6 5"/>
        <path d="M17 17H3s3-2 3-9a4.67 4.67 0 0 1 .3-1.7"/>
        <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
        <line x1="2" y1="2" x2="22" y2="22"/>
    """,
    "zap": """
        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
    """,
    "trash": """
        <polyline points="3 6 5 6 21 6"/>
        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
    """,
    "trash-2": """
        <polyline points="3 6 5 6 21 6"/>
        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
        <line x1="10" y1="11" x2="10" y2="17"/>
        <line x1="14" y1="11" x2="14" y2="17"/>
    """,
    "tool": """
        <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
    """,
    "layers": """
        <polygon points="12 2 2 7 12 12 22 7 12 2"/>
        <polyline points="2 17 12 22 22 17"/>
        <polyline points="2 12 12 17 22 12"/>
    """,
    "activity": """
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
    """,
    "pin": """
        <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>
        <circle cx="12" cy="10" r="3"/>
    """,
    "external-link": """
        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
        <polyline points="15 3 21 3 21 9"/>
        <line x1="10" y1="14" x2="21" y2="3"/>
    """,
    "download": """
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
        <polyline points="7 10 12 15 17 10"/>
        <line x1="12" y1="15" x2="12" y2="3"/>
    """,
    "upload": """
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
        <polyline points="17 8 12 3 7 8"/>
        <line x1="12" y1="3" x2="12" y2="15"/>
    """,
    "plus": """
        <line x1="12" y1="5" x2="12" y2="19"/>
        <line x1="5" y1="12" x2="19" y2="12"/>
    """,
    "minus": """
        <line x1="5" y1="12" x2="19" y2="12"/>
    """,
    "x": """
        <line x1="18" y1="6" x2="6" y2="18"/>
        <line x1="6" y1="6" x2="18" y2="18"/>
    """,
    "search": """
        <circle cx="11" cy="11" r="8"/>
        <line x1="21" y1="21" x2="16.65" y2="16.65"/>
    """,
    "info": """
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="8" x2="12" y2="12"/>
        <line x1="12" y1="16" x2="12.01" y2="16"/>
    """,
    "eye": """
        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
        <circle cx="12" cy="12" r="3"/>
    """,
    "edit": """
        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
    """,
    "copy": """
        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
    """,
    "check": """
        <polyline points="20 6 9 17 4 12"/>
    """,
    "chevron-right": """
        <polyline points="9 18 15 12 9 6"/>
    """,
    "chevron-down": """
        <polyline points="6 9 12 15 18 9"/>
    """,
    "chevron-left": """
        <polyline points="15 18 9 12 15 6"/>
    """,
    "chevron-up": """
        <polyline points="18 15 12 9 6 15"/>
    """,
    "menu": """
        <line x1="3" y1="12" x2="21" y2="12"/>
        <line x1="3" y1="6" x2="21" y2="6"/>
        <line x1="3" y1="18" x2="21" y2="18"/>
    """,
    "more-horizontal": """
        <circle cx="12" cy="12" r="1"/>
        <circle cx="19" cy="12" r="1"/>
        <circle cx="5" cy="12" r="1"/>
    """,
    "more-vertical": """
        <circle cx="12" cy="12" r="1"/>
        <circle cx="12" cy="5" r="1"/>
        <circle cx="12" cy="19" r="1"/>
    """,
    "filter": """
        <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>
    """,
    "tag": """
        <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/>
        <line x1="7" y1="7" x2="7.01" y2="7"/>
    """,
    "link": """
        <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
        <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
    """,
    "mail": """
        <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
        <polyline points="22 6 12 13 2 6"/>
    """,
    "phone": """
        <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/>
    """,
    "image": """
        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
        <circle cx="8.5" cy="8.5" r="1.5"/>
        <polyline points="21 15 16 10 5 21"/>
    """,
    "alert-circle": """
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="8" x2="12" y2="12"/>
        <line x1="12" y1="16" x2="12.01" y2="16"/>
    """,
    "refresh-cw": """
        <polyline points="23 4 23 10 17 10"/>
        <polyline points="1 20 1 14 7 14"/>
        <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
    """,
    "log-out": """
        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
        <polyline points="16 17 21 12 16 7"/>
        <line x1="21" y1="12" x2="9" y2="12"/>
    """,
    "log-in": """
        <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/>
        <polyline points="10 17 15 12 10 7"/>
        <line x1="15" y1="12" x2="3" y2="12"/>
    """,
    "grid": """
        <rect x="3" y="3" width="7" height="7"/>
        <rect x="14" y="3" width="7" height="7"/>
        <rect x="14" y="14" width="7" height="7"/>
        <rect x="3" y="14" width="7" height="7"/>
    """,
    "bar-chart": """
        <line x1="12" y1="20" x2="12" y2="10"/>
        <line x1="18" y1="20" x2="18" y2="4"/>
        <line x1="6" y1="20" x2="6" y2="16"/>
    """,
    "pie-chart": """
        <path d="M21.21 15.89A10 10 0 1 1 8 2.83"/>
        <path d="M22 12A10 10 0 0 0 12 2v10z"/>
    """,
    "table": """
        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
        <line x1="3" y1="9" x2="21" y2="9"/>
        <line x1="3" y1="15" x2="21" y2="15"/>
        <line x1="9" y1="3" x2="9" y2="21"/>
        <line x1="15" y1="3" x2="15" y2="21"/>
    """,
    "folder": """
        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
    """,
    "database": """
        <ellipse cx="12" cy="5" rx="9" ry="3"/>
        <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
        <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
    """,
    "server": """
        <rect x="2" y="2" width="20" height="8" rx="2" ry="2"/>
        <rect x="2" y="14" width="20" height="8" rx="2" ry="2"/>
        <line x1="6" y1="6" x2="6.01" y2="6"/>
        <line x1="6" y1="18" x2="6.01" y2="18"/>
    """,
    "code": """
        <polyline points="16 18 22 12 16 6"/>
        <polyline points="8 6 2 12 8 18"/>
    """,
    "terminal": """
        <polyline points="4 17 10 11 4 5"/>
        <line x1="12" y1="19" x2="20" y2="19"/>
    """,
    "cpu": """
        <rect x="4" y="4" width="16" height="16" rx="2" ry="2"/>
        <rect x="9" y="9" width="6" height="6"/>
        <line x1="9" y1="1" x2="9" y2="4"/>
        <line x1="15" y1="1" x2="15" y2="4"/>
        <line x1="9" y1="20" x2="9" y2="23"/>
        <line x1="15" y1="20" x2="15" y2="23"/>
        <line x1="20" y1="9" x2="23" y2="9"/>
        <line x1="20" y1="14" x2="23" y2="14"/>
        <line x1="1" y1="9" x2="4" y2="9"/>
        <line x1="1" y1="14" x2="4" y2="14"/>
    """,
    "globe": """
        <circle cx="12" cy="12" r="10"/>
        <line x1="2" y1="12" x2="22" y2="12"/>
        <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
    """,
    "star": """
        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
    """,
    "heart": """
        <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
    """,
    "flag": """
        <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/>
        <line x1="4" y1="22" x2="4" y2="15"/>
    """,
    "send": """
        <line x1="22" y1="2" x2="11" y2="13"/>
        <polygon points="22 2 15 22 11 13 2 9 22 2"/>
    """,
    "message-square": """
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    """,
    "archive": """
        <polyline points="21 8 21 21 3 21 3 8"/>
        <rect x="1" y="3" width="22" height="5"/>
        <line x1="10" y1="12" x2="14" y2="12"/>
    """,
    "box": """
        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
        <polyline points="3.27 6.96 12 12.01 20.73 6.96"/>
        <line x1="12" y1="22.08" x2="12" y2="12"/>
    """,
    "layout": """
        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
        <line x1="3" y1="9" x2="21" y2="9"/>
        <line x1="9" y1="21" x2="9" y2="9"/>
    """,
    "sidebar": """
        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
        <line x1="9" y1="3" x2="9" y2="21"/>
    """,
    "hard-drive": """
        <line x1="22" y1="12" x2="2" y2="12"/>
        <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>
        <line x1="6" y1="16" x2="6.01" y2="16"/>
        <line x1="10" y1="16" x2="10.01" y2="16"/>
    """,
}

_SEMANTIC_ICON_ALIASES = {
    "acl": "shield",
    "alert": "triangle-alert",
    "alert-circle": "alert-circle",
    "alert-triangle": "triangle-alert",
    "archive": "archive",
    "activity": "activity",
    "bar-chart": "bar-chart",
    "bell": "bell",
    "bell-off": "bell-off",
    "book": "book-open",
    "box": "box",
    "calendar": "calendar",
    "calendar-x": "calendar-x",
    "check": "check",
    "check-circle": "check-circle",
    # Nome usato da voci di navigazione esistenti: senza alias finiva stampato
    # com'e' nella barra in alto ("check-square" accanto a KICK-OFF).
    "check-square": "check-circle",
    "chevron-down": "chevron-down",
    "chevron-left": "chevron-left",
    "chevron-right": "chevron-right",
    "chevron-up": "chevron-up",
    "clipboard-list": "clipboard-list",
    "clock": "clock",
    "code": "code",
    "copy": "copy",
    "cpu": "cpu",
    "dashboard": "layout-dashboard",
    "database": "database",
    "download": "download",
    "edit": "edit",
    "external-link": "external-link",
    "eye": "eye",
    "file-check": "file-check",
    "file-check-circle": "file-check",
    "file-text": "file-text",
    "filter": "filter",
    "flag": "flag",
    "flow": "workflow",
    "folder": "folder",
    "globe": "globe",
    "grid": "grid",
    "hard-drive": "hard-drive",
    "heart": "heart",
    "home": "home",
    "id-card": "id-card",
    "image": "image",
    "info": "info",
    "key-round": "key-round",
    "layers": "layers",
    "layout": "layout",
    "layout-dashboard": "layout-dashboard",
    "link": "link",
    "list": "list",
    "list-todo": "list-todo",
    "lock": "lock",
    "log-in": "log-in",
    "log-out": "log-out",
    "mail": "mail",
    "map": "map",
    "menu": "menu",
    "message-square": "message-square",
    "minus": "minus",
    "more-horizontal": "more-horizontal",
    "more-vertical": "more-vertical",
    "newspaper": "newspaper",
    "news": "newspaper",
    "notebook": "clipboard-list",
    "octagon-alert": "octagon-alert",
    "package": "package",
    "phone": "phone",
    "pie-chart": "pie-chart",
    "pin": "pin",
    "plus": "plus",
    "recycle": "recycle",
    "refresh-cw": "refresh-cw",
    "scan": "scan",
    "search": "search",
    "send": "send",
    "server": "server",
    "settings": "settings",
    "shield": "shield",
    "shield-check": "shield-check",
    "sidebar": "sidebar",
    "siren": "siren",
    "star": "star",
    "table": "table",
    "tag": "tag",
    "terminal": "terminal",
    "ticket": "ticket",
    "tool": "tool",
    "trash": "trash",
    "trash-2": "trash-2",
    "triangle-alert": "triangle-alert",
    "upload": "upload",
    "user": "user",
    "users": "users",
    "users-round": "users",
    "workflow": "workflow",
    "wrench": "wrench",
    "x": "x",
    "zap": "zap",
    "briefcase": "briefcase",
    "book-open": "book-open",
    "check-circle": "check-circle",
    "calendar-x": "calendar-x",
}

_LABEL_ICON_ALIASES = {
    "accessi-azienda": "key-round",
    "anagrafica": "id-card",
    "anomalie": "octagon-alert",
    "assets": "package",
    "assenze": "calendar-x",
    "automazioni": "zap",
    "automation": "zap",
    "dashboard": "layout-dashboard",
    "diario-preposto": "clipboard-list",
    "dipendenti": "id-card",
    "dpi": "shield-check",
    "fornitori": "briefcase",
    "gestione-anomalie": "octagon-alert",
    "hr": "users",
    "inventario": "package",
    "inventario-asset": "package",
    "manutenzione": "wrench",
    "notizie": "newspaper",
    "notifiche": "bell",
    "planimetria": "map",
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
    # Token di 1-2 char sono quasi sempre placeholder (es. "PN", "A")
    # Token di 3 char potrebbero essere abbreviazioni, ma controlliamo
    # se sembrano un nome Lucide (contengono "-" o sono abbastanza lunghi)
    if len(token) <= 2:
        return True
    if len(token) == 3 and "-" not in token:
        return True
    return False


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
    """Testo da mostrare quando l'icona non si risolve in un'immagine o in un SVG.

    Un'icona puo' essere un'emoji, e allora si stampa. Ma uno **slug** non
    riconosciuto (``check-square``, ``file-text``) non e' un glifo: stamparlo
    significa scrivere il nome dell'icona dentro l'interfaccia, che e' esattamente
    cio' che succedeva nella barra in alto. In quel caso si ripiega sull'iniziale
    dell'etichetta, come per un'icona assente.
    """
    text = str(value or "").strip()
    if text and not _looks_like_icon_slug(text):
        return text
    fallback_text = str(fallback or "").strip()
    return fallback_text[:1].upper() if fallback_text else ""


def _looks_like_icon_slug(text: str) -> bool:
    """Vero per nomi tipo ``check-square``: solo ASCII, piu' lungo di due caratteri."""
    if len(text) <= 2:
        return False
    return all(ch.isascii() and (ch.isalnum() or ch in "-_") for ch in text)
