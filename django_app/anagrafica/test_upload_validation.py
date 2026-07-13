"""Validazione upload FornitoreDocumentoForm (Patch 21H upload hardening)."""
from __future__ import annotations

from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from core.upload_mime import UploadMimeValidationError

from fornitori.forms import FornitoreDocumentoForm


class FornitoreDocumentoFormUploadValidationTests(SimpleTestCase):
    def _form(self, file):
        return FornitoreDocumentoForm(
            # "tipo" deve essere una delle TIPO_CHOICES di FornitoreDocumento
            # (CONTRATTO/OFFERTA/CERTIFICAZIONE/VISURA/ALTRO): "DURC" non lo e' piu'.
            data={"nome": "DURC", "tipo": "CERTIFICAZIONE", "note": ""},
            files={"file": file},
        )

    def test_rejects_disallowed_extension(self):
        f = SimpleUploadedFile("durc.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        form = self._form(f)
        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)
        self.assertIn("formato non consentito", " ".join(form.errors["file"]).lower())

    def test_rejects_empty_file(self):
        f = SimpleUploadedFile("durc.pdf", b"", content_type="application/pdf")
        form = self._form(f)
        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)
        self.assertIn("vuoto", " ".join(form.errors["file"]).lower())

    def test_rejects_path_traversal_filename(self):
        f = SimpleUploadedFile("../../etc/passwd", b"%PDF-1.4", content_type="application/pdf")
        form = self._form(f)
        self.assertFalse(form.is_valid())
        # "../../etc/passwd" -> safe -> "passwd" senza estensione -> formato non consentito.
        self.assertIn("formato non consentito", " ".join(form.errors.get("file", [])).lower())

    def test_accepts_valid_pdf(self):
        f = SimpleUploadedFile("durc.pdf", b"%PDF-1.4", content_type="application/pdf")
        with patch(
            "fornitori.forms.validate_extension_and_mime",
            return_value="application/pdf",
        ):
            form = self._form(f)
            self.assertTrue(form.is_valid(), msg=form.errors)
