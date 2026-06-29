from __future__ import annotations

from django.test import SimpleTestCase

from anomalie.views import _validate_report_template

# Gruppo di placeholder richiesti (un template valido deve contenerne uno completo).
_VALID_BODY = (
    "<html><body>"
    "<h1>Report OP {{ op.id }}</h1>"
    "<p>{{ anomalia.seriale }} - {{ anomalia.descrizione }}</p>"
    "</body></html>"
)


class ReportTemplateValidationTests(SimpleTestCase):
    """SEC: il template OP caricato viene reso col motore Django e servito a chi apre
    il report. La validazione deve bloccare gli script inline, gli handler di evento
    e gli URI javascript:/data: (stored XSS verso utenti più privilegiati)."""

    def _errs(self, body: str):
        return _validate_report_template(body.encode("utf-8"), "report.html")

    def test_clean_template_passes(self):
        self.assertEqual(self._errs(_VALID_BODY), [])

    def test_inline_script_rejected(self):
        errs = self._errs(_VALID_BODY + "<script>alert(1)</script>")
        self.assertTrue(any("script" in e.lower() for e in errs))

    def test_event_handler_rejected(self):
        errs = self._errs(_VALID_BODY + '<img src=x onerror="alert(1)">')
        self.assertTrue(any("evento" in e.lower() or "onclick" in e.lower() for e in errs))

    def test_javascript_uri_rejected(self):
        errs = self._errs(_VALID_BODY + "<a href=\"javascript:alert(1)\">x</a>")
        self.assertTrue(any("javascript" in e.lower() for e in errs))

    def test_external_script_still_rejected(self):
        errs = self._errs(_VALID_BODY + '<script src="https://evil/x.js"></script>')
        self.assertTrue(any("script" in e.lower() for e in errs))
