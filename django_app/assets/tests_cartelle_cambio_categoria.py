"""Cambio categoria di un asset: i documenti delle cartelle della vecchia
categoria restano visibili nella scheda (cartella «categoria precedente")."""

from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from assets.models import Asset, AssetCategory, AssetCategoryDocumentFolder, AssetDocument
from assets.tests import _workspace_temporary_directory
from assets.views import _helpers as h


class CartelleCambioCategoriaTests(TestCase):
    def test_cartella_vecchia_categoria_resta_visibile(self):
        vecchia = AssetCategory.objects.create(code="vecchia-cat", label="Vecchia", is_active=True)
        nuova = AssetCategory.objects.create(code="nuova-cat", label="Nuova", is_active=True)
        AssetCategoryDocumentFolder.objects.create(category=vecchia, name="Verbali di verifica", slug="verbali-di-verifica", order=1)
        AssetCategoryDocumentFolder.objects.create(category=nuova, name="Collaudi", slug="collaudi", order=1)
        asset = Asset.objects.create(name="Bombola", asset_type=Asset.TYPE_OTHER, asset_category=vecchia)
        with _workspace_temporary_directory("assets-orfani-") as tmpdir, override_settings(MEDIA_ROOT=tmpdir):
            AssetDocument.objects.create(
                asset=asset,
                category="verbali-di-verifica",
                file=SimpleUploadedFile("v.pdf", b"%PDF-1.4 test", content_type="application/pdf"),
                original_name="v.pdf",
            )
            asset.asset_category = nuova
            asset.save()
            asset.refresh_from_db()
            specs = h._asset_document_folder_specs(asset)
            labels, grouped = h._build_asset_documents_by_category(asset)

        by_code = {s["code"]: s for s in specs}
        self.assertIn("collaudi", by_code)
        self.assertIn("verbali-di-verifica", by_code)
        self.assertEqual(by_code["verbali-di-verifica"]["scope"], "orphan")
        self.assertEqual(by_code["verbali-di-verifica"]["label"], "Verbali di verifica")
        self.assertFalse(by_code["verbali-di-verifica"]["removable"])
        self.assertEqual(len(grouped["verbali-di-verifica"][0]["documents"]), 1)

    def test_nessuna_cartella_rimasta_senza_documenti(self):
        cat = AssetCategory.objects.create(code="cat-x", label="X", is_active=True)
        asset = Asset.objects.create(name="Porta", asset_type=Asset.TYPE_OTHER, asset_category=cat)
        self.assertFalse([s for s in h._asset_document_folder_specs(asset) if s["scope"] == "orphan"])
