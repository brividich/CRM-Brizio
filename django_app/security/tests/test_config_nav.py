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

    def test_one_menu_entry_and_tabs_on_settings_page(self):
        html = self.client.get(reverse("security:soc_settings")).content.decode()
        menu = html.split('<nav class="soc-nav"', 1)[1].split("</nav>", 1)[0]
        self.assertIn(">Configurazione</a>", menu)
        for old in (">Config</a>", ">Autoconfig</a>", ">Impostazioni</a>", ">Caselle mail</a>"):
            self.assertNotIn(old, menu)
        self.assertIn('class="soc-config-tabs"', html)
        self.assertIn('aria-current="page">Avvisi e automatismi</a>', html)

    def test_tabs_on_config_dashboard_and_not_on_work_pages(self):
        self.assertIn('aria-current="page">Panoramica</a>', self.client.get(reverse("security:admin_config")).content.decode())
        self.assertNotIn('class="soc-config-tabs"', self.client.get(reverse("security:alerts_list")).content.decode())

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
