"""Link di approvazione personali, decisione con login e ripresa del ramo.

Dati sintetici: nessuna email o persona reale.
"""
from __future__ import annotations

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from automazioni.approval_links import build_link_urls, create_link, decide_with_link, hash_token
from automazioni.models import (
    AutomationAction,
    AutomationActionType,
    AutomationApproval,
    AutomationApprovalLink,
    AutomationRule,
    AutomationRuleOperationType,
    AutomationRuleTriggerScope,
    AutomationRunLog,
)
from automazioni.services import execute_action, process_approval_decision

APPROVER_A = "approvatore.a@example.com"
APPROVER_B = "approvatore.b@example.com"


def _rule(code="test-approval-links"):
    return AutomationRule.objects.create(
        code=code,
        name="Approvazioni sintetiche",
        source_code="assenze",
        operation_type=AutomationRuleOperationType.UPDATE,
        trigger_scope=AutomationRuleTriggerScope.ANY_CHANGE,
        is_active=True,
        is_draft=False,
    )


def _approval(rule=None, *, approvers=(APPROVER_A, APPROVER_B), actions=None, **extra):
    rule = rule or _rule()
    run = AutomationRunLog.objects.create(
        rule=rule, source_code="assenze", operation_type="update", status="waiting_approval"
    )
    return AutomationApproval.objects.create(
        run_log=run,
        subject="Richiesta sintetica",
        approver_emails=list(approvers),
        expires_at=timezone.now() + timedelta(days=1),
        approved_actions=actions or [],
        **extra,
    )


class ApprovalLinkServiceTests(TestCase):
    def test_link_stores_only_hash_and_decides_as_its_recipient(self):
        approval = _approval()
        raw = create_link(approval, APPROVER_B)
        link = AutomationApprovalLink.objects.get(approval=approval)
        self.assertNotIn(raw, link.token_hash)
        self.assertEqual(link.token_hash, hash_token(raw))

        result = decide_with_link(raw, "approved")
        self.assertTrue(result["ok"])
        approval.refresh_from_db()
        self.assertEqual(approval.status, "approved")
        self.assertEqual(approval.decided_by_email, APPROVER_B)

    def test_link_is_single_use_and_unknown_token_rejected(self):
        approval = _approval()
        raw = create_link(approval, APPROVER_A)
        self.assertTrue(decide_with_link(raw, "rejected")["ok"])
        second = decide_with_link(raw, "approved")
        self.assertFalse(second["ok"])
        self.assertIn(second["code"], {"already_decided", "already_used"})
        self.assertEqual(decide_with_link("inesistente", "approved")["code"], "not_found")

    def test_expired_link_does_not_decide(self):
        approval = _approval()
        AutomationApproval.objects.filter(pk=approval.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        raw = create_link(approval, APPROVER_A)
        self.assertEqual(decide_with_link(raw, "approved")["code"], "expired")
        approval.refresh_from_db()
        self.assertEqual(approval.status, "pending")


@override_settings(SITE_URL="https://portale.example.local", DEFAULT_FROM_EMAIL="noreply@example.com")
class SendApprovalPersonalLinksTests(TestCase):
    def test_each_recipient_gets_a_different_personal_link(self):
        rule = _rule("test-send-approval-links")
        action = AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.SEND_APPROVAL,
            is_enabled=True,
            config_json={
                "to_template": f"{APPROVER_A}, {APPROVER_B}",
                "subject_template": "Approva",
                "message_template": "Richiesta sintetica",
                "expiry_days": 3,
            },
        )
        run = AutomationRunLog.objects.create(
            rule=rule, source_code="assenze", operation_type="update", status="success"
        )
        result = execute_action(action=action, payload={"id": "ABS-1"}, old_payload=None, run_log=run)
        self.assertEqual(result["status"], "success")

        approval = AutomationApproval.objects.get(run_log=run)
        links = list(approval.links.order_by("recipient_email"))
        self.assertEqual([l.recipient_email for l in links], [APPROVER_A, APPROVER_B])
        self.assertEqual(len(mail.outbox), 2)
        bodies = {m.to[0]: m.body for m in mail.outbox}
        self.assertNotEqual(bodies[APPROVER_A], bodies[APPROVER_B])
        for body in bodies.values():
            self.assertIn("/approval-actions/r/", body)
            self.assertNotIn(str(approval.token), body)
        self.assertNotIn(str(approval.token), result["result_message"])


@override_settings(SITE_URL="https://portale.example.local")
class ApprovalViewsTests(TestCase):
    def setUp(self):
        self.approval = _approval()

    def test_personal_link_get_is_side_effect_free_and_post_decides(self):
        raw = create_link(self.approval, APPROVER_A)
        approve_url, _ = build_link_urls(raw)
        path = approve_url.replace("https://portale.example.local", "")

        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, APPROVER_A)
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.status, "pending")

        response = self.client.post(path)
        self.assertEqual(response.status_code, 302)
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.status, "approved")
        self.assertEqual(self.approval.decided_by_email, APPROVER_A)

    def test_request_link_requires_login(self):
        path = f"/automazioni/approvazione/{self.approval.token}/approva/"
        response = self.client.post(path)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response["Location"])
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.status, "pending")

    def test_teams_style_anonymous_json_post_no_longer_decides(self):
        path = f"/automazioni/approvazione/{self.approval.token}/approva/"
        self.client.post(path, data='{"action":"approve"}', content_type="application/json")
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.status, "pending")

    def test_request_link_rejects_logged_user_not_in_approvers(self):
        user = get_user_model().objects.create_user("estraneo", email="estraneo@example.com", password="x")
        self.client.force_login(user)
        path = f"/automazioni/approvazione/{self.approval.token}/approva/"
        response = self.client.post(path)
        self.assertEqual(response.status_code, 403)
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.status, "pending")

    def test_request_link_accepts_logged_approver(self):
        user = get_user_model().objects.create_user("approvatore", email=APPROVER_B, password="x")
        self.client.force_login(user)
        path = f"/automazioni/approvazione/{self.approval.token}/rifiuta/"
        response = self.client.post(path)
        self.assertEqual(response.status_code, 302)
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.status, "rejected")
        self.assertEqual(self.approval.decided_by_email, APPROVER_B)

    def test_proxy_ignores_identity_headers(self):
        path = f"/approval-actions/approve/{self.approval.token}/"
        response = self.client.post(path, HTTP_X_MS_CLIENT_PRINCIPAL_NAME=APPROVER_A, HTTP_X_FORWARDED_EMAIL=APPROVER_A)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response["Location"])
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.status, "pending")


class ApprovalBranchRecoveryTests(TestCase):
    def test_branch_progress_is_saved_and_recovery_resumes_from_it(self):
        actions = [{"action_type": "write_log"}, {"action_type": "write_log"}, {"action_type": "write_log"}]
        approval = _approval(approvers=(APPROVER_A,), actions=actions)

        calls = []

        def crash_on_second(cfg, *args, **kwargs):
            calls.append(cfg)
            if len(calls) == 2:
                raise RuntimeError("riavvio simulato")
            return {"status": "success"}

        with patch("automazioni.services._execute_inline_action", side_effect=crash_on_second):
            with self.assertRaises(RuntimeError):
                process_approval_decision(str(approval.token), "approved", APPROVER_A)
        approval.refresh_from_db()
        self.assertEqual(approval.branch_status, "running")
        self.assertEqual(approval.branch_progress, 1)

        AutomationApproval.objects.filter(pk=approval.pk).update(
            branch_updated_at=timezone.now() - timedelta(hours=1)
        )
        with patch("automazioni.services._execute_inline_action", return_value={"status": "success"}) as execute:
            call_command("recover_approval_branches", stdout=StringIO())
        self.assertEqual(execute.call_count, 2)  # riprende dalla seconda azione
        approval.refresh_from_db()
        self.assertEqual(approval.branch_status, "done")
        self.assertEqual(approval.branch_progress, 3)

    def test_completed_branch_is_marked_done(self):
        approval = _approval(approvers=(APPROVER_A,), actions=[{"action_type": "write_log"}])
        with patch("automazioni.services._execute_inline_action", return_value={"status": "success"}):
            result = process_approval_decision(str(approval.token), "approved", APPROVER_A)
        self.assertTrue(result["ok"])
        approval.refresh_from_db()
        self.assertEqual(approval.branch_status, "done")
