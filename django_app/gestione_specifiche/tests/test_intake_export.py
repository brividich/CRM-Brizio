"""Test delle funzioni pure di intake_export (mappatura listoni → template F8)."""
from datetime import datetime

from django.test import SimpleTestCase

from gestione_specifiche.intake_export import mappa_cliente, mappa_spte, serial_to_iso


class SerialToIsoTest(SimpleTestCase):
    def test_serial_numerico(self):
        # 43137 = 2018-02-06 (verificato sui dati reali BAC5777)
        self.assertEqual(serial_to_iso(43137.0), "2018-02-06")
        self.assertEqual(serial_to_iso("43137"), "2018-02-06")

    def test_datetime_e_vuoti(self):
        self.assertEqual(serial_to_iso(datetime(2020, 1, 2, 15, 0)), "2020-01-02")
        for v in ("", None, "N/A", 0, -5):
            self.assertEqual(serial_to_iso(v), "")


class MappaSpteTest(SimpleTestCase):
    def _rec(self, **kw):
        base = {"cdocm": "BAC5777", "crevi_ddocm": "G", "fvali": "",
                "tdocm": "WASH PRIMER", "tspec_ddocm": "", "dregi_ddocm": 43137.0,
                "daggi_ddocm": "", "tform_ddocm": r"\\novisrv\Area Produzione\SPECIFICHE\x.pdf"}
        base.update(kw)
        return base

    def test_riga_valida(self):
        r = mappa_spte(self._rec())
        self.assertIsNotNone(r["riga"])
        self.assertEqual(r["riga"]["codice"], "BAC5777")
        self.assertEqual(r["riga"]["revisione"], "G")
        self.assertEqual(r["riga"]["titolo"], "WASH PRIMER")
        self.assertEqual(r["riga"]["fonte"], "generica")
        self.assertEqual(r["riga"]["tipo"], "specifica")
        self.assertEqual(r["riga"]["stato"], "in_validita")
        self.assertEqual(r["riga"]["data_inserimento"], "2018-02-06")
        self.assertTrue(r["path"].startswith("\\\\"))

    def test_codice_vuoto_o_zero_scartato(self):
        self.assertIsNone(mappa_spte(self._rec(cdocm=""))["riga"])
        self.assertIsNone(mappa_spte(self._rec(cdocm="0"))["riga"])

    def test_fvali_escluso_di_default_ma_includibile(self):
        self.assertIsNone(mappa_spte(self._rec(fvali="401768.0"))["riga"])
        r = mappa_spte(self._rec(fvali="401768.0"), escludi_fvali=False)
        self.assertIsNotNone(r["riga"])

    def test_titolo_fallback_e_rev_default(self):
        r = mappa_spte(self._rec(tdocm="", tspec_ddocm="", crevi_ddocm=""))
        self.assertEqual(r["riga"]["titolo"], "BAC5777")  # fallback al codice
        self.assertEqual(r["riga"]["revisione"], "0")      # default

    def test_path_non_unc_scartato(self):
        r = mappa_spte(self._rec(tform_ddocm="C:/locale/x.pdf"))
        self.assertEqual(r["path"], "")  # solo UNC


class MappaClienteTest(SimpleTestCase):
    def _rec(self, **kw):
        base = {"cliente": "Ferrari", "codice": "SPEC-1", "revisione": "A",
                "dataric": "", "sosp": "NO", "sup": ""}
        base.update(kw)
        return base

    def test_riga_valida_titolo_da_codice(self):
        r = mappa_cliente(self._rec())
        self.assertIsNotNone(r["riga"])
        self.assertEqual(r["riga"]["fonte"], "cliente")
        self.assertEqual(r["riga"]["cliente"], "Ferrari")
        self.assertEqual(r["riga"]["titolo"], "SPEC-1")  # Registro senza titolo → codice

    def test_sospesa_o_superata_scartata(self):
        self.assertIsNone(mappa_cliente(self._rec(sosp="SI"))["riga"])
        self.assertIsNone(mappa_cliente(self._rec(sup="S"))["riga"])

    def test_rev_na_e_dataric_na(self):
        r = mappa_cliente(self._rec(revisione="N/A", dataric="N/A"))
        self.assertEqual(r["riga"]["revisione"], "0")
        self.assertEqual(r["riga"]["data_inserimento"], "")

    def test_codice_vuoto_scartato(self):
        self.assertIsNone(mappa_cliente(self._rec(codice=""))["riga"])
