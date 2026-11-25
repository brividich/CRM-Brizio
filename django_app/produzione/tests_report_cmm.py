"""Archivio dei report CMM e andamento delle quote (Ordini di produzione). PDF e cartelle sintetici."""
from __future__ import annotations

import os
import shutil
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from anomalie.tests_report_cmm import _pdf_report_sintetico

from . import report_cmm_indice as cmm
from .models import CartellaReportCMM, MisuraCMM, ReportCMM
from .tests import ProduzioneBase


class NomiTests(SimpleTestCase):
    def test_dati_dal_nome(self):
        self.assertEqual(cmm.dati_dal_nome("210_OP-2026-0007_ZPN_SN900_LATO_B.pdf"),
                         {"fase": "210", "seriale": "SN900", "programma": "210_ZPN_LATO_B"})
        self.assertEqual(cmm.dati_dal_nome("CQF_OP-2026-0008_ZP_SN901.pdf")["seriale"], "SN901")
        self.assertEqual(cmm.dati_dal_nome("32_OP-2026-0009_LPT.pdf")["seriale"], "LPT")
        self.assertEqual(cmm.dati_dal_nome("senza_op.pdf"), {"fase": "", "seriale": "", "programma": ""})

    def test_op_programma_data_seriale(self):
        self.assertEqual(cmm.titolo_op("OP-2026-0010"), "OP/2026/0010")
        self.assertEqual(cmm.titolo_op("CQF_OP-2026-0010_ZP_X.pdf"), "OP/2026/0010")
        self.assertEqual(cmm.programma_base("CQF_PN-PROVA-9_EA_ZP_REV2_LATO"), "CQF_PN-PROVA-9_EA_ZP_LATO")
        self.assertEqual(cmm.programma_base("60_PN-PROVA-9_EG_ZPU_REV1"), "60_PN-PROVA-9_EG_ZPU")
        self.assertEqual(cmm.data_report("16/11/2026").isoformat(), "2026-11-16")
        self.assertIsNone(cmm.data_report("31/02/2026"))
        self.assertEqual(cmm.pulisci_seriale("SN902_RILAVORA\ufffd"), "SN902_RILAVORA")
        self.assertEqual(cmm.chiave_quota(" 163,00 Dia F "), "163,00DIAF")


class ArchivioBase(ProduzioneBase):
    """Share finta: <tmp>/PN-ALFA-1/OP-2026-100/<report>.pdf."""

    def setUp(self):
        super().setUp()
        self.radice = tempfile.mkdtemp(prefix="cmm_")
        self.addCleanup(shutil.rmtree, self.radice, True)
        impostazioni = override_settings(PRODUZIONE_REPORT_CMM_ROOT=self.radice)
        impostazioni.enable()
        self.addCleanup(impostazioni.disable)
        self.cartella_op = os.path.join(self.radice, "PN-ALFA-1", "OP-2026-100")
        os.makedirs(self.cartella_op)

    def scrivi(self, nome, contenuto):
        p = os.path.join(self.cartella_op, nome)
        with open(p, "wb") as fh:
            fh.write(contenuto)
        return p


class LetturaTests(ArchivioBase):
    def test_legge_rilegge_e_toglie(self):
        a = self.scrivi("210_OP-2026-100_ZPN_SN001_A.pdf", _pdf_report_sintetico("SN001"))
        self.scrivi("210_OP-2026-100_ZPN_SN002_A.pdf", _pdf_report_sintetico("SN002"))
        self.scrivi("32_OP-2026-100_LPT.pdf", b"%PDF-1.4 non un report")
        stat = cmm.leggi_pn("pn-alfa-1")
        self.assertEqual((stat["letti"], stat["completa"]), (3, True))
        r = ReportCMM.objects.get(seriale="SN001")
        self.assertEqual((r.pn, r.op, r.programma, r.programma_base), ("PN-ALFA-1", "OP/2026/100", "PRG_PROVA_REV0", "PRG_PROVA"))
        self.assertEqual((r.righe, r.fuori, r.data.isoformat()), (4, 2, "2026-01-01"))
        m = MisuraCMM.objects.get(report=r, chiave="196,00")
        self.assertTrue(m.fuori)
        self.assertAlmostEqual(m.fuori_di, -0.0246)
        self.assertEqual(m.sezione, "DIAMETRI ESTERNI")
        self.assertTrue(ReportCMM.objects.get(file="32_OP-2026-100_LPT.pdf").errore)

        # Invariati: non si rileggono. Sparito: si toglie con le sue misure.
        os.remove(a)
        stat = cmm.leggi_pn("PN-ALFA-1")
        self.assertEqual((stat["letti"], stat["invariati"], stat["tolti"]), (0, 2, 1))
        self.assertFalse(MisuraCMM.objects.filter(report__seriale="SN001").exists())
        self.assertIsNotNone(CartellaReportCMM.objects.get(pn="PN-ALFA-1").letta_il)

    def test_giro_e_cartella_mancante(self):
        self.scrivi("210_OP-2026-100_ZPN_SN001_A.pdf", _pdf_report_sintetico("SN001"))
        self.assertEqual(cmm.giro(1)["letti"], 1)
        self.assertIn("errore", cmm.leggi_pn("PN-INESISTENTE"))

    def test_percorso_sicuro(self):
        p = self.scrivi("210_OP-2026-100_ZPN_SN001_A.pdf", _pdf_report_sintetico("SN001"))
        self.assertEqual(cmm.percorso_sicuro(p), p)
        fuori = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        fuori.close()
        self.addCleanup(os.remove, fuori.name)
        self.assertEqual(cmm.percorso_sicuro(fuori.name), "")
        self.assertEqual(cmm.percorso_sicuro(os.path.join(self.cartella_op, "..", "..", "..", "x.pdf")), "")


class PagineTests(ArchivioBase):
    def setUp(self):
        super().setUp()
        self.scrivi("210_OP-2026-100_ZPN_SN001_A.pdf", _pdf_report_sintetico("SN001"))
        self.scrivi("210_OP-2026-100_ZPN_SN002_A.pdf", _pdf_report_sintetico("SN002"))
        cmm.leggi_pn("PN-ALFA-1")
        self.r1 = ReportCMM.objects.get(seriale="SN001")

    def test_andamento_quota_con_grafico(self):
        url = reverse("produzione:pn_quote")
        pagina = self.client.get(url, {"pn": "PN-ALFA-1"})
        self.assertEqual(pagina.status_code, 200)
        self.assertEqual(pagina.context["prog"], "PRG_PROVA")          # un solo programma: scelto da sé
        self.assertEqual([q["nome"] for q in pagina.context["quote"]], ["178,00", "196,00", "163,00 Dia F", "160,00"])
        self.assertEqual({q["chiave"]: q["n_fuori"] for q in pagina.context["quote"]}["196,00"], 2)
        pagina = self.client.get(url, {"pn": "PN-ALFA-1", "prog": "PRG_PROVA", "q": "196,00", "r": self.r1.pk})
        self.assertEqual(len(pagina.context["punti"]), 2)
        self.assertContains(pagina, "<svg", html=False)
        self.assertContains(pagina, 'class="is-scelto"', html=False)
        # coordinate SVG col punto anche con la localizzazione italiana
        self.assertNotRegex(pagina.content.decode(), r'(?:cx|cy|y1|y2|x)="-?\d+,\d')

    def test_report_fuori_e_link_anomalia(self):
        pagina = self.client.get(reverse("produzione:report_cmm", args=[self.r1.pk]))
        self.assertEqual(pagina.status_code, 200)
        self.assertEqual([m.nome for m in pagina.context["misure"]], ["196,00", "163,00 Dia F"])
        self.assertIn(f"op_id={self.pk}", pagina.context["url_anomalia"])
        self.assertIn(f"report_cmm={self.r1.pk}", pagina.context["url_anomalia"])
        tutte = self.client.get(reverse("produzione:report_cmm", args=[self.r1.pk]), {"tutte": "1"})
        self.assertEqual(len(tutte.context["misure"]), 4)

    def test_pdf_solo_dentro_la_radice(self):
        r = self.client.get(reverse("produzione:report_cmm_pdf", args=[self.r1.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(b"".join(r.streaming_content).startswith(b"%PDF"))
        for chiudi in r._resource_closers:  # r.close() manderebbe request_finished e chiuderebbe il DB del test
            chiudi()
        ReportCMM.objects.filter(pk=self.r1.pk).update(percorso=r"C:\Windows\win.ini")
        self.assertEqual(self.client.get(reverse("produzione:report_cmm_pdf", args=[self.r1.pk])).status_code, 404)

    def test_schede_op_e_pn_mostrano_i_report(self):
        scheda = self.client.get(reverse("produzione:scheda", args=[self.pk]))
        self.assertEqual(len(scheda.context["report_cmm"]), 2)
        pn = self.client.get(reverse("produzione:pn_scheda"), {"pn": "PN-ALFA-1"})
        self.assertEqual(pn.context["report_cmm"]["n"], 2)
        self.assertContains(pn, "Andamento quote")

    def test_leggi_report_accoda(self):
        with patch("produzione.tasks.accoda_lettura_pn", return_value=True) as accoda:
            r = self.client.post(reverse("produzione:pn_leggi_report"), {"pn": "pn-alfa-1"})
        self.assertEqual(r.status_code, 302)
        accoda.assert_called_once_with("PN-ALFA-1")

    def test_pannello_anomalie_legge_il_report_dalla_share(self):
        url = reverse("api_anomalie_report_cmm_leggi")
        with patch("anomalie.views._can_create_anomalie_for_op", return_value=True):
            r = self.client.post(url, {"op_id": "OP/2026/100", "report_cmm": self.r1.pk})
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(r.json()["intestazione"]["seriale"], "SN001")
            self.assertEqual(len(r.json()["righe"]), 4)
            r = self.client.post(url, {"op_id": "OP/2026/100", "report_cmm": 999999})
            self.assertEqual(r.status_code, 404)


class CollegamentiTests(PagineTests):
    def test_ctrl_k_trova_il_report_per_seriale(self):
        r = self.client.get(reverse("api_global_search"), {"q": "SN001"})
        cmm_ris = [x for x in r.json()["results"] if x["tipo"] == "cmm"]
        self.assertEqual([x["label"] for x in cmm_ris], ["SN001"])
        self.assertEqual(cmm_ris[0]["module"], "Report CMM")
        self.assertEqual(cmm_ris[0]["url"], reverse("produzione:report_cmm", args=[self.r1.pk]))

    def test_pannello_anomalie_elenca_i_report_dell_op(self):
        r = self.client.get(reverse("api_anomalie_report_cmm_archivio"), {"op_id": "op/2026/100"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(sorted(x["seriale"] for x in r.json()["report"]), ["SN001", "SN002"])
        self.assertEqual(self.client.get(reverse("api_anomalie_report_cmm_archivio")).status_code, 400)

    def test_elenco_pn_conta_i_report(self):
        pagina = self.client.get(reverse("produzione:pn_elenco"))
        riga = next(r for r in pagina.context["pagina"] if r["pn"] == "PN-ALFA-1")
        self.assertEqual(riga["cmm"], {"n": 2, "con_fuori": 2})
        self.assertContains(pagina, "2/2")

    def test_scheda_fai_porta_ai_report_del_pn(self):
        f = self._fai("OP/2026/100")
        pagina = self.client.get(reverse("tasks:fai_scheda", args=[f.pk]))
        self.assertIn("pn=PN-ALFA-1", pagina.context["url_report_cmm"])
        self.assertContains(pagina, "Report CMM del P/N")

    def test_programma_cmm_del_kickoff_porta_all_andamento(self):
        from types import SimpleNamespace

        from .services import collega_programmi_cmm

        righe = [SimpleNamespace(kind="CMM", code="PRG_PROVA_REV1"), SimpleNamespace(kind="CMM", code="ALTRO")]
        collega_programmi_cmm("PN-ALFA-1", righe)
        self.assertIn("prog=PRG_PROVA", righe[0].url_quote)
        self.assertFalse(hasattr(righe[1], "url_quote"))
