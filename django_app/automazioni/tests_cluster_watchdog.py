import json
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone, translation
from django_q.conf import Conf
from django_q.models import OrmQ, Task
from django_q.signing import SignedPackage

from .broker import FlowBroker
from .cluster_watchdog import report_health
from .flow_health import broker_health
from .models import ClusterHeartbeat, ClusterWatchdogState
from monitoring.models import Issue


@override_settings(MONITORING_ADMIN_EMAILS=["operator@example.invalid"],
                   MONITORING_NOTIFY_CRITICAL_BY_EMAIL=True,
                   MONITORING_EMAIL_RATE_LIMIT_SECONDS=1800)
class ClusterWatchdogTests(TestCase):
    def beat(self, instance="synthetic", **kwargs):
        values = {"cluster": Conf.CLUSTER_NAME, "status": "running", "seen_at": timezone.now()}
        values.update(kwargs)
        return ClusterHeartbeat.objects.create(instance=instance, **values)

    def test_empty_queue_is_unhealthy_without_heartbeat(self):
        health = broker_health()
        self.assertEqual(health["queued"], 0)
        self.assertFalse(health["stalled"])
        self.assertTrue(health["unhealthy"])
        self.assertEqual(health["reason"], "worker_unavailable")

    def test_idle_worker_is_healthy_even_without_completed_tasks(self):
        self.beat()
        self.assertFalse(broker_health()["unhealthy"])

    def test_stale_other_cluster_and_stopped_do_not_mask_outage(self):
        self.beat("old", seen_at=timezone.now()-timedelta(seconds=121))
        self.beat("other", cluster="unrelated")
        self.beat("stopped", status="unavailable")
        self.assertTrue(broker_health()["unhealthy"])

    def test_stopped_instance_does_not_override_another_live_instance(self):
        self.beat("live")
        self.beat("stopped", status="unavailable")
        self.assertFalse(broker_health()["unhealthy"])

    def test_live_worker_with_stalled_queue(self):
        self.beat()
        OrmQ.objects.create(key=Conf.CLUSTER_NAME, payload="synthetic", lock=timezone.now())
        health = broker_health()
        self.assertTrue(health["worker_alive"])
        self.assertEqual(health["reason"], "queue_stalled")
        Task.objects.create(id="synthetic", name="synthetic", func="synthetic", cluster=Conf.CLUSTER_NAME,
                            started=timezone.now(), stopped=timezone.now(), success=True)
        self.assertFalse(broker_health()["unhealthy"])

    def test_sentinel_persists_throttles_and_records_stop(self):
        broker = FlowBroker(Conf.CLUSTER_NAME)
        def packet(status):
            return SignedPackage.dumps(SimpleNamespace(cluster_id="instance", status=status))
        with patch("time.monotonic", side_effect=[100, 101, 116, 117]), translation.override("it"):
            broker.set_stat("synthetic", packet(Conf.IDLE), 3)
            first = ClusterHeartbeat.objects.get().seen_at
            broker.set_stat("synthetic", packet(Conf.WORKING), 3)
            self.assertEqual(ClusterHeartbeat.objects.get().seen_at, first)
            broker.set_stat("synthetic", packet(Conf.WORKING), 3)
            self.assertGreaterEqual(ClusterHeartbeat.objects.get().seen_at, first)
            broker.set_stat("synthetic", packet(Conf.STOPPED), 3)
        self.assertEqual(ClusterHeartbeat.objects.get().status, "unavailable")

    def test_command_read_only_and_exit_status(self):
        output = StringIO()
        with self.assertRaises(SystemExit) as raised:
            call_command("automation_health", stdout=output)
        self.assertEqual(raised.exception.code, 2)
        self.assertTrue(json.loads(output.getvalue())["unhealthy"])
        self.assertFalse(ClusterWatchdogState.objects.exists())
        self.beat()
        output = StringIO()
        call_command("automation_health", stdout=output)
        self.assertEqual(json.loads(output.getvalue())["reason"], "ok")

    @patch("core.email_utils.send_hub_mail", return_value=1)
    def test_alert_rate_limit_survives_separate_invocations_and_recovery(self, send):
        health = broker_health()
        self.assertEqual(report_health(health), "sent")
        self.assertEqual(report_health(health), "not_due")
        self.assertEqual(send.call_count, 1)
        self.assertEqual(Issue.objects.filter(module_name="automazioni").count(), 1)
        state = ClusterWatchdogState.objects.get()
        state.notified_at = timezone.now()-timedelta(minutes=31)
        state.save()
        self.assertEqual(report_health(health), "sent")
        self.beat()
        self.assertEqual(report_health(broker_health()), "sent")
        self.assertIn("RIPRISTINATO", send.call_args.args[0])
        self.assertEqual(report_health(broker_health()), "not_due")
        self.assertEqual(Issue.objects.get(module_name="automazioni").status, Issue.Status.RESOLVED)
        self.assertFalse(broker_health()["watchdog_stale"])

    @patch("core.email_utils.send_hub_mail", side_effect=[0, 1, 0, 1])
    def test_failed_alert_and_recovery_are_retried(self, send):
        self.assertEqual(report_health(broker_health()), "failed")
        self.assertIsNone(ClusterWatchdogState.objects.get().notified_at)
        self.assertEqual(report_health(broker_health()), "sent")
        self.beat()
        self.assertEqual(report_health(broker_health()), "failed")
        self.assertTrue(ClusterWatchdogState.objects.get().recovery_pending)
        self.assertEqual(report_health(broker_health()), "sent")
        self.assertFalse(ClusterWatchdogState.objects.get().recovery_pending)

    @override_settings(MONITORING_NOTIFY_CRITICAL_BY_EMAIL=False)
    @patch("core.email_utils.send_hub_mail")
    def test_disabled_email_is_explicit_and_incident_is_visible(self, send):
        self.assertEqual(report_health(broker_health()), "disabled")
        send.assert_not_called()
        self.assertTrue(Issue.objects.filter(module_name="automazioni").exists())

    @patch("core.reminder_recipients.resolve_reminder_recipients", return_value=[])
    def test_missing_recipients_is_explicit(self, recipients):
        self.assertEqual(report_health(broker_health()), "no_recipients")

    @patch("core.email_utils.send_hub_mail", side_effect=RuntimeError("private transport details"))
    def test_transport_exception_does_not_leak_details(self, send):
        self.assertEqual(report_health(broker_health()), "failed")

    def test_watchdog_stale_and_template_alerts(self):
        self.beat()
        ClusterWatchdogState.objects.create(cluster=Conf.CLUSTER_NAME, checked_at=timezone.now()-timedelta(minutes=6))
        health = broker_health()
        self.assertTrue(health["watchdog_stale"])
        # Compile the actual page; avoid global layout dependencies in a unit test.
        from django.template import engines
        template = engines["django"].engine.get_template("automazioni/pages/pianificati.html")
        from django.template.loader_tags import BlockNode
        block = next(node for node in template.nodelist.get_nodes_by_type(BlockNode) if node.name == "content")
        from django.template import Context
        context = Context({"health": health})
        with context.bind_template(template), patch("django.template.loader_tags.IncludeNode.render", return_value=""):
            rendered = block.render(context)
        self.assertIn("Sorveglianza esterna non attiva", rendered)
        self.assertNotIn("Automazioni a rischio", rendered)
