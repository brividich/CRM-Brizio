from __future__ import annotations

from urllib.parse import urlsplit

from django.db import migrations, models


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


def _infer_required_permission_codes(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    RoutePermissionBinding = apps.get_model("core", "RoutePermissionBinding")

    bindings_by_route: dict[str, str] = {}
    path_bindings: list[tuple[int, str, str]] = []

    for binding in (
        RoutePermissionBinding.objects.filter(is_active=True)
        .order_by("priority", "id")
    ):
        route_name = str(getattr(binding, "route_name", "") or "").strip().lower()
        path_pattern = str(getattr(binding, "path_pattern", "") or "").strip()
        if route_name and route_name not in bindings_by_route:
            bindings_by_route[route_name] = str(binding.permission_id or "")
        if path_pattern:
            normalized = _normalize_path(path_pattern)
            if normalized:
                path_bindings.append(
                    (
                        int(getattr(binding, "id", 0) or 0),
                        normalized,
                        str(binding.permission_id or ""),
                    )
                )

    path_bindings.sort(key=lambda row: (len(row[1]), -row[0]), reverse=True)

    for item in NavigationItem.objects.all().order_by("id"):
        if str(getattr(item, "required_permission_code", "") or "").strip():
            continue

        permission_code = ""
        route_name = str(getattr(item, "route_name", "") or "").strip().lower()
        if route_name:
            permission_code = bindings_by_route.get(route_name, "")

        if not permission_code:
            target_path = _normalize_path(getattr(item, "url_path", "") or "")
            if target_path:
                for _binding_id, path_pattern, candidate_code in path_bindings:
                    if target_path == path_pattern or target_path.startswith(path_pattern + "/"):
                        permission_code = candidate_code
                        break

        if not permission_code:
            continue

        item.required_permission_code = permission_code
        item.save(update_fields=["required_permission_code"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0047_admin_subnav_trigger_generator"),
    ]

    operations = [
        migrations.AddField(
            model_name="navigationitem",
            name="required_permission_code",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="Permission code canonico richiesto per mostrare la voce. Se vuoto, il registry prova a ricavarlo da route_name/url_path.",
                max_length=120,
            ),
        ),
        migrations.RunPython(_infer_required_permission_codes, migrations.RunPython.noop),
    ]
