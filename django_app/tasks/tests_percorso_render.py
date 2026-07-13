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

    def test_nessun_entrypoint_globale_per_creare_attivita(self):
        """Modulo solo-kickoff: nessun bottone «Nuova attività» fuori da un kickoff.

        Ogni link a `tasks:create` deve portare il kickoff nel querystring (?project=),
        altrimenti si offre di nuovo la creazione di un'attività "sciolta".
        """
        from pathlib import Path

        tpl_dir = Path(__file__).resolve().parent / "templates" / "tasks"
        offenders = []
        for tpl in sorted(tpl_dir.glob("*.html")):
            if tpl.name == "form.html":
                continue  # è il form di creazione stesso, non un entry-point
            for num, line in enumerate(tpl.read_text(encoding="utf-8").splitlines(), 1):
                if "url 'tasks:create'" in line and "project=" not in line:
                    offenders.append(f"{tpl.name}:{num}")
        self.assertEqual(offenders, [], f"entry-point globali per creare attività: {offenders}")

    def test_task_create_form_is_kickoff_only(self):
        resp = self.client.get(reverse("tasks:create"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8")
        # niente più selettore "attività singola" / scope single per un nuovo task
        self.assertNotIn("Attivita singola", body)
        self.assertNotIn('value="single"', body)
        # il pannello di aggancio kickoff è presente (task sempre dentro un kickoff)
        self.assertIn("Aggancio e anagrafica kickoff", body)

    def test_task_detail_renders(self):
        from tasks.models import Project, Task

        p = Project.objects.create(name="", created_by=self.admin)
        t = Task.objects.create(title="Task UI", project=p, created_by=self.admin)
        resp = self.client.get(reverse("tasks:detail", args=[t.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("task-detail-layout", resp.content.decode("utf-8"))

    def test_portfolio_page_renders(self):
        from tasks.models import Project

        Project.objects.create(name="", created_by=self.admin, client_name="ACME", part_number="PN1")
        resp = self.client.get(reverse("tasks:project_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("pf-card", resp.content.decode("utf-8"))

    def test_vrf_forms_render_lifecycle_stepper(self):
        from tasks.models import Project

        project = Project.objects.create(name="", created_by=self.admin)
        for url_name in ("tasks:project_vrf_upload", "tasks:project_vrf_compile"):
            resp = self.client.get(reverse(url_name, args=[project.id]))
            self.assertEqual(resp.status_code, 200, url_name)
            self.assertIn("kp-steps", resp.content.decode("utf-8"), url_name)
