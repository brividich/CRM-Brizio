"""Validazione upload allegati Diario Preposto (Patch 21H upload hardening)."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.upload_mime import UploadMimeValidationError

from .models import SegnalazioneAllegato, SegnalazionePreposto


def _aware_dt(year: int, month: int, day: int, hour: int = 9):
    return timezone.make_aware(datetime(year, month, day, hour, 0), timezone.get_current_timezone())


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DiarioPrepostoUploadValidationTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_superuser(
            username="dp-admin", email="dp-admin@example.com", password="pass12345"
        )
        self.client.force_login(self.user)
        self.segnalazione = SegnalazionePreposto.objects.create(
            titolo="Test",
            data_segnalazione=_aware_dt(2026, 5, 1),
            descrizione="x",
        )

    def test_upload_rejects_disallowed_extension(self):
        # .exe non e' nella whitelist DIARIO_ALLEGATO_EXTENSIONS.
        response = self.client.post(
            reverse("diario_preposto:api_allegato_upload"),
            {
                "segnalazione_id": str(self.segnalazione.pk),
                "file": SimpleUploadedFile("evil.exe", b"MZ\x90\x00", content_type="application/octet-stream"),
            },
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("formato non consentito", payload["error"].lower())
        self.assertEqual(SegnalazioneAllegato.objects.count(), 0)

    def test_upload_rejects_path_traversal_filename(self):
        # Il nome viene "stripato" dal safe_filename: "../../etc/passwd" -> "passwd" senza ext.
        response = self.client.post(
            reverse("diario_preposto:api_allegato_upload"),
            {
                "segnalazione_id": str(self.segnalazione.pk),
                "file": SimpleUploadedFile("../../etc/passwd", b"%PDF-1.4\n", content_type="application/pdf"),
            },
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        # Atteso messaggio "formato non consentito" perche' "passwd" non ha estensione.
        self.assertIn("formato non consentito", payload["error"].lower())
        self.assertEqual(SegnalazioneAllegato.objects.count(), 0)

    def test_upload_rejects_empty_file(self):
        response = self.client.post(
            reverse("diario_preposto:api_allegato_upload"),
            {
                "segnalazione_id": str(self.segnalazione.pk),
                "file": SimpleUploadedFile("vuoto.pdf", b"", content_type="application/pdf"),
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("vuoto", response.json()["error"].lower())
        self.assertEqual(SegnalazioneAllegato.objects.count(), 0)

    def test_upload_accepts_valid_pdf_when_mime_validates(self):
        with patch(
            "diario_preposto.views.validate_extension_and_mime",
            return_value="application/pdf",
        ):
            response = self.client.post(
                reverse("diario_preposto:api_allegato_upload"),
                {
                    "segnalazione_id": str(self.segnalazione.pk),
                    "file": SimpleUploadedFile("doc.pdf", b"%PDF-1.4\n", content_type="application/pdf"),
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(SegnalazioneAllegato.objects.count(), 1)

    def test_upload_rejects_mime_spoofing(self):
        with patch(
            "diario_preposto.views.validate_extension_and_mime",
            side_effect=UploadMimeValidationError("doc.pdf: tipo MIME non consentito (text/html)."),
        ):
            response = self.client.post(
                reverse("diario_preposto:api_allegato_upload"),
                {
                    "segnalazione_id": str(self.segnalazione.pk),
                    "file": SimpleUploadedFile("doc.pdf", b"<html></html>", content_type="application/pdf"),
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("tipo MIME non consentito", response.json()["error"])
        self.assertEqual(SegnalazioneAllegato.objects.count(), 0)
