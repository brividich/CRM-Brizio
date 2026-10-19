"""Home personalizzata: preferiti, stanza di apertura, riquadri nascosti, tour."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import UserUiPreference
from dashboard import views_home_portale as hp


class PulisciPrefsTests(TestCase):
    def test_valori_non_validi_scartati(self):
        p = hp._pulisci_home_prefs({
            "preferiti": ["ticket", "ticket", "", None, "x" * 80],
            "stanza": "cantina",
            "nascosti": ["news", "boh"],
            "tour_visto": 1,
        })
        self.assertEqual(p["preferiti"], ["ticket", "x" * 40])
        self.assertEqual(p["stanza"], "")
        self.assertEqual(p["nascosti"], ["news"])
        self.assertTrue(p["tour_visto"])

    def test_non_dizionario(self):
        self.assertEqual(hp._pulisci_home_prefs(None)["preferiti"], [])

    def test_preferiti_solo_moduli_accessibili_nell_ordine_scelto(self):
        groups = [{"modules": [
            {"id": "ticket", "accessible": True, "url": "/tickets/"},
            {"id": "anomalie", "accessible": True, "url": "/anomalie/"},
            {"id": "segreto", "accessible": False, "url": "/x/"},
        ]}]
        ids = [m["id"] for m in hp._preferiti(groups, ["anomalie", "segreto", "sparito", "ticket"])]
        self.assertEqual(ids, ["anomalie", "ticket"])


class HomePrefsViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="adm", email="a@a.it", password="x")
        self.client.force_login(self.user)
        self.url = reverse("home_portale:index")

    def _prefs(self):
        return UserUiPreference.objects.get(user=self.user).home_prefs

    def test_preferito_aggiunto_e_tolto(self):
        r = self.client.post(self.url, {"azione": "preferito", "modulo": "ticket", "on": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["prefs"]["preferiti"], ["ticket"])
        self.client.post(self.url, {"azione": "preferito", "modulo": "ticket", "on": "0"})
        self.assertEqual(self._prefs()["preferiti"], [])

    def test_limite_preferiti(self):
        UserUiPreference.objects.create(
            user=self.user, home_prefs={"preferiti": [f"m{i}" for i in range(hp.PREFERITI_MAX)]}
        )
        r = self.client.post(self.url, {"azione": "preferito", "modulo": "nuovo", "on": "1"})
        self.assertEqual(r.status_code, 400)

    def test_personalizza_stanza_e_riquadri(self):
        r = self.client.post(self.url, {"azione": "personalizza", "stanza": "moduli", "mostra": ["azioni"]})
        self.assertEqual(r.status_code, 200)
        p = self._prefs()
        self.assertEqual(p["stanza"], "moduli")
        self.assertEqual(p["nascosti"], ["brief", "news"])
        resp = self.client.get(self.url)
        self.assertContains(resp, 'data-hs-stanza="moduli"')
        self.assertNotContains(resp, "News aziendali</h3>")

    def test_tour_visto(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'data-hs-tour="nuovo"')
        self.client.post(self.url, {"azione": "tour_visto"})
        self.assertContains(self.client.get(self.url), 'data-hs-tour="visto"')

    def test_azione_sconosciuta(self):
        self.assertEqual(self.client.post(self.url, {"azione": "boh"}).status_code, 400)

    def test_home_mostra_stelle_e_pannello(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, "data-hs-star=")
        self.assertContains(resp, "Personalizza la home")
        self.assertContains(resp, "I miei preferiti")


class NewsHomeTests(TestCase):
    """Le news della home leggono stato/pubblicato_il e rispettano il pubblico."""

    def setUp(self):
        from django.utils import timezone

        from notizie.models import STATO_BOZZA, STATO_PUBBLICATA, Notizia, NotiziaAudience

        self.user = get_user_model().objects.create_superuser(username="adm", email="a@a.it", password="x")
        self.client.force_login(self.user)
        ora = timezone.now()
        Notizia.objects.create(titolo="Mensa chiusa venerdì", corpo="x", stato=STATO_PUBBLICATA, pubblicato_il=ora)
        Notizia.objects.create(titolo="Bozza riservata", corpo="x", stato=STATO_BOZZA)
        ristretta = Notizia.objects.create(titolo="Solo per un ruolo", corpo="x", stato=STATO_PUBBLICATA, pubblicato_il=ora)
        NotiziaAudience.objects.create(notizia=ristretta, legacy_role_id=999)

    def test_news_pubblicate_visibili(self):
        resp = self.client.get(reverse("home_portale:index"))
        self.assertContains(resp, "Mensa chiusa venerdì")
        self.assertNotContains(resp, "Bozza riservata")
        self.assertNotContains(resp, "Solo per un ruolo")
