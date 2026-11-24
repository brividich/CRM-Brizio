"""Home più leggera: «Le mie attività» caricato dopo la pagina, bacheca in cache."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import mock


from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from dashboard import views_home_portale as hp


class BachecaCacheTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def _request(self, ruolo=3):
        legacy = SimpleNamespace(id=7, ruolo_id=ruolo)
        return SimpleNamespace(user=SimpleNamespace(is_superuser=False), legacy_user=legacy)

    @override_settings(HOME_BACHECA_CACHE_SECONDS=300)
    def test_stesso_ruolo_non_ricalcola(self):
        with mock.patch.object(hp, "is_legacy_admin", return_value=False), \
                mock.patch.object(hp, "_documenti_collegamenti_calcola", return_value=[{"name": "A"}]) as calcolo:
            primo = hp._documenti_collegamenti(self._request())
            secondo = hp._documenti_collegamenti(self._request())
        self.assertEqual(primo, secondo)
        self.assertEqual(calcolo.call_count, 1)

    @override_settings(HOME_BACHECA_CACHE_SECONDS=300)
    def test_ruolo_diverso_e_modifica_ricalcolano(self):
        with mock.patch.object(hp, "is_legacy_admin", return_value=False), \
                mock.patch.object(hp, "_documenti_collegamenti_calcola", return_value=[]) as calcolo:
            hp._documenti_collegamenti(self._request(ruolo=3))
            hp._documenti_collegamenti(self._request(ruolo=4))
            hp.bacheca_cache_invalida()  # un documento salvato
            hp._documenti_collegamenti(self._request(ruolo=3))
        self.assertEqual(calcolo.call_count, 3)

    @override_settings(HOME_BACHECA_CACHE_SECONDS=0)
    def test_zero_spegne_la_cache(self):
        with mock.patch.object(hp, "is_legacy_admin", return_value=False), \
                mock.patch.object(hp, "_documenti_collegamenti_calcola", return_value=[]) as calcolo:
            hp._documenti_collegamenti(self._request())
            hp._documenti_collegamenti(self._request())
        self.assertEqual(calcolo.call_count, 2)


class NomiUtenteMemoTests(SimpleTestCase):
    def test_nomi_calcolati_una_volta_per_richiesta(self):
        from anomalie import views as av

        request = SimpleNamespace(legacy_user=SimpleNamespace(id=5, nome="Mario"), user=None)
        with mock.patch.object(av, "_calcola_user_name_norms", return_value={"mario"}) as calcolo:
            for _ in range(5):
                self.assertEqual(av._current_user_name_norms(request), {"mario"})
        self.assertEqual(calcolo.call_count, 1)


class HomeDifferitaViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="adm_diff", email="d@a.it", password="x")
        self.client.force_login(self.user)

    @override_settings(HOME_MIE_ATTIVITA_DIFFERITA=True)
    def test_home_mostra_il_segnaposto_e_non_calcola(self):
        with mock.patch("dashboard.views_mie_attivita.build_cose_da_gestire", side_effect=AssertionError("calcolato")):
            r = self.client.get(reverse("home_portale:index"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, reverse("home_portale:mie_attivita_blocco"))
        self.assertContains(r, 'id="hs-tab-oggi-n"')

    def test_blocco_porta_le_attivita_e_il_numero_della_linguetta(self):
        dati = {"sections": [], "total": 4, "overdue": 1, "soon": 0}
        with mock.patch("dashboard.views_mie_attivita.build_cose_da_gestire", return_value=dati):
            r = self.client.get(reverse("home_portale:mie_attivita_blocco"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "data-ma")
        self.assertContains(r, 'hx-swap-oob="true"')
        self.assertContains(r, "<sup>4</sup>")

    @override_settings(HOME_MIE_ATTIVITA_DIFFERITA=False)
    def test_spenta_torna_come_prima(self):
        r = self.client.get(reverse("home_portale:index"))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, reverse("home_portale:mie_attivita_blocco"))
