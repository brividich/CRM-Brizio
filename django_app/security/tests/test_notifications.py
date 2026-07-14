"""Outbound notification delivery.

Before this patch SecurityNotificationChannel was configuration with nothing behind it:
no send_mail, no webhook call anywhere in the backend. A critical CVE raised at 22:00
reached nobody until someone opened the dashboard by chance.
"""
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from security.models import (
    SecurityAlert,
    SecurityMailboxMessage,
    SecurityNotificationChannel,
    SecurityNotificationLog,
    SecurityRemediationTicket,
    SecuritySource,
    Severity,
    SourceType,
    Status,
)
from security.services import notifications
from security.services.notifications import (
    notify_alert_created,
    parse_recipients,
    resolve_webhook_url,
)
from security.services.parser_engine import run_pending_parsers
from security.services.rule_engine import evaluate_security_rules


CRITICAL_CVE_BODY = (
    "CVE-2025-9999\nSeverity: Critical\nCVSS score: 9.8\n"
    "Exposed devices: 12\nAffected product: Example Browser\n"
)


class NotificationBaseTest(TestCase):
    def setUp(self):
        self.source = SecuritySource.objects.create(name="Mailbox", vendor="Microsoft", source_type=SourceType.EMAIL)

    def _email_channel(self, **kwargs):
        defaults = dict(
            name="SOC email", channel_type="email", enabled=True,
            severity_min=Severity.WARNING, recipients="soc@example.test",
            notify_on_new_alert=True, notify_on_ticket_created=True, cooldown_minutes=0,
        )
        defaults.update(kwargs)
        return SecurityNotificationChannel.objects.create(**defaults)

    def _alert(self, severity=Severity.CRITICAL, dedup_hash="hash-1"):
        return SecurityAlert.objects.create(
            source=self.source, title="Critical exposed vulnerability CVE-2025-9999",
            severity=severity, status=Status.NEW, dedup_hash=dedup_hash,
            decision_trace={"decision": "alert", "rule": "CVE Critical/CVSS >= 9"},
        )


class EmailDeliveryTests(NotificationBaseTest):
    def test_critical_alert_sends_email(self):
        self._email_channel()

        notify_alert_created(self._alert())

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn("CRITICAL", message.subject)
        self.assertIn("CVE-2025-9999", message.subject)
        self.assertEqual(message.to, ["soc@example.test"])
        self.assertIn("CVE Critical/CVSS >= 9", message.body)

    def test_delivery_is_audited(self):
        channel = self._email_channel()

        notify_alert_created(self._alert())

        log = SecurityNotificationLog.objects.get()
        self.assertEqual(log.channel, channel)
        self.assertEqual(log.outcome, SecurityNotificationLog.Outcome.SENT)
        self.assertEqual(log.event_kind, "alert_created")
        self.assertEqual(log.recipients_count, 1)

    def test_body_does_not_leak_raw_payload(self):
        self._email_channel()
        alert = self._alert()
        alert.decision_trace = {"decision": "alert", "rule": "r", "raw_body": "SECRET-PAYLOAD-XYZ"}
        alert.save(update_fields=["decision_trace"])

        notify_alert_created(alert)

        self.assertNotIn("SECRET-PAYLOAD-XYZ", mail.outbox[0].body)

    def test_multiple_recipients_are_parsed(self):
        self._email_channel(recipients="a@example.test, b@example.test\nc@example.test")

        notify_alert_created(self._alert())

        self.assertEqual(sorted(mail.outbox[0].to), ["a@example.test", "b@example.test", "c@example.test"])

    def test_email_channel_without_recipients_is_logged_as_failed(self):
        self._email_channel(recipients="")

        notify_alert_created(self._alert())

        self.assertEqual(len(mail.outbox), 0)
        log = SecurityNotificationLog.objects.get()
        self.assertEqual(log.outcome, SecurityNotificationLog.Outcome.FAILED)
        self.assertIn("no recipients", log.error_message)


class SeverityAndSubscriptionTests(NotificationBaseTest):
    def test_alert_below_channel_threshold_is_not_sent(self):
        self._email_channel(severity_min=Severity.CRITICAL)

        notify_alert_created(self._alert(severity=Severity.WARNING))

        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(SecurityNotificationLog.objects.count(), 0)

    def test_alert_at_channel_threshold_is_sent(self):
        self._email_channel(severity_min=Severity.HIGH)

        notify_alert_created(self._alert(severity=Severity.HIGH))

        self.assertEqual(len(mail.outbox), 1)

    def test_disabled_channel_receives_nothing(self):
        self._email_channel(enabled=False)

        notify_alert_created(self._alert())

        self.assertEqual(len(mail.outbox), 0)

    def test_channel_not_subscribed_to_alerts_receives_nothing(self):
        self._email_channel(notify_on_new_alert=False)

        notify_alert_created(self._alert())

        self.assertEqual(len(mail.outbox), 0)


class CooldownTests(NotificationBaseTest):
    def test_recurring_alert_is_suppressed_within_cooldown(self):
        self._email_channel(cooldown_minutes=60)
        alert = self._alert()

        notify_alert_created(alert)
        notify_alert_created(alert)

        self.assertEqual(len(mail.outbox), 1)
        outcomes = list(SecurityNotificationLog.objects.values_list("outcome", flat=True).order_by("created_at"))
        self.assertEqual(sorted(outcomes), ["cooldown", "sent"])

    def test_cooldown_does_not_silence_a_different_alert(self):
        """Cooldown is scoped per dedup_hash: a noisy alert must not mute an unrelated one."""
        self._email_channel(cooldown_minutes=60)

        notify_alert_created(self._alert(dedup_hash="hash-A"))
        notify_alert_created(self._alert(dedup_hash="hash-B"))

        self.assertEqual(len(mail.outbox), 2)

    def test_cooldown_expires(self):
        self._email_channel(cooldown_minutes=60)
        alert = self._alert()
        notify_alert_created(alert)

        old = timezone.now() - timezone.timedelta(minutes=90)
        SecurityNotificationLog.objects.update(created_at=old)

        notify_alert_created(alert)
        self.assertEqual(len(mail.outbox), 2)


class TeamsWebhookTests(NotificationBaseTest):
    def _teams_channel(self, **kwargs):
        defaults = dict(
            name="SOC Teams", channel_type="teams_webhook", enabled=True,
            severity_min=Severity.WARNING, webhook_url_secret_ref="https://hooks.example.test/abc",
            notify_on_new_alert=True, cooldown_minutes=0,
        )
        defaults.update(kwargs)
        return SecurityNotificationChannel.objects.create(**defaults)

    def test_webhook_is_posted(self):
        self._teams_channel()

        with mock.patch("security.services.notifications._post_teams_webhook") as post:
            notify_alert_created(self._alert())

        post.assert_called_once()
        url, subject, _body, severity = post.call_args[0]
        self.assertEqual(url, "https://hooks.example.test/abc")
        self.assertIn("CVE-2025-9999", subject)
        self.assertEqual(severity, Severity.CRITICAL)
        self.assertEqual(SecurityNotificationLog.objects.get().outcome, SecurityNotificationLog.Outcome.SENT)

    def test_webhook_failure_is_logged_not_raised(self):
        self._teams_channel()

        with mock.patch("security.services.notifications._post_teams_webhook", side_effect=RuntimeError("webhook unreachable")):
            notify_alert_created(self._alert())  # must not raise

        log = SecurityNotificationLog.objects.get()
        self.assertEqual(log.outcome, SecurityNotificationLog.Outcome.FAILED)
        self.assertIn("unreachable", log.error_message)

    def test_webhook_url_can_come_from_a_setting_reference(self):
        channel = self._teams_channel(webhook_url_secret_ref="TEAMS_WEBHOOK_URL")

        with mock.patch("security.services.notifications.get_setting", return_value="https://hooks.example.test/from-setting"):
            self.assertEqual(resolve_webhook_url(channel), "https://hooks.example.test/from-setting")

    def test_missing_webhook_url_is_logged_as_failed(self):
        self._teams_channel(webhook_url_secret_ref="")

        notify_alert_created(self._alert())

        self.assertEqual(SecurityNotificationLog.objects.get().outcome, SecurityNotificationLog.Outcome.FAILED)


class PipelineIntegrationTests(NotificationBaseTest):
    """The point of the whole patch: a critical CVE arriving at night reaches somebody."""

    def test_defender_critical_cve_email_notifies_soc(self):
        self._email_channel(severity_min=Severity.CRITICAL)
        SecurityMailboxMessage.objects.create(
            source=self.source,
            sender="defender-noreply@microsoft.com",
            subject="New vulnerabilities notification from Microsoft Defender for Endpoint",
            body=CRITICAL_CVE_BODY,
        )

        run_pending_parsers()
        evaluate_security_rules()

        self.assertEqual(SecurityAlert.objects.count(), 1)
        self.assertEqual(SecurityRemediationTicket.objects.count(), 1)
        # one notification for the alert, one for the remediation ticket
        subjects = sorted(message.subject for message in mail.outbox)
        self.assertEqual(len(subjects), 2)
        self.assertTrue(any("[ticket]" in subject for subject in subjects))
        self.assertTrue(all("CRITICAL" in subject for subject in subjects))

    def test_broken_channel_does_not_break_detection(self):
        """Fail-safe: alerts and tickets are still persisted when delivery explodes."""
        self._email_channel()
        SecurityMailboxMessage.objects.create(
            source=self.source,
            sender="defender-noreply@microsoft.com",
            subject="New vulnerabilities notification from Microsoft Defender for Endpoint",
            body=CRITICAL_CVE_BODY,
        )

        with mock.patch("security.services.notifications._send_email", side_effect=RuntimeError("smtp down")):
            run_pending_parsers()
            evaluate_security_rules()

        self.assertEqual(SecurityAlert.objects.count(), 1)
        self.assertEqual(SecurityRemediationTicket.objects.count(), 1)
        self.assertTrue(
            SecurityNotificationLog.objects.filter(outcome=SecurityNotificationLog.Outcome.FAILED).exists()
        )

    def test_no_channel_configured_is_a_no_op(self):
        SecurityMailboxMessage.objects.create(
            source=self.source,
            sender="defender-noreply@microsoft.com",
            subject="New vulnerabilities notification from Microsoft Defender for Endpoint",
            body=CRITICAL_CVE_BODY,
        )

        run_pending_parsers()
        evaluate_security_rules()

        self.assertEqual(SecurityAlert.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(SecurityNotificationLog.objects.count(), 0)


class DashboardChannelTests(NotificationBaseTest):
    def test_dashboard_channel_sends_nothing_but_is_audited(self):
        SecurityNotificationChannel.objects.create(
            name="Dashboard only", channel_type="dashboard", enabled=True,
            severity_min=Severity.INFO, notify_on_new_alert=True, cooldown_minutes=0,
        )

        notify_alert_created(self._alert())

        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(SecurityNotificationLog.objects.get().outcome, SecurityNotificationLog.Outcome.SENT)


class HelpersAndCommandTests(NotificationBaseTest):
    def test_parse_recipients_separators(self):
        self.assertEqual(
            parse_recipients("a@x.test, b@x.test; c@x.test\nd@x.test"),
            ["a@x.test", "b@x.test", "c@x.test", "d@x.test"],
        )
        self.assertEqual(parse_recipients(""), [])

    @override_settings(SECURITY_CENTER_BASE_URL="https://soc.example.test")
    def test_alert_body_contains_deep_link(self):
        self._email_channel()
        alert = self._alert()

        notify_alert_created(alert)

        self.assertIn(f"https://soc.example.test/security/alerts/{alert.pk}/", mail.outbox[0].body)

    def test_test_notification_command_sends(self):
        self._email_channel()

        call_command("send_security_test_notification", "--channel", "SOC email")

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Test notification", mail.outbox[0].subject)

    def test_test_notification_command_unknown_channel(self):
        with self.assertRaises(CommandError):
            call_command("send_security_test_notification", "--channel", "nope")
