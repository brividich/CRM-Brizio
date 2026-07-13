from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase

from anagrafica.models import Fornitore, FornitoreDocumento
from anagrafica.storage import PrivateAnagraficaStorage
from fornitori import views


class FornitoreDocumentoDownloadTests(TestCase):
    """SEC: i documenti fornitori non sono più serviti da /media pubblico ma da
    storage privato fuori webroot, attraverso una view protetta."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("forn_admin", "a@example.com", "pwd12345")
        self.fornitore = Fornitore.objects.create(ragione_sociale="ACME SpA")
        self.doc = FornitoreDocumento.objects.create(
            fornitore=self.fornitore,
            nome="Contratto riservato",
            file=SimpleUploadedFile("contratto.pdf", b"%PDF-1.4 contenuto riservato"),
        )
        self.factory = RequestFactory()

    def tearDown(self):
        try:
            if self.doc.file and self.doc.file.name:
                self.doc.file.storage.delete(self.doc.file.name)
        except Exception:
            pass

    def test_storage_is_private_no_public_url(self):
        self.assertIsInstance(self.doc.file.storage, PrivateAnagraficaStorage)
        # Nessun URL pubblico: lo storage privato non espone .url
        with self.assertRaises(NotImplementedError):
            _ = self.doc.file.url
        # Il file risiede sotto la root privata, non sotto MEDIA pubblica
        self.assertIn("media_private", str(self.doc.file.storage.location).replace("\\", "/").lower())

    def test_superuser_download_streams_decrypted_content(self):
        req = self.factory.get("/fornitori/x/documenti/x/download/")
        req.user = self.admin
        with patch("fornitori.views.log_action"):
            resp = views.fornitore_documento_download(req, self.fornitore.id, self.doc.id)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")
        body = b"".join(resp.streaming_content)
        self.assertEqual(body, b"%PDF-1.4 contenuto riservato")

    def test_download_requires_authentication(self):
        from types import SimpleNamespace
        req = self.factory.get("/fornitori/x/documenti/x/download/")
        req.user = SimpleNamespace(is_authenticated=False)
        resp = views.fornitore_documento_download(req, self.fornitore.id, self.doc.id)
        # @login_required → redirect al login (302), nessuno streaming del file
        self.assertEqual(resp.status_code, 302)
