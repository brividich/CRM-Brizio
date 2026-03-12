from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
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
    UPDATE_DASHBOARD_METRIC = "update_dashboard_metric", "Update dashboard metric"
    WRITE_LOG = "write_log", "Write log"


class AutomationRunLogStatus(models.TextChoices):
    SUCCESS = "success", "Success"
    ERROR = "error", "Error"
    SKIPPED = "skipped", "Skipped"
    TEST = "test", "Test"


class AutomationActionLogStatus(models.TextChoices):
    SUCCESS = "success", "Success"
    ERROR = "error", "Error"
    SKIPPED = "skipped", "Skipped"


class AutomationRule(models.Model):
    code = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    source_code = models.CharField(max_length=100, db_index=True)
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
