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


# Esiti di chiusura: «resolved» = il problema è rientrato (non è una disattivazione);
# gli altri dicono «non è un problema» e alimentano la soppressione appresa.
CLOSE_OUTCOMES = {
    "resolved": "Risolto",
    "not_relevant": "Non rilevante",
    "accepted_risk": "Rischio accettato",
}


def close_alert(alert, actor="system", reason="", outcome="resolved", batch="", user=None):
    outcome = outcome if outcome in CLOSE_OUTCOMES else "resolved"
    alert = _transition_alert(
        alert,
        new_status=Status.CLOSED,
        action="close",
        actor=actor,
        reason=reason,
        extra_details={"outcome": outcome},
        closed_at=timezone.now(),
        snoozed_until=None,
    )
    if outcome != "resolved":
        _record_dismissal(alert, outcome, actor, reason, batch, user)
    return alert


def mark_false_positive(alert, actor="system", reason="", batch="", user=None):
    alert = _transition_alert(
        alert,
        new_status=Status.FALSE_POSITIVE,
        action="false_positive",
        actor=actor,
        reason=reason,
        closed_at=timezone.now(),
        snoozed_until=None,
    )
    _record_dismissal(alert, "false_positive", actor, reason, batch, user)
    return alert


def mute_alert(alert, actor="system", reason="", batch="", user=None):
    """Silenzia: l'alert resta in elenco ma non chiede attenzione. Conta come disattivazione."""
    alert = _transition_alert(
        alert,
        new_status=Status.MUTED,
        action="mute",
        actor=actor,
        reason=reason,
        closed_at=None,
        snoozed_until=None,
    )
    _record_dismissal(alert, "mute", actor, reason, batch, user)
    return alert


def _record_dismissal(alert, kind, actor, reason, batch, user=None):
    from security.services.learned_suppression import record_dismissal

    return record_dismissal(alert, kind=kind, actor=actor, reason=reason, batch=batch, user=user)


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


def reopen_alert(alert, actor="system", reason="", user=None):
    alert = _transition_alert(
        alert,
        new_status=Status.OPEN,
        action="reopen",
        actor=actor,
        reason=reason,
        closed_at=None,
        snoozed_until=None,
    )
    # Chi riapre a mano dice «questo è un problema»: la soppressione appresa si spegne.
    from security.services.learned_suppression import on_manual_reopen

    on_manual_reopen(alert, actor=actor, reason=reason, user=user)
    return alert


def _transition_alert(alert, new_status, action, actor, reason="", extra_details=None, **field_updates):
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
        **(extra_details or {}),
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
