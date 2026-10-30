"""Bozza dei form (core/js/hub-form-bozza.js): caricata da base.html, mai dati sensibili."""
from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase

RADICE = Path(__file__).resolve().parent
SCRIPT = RADICE / "static" / "core" / "js" / "hub-form-bozza.js"
BASE = RADICE / "templates" / "core" / "base.html"


class FormBozzaTests(SimpleTestCase):
    def test_caricata_da_base_dopo_flash(self):
        html = BASE.read_text(encoding="utf-8")
        self.assertIn("core/js/hub-form-bozza.js", html)
        self.assertLess(html.index("core/js/hub-flash.js"), html.index("core/js/hub-form-bozza.js"))

    def test_esclude_campi_sensibili_e_usa_solo_la_scheda(self):
        js = SCRIPT.read_text(encoding="utf-8")
        for parola in ("password", "file", "hidden", "csrf", "token"):
            self.assertIn(parola, js)
        self.assertIn("sessionStorage", js)
        self.assertNotIn("localStorage", js)

    def test_ripristino_solo_dopo_errore_o_indietro(self):
        js = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("hub-flash-error", js)
        self.assertIn("back_forward", js)
        self.assertIn("data-hub-no-bozza", js)
