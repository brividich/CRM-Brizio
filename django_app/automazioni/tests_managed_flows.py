from datetime import timedelta
from io import StringIO
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone
from django_q.conf import Conf
from django_q.models import OrmQ, Schedule
from django_q.signing import SignedPackage

from .broker import FlowBroker
from .flow_forms import ManagedScheduleForm
from .forms import AutomationActionForm, AutomationRuleForm
from .managed_flows import catalog, install_flows, run_managed_flow, event_flow, reconcile_expired_approvals
from .models import AutomationRule, AutomationAction, AutomationCondition, AutomationRunLog, ManagedFlow, BrokerRecoveryEntry
from .schedules import spec_by_name, register_schedule
from .services import run_rule


class ManagedFlowsTests(TestCase):
    def test_legacy_tick_preserves_explicit_batch_limit(self):
        callback = Mock(return_value={"ok": True})
        with patch("automazioni.managed_flows.import_string", return_value=callback):
            call_command("process_automation_queue", limit=11, stdout=StringIO())
        callback.assert_called_once_with(limit=11)

    def test_broker_preserves_custom_callbacks(self):
        broker = FlowBroker(Conf.CLUSTER_NAME)
        package = SignedPackage.loads(self.package())
        package["hook"] = "synthetic.callback"
        packet = SignedPackage.dumps(package)
        self.assertNotEqual(broker.enqueue(packet), broker.enqueue(packet))

    def test_legacy_tick_does_not_repeat_recent_completed_flow(self):
        AutomationRule.objects.filter(pk=self.binding.rule_id).update(last_run_at=timezone.now())
        with patch("automazioni.managed_flows.import_string") as importer:
            self.assertEqual(run_managed_flow(self.binding.code)["reason"], "recently_completed")
        importer.assert_not_called()

    def test_setup_preserves_edited_cadence_and_disabled_state(self):
        self.binding.minutes = 17
        self.binding.save()
        AutomationRule.objects.filter(pk=self.binding.rule_id).update(is_active=False)
        with patch("django.core.management.call_command"):
            # Call the command instance: only its documentation subcommand is mocked.
            from .management.commands.setup_q_schedules import Command
            Command(stdout=StringIO()).handle(dry_run=False, delete=False)
        self.binding.refresh_from_db()
        self.assertEqual(self.binding.minutes, 17)
        self.assertFalse(self.binding.rule.is_active)
        self.assertFalse(Schedule.objects.filter(name=self.binding.code).exists())

    def test_designer_lists_and_saves_managed_schedule(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse
        admin = get_user_model().objects.create_superuser("flow_admin", "flow@example.com", "synthetic")
        self.client.force_login(admin)
        designer = reverse("admin_portale:automazioni_rule_designer", args=[self.binding.rule_id])
        self.assertContains(self.client.get(designer), "Salva pianificazione")
        self.assertContains(self.client.get(reverse("admin_portale:automazioni_rule_list")), "Processi del modulo")
        response = self.client.post(reverse("admin_portale:automazioni_pianificati_action"),
            {"name": self.binding.code, "action": "save_schedule", "schedule_type": "I", "minutes": "7", "cron": ""})
        self.assertEqual(response.status_code, 302)
        self.binding.refresh_from_db()
        self.assertEqual(self.binding.minutes, 7)
        self.assertEqual(Schedule.objects.get(name=self.binding.code).minutes, 7)

    def setUp(self):
        install_flows()
        self.binding = ManagedFlow.objects.select_related("rule").get(code="automation_queue")

    def package(self, *, code="automation_queue", manual=False, native=False):
        spec = spec_by_name(code)
        p = {"id": "synthetic-task", "name": "synthetic", "func": spec["func"] if native else "automazioni.managed_flows.run_managed_flow",
             "args": () if native else (code,), "kwargs": spec.get("kwargs", {}) if native else {}}
        if not manual:
            p["group"] = code
        return SignedPackage.dumps(p)

    def test_install_preserves_personalized_actions_and_disabled_state(self):
        rule = self.binding.rule
        rule.is_active = False
        rule.save(update_fields=["is_active"])
        rule.actions.update(config_json={"run_if": {"field": "weekday", "operator": "equals", "value": "1"}})
        self.assertEqual(install_flows(), 0)
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)
        self.assertIn("run_if", rule.actions.get().config_json)
        self.assertEqual(ManagedFlow.objects.count(), len(catalog()))

    def test_dispatch_uses_designer_and_logs_without_native_data(self):
        callback = Mock(return_value={"secret_runtime_data": "not-for-logs"})
        with patch("automazioni.managed_flows.import_string", return_value=callback):
            result = run_managed_flow(self.binding.code)
        callback.assert_called_once_with(limit=50)
        log = AutomationRunLog.objects.get(pk=result["run_id"])
        self.assertEqual(log.status, "success")
        self.assertNotIn("not-for-logs", str(log.payload_json) + log.result_message)

    def test_disabled_flow_never_calls_native_process(self):
        AutomationRule.objects.filter(pk=self.binding.rule_id).update(is_active=False)
        with patch("automazioni.managed_flows.import_string") as importer:
            self.assertEqual(run_managed_flow(self.binding.code)["status"], "skipped")
        importer.assert_not_called()

    def test_condition_blocks_native_call(self):
        AutomationCondition.objects.create(rule=self.binding.rule, order=1, field_name="module",
                                           operator="equals", expected_value="another-module", value_type="string")
        with patch("automazioni.managed_flows.import_string") as importer:
            self.assertEqual(run_managed_flow(self.binding.code)["status"], "skipped")
        importer.assert_not_called()

    def test_preview_does_not_execute_native_action(self):
        with patch("automazioni.managed_flows.import_string") as importer:
            log = run_rule(self.binding.rule, {}, is_test=True)
        self.assertEqual(log.status, "test")
        importer.assert_not_called()

    def test_native_action_cannot_be_called_without_runtime_context(self):
        log = run_rule(self.binding.rule, {}, is_test=False)
        self.assertEqual(log.status, "error")

    def test_duplicate_native_nodes_do_not_repeat_side_effects(self):
        AutomationAction.objects.create(rule=self.binding.rule, order=2, action_type="native_process")
        callback = Mock(return_value={"ok": True})
        with patch("automazioni.managed_flows.import_string", return_value=callback):
            with self.assertRaises(RuntimeError):
                run_managed_flow(self.binding.code)
        callback.assert_called_once()

    def test_concurrent_lease_skips_without_invoking_process(self):
        ManagedFlow.objects.filter(pk=self.binding.pk).update(running_until=timezone.now()+timedelta(minutes=2))
        self.assertEqual(run_managed_flow(self.binding.code)["reason"], "already_running")

    def test_event_notification_runs_from_designer_and_preserves_result(self):
        callback = Mock(return_value=3)
        fn = event_flow("gs_nuova_specifica", skipped_result=0)(callback)
        self.assertEqual(fn("private in-memory argument"), 3)
        callback.assert_called_once_with("private in-memory argument")
        log = AutomationRunLog.objects.get(rule__managed_flow__code="gs_nuova_specifica")
        self.assertNotIn("private", str(log.payload_json))
        AutomationRule.objects.filter(managed_flow__code="gs_nuova_specifica").update(is_active=False)
        self.assertEqual(fn("private"), 0)
        callback.assert_called_once()

    def test_schedule_persists_after_registration_and_does_not_reset_next_run(self):
        self.binding.schedule_type = "C"
        self.binding.cron = "15 8 * * 1-5"
        self.binding.save()
        s, _ = register_schedule(spec_by_name(self.binding.code))
        self.assertEqual(s.func, "automazioni.managed_flows.run_managed_flow")
        self.assertEqual(s.cron, self.binding.cron)
        initial_next_run = s.next_run
        s, _ = register_schedule(spec_by_name(self.binding.code))
        self.assertEqual(s.next_run, initial_next_run)

    def test_schedule_validation_rejects_zero_or_invalid_cron(self):
        self.assertFalse(ManagedScheduleForm({"schedule_type":"I", "minutes":0, "cron":""}, instance=self.binding).is_valid())
        self.assertFalse(ManagedScheduleForm({"schedule_type":"C", "minutes":1, "cron":"not-cron"}, instance=self.binding).is_valid())

    def test_broker_coalesces_periodic_jobs_but_preserves_manual_jobs(self):
        broker = FlowBroker(list_key=Conf.CLUSTER_NAME)
        first = broker.enqueue(self.package())
        self.assertEqual(broker.enqueue(self.package()), first)
        second = broker.enqueue(self.package(manual=True))
        self.assertNotEqual(first, second)
        broker.acknowledge(first)
        self.assertNotEqual(broker.enqueue(self.package()), first)

    def test_broker_does_not_coalesce_other_flows(self):
        broker = FlowBroker(list_key=Conf.CLUSTER_NAME)
        self.assertNotEqual(broker.enqueue(self.package()), broker.enqueue(self.package(code="approval_mailbox")))

    def test_recovery_requires_stopped_workers_and_archives_all_changes(self):
        with self.assertRaises(CommandError):
            call_command("recover_automation_broker", apply=True, stdout=StringIO())
        for _ in range(3):
            OrmQ.objects.create(key=Conf.CLUSTER_NAME, payload=self.package(native=True), lock=timezone.now()-timedelta(minutes=4))
        manual = OrmQ.objects.create(key=Conf.CLUSTER_NAME, payload=self.package(manual=True), lock=timezone.now())
        call_command("recover_automation_broker", stdout=StringIO())
        self.assertEqual(OrmQ.objects.count(), 4)
        call_command("recover_automation_broker", apply=True, workers_stopped=True, stdout=StringIO())
        self.assertEqual(OrmQ.objects.count(), 2)
        self.assertTrue(OrmQ.objects.filter(pk=manual.pk).exists())
        self.assertEqual(BrokerRecoveryEntry.objects.count(), 3)
        kept = OrmQ.objects.exclude(pk=manual.pk).get()
        self.assertEqual(SignedPackage.loads(kept.payload)["func"], "automazioni.managed_flows.run_managed_flow")

    def test_recovery_preserves_locked_flow_and_invalid_signature(self):
        for offset in (-4, 4):
            OrmQ.objects.create(key=Conf.CLUSTER_NAME, payload=self.package(), lock=timezone.now()+timedelta(minutes=offset))
        OrmQ.objects.create(key=Conf.CLUSTER_NAME, payload="untrusted", lock=timezone.now())
        call_command("recover_automation_broker", apply=True, workers_stopped=True, stdout=StringIO())
        self.assertEqual(OrmQ.objects.count(), 3)
        self.assertEqual(BrokerRecoveryEntry.objects.count(), 0)

    def test_form_preserves_native_action(self):
        action = self.binding.rule.actions.get()
        form = AutomationActionForm({"order":1, "action_type":"native_process", "is_enabled":"on"}, instance=action, source_code="managed_flows")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().action_type, "native_process")

    def test_rule_identity_cannot_be_changed_in_form(self):
        form = AutomationRuleForm(instance=self.binding.rule)
        self.assertTrue(form.fields["source_code"].disabled)

    def test_reconcile_expired_approvals_keeps_decisions_untouched(self):
        from .models import AutomationApproval
        run = AutomationRunLog.objects.create(rule=self.binding.rule, source_code="managed_flows", operation_type="manual", status="waiting_approval")
        approval = AutomationApproval.objects.create(run_log=run, action=self.binding.rule.actions.get(), subject="Synthetic", expires_at=timezone.now()-timedelta(days=1))
        self.assertEqual(reconcile_expired_approvals()["expired"], 1)
        approval.refresh_from_db(); run.refresh_from_db()
        self.assertEqual(approval.status, "expired")
        self.assertEqual(run.status, "skipped")
        self.assertEqual(reconcile_expired_approvals()["expired"], 0)

    def test_expiry_keeps_run_waiting_for_other_pending_approvals(self):
        from .models import AutomationApproval
        run = AutomationRunLog.objects.create(rule=self.binding.rule, source_code="managed_flows", operation_type="manual", status="waiting_approval")
        for offset in (-1, 1):
            AutomationApproval.objects.create(run_log=run, subject="Synthetic", expires_at=timezone.now()+timedelta(days=offset))
        reconcile_expired_approvals()
        run.refresh_from_db()
        self.assertEqual(run.status, "waiting_approval")
