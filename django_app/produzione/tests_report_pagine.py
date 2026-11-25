"""Pagina del report CMM con tutte le quote e confronto fra report. Dati inventati."""
from __future__ import annotations

from django.urls import reverse

from . import report_cmm_pagine as pagine
from .models import AliasQuotaCMM
from .tests_quote_migliorie import QuoteBase

D40 = ("Ø40 H7", 40.0, 0.025, 0.0)
D62 = ("Ø62 k6", 62.0, 0.021, 0.002)


def q(quota, x):
    nome, nom, ts, ti = quota
    return (nome, x, nom, ts, ti)


class ReportPaginaTests(QuoteBase):
    def setUp(self):
        super().setUp()
        self.r1 = self.report("SN1", [q(D40, 40.010), q(D62, 62.010)], giorni=0)
        self.r2 = self.report("SN2", [q(D40, 40.020), q(D62, 62.0115)], giorni=1)
        self.r3 = self.report("SN3", [q(D40, 40.030), q(D62, 62.0205)], giorni=2)   # Ø40 fuori, Ø62 al limite

    def test_righe_vicini_e_conteggi(self):
        dati = pagine.righe_report(self.r2)
        self.assertEqual((dati["prima"], dati["dopo"]), (self.r1, self.r3))
        d40 = next(r for r in dati["righe"] if r["m"].nome == "Ø40 H7")
        self.assertAlmostEqual(d40["delta"], 0.010)
        self.assertEqual(d40["u_pct"], 60)                       # 40,020: 60% della metà tolleranza
        dati3 = pagine.righe_report(self.r3)
        self.assertEqual(dati3["righe"][0]["m"].nome, "Ø40 H7")   # la fuori in cima
        self.assertEqual((dati3["conta"]["fuori"], dati3["conta"]["limite"]), (1, 1))
        self.assertIsNone(pagine.righe_report(self.r1)["prima"])

    def test_pagina_tutte_e_filtri(self):
        url = reverse("produzione:report_cmm", args=[self.r3.pk])
        r = self.client.get(url)
        self.assertContains(r, "Ø62 k6")                         # anche quelle in tolleranza
        self.assertContains(r, "‹ Pezzo prima")
        self.assertNotContains(r, "Pezzo dopo ›")
        self.assertContains(r, "prod-tolbar-x is-fuori")
        r = self.client.get(url + "?f=fuori")
        self.assertContains(r, "Ø40 H7")
        self.assertNotContains(r, "<b>Ø62 k6</b>")
        r = self.client.get(url + "?f=limite")
        self.assertContains(r, "<b>Ø62 k6</b>")

    def test_confronto(self):
        dati = pagine.confronta([self.r1, self.r2, self.r3])
        self.assertEqual(dati["totale"], 2)
        d40 = dati["righe"][0]
        self.assertEqual(d40["nome"], "Ø40 H7")
        self.assertTrue(d40["fuori"])
        self.assertAlmostEqual(d40["delta"], 0.020)
        self.assertEqual(d40["delta_pct"], 80)
        self.assertTrue(d40["cambia"])
        solo = pagine.confronta([self.r1, self.r2], solo_cambiate=True)
        self.assertEqual([r["nome"] for r in solo["righe"]], ["Ø40 H7"])      # Ø62: +7% della tolleranza

    def test_confronto_allinea_le_quote_unite(self):
        altro = self.report("SN1", [("Diametro 40", 40.012, 40.0, 0.025, 0.0)], prog="PRG_B", giorni=3)
        AliasQuotaCMM.objects.create(pn="PN-ALFA-1", prog_origine="PRG_B", quota_origine="DIAMETRO 40|40.0000",
                                     prog_destinazione="PRG_A", quota_destinazione="Ø40 H7|40.0000")
        AliasQuotaCMM.objects.filter(pk__isnull=False).update(quota_origine=f"{altro.misure.get().chiave}|40.0000",
                                                              quota_destinazione=f"{self.r1.misure.get(nome='Ø40 H7').chiave}|40.0000")
        dati = pagine.confronta([self.r1, altro])
        d40 = next(r for r in dati["righe"] if r["nome"] == "Ø40 H7")
        self.assertIsNotNone(d40["valori"][1])
        self.assertEqual(dati["totale"], 2)

    def test_proposte(self):
        fase2 = self.report("SN2", [q(D40, 40.021)], prog="PRG_B", giorni=5)
        p = pagine.proposte(self.r2)
        self.assertEqual(p["fasi"], [self.r2.pk, fase2.pk])
        self.assertEqual(p["vicini"], [self.r1.pk, self.r2.pk, self.r3.pk])
        self.assertEqual(p["primo"][0], self.r1.pk)

    def test_vista_confronto_e_csv(self):
        url = reverse("produzione:report_confronta")
        r = self.client.get(url, {"r": [self.r3.pk, self.r1.pk]})
        self.assertContains(r, "Confronto report")
        self.assertContains(r, "SN1")
        self.assertContains(r, "+80% toll.")
        r = self.client.get(url, {"r": [self.r1.pk, self.r3.pk], "formato": "csv"})
        corpo = r.content.decode("utf-8-sig")
        self.assertIn("Ø40 H7;40,0000;40,0000;40,0250;40,0100;40,0300;0,0200;80", corpo)
        r = self.client.get(url, {"r": [self.r1.pk]})
        self.assertRedirects(r, reverse("produzione:report_cmm", args=[self.r1.pk]), fetch_redirect_response=False)
        self.assertEqual(len(pagine.report_da_confrontare([self.r1.pk, "x", self.r1.pk, self.r2.pk])), 2)

    def test_elenco_con_scelta(self):
        r = self.client.get(reverse("produzione:report_cmm", args=[self.r1.pk]))
        self.assertContains(r, "confronta.js")
        altro = self.report("SN1", [q(D40, 40.011)], prog="PRG_B", giorni=4)
        r = self.client.get(reverse("produzione:report_cmm", args=[self.r1.pk]))
        self.assertContains(r, f'name="r" value="{altro.pk}"')
        self.assertContains(r, "Confronta le fasi")


class MatriceOpTests(QuoteBase):
    def setUp(self):
        super().setUp()
        self.report("SN1", [q(D40, 40.010)], prog="P120", giorni=0)
        self.report("SN1", [q(D40, 40.030)], prog="PCQF", giorni=1)            # fuori
        self.report("SN1", [q(D40, 40.012)], prog="PCQF", giorni=2)            # rimisura: OK
        self.report("SN2", [q(D40, 40.024)], prog="P120", giorni=3)            # 92%: al limite
        self.report("SN3", [q(D40, 40.030)], prog="P120", giorni=4, escluso=True)

    def test_matrice(self):
        m = pagine.matrice_op("OP/2026/100", {"SN2": 1})
        self.assertEqual(m["fasi"], ["P120", "PCQF"])
        self.assertEqual([p["sn"] for p in m["pezzi"]], ["SN2", "SN1"])        # il più recente prima, escluso fuori
        sn1 = m["pezzi"][1]
        self.assertEqual([c["stato"] for c in sn1["riga"]], ["ok", "ok"])
        self.assertEqual(sn1["riga"][1]["n"], 2)
        sn2 = m["pezzi"][0]
        self.assertEqual(sn2["riga"][0]["stato"], "limite")
        self.assertIsNone(sn2["riga"][1])
        self.assertEqual(sn2["anomalie"], 1)
        self.assertEqual((m["conta"]["pezzi"], m["conta"]["completi"], m["conta"]["esclusi"] if "esclusi" in m["conta"] else m["esclusi"]), (2, 1, 1))

    def test_pagina_op_pezzi_e_sezioni(self):
        r = self.client.get(reverse("produzione:scheda", args=[self.pk]))
        self.assertContains(r, "Pezzi e fasi")
        self.assertContains(r, "prod-cella is-limite")
        self.assertContains(r, "Cosa è successo")
        for sez in ("report", "documenti", "fai", "programmi", "xyz"):
            self.assertEqual(self.client.get(reverse("produzione:scheda", args=[self.pk]), {"sez": sez}).status_code, 200)
        self.assertEqual(self.client.get(reverse("produzione:scheda", args=[self.pk]), {"aggiungi": "1"}).context["sezione"], "documenti")
