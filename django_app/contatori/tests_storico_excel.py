"""Import dello storico Excel dei contatori. Dati sintetici."""
from datetime import date
from io import StringIO
from pathlib import Path
import tempfile

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from openpyxl import Workbook

from . import storico_excel
from .models import LetturaContatori, Macchina

INTESTAZIONE = ("A4 BN", "A3 BN", "A4 C", "A3 C", "MATRICOLA", "TOTALE")


class EtichettaTrimestreTests(SimpleTestCase):
    def test_formati_liberi(self):
        self.assertEqual(storico_excel.trimestre_da_etichetta("OTT-NOV-DIC-2022"),
                         ("2022-Q4", date(2022, 12, 31)))
        self.assertEqual(storico_excel.trimestre_da_etichetta("APR - MAG -GIU 2026")[0], "2026-Q2")
        self.assertEqual(storico_excel.trimestre_da_etichetta("LUG-AGO-SETT 2023")[0], "2023-Q3")
        self.assertIsNone(storico_excel.trimestre_da_etichetta("TOTALI"))

    def test_righe_vuote_e_colonne_extra_ignorate(self):
        esito = storico_excel.leggi_righe([
            ("GEN-FEB-MAR 2026", *INTESTAZIONE, "BASE", None, "XX"),
            ("UFFICIO A", 100, None, 20, 1, "SYN-A", 121, "BASE"),
            ("UFFICIO B", None, None, None, None, "SYN-B", 0),
            (None,),
            ("UFFICIO C", "n/d", 1, 1, 1, "SYN-C"),
        ])
        self.assertEqual(len(esito.righe), 1)
        r = esito.righe[0]
        self.assertEqual((r.trimestre, r.matricola, r.a3_bn, r.totale), ("2026-Q1", "SYN-A", 0, 121))
        self.assertEqual(len(esito.avvisi), 2)


class ImportaStoricoCommandTests(TestCase):
    def setUp(self):
        self.a = Macchina.objects.create(reparto="UFFICIO A", matricola="SYN-A")
        self.b = Macchina.objects.create(reparto="UFFICIO - 2", matricola="SYN-B")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / "storico.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = storico_excel.FOGLIO_DEFAULT
        for riga in [
            ("OTT-NOV-DIC 2025", *INTESTAZIONE),
            ("UFFICIO A", 1000, 10, 500, 5, "SYN-A"),
            ("UFFICIO 2", 300, None, 200, None, None),
            ("VECCHIA", 50, 0, 0, 0, "SYN-OLD"),
            (),
            ("GEN-FEB-MAR 2026", *INTESTAZIONE),
            ("UFFICIO A", 1200, 9, 600, 6, "SYN-A"),
        ]:
            ws.append(riga)
        wb.save(self.file)

    def _run(self, *args):
        out = StringIO()
        call_command("importa_storico_contatori", str(self.file), *args, stdout=out)
        return out.getvalue()

    def test_dry_run_non_scrive(self):
        out = self._run()
        self.assertIn("CREEREI", out)
        self.assertIn("SYN-OLD", out)
        self.assertEqual(LetturaContatori.objects.count(), 0)

    def test_apply_crea_abbina_reparto_e_segnala_calo(self):
        out = self._run("--apply")
        self.assertEqual(LetturaContatori.objects.count(), 3)
        l = LetturaContatori.objects.get(macchina=self.a, trimestre="2025-Q4")
        self.assertEqual((l.a4_bn, l.data), (1000, date(2025, 12, 31)))
        self.assertTrue(LetturaContatori.objects.filter(macchina=self.b, trimestre="2025-Q4").exists())
        self.assertIn("CALO", out)

    def test_esistente_lasciata_salvo_sovrascrivi(self):
        LetturaContatori.objects.create(macchina=self.a, trimestre="2026-Q1", data=date(2026, 4, 1),
                                        a4_bn=1, a3_bn=1, a4_col=1, a3_col=1)
        self.assertIn("DIVERSA", self._run("--apply"))
        self.assertEqual(LetturaContatori.objects.get(macchina=self.a, trimestre="2026-Q1").a4_bn, 1)
        self._run("--apply", "--sovrascrivi")
        self.assertEqual(LetturaContatori.objects.get(macchina=self.a, trimestre="2026-Q1").a4_bn, 1200)

    def test_dal_filtra_trimestri(self):
        self._run("--apply", "--dal", "2026-Q1")
        self.assertEqual(list(LetturaContatori.objects.values_list("trimestre", flat=True)), ["2026-Q1"])
