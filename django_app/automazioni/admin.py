from django.contrib import admin

from .models import (
    AutomationAction,
    AutomationActionLog,
    AutomationCondition,
    AutomationRule,
    AutomationRunLog,
    DashboardMetricValue,
)


@admin.register(AutomationRule)
class AutomationRuleAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "code",
        "name",
        "source_code",
        "operation_type",
        "trigger_scope",
        "watched_field",
        "is_active",
        "is_draft",
        "last_run_at",
    )
    list_filter = ("source_code", "operation_type", "trigger_scope", "is_active", "is_draft")
    search_fields = ("code", "name", "description", "watched_field")
    autocomplete_fields = ("created_by", "updated_by")
    readonly_fields = ("created_at", "updated_at", "last_run_at", "last_test_at")


@admin.register(AutomationCondition)
class AutomationConditionAdmin(admin.ModelAdmin):
    list_display = ("id", "rule", "order", "field_name", "operator", "value_type", "is_enabled")
    list_filter = ("operator", "value_type", "is_enabled", "compare_with_old")
    search_fields = ("rule__code", "field_name", "expected_value")
    autocomplete_fields = ("rule",)


@admin.register(AutomationAction)
class AutomationActionAdmin(admin.ModelAdmin):
    list_display = ("id", "rule", "order", "action_type", "is_enabled")
    list_filter = ("action_type", "is_enabled")
    search_fields = ("rule__code", "description")
    autocomplete_fields = ("rule",)


@admin.register(AutomationRunLog)
class AutomationRunLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "rule",
        "queue_event_id",
        "source_code",
        "operation_type",
        "status",
        "is_test",
        "started_at",
        "finished_at",
    )
    list_filter = ("source_code", "operation_type", "status", "is_test")
    search_fields = ("rule__code", "source_code", "trigger_event_label", "result_message")
    autocomplete_fields = ("rule", "initiated_by")
    readonly_fields = ("started_at", "finished_at")


@admin.register(AutomationActionLog)
class AutomationActionLogAdmin(admin.ModelAdmin):
    list_display = ("id", "run_log", "action", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("run_log__rule__code", "result_message")
    autocomplete_fields = ("run_log", "action")
    readonly_fields = ("created_at",)


@admin.register(DashboardMetricValue)
class DashboardMetricValueAdmin(admin.ModelAdmin):
    list_display = ("id", "metric_code", "label", "current_value", "updated_at")
    search_fields = ("metric_code", "label")
    readonly_fields = ("updated_at",)
