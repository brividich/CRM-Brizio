from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import ModuleCategory, NavigationItem, NavigationRoleAccess
from core.navigation_registry import bump_navigation_registry_version, publish_navigation_snapshot


def _fields(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("fields")
    return value if isinstance(value, dict) else {}


def _model(row: dict[str, Any]) -> str:
    return str(row.get("model") or "").strip().lower()


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class Command(BaseCommand):
    help = (
        "Ripristina ModuleCategory, NavigationItem e NavigationRoleAccess da un dump JSON "
        "Django serializer. Dry-run di default; usare --apply per scrivere."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            default=str(Path(settings.BASE_DIR) / "fixtures" / "nav_acl_snapshot.json"),
            help="File JSON sorgente. Default: django_app/fixtures/nav_acl_snapshot.json.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Applica il restore. Senza questo flag mostra solo il piano.",
        )
        parser.add_argument(
            "--no-backup",
            action="store_true",
            help="Non pubblica uno snapshot di backup prima del restore.",
        )
        parser.add_argument(
            "--note",
            default="Restore Navigation Registry da fixture locale",
            help="Nota per lo snapshot di backup/cache audit.",
        )

    def handle(self, *args, **options):
        source = Path(str(options["source"])).resolve()
        apply = bool(options["apply"])
        no_backup = bool(options["no_backup"])
        note = str(options["note"] or "").strip()

        if not source.exists():
            raise CommandError(f"File sorgente non trovato: {source}")

        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"JSON non valido: {exc}") from exc

        if not isinstance(payload, list):
            raise CommandError("Formato non valido: atteso un dump JSON serializer Django (lista di oggetti).")

        category_rows = [row for row in payload if isinstance(row, dict) and _model(row) == "core.modulecategory"]
        item_rows = [row for row in payload if isinstance(row, dict) and _model(row) == "core.navigationitem"]
        access_rows = [row for row in payload if isinstance(row, dict) and _model(row) == "core.navigationroleaccess"]

        if not item_rows:
            raise CommandError("La sorgente non contiene core.NavigationItem.")

        source_topbar = [
            _fields(row).get("label") or _fields(row).get("code")
            for row in item_rows
            if str(_fields(row).get("section") or "").strip().lower() == "topbar"
        ]
        current_topbar = list(
            NavigationItem.objects.filter(section="topbar", is_visible=True, is_enabled=True)
            .order_by("order", "id")
            .values_list("label", flat=True)
        )

        self.stdout.write(f"Sorgente: {source}")
        self.stdout.write(f"ModuleCategory sorgente: {len(category_rows)}")
        self.stdout.write(f"NavigationItem sorgente: {len(item_rows)}")
        self.stdout.write(f"NavigationRoleAccess sorgente: {len(access_rows)}")
        self.stdout.write(f"Topbar sorgente ({len(source_topbar)}): {', '.join(str(v) for v in source_topbar)}")
        self.stdout.write(f"Topbar corrente ({len(current_topbar)}): {', '.join(str(v) for v in current_topbar) or '-'}")

        if not apply:
            self.stdout.write(self.style.WARNING("DRY-RUN: nessuna modifica. Ripetere con --apply per ripristinare."))
            return

        with transaction.atomic():
            if not no_backup:
                backup_note = note or "Backup prima restore Navigation Registry"
                snap = publish_navigation_snapshot(note=backup_note)
                self.stdout.write(self.style.SUCCESS(f"Snapshot backup pubblicato: v{snap.version} id={snap.id}"))

            category_pk_to_obj: dict[int, ModuleCategory] = {}
            for row in category_rows:
                fields = _fields(row)
                key = str(fields.get("key") or "").strip()
                if not key:
                    continue
                category, _created = ModuleCategory.objects.update_or_create(
                    key=key,
                    defaults={
                        "label": str(fields.get("label") or key).strip(),
                        "description": str(fields.get("description") or "").strip(),
                        "icon": str(fields.get("icon") or "").strip(),
                        "topbar_color": str(fields.get("topbar_color") or "#1e3a5f").strip(),
                        "order": _as_int(fields.get("order"), 100),
                    },
                )
                category_pk_to_obj[_as_int(row.get("pk"))] = category

            NavigationRoleAccess.objects.all().delete()
            NavigationItem.objects.all().delete()

            item_pk_to_obj: dict[int, NavigationItem] = {}
            for row in item_rows:
                fields = _fields(row)
                code = str(fields.get("code") or "").strip()
                if not code:
                    continue
                category = category_pk_to_obj.get(_as_int(fields.get("category")))
                item = NavigationItem.objects.create(
                    code=code,
                    label=str(fields.get("label") or code).strip(),
                    section=str(fields.get("section") or "topbar").strip() or "topbar",
                    parent_code=str(fields.get("parent_code") or "").strip(),
                    route_name=str(fields.get("route_name") or "").strip(),
                    url_path=str(fields.get("url_path") or "").strip(),
                    required_permission_code=str(fields.get("required_permission_code") or "").strip(),
                    order=_as_int(fields.get("order"), 100),
                    is_visible=_as_bool(fields.get("is_visible"), True),
                    is_enabled=_as_bool(fields.get("is_enabled"), True),
                    open_in_new_tab=_as_bool(fields.get("open_in_new_tab"), False),
                    icon=str(fields.get("icon") or "").strip(),
                    group=str(fields.get("group") or "").strip(),
                    active_patterns=str(fields.get("active_patterns") or "").strip(),
                    description=str(fields.get("description") or "").strip(),
                    category=category,
                )
                item_pk_to_obj[_as_int(row.get("pk"))] = item

            restored_access = 0
            for row in access_rows:
                fields = _fields(row)
                item = item_pk_to_obj.get(_as_int(fields.get("item")))
                role_id = _as_int(fields.get("legacy_role_id"))
                if item is None or not role_id:
                    continue
                NavigationRoleAccess.objects.update_or_create(
                    item=item,
                    legacy_role_id=role_id,
                    defaults={"can_view": _as_bool(fields.get("can_view"), True)},
                )
                restored_access += 1

            transaction.on_commit(bump_navigation_registry_version)

        self.stdout.write(
            self.style.SUCCESS(
                f"Restore completato: categorie={len(category_pk_to_obj)}, "
                f"voci={len(item_pk_to_obj)}, role_access={restored_access}."
            )
        )
