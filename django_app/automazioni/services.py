from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
import logging
import re
import traceback
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.db import connection, transaction
from django.utils import timezone

from .models import (
    AutomationAction,
    AutomationActionLog,
    AutomationActionLogStatus,
    AutomationActionType,
    AutomationCondition,
    AutomationConditionOperator,
    AutomationConditionValueType,
    AutomationRule,
    AutomationRunLog,
    AutomationRunLogStatus,
    DashboardMetricValue,
)


_UNCASTABLE = object()
_PLACEHOLDER_PATTERN = re.compile(r"\{([^{}]+)\}")
_TRUTHY_VALUES = {"1", "true", "yes", "on"}
_FALSY_VALUES = {"0", "false", "no", "off"}
_QUEUE_ERROR_MESSAGE_LIMIT = 1900

logger = logging.getLogger(__name__)


def get_action_table_whitelist() -> dict[str, dict[str, dict[str, set[str]]]]:
    return {
        AutomationActionType.INSERT_RECORD: {
            "core_notifica": {
                "fields": {"legacy_user_id", "tipo", "messaggio", "url_azione", "letta"},
            },
        },
        AutomationActionType.UPDATE_RECORD: {
            "core_notifica": {
                "fields": {"tipo", "messaggio", "url_azione", "letta"},
                "where_fields": {"id", "legacy_user_id", "tipo"},
            },
            "tasks_task": {
                "fields": {"status", "priority", "next_step_text", "next_step_due", "due_date", "assigned_to_id"},
                "where_fields": {"id", "project_id", "assigned_to_id"},
            },
        },
    }


def _normalize_queue_error_message(message: Any) -> str:
    text = str(message or "").strip()
    if not text:
        return "Errore non specificato."
    if len(text) <= _QUEUE_ERROR_MESSAGE_LIMIT:
        return text
    return f"{text[:_QUEUE_ERROR_MESSAGE_LIMIT - 3]}..."


def _coerce_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _normalize_runtime_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return bool(value)

    normalized = str(value).strip().lower()
    if normalized in _TRUTHY_VALUES:
        return True
    if normalized in _FALSY_VALUES:
        return False
    return None


def _resolve_legacy_user_email(legacy_user_id: Any) -> str:
    resolved_id = _coerce_int(legacy_user_id)
    if resolved_id is None:
        return ""

    try:
        from core.legacy_models import UtenteLegacy

        legacy_user = UtenteLegacy.objects.filter(id=resolved_id).only("email").order_by("id").first()
    except Exception:
        legacy_user = None

    return str(getattr(legacy_user, "email", "") or "").strip().lower()


def _resolve_caporeparto_email_from_lookup(lookup_id: Any) -> str:
    resolved_id = _coerce_int(lookup_id)
    if resolved_id is None:
        return ""

    try:
        with connection.cursor() as cursor:
            if connection.vendor == "sqlite":
                cursor.execute(
                    """
SELECT indirizzo_email
FROM capi_reparto
WHERE sharepoint_item_id = %s
ORDER BY id DESC
LIMIT 1
""",
                    [resolved_id],
                )
            else:
                cursor.execute(
                    """
SELECT TOP 1 indirizzo_email
FROM capi_reparto
WHERE sharepoint_item_id = %s
ORDER BY id DESC
""",
                    [resolved_id],
                )
            row = cursor.fetchone()
    except Exception:
        row = None

    if not row or row[0] is None:
        return ""
    return str(row[0] or "").strip().lower()


def _fetch_assenza_runtime_details(assenza_id: Any) -> dict[str, Any]:
    resolved_id = _coerce_int(assenza_id)
    if resolved_id is None:
        return {}

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
SELECT email_esterna, salta_approvazione
FROM assenze
WHERE id = %s
""",
                [resolved_id],
            )
            row = cursor.fetchone()
    except Exception:
        row = None

    if not row:
        return {}

    dipendente_email = str(row[0] or "").strip().lower()
    return {
        "dipendente_email": dipendente_email,
        "salta_approvazione": _normalize_runtime_bool(row[1]),
    }


def _enrich_assenze_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload

    enriched = dict(payload)
    runtime_details = _fetch_assenza_runtime_details(enriched.get("id"))

    capo_email = str(enriched.get("capo_email") or "").strip().lower()
    if not capo_email:
        capo_email = _resolve_legacy_user_email(enriched.get("capo_reparto_id"))
    if not capo_email:
        capo_email = _resolve_caporeparto_email_from_lookup(enriched.get("capo_reparto_lookup_id"))
    if capo_email:
        enriched["capo_email"] = capo_email

    dipendente_email = str(
        enriched.get("dipendente_email")
        or enriched.get("email_esterna")
        or runtime_details.get("dipendente_email")
        or ""
    ).strip().lower()
    if not dipendente_email:
        dipendente_email = _resolve_legacy_user_email(enriched.get("dipendente_id"))
    if dipendente_email:
        enriched["dipendente_email"] = dipendente_email

    salta_approvazione = enriched.get("salta_approvazione")
    if salta_approvazione in {None, ""}:
        salta_approvazione = runtime_details.get("salta_approvazione")
    normalized_salta_approvazione = _normalize_runtime_bool(salta_approvazione)
    if normalized_salta_approvazione is not None:
        enriched["salta_approvazione"] = normalized_salta_approvazione
    return enriched


def _enrich_payload_for_source(source_code: str | None, payload: Any) -> Any:
    normalized_source = str(source_code or "").strip().lower()
    if normalized_source == "assenze":
        return _enrich_assenze_payload(payload)
    return payload


def enrich_payload_for_source(source_code: str | None, payload: Any) -> Any:
    return _enrich_payload_for_source(source_code, payload)


def _cursor_fetch_dicts(cursor) -> list[dict[str, Any]]:
    columns = [column[0] for column in cursor.description or []]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _build_queue_source_filter(source_code: str | None) -> tuple[str, list[Any]]:
    normalized = str(source_code or "").strip()
    if not normalized:
        return "", []
    return " AND source_code = %s", [normalized]


def _build_queue_filter_clauses(
    *,
    status: str | None = None,
    source_code: str | None = None,
    operation_type: str | None = None,
    queue_id: int | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    normalized_status = str(status or "").strip()
    if normalized_status:
        clauses.append("status = %s")
        params.append(normalized_status)

    normalized_source_code = str(source_code or "").strip()
    if normalized_source_code:
        clauses.append("source_code = %s")
        params.append(normalized_source_code)

    normalized_operation_type = str(operation_type or "").strip().lower()
    if normalized_operation_type:
        clauses.append("LOWER(operation_type) = %s")
        params.append(normalized_operation_type)

    if queue_id is not None:
        clauses.append("id = %s")
        params.append(int(queue_id))

    if not clauses:
        return "", params
    return f"WHERE {' AND '.join(clauses)}", params


def _deserialize_queue_json(raw_value: Any, *, field_name: str, allow_null: bool = False) -> dict[str, Any] | None:
    if raw_value in {None, ""}:
        if allow_null:
            return None
        raise ValueError(f"{field_name} mancante o vuoto.")

    if isinstance(raw_value, dict):
        return raw_value

    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field_name} non contiene JSON valido.") from exc

    if parsed is None and allow_null:
        return None
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} deve contenere un oggetto JSON.")
    return parsed


def _did_payload_field_change(payload: Any, old_payload: Any, field_name: str | None) -> bool:
    if not field_name or not isinstance(payload, dict) or not isinstance(old_payload, dict):
        return False
    return safe_get_payload_value(payload, field_name) != safe_get_payload_value(old_payload, field_name)


def _did_payload_change(payload: Any, old_payload: Any) -> bool:
    if not isinstance(payload, dict) or not isinstance(old_payload, dict):
        return False
    return payload != old_payload


def fetch_pending_queue_events(limit: int = 50, source_code: str | None = None) -> list[dict[str, Any]]:
    batch_limit = max(int(limit or 0), 1)
    source_filter_sql, source_filter_params = _build_queue_source_filter(source_code)
    sql = f"""
WITH picked AS (
    SELECT TOP ({batch_limit}) id
    FROM dbo.automation_event_queue WITH (READPAST, UPDLOCK, ROWLOCK)
    WHERE status = %s
    {source_filter_sql}
    ORDER BY id ASC
)
UPDATE queue_rows
SET
    status = %s,
    picked_at = SYSUTCDATETIME(),
    error_message = NULL
OUTPUT
    inserted.id,
    inserted.source_code,
    inserted.source_table,
    inserted.source_pk,
    inserted.operation_type,
    inserted.event_code,
    inserted.watched_field,
    inserted.payload_json,
    inserted.old_payload_json,
    inserted.status,
    inserted.retry_count,
    inserted.error_message,
    inserted.created_at,
    inserted.picked_at,
    inserted.processed_at
FROM dbo.automation_event_queue AS queue_rows
INNER JOIN picked
    ON picked.id = queue_rows.id;
"""
    params = ["pending", *source_filter_params, "processing"]
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return _cursor_fetch_dicts(cursor)


def fetch_pending_queue_event_snapshots(limit: int = 50, source_code: str | None = None) -> list[dict[str, Any]]:
    batch_limit = max(int(limit or 0), 1)
    source_filter_sql, source_filter_params = _build_queue_source_filter(source_code)
    sql = f"""
SELECT TOP ({batch_limit})
    id,
    source_code,
    source_table,
    source_pk,
    operation_type,
    event_code,
    watched_field,
    payload_json,
    old_payload_json,
    status,
    retry_count,
    error_message,
    created_at,
    picked_at,
    processed_at
FROM dbo.automation_event_queue
WHERE status = %s
{source_filter_sql}
ORDER BY id ASC;
"""
    with connection.cursor() as cursor:
        cursor.execute(sql, ["pending", *source_filter_params])
        return _cursor_fetch_dicts(cursor)


def list_queue_events(
    *,
    status: str | None = None,
    source_code: str | None = None,
    operation_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    row_limit = max(int(limit or 0), 1)
    where_sql, params = _build_queue_filter_clauses(
        status=status,
        source_code=source_code,
        operation_type=operation_type,
    )
    sql = f"""
SELECT TOP ({row_limit})
    id,
    source_code,
    source_table,
    source_pk,
    operation_type,
    event_code,
    watched_field,
    status,
    retry_count,
    error_message,
    created_at,
    picked_at,
    processed_at
FROM dbo.automation_event_queue
{where_sql}
ORDER BY id DESC;
"""
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return _cursor_fetch_dicts(cursor)


def get_queue_event_detail(queue_id: int) -> dict[str, Any] | None:
    where_sql, params = _build_queue_filter_clauses(queue_id=queue_id)
    sql = f"""
SELECT
    id,
    source_code,
    source_table,
    source_pk,
    operation_type,
    event_code,
    watched_field,
    payload_json,
    old_payload_json,
    status,
    retry_count,
    error_message,
    created_at,
    picked_at,
    processed_at
FROM dbo.automation_event_queue
{where_sql};
"""
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = _cursor_fetch_dicts(cursor)
    return rows[0] if rows else None


def count_queue_by_status(
    *,
    source_code: str | None = None,
    operation_type: str | None = None,
) -> dict[str, int]:
    where_sql, params = _build_queue_filter_clauses(source_code=source_code, operation_type=operation_type)
    sql = f"""
SELECT status, COUNT(*) AS total
FROM dbo.automation_event_queue
{where_sql}
GROUP BY status;
"""
    counts = {"pending": 0, "processing": 0, "done": 0, "error": 0}
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        for row in _cursor_fetch_dicts(cursor):
            counts[str(row["status"])] = int(row["total"])
    return counts


def reset_queue_event_to_pending(queue_id: int) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
UPDATE dbo.automation_event_queue
SET
    status = %s,
    error_message = NULL,
    picked_at = NULL,
    processed_at = NULL
WHERE id = %s
  AND status = %s
""",
            ["pending", int(queue_id), "error"],
        )
        return bool(cursor.rowcount)


def claim_queue_event_by_id(queue_id: int, *, allowed_statuses: tuple[str, ...] = ("pending", "error")) -> dict[str, Any] | None:
    normalized_statuses = tuple(str(status).strip() for status in allowed_statuses if str(status).strip())
    if not normalized_statuses:
        return None

    placeholders = ", ".join(["%s"] * len(normalized_statuses))
    sql = f"""
UPDATE dbo.automation_event_queue
SET
    status = %s,
    picked_at = SYSUTCDATETIME(),
    error_message = NULL
OUTPUT
    inserted.id,
    inserted.source_code,
    inserted.source_table,
    inserted.source_pk,
    inserted.operation_type,
    inserted.event_code,
    inserted.watched_field,
    inserted.payload_json,
    inserted.old_payload_json,
    inserted.status,
    inserted.retry_count,
    inserted.error_message,
    inserted.created_at,
    inserted.picked_at,
    inserted.processed_at
WHERE id = %s
  AND status IN ({placeholders});
"""
    params = ["processing", int(queue_id), *normalized_statuses]
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = _cursor_fetch_dicts(cursor)
    return rows[0] if rows else None


def mark_queue_done(queue_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
UPDATE dbo.automation_event_queue
SET
    status = %s,
    processed_at = SYSUTCDATETIME(),
    error_message = NULL
WHERE id = %s
""",
            ["done", int(queue_id)],
        )


def mark_queue_error(queue_id: int, error_message: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
UPDATE dbo.automation_event_queue
SET
    status = %s,
    retry_count = retry_count + 1,
    error_message = %s,
    processed_at = SYSUTCDATETIME()
WHERE id = %s
""",
            ["error", _normalize_queue_error_message(error_message), int(queue_id)],
        )


def safe_get_payload_value(payload: Any, field_name: str | None) -> Any:
    if not isinstance(payload, dict) or not field_name:
        return None

    current = payload
    for chunk in str(field_name).split("."):
        if not isinstance(current, dict):
            return None
        if chunk not in current:
            return None
        current = current.get(chunk)
    return current


def render_template_string(template_str: str | None, context: Any) -> str:
    if template_str is None:
        return ""

    context_dict = context if isinstance(context, dict) else {}
    template = str(template_str)

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        value = safe_get_payload_value(context_dict, key)
        if value is None:
            return match.group(0)
        return str(value)

    return _PLACEHOLDER_PATTERN.sub(_replace, template)


def _normalize_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return bool(value)

    normalized = str(value).strip().lower()
    if normalized in _TRUTHY_VALUES:
        return True
    if normalized in _FALSY_VALUES:
        return False
    return None


def _parse_datetime(value: Any) -> datetime | object | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if not isinstance(value, str):
        return _UNCASTABLE

    normalized = value.strip()
    if not normalized:
        return None

    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return _UNCASTABLE


def _parse_date(value: Any) -> date | object | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return _UNCASTABLE

    normalized = value.strip()
    if not normalized:
        return None

    try:
        return date.fromisoformat(normalized)
    except ValueError:
        parsed = _parse_datetime(normalized)
        if parsed in {_UNCASTABLE, None}:
            return parsed
        return parsed.date()


def _coerce_value(value: Any, value_type: str | None) -> Any:
    if value is None:
        return None

    normalized_type = str(value_type or AutomationConditionValueType.STRING).strip().lower()

    if normalized_type == AutomationConditionValueType.STRING:
        return str(value)

    if normalized_type == AutomationConditionValueType.INT:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return _UNCASTABLE

    if normalized_type == AutomationConditionValueType.FLOAT:
        try:
            return Decimal(str(value).strip())
        except (InvalidOperation, TypeError, ValueError):
            return _UNCASTABLE

    if normalized_type == AutomationConditionValueType.BOOL:
        normalized_bool = _normalize_bool(value)
        return normalized_bool if normalized_bool is not None else _UNCASTABLE

    if normalized_type == AutomationConditionValueType.DATE:
        return _parse_date(value)

    if normalized_type == AutomationConditionValueType.DATETIME:
        return _parse_datetime(value)

    return str(value)


def _split_csv_values(raw_value: str, value_type: str | None) -> list[Any] | None:
    values: list[Any] = []
    for chunk in str(raw_value or "").split(","):
        candidate = _coerce_value(chunk.strip(), value_type)
        if candidate is _UNCASTABLE:
            return None
        values.append(candidate)
    return values


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _build_trigger_event_label(rule: AutomationRule) -> str:
    if rule.watched_field:
        return f"{rule.source_code}.{rule.operation_type}.{rule.watched_field}"
    return f"{rule.source_code}.{rule.operation_type}.{rule.trigger_scope}"


def evaluate_condition(condition: AutomationCondition, payload: Any, old_payload: Any = None) -> bool:
    try:
        operator = condition.operator
        value_type = condition.value_type
        compare_with_old = bool(condition.compare_with_old)

        current_raw = safe_get_payload_value(payload, condition.field_name)
        old_raw = safe_get_payload_value(old_payload, condition.field_name)
        selected_raw = old_raw if compare_with_old else current_raw

        if operator == AutomationConditionOperator.IS_EMPTY:
            return _is_empty_value(selected_raw)

        if operator == AutomationConditionOperator.IS_NOT_EMPTY:
            return not _is_empty_value(selected_raw)

        if operator in {
            AutomationConditionOperator.CHANGED,
            AutomationConditionOperator.CHANGED_TO,
            AutomationConditionOperator.CHANGED_FROM_TO,
        } and not isinstance(old_payload, dict):
            return False

        current_value = _coerce_value(current_raw, value_type)
        old_value = _coerce_value(old_raw, value_type)
        selected_value = old_value if compare_with_old else current_value
        expected_value = _coerce_value(condition.expected_value, value_type)

        if operator == AutomationConditionOperator.EQUALS:
            return selected_value not in {_UNCASTABLE} and expected_value not in {_UNCASTABLE} and selected_value == expected_value

        if operator == AutomationConditionOperator.NOT_EQUALS:
            return selected_value not in {_UNCASTABLE} and expected_value not in {_UNCASTABLE} and selected_value != expected_value

        if operator == AutomationConditionOperator.CONTAINS:
            if selected_value in {_UNCASTABLE, None} or expected_value in {_UNCASTABLE, None}:
                return False
            return str(expected_value) in str(selected_value)

        if operator == AutomationConditionOperator.STARTSWITH:
            if selected_value in {_UNCASTABLE, None} or expected_value in {_UNCASTABLE, None}:
                return False
            return str(selected_value).startswith(str(expected_value))

        if operator == AutomationConditionOperator.ENDSWITH:
            if selected_value in {_UNCASTABLE, None} or expected_value in {_UNCASTABLE, None}:
                return False
            return str(selected_value).endswith(str(expected_value))

        if operator == AutomationConditionOperator.GT:
            return selected_value not in {_UNCASTABLE, None} and expected_value not in {_UNCASTABLE, None} and selected_value > expected_value

        if operator == AutomationConditionOperator.GTE:
            return selected_value not in {_UNCASTABLE, None} and expected_value not in {_UNCASTABLE, None} and selected_value >= expected_value

        if operator == AutomationConditionOperator.LT:
            return selected_value not in {_UNCASTABLE, None} and expected_value not in {_UNCASTABLE, None} and selected_value < expected_value

        if operator == AutomationConditionOperator.LTE:
            return selected_value not in {_UNCASTABLE, None} and expected_value not in {_UNCASTABLE, None} and selected_value <= expected_value

        if operator == AutomationConditionOperator.IS_TRUE:
            return selected_value is True

        if operator == AutomationConditionOperator.IS_FALSE:
            return selected_value is False

        if operator == AutomationConditionOperator.IN_CSV:
            if selected_value in {_UNCASTABLE, None}:
                return False
            expected_values = _split_csv_values(condition.expected_value, value_type)
            return expected_values is not None and selected_value in expected_values

        if operator == AutomationConditionOperator.NOT_IN_CSV:
            if selected_value in {_UNCASTABLE, None}:
                return False
            expected_values = _split_csv_values(condition.expected_value, value_type)
            return expected_values is not None and selected_value not in expected_values

        if operator == AutomationConditionOperator.CHANGED:
            return current_value not in {_UNCASTABLE} and old_value not in {_UNCASTABLE} and current_value != old_value

        if operator == AutomationConditionOperator.CHANGED_TO:
            return (
                current_value not in {_UNCASTABLE}
                and old_value not in {_UNCASTABLE}
                and expected_value not in {_UNCASTABLE}
                and old_value != current_value
                and current_value == expected_value
            )

        if operator == AutomationConditionOperator.CHANGED_FROM_TO:
            if "|" not in str(condition.expected_value or ""):
                return False
            raw_old_expected, raw_new_expected = str(condition.expected_value).split("|", 1)
            old_expected = _coerce_value(raw_old_expected.strip(), value_type)
            new_expected = _coerce_value(raw_new_expected.strip(), value_type)
            return (
                current_value not in {_UNCASTABLE}
                and old_value not in {_UNCASTABLE}
                and old_expected not in {_UNCASTABLE}
                and new_expected not in {_UNCASTABLE}
                and old_value == old_expected
                and current_value == new_expected
                and old_value != current_value
            )

        return False
    except Exception:
        return False


def _create_action_log(
    *,
    run_log: AutomationRunLog | None,
    action: AutomationAction,
    status: str,
    result_message: str,
    error_trace: str = "",
) -> AutomationActionLog | None:
    if run_log is None:
        return None

    return AutomationActionLog.objects.create(
        run_log=run_log,
        action=action,
        status=status,
        result_message=result_message,
        error_trace=error_trace or None,
    )


def _render_action_value(raw_value: Any, payload: Any) -> Any:
    if raw_value is None:
        return None
    if isinstance(raw_value, (list, tuple, set)):
        return [_render_action_value(item, payload) for item in raw_value]
    if isinstance(raw_value, (bool, int, float, Decimal)):
        return raw_value
    return render_template_string(str(raw_value), payload if isinstance(payload, dict) else {})


def _parse_email_recipients(raw_value: Any, payload: Any, field_name: str) -> list[str]:
    rendered_value = _render_action_value(raw_value, payload)

    if rendered_value is None or rendered_value == "":
        return []

    if isinstance(rendered_value, str):
        candidates = rendered_value.split(",")
    elif isinstance(rendered_value, (list, tuple, set)):
        candidates = list(rendered_value)
    else:
        raise ValueError(f"{field_name} deve essere una stringa CSV o una lista.")

    emails: list[str] = []
    for candidate in candidates:
        email = str(candidate).strip()
        if not email:
            continue
        try:
            validate_email(email)
        except ValidationError as exc:
            raise ValueError(f"Indirizzo email non valido in {field_name}: {email}.") from exc
        emails.append(email)
    return emails


def _validate_sender_email(raw_value: Any, payload: Any) -> str:
    rendered = _render_action_value(raw_value, payload)
    from_email = str(rendered or settings.DEFAULT_FROM_EMAIL or "").strip()
    if not from_email:
        raise ValueError("from_email mancante e DEFAULT_FROM_EMAIL non configurato.")
    try:
        validate_email(from_email)
    except ValidationError as exc:
        raise ValueError(f"Indirizzo from_email non valido: {from_email}.") from exc
    return from_email


def validate_target_table_and_fields(
    action_type: str,
    target_table: str,
    data_fields: list[str] | set[str],
    where_field: str | None = None,
) -> dict[str, set[str]]:
    table_name = str(target_table or "").strip()
    whitelist = get_action_table_whitelist().get(action_type, {})
    table_rules = whitelist.get(table_name)
    if table_rules is None:
        raise ValueError(f"Tabella target non whitelistata per {action_type}: {table_name or '<vuota>'}.")

    requested_fields = {str(field).strip() for field in data_fields if str(field).strip()}
    invalid_fields = requested_fields - set(table_rules.get("fields", set()))
    if invalid_fields:
        invalid_list = ", ".join(sorted(invalid_fields))
        raise ValueError(f"Colonne non whitelistate per {table_name}: {invalid_list}.")

    if where_field is not None:
        normalized_where_field = str(where_field).strip()
        if not normalized_where_field:
            raise ValueError("where_field e' obbligatorio.")
        allowed_where_fields = set(table_rules.get("where_fields", set()))
        if normalized_where_field not in allowed_where_fields:
            raise ValueError(f"Campo where non whitelistato per {table_name}: {normalized_where_field}.")

    return {
        "fields": set(table_rules.get("fields", set())),
        "where_fields": set(table_rules.get("where_fields", set())),
    }


def execute_safe_insert(target_table: str, field_values: dict[str, Any]) -> dict[str, Any]:
    if not field_values:
        raise ValueError("field_mappings non puo' essere vuoto.")

    validate_target_table_and_fields(AutomationActionType.INSERT_RECORD, target_table, list(field_values.keys()))

    columns = list(field_values.keys())
    quoted_table = connection.ops.quote_name(target_table)
    quoted_columns = ", ".join(connection.ops.quote_name(column) for column in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    params = [field_values[column] for column in columns]
    sql = f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})"

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return {
                "rowcount": cursor.rowcount if cursor.rowcount is not None else 1,
                "inserted_pk": getattr(cursor, "lastrowid", None),
                "sql": sql,
                "params": params,
            }


def execute_safe_update(
    target_table: str,
    update_fields: dict[str, Any],
    where_field: str,
    where_value: Any,
) -> dict[str, Any]:
    if not update_fields:
        raise ValueError("update_fields non puo' essere vuoto.")
    if where_value is None or where_value == "":
        raise ValueError("where_value_template non produce un valore valido.")

    validate_target_table_and_fields(
        AutomationActionType.UPDATE_RECORD,
        target_table,
        list(update_fields.keys()),
        where_field=where_field,
    )

    columns = list(update_fields.keys())
    quoted_table = connection.ops.quote_name(target_table)
    assignments = ", ".join(f"{connection.ops.quote_name(column)} = %s" for column in columns)
    quoted_where_field = connection.ops.quote_name(where_field)
    params = [update_fields[column] for column in columns] + [where_value]
    sql = f"UPDATE {quoted_table} SET {assignments} WHERE {quoted_where_field} = %s"

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return {
                "rowcount": cursor.rowcount if cursor.rowcount is not None else 0,
                "sql": sql,
                "params": params,
            }


def find_matching_rules(queue_event: dict[str, Any]) -> list[AutomationRule]:
    source_code = str(queue_event.get("source_code") or "").strip()
    operation_type = str(queue_event.get("operation_type") or "").strip().lower()
    payload = queue_event.get("payload")
    old_payload = queue_event.get("old_payload")

    if not source_code or operation_type not in {"insert", "update"}:
        return []

    base_queryset = AutomationRule.objects.filter(
        source_code=source_code,
        operation_type=operation_type,
        is_active=True,
        is_draft=False,
    ).order_by("id")

    if operation_type == "insert":
        return list(base_queryset.filter(trigger_scope="all_inserts"))

    matched_rules: list[AutomationRule] = []
    for rule in base_queryset.filter(trigger_scope__in=["all_updates", "any_change", "specific_field"]):
        if rule.trigger_scope == "all_updates":
            matched_rules.append(rule)
            continue
        if rule.trigger_scope == "any_change" and _did_payload_change(payload, old_payload):
            matched_rules.append(rule)
            continue
        if rule.trigger_scope == "specific_field" and _did_payload_field_change(payload, old_payload, rule.watched_field):
            matched_rules.append(rule)
    return matched_rules


def process_queue_event(queue_event: dict[str, Any]) -> dict[str, Any]:
    queue_id = int(queue_event["id"])
    source_code = str(queue_event.get("source_code") or "").strip()

    try:
        payload = _deserialize_queue_json(queue_event.get("payload_json"), field_name="payload_json")
        old_payload = _deserialize_queue_json(
            queue_event.get("old_payload_json"),
            field_name="old_payload_json",
            allow_null=True,
        )
        payload = _enrich_payload_for_source(source_code, payload)
        old_payload = _enrich_payload_for_source(source_code, old_payload)
    except ValueError as exc:
        mark_queue_error(queue_id, exc)
        return {"queue_id": queue_id, "status": "error", "rule_runs": 0, "message": str(exc)}

    event_context = {
        **queue_event,
        "operation_type": str(queue_event.get("operation_type") or "").strip().lower(),
        "payload": payload,
        "old_payload": old_payload,
    }

    try:
        matching_rules = find_matching_rules(event_context)
    except Exception as exc:
        logger.exception("Errore matching regole per queue event %s", queue_id)
        mark_queue_error(queue_id, f"Errore matching regole: {exc}")
        return {"queue_id": queue_id, "status": "error", "rule_runs": 0, "message": str(exc)}

    worker_errors: list[str] = []
    for rule in matching_rules:
        try:
            run_rule(
                rule,
                payload,
                old_payload=old_payload,
                queue_event_id=queue_id,
                initiated_by=None,
                is_test=False,
            )
        except Exception as exc:
            logger.exception("Errore run_rule per queue event %s e regola %s", queue_id, rule.code)
            worker_errors.append(f"{rule.code}: {exc}")

    if worker_errors:
        mark_queue_error(queue_id, "; ".join(worker_errors))
        return {
            "queue_id": queue_id,
            "status": "error",
            "rule_runs": len(matching_rules),
            "message": "; ".join(worker_errors),
        }

    mark_queue_done(queue_id)
    return {
        "queue_id": queue_id,
        "status": "done",
        "rule_runs": len(matching_rules),
        "message": "" if matching_rules else "Nessuna regola candidata.",
    }


def process_single_queue_event_by_id(queue_id: int) -> dict[str, Any]:
    queue_event = claim_queue_event_by_id(queue_id, allowed_statuses=("pending", "error"))
    if queue_event is None:
        detail = get_queue_event_detail(queue_id)
        if detail is None:
            return {
                "queue_id": int(queue_id),
                "status": "error",
                "rule_runs": 0,
                "message": "Evento queue non trovato.",
            }
        return {
            "queue_id": int(queue_id),
            "status": "error",
            "rule_runs": 0,
            "message": f"Evento queue non processabile nello stato corrente: {detail.get('status')}.",
        }
    return process_queue_event(queue_event)


def process_pending_queue_events(
    limit: int = 50,
    source_code: str | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    summary = {
        "limit": max(int(limit or 0), 1),
        "source_code": str(source_code or "").strip() or None,
        "dry_run": bool(dry_run),
        "fetched": 0,
        "done": 0,
        "error": 0,
        "rule_runs": 0,
        "events": [],
    }

    if dry_run:
        queue_events = fetch_pending_queue_event_snapshots(summary["limit"], source_code=summary["source_code"])
        summary["fetched"] = len(queue_events)
        for queue_event in queue_events:
            try:
                payload = _deserialize_queue_json(queue_event.get("payload_json"), field_name="payload_json")
                old_payload = _deserialize_queue_json(
                    queue_event.get("old_payload_json"),
                    field_name="old_payload_json",
                    allow_null=True,
                )
                event_source_code = str(queue_event.get("source_code") or "").strip()
                payload = _enrich_payload_for_source(event_source_code, payload)
                old_payload = _enrich_payload_for_source(event_source_code, old_payload)
                event_context = {
                    **queue_event,
                    "operation_type": str(queue_event.get("operation_type") or "").strip().lower(),
                    "payload": payload,
                    "old_payload": old_payload,
                }
                rules = find_matching_rules(event_context)
                summary["events"].append(
                    {
                        "queue_id": int(queue_event["id"]),
                        "status": "dry-run",
                        "candidate_rule_codes": [rule.code for rule in rules],
                    }
                )
            except Exception as exc:
                summary["error"] += 1
                summary["events"].append(
                    {
                        "queue_id": int(queue_event["id"]),
                        "status": "error",
                        "message": _normalize_queue_error_message(exc),
                    }
                )
        return summary

    queue_events = fetch_pending_queue_events(summary["limit"], source_code=summary["source_code"])
    summary["fetched"] = len(queue_events)
    for queue_event in queue_events:
        try:
            event_result = process_queue_event(queue_event)
        except Exception as exc:
            queue_id = int(queue_event["id"])
            logger.exception("Errore batch processing queue event %s", queue_id)
            try:
                mark_queue_error(queue_id, exc)
            except Exception:
                logger.exception("Errore durante mark_queue_error per queue event %s", queue_id)
            event_result = {
                "queue_id": queue_id,
                "status": "error",
                "rule_runs": 0,
                "message": _normalize_queue_error_message(exc),
            }

        summary["events"].append(event_result)
        summary["rule_runs"] += int(event_result.get("rule_runs") or 0)
        if event_result.get("status") == "done":
            summary["done"] += 1
        elif event_result.get("status") == "error":
            summary["error"] += 1

    return summary


def execute_action(
    action: AutomationAction,
    payload: Any,
    old_payload: Any = None,
    run_log: AutomationRunLog | None = None,
) -> dict[str, Any]:
    config = action.config_json if isinstance(action.config_json, dict) else {}
    payload_context = payload if isinstance(payload, dict) else {}

    try:
        if action.action_type == AutomationActionType.SEND_EMAIL:
            to = _parse_email_recipients(config.get("to"), payload_context, "to")
            cc = _parse_email_recipients(config.get("cc"), payload_context, "cc")
            bcc = _parse_email_recipients(config.get("bcc"), payload_context, "bcc")
            reply_to = _parse_email_recipients(config.get("reply_to"), payload_context, "reply_to")
            if not any([to, cc, bcc]):
                raise ValueError("send_email richiede almeno un destinatario in to, cc o bcc.")

            from_email = _validate_sender_email(config.get("from_email"), payload_context)
            subject = render_template_string(config.get("subject_template"), payload_context).strip()
            body_text = render_template_string(config.get("body_text_template"), payload_context)
            body_html = render_template_string(config.get("body_html_template"), payload_context)
            fail_silently = bool(config.get("fail_silently"))

            message = EmailMultiAlternatives(
                subject=subject,
                body=body_text,
                from_email=from_email,
                to=to,
                cc=cc,
                bcc=bcc,
                reply_to=reply_to,
            )
            if body_html:
                message.attach_alternative(body_html, "text/html")

            sent_count = message.send(fail_silently=fail_silently)
            if sent_count < 1:
                raise ValueError("Il backend email non ha confermato l'invio del messaggio.")

            recipients = ", ".join(to + cc + bcc)
            result_message = f"Email inviata a [{recipients}] con subject='{subject[:120]}'."
            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_message, "action_log": action_log}

        if action.action_type == AutomationActionType.WRITE_LOG:
            message = render_template_string(config.get("message_template"), payload_context)
            result_message = message or "write_log eseguita senza message_template valorizzato."
            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_message, "action_log": action_log}

        if action.action_type == AutomationActionType.UPDATE_DASHBOARD_METRIC:
            metric_code = str(config.get("metric_code") or "").strip()
            operation = str(config.get("operation") or "").strip().lower()
            rendered_value = render_template_string(
                config.get("value_template"),
                payload_context,
            ).strip()

            if not metric_code:
                raise ValueError("update_dashboard_metric richiede metric_code.")
            if operation not in {"set", "increment", "decrement"}:
                raise ValueError("update_dashboard_metric richiede operation valida: set, increment o decrement.")
            if not rendered_value:
                raise ValueError("update_dashboard_metric richiede value_template valorizzato.")

            try:
                delta = Decimal(rendered_value)
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValueError("value_template non produce un numero decimale valido.") from exc

            metric, created = DashboardMetricValue.objects.get_or_create(
                metric_code=metric_code,
                defaults={
                    "label": metric_code.replace("_", " ").strip().title() or metric_code,
                    "current_value": Decimal("0"),
                },
            )

            if operation == "set":
                metric.current_value = delta
            elif operation == "increment":
                metric.current_value = Decimal(metric.current_value) + delta
            else:
                metric.current_value = Decimal(metric.current_value) - delta
            metric.save()

            prefix = "creata" if created else "aggiornata"
            result_message = (
                f"Dashboard metric {metric.metric_code} {prefix} con operation={operation} e value={delta}."
            )
            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_message, "action_log": action_log}

        if action.action_type == AutomationActionType.INSERT_RECORD:
            target_table = str(config.get("target_table") or "").strip()
            field_mappings = config.get("field_mappings")
            if not isinstance(field_mappings, dict) or not field_mappings:
                raise ValueError("insert_record richiede field_mappings non vuoto.")

            rendered_fields = {
                str(field_name).strip(): _render_action_value(raw_value, payload_context)
                for field_name, raw_value in field_mappings.items()
            }
            result = execute_safe_insert(target_table, rendered_fields)
            columns = ", ".join(rendered_fields.keys())
            result_message = (
                f"Insert eseguito su {target_table} con colonne [{columns}]"
                f" e righe inserite={result['rowcount']}."
            )
            if result.get("inserted_pk") is not None:
                result_message = f"{result_message} PK={result['inserted_pk']}."
            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_message, "action_log": action_log}

        if action.action_type == AutomationActionType.UPDATE_RECORD:
            target_table = str(config.get("target_table") or "").strip()
            where_field = str(config.get("where_field") or "").strip()
            where_value = _render_action_value(config.get("where_value_template"), payload_context)
            if isinstance(where_value, str) and _PLACEHOLDER_PATTERN.search(where_value):
                raise ValueError("where_value_template non produce un valore valido.")
            update_fields = config.get("update_fields")
            if not isinstance(update_fields, dict) or not update_fields:
                raise ValueError("update_record richiede update_fields non vuoto.")

            rendered_update_fields = {
                str(field_name).strip(): _render_action_value(raw_value, payload_context)
                for field_name, raw_value in update_fields.items()
            }
            result = execute_safe_update(target_table, rendered_update_fields, where_field, where_value)
            columns = ", ".join(rendered_update_fields.keys())
            result_message = (
                f"Update eseguito su {target_table} usando {where_field}"
                f" e colonne [{columns}]. Record aggiornati={result['rowcount']}."
            )
            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_message, "action_log": action_log}

        raise NotImplementedError(f"Action type '{action.action_type}' non ancora implementato in fase 4B.")
    except Exception as exc:
        error_trace = traceback.format_exc()
        result_message = str(exc) or "Errore durante esecuzione action."
        action_log = _create_action_log(
            run_log=run_log,
            action=action,
            status=AutomationActionLogStatus.ERROR,
            result_message=result_message,
            error_trace=error_trace,
        )
        return {"status": AutomationActionLogStatus.ERROR, "result_message": result_message, "action_log": action_log}


def run_rule(
    rule: AutomationRule,
    payload: Any,
    old_payload: Any = None,
    queue_event_id: int | None = None,
    initiated_by: Any = None,
    is_test: bool = False,
) -> AutomationRunLog:
    started_at = timezone.now()
    payload = _enrich_payload_for_source(rule.source_code, payload)
    old_payload = _enrich_payload_for_source(rule.source_code, old_payload)
    run_log = AutomationRunLog.objects.create(
        rule=rule,
        queue_event_id=queue_event_id,
        source_code=rule.source_code,
        operation_type=rule.operation_type,
        trigger_event_label=_build_trigger_event_label(rule),
        status=AutomationRunLogStatus.TEST if is_test else AutomationRunLogStatus.SUCCESS,
        payload_json=payload if payload is not None else {},
        old_payload_json=old_payload,
        started_at=started_at,
        initiated_by=initiated_by,
        is_test=is_test,
        result_message="Esecuzione avviata.",
    )

    try:
        enabled_conditions = rule.conditions.filter(is_enabled=True).order_by("order", "id")
        for condition in enabled_conditions:
            if not evaluate_condition(condition, payload, old_payload=old_payload):
                run_log.status = AutomationRunLogStatus.SKIPPED
                run_log.result_message = (
                    f"Condizione non soddisfatta: {condition.field_name} {condition.operator} (order={condition.order})."
                )
                break
        else:
            action_errors = 0
            action_count = 0
            enabled_actions = rule.actions.filter(is_enabled=True).order_by("order", "id")
            for action in enabled_actions:
                action_count += 1
                result = execute_action(action, payload, old_payload=old_payload, run_log=run_log)
                if result["status"] == AutomationActionLogStatus.ERROR:
                    action_errors += 1
                    if rule.stop_on_first_failure:
                        run_log.result_message = (
                            f"Esecuzione interrotta alla action {action.order} ({action.action_type}) per stop_on_first_failure."
                        )
                        break

            if action_errors:
                run_log.status = AutomationRunLogStatus.ERROR
                if not run_log.result_message or run_log.result_message == "Esecuzione avviata.":
                    run_log.result_message = f"Esecuzione completata con {action_errors} action in errore."
            else:
                run_log.status = AutomationRunLogStatus.TEST if is_test else AutomationRunLogStatus.SUCCESS
                run_log.result_message = f"Regola eseguita con successo. Azioni elaborate: {action_count}."
    except Exception:
        run_log.status = AutomationRunLogStatus.ERROR
        run_log.result_message = "Errore inatteso durante l'esecuzione della regola."
        run_log.error_trace = traceback.format_exc()
    finally:
        finished_at = timezone.now()
        run_log.finished_at = finished_at
        run_log.execution_ms = max(int((finished_at - started_at).total_seconds() * 1000), 0)
        if is_test:
            rule.last_test_at = finished_at
            rule.save(update_fields=["last_test_at", "updated_at"])
        else:
            rule.last_run_at = finished_at
            rule.save(update_fields=["last_run_at", "updated_at"])
        run_log.save()

    return run_log
