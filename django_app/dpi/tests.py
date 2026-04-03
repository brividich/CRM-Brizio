from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import FileField, ImageField
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.upload_mime import UploadMimeValidationError
from dpi.models import CategoriaDPI
from dpi.views import DPI_MIME_POLICY_FIELDS


def _reset_test_dir(name: str) -> Path:
    root = Path(__file__).resolve().parents[2] / ".tmp_tests"
    target = root / name
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    return target


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DpiCategoryMimeValidationTests(TestCase):
    def setUp(self):
        super().setUp()
        self._test_dir = _reset_test_dir("dpi_mime_validation")
        self._media_root = self._test_dir / "media"
        self._upload_tmp = self._test_dir / "upload_tmp"
        self._media_root.mkdir(parents=True, exist_ok=True)
        self._upload_tmp.mkdir(parents=True, exist_ok=True)
        self._media_override = override_settings(
            MEDIA_ROOT=self._media_root,
            FILE_UPLOAD_TEMP_DIR=str(self._upload_tmp),
        )
        self._media_override.enable()
        self.addCleanup(self._media_override.disable)
        self.addCleanup(lambda: shutil.rmtree(self._test_dir, ignore_errors=True))
        self.user = get_user_model().objects.create_superuser(
            username="dpi-admin",
            email="dpi-admin@example.com",
            password="pass12345",
        )
        self.client.force_login(self.user)
        self.url = reverse("dpi:categoria_nuova")

    def _base_payload(self) -> dict:
        return {
            "nome": "Guanti anti-taglio",
            "descrizione": "Categoria test",
            "icona_emoji": "G",
            "vita_utile_giorni": "120",
            "unita_misura": "pz",
            "scorta_minima": "2",
            "is_active": "on",
            "order_index": "10",
        }

    def test_categoria_upload_accepts_valid_image_when_mime_is_valid(self):
        with patch("dpi.views.validate_extension_and_mime", return_value="image/png"):
            response = self.client.post(
                self.url,
                {
                    **self._base_payload(),
                    "immagine": SimpleUploadedFile("categoria.png", b"\x89PNG\r\n\x1a\n", content_type="image/png"),
                },
            )

        self.assertEqual(response.status_code, 302)
        categoria = CategoriaDPI.objects.get(nome="Guanti anti-taglio")
        self.assertTrue(bool(categoria.immagine))

    def test_categoria_upload_rejects_spoofed_mime(self):
        with patch(
            "dpi.views.validate_extension_and_mime",
            side_effect=UploadMimeValidationError("categoria.png: tipo MIME non consentito (application/x-msdownload)."),
        ) as mock_validate:
            response = self.client.post(
                self.url,
                {
                    **self._base_payload(),
                    "immagine": SimpleUploadedFile("categoria.png", b"MZ...", content_type="image/png"),
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(mock_validate.called)
        self.assertEqual(CategoriaDPI.objects.count(), 0)

    def test_categoria_upload_fails_closed_when_mime_engine_is_unavailable(self):
        with patch(
            "dpi.views.validate_extension_and_mime",
            side_effect=UploadMimeValidationError("Validazione MIME non disponibile sul server. Upload bloccato."),
        ) as mock_validate:
            response = self.client.post(
                self.url,
                {
                    **self._base_payload(),
                    "immagine": SimpleUploadedFile("categoria.png", b"\x89PNG\r\n\x1a\n", content_type="image/png"),
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(mock_validate.called)
        self.assertEqual(CategoriaDPI.objects.count(), 0)


class DpiMimePolicyCoverageTests(SimpleTestCase):
    def test_all_dpi_file_and_image_fields_are_covered_by_mime_policy(self):
        app_config = apps.get_app_config("dpi")
        discovered_fields: set[str] = set()
        for model in app_config.get_models():
            for field in model._meta.get_fields():
                if not isinstance(field, (FileField, ImageField)):
                    continue
                discovered_fields.add(f"{model.__name__}.{field.name}")

        self.assertEqual(discovered_fields, set(DPI_MIME_POLICY_FIELDS))
