"""Copilota KICK-OFF: commesse simili, punti proposti (AI mockata) e apprendimento dalla minuta."""
from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from ai_assistant.models import AiProposta
from tasks import ai_kickoff
from tasks.models import GanttBaseline, KickoffMeeting, MeetingIssue, MeetingIssueStatus, MeetingStatus, Task
from tasks.tests import TasksBaseTestCase, _create_user_with_legacy, _ensure_role, _grant_role_actions

from .tests_utils import make_project

CHAT = "ai_assistant.services.chat_with_ollama"


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class KickoffCopilotaTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(username="kickoff-ai", legacy_user_id=411, role_id=2, role_name="tasks")
        self.client.force_login(self.user)
        self.vecchia = make_project(name="Flangia turbina lotto 1", client_name="Cliente Demo", part_number="PN-77",
                                    created_by=self.user, project_manager=self.user)
        self.altra = make_project(name="Flangia turbina lotto 2", client_name="Cliente Demo", created_by=self.user, project_manager=self.user)
        for progetto in (self.vecchia, self.altra):
            MeetingIssue.objects.create(project=progetto, title="Disegno cliente senza tolleranze sul foro",
                                        status=MeetingIssueStatus.RESOLVED, created_by=self.user)
        task = Task.objects.create(title="Industrializzazione ciclo", project=self.vecchia, created_by=self.user,
                                   due_date=date(2026, 6, 30))
        GanttBaseline.objects.create(project=self.vecchia, snapshot={str(task.pk): {"start": "2026-05-01", "end": "2026-06-10"}})
        make_project(name="Imballo pallet", client_name="Altro cliente", created_by=self.user)
        self.nuova = make_project(name="Flangia turbina lotto 3", client_name="Cliente Demo", part_number="PN-77",
                                  created_by=self.user, project_manager=self.user)
        self.meeting = KickoffMeeting.objects.create(project=self.nuova, data=timezone.localdate() + timedelta(days=3),
                                                     agenda_items=[{"id": "a1", "titolo": "Presentazioni"}], created_by=self.user)

    def test_simili_ricorrenti_e_slittamenti(self):
        from tasks.models import Project

        simili = ai_kickoff.commesse_simili(self.nuova, scope_queryset=Project.objects.all())
        nomi = [c["nome"] for c in simili]
        self.assertEqual(nomi[0], "Flangia turbina lotto 1")  # stesso cliente e stesso P/N
        self.assertNotIn("Imballo pallet", nomi)
        self.assertIn("Industrializzazione ciclo (+20 giorni)", simili[0]["slittamenti"])
        ricorrenti = ai_kickoff.punti_ricorrenti(simili)
        self.assertEqual(ricorrenti[0]["titolo"], "Disegno cliente senza tolleranze sul foro")
        self.assertIn("PROBLEMI RICORRENTI", ai_kickoff.contesto(self.nuova, self.meeting, simili))

    def test_proposta_pagina_aggiunta_e_apprendimento(self):
        url = reverse("tasks:project_meeting_detail", args=[self.nuova.pk, self.meeting.pk])
        self.assertContains(self.client.get(url), "Dalle commesse simili")
        risposta = SimpleNamespace(content=json.dumps([
            {"titolo": "Chiedere al cliente le tolleranze del foro", "nota": "Già successo nei lotti 1 e 2", "durata_minuti": 15},
            {"titolo": "Presentazioni", "nota": "già in agenda"},
            {"titolo": "Verificare la pianificazione dell'industrializzazione", "nota": "slittata di 20 giorni"},
        ]))
        with patch(CHAT, return_value=risposta):
            r = self.client.post(reverse("tasks:project_meeting_ai_punti", args=[self.nuova.pk, self.meeting.pk]))
        self.assertContains(r, 'data-titolo="Chiedere al cliente le tolleranze del foro"')
        self.assertNotContains(r, 'data-titolo="Presentazioni"')  # gia' in agenda
        self.meeting.refresh_from_db()
        self.assertEqual(len(self.meeting.agenda_items), 1)  # proporre non cambia l'agenda

        r = self.client.post(reverse("tasks:project_meeting_agenda_item_add", args=[self.nuova.pk, self.meeting.pk]),
                             {"titolo": "Chiedere al cliente le tolleranze del foro", "source": "ai"})
        self.assertTrue(r.json()["ok"])
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.agenda_items[-1]["source"], "ai")

        self.meeting.stato = MeetingStatus.SVOLTO
        self.meeting.svolto_at = timezone.now()
        self.meeting.save()
        self.client.post(reverse("tasks:project_meeting_minute_close", args=[self.nuova.pk, self.meeting.pk]))
        proposta = AiProposta.objects.get(modulo="kickoff")
        self.assertEqual(proposta.esito, AiProposta.ACCETTATA)  # tenuta almeno meta' dei punti proposti
        esperienza = ai_kickoff.esperienza_punti()
        self.assertEqual(esperienza["tenuti"], ["Chiedere al cliente le tolleranze del foro"])
        self.assertIn("Verificare la pianificazione dell'industrializzazione", esperienza["scartati"])

    def test_ai_spenta_restano_le_commesse_simili(self):
        with patch(CHAT, side_effect=RuntimeError("giù")):
            r = self.client.post(reverse("tasks:project_meeting_ai_punti", args=[self.nuova.pk, self.meeting.pk]))
        self.assertContains(r, "Flangia turbina lotto 1")
        self.assertContains(r, "AI locale non ha risposto")
        self.assertFalse(AiProposta.objects.exists())

    def test_commesse_fuori_scope_non_entrano_nel_contesto(self):
        """Audit M13: senza scope (o con scope vuoto) nessuna commessa altrui finisce all'LLM."""
        from tasks.models import Project

        self.assertEqual(ai_kickoff.commesse_simili(self.nuova), [])
        self.assertEqual(ai_kickoff.commesse_simili(self.nuova, scope_queryset=Project.objects.none()), [])
