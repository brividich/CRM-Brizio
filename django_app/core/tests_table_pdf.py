from django.test import TestCase

from core.table_pdf import render_table_pdf


class RenderTablePdfTests(TestCase):
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
