"""«Organizzazione», pagina d'ingresso della sezione: numeri, collegamenti diretti, cose da fare.

Scenario di ``tests_richieste``: bianchi responsabile di rossi, neri RDD, verdi MSO.
"""
from __future__ import annotations

from unittest import mock

from django.urls import reverse

from .models import SubnavLinkAnagrafica
from .models_richieste import RichiestaCompetenze as R
from .services import organizzazione_panoramica as svc
from .services import struttura_vista as vista
from .tests_richieste import _Scenario

URL = "anagrafica:organizzazione"


class PanoramicaTests(_Scenario):
    def _come(self, attore, user=None):
        self.client.force_login(user or attore.user)
        return mock.patch("anagrafica.services.richieste.attore", return_value=attore)

    def test_chi_vede_la_struttura_ha_numeri_tessere_e_nota(self):
        with self._come(self.hr, self.admin):
            r = self.client.get(reverse(URL))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "{#")
        numeri = {x["nome"]: x for x in r.context["numeri"]}
        self.assertEqual(list(numeri), ["Centri di costo", "Reparti", "Aree", "Ruoli", "Mansioni", "Competenze",
                                        "Persone in forza"])
        # Stessi numeri della pagina «Struttura organizzativa», a cui portano.
        mansioni = vista._mansioni()
        kpi = vista.kpi(vista.albero(mansioni), vista.processi(mansioni), vista.ruoli(mansioni), mansioni)
        self.assertEqual((numeri["Reparti"]["n"], numeri["Aree"]["n"], numeri["Ruoli"]["n"], numeri["Mansioni"]["n"]),
                         (kpi["reparti"], kpi["aree"], kpi["ruoli"], kpi["mansioni"]))
        self.assertEqual(numeri["Centri di costo"]["n"], 1)
        tessere = [t["nome"] for t in r.context["collegamenti"]]
        self.assertEqual(tessere, ["Esplora la struttura", "Mansioni", "Richieste", "Reparti e capi", "Centri di costo",
                                   "Organigramma", "Prova un cambiamento", "Struttura e revisioni"])
        self.assertIn("bozza", r.context["nota"])
        self.assertContains(r, "Collegamenti diretti")
        for t in r.context["collegamenti"]:
            self.assertEqual(self.client.get(t["url"]).status_code, 200, t["nome"])

    def test_da_fare_mostra_solo_cio_che_aspetta(self):
        with self._come(self.rdd):
            self.assertNotIn("Richieste da approvare", [x["titolo"] for x in self.client.get(reverse(URL)).context["da_fare"]])
        self._ram()
        with self._come(self.rdd):
            righe = self.client.get(reverse(URL)).context["da_fare"]
        self.assertEqual((righe[0]["titolo"], righe[0]["n"], righe[0]["urgente"], righe[0]["azione"]),
                         ("Richieste da approvare", 1, True, "Decidi"))
        self.assertTrue(all(x["n"] for x in righe))
        with self._come(self.capo):
            r = self.client.get(reverse(URL))
        self.assertEqual([x["titolo"] for x in r.context["da_fare"]], ["Le mie richieste in attesa di altri"])
        self.assertTrue(r.context["puo_chiedere"])
        self.assertContains(r, reverse("anagrafica:richiesta_nuova"))

    def test_chi_non_vede_la_struttura_non_ha_numeri(self):
        with self._come(self.estraneo), mock.patch("anagrafica.views_mansionario._puo_vedere", return_value=False):
            r = self.client.get(reverse(URL))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["numeri"], [])
        self.assertEqual(r.context["nota"], "")
        self.assertEqual(r.context["da_fare"], [])
        self.assertContains(r, "Niente da fare in questa sezione.")
        self.assertFalse(r.context["puo_chiedere"])
        richieste = next(t for t in r.context["collegamenti"] if t["nome"] == "Richieste")
        self.assertEqual(richieste["etichetta"], "0 aperte")
        self.assertEqual(next(t for t in r.context["collegamenti"] if t["nome"] == "Mansioni")["etichetta"], "")

    def test_la_tessera_richieste_conta_le_aperte_visibili(self):
        richiesta = self._ram()
        with self._come(self.rdd):
            tessera = next(t for t in self.client.get(reverse(URL)).context["collegamenti"] if t["nome"] == "Richieste")
        self.assertEqual((tessera["etichetta"], tessera["attesa"]), ("1 aperta", 1))
        from .services import richieste as rq

        rq.decidi(self.rdd, richiesta, approva=False, nota="no")
        self.assertEqual(R.objects.get().stato, R.STATO_RESPINTA)
        with self._come(self.rdd):
            tessera = next(t for t in self.client.get(reverse(URL)).context["collegamenti"] if t["nome"] == "Richieste")
        self.assertEqual((tessera["etichetta"], tessera["attesa"]), ("0 aperte", 0))

    def test_le_tessere_seguono_i_permessi(self):
        with self._come(self.hr, self.admin), \
                mock.patch.object(svc, "_puo_aprire", side_effect=lambda request, url: "mansionario" in url):
            tessere = [t["nome"] for t in self.client.get(reverse(URL)).context["collegamenti"]]
        self.assertEqual(tessere, ["Mansioni"])

    def test_voce_di_menu_prima_del_pilastro(self):
        voce = SubnavLinkAnagrafica.objects.get(url_value=URL)
        struttura = SubnavLinkAnagrafica.objects.get(url_value="anagrafica:struttura_org")
        self.assertEqual((voce.etichetta, voce.categoria_id, voce.gruppo), ("Panoramica", struttura.categoria_id, struttura.gruppo))
        prima = SubnavLinkAnagrafica.objects.filter(categoria_id=voce.categoria_id, is_active=True).order_by("ordine", "id").first()
        self.assertEqual(prima.url_value, URL)
