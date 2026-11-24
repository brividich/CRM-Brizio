"""Cartelle di categoria scelte per singolo asset: togli/aggiungi, facoltative,
asset senza cartelle di categoria."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset, AssetCategory, AssetCategoryDocumentFolder, AssetDocument
from assets.services import cartelle_asset
from assets.tests import _workspace_temporary_directory
from assets.views import _helpers as h
from core.models import UserOnboarding


def _codici(asset):
    asset.refresh_from_db()
    return {s["code"] for s in h._asset_document_folder_specs(asset) if s["scope"] == "category"}


class CartellePerAssetTests(TestCase):
    def setUp(self):
        self.cat = AssetCategory.objects.create(code="impianti-x", label="Impianti X", is_active=True)
        self.verbali = AssetCategoryDocumentFolder.objects.create(category=self.cat, name="Verbali", slug="verbali", order=1)
        self.collaudi = AssetCategoryDocumentFolder.objects.create(category=self.cat, name="Collaudi", slug="collaudi", order=2)
        self.a = Asset.objects.create(name="Bombola A", asset_type=Asset.TYPE_OTHER, asset_category=self.cat)
        self.b = Asset.objects.create(name="Bombola B", asset_type=Asset.TYPE_OTHER, asset_category=self.cat)
        user = get_user_model().objects.create_superuser(username="cart_admin", email="c@example.com", password="x")
        UserOnboarding.objects.update_or_create(user=user, defaults={"completed": True})
        self.client.force_login(user)

    def _post(self, asset, action, slug):
        return self.client.post(reverse("assets:asset_view", args=[asset.id]), {"action": action, "folder_slug": slug})

    def test_togli_solo_da_questo_asset_e_rimetti(self):
        self._post(self.a, "togli_cartella_categoria", "verbali")
        self.assertEqual(_codici(self.a), {"collaudi"})
        self.assertEqual(_codici(self.b), {"verbali", "collaudi"})
        nascoste = h._asset_document_hidden_category_folders(self.a, h._asset_document_folder_specs(self.a))
        self.assertEqual([c["slug"] for c in nascoste], ["verbali"])
        self._post(self.a, "aggiungi_cartella_categoria", "verbali")
        self.assertEqual(_codici(self.a), {"verbali", "collaudi"})

    def test_non_si_toglie_una_cartella_con_documenti(self):
        with _workspace_temporary_directory("assets-cart-") as tmpdir, override_settings(MEDIA_ROOT=tmpdir):
            AssetDocument.objects.create(
                asset=self.a, category="verbali",
                file=SimpleUploadedFile("v.pdf", b"%PDF-1.4 test", content_type="application/pdf"), original_name="v.pdf",
            )
            self._post(self.a, "togli_cartella_categoria", "verbali")
            self.assertIn("verbali", _codici(self.a))

    def test_facoltativa_solo_dove_aggiunta(self):
        self.collaudi.facoltativa = True
        self.collaudi.save(update_fields=["facoltativa"])
        self.assertEqual(_codici(self.a), {"verbali"})
        self._post(self.a, "aggiungi_cartella_categoria", "collaudi")
        self.assertEqual(_codici(self.a), {"verbali", "collaudi"})
        self.assertEqual(_codici(self.b), {"verbali"})

    def test_asset_senza_cartelle_di_categoria(self):
        cartelle_asset.salva(self.a, {"senza_categoria": True, "tolte": set(), "aggiunte": {"collaudi"}})
        self.assertEqual(_codici(self.a), {"collaudi"})
        cartelle_asset.salva(self.a, {"senza_categoria": False, "tolte": set(), "aggiunte": set()})
        self.a.refresh_from_db()
        self.assertNotIn(cartelle_asset.CHIAVE, self.a.extra_columns or {})

    def test_form_spunta_usa_cartelle(self):
        from assets.forms import AssetForm

        cartelle_asset.salva(self.a, {"senza_categoria": True, "tolte": set(), "aggiunte": set()})
        self.a.refresh_from_db()
        form = AssetForm(instance=self.a)
        self.assertFalse(form.fields["usa_cartelle_categoria"].initial)
        self.assertTrue(AssetForm().fields["usa_cartelle_categoria"].initial)
