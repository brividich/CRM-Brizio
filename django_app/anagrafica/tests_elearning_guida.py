"""Guida d'uso dell'e-learning nel portale. Dati sintetici."""
from __future__ import annotations

import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.urls import reverse

from .tests_elearning_pro import _Pro

User = get_user_model()
URL = "anagrafica:formazione_online_guida"
PAGINE = Path(__file__).resolve().parent / "templates" / "anagrafica" / "pages"


class GuidaElearningTests(_Pro):
    def test_discente_vede_solo_la_sua_parte(self):
        r = self.client.get(reverse(URL))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="discente"')
        self.assertContains(r, 'id="verifica"')
        self.assertNotContains(r, 'id="regole"')
        self.assertNotContains(r, "Per HR e RSPP")

    def test_hr_vede_anche_la_parte_di_gestione(self):
        self.client.force_login(User.objects.create_superuser("guida.hr", "guida@example.invalid", "x"))
        r = self.client.get(reverse(URL))
        self.assertContains(r, "Per HR e RSPP")
        self.assertContains(r, 'id="regole"')

    def test_ogni_pulsante_guida_punta_a_un_paragrafo_esistente(self):
        self.client.force_login(User.objects.create_superuser("guida.hr2", "guida2@example.invalid", "x"))
        html = self.client.get(reverse(URL)).content.decode()
        ancore = set()
        for pagina in PAGINE.glob("*.html"):
            ancore |= set(re.findall(r'_elearning_guida_link\.html" with ancora="([\w-]+)"', pagina.read_text("utf-8")))
        self.assertGreaterEqual(len(ancore), 6)
        for ancora in ancore:
            self.assertIn(f'id="{ancora}"', html, ancora)

    def test_pulsante_nel_catalogo(self):
        r = self.client.get(reverse("anagrafica:formazione_online_catalog"))
        self.assertContains(r, reverse(URL) + "#discente")

    def test_anonimo_va_al_login(self):
        self.client.logout()
        r = self.client.get(reverse(URL))
        self.assertEqual(r.status_code, 302)
