"""Validazione upload allegati Notizie (Patch 21H upload hardening)."""
from __future__ import annotations

from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from core.upload_mime import UploadMimeValidationError

from .forms import NotiziaAllegatoForm


class NotiziaAllegatoFormUploadValidationTests(SimpleTestCase):
    def _build(self, file, nome_file="allegato"):
        return NotiziaAllegatoForm(
            data={"nome_file": nome_file, "url_esterno": ""},
            files={"file": file},
        )

    def test_form_rejects_disallowed_extension(self):
        f = SimpleUploadedFile("evil.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        form = self._build(f)
        self.assertFalse(form.is_valid())
        # Errore aggregato in __all__ (clean() raise ValidationError).
        all_errors = form.errors.get("__all__", []) + form.non_field_errors()
        self.assertTrue(any("formato non consentito" in e.lower() for e in all_errors))

    def test_form_rejects_empty_file(self):
        f = SimpleUploadedFile("vuoto.pdf", b"", content_type="application/pdf")
        form = self._build(f)
        self.assertFalse(form.is_valid())
        all_errors = form.errors.get("__all__", []) + form.non_field_errors()
        self.assertTrue(any("vuoto" in e.lower() for e in all_errors))

    def test_form_accepts_valid_pdf(self):
        f = SimpleUploadedFile("doc.pdf", b"%PDF-1.4\n%test", content_type="application/pdf")
        with patch(
            "notizie.forms.validate_extension_and_mime",
            return_value="application/pdf",
        ):
            form = self._build(f)
            # Senza istanza padre per via di inline=False, il save fallisce ma la
            # validazione del clean() del campo file deve passare.
            form.is_valid()  # popola cleaned_data
        # Nessun errore relativo al file.
        all_errors = form.errors.get("__all__", []) + form.non_field_errors()
        self.assertFalse(any("formato non consentito" in e.lower() for e in all_errors))
        self.assertFalse(any("vuoto" in e.lower() for e in all_errors))

    def test_form_rejects_mime_spoofing(self):
        f = SimpleUploadedFile("doc.pdf", b"%PDF-1.4", content_type="application/pdf")
        with patch(
            "notizie.forms.validate_extension_and_mime",
            side_effect=UploadMimeValidationError("doc.pdf: tipo MIME non consentito (text/html)."),
        ):
            form = self._build(f)
            self.assertFalse(form.is_valid())
            all_errors = form.errors.get("__all__", []) + form.non_field_errors()
            self.assertTrue(any("tipo MIME non consentito" in e for e in all_errors))

    def test_form_strips_path_traversal_in_default_name(self):
        f = SimpleUploadedFile("../../etc/passwd.pdf", b"%PDF-1.4", content_type="application/pdf")
        with patch(
            "notizie.forms.validate_extension_and_mime",
            return_value="application/pdf",
        ):
            form = NotiziaAllegatoForm(
                data={"nome_file": "", "url_esterno": ""},
                files={"file": f},
            )
            form.is_valid()
        # Il nome di default e' derivato dal safe_filename, non contiene "/" o "..".
        cleaned_name = form.cleaned_data.get("nome_file") or ""
        self.assertNotIn("..", cleaned_name)
        self.assertNotIn("/", cleaned_name)
        self.assertNotIn("\\", cleaned_name)
