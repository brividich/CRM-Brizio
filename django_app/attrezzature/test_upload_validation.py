"""Validazione upload ImportUploadForm attrezzature (Patch 21H upload hardening)."""
from __future__ import annotations

from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from core.upload_mime import UploadMimeValidationError

from .forms import ImportUploadForm


class ImportUploadFormValidationTests(SimpleTestCase):
    def _form(self, file):
        return ImportUploadForm(data={}, files={"file": file})

    def test_rejects_disallowed_extension(self):
        f = SimpleUploadedFile("import.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        form = self._form(f)
        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)
        self.assertIn("formato non consentito", " ".join(form.errors["file"]).lower())

    def test_rejects_empty_file(self):
        f = SimpleUploadedFile("import.xlsx", b"", content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        form = self._form(f)
        self.assertFalse(form.is_valid())
        self.assertIn("vuoto", " ".join(form.errors["file"]).lower())

    def test_rejects_mime_spoofing(self):
        f = SimpleUploadedFile("import.xlsx", b"<html>", content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with patch(
            "attrezzature.forms.validate_extension_and_mime",
            side_effect=UploadMimeValidationError("import.xlsx: tipo MIME non consentito (text/html)."),
        ):
            form = self._form(f)
            self.assertFalse(form.is_valid())
            self.assertIn("tipo MIME non consentito", " ".join(form.errors.get("file", [])))

    def test_accepts_valid_xlsx(self):
        f = SimpleUploadedFile("import.xlsx", b"PK\x03\x04rest", content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with patch(
            "attrezzature.forms.validate_extension_and_mime",
            return_value="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ):
            form = self._form(f)
            self.assertTrue(form.is_valid(), msg=form.errors)
