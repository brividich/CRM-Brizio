from __future__ import annotations

import hashlib
import logging
import re
from datetime import timedelta
from traceback import format_exception
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import OuterRef, Q, Subquery
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from core.module_registry import resolve_module_label

from .models import AutomationExecution, AutomationJob, Issue, IssueOccurrence, UserProblemReport

logger = logging.getLogger(__name__)

OPEN_ISSUE_STATUSES = (
    Issue.Status.NEW,
    Issue.Status.TRIAGE,
    Issue.Status.IN_PROGRESS,
)

_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I)
_HEX_RE = re.compile(r"\b0x[0-9a-f]+\b", re.I)
_NUMBER_RE = re.compile(r"\b\d+\b")
_MULTISPACE_RE = re.compile(r"\s+")
_QUOTED_RE = re.compile(r"(['\"]).*?\1")
_PATH_DYNAMIC_SEGMENT_RE = re.compile(r"/([^/]+)")

_SEVERITY_RANK = {
    Issue.Severity.LOW: 1,
    Issue.Severity.MEDIUM: 2,
    Issue.Severity.HIGH: 3,
    Issue.Severity.CRITICAL: 4,
}


def get_default_release_version() -> str:
    return str(getattr(settings, "APP_VERSION", "") or "").strip()


def get_default_environment() -> str:
    explicit = str(getattr(settings, "MONITORING_ENVIRONMENT", "") or "").strip()
    if explicit:
        return explicit
    return "development" if getattr(settings, "DEBUG", False) else "production"


def get_exception_traceback(exc: BaseException) -> str:
    return _trim_text("".join(format_exception(type(exc), exc, exc.__traceback__)), 40000)


def resolve_request_module_name(request) -> str:
    resolver_match = getattr(request, "resolver_match", None)
    if resolver_match is not None:
        app_names = [part for part in getattr(resolver_match, "app_names", ()) if part]
        if app_names:
            return str(app_names[0]).strip().lower()

        namespaces = [part for part in getattr(resolver_match, "namespaces", ()) if part]
        if namespaces:
            return str(namespaces[0]).strip().lower()

        view_name = str(getattr(resolver_match, "view_name", "") or "").strip()
        if ":" in view_name:
            return view_name.split(":", 1)[0].strip().lower()

        func = getattr(resolver_match, "func", None)
        module_name = str(getattr(func, "__module__", "") or "").strip()
        if module_name:
            return module_name.split(".", 1)[0].strip().lower()

    path = str(getattr(request, "path", "") or "").strip("/")
    if not path:
        return "dashboard"
    first_segment = path.split("/", 1)[0].strip().lower()
    if first_segment in {"admin-portale", "admin"}:
        return "admin_portale"
    return first_segment or "core"


def build_request_event_context(request) -> dict[str, object]:
    user = getattr(request, "user", None)
    resolver_match = getattr(request, "resolver_match", None)
    legacy_user = getattr(request, "legacy_user", None)
    legacy_user_id = getattr(legacy_user, "id", None)

    if legacy_user_id is None and getattr(user, "is_authenticated", False):
        try:
            legacy_user_id = getattr(user.profile, "legacy_user_id", None)
        except Exception:
            legacy_user_id = None

    return {
        "method": str(getattr(request, "method", "") or "").upper(),
        "current_url": request.get_full_path() if hasattr(request, "get_full_path") else str(getattr(request, "path", "") or ""),
        "route_name": getattr(resolver_match, "view_name", "") or "",
        "module_name": resolve_request_module_name(request),
        "view_name": getattr(getattr(request, "resolver_match", None), "view_name", "") or "",
        "user": user if getattr(user, "is_authenticated", False) else None,
        "legacy_user_id": legacy_user_id,
        "session_key": getattr(getattr(request, "session", None), "session_key", "") or "",
        "request_id": (
            request.headers.get("X-Request-ID")
            or request.META.get("HTTP_X_REQUEST_ID")
            or request.META.get("REQUEST_ID")
            or ""
        ),
        "user_agent": request.META.get("HTTP_USER_AGENT", "") or "",
        "remote_addr": _get_client_ip(request),
        "release_version": get_default_release_version(),
        "environment": get_default_environment(),
    }


def build_issue_fingerprint(
    *,
    source: str,
    category: str = "",
    exception_class: str = "",
    route_name: str = "",
    current_url: str = "",
    module_name: str = "",
    message: str = "",
    job_code: str = "",
) -> str:
    path_part = _normalize_path(current_url)
    message_part = _stable_message_part(message)
    base = "|".join(
        [
            str(source or "").strip().lower(),
            str(category or "").strip().lower(),
            str(job_code or "").strip().lower(),
            str(exception_class or "").strip().lower(),
            str(route_name or path_part or "").strip().lower(),
            str(module_name or "").strip().lower(),
            message_part,
        ]
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def build_issue_title(
    *,
    category: str,
    source: str,
    module_name: str = "",
    route_name: str = "",
    current_url: str = "",
    status_code: int | None = None,
    job_name: str = "",
    job_code: str = "",
    message: str = "",
    consecutive_failures: int | None = None,
) -> str:
    module_label = _display_module_name(module_name, route_name=route_name, current_url=current_url)
    if category == Issue.Category.USER_REPORT:
        return f"Segnalazione utente: {_title_snippet(message, fallback='problema segnalato')}"

    if source in {Issue.Source.AUTOMATION, Issue.Source.SYSTEM_WATCHDOG}:
        job_label = str(job_name or job_code or module_label or "job").strip()
        lower_message = str(message or "").lower()
        if "non risulta eseguito" in lower_message or "non eseguito" in lower_message:
            return f"Automazione {job_label} non eseguita nei tempi attesi"
        if "bloccata" in lower_message or "troppo tempo" in lower_message:
            return f"Automazione {job_label} bloccata"
        if consecutive_failures and consecutive_failures > 1:
            return f"Automazione {job_label} fallita {consecutive_failures} volte consecutive"
        return f"Errore automazione {job_label}"

    if category == Issue.Category.PERFORMANCE:
        return f"Richiesta lenta in {module_label}"
    if status_code == 403 or category == Issue.Category.ACL:
        return f"Accesso negato inatteso in {module_label}"
    if status_code == 500:
        return f"Errore 500 in {module_label}"
    if status_code:
        return f"Errore {status_code} in {module_label}"
    return f"Errore in {module_label}"


def register_issue_occurrence(
    issue: Issue,
    *,
    occurred_at=None,
    source: str,
    category: str,
    severity: str,
    status_code: int | None = None,
    method: str = "",
    current_url: str = "",
    route_name: str = "",
    module_name: str = "",
    view_name: str = "",
    user=None,
    username_snapshot: str = "",
    legacy_user_id: int | None = None,
    session_key: str = "",
    request_id: str = "",
    message: str = "",
    exception_class: str = "",
    traceback_text: str = "",
    user_agent: str = "",
    remote_addr: str = "",
    extra_json: dict | None = None,
    release_version: str = "",
    environment: str = "",
) -> IssueOccurrence:
    return IssueOccurrence.objects.create(
        issue=issue,
        occurred_at=occurred_at or timezone.now(),
        source=source,
        category=category,
        severity=severity,
        status_code=status_code,
        method=(method or "")[:16],
        current_url=(current_url or "")[:500],
        route_name=(route_name or "")[:200],
        module_name=(module_name or "")[:100],
        view_name=(view_name or "")[:255],
        user=user if getattr(user, "is_authenticated", False) else None,
        username_snapshot=_username_snapshot(user, username_snapshot),
        legacy_user_id=legacy_user_id,
        session_key=(session_key or "")[:64],
        request_id=(request_id or "")[:128],
        message=_trim_text(message, 4000),
        exception_class=(exception_class or "")[:255],
        traceback_text=_trim_text(traceback_text, 40000),
        user_agent=(user_agent or "")[:500],
        remote_addr=(remote_addr or "")[:64],
        extra_json=extra_json or {},
        release_version=(release_version or get_default_release_version())[:64],
        environment=(environment or get_default_environment())[:64],
    )


def open_or_update_issue_from_web_error(
    *,
    title: str = "",
    category: str = Issue.Category.SYSTEM,
    severity: str = Issue.Severity.HIGH,
    source: str = Issue.Source.WEB,
    status_code: int | None = None,
    method: str = "",
    current_url: str = "",
    route_name: str = "",
    module_name: str = "",
    view_name: str = "",
    user=None,
    legacy_user_id: int | None = None,
    session_key: str = "",
    request_id: str = "",
    message: str = "",
    exception_class: str = "",
    traceback_text: str = "",
    user_agent: str = "",
    remote_addr: str = "",
    extra_json: dict | None = None,
    occurred_at=None,
    release_version: str = "",
    environment: str = "",
) -> Issue:
    occurred_at = occurred_at or timezone.now()
    release_version = release_version or get_default_release_version()
    environment = environment or get_default_environment()
    fingerprint = build_issue_fingerprint(
        source=source,
        category=category,
        exception_class=exception_class or f"http-{status_code or 'error'}",
        route_name=route_name,
        current_url=current_url,
        module_name=module_name,
        message=message,
    )
    title = title or build_issue_title(
        category=category,
        source=source,
        module_name=module_name,
        route_name=route_name,
        current_url=current_url,
        status_code=status_code,
        message=message,
    )

    with transaction.atomic():
        issue = (
            Issue.objects.select_for_update()
            .filter(fingerprint=fingerprint, status__in=OPEN_ISSUE_STATUSES)
            .order_by("-last_seen_at", "-id")
            .first()
        )
        if issue is None:
            issue = _create_issue(
                fingerprint=fingerprint,
                title=title,
                category=category,
                severity=severity,
                source=source,
                occurred_at=occurred_at,
                module_name=module_name,
                current_url=current_url,
                route_name=route_name,
                user=user if source == Issue.Source.USER_MANUAL else None,
                release_version=release_version,
                environment=environment,
            )
        else:
            _update_issue_rollup(
                issue,
                occurred_at=occurred_at,
                severity=severity,
                module_name=module_name,
                current_url=current_url,
                route_name=route_name,
                release_version=release_version,
                environment=environment,
                user=user,
            )

        register_issue_occurrence(
            issue,
            occurred_at=occurred_at,
            source=source,
            category=category,
            severity=severity,
            status_code=status_code,
            method=method,
            current_url=current_url,
            route_name=route_name,
            module_name=module_name,
            view_name=view_name,
            user=user,
            legacy_user_id=legacy_user_id,
            session_key=session_key,
            request_id=request_id,
            message=message,
            exception_class=exception_class,
            traceback_text=traceback_text,
            user_agent=user_agent,
            remote_addr=remote_addr,
            extra_json=extra_json,
            release_version=release_version,
            environment=environment,
        )

    notify_admins_for_critical_issue(issue)
    return issue


def open_or_update_issue_from_automation_error(
    *,
    job: AutomationJob,
    title: str = "",
    category: str = Issue.Category.AUTOMATION,
    severity: str = Issue.Severity.HIGH,
    source: str = Issue.Source.AUTOMATION,
    message: str = "",
    exception_class: str = "",
    traceback_text: str = "",
    extra_json: dict | None = None,
    occurred_at=None,
    release_version: str = "",
    environment: str = "",
    consecutive_failures: int | None = None,
    run_identifier: str = "",
) -> Issue:
    occurred_at = occurred_at or timezone.now()
    release_version = release_version or get_default_release_version()
    environment = environment or get_default_environment()
    fingerprint = build_issue_fingerprint(
        source=source,
        category=category,
        exception_class=exception_class or "automation-error",
        module_name=job.module_name,
        message=message,
        job_code=job.code,
    )
    title = title or build_issue_title(
        category=category,
        source=source,
        module_name=job.module_name,
        job_name=job.name,
        job_code=job.code,
        message=message,
        consecutive_failures=consecutive_failures,
    )
    payload = {
        "job_code": job.code,
        "job_name": job.name,
        "run_identifier": run_identifier,
        **(extra_json or {}),
    }

    with transaction.atomic():
        issue = (
            Issue.objects.select_for_update()
            .filter(fingerprint=fingerprint, status__in=OPEN_ISSUE_STATUSES)
            .order_by("-last_seen_at", "-id")
            .first()
        )
        if issue is None:
            issue = _create_issue(
                fingerprint=fingerprint,
                title=title,
                category=category,
                severity=severity,
                source=source,
                occurred_at=occurred_at,
                module_name=job.module_name,
                current_url=f"job:{job.code}",
                route_name="",
                user=None,
                release_version=release_version,
                environment=environment,
            )
        else:
            _update_issue_rollup(
                issue,
                occurred_at=occurred_at,
                severity=severity,
                module_name=job.module_name,
                current_url=f"job:{job.code}",
                route_name="",
                release_version=release_version,
                environment=environment,
                user=None,
            )

        register_issue_occurrence(
            issue,
            occurred_at=occurred_at,
            source=source,
            category=category,
            severity=severity,
            current_url=f"job:{job.code}",
            route_name="",
            module_name=job.module_name,
            view_name="",
            user=None,
            legacy_user_id=None,
            session_key="",
            request_id="",
            message=message,
            exception_class=exception_class,
            traceback_text=traceback_text,
            user_agent="",
            remote_addr="",
            extra_json=payload,
            release_version=release_version,
            environment=environment,
        )

    notify_admins_for_critical_issue(issue)
    return issue


def register_user_problem_report(
    *,
    user=None,
    current_url: str = "",
    route_name: str = "",
    module_name: str = "",
    message: str,
    browser_info: str = "",
    extra_json: dict | None = None,
) -> UserProblemReport:
    issue = _find_correlated_issue(current_url=current_url, route_name=route_name, module_name=module_name)
    if issue is None:
        issue = open_or_update_issue_from_web_error(
            category=Issue.Category.USER_REPORT,
            severity=Issue.Severity.MEDIUM,
            source=Issue.Source.USER_MANUAL,
            current_url=current_url,
            route_name=route_name,
            module_name=module_name,
            view_name="",
            user=user,
            message=message,
            exception_class="UserProblemReport",
            traceback_text="",
            user_agent=browser_info,
            remote_addr="",
            extra_json=extra_json or {},
        )
    else:
        with transaction.atomic():
            locked_issue = Issue.objects.select_for_update().get(pk=issue.pk)
            _update_issue_rollup(
                locked_issue,
                occurred_at=timezone.now(),
                severity=Issue.Severity.MEDIUM,
                module_name=module_name or locked_issue.module_name,
                current_url=current_url or locked_issue.current_url,
                route_name=route_name or locked_issue.route_name,
                release_version=get_default_release_version(),
                environment=get_default_environment(),
                user=user,
            )
            register_issue_occurrence(
                locked_issue,
                source=Issue.Source.USER_MANUAL,
                category=Issue.Category.USER_REPORT,
                severity=Issue.Severity.MEDIUM,
                current_url=current_url,
                route_name=route_name,
                module_name=module_name,
                view_name="",
                user=user,
                legacy_user_id=None,
                message=message,
                exception_class="UserProblemReport",
                traceback_text="",
                user_agent=browser_info,
                remote_addr="",
                extra_json=extra_json or {},
                release_version=get_default_release_version(),
                environment=get_default_environment(),
            )
            issue = locked_issue

    return UserProblemReport.objects.create(
        issue=issue,
        user=user if getattr(user, "is_authenticated", False) else None,
        username_snapshot=_username_snapshot(user),
        current_url=(current_url or "")[:500],
        route_name=(route_name or "")[:200],
        module_name=(module_name or "")[:100],
        message=_trim_text(message, 4000),
        browser_info=(browser_info or "")[:500],
        extra_json=extra_json or {},
    )


def register_automation_execution(
    *,
    job: AutomationJob,
    trigger_type: str = AutomationExecution.TriggerType.SCHEDULER,
    run_identifier: str = "",
    message: str = "",
    payload_json: dict | None = None,
    retry_count: int = 0,
    release_version: str = "",
    environment: str = "",
) -> AutomationExecution:
    return AutomationExecution.objects.create(
        job=job,
        started_at=timezone.now(),
        status=AutomationExecution.Status.WARNING,
        trigger_type=trigger_type,
        run_identifier=run_identifier or None,
        message=_trim_text(message, 2000),
        payload_json=payload_json or {},
        retry_count=max(0, int(retry_count or 0)),
        release_version=(release_version or get_default_release_version())[:64],
        environment=(environment or get_default_environment())[:64],
    )


def mark_automation_success(
    execution: AutomationExecution,
    *,
    message: str = "",
    payload_json: dict | None = None,
    status: str = AutomationExecution.Status.SUCCESS,
) -> AutomationExecution:
    finished_at = timezone.now()
    execution.finished_at = finished_at
    execution.duration_seconds = max(0, int((finished_at - execution.started_at).total_seconds()))
    execution.status = status
    execution.message = _trim_text(message, 2000)
    if payload_json is not None:
        execution.payload_json = payload_json
    execution.save(
        update_fields=[
            "finished_at",
            "duration_seconds",
            "status",
            "message",
            "payload_json",
        ]
    )
    return execution


def detect_missed_jobs(*, now=None, create_issues: bool = False) -> list[dict[str, object]]:
    now = now or timezone.now()
    latest_execution = AutomationExecution.objects.filter(job=OuterRef("pk")).order_by("-started_at")
    jobs = (
        AutomationJob.objects.filter(is_active=True, expected_max_interval_minutes__isnull=False)
        .annotate(
            last_started_at=Subquery(latest_execution.values("started_at")[:1]),
            last_status=Subquery(latest_execution.values("status")[:1]),
        )
        .order_by("name", "code")
    )

    alerts: list[dict[str, object]] = []
    for job in jobs:
        interval_minutes = int(job.expected_max_interval_minutes or 0)
        if interval_minutes <= 0:
            continue
        reference_time = job.last_started_at or job.created_at
        expected_at = reference_time + timedelta(minutes=interval_minutes)
        if expected_at > now:
            continue

        alert: dict[str, object] = {
            "job": job,
            "expected_at": expected_at,
            "last_started_at": job.last_started_at,
            "overdue_minutes": int(max(0, (now - expected_at).total_seconds() // 60)),
        }
        if create_issues:
            alert["issue"] = open_or_update_issue_from_automation_error(
                job=job,
                category=Issue.Category.AUTOMATION,
                severity=Issue.Severity.CRITICAL if job.is_critical else Issue.Severity.HIGH,
                source=Issue.Source.SYSTEM_WATCHDOG,
                message=(
                    f"Il job {job.name} ({job.code}) non risulta eseguito entro "
                    f"{interval_minutes} minuti dal controllo atteso."
                ),
                exception_class="MissedAutomationExecution",
                extra_json={
                    "expected_max_interval_minutes": interval_minutes,
                    "last_started_at": job.last_started_at.isoformat() if job.last_started_at else "",
                    "expected_at": expected_at.isoformat(),
                },
                consecutive_failures=None,
            )
        alerts.append(alert)
    return alerts


def detect_stuck_jobs(*, now=None, create_issues: bool = False) -> list[dict[str, object]]:
    now = now or timezone.now()
    executions = (
        AutomationExecution.objects.select_related("job")
        .filter(job__is_active=True, finished_at__isnull=True, job__expected_max_duration_seconds__isnull=False)
        .order_by("started_at")
    )
    alerts: list[dict[str, object]] = []
    for execution in executions:
        threshold_seconds = int(execution.job.expected_max_duration_seconds or 0)
        if threshold_seconds <= 0:
            continue
        deadline = execution.started_at + timedelta(seconds=threshold_seconds)
        if deadline > now:
            continue

        alert: dict[str, object] = {
            "execution": execution,
            "job": execution.job,
            "deadline": deadline,
            "delay_seconds": int(max(0, (now - deadline).total_seconds())),
        }
        if create_issues:
            alert["issue"] = open_or_update_issue_from_automation_error(
                job=execution.job,
                category=Issue.Category.SYSTEM,
                severity=Issue.Severity.CRITICAL if execution.job.is_critical else Issue.Severity.HIGH,
                source=Issue.Source.SYSTEM_WATCHDOG,
                message=(
                    f"Il job {execution.job.name} ({execution.job.code}) risulta in esecuzione "
                    f"da troppo tempo oltre la soglia di {threshold_seconds} secondi."
                ),
                exception_class="StuckAutomationExecution",
                extra_json={
                    "execution_id": execution.pk,
                    "started_at": execution.started_at.isoformat(),
                    "expected_max_duration_seconds": threshold_seconds,
                },
                run_identifier=execution.run_identifier or "",
            )
        alerts.append(alert)
    return alerts


def notify_admins_for_critical_issue(issue: Issue, *, force: bool = False) -> bool:
    if issue.severity != Issue.Severity.CRITICAL:
        return False
    if not bool(getattr(settings, "MONITORING_NOTIFY_CRITICAL_BY_EMAIL", True)):
        return False

    rate_limit_seconds = int(getattr(settings, "MONITORING_EMAIL_RATE_LIMIT_SECONDS", 1800) or 1800)
    cache_key = f"monitoring:critical-notify:{issue.pk}"
    if not force and cache.get(cache_key):
        return False

    recipients = _admin_recipients()
    if not recipients:
        return False

    detail_path = ""
    try:
        detail_path = reverse("monitoring_admin:issue_detail", args=[issue.pk])
    except NoReverseMatch:
        detail_path = ""

    subject = f"[{issue.severity.upper()}] {issue.code} - {issue.title}"
    body = "\n".join(
        [
            f"Codice: {issue.code}",
            f"Titolo: {issue.title}",
            f"Source: {issue.source}",
            f"Categoria: {issue.category}",
            f"Modulo: {issue.module_name or '-'}",
            f"URL/Job: {issue.current_url or '-'}",
            f"First seen: {timezone.localtime(issue.first_seen_at):%d/%m/%Y %H:%M:%S}",
            f"Last seen: {timezone.localtime(issue.last_seen_at):%d/%m/%Y %H:%M:%S}",
            f"Occorrenze: {issue.occurrences_count}",
            f"Ambiente: {issue.environment or '-'}",
            f"Release: {issue.release_version or '-'}",
            f"Dettaglio: {detail_path or 'non disponibile'}",
        ]
    )
    try:
        sent = send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "") or None,
            recipient_list=recipients,
            fail_silently=True,
        )
    except Exception:
        logger.exception("Invio email monitoring fallito per issue=%s", issue.pk)
        return False

    if sent:
        cache.set(cache_key, True, timeout=rate_limit_seconds)
        return True
    return False


def count_consecutive_failures(job: AutomationJob, *, limit: int = 10, exclude_pk: int | None = None) -> int:
    """Conta le esecuzioni FAILED consecutive più recenti del job.

    ``exclude_pk`` esclude l'esecuzione corrente (in stato intermedio)
    dal conteggio, così la soglia viene calcolata sui run già completati.
    """
    failures = 0
    qs = job.executions.order_by("-started_at", "-id")
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    for execution in qs[:limit]:
        if execution.status != AutomationExecution.Status.FAILED:
            break
        failures += 1
    return failures


def _get_client_ip(request) -> str:
    remote_addr = request.META.get("REMOTE_ADDR", "") or ""
    trusted_proxies = getattr(settings, "TRUSTED_PROXY_IPS", set()) or set()
    if remote_addr in trusted_proxies:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "") or ""
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    return remote_addr


def _normalize_path(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    path = parsed.path or raw

    def _replace_segment(match: re.Match[str]) -> str:
        segment = str(match.group(1) or "").strip()
        lowered = segment.lower()
        if _UUID_RE.fullmatch(lowered) or lowered.isdigit():
            return "/:id"
        return f"/{segment}"

    normalized = _PATH_DYNAMIC_SEGMENT_RE.sub(_replace_segment, path)
    normalized = re.sub(r"/{2,}", "/", normalized).strip()
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if len(normalized) > 1:
        normalized = normalized.rstrip("/")
    return normalized


def _stable_message_part(message: str) -> str:
    raw = str(message or "").strip().lower()
    if not raw:
        return ""
    stable = _QUOTED_RE.sub("<value>", raw)
    stable = _UUID_RE.sub("<uuid>", stable)
    stable = _HEX_RE.sub("<hex>", stable)
    stable = _NUMBER_RE.sub("<num>", stable)
    stable = _MULTISPACE_RE.sub(" ", stable).strip()
    return stable[:160]


def _display_module_name(module_name: str, *, route_name: str = "", current_url: str = "") -> str:
    raw = str(module_name or "").strip().lower()
    if raw:
        fallback = raw.replace("_", " ").replace("-", " ").title()
        return resolve_module_label(raw, fallback=fallback)

    route = str(route_name or "").strip()
    if ":" in route:
        return route.split(":", 1)[0].replace("_", " ").title()

    normalized_path = _normalize_path(current_url).strip("/")
    if normalized_path:
        return normalized_path.split("/", 1)[0].replace("-", " ").replace("_", " ").title()
    return "Portale"


def _title_snippet(value: str, *, fallback: str) -> str:
    raw = _MULTISPACE_RE.sub(" ", str(value or "").strip())
    if not raw:
        return fallback
    snippet = raw[:80].rstrip(" .,;:-")
    return snippet or fallback


def _trim_text(value: str, max_length: int) -> str:
    raw = str(value or "")
    if len(raw) <= max_length:
        return raw
    return f"{raw[: max(0, max_length - 16)]}\n...[troncato]"


def _username_snapshot(user, explicit: str = "") -> str:
    explicit = str(explicit or "").strip()
    if explicit:
        return explicit[:255]
    if user is None or not getattr(user, "is_authenticated", False):
        return ""
    full_name = ""
    try:
        full_name = str(user.get_full_name() or "").strip()
    except Exception:
        full_name = ""
    username = str(getattr(user, "username", "") or "").strip()
    return (full_name or username)[:255]


def _create_issue(
    *,
    fingerprint: str,
    title: str,
    category: str,
    severity: str,
    source: str,
    occurred_at,
    module_name: str,
    current_url: str,
    route_name: str,
    user,
    release_version: str,
    environment: str,
) -> Issue:
    issue = None
    last_error = None
    is_regression = Issue.objects.filter(fingerprint=fingerprint).exists()
    for _ in range(5):
        code = _generate_issue_code(occurred_at)
        try:
            issue = Issue.objects.create(
                code=code,
                title=title[:255],
                category=category,
                severity=severity,
                source=source,
                status=Issue.Status.NEW,
                fingerprint=fingerprint,
                first_seen_at=occurred_at,
                last_seen_at=occurred_at,
                occurrences_count=1,
                affected_users_count=1 if getattr(user, "is_authenticated", False) else 0,
                module_name=(module_name or "")[:100],
                current_url=(current_url or "")[:500],
                route_name=(route_name or "")[:200],
                release_version=(release_version or "")[:64],
                environment=(environment or "")[:64],
                is_regression=is_regression,
                created_by_user=user if getattr(user, "is_authenticated", False) else None,
            )
            break
        except IntegrityError as exc:
            last_error = exc
            continue
    if issue is None:
        raise last_error or IntegrityError("Impossibile generare un codice issue univoco.")
    return issue


def _update_issue_rollup(
    issue: Issue,
    *,
    occurred_at,
    severity: str,
    module_name: str,
    current_url: str,
    route_name: str,
    release_version: str,
    environment: str,
    user,
) -> None:
    update_fields = ["last_seen_at", "occurrences_count", "updated_at"]
    issue.last_seen_at = max(issue.last_seen_at, occurred_at) if issue.last_seen_at else occurred_at
    issue.occurrences_count = int(issue.occurrences_count or 0) + 1

    if _SEVERITY_RANK.get(severity, 0) > _SEVERITY_RANK.get(issue.severity, 0):
        issue.severity = severity
        update_fields.append("severity")

    if module_name and issue.module_name != module_name[:100]:
        issue.module_name = module_name[:100]
        update_fields.append("module_name")
    if current_url and issue.current_url != current_url[:500]:
        issue.current_url = current_url[:500]
        update_fields.append("current_url")
    if route_name and issue.route_name != route_name[:200]:
        issue.route_name = route_name[:200]
        update_fields.append("route_name")
    if release_version and issue.release_version != release_version[:64]:
        issue.release_version = release_version[:64]
        update_fields.append("release_version")
    if environment and issue.environment != environment[:64]:
        issue.environment = environment[:64]
        update_fields.append("environment")
    if getattr(user, "is_authenticated", False) and not IssueOccurrence.objects.filter(issue=issue, user=user).exists():
        issue.affected_users_count = int(issue.affected_users_count or 0) + 1
        update_fields.append("affected_users_count")

    issue.save(update_fields=list(dict.fromkeys(update_fields)))


def _generate_issue_code(occurred_at) -> str:
    prefix = f"INC-{timezone.localtime(occurred_at):%Y%m%d}-"
    last_code = (
        Issue.objects.filter(code__startswith=prefix)
        .order_by("-code")
        .values_list("code", flat=True)
        .first()
    )
    sequence = 1
    if last_code and str(last_code).startswith(prefix):
        try:
            sequence = int(str(last_code)[-4:]) + 1
        except ValueError:
            sequence = 1
    return f"{prefix}{sequence:04d}"


def _find_correlated_issue(*, current_url: str, route_name: str, module_name: str) -> Issue | None:
    filters = Q(status__in=OPEN_ISSUE_STATUSES)
    correlation = Q()
    if current_url:
        correlation |= Q(current_url__iexact=current_url)
    if route_name:
        correlation |= Q(route_name__iexact=route_name)
    if module_name:
        correlation |= Q(module_name__iexact=module_name)
    if not correlation:
        return None
    return Issue.objects.filter(filters & correlation).order_by("-last_seen_at", "-id").first()


def _admin_recipients() -> list[str]:
    explicit = getattr(settings, "MONITORING_ADMIN_EMAILS", None)
    if explicit:
        if isinstance(explicit, str):
            emails = [item.strip() for item in explicit.split(",")]
        else:
            emails = [str(item).strip() for item in explicit]
        return [email for email in emails if email]

    admins = getattr(settings, "ADMINS", ()) or ()
    admin_emails = [str(email).strip() for _name, email in admins if str(email).strip()]
    if admin_emails:
        return admin_emails

    User = get_user_model()
    return list(
        User.objects.filter(is_active=True, is_superuser=True)
        .exclude(email="")
        .values_list("email", flat=True)
        .distinct()
    )
