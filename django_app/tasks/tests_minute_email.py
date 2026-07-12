from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from tasks.models import KickoffMeeting, Project
from tasks.minute_email import build_minute_email, send_meeting_minute

User = get_user_model()


class MinuteEmailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pm", email="pm@example.com", password="x")
        self.project = Project.objects.create(name="", created_by=self.user)
        self.meeting = KickoffMeeting.objects.create(
            project=self.project,
            data="2026-07-15",
            titolo="Avvio commessa",
            luogo="Sala A",
            ordine_del_giorno="1. Presentazione\n2. Rischi",
            note="Riunione conclusa, tutti allineati.",
            next_steps="Inviare offerta entro venerdì.",
            partecipanti_email_extra="mario@example.com\nlucia@example.com",
        )

    def test_build_minute_email_contains_verbale_and_subject(self):
        subject, body_text, body_html = build_minute_email(self.meeting)
        self.assertIn("Minuta", subject)
        self.assertIn(str(self.meeting.project.kickoff_number), subject)
        self.assertIn("Riunione conclusa", body_html)
        self.assertIn("Inviare offerta", body_html)

    def test_send_meeting_minute_sends_to_all_attendees(self):
        result = send_meeting_minute(self.meeting)
        self.assertTrue(result["sent"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertCountEqual(
            mail.outbox[0].to, ["mario@example.com", "lucia@example.com"]
        )

    def test_send_meeting_minute_skips_without_recipients(self):
        self.meeting.partecipanti_email_extra = ""
        self.meeting.save(update_fields=["partecipanti_email_extra"])
        result = send_meeting_minute(self.meeting)
        self.assertFalse(result["sent"])
        self.assertEqual(result["reason"], "no_recipients")
        self.assertEqual(len(mail.outbox), 0)
