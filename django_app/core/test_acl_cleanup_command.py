"""``acl_cleanup``: riattiva i binding senza togliere accesso a nessuno.

Il rischio del comando non e' quello che scrive, e' quello che potrebbe chiudere:
riattivando il binding proprio di una pagina, il prefisso permissivo che la
governava smette di valere. Questi test fissano il patto: dry-run non scrive, e
chi entrava prima entra anche dopo.
"""
from __future__ import annotations

from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings

from core.acl_resolver import resolve_permission_decision
from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Permesso, Ruolo, UtenteLegacy
from core.models import (
    PermissionDefinition,
    RolePermissionGrant,
    RoutePermissionBinding,
)
from core.test_acl_v2 import _clear_legacy_acl_tables, _ensure_legacy_acl_tables

RUOLO_ID = 55
ROUTE = "assets:gestione_admin"
PREFIX_CODE = "legacy.assets.view_assets"
OWN_CODE = "assets.gestione_admin.view"


@override_settings(LEGACY_AUTH_ENABLED=True)
class AclCleanupCommandTest(TestCase):
    def setUp(self):
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        cache.clear()

        Ruolo.objects.create(id=RUOLO_ID, nome="manutenzione")
        self.legacy_user = UtenteLegacy.objects.create(
            nome="Mario Manutentore",
            email="manutentore@example.local",
            password="x",
            ruolo="manutenzione",
            attivo=True,
            deve_cambiare_password=False,
            ruolo_id=RUOLO_ID,
        )

        self.prefix_permission = PermissionDefinition.objects.create(
            code=PREFIX_CODE, label="Inventario Asset", module="assets"
        )
        self.own_permission = PermissionDefinition.objects.create(
            code=OWN_CODE, label="Assets - Impostazioni", module="assets"
        )
        # Il prefisso governa oggi tutte le pagine sotto /assets, impostazioni comprese.
        RoutePermissionBinding.objects.create(
            path_pattern="/assets",
            match_strategy=RoutePermissionBinding.MATCH_PREFIX,
            permission=self.prefix_permission,
            is_active=True,
            priority=100,
        )
        # Il binding proprio della pagina esiste ma e' spento: e' il difetto.
        self.own_binding = RoutePermissionBinding.objects.create(
            route_name=ROUTE,
            permission=self.own_permission,
            is_active=False,
            priority=200,
        )
        # Il ruolo entra oggi, grazie al permesso dell'inventario.
        RolePermissionGrant.objects.create(
            legacy_role_id=RUOLO_ID, permission=self.prefix_permission, enabled=True
        )
        bump_legacy_cache_version()

    def _run(self, *args) -> str:
        out = StringIO()
        call_command("acl_cleanup", *args, stdout=out)
        return out.getvalue()

    def _can(self, code: str) -> bool:
        return resolve_permission_decision(
            permission_code=code,
            legacy_user=self.legacy_user,
            allow_superuser=False,
            allow_legacy_admin=False,
        ).allowed

    def test_dry_run_non_scrive_nulla(self):
        output = self._run()
        self.assertIn("DRY-RUN", output)
        self.own_binding.refresh_from_db()
        self.assertFalse(self.own_binding.is_active)
        self.assertFalse(
            RolePermissionGrant.objects.filter(
                legacy_role_id=RUOLO_ID, permission_id=OWN_CODE
            ).exists()
        )

    def test_apply_riattiva_il_binding_proprio(self):
        self._run("--apply")
        self.own_binding.refresh_from_db()
        self.assertTrue(self.own_binding.is_active)

    def test_chi_entrava_prima_entra_anche_dopo(self):
        self.assertTrue(self._can(PREFIX_CODE))
        self.assertFalse(self._can(OWN_CODE))

        self._run("--apply")
        cache.clear()

        self.assertTrue(self._can(OWN_CODE))
        grant = RolePermissionGrant.objects.get(legacy_role_id=RUOLO_ID, permission_id=OWN_CODE)
        self.assertTrue(grant.enabled)
        self.assertIn("grandfathering", grant.note)

    def test_e_idempotente(self):
        self._run("--apply")
        prima = RolePermissionGrant.objects.count()
        self._run("--apply")
        self.assertEqual(RolePermissionGrant.objects.count(), prima)

    def test_sync_legacy_riallinea_il_grant_che_ignorava_il_pannello(self):
        """Il permesso e' spuntato nel pannello legacy ma il canonico dice no."""
        permission = PermissionDefinition.objects.create(
            code="legacy.assets.admin_assets", label="Gestione interna Assets", module="assets"
        )
        RolePermissionGrant.objects.create(
            legacy_role_id=RUOLO_ID, permission=permission, enabled=False
        )
        Permesso.objects.create(
            ruolo_id=RUOLO_ID, modulo="assets", azione="admin_assets", consentito=1, can_view=1
        )
        bump_legacy_cache_version()
        cache.clear()

        self.assertFalse(self._can("legacy.assets.admin_assets"))
        self._run("--apply", "--sync-legacy")
        cache.clear()
        self.assertTrue(self._can("legacy.assets.admin_assets"))
