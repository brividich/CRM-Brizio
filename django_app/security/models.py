import hashlib
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Severity(models.TextChoices):
    INFO = "info", "Info"
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    WARNING = "warning", "Warning"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class Status(models.TextChoices):
    NEW = "new", "New"
    OPEN = "open", "Open"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    IN_PROGRESS = "in_progress", "In progress"
    SNOOZED = "snoozed", "Snoozed"
    MUTED = "muted", "Muted"
    CLOSED = "closed", "Closed"
    FALSE_POSITIVE = "false_positive", "False positive"
    RESOLVED = "resolved", "Resolved"
    SUPPRESSED = "suppressed", "Suppressed"


class ParseStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PARSED = "parsed", "Parsed"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


class SourceType(models.TextChoices):
    EMAIL = "email", "Email"
    PDF = "pdf", "PDF"
    CSV = "csv", "CSV"
    API = "api", "API"
    MANUAL = "manual", "Manual"


class SettingValueType(models.TextChoices):
    STRING = "string", "String"
    INT = "int", "Integer"
    FLOAT = "float", "Float"
    BOOL = "bool", "Boolean"
    JSON = "json", "JSON"


class ConfigStatus(models.TextChoices):
    OK = "ok", "OK"
    WARNING = "warning", "Warning"
    DISABLED = "disabled", "Disabled"
    MISCONFIGURED = "misconfigured", "Misconfigured"


def empty_setting_value():
    return ""


class SecuritySource(models.Model):
    name = models.CharField(max_length=160, unique=True)
    vendor = models.CharField(max_length=120, blank=True)
    source_type = models.CharField(max_length=32, choices=SourceType.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["source_type", "is_active"]),
        ]

    def __str__(self):
        return self.name


class SecurityCenterSetting(models.Model):
    key = models.CharField(max_length=160, unique=True)
    value = models.JSONField(default=empty_setting_value, blank=True)
    value_type = models.CharField(max_length=16, choices=SettingValueType.choices, default=SettingValueType.STRING)
    category = models.CharField(max_length=80, db_index=True)
    description = models.TextField(blank=True)
    is_secret = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        permissions = [
            ("manage_security_configuration", "Can manage Security Center configuration"),
        ]
        indexes = [
            models.Index(fields=["category", "key"]),
        ]

    def __str__(self):
        return self.key


class SecuritySourceConfig(models.Model):
    FREQUENCY_CHOICES = [
        ("manual", "Manual"),
        ("hourly", "Hourly"),
        ("daily", "Daily"),
        ("weekly", "Weekly"),
        ("monthly", "Monthly"),
    ]

    name = models.CharField(max_length=160, unique=True)
    source_type = models.CharField(max_length=80, db_index=True)
    vendor = models.CharField(max_length=120, blank=True, db_index=True)
    enabled = models.BooleanField(default=True, db_index=True)
    description = models.TextField(blank=True)
    expected_frequency = models.CharField(max_length=24, choices=FREQUENCY_CHOICES, default="daily")
    expected_time_window_start = models.TimeField(null=True, blank=True)
    expected_time_window_end = models.TimeField(null=True, blank=True)
    mailbox_sender_patterns = models.JSONField(default=list, blank=True)
    mailbox_subject_patterns = models.JSONField(default=list, blank=True)
    parser_name = models.CharField(max_length=160, blank=True)
    severity_mapping_json = models.JSONField(default=dict, blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["source_type", "enabled"]),
            models.Index(fields=["vendor", "enabled"]),
        ]

    def __str__(self):
        return self.name


class SecurityParserConfig(models.Model):
    parser_name = models.CharField(max_length=160, unique=True)
    enabled = models.BooleanField(default=True, db_index=True)
    priority = models.PositiveIntegerField(default=100, db_index=True)
    source_type = models.CharField(max_length=80, blank=True, db_index=True)
    input_type = models.CharField(max_length=32, blank=True)
    description = models.TextField(blank=True)
    config_json = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.parser_name


class SecurityAlertRuleConfig(models.Model):
    OPERATOR_CHOICES = [
        ("gt", ">"),
        ("gte", ">="),
        ("lt", "<"),
        ("lte", "<="),
        ("eq", "="),
        ("neq", "!="),
        ("contains", "Contains"),
        ("regex", "Regex"),
        ("baseline_deviation", "Baseline deviation"),
    ]

    code = models.CharField(max_length=160, unique=True)
    name = models.CharField(max_length=200)
    enabled = models.BooleanField(default=True, db_index=True)
    source_type = models.CharField(max_length=80, blank=True, db_index=True)
    metric_name = models.CharField(max_length=120, blank=True, db_index=True)
    condition_operator = models.CharField(max_length=32, choices=OPERATOR_CHOICES, default="gte")
    threshold_value = models.CharField(max_length=120, blank=True)
    threshold_json = models.JSONField(default=dict, blank=True)
    severity = models.CharField(max_length=24, choices=Severity.choices, default=Severity.WARNING)
    cooldown_minutes = models.PositiveIntegerField(default=60)
    dedup_window_minutes = models.PositiveIntegerField(default=1440)
    auto_create_ticket = models.BooleanField(default=False)
    auto_create_evidence_container = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    last_triggered_at = models.DateTimeField(null=True, blank=True)
    trigger_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.name


class SecurityMailboxMessage(models.Model):
    source = models.ForeignKey(SecuritySource, on_delete=models.CASCADE, related_name="mailbox_messages")
    external_id = models.CharField(max_length=255, blank=True, db_index=True)
    sender = models.EmailField(blank=True)
    subject = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    received_at = models.DateTimeField(default=timezone.now, db_index=True)
    parse_status = models.CharField(max_length=24, choices=ParseStatus.choices, default=ParseStatus.PENDING, db_index=True)
    fingerprint = models.CharField(max_length=64, blank=True, db_index=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    pipeline_result = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["source", "received_at"]),
            models.Index(fields=["source", "fingerprint"]),
        ]

    def save(self, *args, **kwargs):
        if not self.fingerprint:
            seed = f"{self.source_id}:{self.external_id}:{self.subject}:{self.received_at.isoformat()}"
            self.fingerprint = hashlib.sha256(seed.encode()).hexdigest()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.subject


class SecuritySourceFile(models.Model):
    source = models.ForeignKey(SecuritySource, on_delete=models.CASCADE, related_name="files")
    original_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=32, choices=SourceType.choices)
    content = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True, db_index=True)
    parse_status = models.CharField(max_length=24, choices=ParseStatus.choices, default=ParseStatus.PENDING, db_index=True)
    fingerprint = models.CharField(max_length=64, blank=True, db_index=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["source", "uploaded_at"]),
            models.Index(fields=["source", "fingerprint"]),
        ]

    def save(self, *args, **kwargs):
        if not self.fingerprint:
            seed = f"{self.source_id}:{self.original_name}:{self.content[:500]}"
            self.fingerprint = hashlib.sha256(seed.encode()).hexdigest()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.original_name


class SecurityReport(models.Model):
    source = models.ForeignKey(SecuritySource, on_delete=models.CASCADE, related_name="reports")
    mailbox_message = models.ForeignKey(SecurityMailboxMessage, on_delete=models.SET_NULL, null=True, blank=True)
    source_file = models.ForeignKey(SecuritySourceFile, on_delete=models.SET_NULL, null=True, blank=True)
    report_type = models.CharField(max_length=100, db_index=True)
    title = models.CharField(max_length=255)
    report_date = models.DateField(default=timezone.localdate, db_index=True)
    parser_name = models.CharField(max_length=160)
    parse_status = models.CharField(max_length=24, choices=ParseStatus.choices, default=ParseStatus.PARSED, db_index=True)
    parsed_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["source", "report_date"]),
            models.Index(fields=["report_type", "parse_status"]),
        ]

    def __str__(self):
        return self.title


class SecurityReportMetric(models.Model):
    report = models.ForeignKey(SecurityReport, on_delete=models.CASCADE, related_name="metrics")
    name = models.CharField(max_length=120, db_index=True)
    value = models.FloatField()
    unit = models.CharField(max_length=40, blank=True)
    labels = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["name", "created_at"]),
        ]


class SecurityAsset(models.Model):
    source = models.ForeignKey(SecuritySource, on_delete=models.SET_NULL, null=True, blank=True)
    hostname = models.CharField(max_length=255, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    asset_type = models.CharField(max_length=80, blank=True)
    owner = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("source", "hostname")]
        indexes = [
            models.Index(fields=["hostname", "asset_type"]),
        ]

    def __str__(self):
        return self.hostname


class SecurityEventRecord(models.Model):
    source = models.ForeignKey(SecuritySource, on_delete=models.CASCADE, related_name="events")
    report = models.ForeignKey(SecurityReport, on_delete=models.SET_NULL, null=True, blank=True, related_name="events")
    asset = models.ForeignKey(SecurityAsset, on_delete=models.SET_NULL, null=True, blank=True)
    event_type = models.CharField(max_length=120, db_index=True)
    severity = models.CharField(max_length=24, choices=Severity.choices, default=Severity.INFO, db_index=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    fingerprint = models.CharField(max_length=64, db_index=True)
    dedup_hash = models.CharField(max_length=64, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    suppressed = models.BooleanField(default=False, db_index=True)
    decision_trace = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["source", "occurred_at"]),
            models.Index(fields=["severity", "occurred_at"]),
            models.Index(fields=["asset", "occurred_at"]),
            models.Index(fields=["dedup_hash", "event_type"]),
        ]

    def __str__(self):
        return f"{self.event_type} {self.severity}"


class SecurityAlert(models.Model):
    source = models.ForeignKey(SecuritySource, on_delete=models.CASCADE, related_name="alerts")
    event = models.ForeignKey(SecurityEventRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name="alerts")
    title = models.CharField(max_length=255)
    severity = models.CharField(max_length=24, choices=Severity.choices, db_index=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.NEW, db_index=True)
    dedup_hash = models.CharField(max_length=64, db_index=True)
    decision_trace = models.JSONField(default=dict)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    snoozed_until = models.DateTimeField(null=True, blank=True)
    status_reason = models.TextField(blank=True)
    owner = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["source", "severity", "status"]),
            models.Index(fields=["dedup_hash", "status"]),
        ]

    def __str__(self):
        return self.title


class SecurityEvidenceContainer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(SecuritySource, on_delete=models.CASCADE)
    alert = models.ForeignKey(SecurityAlert, on_delete=models.SET_NULL, null=True, blank=True, related_name="evidence_containers")
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN, db_index=True)
    decision_trace = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["source", "status", "created_at"]),
        ]

    def __str__(self):
        return self.title


class SecurityEvidenceItem(models.Model):
    container = models.ForeignKey(SecurityEvidenceContainer, on_delete=models.CASCADE, related_name="items")
    event = models.ForeignKey(SecurityEventRecord, on_delete=models.SET_NULL, null=True, blank=True)
    report = models.ForeignKey(SecurityReport, on_delete=models.SET_NULL, null=True, blank=True)
    item_type = models.CharField(max_length=80)
    content = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class SecurityVulnerabilityFinding(models.Model):
    source = models.ForeignKey(SecuritySource, on_delete=models.CASCADE)
    report = models.ForeignKey(SecurityReport, on_delete=models.SET_NULL, null=True, blank=True)
    asset = models.ForeignKey(SecurityAsset, on_delete=models.SET_NULL, null=True, blank=True)
    cve = models.CharField(max_length=32, db_index=True)
    affected_product = models.CharField(max_length=255, db_index=True)
    cvss = models.FloatField(db_index=True)
    exposed_devices = models.PositiveIntegerField(default=0)
    severity = models.CharField(max_length=24, choices=Severity.choices, db_index=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN, db_index=True)
    dedup_hash = models.CharField(max_length=64, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    first_seen_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_seen_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["source", "cve", "affected_product"]),
            models.Index(fields=["severity", "status"]),
        ]

    def __str__(self):
        return f"{self.cve} {self.affected_product}"


class BackupJobRecord(models.Model):
    source = models.ForeignKey(SecuritySource, on_delete=models.CASCADE)
    report = models.ForeignKey(SecurityReport, on_delete=models.SET_NULL, null=True, blank=True)
    job_name = models.CharField(max_length=255, db_index=True)
    status = models.CharField(max_length=40, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    protected_items = models.PositiveIntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)
    dedup_hash = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class SecurityKpiSnapshot(models.Model):
    source = models.ForeignKey(SecuritySource, on_delete=models.SET_NULL, null=True, blank=True)
    snapshot_date = models.DateField(db_index=True)
    name = models.CharField(max_length=120, db_index=True)
    value = models.FloatField()
    labels = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        unique_together = [("source", "snapshot_date", "name")]
        indexes = [
            models.Index(fields=["snapshot_date", "name"]),
        ]


class SecurityAlertSuppressionRule(models.Model):
    name = models.CharField(max_length=160)
    source = models.ForeignKey(SecuritySource, on_delete=models.SET_NULL, null=True, blank=True)
    event_type = models.CharField(max_length=120, blank=True, db_index=True)
    severity = models.CharField(max_length=24, choices=Severity.choices, blank=True, db_index=True)
    match_payload = models.JSONField(default=dict, blank=True)
    scope_type = models.CharField(max_length=32, default="alert_type", db_index=True)
    conditions_json = models.JSONField(default=dict, blank=True)
    reason = models.TextField()
    owner = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_suppression_rules")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    hit_count = models.PositiveIntegerField(default=0)
    last_hit_at = models.DateTimeField(null=True, blank=True)

    def matches(self, event):
        now = timezone.now()
        if self.starts_at and self.starts_at > now:
            return False
        if self.expires_at and self.expires_at <= now:
            return False
        if self.source_id and self.source_id != event.source_id:
            return False
        if self.event_type and self.event_type != event.event_type:
            return False
        if self.severity and self.severity != event.severity:
            return False
        conditions = self.conditions_json or self.match_payload or {}
        return all(event.payload.get(key) == value for key, value in conditions.items())

    @property
    def enabled(self):
        return self.is_active

    @property
    def is_expired(self):
        return bool(self.expires_at and self.expires_at <= timezone.now())

    def __str__(self):
        return self.name


class BackupExpectedJobConfig(models.Model):
    job_name = models.CharField(max_length=255, db_index=True)
    device_name = models.CharField(max_length=255, blank=True, db_index=True)
    nas_name = models.CharField(max_length=255, blank=True, db_index=True)
    enabled = models.BooleanField(default=True, db_index=True)
    critical_asset = models.BooleanField(default=False)
    expected_days_of_week = models.JSONField(default=list, blank=True)
    expected_start_time_from = models.TimeField(null=True, blank=True)
    expected_start_time_to = models.TimeField(null=True, blank=True)
    max_duration_minutes = models.PositiveIntegerField(default=0)
    min_transferred_gb = models.FloatField(null=True, blank=True)
    max_transferred_gb = models.FloatField(null=True, blank=True)
    missing_after_hours = models.PositiveIntegerField(default=30)
    alert_on_missing = models.BooleanField(default=True)
    alert_on_failure = models.BooleanField(default=True)
    alert_on_duration_anomaly = models.BooleanField(default=True)
    alert_on_size_anomaly = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        unique_together = [("job_name", "device_name", "nas_name")]
        indexes = [
            models.Index(fields=["enabled", "critical_asset"]),
        ]

    def __str__(self):
        return f"{self.job_name} / {self.device_name or '*'}"


class SecurityNotificationChannel(models.Model):
    CHANNEL_CHOICES = [
        ("email", "Email"),
        ("teams_webhook", "Teams webhook"),
        ("dashboard", "Dashboard"),
    ]

    name = models.CharField(max_length=160, unique=True)
    channel_type = models.CharField(max_length=32, choices=CHANNEL_CHOICES, db_index=True)
    enabled = models.BooleanField(default=True, db_index=True)
    severity_min = models.CharField(max_length=24, choices=Severity.choices, default=Severity.WARNING)
    recipients = models.TextField(blank=True)
    webhook_url_secret_ref = models.CharField(max_length=255, blank=True)
    notify_on_new_alert = models.BooleanField(default=True)
    notify_on_ticket_created = models.BooleanField(default=True)
    notify_on_sla_breach = models.BooleanField(default=True)
    cooldown_minutes = models.PositiveIntegerField(default=60)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    @property
    def masked_secret(self):
        return "********" if self.webhook_url_secret_ref else ""

    def __str__(self):
        return self.name


class SecurityTicketConfig(models.Model):
    aggregation_strategy = models.CharField(max_length=32, default="per_product")
    default_assignee = models.CharField(max_length=160, blank=True)
    default_group = models.CharField(max_length=160, blank=True)
    statuses = models.JSONField(default=list, blank=True)
    auto_close_enabled = models.BooleanField(default=False)
    reopen_on_recurrence = models.BooleanField(default=True)
    sla_by_severity = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return "Ticket configuration"


class SecurityConfigurationAuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=80, db_index=True)
    model_name = models.CharField(max_length=120, db_index=True)
    object_id = models.CharField(max_length=80, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    field_name = models.CharField(max_length=120, blank=True)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    request_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["model_name", "created_at"]),
        ]


class SecurityRemediationTicket(models.Model):
    source = models.ForeignKey(SecuritySource, on_delete=models.CASCADE)
    alert = models.ForeignKey(SecurityAlert, on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets")
    linked_alerts = models.ManyToManyField(SecurityAlert, blank=True, related_name="linked_remediation_tickets")
    cve = models.CharField(max_length=32, blank=True, db_index=True)
    cve_ids = models.JSONField(default=list, blank=True)
    affected_product = models.CharField(max_length=255, blank=True, db_index=True)
    organization = models.CharField(max_length=255, blank=True, db_index=True)
    source_system = models.CharField(max_length=80, blank=True, db_index=True)
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN, db_index=True)
    severity = models.CharField(max_length=24, choices=Severity.choices, default=Severity.WARNING, db_index=True)
    max_cvss = models.FloatField(default=0)
    max_exposed_devices = models.PositiveIntegerField(default=0)
    first_seen_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_seen_at = models.DateTimeField(default=timezone.now, db_index=True)
    occurrence_count = models.PositiveIntegerField(default=1)
    dedup_hash = models.CharField(max_length=64, db_index=True)
    evidence = models.ManyToManyField(SecurityEvidenceContainer, blank=True, related_name="tickets")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["source", "cve", "affected_product", "status"]),
            models.Index(fields=["dedup_hash", "status"]),
        ]

    def __str__(self):
        return self.title


class SecurityAlertActionLog(models.Model):
    alert = models.ForeignKey(SecurityAlert, on_delete=models.SET_NULL, null=True, blank=True, related_name="action_logs")
    ticket = models.ForeignKey(SecurityRemediationTicket, on_delete=models.SET_NULL, null=True, blank=True, related_name="action_logs")
    action = models.CharField(max_length=120, db_index=True)
    actor = models.CharField(max_length=120, default="system")
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["action", "created_at"]),
        ]


class SecurityMailboxSource(models.Model):
    SOURCE_TYPE_CHOICES = [
        ("manual", "Manual"),
        ("mock", "Mock"),
        ("graph", "Microsoft Graph"),
        ("imap", "IMAP"),
    ]

    name = models.CharField(max_length=160, unique=True)
    code = models.CharField(max_length=80, unique=True, db_index=True)
    enabled = models.BooleanField(default=True, db_index=True)
    source_type = models.CharField(max_length=32, choices=SOURCE_TYPE_CHOICES, default="manual")
    mailbox_address = models.EmailField(blank=True)
    description = models.TextField(blank=True)
    sender_allowlist_text = models.TextField(blank=True)
    subject_include_text = models.TextField(blank=True)
    subject_exclude_text = models.TextField(blank=True)
    body_include_text = models.TextField(blank=True)
    attachment_extensions = models.CharField(max_length=255, blank=True)
    max_messages_per_run = models.PositiveIntegerField(default=50)
    mark_as_read_after_import = models.BooleanField(default=False)
    process_attachments = models.BooleanField(default=True)
    process_email_body = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    last_error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["enabled", "source_type"]),
        ]

    def __str__(self):
        return self.name


class SecurityMailboxIngestionRun(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("success", "Success"),
        ("partial", "Partial"),
        ("failed", "Failed"),
    ]

    source = models.ForeignKey(SecurityMailboxSource, on_delete=models.CASCADE, related_name="ingestion_runs")
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default="pending", db_index=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    imported_messages_count = models.PositiveIntegerField(default=0)
    skipped_messages_count = models.PositiveIntegerField(default=0)
    duplicate_messages_count = models.PositiveIntegerField(default=0)
    imported_files_count = models.PositiveIntegerField(default=0)
    processed_items_count = models.PositiveIntegerField(default=0)
    generated_alerts_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["source", "started_at"]),
            models.Index(fields=["status", "started_at"]),
        ]

    def __str__(self):
        return f"{self.source.name} - {self.started_at.strftime('%Y-%m-%d %H:%M')}"


class SecurityAiInteractionLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=80, db_index=True)
    provider = models.CharField(max_length=80, blank=True)
    model = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=32, db_index=True)
    page = models.CharField(max_length=80, blank=True)
    object_type = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=80, blank=True)
    request_chars = models.PositiveIntegerField(default=0)
    response_chars = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.action} - {self.status}"


class AIKnowledgeDocument(models.Model):
    title = models.CharField(max_length=255)
    source_type = models.CharField(max_length=80, db_index=True)
    source_object_type = models.CharField(max_length=80, blank=True, db_index=True)
    source_object_id = models.CharField(max_length=80, blank=True, db_index=True)
    content_hash = models.CharField(max_length=64, db_index=True)
    raw_text = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        indexes = [
            models.Index(fields=["source_type", "source_object_type"]),
            models.Index(fields=["source_object_type", "source_object_id"]),
            models.Index(fields=["content_hash"]),
        ]

    def __str__(self):
        return self.title


class AIKnowledgeChunk(models.Model):
    document = models.ForeignKey(AIKnowledgeDocument, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.PositiveIntegerField()
    text = models.TextField()
    text_hash = models.CharField(max_length=64, db_index=True)
    embedding = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["document", "chunk_index"]
        unique_together = [("document", "chunk_index")]
        indexes = [
            models.Index(fields=["document", "chunk_index"]),
            models.Index(fields=["text_hash"]),
        ]

    def __str__(self):
        return f"{self.document_id} chunk {self.chunk_index}"


class AIKnowledgeEmbedding(models.Model):
    chunk = models.OneToOneField(AIKnowledgeChunk, on_delete=models.CASCADE, related_name="knowledge_embedding")
    provider = models.CharField(max_length=80, db_index=True)
    model_name = models.CharField(max_length=160, blank=True)
    dimensions = models.PositiveIntegerField(default=384, db_index=True)
    embedding_hash = models.CharField(max_length=64, db_index=True)
    embedding = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["chunk__document", "chunk__chunk_index"]
        indexes = [
            models.Index(fields=["provider", "model_name", "dimensions"], name="security_ai_provide_2705a6_idx"),
            models.Index(fields=["embedding_hash"], name="security_ai_embeddi_cb8f77_idx"),
        ]

    def __str__(self):
        return f"{self.provider}:{self.model_name or 'default'} chunk {self.chunk_id}"


class AIMemoryFact(models.Model):
    scope = models.CharField(max_length=80, default="global", db_index=True)
    key = models.CharField(max_length=160, db_index=True)
    value = models.TextField()
    category = models.CharField(max_length=80, blank=True, db_index=True)
    confidence = models.FloatField(default=1.0)
    is_approved = models.BooleanField(default=False, db_index=True)
    source = models.CharField(max_length=160, blank=True)
    source_object_type = models.CharField(max_length=80, blank=True, db_index=True)
    source_object_id = models.CharField(max_length=80, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scope", "category", "key"]
        unique_together = [("scope", "key", "category")]
        indexes = [
            models.Index(fields=["scope", "category", "is_approved"]),
            models.Index(fields=["source_object_type", "source_object_id"]),
        ]

    def __str__(self):
        return f"{self.scope}:{self.key}"


class AIConversation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=255, blank=True)
    context_type = models.CharField(max_length=80, blank=True, db_index=True)
    context_object_id = models.CharField(max_length=80, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        indexes = [
            models.Index(fields=["user", "updated_at"]),
            models.Index(fields=["context_type", "context_object_id"]),
        ]

    def __str__(self):
        return self.title or f"Conversation #{self.pk}"


class AIConversationMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        SYSTEM = "system", "System"
        TOOL = "tool", "Tool"

    conversation = models.ForeignKey(AIConversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["role", "created_at"]),
        ]

    def __str__(self):
        return f"{self.conversation_id}:{self.role}"
