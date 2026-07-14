"""Dedup must be enforced by the database, not by hope.

Every dedup path was check-then-create with nothing underneath: `filter(...).exists()`
followed by `create()`. Two workers - Celery, `ingest_security_mailbox --loop`, the Inbox
Workbench, a `--force-reprocess` - could both read "no alert yet" and both create one.
Duplicates therefore appeared during a burst, when the same report arrives twice: exactly
when dedup is supposed to earn its keep.

Partial unique indexes on (source, dedup_hash), scoped to the *active* statuses, now make
the database the arbiter. Losing the race is not an error: it means somebody else created
what we were about to create, so we adopt it.

A true thread race cannot be reproduced on SQLite in-process, so the lost race is
simulated by forcing the INSERT to raise IntegrityError - which is precisely what the
database does to the loser.
"""
from unittest import mock

from django.db import IntegrityError
from django.test import TestCase

from security.models import (
    SecurityAlert,
    SecurityEventRecord,
    SecurityRemediationTicket,
    SecuritySource,
    Severity,
    SourceType,
    Status,
)
from security.services.rule_engine import _get_or_create_active_alert
from security.services.ticketing import (
    create_backup_ticket,
    create_or_update_remediation_ticket_for_vulnerability_finding,
)


class ActiveAlertUniquenessTests(TestCase):
    def setUp(self):
        self.source = SecuritySource.objects.create(name="S", vendor="v", source_type=SourceType.EMAIL)
        self.event = SecurityEventRecord.objects.create(
            source=self.source, event_type="vulnerability_finding", severity=Severity.CRITICAL,
            fingerprint="f", dedup_hash="hash-1", payload={},
        )

    def _create(self):
        return _get_or_create_active_alert(
            source=self.source, event=self.event, title="Alert", severity=Severity.CRITICAL,
            dedup_hash="hash-1", decision_trace={"decision": "alert"},
        )

    def test_second_call_reuses_the_active_alert(self):
        alert_a, created_a = self._create()
        alert_b, created_b = self._create()

        self.assertTrue(created_a)
        self.assertFalse(created_b)
        self.assertEqual(alert_a.pk, alert_b.pk)
        self.assertEqual(SecurityAlert.objects.count(), 1)

    def test_database_rejects_a_second_active_alert_for_the_same_dedup(self):
        """The guarantee itself: not the code's good manners, the database's refusal."""
        self._create()

        with self.assertRaises(IntegrityError):
            SecurityAlert.objects.create(
                source=self.source, title="Duplicate", severity=Severity.CRITICAL,
                status=Status.NEW, dedup_hash="hash-1", decision_trace={},
            )

    def test_losing_the_race_adopts_the_winner_instead_of_crashing(self):
        winner, _ = self._create()

        real_create = SecurityAlert.objects.create
        calls = {"n": 0}

        def racing_create(*args, **kwargs):
            # Simulate the concurrent worker that inserted first: our INSERT is refused.
            calls["n"] += 1
            raise IntegrityError("UNIQUE constraint failed")

        # Force the "no alert visible yet" state, then have the INSERT lose the race.
        with mock.patch.object(SecurityAlert.objects, "filter", side_effect=SecurityAlert.objects.filter):
            with mock.patch.object(SecurityAlert.objects, "create", side_effect=racing_create):
                with mock.patch("security.services.rule_engine._active_alert", side_effect=[None, winner]):
                    alert, created = self._create()

        self.assertEqual(calls["n"], 1)
        self.assertFalse(created, "losing the race must not be reported as a creation")
        self.assertEqual(alert.pk, winner.pk)
        self.assertEqual(SecurityAlert.objects.count(), 1)

    def test_an_unexplained_integrity_error_is_not_swallowed(self):
        """If the constraint fires but no alert exists, something else is wrong: raise."""
        with mock.patch.object(SecurityAlert.objects, "create", side_effect=IntegrityError("boom")):
            with mock.patch("security.services.rule_engine._active_alert", return_value=None):
                with self.assertRaises(IntegrityError):
                    self._create()

    def test_a_closed_alert_does_not_block_a_new_one(self):
        alert, _ = self._create()
        alert.status = Status.CLOSED
        alert.save(update_fields=["status"])

        fresh, created = self._create()

        self.assertTrue(created)
        self.assertNotEqual(fresh.pk, alert.pk)
        self.assertEqual(SecurityAlert.objects.count(), 2)


class ActiveTicketUniquenessTests(TestCase):
    def setUp(self):
        self.source = SecuritySource.objects.create(name="S", vendor="v", source_type=SourceType.EMAIL)
        self.finding = {
            "cve": "CVE-2025-9999", "affected_product": "Edge", "source": "microsoft_defender",
            "organization": "Example", "cvss": 9.8, "exposed_devices": 3, "severity": Severity.CRITICAL,
        }

    def test_database_rejects_a_second_active_ticket_for_the_same_dedup(self):
        create_or_update_remediation_ticket_for_vulnerability_finding(
            self.source, None, None, self.finding, dedup_hash="tick-1"
        )

        with self.assertRaises(IntegrityError):
            SecurityRemediationTicket.objects.create(
                source=self.source, title="Duplicate", dedup_hash="tick-1", status=Status.OPEN,
            )

    def test_losing_the_ticket_race_adopts_the_winner(self):
        winner, _ = create_or_update_remediation_ticket_for_vulnerability_finding(
            self.source, None, None, self.finding, dedup_hash="tick-1"
        )

        with mock.patch("security.services.ticketing._find_existing_vulnerability_ticket", return_value=None):
            with mock.patch.object(
                SecurityRemediationTicket.objects, "create", side_effect=IntegrityError("UNIQUE")
            ):
                ticket, created = create_or_update_remediation_ticket_for_vulnerability_finding(
                    self.source, None, None, self.finding, dedup_hash="tick-1"
                )

        self.assertFalse(created)
        self.assertEqual(ticket.pk, winner.pk)
        self.assertEqual(SecurityRemediationTicket.objects.count(), 1)


class BackupTicketDedupTests(TestCase):
    """A job failing every night used to open a ticket every night: the dedup_hash was
    stored and never checked."""

    def setUp(self):
        self.source = SecuritySource.objects.create(name="S", vendor="v", source_type=SourceType.EMAIL)

    def test_recurring_backup_failure_reuses_the_open_ticket(self):
        first = create_backup_ticket(self.source, None, None, "BCK-NIGHTLY", "backup-hash")
        second = create_backup_ticket(self.source, None, None, "BCK-NIGHTLY", "backup-hash")
        third = create_backup_ticket(self.source, None, None, "BCK-NIGHTLY", "backup-hash")

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.pk, third.pk)
        self.assertEqual(SecurityRemediationTicket.objects.count(), 1)

        first.refresh_from_db()
        self.assertEqual(first.occurrence_count, 3)

    def test_a_closed_backup_ticket_does_not_block_a_new_one(self):
        first = create_backup_ticket(self.source, None, None, "BCK-NIGHTLY", "backup-hash")
        first.status = Status.CLOSED
        first.save(update_fields=["status"])

        second = create_backup_ticket(self.source, None, None, "BCK-NIGHTLY", "backup-hash")

        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(SecurityRemediationTicket.objects.count(), 2)

    def test_different_jobs_get_different_tickets(self):
        create_backup_ticket(self.source, None, None, "BCK-A", "hash-a")
        create_backup_ticket(self.source, None, None, "BCK-B", "hash-b")

        self.assertEqual(SecurityRemediationTicket.objects.count(), 2)
