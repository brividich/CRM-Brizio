"""Malformed input must fail closed, never silently look healthy.

Three silent failures this covers:

1. An unreadable CVSS became ``0`` - which every downstream threshold reads as
   "harmless". A critical CVE would slip under the >= 9.0 rule the moment Microsoft
   changed the mail layout, with no warning anywhere.
2. Attachments were cut at 10 000 characters with no trace. The real VPN CSV is 15 KB:
   the rows past the cut were dropped, so per-user/per-IP thresholds were computed on
   partial data and alert candidates silently disappeared.
3. A crashing parser was flagged FAILED in a table nobody reads, with no log line. The
   source stopped producing alerts and the system looked calm.
"""
from datetime import datetime, timezone as dt_timezone
from unittest import mock

from django.test import TestCase, override_settings

from security.models import (
    ParseStatus,
    SecurityAlert,
    SecurityMailboxMessage,
    SecurityMailboxSource,
    SecurityRemediationTicket,
    SecuritySource,
    SecuritySourceFile,
    SecurityVulnerabilityFinding,
    Severity,
    SourceType,
)
from security.parsers.microsoft_defender_vulnerability_notification_email_parser import (
    microsoft_defender_vulnerability_notification_email_parser as parse_defender,
)
from security.services.mailbox_ingestion import (
    _attachment_source_type,
    attachment_max_chars,
    ingest_mailbox_message,
)
from security.services.mailbox_providers import MailboxAttachment, MailboxMessage
from security.services.parser_engine import _coerce_cvss, run_pending_parsers
from security.services.rule_engine import evaluate_security_rules


SENDER = "defender-noreply@microsoft.com"
SUBJECT = "New vulnerabilities notification from Microsoft Defender for Endpoint"


class CvssParsingTests(TestCase):
    def test_unreadable_cvss_is_flagged_not_zeroed(self):
        parsed = parse_defender(
            SUBJECT,
            "CVE-2025-1000\nCVSS score: not available\nExposed devices: 4\nAffected product: Edge",
            sender=SENDER,
        )
        finding = parsed["findings"][0]

        self.assertIsNone(finding["cvss"])          # never a confident 0.0
        self.assertTrue(finding["cvss_unparsed"])
        self.assertTrue(any("CVSS" in warning for warning in parsed["parse_warnings"]))

    def test_out_of_range_cvss_is_treated_as_unparsed(self):
        parsed = parse_defender(
            SUBJECT,
            "CVE-2025-1001\nCVSS score: 98\nExposed devices: 4\nAffected product: Edge",
            sender=SENDER,
        )
        finding = parsed["findings"][0]

        self.assertIsNone(finding["cvss"])
        self.assertTrue(finding["cvss_unparsed"])

    def test_absent_cvss_is_not_an_unparsed_cvss(self):
        """No CVSS mentioned at all is different from a CVSS we failed to read."""
        parsed = parse_defender(
            SUBJECT,
            "CVE-2025-1002\nSeverity: Critical\nExposed devices: 4\nAffected product: Edge",
            sender=SENDER,
        )
        finding = parsed["findings"][0]

        self.assertIsNone(finding["cvss"])
        self.assertFalse(finding["cvss_unparsed"])
        self.assertFalse(finding["severity_unrecognized"])

    def test_valid_cvss_still_parses(self):
        parsed = parse_defender(
            SUBJECT,
            "CVE-2025-1003\nSeverity: Critical\nCVSS score: 9,8\nExposed devices: 4\nAffected product: Edge",
            sender=SENDER,
        )
        finding = parsed["findings"][0]

        self.assertEqual(finding["cvss"], 9.8)
        self.assertFalse(finding["cvss_unparsed"])

    def test_unrecognized_severity_is_flagged(self):
        parsed = parse_defender(
            SUBJECT,
            "CVE-2025-1004\nSeverity: Sev-Unknown-9\nCVSS score: n/d\nExposed devices: 2\nAffected product: Edge",
            sender=SENDER,
        )
        finding = parsed["findings"][0]

        self.assertTrue(finding["severity_unrecognized"])
        self.assertEqual(finding["severity"], Severity.HIGH)  # fallback, but declared

    def test_coerce_cvss_helper(self):
        self.assertEqual(_coerce_cvss(9.8), (9.8, False))
        self.assertEqual(_coerce_cvss(None), (0.0, True))
        self.assertEqual(_coerce_cvss("garbage"), (0.0, True))
        self.assertEqual(_coerce_cvss(42), (0.0, True))
        self.assertEqual(_coerce_cvss(0.0), (0.0, False))


class FailClosedRuleTests(TestCase):
    def setUp(self):
        self.source = SecuritySource.objects.create(name="Mailbox", vendor="Microsoft", source_type=SourceType.EMAIL)

    def _ingest(self, body):
        SecurityMailboxMessage.objects.create(source=self.source, sender=SENDER, subject=SUBJECT, body=body)
        run_pending_parsers()
        evaluate_security_rules()

    def test_unreadable_vulnerability_with_exposed_devices_raises_alert(self):
        """The core of the fix: unknown score + unknown severity + exposed devices != harmless."""
        self._ingest(
            "CVE-2025-2000\nSeverity: ???\nCVSS score: unavailable\nExposed devices: 7\nAffected product: Edge"
        )

        alert = SecurityAlert.objects.get()
        self.assertEqual(alert.severity, Severity.HIGH)
        self.assertIn("Unreadable vulnerability data", alert.title)
        self.assertTrue(alert.decision_trace["cvss_unparsed"])
        self.assertIn("fail-closed", alert.decision_trace["rule"])
        # Evidence yes (so an operator can look at it), remediation ticket no:
        # the data is not trustworthy enough to drive a fix.
        self.assertEqual(alert.evidence_containers.count(), 1)
        self.assertEqual(SecurityRemediationTicket.objects.count(), 0)

    def test_unreadable_vulnerability_without_exposed_devices_is_kpi_only(self):
        """No exposure, no urgency: this must not become alert noise."""
        self._ingest(
            "CVE-2025-2001\nSeverity: ???\nCVSS score: unavailable\nExposed devices: 0\nAffected product: Edge"
        )

        self.assertEqual(SecurityAlert.objects.count(), 0)

    def test_readable_critical_still_alerts_normally(self):
        self._ingest(
            "CVE-2025-2002\nSeverity: Critical\nCVSS score: 9.8\nExposed devices: 3\nAffected product: Edge"
        )

        alert = SecurityAlert.objects.get()
        self.assertEqual(alert.severity, Severity.CRITICAL)
        self.assertEqual(SecurityRemediationTicket.objects.count(), 1)

    def test_readable_low_score_still_kpi_only(self):
        self._ingest(
            "CVE-2025-2003\nSeverity: Medium\nCVSS score: 5.1\nExposed devices: 3\nAffected product: Edge"
        )

        self.assertEqual(SecurityAlert.objects.count(), 0)

    def test_finding_persists_the_unparsed_flag(self):
        self._ingest(
            "CVE-2025-2004\nSeverity: ???\nCVSS score: unavailable\nExposed devices: 7\nAffected product: Edge"
        )

        finding = SecurityVulnerabilityFinding.objects.get()
        self.assertEqual(finding.cvss, 0.0)                     # the column cannot hold "unknown"
        self.assertTrue(finding.payload["cvss_unparsed"])       # ...but the truth is preserved


class AttachmentTruncationTests(TestCase):
    def setUp(self):
        self.source = SecurityMailboxSource.objects.create(
            name="Mailbox", code="mbx", source_type="mock", enabled=True,
            process_attachments=True, attachment_extensions="csv",
        )

    def _message_with_csv(self, rows):
        content = ("user,ip,login\n" + "\n".join(rows)).encode("utf-8")
        return MailboxMessage(
            provider_message_id="m1", internet_message_id="<m1@example.test>",
            sender="reports@example.test", recipients=["soc@example.test"],
            subject="Report", received_at=datetime.now(dt_timezone.utc),
            body_text="", body_html="",
            attachments=[MailboxAttachment(
                filename="auth.csv", content_type="text/csv",
                content_bytes=content, size_bytes=len(content),
            )],
        )

    def test_default_limit_no_longer_truncates_a_realistic_csv(self):
        """The real authentication CSV is ~16 KB: it must survive intact."""
        rows = [f"user{i}@example.local,10.99.99.{i % 250},2026-04-25 10:{i % 60:02d}:00" for i in range(400)]
        ingest_mailbox_message(self.source, self._message_with_csv(rows))

        source_file = SecuritySourceFile.objects.get()
        self.assertFalse(source_file.raw_payload["content_truncated"])
        self.assertEqual(source_file.content.count("\n"), 400)  # header + 400 rows, last has no \n

    @override_settings(SECURITY_ATTACHMENT_MAX_CHARS=200)
    def test_truncation_is_recorded_never_silent(self):
        rows = [f"user{i}@example.local,10.99.99.{i},2026-04-25 10:00:00" for i in range(50)]
        with self.assertLogs("security.services.mailbox_ingestion", level="WARNING") as logs:
            ingest_mailbox_message(self.source, self._message_with_csv(rows))

        source_file = SecuritySourceFile.objects.get()
        self.assertTrue(source_file.raw_payload["content_truncated"])
        self.assertEqual(source_file.raw_payload["content_chars_stored"], 200)
        self.assertGreater(source_file.raw_payload["content_chars"], 200)
        self.assertTrue(source_file.raw_payload["parse_warnings"])
        self.assertTrue(any("PARTIAL" in line for line in logs.output))

    def test_csv_attachment_is_typed_as_csv_not_email(self):
        ingest_mailbox_message(self.source, self._message_with_csv(["a@example.local,10.99.99.1,x"]))

        self.assertEqual(SecuritySourceFile.objects.get().file_type, SourceType.CSV)

    def test_attachment_source_type_mapping(self):
        self.assertEqual(_attachment_source_type("a.csv"), SourceType.CSV)
        self.assertEqual(_attachment_source_type("a.PDF"), SourceType.PDF)
        self.assertEqual(_attachment_source_type("a.bin"), SourceType.EMAIL)
        self.assertEqual(_attachment_source_type("noext"), SourceType.EMAIL)

    def test_limit_is_configurable(self):
        self.assertEqual(attachment_max_chars(), 500_000)
        with override_settings(SECURITY_ATTACHMENT_MAX_CHARS="not-a-number"):
            self.assertEqual(attachment_max_chars(), 500_000)


class ParserFailureVisibilityTests(TestCase):
    def setUp(self):
        self.source = SecuritySource.objects.create(name="Mailbox", vendor="Microsoft", source_type=SourceType.EMAIL)

    def test_crashing_parser_is_logged_and_recorded(self):
        SecurityMailboxMessage.objects.create(
            source=self.source, sender=SENDER, subject=SUBJECT,
            body="CVE-2025-3000\nSeverity: Critical\nCVSS score: 9.8\nExposed devices: 1\nAffected product: Edge",
        )

        target = (
            "security.parsers.microsoft_defender_vulnerability_notification_email_parser"
            ".MicrosoftDefenderVulnerabilityNotificationEmailParser.parse"
        )
        with mock.patch(target, side_effect=RuntimeError("vendor changed the layout")):
            with self.assertLogs("security.services.parser_engine", level="ERROR") as logs:
                run_pending_parsers()

        message = SecurityMailboxMessage.objects.get()
        self.assertEqual(message.parse_status, ParseStatus.FAILED)
        self.assertIn("vendor changed the layout", message.raw_payload["parser_error"])
        self.assertEqual(
            message.raw_payload["parser_name"],
            "microsoft_defender_vulnerability_notification_email_parser",
        )
        self.assertTrue(any("Parser" in line for line in logs.output))
