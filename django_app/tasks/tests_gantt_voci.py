"""Gantt con incontri, azioni, problemi, programmi e FAI (09/11/2026)."""
from __future__ import annotations

from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from tasks.models import (
    KickoffMeeting,
    MeetingActionItem,
    MeetingActionStatus,
    MeetingStatus,
    ProjectTechRef,
    Task,
    TaskStatus,
)
from tasks.services.gantt_voci import gantt_voci
from tasks.tests_utils import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
    make_project,
)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class GanttVociTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.pm = _create_user_with_legacy(username="gv-pm", legacy_user_id=711, role_id=2, role_name="tasks")
        self.project = make_project(name="Commessa voci", created_by=self.pm, project_manager=self.pm)
        self.oggi = timezone.localdate()
        self.cam = Task.objects.create(title="Programmazione CAM", project=self.project, created_by=self.pm,
                                       next_step_due=self.oggi, due_date=self.oggi + timedelta(days=3))
        self.client.force_login(self.pm)

    def test_voce_legata_a_attivita_aperta_va_sulla_sua_riga(self):
        ProjectTechRef.objects.create(project=self.project, kind="CAM", code="OP10", task=self.cam)
        MeetingActionItem.objects.create(project=self.project, title="Azione libera", due_date=self.oggi + timedelta(days=2))
        dati = gantt_voci(self.project, [self.cam])
        self.assertEqual([v["titolo"] for v in dati["per_attivita"][self.cam.id]], ["OP10"])
        self.assertEqual([v["titolo"] for v in dati["voci"]], ["Azione libera"])

    def test_chiuse_e_annullati_restano_fuori(self):
        MeetingActionItem.objects.create(project=self.project, title="Fatta", status=MeetingActionStatus.DONE)
        KickoffMeeting.objects.create(project=self.project, data=self.oggi, created_by=self.pm,
                                      stato=MeetingStatus.ANNULLATO, titolo="Saltato")
        dati = gantt_voci(self.project, [self.cam])
        self.assertEqual(dati["voci"], [])
        self.assertEqual(dati["incontri"], [])

    def test_voce_di_attivita_chiusa_torna_riga_propria(self):
        self.cam.status = TaskStatus.DONE
        self.cam.save()
        # Il programma senza codice resta «da inserire» anche ad attività chiusa:
        # non ha più una barra aperta che lo porti, quindi ha una riga sua.
        ProjectTechRef.objects.create(project=self.project, kind="CAM", task=self.cam)
        dati = gantt_voci(self.project, [self.cam])
        self.assertEqual([v["titolo"] for v in dati["voci"]], ["da inserire"])
        self.assertEqual(dati["per_attivita"], {})

    def test_pagina_mostra_incontri_e_scadenze_e_allarga_il_periodo(self):
        lontano = self.oggi + timedelta(days=60)
        KickoffMeeting.objects.create(project=self.project, data=lontano, created_by=self.pm, titolo="Riesame finale")
        MeetingActionItem.objects.create(project=self.project, title="Scaduta ieri", due_date=self.oggi - timedelta(days=1))
        html = self.client.get(reverse("tasks:project_gantt", args=[self.project.id])).content.decode()
        self.assertIn("Riesame finale", html)
        self.assertIn('class="gmeet', html)
        self.assertIn("Scaduta ieri", html)
        self.assertIn("gmile gmile--azione scaduta", html)
        self.assertIn("1 scadenza da incontri, programmi e FAI", html)
        risposta = self.client.get(reverse("tasks:project_gantt", args=[self.project.id]))
        self.assertGreaterEqual(risposta.context["gantt_timeline_end"], lontano)

    def test_senza_attivita_le_scadenze_si_vedono_lo_stesso(self):
        self.cam.delete()
        MeetingActionItem.objects.create(project=self.project, title="Unica voce", due_date=self.oggi + timedelta(days=5))
        html = self.client.get(reverse("tasks:project_gantt", args=[self.project.id])).content.decode()
        self.assertIn("Unica voce", html)
