import csv
import io

from django.test import SimpleTestCase

from core.csv_export import csv_safe, safe_csv_writer


class CsvSafeTests(SimpleTestCase):
    def test_formula_prefixes_are_neutralized(self):
        for dangerous in (
            '=HYPERLINK("http://evil","apri")',
            "=1+1",
            "@SUM(A1:A9)",
            "\t=cmd",
            "\r=cmd",
        ):
            self.assertEqual(csv_safe(dangerous), "'" + dangerous, dangerous)

    def test_legitimate_numbers_are_not_touched(self):
        for legit in ("-12,50", "-12.50", "+3", "1234", "0,5"):
            self.assertEqual(csv_safe(legit), legit, legit)

    def test_plain_text_is_not_touched(self):
        self.assertEqual(csv_safe("Mario Rossi"), "Mario Rossi")
        self.assertEqual(csv_safe(""), "")
        self.assertEqual(csv_safe(None), None)
        self.assertEqual(csv_safe(42), 42)

    def test_negative_text_is_neutralized(self):
        # "-" seguito da testo non è un numero: va trattato come potenziale formula.
        self.assertEqual(csv_safe("-2+3+cmd|' /C calc'!A0"), "'-2+3+cmd|' /C calc'!A0")


class SafeCsvWriterTests(SimpleTestCase):
    def _roundtrip(self, rows):
        buf = io.StringIO()
        writer = safe_csv_writer(buf)
        writer.writerows(rows)
        buf.seek(0)
        return list(csv.reader(buf))

    def test_writer_sanitizes_cells(self):
        out = self._roundtrip([["Nome", "Note"], ["Mario", '=HYPERLINK("http://evil","x")']])
        self.assertEqual(out[0], ["Nome", "Note"])
        self.assertEqual(out[1], ["Mario", '\'=HYPERLINK("http://evil","x")'])

    def test_writer_preserves_legitimate_values(self):
        out = self._roundtrip([["Saldo", "Testo"], ["-12,50", "Nessuna nota"]])
        self.assertEqual(out[1], ["-12,50", "Nessuna nota"])


class ExportRowsResponseCsvTests(SimpleTestCase):
    """`core.exporting.export_rows_response` è la via comune di più moduli: il suo
    ramo CSV non deve riemettere formule vive."""

    def _rows_from(self, response):
        # NB: `HttpResponse` con charset utf-8-sig antepone il BOM a OGNI write
        # (comportamento preesistente di `export_rows_response`): qui lo si ignora.
        body = b"".join(response).decode("utf-8").replace("﻿", "")
        return list(csv.reader(io.StringIO(body)))

    def test_csv_branch_neutralizes_formulas(self):
        from core.exporting import export_rows_response

        response = export_rows_response(
            rows=[{"nome": "Mario", "note": '=HYPERLINK("http://evil","apri")'}],
            columns=[("Nome", "nome"), ("Note", "note")],
            filename="export.csv",
            fmt="csv",
        )
        rows = self._rows_from(response)
        self.assertEqual(rows[0], ["Nome", "Note"])
        self.assertEqual(rows[1], ["Mario", '\'=HYPERLINK("http://evil","apri")'])

    def test_csv_branch_keeps_legitimate_values(self):
        from core.exporting import export_rows_response

        response = export_rows_response(
            rows=[{"nome": "Anna", "saldo": "-12,50"}],
            columns=[("Nome", "nome"), ("Saldo", "saldo")],
            filename="export.csv",
            fmt="csv",
        )
        self.assertEqual(self._rows_from(response)[1], ["Anna", "-12,50"])
