"""Validazione upload TaskAttachmentForm (Patch 21H upload hardening)."""
from __future__ import annotations

from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from core.upload_mime import UploadMimeValidationError

from .forms import TaskAttachmentForm


def _noop_post_clean(self):
    """Bypass _post_clean: questi test verificano solo la validazione MIME/upload,
    non l'assegnazione delle FK task/project che richiede un DB reale."""


class TaskAttachmentFormUploadValidationTests(SimpleTestCase):
    def test_rejects_disallowed_extension(self):
        f = SimpleUploadedFile("evil.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        with patch.object(TaskAttachmentForm, "_post_clean", _noop_post_clean):
            form = TaskAttachmentForm(
                data={"attach_to": TaskAttachmentForm.TARGET_TASK},
                files={"file": f},
            )
            valid = form.is_valid()
        self.assertFalse(valid)
        errors_text = " ".join(
            list(form.errors.get("file", []))
            + list(form.errors.get("__all__", []))
        )
        self.assertIn("formato non consentito", errors_text.lower())

    def test_rejects_empty_file(self):
        f = SimpleUploadedFile("doc.pdf", b"", content_type="application/pdf")
        with patch.object(TaskAttachmentForm, "_post_clean", _noop_post_clean):
            form = TaskAttachmentForm(
                data={"attach_to": TaskAttachmentForm.TARGET_TASK},
                files={"file": f},
            )
            valid = form.is_valid()
        self.assertFalse(valid)
        errors_text = " ".join(
            list(form.errors.get("file", []))
            + list(form.errors.get("__all__", []))
        )
        self.assertIn("vuoto", errors_text.lower())

    def test_rejects_mime_spoofing(self):
        f = SimpleUploadedFile("doc.pdf", b"%PDF-1.4", content_type="application/pdf")
        with patch("tasks.forms.validate_extension_and_mime",
                   side_effect=UploadMimeValidationError("doc.pdf: tipo MIME non consentito (text/html).")), \
             patch.object(TaskAttachmentForm, "_post_clean", _noop_post_clean):
            form = TaskAttachmentForm(
                data={"attach_to": TaskAttachmentForm.TARGET_TASK},
                files={"file": f},
            )
            valid = form.is_valid()
        self.assertFalse(valid)
        errors_text = " ".join(
            list(form.errors.get("file", []))
            + list(form.errors.get("__all__", []))
        )
        self.assertIn("tipo MIME non consentito", errors_text)

    def test_accepts_valid_pdf(self):
        f = SimpleUploadedFile("doc.pdf", b"%PDF-1.4", content_type="application/pdf")
        with patch("tasks.forms.validate_extension_and_mime", return_value="application/pdf"), \
             patch.object(TaskAttachmentForm, "_post_clean", _noop_post_clean):
            form = TaskAttachmentForm(
                data={"attach_to": TaskAttachmentForm.TARGET_TASK},
                files={"file": f},
            )
            valid = form.is_valid()
        self.assertTrue(valid, msg=form.errors)
