"""Nome mostrato sulle richieste di assenza: formato unico, dato SharePoint intatto."""
from unittest import mock

from django.test import SimpleTestCase

from assenze import views


class ApplicaNominativoTests(SimpleTestCase):
    def test_collegata_a_utente_mostra_nominativo_anagrafica(self):
        rows = [{"dipendente": "Mario Rossi", "utente_id": 5}]
        with mock.patch.object(views, "_nominativi_per_utente", return_value={5: "ROSSI MARIO"}):
            views._applica_nominativo(rows)
        self.assertEqual(rows[0]["dipendente"], "ROSSI MARIO")

    def test_senza_collegamento_mostra_testo_salvato_in_maiuscolo(self):
        rows = [{"dipendente": "verdi  anna"}]
        with mock.patch.object(views, "_nominativi_per_utente", return_value={}):
            views._applica_nominativo(rows)
        self.assertEqual(rows[0]["dipendente"], "VERDI ANNA")

    def test_campo_vuoto_resta_vuoto(self):
        rows = [{"dipendente": None, "utente_id": None}]
        with mock.patch.object(views, "_nominativi_per_utente", return_value={}):
            views._applica_nominativo(rows)
        self.assertEqual(rows[0]["dipendente"], "")
