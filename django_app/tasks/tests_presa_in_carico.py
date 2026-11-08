"""Chi riceve un'attivita': mail, «Le mie azioni», chiusura dal responsabile, sollecito del lunedi'.

Revisione dell'08/11/2026: prima l'assegnazione arrivava solo come notifica
nel portale, «Le mie azioni» non mostrava le attivita' del piano e il digest
del lunedi' ignorava le attivita' scadute.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from tasks.models import Task, TaskStatus
from tasks.tests_utils import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
    make_project,
)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False, SITE_URL="https://hub.example.com")
class PresaInCaricoTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.pm = _create_user_with_legacy(username="pic-pm", legacy_user_id=511, role_id=2, role_name="tasks")
        self.pm.email = "pm@example.com"
        self.pm.save(update_fields=["email"])
        self.resp = _create_user_with_legacy(username="pic-resp", legacy_user_id=512, role_id=2, role_name="tasks")
        self.resp.email = "resp@example.com"
        self.resp.save(update_fields=["email"])
        self.project = make_project(name="Commessa prova", created_by=self.pm, project_manager=self.pm)

    def _task(self, **kwargs):
        dati = {"title": "Programmare la macchina", "project": self.project, "created_by": self.pm,
                "assigned_to": self.resp}
        dati.update(kwargs)
        return Task.objects.create(**dati)

    def test_assegnazione_manda_la_mail_al_responsabile(self):
        from tasks.services.meeting_tasks import crea_attivita_rapida

        crea_attivita_rapida(
            project=self.project, user=self.pm, title="Preparare il collaudo",
            assigned_to=self.resp, due_date=timezone.localdate() + timedelta(days=5),
        )
        self.assertEqual(len(mail.outbox), 1)
        messaggio = mail.outbox[0]
        self.assertEqual(messaggio.to, ["resp@example.com"])
        self.assertIn("Preparare il collaudo", messaggio.subject)
        self.assertIn("https://hub.example.com/tasks/mie-azioni/", messaggio.body)

    def test_chi_si_assegna_da_solo_non_riceve_la_mail(self):
        from tasks.services.meeting_tasks import crea_attivita_rapida

        crea_attivita_rapida(project=self.project, user=self.resp, title="Mia", assigned_to=self.resp)
        self.assertEqual(mail.outbox, [])

    def test_le_mie_azioni_mostra_le_attivita_assegnate(self):
        self._task(title="Attività mia")
        self._task(title="Attività di altri", assigned_to=self.pm)
        self.client.force_login(self.resp)
        pagina = self.client.get(reverse("tasks:mie_azioni"))
        self.assertContains(pagina, "Attività mia")
        self.assertNotContains(pagina, "Attività di altri")
        self.assertContains(pagina, ">Inizia<")

    def test_il_responsabile_la_prende_in_carico_e_la_chiude(self):
        task = self._task()
        self.client.force_login(self.resp)
        url = reverse("tasks:mia_voce_stato", args=["attivita", task.pk])
        self.client.post(url, {"action": "start"})
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)
        self.client.post(url, {"action": "done"})
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.DONE)
        self.assertEqual(task.progress, 100)
        pagina = self.client.get(reverse("tasks:mie_azioni"))
        self.assertNotContains(pagina, "Programmare la macchina")

    def test_chi_non_e_responsabile_non_la_chiude(self):
        task = self._task(assigned_to=self.pm)
        self.client.force_login(self.resp)
        self.client.post(reverse("tasks:mia_voce_stato", args=["attivita", task.pk]), {"action": "done"})
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.TODO)

    def test_digest_del_lunedi_comprende_le_attivita(self):
        from tasks.tasks import run_meetings_digest

        lunedi = date(2026, 11, 9)
        self._task(title="Scaduta da giorni", due_date=lunedi - timedelta(days=3))
        self._task(title="Scade giovedi", due_date=lunedi + timedelta(days=3))
        self._task(title="Scade tra un mese", due_date=lunedi + timedelta(days=30))
        mail.outbox = []
        with patch("django.utils.timezone.localdate", return_value=lunedi):
            run_meetings_digest()
        mie = [m for m in mail.outbox if m.to == ["resp@example.com"]]
        self.assertEqual(len(mie), 1)
        self.assertIn("Attività scadute a te assegnate", mie[0].body)
        self.assertIn("Scaduta da giorni", mie[0].body)
        self.assertIn("Scade giovedi", mie[0].body)
        self.assertNotIn("Scade tra un mese", mie[0].body)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class GanttPaginaTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.pm = _create_user_with_legacy(username="gp-pm", legacy_user_id=521, role_id=2, role_name="tasks")
        self.project = make_project(name="Commessa gantt", created_by=self.pm, project_manager=self.pm)
        oggi = timezone.localdate()
        Task.objects.create(title="Prima", project=self.project, created_by=self.pm, next_step_due=oggi,
                            due_date=oggi + timedelta(days=2))
        self.client.force_login(self.pm)

    def test_form_baseline_non_annidati_nel_form_della_finestra(self):
        html = self.client.get(reverse("tasks:project_gantt", args=[self.project.id])).content.decode()
        inizio = html.index('id="g-finestra"')
        fine = html.index("</form>", inizio)
        self.assertNotIn("baseline", html[inizio:fine])
        self.assertIn(reverse("tasks:project_gantt_fix_baseline", args=[self.project.id]), html)
        self.assertNotIn("Â·", html)

    def test_form_nuova_attivita_mette_prima_l_essenziale(self):
        html = self.client.get(reverse("tasks:create") + f"?project={self.project.id}").content.decode()
        self.assertIn("Cosa, chi e quando", html)
        self.assertLess(html.index('name="assigned_to"'), html.index('name="description"'))
