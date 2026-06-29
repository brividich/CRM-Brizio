from __future__ import annotations

from django.test import SimpleTestCase

from procedure_refresh.views import _csv_cell


class CsvInjectionCellTests(SimpleTestCase):
    """SEC: le celle di testo dell'export CSV (es. user_note, input non privilegiato)
    che iniziano con un carattere di formula vanno neutralizzate con un apostrofo."""

    def test_formula_chars_are_prefixed(self):
        for danger in ("=", "+", "-", "@", "\t", "\r"):
            self.assertEqual(_csv_cell(danger + "cmd"), "'" + danger + "cmd")

    def test_normal_text_unchanged(self):
        self.assertEqual(_csv_cell("Mario Rossi"), "Mario Rossi")
        self.assertEqual(_csv_cell("note: ok"), "note: ok")

    def test_non_string_unchanged(self):
        self.assertEqual(_csv_cell(42), 42)
        self.assertEqual(_csv_cell(None), None)

    def test_empty_string_unchanged(self):
        self.assertEqual(_csv_cell(""), "")
