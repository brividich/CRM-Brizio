"""Provenance hardening: a spoofed sender must never mint alerts or tickets.

Before this fix two independent weaknesses let anyone able to deliver a mail into the
monitored mailbox impersonate Microsoft Defender:

1. ``MicrosoftDefenderVulnerabilityNotificationEmailParser.can_parse`` matched on
   ``sender + subject + body`` concatenated, so writing "defender-noreply@microsoft.com"
   (or "Microsoft Defender" plus a CVE id) in the BODY was enough to be parsed as a
   genuine notification -> CRITICAL SecurityAlert + Evidence + remediation ticket.
2. ``should_accept_message`` tested the allowlist with a substring match, so the entry
   ``microsoft.com`` also accepted ``defender-noreply@microsoft.com.attacker.io``.
"""
from datetime import datetime, timezone as dt_timezone

from django.test import TestCase

from security.models import (
    SecurityAlert,
    SecurityMailboxMessage,
    SecurityMailboxSource,
    SecurityRemediationTicket,
    SecuritySource,
    SourceType,
)
from security.parsers.microsoft_defender_vulnerability_notification_email_parser import (
    MicrosoftDefenderVulnerabilityNotificationEmailParser,
)
from security.services.mailbox_ingestion import sender_matches_allowlist, should_accept_message
from security.services.mailbox_providers import MailboxMessage, evaluate_sender_authentication
from security.services.parser_engine import run_pending_parsers
from security.services.rule_engine import evaluate_security_rules


CRITICAL_CVE_BODY = (
    "Organization: Example Corp\n"
    "CVE-2025-9999\n"
    "Severity: Critical\n"
    "CVSS score: 9.8\n"
    "Exposed devices: 12\n"
    "Affected product: Example Browser\n"
)
LEGIT_SUBJECT = "New vulnerabilities notification from Microsoft Defender for Endpoint"


def _mailbox_message(sender, subject="Security Report", body="body", **kwargs):
    return MailboxMessage(
        provider_message_id="m1",
        internet_message_id="<m1@example.test>",
        sender=sender,
        recipients=["soc@example.test"],
        subject=subject,
        received_at=datetime.now(dt_timezone.utc),
        body_text=body,
        body_html="",
        attachments=[],
        **kwargs,
    )


class DefenderCanParseProvenanceTests(TestCase):
    """can_parse must decide provenance from the sender field ALONE."""

    def setUp(self):
        self.parser = MicrosoftDefenderVulnerabilityNotificationEmailParser()
        self.source = SecuritySource.objects.create(name="Mailbox", vendor="Microsoft", source_type=SourceType.EMAIL)

    def _message(self, sender, subject=LEGIT_SUBJECT, body=CRITICAL_CVE_BODY):
        return SecurityMailboxMessage.objects.create(
            source=self.source, sender=sender, subject=subject, body=body
        )

    def test_genuine_defender_email_is_still_parsed(self):
        """No regression: legitimate sender + legitimate content is accepted."""
        self.assertTrue(self.parser.can_parse(self._message("defender-noreply@microsoft.com")))

    def test_genuine_defender_email_with_display_name_is_parsed(self):
        message = self._message("Microsoft Defender <defender-noreply@microsoft.com>")
        self.assertTrue(self.parser.can_parse(message))

    def test_trusted_sender_address_in_body_does_not_grant_provenance(self):
        """The core of the vulnerability: the trusted address written in the BODY."""
        body = f"Reply to defender-noreply@microsoft.com for details.\n{CRITICAL_CVE_BODY}"
        message = self._message("attacker@evil.test", subject=LEGIT_SUBJECT, body=body)
        self.assertFalse(self.parser.can_parse(message))

    def test_defender_keywords_in_body_do_not_grant_provenance(self):
        body = f"Microsoft Defender for Endpoint reports:\n{CRITICAL_CVE_BODY}"
        message = self._message("newsletter@marketing.test", subject="Weekly digest", body=body)
        self.assertFalse(self.parser.can_parse(message))

    def test_lookalike_sender_domain_is_rejected(self):
        for spoofed in (
            "defender-noreply@microsoft.com.attacker.io",
            "defender-noreply@notmicrosoft.com",
            "defender-noreply@microsoft.com.evil.test",
            "microsoft.com@attacker.test",
        ):
            with self.subTest(sender=spoofed):
                self.assertFalse(self.parser.can_parse(self._message(spoofed)))

    def test_missing_sender_is_rejected(self):
        self.assertFalse(self.parser.can_parse(self._message("")))

    def test_trusted_sender_with_unrelated_content_is_not_claimed(self):
        """Content still decides the report FORMAT, once provenance is established."""
        message = self._message(
            "billing@microsoft.com", subject="Your invoice", body="Nothing security related here."
        )
        self.assertFalse(self.parser.can_parse(message))


class SpoofedEmailCreatesNoAlertTests(TestCase):
    """End-to-end: a spoofed mail must not reach alerts/tickets through the pipeline."""

    def setUp(self):
        self.source = SecuritySource.objects.create(name="Mailbox", vendor="Microsoft", source_type=SourceType.EMAIL)

    def test_spoofed_defender_email_generates_no_alert_or_ticket(self):
        SecurityMailboxMessage.objects.create(
            source=self.source,
            sender="attacker@evil.test",
            subject=LEGIT_SUBJECT,
            body=f"defender-noreply@microsoft.com\n{CRITICAL_CVE_BODY}",
        )

        run_pending_parsers()
        evaluate_security_rules()

        self.assertEqual(SecurityAlert.objects.count(), 0)
        self.assertEqual(SecurityRemediationTicket.objects.count(), 0)

    def test_genuine_defender_email_still_creates_alert_and_ticket(self):
        """The same body from the real sender must still produce the alert."""
        SecurityMailboxMessage.objects.create(
            source=self.source,
            sender="defender-noreply@microsoft.com",
            subject=LEGIT_SUBJECT,
            body=CRITICAL_CVE_BODY,
        )

        run_pending_parsers()
        evaluate_security_rules()

        self.assertEqual(SecurityAlert.objects.count(), 1)
        self.assertEqual(SecurityRemediationTicket.objects.count(), 1)


class SenderAllowlistAnchoringTests(TestCase):
    def test_lookalike_domain_with_deceptive_suffix_is_rejected(self):
        self.assertFalse(
            sender_matches_allowlist("defender-noreply@microsoft.com.attacker.io", "defender-noreply@microsoft.com")
        )
        self.assertFalse(sender_matches_allowlist("defender-noreply@microsoft.com.attacker.io", "microsoft.com"))
        self.assertFalse(sender_matches_allowlist("evil@fakemicrosoft.com", "microsoft.com"))

    def test_full_address_entry_requires_exact_match(self):
        self.assertTrue(sender_matches_allowlist("noreply@vendor.test", "noreply@vendor.test"))
        self.assertFalse(sender_matches_allowlist("other@vendor.test", "noreply@vendor.test"))

    def test_domain_entry_matches_any_local_part_of_that_domain(self):
        for entry in ("vendor.test", "@vendor.test"):
            with self.subTest(entry=entry):
                self.assertTrue(sender_matches_allowlist("noreply@vendor.test", entry))
                self.assertTrue(sender_matches_allowlist("alerts@vendor.test", entry))

    def test_subdomain_is_not_implied_by_domain_entry(self):
        self.assertFalse(sender_matches_allowlist("noreply@mail.vendor.test", "vendor.test"))

    def test_display_name_form_is_normalized(self):
        self.assertTrue(sender_matches_allowlist("Vendor Alerts <noreply@vendor.test>", "noreply@vendor.test"))

    def test_empty_allowlist_accepts_everything(self):
        self.assertTrue(sender_matches_allowlist("anyone@anywhere.test", ""))

    def test_should_accept_message_rejects_trap_domain(self):
        source = SecurityMailboxSource.objects.create(
            name="Defender", code="defender", source_type="graph",
            sender_allowlist_text="defender-noreply@microsoft.com",
        )
        trap = _mailbox_message("defender-noreply@microsoft.com.attacker.io")
        legit = _mailbox_message("defender-noreply@microsoft.com")

        self.assertFalse(should_accept_message(source, trap))
        self.assertTrue(should_accept_message(source, legit))


class VerifiedSenderTests(TestCase):
    """Optional hardening: DKIM/SPF/DMARC gate on sources marked as verified-only."""

    def setUp(self):
        self.source = SecurityMailboxSource.objects.create(
            name="Defender", code="defender-verified", source_type="graph",
            sender_allowlist_text="defender-noreply@microsoft.com",
            require_verified_sender=True,
        )

    def test_unverified_message_is_rejected_when_verification_required(self):
        message = _mailbox_message("defender-noreply@microsoft.com", sender_verified=False)
        self.assertFalse(should_accept_message(self.source, message))

    def test_verified_message_is_accepted(self):
        message = _mailbox_message("defender-noreply@microsoft.com", sender_verified=True)
        self.assertTrue(should_accept_message(self.source, message))

    def test_gate_is_opt_in(self):
        self.source.require_verified_sender = False
        self.source.save(update_fields=["require_verified_sender"])
        message = _mailbox_message("defender-noreply@microsoft.com", sender_verified=False)
        self.assertTrue(should_accept_message(self.source, message))

    def test_authentication_results_parsing(self):
        def headers(value):
            return [{"name": "Authentication-Results", "value": value}]

        verified, _ = evaluate_sender_authentication(headers("spf=pass (sender ip is 192.0.2.1) smtp.mailfrom=microsoft.com; dkim=pass; dmarc=pass"))
        self.assertTrue(verified)

        verified, _ = evaluate_sender_authentication(headers("spf=fail; dkim=fail; dmarc=fail"))
        self.assertFalse(verified)

        # DMARC failure overrides an SPF pass (typical of a spoofed envelope).
        verified, _ = evaluate_sender_authentication(headers("spf=pass; dkim=none; dmarc=fail"))
        self.assertFalse(verified)

    def test_missing_header_is_not_verified_fail_closed(self):
        verified, summary = evaluate_sender_authentication([])
        self.assertFalse(verified)
        self.assertEqual(summary, "")
