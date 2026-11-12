"""Dopo la fine dell'incontro: correzioni solo del capocommessa, minuta da reinviare, azioni non doppie."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import KickoffMeeting, MeetingActionItem, MeetingStatus
from .tests_utils import TasksBaseTestCase, _create_user_with_legacy, _ensure_role, _grant_role_actions, make_project


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MinutaDopoFineTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.pm = _create_user_with_legacy(username="mf-pm", legacy_user_id=811, role_id=2, role_name="tasks")
        self.cc = _create_user_with_legacy(username="mf-cc", legacy_user_id=812, role_id=2, role_name="tasks")
        self.project = make_project(name="Commessa minuta", created_by=self.pm, project_manager=self.pm)
        self.project.add_team_member("CC", self.cc)
        self.meeting = KickoffMeeting.objects.create(
            project=self.project, data=date(2026, 11, 2), stato=MeetingStatus.SVOLTO, note="Verbale",
            partecipanti_email_extra="esterno@example.com", created_by=self.pm,
            minuta_chiusa_at=timezone.now(), minuta_chiusa_da=self.pm,
        )
        # Il capocommessa vede la commessa (qui da convocato; in esercizio dal ruolo di team).
        self.meeting.partecipanti_utenti.add(self.cc)
        self.reopen_url = reverse("tasks:project_meeting_minute_reopen", args=[self.project.pk, self.meeting.pk])
        self.edit_url = reverse("tasks:project_meeting_edit", args=[self.project.pk, self.meeting.pk])

    def test_riapre_solo_il_capocommessa(self):
        self.client.force_login(self.pm)
        self.client.post(self.reopen_url, {"motivo": "errore di battitura"})
        self.meeting.refresh_from_db()
        self.assertTrue(self.meeting.minuta_chiusa)
        self.client.force_login(self.cc)
        self.client.post(self.reopen_url, {"motivo": "errore di battitura"})
        self.meeting.refresh_from_db()
        self.assertFalse(self.meeting.minuta_chiusa)
        self.assertEqual(self.meeting.minuta_riaperture, 1)

    def test_odg_dopo_la_fine_solo_capocommessa(self):
        self.client.force_login(self.pm)
        self.assertRedirects(
            self.client.get(self.edit_url),
            reverse("tasks:project_meeting_detail", args=[self.project.pk, self.meeting.pk]),
            fetch_redirect_response=False,
        )
        self.client.force_login(self.cc)
        self.assertEqual(self.client.get(self.edit_url).status_code, 200)

    def test_dettaglio_mostra_riapri_solo_al_capocommessa(self):
        detail = reverse("tasks:project_meeting_detail", args=[self.project.pk, self.meeting.pk])
        self.client.force_login(self.pm)
        self.assertNotContains(self.client.get(detail), "Riapri minuta")
        self.client.force_login(self.cc)
        pagina = self.client.get(detail)
        self.assertContains(pagina, "Riapri minuta")
        self.assertContains(pagina, "Correggi ordine del giorno")

    def test_minuta_da_reinviare_dopo_modifica(self):
        from .minute_email import send_meeting_minute

        with patch("core.email_utils.send_hub_mail", return_value=1) as invio:
            esito = send_meeting_minute(self.meeting, with_pdf=False)
        self.assertTrue(esito["sent"])
        self.assertFalse(esito["aggiornamento"])
        self.meeting.refresh_from_db()
        self.assertTrue(self.meeting.minuta_inviata)
        self.assertFalse(self.meeting.minuta_da_reinviare)
        MeetingActionItem.objects.create(project=self.project, source_meeting=self.meeting, title="Nuova azione")
        self.assertTrue(self.meeting.minuta_da_reinviare)
        with patch("core.email_utils.send_hub_mail", return_value=1) as invio:
            esito = send_meeting_minute(self.meeting, with_pdf=False)
        self.assertTrue(esito["aggiornamento"])
        self.assertTrue(invio.call_args.args[0].startswith("Aggiornamento minuta"))
        self.meeting.refresh_from_db()
        self.assertFalse(self.meeting.minuta_da_reinviare)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AzioniNonDoppieTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.pm = _create_user_with_legacy(username="az-pm", legacy_user_id=821, role_id=2, role_name="tasks")
        self.project = make_project(name="Commessa azioni", created_by=self.pm, project_manager=self.pm)
        self.meeting = KickoffMeeting.objects.create(project=self.project, data=date(2026, 11, 2), created_by=self.pm)
        self.client.force_login(self.pm)

    def test_esito_salvato_due_volte_non_raddoppia(self):
        url = reverse("tasks:project_meeting_minutes", args=[self.project.pk, self.meeting.pk])
        dati = {"note": "verbale", "problemi_aperti": "", "next_steps": "",
                "new_action_title": ["Ordinare il materiale"], "new_action_assigned_to": [str(self.pm.pk)]}
        self.client.post(url, dati)
        self.client.post(url, dati)
        self.assertEqual(MeetingActionItem.objects.filter(source_meeting=self.meeting).count(), 1)
