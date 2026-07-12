"""Smoke-render dei form del modulo migrati al componente 'percorso' (kp-).

Verifica solo che le pagine rendano (200) e contengano il markup delle tappe,
così un errore di template/campo emerge subito.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class PercorsoRenderTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin_px", email="admin_px@example.com", password="x"
        )
        self.client.force_login(self.admin)

    def test_project_create_renders_percorso(self):
        resp = self.client.get(reverse("tasks:project_create"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8")
        self.assertIn("kp-station", body)
        self.assertIn("kp-rail", body)
        self.assertIn('data-title="Identificazione"', body)
