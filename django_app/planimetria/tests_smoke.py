"""Smoke test delle pagine principali di Planimetria.

Le viste di `planimetria` sono alias che reindirizzano alle pagine di `assets`:
per l'admin la catena di redirect deve chiudersi con un 200 sulla pagina
`assets`; per l'anonimo nessuna pagina deve essere servita (redirect al login
o 401/403).
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

PAGINE = (
    ("planimetria:mappa", "assets:plant_layout_map"),
    ("planimetria:editor", "assets:plant_layout_editor"),
)


class PlanimetriaSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = get_user_model().objects.create_superuser(
            username="planimetria_smoke_admin",
            email="planimetria-smoke@example.com",
            password="smoke-test-pwd",
        )

    def test_admin_apre_le_pagine_principali(self):
        self.client.force_login(self.admin_user)
        for nome, destinazione in PAGINE:
            with self.subTest(pagina=nome):
                response = self.client.get(reverse(nome), follow=True)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.redirect_chain, "attesa redirect verso assets")
                self.assertEqual(response.redirect_chain[-1][0], reverse(destinazione))

    def test_anonimo_non_vede_le_pagine(self):
        for nome, _destinazione in PAGINE:
            with self.subTest(pagina=nome):
                response = self.client.get(reverse(nome))
                self.assertIn(response.status_code, (302, 401, 403))
                if response.status_code == 302:
                    self.assertIn("login", response["Location"].lower())
