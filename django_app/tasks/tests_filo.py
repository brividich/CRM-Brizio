"""Filo kickoff → incontro → attività: creazione guidata, ODG dalle tappe, assegnazione in riunione, prossimi passi."""
from __future__ import annotations

from datetime import date, time, timedelta
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import KickoffMeeting, MeetingRoom, MeetingStatus, Project, Task
from .services.filo import prossimi_passi
from .tests_utils import TasksBaseTestCase, _create_user_with_legacy, _ensure_role, _grant_role_actions, make_project


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class FiloBase(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(username="filo-pm", legacy_user_id=911, role_id=2, role_name="tasks")
        self.client.force_login(self.user)
        patcher = patch("tasks.services.meeting_tasks._mail_assegnazione")
        patcher.start()
        self.addCleanup(patcher.stop)

    def crea_kickoff(self, pn: str, **extra):
        dati = {
            "client_name": "Cliente", "part_number": pn, "revisione": "A", "versione": "1.0", "description": "",
            "control_method": "", "vrf_quote_number": "", "vrf_description": "", "vrf_esp": "",
            "project_managers": [self.user.id],
        }
        dati.update(extra)
        return self.client.post(reverse("tasks:project_create"), dati)


class CreazioneGuidataTests(FiloBase):
    def test_cosa_serve_e_primo_incontro(self):
        sala = MeetingRoom.objects.create(nome="Sala Filo", email="sala.filo@example.com")
        self.crea_kickoff(
            "PN-FILO-1", tappe_presenti="1", tappe_servono=["MATERIALI", "CAM", "MACCHINA", "FAI"],
            primo_data="2026-12-03", primo_ora="09:30", primo_sala=str(sala.pk),
        )
        project = Project.objects.get(part_number="PN-FILO-1")
        self.assertEqual(project.tappe_escluse, ["CMM", "ATTREZZATURA", "UTENSILI", "TERZISTA", "PROCESSI"])
        m = project.meetings.get()
        self.assertEqual((m.data, m.ora, m.sala, m.luogo), (date(2026, 12, 3), time(9, 30), sala, "Sala Filo"))
        fonti = [i["source"] for i in m.agenda_items]
        self.assertEqual(fonti, ["tappa:MATERIALI", "tappa:CAM", "tappa:MACCHINA", "tappa:FAI"])

    def test_senza_campi_nuovi_non_cambia_nulla(self):
        self.crea_kickoff("PN-FILO-2")
        project = Project.objects.get(part_number="PN-FILO-2")
        self.assertEqual(project.tappe_escluse, [])
        self.assertEqual(project.meetings.get().data, timezone.localdate())

    def test_modifica_commessa_aggiorna_cosa_serve(self):
        _grant_role_actions(2, ["tasks_view", "tasks_create", "tasks_edit"])
        self._refresh_acl_cache()
        self.crea_kickoff("PN-FILO-3")
        project = Project.objects.get(part_number="PN-FILO-3")
        dati = {
            "client_name": "Cliente", "part_number": "PN-FILO-3", "revisione": "A", "versione": "1.0",
            "description": "", "control_method": "", "vrf_quote_number": "", "vrf_description": "", "vrf_esp": "",
            "project_managers": [self.user.id], "tappe_presenti": "1",
            "tappe_servono": ["MATERIALI", "CAM", "CMM", "MACCHINA", "ATTREZZATURA", "UTENSILI", "FAI"],
        }
        self.client.post(reverse("tasks:project_edit", args=[project.pk]), dati)
        project.refresh_from_db()
        self.assertEqual(project.tappe_escluse, ["TERZISTA", "PROCESSI"])

    def test_form_mostra_le_nuove_tappe(self):
        pagina = self.client.get(reverse("tasks:project_create"))
        self.assertContains(pagina, "Cosa serve a questa commessa")
        self.assertContains(pagina, "Primo incontro")


class OdgERiunioneTests(FiloBase):
    def setUp(self):
        super().setUp()
        self.project = make_project(name="Commessa filo", created_by=self.user, project_manager=self.user)
        self.project.tappe_escluse = ["TERZISTA", "PROCESSI", "CMM", "FAI"]
        self.project.save()

    def test_nuovo_incontro_propone_le_tappe_aperte(self):
        pagina = self.client.get(reverse("tasks:project_meeting_create", args=[self.project.pk]))
        self.assertIn("tappa:MATERIALI", pagina.context["form"].initial["agenda_items_raw"])
        self.assertNotIn("tappa:TERZISTA", pagina.context["form"].initial["agenda_items_raw"])

    def test_assegna_la_tappa_dal_punto_in_riunione(self):
        from .services.tappe import agenda_items

        m = KickoffMeeting.objects.create(
            project=self.project, data=date(2026, 12, 3), created_by=self.user, agenda_items=agenda_items(self.project),
        )
        punto = next(i for i in m.agenda_items if i["source"] == "tappa:MATERIALI")
        risposta = self.client.post(
            reverse("tasks:project_meeting_agenda_item_task_create", args=[self.project.pk, m.pk]),
            {"item_id": punto["id"], "title": "", "assigned_to": self.user.pk, "due_date": "2026-12-20"},
        )
        self.assertEqual(risposta.status_code, 200, risposta.content)
        task = Task.objects.get(pk=risposta.json()["task_id"])
        self.assertEqual(task.category.tappa, "MATERIALI")
        self.assertTrue(task.description.startswith(f"Dall'incontro #{m.numero} ("))
        m.refresh_from_db()
        self.assertEqual(next(i for i in m.agenda_items if i["id"] == punto["id"])["task_id"], task.pk)

    def test_conduzione_mostra_assegna_la_tappa(self):
        from .services.tappe import agenda_items

        m = KickoffMeeting.objects.create(
            project=self.project, data=date(2026, 12, 3), created_by=self.user, agenda_items=agenda_items(self.project),
        )
        pagina = self.client.get(reverse("tasks:project_meeting_run", args=[self.project.pk, m.pk]))
        self.assertContains(pagina, "Assegna la tappa")
        self.assertContains(pagina, 'data-role="task-new-asset"')


class ProssimiPassiTests(FiloBase):
    def setUp(self):
        super().setUp()
        self.project = make_project(name="Commessa passi", created_by=self.user, project_manager=self.user)

    def titoli(self, **kw):
        return [p["titolo"] for p in prossimi_passi(self.project, limite=10, **kw)]

    def test_senza_incontri(self):
        self.assertIn("Pianifica il primo incontro", self.titoli())

    def test_incontro_passato_da_registrare(self):
        KickoffMeeting.objects.create(project=self.project, data=timezone.localdate() - timedelta(days=2), created_by=self.user)
        self.assertEqual(self.titoli()[0], "Registra l'esito dell'incontro 1")

    def test_incontro_futuro_da_convocare(self):
        KickoffMeeting.objects.create(project=self.project, data=timezone.localdate() + timedelta(days=5), created_by=self.user)
        self.assertIn("Convoca l'incontro 1", self.titoli())

    def test_svolto_minuta_e_prossimo(self):
        KickoffMeeting.objects.create(
            project=self.project, data=timezone.localdate() - timedelta(days=3), stato=MeetingStatus.SVOLTO, created_by=self.user,
        )
        titoli = self.titoli()
        self.assertIn("Approva la minuta dell'incontro 1", titoli)
        self.assertIn("Pianifica il prossimo incontro", titoli)

    def test_tappe_da_assegnare(self):
        from .services.tappe import percorso

        titoli = self.titoli(tappe=percorso(self.project))
        self.assertIn("Assegna 9 tappe del percorso", titoli)

    def test_panoramica_mostra_i_passi(self):
        pagina = self.client.get(reverse("tasks:project_overview", args=[self.project.pk]))
        self.assertContains(pagina, "Prossimi passi")
        self.assertContains(pagina, 'id="percorso"')
