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

    def test_meeting_form_renders_percorso(self):
        from tasks.models import Project

        project = Project.objects.create(name="", created_by=self.admin)
        resp = self.client.get(reverse("tasks:project_meeting_create", args=[project.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8")
        self.assertIn("kp-rail", body)
        self.assertIn('data-title="Dettagli"', body)
        self.assertIn('data-title="Notifiche"', body)
        # l'agenda builder (JS) resta presente
        self.assertIn('id="agenda-add-btn"', body)

    def test_vrf_forms_render_lifecycle_stepper(self):
        from tasks.models import Project

        project = Project.objects.create(name="", created_by=self.admin)
        for url_name in ("tasks:project_vrf_upload", "tasks:project_vrf_compile"):
            resp = self.client.get(reverse(url_name, args=[project.id]))
            self.assertEqual(resp.status_code, 200, url_name)
            self.assertIn("kp-steps", resp.content.decode("utf-8"), url_name)
