"""Registro delle quote e pagina della quota: indici sul tratto con la tolleranza di oggi, limiti di controllo sulla
base congelata, analisi salvata con id stabile, pagina unica. Dati sintetici."""
import json
import random
import shutil
import subprocess
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase
from django.urls import reverse

from . import articoli, spc
from . import report_cmm_indice as cmm
from . import report_cmm_pagine as pagine
from .models import ArticoloPN, QuotaCapacita
from .tests_quote_migliorie import QuoteBase

JS = Path(__file__).parent / "static" / "produzione" / "js" / "spc.js"


class FormuleTests(SimpleTestCase):
    def test_tratto_tolleranza(self):
        self.assertEqual(spc.tratto_tolleranza([]), 0)
        self.assertEqual(spc.tratto_tolleranza([(9.9, 10.1)] * 5), 0)
        self.assertEqual(spc.tratto_tolleranza([(9.9, 10.1)] * 3 + [(9.95, 10.05)] * 4), 3)
        self.assertEqual(spc.tratto_tolleranza([(9.9, 10.1), (9.95, 10.05), (9.9, 10.1)]), 2)   # conta solo l'ultimo tratto

    def test_base_congelata(self):
        self.assertEqual(spc.base_controllo(20), 20)          # pochi pezzi: tutti
        self.assertEqual(spc.base_controllo(30), 15)
        self.assertEqual(spc.base_controllo(100), 50)
        rnd = random.Random(7)
        xs = [10 + rnd.gauss(0, 0.002) for _ in range(15)] + [10.02 + rnd.gauss(0, 0.002) for _ in range(15)]
        tutti, base = spc.limiti_controllo(xs), spc.limiti_controllo(xs, spc.base_controllo(len(xs)))
        self.assertEqual(base["base"], 15)
        self.assertAlmostEqual(base["centro"], sum(xs[:15]) / 15, places=9)
        self.assertLess(base["centro"], tutti["centro"])      # lo spostamento non entra nei limiti che lo devono vedere
        regole = {g["regola"] for g in spc.segnali(xs, 15)}
        self.assertIn(1, regole)                              # i pezzi spostati sono oltre 3σ della base
        self.assertEqual(spc.limiti_controllo([1.0] * 30, 15)["base"], 30)   # base senza dispersione: tutti

    def test_stato_processo(self):
        self.assertEqual(spc.stato_processo({"verso": "sup"}, [{"indice": 3}], [{"regola": 1}], 30), "deriva")
        self.assertEqual(spc.stato_processo(None, [{"indice": 3}], [], 30), "spostato")
        self.assertEqual(spc.stato_processo(None, [], [{"regola": 2}], 30), "segnali")
        self.assertEqual(spc.stato_processo(None, [], [], 10), "pochi")
        self.assertEqual(spc.stato_processo(None, [], [], 30), "stabile")

    def test_base_uguale_in_javascript(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node non disponibile")
        rnd = random.Random(21)
        xs = [round(10 + rnd.gauss(0, 0.003) + (0.01 if i >= 20 else 0), 5) for i in range(40)]
        script = JS.read_text(encoding="utf-8") + "\nconst xs = " + json.dumps(xs) + """;
const b = SPC.base_controllo(xs.length), l = SPC.limiti_controllo(xs, b);
console.log(JSON.stringify({b: b, lcs: l.lcs, lci: l.lci, base: l.base, segnali: SPC.segnali(xs, b).map(g => [String(g.regola), g.da, g.a]),
  tratti: [SPC.tratto_tolleranza([]), SPC.tratto_tolleranza([[9.9, 10.1], [9.9, 10.1]]), SPC.tratto_tolleranza([[9.9, 10.1], [9.95, 10.05], [9.95, 10.05]]),
           SPC.tratto_tolleranza([[9.9, 10.1], [9.95, 10.05], [9.9, 10.1]])]}));
"""
        r = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        j = json.loads(r.stdout)
        b = spc.base_controllo(len(xs))
        lim = spc.limiti_controllo(xs, b)
        self.assertEqual((j["b"], j["base"]), (b, lim["base"]))
        self.assertAlmostEqual(j["lcs"], lim["lcs"], places=9)
        self.assertAlmostEqual(j["lci"], lim["lci"], places=9)
        self.assertEqual(j["segnali"], [[str(g["regola"]), g["da"], g["a"]] for g in spc.segnali(xs, b)])
        self.assertEqual(j["tratti"], [spc.tratto_tolleranza([]), spc.tratto_tolleranza([(9.9, 10.1)] * 2),
                                       spc.tratto_tolleranza([(9.9, 10.1), (9.95, 10.05), (9.95, 10.05)]),
                                       spc.tratto_tolleranza([(9.9, 10.1), (9.95, 10.05), (9.9, 10.1)])])


class RegistroQuoteTests(QuoteBase):
    def setUp(self):
        super().setUp()
        rnd = random.Random(3)
        # 10 pezzi con tolleranza ±0,05, poi il programma la stringe a ±0,02 per 30 pezzi (due OP)
        for i in range(40):
            tol = 0.05 if i < 10 else 0.02
            self.report(f"SN{i:03d}", [("D10", round(10 + rnd.gauss(0, 0.003), 4), 10.0, tol, -tol)], giorni=i,
                        op="OP/2026/100" if i < 25 else "OP/2026/101")
        self.articolo = ArticoloPN.objects.create(pn="PN-ALFA-1")

    def test_indici_solo_sul_tratto_con_la_tolleranza_di_oggi(self):
        a = cmm.analisi_pn("PN-ALFA-1")[0]
        self.assertEqual(len(a["serie"]), 30)                 # la finestra: ultimi 30 pezzi (SN010…SN039), tutti a ±0,02
        self.assertIsNone(a["tol_cambio"])
        larga = cmm.analisi_pn("PN-ALFA-1", ultimi=50)[0]     # finestra più larga: dentro c'è il cambio
        self.assertEqual(len(larga["serie"]), 40)
        self.assertEqual(larga["n"], 30)                      # indici solo sui 30 pezzi con la tolleranza di oggi
        self.assertEqual(larga["tol_cambio"]["indice"], 10)
        self.assertEqual(larga["tol_cambio"]["sn"], "SN010")
        self.assertAlmostEqual(larga["tol_cambio"]["usl"], 10.05)
        self.assertAlmostEqual(larga["cpk"], a["cpk"], places=9)
        self.assertTrue(all(g["da"] >= 10 for g in larga["segnali"]))
        self.assertEqual(a["controllo"]["base"], 15)
        self.assertIn(a["processo"], {"stabile", "segnali", "spostato", "deriva"})
        self.assertEqual({o["op"] for o in a["op_confronto"]["op"]}, {"OP/2026/100", "OP/2026/101"})
        self.assertIn("min", a["op_confronto"]["op"][0])

    def test_id_stabile_e_analisi_salvata(self):
        articoli.analizza(self.articolo)
        q = QuotaCapacita.objects.get(pn="PN-ALFA-1")
        self.assertTrue(q.dati)
        primo_id = q.pk
        with mock.patch.object(cmm, "analisi_pn", side_effect=AssertionError("non deve ricalcolare")):
            salvata = cmm.analisi_salvata("PN-ALFA-1")
        self.assertEqual(salvata[0]["pk"], primo_id)
        self.assertEqual(len(salvata[0]["serie"]), 30)
        # un report nuovo: l'analisi salvata è vecchia, la pagina ricalcola; dopo il giro l'id è lo stesso
        self.report("SN040", [("D10", 10.001, 10.0, 0.02, -0.02)], giorni=40, op="OP/2026/101")
        with mock.patch.object(cmm, "analisi_pn", return_value=[]) as calcolo:
            cmm.analisi_salvata("PN-ALFA-1")
        calcolo.assert_called_once()
        articoli.analizza(ArticoloPN.objects.get(pn="PN-ALFA-1"))
        self.assertEqual(list(QuotaCapacita.objects.filter(pn="PN-ALFA-1").values_list("pk", flat=True)), [primo_id])
        self.assertEqual(json.loads(QuotaCapacita.objects.get(pk=primo_id).dati)["serie"][-1][0], 10.001)

    def test_quota_sparita_si_toglie(self):
        articoli.analizza(self.articolo)
        QuotaCapacita.objects.create(pn="PN-ALFA-1", prog="PRG_A", quota_id="VECCHIA|1.0000", nome="vecchia", nominale=1.0)
        articoli.analizza(ArticoloPN.objects.get(pn="PN-ALFA-1"))
        self.assertEqual(QuotaCapacita.objects.filter(pn="PN-ALFA-1").count(), 1)

    def test_pagina_della_quota(self):
        articoli.analizza(self.articolo)
        q = QuotaCapacita.objects.get(pn="PN-ALFA-1")
        d = pagine.quota_pagina(q)
        self.assertEqual(d["a"]["pk"], q.pk)
        self.assertEqual(len(d["grafico"]["serie"]), 30)
        self.assertTrue(d["a"]["processo_testo"])
        self.assertTrue(any("barra" in o for o in d["a"]["op_confronto"]["op"]))
        pagina = self.client.get(reverse("produzione:quota", args=[q.pk]))
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, "D10")
        self.assertContains(pagina, "processo:")
        # in mezzo l'analisi interattiva di Analisi quote, su questa sola quota
        self.assertContains(pagina, 'data-solo="1"')
        self.assertContains(pagina, "aq-stato")
        self.assertContains(pagina, 'data-pane="quota"')
        self.assertEqual(pagina.context["stato"]["q"], q.quota_id)
        self.assertEqual(pagina.context["stato"]["prog"], "PRG_A")
        self.assertNotContains(pagina, "data-carta-qualita")             # un solo grafico: quello interattivo
        self.assertNotContains(pagina, "Apri in Analisi quote")
        self.assertContains(pagina, "Tutte le quote del programma")
        filtrata = self.client.get(reverse("produzione:quota", args=[q.pk]) + "?per=90&op=OP/2026/101")
        self.assertEqual((filtrata.context["stato"]["per"], filtrata.context["stato"]["op"]), ("90", "OP/2026/101"))
        # l'API dice ad Analisi quote l'id stabile di ogni quota (link «Pagina della quota»)
        api = self.client.get(reverse("produzione:api_quote"), {"pn": "PN-ALFA-1", "prog": "PRG_A"}).json()
        self.assertEqual(api["quote"][0]["pk"], q.pk)
        programma = self.client.get(reverse("produzione:pn_quote"), {"pn": "PN-ALFA-1"})
        self.assertContains(programma, "data-url-quota")
        self.assertNotContains(programma, 'data-solo="1"')
        self.assertNotContains(programma, "{#")
        self.assertNotContains(pagina, "Pagina della quota")              # ci siamo già
        self.assertNotContains(pagina, "{#")
        self.assertEqual(self.client.get(reverse("produzione:quota", args=[q.pk + 999])).status_code, 404)
        # dalla scheda P/N e da Quote CMM si arriva alla pagina della quota
        scheda = self.client.get(reverse("produzione:pn", args=["PN-ALFA-1"]) + "?sez=qualita")
        self.assertContains(scheda, reverse("produzione:quota", args=[q.pk]))
        self.assertNotContains(scheda, "{#")
