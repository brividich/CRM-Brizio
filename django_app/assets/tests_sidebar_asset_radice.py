"""Sidebar: gli asset assegnati direttamente a una categoria radice con
sotto-categorie compaiono come voci che aprono la scheda (es. «Azoto» sotto
«Novicrom»)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from assets.models import Asset, AssetCategory, AssetSidebarButton
from assets.services.sidebar_categories import rebuild_category_sidebar
from assets.views import _helpers_c


class SidebarAssetRadiceTests(TestCase):
    def setUp(self):
        self.root = AssetCategory.objects.create(code="sede-x", label="Sede X", is_active=True)
        AssetCategory.objects.create(code="scale-x", label="Scale X", parent=self.root, is_active=True)
        rebuild_category_sidebar(AssetCategory, AssetSidebarButton)
        self.azoto = Asset.objects.create(name="Azoto", asset_type=Asset.TYPE_OTHER, asset_category=self.root)
        self.dismesso = Asset.objects.create(
            name="Vecchio", asset_type=Asset.TYPE_OTHER, asset_category=self.root, status=Asset.STATUS_RETIRED
        )
        user = get_user_model().objects.create_superuser(username="sb_admin", email="sb@example.com", password="x")
        self.request = RequestFactory().get(reverse("assets:asset_view", args=[self.azoto.id]))
        self.request.user = user

    def _gruppo(self):
        for section in _helpers_c._build_sidebar_groups(self.request):
            for item in section["items"]:
                if item["label"] == "Sede X":
                    return item
        self.fail("gruppo Sede X assente")

    def test_asset_della_radice_come_voce(self):
        gruppo = self._gruppo()
        etichette = [c["label"] for c in gruppo["children"]]
        self.assertIn("Scale X", etichette)
        self.assertIn("Azoto", etichette)
        self.assertNotIn("Vecchio", etichette)
        voce = next(c for c in gruppo["children"] if c["label"] == "Azoto")
        self.assertEqual(voce["url"], reverse("assets:asset_view", args=[self.azoto.id]))
        self.assertTrue(voce["active"])
        self.assertTrue(gruppo["expanded"])
