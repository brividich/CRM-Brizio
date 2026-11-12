from django.test import SimpleTestCase

from fornitori.nomi import chiave_ditta, unico


class ChiaveDittaTests(SimpleTestCase):
    def test_stessa_ditta_scritta_in_modi_diversi(self):
        base = chiave_ditta("Rossi Impianti")
        for variante in ("ROSSI IMPIANTI S.R.L.", "Rossi Impianti srl", "Rossi  Impianti S.r.l.s.",
                         "rossi impianti, s.p.a.", "Rossi Impianti Snc", "Rossì Impianti"):
            self.assertEqual(chiave_ditta(variante), base, variante)

    def test_ditte_diverse_restano_diverse(self):
        self.assertNotEqual(chiave_ditta("Rossi Impianti"), chiave_ditta("Rossi Impianti Elettrici"))
        self.assertNotEqual(chiave_ditta("Bianchi & C."), chiave_ditta("Bianchi Costruzioni"))

    def test_nome_fatto_solo_di_forma_non_diventa_vuoto(self):
        self.assertEqual(chiave_ditta("S.r.l."), "s r l")
        self.assertEqual(chiave_ditta(""), "")
        self.assertEqual(chiave_ditta(None), "")

    def test_unico(self):
        coppie = [(1, "Rossi Impianti SRL"), (2, "Verdi Spa"), (3, "VERDI S.P.A.")]
        self.assertEqual(unico(chiave_ditta("rossi impianti"), coppie), 1)
        self.assertIsNone(unico(chiave_ditta("Verdi"), coppie))  # due fornitori: ambiguo
        self.assertIsNone(unico(chiave_ditta("Neri"), coppie))
