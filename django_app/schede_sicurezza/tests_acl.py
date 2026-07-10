from __future__ import annotations

from django.test import TestCase

from .acl_bootstrap import PERM_GESTISCI, PERM_VIEW, _bootstrap_canonical


class AclBootstrapTest(TestCase):
    def test_crea_permessi_binding_e_menu(self):
        from core.models import NavigationItem, PermissionDefinition, RoutePermissionBinding

        _bootstrap_canonical()

        self.assertTrue(PermissionDefinition.objects.filter(code=PERM_VIEW).exists())
        self.assertTrue(PermissionDefinition.objects.filter(code=PERM_GESTISCI).exists())
        self.assertTrue(RoutePermissionBinding.objects.filter(
            route_name="schede_sicurezza:scheda_mobile", permission_id=PERM_VIEW
        ).exists())
        self.assertTrue(RoutePermissionBinding.objects.filter(
            route_name="schede_sicurezza:prodotto_nuovo", permission_id=PERM_GESTISCI
        ).exists())
        nav = NavigationItem.objects.get(code="schede-sicurezza")
        self.assertEqual(nav.required_permission_code, PERM_VIEW)

    def test_idempotente(self):
        from core.models import RoutePermissionBinding

        _bootstrap_canonical()
        _bootstrap_canonical()
        self.assertEqual(
            RoutePermissionBinding.objects.filter(
                route_name="schede_sicurezza:scheda_mobile"
            ).count(),
            1,
        )

    def test_binding_report_compliance(self):
        from core.models import RoutePermissionBinding

        _bootstrap_canonical()
        self.assertTrue(RoutePermissionBinding.objects.filter(
            route_name="schede_sicurezza:report_compliance", permission_id=PERM_GESTISCI
        ).exists())
