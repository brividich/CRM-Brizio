from django.test import SimpleTestCase

from automazioni.services import errore_cooldown


class PausaScrittaMaleTests(SimpleTestCase):
    """Audit P16: una pausa scritta male si ferma al salvataggio."""

    def test_valori_buoni(self):
        for valore in ("mail_anomalie_op:5", "5", " gruppo : 30 "):
            self.assertEqual(errore_cooldown(valore), "", valore)

    def test_valori_sbagliati(self):
        for valore in ("5m", "gruppo:", "gruppo:cinque", "", "gruppo:0", "gruppo:-3"):
            self.assertIn("Pausa scritta male", errore_cooldown(valore), valore)
