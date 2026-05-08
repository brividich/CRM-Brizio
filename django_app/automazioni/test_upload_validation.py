"""Validazione upload package/flow Automazioni (Patch 21H upload hardening)."""
from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from .forms import AutomationPackageUploadForm, PowerAutomateFlowUploadForm


class AutomationPackageUploadValidationTests(SimpleTestCase):
    def _form(self, file):
        return AutomationPackageUploadForm(data={}, files={"package_file": file})

    def test_rejects_disallowed_extension(self):
        f = SimpleUploadedFile("evil.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        form = self._form(f)
        self.assertFalse(form.is_valid())
        self.assertIn("package_file", form.errors)

    def test_rejects_empty_file(self):
        f = SimpleUploadedFile("pkg.json", b"", content_type="application/json")
        form = self._form(f)
        self.assertFalse(form.is_valid())
        self.assertIn("vuoto", " ".join(form.errors.get("package_file", [])).lower())

    def test_rejects_path_traversal(self):
        f = SimpleUploadedFile("../../etc/passwd", b"{}", content_type="application/json")
        form = self._form(f)
        self.assertFalse(form.is_valid())
        # Diventa "passwd" senza ext valida.
        self.assertIn("package_file", form.errors)

    def test_accepts_valid_json(self):
        f = SimpleUploadedFile("pkg.automation_package.json", b"{}", content_type="application/json")
        form = self._form(f)
        self.assertTrue(form.is_valid(), msg=form.errors)


class PowerAutomateFlowUploadValidationTests(SimpleTestCase):
    def _form(self, file):
        return PowerAutomateFlowUploadForm(data={}, files={"flow_file": file})

    def test_rejects_disallowed_extension(self):
        f = SimpleUploadedFile("flow.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        form = self._form(f)
        self.assertFalse(form.is_valid())
        self.assertIn("flow_file", form.errors)

    def test_rejects_empty_file(self):
        f = SimpleUploadedFile("flow.zip", b"", content_type="application/zip")
        form = self._form(f)
        self.assertFalse(form.is_valid())
        self.assertIn("vuoto", " ".join(form.errors.get("flow_file", [])).lower())

    def test_accepts_valid_zip(self):
        f = SimpleUploadedFile("flow.zip", b"PK\x03\x04rest", content_type="application/zip")
        form = self._form(f)
        self.assertTrue(form.is_valid(), msg=form.errors)
