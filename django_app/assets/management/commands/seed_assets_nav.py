from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import NavigationItem, NavigationRoleAccess
from core.navigation_registry import bump_navigation_registry_version


class Command(BaseCommand):
    help = "Crea (idempotente) la voce topbar 'Inventario asset' nel navigation registry."

    def add_arguments(self, parser):
        parser.add_argument("--code", default="assets", help="Codice univoco voce navigation.")
        parser.add_argument("--label", default="Inventario asset", help="Etichetta topbar.")
        parser.add_argument("--order", type=int, default=35, help="Ordine topbar.")
        parser.add_argument(
            "--role-id",
            action="append",
            dest="role_ids",
            default=[],
            help="Ruolo legacy da autorizzare esplicitamente (ripetibile).",
        )

    def handle(self, *args, **options):
        code = str(options["code"]).strip() or "assets"
        label = str(options["label"]).strip() or "Inventario asset"
        order = int(options["order"] or 35)
        role_ids = []
        for raw in options.get("role_ids") or []:
            try:
                role_ids.append(int(raw))
            except Exception:
                continue

        changed = False
        with transaction.atomic():
            item, created = NavigationItem.objects.get_or_create(
                code=code,
                defaults={
                    "label": label,
                    "route_name": "assets:asset_list",
                    "section": "topbar",
                    "order": order,
                    "is_visible": True,
                    "is_enabled": True,
                },
            )
            changed = changed or created
            updates = []
            if item.label != label:
                item.label = label
                updates.append("label")
            if item.route_name != "assets:asset_list":
                item.route_name = "assets:asset_list"
                updates.append("route_name")
            if item.section != "topbar":
                item.section = "topbar"
                updates.append("section")
            if item.order != order:
                item.order = order
                updates.append("order")
            if not item.is_visible:
                item.is_visible = True
                updates.append("is_visible")
            if not item.is_enabled:
                item.is_enabled = True
                updates.append("is_enabled")
            if updates:
                item.save(update_fields=updates)
                changed = True

            for role_id in role_ids:
                _, access_created = NavigationRoleAccess.objects.get_or_create(
                    item=item,
                    legacy_role_id=role_id,
                    defaults={"can_view": True},
                )
                if access_created:
                    changed = True

        if changed:
            try:
                bump_navigation_registry_version()
            except Exception:
                pass

        self.stdout.write(
            self.style.SUCCESS(
                f"Navigation seed completato: code={code}, changed={'yes' if changed else 'no'}, role_access={len(role_ids)}"
            )
        )
