"""Formule SPC (``produzione/spc.py``) e uguaglianza con ``static/produzione/js/spc.js``."""
from __future__ import annotations

import json
import math
import random
import shutil
import subprocess
from pathlib import Path

from django.test import SimpleTestCase

from . import spc

JS = Path(__file__).resolve().parent / "static" / "produzione" / "js" / "spc.js"


def _serie(seed, n=40, m=40.0125, s=0.003, salto=None, trend=0.0):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        x = rnd.gauss(m, s) + trend * i
        if salto and i >= salto[0]:
            x += salto[1]
        out.append(round(x, 5))
    return out


class CapacitaTests(SimpleTestCase):
    def test_sigma_breve_e_cpk_ppk(self):
        xs = [10.0, 10.02, 10.01, 10.03, 10.02, 10.04, 10.03, 10.05]
        mr = [0.02, 0.01, 0.02, 0.01, 0.02, 0.01, 0.02]
        self.assertAlmostEqual(spc.sigma_breve(xs), sum(mr) / len(mr) / 1.128, places=9)
        c = spc.capacita(xs, 9.9, 10.1, 10.0)
        m = sum(xs) / len(xs)
        self.assertAlmostEqual(c["cpk"], min(10.1 - m, m - 9.9) / (3 * spc.sigma_breve(xs)), places=9)
        self.assertAlmostEqual(c["ppk"], min(10.1 - m, m - 9.9) / (3 * spc.dev_std(xs)), places=9)
        self.assertLess(c["ppk"], c["cpk"])                      # serie che sale: il processo si sposta
        self.assertEqual(c["indice"], c["ppk"])
        self.assertEqual(c["verdetto"], "pochi dati")            # 8 pezzi

    def test_intervallo_e_verdetto(self):
        lo, hi = spc.intervallo_cpk(1.4, 30)
        self.assertAlmostEqual(lo, 1.4 - 1.96 * math.sqrt(1 / 270 + 1.96 / 58), places=9)
        self.assertLess(lo, 1.4)
        self.assertGreater(hi, 1.4)
        self.assertEqual(spc.verdetto(1.4, 30), "capace")          # l'intervallo si mostra, non decide
        self.assertEqual(spc.verdetto(1.2, 30), "al limite")
        self.assertEqual(spc.verdetto(0.8, 30), "non capace")
        self.assertIsNone(spc.capacita([1, 2], 0, 3)["cpk"])

    def test_forma_metodo_percentili(self):
        rnd = random.Random(3)
        xs = [round(0.006 * rnd.weibullvariate(1, 1.6), 5) for _ in range(60)]   # planarità: solo positivi, coda a destra
        c = spc.capacita(xs, 0.0, 0.02, 0.0)
        self.assertEqual(c["metodo"], "percentili")
        w = c["weibull"]
        self.assertAlmostEqual(w["k"], 1.6, delta=0.45)
        x50, xa = spc.weibull_quantile(w, 0.5), spc.weibull_quantile(w, spc.P_ALTO)
        self.assertAlmostEqual(c["ppk"], (0.02 - x50) / (xa - x50), places=9)
        normale = (0.02 - sum(xs) / len(xs)) / (3 * spc.dev_std(xs))
        self.assertNotAlmostEqual(c["ppk"], normale, places=2)   # la normale darebbe un altro numero


class SegnaliTests(SimpleTestCase):
    def test_nelson(self):
        xs = [0.0, 0.1, -0.1] * 4 + [0.05] * 2
        self.assertEqual(spc.segnali(xs[:8]), [])
        stabile = _serie(1, 30, 10, 0.01)
        regole = {g["regola"] for g in spc.segnali(stabile)}
        self.assertFalse({1, 2, 3} & regole)
        fuori = stabile[:20] + [10.2] + stabile[20:]
        self.assertIn(1, {g["regola"] for g in spc.segnali(fuori)})
        sopra = stabile[:10] + [x + 0.05 for x in stabile[10:22]]          # 12 pezzi spostati di 5σ
        self.assertIn(2, {g["regola"] for g in spc.segnali(sopra)})
        sale = stabile[:10] + [10 + 0.004 * i for i in range(8)] + stabile[10:]
        self.assertIn(3, {g["regola"] for g in spc.segnali(sale)})
        zigzag = [10 + (0.01 if i % 2 else -0.01) for i in range(16)] + stabile[:5]
        self.assertIn(4, {g["regola"] for g in spc.segnali(zigzag)})

    def test_ewma_vede_un_salto_piccolo(self):
        xs = _serie(7, 40, 10, 0.01, salto=(25, 0.012))
        reg = [g for g in spc.segnali(xs) if g["regola"] == "ewma"]
        self.assertTrue(reg)
        self.assertGreaterEqual(reg[-1]["a"], 30)

    def test_punti_cambio(self):
        xs = _serie(5, 40, 10, 0.005, salto=(22, 0.02))
        cambi = spc.punti_cambio(xs)
        self.assertEqual(len(cambi), 1)
        self.assertAlmostEqual(cambi[0]["indice"], 22, delta=2)
        self.assertAlmostEqual(cambi[0]["dopo"] - cambi[0]["prima"], 0.02, delta=0.006)
        self.assertEqual(spc.punti_cambio(_serie(5, 40, 10, 0.005)), [])

    def test_rischio_prossimo(self):
        centrata = _serie(2, 30, 40.0125, 0.002)
        self.assertLess(spc.rischio_prossimo(centrata, 40.0, 40.025, 40.0), 0.001)
        al_limite = _serie(2, 30, 40.0015, 0.002)
        self.assertGreater(spc.rischio_prossimo(al_limite, 40.0, 40.025, 40.0), 0.2)

    def test_forchetta_pezzi(self):
        basso, alto = spc.pezzi_al_limite(0.02, 0.005, 0.6)
        self.assertEqual(basso, math.ceil(0.4 / (0.02 + 1.96 * 0.005)))
        self.assertEqual(alto, math.ceil(0.4 / (0.02 - 1.96 * 0.005)))
        self.assertEqual(spc.pezzi_al_limite(0.01, 0.01, 0.6)[1], None)    # pendenza lenta che può essere zero


class ConfrontiTests(SimpleTestCase):
    def test_famiglie(self):
        rnd = random.Random(4)
        base = [rnd.gauss(0, 1) for _ in range(30)]
        serie = {"A": {i: 40 + b * 0.003 for i, b in enumerate(base)},
                 "B": {i: 62 + b * 0.004 + rnd.gauss(0, 0.0005) for i, b in enumerate(base)},
                 "C": {i: 80 + rnd.gauss(0, 0.003) for i in range(30)}}
        numero, legami = spc.famiglie(serie)
        self.assertEqual(numero["A"], numero["B"])
        self.assertNotIn("C", numero)
        self.assertGreater(legami["A"][0][1], 0.9)

    def test_kruskal(self):
        rnd = random.Random(9)
        uguali = spc.kruskal({"OP1": [rnd.gauss(0, 1) for _ in range(20)], "OP2": [rnd.gauss(0, 1) for _ in range(20)]})
        diversi = spc.kruskal({"OP1": [rnd.gauss(0, 1) for _ in range(20)], "OP2": [rnd.gauss(2, 1) for _ in range(20)]})
        self.assertGreater(uguali["p"], 0.05)
        self.assertLess(diversi["p"], 0.001)
        self.assertIsNone(spc.kruskal({"OP1": [1, 2, 3, 4, 5]}))
        self.assertAlmostEqual(spc._gammq(1.0, 2.0), math.exp(-2.0), places=9)   # Q(1, x) = e^-x

    def test_ripetibilita(self):
        r = spc.ripetibilita([0.001, -0.002, 0.0015, -0.001, 0.0005], 0.025)
        s = math.sqrt((1 + 4 + 2.25 + 1 + 0.25) * 1e-6 / 10)
        self.assertAlmostEqual(r["sigma"], s, places=12)
        self.assertAlmostEqual(r["pct"], 6 * s / 0.025 * 100, places=9)
        self.assertIsNone(spc.ripetibilita([0.001] * 4, 0.025))


class UgualeAlJavaScriptTests(SimpleTestCase):
    """Le stesse serie calcolate da spc.py e da spc.js (con Node, se c'è) devono dare gli stessi numeri."""

    def test_stessi_numeri(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node non disponibile")
        casi = [
            {"xs": _serie(11, 35, 40.0125, 0.003), "lsl": 40.0, "usl": 40.025, "nom": 40.0},
            {"xs": _serie(12, 30, 40.004, 0.002, trend=0.0002), "lsl": 40.0, "usl": 40.025, "nom": 40.0},
            {"xs": [round(0.005 * random.Random(13).weibullvariate(1, 1.8) + 0.0001 * i, 5) for i in range(40)],
             "lsl": 0.0, "usl": 0.02, "nom": 0.0},
            {"xs": _serie(14, 40, 10, 0.01, salto=(25, 0.012)), "lsl": 9.95, "usl": 10.05, "nom": 10.0},
        ]
        script = JS.read_text(encoding="utf-8") + "\nconst casi = " + json.dumps(casi) + ";\n" + """
const out = casi.map(c => {
  const cap = SPC.capacita(c.xs, c.lsl, c.usl, c.nom);
  return {cpk: cap.cpk, ppk: cap.ppk, basso: cap.cpk_basso, metodo: cap.metodo, verdetto: cap.verdetto,
          segnali: SPC.segnali(c.xs).map(g => [String(g.regola), g.da, g.a]),
          rischio: SPC.rischio_prossimo(c.xs, c.lsl, c.usl, c.nom), cambi: SPC.punti_cambio(c.xs).map(p => p.indice),
          deriva: SPC.deriva(c.xs.map(x => SPC.usata(x, c.nom, c.lsl, c.usl)))};
});
console.log(JSON.stringify(out));
"""
        r = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        js = json.loads(r.stdout)
        for c, j in zip(casi, js):
            cap = spc.capacita(c["xs"], c["lsl"], c["usl"], c["nom"])
            for k_py, k_js in (("cpk", "cpk"), ("ppk", "ppk"), ("cpk_basso", "basso")):
                self.assertAlmostEqual(cap[k_py], j[k_js], places=6, msg=(k_py, c["xs"][:3]))
            self.assertEqual((cap["metodo"], cap["verdetto"]), (j["metodo"], j["verdetto"]))
            self.assertEqual([[str(g["regola"]), g["da"], g["a"]] for g in spc.segnali(c["xs"])], j["segnali"])
            self.assertAlmostEqual(spc.rischio_prossimo(c["xs"], c["lsl"], c["usl"], c["nom"]), j["rischio"], places=6)
            self.assertEqual([p["indice"] for p in spc.punti_cambio(c["xs"])], j["cambi"])
            d = spc.deriva([spc.usata(x, c["nom"], c["lsl"], c["usl"]) for x in c["xs"]])
            self.assertEqual(d is None, j["deriva"] is None)
            if d:
                self.assertEqual((d["pezzi"], d["verso"], d["pezzi_min"], d["pezzi_max"]),
                                 (j["deriva"]["pezzi"], j["deriva"]["verso"], j["deriva"]["pezzi_min"], j["deriva"]["pezzi_max"]))
                self.assertAlmostEqual(d["pendenza"], j["deriva"]["pendenza"], places=9)
