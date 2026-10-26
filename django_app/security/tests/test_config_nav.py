"""Configurazione: una voce di menu e le sezioni come schede su ogni pagina di configurazione."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from security.templatetags import security_config_nav as nav


class ConfigNavTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="soc_config_nav", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)

    def test_one_menu_entry_and_five_tabs(self):
        html = self.client.get(reverse("security:soc_settings")).content.decode()
        menu = html.split('<nav class="soc-tabs"', 1)[1].split("</nav>", 1)[0]
        sub = html.split('<nav class="soc-subnav"', 1)[1].split("</nav>", 1)[0]
        self.assertIn("<span>Impostazioni</span>", menu)  # una sola voce di menu per tutta la configurazione
        self.assertIn('aria-current="page">Avvisi e automatismi</a>', sub)
        # le sezioni si aprono dalla Panoramica: niente 15 schede su due righe (6 con il Battito del SOC)
        self.assertEqual(sub.count("<a "), 6)
        self.assertIn(">Battito del SOC</a>", sub)
        self.assertNotIn(">Caselle mail</a>", sub)
        self.assertEqual(html.count('class="soc-subnav"'), 1)

    def test_panoramica_per_compito_e_percorso_nelle_pagine_interne(self):
        page = self.client.get(reverse("security:admin_config")).content.decode()
        self.assertIn('aria-current="page">Panoramica</a>', page)
        for titolo in ("Da dove arrivano i dati", "Cosa diventa un alert", "Chi viene avvisato", "Controllo e manutenzione"):
            self.assertIn(titolo, page)
        self.assertIn("Nessun canale di notifica attivo", page)  # «Da sistemare»
        interna = self.client.get(reverse("security:admin_config_notifications")).content.decode()
        self.assertIn('class="soc-crumb"', interna)
        self.assertIn("<strong>Canali di notifica</strong>", interna)
        self.assertIn('aria-current="page">Panoramica</a>', interna)
        self.assertNotIn('class="soc-crumb"', self.client.get(reverse("security:alerts_list")).content.decode())

    def test_every_tab_route_exists(self):
        for route, _label, names, _admin in nav.CONFIG_TABS:
            reverse(f"security:{route}")
            self.assertIn(route, names)

    def test_viewer_without_config_permission_sees_only_settings(self):
        request = RequestFactory().get("/")
        request.user = self.user
        with patch.object(nav, "can_manage_security_config", return_value=False):
            self.assertEqual(nav.soc_config_home_url({"request": request}), reverse("security:soc_settings"))
            tabs = nav.soc_config_tabs({"request": request}, "soc_settings")
        self.assertEqual([t["label"] for t in tabs["tabs"]], ["Avvisi e automatismi"])
        self.assertFalse(tabs["show"])
