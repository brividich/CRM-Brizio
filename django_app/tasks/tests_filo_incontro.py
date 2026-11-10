"""Filo dell'incontro: problemi, azioni e decisioni legati al punto da cui nascono.

Copre la cattura dalla conduzione con il punto, la chiusura al volo (JSON) di
problemi e azioni riportati, la scelta del punto nell'esito, le fasi in testa
alle pagine e il punto nel registro azioni.
"""
from __future__ import annotations

from django.test import override_settings
from django.urls import reverse

from tasks.action_register import build_project_actions
from tasks.models import (
    KickoffMeeting,
    MeetingActionItem,
    MeetingAgendaItem,
    MeetingDecision,
    MeetingIssue,
    MeetingIssueStatus,
)
from tasks.services.agenda import _meeting_action_agenda_item, _meeting_issue_agenda_item
from tasks.tests_utils import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
    make_project,
)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class FiloIncontroTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(username="filo-pm", legacy_user_id=411, role_id=2, role_name="tasks")
        self.project = make_project(name="Filo", created_by=self.user, project_manager=self.user)
        self.previous = KickoffMeeting.objects.create(project=self.project, data="2026-09-01", created_by=self.user)
        self.issue = MeetingIssue.objects.create(project=self.project, source_meeting=self.previous, title="Foro fuori tolleranza")
        self.action = MeetingActionItem.objects.create(project=self.project, source_meeting=self.previous, title="Chiedere deroga")
        self.meeting = KickoffMeeting.objects.create(
            project=self.project,
            data="2026-09-10",
            created_by=self.user,
            agenda_items=[
                {"id": "p1", "titolo": "Materiali", "nota": "", "done": False},
                _meeting_issue_agenda_item(self.issue),
                _meeting_action_agenda_item(self.action),
            ],
        )
        self.client.force_login(self.user)
        self.capture_url = reverse("tasks:project_meeting_quick_capture", args=[self.project.pk, self.meeting.pk])

    def _ajax(self, url, data):
        return self.client.post(url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_cattura_dal_punto_lega_il_problema(self):
        response = self._ajax(self.capture_url, {"kind": "issue", "titolo": "Grezzo corto", "item_id": "p1"})
        data = response.json()
        self.assertTrue(data["ok"])
        issue = MeetingIssue.objects.get(title="Grezzo corto")
        self.assertEqual(issue.punto, "p1")
        self.assertEqual(data["voce"]["punto_num"], 1)

    def test_punto_inesistente_non_viene_salvato(self):
        self._ajax(self.capture_url, {"kind": "decision", "titolo": "Cinque assi", "item_id": "nessuno"})
        self.assertEqual(MeetingDecision.objects.get(testo="Cinque assi").punto, "")

    def test_attivita_dal_punto_si_collega_al_punto(self):
        data = self._ajax(self.capture_url, {"kind": "task", "titolo": "Ordina grezzo", "item_id": "p1"}).json()
        self.assertTrue(data["task_collegata"])
        self.assertEqual(MeetingAgendaItem.objects.get(meeting=self.meeting, item_id="p1").task_id, data["id"])

    def test_problema_riportato_si_chiude_dalla_conduzione(self):
        url = reverse("tasks:project_meeting_issue_status", args=[self.project.pk, self.meeting.pk, self.issue.pk])
        data = self._ajax(url, {"action": "resolve"}).json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["chiusa"])
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.status, MeetingIssueStatus.RESOLVED)
        self.assertTrue(MeetingAgendaItem.objects.get(meeting=self.meeting, issue=self.issue).done)

    def test_azione_riportata_chiusa_segna_il_punto(self):
        url = reverse("tasks:project_meeting_action_status", args=[self.project.pk, self.meeting.pk, self.action.pk])
        data = self._ajax(url, {"action": "done"}).json()
        self.assertTrue(data["chiusa"])
        self.assertTrue(MeetingAgendaItem.objects.get(meeting=self.meeting, action=self.action).done)
        self._ajax(url, {"action": "reopen"})
        self.assertFalse(MeetingAgendaItem.objects.get(meeting=self.meeting, action=self.action).done)

    def test_redirect_torna_alla_pagina_di_partenza_solo_se_interna(self):
        url = reverse("tasks:project_meeting_action_status", args=[self.project.pk, self.meeting.pk, self.action.pk])
        run = reverse("tasks:project_meeting_run", args=[self.project.pk, self.meeting.pk])
        self.assertRedirects(self.client.post(url, {"action": "done", "next": run}), run, fetch_redirect_response=False)
        detail = reverse("tasks:project_meeting_detail", args=[self.project.pk, self.meeting.pk])
        response = self.client.post(url, {"action": "reopen", "next": "https://esempio.invalid/"})
        self.assertRedirects(response, detail, fetch_redirect_response=False)

    def test_conduzione_mostra_registro_e_voci_del_punto(self):
        MeetingIssue.objects.create(project=self.project, source_meeting=self.meeting, title="Bava sul bordo", punto="p1")
        page = self.client.get(reverse("tasks:project_meeting_run", args=[self.project.pk, self.meeting.pk]))
        self.assertContains(page, "Registro dell'incontro")
        self.assertContains(page, "Problemi trovati")
        self.assertEqual(page.content.decode().count('data-voce="issue-'), 3)  # sotto il punto, nel registro, il problema riportato
        self.assertContains(page, 'class="mfasi"')

    def test_esito_registra_il_punto_dei_nuovi_problemi(self):
        url = reverse("tasks:project_meeting_minutes", args=[self.project.pk, self.meeting.pk])
        self.client.post(url, {"note": "", "new_issue_title": ["Staffa storta"], "new_issue_punto": ["p1"],
                               "new_decision_testo": ["Rifare staffa"], "new_decision_punto": ["inesistente"]})
        self.assertEqual(MeetingIssue.objects.get(title="Staffa storta").punto, "p1")
        self.assertEqual(MeetingDecision.objects.get(testo="Rifare staffa").punto, "")

    def test_registro_azioni_riporta_il_punto(self):
        MeetingIssue.objects.create(project=self.project, source_meeting=self.meeting, title="Bava", punto="p1")
        rows = {row.title: row for row in build_project_actions(self.project)}
        self.assertIn("punto 1 «Materiali»", rows["Bava"].source_label)
        self.assertEqual(rows["Foro fuori tolleranza"].source_label, f"Incontro {self.previous.numero}")
