from __future__ import annotations

from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, connections
from django.urls import NoReverseMatch, reverse

from core.legacy_models import Permesso, Pulsante
from core.legacy_utils import legacy_table_has_column


LEGACY_CACHE_VERSION_KEY = "legacy_acl_cache_version"
_DEFAULT_CACHE_VERSION = 1
_DEFAULT_ACL_CACHE_TTL = 120
_DEFAULT_NAV_CACHE_TTL = 120


def _safe_positive_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def get_legacy_acl_cache_ttl() -> int:
    return _safe_positive_int(getattr(settings, "LEGACY_ACL_CACHE_TTL", _DEFAULT_ACL_CACHE_TTL), _DEFAULT_ACL_CACHE_TTL)


def get_legacy_nav_cache_ttl() -> int:
    return _safe_positive_int(getattr(settings, "LEGACY_NAV_CACHE_TTL", _DEFAULT_NAV_CACHE_TTL), _DEFAULT_NAV_CACHE_TTL)


def get_legacy_cache_version() -> int:
    cached = cache.get(LEGACY_CACHE_VERSION_KEY)
    if isinstance(cached, int) and cached > 0:
        return cached
    cache.add(LEGACY_CACHE_VERSION_KEY, _DEFAULT_CACHE_VERSION, timeout=None)
    cached = cache.get(LEGACY_CACHE_VERSION_KEY)
    if isinstance(cached, int) and cached > 0:
        return cached
    cache.set(LEGACY_CACHE_VERSION_KEY, _DEFAULT_CACHE_VERSION, timeout=None)
    return _DEFAULT_CACHE_VERSION


def bump_legacy_cache_version() -> int:
    try:
        return int(cache.incr(LEGACY_CACHE_VERSION_KEY))
    except Exception:
        next_value = get_legacy_cache_version() + 1
        cache.set(LEGACY_CACHE_VERSION_KEY, next_value, timeout=None)
        return next_value


def _versioned_key(base_key: str) -> str:
    return f"{base_key}:v{get_legacy_cache_version()}"


def normalize_legacy_path(path: str) -> str:
    raw = urlsplit(path or "/").path or "/"
    path_norm = raw.strip().lower()
    if not path_norm.startswith("/"):
        path_norm = "/" + path_norm
    if path_norm != "/":
        path_norm = path_norm.rstrip("/")
    if path_norm.startswith("/admin/api/"):
        path_norm = path_norm.replace("/admin/api/", "/api/", 1)
    return path_norm or "/"


def normalize_legacy_button_url(url_value: str) -> str:
    raw_url = (url_value or "").strip()
    if not raw_url:
        return ""
    lower_url = raw_url.lower()
    if lower_url.startswith(("route:", "django:")):
        _, route_name = raw_url.split(":", 1)
        route_name = (route_name or "").strip()
        if not route_name:
            return ""
        try:
            raw_url = reverse(route_name)
        except NoReverseMatch:
            return ""
    return normalize_legacy_path(raw_url)


def _load_pulsanti_catalog() -> list[dict]:
    rows: list[dict] = []
    try:
        pulsanti = Pulsante.objects.all().order_by("modulo", "id")
    except DatabaseError:
        return rows
    for p in pulsanti:
        modulo = (p.modulo or "").strip()
        codice = (p.codice or "").strip()
        rows.append(
            {
                "id": int(p.id),
                "modulo": modulo,
                "modulo_norm": modulo.lower(),
                "codice": codice,
                "codice_norm": codice.lower(),
                "label": p.label,
                "url": (p.url or "").strip() or "/",
                "url_normalized": normalize_legacy_button_url(p.url or "/"),
            }
        )
    return rows


def get_cached_pulsanti_catalog() -> list[dict]:
    cache_key = _versioned_key("legacy:pulsanti")
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    rows = _load_pulsanti_catalog()
    cache.set(cache_key, rows, timeout=max(get_legacy_acl_cache_ttl(), get_legacy_nav_cache_ttl()))
    return rows


def _load_acl_pulsanti() -> list[dict]:
    rows = []
    for item in get_cached_pulsanti_catalog():
        url_norm = (item.get("url_normalized") or "").strip()
        if not url_norm:
            continue
        rows.append(
            {
                "id": int(item["id"]),
                "modulo": item.get("modulo", ""),
                "modulo_norm": item.get("modulo_norm", ""),
                "codice": item.get("codice", ""),
                "codice_norm": item.get("codice_norm", ""),
                "label": item.get("label", ""),
                "url": item.get("url", ""),
                "url_normalized": url_norm,
                "url_len": len(url_norm),
            }
        )
    rows.sort(key=lambda x: (-int(x["url_len"]), int(x["id"])))
    return rows


def get_cached_acl_pulsanti() -> list[dict]:
    cache_key = _versioned_key("legacy:pulsanti_acl")
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    rows = _load_acl_pulsanti()
    cache.set(cache_key, rows, timeout=get_legacy_acl_cache_ttl())
    return rows


def _load_perm_map(ruolo_id: int) -> dict[tuple[str, str], bool]:
    perm_map: dict[tuple[str, str], bool] = {}
    try:
        perms = Permesso.objects.filter(ruolo_id=ruolo_id).order_by("-id")
    except DatabaseError:
        return perm_map
    for perm in perms:
        modulo = (perm.modulo or "").strip().lower()
        azione = (perm.azione or "").strip().lower()
        if not modulo or not azione:
            continue
        key = (modulo, azione)
        if key in perm_map:
            continue
        perm_map[key] = bool(getattr(perm, "can_view", 0)) or bool(getattr(perm, "consentito", 0))
    return perm_map


def get_cached_perm_map(ruolo_id: int | None) -> dict[tuple[str, str], bool]:
    if not ruolo_id:
        return {}
    ruolo_int = int(ruolo_id)
    cache_key = _versioned_key(f"legacy:perm_map:{ruolo_int}")
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    perm_map = _load_perm_map(ruolo_int)
    cache.set(cache_key, perm_map, timeout=get_legacy_acl_cache_ttl())
    return perm_map


def _load_pulsanti_order_map() -> dict[int, int]:
    if not legacy_table_has_column("pulsanti", "ordine"):
        return {}
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT id, ordine FROM pulsanti")
            rows = cursor.fetchall()
    except Exception:
        return {}
    result: dict[int, int] = {}
    for row in rows:
        try:
            pulsante_id = int(row[0])
            order_value = int(row[1]) if row[1] is not None else 999999
        except (TypeError, ValueError):
            continue
        result[pulsante_id] = order_value
    return result


def get_cached_pulsanti_order_map() -> dict[int, int]:
    cache_key = _versioned_key("legacy:order_map")
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    order_map = _load_pulsanti_order_map()
    cache.set(cache_key, order_map, timeout=get_legacy_nav_cache_ttl())
    return order_map


def _boolish_db(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    try:
        return bool(int(value))
    except Exception:
        return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def _load_ui_meta_map() -> dict[int, dict]:
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute(
                """
                SELECT pulsante_id, ui_slot, ui_section, ui_order, visible_topbar, enabled
                FROM ui_pulsanti_meta
                """
            )
            rows = cursor.fetchall()
    except Exception:
        return {}
    result: dict[int, dict] = {}
    for row in rows:
        try:
            pid = int(row[0])
        except Exception:
            continue
        result[pid] = {
            "ui_slot": (row[1] or "").strip().lower() if row[1] is not None else "",
            "ui_section": (row[2] or "").strip() if row[2] is not None else "",
            "ui_order": int(row[3]) if row[3] is not None else None,
            "visible_topbar": _boolish_db(row[4], True),
            "enabled": _boolish_db(row[5], True),
        }
    return result


def get_cached_ui_meta_map() -> dict[int, dict]:
    cache_key = _versioned_key("legacy:ui_meta_map")
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    ui_meta_map = _load_ui_meta_map()
    cache.set(cache_key, ui_meta_map, timeout=get_legacy_nav_cache_ttl())
    return ui_meta_map
