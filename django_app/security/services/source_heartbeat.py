"""Source heartbeat: detect the reports that never arrived.

Every other check in this system reasons about what *came in*. That leaves the most
dangerous failure invisible: a source going quiet. If the firewall stops emailing its
reports, or the scheduler stops running, the dashboards stay green - there is simply
nothing to turn them red. The absence of a report is itself the signal.

Two distinct silences, both covered here:

- **no data**: ingestion runs fine, but no report has arrived within the expected cadence
  (the vendor stopped sending, a mailbox rule swallowed the mail, the export job died);
- **no run**: ingestion itself has not run (the scheduler is down), which the first check
  alone cannot distinguish from a healthy quiet period.

The result is an ordinary ``SecurityEventRecord``, so it flows through the existing rule
engine, alert lifecycle, evidence and notification paths like any other finding.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from security.models import (
    SecurityEventRecord,
    SecurityMailboxSource,
    SecurityReport,
    SecuritySource,
    Severity,
    SourceType,
)
from security.services.dedup import make_hash

logger = logging.getLogger(__name__)

DEFAULT_GRACE_HOURS = 6

REASON_NO_DATA = "no_report_within_expected_window"
REASON_NO_RUN = "ingestion_has_not_run"


def grace_hours() -> int:
    """Slack on top of the expected cadence, so a report running a bit late is not an alert."""
    try:
        return max(0, int(getattr(settings, "SECURITY_SOURCE_SILENCE_GRACE_HOURS", DEFAULT_GRACE_HOURS)))
    except (TypeError, ValueError):
        return DEFAULT_GRACE_HOURS


def evaluate_source_heartbeat(now=None) -> list[SecurityEventRecord]:
    """Raise one event per source that has gone quiet beyond its expected cadence."""
    now = now or timezone.now()
    events = []

    for mailbox_source in SecurityMailboxSource.objects.filter(enabled=True).exclude(expected_every_hours=0):
        verdict = _evaluate_one(mailbox_source, now)
        if verdict is None:
            continue
        event = _record_silence(mailbox_source, verdict, now)
        if event:
            events.append(event)
    return events


def _evaluate_one(mailbox_source, now):
    """Return the silence verdict for a source, or None when it is healthy."""
    deadline_hours = mailbox_source.expected_every_hours + grace_hours()
    threshold = now - timezone.timedelta(hours=deadline_hours)

    last_report_at = _last_report_at(mailbox_source)
    last_run_at = mailbox_source.last_run_at

    # The scheduler is not running: no amount of "no data" reasoning is meaningful until
    # this is fixed, and it is the failure most likely to go unnoticed.
    if last_run_at is None or last_run_at < threshold:
        return {
            "reason": REASON_NO_RUN,
            "detail": "Mailbox ingestion has not run within the expected window",
            "last_run_at": last_run_at,
            "last_report_at": last_report_at,
            "hours_silent": _hours_between(last_run_at, now),
            "deadline_hours": deadline_hours,
        }

    if last_report_at is None or last_report_at < threshold:
        return {
            "reason": REASON_NO_DATA,
            "detail": "Ingestion is running but no report arrived within the expected window",
            "last_run_at": last_run_at,
            "last_report_at": last_report_at,
            "hours_silent": _hours_between(last_report_at, now),
            "deadline_hours": deadline_hours,
        }

    return None


def _last_report_at(mailbox_source):
    security_source = SecuritySource.objects.filter(name=mailbox_source.name).first()
    if not security_source:
        return None
    return (
        SecurityReport.objects.filter(source=security_source)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )


def _hours_between(value, now):
    if not value:
        return None
    return round((now - value).total_seconds() / 3600, 1)


def _record_silence(mailbox_source, verdict, now):
    """One event per source per day: a source that stays quiet must not become a daily flood
    of *new* alerts, but it must not fall silent in the alert log either."""
    security_source, _ = SecuritySource.objects.get_or_create(
        name=mailbox_source.name,
        defaults={"source_type": SourceType.EMAIL, "vendor": "mailbox"},
    )
    dedup_hash = make_hash(
        security_source.pk, "source_silent", mailbox_source.code, verdict["reason"], now.date().isoformat()
    )
    if SecurityEventRecord.objects.filter(
        source=security_source, dedup_hash=dedup_hash, event_type="source_silent"
    ).exists():
        return None

    payload = {
        "source_code": mailbox_source.code,
        "source_name": mailbox_source.name,
        "expected_every_hours": mailbox_source.expected_every_hours,
        "alert_candidate": True,
        "severity": Severity.WARNING,
        **{key: (value.isoformat() if hasattr(value, "isoformat") else value) for key, value in verdict.items()},
    }
    logger.warning(
        "Source %s is silent (%s): last report %s, last run %s",
        mailbox_source.code, verdict["reason"], verdict["last_report_at"], verdict["last_run_at"],
    )
    return SecurityEventRecord.objects.create(
        source=security_source,
        event_type="source_silent",
        severity=Severity.WARNING,
        occurred_at=now,
        fingerprint=dedup_hash,
        dedup_hash=dedup_hash,
        payload=payload,
    )
