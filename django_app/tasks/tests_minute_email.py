from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings

from tasks.minute_email import (
    build_invite_email,
    build_minute_email,
    build_minute_pdf,
    create_tasks_from_next_steps,
    send_meeting_invite,
    send_meeting_minute,
)
from tasks.models import KickoffMeeting, Project, Task

User = get_user_model()


class MinuteEmailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pm", email="pm@example.com", password="x")
        self.capo = User.objects.create_user(username="capo", email="capo@example.com", password="x")
        self.project = Project.objects.create(
            name="", created_by=self.user, project_manager=self.user, capo_commessa=self.capo
        )
        self.meeting = KickoffMeeting.objects.create(
            project=self.project,
            data="2026-07-15",
            titolo="Avvio commessa",
            luogo="Sala A",
            ordine_del_giorno="1. Presentazione\n2. Rischi",
            note="Riunione conclusa, tutti allineati.",
            next_steps="Inviare offerta entro venerdì.\nPreparare disegni.",
            partecipanti_email_extra="mario@example.com\nlucia@example.com",
            created_by=self.user,
        )

    def test_build_minute_email_contains_verbale_and_subject(self):
        subject, body_text, body_html = build_minute_email(self.meeting)
        self.assertIn("Minuta", subject)
        self.assertIn(str(self.meeting.project.kickoff_number), subject)
        self.assertIn("Riunione conclusa", body_html)
        self.assertIn("Inviare offerta", body_html)

    @override_settings(SITE_URL="https://hub.example.com")
    def test_email_contains_real_link_when_site_url_set(self):
        _, _, body_html = build_minute_email(self.meeting)
        self.assertIn(f"https://hub.example.com/tasks/projects/{self.project.id}/incontri/{self.meeting.id}/", body_html)

    def test_send_meeting_minute_sends_to_all_attendees_with_cc_and_pdf(self):
        result = send_meeting_minute(self.meeting)
        self.assertTrue(result["sent"])
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertCountEqual(msg.to, ["mario@example.com", "lucia@example.com"])
        # CC a PM + capo commessa
        self.assertCountEqual(msg.cc, ["pm@example.com", "capo@example.com"])
        # PDF allegato
        self.assertTrue(any(att[2] == "application/pdf" for att in msg.attachments))

    def test_send_meeting_minute_skips_without_recipients(self):
        self.meeting.partecipanti_email_extra = ""
        self.meeting.save(update_fields=["partecipanti_email_extra"])
        result = send_meeting_minute(self.meeting)
        self.assertFalse(result["sent"])
        self.assertEqual(result["reason"], "no_recipients")
        self.assertEqual(len(mail.outbox), 0)

    def test_build_minute_pdf_returns_pdf_bytes(self):
        pdf = build_minute_pdf(self.meeting)
        self.assertIsInstance(pdf, bytes)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_build_invite_email_has_agenda_no_verbale(self):
        subject, _, body_html = build_invite_email(self.meeting)
        self.assertIn("Convocazione", subject)
        self.assertIn("Presentazione", body_html)  # ordine del giorno
        self.assertNotIn("Riunione conclusa", body_html)  # niente verbale

    def test_send_meeting_invite_sends_with_ics(self):
        result = send_meeting_invite(self.meeting)
        self.assertTrue(result["sent"])
        self.assertEqual(len(mail.outbox), 1)
        # .ics allegato
        self.assertTrue(any(att[2] == "text/calendar" for att in mail.outbox[0].attachments))

    def test_build_meeting_ics_is_valid_vevent(self):
        from tasks.minute_email import build_meeting_ics

        ics = build_meeting_ics(self.meeting).decode("utf-8")
        self.assertIn("BEGIN:VCALENDAR", ics)
        self.assertIn("BEGIN:VEVENT", ics)
        self.assertIn("SUMMARY:", ics)
        self.assertIn("DTSTART", ics)

    def test_create_tasks_from_next_steps_dedup(self):
        n1 = create_tasks_from_next_steps(self.meeting)
        self.assertEqual(n1, 2)
        self.assertEqual(Task.objects.filter(project=self.project).count(), 2)
        # secondo giro: nessun duplicato
        n2 = create_tasks_from_next_steps(self.meeting)
        self.assertEqual(n2, 0)
        self.assertEqual(Task.objects.filter(project=self.project).count(), 2)


class MeetingIssueReminderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="resp", email="resp@example.com", password="x")
        self.project = Project.objects.create(name="", created_by=self.user)

    def test_reminder_emails_overdue_open_issue(self):
        from unittest.mock import patch

        from tasks.models import MeetingIssue, MeetingIssueStatus
        from tasks.tasks import run_meetings_digest

        monday = date(2026, 9, 7)  # il sollecito problemi gira solo il lunedi

        MeetingIssue.objects.create(
            project=self.project,
            title="Problema scaduto",
            status=MeetingIssueStatus.OPEN,
            assigned_to=self.user,
            due_date=monday - timedelta(days=3),
        )
        # non scaduto → non deve produrre reminder
        MeetingIssue.objects.create(
            project=self.project,
            title="Futuro",
            status=MeetingIssueStatus.OPEN,
            assigned_to=self.user,
            due_date=monday + timedelta(days=5),
        )
        with patch("django.utils.timezone.localdate", return_value=monday):
            result = run_meetings_digest()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["resp@example.com"])
        self.assertIn("Problema scaduto", mail.outbox[0].body)
