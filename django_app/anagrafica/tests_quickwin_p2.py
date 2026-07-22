"""Blocco 2 — quick-win P2. 1.15: matricola senza zeri di padding (display-only)."""
from __future__ import annotations

from django.test import SimpleTestCase

from anagrafica.templatetags.anagrafica_extras import matricola_fmt


class MatricolaFmtTests(SimpleTestCase):
    def test_numerica_strippa_zeri(self):
        self.assertEqual(matricola_fmt("0001"), "1")
        self.assertEqual(matricola_fmt("120"), "120")

    def test_tutti_zeri_resta_zero(self):
        self.assertEqual(matricola_fmt("000"), "0")

    def test_alfanumerica_invariata(self):
        self.assertEqual(matricola_fmt("CNO 0001"), "CNO 0001")
        self.assertEqual(matricola_fmt("A007"), "A007")

    def test_vuota_o_none(self):
        self.assertEqual(matricola_fmt(""), "")
        self.assertEqual(matricola_fmt(None), "")
