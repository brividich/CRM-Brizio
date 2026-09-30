from copy import deepcopy
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from .assenze_flow_merge import LEGACY, BRANCHED, MERGED, combined_config, merge_flows
from .models import AutomationRule, AutomationAction, AutomationCondition, AutomationApproval, AutomationRunLog
from .services import process_approval_decision


class AbsenceFlowMergeTests(TestCase):
    def setUp(self):
        email = {"action_type": "send_email", "to": "synthetic@example.com", "subject_template": "Synthetic", "body_text_template": "Synthetic"}
        self.legacy = {"to_template": "{capo_email}", "approved_actions": [
            {"action_type": "update_trigger_record", "config_json": {"update_fields": {"moderation_status": 0}}},
            {"action_type": "split_assenza_giornaliera", "config_json": {"dedupe": True}}, email],
            "rejected_actions": [{"action_type": "update_trigger_record", "config_json": {"update_fields": {"moderation_status": 1}}}, email]}
        terminal = {"action_type": "send_approval", "to_template": "synthetic@example.com",
                    "approved_actions": [deepcopy(email)], "rejected_actions": [deepcopy(email)]}
        two_steps = deepcopy(terminal)
        two_steps["approved_actions"] = [deepcopy(terminal)]
        self.branched = {"condition_field": "tipo_assenza", "condition_operator": "equals", "condition_value": "Ferie",
                         "then_actions": [two_steps], "else_actions": []}
        for code, action_type, config in ((LEGACY, "send_approval", self.legacy), (BRANCHED, "branch", self.branched)):
            rule = AutomationRule.objects.create(code=code, name=code, source_code="assenze", operation_type="insert",
                trigger_scope="all_inserts", is_active=True, is_draft=False)
            AutomationCondition.objects.create(rule=rule, order=1, field_name="salta_approvazione", operator="is_false", value_type="bool")
            if code == LEGACY:
                AutomationCondition.objects.create(rule=rule, order=2, field_name="moderation_status", operator="equals", expected_value="2", value_type="int")
                AutomationCondition.objects.create(rule=rule, order=3, field_name="capo_email", operator="is_not_empty", value_type="string")
            AutomationAction.objects.create(rule=rule, order=1, action_type=action_type, config_json=config)

    def test_merge_uses_single_active_rule_keeps_originals_and_is_idempotent(self):
        originals = list(AutomationAction.objects.values_list("config_json", flat=True))
        self.assertTrue(merge_flows()["preview"])
        self.assertEqual(AutomationRule.objects.count(), 2)
        self.assertTrue(merge_flows(apply=True)["created"])
        self.assertEqual(list(AutomationRule.objects.filter(is_active=True).values_list("code", flat=True)), [MERGED])
        self.assertEqual(list(AutomationAction.objects.filter(rule__code__in=[LEGACY, BRANCHED]).values_list("config_json", flat=True)), originals)
        self.assertFalse(merge_flows(apply=True)["created"])

    def test_state_changes_only_after_terminal_decision_with_legacy_fallback(self):
        merged = combined_config(self.legacy, self.branched)
        first = merged["then_actions"][0]
        self.assertEqual(first["approved_actions"][0]["action_type"], "send_approval")
        terminal = first["approved_actions"][0]
        self.assertEqual([a["action_type"] for a in terminal["approved_actions"]],
                         ["update_trigger_record", "split_assenza_giornaliera", "send_email"])
        self.assertEqual(first["rejected_actions"][0]["action_type"], "update_trigger_record")
        self.assertEqual(merged["else_actions"][0]["config_json"], self.legacy)
        self.assertEqual(self.branched["else_actions"], [])

    def test_unknown_customizations_fail_without_mutations(self):
        branch = AutomationRule.objects.get(code=BRANCHED)
        branch.actions.update(config_json={"unexpected": True})
        with self.assertRaises(ValueError):
            merge_flows(apply=True)
        self.assertEqual(AutomationRule.objects.filter(is_active=True).count(), 2)

    def test_approval_resume_stops_on_error_and_does_not_report_success(self):
        rule = AutomationRule.objects.get(code=LEGACY)
        rule.stop_on_first_failure = True
        rule.save()
        run = AutomationRunLog.objects.create(rule=rule, source_code="assenze", operation_type="insert", status="waiting_approval")
        approval = AutomationApproval.objects.create(run_log=run, subject="Synthetic", approver_emails=["synthetic@example.com"],
            expires_at=timezone.now()+timedelta(days=1), approved_actions=self.legacy["approved_actions"])
        with patch("automazioni.services._execute_inline_action", return_value={"status": "error"}) as execute:
            result = process_approval_decision(str(approval.token), "approved", "synthetic@example.com")
        self.assertEqual(result["actions_errors"], 1)
        execute.assert_called_once()
        run.refresh_from_db()
        self.assertEqual(run.status, "error")
