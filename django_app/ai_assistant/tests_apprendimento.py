"""Il registro con cui i copiloti imparano dalle decisioni delle persone."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from ai_assistant.apprendimento import lezioni, lezioni_testo, registra_decisione, registra_proposta, stesso_valore
from ai_assistant.models import AiProposta


class ApprendimentoTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="impara")

    def _giro(self, ref, proposto, deciso):
        registra_proposta(modulo="m", azione="a", oggetto_ref=ref, proposta={"gravita": proposto}, user=self.user)
        return registra_decisione(modulo="m", azione="a", oggetto_ref=ref, decisione={"gravita": deciso}, user=self.user)

    def test_accettata_corretta_scartata(self):
        self.assertEqual(self._giro(1, "MINORE", "minore").esito, AiProposta.ACCETTATA)
        registra_proposta(modulo="m", azione="a", oggetto_ref=2, proposta={"gravita": "MINORE", "tipo": "Bava"})
        p = registra_decisione(modulo="m", azione="a", oggetto_ref=2, decisione={"gravita": "MAGGIORE", "tipo": "Bava"})
        self.assertEqual((p.esito, p.campi_corretti), (AiProposta.MODIFICATA, ["gravita"]))
        self.assertEqual(self._giro(3, "MINORE", "CRITICA").esito, AiProposta.SCARTATA)

    def test_senza_proposta_non_impara_nulla_e_vale_solo_l_ultima(self):
        self.assertIsNone(registra_decisione(modulo="m", azione="a", oggetto_ref=9, decisione={"gravita": "X"}))
        registra_proposta(modulo="m", azione="a", oggetto_ref=9, proposta={"gravita": "MINORE"})
        registra_proposta(modulo="m", azione="a", oggetto_ref=9, proposta={"gravita": "MAGGIORE"})
        p = registra_decisione(modulo="m", azione="a", oggetto_ref=9, decisione={"gravita": "MAGGIORE"})
        self.assertEqual(p.esito, AiProposta.ACCETTATA)
        self.assertEqual(AiProposta.objects.filter(esito=AiProposta.SUPERATA).count(), 1)
        self.assertIsNone(registra_decisione(modulo="m", azione="a", oggetto_ref=9, decisione={"gravita": "MINORE"}))

    def test_testi_ed_elenchi_riformulati_contano_come_accettati(self):
        self.assertTrue(stesso_valore("Utensile usurato per mancata sostituzione programmata",
                                      "utensile usurato: mancata sostituzione programmata dell'inserto"))
        self.assertFalse(stesso_valore("Utensile usurato", "Errore di lettura del disegno"))
        self.assertTrue(stesso_valore(["Sostituire l'utensile ogni 200 pezzi", "Formare l'operatore sul controllo"],
                                      ["sostituire utensile ogni 200 pezzi lavorati"]))

    def test_le_correzioni_ripetute_diventano_lezioni(self):
        for ref in range(4):
            self._giro(ref, "MINORE", "MAGGIORE")
        self._giro(10, "MINORE", "MINORE")
        dati = lezioni("m", "a", etichette={"gravita": "gravità"})
        self.assertEqual((dati["totale"], dati["accettate"], dati["percentuale_accettate"]), (5, 1, 20))
        self.assertEqual(dati["correzioni"][0], {"campo": "gravità", "proposto": "MINORE", "scelto": "MAGGIORE", "volte": 4})
        testo = lezioni_testo("m", "a", etichette={"gravita": "gravità"})
        self.assertIn("proponevi «MINORE», le persone hanno scelto «MAGGIORE» (4 volte)", testo)

    def test_poche_decisioni_nessuna_lezione(self):
        self._giro(1, "MINORE", "MAGGIORE")
        self.assertEqual(lezioni_testo("m", "a"), "")
