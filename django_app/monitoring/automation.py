from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import contextmanager
from datetime import timedelta
from functools import wraps
from typing import ParamSpec, TypeVar

from django.conf import settings
from django.utils import timezone

from .models import AutomationExecution, AutomationJob, Issue
from .services import (
    count_consecutive_failures,
    detect_missed_jobs,
    detect_stuck_jobs,
    get_default_environment,
    get_default_release_version,
    get_exception_traceback,
    notify_admins_for_critical_issue,
    open_or_update_issue_from_automation_error,
    register_automation_execution,
)

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def get_or_create_automation_job(
    *,
    job_code: str,
    job_name: str,
    module_name: str,
    critical: bool = False,
    description: str = "",
    schedule_hint: str = "",
    expected_max_interval_minutes: int | None = None,
    expected_max_duration_seconds: int | None = None,
    alert_after_consecutive_failures: int = 3,
    owners_text: str = "",
    is_active: bool = True,
) -> AutomationJob:
    defaults = {
        "name": job_name,
        "module_name": module_name,
        "description": description,
        "schedule_hint": schedule_hint,
        "is_active": is_active,
        "is_critical": critical,
        "expected_max_interval_minutes": expected_max_interval_minutes,
        "expected_max_duration_seconds": expected_max_duration_seconds,
        "alert_after_consecutive_failures": max(1, int(alert_after_consecutive_failures or 1)),
        "owners_text": owners_text,
    }
    job, created = AutomationJob.objects.get_or_create(code=job_code, defaults=defaults)
    if created:
        return job

    update_fields: list[str] = []
    for field_name, value in defaults.items():
        if getattr(job, field_name) != value:
            setattr(job, field_name, value)
            update_fields.append(field_name)
    if update_fields:
        job.save(update_fields=update_fields + ["updated_at"])
    return job


@contextmanager
def automation_run_context(
    *,
    job_code: str,
    job_name: str,
    module_name: str,
    critical: bool = False,
    description: str = "",
    schedule_hint: str = "",
    expected_max_interval_minutes: int | None = None,
    expected_max_duration_seconds: int | None = None,
    alert_after_consecutive_failures: int = 3,
    owners_text: str = "",
    trigger_type: str = AutomationExecution.TriggerType.SCHEDULER,
    run_identifier: str = "",
    payload_json: dict | None = None,
    retry_count: int = 0,
    re_raise: bool = True,
    auto_complete_success: bool = True,
):
    job = get_or_create_automation_job(
        job_code=job_code,
        job_name=job_name,
        module_name=module_name,
        critical=critical,
        description=description,
        schedule_hint=schedule_hint,
        expected_max_interval_minutes=expected_max_interval_minutes,
        expected_max_duration_seconds=expected_max_duration_seconds,
        alert_after_consecutive_failures=alert_after_consecutive_failures,
        owners_text=owners_text,
    )
    execution = register_automation_execution(
        job=job,
        trigger_type=trigger_type,
        run_identifier=run_identifier,
        message="Esecuzione avviata",
        payload_json=payload_json or {},
        retry_count=retry_count,
        release_version=get_default_release_version(),
        environment=get_default_environment(),
    )
    context = {"job": job, "execution": execution}
    try:
        yield context
    except Exception as exc:
        _mark_automation_failure(
            execution,
            exc=exc,
            trigger_type=trigger_type,
            payload_json=payload_json or {},
        )
        if re_raise:
            raise
    else:
        if not auto_complete_success:
            return
        _complete_execution(
            execution,
            status=AutomationExecution.Status.SUCCESS,
            message="Esecuzione completata con successo",
            payload_json=payload_json or execution.payload_json,
        )


def monitored_automation(
    *,
    job_code: str,
    job_name: str,
    module_name: str,
    critical: bool = False,
    description: str = "",
    schedule_hint: str = "",
    expected_max_interval_minutes: int | None = None,
    expected_max_duration_seconds: int | None = None,
    alert_after_consecutive_failures: int = 3,
    owners_text: str = "",
    re_raise: bool = True,
) -> Callable[[Callable[P, R]], Callable[P, R | None]]:
    def decorator(func: Callable[P, R]) -> Callable[P, R | None]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | None:
            trigger_type = kwargs.pop("monitoring_trigger_type", AutomationExecution.TriggerType.SCHEDULER)
            run_identifier = kwargs.pop("monitoring_run_identifier", "")
            payload_json = kwargs.pop("monitoring_payload", None) or {}
            retry_count = kwargs.pop("monitoring_retry_count", 0)
            should_reraise = bool(kwargs.pop("monitoring_reraise", re_raise))

            with automation_run_context(
                job_code=job_code,
                job_name=job_name,
                module_name=module_name,
                critical=critical,
                description=description,
                schedule_hint=schedule_hint,
                expected_max_interval_minutes=expected_max_interval_minutes,
                expected_max_duration_seconds=expected_max_duration_seconds,
                alert_after_consecutive_failures=alert_after_consecutive_failures,
                owners_text=owners_text,
                trigger_type=trigger_type,
                run_identifier=run_identifier,
                payload_json=payload_json,
                retry_count=retry_count,
                re_raise=should_reraise,
                auto_complete_success=False,
            ) as ctx:
                result = func(*args, **kwargs)
                completion_message = "Esecuzione completata con successo"
                if isinstance(result, dict):
                    if result.get("monitoring_message"):
                        completion_message = str(result["monitoring_message"])
                    if result.get("monitoring_payload"):
                        ctx["execution"].payload_json = result["monitoring_payload"]
                _complete_execution(
                    ctx["execution"],
                    status=AutomationExecution.Status.SUCCESS,
                    message=completion_message,
                    payload_json=ctx["execution"].payload_json,
                )
                return result

        return wrapper

    return decorator


@monitored_automation(
    job_code="monitoring_healthcheck",
    job_name="Monitoring health check",
    module_name="monitoring",
    critical=True,
    description="Controllo periodico di issue critiche e automazioni mancanti/in errore.",
    schedule_hint="Ogni 5-15 minuti",
    expected_max_interval_minutes=15,
    expected_max_duration_seconds=120,
    alert_after_consecutive_failures=1,
)
def run_monitoring_healthcheck() -> dict[str, object]:
    now = timezone.now()
    missing_jobs = detect_missed_jobs(now=now, create_issues=True)
    stuck_jobs = detect_stuck_jobs(now=now, create_issues=True)
    failing_jobs = _detect_jobs_with_consecutive_failures(now=now)
    stale_critical_issues = _detect_stale_critical_issues(now=now)

    return {
        "monitoring_message": (
            f"Health check completato: missing={len(missing_jobs)}, "
            f"stuck={len(stuck_jobs)}, failing={len(failing_jobs)}, "
            f"stale_critical={len(stale_critical_issues)}"
        ),
        "monitoring_payload": {
            "missing_jobs": [item["job"].code for item in missing_jobs],
            "stuck_jobs": [item["job"].code for item in stuck_jobs],
            "failing_jobs": [item["job"].code for item in failing_jobs],
            "stale_critical_issues": [item["issue"].code for item in stale_critical_issues],
        },
    }


def _complete_execution(
    execution: AutomationExecution,
    *,
    status: str,
    message: str,
    payload_json: dict | None,
    exception_class: str = "",
    traceback_text: str = "",
    related_issue: Issue | None = None,
) -> AutomationExecution:
    finished_at = timezone.now()
    execution.finished_at = finished_at
    execution.duration_seconds = max(0, int((finished_at - execution.started_at).total_seconds()))
    execution.status = status
    execution.message = message
    execution.payload_json = payload_json or {}
    execution.exception_class = exception_class[:255]
    execution.traceback_text = traceback_text
    execution.related_issue = related_issue
    execution.release_version = get_default_release_version()
    execution.environment = get_default_environment()
    execution.save(
        update_fields=[
            "finished_at",
            "duration_seconds",
            "status",
            "message",
            "payload_json",
            "exception_class",
            "traceback_text",
            "related_issue",
            "release_version",
            "environment",
        ]
    )
    return execution


def _mark_automation_failure(
    execution: AutomationExecution,
    *,
    exc: BaseException,
    trigger_type: str,
    payload_json: dict,
) -> AutomationExecution:
    job = execution.job
    trace = get_exception_traceback(exc)
    consecutive_failures = count_consecutive_failures(job) + 1
    issue = None
    if consecutive_failures >= max(1, int(job.alert_after_consecutive_failures or 1)):
        issue = open_or_update_issue_from_automation_error(
            job=job,
            category=Issue.Category.AUTOMATION,
            severity=Issue.Severity.CRITICAL if job.is_critical else Issue.Severity.HIGH,
            source=Issue.Source.AUTOMATION,
            message=str(exc) or f"Errore automazione {job.code}",
            exception_class=exc.__class__.__name__,
            traceback_text=trace,
            extra_json={
                "trigger_type": trigger_type,
                "execution_id": execution.pk,
                "retry_count": execution.retry_count,
            },
            consecutive_failures=consecutive_failures,
            run_identifier=execution.run_identifier or "",
        )
    return _complete_execution(
        execution,
        status=AutomationExecution.Status.FAILED,
        message=str(exc) or "Esecuzione fallita",
        payload_json=payload_json or execution.payload_json,
        exception_class=exc.__class__.__name__,
        traceback_text=trace,
        related_issue=issue,
    )


def _detect_jobs_with_consecutive_failures(*, now) -> list[dict[str, object]]:
    alerts: list[dict[str, object]] = []
    for job in AutomationJob.objects.filter(is_active=True):
        consecutive_failures = count_consecutive_failures(job)
        threshold = max(1, int(job.alert_after_consecutive_failures or 1))
        if consecutive_failures < threshold:
            continue
        issue = open_or_update_issue_from_automation_error(
            job=job,
            category=Issue.Category.AUTOMATION,
            severity=Issue.Severity.CRITICAL if job.is_critical else Issue.Severity.HIGH,
            source=Issue.Source.SYSTEM_WATCHDOG,
            message=f"Il job {job.name} ({job.code}) ha totalizzato {consecutive_failures} fallimenti consecutivi.",
            exception_class="ConsecutiveAutomationFailures",
            extra_json={
                "consecutive_failures": consecutive_failures,
                "checked_at": now.isoformat(),
            },
            consecutive_failures=consecutive_failures,
        )
        alerts.append({"job": job, "issue": issue, "consecutive_failures": consecutive_failures})
    return alerts


def _detect_stale_critical_issues(*, now) -> list[dict[str, object]]:
    threshold_minutes = int(getattr(settings, "MONITORING_WATCHDOG_CRITICAL_UNASSIGNED_MINUTES", 120) or 120)
    deadline = now - timedelta(minutes=threshold_minutes)
    stale_issues = Issue.objects.filter(
        severity=Issue.Severity.CRITICAL,
        status=Issue.Status.NEW,
        assigned_to__isnull=True,
        last_seen_at__lte=deadline,
    ).order_by("last_seen_at", "id")

    alerts: list[dict[str, object]] = []
    watchdog_job = get_or_create_automation_job(
        job_code="monitoring_healthcheck",
        job_name="Monitoring health check",
        module_name="monitoring",
        critical=True,
        description="Controllo periodico di issue critiche e automazioni mancanti/in errore.",
        schedule_hint="Ogni 5-15 minuti",
        expected_max_interval_minutes=15,
        expected_max_duration_seconds=120,
        alert_after_consecutive_failures=1,
    )
    for stale_issue in stale_issues:
        issue = open_or_update_issue_from_automation_error(
            job=watchdog_job,
            category=Issue.Category.SYSTEM,
            severity=Issue.Severity.CRITICAL,
            source=Issue.Source.SYSTEM_WATCHDOG,
            message=(
                f"L'issue critica {stale_issue.code} non e' presa in carico da oltre "
                f"{threshold_minutes} minuti."
            ),
            exception_class="CriticalIssueUnassigned",
            extra_json={
                "stale_issue_id": stale_issue.pk,
                "stale_issue_code": stale_issue.code,
                "last_seen_at": stale_issue.last_seen_at.isoformat(),
            },
        )
        notify_admins_for_critical_issue(issue, force=True)
        alerts.append({"issue": stale_issue, "watchdog_issue": issue})
    return alerts
