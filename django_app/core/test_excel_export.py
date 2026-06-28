from __future__ import annotations

from io import BytesIO

from django.test import SimpleTestCase


class ExcelExportUtilTests(SimpleTestCase):
    def test_build_xlsx_bytes_valid(self):
        from openpyxl import load_workbook

        from core.excel_export import build_xlsx_bytes

        data = build_xlsx_bytes(
            columns=["A", "B"], rows=[["x", 1], ["y", 2]], title="Titolo", sheet_title="Foglio"
        )
        self.assertEqual(data[:2], b"PK")  # firma xlsx (zip)

        ws = load_workbook(BytesIO(data)).active
        self.assertEqual(ws.title, "Foglio")
        self.assertEqual(ws.cell(row=1, column=1).value, "Titolo")  # titolo in cima
        self.assertEqual(ws.cell(row=3, column=1).value, "A")        # intestazione (riga 3 con titolo)
        self.assertEqual(ws.cell(row=4, column=2).value, 1)          # primo dato

    def test_make_xlsx_response(self):
        from core.excel_export import make_xlsx_response

        resp = make_xlsx_response(filename='c"on.xlsx', columns=["A"], rows=[["x"]])
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])
        self.assertIn('filename="con.xlsx"', resp["Content-Disposition"])  # virgolette interne ripulite
        self.assertEqual(resp.content[:2], b"PK")
