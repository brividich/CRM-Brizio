"""Test del bootstrap ACL v2 canonico (PASSO 6)."""
from django.test import TestCase

from .acl_bootstrap import PERM_EDIT, PERM_VIEW, _bootstrap_canonical


class AclBootstrapTest(TestCase):
    def test_crea_permessi_binding_e_menu(self):
        from core.models import (
            NavigationItem, PermissionDefinition, RoutePermissionBinding,
        )

        _bootstrap_canonical()

        self.assertTrue(PermissionDefinition.objects.filter(code=PERM_VIEW).exists())
        self.assertTrue(PermissionDefinition.objects.filter(code=PERM_EDIT).exists())
        # binding view su una route di lettura, edit su una di scrittura
        self.assertTrue(RoutePermissionBinding.objects.filter(
            route_name="gestione_carichi_macchina:excel", permission_id=PERM_VIEW
        ).exists())
        self.assertTrue(RoutePermissionBinding.objects.filter(
            route_name="gestione_carichi_macchina:reschedule", permission_id=PERM_EDIT
        ).exists())
        nav = NavigationItem.objects.get(code="carichi-macchina")
        self.assertEqual(nav.required_permission_code, PERM_VIEW)
        self.assertEqual(nav.route_name, "gestione_carichi_macchina:excel")

    def test_idempotente(self):
        from core.models import RoutePermissionBinding

        _bootstrap_canonical()
        _bootstrap_canonical()
        self.assertEqual(
            RoutePermissionBinding.objects.filter(
                route_name="gestione_carichi_macchina:excel"
            ).count(),
            1,
        )
