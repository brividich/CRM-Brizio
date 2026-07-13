from django.test import TestCase

from core.table_pdf import _cell_text, render_table_pdf


class CellTextTests(TestCase):
    def test_strips_whitespace(self):
        self.assertEqual(_cell_text("  Mario  "), "Mario")

    def test_none_becomes_empty_string(self):
        self.assertEqual(_cell_text(None), "")

    def test_whitespace_only_collapses_to_empty_string(self):
        self.assertEqual(_cell_text("   "), "")


class RenderTablePdfTests(TestCase):
    def test_cell_normalization_does_not_raise(self):
        data = render_table_pdf(
            title="Normalizzazione celle",
            headers=["Nome", "Note"],
            rows=[["  Mario  ", None]],
        )
        self.assertTrue(data.startswith(b"%PDF"))

    def test_returns_pdf_bytes(self):
        data = render_table_pdf(
            title="Elenco di prova",
            headers=["Nome", "Reparto"],
            rows=[["Mario Bianchi", "Officina"], ["Anna Verdi", "Qualita"]],
            subtitle="Generato il 12-07-2026 · 2 righe",
        )
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 800)

    def test_empty_rows_still_produce_pdf(self):
        data = render_table_pdf(title="Vuoto", headers=["Nome"], rows=[])
        self.assertTrue(data.startswith(b"%PDF"))
