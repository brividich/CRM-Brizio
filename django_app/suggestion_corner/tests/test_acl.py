from __future__ import annotations

from django.test import TestCase

from core.legacy_models import Ruolo
from core.models import NavigationItem, PermissionDefinition, RoutePermissionBinding
from suggestion_corner.acl_bootstrap import (
    PERM_VIEW, bootstrap_suggestion_corner_acl,
)


class SuggestionCornerAclTest(TestCase):
    def test_bootstrap_crea_permesso_binding_nav(self):
        Ruolo.objects.get_or_create(id=1, defaults={"nome": "admin"})
        bootstrap_suggestion_corner_acl(force=True)

        self.assertTrue(PermissionDefinition.objects.filter(code=PERM_VIEW).exists())
        self.assertTrue(
            RoutePermissionBinding.objects.filter(
                route_name="suggestion_corner:home", permission_id=PERM_VIEW
            ).exists()
        )
        self.assertTrue(
            RoutePermissionBinding.objects.filter(
                route_name="suggestion_corner:dettaglio", permission_id=PERM_VIEW
            ).exists()
        )
        self.assertTrue(NavigationItem.objects.filter(code="suggestion-corner").exists())
