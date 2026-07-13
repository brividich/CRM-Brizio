from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from tasks.models import Project, ProjectPhase, VRFDocStatus
from tasks.project_alerts import project_recipients, send_project_alert

User = get_user_model()


class ProjectAlertTests(TestCase):
    def setUp(self):
        self.pm = User.objects.create_user(username="pm", email="pm@example.com", password="x")
        self.capo = User.objects.create_user(username="capo", email="capo@example.com", password="x")
        self.project = Project.objects.create(
            name="", created_by=self.pm, project_manager=self.pm, capo_commessa=self.capo,
            safety_impact=True, vrf_status=VRFDocStatus.PENDING, phase=ProjectPhase.EXEC,
        )

    def test_project_recipients(self):
        self.assertCountEqual(project_recipients(self.project), ["pm@example.com", "capo@example.com"])

    def test_safety_alert_sends_to_stakeholders_and_extra(self):
        result = send_project_alert(self.project, "safety", extra_to="rspp@example.com")
        self.assertTrue(result["sent"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertCountEqual(mail.outbox[0].to, ["pm@example.com", "capo@example.com", "rspp@example.com"])
        self.assertIn("sicurezza", mail.outbox[0].subject.lower())

    def test_vrf_pending_alert_sends(self):
        result = send_project_alert(self.project, "vrf_pending")
        self.assertTrue(result["sent"])
        self.assertIn("VRF", mail.outbox[0].subject)

    def test_unknown_kind_skips(self):
        result = send_project_alert(self.project, "boh")
        self.assertFalse(result["sent"])
        self.assertEqual(result["reason"], "unknown_kind")

    def test_no_recipients_skips(self):
        p = Project.objects.create(name="", created_by=self.pm)  # niente PM/capo
        result = send_project_alert(p, "safety")
        self.assertFalse(result["sent"])
        self.assertEqual(result["reason"], "no_recipients")


class ProjectAlertActionTests(TestCase):
    def setUp(self):
        from automazioni.models import (
            AutomationAction,
            AutomationActionType,
            AutomationRule,
            AutomationRuleOperationType,
        )

        self.pm = User.objects.create_user(username="pm2", email="pm2@example.com", password="x")
        self.project = Project.objects.create(
            name="", created_by=self.pm, project_manager=self.pm, safety_impact=True,
        )
        self.rule = AutomationRule.objects.create(
            code="au54-safety", name="Safety", source_code="tasks_project",
            operation_type=AutomationRuleOperationType.UPDATE,
        )
        self.action = AutomationAction.objects.create(
            rule=self.rule, order=1, action_type=AutomationActionType.SEND_PROJECT_ALERT,
            config_json={"alert": "safety", "extra_to": "rspp@example.com"},
        )

    def test_action_sends_alert(self):
        from automazioni.services import execute_action

        result = execute_action(
            self.action,
            payload={"id": self.project.id, "safety_impact": True},
            queue_event={"source_code": "tasks_project"},
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("rspp@example.com", mail.outbox[0].to)
