from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings

from core.acl_v2 import validate_permission_code
from core.legacy_models import Permesso, Pulsante
from core.management.commands.bootstrap_acl_v2 import STATUS_LEGACY_FALLBACK, STATUS_UNBOUND, _collect_route_coverage
from core.models import PermissionDefinition, RolePermissionGrant, RoutePermissionBinding


@override_settings(LEGACY_AUTH_ENABLED=True, SECURE_SSL_REDIRECT=False)
class BootstrapAclV2CommandTests(TestCase):
    def setUp(self):
        self._ensure_legacy_acl_tables()

    def _run_cmd(self, *args: str) -> str:
        stdout = StringIO()
        call_command("bootstrap_acl_v2", *args, stdout=stdout, verbosity=0)
        return stdout.getvalue()

    def _ensure_legacy_acl_tables(self):
        vendor = connection.vendor
        with connection.cursor() as cursor:
            if vendor == "sqlite":
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS pulsanti (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        codice VARCHAR(100) NOT NULL,
                        nome_visibile VARCHAR(200) NULL,
                        icona VARCHAR(20) NULL,
                        modulo VARCHAR(100) NOT NULL,
                        url VARCHAR(500) NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS permessi (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        modulo VARCHAR(100) NOT NULL,
                        azione VARCHAR(100) NOT NULL,
                        ruolo_id INTEGER NOT NULL,
                        consentito INTEGER NULL,
                        can_view INTEGER NULL,
                        can_edit INTEGER NULL,
                        can_delete INTEGER NULL,
                        can_approve INTEGER NULL
                    )
                    """
                )
            else:
                cursor.execute(
                    """
                    IF OBJECT_ID('pulsanti', 'U') IS NULL
                    CREATE TABLE pulsanti (
                        id INT IDENTITY(1,1) PRIMARY KEY,
                        codice NVARCHAR(100) NOT NULL,
                        nome_visibile NVARCHAR(200) NULL,
                        icona NVARCHAR(20) NULL,
                        modulo NVARCHAR(100) NOT NULL,
                        url NVARCHAR(500) NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    IF OBJECT_ID('permessi', 'U') IS NULL
                    CREATE TABLE permessi (
                        id INT IDENTITY(1,1) PRIMARY KEY,
                        modulo NVARCHAR(100) NOT NULL,
                        azione NVARCHAR(100) NOT NULL,
                        ruolo_id INT NOT NULL,
                        consentito INT NULL,
                        can_view INT NULL,
                        can_edit INT NULL,
                        can_delete INT NULL,
                        can_approve INT NULL
                    )
                    """
                )

    def test_dry_run_does_not_write_permissions_or_bindings(self):
        permissions_before = PermissionDefinition.objects.count()
        bindings_before = RoutePermissionBinding.objects.count()

        output = self._run_cmd("--dry-run", "--apps", "assets")

        self.assertEqual(PermissionDefinition.objects.count(), permissions_before)
        self.assertEqual(RoutePermissionBinding.objects.count(), bindings_before)
        self.assertIn("Route LEGACY_FALLBACK / UNBOUND raggruppate per app", output)
        self.assertIn("assets", output)

    def test_apply_creates_canonical_binding_for_assets_and_is_idempotent(self):
        self._run_cmd("--apply", "--apps", "assets")

        binding = RoutePermissionBinding.objects.filter(route_name="assets:asset_list", path_pattern="").first()
        self.assertIsNotNone(binding)
        self.assertTrue(binding.is_active)
        self.assertTrue(binding.permission_id)
        is_valid, _ = validate_permission_code(binding.permission_id)
        self.assertTrue(is_valid)

        count_first = RoutePermissionBinding.objects.filter(route_name="assets:asset_list", path_pattern="").count()
        self._run_cmd("--apply", "--apps", "assets")
        count_second = RoutePermissionBinding.objects.filter(route_name="assets:asset_list", path_pattern="").count()
        self.assertEqual(count_first, count_second)

    def test_apply_reduces_unbound_count_for_target_app(self):
        before = sum(
            1
            for row in _collect_route_coverage()
            if row.app_label == "assets" and row.status == STATUS_UNBOUND
        )

        self._run_cmd("--apply", "--apps", "assets")

        after = sum(
            1
            for row in _collect_route_coverage()
            if row.app_label == "assets" and row.status == STATUS_UNBOUND
        )

        self.assertGreater(before, 0)
        self.assertLess(after, before)

    def test_apply_syncs_role_grants_for_legacy_fallback_routes(self):
        Pulsante.objects.create(
            codice="map_acl",
            nome_visibile="Mappa ACL",
            icona="map",
            modulo="admin_portale",
            url="route:admin_portale:mappa_permessi_navigazione",
        )
        Permesso.objects.create(
            modulo="admin_portale",
            azione="map_acl",
            ruolo_id=6,
            can_view=1,
            consentito=1,
        )

        before_status = next(
            row.status
            for row in _collect_route_coverage()
            if row.route_name == "admin_portale:mappa_permessi_navigazione"
        )
        self.assertEqual(before_status, STATUS_LEGACY_FALLBACK)

        self._run_cmd("--apply", "--apps", "admin_portale")

        binding = RoutePermissionBinding.objects.filter(
            route_name="admin_portale:mappa_permessi_navigazione",
            path_pattern="",
        ).first()
        self.assertIsNotNone(binding)

        grant = RolePermissionGrant.objects.filter(
            legacy_role_id=6,
            permission_id=binding.permission_id,
        ).first()
        self.assertIsNotNone(grant)
        self.assertTrue(grant.enabled)
