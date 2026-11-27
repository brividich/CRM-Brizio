"""Regole uniche del modulo: un giudizio di capacità, una finestra impostabile, un «da guardare», pezzi in ordine
di giorno e ora del file. Dati sintetici."""
from datetime import date

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from . import report_cmm_indice as cmm
from . import spc
from .models import ArticoloPN, CartellaReportCMM, ImpostazioniQuoteCMM, MisuraCMM, ReportCMM


class GiudizioUnicoTests(SimpleTestCase):
    def test_verdetto_sull_indice(self):
        self.assertEqual(spc.verdetto(1.40, 30), "capace")          # prima era «al limite» per il limite basso
        self.assertEqual(spc.verdetto(1.33, 30), "capace")
        self.assertEqual(spc.verdetto(1.20, 30), "al limite")
        self.assertEqual(spc.verdetto(0.99, 30), "non capace")
        self.assertEqual(spc.verdetto(0.50, 24), "pochi dati")
        self.assertIsNone(spc.verdetto(None, 30))

    def test_da_guardare(self):
        self.assertTrue(spc.da_guardare(True, None, "capace"))
        self.assertTrue(spc.da_guardare(False, {"verso": "sup"}, "capace"))
        self.assertTrue(spc.da_guardare(False, None, "al limite"))
        self.assertTrue(spc.da_guardare(False, None, "non capace"))
        self.assertFalse(spc.da_guardare(False, None, "pochi dati"))
        self.assertFalse(spc.da_guardare(False, None, "capace"))
        self.assertTrue(cmm.pn_da_guardare(1, 0, 0, 0))
        self.assertFalse(cmm.pn_da_guardare(0, 0, 0, 0))

    def test_seriali(self):
        self.assertEqual(spc.chiave_seriale(" sn-00 1/a "), "SN001A")
        self.assertEqual(spc.ultima_per_seriale(["SN-1", "SN 2", "sn1", ""]), [1, 2, 3])

    def test_deriva_con_forchetta(self):
        us = [0.30 + 0.03 * i for i in range(20)]
        d = spc.deriva(us)
        self.assertEqual(d["verso"], "sup")
        self.assertEqual(d["n"], 20)
        self.assertIsNotNone(d["pezzi_min"])
        self.assertEqual(cmm.deriva(us), d)                          # report_cmm_indice usa la stessa
        self.assertIsNone(spc.deriva([0.1] * 20))
        self.assertAlmostEqual(spc.usata(10.05, 10.0, 9.9, 10.1), 0.5)
        self.assertAlmostEqual(spc.usata(0.01, 0.0, 0.0, 0.02), 0.5)


class FinestraEOrdineTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_finestra_impostabile(self):
        self.assertEqual(cmm.finestra(), 30)
        ArticoloPN.objects.create(pn="PN-0001", analisi_il="2026-11-01T10:00:00Z")
        self.assertFalse(cmm.imposta_finestra(40))                   # non è fra le scelte
        self.assertTrue(cmm.imposta_finestra(50))
        self.assertEqual(cmm.finestra(), 50)
        self.assertEqual(ImpostazioniQuoteCMM.attuali().finestra, 50)
        self.assertIsNone(ArticoloPN.objects.get(pn="PN-0001").analisi_il)   # da ricalcolare al prossimo giro
        self.assertFalse(cmm.imposta_finestra(50))

    def test_stesso_giorno_vale_l_ora_del_file(self):
        cartella = CartellaReportCMM.objects.create(pn="PN-0001", percorso=r"X:\sintetico\PN-0001")
        giorno = date(2026, 11, 20)
        # letti in ordine inverso a quello di misura: l'id non dice l'ordine, l'ora del file sì
        for sn, ora, valore in (("SN-0003", 3000.0, 10.03), ("SN-0001", 1000.0, 10.01), ("SN-0002", 2000.0, 10.02)):
            r = ReportCMM.objects.create(cartella=cartella, pn="PN-0001", op="OP/2026/0001", percorso=rf"X:\sintetico\{sn}.pdf",
                                         file=f"{sn}.pdf", programma="PROG_A", programma_base="PROG_A", seriale=sn, data=giorno,
                                         modificato=ora, righe=1)
            MisuraCMM.objects.create(report=r, indice=1, nome="D1", chiave="D1", misurato=valore, nominale=10.0,
                                     tol_sup=0.1, tol_inf=-0.1)
        d = cmm.dati_programma("PN-0001", "PROG_A")
        self.assertEqual([r[1] for r in d["report"]], ["SN-0001", "SN-0002", "SN-0003"])
        self.assertEqual([v[1] for v in d["valori"][0]], [10.01, 10.02, 10.03])
        from .report_cmm_pagine import vicini

        centro = ReportCMM.objects.get(seriale="SN-0002")
        prima, dopo = vicini(centro)
        self.assertEqual((prima.seriale, dopo.seriale), ("SN-0001", "SN-0003"))
        self.assertEqual(ReportCMM.objects.first().seriale, "SN-0003")          # Meta.ordering: il più recente
