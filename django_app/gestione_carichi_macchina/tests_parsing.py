"""Test della grammatica di parsing cella (funzioni pure, niente DB)."""
from django.test import SimpleTestCase

from .parsing import build_vocabolario, parse_cell, parse_cicli, scegli_famiglia


class ParseCellTest(SimpleTestCase):
    def test_qta_ore_famiglia(self):
        p = parse_cell("8 gimbal 6F (33h)")
        self.assertEqual(p.qta, 8)
        self.assertEqual(p.ore, 33)
        self.assertEqual(p.operazioni, [])
        self.assertFalse(p.macchina_ferma)
        self.assertIn("gimbal", p.tokens)

    def test_fase_finitura(self):
        p = parse_cell("2 koala fin")
        self.assertEqual(p.qta, 2)
        self.assertEqual(p.fase, "fin")
        self.assertEqual(p.tokens, ["koala"])

    def test_fase_sgrossatura(self):
        p = parse_cell("5 musetti 109 sgr")
        self.assertEqual(p.qta, 5)
        self.assertEqual(p.fase, "sgr")
        self.assertEqual(p.tokens, ["musetti"])

    def test_operazioni_e_assemblaggio(self):
        p = parse_cell("ass (op3+4)")
        self.assertIsNone(p.qta)
        self.assertEqual(p.fase, "ass")
        self.assertEqual(p.operazioni, [3, 4])

    def test_operazione_singola(self):
        p = parse_cell("6 Bas Inf Yamaha (op2)")
        self.assertEqual(p.qta, 6)
        self.assertEqual(p.operazioni, [2])
        self.assertEqual(p.tokens, ["yamaha"])  # bas/inf scartati (len<4)

    def test_pezzi_non_ore(self):
        # il numero iniziale sono PEZZI (informativi), non ore
        p = parse_cell("4 coperchi koala")
        self.assertEqual(p.qta, 4)
        self.assertIsNone(p.ore)

    def test_pezzi_con_prefisso_n_e_ore_esplicite(self):
        p = parse_cell("N°5 Sup.Aprilia (4°OP) 30h")
        self.assertEqual(p.qta, 5)        # N°5 = pezzi
        self.assertEqual(p.ore, 30)       # 30h = ore
        self.assertIn(4, p.operazioni)    # 4°OP

    def test_numero_iniziale_di_operazione_non_e_qta(self):
        p = parse_cell("2°op Bas 4pz")
        self.assertEqual(p.qta, 4)        # 4pz = pezzi, NON il 2 dell'operazione
        self.assertIn(2, p.operazioni)

    def test_macchina_ferma(self):
        for testo in ("DM3 guasto", "in manutenzione", "ferma per revisione"):
            p = parse_cell(testo)
            self.assertTrue(p.macchina_ferma, testo)
            self.assertIsNone(p.qta)

    def test_cella_vuota(self):
        p = parse_cell("")
        self.assertIsNone(p.qta)
        self.assertEqual(p.tokens, [])


class VocabolarioTest(SimpleTestCase):
    def test_due_passate_sceglie_token_noto(self):
        celle = [
            "8 gimbal (33h)", "4 gimbal sgr", "2 gimbal fin", "1 gimbal",
            "3 koala", "5 musetti",
        ]
        noti, freq = build_vocabolario(celle, min_freq=4)
        self.assertIn("gimbal", noti)
        self.assertNotIn("koala", noti)  # freq < 4

        p = parse_cell("7 gimbal koala (10h)")
        self.assertEqual(scegli_famiglia(p, noti, freq), "gimbal")

    def test_fallback_primo_token(self):
        noti, freq = build_vocabolario(["1 sombrero", "1 ragni"], min_freq=4)
        p = parse_cell("2 campane nuove")
        # nessun token noto -> fallback al primo token
        self.assertEqual(scegli_famiglia(p, noti, freq), "campane")

    def test_macchina_ferma_niente_famiglia(self):
        noti, freq = build_vocabolario(["1 gimbal"], min_freq=1)
        p = parse_cell("guasto")
        self.assertIsNone(scegli_famiglia(p, noti, freq))


class CicliTest(SimpleTestCase):
    def test_parse_cicli(self):
        lines = [
            "CICLI APRILIA:",
            "* BAS SUP",
            "op1 MZ3 = 550 cent/cad",
            "op4 DM10 (MK3) = 750 cent/cad",
            "MG finte teste = 70 cent/cad",
            "* BAS INF",
            "op1 DM11 (DM3) = 300 cent/cad",
        ]
        cicli = parse_cicli(lines)
        self.assertEqual(len(cicli), 2)
        bas_sup = cicli[0]
        self.assertEqual(bas_sup["cliente"], "APRILIA")
        self.assertEqual(bas_sup["pezzo"], "BAS SUP")
        self.assertEqual(len(bas_sup["operazioni"]), 2)
        op4 = bas_sup["operazioni"][1]
        self.assertEqual((op4["seq"], op4["macchina"], op4["regola"], op4["tempo"]),
                         (4, "DM10", "MK3", 750))
        self.assertIn("MG finte teste = 70 cent/cad", bas_sup["note"])
        self.assertEqual(cicli[1]["pezzo"], "BAS INF")
