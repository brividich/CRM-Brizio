"""Selezione multipla e pannello di anteprima nel codice comune (core/js/hub-bulk-pannello.js).

Il SOC li usa senza inizializzarli una seconda volta: soc-ui.js tiene solo barra live,
sezioni vive e suggerimenti.
"""
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse


def _statico(percorso):
    trovato = finders.find(percorso)
    assert trovato, percorso
    return Path(trovato).read_text(encoding="utf-8")


class CodiceComuneTests(TestCase):
    def test_js_comune_conserva_le_correzioni(self):
        js = _statico("core/js/hub-bulk-pannello.js")
        self.assertIn("window.HubBulkPannello", js)
        # Un campo name="action" nel form sovrascrive form.action: l'URL si legge con getAttribute.
        self.assertIn('form.getAttribute("action")', js)
        self.assertNotIn("fetch(form.action", js)
        # Le caselle fuori dal form (attributo form=) contano nella selezione.
        self.assertIn('.sec-bulk-item[form="', js)
        self.assertIn("[data-drawer-host], .soc-module", js)

    def test_soc_ui_non_reinizializza(self):
        js = _statico("security/soc-ui.js")
        for doppione in ("function initBulk", "soc-drawer-panel", 'document.addEventListener("click"', "data-drawer-form"):
            self.assertNotIn(doppione, js)
        self.assertIn("HubBulkPannello", js)

    def test_css_comune_neutro_con_tema_scuro(self):
        css = _statico("core/css/hub-bulk-pannello.css")
        self.assertNotIn(".soc-module", css)
        for regola in (".sec-bulk-bar", ".sec-check-col", ".soc-drawer-panel", ".pv-facts", "body.theme-dark .soc-drawer-panel"):
            self.assertIn(regola, css)
        soc = _statico("security/soc-live.css") + _statico("security/security.css")
        self.assertNotIn(".soc-module .sec-bulk-bar {", soc)
        self.assertNotIn(".soc-drawer-panel {", soc)


class CaricamentoTests(TestCase):
    def setUp(self):
        cache.clear()
        user = get_user_model().objects.create(username="soc_comune_user", is_staff=True, is_superuser=True)
        self.client.force_login(user)

    def test_soc_carica_comune_una_volta_e_soc_ui(self):
        page = self.client.get(reverse("security:tickets_list"))
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        self.assertEqual(html.count("core/js/hub-bulk-pannello.js"), 1)
        self.assertEqual(html.count("core/css/hub-bulk-pannello.css"), 1)
        self.assertIn("security/soc-ui.js", html)
