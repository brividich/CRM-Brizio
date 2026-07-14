"""A source that goes quiet must raise an alert.

This is the one failure the rest of the system structurally cannot see: every other check
reasons about data that arrived. If the firewall stops emailing its reports, or the
scheduler dies, nothing turns red - there is simply nothing to turn it red.
"""
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from io import StringIO

from security.models import (
    SecurityAlert,
    SecurityEventRecord,
    SecurityMailboxSource,
    SecurityReport,
    SecuritySource,
    Severity,
    SourceType,
)
from security.services.rule_engine import evaluate_security_rules
from security.services.source_heartbeat import (
    REASON_NO_DATA,
    REASON_NO_RUN,
    evaluate_source_heartbeat,
    grace_hours,
)


class HeartbeatBaseTest(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.mailbox = SecurityMailboxSource.objects.create(
            name="Firewall reports", code="fw", source_type="graph", enabled=True,
            mailbox_address="soc@example.test", expected_every_hours=24,
        )
        self.runtime = SecuritySource.objects.create(
            name="Firewall reports", vendor="mailbox", source_type=SourceType.EMAIL,
        )

    def _report(self, age_hours):
        report = SecurityReport.objects.create(
            source=self.runtime, report_type="t", title="Report",
            parser_name="p", report_date=timezone.localdate(),
        )
        # created_at is auto_now_add: rewrite it to place the report in the past.
        SecurityReport.objects.filter(pk=report.pk).update(
            created_at=self.now - timedelta(hours=age_hours)
        )
        return report

    def _ran(self, age_hours):
        self.mailbox.last_run_at = self.now - timedelta(hours=age_hours)
        self.mailbox.save(update_fields=["last_run_at"])


class SilenceDetectionTests(HeartbeatBaseTest):
    def test_healthy_source_raises_nothing(self):
        self._ran(1)
        self._report(2)

        self.assertEqual(evaluate_source_heartbeat(now=self.now), [])

    def test_report_within_grace_is_still_healthy(self):
        """A report running a little late must not be an alert."""
        self._ran(1)
        self._report(24 + grace_hours() - 1)

        self.assertEqual(evaluate_source_heartbeat(now=self.now), [])

    def test_source_that_stopped_reporting_raises_an_event(self):
        self._ran(1)  # ingestion is running fine...
        self._report(24 + grace_hours() + 5)  # ...but nothing has arrived

        events = evaluate_source_heartbeat(now=self.now)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "source_silent")
        self.assertEqual(events[0].payload["reason"], REASON_NO_DATA)
        self.assertEqual(events[0].severity, Severity.WARNING)

    def test_source_that_never_reported_raises_an_event(self):
        self._ran(1)  # no report at all, ever

        events = evaluate_source_heartbeat(now=self.now)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["reason"], REASON_NO_DATA)

    def test_scheduler_not_running_is_reported_distinctly(self):
        """"No data" and "nobody is even looking" are different failures."""
        self._ran(24 + grace_hours() + 10)
        self._report(1)

        events = evaluate_source_heartbeat(now=self.now)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["reason"], REASON_NO_RUN)

    def test_ingestion_never_ran_is_reported(self):
        events = evaluate_source_heartbeat(now=self.now)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["reason"], REASON_NO_RUN)

    def test_source_without_expectation_is_never_checked(self):
        self.mailbox.expected_every_hours = 0
        self.mailbox.save(update_fields=["expected_every_hours"])

        self.assertEqual(evaluate_source_heartbeat(now=self.now), [])

    def test_disabled_source_is_never_checked(self):
        self.mailbox.enabled = False
        self.mailbox.save(update_fields=["enabled"])

        self.assertEqual(evaluate_source_heartbeat(now=self.now), [])

    @override_settings(SECURITY_SOURCE_SILENCE_GRACE_HOURS=0)
    def test_grace_is_configurable(self):
        self._ran(1)
        self._report(25)  # past 24h, and with no grace that is already too late

        self.assertEqual(len(evaluate_source_heartbeat(now=self.now)), 1)

    def test_silence_is_not_re_raised_the_same_day(self):
        """A source stays quiet for a week: that is one alert, not a daily flood."""
        self._ran(1)
        self._report(100)

        first = evaluate_source_heartbeat(now=self.now)
        second = evaluate_source_heartbeat(now=self.now)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(SecurityEventRecord.objects.filter(event_type="source_silent").count(), 1)


class SilenceReachesTheAlertPathTests(HeartbeatBaseTest):
    def test_silent_source_produces_an_alert_with_evidence(self):
        self._ran(1)
        self._report(200)

        evaluate_source_heartbeat(now=self.now)
        evaluate_security_rules()

        alert = SecurityAlert.objects.get()
        self.assertIn("Source silent", alert.title)
        self.assertEqual(alert.severity, Severity.WARNING)
        self.assertIn("silent", alert.decision_trace["rule"].lower())
        self.assertEqual(alert.evidence_containers.count(), 1)


class HeartbeatCommandTests(HeartbeatBaseTest):
    def test_dry_run_reports_without_writing(self):
        self._ran(1)
        self._report(200)

        out = StringIO()
        call_command("check_security_source_heartbeat", "--dry-run", stdout=out)

        self.assertIn("SILENT fw", out.getvalue())
        self.assertEqual(SecurityEventRecord.objects.count(), 0)
        self.assertEqual(SecurityAlert.objects.count(), 0)

    def test_command_raises_the_alert(self):
        self._ran(1)
        self._report(200)

        out = StringIO()
        call_command("check_security_source_heartbeat", stdout=out)

        self.assertIn("SILENT fw", out.getvalue())
        self.assertEqual(SecurityAlert.objects.count(), 1)

    def test_command_is_quiet_when_all_is_well(self):
        self._ran(1)
        self._report(2)

        out = StringIO()
        call_command("check_security_source_heartbeat", stdout=out)

        self.assertIn("reported within their expected window", out.getvalue())
        self.assertEqual(SecurityAlert.objects.count(), 0)
