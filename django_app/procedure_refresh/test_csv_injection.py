from __future__ import annotations

from django.test import SimpleTestCase

from core.csv_export import csv_safe


class CsvInjectionCellTests(SimpleTestCase):
    """SEC: le celle di testo dell'export CSV (es. user_note, input non privilegiato)
    che iniziano con un carattere di formula vanno neutralizzate con un apostrofo.

    La sanificazione vive in `core.csv_export` (sede unica, condivisa da tutti gli
    export CSV del portale); qui si verifica la politica su cui l'export di
    procedure_refresh fa affidamento.
    """

    def test_formula_chars_are_prefixed(self):
        for danger in ("=", "+", "-", "@", "\t", "\r"):
            self.assertEqual(csv_safe(danger + "cmd"), "'" + danger + "cmd")

    def test_normal_text_unchanged(self):
        self.assertEqual(csv_safe("Mario Rossi"), "Mario Rossi")
        self.assertEqual(csv_safe("note: ok"), "note: ok")

    def test_non_string_unchanged(self):
        self.assertEqual(csv_safe(42), 42)
        self.assertEqual(csv_safe(None), None)

    def test_empty_string_unchanged(self):
        self.assertEqual(csv_safe(""), "")

    def test_export_view_uses_shared_safe_writer(self):
        # Regressione: l'export non deve tornare a `csv.writer` grezzo.
        from procedure_refresh import views

        self.assertIs(views.safe_csv_writer, __import__("core.csv_export", fromlist=["x"]).safe_csv_writer)
