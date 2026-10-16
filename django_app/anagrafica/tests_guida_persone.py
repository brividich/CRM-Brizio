"""Guida «persone e account» dentro il portale. Dati sintetici."""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

User = get_user_model()
URL = "anagrafica:guida_persone_account"
TEMPLATES = Path(__file__).resolve().parent / "templates" / "anagrafica"


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class GuidaPersoneTests(TestCase):
    def test_utente_vede_solo_l_elenco(self):
        # Un utente senza profilo legacy finirebbe sull'onboarding del portale: si simula l'assenza
        # del permesso di gestione dell'anagrafica.
        self.client.force_login(User.objects.create_superuser("guida.base", "guida.base@example.invalid", "x"))
        with patch("anagrafica.views._is_anagrafica_admin", return_value=False):
            r = self.client.get(reverse(URL))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="elenco"')
        self.assertContains(r, 'id="capo"')
        self.assertNotContains(r, 'id="coerenza-capi"')
        self.assertNotContains(r, 'id="avviso-it"')
        self.assertNotContains(r, "Per amministratori del portale e IT")

    def test_admin_vede_anche_gestione_e_it(self):
        self.client.force_login(User.objects.create_superuser("guida.admin", "guida.admin@example.invalid", "x"))
        r = self.client.get(reverse(URL))
        for ancora in ("capo", "coerenza-capi", "viste", "nuovo-dipendente", "account-portale", "amministrazione", "ad", "avviso-it", "dopo-il-deploy"):
            self.assertContains(r, f'id="{ancora}"')

    def test_ogni_pulsante_guida_punta_a_un_paragrafo_esistente(self):
        self.client.force_login(User.objects.create_superuser("guida.admin2", "guida.admin2@example.invalid", "x"))
        html = self.client.get(reverse(URL)).content.decode()
        ancore = set()
        for pagina in TEMPLATES.rglob("*.html"):
            ancore |= set(re.findall(r'_guida_persone_link\.html" with ancora="([\w-]+)"', pagina.read_text("utf-8")))
        self.assertGreaterEqual(len(ancore), 6)
        for ancora in ancore:
            self.assertIn(f'id="{ancora}"', html, ancora)

    def test_pulsante_nell_hub_e_nel_nuovo_dipendente(self):
        self.client.force_login(User.objects.create_superuser("guida.admin3", "guida.admin3@example.invalid", "x"))
        guida = reverse(URL)
        self.assertContains(self.client.get(reverse("anagrafica:amministrazione_hub")), guida + "#amministrazione")
        self.assertContains(self.client.get(reverse("anagrafica:dipendente_create")), guida + "#nuovo-dipendente")
        self.assertContains(self.client.get(reverse("anagrafica:coerenza_capi")), guida + "#coerenza-capi")

    def test_anonimo_va_al_login(self):
        self.assertEqual(self.client.get(reverse(URL)).status_code, 302)
