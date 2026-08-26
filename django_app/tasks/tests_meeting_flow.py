"""Flusso incontro KICK-OFF in due tempi: convocazione → esito.

Copre la separazione fra `project_meeting_edit` (prima dell'incontro) e
`project_meeting_minutes` (dopo), e le azioni documentali esposte dal dettaglio
incontro: invio convocazione, invio minuta, download PDF.
"""
from __future__ import annotations

from unittest.mock import patch

from django.core import mail
from django.test import override_settings
from django.urls import reverse

from tasks.models import (
    KickoffMeeting,
    MeetingIssue,
    MeetingIssueStatus,
    MeetingStatus,
    Project,
)
from tasks.tests import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MeetingTwoStepFlowTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="meeting-flow",
            legacy_user_id=311,
            role_id=2,
            role_name="tasks",
        )
        self.user.email = "pm@example.com"
        self.user.save(update_fields=["email"])
        self.project = Project.objects.create(
            name="", created_by=self.user, project_manager=self.user
        )
        self.meeting = KickoffMeeting.objects.create(
            project=self.project,
            data="2026-09-10",
            titolo="Avvio commessa",
            luogo="Sala A",
            partecipanti_email_extra="mario@example.com",
            agenda_items=[
                {"id": "a1", "titolo": "Stato avanzamento", "nota": "", "done": False},
            ],
            created_by=self.user,
        )
        self.client.force_login(self.user)

    # ── separazione dei due form ────────────────────────────────────────
    def test_convocazione_non_chiede_il_verbale(self):
        response = self.client.get(
            reverse("tasks:project_meeting_edit", args=[self.project.id, self.meeting.id])
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertNotIn('name="note"', body)
        self.assertNotIn('name="next_steps"', body)
        self.assertIn('name="data"', body)
        self.assertIn('name="stato"', body)

    def test_esito_chiede_solo_il_dopo_incontro(self):
        response = self.client.get(
            reverse("tasks:project_meeting_minutes", args=[self.project.id, self.meeting.id])
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('name="note"', body)
        self.assertIn('name="next_steps"', body)
        self.assertNotIn('name="data"', body)

    def test_salvare_la_convocazione_non_declassa_un_incontro_svolto(self):
        self.meeting.stato = MeetingStatus.SVOLTO
        self.meeting.save(update_fields=["stato"])
        response = self.client.post(
            reverse("tasks:project_meeting_edit", args=[self.project.id, self.meeting.id]),
            {
                "titolo": "Avvio commessa",
                "data": "2026-09-10",
                "ora": "",
                "luogo": "Sala B",
                "stato": MeetingStatus.SVOLTO,
                "agenda_items_raw": "[]",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.stato, MeetingStatus.SVOLTO)
        self.assertEqual(self.meeting.luogo, "Sala B")

    def test_esito_puo_essere_aggiornato_senza_riscrivere_svolto_at(self):
        url = reverse("tasks:project_meeting_minutes", args=[self.project.id, self.meeting.id])
        self.client.post(url, {"note": "primo giro", "problemi_aperti": "", "next_steps": ""})
        self.meeting.refresh_from_db()
        first_timestamp = self.meeting.svolto_at
        self.assertIsNotNone(first_timestamp)

        self.client.post(url, {"note": "secondo giro", "problemi_aperti": "", "next_steps": ""})
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.note, "secondo giro")
        self.assertEqual(self.meeting.svolto_at, first_timestamp)

    # ── azioni documentali ──────────────────────────────────────────────
    def test_invio_convocazione_raggiunge_i_partecipanti(self):
        response = self.client.post(
            reverse("tasks:project_meeting_send_invite", args=[self.project.id, self.meeting.id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("mario@example.com", mail.outbox[0].to)
        self.assertIn("Convocazione", mail.outbox[0].subject)

    def test_invio_minuta_raggiunge_i_partecipanti(self):
        self.meeting.note = "Verbale del giorno"
        self.meeting.stato = MeetingStatus.SVOLTO
        self.meeting.save(update_fields=["note", "stato"])
        response = self.client.post(
            reverse("tasks:project_meeting_send_minute", args=[self.project.id, self.meeting.id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Minuta", mail.outbox[0].subject)

    def test_invio_senza_destinatari_non_manda_nulla(self):
        self.meeting.partecipanti_email_extra = ""
        self.meeting.save(update_fields=["partecipanti_email_extra"])
        response = self.client.post(
            reverse("tasks:project_meeting_send_minute", args=[self.project.id, self.meeting.id]),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertContains(response, "non ha partecipanti")

    def test_minuta_pdf_scaricabile(self):
        response = self.client.get(
            reverse("tasks:project_meeting_minute_pdf", args=[self.project.id, self.meeting.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    # ── pulizia calendario ──────────────────────────────────────────────
    def test_eliminare_l_incontro_rimuove_l_evento_outlook(self):
        self.meeting.sync_outlook = True
        self.meeting.outlook_event_id = "AAA-EVENT-ID"
        self.meeting.save(update_fields=["sync_outlook", "outlook_event_id"])

        with patch("tasks.meeting_outlook.sync_meeting_outlook_event", return_value=("info", "ok")) as sync:
            response = self.client.post(
                reverse("tasks:project_meeting_delete", args=[self.project.id, self.meeting.id])
            )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(KickoffMeeting.objects.filter(pk=self.meeting.pk).exists())
        sync.assert_called_once()
        # La cancellazione su Graph avviene proprio perche' sync_outlook e' falso.
        self.assertFalse(sync.call_args.kwargs["meeting"].sync_outlook)


class MinuteContentTests(TasksBaseTestCase):
    """La minuta deve contenere l'agenda strutturata e i problemi tracciati."""

    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="minute-content",
            legacy_user_id=312,
            role_id=2,
            role_name="tasks",
        )
        self.project = Project.objects.create(name="", created_by=self.user)
        self.meeting = KickoffMeeting.objects.create(
            project=self.project,
            data="2026-09-10",
            partecipanti_email_extra="mario@example.com",
            agenda_items=[
                {"id": "a1", "titolo": "Collaudo linea 3", "nota": "con il cliente", "done": True},
            ],
            created_by=self.user,
        )
        MeetingIssue.objects.create(
            project=self.project,
            source_meeting=self.meeting,
            title="Ritardo fornitore stampi",
            status=MeetingIssueStatus.OPEN,
            created_by=self.user,
        )

    def test_minuta_contiene_agenda_strutturata_e_problemi(self):
        from tasks.minute_email import build_minute_email

        _, body_text, body_html = build_minute_email(self.meeting)
        self.assertIn("Collaudo linea 3", body_html)
        self.assertIn("Ritardo fornitore stampi", body_html)
        self.assertIn("Collaudo linea 3", body_text)

    def test_convocazione_contiene_agenda_ma_non_i_problemi(self):
        from tasks.minute_email import build_invite_email

        _, _, body_html = build_invite_email(self.meeting)
        self.assertIn("Collaudo linea 3", body_html)
        self.assertNotIn("Ritardo fornitore stampi", body_html)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class FirstMeetingOnKickoffCreateTests(TasksBaseTestCase):
    """Creare un kickoff crea anche il suo incontro 1 e ci porta sopra."""

    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="kickoff-first",
            legacy_user_id=313,
            role_id=2,
            role_name="tasks",
        )
        self.client.force_login(self.user)

    def _create_kickoff(self, part_number: str, **extra):
        payload = {
            "client_name": "Cliente",
            "part_number": part_number,
            "revisione": "A",
            "versione": "1.0",
            "description": "",
            "control_method": "",
            "vrf_quote_number": "",
            "vrf_description": "",
            "vrf_esp": "",
            "project_manager": self.user.id,
        }
        payload.update(extra)
        return self.client.post(reverse("tasks:project_create"), payload)

    def test_kickoff_nasce_con_il_suo_primo_incontro(self):
        response = self._create_kickoff("PN-FIRST-001")
        project = Project.objects.get(part_number="PN-FIRST-001")
        meeting = project.meetings.get()

        self.assertEqual(meeting.numero, 1)
        self.assertEqual(meeting.stato, MeetingStatus.PIANIFICATO)
        self.assertRedirects(
            response, reverse("tasks:project_meeting_edit", args=[project.id, meeting.id])
        )

    def test_la_convocazione_di_arrivo_e_compilabile(self):
        self._create_kickoff("PN-FIRST-002")
        project = Project.objects.get(part_number="PN-FIRST-002")
        meeting = project.meetings.get()

        page = self.client.get(
            reverse("tasks:project_meeting_edit", args=[project.id, meeting.id])
        )
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn('name="data"', body)
        self.assertIn('name="luogo"', body)

    def test_helper_idempotente_non_crea_un_secondo_incontro(self):
        from tasks.views import _create_first_meeting

        project = Project.objects.create(name="", created_by=self.user)
        first = _create_first_meeting(project, self.user)
        second = _create_first_meeting(project, self.user)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(project.meetings.count(), 1)

    def test_incontro_senza_team_resta_senza_partecipanti(self):
        from tasks.views import _create_first_meeting

        project = Project.objects.create(name="", created_by=self.user)
        meeting = _create_first_meeting(project, self.user)

        self.assertEqual(meeting.partecipanti_utenti.count(), 0)
