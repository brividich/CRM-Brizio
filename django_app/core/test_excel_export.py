from __future__ import annotations

from io import BytesIO

from django.test import TestCase

from openpyxl import load_workbook

from core.excel_export import build_xlsx_bytes


class ExcelExportUtilTests(TestCase):
    # TestCase (non SimpleTestCase): con `title` valorizzato build_xlsx_bytes
    # legge il branding via PdfTheme.from_branding() (query DB SiteConfig).
    def test_build_xlsx_bytes_valid(self):
        from openpyxl import load_workbook

        from core.excel_export import build_xlsx_bytes

        data = build_xlsx_bytes(
            columns=["A", "B"], rows=[["x", 1], ["y", 2]], title="Titolo", sheet_title="Foglio"
        )
        self.assertEqual(data[:2], b"PK")  # firma xlsx (zip)

        ws = load_workbook(BytesIO(data)).active
        self.assertEqual(ws.title, "Foglio")
        # Con `title` valorizzato il blocco intestazione HUB sposta titolo/header:
        # titolo in A3, header tabella in riga 7 (vedi XlsxDocumentHeaderTests).
        self.assertEqual(ws.cell(row=3, column=1).value, "Titolo")
        self.assertEqual(ws.cell(row=7, column=1).value, "A")
        self.assertEqual(ws.cell(row=8, column=2).value, 1)

    def test_make_xlsx_response(self):
        from core.excel_export import make_xlsx_response

        resp = make_xlsx_response(filename='c"on.xlsx', columns=["A"], rows=[["x"]])
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])
        self.assertIn('filename="con.xlsx"', resp["Content-Disposition"])  # virgolette interne ripulite
        self.assertEqual(resp.content[:2], b"PK")


class XlsxDocumentHeaderTests(TestCase):
    def test_header_block_contains_title_subtitle_and_filters(self):
        data = build_xlsx_bytes(
            columns=["Nominativo", "Reparto"],
            rows=[["Mario Bianchi", "Officina"]],
            title="Elenco dipendenti",
            subtitle="Generato il 12-07-2026 da Mario Rossi",
            filters_label="Filtri: Reparto = Officina · 1 righe",
        )
        ws = load_workbook(BytesIO(data)).active
        self.assertEqual(ws["A3"].value, "Elenco dipendenti")
        self.assertEqual(ws["A4"].value, "Generato il 12-07-2026 da Mario Rossi")
        self.assertEqual(ws["A5"].value, "Filtri: Reparto = Officina · 1 righe")
        self.assertEqual(ws["A7"].value, "Nominativo")
        self.assertEqual(ws["A8"].value, "Mario Bianchi")
        self.assertEqual(ws.freeze_panes, "A8")

    def test_without_title_header_stays_on_first_row(self):
        data = build_xlsx_bytes(columns=["Nominativo"], rows=[["Mario Bianchi"]])
        ws = load_workbook(BytesIO(data)).active
        self.assertEqual(ws["A1"].value, "Nominativo")
        self.assertEqual(ws["A2"].value, "Mario Bianchi")
