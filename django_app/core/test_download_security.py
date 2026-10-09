from __future__ import annotations

from django.http import HttpResponse
from django.test import SimpleTestCase

from core.download_security import guess_mime_from_name, harden_file_response


class HardenFileResponseTests(SimpleTestCase):
    """Audit A8: i file caricati non vengono mai resi come pagina del portale."""

    def _resp(self, disposition='inline; filename="x"'):
        r = HttpResponse(b"data", content_type="text/html")
        r["Content-Disposition"] = disposition
        return r

    def test_html_is_forced_to_attachment_octet_stream(self):
        r = harden_file_response(self._resp('inline; filename="referto.html"'), "referto.html")
        self.assertEqual(r["Content-Type"], "application/octet-stream")
        self.assertTrue(r["Content-Disposition"].startswith("attachment;"))
        self.assertIn("referto.html", r["Content-Disposition"])
        self.assertIn("sandbox", r["Content-Security-Policy"])
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")

    def test_svg_is_not_inline(self):
        r = harden_file_response(self._resp(), "logo.svg")
        self.assertTrue(r["Content-Disposition"].startswith("attachment"))

    def test_pdf_stays_inline_without_sandbox(self):
        r = harden_file_response(self._resp('inline; filename="referto.pdf"'), "referto.pdf")
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r["Content-Disposition"].startswith("inline;"))
        self.assertNotIn("Content-Security-Policy", r)

    def test_client_declared_mime_is_ignored(self):
        # Il nome dice .png: il Content-Type text/html dichiarato dal client sparisce.
        r = harden_file_response(self._resp(), "foto.PNG")
        self.assertEqual(r["Content-Type"], "image/png")

    def test_inline_false_forces_attachment_for_pdf(self):
        r = harden_file_response(self._resp('attachment; filename="a.pdf"'), "a.pdf", inline=False)
        self.assertTrue(r["Content-Disposition"].startswith("attachment;"))
        self.assertEqual(r["Content-Type"], "application/octet-stream")

    def test_guess_unknown_extension(self):
        self.assertEqual(guess_mime_from_name("senza_estensione"), "application/octet-stream")
