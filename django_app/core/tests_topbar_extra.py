"""Topbar: griglia Moduli, Preferiti (stesso salvataggio della home), Suggestion Corner come icona."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from core.context_processors import NavItem, _group_nav_items
from core.models import UserOnboarding, UserUiPreference
from core.topbar_extra import DESCRIZIONI, arricchisci_topbar, id_preferito

User = get_user_model()


def voce(label, codice, href, cat="", group="", order=10, active=False):
    return NavItem(
        label=label, legacy_url="", href=href, active=active, coming=False, modulo="", codice=codice, group=group,
        order_hint=order, category_key=cat, category_label=cat.capitalize() if cat else "", category_order=order,
    )


class IdPreferitoTests(SimpleTestCase):
    def test_modulo_del_catalogo_usa_l_id_della_home(self):
        self.assertEqual(id_preferito(voce("Anagrafica", "anagrafica", reverse("anagrafica:index"))), "anagrafica")

    def test_altra_voce_usa_il_codice(self):
        self.assertEqual(id_preferito(voce("Carichi", "carichi-macchina", "/carichi/")), "nav:carichi-macchina")


class ArricchisciTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("topbar_u", "topbar@example.invalid", "x")

    def _risultato(self, voci):
        request = RequestFactory().get("/")
        request.user = self.user
        result = {"topbar_groups": _group_nav_items(voci)}
        arricchisci_topbar(request, result)
        return result

    def test_griglia_con_aree_e_voci_dirette(self):
        res = self._risultato([
            voce("KICK-OFF", "tasks", "/tasks/", cat="produzione", group="Commesse"),
            voce("Scadenzario", "scadenzario", "/scadenze/", order=78),
        ])
        griglia = res["topbar_griglia"]
        self.assertEqual([a["label"] for a in griglia["aree"]], ["Produzione"])
        self.assertEqual([v["label"] for v in griglia["dirette"]], ["Scadenzario"])

    def test_preferiti_nell_ordine_salvato_e_solo_tra_le_voci_visibili(self):
        UserUiPreference.objects.create(
            user=self.user, home_prefs={"preferiti": ["nav:scadenzario", "nav:non-visibile", "nav:tasks"]},
        )
        res = self._risultato([
            voce("Pianificazione", "tasks", "/fuori-catalogo/", cat="produzione"),
            voce("Scadenzario", "scadenzario", "/scadenze/", order=78),
        ])
        self.assertEqual([v["label"] for v in res["topbar_griglia"]["preferiti"]], ["Scadenzario", "Pianificazione"])

    def test_suggestion_corner_diventa_icona(self):
        res = self._risultato([voce("Suggestion Corner", "suggestion-corner", "/sc/", order=80)])
        self.assertEqual(res["topbar_icona_suggerimenti"].href, "/sc/")
        self.assertTrue(res["topbar_groups"][0]["in_icona"])

    def test_descrizione_sulla_voce(self):
        item = voce("DPI", "dpi", "/dpi/", cat="sicurezza")
        self._risultato([item])
        self.assertEqual(item.descrizione, DESCRIZIONI["dpi"])


class StellaSalvataggioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser("topbar_star", "star@example.invalid", "x")
        UserOnboarding.objects.update_or_create(user=cls.user, defaults={"completed": True})

    def test_voce_fuori_catalogo_si_salva_e_la_home_la_ignora(self):
        from dashboard.views_home_portale import _preferiti

        self.client.force_login(self.user)
        r = self.client.post(reverse("home_portale:index"), {"azione": "preferito", "modulo": "nav:carichi-macchina", "on": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        salvati = UserUiPreference.objects.get(user=self.user).home_prefs["preferiti"]
        self.assertEqual(salvati, ["nav:carichi-macchina"])
        self.assertEqual(_preferiti([], salvati), [])
