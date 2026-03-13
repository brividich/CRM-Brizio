from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from django.core.cache import cache
from django.db import transaction
from django.urls import NoReverseMatch, reverse

from core.legacy_cache import normalize_legacy_path
from core.module_registry import navigation_code_label_map
from core.models import NavigationItem, NavigationRoleAccess, NavigationSnapshot


NAV_REGISTRY_VERSION_KEY = "nav_registry_version"
_DEFAULT_VERSION = 1
_NAV_CACHE_TTL = 300


@dataclass
class NavigationNode:
    label: str
    href: str
    active: bool
    order_hint: int
    coming: bool
    legacy_url: str
    modulo: str
    codice: str


def _safe_int(value, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def get_navigation_registry_version() -> int:
    cached = cache.get(NAV_REGISTRY_VERSION_KEY)
    if isinstance(cached, int) and cached > 0:
        return cached
    cache.add(NAV_REGISTRY_VERSION_KEY, _DEFAULT_VERSION, timeout=None)
    cached = cache.get(NAV_REGISTRY_VERSION_KEY)
    if isinstance(cached, int) and cached > 0:
        return cached
    cache.set(NAV_REGISTRY_VERSION_KEY, _DEFAULT_VERSION, timeout=None)
    return _DEFAULT_VERSION


def bump_navigation_registry_version() -> int:
    try:
        return int(cache.incr(NAV_REGISTRY_VERSION_KEY))
    except Exception:
        next_value = get_navigation_registry_version() + 1
        cache.set(NAV_REGISTRY_VERSION_KEY, next_value, timeout=None)
        return next_value


def _versioned_key(base: str) -> str:
    return f"{base}:v{get_navigation_registry_version()}"


def _path_variants(path: str) -> set[str]:
    norm = normalize_legacy_path(path)
    variants = {norm}
    if norm == "/":
        variants.add("/dashboard")
    elif norm == "/dashboard":
        variants.add("/")
    return variants


def _resolve_item_href(item: NavigationItem) -> tuple[str, bool]:
    route_name = (item.route_name or "").strip()
    if route_name:
        try:
            return reverse(route_name), False
        except NoReverseMatch:
            return reverse("coming_admin"), True
    url_path = (item.url_path or "").strip()
    if url_path:
        return url_path, False
    return reverse("coming_admin"), True


def _compiled_items_for_role(*, role_id: int | None, is_admin: bool, section: str) -> list[dict]:
    role_key = role_id if role_id is not None else 0
    cache_key = _versioned_key(f"nav_registry:role:{role_key}:admin:{1 if is_admin else 0}:section:{section}")
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    qs = NavigationItem.objects.filter(section=section, is_visible=True, is_enabled=True).order_by("order", "id")
    items = list(qs)
    item_ids = [int(item.id) for item in items]
    access_rows = list(NavigationRoleAccess.objects.filter(item_id__in=item_ids))

    access_map: dict[int, dict[int, bool]] = {}
    for row in access_rows:
        access_map.setdefault(int(row.item_id), {})[int(row.legacy_role_id)] = bool(row.can_view)

    compiled: list[dict] = []
    label_overrides = navigation_code_label_map(surface="menu")
    for item in items:
        item_access = access_map.get(int(item.id), {})
        # Nessun record accesso -> visibile a tutti
        allowed = True
        if item_access and not is_admin:
            allowed = bool(role_id is not None and item_access.get(int(role_id), False))
        if not allowed:
            continue
        href, coming = _resolve_item_href(item)
        normalized_code = str(item.code or "").strip().lower()
        compiled.append(
            {
                "id": int(item.id),
                "code": item.code,
                "label": label_overrides.get(normalized_code, item.label),
                "href": href,
                "order": _safe_int(item.order, 100),
                "coming": coming,
                "route_name": item.route_name,
                "url_path": item.url_path,
                "parent_code": item.parent_code or "",
            }
        )
    cache.set(cache_key, compiled, timeout=_NAV_CACHE_TTL)
    return compiled


def get_subnav_nodes(*, parent_code: str, role_id: int | None, is_admin: bool) -> list[NavigationNode]:
    """Restituisce le voci subnav per la sezione corrente (parent_code)."""
    if not parent_code:
        return []
    compiled = _compiled_items_for_role(role_id=role_id, is_admin=is_admin, section="subnav")
    nodes: list[NavigationNode] = []
    for row in compiled:
        if row.get("parent_code", "") != parent_code:
            continue
        nodes.append(
            NavigationNode(
                label=row["label"],
                href=row["href"],
                active=False,  # calcolato nel context processor
                order_hint=_safe_int(row["order"], 100),
                coming=bool(row["coming"]),
                legacy_url=row.get("route_name") or row.get("url_path") or "",
                modulo="navigation",
                codice=row["code"],
            )
        )
    nodes.sort(key=lambda n: (n.order_hint, n.label.lower()))
    return nodes


def get_topbar_nodes(*, current_path: str, role_id: int | None, is_admin: bool) -> list[NavigationNode]:
    compiled = _compiled_items_for_role(role_id=role_id, is_admin=is_admin, section="topbar")
    current_variants = _path_variants(current_path)
    nodes: list[NavigationNode] = []
    for row in compiled:
        href = row["href"]
        href_path = normalize_legacy_path(urlsplit(href).path or "/")
        active = bool(current_variants.intersection({href_path}))
        nodes.append(
            NavigationNode(
                label=row["label"],
                href=href,
                active=active,
                order_hint=_safe_int(row["order"], 100),
                coming=bool(row["coming"]),
                legacy_url=href_path,
                modulo="navigation",
                codice=row["code"],
            )
        )
    nodes.sort(key=lambda n: (n.order_hint, n.label.lower()))
    return nodes


def export_navigation_state() -> dict:
    items_payload = []
    for item in NavigationItem.objects.all().order_by("section", "order", "id"):
        items_payload.append(
            {
                "code": item.code,
                "label": item.label,
                "section": item.section,
                "route_name": item.route_name,
                "url_path": item.url_path,
                "order": item.order,
                "is_visible": item.is_visible,
                "is_enabled": item.is_enabled,
                "open_in_new_tab": item.open_in_new_tab,
                "description": item.description,
            }
        )
    access_payload = []
    for acc in NavigationRoleAccess.objects.select_related("item").all().order_by("item__code", "legacy_role_id"):
        access_payload.append(
            {
                "item_code": acc.item.code,
                "legacy_role_id": int(acc.legacy_role_id),
                "can_view": bool(acc.can_view),
            }
        )
    return {"items": items_payload, "role_access": access_payload}


def publish_navigation_snapshot(*, created_by=None, note: str = "") -> NavigationSnapshot:
    payload = export_navigation_state()
    latest = NavigationSnapshot.objects.order_by("-version", "-id").first()
    next_version = (int(latest.version) + 1) if latest else 1
    snap = NavigationSnapshot.objects.create(
        version=next_version,
        payload=payload,
        note=(note or "").strip(),
        created_by=created_by,
    )
    transaction.on_commit(bump_navigation_registry_version)
    return snap


def restore_navigation_snapshot(snapshot: NavigationSnapshot) -> None:
    payload = snapshot.payload if isinstance(snapshot.payload, dict) else {}
    items_payload = payload.get("items") if isinstance(payload.get("items"), list) else []
    access_payload = payload.get("role_access") if isinstance(payload.get("role_access"), list) else []

    with transaction.atomic():
        NavigationRoleAccess.objects.all().delete()
        NavigationItem.objects.all().delete()

        item_map: dict[str, NavigationItem] = {}
        for row in items_payload:
            if not isinstance(row, dict):
                continue
            code = str(row.get("code") or "").strip()
            if not code:
                continue
            item = NavigationItem.objects.create(
                code=code,
                label=str(row.get("label") or code),
                section=str(row.get("section") or "topbar"),
                route_name=str(row.get("route_name") or "").strip(),
                url_path=str(row.get("url_path") or "").strip(),
                order=_safe_int(row.get("order"), 100),
                is_visible=bool(row.get("is_visible", True)),
                is_enabled=bool(row.get("is_enabled", True)),
                open_in_new_tab=bool(row.get("open_in_new_tab", False)),
                description=str(row.get("description") or "").strip(),
            )
            item_map[code] = item

        for row in access_payload:
            if not isinstance(row, dict):
                continue
            code = str(row.get("item_code") or "").strip()
            item = item_map.get(code)
            if item is None:
                continue
            role_id = row.get("legacy_role_id")
            try:
                legacy_role_id = int(role_id)
            except Exception:
                continue
            NavigationRoleAccess.objects.create(
                item=item,
                legacy_role_id=legacy_role_id,
                can_view=bool(row.get("can_view", True)),
            )
        transaction.on_commit(bump_navigation_registry_version)
