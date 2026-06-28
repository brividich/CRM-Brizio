from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class Issue(models.Model):
    class Category(models.TextChoices):
        BUG = "bug", "Bug"
        ACL = "acl", "ACL"
        UI = "ui", "UI"
        INTEGRATION = "integration", "Integration"
        AUTOMATION = "automation", "Automation"
        PERFORMANCE = "performance", "Performance"
        DATA = "data", "Data"
        SYSTEM = "system", "System"
        USER_REPORT = "user_report", "Segnalazione utente"

    class Severity(models.TextChoices):
        LOW = "low", "Bassa"
        MEDIUM = "medium", "Media"
        HIGH = "high", "Alta"
        CRITICAL = "critical", "Critica"

    class Source(models.TextChoices):
        WEB = "web", "Web"
        AUTOMATION = "automation", "Automation"
        USER_MANUAL = "user_manual", "Utente"
        SYSTEM_WATCHDOG = "system_watchdog", "Watchdog"

    class Status(models.TextChoices):
        NEW = "new", "Nuova"
        TRIAGE = "triage", "In triage"
        IN_PROGRESS = "in_progress", "In lavorazione"
        RESOLVED = "resolved", "Risolta"
        IGNORED = "ignored", "Ignorata"

    code = models.CharField(max_length=32, unique=True)
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=24, choices=Category.choices, db_index=True)
    severity = models.CharField(max_length=16, choices=Severity.choices, db_index=True)
    source = models.CharField(max_length=24, choices=Source.choices, db_index=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.NEW, db_index=True)
    fingerprint = models.CharField(max_length=64, db_index=True)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now, db_index=True)
    occurrences_count = models.PositiveIntegerField(default=1)
    affected_users_count = models.PositiveIntegerField(default=0)
    module_name = models.CharField(max_length=100, blank=True, default="")
    current_url = models.CharField(max_length=500, blank=True, default="")
    route_name = models.CharField(max_length=200, blank=True, default="")
    release_version = models.CharField(max_length=64, blank=True, default="")
    environment = models.CharField(max_length=64, blank=True, default="")
    is_regression = models.BooleanField(default=False)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="monitoring_issues_assigned",
    )
    created_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="monitoring_issues_created",
    )
    notes_internal = models.TextField(blank=True, default="")
    resolution_summary = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_seen_at", "-id"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["severity"]),
            models.Index(fields=["last_seen_at"]),
            models.Index(fields=["fingerprint"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.title}"


class IssueOccurrence(models.Model):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="occurrences")
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    source = models.CharField(max_length=24, choices=Issue.Source.choices)
    category = models.CharField(max_length=24, choices=Issue.Category.choices)
    severity = models.CharField(max_length=16, choices=Issue.Severity.choices)
    status_code = models.PositiveIntegerField(null=True, blank=True)
    method = models.CharField(max_length=16, blank=True, default="")
    current_url = models.CharField(max_length=500, blank=True, default="")
    route_name = models.CharField(max_length=200, blank=True, default="")
    module_name = models.CharField(max_length=100, blank=True, default="")
    view_name = models.CharField(max_length=255, blank=True, default="")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="monitoring_issue_occurrences",
    )
    username_snapshot = models.CharField(max_length=255, blank=True, default="")
    legacy_user_id = models.IntegerField(null=True, blank=True)
    session_key = models.CharField(max_length=64, blank=True, default="")
    request_id = models.CharField(max_length=128, blank=True, default="")
    message = models.TextField(blank=True, default="")
    exception_class = models.CharField(max_length=255, blank=True, default="")
    traceback_text = models.TextField(blank=True, default="")
    user_agent = models.CharField(max_length=500, blank=True, default="")
    remote_addr = models.CharField(max_length=64, blank=True, default="")
    extra_json = models.JSONField(default=dict, blank=True)
    release_version = models.CharField(max_length=64, blank=True, default="")
    environment = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["occurred_at"]),
            models.Index(fields=["issue", "-occurred_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.issue.code} @ {self.occurred_at:%Y-%m-%d %H:%M:%S}"


class UserProblemReport(models.Model):
    issue = models.ForeignKey(
        Issue,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_problem_reports",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="monitoring_problem_reports",
    )
    username_snapshot = models.CharField(max_length=255, blank=True, default="")
    current_url = models.CharField(max_length=500, blank=True, default="")
    route_name = models.CharField(max_length=200, blank=True, default="")
    module_name = models.CharField(max_length=100, blank=True, default="")
    message = models.TextField()
    browser_info = models.CharField(max_length=500, blank=True, default="")
    extra_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"Report #{self.pk} - {self.username_snapshot or 'anonimo'}"


class AutomationJob(models.Model):
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    module_name = models.CharField(max_length=100, blank=True, default="")
    description = models.TextField(blank=True, default="")
    schedule_hint = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True, db_index=True)
    is_critical = models.BooleanField(default=False, db_index=True)
    expected_max_interval_minutes = models.PositiveIntegerField(null=True, blank=True)
    expected_max_duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    alert_after_consecutive_failures = models.PositiveIntegerField(default=3)
    owners_text = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "code"]

    def __str__(self) -> str:
        return f"{self.name} [{self.code}]"


class AutomationExecution(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        WARNING = "warning", "Warning"
        FAILED = "failed", "Failed"
        MISSED = "missed", "Missed"

    class TriggerType(models.TextChoices):
        SCHEDULER = "scheduler", "Scheduler"
        MANUAL = "manual", "Manual"
        RETRY = "retry", "Retry"
        WATCHDOG = "watchdog", "Watchdog"

    job = models.ForeignKey(AutomationJob, on_delete=models.CASCADE, related_name="executions")
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.WARNING, db_index=True)
    trigger_type = models.CharField(max_length=16, choices=TriggerType.choices, default=TriggerType.SCHEDULER)
    run_identifier = models.CharField(max_length=128, null=True, blank=True)
    message = models.TextField(blank=True, default="")
    exception_class = models.CharField(max_length=255, blank=True, default="")
    traceback_text = models.TextField(blank=True, default="")
    payload_json = models.JSONField(default=dict, blank=True)
    related_issue = models.ForeignKey(
        Issue,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="automation_executions",
    )
    retry_count = models.PositiveIntegerField(default=0)
    release_version = models.CharField(max_length=64, blank=True, default="")
    environment = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        indexes = [
            models.Index(fields=["started_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["job", "-started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.job.code} - {self.status} - {self.started_at:%Y-%m-%d %H:%M:%S}"


class ScheduleControl(models.Model):
    """Stato di abilitazione DUREVOLE di uno Schedule django-q, gestito dalla
    centrale di comando. ``setup_q_schedules`` lo consulta: se ``enabled=False``
    NON registra (ed elimina) lo schedule, anche dopo un redeploy. La cadenza
    resta definita nel codice (``automazioni/schedules.py`` = fonte di verità)."""

    name = models.CharField(max_length=120, unique=True, db_index=True)
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="monitoring_schedule_controls",
    )

    class Meta:
        verbose_name = "controllo schedule"
        verbose_name_plural = "controlli schedule"

    def __str__(self) -> str:
        return f"{self.name} [{'on' if self.enabled else 'off'}]"
