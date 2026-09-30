"""Invoked by Windows Task Scheduler, never by django-q itself."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django_q.conf import Conf

from .models import ClusterWatchdogState


def report_health(health):
    from core.email_utils import send_hub_mail
    from core.reminder_recipients import resolve_reminder_recipients
    from monitoring.models import Issue
    from monitoring.services import get_default_environment, open_or_update_issue_from_health_check, resolve_health_check_issue

    now = timezone.now()
    environment = get_default_environment()
    check_name = f"qcluster:{Conf.CLUSTER_NAME}"
    # Durable rate limit: separate invocations must not depend on LocMemCache.
    with transaction.atomic(using=Conf.ORM):
        state, _ = ClusterWatchdogState.objects.using(Conf.ORM).select_for_update().get_or_create(cluster=Conf.CLUSTER_NAME)
        state.checked_at = now
        unhealthy = health["unhealthy"]
        changed = unhealthy != state.unhealthy
        if unhealthy and changed:
            state.notified_at = None
            state.recovery_pending = False
        elif not unhealthy and changed:
            state.recovery_pending = state.notified_at is not None
            state.notified_at = None
        state.unhealthy = unhealthy
        interval = max(60, int(getattr(settings, "MONITORING_EMAIL_RATE_LIMIT_SECONDS", 1800)))
        due = state.notified_at is None or state.notified_at <= now-timedelta(seconds=interval)
        message = (f"Ambiente: {environment}. Stato: {health['reason']}. Coda: {health['queued']}. "
                   f"Ultimo heartbeat: {health['last_heartbeat']}. "
                   f"Ultimo completamento: {health['last_completed']}.")
        if unhealthy and (changed or due):
            open_or_update_issue_from_health_check(
                check_name=check_name, title="Qcluster non operativo", message=message,
                severity=Issue.Severity.CRITICAL, module_name="automazioni", notify=False,
            )
        elif not unhealthy:
            resolve_health_check_issue(check_name=check_name, summary="Heartbeat e avanzamento coda regolari.")
        outcome = "not_due"
        if (unhealthy and due) or state.recovery_pending:
            if not getattr(settings, "MONITORING_NOTIFY_CRITICAL_BY_EMAIL", True):
                outcome = "disabled"
            else:
                recipients = resolve_reminder_recipients(setting_emails_key="MONITORING_ADMIN_EMAILS")
                outcome = "no_recipients"
                if recipients:
                    label = "ALLARME" if unhealthy else "RIPRISTINATO"
                    try:
                        sent = send_hub_mail(
                            f"[{label}] Qcluster {environment} / {Conf.CLUSTER_NAME}", message, recipients,
                            email_type="Monitoraggio", badge=label, section_label="Qcluster",
                            fail_silently=False,
                        )
                        outcome = "sent" if sent else "failed"
                    except Exception:
                        # No SMTP exceptions/credentials in command output or event logs.
                        outcome = "failed"
                    if outcome == "sent":
                        state.notified_at = now
                        state.recovery_pending = False
        state.save()
    return outcome
