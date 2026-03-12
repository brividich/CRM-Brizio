from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import connection, transaction
from django.utils.text import slugify

from .models import (
    AutomationAction,
    AutomationActionType,
    AutomationCondition,
    AutomationConditionOperator,
    AutomationConditionValueType,
    AutomationRule,
    AutomationRuleOperationType,
    AutomationRuleTriggerScope,
)
from .services import (
    evaluate_condition,
    render_template_string,
    safe_get_payload_value,
    validate_target_table_and_fields,
)
from .source_registry import get_source_definition, get_source_fields


PLACEHOLDER_PATTERN = re.compile(r"\{([^{}]+)\}")
SAMPLE_VALUE_BY_TYPE = {
    "int": 101,
    "float": 1.5,
    "bool": True,
    "date": "2026-03-11",
    "datetime": "2026-03-11T09:00:00",
    "string": "esempio",
}
IMPORT_STATUS_LABELS = {
    "ready": "pronto all'import",
    "partial": "import parziale",
    "blocked": "bloccato",
}
SUPPORTED_ACTION_TYPES = {choice[0] for choice in AutomationActionType.choices}
SUPPORTED_OPERATIONS = {choice[0] for choice in AutomationRuleOperationType.choices}
SUPPORTED_TRIGGER_SCOPES = {choice[0] for choice in AutomationRuleTriggerScope.choices}
SUPPORTED_CONDITION_OPERATORS = {choice[0] for choice in AutomationConditionOperator.choices}
SUPPORTED_CONDITION_VALUE_TYPES = {choice[0] for choice in AutomationConditionValueType.choices}


class PackageImportError(ValueError):
    pass


def _string(value: Any) -> str:
    return str(value or "").strip()


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _string(value).lower() in {"1", "true", "yes", "on"}


def _serialize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool, Decimal)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _normalize_token(value: Any) -> str:
    text = _string(value)
    if not text:
        return ""
    text = text.replace("{", "").replace("}", "")
    text = re.sub(r"[\s\-]+", "_", text.lower())
    return re.sub(r"[^a-z0-9_\.]", "", text)


def _pretty_json(value: Any) -> str:
    if value is None or value == "" or value == [] or value == {}:
        return ""
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, default=str)


def _summarize_value(value: Any) -> list[str]:
    if value is None or value == "" or value == [] or value == {}:
        return []
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            else:
                result.append(json.dumps(item, ensure_ascii=False, sort_keys=True, default=str))
        return result
    if isinstance(value, dict):
        result = []
        for key, item_value in value.items():
            if isinstance(item_value, (dict, list)):
                result.append(f"{key}: {json.dumps(item_value, ensure_ascii=False, sort_keys=True, default=str)}")
            else:
                result.append(f"{key}: {item_value}")
        return result
    return [_string(value)]


def _package_hash(package_data: dict[str, Any]) -> str:
    payload = json.dumps(package_data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _deep_get(data: Any, *path: str) -> Any:
    current = data
    for chunk in path:
        if not isinstance(current, dict):
            return None
        current = current.get(chunk)
    return current


def _extract_flow_name(package_data: dict[str, Any], filename: str) -> str:
    candidates = [
        package_data.get("flow_name"),
        _deep_get(package_data, "input", "flow_name"),
        _deep_get(package_data, "input", "name"),
        _deep_get(package_data, "input", "flow", "name"),
        _deep_get(package_data, "target_context", "flow_name"),
        _deep_get(package_data, "target_context", "name"),
        _deep_get(package_data, "source_candidate", "flow_name"),
    ]
    for candidate in candidates:
        value = _string(candidate)
        if value:
            return value
    return _string(filename).removesuffix(".automation_package.json").removesuffix(".json") or "Package importato"


def _extract_source_candidate(package_data: dict[str, Any]) -> dict[str, Any]:
    raw_candidate = package_data.get("source_candidate")
    if isinstance(raw_candidate, dict):
        source_code = _string(
            raw_candidate.get("source_code")
            or raw_candidate.get("code")
            or raw_candidate.get("source")
        )
        return {
            "source_code": source_code,
            "label": _string(raw_candidate.get("label") or raw_candidate.get("name")) or source_code,
            "raw": deepcopy(raw_candidate),
        }
    if isinstance(raw_candidate, str):
        return {"source_code": _string(raw_candidate), "label": _string(raw_candidate), "raw": raw_candidate}
    return {"source_code": "", "label": "", "raw": raw_candidate}


def build_example_payload(source_code: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in get_source_fields(source_code):
        field_name = _string(field.get("name"))
        data_type = _string(field.get("data_type"))
        if not field_name:
            continue
        payload[field_name] = _sample_value_for_field(source_code, field_name, data_type)
    return payload


def build_example_payload_json(source_code: str | None) -> str:
    return _pretty_json(build_example_payload(source_code))


def _sample_value_for_field(source_code: str | None, field_name: str, data_type: str) -> Any:
    normalized_source = _string(source_code).lower()
    normalized_field = _string(field_name).lower()

    if "email" in normalized_field:
        return "demo@example.com"

    if normalized_source == "assenze":
        if normalized_field == "tipo_assenza":
            return "Malattia"
        if normalized_field == "moderation_status":
            return 0
        if normalized_field == "motivazione_richiesta":
            return "Inserimento di esempio"

    if normalized_source == "tasks":
        if normalized_field == "title":
            return "Task di esempio"
        if normalized_field == "status":
            return "DONE"
        if normalized_field == "priority":
            return "MEDIUM"

    if normalized_source == "tickets":
        if normalized_field == "stato":
            return "APERTA"
        if normalized_field == "priorita":
            return "MEDIA"
        if normalized_field == "titolo":
            return "Ticket di esempio"

    if normalized_source == "assets":
        if normalized_field == "status":
            return "IN_USE"
        if normalized_field == "asset_tag":
            return "AST-000101"
        if normalized_field == "name":
            return "Asset di esempio"

    if normalized_source == "anomalie":
        if normalized_field == "avanzamento":
            return "APERTO"
        if normalized_field == "seriale":
            return "SN-EXAMPLE-001"

    return SAMPLE_VALUE_BY_TYPE.get(data_type, "esempio")


def _quote_name(name: str) -> str:
    return connection.ops.quote_name(name)


def _pick_display_fields(source_code: str | None, limit: int = 5) -> list[str]:
    preferred = ["title", "titolo", "name", "asset_tag", "status", "stato", "tipo_assenza", "priority", "priorita"]
    available = [_string(field.get("name")) for field in get_source_fields(source_code)]
    selected: list[str] = []
    for candidate in preferred:
        if candidate in available and candidate not in selected:
            selected.append(candidate)
    for candidate in available:
        if candidate not in selected:
            selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


def list_recent_source_records(source_code: str | None, limit: int = 12) -> list[dict[str, Any]]:
    source = get_source_definition(source_code)
    if source is None:
        return []

    pk_field = _string(source.get("pk_field")) or "id"
    display_fields = _pick_display_fields(source_code)
    fields = [pk_field, *[field for field in display_fields if field != pk_field]]
    quoted_fields = ", ".join(_quote_name(field) for field in fields)
    quoted_pk = _quote_name(pk_field)
    quoted_table = _quote_name(_string(source.get("table_name")))

    if connection.vendor == "sqlite":
        sql = f"SELECT {quoted_fields} FROM {quoted_table} ORDER BY {quoted_pk} DESC LIMIT %s"
        params: list[Any] = [max(int(limit or 0), 1)]
    else:
        sql = f"SELECT TOP ({max(int(limit or 0), 1)}) {quoted_fields} FROM {quoted_table} ORDER BY {quoted_pk} DESC"
        params = []

    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [column[0] for column in cursor.description or []]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception:
        return []

    records: list[dict[str, Any]] = []
    for row in rows:
        row_id = row.get(pk_field)
        label_bits = [f"{field}={row.get(field)}" for field in fields if field != pk_field and row.get(field) not in {None, ""}]
        records.append(
            {
                "id": row_id,
                "label": f"#{row_id} - {' | '.join(label_bits[:3])}" if label_bits else f"#{row_id}",
            }
        )
    return records


def load_source_record_payload(source_code: str | None, record_id: Any) -> dict[str, Any] | None:
    source = get_source_definition(source_code)
    if source is None:
        return None

    record_pk = _string(record_id)
    if not record_pk:
        return None

    fields = [_string(field.get("name")) for field in get_source_fields(source_code)]
    pk_field = _string(source.get("pk_field")) or "id"
    if pk_field not in fields:
        fields.insert(0, pk_field)

    quoted_fields = ", ".join(_quote_name(field) for field in fields if field)
    quoted_pk = _quote_name(pk_field)
    quoted_table = _quote_name(_string(source.get("table_name")))
    sql = f"SELECT {quoted_fields} FROM {quoted_table} WHERE {quoted_pk} = %s"

    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, [record_pk])
            row = cursor.fetchone()
            columns = [column[0] for column in cursor.description or []]
    except Exception:
        return None

    if row is None:
        return None
    return dict(zip(columns, row))


def _build_base_alias_map(source_code: str | None) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for field in get_source_fields(source_code):
        field_name = _string(field.get("name"))
        field_label = _string(field.get("label"))
        for alias in {field_name, field_label}:
            normalized = _normalize_token(alias)
            if normalized:
                alias_map[normalized] = field_name
    return alias_map


def _resolve_source_field_name(raw_field_name: Any, alias_map: dict[str, str]) -> str:
    normalized = _normalize_token(raw_field_name)
    if not normalized:
        return ""
    return alias_map.get(normalized, "")


def _extract_candidate_target(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in (
            "target_field",
            "target",
            "automation_field",
            "portal_field",
            "field_name",
            "mapped_field",
            "approved_target_field",
        ):
            target = _string(value.get(key))
            if target:
                return target
        for key in ("candidates", "candidate_fields", "approved_candidates"):
            raw_candidates = value.get(key)
            if isinstance(raw_candidates, list):
                for item in raw_candidates:
                    candidate = _extract_candidate_target(item)
                    if candidate:
                        return candidate
    if isinstance(value, list):
        for item in value:
            candidate = _extract_candidate_target(item)
            if candidate:
                return candidate
    return ""


def _iter_mapping_pairs(raw_mapping: Any) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if isinstance(raw_mapping, dict):
        for key, value in raw_mapping.items():
            extracted_target = _extract_candidate_target(value)
            if extracted_target:
                pairs.append((_string(key), extracted_target))
                continue
            if isinstance(value, dict):
                source = _string(
                    value.get("source_field")
                    or value.get("source")
                    or value.get("source_column")
                    or value.get("column")
                ) or _string(key)
                target = _string(
                    value.get("target_field")
                    or value.get("target")
                    or value.get("automation_field")
                    or value.get("portal_field")
                    or value.get("field_name")
                )
                if source or target:
                    pairs.append((source, target))
            elif isinstance(value, str):
                pairs.append((_string(key), _string(value)))
    elif isinstance(raw_mapping, list):
        for item in raw_mapping:
            if isinstance(item, dict):
                source = _string(
                    item.get("source_field")
                    or item.get("source")
                    or item.get("source_column")
                    or item.get("column")
                    or item.get("name")
                )
                target = _string(
                    item.get("target_field")
                    or item.get("target")
                    or item.get("automation_field")
                    or item.get("portal_field")
                    or item.get("field_name")
                )
                if not target:
                    target = _extract_candidate_target(item.get("candidates"))
                if source or target:
                    pairs.append((source, target))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                pairs.append((_string(item[0]), _string(item[1])))
    return pairs


def _normalize_mapping_rows(
    raw_mapping: Any,
    *,
    source_code: str | None,
    mapping_source: str,
) -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
    alias_map = _build_base_alias_map(source_code)
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []

    for source_field, target_field in _iter_mapping_pairs(raw_mapping):
        resolved_target = _resolve_source_field_name(target_field, alias_map)
        reverse_target = _resolve_source_field_name(source_field, alias_map)

        effective_source = source_field
        effective_target = resolved_target
        if not effective_target and reverse_target:
            effective_target = reverse_target
            effective_source = target_field

        row = {
            "source_field": effective_source or target_field or source_field,
            "target_field": effective_target,
            "mapping_source": mapping_source,
            "valid_target": bool(effective_target),
        }
        if effective_target:
            normalized_source = _normalize_token(effective_source)
            if normalized_source:
                alias_map[normalized_source] = effective_target
        else:
            warnings.append(
                f"Mapping non risolto: `{effective_source or '<vuoto>'}` -> `{target_field or '<vuoto>'}`."
            )
        rows.append(row)

    return rows, alias_map, warnings


def _translate_placeholders(value: Any, alias_map: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _translate_placeholders(item_value, alias_map) for key, item_value in value.items()}
    if isinstance(value, list):
        return [_translate_placeholders(item_value, alias_map) for item_value in value]
    if isinstance(value, tuple):
        return [_translate_placeholders(item_value, alias_map) for item_value in value]
    if not isinstance(value, str):
        return value

    def _replace(match: re.Match[str]) -> str:
        placeholder = _string(match.group(1))
        resolved = _resolve_source_field_name(placeholder, alias_map)
        if not resolved:
            return match.group(0)
        return f"{{{resolved}}}"

    return PLACEHOLDER_PATTERN.sub(_replace, value)


def _collect_placeholders(value: Any) -> set[str]:
    placeholders: set[str] = set()
    if isinstance(value, dict):
        for item_value in value.values():
            placeholders.update(_collect_placeholders(item_value))
    elif isinstance(value, (list, tuple)):
        for item_value in value:
            placeholders.update(_collect_placeholders(item_value))
    elif isinstance(value, str):
        for match in PLACEHOLDER_PATTERN.findall(value):
            normalized = _string(match)
            if normalized:
                placeholders.add(normalized)
    return placeholders


def _missing_placeholders_in_payload(value: Any, payload: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for placeholder in sorted(_collect_placeholders(value)):
        if safe_get_payload_value(payload, placeholder) is None:
            missing.append(placeholder)
    return missing


def _extract_rules(package_data: dict[str, Any]) -> list[Any]:
    proposed_rules = package_data.get("proposed_rules")
    if isinstance(proposed_rules, list):
        return proposed_rules
    rules = package_data.get("rules")
    if isinstance(rules, list):
        return rules
    return []


def _compatibility_is_blocking(compatibility: Any) -> bool:
    if isinstance(compatibility, bool):
        return not compatibility
    if isinstance(compatibility, dict):
        if "compatible" in compatibility and compatibility.get("compatible") is False:
            return True
        if "is_compatible" in compatibility and compatibility.get("is_compatible") is False:
            return True
        status = _string(compatibility.get("status")).lower()
        return status in {"blocked", "error", "incompatible", "unsupported"}
    if isinstance(compatibility, list):
        return any(_compatibility_is_blocking(item) for item in compatibility)
    return False


def _normalize_action_config(raw_action: dict[str, Any], action_type: str) -> dict[str, Any]:
    raw_config = raw_action.get("config_json")
    if not isinstance(raw_config, dict):
        raw_config = raw_action.get("config")
    if not isinstance(raw_config, dict):
        raw_config = {}

    def pick(*keys: str, default: Any = "") -> Any:
        for key in keys:
            if key in raw_action:
                raw_value = raw_action.get(key)
                if raw_value is not None and raw_value != "":
                    return raw_value
            if key in raw_config:
                raw_value = raw_config.get(key)
                if raw_value is not None and raw_value != "":
                    return raw_value
        return default

    if action_type == AutomationActionType.SEND_EMAIL:
        return {
            "from_email": pick("from_email", "email_from_email", "email_from"),
            "to": pick("to", "email_to"),
            "cc": pick("cc", "email_cc"),
            "bcc": pick("bcc", "email_bcc"),
            "reply_to": pick("reply_to", "email_reply_to"),
            "subject_template": pick("subject_template", "email_subject_template", "subject"),
            "body_text_template": pick("body_text_template", "email_body_text_template", "body_text", "body"),
            "body_html_template": pick("body_html_template", "email_body_html_template", "body_html"),
            "fail_silently": _bool(pick("fail_silently", "email_fail_silently")),
        }

    if action_type == AutomationActionType.WRITE_LOG:
        return {
            "message_template": pick("message_template", "write_log_message_template", "message"),
        }

    if action_type == AutomationActionType.UPDATE_DASHBOARD_METRIC:
        return {
            "metric_code": pick("metric_code"),
            "operation": _string(pick("operation", "metric_operation")).lower(),
            "value_template": pick("value_template", "metric_value_template", "value"),
        }

    if action_type == AutomationActionType.INSERT_RECORD:
        field_mappings = pick("field_mappings", "fields", "mappings", default={})
        if isinstance(field_mappings, list):
            field_mappings = {
                _string(item.get("target_field") or item.get("field") or item.get("name")): item.get("value")
                for item in field_mappings
                if isinstance(item, dict)
            }
        return {
            "target_table": pick("target_table", "insert_target_table", "table"),
            "field_mappings": field_mappings if isinstance(field_mappings, dict) else {},
        }

    if action_type == AutomationActionType.UPDATE_RECORD:
        update_fields = pick("update_fields", "fields", "mappings", default={})
        if isinstance(update_fields, list):
            update_fields = {
                _string(item.get("target_field") or item.get("field") or item.get("name")): item.get("value")
                for item in update_fields
                if isinstance(item, dict)
            }
        raw_where = raw_config.get("where") if isinstance(raw_config.get("where"), dict) else raw_action.get("where")
        where_field = pick("where_field", "update_where_field")
        where_value_template = pick("where_value_template", "update_where_value_template")
        if not where_field and isinstance(raw_where, dict):
            where_field = _string(raw_where.get("field"))
            where_value_template = raw_where.get("value_template") or raw_where.get("value")
        return {
            "target_table": pick("target_table", "update_target_table", "table"),
            "where_field": where_field,
            "where_value_template": where_value_template,
            "update_fields": update_fields if isinstance(update_fields, dict) else {},
        }

    if isinstance(raw_config, dict) and raw_config:
        return deepcopy(raw_config)

    ignored_keys = {"action_type", "type", "description", "is_enabled", "enabled", "order", "config", "config_json"}
    return {key: value for key, value in raw_action.items() if key not in ignored_keys}


def _build_portal_code(raw_code: str, index: int) -> str:
    normalized = slugify(raw_code or f"import-rule-{index}")
    return normalized[:120] or f"import-rule-{index}"


def generate_available_rule_code(base_code: str, reserved_codes: set[str] | None = None) -> str:
    normalized_base = _build_portal_code(base_code, 1)
    reserved = {code for code in (reserved_codes or set()) if code}
    existing_codes = set(AutomationRule.objects.values_list("code", flat=True))
    if normalized_base not in existing_codes and normalized_base not in reserved:
        return normalized_base

    stem = normalized_base[:100] or "import-rule"
    suffix = 2
    while True:
        candidate = f"{stem}-{suffix}"
        if candidate not in existing_codes and candidate not in reserved:
            return candidate
        suffix += 1


def _render_recipient_list(value: Any, payload: dict[str, Any]) -> list[str]:
    rendered = render_template_string(_serialize_text(value), payload).strip()
    if not rendered:
        return []
    return [item.strip() for item in rendered.split(",") if item.strip()]


def _validate_email_list(emails: list[str], *, field_name: str) -> list[str]:
    errors: list[str] = []
    for email in emails:
        if PLACEHOLDER_PATTERN.search(email):
            continue
        try:
            validate_email(email)
        except ValidationError:
            errors.append(f"{field_name}: indirizzo non valido `{email}`.")
    return errors


def _validate_action_structure(
    action_plan: dict[str, Any],
    *,
    source_code: str,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    config_json = action_plan["config_json"]
    action_type = action_plan["action_type"]
    missing_placeholders = [
        placeholder
        for placeholder in sorted(_collect_placeholders(config_json))
        if not _resolve_source_field_name(placeholder, _build_base_alias_map(source_code))
    ]
    if missing_placeholders:
        errors.append(
            "Placeholder non presenti nella sorgente portale: " + ", ".join(f"{{{item}}}" for item in missing_placeholders) + "."
        )

    if action_type not in SUPPORTED_ACTION_TYPES:
        errors.append(f"Action `{action_type or '<vuota>'}` non supportata dal runtime corrente.")
        return errors, warnings

    if action_type == AutomationActionType.SEND_EMAIL:
        has_any_recipient = any(_string(config_json.get(key)) for key in ("to", "cc", "bcc"))
        if not has_any_recipient:
            errors.append("send_email richiede almeno un destinatario in to, cc o bcc.")
        static_recipients = []
        for key in ("to", "cc", "bcc", "reply_to"):
            raw_value = config_json.get(key)
            if isinstance(raw_value, str) and raw_value:
                static_recipients.extend([item.strip() for item in raw_value.split(",") if item.strip()])
        errors.extend(_validate_email_list(static_recipients, field_name="destinatario"))
        from_email = _string(config_json.get("from_email"))
        if from_email and not PLACEHOLDER_PATTERN.search(from_email):
            try:
                validate_email(from_email)
            except ValidationError:
                errors.append(f"from_email non valido: `{from_email}`.")
        if not _string(config_json.get("subject_template")):
            warnings.append("send_email senza subject_template valorizzato.")
        if not _string(config_json.get("body_text_template")) and not _string(config_json.get("body_html_template")):
            warnings.append("send_email senza body_text_template/body_html_template valorizzati.")

    elif action_type == AutomationActionType.WRITE_LOG:
        if not _string(config_json.get("message_template")):
            warnings.append("write_log senza message_template valorizzato.")

    elif action_type == AutomationActionType.UPDATE_DASHBOARD_METRIC:
        metric_code = _string(config_json.get("metric_code"))
        operation = _string(config_json.get("operation")).lower()
        value_template = _string(config_json.get("value_template"))
        if not metric_code:
            errors.append("update_dashboard_metric richiede metric_code.")
        if operation not in {"set", "increment", "decrement"}:
            errors.append("update_dashboard_metric richiede operation valida: set, increment o decrement.")
        if not value_template:
            errors.append("update_dashboard_metric richiede value_template valorizzato.")
        elif not PLACEHOLDER_PATTERN.search(value_template):
            try:
                Decimal(value_template)
            except (InvalidOperation, TypeError, ValueError):
                errors.append("update_dashboard_metric richiede value_template numerico o placeholder valido.")

    elif action_type == AutomationActionType.INSERT_RECORD:
        target_table = _string(config_json.get("target_table"))
        field_mappings = config_json.get("field_mappings")
        if not isinstance(field_mappings, dict) or not field_mappings:
            errors.append("insert_record richiede field_mappings non vuoto.")
        else:
            try:
                validate_target_table_and_fields(action_type, target_table, list(field_mappings.keys()))
            except ValueError as exc:
                errors.append(str(exc))

    elif action_type == AutomationActionType.UPDATE_RECORD:
        target_table = _string(config_json.get("target_table"))
        where_field = _string(config_json.get("where_field"))
        update_fields = config_json.get("update_fields")
        if not isinstance(update_fields, dict) or not update_fields:
            errors.append("update_record richiede update_fields non vuoto.")
        try:
            validate_target_table_and_fields(
                action_type,
                target_table,
                list(update_fields.keys()) if isinstance(update_fields, dict) else [],
                where_field=where_field,
            )
        except ValueError as exc:
            errors.append(str(exc))
        if not _string(config_json.get("where_value_template")):
            errors.append("update_record richiede where_value_template valorizzato.")

    return errors, warnings


def _simulate_action(
    action_plan: dict[str, Any],
    *,
    payload: dict[str, Any],
) -> dict[str, Any]:
    action_type = action_plan["action_type"]
    config_json = action_plan["config_json"]
    missing_payload_placeholders = _missing_placeholders_in_payload(config_json, payload)
    errors: list[str] = []
    preview = ""

    if action_type not in SUPPORTED_ACTION_TYPES:
        errors.append(f"Action `{action_type or '<vuota>'}` non supportata.")
        return {
            "status": "error",
            "missing_payload_placeholders": missing_payload_placeholders,
            "errors": errors,
            "preview": preview,
        }

    if action_type == AutomationActionType.SEND_EMAIL:
        to = _render_recipient_list(config_json.get("to"), payload)
        cc = _render_recipient_list(config_json.get("cc"), payload)
        bcc = _render_recipient_list(config_json.get("bcc"), payload)
        reply_to = _render_recipient_list(config_json.get("reply_to"), payload)
        rendered_from = render_template_string(_serialize_text(config_json.get("from_email")), payload).strip()
        rendered_subject = render_template_string(_serialize_text(config_json.get("subject_template")), payload).strip()
        if not any([to, cc, bcc]):
            errors.append("Nessun destinatario risolto nel dry-run.")
        errors.extend(_validate_email_list(to + cc + bcc + reply_to, field_name="destinatario"))
        if rendered_from and not PLACEHOLDER_PATTERN.search(rendered_from):
            try:
                validate_email(rendered_from)
            except ValidationError:
                errors.append(f"from_email non valido nel dry-run: `{rendered_from}`.")
        preview = f"Email dry-run -> to={', '.join(to) or '-'} subject={rendered_subject or '-'}"

    elif action_type == AutomationActionType.WRITE_LOG:
        preview = render_template_string(_serialize_text(config_json.get("message_template")), payload).strip() or "-"

    elif action_type == AutomationActionType.UPDATE_DASHBOARD_METRIC:
        rendered_value = render_template_string(_serialize_text(config_json.get("value_template")), payload).strip()
        if not rendered_value:
            errors.append("value_template non risolto nel dry-run.")
        elif not PLACEHOLDER_PATTERN.search(rendered_value):
            try:
                Decimal(rendered_value)
            except (InvalidOperation, TypeError, ValueError):
                errors.append("value_template non produce un numero valido nel dry-run.")
        preview = (
            f"Metric dry-run -> {config_json.get('metric_code') or '-'}"
            f" {config_json.get('operation') or '-'} {rendered_value or '-'}"
        )

    elif action_type == AutomationActionType.INSERT_RECORD:
        field_mappings = config_json.get("field_mappings") or {}
        rendered_fields = {
            field_name: render_template_string(_serialize_text(field_value), payload)
            for field_name, field_value in field_mappings.items()
        }
        preview = f"Insert dry-run -> {config_json.get('target_table') or '-'} {json.dumps(rendered_fields, ensure_ascii=False, sort_keys=True)}"

    elif action_type == AutomationActionType.UPDATE_RECORD:
        rendered_where = render_template_string(_serialize_text(config_json.get("where_value_template")), payload).strip()
        rendered_fields = {
            field_name: render_template_string(_serialize_text(field_value), payload)
            for field_name, field_value in (config_json.get("update_fields") or {}).items()
        }
        if not rendered_where or PLACEHOLDER_PATTERN.search(rendered_where):
            errors.append("where_value_template non risolto nel dry-run.")
        preview = (
            f"Update dry-run -> {config_json.get('target_table') or '-'}"
            f" where {config_json.get('where_field') or '-'}={rendered_where or '-'}"
            f" set {json.dumps(rendered_fields, ensure_ascii=False, sort_keys=True)}"
        )

    status = "error" if errors or missing_payload_placeholders else "ok"
    return {
        "status": status,
        "missing_payload_placeholders": missing_payload_placeholders,
        "errors": errors,
        "preview": preview,
    }


def analyze_package_bytes(raw_bytes: bytes, *, filename: str) -> dict[str, Any]:
    normalized_filename = _string(filename)
    if not (normalized_filename.endswith(".automation_package.json") or normalized_filename.endswith(".json")):
        raise PackageImportError("Sono accettati solo file `.automation_package.json` o `.json` compatibili.")

    try:
        decoded = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PackageImportError("Il file deve essere UTF-8 valido.") from exc

    try:
        package_data = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise PackageImportError("Il file non contiene JSON valido.") from exc

    if not isinstance(package_data, dict):
        raise PackageImportError("Il package deve essere un oggetto JSON.")

    rules = _extract_rules(package_data)
    if not isinstance(rules, list):
        raise PackageImportError("Il package deve contenere `proposed_rules` come lista.")
    if not rules:
        raise PackageImportError("Il package non contiene regole proposte in `proposed_rules`.")

    return analyze_package_dict(package_data, filename=normalized_filename)


def analyze_package_dict(package_data: dict[str, Any], *, filename: str) -> dict[str, Any]:
    flow_name = _extract_flow_name(package_data, filename)
    source_candidate = _extract_source_candidate(package_data)
    source_code = source_candidate["source_code"]
    raw_rules = _extract_rules(package_data)
    package_warnings: list[str] = []
    package_errors: list[str] = []

    compatibility = package_data.get("compatibility")
    issues = package_data.get("issues")
    target_context = package_data.get("target_context")
    package_version = _string(package_data.get("package_version")) or "n/d"

    source_definition = get_source_definition(source_code)
    if source_definition is None:
        package_errors.append(f"Sorgente package non supportata dal portale: `{source_code or '<vuota>'}`.")

    if _compatibility_is_blocking(compatibility):
        package_errors.append("Il package segnala una compatibilita' bloccante o incompatibile.")

    raw_mapping = package_data.get("approved_field_mapping")
    mapping_source = "approved_field_mapping"
    if raw_mapping is None or raw_mapping == "" or raw_mapping == [] or raw_mapping == {}:
        raw_mapping = package_data.get("field_mapping_candidates")
        mapping_source = "field_mapping_candidates"
        if raw_mapping is not None and raw_mapping != "" and raw_mapping != [] and raw_mapping != {}:
            package_warnings.append(
                "`approved_field_mapping` assente: uso `field_mapping_candidates` come fallback conservativo."
            )
        else:
            package_warnings.append("Nessun mapping approvato disponibile: saranno usati solo i nomi campo gia' compatibili.")

    mapping_rows, alias_map, mapping_warnings = _normalize_mapping_rows(
        raw_mapping,
        source_code=source_code,
        mapping_source=mapping_source,
    )
    package_warnings.extend(mapping_warnings)

    reserved_codes: set[str] = set()
    analyzed_rules: list[dict[str, Any]] = []
    importable_rule_count = 0

    for index, raw_rule in enumerate(raw_rules, start=1):
        if not isinstance(raw_rule, dict):
            analyzed_rules.append(
                {
                    "index": index,
                    "name": f"Regola #{index}",
                    "source_rule_code": "",
                    "portal_code": "",
                    "requested_is_active": False,
                    "requested_is_draft": True,
                    "final_is_active": False,
                    "final_is_draft": True,
                    "conditions": [],
                    "actions": [],
                    "errors": ["Regola non valida: ogni elemento di `proposed_rules` deve essere un oggetto JSON."],
                    "warnings": [],
                    "import_decision": "skip",
                    "is_importable": False,
                }
            )
            continue

        rule_errors: list[str] = []
        rule_warnings: list[str] = []
        source_rule_code = _string(raw_rule.get("code")) or f"import-rule-{index}"
        base_code = _build_portal_code(source_rule_code, index)
        portal_code = generate_available_rule_code(base_code, reserved_codes)
        reserved_codes.add(portal_code)
        if portal_code != base_code:
            rule_warnings.append(f"Code portale riallineato per evitare collisioni: `{portal_code}`.")

        rule_name = _string(raw_rule.get("name")) or source_rule_code or f"Regola importata {index}"
        rule_source_code = _string(raw_rule.get("source_code")) or source_code
        if source_code and rule_source_code and rule_source_code != source_code:
            rule_errors.append(
                f"source_code regola `{rule_source_code}` diverso dalla sorgente package `{source_code}`."
            )

        operation_type = _string(raw_rule.get("operation_type")).lower()
        if operation_type not in SUPPORTED_OPERATIONS:
            rule_errors.append(f"operation_type non supportato: `{operation_type or '<vuoto>'}`.")

        trigger_scope = _string(raw_rule.get("trigger_scope")).lower()
        if trigger_scope not in SUPPORTED_TRIGGER_SCOPES:
            rule_errors.append(f"trigger_scope non supportato: `{trigger_scope or '<vuoto>'}`.")

        watched_field_raw = _string(
            raw_rule.get("watched_field")
            or raw_rule.get("watchedField")
            or raw_rule.get("trigger_field")
        )
        watched_field = _resolve_source_field_name(watched_field_raw, alias_map) if watched_field_raw else ""
        if watched_field_raw and not watched_field:
            rule_errors.append(f"watched_field non risolto sulla sorgente portale: `{watched_field_raw}`.")
        elif watched_field_raw and watched_field and watched_field != watched_field_raw:
            rule_warnings.append(f"watched_field mappato da `{watched_field_raw}` a `{watched_field}`.")

        requested_is_active = _bool(raw_rule.get("is_active"))
        requested_is_draft = raw_rule.get("is_draft")
        requested_is_draft_bool = True if requested_is_draft in {None, ""} else _bool(requested_is_draft)
        if requested_is_active or not requested_is_draft_bool:
            rule_warnings.append("La regola verra' importata sempre come draft disattiva.")

        normalized_conditions: list[dict[str, Any]] = []
        for condition_index, raw_condition in enumerate(raw_rule.get("conditions") or [], start=1):
            if not isinstance(raw_condition, dict):
                normalized_conditions.append(
                    {
                        "order": condition_index,
                        "field_name": "",
                        "source_field_name": "",
                        "operator": "",
                        "expected_value": "",
                        "value_type": AutomationConditionValueType.STRING,
                        "compare_with_old": False,
                        "is_enabled": True,
                        "errors": ["Condizione non valida: deve essere un oggetto JSON."],
                        "warnings": [],
                    }
                )
                continue

            source_field_name = _string(
                raw_condition.get("field_name")
                or raw_condition.get("field")
                or raw_condition.get("source_field")
            )
            field_name = _resolve_source_field_name(source_field_name, alias_map)
            condition_errors: list[str] = []
            condition_warnings: list[str] = []
            operator = _string(raw_condition.get("operator")).lower()
            value_type = _string(raw_condition.get("value_type")).lower() or AutomationConditionValueType.STRING
            if operator not in SUPPORTED_CONDITION_OPERATORS:
                condition_errors.append(f"Operatore non supportato: `{operator or '<vuoto>'}`.")
            if value_type not in SUPPORTED_CONDITION_VALUE_TYPES:
                condition_errors.append(f"value_type non supportato: `{value_type or '<vuoto>'}`.")
            if source_field_name and not field_name:
                condition_errors.append(f"Campo condizione non risolto sulla sorgente portale: `{source_field_name}`.")
            elif source_field_name and field_name != source_field_name:
                condition_warnings.append(f"Campo condizione mappato da `{source_field_name}` a `{field_name}`.")

            normalized_conditions.append(
                {
                    "order": int(raw_condition.get("order") or condition_index),
                    "source_field_name": source_field_name,
                    "field_name": field_name,
                    "operator": operator,
                    "expected_value": _serialize_text(
                        raw_condition.get("expected_value", raw_condition.get("value", raw_condition.get("expected", "")))
                    ),
                    "value_type": value_type,
                    "compare_with_old": _bool(raw_condition.get("compare_with_old")),
                    "is_enabled": True if raw_condition.get("is_enabled") in {None, ""} else _bool(raw_condition.get("is_enabled")),
                    "errors": condition_errors,
                    "warnings": condition_warnings,
                }
            )

        normalized_actions: list[dict[str, Any]] = []
        for action_index, raw_action in enumerate(raw_rule.get("actions") or [], start=1):
            if not isinstance(raw_action, dict):
                normalized_actions.append(
                    {
                        "order": action_index,
                        "action_type": "",
                        "description": "",
                        "config_json": {},
                        "is_enabled": True,
                        "supported": False,
                        "errors": ["Action non valida: deve essere un oggetto JSON."],
                        "warnings": [],
                    }
                )
                continue

            action_type = _string(raw_action.get("action_type") or raw_action.get("type")).lower()
            action_config = _translate_placeholders(_normalize_action_config(raw_action, action_type), alias_map)
            action_plan = {
                "order": int(raw_action.get("order") or action_index),
                "action_type": action_type,
                "description": _string(raw_action.get("description") or raw_action.get("name") or action_type),
                "config_json": action_config,
                "is_enabled": True if raw_action.get("is_enabled") in {None, ""} else _bool(raw_action.get("is_enabled")),
            }
            action_errors, action_warnings = _validate_action_structure(action_plan, source_code=source_code)
            action_plan.update(
                {
                    "supported": action_type in SUPPORTED_ACTION_TYPES,
                    "errors": action_errors,
                    "warnings": action_warnings,
                }
            )
            normalized_actions.append(action_plan)

        if not normalized_actions:
            rule_errors.append("La regola non contiene action importabili.")

        if source_definition is not None:
            preview_rule = AutomationRule(
                code=portal_code,
                name=rule_name,
                description=_string(raw_rule.get("description")),
                source_code=source_code,
                import_flow_name=flow_name,
                import_source_rule_code=source_rule_code,
                import_source_package_version=package_version,
                operation_type=operation_type,
                watched_field=watched_field or None,
                trigger_scope=trigger_scope,
                is_active=False,
                is_draft=True,
                stop_on_first_failure=_bool(raw_rule.get("stop_on_first_failure")),
            )
            try:
                preview_rule.full_clean(validate_unique=False)
            except ValidationError as exc:
                if hasattr(exc, "message_dict"):
                    for field_errors in exc.message_dict.values():
                        rule_errors.extend(field_errors)
                else:
                    rule_errors.extend(exc.messages)

        for condition in normalized_conditions:
            rule_errors.extend(condition["errors"])
            rule_warnings.extend(condition["warnings"])
        for action in normalized_actions:
            rule_errors.extend(action["errors"])
            rule_warnings.extend(action["warnings"])

        is_importable = not rule_errors
        if is_importable:
            importable_rule_count += 1

        analyzed_rules.append(
            {
                "index": index,
                "name": rule_name,
                "source_rule_code": source_rule_code,
                "portal_code": portal_code,
                "description": _string(raw_rule.get("description")),
                "source_code": source_code,
                "operation_type": operation_type,
                "trigger_scope": trigger_scope,
                "watched_field": watched_field,
                "requested_is_active": requested_is_active,
                "requested_is_draft": requested_is_draft_bool,
                "final_is_active": False,
                "final_is_draft": True,
                "stop_on_first_failure": _bool(raw_rule.get("stop_on_first_failure")),
                "conditions": normalized_conditions,
                "actions": normalized_actions,
                "errors": rule_errors,
                "warnings": rule_warnings,
                "import_decision": "import" if is_importable else "skip",
                "is_importable": is_importable,
            }
        )

    skipped_rule_count = len(analyzed_rules) - importable_rule_count
    if importable_rule_count == 0:
        status = "blocked"
    elif skipped_rule_count or package_warnings:
        status = "partial"
    else:
        status = "ready"

    if package_errors:
        status = "blocked"

    return {
        "package_hash": _package_hash(package_data),
        "filename": filename,
        "flow_name": flow_name,
        "package_version": package_version,
        "source_code": source_code,
        "source_candidate": source_candidate,
        "source_supported": source_definition is not None,
        "compatibility_lines": _summarize_value(compatibility),
        "compatibility_pretty": _pretty_json(compatibility),
        "issues_lines": _summarize_value(issues),
        "issues_pretty": _pretty_json(issues),
        "target_context_pretty": _pretty_json(target_context),
        "target_context": deepcopy(target_context),
        "mapping_source": mapping_source,
        "mapping_rows": mapping_rows,
        "status": status,
        "status_label": IMPORT_STATUS_LABELS[status],
        "warnings": package_warnings,
        "errors": package_errors,
        "rules": analyzed_rules,
        "rule_count": len(analyzed_rules),
        "importable_rule_count": importable_rule_count,
        "skipped_rule_count": skipped_rule_count,
    }


def run_package_dry_run(
    analysis: dict[str, Any],
    *,
    payload: dict[str, Any],
    old_payload: dict[str, Any] | None = None,
    sample_label: str,
) -> dict[str, Any]:
    if analysis.get("status") == "blocked":
        raise PackageImportError("Il package e' bloccato e non puo' essere testato.")

    normalized_payload = deepcopy(payload)
    normalized_old_payload = deepcopy(old_payload) if old_payload is not None else None
    rule_results: list[dict[str, Any]] = []
    has_errors = False

    for rule_plan in analysis.get("rules", []):
        if not rule_plan.get("is_importable"):
            rule_results.append(
                {
                    "name": rule_plan.get("name"),
                    "portal_code": rule_plan.get("portal_code"),
                    "status": "skipped",
                    "is_valid": False,
                    "fields_exist": False,
                    "actions_supported": False,
                    "would_execute": False,
                    "messages": list(rule_plan.get("errors") or []),
                    "condition_results": [],
                    "action_results": [],
                    "missing_payload_placeholders": [],
                }
            )
            has_errors = True
            continue

        condition_results: list[dict[str, Any]] = []
        condition_match = True
        for condition_plan in rule_plan.get("conditions", []):
            if not condition_plan.get("is_enabled", True):
                continue
            condition_obj = SimpleNamespace(
                field_name=condition_plan.get("field_name"),
                operator=condition_plan.get("operator"),
                expected_value=condition_plan.get("expected_value"),
                value_type=condition_plan.get("value_type"),
                compare_with_old=condition_plan.get("compare_with_old"),
            )
            matched = evaluate_condition(condition_obj, normalized_payload, old_payload=normalized_old_payload)
            condition_results.append(
                {
                    "order": condition_plan.get("order"),
                    "field_name": condition_plan.get("field_name"),
                    "operator": condition_plan.get("operator"),
                    "matched": matched,
                }
            )
            if not matched:
                condition_match = False

        action_results: list[dict[str, Any]] = []
        missing_payload_placeholders: set[str] = set()
        simulation_errors: list[str] = []
        action_supported = True
        for action_plan in rule_plan.get("actions", []):
            if not action_plan.get("is_enabled", True):
                continue
            simulation = _simulate_action(action_plan, payload=normalized_payload)
            action_results.append(
                {
                    "order": action_plan.get("order"),
                    "action_type": action_plan.get("action_type"),
                    "status": simulation["status"],
                    "preview": simulation["preview"],
                    "errors": simulation["errors"],
                    "missing_payload_placeholders": simulation["missing_payload_placeholders"],
                }
            )
            missing_payload_placeholders.update(simulation["missing_payload_placeholders"])
            simulation_errors.extend(simulation["errors"])
            if simulation["status"] == "error":
                action_supported = False

        fields_exist = not any(
            "sorgente portale" in error.lower() or "placeholder non presenti" in error.lower()
            for error in rule_plan.get("errors", [])
        )
        rule_messages = [*rule_plan.get("warnings", []), *simulation_errors]
        is_valid = not simulation_errors and not missing_payload_placeholders and not rule_plan.get("errors")
        if missing_payload_placeholders:
            rule_messages.append(
                "Placeholder mancanti nel payload di test: "
                + ", ".join(f"{{{item}}}" for item in sorted(missing_payload_placeholders))
                + "."
            )

        rule_status = "ok" if is_valid else "error"
        if rule_status == "error":
            has_errors = True

        rule_results.append(
            {
                "name": rule_plan.get("name"),
                "portal_code": rule_plan.get("portal_code"),
                "status": rule_status,
                "is_valid": is_valid,
                "fields_exist": fields_exist,
                "actions_supported": action_supported,
                "would_execute": condition_match and action_supported and is_valid,
                "messages": rule_messages,
                "condition_results": condition_results,
                "action_results": action_results,
                "missing_payload_placeholders": sorted(missing_payload_placeholders),
            }
        )

    return {
        "status": "error" if has_errors else "ok",
        "sample_label": sample_label,
        "payload_pretty": _pretty_json(normalized_payload),
        "old_payload_pretty": _pretty_json(normalized_old_payload),
        "rules": rule_results,
    }


def _create_imported_rule(
    rule_plan: dict[str, Any],
    *,
    flow_name: str,
    package_version: str,
    created_by: Any,
    final_code: str,
) -> AutomationRule:
    rule = AutomationRule.objects.create(
        code=final_code,
        name=rule_plan["name"],
        description=rule_plan.get("description", ""),
        source_code=rule_plan["source_code"],
        import_flow_name=flow_name,
        import_source_rule_code=rule_plan["source_rule_code"],
        import_source_package_version=package_version,
        operation_type=rule_plan["operation_type"],
        watched_field=rule_plan["watched_field"] or None,
        trigger_scope=rule_plan["trigger_scope"],
        is_active=False,
        is_draft=True,
        stop_on_first_failure=bool(rule_plan.get("stop_on_first_failure")),
        created_by=created_by,
        updated_by=created_by,
    )

    for condition_plan in rule_plan.get("conditions", []):
        AutomationCondition.objects.create(
            rule=rule,
            order=int(condition_plan.get("order") or 0),
            field_name=condition_plan.get("field_name") or "",
            operator=condition_plan.get("operator") or AutomationConditionOperator.EQUALS,
            expected_value=condition_plan.get("expected_value") or "",
            value_type=condition_plan.get("value_type") or AutomationConditionValueType.STRING,
            compare_with_old=bool(condition_plan.get("compare_with_old")),
            is_enabled=bool(condition_plan.get("is_enabled", True)),
        )

    for action_plan in rule_plan.get("actions", []):
        AutomationAction.objects.create(
            rule=rule,
            order=int(action_plan.get("order") or 0),
            action_type=action_plan.get("action_type") or AutomationActionType.WRITE_LOG,
            is_enabled=bool(action_plan.get("is_enabled", True)),
            description=action_plan.get("description") or "",
            config_json=deepcopy(action_plan.get("config_json") or {}),
        )

    return rule


def import_analyzed_package(analysis: dict[str, Any], *, created_by: Any) -> dict[str, Any]:
    if analysis.get("status") == "blocked":
        raise PackageImportError("Il package e' bloccato e non puo' essere importato.")

    importable_rules = [rule for rule in analysis.get("rules", []) if rule.get("is_importable")]
    if not importable_rules:
        raise PackageImportError("Il package non contiene regole importabili.")

    skipped_rules = [
        {
            "name": rule.get("name"),
            "portal_code": rule.get("portal_code"),
            "reasons": list(rule.get("errors") or []),
        }
        for rule in analysis.get("rules", [])
        if not rule.get("is_importable")
    ]

    created_rules: list[dict[str, Any]] = []
    reserved_codes: set[str] = set()
    with transaction.atomic():
        for rule_plan in importable_rules:
            final_code = generate_available_rule_code(rule_plan["portal_code"], reserved_codes)
            reserved_codes.add(final_code)
            created_rule = _create_imported_rule(
                rule_plan,
                flow_name=analysis.get("flow_name") or "",
                package_version=analysis.get("package_version") or "",
                created_by=created_by,
                final_code=final_code,
            )
            created_rules.append(
                {
                    "id": created_rule.id,
                    "name": created_rule.name,
                    "code": created_rule.code,
                    "warnings": list(rule_plan.get("warnings") or []),
                }
            )

    status = "ready" if not skipped_rules else "partial"
    return {
        "status": status,
        "status_label": IMPORT_STATUS_LABELS[status],
        "flow_name": analysis.get("flow_name"),
        "package_version": analysis.get("package_version"),
        "created_rules": created_rules,
        "created_rule_count": len(created_rules),
        "skipped_rules": skipped_rules,
        "warnings": list(analysis.get("warnings") or []),
        "source_code": analysis.get("source_code"),
    }
