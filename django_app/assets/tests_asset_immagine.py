"""Immagine dell'asset mostrata come icona della scheda: caricamento, permessi, rimozione."""
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset
from assets.tests import _valid_png_upload, _workspace_temporary_directory


class AssetImmagineTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("img-demo", "img@example.test", "synthetic-only")
        self.asset = Asset.objects.create(asset_tag="IMG-DEMO", name="Stampante demo", asset_type=Asset.TYPE_STAMPANTE)
        self.url = reverse("assets:asset_image_upload", args=[self.asset.id])
        self.client.force_login(self.user)

    def test_upload_shows_image_as_icon_and_replace_deletes_old_file(self):
        with _workspace_temporary_directory("assets-immagine-") as tmpdir, override_settings(MEDIA_ROOT=Path(tmpdir)):
            response = self.client.post(self.url, {"immagine": _valid_png_upload("foto.png")})
            self.assertRedirects(response, reverse("assets:asset_view", args=[self.asset.id]), fetch_redirect_response=False)
            self.asset.refresh_from_db()
            first = Path(self.asset.immagine.path)
            self.assertTrue(first.exists())
            page = self.client.get(reverse("assets:asset_view", args=[self.asset.id]))
            self.assertContains(page, 'class="af-asset-mark af-asset-mark--img"')
            self.assertContains(page, self.asset.immagine.url)

            self.client.post(self.url, {"immagine": _valid_png_upload("nuova.png")})
            self.asset.refresh_from_db()
            self.assertTrue(Path(self.asset.immagine.path).exists())
            self.assertFalse(first.exists())

            self.client.post(self.url, {"clear_immagine": "1"})
            self.asset.refresh_from_db()
            self.assertFalse(self.asset.immagine)
            page = self.client.get(reverse("assets:asset_view", args=[self.asset.id]))
            self.assertNotContains(page, 'class="af-asset-mark af-asset-mark--img"')
            self.assertContains(page, "+ Immagine")

    def test_rejects_non_images(self):
        with _workspace_temporary_directory("assets-immagine-") as tmpdir, override_settings(MEDIA_ROOT=Path(tmpdir)):
            finto = SimpleUploadedFile("foto.png", b"non sono un'immagine", content_type="image/png")
            self.client.post(self.url, {"immagine": finto})
            pdf = SimpleUploadedFile("doc.pdf", b"%PDF-1.4", content_type="application/pdf")
            self.client.post(self.url, {"immagine": pdf})
        self.asset.refresh_from_db()
        self.assertFalse(self.asset.immagine)

    def test_without_edit_permission_upload_is_forbidden_and_control_hidden(self):
        edit_url = reverse("assets:asset_edit", args=[self.asset.id])

        def acl(path, **_kw):
            return not path.startswith(edit_url)

        with patch("core.middleware.acl_allows_path", side_effect=acl):
            response = self.client.post(self.url, {"immagine": _valid_png_upload("foto.png")})
            self.assertEqual(response.status_code, 403)
            page = self.client.get(reverse("assets:asset_view", args=[self.asset.id]))
        self.assertNotContains(page, "+ Immagine")
        self.asset.refresh_from_db()
        self.assertFalse(self.asset.immagine)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)
