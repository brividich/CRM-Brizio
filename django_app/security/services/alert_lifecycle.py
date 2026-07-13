from django.utils import timezone

from security.models import SecurityAlertActionLog, Status


ACTIVE_ALERT_STATUSES = [
    Status.NEW,
    Status.OPEN,
    Status.ACKNOWLEDGED,
    Status.IN_PROGRESS,
    Status.SNOOZED,
    Status.MUTED,
]

CLOSED_ALERT_STATUSES = [
    Status.CLOSED,
    Status.FALSE_POSITIVE,
    Status.RESOLVED,
    Status.SUPPRESSED,
]


def acknowledge_alert(alert, actor="system", reason=""):
    now = timezone.now()
    return _transition_alert(
        alert,
        new_status=Status.ACKNOWLEDGED,
        action="acknowledge",
        actor=actor,
        reason=reason,
        acknowledged_at=now,
        closed_at=None,
        snoozed_until=None,
    )


def close_alert(alert, actor="system", reason=""):
    return _transition_alert(
        alert,
        new_status=Status.CLOSED,
        action="close",
        actor=actor,
        reason=reason,
        closed_at=timezone.now(),
        snoozed_until=None,
    )


def mark_false_positive(alert, actor="system", reason=""):
    return _transition_alert(
        alert,
        new_status=Status.FALSE_POSITIVE,
        action="false_positive",
        actor=actor,
        reason=reason,
        closed_at=timezone.now(),
        snoozed_until=None,
    )


def snooze_alert(alert, until, actor="system", reason=""):
    return _transition_alert(
        alert,
        new_status=Status.SNOOZED,
        action="snooze",
        actor=actor,
        reason=reason,
        snoozed_until=until,
        closed_at=None,
    )


def reopen_alert(alert, actor="system", reason=""):
    return _transition_alert(
        alert,
        new_status=Status.OPEN,
        action="reopen",
        actor=actor,
        reason=reason,
        closed_at=None,
        snoozed_until=None,
    )


def _transition_alert(alert, new_status, action, actor, reason="", **field_updates):
    old_status = alert.status
    alert.status = new_status
    alert.status_reason = reason or ""
    for field_name, value in field_updates.items():
        setattr(alert, field_name, value)
    alert.save(
        update_fields=[
            "status",
            "status_reason",
            "acknowledged_at",
            "closed_at",
            "snoozed_until",
            "updated_at",
        ]
    )
    details = {
        "old_status": old_status,
        "new_status": new_status,
        "reason": reason,
        "actor": actor,
    }
    if alert.snoozed_until:
        details["snoozed_until"] = alert.snoozed_until.isoformat()
    SecurityAlertActionLog.objects.create(
        alert=alert,
        action=action,
        actor=actor,
        details=details,
    )
    return alert
