"""Pannello attività della commessa: striscia del tempo, aggiunta rapida, controlli sul posto."""
from __future__ import annotations

from datetime import date, timedelta

from django.test import override_settings
from django.urls import reverse

from tasks.models import Task, TaskStatus
from tasks.services.striscia import striscia_commessa
from tasks.tests_utils import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
    make_project,
)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class PannelloAttivitaTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.pm = _create_user_with_legacy(username="pa-pm", legacy_user_id=551, role_id=2, role_name="tasks")
        self.resp = _create_user_with_legacy(username="pa-resp", legacy_user_id=552, role_id=2, role_name="tasks")
        self.project = make_project(name="Commessa pannello", created_by=self.pm, project_manager=self.pm)
        self.project.add_team_member("programmers", self.resp)
        self.url = reverse("tasks:project_actions", args=[self.project.pk])
        oggi = date(2026, 11, 20)
        self.oggi = oggi
        self.mia = Task.objects.create(
            title="Programma CAM", project=self.project, created_by=self.pm, assigned_to=self.resp,
            next_step_due=oggi + timedelta(days=3), due_date=oggi + timedelta(days=14),
        )
        self.altrui = Task.objects.create(
            title="Ordine materiale", project=self.project, created_by=self.pm, assigned_to=self.pm,
            due_date=oggi - timedelta(days=1),
        )

    def test_chi_gestisce_la_commessa_ha_i_controlli_su_ogni_attivita(self):
        self.client.force_login(self.pm)
        pagina = self.client.get(self.url)
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, "data-ka-stato", count=2)
        self.assertContains(pagina, "data-ka-fine", count=2)
        self.assertContains(pagina, 'class="ka-rapida"')
        self.assertContains(pagina, "Linea del tempo")

    def test_l_incaricato_ha_i_controlli_solo_sulla_sua_attivita(self):
        self.client.force_login(self.resp)
        pagina = self.client.get(self.url)
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, "data-ka-stato", count=1)
        self.assertContains(pagina, reverse("tasks:mia_voce_stato", args=["attivita", self.mia.pk]))
        self.assertNotContains(pagina, reverse("tasks:mia_voce_stato", args=["attivita", self.altrui.pk]))
        self.assertNotContains(pagina, 'class="ka-rapida"')

    def test_l_aggiunta_rapida_torna_al_pannello(self):
        self.client.force_login(self.pm)
        risposta = self.client.post(
            reverse("tasks:project_quick_task", args=[self.project.pk]),
            {"title": "Scelta utensili", "assigned_to": str(self.resp.pk), "due_date": "2026-12-11", "next": self.url},
        )
        self.assertRedirects(risposta, self.url, fetch_redirect_response=False)
        self.assertTrue(self.project.tasks.filter(title="Scelta utensili", assigned_to=self.resp).exists())

    def test_l_aggiunta_rapida_non_segue_un_indirizzo_esterno(self):
        self.client.force_login(self.pm)
        risposta = self.client.post(
            reverse("tasks:project_quick_task", args=[self.project.pk]),
            {"title": "Altra attività", "next": "https://example.com/tasks/"},
        )
        self.assertTrue(risposta["Location"].startswith(reverse("tasks:project_gantt", args=[self.project.pk])))

    def test_la_striscia_colloca_barre_oggi_e_ritardi(self):
        striscia = striscia_commessa(self.project, self.oggi, evidenzia=self.mia.pk)
        per_titolo = {r["task"].title: r for r in striscia["righe"]}
        self.assertEqual(per_titolo["Ordine materiale"]["classe"], "is-ritardo")
        self.assertEqual(per_titolo["Programma CAM"]["classe"], "")
        self.assertTrue(per_titolo["Programma CAM"]["evidenziata"])
        for riga in striscia["righe"]:
            self.assertGreaterEqual(riga["sinistra"], 0)
            self.assertLessEqual(riga["sinistra"] + riga["larghezza"], 100.01)
        self.assertTrue(0 <= striscia["oggi"] <= 100)
        # Il periodo parte di lunedì: la prima etichetta è l'inizio della settimana.
        self.assertEqual(striscia["settimane"][0]["etichetta"].weekday(), 0)

    def test_senza_date_la_striscia_non_c_e(self):
        Task.objects.filter(project=self.project).update(due_date=None, next_step_due=None)
        self.assertIsNone(striscia_commessa(self.project, self.oggi))
        self.client.force_login(self.pm)
        pagina = self.client.get(self.url)
        self.assertContains(pagina, "ka-striscia is-vuota")
        self.assertNotContains(pagina, "ka-striscia-riga")

    def test_le_attivita_annullate_non_hanno_controlli(self):
        self.mia.status = TaskStatus.CANCELED
        self.mia.save()
        self.client.force_login(self.pm)
        pagina = self.client.get(self.url + "?closed=1")
        self.assertNotContains(pagina, reverse("tasks:mia_voce_stato", args=["attivita", self.mia.pk]))
