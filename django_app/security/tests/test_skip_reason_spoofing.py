"""Gli elementi scartati dicono perché, e uno spoofing sospetto diventa un alert.

Prima: SKIPPED senza motivo per tutto. Una mail «Microsoft Defender» da un mittente non
Microsoft veniva (giustamente) rifiutata dal parser, ma in silenzio: il tentativo di
spoofing verso la casella SOC non lasciava traccia visibile.
"""
from django.test import TestCase

from security.models import (
    ParseStatus,
    SecurityAlert,
    SecurityEventRecord,
    SecurityMailboxMessage,
    SecurityParserConfig,
    SecurityVulnerabilityFinding,
    SecuritySource,
    SourceType,
)
from security.services.parser_engine import (
    SKIP_NO_PARSER,
    SKIP_PARSER_DISABLED,
    SKIP_UNTRUSTED_SENDER,
    run_pending_parsers,
)
from security.services.rule_engine import evaluate_security_rules
from security.services.security_inbox_pipeline import process_mailbox_message

DEFENDER_BODY = "CVE-2025-12345\nAffected product: Contoso VPN Gateway\nCVSS: 9.8\nExposed devices: 3\nSeverity: Critical"
DEFENDER_PARSER = "microsoft_defender_vulnerability_notification_email_parser"


class SkipReasonTest(TestCase):
    def setUp(self):
        self.source = SecuritySource.objects.create(name="Casella SOC", vendor="Demo", source_type=SourceType.EMAIL)

    def _message(self, sender, subject="Microsoft Defender vulnerability notification", body=DEFENDER_BODY):
        return SecurityMailboxMessage.objects.create(source=self.source, sender=sender, subject=subject, body=body)

    def test_unknown_content_records_no_parser(self):
        msg = self._message("newsletter@example.test", subject="Offerte del mese", body="Niente di rilevante")
        run_pending_parsers()
        msg.refresh_from_db()
        self.assertEqual(msg.parse_status, ParseStatus.SKIPPED)
        self.assertEqual(msg.raw_payload["skip_reason"], SKIP_NO_PARSER)
        self.assertFalse(SecurityEventRecord.objects.filter(event_type="possible_sender_spoofing").exists())

    def test_spoofed_defender_is_flagged_not_parsed(self):
        msg = self._message("defender-noreply@microsoft.com.attacker.example")
        run_pending_parsers()
        msg.refresh_from_db()
        self.assertEqual(msg.raw_payload["skip_reason"], SKIP_UNTRUSTED_SENDER)
        self.assertIn("Microsoft Defender", msg.raw_payload["skip_detail"])
        # Fail-closed resta: nessuna vulnerabilità creata dal contenuto non attendibile.
        self.assertFalse(SecurityVulnerabilityFinding.objects.exists())
        event = SecurityEventRecord.objects.get(event_type="possible_sender_spoofing")
        self.assertNotIn("body", event.payload)
        evaluate_security_rules()
        alert = SecurityAlert.objects.get(event=event)
        self.assertIn("spoofing", alert.title.lower())
        self.assertEqual(alert.decision_trace["claimed_vendor"], "Microsoft Defender")

    def test_repeated_spoofing_reuses_one_alert(self):
        self._message("a@attacker.example")
        self._message("b@attacker.example")
        run_pending_parsers()
        evaluate_security_rules()
        self.assertEqual(SecurityAlert.objects.filter(title__icontains="spoofing").count(), 1)

    def test_trusted_defender_still_parsed(self):
        msg = self._message("defender-noreply@microsoft.com")
        run_pending_parsers()
        msg.refresh_from_db()
        self.assertEqual(msg.parse_status, ParseStatus.PARSED)
        self.assertNotIn("skip_reason", msg.raw_payload)

    def test_disabled_parser_reason(self):
        SecurityParserConfig.objects.create(parser_name=DEFENDER_PARSER, enabled=False)
        msg = self._message("defender-noreply@microsoft.com")
        run_pending_parsers()
        msg.refresh_from_db()
        self.assertEqual(msg.raw_payload["skip_reason"], SKIP_PARSER_DISABLED)

    def test_inbox_pipeline_reports_reason_and_alert(self):
        msg = self._message("security@attacker.example")
        result = process_mailbox_message(msg)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["skip_reason"], SKIP_UNTRUSTED_SENDER)
        self.assertEqual(result["alerts_created"], 1)
