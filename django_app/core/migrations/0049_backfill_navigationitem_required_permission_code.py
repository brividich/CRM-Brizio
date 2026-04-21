from __future__ import annotations

import re
from urllib.parse import urlsplit

from django.db import migrations
from django.urls import NoReverseMatch, reverse


def _normalize_path(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        raw = parsed.path or "/"
    if not raw.startswith("/"):
        raw = "/" + raw
    if raw != "/":
        raw = raw.rstrip("/")
    return raw.lower()


def _binding_matches_path(binding, path_norm: str) -> bool:
    strategy = str(getattr(binding, "match_strategy", "") or "exact").strip().lower()
    pattern_raw = str(getattr(binding, "path_pattern", "") or "").strip()
    if not pattern_raw:
        return False
    if strategy == "regex":
        try:
            return re.search(pattern_raw, path_norm) is not None
        except re.error:
            return False
    pattern = _normalize_path(pattern_raw)
    if not pattern:
        return False
    if strategy == "prefix":
        return path_norm == pattern or path_norm.startswith(pattern + "/")
    return path_norm == pattern


def _binding_sort_key(binding) -> tuple[int, int, int, int]:
    strategy = str(getattr(binding, "match_strategy", "") or "exact").strip().lower()
    if strategy == "exact":
        strategy_rank = 0
        pattern = _normalize_path(getattr(binding, "path_pattern", "") or "")
    elif strategy == "prefix":
        strategy_rank = 1
        pattern = _normalize_path(getattr(binding, "path_pattern", "") or "")
    else:
        strategy_rank = 2
        pattern = str(getattr(binding, "path_pattern", "") or "")
    return (
        int(getattr(binding, "priority", 0) or 0),
        strategy_rank,
        -len(pattern),
        int(getattr(binding, "id", 0) or 0),
    )


def _infer_required_permission_codes(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    RoutePermissionBinding = apps.get_model("core", "RoutePermissionBinding")

    bindings_by_route: dict[str, str] = {}
    path_bindings = list(
        RoutePermissionBinding.objects.filter(is_active=True)
        .exclude(path_pattern="")
        .order_by("priority", "id")
    )

    for binding in RoutePermissionBinding.objects.filter(is_active=True).order_by("priority", "id"):
        route_name = str(getattr(binding, "route_name", "") or "").strip().lower()
        if route_name and route_name not in bindings_by_route:
            bindings_by_route[route_name] = str(binding.permission_id or "")

    for item in NavigationItem.objects.all().order_by("id"):
        if str(getattr(item, "required_permission_code", "") or "").strip():
            continue

        permission_code = ""
        route_name = str(getattr(item, "route_name", "") or "").strip()
        route_name_norm = route_name.lower()
        if route_name_norm:
            permission_code = bindings_by_route.get(route_name_norm, "")

        candidate_path = ""
        if not permission_code and route_name:
            try:
                candidate_path = _normalize_path(reverse(route_name))
            except NoReverseMatch:
                candidate_path = ""
        if not candidate_path:
            candidate_path = _normalize_path(getattr(item, "url_path", "") or "")

        if not permission_code and candidate_path:
            matches = [binding for binding in path_bindings if _binding_matches_path(binding, candidate_path)]
            winner = min(matches, key=_binding_sort_key) if matches else None
            permission_code = str(getattr(winner, "permission_id", "") or "") if winner is not None else ""

        if not permission_code:
            continue

        item.required_permission_code = permission_code
        item.save(update_fields=["required_permission_code"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0048_navigationitem_required_permission_code"),
    ]

    operations = [
        migrations.RunPython(_infer_required_permission_codes, migrations.RunPython.noop),
    ]
