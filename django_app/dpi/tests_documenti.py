"""Raccoglitore documenti DPI (certificati, attestati, manuali d'uso)."""

from __future__ import annotations

import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import CategoriaDPI, DocumentoDPI, ModelloDPI, TipoDPI

User = get_user_model()
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF\n"


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DocumentiDpiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="dpi-doc-admin", password="x", email="a@y.z")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        override = override_settings(ANAGRAFICA_PRIVATE_ROOT=tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        patcher = mock.patch("core.upload_mime.sniff_upload_mime", return_value="application/pdf")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _modello(self, codice="CASCO-1"):
        cat = CategoriaDPI.objects.get_or_create(nome="Caschi", defaults={"icona_emoji": "helmet", "vita_utile_giorni": 365})[0]
        tipo = TipoDPI.objects.get_or_create(categoria=cat, nome="Casco antinfortunistico")[0]
        return ModelloDPI.objects.create(tipo=tipo, codice=codice, nome=f"Casco {codice}")

    def _upload(self, name="manuale.pdf", modello=None):
        modello = modello or getattr(self, "modello", None) or self._modello()
        self.modello = modello
        return self.client.post(reverse("dpi:documenti"), {
            "modello": modello.pk,
            "titolo": "Manuale casco",
            "descrizione": "Modello X",
            "files": SimpleUploadedFile(name, PDF, content_type="application/pdf"),
        })

    def test_gestore_carica_scarica_ed_elimina(self):
        self.client.force_login(self.admin)
        self.assertRedirects(self._upload(), reverse("dpi:documenti"))
        doc = DocumentoDPI.objects.get()
        self.assertEqual(doc.titolo, "Manuale casco")
        self.assertEqual(doc.nome_originale, "manuale.pdf")
        self.assertContains(self.client.get(reverse("dpi:documenti")), "Manuale casco")
        self.assertNotContains(self.client.get(reverse("dpi:documenti"), {"q": "inesistente"}), "Manuale casco")
        response = self.client.get(reverse("dpi:documento_download", args=[doc.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), PDF)
        self.client.post(reverse("dpi:documento_elimina", args=[doc.pk]))
        self.assertFalse(DocumentoDPI.objects.exists())

    def test_utente_non_gestore_consulta_ma_non_carica_ne_elimina(self):
        self.client.force_login(self.admin)
        self._upload()
        doc = DocumentoDPI.objects.get()
        with mock.patch("dpi.views._is_gestore", return_value=False):
            page = self.client.get(reverse("dpi:documenti"))
            self.assertContains(page, "Manuale casco")
            self.assertNotContains(page, "Carica documenti")
            response = self.client.get(reverse("dpi:documento_download", args=[doc.pk]))
            self.assertEqual(response.status_code, 200)
            self._upload("altro.pdf")
            self.client.post(reverse("dpi:documento_elimina", args=[doc.pk]))
        self.assertEqual(DocumentoDPI.objects.count(), 1)

    def test_estensione_non_consentita_rifiutata(self):
        self.client.force_login(self.admin)
        self._upload("script.exe")
        self.assertFalse(DocumentoDPI.objects.exists())

    def test_documento_senza_dpi_rifiutato(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("dpi:documenti"), {
            "files": SimpleUploadedFile("manuale.pdf", PDF, content_type="application/pdf"),
        })
        self.assertFalse(DocumentoDPI.objects.exists())

    def test_documento_legato_al_dpi_e_filtrabile(self):
        self.client.force_login(self.admin)
        altro = self._modello("CASCO-2")
        self._upload("uno.pdf", modello=altro)
        self._upload("due.pdf", modello=self._modello("GUANTO-9"))
        doc = DocumentoDPI.objects.get(nome_originale="uno.pdf")
        self.assertEqual(doc.modello, altro)
        page = self.client.get(reverse("dpi:documenti"), {"modello": altro.pk})
        self.assertContains(page, "uno")
        self.assertNotContains(page, "due.pdf")
