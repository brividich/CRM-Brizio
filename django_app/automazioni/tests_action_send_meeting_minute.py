from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from automazioni.models import (
    AutomationAction,
    AutomationActionType,
    AutomationRule,
    AutomationRuleOperationType,
)
from automazioni.services import execute_action
from tasks.models import KickoffMeeting, Project

User = get_user_model()


class SendMeetingMinuteActionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pm", email="pm@example.com", password="x")
        self.project = Project.objects.create(name="", created_by=self.user)
        self.meeting = KickoffMeeting.objects.create(
            project=self.project,
            data="2026-07-15",
            titolo="Avvio",
            note="Verbale ok.",
            partecipanti_email_extra="a@example.com",
        )
        self.rule = AutomationRule.objects.create(
            code="au52-kickoff-minuta",
            name="Minuta incontro",
            source_code="tasks_kickoff",
            operation_type=AutomationRuleOperationType.UPDATE,
        )
        self.action = AutomationAction.objects.create(
            rule=self.rule,
            order=1,
            action_type=AutomationActionType.SEND_MEETING_MINUTE,
            config_json={},
        )

    def test_action_sends_minute(self):
        result = execute_action(
            self.action,
            payload={"id": self.meeting.id, "note": "Verbale ok."},
            queue_event={"source_code": "tasks_kickoff"},
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["a@example.com"])
        self.assertEqual(result["status"], "success")

    def test_action_missing_meeting_does_not_raise(self):
        result = execute_action(
            self.action,
            payload={"id": 999999},
            queue_event={"source_code": "tasks_kickoff"},
        )
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn(result["status"], ("error", "skipped"))

    def test_minute_action_creates_tasks_from_next_steps(self):
        from tasks.models import Task

        self.meeting.created_by = self.user
        self.meeting.next_steps = "Fare A\nFare B"
        self.meeting.save(update_fields=["created_by", "next_steps"])
        execute_action(
            self.action,
            payload={"id": self.meeting.id, "note": "Verbale ok."},
            queue_event={"source_code": "tasks_kickoff"},
        )
        self.assertEqual(Task.objects.filter(project=self.project).count(), 2)

    def test_invite_action_sends_convocazione(self):
        invite_rule = AutomationRule.objects.create(
            code="au53-kickoff-convocazione",
            name="Convocazione incontro",
            source_code="tasks_kickoff",
            operation_type=AutomationRuleOperationType.INSERT,
        )
        invite_action = AutomationAction.objects.create(
            rule=invite_rule,
            order=1,
            action_type=AutomationActionType.SEND_MEETING_INVITE,
            config_json={},
        )
        result = execute_action(
            invite_action,
            payload={"id": self.meeting.id},
            queue_event={"source_code": "tasks_kickoff"},
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Convocazione", mail.outbox[0].subject)
        self.assertEqual(result["status"], "success")
