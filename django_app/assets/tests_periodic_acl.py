"""ACL v2 delle verifiche periodiche: binding propri e nessun accesso perso (migrazione 0118)."""

from __future__ import annotations

import importlib

from django.apps import apps as django_apps
from django.test import TestCase

from core.acl_v2 import resolve_canonical_target
from core.models import PermissionDefinition, RolePermissionGrant, RoutePermissionBinding, UserPermissionGrant

migration = importlib.import_module("assets.migrations.0118_acl_v2_verifiche_impianti")

ROOT_CODE = "legacy.assets.assets_periodic_checks"
CATEGORIES_CODE = "legacy.assets.assets_periodic_check_categories"


class VerificheAclV2Tests(TestCase):
    def _code_for(self, route_name: str, **kwargs) -> str:
        from django.urls import reverse

        target = resolve_canonical_target(path=reverse(route_name, kwargs=kwargs or None))
        return (target["permission"] or {}).get("code", "")

    def test_rotte_verifiche_legate_al_permesso_proprio(self):
        RoutePermissionBinding.objects.get_or_create(
            route_name="", path_pattern="/assets",
            defaults={"match_strategy": "prefix", "permission": PermissionDefinition.objects.get_or_create(
                code=migration.SOURCE_CODE, defaults={"label": "Assets", "module": "assets"})[0]},
        )
        self.assertEqual(self._code_for("assets:periodic_check_list"), ROOT_CODE)
        self.assertEqual(self._code_for("assets:periodic_check_systems"), ROOT_CODE)
        self.assertEqual(self._code_for("assets:periodic_check_intake"), ROOT_CODE)
        self.assertEqual(self._code_for("assets:periodic_check_type_detail", type_id=1), ROOT_CODE)
        self.assertEqual(self._code_for("assets:periodic_check_categories"), CATEGORIES_CODE)
        # Il resto del modulo resta sul prefisso generico.
        self.assertEqual(self._code_for("assets:asset_dashboard"), migration.SOURCE_CODE)

    def test_grant_copiati_da_view_assets(self):
        source, _ = PermissionDefinition.objects.get_or_create(
            code=migration.SOURCE_CODE, defaults={"label": "Assets", "module": "assets"}
        )
        RolePermissionGrant.objects.create(legacy_role_id=7, permission=source, enabled=True)
        RolePermissionGrant.objects.create(legacy_role_id=8, permission=source, enabled=False)
        UserPermissionGrant.objects.create(legacy_user_id=42, permission=source, enabled=True)

        migration.avanti(django_apps, None)
        migration.avanti(django_apps, None)  # idempotente

        for code in (ROOT_CODE, CATEGORIES_CODE):
            self.assertTrue(RolePermissionGrant.objects.get(legacy_role_id=7, permission_id=code).enabled)
            self.assertFalse(RolePermissionGrant.objects.get(legacy_role_id=8, permission_id=code).enabled)
            self.assertTrue(UserPermissionGrant.objects.get(legacy_user_id=42, permission_id=code).enabled)
            self.assertEqual(RoutePermissionBinding.objects.filter(permission_id=code).count(), 1)
