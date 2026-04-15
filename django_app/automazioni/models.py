from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

from .source_registry import get_source_definition, get_source_fields


class AutomationRuleOperationType(models.TextChoices):
    INSERT = "insert", "Insert"
    UPDATE = "update", "Update"


class AutomationRuleTriggerScope(models.TextChoices):
    ALL_INSERTS = "all_inserts", "All inserts"
    ALL_UPDATES = "all_updates", "All updates"
    SPECIFIC_FIELD = "specific_field", "Specific field"
    ANY_CHANGE = "any_change", "Any change"


class AutomationConditionOperator(models.TextChoices):
    EQUALS = "equals", "Equals"
    NOT_EQUALS = "not_equals", "Not equals"
    CONTAINS = "contains", "Contains"
    STARTSWITH = "startswith", "Starts with"
    ENDSWITH = "endswith", "Ends with"
    GT = "gt", "Greater than"
    GTE = "gte", "Greater than or equal"
    LT = "lt", "Less than"
    LTE = "lte", "Less than or equal"
    IS_TRUE = "is_true", "Is true"
    IS_FALSE = "is_false", "Is false"
    IN_CSV = "in_csv", "In CSV"
    NOT_IN_CSV = "not_in_csv", "Not in CSV"
    IS_EMPTY = "is_empty", "Is empty"
    IS_NOT_EMPTY = "is_not_empty", "Is not empty"
    CHANGED = "changed", "Changed"
    CHANGED_TO = "changed_to", "Changed to"
    CHANGED_FROM_TO = "changed_from_to", "Changed from to"


class AutomationConditionValueType(models.TextChoices):
    STRING = "string", "String"
    INT = "int", "Integer"
    FLOAT = "float", "Float"
    BOOL = "bool", "Boolean"
    DATE = "date", "Date"
    DATETIME = "datetime", "Datetime"


class AutomationActionType(models.TextChoices):
    SEND_EMAIL = "send_email", "Send email"
    INSERT_RECORD = "insert_record", "Insert record"
    UPDATE_RECORD = "update_record", "Update record"
    UPDATE_TRIGGER_RECORD = "update_trigger_record", "Update triggering record"
    UPDATE_DASHBOARD_METRIC = "update_dashboard_metric", "Update dashboard metric"
    WRITE_LOG = "write_log", "Write log"
    DELAY_SCHEDULE = "delay_schedule", "Delay / Schedule"
    HTTP_REQUEST = "http_request", "HTTP request"
    TEAMS_WEBHOOK = "teams_webhook", "Teams webhook"
    # Controllo flusso
    SEND_APPROVAL = "send_approval", "Richiedi Approvazione"
    DO_UNTIL = "do_until", "Do Until (Ripeti fino a condizione)"
    FOR_EACH = "for_each", "Per Ogni Elemento (For Each)"
    BRANCH = "branch", "Branch / Condizione If-Else"


class ApprovalDeliveryMode(models.TextChoices):
    EMAIL = "email", "Email"
    TEAMS_WEBHOOK_LEGACY = "teams_webhook_legacy", "Teams webhook legacy"
    TEAMS_CHAT_FLOW = "teams_chat_flow", "Teams chat flow"
    EMAIL_AND_TEAMS_CHAT_FLOW = "email_and_teams_chat_flow", "Email + Teams chat flow"


class AutomationRunLogStatus(models.TextChoices):
    SUCCESS = "success", "Success"
    ERROR = "error", "Error"
    SKIPPED = "skipped", "Skipped"
    TEST = "test", "Test"
    WAITING_APPROVAL = "waiting_approval", "In attesa approvazione"


class AutomationActionLogStatus(models.TextChoices):
    SUCCESS = "success", "Success"
    ERROR = "error", "Error"
    SKIPPED = "skipped", "Skipped"


class AutomationRule(models.Model):
    code = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    source_code = models.CharField(max_length=100, db_index=True)
    import_flow_name = models.CharField(max_length=255, blank=True, default="")
    import_source_rule_code = models.CharField(max_length=120, blank=True, default="")
    import_source_package_version = models.CharField(max_length=80, blank=True, default="")
    operation_type = models.CharField(
        max_length=20,
        choices=AutomationRuleOperationType.choices,
        db_index=True,
    )
    watched_field = models.CharField(max_length=100, null=True, blank=True)
    trigger_scope = models.CharField(
        max_length=30,
        choices=AutomationRuleTriggerScope.choices,
        db_index=True,
    )
    is_active = models.BooleanField(default=True, db_index=True)
    is_draft = models.BooleanField(default=True, db_index=True)
    stop_on_first_failure = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="automation_rules_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="automation_rules_updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_test_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self) -> str:
        return f"{self.name} [{self.code}]"

    def clean(self) -> None:
        super().clean()

        errors: dict[str, list[str]] = {}
        source = get_source_definition(self.source_code)

        if source is None:
            errors.setdefault("source_code", []).append("La sorgente deve essere registrata nel source registry.")

        watched_field = (self.watched_field or "").strip()

        if self.trigger_scope == AutomationRuleTriggerScope.SPECIFIC_FIELD and not watched_field:
            errors.setdefault("watched_field", []).append(
                "Il campo osservato e' obbligatorio per trigger_scope='specific_field'."
            )

        if self.trigger_scope != AutomationRuleTriggerScope.SPECIFIC_FIELD and watched_field:
            errors.setdefault("watched_field", []).append(
                "Il campo osservato e' consentito solo per trigger_scope='specific_field'."
            )

        if self.operation_type == AutomationRuleOperationType.INSERT:
            if self.trigger_scope != AutomationRuleTriggerScope.ALL_INSERTS:
                errors.setdefault("trigger_scope", []).append(
                    "Le regole su insert possono usare solo trigger_scope='all_inserts'."
                )
        elif self.operation_type == AutomationRuleOperationType.UPDATE:
            if self.trigger_scope == AutomationRuleTriggerScope.ALL_INSERTS:
                errors.setdefault("trigger_scope", []).append(
                    "Le regole su update non possono usare trigger_scope='all_inserts'."
                )

        if watched_field and source is not None:
            valid_field_names = {field["name"] for field in get_source_fields(self.source_code)}
            if watched_field not in valid_field_names:
                errors.setdefault("watched_field", []).append(
                    "Il campo osservato deve appartenere ai campi esposti dalla sorgente selezionata."
                )

        if errors:
            raise ValidationError(errors)


class AutomationCondition(models.Model):
    rule = models.ForeignKey(AutomationRule, on_delete=models.CASCADE, related_name="conditions")
    order = models.PositiveIntegerField(default=0, db_index=True)
    field_name = models.CharField(max_length=100)
    operator = models.CharField(max_length=30, choices=AutomationConditionOperator.choices)
    expected_value = models.TextField(blank=True, default="")
    value_type = models.CharField(max_length=20, choices=AutomationConditionValueType.choices)
    compare_with_old = models.BooleanField(default=False)
    is_enabled = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"Condition<{self.rule.code}:{self.order}:{self.field_name}>"


class AutomationAction(models.Model):
    rule = models.ForeignKey(AutomationRule, on_delete=models.CASCADE, related_name="actions")
    order = models.PositiveIntegerField(default=0, db_index=True)
    action_type = models.CharField(max_length=40, choices=AutomationActionType.choices)
    is_enabled = models.BooleanField(default=True, db_index=True)
    description = models.TextField(blank=True, default="")
    config_json = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"Action<{self.rule.code}:{self.order}:{self.action_type}>"


class AutomationRunLog(models.Model):
    rule = models.ForeignKey(
        AutomationRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="run_logs",
    )
    queue_event_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    source_code = models.CharField(max_length=100, db_index=True)
    operation_type = models.CharField(max_length=20, choices=AutomationRuleOperationType.choices, db_index=True)
    trigger_event_label = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=20, choices=AutomationRunLogStatus.choices, db_index=True)
    payload_json = models.JSONField(default=dict, blank=True)
    old_payload_json = models.JSONField(null=True, blank=True)
    result_message = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    execution_ms = models.PositiveIntegerField(null=True, blank=True)
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="automation_runs_initiated",
    )
    is_test = models.BooleanField(default=False, db_index=True)
    error_trace = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        indexes = [
            models.Index(fields=["rule", "status"], name="automrunlog_rule_status_idx"),
            models.Index(fields=["source_code", "operation_type"], name="automrunlog_src_optype_idx"),
        ]

    def __str__(self) -> str:
        target = self.rule.code if self.rule_id else self.source_code
        return f"RunLog<{target}:{self.status}:{self.id or 'new'}>"


class AutomationActionLog(models.Model):
    run_log = models.ForeignKey(AutomationRunLog, on_delete=models.CASCADE, related_name="action_logs")
    action = models.ForeignKey(
        AutomationAction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="action_logs",
    )
    status = models.CharField(max_length=20, choices=AutomationActionLogStatus.choices, db_index=True)
    result_message = models.TextField(blank=True, default="")
    error_trace = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["run_log", "status"], name="automactionlog_run_status_idx"),
        ]

    def __str__(self) -> str:
        return f"ActionLog<{self.run_log_id}:{self.status}:{self.id or 'new'}>"


class DashboardMetricValue(models.Model):
    metric_code = models.SlugField(max_length=120, unique=True)
    label = models.CharField(max_length=255)
    current_value = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["metric_code", "id"]

    def __str__(self) -> str:
        return f"{self.label} [{self.metric_code}]"


class AutomationDeliveryEndpointType(models.TextChoices):
    TEAMS_WEBHOOK_LEGACY = "teams_webhook_legacy", "Teams webhook legacy"
    TEAMS_FLOW_WEBHOOK = "teams_flow_webhook", "Teams flow webhook"


class AutomationTableConfig(models.Model):
    """Whitelist dinamica delle tabelle accessibili dalle azioni insert_record / update_record."""

    ACTION_TYPE_CHOICES = [
        ("insert_record", "Insert record"),
        ("update_record", "Update record"),
    ]

    action_type = models.CharField(max_length=50, choices=ACTION_TYPE_CHOICES)
    table_name = models.CharField(max_length=200)
    allowed_fields = models.JSONField(default=list, help_text="Campi scrivibili (lista stringhe)")
    where_fields = models.JSONField(default=list, help_text="Campi usabili nel WHERE (solo update_record)")
    notes = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("action_type", "table_name")]
        ordering = ["action_type", "table_name"]

    def __str__(self) -> str:
        return f"{self.action_type} → {self.table_name}"


class AutomationDeliveryEndpoint(models.Model):
    code = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=120, unique=True)
    endpoint_type = models.CharField(
        max_length=40,
        choices=AutomationDeliveryEndpointType.choices,
        db_index=True,
    )
    endpoint_url = models.TextField(verbose_name="Endpoint URL")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="Attivo")
    description = models.CharField(max_length=255, blank=True, default="", verbose_name="Descrizione")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Endpoint delivery automazioni"
        verbose_name_plural = "Endpoint delivery automazioni"

    def __str__(self) -> str:
        return self.name


AUTOMATION_DELIVERY_ENDPOINT_TABLE_NAME = "automazioni_automationdeliveryendpoint"
AUTOMATION_DELIVERY_ENDPOINT_UNAVAILABLE_MESSAGE = (
    "Endpoint Teams Flow temporaneamente non disponibili: applicare la migration "
    "`automazioni.0010_automationdeliveryendpoint`."
)


def _db_exception_text(exc: Exception) -> str:
    parts = [str(exc)]
    parts.extend(str(arg) for arg in getattr(exc, "args", ()) if str(arg))
    return " ".join(part for part in parts if part).lower()


def is_automation_delivery_endpoint_table_missing(exc: Exception) -> bool:
    message = _db_exception_text(exc)
    return (
        AUTOMATION_DELIVERY_ENDPOINT_TABLE_NAME in message
        and any(
            marker in message
            for marker in (
                "42s02",
                "no such table",
                "invalid object name",
                "nome di oggetto",
                "non è valido",
            )
        )
    )


def list_teams_flow_endpoints(*, active_only: bool | None = None) -> tuple[list["AutomationDeliveryEndpoint"], bool]:
    queryset = AutomationDeliveryEndpoint.objects.filter(
        endpoint_type=AutomationDeliveryEndpointType.TEAMS_FLOW_WEBHOOK
    )
    if active_only is not None:
        queryset = queryset.filter(is_active=active_only)
    try:
        return list(queryset.order_by("name")), False
    except (OperationalError, ProgrammingError) as exc:
        if is_automation_delivery_endpoint_table_missing(exc):
            return [], True
        raise


def get_teams_flow_endpoint_by_id(
    endpoint_id: object,
    *,
    active_only: bool = True,
) -> tuple["AutomationDeliveryEndpoint | None", bool]:
    endpoint_id_raw = str(endpoint_id or "").strip()
    if not endpoint_id_raw:
        return None, False
    queryset = AutomationDeliveryEndpoint.objects.filter(
        pk=endpoint_id_raw,
        endpoint_type=AutomationDeliveryEndpointType.TEAMS_FLOW_WEBHOOK,
    )
    if active_only:
        queryset = queryset.filter(is_active=True)
    try:
        return queryset.first(), False
    except (OperationalError, ProgrammingError) as exc:
        if is_automation_delivery_endpoint_table_missing(exc):
            return None, True
        raise


class AutomationApproval(models.Model):
    """
    Richiesta di approvazione umana generata dall'azione send_approval.
    Il flusso si mette in pausa finché l'approvatore decide.
    Dopo la decisione, vengono eseguite le azioni del ramo approvato o rifiutato.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "In attesa"
        APPROVED = "approved", "Approvato"
        REJECTED = "rejected", "Rifiutato"
        EXPIRED = "expired", "Scaduto"

    run_log = models.ForeignKey(
        AutomationRunLog,
        on_delete=models.CASCADE,
        related_name="approvals",
        help_text="Run log che ha generato questa richiesta.",
    )
    action = models.ForeignKey(
        AutomationAction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_requests",
        help_text="Azione send_approval che ha originato la richiesta.",
    )
    token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        help_text="Token univoco usato negli URL di approvazione/rifiuto.",
    )
    approver_emails = models.JSONField(
        default=list,
        help_text="Lista email degli approvatori a cui è stata inviata la richiesta.",
    )
    subject = models.CharField(max_length=512, help_text="Oggetto dell'email di approvazione.")
    message = models.TextField(blank=True, default="", help_text="Corpo del messaggio inviato all'approvatore.")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    decided_by_email = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Email di chi ha preso la decisione.",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Scadenza della richiesta.")
    resume_payload = models.JSONField(
        default=dict,
        help_text="Payload originale da usare per eseguire le azioni post-decisione.",
    )
    resume_old_payload = models.JSONField(
        null=True,
        blank=True,
        help_text="Old payload originale.",
    )
    # Azioni da eseguire dopo la decisione, serializzate come lista di {action_type, config_json, description}
    approved_actions = models.JSONField(
        default=list,
        help_text="Azioni da eseguire se la richiesta viene approvata.",
    )
    rejected_actions = models.JSONField(
        default=list,
        help_text="Azioni da eseguire se la richiesta viene rifiutata.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "expires_at"], name="autom_approval_status_exp_idx"),
        ]

    def __str__(self) -> str:
        rule_code = getattr(getattr(self.run_log, "rule", None), "code", "?") if self.run_log_id else "?"
        return f"Approval<{rule_code}:{self.status}:{self.token}>"

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return timezone.now() > self.expires_at


class TeamsWebhookPreset(models.Model):
    """Canale Teams riutilizzabile: salva webhook URL una volta, selezionalo in qualsiasi send_approval."""

    name = models.CharField(max_length=100, unique=True, verbose_name="Nome canale")
    webhook_url = models.TextField(verbose_name="Webhook URL")
    description = models.CharField(max_length=255, blank=True, verbose_name="Descrizione")
    is_active = models.BooleanField(default=True, verbose_name="Attivo")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Preset webhook Teams"
        verbose_name_plural = "Preset webhook Teams"

    def __str__(self) -> str:
        return self.name
