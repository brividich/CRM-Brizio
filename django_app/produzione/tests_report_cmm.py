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
        self.assertEqual((stat["letti"], stat["completa"]), (2, True))          # LPT: non si apre
        r = ReportCMM.objects.get(seriale="SN001")
        self.assertEqual((r.pn, r.op, r.programma, r.programma_base), ("PN-ALFA-1", "OP/2026/100", "PRG_PROVA_REV0", "PRG_PROVA"))
        self.assertEqual((r.righe, r.fuori, r.data.isoformat()), (4, 2, "2026-01-01"))
        m = MisuraCMM.objects.get(report=r, chiave="196,00")
        self.assertTrue(m.fuori)
        self.assertAlmostEqual(m.fuori_di, -0.0246)
        self.assertEqual(m.sezione, "DIAMETRI ESTERNI")
        self.assertFalse(ReportCMM.objects.filter(file="32_OP-2026-100_LPT.pdf").exists())

        # Invariati: non si rileggono. Sparito: si toglie con le sue misure.
        os.remove(a)
        stat = cmm.leggi_pn("PN-ALFA-1")
        self.assertEqual((stat["letti"], stat["invariati"], stat["tolti"]), (0, 1, 1))
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

    def test_pagina_analisi_quote(self):
        pagina = self.client.get(reverse("produzione:pn_quote"), {"pn": "PN-ALFA-1", "q": "196,00", "tab": "mappa"})
        self.assertEqual(pagina.status_code, 200)
        self.assertEqual(pagina.context["prog"], "PRG_PROVA")          # il programma più recente, scelto da sé
        self.assertEqual(pagina.context["stato"]["tab"], "mappa")
        self.assertContains(pagina, 'id="aq-stato"', html=False)
        self.assertContains(pagina, "analisi_quote.js", html=False)

    def test_api_quote(self):
        r = self.client.get(reverse("produzione:api_quote"), {"pn": "pn-alfa-1", "prog": "PRG_PROVA"})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(sorted(x[1] for x in d["report"]), ["SN001", "SN002"])
        self.assertEqual([q["nome"] for q in d["quote"]], ["178,00", "196,00", "163,00 Dia F", "160,00"])
        self.assertEqual(d["quote"][1]["id"], "196,00|131.3610")
        v = d["valori"][1][0]                                            # [report, rilevato, tol+, tol-, fuori, fuori di, da ver.]
        self.assertEqual(v[1:5], [131.3364, 0.025, 0.0, 1])
        self.assertAlmostEqual(v[5], -0.0246)
        self.assertEqual(d["tagliati"], 0)
        # periodo: i report sono del 01/01/2026
        vuoto = self.client.get(reverse("produzione:api_quote"), {"pn": "PN-ALFA-1", "prog": "PRG_PROVA", "da": "2026-02-01"}).json()
        self.assertEqual((vuoto["report"], vuoto["totale"]), ([], 0))
        self.assertEqual(self.client.get(reverse("produzione:api_quote"), {"pn": "PN-ALFA-1"}).status_code, 400)

    def test_api_quote_json_anche_per_chi_non_e_entrato(self):
        self.client.logout()
        r = self.client.get(reverse("produzione:api_quote"), {"pn": "PN-ALFA-1", "prog": "PRG_PROVA"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r["Content-Type"], "application/json")

    def test_utente_normale_vede_pagina_e_dati(self):
        from tasks.tests_utils import _create_user_with_legacy

        utente = _create_user_with_legacy(username="prod-oper", legacy_user_id=682, role_id=2, role_name="operatore")
        self.client.force_login(utente)
        self.assertEqual(self.client.get(reverse("produzione:pn_quote"), {"pn": "PN-ALFA-1"}).status_code, 200)
        r = self.client.get(reverse("produzione:api_quote"), {"pn": "PN-ALFA-1", "prog": "PRG_PROVA"})
        self.assertEqual(r.status_code, 200, r.content[:200])

    def test_statistiche_e_quote_critiche(self):
        s = cmm.statistiche([(10.01, 9.9, 10.1), (10.03, 9.9, 10.1), (9.99, 9.9, 10.1), (10.02, 9.9, 10.1), (10.0, 9.9, 10.1)])
        self.assertAlmostEqual(s["media"], 10.01)
        self.assertAlmostEqual(s["sd"], 0.015811, places=5)
        self.assertAlmostEqual(s["cp"], 0.2 / (6 * s["sd"]), places=6)
        self.assertAlmostEqual(s["cpk"], (10.1 - 10.01) / (3 * s["sd"]), places=6)
        self.assertAlmostEqual(s["u"], 0.0)
        self.assertIsNone(cmm.statistiche([(1, 0, 2)])["cpk"])           # meno di 5 punti
        critiche = cmm.quote_critiche("PN-ALFA-1")
        self.assertEqual({c["quota"]["nome"] for c in critiche}, {"196,00", "163,00 Dia F"})
        self.assertTrue(all(c["fuori_ultimo"] for c in critiche))
        pagina = self.client.get(reverse("produzione:pn_scheda"), {"pn": "PN-ALFA-1"}, follow=True)
        self.assertContains(pagina, "Quote da tenere d", html=False)

    def test_report_fuori_e_link_anomalia(self):
        pagina = self.client.get(reverse("produzione:report_cmm", args=[self.r1.pk]))
        self.assertEqual(pagina.status_code, 200)
        self.assertEqual([r["m"].nome for r in pagina.context["righe"]][:2], ["196,00", "163,00 Dia F"])   # fuori in cima
        self.assertIn(f"op_id={self.pk}", pagina.context["url_anomalia"])
        self.assertIn(f"report_cmm={self.r1.pk}", pagina.context["url_anomalia"])
        self.assertEqual(len(pagina.context["righe"]), 4)                                # tutte le quote
        fuori = self.client.get(reverse("produzione:report_cmm", args=[self.r1.pk]), {"f": "fuori"})
        self.assertEqual(len(fuori.context["righe"]), 2)

    def test_pdf_solo_dentro_la_radice(self):
        r = self.client.get(reverse("produzione:report_cmm_pdf", args=[self.r1.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(b"".join(r.streaming_content).startswith(b"%PDF"))
        for chiudi in r._resource_closers:  # r.close() manderebbe request_finished e chiuderebbe il DB del test
            chiudi()
        ReportCMM.objects.filter(pk=self.r1.pk).update(percorso=r"C:\Windows\win.ini")
        self.assertEqual(self.client.get(reverse("produzione:report_cmm_pdf", args=[self.r1.pk])).status_code, 302)   # torna al report col messaggio

    def test_schede_op_e_pn_mostrano_i_report(self):
        scheda = self.client.get(reverse("produzione:scheda", args=[self.pk]))
        self.assertEqual(len(scheda.context["report_cmm"]), 2)
        pn = self.client.get(reverse("produzione:pn_scheda"), {"pn": "PN-ALFA-1"}, follow=True)
        self.assertEqual(pn.context["report_cmm"]["n"], 2)
        self.assertContains(pn, "Analisi quote")

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


class UnilateraliTests(SimpleTestCase):
    def test_forma_e_posizione_contano_verso_il_limite_superiore(self):
        self.assertTrue(cmm.unilaterale(0.0, 0.0, 0.05))
        self.assertFalse(cmm.unilaterale(8.0, 8.025, 8.034))
        self.assertAlmostEqual(cmm.usata(0.01, 0.0, 0.0, 0.05), 0.2)      # 20%, non -60%
        self.assertAlmostEqual(cmm.usata(8.0295, 8.0, 8.025, 8.034), 0.0)  # centro della zona
        punti = [(0.010, 0.0, 0.05), (0.012, 0.0, 0.05), (0.011, 0.0, 0.05), (0.009, 0.0, 0.05), (0.013, 0.0, 0.05)]
        s = cmm.statistiche(punti, 0.0)
        self.assertIsNone(s["cp"])
        self.assertAlmostEqual(s["cpk"], (0.05 - 0.011) / (3 * s["sd"]), places=6)


class GiroTests(ArchivioBase):
    def test_solo_report_cmm_fino_a_tre_livelli(self):
        self.scrivi("210_OP-2026-100_ZPN_SN001_A.pdf", _pdf_report_sintetico("SN001"))
        profonda = os.path.join(self.cartella_op, "a", "b", "c", "d")
        os.makedirs(profonda)
        with open(os.path.join(profonda, "210_OP-2026-100_ZPN_SN009_A.pdf"), "wb") as fh:
            fh.write(_pdf_report_sintetico("SN009"))
        nomi = [x[1] for x in cmm._pdf_della_cartella(os.path.join(self.radice, "PN-ALFA-1"))]
        self.assertEqual(nomi, ["210_OP-2026-100_ZPN_SN001_A.pdf"])
        self.assertTrue(cmm.nome_da_report_cmm("CQF_OP-2026-0008_ZP_SN901.pdf"))
        self.assertFalse(cmm.nome_da_report_cmm("450_OP-2026-0008_M.pdf"))
        self.assertFalse(cmm.nome_da_report_cmm("CQC 12-3456_OP-2026-0008.pdf"))

    def test_tempo_scaduto_mentre_scorre_le_cartelle(self):
        import time

        self.scrivi("210_OP-2026-100_ZPN_SN001_A.pdf", _pdf_report_sintetico("SN001"))
        stat = cmm.leggi_cartella("PN-ALFA-1", os.path.join(self.radice, "PN-ALFA-1"), time.monotonic() - 1)
        self.assertEqual((stat["letti"], stat["completa"]), (0, False))

    def test_pdf_non_leggibile_messaggio_chiaro(self):
        self.scrivi("210_OP-2026-100_ZPN_SN001_A.pdf", _pdf_report_sintetico("SN001"))
        cmm.leggi_pn("PN-ALFA-1")
        r = ReportCMM.objects.get()
        with override_settings(PRODUZIONE_REPORT_CMM_ROOT=os.path.join(self.radice, "non-esiste")):
            resp = self.client.get(reverse("produzione:report_cmm_pdf", args=[r.pk]), follow=True)
        self.assertContains(resp, "permesso di lettura")
