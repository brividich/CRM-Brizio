from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.db.models import Count
from django.db import connection, transaction
from django.db.utils import OperationalError as DjangoOperationalError, ProgrammingError as DjangoProgrammingError
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from admin_portale.decorators import legacy_admin_required
from core.audit import log_action
from monitoring.models import AutomationJob, AutomationExecution
from monitoring.services import detect_missed_jobs, detect_stuck_jobs

from .forms import (
    ApprovalEmailTemplateForm,
    AutomationDeliveryEndpointForm,
    AutomationActionFormSet,
    AutomationConditionFormSet,
    AutomationPackageDryRunForm,
    AutomationPackageUploadForm,
    AutomationRuleForm,
    AutomationRuleTestForm,
    PowerAutomateFlowUploadForm,
    TeamsWebhookPresetForm,
    _safe_json_array_length,
)
from .models import (
    ApprovalEmailTemplate,
    ApprovalEmailTemplateDeliveryMode,
    APPROVAL_EMAIL_TEMPLATE_UNAVAILABLE_MESSAGE,
    AutomationAction,
    AutomationActionLog,
    AutomationActionType,
    AutomationCondition,
    AutomationConditionOperator,
    AutomationConditionValueType,
    AUTOMATION_DELIVERY_ENDPOINT_UNAVAILABLE_MESSAGE,
    AutomationRule,
    AutomationRuleOperationType,
    AutomationRuleTriggerScope,
    AutomationRunLog,
    AutomationRunLogStatus,
    AutomationDeliveryEndpoint,
    AutomationDeliveryEndpointType,
    AutomationTableConfig,
    TeamsWebhookPreset,
    list_teams_flow_endpoints,
    list_approval_email_templates,
)
from .approval_mailbox_runtime import (
    get_approval_graph_form_defaults,
    get_approval_graph_status,
    get_approval_imap_form_defaults,
    get_approval_imap_status,
    get_approval_mailbox_backend,
    get_default_approval_mailbox_details,
    run_approval_poll_now,
    run_approval_imap_poll_now,
    save_approval_graph_settings,
    save_approval_imap_settings,
    MAILBOX_BACKEND_GRAPH,
    MAILBOX_BACKEND_IMAP,
)
from .services import (
    count_queue_by_status,
    discover_module_tables,
    get_action_table_whitelist,
    get_queue_event_detail,
    list_queue_events,
    process_approval_decision,
    delete_queue_event,
    process_single_queue_event_by_id,
    reset_queue_event_to_pending,
    run_rule,
    stop_queue_event,
)
from .package_importer import (
    PackageImportError,
    analyze_package_dict,
    analyze_package_bytes,
    build_example_payload,
    build_example_payload_json,
    create_rule_draft_from_analysis,
    import_analyzed_package,
    list_recent_source_records,
    load_source_record_payload,
    run_package_dry_run,
)
from .power_automate_bridge import (
    analyze_power_automate_flow_upload,
    apply_power_automate_recommended_remediation,
)
from .source_registry import (
    AUTOMAZIONI_ACL_ACTIONS,
    AUTOMAZIONI_MODULE_CODE,
    build_placeholder_examples,
    get_action_mapping_fields,
    get_condition_fields,
    get_registered_sources,
    get_source_definition,
    get_source_fields,
    get_template_fields,
    get_trigger_fields,
)


QUEUE_STATUS_CHOICES = ("pending", "processing", "done", "error")
QUEUE_OPERATION_CHOICES = ("insert", "update")
RULE_BOOLEAN_FILTER_CHOICES = (("true", "Si"), ("false", "No"))
SAMPLE_VALUE_BY_TYPE = {
    "int": 101,
    "float": 1.5,
    "bool": True,
    "date": "2026-03-11",
    "datetime": "2026-03-11T09:00:00",
    "string": "esempio",
}
FIELD_DISTINCT_VALUES_LIMIT = 24
PACKAGE_IMPORT_SESSION_KEY = "automazioni_package_import_state"
PACKAGE_IMPORT_RESULT_SESSION_KEY = "automazioni_package_import_result"
POWER_AUTOMATE_CONVERTER_SESSION_KEY = "automazioni_power_automate_converter_state"
QUEUE_POLLER_JOB_CODE = "automazioni_process_queue"
QUEUE_POLLER_TASK_NAME = "Portale Hub Polling Mail"
QUEUE_POLLER_LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "automation_queue.log"


def _base_context() -> dict[str, object]:
    return {
        "automazioni_module_code": AUTOMAZIONI_MODULE_CODE,
        "acl_action_contract": AUTOMAZIONI_ACL_ACTIONS,
    }


def _get_filter_value(request, key: str) -> str:
    return str(request.GET.get(key) or "").strip()


def _get_default_source_code() -> str:
    sources = get_registered_sources()
    if not sources:
        return ""
    return str(sources[0]["code"])


def _json_pretty(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, dict):
        return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
    try:
        parsed = json.loads(value)
        return json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError, json.JSONDecodeError):
        return str(value)


def _string_value(value) -> str:
    return str(value or "").strip()


def _bool_value(value) -> bool:
    if isinstance(value, bool):
        return value
    return _string_value(value).lower() in {"1", "true", "on", "yes"}


def _get_package_import_state(request) -> dict[str, object]:
    state = request.session.get(PACKAGE_IMPORT_SESSION_KEY)
    return state if isinstance(state, dict) else {}


def _set_package_import_state(request, state: dict[str, object]) -> None:
    request.session[PACKAGE_IMPORT_SESSION_KEY] = state
    request.session.modified = True


def _clear_package_import_state(request) -> None:
    if PACKAGE_IMPORT_SESSION_KEY in request.session:
        del request.session[PACKAGE_IMPORT_SESSION_KEY]
        request.session.modified = True


def _set_package_import_result(request, result: dict[str, object]) -> None:
    request.session[PACKAGE_IMPORT_RESULT_SESSION_KEY] = result
    request.session.modified = True


def _pop_package_import_result(request) -> dict[str, object] | None:
    result = request.session.pop(PACKAGE_IMPORT_RESULT_SESSION_KEY, None)
    if result is not None:
        request.session.modified = True
    return result if isinstance(result, dict) else None


def _get_power_automate_converter_state(request) -> dict[str, object]:
    state = request.session.get(POWER_AUTOMATE_CONVERTER_SESSION_KEY)
    return state if isinstance(state, dict) else {}


def _set_power_automate_converter_state(request, state: dict[str, object]) -> None:
    request.session[POWER_AUTOMATE_CONVERTER_SESSION_KEY] = state
    request.session.modified = True


def _clear_power_automate_converter_state(request) -> None:
    if POWER_AUTOMATE_CONVERTER_SESSION_KEY in request.session:
        del request.session[POWER_AUTOMATE_CONVERTER_SESSION_KEY]
        request.session.modified = True


def _build_power_automate_target_table_choices() -> list[tuple[str, str]]:
    catalog = discover_module_tables()
    return [(table_name, str(meta.get("label") or table_name)) for table_name, meta in catalog.items()]


def _build_power_automate_approval_template_state() -> dict[str, object]:
    templates, templates_unavailable = list_approval_email_templates(enabled_only=True)
    template_choices: list[tuple[str, str]] = []
    templates_by_code: dict[str, dict[str, str]] = {}
    default_template_code = ""
    fallback_template_code = ""

    for template in templates:
        code = _string_value(getattr(template, "code", ""))
        delivery_mode = _string_value(getattr(template, "delivery_mode", ""))
        if not code:
            continue
        template_choices.append(
            (
                code,
                f"{template.name} [{template.get_delivery_mode_display()}]" if delivery_mode else template.name,
            )
        )
        templates_by_code[code] = {
            "code": code,
            "name": _string_value(getattr(template, "name", "")),
            "delivery_mode": delivery_mode,
        }
        if not default_template_code and delivery_mode == ApprovalEmailTemplateDeliveryMode.HYBRID:
            default_template_code = code
        if not fallback_template_code and delivery_mode == ApprovalEmailTemplateDeliveryMode.MAIL_REPLY:
            fallback_template_code = code

    warning_message = ""
    if templates_unavailable:
        warning_message = APPROVAL_EMAIL_TEMPLATE_UNAVAILABLE_MESSAGE
    elif not default_template_code and not fallback_template_code:
        warning_message = (
            "Nessun template approval attivo con delivery_mode `hybrid` o `mail_reply`: "
            "i flow con approval verranno analizzati ma non potranno generare `send_approval`."
        )

    return {
        "choices": template_choices,
        "templates_by_code": templates_by_code,
        "default_code": default_template_code or fallback_template_code,
        "warning_message": warning_message,
    }


def _build_power_automate_upload_form(
    *args,
    approval_template_state: dict[str, object] | None = None,
    **kwargs,
) -> PowerAutomateFlowUploadForm:
    approval_state = approval_template_state or _build_power_automate_approval_template_state()
    return PowerAutomateFlowUploadForm(
        *args,
        target_table_choices=_build_power_automate_target_table_choices(),
        approval_template_choices=list(approval_state.get("choices") or []),
        default_approval_template_code=_string_value(approval_state.get("default_code")),
        approval_template_warning=_string_value(approval_state.get("warning_message")),
        **kwargs,
    )


def _build_power_automate_target_context(table_name: str) -> dict[str, object] | None:
    normalized_table = _string_value(table_name)
    if not normalized_table:
        return None

    table_catalog = discover_module_tables()
    table_meta = table_catalog.get(normalized_table)
    if not table_meta:
        return None

    all_fields = list(table_meta.get("all_fields") or table_meta.get("fields") or [])
    if "." in normalized_table:
        schema_name, short_table_name = normalized_table.split(".", 1)
        full_name = normalized_table
    else:
        schema_name = ""
        short_table_name = normalized_table
        full_name = normalized_table

    return {
        "db_type": connection.vendor,
        "server": "",
        "database": str(connection.settings_dict.get("NAME") or ""),
        "schema": schema_name,
        "table": short_table_name,
        "full_name": full_name,
        "columns": [
            {
                "name": field_name,
                "data_type": "",
                "is_nullable": True,
                "ordinal_position": index,
                "is_primary_key": False,
            }
            for index, field_name in enumerate(all_fields, start=1)
        ],
    }


def _power_automate_package_filename(record: dict[str, object], *, fallback_name: str = "power-automate") -> str:
    package = record.get("package") if isinstance(record, dict) else {}
    package = package if isinstance(package, dict) else {}
    input_meta = package.get("input") if isinstance(package.get("input"), dict) else {}
    input_meta = input_meta if isinstance(input_meta, dict) else {}
    base_name = _string_value(input_meta.get("flow_slug")) or slugify(_string_value(input_meta.get("flow_name")))
    base_name = base_name or slugify(fallback_name) or "power-automate"
    return f"{base_name}.automation_package.json"


def _prepare_power_automate_diagram(converter_record: dict[str, object] | None) -> dict[str, object]:
    if not converter_record:
        return {}
    normalized = converter_record.get("normalized")
    if not isinstance(normalized, dict):
        return {}
    raw_diagram = normalized.get("diagram")
    if not isinstance(raw_diagram, dict):
        return {}

    diagram = json.loads(json.dumps(raw_diagram))
    for node in diagram.get("nodes", []):
        width = int(node.get("width") or 0)
        height = int(node.get("height") or 0)
        node["icon_y"] = (height // 2) + 4
        node["issue_rect_x"] = width - 54
        node["issue_rect_y"] = height - 24
        node["issue_text_x"] = width - 30
        node["issue_text_y"] = height - 12
    return diagram


def _build_package_record_choices(source_code: str | None) -> list[tuple[str, str]]:
    return [(str(record["id"]), str(record["label"])) for record in list_recent_source_records(source_code)]


def _build_package_dry_run_form(
    analysis: dict[str, object] | None,
    *args,
    **kwargs,
) -> AutomationPackageDryRunForm | None:
    if not analysis:
        return None
    source_code = str(analysis.get("source_code") or "").strip()
    if "initial" not in kwargs:
        kwargs["initial"] = {
            "sample_mode": "example",
            "payload_json": build_example_payload_json(source_code),
            "old_payload_json": "",
        }
    return AutomationPackageDryRunForm(
        *args,
        record_choices=_build_package_record_choices(source_code),
        **kwargs,
    )


def _build_dry_run_activation_state(dry_run_result: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(dry_run_result, dict):
        return {}

    serialized_rules: list[dict[str, object]] = []
    for rule_result in dry_run_result.get("rules") or []:
        if not isinstance(rule_result, dict):
            continue
        serialized_rules.append(
            {
                "portal_code": _string_value(rule_result.get("portal_code")),
                "status": _string_value(rule_result.get("status")),
                "is_valid": bool(rule_result.get("is_valid")),
                "fields_exist": bool(rule_result.get("fields_exist")),
                "actions_supported": bool(rule_result.get("actions_supported")),
            }
        )

    return {
        "status": _string_value(dry_run_result.get("status")),
        "rules": serialized_rules,
    }


def _dry_run_allows_activation(
    analysis: dict[str, object] | None,
    dry_run_activation_state: dict[str, object] | None,
) -> bool:
    if not isinstance(analysis, dict) or not isinstance(dry_run_activation_state, dict):
        return False

    importable_codes = {
        _string_value(rule.get("portal_code"))
        for rule in analysis.get("rules") or []
        if isinstance(rule, dict) and rule.get("is_importable")
    }
    importable_codes.discard("")
    if not importable_codes:
        return False

    matching_rules = [
        rule
        for rule in dry_run_activation_state.get("rules") or []
        if isinstance(rule, dict) and _string_value(rule.get("portal_code")) in importable_codes
    ]
    if not matching_rules:
        return False

    for rule in matching_rules:
        if _string_value(rule.get("status")) == "skipped":
            return False
        if not bool(rule.get("is_valid")):
            return False
        if not bool(rule.get("fields_exist")):
            return False
        if not bool(rule.get("actions_supported")):
            return False
    return True


def _truncate_text(value, limit: int = 120) -> str:
    text = _string_value(value)
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}..."


def _quote_table_reference(table_name: str | None) -> str:
    normalized = _string_value(table_name)
    if not normalized:
        return ""
    return ".".join(connection.ops.quote_name(part) for part in normalized.split(".") if part)


def _get_source_field_definition(source_code: str | None, field_name: str | None) -> dict[str, object] | None:
    normalized_field = _string_value(field_name)
    if not normalized_field:
        return None
    for field in get_source_fields(source_code):
        if _string_value(field.get("name")) == normalized_field:
            return field
    return None


def _fetch_source_field_distinct_values(
    source_code: str | None,
    field_name: str | None,
    *,
    limit: int = FIELD_DISTINCT_VALUES_LIMIT,
) -> dict[str, object]:
    source_definition = get_source_definition(source_code)
    field_definition = _get_source_field_definition(source_code, field_name)
    if not source_definition or not field_definition:
        return {
            "queryable": False,
            "values": [],
            "message": "Campo non registrato per la sorgente selezionata.",
        }

    table_name = _string_value(source_definition.get("table_name"))
    db_column = _string_value(field_definition.get("db_column"))
    if not table_name or not db_column or bool(field_definition.get("is_virtual")):
        return {
            "queryable": False,
            "values": [],
            "message": "Questo campo non e' collegato direttamente a una colonna interrogabile.",
        }

    safe_limit = max(1, min(int(limit or FIELD_DISTINCT_VALUES_LIMIT), 50))
    fetch_limit = safe_limit * 3
    quoted_table = _quote_table_reference(table_name)
    quoted_column = connection.ops.quote_name(db_column)
    if not quoted_table or not quoted_column:
        return {
            "queryable": False,
            "values": [],
            "message": "Impossibile determinare la colonna sorgente per il lookup valori.",
        }

    if str(connection.vendor or "").lower() in {"mssql", "microsoft", "sql_server"}:
        sql = (
            f"SELECT DISTINCT TOP {fetch_limit} {quoted_column} AS value "
            f"FROM {quoted_table} "
            f"WHERE {quoted_column} IS NOT NULL "
            f"ORDER BY {quoted_column}"
        )
        params: tuple[object, ...] = ()
    else:
        sql = (
            f"SELECT DISTINCT {quoted_column} AS value "
            f"FROM {quoted_table} "
            f"WHERE {quoted_column} IS NOT NULL "
            f"ORDER BY {quoted_column} "
            f"LIMIT %s"
        )
        params = (fetch_limit,)

    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    except (DjangoOperationalError, DjangoProgrammingError):
        return {
            "queryable": False,
            "values": [],
            "message": "Lookup valori non disponibile sul database corrente per questo campo.",
        }

    values: list[str] = []
    seen: set[str] = set()
    for row in rows:
        raw_value = row[0] if row else None
        text_value = _string_value(raw_value)
        if not text_value or text_value in seen:
            continue
        seen.add(text_value)
        values.append(text_value)
        if len(values) >= safe_limit:
            break

    return {
        "queryable": True,
        "values": values,
        "message": "" if values else "Nessun valore distinto trovato nella colonna selezionata.",
    }


def _choice_label(choice_enum, value: str) -> str:
    normalized = _string_value(value)
    if not normalized:
        return "-"
    try:
        return str(choice_enum(normalized).label)
    except ValueError:
        return normalized


def _field_label_map(source_code: str | None) -> dict[str, str]:
    return {
        _string_value(field.get("name")): _string_value(field.get("label")) or _string_value(field.get("name"))
        for field in get_source_fields(source_code)
    }


def _bound_or_instance_value(form, field_name: str, *, default=""):
    field = form.fields.get(field_name)
    if field is not None:
        value = form[field_name].value()
        if value not in (None, ""):
            return value
        if isinstance(value, bool):
            return value
    return getattr(form.instance, field_name, default)


def _build_example_payload(source_code: str | None) -> str:
    return json.dumps(
        build_example_payload(source_code),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )


def _mutate_example_value(value, data_type: str):
    normalized_type = _string_value(data_type)
    if normalized_type == "bool":
        if isinstance(value, bool):
            return not value
        return False
    if normalized_type == "int":
        try:
            return int(value) + 1
        except (TypeError, ValueError):
            return 1
    if normalized_type == "float":
        try:
            return float(value) + 0.5
        except (TypeError, ValueError):
            return 1.5
    if normalized_type == "date":
        return "2026-03-10"
    if normalized_type == "datetime":
        return "2026-03-10T08:30:00"
    text = _string_value(value)
    return f"{text} (prima)" if text else "valore precedente"


def _build_example_old_payload(rule: AutomationRule | None) -> dict[str, object] | None:
    if not rule or rule.operation_type != AutomationRuleOperationType.UPDATE:
        return None

    payload = build_example_payload(rule.source_code)
    if not payload:
        return None

    field_map = {
        _string_value(field.get("name")): field
        for field in get_source_fields(rule.source_code)
    }
    candidate_fields = [
        _string_value(rule.watched_field),
        _pick_source_field(rule.source_code, ["moderation_status", "status", "stato"], fallback_index=None),
        _pick_source_field(rule.source_code, ["assigned_to_id", "assegnato_a", "priorita", "priority"], fallback_index=None),
    ]
    candidate_fields = [field_name for field_name in candidate_fields if field_name]

    changed = False
    for field_name in candidate_fields:
        if field_name not in payload or field_name not in field_map:
            continue
        payload[field_name] = _mutate_example_value(payload.get(field_name), _string_value(field_map[field_name].get("data_type")))
        changed = True
        if _string_value(rule.watched_field):
            break

    if not changed:
        first_field_name = next(iter(field_map.keys()), "")
        if first_field_name and first_field_name in payload:
            payload[first_field_name] = _mutate_example_value(
                payload.get(first_field_name),
                _string_value(field_map[first_field_name].get("data_type")),
            )

    return payload


def _serialize_source_field_detail(field: dict[str, object], *, sample_value=None) -> dict[str, object]:
    field_name = _string_value(field.get("name"))
    data_type = _string_value(field.get("data_type"))
    allowed_values = [_string_value(value) for value in (field.get("allowed_values") or []) if _string_value(value)]
    return {
        "name": field_name,
        "label": _string_value(field.get("label")) or field_name,
        "full_label": f"{_string_value(field.get('label')) or field_name} ({field_name})",
        "data_type": data_type,
        "description": _string_value(field.get("description")),
        "placeholder": f"{{{field_name}}}",
        "sample_value": sample_value if sample_value is not None else SAMPLE_VALUE_BY_TYPE.get(data_type, "esempio"),
        "aliases": [str(alias) for alias in (field.get("aliases") or []) if str(alias).strip()],
        "allowed_values": allowed_values,
        "has_allowed_values": bool(allowed_values),
        "value_source_label": _string_value(field.get("value_source_label")),
        "ui_control": _string_value(field.get("ui_control")),
        "db_column": _string_value(field.get("db_column")),
        "is_virtual": bool(field.get("is_virtual")),
        "usable_in_trigger": bool(field.get("usable_in_trigger")),
        "usable_in_condition": bool(field.get("usable_in_condition")),
        "usable_in_template": bool(field.get("usable_in_template")),
        "usable_in_action_mapping": bool(field.get("usable_in_action_mapping")),
    }


def _pick_source_field(source_code: str | None, preferred_names: list[str], *, fallback_index: int | None = None) -> str:
    field_names = [_string_value(field.get("name")) for field in get_source_fields(source_code)]
    for preferred in preferred_names:
        if preferred in field_names:
            return preferred
    if fallback_index is not None and 0 <= fallback_index < len(field_names):
        return field_names[fallback_index]
    return field_names[0] if field_names else "id"


def _build_action_suggestions(source_code: str | None) -> dict[str, dict[str, object]]:
    source = get_source_definition(source_code) or {"code": source_code or "regola", "label": source_code or "Regola"}
    source_code_value = _string_value(source.get("code")) or "regola"
    source_label = _string_value(source.get("label")) or "Regola"
    status_field = _pick_source_field(source_code, ["moderation_status", "status", "stato", "avanzamento"], fallback_index=0)
    user_field = _pick_source_field(
        source_code,
        ["dipendente_id", "assigned_to_id", "richiedente_legacy_user_id", "created_by", "legacy_user_id"],
        fallback_index=0,
    )
    title_field = _pick_source_field(source_code, ["tipo_assenza", "title", "titolo", "name", "seriale"], fallback_index=0)
    source_update_fields = [
        _string_value(field.get("name"))
        for field in get_action_mapping_fields(source_code)
        if field.get("db_column") and not field.get("is_virtual")
    ]
    source_pk_field = _string_value((source.get("pk_field") if isinstance(source, dict) else "") or "id")
    source_update_field = next(
        (field_name for field_name in source_update_fields if field_name and field_name != source_pk_field),
        status_field,
    )

    insert_whitelist = get_action_table_whitelist().get(AutomationActionType.INSERT_RECORD, {})
    update_whitelist = get_action_table_whitelist().get(AutomationActionType.UPDATE_RECORD, {})
    insert_table = sorted(insert_whitelist.keys())[0] if insert_whitelist else ""
    update_table = (
        "tasks_task"
        if "tasks_task" in update_whitelist and source_code_value == "tasks"
        else (sorted(update_whitelist.keys())[0] if update_whitelist else "")
    )

    suggestions = {
        AutomationActionType.SEND_EMAIL: {
            "group_title": f"Preset suggeriti per {source_label}",
            "group_subtitle": "Base precompilata piu' modelli visuali pronti da adattare.",
            "values": {
                "description": f"Invia email automatica per {source_label.lower()}",
                "email_subject_template": f"[{source_label}] aggiornamento record #{{id}}",
                "email_body_text_template": (
                    f"Record {{id}} aggiornato.\n"
                    f"Riferimento: {{{title_field}}}\n"
                    f"Stato: {{{status_field}}}\n"
                    f"Utente: {{{user_field}}}"
                ),
                "email_body_html_template": (
                    f"<p>Record <strong>{{id}}</strong> aggiornato.</p>"
                    f"<p>{title_field}: {{{title_field}}}</p>"
                    f"<p>{status_field}: {{{status_field}}}</p>"
                ),
            },
            "placeholders": {
                "email_to": "es. ufficio@example.com",
                "email_cc": "es. responsabile@example.com",
                "email_bcc": "es. audit@example.com",
                "email_reply_to": "es. noreply@example.com",
                "email_from_email": "es. no-reply@example.local",
            },
            "presets": [
                {
                    "key": "default_email",
                    "title": "Email standard",
                    "description": "Template neutro con riferimento, stato e utente.",
                    "theme": "blue",
                    "values": {},
                    "placeholders": {},
                }
            ],
        },
        AutomationActionType.WRITE_LOG: {
            "group_title": f"Preset suggeriti per {source_label}",
            "group_subtitle": "Log leggibili in run log e audit tecnico.",
            "values": {
                "description": f"Scrive log operativo per {source_label.lower()}",
                "write_log_message_template": (
                    f"{source_label} #{{id}} elaborata: "
                    f"{title_field}={{{title_field}}}, {status_field}={{{status_field}}}"
                ),
            },
            "placeholders": {},
            "presets": [
                {
                    "key": "default_log",
                    "title": "Log standard",
                    "description": "Scrive un messaggio descrittivo con riferimento e stato.",
                    "theme": "slate",
                    "values": {},
                    "placeholders": {},
                }
            ],
        },
        AutomationActionType.UPDATE_DASHBOARD_METRIC: {
            "group_title": f"Preset suggeriti per {source_label}",
            "group_subtitle": "Metriche incrementali o di controllo operative.",
            "values": {
                "description": f"Aggiorna metrica dashboard di {source_label.lower()}",
                "metric_code": f"{source_code_value}_metric",
                "metric_operation": "increment",
                "metric_value_template": "1",
            },
            "placeholders": {},
            "presets": [
                {
                    "key": "default_metric",
                    "title": "Contatore base",
                    "description": "Incrementa una metrica generale della sorgente.",
                    "theme": "green",
                    "values": {},
                    "placeholders": {},
                }
            ],
        },
        AutomationActionType.INSERT_RECORD: {
            "group_title": f"Preset suggeriti per {source_label}",
            "group_subtitle": "Inserimenti whitelistati pronti come base di lavoro.",
            "values": {
                "description": f"Inserisce record derivato da {source_label.lower()}",
                "insert_target_table": insert_table,
                "insert_field_mappings_text": (
                    f"legacy_user_id = {{{user_field}}}\n"
                    f"tipo = automation_{source_code_value}\n"
                    f"messaggio = {source_label} #{{id}} aggiornata: {{{status_field}}}\n"
                    f"letta = 0"
                ) if insert_table == "core_notifica" else "",
            },
            "placeholders": {},
            "presets": [
                {
                    "key": "default_insert",
                    "title": "Inserimento base",
                    "description": "Crea un record derivato dalla sorgente selezionata.",
                    "theme": "amber",
                    "values": {},
                    "placeholders": {},
                }
            ],
        },
        AutomationActionType.UPDATE_RECORD: {
            "group_title": f"Preset suggeriti per {source_label}",
            "group_subtitle": "Aggiornamenti sicuri sulle tabelle whitelistate.",
            "values": {
                "description": f"Aggiorna record collegato a {source_label.lower()}",
                "update_target_table": update_table,
                "update_where_field": "id" if update_table == "tasks_task" else "legacy_user_id",
                "update_where_value_template": "{id}" if update_table == "tasks_task" else f"{{{user_field}}}",
                "update_fields_text": (
                    "status = DONE\npriority = HIGH"
                    if update_table == "tasks_task"
                    else f"messaggio = {source_label} #{{id}} aggiornata\nletta = 0"
                ),
            },
            "placeholders": {},
            "presets": [
                {
                    "key": "default_update",
                    "title": "Aggiornamento base",
                    "description": "Precompila target, where e campi modificabili.",
                    "theme": "rose",
                    "values": {},
                    "placeholders": {},
                }
            ],
        },
        AutomationActionType.UPDATE_TRIGGER_RECORD: {
            "group_title": f"Preset trigger-record per {source_label}",
            "group_subtitle": "Aggiorna direttamente il record che ha scatenato l'automazione.",
            "values": {
                "description": f"Aggiorna il record triggerante di {source_label.lower()}",
                "trigger_update_fields_text": f"{source_update_field} = {{{status_field}}}",
            },
            "placeholders": {},
            "presets": [
                {
                    "key": "default_update_trigger",
                    "title": "Aggiorna record triggerante",
                    "description": "Imposta uno o piu' campi sul record sorgente corrente.",
                    "theme": "green",
                    "values": {},
                    "placeholders": {},
                }
            ],
        },
        AutomationActionType.SPLIT_ASSENZA_GIORNALIERA: {
            "group_title": "Preset split giornaliero Assenze",
            "group_subtitle": "Crea record giornalieri derivati da richieste Assenze multi-giorno.",
            "values": {
                "description": "Crea righe giornaliere Assenze derivate",
                "split_start_field": "data_inizio",
                "split_end_field": "data_fine",
                "split_days_count_fields": "giorni_permesso,giornipermesso,Giornipermesso,giorni",
                "split_max_days": "60",
                "split_tipo_assenza_template": "Permesso",
                "split_moderation_status": "0",
                "split_consenso_template": "Approvato",
                "split_salta_approvazione": True,
                "split_dedupe": True,
            },
            "placeholders": {},
            "presets": [
                {
                    "key": "assenze_split_daily",
                    "title": "Split giornaliero",
                    "description": "Replica il loop addDays del flow storico sulle assenze multi-giorno.",
                    "theme": "blue",
                    "values": {},
                    "placeholders": {},
                }
            ],
        },
        AutomationActionType.DELAY_SCHEDULE: {
            "group_title": f"Preset delay per {source_label}",
            "group_subtitle": "Rimanda l'elaborazione in stile Power Automate Delay/Delay Until.",
            "values": {
                "description": f"Rimanda una nuova esecuzione per {source_label.lower()}",
                "delay_mode": "relative",
                "delay_value_template": "1",
                "delay_unit": "days",
            },
            "placeholders": {},
            "presets": [
                {
                    "key": "default_delay_relative",
                    "title": "Delay semplice",
                    "description": "Riesegue l'evento dopo un intervallo relativo.",
                    "theme": "amber",
                    "values": {},
                    "placeholders": {},
                },
                {
                    "key": "default_delay_until",
                    "title": "Delay until",
                    "description": "Riesegue l'evento a una data/ora precisa.",
                    "theme": "blue",
                    "values": {
                        "delay_mode": "until",
                        "delay_until_template": "{updated_at}",
                    },
                    "placeholders": {},
                },
            ],
        },
        AutomationActionType.HTTP_REQUEST: {
            "group_title": f"Preset HTTP per {source_label}",
            "group_subtitle": "Webhook e chiamate API esterne stile Power Automate HTTP.",
            "values": {
                "description": f"Invia una chiamata HTTP per {source_label.lower()}",
                "http_method": "POST",
                "http_headers_text": "Content-Type = application/json",
                "http_body_template": (
                    "{\n"
                    f"  \"source\": \"{source_code_value}\",\n"
                    "  \"id\": \"{id}\",\n"
                    f"  \"status\": \"{{{status_field}}}\"\n"
                    "}"
                ),
                "http_expected_status_csv": "200,201,202,204",
            },
            "placeholders": {
                "http_url_template": "https://example.local/webhook",
            },
            "presets": [
                {
                    "key": "default_http_webhook",
                    "title": "Webhook JSON",
                    "description": "POST JSON verso un endpoint esterno.",
                    "theme": "blue",
                    "values": {},
                    "placeholders": {},
                },
                {
                    "key": "default_http_patch",
                    "title": "PATCH esterno",
                    "description": "Aggiorna una risorsa remota con status e riferimento record.",
                    "theme": "rose",
                    "values": {
                        "http_method": "PATCH",
                        "http_expected_status_csv": "200,204",
                    },
                    "placeholders": {
                        "http_url_template": "https://example.local/resource/{id}",
                    },
                },
            ],
        },
        AutomationActionType.TEAMS_WEBHOOK: {
            "group_title": f"Preset Teams per {source_label}",
            "group_subtitle": "Messaggi webhook per canali Teams o connettori compatibili.",
            "values": {
                "description": f"Invia card Teams per {source_label.lower()}",
                "teams_title_template": f"[{source_label}] record #{{id}}",
                "teams_summary_template": f"{source_label} aggiornata",
                "teams_text_template": f"{title_field}: {{{title_field}}}\n{status_field}: {{{status_field}}}",
                "teams_theme_color": "2563EB",
                "teams_facts_text": f"ID = {{id}}\nStato = {{{status_field}}}",
            },
            "placeholders": {
                "teams_webhook_url": "https://outlook.office.com/webhook/...",
            },
            "presets": [
                {
                    "key": "default_teams_card",
                    "title": "Card Teams",
                    "description": "Invia una card essenziale con facts e riepilogo.",
                    "theme": "green",
                    "values": {},
                    "placeholders": {},
                }
            ],
        },
    }

    if source_code_value == "assenze":
        suggestions[AutomationActionType.SEND_EMAIL]["group_title"] = "Preset email per Assenze"
        suggestions[AutomationActionType.SEND_EMAIL]["group_subtitle"] = "Messaggi pronti per approvazione, rifiuto e avviso al responsabile."
        suggestions[AutomationActionType.SEND_EMAIL]["presets"] = [
            {
                "key": "assenze_approved_email",
                "title": "Approvazione assenza",
                "description": "Conferma all'utente che la richiesta e' stata approvata.",
                "theme": "green",
                "values": {
                    "description": "Invia conferma approvazione assenza",
                    "email_subject_template": "[Assenze] richiesta #{id} approvata",
                    "email_body_text_template": (
                        "La tua richiesta di {tipo_assenza} dal {data_inizio} al {data_fine} "
                        "e' stata approvata.\nStato attuale: {moderation_status}"
                    ),
                    "email_body_html_template": (
                        "<p>La richiesta <strong>#{id}</strong> e' stata approvata.</p>"
                        "<p>Tipo: {tipo_assenza}</p>"
                        "<p>Periodo: {data_inizio} - {data_fine}</p>"
                    ),
                },
                "placeholders": {
                    "email_to": "es. email dipendente o destinatario manuale",
                },
            },
            {
                "key": "assenze_rejected_email",
                "title": "Rifiuto assenza",
                "description": "Comunica un esito negativo con tono operativo chiaro.",
                "theme": "rose",
                "values": {
                    "description": "Invia comunicazione di rifiuto assenza",
                    "email_subject_template": "[Assenze] richiesta #{id} non approvata",
                    "email_body_text_template": (
                        "La richiesta di {tipo_assenza} dal {data_inizio} al {data_fine} "
                        "non e' stata approvata.\nVerifica il workflow o contatta il responsabile."
                    ),
                    "email_body_html_template": (
                        "<p>La richiesta <strong>#{id}</strong> non e' stata approvata.</p>"
                        "<p>Tipo: {tipo_assenza}</p>"
                        "<p>Periodo: {data_inizio} - {data_fine}</p>"
                    ),
                },
                "placeholders": {
                    "email_to": "es. email dipendente o destinatario manuale",
                },
            },
            {
                "key": "assenze_manager_email",
                "title": "Avviso al responsabile",
                "description": "Segnala al capo reparto che una richiesta richiede attenzione.",
                "theme": "blue",
                "values": {
                    "description": "Invia avviso al responsabile per richiesta assenza",
                    "email_to": "{capo_email}",
                    "email_subject_template": "[Assenze] richiesta #{id} da verificare",
                    "email_body_text_template": (
                        "Richiesta assenza #{id} del dipendente {dipendente_id}.\n"
                        "Tipo: {tipo_assenza}\nPeriodo: {data_inizio} - {data_fine}\n"
                        "Capo reparto: {capo_email}"
                    ),
                    "email_body_html_template": (
                        "<p>Richiesta assenza <strong>#{id}</strong> da verificare.</p>"
                        "<p>Dipendente: {dipendente_id}</p>"
                        "<p>Tipo: {tipo_assenza}</p>"
                        "<p>Capo reparto: {capo_email}</p>"
                    ),
                },
                "placeholders": {
                    "email_to": "Usa {capo_email} o inserisci un destinatario manuale",
                    "email_cc": "es. ufficio personale@example.com",
                },
            },
        ]

        suggestions[AutomationActionType.WRITE_LOG]["group_title"] = "Preset log per Assenze"
        suggestions[AutomationActionType.WRITE_LOG]["group_subtitle"] = "Messaggi tecnici leggibili per approvazioni, rifiuti e audit."
        suggestions[AutomationActionType.WRITE_LOG]["presets"] = [
            {
                "key": "assenze_log_approved",
                "title": "Log approvazione",
                "description": "Scrive il passaggio approvato con riferimento al dipendente.",
                "theme": "green",
                "values": {
                    "description": "Log approvazione assenza",
                    "write_log_message_template": (
                        "Assenza #{id} approvata per dipendente {dipendente_id} "
                        "({tipo_assenza}) con stato {moderation_status}"
                    ),
                },
                "placeholders": {},
            },
            {
                "key": "assenze_log_rejected",
                "title": "Log rifiuto",
                "description": "Tiene traccia del rifiuto della richiesta.",
                "theme": "rose",
                "values": {
                    "description": "Log rifiuto assenza",
                    "write_log_message_template": (
                        "Assenza #{id} non approvata per dipendente {dipendente_id} "
                        "({tipo_assenza}) con stato {moderation_status}"
                    ),
                },
                "placeholders": {},
            },
            {
                "key": "assenze_log_audit",
                "title": "Audit completo",
                "description": "Log piu' verboso con date e responsabile.",
                "theme": "slate",
                "values": {
                    "description": "Audit completo richiesta assenza",
                    "write_log_message_template": (
                        "Audit assenza #{id}: dipendente={dipendente_id}, tipo={tipo_assenza}, "
                        "inizio={data_inizio}, fine={data_fine}, capo_reparto={capo_reparto_id}, "
                        "moderation_status={moderation_status}"
                    ),
                },
                "placeholders": {},
            },
        ]

        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["group_title"] = "Preset metriche per Assenze"
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["group_subtitle"] = "Contatori dedicati per esiti del workflow assenze."
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["presets"] = [
            {
                "key": "assenze_metric_approved",
                "title": "Conta approvate",
                "description": "Incrementa il contatore delle richieste approvate.",
                "theme": "green",
                "values": {
                    "description": "Incrementa contatore assenze approvate",
                    "metric_code": "assenze_approvate_oggi",
                    "metric_operation": "increment",
                    "metric_value_template": "1",
                },
                "placeholders": {},
            },
            {
                "key": "assenze_metric_rejected",
                "title": "Conta respinte",
                "description": "Incrementa il contatore delle richieste respinte.",
                "theme": "rose",
                "values": {
                    "description": "Incrementa contatore assenze respinte",
                    "metric_code": "assenze_respinte_oggi",
                    "metric_operation": "increment",
                    "metric_value_template": "1",
                },
                "placeholders": {},
            },
        ]

        suggestions[AutomationActionType.INSERT_RECORD]["group_title"] = "Preset notifiche interne per Assenze"
        suggestions[AutomationActionType.INSERT_RECORD]["group_subtitle"] = "Crea notifiche interne gia' impostate su core_notifica."
        suggestions[AutomationActionType.INSERT_RECORD]["presets"] = [
            {
                "key": "assenze_notify_employee",
                "title": "Notifica interna dipendente",
                "description": "Crea una notifica nel portale per il dipendente.",
                "theme": "blue",
                "values": {
                    "description": "Notifica interna al dipendente",
                    "insert_target_table": "core_notifica",
                    "insert_field_mappings_text": (
                        "legacy_user_id = {dipendente_id}\n"
                        "tipo = assenze_esito\n"
                        "messaggio = La richiesta #{id} ({tipo_assenza}) e' stata aggiornata con stato {moderation_status}\n"
                        "letta = 0"
                    ),
                },
                "placeholders": {},
            },
            {
                "key": "assenze_notify_manager",
                "title": "Notifica interna responsabile",
                "description": "Notifica il capo reparto della richiesta.",
                "theme": "amber",
                "values": {
                    "description": "Notifica interna al responsabile",
                    "insert_target_table": "core_notifica",
                    "insert_field_mappings_text": (
                        "legacy_user_id = {capo_reparto_id}\n"
                        "tipo = assenze_reparto\n"
                        "messaggio = Richiesta assenza #{id} del dipendente {dipendente_id}: {tipo_assenza}\n"
                        "letta = 0"
                    ),
                },
                "placeholders": {},
            },
        ]

        suggestions[AutomationActionType.UPDATE_RECORD]["group_title"] = "Preset update per Assenze"
        suggestions[AutomationActionType.UPDATE_RECORD]["group_subtitle"] = "Aggiornamenti pronti per notifiche collegate."
        suggestions[AutomationActionType.UPDATE_RECORD]["presets"] = [
            {
                "key": "assenze_update_notification_message",
                "title": "Aggiorna messaggio notifica",
                "description": "Riscrive il messaggio di una notifica legata al dipendente.",
                "theme": "slate",
                "values": {
                    "description": "Aggiorna messaggio notifica assenza",
                    "update_target_table": "core_notifica",
                    "update_where_field": "legacy_user_id",
                    "update_where_value_template": "{dipendente_id}",
                    "update_fields_text": (
                        "tipo = assenze_esito\n"
                        "messaggio = Richiesta #{id} aggiornata: {tipo_assenza} / {moderation_status}\n"
                        "letta = 0"
                    ),
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.DELAY_SCHEDULE]["group_title"] = "Preset delay per Assenze"
        suggestions[AutomationActionType.DELAY_SCHEDULE]["group_subtitle"] = "Pattern vicini ai flow Power Automate di approvazione e follow-up."
        suggestions[AutomationActionType.DELAY_SCHEDULE]["presets"] = [
            {
                "key": "assenze_delay_reminder",
                "title": "Sollecito dopo 1 giorno",
                "description": "Riesegue l'evento dopo 1 giorno per reminder o escalation.",
                "theme": "amber",
                "values": {
                    "description": "Riprogramma reminder assenza",
                    "delay_mode": "relative",
                    "delay_value_template": "1",
                    "delay_unit": "days",
                },
                "placeholders": {},
            },
            {
                "key": "assenze_delay_until",
                "title": "Attendi data fine",
                "description": "Delay until basato sulla data fine della richiesta.",
                "theme": "blue",
                "values": {
                    "description": "Riprogramma alla data fine richiesta",
                    "delay_mode": "until",
                    "delay_until_template": "{data_fine}",
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.UPDATE_TRIGGER_RECORD]["group_title"] = "Preset update record triggerante per Assenze"
        suggestions[AutomationActionType.UPDATE_TRIGGER_RECORD]["group_subtitle"] = "Aggiornamenti diretti sul record assenza corrente."
        suggestions[AutomationActionType.UPDATE_TRIGGER_RECORD]["presets"] = [
            {
                "key": "assenze_flag_skip_approval",
                "title": "Forza salta approvazione",
                "description": "Imposta il flag `salta_approvazione` sul record corrente.",
                "theme": "green",
                "values": {
                    "description": "Imposta salta approvazione sul record corrente",
                    "trigger_update_fields_text": "salta_approvazione = True",
                },
                "placeholders": {},
            },
        ]

    elif source_code_value == "tasks":
        suggestions[AutomationActionType.SEND_EMAIL]["group_title"] = "Preset email per Tasks"
        suggestions[AutomationActionType.SEND_EMAIL]["group_subtitle"] = "Notifiche pronte per assegnazioni, scadenze e completamenti."
        suggestions[AutomationActionType.SEND_EMAIL]["presets"] = [
            {
                "key": "tasks_assigned_email",
                "title": "Task assegnato",
                "description": "Avvisa l'assegnatario quando un task viene assegnato.",
                "theme": "blue",
                "values": {
                    "description": "Notifica assegnazione task",
                    "email_subject_template": "[KICK-OFF] Task #{id} assegnato a te",
                    "email_body_text_template": (
                        "Ti e' stato assegnato il task #{id}.\n"
                        "Titolo: {title}\n"
                        "Priorita': {priority}\n"
                        "Scadenza: {due_date}"
                    ),
                    "email_body_html_template": (
                        "<p>Ti e' stato assegnato il task <strong>#{id}</strong>.</p>"
                        "<p>Titolo: {title}</p>"
                        "<p>Priorita': {priority} | Scadenza: {due_date}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. responsabile@example.com"},
            },
            {
                "key": "tasks_completed_email",
                "title": "Task completato",
                "description": "Informa il responsabile del progetto quando un task passa a DONE.",
                "theme": "green",
                "values": {
                    "description": "Notifica completamento task",
                    "email_subject_template": "[KICK-OFF] Task #{id} completato",
                    "email_body_text_template": (
                        "Il task #{id} e' stato completato.\n"
                        "Titolo: {title}\n"
                        "Stato: {status}"
                    ),
                    "email_body_html_template": (
                        "<p>Il task <strong>#{id}</strong> e' stato completato.</p>"
                        "<p>Titolo: {title}</p>"
                        "<p>Stato: {status}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. pm@example.com"},
            },
            {
                "key": "tasks_overdue_email",
                "title": "Reminder scadenza",
                "description": "Reminder automatico quando la scadenza e' prossima.",
                "theme": "amber",
                "values": {
                    "description": "Reminder scadenza task",
                    "email_subject_template": "[KICK-OFF] Reminder: Task #{id} in scadenza",
                    "email_body_text_template": (
                        "Il task #{id} e' prossimo alla scadenza ({due_date}).\n"
                        "Titolo: {title}\n"
                        "Priorita': {priority}"
                    ),
                    "email_body_html_template": (
                        "<p>Il task <strong>#{id}</strong> e' prossimo alla scadenza.</p>"
                        "<p>Scadenza: {due_date}</p>"
                        "<p>Titolo: {title} | Priorita': {priority}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. assegnato@example.com"},
            },
        ]
        suggestions[AutomationActionType.INSERT_RECORD]["group_title"] = "Preset notifiche interne per Tasks"
        suggestions[AutomationActionType.INSERT_RECORD]["group_subtitle"] = "Notifiche nel portale per assegnazioni e aggiornamenti task."
        suggestions[AutomationActionType.INSERT_RECORD]["presets"] = [
            {
                "key": "tasks_notify_assigned",
                "title": "Notifica assegnazione",
                "description": "Crea una notifica interna per l'assegnatario del task.",
                "theme": "blue",
                "values": {
                    "description": "Notifica interna assegnazione task",
                    "insert_target_table": "core_notifica",
                    "insert_field_mappings_text": (
                        "legacy_user_id = {assigned_to_id}\n"
                        "tipo = tasks_assegnazione\n"
                        "messaggio = Ti e' stato assegnato il task #{id}: {title}\n"
                        "letta = 0"
                    ),
                },
                "placeholders": {},
            },
            {
                "key": "tasks_notify_status_change",
                "title": "Notifica cambio stato",
                "description": "Notifica interna quando lo stato del task cambia.",
                "theme": "green",
                "values": {
                    "description": "Notifica cambio stato task",
                    "insert_target_table": "core_notifica",
                    "insert_field_mappings_text": (
                        "legacy_user_id = {assigned_to_id}\n"
                        "tipo = tasks_aggiornamento\n"
                        "messaggio = Task #{id} aggiornato: {title} - Stato: {status}\n"
                        "letta = 0"
                    ),
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.WRITE_LOG]["group_title"] = "Preset log per Tasks"
        suggestions[AutomationActionType.WRITE_LOG]["group_subtitle"] = "Log operativi per monitoraggio stati e assegnazioni."
        suggestions[AutomationActionType.WRITE_LOG]["presets"] = [
            {
                "key": "tasks_log_status",
                "title": "Log cambio stato",
                "description": "Registra il cambio di stato del task nel log.",
                "theme": "blue",
                "values": {
                    "description": "Log cambio stato task",
                    "write_log_message_template": "Task #{id} '{title}' - stato: {status}, priorita': {priority}, assegnato: {assigned_to_id}",
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["group_title"] = "Preset metriche per Tasks"
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["group_subtitle"] = "Contatori task completati, aperti, in ritardo."
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["presets"] = [
            {
                "key": "tasks_metric_completed",
                "title": "Conta task completati",
                "description": "Incrementa il contatore dei task completati.",
                "theme": "green",
                "values": {
                    "description": "Conta task completati",
                    "metric_code": "tasks_completati_oggi",
                    "metric_operation": "increment",
                    "metric_value_template": "1",
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.UPDATE_RECORD]["group_title"] = "Preset update per Tasks"
        suggestions[AutomationActionType.UPDATE_RECORD]["group_subtitle"] = "Aggiorna record task o notifiche collegate."
        suggestions[AutomationActionType.UPDATE_RECORD]["presets"] = [
            {
                "key": "tasks_update_task_status",
                "title": "Aggiorna stato task",
                "description": "Modifica lo stato di un task su tasks_task.",
                "theme": "blue",
                "values": {
                    "description": "Aggiorna stato task",
                    "update_target_table": "tasks_task",
                    "update_where_field": "id",
                    "update_where_value_template": "{id}",
                    "update_fields_text": "status = DONE\npriority = HIGH",
                },
                "placeholders": {},
            },
        ]

    elif source_code_value == "tickets":
        suggestions[AutomationActionType.TEAMS_WEBHOOK]["group_title"] = "Preset Teams per Tickets"
        suggestions[AutomationActionType.TEAMS_WEBHOOK]["group_subtitle"] = "Avvisi rapidi per ticket critici e manutenzione."
        suggestions[AutomationActionType.TEAMS_WEBHOOK]["presets"] = [
            {
                "key": "tickets_teams_critical",
                "title": "Ticket critico a Teams",
                "description": "Invia una card Teams con numero ticket, stato e priorita'.",
                "theme": "green",
                "values": {
                    "description": "Invia ticket critico su Teams",
                    "teams_title_template": "[Ticket] {numero_ticket} - {titolo}",
                    "teams_summary_template": "Nuovo ticket da verificare",
                    "teams_text_template": "Tipo: {tipo}\nPriorita': {priorita}\nStato: {stato}\nRichiedente: {richiedente_nome}",
                    "teams_facts_text": "Ticket = {numero_ticket}\nPriorita' = {priorita}\nStato = {stato}\nAsset = {asset_id}",
                    "teams_theme_color": "DC2626",
                },
                "placeholders": {
                    "teams_webhook_url": "Webhook Teams reparto manutenzione",
                },
            },
        ]
        suggestions[AutomationActionType.SEND_EMAIL]["group_title"] = "Preset email per Tickets"
        suggestions[AutomationActionType.SEND_EMAIL]["group_subtitle"] = "Notifiche pronte per apertura, presa in carico e risoluzione ticket."
        suggestions[AutomationActionType.SEND_EMAIL]["presets"] = [
            {
                "key": "tickets_new_email",
                "title": "Nuovo ticket aperto",
                "description": "Avvisa il team quando viene aperto un nuovo ticket.",
                "theme": "blue",
                "values": {
                    "description": "Notifica apertura nuovo ticket",
                    "email_subject_template": "[Ticket] #{id} aperto: {titolo}",
                    "email_body_text_template": (
                        "E' stato aperto un nuovo ticket #{id}.\n"
                        "Titolo: {titolo}\n"
                        "Categoria: {categoria}\n"
                        "Priorita': {priorita}\n"
                        "Richiedente: {richiedente_legacy_user_id}"
                    ),
                    "email_body_html_template": (
                        "<p>Nuovo ticket <strong>#{id}</strong> aperto.</p>"
                        "<p>Titolo: {titolo}</p>"
                        "<p>Categoria: {categoria} | Priorita': {priorita}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. helpdesk@example.com"},
            },
            {
                "key": "tickets_resolved_email",
                "title": "Ticket risolto",
                "description": "Comunica al richiedente che il ticket e' stato risolto.",
                "theme": "green",
                "values": {
                    "description": "Notifica risoluzione ticket",
                    "email_subject_template": "[Ticket] #{id} risolto",
                    "email_body_text_template": (
                        "Il ticket #{id} '{titolo}' e' stato risolto.\n"
                        "Assegnato a: {assegnato_a}\n"
                        "Stato: {stato}"
                    ),
                    "email_body_html_template": (
                        "<p>Il ticket <strong>#{id}</strong> e' stato risolto.</p>"
                        "<p>Titolo: {titolo}</p>"
                        "<p>Risolto da: {assegnato_a}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. richiedente@example.com"},
            },
            {
                "key": "tickets_assigned_email",
                "title": "Ticket assegnato",
                "description": "Avvisa il tecnico assegnato di prendere in carico il ticket.",
                "theme": "amber",
                "values": {
                    "description": "Notifica assegnazione ticket",
                    "email_subject_template": "[Ticket] #{id} assegnato a te",
                    "email_body_text_template": (
                        "Il ticket #{id} ti e' stato assegnato.\n"
                        "Titolo: {titolo}\n"
                        "Priorita': {priorita}\n"
                        "Categoria: {categoria}"
                    ),
                    "email_body_html_template": (
                        "<p>Il ticket <strong>#{id}</strong> ti e' stato assegnato.</p>"
                        "<p>Titolo: {titolo} | Priorita': {priorita}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. tecnico@example.com"},
            },
        ]
        suggestions[AutomationActionType.INSERT_RECORD]["group_title"] = "Preset notifiche interne per Tickets"
        suggestions[AutomationActionType.INSERT_RECORD]["group_subtitle"] = "Notifiche portale per apertura e aggiornamento ticket."
        suggestions[AutomationActionType.INSERT_RECORD]["presets"] = [
            {
                "key": "tickets_notify_new",
                "title": "Notifica nuovo ticket",
                "description": "Crea notifica interna per nuovo ticket aperto.",
                "theme": "blue",
                "values": {
                    "description": "Notifica interna nuovo ticket",
                    "insert_target_table": "core_notifica",
                    "insert_field_mappings_text": (
                        "legacy_user_id = {richiedente_legacy_user_id}\n"
                        "tipo = ticket_aperto\n"
                        "messaggio = Ticket #{id} aperto: {titolo} (priorita': {priorita})\n"
                        "letta = 0"
                    ),
                },
                "placeholders": {},
            },
            {
                "key": "tickets_notify_resolved",
                "title": "Notifica ticket risolto",
                "description": "Notifica interna al richiedente quando il ticket viene chiuso.",
                "theme": "green",
                "values": {
                    "description": "Notifica interna risoluzione ticket",
                    "insert_target_table": "core_notifica",
                    "insert_field_mappings_text": (
                        "legacy_user_id = {richiedente_legacy_user_id}\n"
                        "tipo = ticket_risolto\n"
                        "messaggio = Il tuo ticket #{id} '{titolo}' e' stato risolto da {assegnato_a}\n"
                        "letta = 0"
                    ),
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.WRITE_LOG]["group_title"] = "Preset log per Tickets"
        suggestions[AutomationActionType.WRITE_LOG]["group_subtitle"] = "Log operativi per tracciamento stati e assegnazioni ticket."
        suggestions[AutomationActionType.WRITE_LOG]["presets"] = [
            {
                "key": "tickets_log_status",
                "title": "Log cambio stato",
                "description": "Registra il cambio di stato del ticket.",
                "theme": "slate",
                "values": {
                    "description": "Log stato ticket",
                    "write_log_message_template": "Ticket #{id} '{titolo}' - stato: {stato}, priorita': {priorita}, assegnato: {assegnato_a}",
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["group_title"] = "Preset metriche per Tickets"
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["group_subtitle"] = "Contatori ticket aperti, risolti, in attesa."
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["presets"] = [
            {
                "key": "tickets_metric_open",
                "title": "Conta ticket aperti",
                "description": "Incrementa il contatore dei ticket aperti.",
                "theme": "blue",
                "values": {
                    "description": "Conta ticket aperti",
                    "metric_code": "tickets_aperti",
                    "metric_operation": "increment",
                    "metric_value_template": "1",
                },
                "placeholders": {},
            },
            {
                "key": "tickets_metric_resolved",
                "title": "Conta ticket risolti",
                "description": "Incrementa il contatore dei ticket risolti oggi.",
                "theme": "green",
                "values": {
                    "description": "Conta ticket risolti",
                    "metric_code": "tickets_risolti_oggi",
                    "metric_operation": "increment",
                    "metric_value_template": "1",
                },
                "placeholders": {},
            },
        ]

    elif source_code_value == "assets":
        suggestions[AutomationActionType.SEND_EMAIL]["group_title"] = "Preset email per Assets"
        suggestions[AutomationActionType.SEND_EMAIL]["group_subtitle"] = "Notifiche per scadenze manutenzione, assegnazioni e cambio stato."
        suggestions[AutomationActionType.SEND_EMAIL]["presets"] = [
            {
                "key": "assets_maintenance_due_email",
                "title": "Scadenza manutenzione",
                "description": "Avvisa il responsabile della scadenza di manutenzione imminente.",
                "theme": "amber",
                "values": {
                    "description": "Notifica scadenza manutenzione asset",
                    "email_subject_template": "[Asset] Manutenzione in scadenza: {name} ({asset_tag})",
                    "email_body_text_template": (
                        "L'asset {name} (codice: {asset_tag}) ha una manutenzione in scadenza.\n"
                        "Stato: {status}\n"
                        "Posizione: {assignment_location}"
                    ),
                    "email_body_html_template": (
                        "<p>Asset <strong>{name}</strong> (codice: {asset_tag}).</p>"
                        "<p>Manutenzione in scadenza. Stato attuale: {status}</p>"
                        "<p>Posizione: {assignment_location}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. manutenzione@example.com"},
            },
            {
                "key": "assets_assigned_email",
                "title": "Asset assegnato",
                "description": "Notifica l'assegnatario quando un asset gli viene attribuito.",
                "theme": "blue",
                "values": {
                    "description": "Notifica assegnazione asset",
                    "email_subject_template": "[Asset] {name} assegnato",
                    "email_body_text_template": (
                        "L'asset {name} (codice: {asset_tag}) e' stato assegnato.\n"
                        "Categoria: {asset_category_id}\n"
                        "Posizione: {assignment_location}"
                    ),
                    "email_body_html_template": (
                        "<p>Asset <strong>{name}</strong> (codice: {asset_tag}) assegnato.</p>"
                        "<p>Categoria: {asset_category_id} | Posizione: {assignment_location}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. utente@example.com"},
            },
        ]
        suggestions[AutomationActionType.INSERT_RECORD]["group_title"] = "Preset notifiche interne per Assets"
        suggestions[AutomationActionType.INSERT_RECORD]["group_subtitle"] = "Notifiche portale per cambi stato e scadenze asset."
        suggestions[AutomationActionType.INSERT_RECORD]["presets"] = [
            {
                "key": "assets_notify_status_change",
                "title": "Notifica cambio stato",
                "description": "Notifica interna quando lo stato di un asset cambia.",
                "theme": "blue",
                "values": {
                    "description": "Notifica cambio stato asset",
                    "insert_target_table": "core_notifica",
                    "insert_field_mappings_text": (
                        "legacy_user_id = {assigned_legacy_user_id}\n"
                        "tipo = asset_aggiornamento\n"
                        "messaggio = Asset #{id} '{name}' aggiornato: stato {status}\n"
                        "letta = 0"
                    ),
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.WRITE_LOG]["group_title"] = "Preset log per Assets"
        suggestions[AutomationActionType.WRITE_LOG]["group_subtitle"] = "Log tecnici per tracciamento modifiche e scadenze asset."
        suggestions[AutomationActionType.WRITE_LOG]["presets"] = [
            {
                "key": "assets_log_status",
                "title": "Log cambio stato",
                "description": "Registra il cambio di stato dell'asset.",
                "theme": "slate",
                "values": {
                    "description": "Log stato asset",
                    "write_log_message_template": "Asset #{id} '{name}' (tag: {asset_tag}) - stato: {status}, posizione: {assignment_location}",
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["group_title"] = "Preset metriche per Assets"
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["group_subtitle"] = "Contatori per asset attivi, in manutenzione, dismessi."
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["presets"] = [
            {
                "key": "assets_metric_active",
                "title": "Conta asset attivi",
                "description": "Incrementa il contatore degli asset attivi.",
                "theme": "green",
                "values": {
                    "description": "Conta asset attivi",
                    "metric_code": "assets_attivi",
                    "metric_operation": "increment",
                    "metric_value_template": "1",
                },
                "placeholders": {},
            },
        ]

    elif source_code_value == "anomalie":
        suggestions[AutomationActionType.HTTP_REQUEST]["group_title"] = "Preset HTTP per Anomalie"
        suggestions[AutomationActionType.HTTP_REQUEST]["group_subtitle"] = "Webhook esterni vicini al flow `GESTIONE ANOMALIE - new OP`."
        suggestions[AutomationActionType.HTTP_REQUEST]["presets"] = [
            {
                "key": "anomalie_http_newop",
                "title": "Webhook creazione cartella OP",
                "description": "Invia OP e identificativi a un endpoint che crea la cartella e restituisce il link.",
                "theme": "blue",
                "values": {
                    "description": "Chiama webhook esterno per new OP",
                    "http_method": "POST",
                    "http_headers_text": "Content-Type = application/json",
                    "http_body_template": "{\n  \"op\": \"{ex_op_nominativo}\",\n  \"anomalia_id\": \"{id}\",\n  \"seriale\": \"{seriale}\"\n}",
                    "http_expected_status_csv": "200,201,202",
                },
                "placeholders": {
                    "http_url_template": "Endpoint che replica la logica new OP",
                },
            },
        ]
        suggestions[AutomationActionType.SEND_EMAIL]["group_title"] = "Preset email per Anomalie"
        suggestions[AutomationActionType.SEND_EMAIL]["group_subtitle"] = "Notifiche per nuove anomalie, aggiornamenti e chiusure."
        suggestions[AutomationActionType.SEND_EMAIL]["presets"] = [
            {
                "key": "anomalie_new_email",
                "title": "Nuova anomalia aperta",
                "description": "Avvisa il responsabile quando viene segnalata una nuova anomalia.",
                "theme": "rose",
                "values": {
                    "description": "Notifica nuova anomalia",
                    "email_subject_template": "[Anomalia] #{id} aperta: {ex_op_nominativo}",
                    "email_body_text_template": (
                        "E' stata segnalata una nuova anomalia #{id}.\n"
                        "OP: {ex_op_nominativo}\n"
                        "PN/Seriale: {seriale}\n"
                        "Stato: {avanzamento}"
                    ),
                    "email_body_html_template": (
                        "<p>Nuova anomalia <strong>#{id}</strong> segnalata.</p>"
                        "<p>OP: {ex_op_nominativo} | PN: {seriale}</p>"
                        "<p>Stato: {avanzamento}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. responsabile@example.com"},
            },
            {
                "key": "anomalie_closed_email",
                "title": "Anomalia chiusa",
                "description": "Comunica la chiusura dell'anomalia al responsabile.",
                "theme": "green",
                "values": {
                    "description": "Notifica chiusura anomalia",
                    "email_subject_template": "[Anomalia] #{id} chiusa",
                    "email_body_text_template": (
                        "L'anomalia #{id} e' stata chiusa.\n"
                        "OP: {ex_op_nominativo}\n"
                        "PN: {seriale}\n"
                        "Stato finale: {avanzamento}"
                    ),
                    "email_body_html_template": (
                        "<p>Anomalia <strong>#{id}</strong> chiusa.</p>"
                        "<p>OP: {ex_op_nominativo} | PN: {seriale}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. qualita@example.com"},
            },
        ]
        suggestions[AutomationActionType.INSERT_RECORD]["group_title"] = "Preset notifiche interne per Anomalie"
        suggestions[AutomationActionType.INSERT_RECORD]["group_subtitle"] = "Notifiche portale per nuove anomalie e aggiornamenti."
        suggestions[AutomationActionType.INSERT_RECORD]["presets"] = [
            {
                "key": "anomalie_notify_new",
                "title": "Notifica nuova anomalia",
                "description": "Crea notifica interna al responsabile per anomalia aperta.",
                "theme": "rose",
                "values": {
                    "description": "Notifica interna nuova anomalia",
                    "insert_target_table": "core_notifica",
                    "insert_field_mappings_text": (
                        "legacy_user_id = {created_by}\n"
                        "tipo = anomalia_aperta\n"
                        "messaggio = Nuova anomalia #{id}: OP {ex_op_nominativo}, PN {seriale}\n"
                        "letta = 0"
                    ),
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.WRITE_LOG]["group_title"] = "Preset log per Anomalie"
        suggestions[AutomationActionType.WRITE_LOG]["group_subtitle"] = "Log tecnici per audit e tracciamento anomalie produzione."
        suggestions[AutomationActionType.WRITE_LOG]["presets"] = [
            {
                "key": "anomalie_log_status",
                "title": "Log cambio stato",
                "description": "Registra il cambio di avanzamento dell'anomalia.",
                "theme": "slate",
                "values": {
                    "description": "Log stato anomalia",
                    "write_log_message_template": "Anomalia #{id} - OP: {ex_op_nominativo}, PN: {seriale}, stato: {avanzamento}, da_chiudere: {chiudere}",
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["group_title"] = "Preset metriche per Anomalie"
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["group_subtitle"] = "Contatori anomalie aperte, chiuse, in lavorazione."
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["presets"] = [
            {
                "key": "anomalie_metric_aperte",
                "title": "Conta anomalie aperte",
                "description": "Incrementa il contatore delle anomalie aperte.",
                "theme": "rose",
                "values": {
                    "description": "Conta anomalie aperte",
                    "metric_code": "anomalie_aperte",
                    "metric_operation": "increment",
                    "metric_value_template": "1",
                },
                "placeholders": {},
            },
            {
                "key": "anomalie_metric_chiuse",
                "title": "Conta anomalie chiuse",
                "description": "Incrementa il contatore delle anomalie chiuse.",
                "theme": "green",
                "values": {
                    "description": "Conta anomalie chiuse",
                    "metric_code": "anomalie_chiuse_oggi",
                    "metric_operation": "increment",
                    "metric_value_template": "1",
                },
                "placeholders": {},
            },
        ]

    elif source_code_value == "notizie":
        suggestions[AutomationActionType.SEND_EMAIL]["group_title"] = "Preset email per Notizie"
        suggestions[AutomationActionType.SEND_EMAIL]["group_subtitle"] = "Notifiche per pubblicazione e aggiornamento comunicazioni."
        suggestions[AutomationActionType.SEND_EMAIL]["presets"] = [
            {
                "key": "notizie_pubblicata_email",
                "title": "Notizia pubblicata",
                "description": "Invia email ai destinatari quando una notizia viene pubblicata.",
                "theme": "blue",
                "values": {
                    "description": "Notifica pubblicazione notizia",
                    "email_subject_template": "[Bacheca] Nuova comunicazione: {titolo}",
                    "email_body_text_template": (
                        "E' stata pubblicata una nuova comunicazione.\n"
                        "Titolo: {titolo}\n"
                        "Versione: {versione}\n"
                        "Accedi al portale per leggerla."
                    ),
                    "email_body_html_template": (
                        "<p>E' stata pubblicata una nuova comunicazione.</p>"
                        "<p><strong>{titolo}</strong> (versione {versione})</p>"
                        "<p>Accedi al portale per leggerla.</p>"
                    ),
                },
                "placeholders": {"email_to": "es. tutti@example.com o destinatario specifico"},
            },
            {
                "key": "notizie_obbligatoria_email",
                "title": "Comunicazione obbligatoria",
                "description": "Avvisa i destinatari di una comunicazione che richiede conferma.",
                "theme": "rose",
                "values": {
                    "description": "Avviso comunicazione obbligatoria",
                    "email_subject_template": "[IMPORTANTE] Comunicazione obbligatoria: {titolo}",
                    "email_body_text_template": (
                        "E' stata pubblicata una comunicazione obbligatoria che richiede la tua conferma.\n"
                        "Titolo: {titolo}\n"
                        "Versione: {versione}\n"
                        "Accedi al portale e confermala entro i termini previsti."
                    ),
                    "email_body_html_template": (
                        "<p><strong>Attenzione:</strong> comunicazione obbligatoria pubblicata.</p>"
                        "<p><strong>{titolo}</strong> (versione {versione})</p>"
                        "<p>Accedi al portale e conferma la lettura.</p>"
                    ),
                },
                "placeholders": {"email_to": "es. destinatario specifico"},
            },
        ]
        suggestions[AutomationActionType.INSERT_RECORD]["group_title"] = "Preset notifiche interne per Notizie"
        suggestions[AutomationActionType.INSERT_RECORD]["group_subtitle"] = "Notifiche portale per pubblicazioni e aggiornamenti bacheca."
        suggestions[AutomationActionType.INSERT_RECORD]["presets"] = [
            {
                "key": "notizie_notify_pubblicata",
                "title": "Notifica pubblicazione",
                "description": "Crea notifica interna quando una notizia viene pubblicata.",
                "theme": "blue",
                "values": {
                    "description": "Notifica interna pubblicazione notizia",
                    "insert_target_table": "core_notifica",
                    "insert_field_mappings_text": (
                        "tipo = notizia_pubblicata\n"
                        "messaggio = Nuova comunicazione: {titolo} (v{versione})\n"
                        "letta = 0"
                    ),
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.WRITE_LOG]["group_title"] = "Preset log per Notizie"
        suggestions[AutomationActionType.WRITE_LOG]["presets"] = [
            {
                "key": "notizie_log_pubblicata",
                "title": "Log pubblicazione",
                "description": "Registra la pubblicazione della notizia nel log operativo.",
                "theme": "slate",
                "values": {
                    "description": "Log pubblicazione notizia",
                    "write_log_message_template": "Notizia #{id} pubblicata: '{titolo}' (v{versione}), obbligatoria={obbligatoria}",
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["group_title"] = "Preset metriche per Notizie"
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["presets"] = [
            {
                "key": "notizie_metric_pubblicata",
                "title": "Conta notizie pubblicate",
                "description": "Incrementa il contatore delle notizie pubblicate.",
                "theme": "blue",
                "values": {
                    "description": "Conta notizie pubblicate",
                    "metric_code": "notizie_pubblicate",
                    "metric_operation": "increment",
                    "metric_value_template": "1",
                },
                "placeholders": {},
            },
        ]

    elif source_code_value == "diario_preposto":
        suggestions[AutomationActionType.SEND_EMAIL]["group_title"] = "Preset email per Diario Preposto"
        suggestions[AutomationActionType.SEND_EMAIL]["group_subtitle"] = "Notifiche per nuove segnalazioni sicurezza del preposto."
        suggestions[AutomationActionType.SEND_EMAIL]["presets"] = [
            {
                "key": "diario_preposto_nuova_email",
                "title": "Nuova segnalazione",
                "description": "Avvisa il responsabile sicurezza di una nuova segnalazione.",
                "theme": "rose",
                "values": {
                    "description": "Notifica nuova segnalazione preposto",
                    "email_subject_template": "[Sicurezza] Nuova segnalazione preposto: {codice_identificativo}",
                    "email_body_text_template": (
                        "E' stata inserita una nuova segnalazione preposto.\n"
                        "Codice: {codice_identificativo}\n"
                        "Titolo: {titolo}\n"
                        "Preposto: {preposto}\n"
                        "Segnalato da: {chi_segnala}\n"
                        "Data: {data_segnalazione}"
                    ),
                    "email_body_html_template": (
                        "<p>Nuova segnalazione preposto <strong>{codice_identificativo}</strong>.</p>"
                        "<p>Titolo: {titolo}</p>"
                        "<p>Preposto: {preposto} | Segnalato da: {chi_segnala}</p>"
                        "<p>Data: {data_segnalazione}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. rspp@example.com"},
            },
        ]
        suggestions[AutomationActionType.INSERT_RECORD]["group_title"] = "Preset notifiche interne per Diario Preposto"
        suggestions[AutomationActionType.INSERT_RECORD]["presets"] = [
            {
                "key": "diario_preposto_notify_new",
                "title": "Notifica nuova segnalazione",
                "description": "Notifica interna al responsabile sicurezza.",
                "theme": "rose",
                "values": {
                    "description": "Notifica interna nuova segnalazione preposto",
                    "insert_target_table": "core_notifica",
                    "insert_field_mappings_text": (
                        "tipo = diario_preposto_segnalazione\n"
                        "messaggio = Nuova segnalazione preposto {codice_identificativo}: {titolo}\n"
                        "letta = 0"
                    ),
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.WRITE_LOG]["group_title"] = "Preset log per Diario Preposto"
        suggestions[AutomationActionType.WRITE_LOG]["presets"] = [
            {
                "key": "diario_preposto_log",
                "title": "Log nuova segnalazione",
                "description": "Registra la segnalazione nel log operativo.",
                "theme": "slate",
                "values": {
                    "description": "Log segnalazione preposto",
                    "write_log_message_template": "Segnalazione preposto #{id} '{codice_identificativo}': {titolo}, preposto={preposto}, chi_segnala={chi_segnala}",
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["group_title"] = "Preset metriche per Diario Preposto"
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["presets"] = [
            {
                "key": "diario_preposto_metric",
                "title": "Conta segnalazioni",
                "description": "Incrementa il contatore delle segnalazioni.",
                "theme": "rose",
                "values": {
                    "description": "Conta segnalazioni preposto",
                    "metric_code": "segnalazioni_preposto",
                    "metric_operation": "increment",
                    "metric_value_template": "1",
                },
                "placeholders": {},
            },
        ]

    elif source_code_value == "rilevazione_incidenti":
        suggestions[AutomationActionType.SEND_EMAIL]["group_title"] = "Preset email per Incidenti / Sicurezza"
        suggestions[AutomationActionType.SEND_EMAIL]["group_subtitle"] = "Notifiche per apertura, approvazione RLS e chiusura RSPP."
        suggestions[AutomationActionType.SEND_EMAIL]["presets"] = [
            {
                "key": "incidenti_nuova_email",
                "title": "Nuovo incidente segnalato",
                "description": "Avvisa il RSPP e il responsabile di una nuova rilevazione.",
                "theme": "rose",
                "values": {
                    "description": "Notifica nuovo incidente",
                    "email_subject_template": "[Sicurezza] Nuova rilevazione: {tipologia_scheda} - {reparto}",
                    "email_body_text_template": (
                        "E' stata registrata una nuova rilevazione sicurezza.\n"
                        "Tipologia: {tipologia_scheda}\n"
                        "Reparto: {reparto}\n"
                        "Nominativo: {nominativo}\n"
                        "Data segnalazione: {data_segnalazione}\n"
                        "Persone coinvolte: {persone_coinvolte}"
                    ),
                    "email_body_html_template": (
                        "<p>Nuova rilevazione sicurezza registrata.</p>"
                        "<p>Tipologia: <strong>{tipologia_scheda}</strong> | Reparto: {reparto}</p>"
                        "<p>Nominativo: {nominativo} | Data: {data_segnalazione}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. rspp@example.com"},
            },
            {
                "key": "incidenti_chiusa_rspp_email",
                "title": "Incidente chiuso RSPP",
                "description": "Notifica la chiusura dell'incidente da parte del RSPP.",
                "theme": "green",
                "values": {
                    "description": "Notifica chiusura RSPP",
                    "email_subject_template": "[Sicurezza] Incidente #{id} chiuso da RSPP",
                    "email_body_text_template": (
                        "L'incidente #{id} e' stato chiuso dal RSPP.\n"
                        "Tipologia: {tipologia_scheda}\n"
                        "Nominativo: {nominativo}\n"
                        "Data chiusura: {data_chiusura_rspp}"
                    ),
                    "email_body_html_template": (
                        "<p>Incidente <strong>#{id}</strong> chiuso dal RSPP.</p>"
                        "<p>Tipologia: {tipologia_scheda} | Data chiusura: {data_chiusura_rspp}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. responsabile@example.com"},
            },
        ]
        suggestions[AutomationActionType.INSERT_RECORD]["group_title"] = "Preset notifiche interne per Incidenti"
        suggestions[AutomationActionType.INSERT_RECORD]["presets"] = [
            {
                "key": "incidenti_notify_new",
                "title": "Notifica nuovo incidente",
                "description": "Crea notifica interna al RSPP per nuova rilevazione.",
                "theme": "rose",
                "values": {
                    "description": "Notifica interna nuovo incidente",
                    "insert_target_table": "core_notifica",
                    "insert_field_mappings_text": (
                        "tipo = incidente_segnalato\n"
                        "messaggio = Nuova rilevazione #{id}: {tipologia_scheda} in {reparto} - {nominativo}\n"
                        "letta = 0"
                    ),
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.WRITE_LOG]["group_title"] = "Preset log per Incidenti"
        suggestions[AutomationActionType.WRITE_LOG]["presets"] = [
            {
                "key": "incidenti_log",
                "title": "Log rilevazione",
                "description": "Registra la rilevazione nel log operativo.",
                "theme": "slate",
                "values": {
                    "description": "Log rilevazione incidente",
                    "write_log_message_template": "Incidente #{id}: {tipologia_scheda}, reparto={reparto}, nominativo={nominativo}, chiusura_rspp={chiusura_rspp}",
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["group_title"] = "Preset metriche per Incidenti"
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["presets"] = [
            {
                "key": "incidenti_metric_aperti",
                "title": "Conta incidenti",
                "description": "Incrementa il contatore degli incidenti registrati.",
                "theme": "rose",
                "values": {
                    "description": "Conta incidenti registrati",
                    "metric_code": "incidenti_registrati",
                    "metric_operation": "increment",
                    "metric_value_template": "1",
                },
                "placeholders": {},
            },
        ]

    elif source_code_value == "rentri":
        suggestions[AutomationActionType.SEND_EMAIL]["group_title"] = "Preset email per RENTRI / Rifiuti"
        suggestions[AutomationActionType.SEND_EMAIL]["group_subtitle"] = "Notifiche per carichi, scarichi e movimenti da trasmettere a RENTRI."
        suggestions[AutomationActionType.SEND_EMAIL]["presets"] = [
            {
                "key": "rentri_carico_email",
                "title": "Nuovo carico rifiuti",
                "description": "Notifica la registrazione di un nuovo carico rifiuti.",
                "theme": "amber",
                "values": {
                    "description": "Notifica nuovo carico rifiuti",
                    "email_subject_template": "[RENTRI] Nuovo carico registrato: {id_registrazione}",
                    "email_body_text_template": (
                        "E' stato registrato un nuovo movimento rifiuti.\n"
                        "ID registrazione: {id_registrazione}\n"
                        "Tipo: {tipo}\n"
                        "Codice rifiuto: {codice}\n"
                        "Quantita': {quantita}\n"
                        "Inserito da: {inserito_da}"
                    ),
                    "email_body_html_template": (
                        "<p>Nuovo movimento rifiuti registrato.</p>"
                        "<p>ID: <strong>{id_registrazione}</strong> | Tipo: {tipo}</p>"
                        "<p>Codice: {codice} | Quantita': {quantita}</p>"
                        "<p>Inserito da: {inserito_da}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. rentri@example.com"},
            },
            {
                "key": "rentri_da_trasmettere_email",
                "title": "Movimento da trasmettere RENTRI",
                "description": "Avvisa quando un movimento e' flaggato per trasmissione RENTRI.",
                "theme": "rose",
                "values": {
                    "description": "Avviso movimento RENTRI",
                    "email_subject_template": "[RENTRI] Movimento {id_registrazione} da trasmettere",
                    "email_body_text_template": (
                        "Il movimento {id_registrazione} richiede trasmissione a RENTRI.\n"
                        "Tipo: {tipo}\n"
                        "Codice rifiuto: {codice}\n"
                        "Quantita': {quantita}\n"
                        "Data: {data}"
                    ),
                    "email_body_html_template": (
                        "<p>Movimento <strong>{id_registrazione}</strong> da trasmettere a RENTRI.</p>"
                        "<p>Tipo: {tipo} | Codice: {codice} | Data: {data}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. responsabile_ambientale@example.com"},
            },
        ]
        suggestions[AutomationActionType.WRITE_LOG]["group_title"] = "Preset log per RENTRI"
        suggestions[AutomationActionType.WRITE_LOG]["presets"] = [
            {
                "key": "rentri_log_movimento",
                "title": "Log movimento",
                "description": "Registra il movimento rifiuti nel log operativo.",
                "theme": "slate",
                "values": {
                    "description": "Log movimento rifiuti",
                    "write_log_message_template": "Movimento RENTRI #{id}: {id_registrazione}, tipo={tipo}, codice={codice}, quantita={quantita}, rentri={rentri_si_no}",
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.INSERT_RECORD]["group_title"] = "Preset notifiche interne per RENTRI"
        suggestions[AutomationActionType.INSERT_RECORD]["presets"] = [
            {
                "key": "rentri_notify_movimento",
                "title": "Notifica nuovo movimento",
                "description": "Notifica interna per nuovo carico/scarico rifiuti.",
                "theme": "amber",
                "values": {
                    "description": "Notifica interna movimento rifiuti",
                    "insert_target_table": "core_notifica",
                    "insert_field_mappings_text": (
                        "tipo = rentri_movimento\n"
                        "messaggio = Nuovo movimento RENTRI {id_registrazione}: {tipo} - codice {codice} - {quantita} unita'\n"
                        "letta = 0"
                    ),
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["group_title"] = "Preset metriche per RENTRI"
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["presets"] = [
            {
                "key": "rentri_metric_movimenti",
                "title": "Conta movimenti",
                "description": "Incrementa il contatore dei movimenti registrati.",
                "theme": "amber",
                "values": {
                    "description": "Conta movimenti RENTRI",
                    "metric_code": "rentri_movimenti",
                    "metric_operation": "increment",
                    "metric_value_template": "1",
                },
                "placeholders": {},
            },
        ]

    elif source_code_value == "dpi":
        suggestions[AutomationActionType.SEND_EMAIL]["group_title"] = "Preset email per DPI"
        suggestions[AutomationActionType.SEND_EMAIL]["group_subtitle"] = "Notifiche per approvazione, rifiuto e consegna DPI."
        suggestions[AutomationActionType.SEND_EMAIL]["presets"] = [
            {
                "key": "dpi_approvata_email",
                "title": "Richiesta DPI approvata",
                "description": "Avvisa il richiedente che la richiesta DPI e' stata approvata.",
                "theme": "green",
                "values": {
                    "description": "Notifica approvazione richiesta DPI",
                    "email_subject_template": "[DPI] Richiesta {numero} approvata",
                    "email_body_text_template": (
                        "La tua richiesta DPI {numero} e' stata approvata.\n"
                        "Reparto: {richiedente_reparto}\n"
                        "Quantita': {quantita}\n"
                        "{note_gestione}"
                    ),
                    "email_body_html_template": (
                        "<p>La richiesta DPI <strong>{numero}</strong> e' stata approvata.</p>"
                        "<p>Reparto: {richiedente_reparto} | Quantita': {quantita}</p>"
                        "<p>Note: {note_gestione}</p>"
                    ),
                },
                "placeholders": {"email_to": "{richiedente_email}"},
            },
            {
                "key": "dpi_rifiutata_email",
                "title": "Richiesta DPI rifiutata",
                "description": "Comunica al richiedente il rifiuto della richiesta DPI.",
                "theme": "rose",
                "values": {
                    "description": "Notifica rifiuto richiesta DPI",
                    "email_subject_template": "[DPI] Richiesta {numero} non approvata",
                    "email_body_text_template": (
                        "La tua richiesta DPI {numero} non e' stata approvata.\n"
                        "Motivazione: {motivazione}\n"
                        "Note gestione: {note_gestione}\n"
                        "Contatta il tuo responsabile per ulteriori informazioni."
                    ),
                    "email_body_html_template": (
                        "<p>La richiesta DPI <strong>{numero}</strong> non e' stata approvata.</p>"
                        "<p>Note: {note_gestione}</p>"
                    ),
                },
                "placeholders": {"email_to": "{richiedente_email}"},
            },
            {
                "key": "dpi_nuova_richiesta_email",
                "title": "Nuova richiesta DPI",
                "description": "Avvisa il gestore DPI di una nuova richiesta da processare.",
                "theme": "blue",
                "values": {
                    "description": "Notifica nuova richiesta DPI",
                    "email_subject_template": "[DPI] Nuova richiesta da {richiedente_nome}: {numero}",
                    "email_body_text_template": (
                        "E' arrivata una nuova richiesta DPI.\n"
                        "Numero: {numero}\n"
                        "Richiedente: {richiedente_nome} ({richiedente_reparto})\n"
                        "Quantita': {quantita}\n"
                        "Motivazione: {motivazione}"
                    ),
                    "email_body_html_template": (
                        "<p>Nuova richiesta DPI <strong>{numero}</strong>.</p>"
                        "<p>Richiedente: {richiedente_nome} ({richiedente_reparto})</p>"
                        "<p>Quantita': {quantita}</p>"
                        "<p>Motivazione: {motivazione}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. magazzino@example.com"},
            },
        ]
        suggestions[AutomationActionType.INSERT_RECORD]["group_title"] = "Preset notifiche interne per DPI"
        suggestions[AutomationActionType.INSERT_RECORD]["group_subtitle"] = "Notifiche portale per workflow approvazione/rifiuto/consegna DPI."
        suggestions[AutomationActionType.INSERT_RECORD]["presets"] = [
            {
                "key": "dpi_notify_richiedente",
                "title": "Notifica richiedente",
                "description": "Notifica interna al richiedente DPI per cambio stato.",
                "theme": "blue",
                "values": {
                    "description": "Notifica interna richiedente DPI",
                    "insert_target_table": "core_notifica",
                    "insert_field_mappings_text": (
                        "legacy_user_id = {richiedente_legacy_id}\n"
                        "tipo = dpi_aggiornamento\n"
                        "messaggio = Richiesta DPI {numero}: stato aggiornato a {stato}\n"
                        "letta = 0"
                    ),
                },
                "placeholders": {},
            },
            {
                "key": "dpi_notify_gestore",
                "title": "Notifica gestore",
                "description": "Notifica interna al gestore per nuova richiesta DPI.",
                "theme": "amber",
                "values": {
                    "description": "Notifica interna gestore DPI",
                    "insert_target_table": "core_notifica",
                    "insert_field_mappings_text": (
                        "tipo = dpi_nuova_richiesta\n"
                        "messaggio = Nuova richiesta DPI {numero} da {richiedente_nome} ({richiedente_reparto})\n"
                        "letta = 0"
                    ),
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.WRITE_LOG]["group_title"] = "Preset log per DPI"
        suggestions[AutomationActionType.WRITE_LOG]["presets"] = [
            {
                "key": "dpi_log_stato",
                "title": "Log cambio stato",
                "description": "Registra il cambio di stato della richiesta DPI.",
                "theme": "slate",
                "values": {
                    "description": "Log stato richiesta DPI",
                    "write_log_message_template": "Richiesta DPI {numero} - stato: {stato}, richiedente: {richiedente_nome} ({richiedente_reparto}), quantita': {quantita}",
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["group_title"] = "Preset metriche per DPI"
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["presets"] = [
            {
                "key": "dpi_metric_richieste",
                "title": "Conta richieste DPI",
                "description": "Incrementa il contatore delle richieste DPI.",
                "theme": "blue",
                "values": {
                    "description": "Conta richieste DPI",
                    "metric_code": "dpi_richieste",
                    "metric_operation": "increment",
                    "metric_value_template": "1",
                },
                "placeholders": {},
            },
        ]

    elif source_code_value == "procedure_campagne":
        suggestions[AutomationActionType.SEND_EMAIL]["group_title"] = "Preset email per Campagne Procedure"
        suggestions[AutomationActionType.SEND_EMAIL]["group_subtitle"] = "Notifiche per lancio, scadenza e chiusura campagne MT/MTSI."
        suggestions[AutomationActionType.SEND_EMAIL]["presets"] = [
            {
                "key": "procedure_campagna_pubblicata_email",
                "title": "Campagna pubblicata",
                "description": "Avvisa i destinatari del lancio di una nuova campagna presa visione.",
                "theme": "blue",
                "values": {
                    "description": "Notifica lancio campagna procedure",
                    "email_subject_template": "[Procedure] Campagna avviata: {name}",
                    "email_body_text_template": (
                        "E' stata avviata una nuova campagna di presa visione procedure.\n"
                        "Campagna: {name}\n"
                        "Inizio: {start_date}\n"
                        "Scadenza: {due_date}\n"
                        "Accedi al portale per consultare i documenti assegnati."
                    ),
                    "email_body_html_template": (
                        "<p>Nuova campagna presa visione avviata.</p>"
                        "<p><strong>{name}</strong></p>"
                        "<p>Inizio: {start_date} | Scadenza: {due_date}</p>"
                        "<p>Accedi al portale per i documenti assegnati.</p>"
                    ),
                },
                "placeholders": {"email_to": "es. tutti@example.com"},
            },
            {
                "key": "procedure_campagna_chiusa_email",
                "title": "Campagna chiusa",
                "description": "Notifica la chiusura della campagna ai responsabili.",
                "theme": "green",
                "values": {
                    "description": "Notifica chiusura campagna procedure",
                    "email_subject_template": "[Procedure] Campagna chiusa: {name}",
                    "email_body_text_template": (
                        "La campagna di presa visione '{name}' e' stata chiusa.\n"
                        "Periodo: {start_date} - {due_date}\n"
                        "Chiusa il: {closed_at}"
                    ),
                    "email_body_html_template": (
                        "<p>Campagna <strong>{name}</strong> chiusa.</p>"
                        "<p>Periodo: {start_date} - {due_date}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. responsabile@example.com"},
            },
        ]
        suggestions[AutomationActionType.INSERT_RECORD]["group_title"] = "Preset notifiche interne per Campagne"
        suggestions[AutomationActionType.INSERT_RECORD]["presets"] = [
            {
                "key": "procedure_campagna_notify",
                "title": "Notifica lancio campagna",
                "description": "Notifica interna per nuovo lancio campagna procedure.",
                "theme": "blue",
                "values": {
                    "description": "Notifica interna lancio campagna",
                    "insert_target_table": "core_notifica",
                    "insert_field_mappings_text": (
                        "tipo = procedure_campagna\n"
                        "messaggio = Nuova campagna presa visione: {name} (scadenza: {due_date})\n"
                        "letta = 0"
                    ),
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.WRITE_LOG]["group_title"] = "Preset log per Campagne"
        suggestions[AutomationActionType.WRITE_LOG]["presets"] = [
            {
                "key": "procedure_campagna_log",
                "title": "Log cambio stato campagna",
                "description": "Registra il cambio di stato della campagna.",
                "theme": "slate",
                "values": {
                    "description": "Log stato campagna procedure",
                    "write_log_message_template": "Campagna procedure #{id} '{name}': stato={status}, inizio={start_date}, scadenza={due_date}",
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["group_title"] = "Preset metriche per Campagne"
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["presets"] = [
            {
                "key": "procedure_metric_campagna",
                "title": "Conta campagne attive",
                "description": "Incrementa il contatore delle campagne pubblicate.",
                "theme": "blue",
                "values": {
                    "description": "Conta campagne procedure",
                    "metric_code": "procedure_campagne_attive",
                    "metric_operation": "increment",
                    "metric_value_template": "1",
                },
                "placeholders": {},
            },
        ]

    elif source_code_value == "procedure_assegnazioni":
        suggestions[AutomationActionType.SEND_EMAIL]["group_title"] = "Preset email per Assegnazioni Procedure"
        suggestions[AutomationActionType.SEND_EMAIL]["group_subtitle"] = "Reminder e notifiche per assegnazioni, aperture e conferme lettura."
        suggestions[AutomationActionType.SEND_EMAIL]["presets"] = [
            {
                "key": "procedure_assegnata_email",
                "title": "Procedura assegnata",
                "description": "Avvisa l'utente dell'assegnazione di una procedura da leggere.",
                "theme": "blue",
                "values": {
                    "description": "Notifica assegnazione procedura",
                    "email_subject_template": "[Procedure] Hai una procedura da leggere entro {due_date}",
                    "email_body_text_template": (
                        "Ti e' stata assegnata una procedura da leggere e confermare.\n"
                        "Scadenza: {due_date}\n"
                        "Accedi al portale per consultare il documento assegnato."
                    ),
                    "email_body_html_template": (
                        "<p>Ti e' stata assegnata una procedura da leggere.</p>"
                        "<p>Scadenza: <strong>{due_date}</strong></p>"
                        "<p>Accedi al portale per il documento assegnato.</p>"
                    ),
                },
                "placeholders": {"email_to": "es. utente@example.com"},
            },
            {
                "key": "procedure_reminder_email",
                "title": "Reminder scadenza lettura",
                "description": "Reminder automatico prima della scadenza di lettura.",
                "theme": "amber",
                "values": {
                    "description": "Reminder scadenza lettura procedura",
                    "email_subject_template": "[REMINDER] Procedura non ancora confermata - scadenza {due_date}",
                    "email_body_text_template": (
                        "Reminder: hai una procedura assegnata non ancora confermata.\n"
                        "Scadenza: {due_date}\n"
                        "Aperta: {open_count} volte | Prima apertura: {first_opened_at}\n"
                        "Accedi al portale e conferma la lettura."
                    ),
                    "email_body_html_template": (
                        "<p>Reminder: procedura non ancora confermata.</p>"
                        "<p>Scadenza: <strong>{due_date}</strong></p>"
                        "<p>Aperture: {open_count}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. utente@example.com"},
            },
            {
                "key": "procedure_confermata_email",
                "title": "Lettura confermata",
                "description": "Notifica il responsabile quando l'utente conferma la lettura.",
                "theme": "green",
                "values": {
                    "description": "Notifica conferma lettura procedura",
                    "email_subject_template": "[Procedure] Lettura confermata da utente #{user_id}",
                    "email_body_text_template": (
                        "L'assegnazione #{id} e' stata confermata.\n"
                        "Utente: #{user_id}\n"
                        "Confermato il: {read_confirmed_at}\n"
                        "Numero aperture: {open_count}"
                    ),
                    "email_body_html_template": (
                        "<p>Lettura procedura confermata.</p>"
                        "<p>Utente #{user_id} | Confermato: {read_confirmed_at}</p>"
                        "<p>Aperture totali: {open_count}</p>"
                    ),
                },
                "placeholders": {"email_to": "es. responsabile@example.com"},
            },
        ]
        suggestions[AutomationActionType.INSERT_RECORD]["group_title"] = "Preset notifiche interne per Assegnazioni"
        suggestions[AutomationActionType.INSERT_RECORD]["presets"] = [
            {
                "key": "procedure_assegnata_notify",
                "title": "Notifica assegnazione",
                "description": "Notifica interna all'utente per nuova procedura assegnata.",
                "theme": "blue",
                "values": {
                    "description": "Notifica interna assegnazione procedura",
                    "insert_target_table": "core_notifica",
                    "insert_field_mappings_text": (
                        "legacy_user_id = {user_id}\n"
                        "tipo = procedura_assegnata\n"
                        "messaggio = Nuova procedura assegnata da leggere entro {due_date}\n"
                        "letta = 0"
                    ),
                },
                "placeholders": {},
            },
            {
                "key": "procedure_scaduta_notify",
                "title": "Notifica scadenza",
                "description": "Notifica interna quando la procedura non e' confermata in tempo.",
                "theme": "rose",
                "values": {
                    "description": "Notifica scadenza lettura procedura",
                    "insert_target_table": "core_notifica",
                    "insert_field_mappings_text": (
                        "legacy_user_id = {user_id}\n"
                        "tipo = procedura_scaduta\n"
                        "messaggio = Procedura assegnata #{id} scaduta il {due_date}: lettura non ancora confermata\n"
                        "letta = 0"
                    ),
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.WRITE_LOG]["group_title"] = "Preset log per Assegnazioni"
        suggestions[AutomationActionType.WRITE_LOG]["presets"] = [
            {
                "key": "procedure_assegnazione_log",
                "title": "Log cambio stato assegnazione",
                "description": "Registra il cambio di stato dell'assegnazione procedura.",
                "theme": "slate",
                "values": {
                    "description": "Log stato assegnazione procedura",
                    "write_log_message_template": "Assegnazione procedura #{id}: utente={user_id}, campagna={campaign_id}, stato={status}, aperture={open_count}, confermato={read_confirmed_flag}",
                },
                "placeholders": {},
            },
        ]
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["group_title"] = "Preset metriche per Assegnazioni"
        suggestions[AutomationActionType.UPDATE_DASHBOARD_METRIC]["presets"] = [
            {
                "key": "procedure_metric_confermate",
                "title": "Conta letture confermate",
                "description": "Incrementa il contatore delle letture confermate.",
                "theme": "green",
                "values": {
                    "description": "Conta conferme lettura procedure",
                    "metric_code": "procedure_confermate",
                    "metric_operation": "increment",
                    "metric_value_template": "1",
                },
                "placeholders": {},
            },
            {
                "key": "procedure_metric_scadute",
                "title": "Conta assegnazioni scadute",
                "description": "Incrementa il contatore delle assegnazioni overdue.",
                "theme": "rose",
                "values": {
                    "description": "Conta assegnazioni scadute",
                    "metric_code": "procedure_scadute",
                    "metric_operation": "increment",
                    "metric_value_template": "1",
                },
                "placeholders": {},
            },
        ]

    return suggestions


def _build_condition_suggestions(source_code: str | None) -> dict[str, dict[str, object]]:
    source = get_source_definition(source_code) or {"code": source_code or "regola", "label": source_code or "Regola"}
    source_code_value = _string_value(source.get("code")) or "regola"
    source_label = _string_value(source.get("label")) or "Regola"
    status_field = _pick_source_field(source_code, ["moderation_status", "status", "stato", "avanzamento"], fallback_index=0)
    title_field = _pick_source_field(source_code, ["tipo_assenza", "title", "titolo", "name", "seriale"], fallback_index=0)
    owner_field = _pick_source_field(source_code, ["capo_reparto_id", "assigned_to_id", "created_by", "richiedente_legacy_user_id"], fallback_index=0)

    suggestions = {
        "base": {
            "group_title": f"Preset condizioni per {source_label}",
            "group_subtitle": "Base guidata e preset visuali pronti da adattare.",
            "values": {
                "field_name": status_field,
                "operator": AutomationConditionOperator.EQUALS,
                "expected_value": "1",
                "value_type": AutomationConditionValueType.INT,
                "compare_with_old": False,
                "is_enabled": True,
            },
            "presets": [
                {
                    "key": "default_status_equals",
                    "title": "Controlla stato",
                    "description": f"Verifica se `{status_field}` corrisponde a un valore specifico.",
                    "theme": "blue",
                    "values": {},
                },
                {
                    "key": "default_title_not_empty",
                    "title": "Campo valorizzato",
                    "description": f"Verifica che `{title_field}` non sia vuoto.",
                    "theme": "slate",
                    "values": {
                        "field_name": title_field,
                        "operator": AutomationConditionOperator.IS_NOT_EMPTY,
                        "expected_value": "",
                        "value_type": AutomationConditionValueType.STRING,
                        "compare_with_old": False,
                        "is_enabled": True,
                    },
                },
            ],
        }
    }

    if source_code_value == "assenze":
        suggestions["base"]["group_title"] = "Preset condizioni per Assenze"
        suggestions["base"]["group_subtitle"] = "Preset compatti per workflow approvazione, esclusioni e controlli old/new."
        suggestions["base"]["presets"] = [
            {
                "key": "assenze_status_to_2",
                "title": "Stato passa a 2",
                "description": "Preset rapido per workflow che reagiscono quando `moderation_status` diventa `2`.",
                "theme": "green",
                "values": {
                    "field_name": "moderation_status",
                    "operator": AutomationConditionOperator.CHANGED_TO,
                    "expected_value": "2",
                    "value_type": AutomationConditionValueType.INT,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
            {
                "key": "assenze_exclude_malattia",
                "title": "Escludi malattia",
                "description": "Usa `tipo_assenza != Malattia` per evitare regole su casistiche escluse.",
                "theme": "amber",
                "values": {
                    "field_name": "tipo_assenza",
                    "operator": AutomationConditionOperator.NOT_EQUALS,
                    "expected_value": "Malattia",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
            {
                "key": "assenze_status_changed",
                "title": "Status changed",
                "description": "Controlla che `moderation_status` sia effettivamente cambiato rispetto all'old payload.",
                "theme": "blue",
                "values": {
                    "field_name": "moderation_status",
                    "operator": AutomationConditionOperator.CHANGED,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.INT,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
            {
                "key": "assenze_manager_present",
                "title": "Capo reparto presente",
                "description": "Verifica che il responsabile sia valorizzato prima di proseguire.",
                "theme": "slate",
                "values": {
                    "field_name": "capo_reparto_id",
                    "operator": AutomationConditionOperator.IS_NOT_EMPTY,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.INT,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
        ]
    elif source_code_value == "tasks":
        suggestions["base"]["group_title"] = "Preset condizioni per Tasks"
        suggestions["base"]["group_subtitle"] = "Preset per stato, priorita' e assegnazioni task."
        suggestions["base"]["values"]["field_name"] = "status"
        suggestions["base"]["values"]["expected_value"] = "DONE"
        suggestions["base"]["values"]["value_type"] = AutomationConditionValueType.STRING
        suggestions["base"]["presets"] = [
            {
                "key": "tasks_status_done",
                "title": "Task completato",
                "description": "Reagisce quando lo stato del task passa a DONE.",
                "theme": "green",
                "values": {
                    "field_name": "status",
                    "operator": AutomationConditionOperator.CHANGED_TO,
                    "expected_value": "DONE",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
            {
                "key": "tasks_priority_high",
                "title": "Priorita' alta",
                "description": "Filtra solo i task con priorita' HIGH o CRITICAL.",
                "theme": "rose",
                "values": {
                    "field_name": "priority",
                    "operator": AutomationConditionOperator.IN_CSV,
                    "expected_value": "HIGH,CRITICAL",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
            {
                "key": "tasks_assigned",
                "title": "Assegnato presente",
                "description": "Verifica che il task abbia un assegnatario.",
                "theme": "blue",
                "values": {
                    "field_name": "assigned_to_id",
                    "operator": AutomationConditionOperator.IS_NOT_EMPTY,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.INT,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
            {
                "key": "tasks_status_changed",
                "title": "Stato cambiato",
                "description": "Verifica che lo stato del task sia effettivamente cambiato.",
                "theme": "amber",
                "values": {
                    "field_name": "status",
                    "operator": AutomationConditionOperator.CHANGED,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
        ]

    elif source_code_value == "tickets":
        suggestions["base"]["group_title"] = "Preset condizioni per Tickets"
        suggestions["base"]["group_subtitle"] = "Preset per stato, priorita' e apertura ticket."
        suggestions["base"]["values"]["field_name"] = "stato"
        suggestions["base"]["values"]["expected_value"] = "aperto"
        suggestions["base"]["values"]["value_type"] = AutomationConditionValueType.STRING
        suggestions["base"]["presets"] = [
            {
                "key": "tickets_stato_aperto",
                "title": "Ticket aperto",
                "description": "Reagisce quando un ticket viene aperto.",
                "theme": "blue",
                "values": {
                    "field_name": "stato",
                    "operator": AutomationConditionOperator.EQUALS,
                    "expected_value": "aperto",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
            {
                "key": "tickets_priorita_alta",
                "title": "Priorita' alta",
                "description": "Filtra solo i ticket con priorita' alta o urgente.",
                "theme": "rose",
                "values": {
                    "field_name": "priorita",
                    "operator": AutomationConditionOperator.IN_CSV,
                    "expected_value": "alta,urgente",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
            {
                "key": "tickets_stato_changed",
                "title": "Stato cambiato",
                "description": "Verifica che lo stato del ticket sia cambiato.",
                "theme": "amber",
                "values": {
                    "field_name": "stato",
                    "operator": AutomationConditionOperator.CHANGED,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
            {
                "key": "tickets_assegnato_presente",
                "title": "Assegnato presente",
                "description": "Verifica che il ticket abbia un assegnatario.",
                "theme": "slate",
                "values": {
                    "field_name": "assegnato_a",
                    "operator": AutomationConditionOperator.IS_NOT_EMPTY,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
        ]

    elif source_code_value == "assets":
        suggestions["base"]["group_title"] = "Preset condizioni per Assets"
        suggestions["base"]["group_subtitle"] = "Preset per stato, categoria e assegnazione asset."
        suggestions["base"]["values"]["field_name"] = "status"
        suggestions["base"]["values"]["expected_value"] = "active"
        suggestions["base"]["values"]["value_type"] = AutomationConditionValueType.STRING
        suggestions["base"]["presets"] = [
            {
                "key": "assets_status_changed",
                "title": "Stato cambiato",
                "description": "Reagisce quando lo stato dell'asset cambia.",
                "theme": "blue",
                "values": {
                    "field_name": "status",
                    "operator": AutomationConditionOperator.CHANGED,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
            {
                "key": "assets_assigned",
                "title": "Assegnatario presente",
                "description": "Verifica che l'asset abbia un assegnatario.",
                "theme": "amber",
                "values": {
                    "field_name": "assigned_legacy_user_id",
                    "operator": AutomationConditionOperator.IS_NOT_EMPTY,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.INT,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
            {
                "key": "assets_tag_valorizzato",
                "title": "Codice asset valorizzato",
                "description": "Verifica che l'asset abbia un codice (asset_tag).",
                "theme": "slate",
                "values": {
                    "field_name": "asset_tag",
                    "operator": AutomationConditionOperator.IS_NOT_EMPTY,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
        ]

    elif source_code_value == "anomalie":
        suggestions["base"]["group_title"] = "Preset condizioni per Anomalie"
        suggestions["base"]["group_subtitle"] = "Preset per avanzamento, chiusura e identificazione anomalie."
        suggestions["base"]["values"]["field_name"] = "avanzamento"
        suggestions["base"]["values"]["expected_value"] = "chiusa"
        suggestions["base"]["values"]["value_type"] = AutomationConditionValueType.STRING
        suggestions["base"]["presets"] = [
            {
                "key": "anomalie_chiusa",
                "title": "Anomalia chiusa",
                "description": "Reagisce quando l'avanzamento passa a 'chiusa'.",
                "theme": "green",
                "values": {
                    "field_name": "avanzamento",
                    "operator": AutomationConditionOperator.CHANGED_TO,
                    "expected_value": "chiusa",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
            {
                "key": "anomalie_da_chiudere",
                "title": "Da chiudere",
                "description": "Verifica che il flag 'chiudere' sia attivo.",
                "theme": "rose",
                "values": {
                    "field_name": "chiudere",
                    "operator": AutomationConditionOperator.EQUALS,
                    "expected_value": "True",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
            {
                "key": "anomalie_stato_changed",
                "title": "Avanzamento cambiato",
                "description": "Reagisce quando l'avanzamento dell'anomalia cambia.",
                "theme": "amber",
                "values": {
                    "field_name": "avanzamento",
                    "operator": AutomationConditionOperator.CHANGED,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
            {
                "key": "anomalie_op_presente",
                "title": "OP valorizzato",
                "description": "Verifica che l'ordine di produzione sia valorizzato.",
                "theme": "slate",
                "values": {
                    "field_name": "ex_op_nominativo",
                    "operator": AutomationConditionOperator.IS_NOT_EMPTY,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
        ]

    elif source_code_value == "notizie":
        suggestions["base"]["group_title"] = "Preset condizioni per Notizie"
        suggestions["base"]["group_subtitle"] = "Preset per stato pubblicazione e obbligatorietà."
        suggestions["base"]["values"]["field_name"] = "stato"
        suggestions["base"]["values"]["expected_value"] = "pubblicata"
        suggestions["base"]["values"]["value_type"] = AutomationConditionValueType.STRING
        suggestions["base"]["presets"] = [
            {
                "key": "notizie_pubblicata",
                "title": "Notizia pubblicata",
                "description": "Reagisce quando la notizia passa allo stato 'pubblicata'.",
                "theme": "blue",
                "values": {
                    "field_name": "stato",
                    "operator": AutomationConditionOperator.CHANGED_TO,
                    "expected_value": "pubblicata",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
            {
                "key": "notizie_obbligatoria",
                "title": "Obbligatoria",
                "description": "Filtra solo le notizie con conferma obbligatoria.",
                "theme": "rose",
                "values": {
                    "field_name": "obbligatoria",
                    "operator": AutomationConditionOperator.EQUALS,
                    "expected_value": "True",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
            {
                "key": "notizie_stato_changed",
                "title": "Stato cambiato",
                "description": "Reagisce a qualsiasi cambio di stato della notizia.",
                "theme": "amber",
                "values": {
                    "field_name": "stato",
                    "operator": AutomationConditionOperator.CHANGED,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
        ]

    elif source_code_value == "diario_preposto":
        suggestions["base"]["group_title"] = "Preset condizioni per Diario Preposto"
        suggestions["base"]["group_subtitle"] = "Preset per identificare nuove segnalazioni e responsabili."
        suggestions["base"]["values"]["field_name"] = "codice_identificativo"
        suggestions["base"]["values"]["expected_value"] = ""
        suggestions["base"]["values"]["value_type"] = AutomationConditionValueType.STRING
        suggestions["base"]["presets"] = [
            {
                "key": "diario_preposto_codice_presente",
                "title": "Codice valorizzato",
                "description": "Verifica che la segnalazione abbia un codice identificativo.",
                "theme": "blue",
                "values": {
                    "field_name": "codice_identificativo",
                    "operator": AutomationConditionOperator.IS_NOT_EMPTY,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
            {
                "key": "diario_preposto_preposto_presente",
                "title": "Preposto valorizzato",
                "description": "Verifica che il preposto sia indicato nella segnalazione.",
                "theme": "amber",
                "values": {
                    "field_name": "preposto",
                    "operator": AutomationConditionOperator.IS_NOT_EMPTY,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
        ]

    elif source_code_value == "rilevazione_incidenti":
        suggestions["base"]["group_title"] = "Preset condizioni per Incidenti / Sicurezza"
        suggestions["base"]["group_subtitle"] = "Preset per tipologia, stato approvazione e chiusura RSPP."
        suggestions["base"]["values"]["field_name"] = "chiusura_rspp"
        suggestions["base"]["values"]["expected_value"] = "True"
        suggestions["base"]["values"]["value_type"] = AutomationConditionValueType.STRING
        suggestions["base"]["presets"] = [
            {
                "key": "incidenti_chiuso_rspp",
                "title": "Chiuso RSPP",
                "description": "Reagisce quando l'incidente viene chiuso dal RSPP.",
                "theme": "green",
                "values": {
                    "field_name": "chiusura_rspp",
                    "operator": AutomationConditionOperator.CHANGED_TO,
                    "expected_value": "True",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
            {
                "key": "incidenti_tipologia_accident",
                "title": "Tipologia Accident",
                "description": "Filtra solo gli eventi di tipo Accident (più gravi).",
                "theme": "rose",
                "values": {
                    "field_name": "tipologia_scheda",
                    "operator": AutomationConditionOperator.EQUALS,
                    "expected_value": "Accident",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
            {
                "key": "incidenti_approvazione_rls",
                "title": "RLS approvato",
                "description": "Verifica che l'approvazione RLS sia valorizzata.",
                "theme": "blue",
                "values": {
                    "field_name": "approvazione_rls",
                    "operator": AutomationConditionOperator.IS_NOT_EMPTY,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
        ]

    elif source_code_value == "rentri":
        suggestions["base"]["group_title"] = "Preset condizioni per RENTRI / Rifiuti"
        suggestions["base"]["group_subtitle"] = "Preset per tipo movimento e flag trasmissione RENTRI."
        suggestions["base"]["values"]["field_name"] = "rentri_si_no"
        suggestions["base"]["values"]["expected_value"] = "True"
        suggestions["base"]["values"]["value_type"] = AutomationConditionValueType.STRING
        suggestions["base"]["presets"] = [
            {
                "key": "rentri_da_trasmettere",
                "title": "Da trasmettere RENTRI",
                "description": "Filtra solo i movimenti flaggati per trasmissione RENTRI.",
                "theme": "amber",
                "values": {
                    "field_name": "rentri_si_no",
                    "operator": AutomationConditionOperator.EQUALS,
                    "expected_value": "True",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
            {
                "key": "rentri_tipo_carico",
                "title": "Tipo carico (C)",
                "description": "Filtra solo i movimenti di tipo carico.",
                "theme": "blue",
                "values": {
                    "field_name": "tipo",
                    "operator": AutomationConditionOperator.EQUALS,
                    "expected_value": "C",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
            {
                "key": "rentri_codice_valorizzato",
                "title": "Codice rifiuto valorizzato",
                "description": "Verifica che il codice CER sia valorizzato.",
                "theme": "slate",
                "values": {
                    "field_name": "codice",
                    "operator": AutomationConditionOperator.IS_NOT_EMPTY,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
        ]

    elif source_code_value == "dpi":
        suggestions["base"]["group_title"] = "Preset condizioni per DPI"
        suggestions["base"]["group_subtitle"] = "Preset per stato richiesta e workflow approvazione/consegna."
        suggestions["base"]["values"]["field_name"] = "stato"
        suggestions["base"]["values"]["expected_value"] = "APPROVATA"
        suggestions["base"]["values"]["value_type"] = AutomationConditionValueType.STRING
        suggestions["base"]["presets"] = [
            {
                "key": "dpi_stato_approvata",
                "title": "Richiesta approvata",
                "description": "Reagisce quando la richiesta DPI passa ad APPROVATA.",
                "theme": "green",
                "values": {
                    "field_name": "stato",
                    "operator": AutomationConditionOperator.CHANGED_TO,
                    "expected_value": "APPROVATA",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
            {
                "key": "dpi_stato_rifiutata",
                "title": "Richiesta rifiutata",
                "description": "Reagisce quando la richiesta DPI viene rifiutata.",
                "theme": "rose",
                "values": {
                    "field_name": "stato",
                    "operator": AutomationConditionOperator.CHANGED_TO,
                    "expected_value": "RIFIUTATA",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
            {
                "key": "dpi_stato_consegnata",
                "title": "DPI consegnato",
                "description": "Reagisce quando la richiesta DPI passa a CONSEGNATA.",
                "theme": "blue",
                "values": {
                    "field_name": "stato",
                    "operator": AutomationConditionOperator.CHANGED_TO,
                    "expected_value": "CONSEGNATA",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
            {
                "key": "dpi_stato_changed",
                "title": "Stato cambiato",
                "description": "Reagisce a qualsiasi cambio di stato della richiesta DPI.",
                "theme": "amber",
                "values": {
                    "field_name": "stato",
                    "operator": AutomationConditionOperator.CHANGED,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
        ]

    elif source_code_value == "procedure_campagne":
        suggestions["base"]["group_title"] = "Preset condizioni per Campagne Procedure"
        suggestions["base"]["group_subtitle"] = "Preset per pubblicazione, chiusura e scadenza campagne."
        suggestions["base"]["values"]["field_name"] = "status"
        suggestions["base"]["values"]["expected_value"] = "published"
        suggestions["base"]["values"]["value_type"] = AutomationConditionValueType.STRING
        suggestions["base"]["presets"] = [
            {
                "key": "procedure_campagna_pubblicata",
                "title": "Campagna pubblicata",
                "description": "Reagisce quando la campagna viene pubblicata.",
                "theme": "blue",
                "values": {
                    "field_name": "status",
                    "operator": AutomationConditionOperator.CHANGED_TO,
                    "expected_value": "published",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
            {
                "key": "procedure_campagna_chiusa",
                "title": "Campagna chiusa",
                "description": "Reagisce quando la campagna viene chiusa.",
                "theme": "green",
                "values": {
                    "field_name": "status",
                    "operator": AutomationConditionOperator.CHANGED_TO,
                    "expected_value": "closed",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
            {
                "key": "procedure_campagna_scadenza_valorizzata",
                "title": "Scadenza valorizzata",
                "description": "Verifica che la campagna abbia una data di scadenza.",
                "theme": "amber",
                "values": {
                    "field_name": "due_date",
                    "operator": AutomationConditionOperator.IS_NOT_EMPTY,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
        ]

    elif source_code_value == "procedure_assegnazioni":
        suggestions["base"]["group_title"] = "Preset condizioni per Assegnazioni Procedure"
        suggestions["base"]["group_subtitle"] = "Preset per stato lettura, conferma e scadenza."
        suggestions["base"]["values"]["field_name"] = "status"
        suggestions["base"]["values"]["expected_value"] = "read_confirmed"
        suggestions["base"]["values"]["value_type"] = AutomationConditionValueType.STRING
        suggestions["base"]["presets"] = [
            {
                "key": "procedure_confermata",
                "title": "Lettura confermata",
                "description": "Reagisce quando l'utente conferma la lettura della procedura.",
                "theme": "green",
                "values": {
                    "field_name": "status",
                    "operator": AutomationConditionOperator.CHANGED_TO,
                    "expected_value": "read_confirmed",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
            {
                "key": "procedure_overdue",
                "title": "Scaduta (overdue)",
                "description": "Reagisce quando l'assegnazione diventa overdue.",
                "theme": "rose",
                "values": {
                    "field_name": "status",
                    "operator": AutomationConditionOperator.CHANGED_TO,
                    "expected_value": "overdue",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": True,
                    "is_enabled": True,
                },
            },
            {
                "key": "procedure_non_ancora_confermata",
                "title": "Non ancora confermata",
                "description": "Verifica che la lettura non sia ancora stata confermata.",
                "theme": "amber",
                "values": {
                    "field_name": "read_confirmed_flag",
                    "operator": AutomationConditionOperator.EQUALS,
                    "expected_value": "False",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
            {
                "key": "procedure_scadenza_valorizzata",
                "title": "Scadenza valorizzata",
                "description": "Verifica che l'assegnazione abbia una data di scadenza.",
                "theme": "slate",
                "values": {
                    "field_name": "due_date",
                    "operator": AutomationConditionOperator.IS_NOT_EMPTY,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            },
        ]

    else:
        suggestions["base"]["presets"].append(
            {
                "key": "default_owner_present",
                "title": "Responsabile presente",
                "description": f"Verifica che `{owner_field}` sia valorizzato.",
                "theme": "amber",
                "values": {
                    "field_name": owner_field,
                    "operator": AutomationConditionOperator.IS_NOT_EMPTY,
                    "expected_value": "",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "is_enabled": True,
                },
            }
        )
    return suggestions


def _describe_trigger_values(
    *,
    source_code: str,
    operation_type: str,
    trigger_scope: str,
    watched_field: str,
    is_active: bool,
    is_draft: bool,
    stop_on_first_failure: bool,
) -> dict[str, object]:
    source = get_source_definition(source_code) or {"code": source_code, "label": source_code or "sorgente"}
    source_label = _string_value(source.get("label")) or _string_value(source.get("code")) or "sorgente"
    operation_text = {
        AutomationRuleOperationType.INSERT: "viene creato",
        AutomationRuleOperationType.UPDATE: "viene aggiornato",
    }.get(operation_type, f"riceve l'evento {operation_type}")
    trigger_scope_detail = {
        AutomationRuleTriggerScope.ALL_INSERTS: "su ogni inserimento",
        AutomationRuleTriggerScope.ALL_UPDATES: "su ogni aggiornamento",
        AutomationRuleTriggerScope.ANY_CHANGE: "quando cambia almeno un campo",
        AutomationRuleTriggerScope.SPECIFIC_FIELD: (
            f"solo quando cambia il campo `{watched_field}`" if watched_field else "su campo specifico"
        ),
    }.get(trigger_scope, trigger_scope or "-")
    status_parts = []
    status_parts.append("regola attiva" if is_active and not is_draft else "regola non eseguibile")
    if is_draft:
        status_parts.append("bozza")
    if stop_on_first_failure:
        status_parts.append("stop al primo errore")
    watched_line = f"e il campo `{watched_field}` è monitorato" if watched_field else ""
    return {
        "source_label": source_label,
        "is_active": is_active,
        "is_draft": is_draft,
        "operation_label": _choice_label(AutomationRuleOperationType, operation_type),
        "trigger_scope_label": _choice_label(AutomationRuleTriggerScope, trigger_scope),
        "status_text": ", ".join(status_parts),
        "headline": f"Quando un record di {source_label} {operation_text}",
        "watched_line": watched_line,
        "natural_when": f"QUANDO un record di {source_label} {operation_text}",
        "natural_scope": (
            f"SE il trigger è `{trigger_scope}` sul campo `{watched_field}`"
            if watched_field
            else f"SE il trigger è `{trigger_scope}`"
        ),
        "scope_detail": trigger_scope_detail,
    }


def _describe_condition_values(
    *,
    source_code: str,
    order,
    field_name: str,
    operator: str,
    expected_value: str,
    value_type: str,
    compare_with_old: bool,
    is_enabled: bool,
    marked_for_delete: bool,
    item_id: int | None,
):
    label_map = _field_label_map(source_code)
    field_label = label_map.get(field_name, field_name or "Campo")
    expected_text = _truncate_text(expected_value or "-", 90)
    summary = f"{field_name or 'campo'} {operator or 'operatore'}"
    if _string_value(expected_value):
        summary = f"{summary} {expected_text}"
    badges = []
    if compare_with_old:
        badges.append("old/new")
    badges.append("abilitata" if is_enabled else "disabilitata")
    if marked_for_delete:
        badges.append("da eliminare")
    return {
        "item_id": item_id,
        "order_value": order or "-",
        "field_name": field_name,
        "field_label": field_label,
        "operator": operator,
        "operator_label": _choice_label(AutomationConditionOperator, operator) if operator else "",
        "expected_value": expected_value,
        "summary": summary,
        "human_summary": f"{field_label} • {_choice_label(AutomationConditionOperator, operator)}",
        "expected_preview": expected_text,
        "badges": badges,
    }


def _describe_action_values(
    *,
    order,
    action_type: str,
    is_enabled: bool,
    description: str,
    item_id: int | None,
    marked_for_delete: bool,
    preview_lines: list[str],
):
    badges = ["abilitata" if is_enabled else "disabilitata"]
    if marked_for_delete:
        badges.append("da eliminare")
    return {
        "item_id": item_id,
        "order_value": order or "-",
        "action_label": _choice_label(AutomationActionType, action_type),
        "summary": _truncate_text(description or _choice_label(AutomationActionType, action_type), 100),
        "preview_lines": preview_lines,
        "badges": badges,
    }


def _build_action_preview_from_form(form) -> list[str]:
    action_type = _string_value(_bound_or_instance_value(form, "action_type"))
    preview_lines: list[str]
    if action_type == AutomationActionType.SEND_EMAIL:
        recipients = _truncate_text(_bound_or_instance_value(form, "email_to"), 80) or "-"
        subject = _truncate_text(_bound_or_instance_value(form, "email_subject_template"), 80) or "-"
        body = _truncate_text(_bound_or_instance_value(form, "email_body_text_template"), 90) or "-"
        preview_lines = [
            f"Destinatari: {recipients}",
            f"Subject: {subject}",
            f"Body: {body}",
        ]
    elif action_type == AutomationActionType.WRITE_LOG:
        preview_lines = [f"Messaggio: {_truncate_text(_bound_or_instance_value(form, 'write_log_message_template'), 120) or '-'}"]
    elif action_type == AutomationActionType.UPDATE_DASHBOARD_METRIC:
        metric_code = _truncate_text(_bound_or_instance_value(form, "metric_code"), 80) or "-"
        operation = _truncate_text(_bound_or_instance_value(form, "metric_operation"), 80) or "-"
        value_template = _truncate_text(_bound_or_instance_value(form, "metric_value_template"), 80) or "-"
        preview_lines = [
            f"Metrica: {metric_code}",
            f"Operazione: {operation}",
            f"Valore: {value_template}",
        ]
    elif action_type == AutomationActionType.INSERT_RECORD:
        target_table = _truncate_text(_bound_or_instance_value(form, "insert_target_table"), 80) or "-"
        mappings_text = _string_value(_bound_or_instance_value(form, "insert_field_mappings_text"))
        mappings_count = len([line for line in mappings_text.splitlines() if _string_value(line)])
        preview_lines = [
            f"Tabella: {target_table}",
            f"Field mappings: {mappings_count}",
        ]
    elif action_type == AutomationActionType.UPDATE_RECORD:
        target_table = _truncate_text(_bound_or_instance_value(form, "update_target_table"), 80) or "-"
        where_field = _truncate_text(_bound_or_instance_value(form, "update_where_field"), 80) or "-"
        update_fields_text = _string_value(_bound_or_instance_value(form, "update_fields_text"))
        update_fields_count = len([line for line in update_fields_text.splitlines() if _string_value(line)])
        preview_lines = [
            f"Tabella: {target_table}",
            f"Where field: {where_field}",
            f"Update fields: {update_fields_count}",
        ]
    elif action_type == AutomationActionType.UPDATE_TRIGGER_RECORD:
        update_fields_text = _string_value(_bound_or_instance_value(form, "trigger_update_fields_text"))
        update_fields_count = len([line for line in update_fields_text.splitlines() if _string_value(line)])
        preview_lines = [
            "Target: record triggerante",
            f"Update fields: {update_fields_count}",
        ]
    elif action_type == AutomationActionType.SPLIT_ASSENZA_GIORNALIERA:
        start_field = _truncate_text(_bound_or_instance_value(form, "split_start_field"), 60) or "data_inizio"
        end_field = _truncate_text(_bound_or_instance_value(form, "split_end_field"), 60) or "data_fine"
        max_days = _truncate_text(_bound_or_instance_value(form, "split_max_days"), 20) or "60"
        tipo_template = _truncate_text(_bound_or_instance_value(form, "split_tipo_assenza_template"), 80) or "Permesso"
        preview_lines = [
            f"Periodo: {start_field} -> {end_field}",
            f"Max giorni creati: {max_days}",
            f"Tipo righe create: {tipo_template}",
            f"Deduplica: {'si' if _bool_value(_bound_or_instance_value(form, 'split_dedupe')) else 'no'}",
        ]
    elif action_type == AutomationActionType.DELAY_SCHEDULE:
        delay_mode = _string_value(_bound_or_instance_value(form, "delay_mode")) or "relative"
        if delay_mode == "until":
            preview_lines = [f"Fino a: {_truncate_text(_bound_or_instance_value(form, 'delay_until_template'), 100) or '-'}"]
        else:
            delay_value = _truncate_text(_bound_or_instance_value(form, "delay_value_template"), 80) or "-"
            delay_unit = _truncate_text(_bound_or_instance_value(form, "delay_unit"), 80) or "-"
            preview_lines = [f"Delay: {delay_value} {delay_unit}"]
    elif action_type == AutomationActionType.HTTP_REQUEST:
        method = _truncate_text(_bound_or_instance_value(form, "http_method"), 30) or "-"
        url = _truncate_text(_bound_or_instance_value(form, "http_url_template"), 100) or "-"
        expected = _truncate_text(_bound_or_instance_value(form, "http_expected_status_csv"), 80) or "2xx"
        preview_lines = [
            f"HTTP: {method} {url}",
            f"Status attesi: {expected}",
        ]
    elif action_type == AutomationActionType.TEAMS_WEBHOOK:
        title = _truncate_text(_bound_or_instance_value(form, "teams_title_template"), 100) or "-"
        summary = _truncate_text(_bound_or_instance_value(form, "teams_summary_template"), 100) or "-"
        preview_lines = [
            f"Teams title: {title}",
            f"Summary: {summary}",
        ]
    elif action_type == AutomationActionType.SEND_APPROVAL:
        delivery_mode = _string_value(_bound_or_instance_value(form, "approval_delivery_mode")) or "email"
        email_to = _truncate_text(_bound_or_instance_value(form, "approval_to_template"), 80) or "-"
        teams_recipient = _truncate_text(_bound_or_instance_value(form, "approval_teams_recipient_email_template"), 80) or "-"
        subject = _truncate_text(_bound_or_instance_value(form, "approval_subject_template"), 90) or "-"
        approved_update_count = len(
            [
                line
                for line in _string_value(_bound_or_instance_value(form, "approval_approved_update_fields_text")).splitlines()
                if _string_value(line)
            ]
        )
        rejected_update_count = len(
            [
                line
                for line in _string_value(_bound_or_instance_value(form, "approval_rejected_update_fields_text")).splitlines()
                if _string_value(line)
            ]
        )
        approved_actions_count = approved_update_count + _safe_json_array_length(
            _bound_or_instance_value(form, "approval_approved_actions_json")
        )
        rejected_actions_count = rejected_update_count + _safe_json_array_length(
            _bound_or_instance_value(form, "approval_rejected_actions_json")
        )
        preview_lines = [
            f"Recapito: {delivery_mode}",
            f"Email approvatori: {email_to}",
            f"Destinatario Teams: {teams_recipient}",
            f"Oggetto: {subject}",
            f"Se approvato: {approved_actions_count} azioni",
            f"Se rifiutato: {rejected_actions_count} azioni",
        ]
    elif action_type == AutomationActionType.DO_UNTIL:
        check_field = _truncate_text(_bound_or_instance_value(form, "loop_check_field"), 60) or "-"
        check_operator = _truncate_text(_bound_or_instance_value(form, "loop_check_operator"), 40) or "-"
        check_value = _truncate_text(_bound_or_instance_value(form, "loop_check_value"), 60)
        retry_value = _truncate_text(_bound_or_instance_value(form, "loop_retry_delay_value"), 20) or "24"
        retry_unit = _truncate_text(_bound_or_instance_value(form, "loop_retry_delay_unit"), 20) or "hours"
        max_iterations = _truncate_text(_bound_or_instance_value(form, "loop_max_iterations"), 20) or "10"
        condition_line = f"Uscita: {check_field} {check_operator}".strip()
        if check_value:
            condition_line += f" {check_value}"
        preview_lines = [
            condition_line,
            f"Retry: {retry_value} {retry_unit}",
            f"Max iterazioni: {max_iterations}",
            f"Corpo loop: {_safe_json_array_length(_bound_or_instance_value(form, 'loop_loop_actions_json'))} azioni",
            "Successo/timeout: "
            f"{_safe_json_array_length(_bound_or_instance_value(form, 'loop_on_success_actions_json'))}"
            "/"
            f"{_safe_json_array_length(_bound_or_instance_value(form, 'loop_on_timeout_actions_json'))}",
        ]
    elif action_type == AutomationActionType.FOR_EACH:
        source_code = _truncate_text(_bound_or_instance_value(form, "each_source_code"), 60) or "-"
        filter_field = _truncate_text(_bound_or_instance_value(form, "each_filter_field"), 60)
        filter_value = _truncate_text(_bound_or_instance_value(form, "each_filter_value_template"), 60)
        max_items = _truncate_text(_bound_or_instance_value(form, "each_max_items"), 20) or "50"
        preview_lines = [
            f"Sorgente: {source_code}",
            f"Filtro: {filter_field or '-'}" + (f" = {filter_value}" if filter_field and filter_value else ""),
            f"Azioni per elemento: {_safe_json_array_length(_bound_or_instance_value(form, 'each_actions_json'))}",
            f"Max elementi: {max_items}",
        ]
    elif action_type == AutomationActionType.BRANCH:
        branch_field = _truncate_text(_bound_or_instance_value(form, "branch_condition_field"), 60) or "-"
        branch_operator = _truncate_text(_bound_or_instance_value(form, "branch_condition_operator"), 40) or "-"
        branch_value = _truncate_text(_bound_or_instance_value(form, "branch_condition_value"), 60)
        compare_with_old = _bool_value(_bound_or_instance_value(form, "branch_compare_with_old"))
        condition_line = f"If: {branch_field} {branch_operator}".strip()
        if branch_value:
            condition_line += f" {branch_value}"
        preview_lines = [
            condition_line,
            f"Se vero: {_safe_json_array_length(_bound_or_instance_value(form, 'branch_if_true_actions_json'))} azioni",
            f"Se falso: {_safe_json_array_length(_bound_or_instance_value(form, 'branch_if_false_actions_json'))} azioni",
        ]
        if compare_with_old:
            preview_lines.append("Confronta con old payload")
    else:
        preview_lines = ["Configurazione non disponibile."]

    run_if_field = _string_value(_bound_or_instance_value(form, "run_if_field_name"))
    run_if_operator = _string_value(_bound_or_instance_value(form, "run_if_operator"))
    run_if_expected = _truncate_text(_bound_or_instance_value(form, "run_if_expected_value"), 80)
    run_if_negate = _bool_value(_bound_or_instance_value(form, "run_if_negate"))
    if any([run_if_field, run_if_operator, run_if_expected, run_if_negate]):
        branch_line = "Branch: "
        if run_if_negate:
            branch_line += "NOT "
        branch_line += f"{run_if_field or 'campo'} {run_if_operator or 'operatore'}"
        if run_if_expected:
            branch_line += f" {run_if_expected}"
        preview_lines.append(branch_line)
    return preview_lines


def _build_condition_entries(condition_formset, *, source_code: str) -> list[dict[str, object]]:
    entries = []
    for index, form in enumerate(condition_formset.forms, start=1):
        marked_for_delete = _bool_value(form["DELETE"].value()) if "DELETE" in form.fields else False
        order = _string_value(_bound_or_instance_value(form, "order"))
        field_name = _string_value(_bound_or_instance_value(form, "field_name"))
        operator = _string_value(_bound_or_instance_value(form, "operator"))
        expected_value = _string_value(_bound_or_instance_value(form, "expected_value"))
        value_type = _string_value(_bound_or_instance_value(form, "value_type"))
        compare_with_old = _bool_value(_bound_or_instance_value(form, "compare_with_old"))
        is_enabled = _bool_value(_bound_or_instance_value(form, "is_enabled"))
        descriptor = _describe_condition_values(
            source_code=source_code,
            order=order,
            field_name=field_name,
            operator=operator,
            expected_value=expected_value,
            value_type=value_type,
            compare_with_old=compare_with_old,
            is_enabled=is_enabled,
            marked_for_delete=marked_for_delete,
            item_id=form.instance.pk,
        )
        entries.append(
            {
                "form": form,
                "index": index,
                "is_existing": bool(form.instance.pk),
                "has_content": any([order, field_name, operator, expected_value, value_type]),
                "marked_for_delete": marked_for_delete,
                "descriptor": descriptor,
                "meta_rows": [
                    ("Order", order or "-"),
                    ("field_name", field_name or "-"),
                    ("operator", operator or "-"),
                    ("expected_value", expected_value or "-"),
                    ("value_type", value_type or "-"),
                    ("compare_with_old", "Si" if compare_with_old else "No"),
                    ("is_enabled", "Si" if is_enabled else "No"),
                ],
            }
        )
    return entries


def _build_action_entries(action_formset) -> list[dict[str, object]]:
    entries = []
    for index, form in enumerate(action_formset.forms, start=1):
        marked_for_delete = _bool_value(form["DELETE"].value()) if "DELETE" in form.fields else False
        order = _string_value(_bound_or_instance_value(form, "order"))
        action_type = _string_value(_bound_or_instance_value(form, "action_type"))
        is_enabled = _bool_value(_bound_or_instance_value(form, "is_enabled"))
        description = _string_value(_bound_or_instance_value(form, "description"))
        run_if_field = _string_value(_bound_or_instance_value(form, "run_if_field_name"))
        run_if_operator = _string_value(_bound_or_instance_value(form, "run_if_operator"))
        run_if_negate = _bool_value(_bound_or_instance_value(form, "run_if_negate"))
        preview_lines = _build_action_preview_from_form(form)
        descriptor = _describe_action_values(
            order=order,
            action_type=action_type,
            is_enabled=is_enabled,
            description=description,
            item_id=form.instance.pk,
            marked_for_delete=marked_for_delete,
            preview_lines=preview_lines,
        )
        entries.append(
            {
                "form": form,
                "index": index,
                "is_existing": bool(form.instance.pk),
                "has_content": any([order, action_type, description]),
                "marked_for_delete": marked_for_delete,
                "descriptor": descriptor,
                "meta_rows": [
                    ("Order", order or "-"),
                    ("action_type", action_type or "-"),
                    ("branch", "Si" if any([run_if_field, run_if_operator, run_if_negate]) else "No"),
                    ("is_enabled", "Si" if is_enabled else "No"),
                ],
            }
        )
    return entries


def _build_empty_action_entry(action_formset) -> dict[str, object]:
    empty_form = action_formset.empty_form
    return {
        "form": empty_form,
        "index": None,
        "is_existing": False,
        "has_content": False,
        "marked_for_delete": False,
        "descriptor": _describe_action_values(
            order="",
            action_type="",
            is_enabled=True,
            description="Nuova azione",
            item_id=None,
            marked_for_delete=False,
            preview_lines=_build_action_preview_from_form(empty_form),
        ),
        "meta_rows": [],
    }


def _build_human_rule_summary(trigger_descriptor: dict[str, object], condition_entries, action_entries) -> dict[str, object]:
    active_conditions = [entry for entry in condition_entries if entry["descriptor"]["field_label"] != "Campo" and not entry["marked_for_delete"]]
    active_actions = [
        entry
        for entry in action_entries
        if _string_value(entry["descriptor"]["action_label"]) != "-" and not entry["marked_for_delete"]
    ]
    if active_conditions:
        condition_line = "E tutte le condizioni risultano vere"
    else:
        condition_line = "E senza condizioni aggiuntive"
    then_lines = [f"- {entry['descriptor']['action_label']}" for entry in active_actions] or ["- nessuna azione configurata"]
    return {
        "when": trigger_descriptor["natural_when"],
        "scope": trigger_descriptor["natural_scope"],
        "condition_line": condition_line,
        "then_lines": then_lines,
    }


def _reorder_rule_items(*, rule: AutomationRule, model, ordered_ids: list[int]) -> None:
    current_ids = list(model.objects.filter(rule=rule).order_by("order", "id").values_list("id", flat=True))
    if not ordered_ids:
        raise ValueError("Ordine vuoto.")
    if len(ordered_ids) != len(set(ordered_ids)):
        raise ValueError("Ordine duplicato.")
    if sorted(current_ids) != sorted(ordered_ids):
        raise ValueError("Ordine incoerente con gli elementi della regola.")
    with transaction.atomic():
        for position, item_id in enumerate(ordered_ids, start=1):
            model.objects.filter(rule=rule, pk=item_id).update(order=position)


def _extract_ordered_ids(request) -> list[int]:
    raw_ids = request.POST.getlist("ordered_ids") or request.POST.getlist("ordered_ids[]")
    if not raw_ids:
        payload = _string_value(request.POST.get("ordered_ids_json"))
        if payload:
            raw_ids = json.loads(payload)
    try:
        return [int(value) for value in raw_ids]
    except (TypeError, ValueError):
        raise ValueError("Identificativi ordine non validi.")


def _build_all_source_fields_json() -> dict[str, object]:
    result: dict[str, object] = {}
    for source in get_registered_sources():
        code = str(source["code"])
        example_payload = build_example_payload(code)
        all_fields = get_source_fields(code)
        trigger_fields = get_trigger_fields(code)
        condition_fields = get_condition_fields(code)
        template_fields = get_template_fields(code)
        action_mapping_fields = get_action_mapping_fields(code)
        result[code] = {
            "code": code,
            "label": _string_value(source.get("label")),
            "description": _string_value(source.get("description")),
            "supported_operations": [str(value) for value in (source.get("supported_operations") or [])],
            "trigger": [
                {"name": str(f["name"]), "label": f"{f['label']} ({f['name']})"}
                for f in trigger_fields
            ],
            "condition": [
                {"name": str(f["name"]), "label": f"{f['label']} ({f['name']})"}
                for f in condition_fields
            ],
            "all": [
                _serialize_source_field_detail(field, sample_value=example_payload.get(_string_value(field.get("name"))))
                for field in all_fields
            ],
            "template": [
                _serialize_source_field_detail(field, sample_value=example_payload.get(_string_value(field.get("name"))))
                for field in template_fields
            ],
            "action_mapping": [
                _serialize_source_field_detail(field, sample_value=example_payload.get(_string_value(field.get("name"))))
                for field in action_mapping_fields
            ],
            "placeholder_examples": [f"{{{_string_value(field.get('name'))}}}" for field in template_fields],
            "example_payload": example_payload,
        }
    return result


def _build_source_catalog_context(selected_source_code: str | None) -> dict[str, object]:
    selected = str(selected_source_code or "").strip() or _get_default_source_code()
    panels = []
    for source in get_registered_sources():
        code = str(source["code"])
        panels.append(
            {
                **source,
                "all_fields": get_source_fields(code),
                "trigger_fields": get_trigger_fields(code),
                "condition_fields": get_condition_fields(code),
                "template_fields": get_template_fields(code),
                "action_mapping_fields": get_action_mapping_fields(code),
                "placeholder_examples": build_placeholder_examples(code),
            }
        )
    return {
        "source_catalog_panels": panels,
        "selected_source_code": selected,
    }


def _get_rule_source_code(request, rule: AutomationRule | None = None) -> str:
    if request.method == "POST":
        return str(request.POST.get("source_code") or "").strip() or (rule.source_code if rule else "") or _get_default_source_code()
    requested = str(request.GET.get("source_code") or "").strip()
    if requested:
        return requested
    if rule and rule.source_code:
        return rule.source_code
    return _get_default_source_code()


def _build_rule_filters_context(request) -> dict[str, str]:
    return {
        "source_code": _get_filter_value(request, "source_code"),
        "operation_type": _get_filter_value(request, "operation_type"),
        "is_active": _get_filter_value(request, "is_active"),
        "is_draft": _get_filter_value(request, "is_draft"),
    }


def _apply_rule_filters(queryset, filters: dict[str, str]):
    if filters["source_code"]:
        queryset = queryset.filter(source_code=filters["source_code"])
    if filters["operation_type"]:
        queryset = queryset.filter(operation_type=filters["operation_type"])
    if filters["is_active"] in {"true", "false"}:
        queryset = queryset.filter(is_active=filters["is_active"] == "true")
    if filters["is_draft"] in {"true", "false"}:
        queryset = queryset.filter(is_draft=filters["is_draft"] == "true")
    return queryset


def _build_rule_form_context(
    *,
    rule_form,
    condition_formset,
    action_formset,
    page_title: str,
    page_subtitle: str,
    submit_label: str,
    selected_source_code: str,
    rule: AutomationRule | None = None,
):
    teams_flow_endpoints, teams_flow_endpoints_warning = _get_teams_flow_endpoints_context(active_only=True)
    return {
        **_base_context(),
        **_build_source_catalog_context(selected_source_code),
        "rule_form": rule_form,
        "condition_formset": condition_formset,
        "action_formset": action_formset,
        "page_title": page_title,
        "page_subtitle": page_subtitle,
        "submit_label": submit_label,
        "rule": rule,
        "source_fields_json": _build_all_source_fields_json(),
        "teams_presets": _get_active_teams_presets(),
        "teams_flow_endpoints": teams_flow_endpoints,
        "teams_flow_endpoints_warning": teams_flow_endpoints_warning,
    }


def _get_active_teams_presets():
    """Restituisce la lista dei TeamsWebhookPreset attivi per i template."""
    return list(TeamsWebhookPreset.objects.filter(is_active=True).order_by("name"))


def _get_active_teams_flow_endpoints():
    """Restituisce la lista degli endpoint Teams Flow attivi per i template."""
    endpoints, _warning = _get_teams_flow_endpoints_context(active_only=True)
    return endpoints


def _get_teams_flow_endpoints_context(*, active_only: bool | None = None) -> tuple[list[AutomationDeliveryEndpoint], str]:
    endpoints, unavailable = list_teams_flow_endpoints(active_only=active_only)
    return (
        endpoints,
        AUTOMATION_DELIVERY_ENDPOINT_UNAVAILABLE_MESSAGE if unavailable else "",
    )


def _build_teams_delivery_context(
    *,
    preset_form=None,
    preset_form_mode: str = "",
    edit_preset: TeamsWebhookPreset | None = None,
    flow_form=None,
    flow_form_mode: str = "",
    edit_flow_endpoint: AutomationDeliveryEndpoint | None = None,
) -> dict[str, object]:
    flow_endpoints, flow_endpoints_warning = _get_teams_flow_endpoints_context(active_only=None)
    return {
        **_base_context(),
        "presets": list(TeamsWebhookPreset.objects.order_by("name")),
        "flow_endpoints": flow_endpoints,
        "flow_endpoints_warning": flow_endpoints_warning,
        "preset_form": preset_form,
        "preset_form_mode": preset_form_mode,
        "edit_preset": edit_preset,
        "flow_form": flow_form,
        "flow_form_mode": flow_form_mode,
        "edit_flow_endpoint": edit_flow_endpoint,
    }


def _safe_runlog_count() -> int | None:
    """Numero totale di RunLog in tabella (per contesto in UI). None se non leggibile."""
    try:
        return AutomationRunLog.objects.count()
    except Exception:
        return None


def _build_automation_settings_context(
    *,
    poll_result=None,
    approval_imap_form=None,
    approval_graph_form=None,
) -> dict[str, object]:
    from .approval_email_templates import APPROVAL_MAILBOX_SITE_CONFIG_KEY
    from .scadenze_config import get_scadenze_config
    from .runlog_retention import (
        get_retention_days,
        DEFAULT_RETENTION_DAYS,
        RETENTION_MIN,
        RETENTION_MAX,
    )

    mailbox_details = get_default_approval_mailbox_details()
    active_backend = get_approval_mailbox_backend()
    return {
        **_base_context(),
        # ── Retention RunLog (GDPR) ────────────────────────────────────────
        "runlog_retention_days": get_retention_days(),
        "runlog_retention_default": DEFAULT_RETENTION_DAYS,
        "runlog_retention_min": RETENTION_MIN,
        "runlog_retention_max": RETENTION_MAX,
        "runlog_total_count": _safe_runlog_count(),
        # ── Report scadenze (visite mediche / contratti) ──────────────────
        "scadenze_config": get_scadenze_config(),
        # ── Graph (nuovo backend) ──────────────────────────────────────────
        "approval_graph_status": get_approval_graph_status(),
        "approval_graph_form": approval_graph_form or get_approval_graph_form_defaults(),
        # ── IMAP (retrocompat) ────────────────────────────────────────────
        "approval_imap_status": get_approval_imap_status(),
        "approval_imap_form": approval_imap_form or get_approval_imap_form_defaults(),
        # ── Backend attivo ────────────────────────────────────────────────
        "approval_mailbox_backend": active_backend,
        "approval_mailbox_backend_is_graph": active_backend == MAILBOX_BACKEND_GRAPH,
        "approval_mailbox_backend_is_imap": active_backend == MAILBOX_BACKEND_IMAP,
        # ── Risultato ultimo poll ─────────────────────────────────────────
        # Separati per evitare che il risultato di un backend appaia nel pannello dell'altro.
        "approval_graph_result": poll_result if active_backend == MAILBOX_BACKEND_GRAPH else None,
        "approval_imap_result": poll_result if active_backend == MAILBOX_BACKEND_IMAP else None,
        "approval_mailbox_site_config_key": APPROVAL_MAILBOX_SITE_CONFIG_KEY,
        "approval_mailbox_site_config_value": (
            str(mailbox_details["value"] or "") if mailbox_details.get("source") == "site_config" else ""
        ),
    }


def _build_rule_designer_context(
    *,
    rule: AutomationRule | None,
    rule_form,
    condition_formset,
    action_formset,
    selected_source_code: str,
):
    source_code = _string_value(rule_form["source_code"].value() if "source_code" in rule_form.fields else selected_source_code) or selected_source_code
    trigger_descriptor = _describe_trigger_values(
        source_code=source_code,
        operation_type=_string_value(_bound_or_instance_value(rule_form, "operation_type")),
        trigger_scope=_string_value(_bound_or_instance_value(rule_form, "trigger_scope")),
        watched_field=_string_value(_bound_or_instance_value(rule_form, "watched_field")),
        is_active=_bool_value(_bound_or_instance_value(rule_form, "is_active")),
        is_draft=_bool_value(_bound_or_instance_value(rule_form, "is_draft")),
        stop_on_first_failure=_bool_value(_bound_or_instance_value(rule_form, "stop_on_first_failure")),
    )
    condition_entries = _build_condition_entries(condition_formset, source_code=source_code)
    action_entries = _build_action_entries(action_formset)
    flow_nodes = _build_flow_nodes(rule, trigger_descriptor, condition_entries, action_entries)
    teams_flow_endpoints, teams_flow_endpoints_warning = _get_teams_flow_endpoints_context(active_only=True)
    return {
        **_base_context(),
        **_build_source_catalog_context(source_code),
        "enable_smart_field_panel": True,
        "rule": rule,
        "is_new_rule": not bool(getattr(rule, "pk", None)),
        "rule_form": rule_form,
        "condition_formset": condition_formset,
        "action_formset": action_formset,
        "rule_name_value": _string_value(_bound_or_instance_value(rule_form, "name")) or getattr(rule, "name", "") or "Nuova regola",
        "trigger_descriptor": trigger_descriptor,
        "condition_entries": condition_entries,
        "action_entries": action_entries,
        "existing_condition_entries": [entry for entry in condition_entries if entry["is_existing"]],
        "new_condition_entries": [entry for entry in condition_entries if not entry["is_existing"]],
        "existing_action_entries": [entry for entry in action_entries if entry["is_existing"]],
        "new_action_entries": [entry for entry in action_entries if not entry["is_existing"]],
        "empty_action_entry": _build_empty_action_entry(action_formset),
        "human_rule_summary": _build_human_rule_summary(trigger_descriptor, condition_entries, action_entries),
        "source_definition": get_source_definition(source_code),
        "sample_payload_json": _build_example_payload(source_code),
        "sample_old_payload_json": json.dumps(_build_example_old_payload(rule) or {}, indent=2, ensure_ascii=False, sort_keys=True),
        "rule_is_update": getattr(rule, "operation_type", "") == AutomationRuleOperationType.UPDATE,
        "condition_suggestions_json": _build_condition_suggestions(source_code),
        "action_suggestions_json": _build_action_suggestions(source_code),
        "source_fields_json": _build_all_source_fields_json(),
        "diagram_action_choices": _build_diagram_action_choices(),
        "flow_nodes_json": flow_nodes,
        "teams_presets": _get_active_teams_presets(),
        "teams_flow_endpoints": teams_flow_endpoints,
        "teams_flow_endpoints_warning": teams_flow_endpoints_warning,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Flow Diagram helpers
# ─────────────────────────────────────────────────────────────────────────────

_ACTION_NODE_STYLES: dict[str, dict[str, str]] = {
    "send_email":            {"icon": "✉️",  "color": "#2563eb", "bg": "#eff6ff", "app": "Email"},
    "insert_record":         {"icon": "➕",  "color": "#16a34a", "bg": "#f0fdf4", "app": "Database"},
    "update_record":         {"icon": "✏️",  "color": "#0d9488", "bg": "#f0fdfa", "app": "Database"},
    "update_trigger_record": {"icon": "🔄",  "color": "#0d9488", "bg": "#f0fdfa", "app": "Database"},
    "update_dashboard_metric":{"icon": "📊", "color": "#7c3aed", "bg": "#f5f3ff", "app": "Dashboard"},
    "write_log":             {"icon": "📝",  "color": "#475569", "bg": "#f8fafc", "app": "Log"},
    "delay_schedule":        {"icon": "⏰",  "color": "#d97706", "bg": "#fffbeb", "app": "Scheduler"},
    "http_request":          {"icon": "🌐",  "color": "#0369a1", "bg": "#f0f9ff", "app": "HTTP"},
    "teams_webhook":         {"icon": "💬",  "color": "#5b5fc7", "bg": "#eef2ff", "app": "Teams"},
    "send_approval":         {"icon": "✅",  "color": "#9333ea", "bg": "#faf5ff", "app": "Approvazione"},
    "do_until":              {"icon": "🔁",  "color": "#0891b2", "bg": "#ecfeff", "app": "Loop"},
    "for_each":              {"icon": "🔂",  "color": "#4f46e5", "bg": "#eef2ff", "app": "Iterazione"},
    "branch":                {"icon": "🔀",  "color": "#ea580c", "bg": "#fff7ed", "app": "Condizione"},
}
_DEFAULT_NODE_STYLE = {"icon": "⚡", "color": "#64748b", "bg": "#f8fafc", "app": "Azione"}


_ACTION_NODE_STYLES["split_assenza_giornaliera"] = {
    "icon": "DAY",
    "color": "#0284c7",
    "bg": "#e0f2fe",
    "app": "Assenze",
}


def _build_diagram_action_choices() -> list[dict[str, str]]:
    """Espone le azioni del flow picker gia' renderizzabili lato server."""
    items: list[dict[str, str]] = []
    for action_type, label in AutomationActionType.choices:
        style = _ACTION_NODE_STYLES.get(action_type, _DEFAULT_NODE_STYLE)
        items.append(
            {
                "value": str(action_type),
                "label": str(label),
                "icon": str(style.get("icon") or _DEFAULT_NODE_STYLE["icon"]),
                "color": str(style.get("color") or _DEFAULT_NODE_STYLE["color"]),
                "bg": str(style.get("bg") or _DEFAULT_NODE_STYLE["bg"]),
                "app": str(style.get("app") or _DEFAULT_NODE_STYLE["app"]),
            }
        )
    return items


def _build_flow_nodes(rule, trigger_descriptor: dict, condition_entries: list, action_entries: list) -> list[dict]:
    """Costruisce la lista di nodi per il diagramma di flusso Power Automate-style."""
    nodes: list[dict] = []

    # ── Nodo Trigger ──
    source_label = str((trigger_descriptor or {}).get("source_label") or "")
    trigger_summary_lines = list((trigger_descriptor or {}).get("summary_lines") or [])
    nodes.append({
        "id": "trigger",
        "type": "trigger",
        "title": "Quando questo accade…",
        "subtitle": source_label,
        "description": " · ".join(str(l) for l in trigger_summary_lines if l),
        "icon": "⚡",
        "color": "#2563eb",
        "bg": "#eff6ff",
        "app": "Trigger",
        "edit_anchor": "trigger-section",
    })

    # ── Nodo Condizioni (se presenti) ──
    existing_conditions = [e for e in condition_entries if e.get("is_existing")]
    if existing_conditions:
        cond_items = []
        for ce in existing_conditions:
            d = ce.get("descriptor") or {}
            field = str(d.get("field_label") or d.get("field_name") or "Campo")
            op = str(d.get("operator_label") or d.get("operator") or "")
            val = str(d.get("expected_value") or "")
            label = " ".join(part for part in (field, op, val) if part).strip()
            badges = d.get("badges") or []
            enabled = "disabilitata" not in badges
            cond_items.append({"label": label or field, "enabled": enabled})
        cond_count = len(existing_conditions)
        nodes.append({
            "id": "conditions",
            "type": "conditions",
            "title": "Condizioni (AND)",
            "subtitle": f"{cond_count} condizion{'i' if cond_count > 1 else 'e'}",
            "items": cond_items,
            "icon": "🔍",
            "color": "#d97706",
            "bg": "#fffbeb",
            "app": "Filtro",
            "edit_anchor": "conditions-section",
        })

    # ── Nodi Azioni ──
    for entry in action_entries:
        if not entry.get("is_existing"):
            continue
        descriptor = entry.get("descriptor") or {}
        action_type = str(descriptor.get("action_type") or "")
        item_id = str(descriptor.get("item_id") or "")
        order_val = int(descriptor.get("order_value") or 0)
        badges: list[str] = list(descriptor.get("badges") or [])
        enabled = "da eliminare" not in badges
        preview_lines: list[str] = [str(l) for l in (descriptor.get("preview_lines") or []) if l]
        config = {}
        # Retrieve config from formset for branch/approval/loop info
        form = entry.get("form")
        if form is not None:
            instance_config = getattr(getattr(form, "instance", None), "config_json", None)
            if isinstance(instance_config, dict):
                config = instance_config
            try:
                cfg_raw = form["config_json"].value()
                if isinstance(cfg_raw, str):
                    try:
                        config = json.loads(cfg_raw)
                    except Exception:
                        pass
                elif isinstance(cfg_raw, dict):
                    config = cfg_raw
            except Exception:
                pass

        style = _ACTION_NODE_STYLES.get(action_type, _DEFAULT_NODE_STYLE)
        node: dict = {
            "id": f"action-{item_id}",
            "type": action_type if action_type in ("send_approval", "do_until", "for_each", "branch") else "action",
            "action_type": action_type,
            "title": str(descriptor.get("action_label") or action_type),
            "subtitle": str(descriptor.get("summary") or ""),
            "preview": preview_lines[:3],
            "enabled": enabled,
            "order": order_val,
            "edit_anchor": f"action-card-{item_id}",
            **style,
        }

        # Azioni speciali: aggiungi rami/loop
        if action_type == "send_approval":
            approved_count = len(config.get("approved_actions") or [])
            rejected_count = len(config.get("rejected_actions") or [])
            node["branches"] = {
                "approved": {
                    "label": str(config.get("approve_label") or "Approvato"),
                    "color": "#16a34a",
                    "bg": "#f0fdf4",
                    "actions": _inline_action_nodes(config.get("approved_actions") or []),
                    "count": approved_count,
                },
                "rejected": {
                    "label": str(config.get("reject_label") or "Rifiutato"),
                    "color": "#dc2626",
                    "bg": "#fef2f2",
                    "actions": _inline_action_nodes(config.get("rejected_actions") or []),
                    "count": rejected_count,
                },
            }
        elif action_type == "do_until":
            node["loop"] = {
                "check_field": str(config.get("check_field") or ""),
                "check_operator": str(config.get("check_operator") or "equals"),
                "check_value": str(config.get("check_value") or ""),
                "max_iterations": int(config.get("max_iterations") or 10),
                "retry_delay": f"{config.get('retry_delay_value', 24)} {config.get('retry_delay_unit', 'hours')}",
                "loop_actions": _inline_action_nodes(config.get("loop_actions") or []),
                "on_success_actions": _inline_action_nodes(config.get("on_success_actions") or []),
                "on_timeout_actions": _inline_action_nodes(config.get("on_timeout_actions") or []),
            }
        elif action_type == "for_each":
            node["each"] = {
                "source_code": str(config.get("source_code") or ""),
                "filter_field": str(config.get("filter_field") or ""),
                "max_items": int(config.get("max_items") or 50),
                "each_actions": _inline_action_nodes(config.get("each_actions") or []),
            }
        elif action_type == "branch":
            node["if_else"] = {
                "condition_field": str(config.get("condition_field") or ""),
                "condition_operator": str(config.get("condition_operator") or "equals"),
                "condition_value": str(config.get("condition_value") or ""),
                "if_true_actions": _inline_action_nodes(config.get("if_true_actions") or []),
                "if_false_actions": _inline_action_nodes(config.get("if_false_actions") or []),
            }

        nodes.append(node)

    # ── Nodo Fine ──
    nodes.append({
        "id": "end",
        "type": "end",
        "title": "Fine flusso",
        "subtitle": "",
        "icon": "🏁",
        "color": "#64748b",
        "bg": "#f8fafc",
        "app": "",
    })

    return nodes


def _inline_action_nodes(actions: list) -> list[dict]:
    """Converte una lista di config dict inline in nodi leggeri per il diagramma."""
    nodes = []
    for cfg in (actions or []):
        if not isinstance(cfg, dict):
            continue
        at = str(cfg.get("action_type") or "")
        style = _ACTION_NODE_STYLES.get(at, _DEFAULT_NODE_STYLE)
        nodes.append({
            "action_type": at,
            "title": str(cfg.get("description") or at),
            "icon": style["icon"],
            "color": style["color"],
        })
    return nodes


@legacy_admin_required
@require_GET
def sorgenti_page(request):
    sources = []
    for source in get_registered_sources():
        source["field_count"] = len(get_source_fields(source["code"]))
        source["operations_display"] = ", ".join(source.get("supported_operations", []))
        sources.append(source)
    context = {
        **_base_context(),
        "sources": sources,
    }
    return render(request, "automazioni/pages/sorgenti.html", context)


@legacy_admin_required
@require_GET
def contenuti_page(request):
    sources = []
    for source in get_registered_sources():
        code = source["code"]
        sources.append(
            {
                **source,
                "trigger_fields": get_trigger_fields(code),
                "condition_fields": get_condition_fields(code),
                "template_fields": get_template_fields(code),
                "action_mapping_fields": get_action_mapping_fields(code),
                "placeholder_examples": build_placeholder_examples(code),
            }
        )

    context = {
        **_base_context(),
        "sources": sources,
    }
    return render(request, "automazioni/pages/contenuti.html", context)


@legacy_admin_required
@require_GET
def rule_list_page(request):
    filters = _build_rule_filters_context(request)
    queryset = _apply_rule_filters(
        AutomationRule.objects.select_related("created_by", "updated_by").order_by("source_code", "name", "id"),
        filters,
    )
    all_sources = get_registered_sources()
    source_map = {s["code"]: s for s in all_sources}

    # Group rules by source_code preserving registry order
    from collections import defaultdict
    groups: dict[str, list] = defaultdict(list)
    # Mini-mappa flusso (blocco 9): prefetch azioni e condizioni per evitare N+1
    # quando costruiamo l'anteprima visiva inline accanto al nome.
    rules_qs = queryset[:500].prefetch_related("actions", "conditions")
    for rule in rules_qs:
        # Usa i dati prefetchati: sort in Python, no nuove query.
        actions_seq = sorted(rule.actions.all(), key=lambda a: (a.order, a.id))
        cond_count = sum(1 for _ in rule.conditions.all())
        rule.flow_preview = {
            "trigger_op": rule.operation_type,
            "cond_count": cond_count,
            "actions": [a.action_type for a in actions_seq[:3]],
            "more_actions": max(0, len(actions_seq) - 3),
        }
        groups[rule.source_code].append(rule)

    # Build ordered group list following registry order, then unknown sources
    registry_order = [s["code"] for s in all_sources]
    seen = set()
    rules_by_source = []
    for code in registry_order:
        if code in groups:
            src = source_map[code]
            rules_by_source.append({
                "source_code": code,
                "source_label": src.get("label", code),
                "source_app": src.get("source_app", ""),
                "rules": groups[code],
            })
            seen.add(code)
    for code, rules in groups.items():
        if code not in seen:
            rules_by_source.append({
                "source_code": code,
                "source_label": code,
                "source_app": "",
                "rules": rules,
            })

    context = {
        **_base_context(),
        "rules_by_source": rules_by_source,
        "total_rules": sum(len(g["rules"]) for g in rules_by_source),
        "filters": filters,
        "source_choices": [(source["code"], source["label"]) for source in all_sources],
        "operation_choices": AutomationRuleOperationType.choices,
        "trigger_scope_choices": AutomationRuleTriggerScope.choices,
        "boolean_filter_choices": RULE_BOOLEAN_FILTER_CHOICES,
    }
    return render(request, "automazioni/pages/rule_list.html", context)


def _build_power_automate_converter_context(
    *,
    upload_form: PowerAutomateFlowUploadForm,
    converter_record: dict[str, object] | None,
    analysis: dict[str, object] | None,
) -> dict[str, object]:
    return {
        **_base_context(),
        "upload_form": upload_form,
        "converter_record": converter_record,
        "converter_diagram": _prepare_power_automate_diagram(converter_record),
        "approval_conversion": ((converter_record or {}).get("package") or {}).get("approval_conversion") if converter_record else None,
        "analysis": analysis,
        "package_pretty": _json_pretty((converter_record or {}).get("package")) if converter_record else "",
        "status_label_map": {
            "ready": "Pronto all'import",
            "partial": "Import parziale",
            "blocked": "Bloccato",
            "ok": "OK",
            "error": "Errore",
            "skipped": "Saltata",
        },
    }


@legacy_admin_required
def rule_power_automate_convert_page(request):
    approval_template_state = _build_power_automate_approval_template_state()
    state = _get_power_automate_converter_state(request)
    converter_record = state.get("record") if isinstance(state.get("record"), dict) else None
    analysis = state.get("analysis") if isinstance(state.get("analysis"), dict) else None
    selected_target_table = _string_value(state.get("selected_target_table"))
    selected_approval_template_code = _string_value(state.get("selected_approval_template_code"))
    upload_form = _build_power_automate_upload_form(
        initial={
            "target_table": selected_target_table,
            "approval_email_template_code": selected_approval_template_code or _string_value(approval_template_state.get("default_code")),
        },
        approval_template_state=approval_template_state,
    )

    if request.method == "POST":
        action = _string_value(request.POST.get("action"))

        if action == "reset":
            _clear_power_automate_converter_state(request)
            messages.success(request, "Workflow conversione Power Automate azzerato.")
            return redirect("admin_portale:automazioni_rule_power_automate_convert")

        if action == "analyze":
            upload_form = _build_power_automate_upload_form(
                request.POST,
                request.FILES,
                approval_template_state=approval_template_state,
            )
            if upload_form.is_valid():
                uploaded_file = upload_form.cleaned_data["flow_file"]
                selected_target_table = _string_value(upload_form.cleaned_data.get("target_table"))
                selected_approval_template_code = _string_value(
                    upload_form.cleaned_data.get("approval_email_template_code")
                ) or _string_value(approval_template_state.get("default_code"))
                target_context = _build_power_automate_target_context(selected_target_table)
                selected_approval_template = (
                    approval_template_state.get("templates_by_code", {}) or {}
                ).get(selected_approval_template_code)

                try:
                    converter_record = analyze_power_automate_flow_upload(
                        str(uploaded_file.name),
                        uploaded_file.read(),
                        target_context=target_context,
                        approval_template=selected_approval_template,
                    )
                    analysis = analyze_package_dict(
                        converter_record["package"],
                        filename=_power_automate_package_filename(converter_record, fallback_name=str(uploaded_file.name)),
                    )
                except PackageImportError as exc:
                    upload_form.add_error("flow_file", str(exc))
                    converter_record = None
                    analysis = None
                except Exception as exc:
                    upload_form.add_error("flow_file", f"Analisi Power Automate fallita: {exc}")
                    converter_record = None
                    analysis = None
                else:
                    _set_power_automate_converter_state(
                        request,
                        {
                            "record": converter_record,
                            "analysis": analysis,
                            "selected_target_table": selected_target_table,
                            "selected_approval_template_code": selected_approval_template_code,
                        },
                    )
                    messages.success(
                        request,
                        "Flow Power Automate analizzato. Puoi rivedere diagramma, remediation e poi passare all'import guidato.",
                    )
                    return redirect("admin_portale:automazioni_rule_power_automate_convert")

        elif action == "apply_remediation":
            if not converter_record:
                messages.error(request, "Analizza prima un export Power Automate.")
                return redirect("admin_portale:automazioni_rule_power_automate_convert")
            try:
                converter_record = apply_power_automate_recommended_remediation(converter_record)
                analysis = analyze_package_dict(
                    converter_record["package"],
                    filename=_power_automate_package_filename(converter_record),
                )
            except PackageImportError as exc:
                messages.error(request, str(exc))
            else:
                _set_power_automate_converter_state(
                    request,
                        {
                            "record": converter_record,
                            "analysis": analysis,
                            "selected_target_table": selected_target_table,
                            "selected_approval_template_code": selected_approval_template_code,
                        },
                    )
                messages.success(request, "Remediation consigliata applicata al package convertito.")
                return redirect("admin_portale:automazioni_rule_power_automate_convert")

        elif action == "handoff_import":
            if not analysis:
                messages.error(request, "Analizza prima un export Power Automate.")
                return redirect("admin_portale:automazioni_rule_power_automate_convert")
            _set_package_import_state(
                request,
                {
                    "analysis": analysis,
                    "dry_run_completed_hash": "",
                    "dry_run_activation_state": {},
                },
            )
            messages.success(
                request,
                "Package convertito trasferito all'import guidato. Ora puoi eseguire dry-run e conferma finale.",
            )
            return redirect("admin_portale:automazioni_rule_import_package")

        elif action == "open_designer":
            if not analysis:
                messages.error(request, "Analizza prima un export Power Automate.")
                return redirect("admin_portale:automazioni_rule_power_automate_convert")

            try:
                rule_index = int(request.POST.get("rule_index") or 0)
            except (TypeError, ValueError):
                messages.error(request, "Regola richiesta non valida per l'apertura nel designer.")
                return redirect("admin_portale:automazioni_rule_power_automate_convert")

            try:
                created_rule = create_rule_draft_from_analysis(
                    analysis,
                    created_by=request.user,
                    rule_index=rule_index,
                )
            except PackageImportError as exc:
                messages.error(request, str(exc))
                return redirect("admin_portale:automazioni_rule_power_automate_convert")

            messages.success(
                request,
                (
                    "Bozza creata dal converter Power Automate e aperta nel designer visuale. "
                    "La regola resta draft e disattiva finche' non la pubblichi."
                ),
            )
            return redirect("admin_portale:automazioni_rule_designer", rule_id=created_rule.id)

    context = _build_power_automate_converter_context(
        upload_form=upload_form,
        converter_record=converter_record,
        analysis=analysis,
    )
    return render(request, "automazioni/pages/power_automate_convert.html", context)


@legacy_admin_required
@require_GET
def rule_power_automate_package_download(request):
    state = _get_power_automate_converter_state(request)
    converter_record = state.get("record") if isinstance(state.get("record"), dict) else None
    if not converter_record:
        messages.info(request, "Nessun package convertito disponibile per il download.")
        return redirect("admin_portale:automazioni_rule_power_automate_convert")

    package_content = json.dumps(
        converter_record.get("package") or {},
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )
    response = HttpResponse(package_content, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="{_power_automate_package_filename(converter_record)}"'
    )
    return response


def _build_package_import_context(
    *,
    request,
    upload_form: AutomationPackageUploadForm,
    analysis: dict[str, object] | None,
    dry_run_form: AutomationPackageDryRunForm | None,
    dry_run_result: dict[str, object] | None = None,
) -> dict[str, object]:
    state = _get_package_import_state(request)
    dry_run_completed_hash = str(state.get("dry_run_completed_hash") or "").strip()
    dry_run_activation_state = state.get("dry_run_activation_state")
    analysis_hash = str((analysis or {}).get("package_hash") or "").strip()
    return {
        **_base_context(),
        "upload_form": upload_form,
        "analysis": analysis,
        "dry_run_form": dry_run_form,
        "dry_run_result": dry_run_result,
        "status_label_map": {
            "ready": "Pronto all'import",
            "partial": "Import parziale",
            "blocked": "Bloccato",
            "ok": "OK",
            "error": "Errore",
            "skipped": "Saltata",
        },
        "dry_run_completed": bool(analysis_hash and dry_run_completed_hash == analysis_hash),
        "can_import": bool(
            analysis
            and analysis.get("status") != "blocked"
            and int(analysis.get("importable_rule_count") or 0) > 0
            and analysis_hash
            and dry_run_completed_hash == analysis_hash
        ),
        "can_activate_after_import": bool(
            analysis
            and analysis_hash
            and dry_run_completed_hash == analysis_hash
            and _dry_run_allows_activation(analysis, dry_run_activation_state if isinstance(dry_run_activation_state, dict) else {})
        ),
    }


@legacy_admin_required
def rule_package_import_page(request):
    state = _get_package_import_state(request)
    analysis = state.get("analysis") if isinstance(state.get("analysis"), dict) else None
    upload_form = AutomationPackageUploadForm()
    dry_run_form = _build_package_dry_run_form(analysis)
    dry_run_result = None

    if request.method == "POST":
        action = _string_value(request.POST.get("action"))

        if action == "reset":
            _clear_package_import_state(request)
            messages.success(request, "Workflow import package azzerato.")
            return redirect("admin_portale:automazioni_rule_import_package")

        if action == "analyze":
            upload_form = AutomationPackageUploadForm(request.POST, request.FILES)
            if upload_form.is_valid():
                uploaded_file = upload_form.cleaned_data["package_file"]
                try:
                    analysis = analyze_package_bytes(uploaded_file.read(), filename=str(uploaded_file.name))
                except PackageImportError as exc:
                    upload_form.add_error("package_file", str(exc))
                    analysis = None
                    dry_run_form = None
                else:
                    _set_package_import_state(
                        request,
                        {
                            "analysis": analysis,
                            "dry_run_completed_hash": "",
                            "dry_run_activation_state": {},
                        },
                    )
                    messages.success(request, "Package analizzato. Esegui il test al volo prima di confermare l'import.")
                    return redirect("admin_portale:automazioni_rule_import_package")

        elif action == "dry_run":
            if not analysis:
                messages.error(request, "Carica prima un package da analizzare.")
                return redirect("admin_portale:automazioni_rule_import_package")

            dry_run_form = _build_package_dry_run_form(analysis, request.POST)
            if dry_run_form and dry_run_form.is_valid():
                sample_mode = dry_run_form.cleaned_data["sample_mode"]
                source_code = str(analysis.get("source_code") or "").strip()
                old_payload = dry_run_form.cleaned_data["old_payload_json"]

                if sample_mode == "json":
                    payload = dry_run_form.cleaned_data["payload_json"] or {}
                    sample_label = "JSON incollato"
                elif sample_mode == "record":
                    record_id = dry_run_form.cleaned_data["source_record_id"]
                    payload = load_source_record_payload(source_code, record_id)
                    if payload is None:
                        dry_run_form.add_error("source_record_id", "Record non disponibile per la sorgente selezionata.")
                    sample_label = f"Record sorgente #{record_id}"
                else:
                    payload = json.loads(build_example_payload_json(source_code) or "{}")
                    sample_label = "Payload di esempio"

                if dry_run_form.errors:
                    pass
                else:
                    try:
                        dry_run_result = run_package_dry_run(
                            analysis,
                            payload=payload,
                            old_payload=old_payload,
                            sample_label=sample_label,
                        )
                    except PackageImportError as exc:
                        messages.error(request, str(exc))
                    else:
                        state["dry_run_completed_hash"] = analysis.get("package_hash") or ""
                        state["dry_run_activation_state"] = _build_dry_run_activation_state(dry_run_result)
                        _set_package_import_state(request, state)

        elif action == "import":
            if not analysis:
                messages.error(request, "Carica prima un package da analizzare.")
                return redirect("admin_portale:automazioni_rule_import_package")
            if str(state.get("dry_run_completed_hash") or "") != str(analysis.get("package_hash") or ""):
                messages.error(request, "Esegui prima il test al volo del package corrente.")
                return redirect("admin_portale:automazioni_rule_import_package")
            activate_after_import = _bool_value(request.POST.get("activate_after_import"))
            if activate_after_import and not _dry_run_allows_activation(
                analysis,
                state.get("dry_run_activation_state") if isinstance(state.get("dry_run_activation_state"), dict) else {},
            ):
                messages.error(
                    request,
                    "L'attivazione diretta richiede un test al volo valido per tutte le regole importabili del package corrente.",
                )
                return redirect("admin_portale:automazioni_rule_import_package")
            try:
                result = import_analyzed_package(
                    analysis,
                    created_by=request.user,
                    activate_created_rules=activate_after_import,
                )
            except PackageImportError as exc:
                messages.error(request, str(exc))
            except Exception as exc:
                messages.error(request, f"Import fallito, nessuna regola creata: {exc}")
            else:
                _set_package_import_result(request, result)
                _clear_package_import_state(request)
                if result.get("activation_applied"):
                    messages.success(
                        request,
                        "Import completato. "
                        f"Regole create: {result['created_rule_count']}. "
                        f"Regole attivate: {result['activated_rule_count']}.",
                    )
                else:
                    messages.success(request, f"Import completato. Regole create: {result['created_rule_count']}.")
                return redirect("admin_portale:automazioni_rule_import_result")

    context = _build_package_import_context(
        request=request,
        upload_form=upload_form,
        analysis=analysis,
        dry_run_form=dry_run_form,
        dry_run_result=dry_run_result,
    )
    return render(request, "automazioni/pages/package_import.html", context)


@legacy_admin_required
@require_GET
def rule_package_import_result_page(request):
    result = _pop_package_import_result(request)
    if result is None:
        messages.info(request, "Nessun risultato import disponibile.")
        return redirect("admin_portale:automazioni_rule_import_package")
    context = {
        **_base_context(),
        "result": result,
    }
    return render(request, "automazioni/pages/package_import_result.html", context)


@legacy_admin_required
@require_GET
def rule_detail_page(request, rule_id: int):
    rule = get_object_or_404(
        AutomationRule.objects.select_related("created_by", "updated_by"),
        pk=rule_id,
    )
    recent_run_logs = list(
        rule.run_logs.select_related("initiated_by")
        .order_by("-started_at", "-id")[:10]
    )
    latest_test_log = (
        rule.run_logs.filter(is_test=True)
        .select_related("initiated_by")
        .order_by("-started_at", "-id")
        .first()
    )
    conditions = list(rule.conditions.order_by("order", "id"))
    actions = list(rule.actions.order_by("order", "id"))
    # Per sparkbar durata: max sui run mostrati (0 = nessuna barra).
    max_execution_ms = max((rl.execution_ms or 0 for rl in recent_run_logs), default=0)
    has_compare_with_old = any(getattr(c, "compare_with_old", False) for c in conditions)
    from django.urls import reverse
    _rule_list_url = reverse("admin_portale:automazioni_rule_list")
    breadcrumb_items = [
        {"label": "Regole", "url": _rule_list_url},
        {"label": rule.source_code or "?", "url": f"{_rule_list_url}?source_code={rule.source_code}"},
        {"label": rule.name, "url": None},
    ]
    context = {
        **_base_context(),
        "rule": rule,
        "conditions": conditions,
        "actions": actions,
        "recent_run_logs": recent_run_logs,
        "latest_test_log": latest_test_log,
        "max_execution_ms": max_execution_ms,
        "has_compare_with_old": has_compare_with_old,
        "breadcrumb_items": breadcrumb_items,
    }
    return render(request, "automazioni/pages/rule_detail.html", context)


@legacy_admin_required
def rule_create_page(request):
    rule = AutomationRule()
    selected_source_code = _get_rule_source_code(request, rule)

    if request.method == "POST":
        rule_form = AutomationRuleForm(request.POST, instance=rule)
        selected_source_code = str(request.POST.get("source_code") or "").strip() or _get_default_source_code()
        condition_formset = AutomationConditionFormSet(
            request.POST,
            instance=rule,
            prefix="conditions",
            form_kwargs={"source_code": selected_source_code},
        )
        action_formset = AutomationActionFormSet(
            request.POST,
            instance=rule,
            prefix="actions",
            form_kwargs={"source_code": selected_source_code},
        )
        if rule_form.is_valid() and condition_formset.is_valid() and action_formset.is_valid():
            with transaction.atomic():
                saved_rule = rule_form.save(commit=False)
                saved_rule.created_by = request.user
                saved_rule.updated_by = request.user
                saved_rule.save()
                condition_formset.instance = saved_rule
                action_formset.instance = saved_rule
                condition_formset.save()
                action_formset.save()
            messages.success(request, f"Regola {saved_rule.name} creata correttamente.")
            return redirect("admin_portale:automazioni_rule_detail", rule_id=saved_rule.id)
    else:
        rule_form = AutomationRuleForm(instance=rule, initial={"source_code": selected_source_code})
        condition_formset = AutomationConditionFormSet(
            instance=rule,
            prefix="conditions",
            form_kwargs={"source_code": selected_source_code},
        )
        action_formset = AutomationActionFormSet(
            instance=rule,
            prefix="actions",
            form_kwargs={"source_code": selected_source_code},
        )

    context = _build_rule_form_context(
        rule_form=rule_form,
        condition_formset=condition_formset,
        action_formset=action_formset,
        page_title="Automazioni - Nuova Regola",
        page_subtitle="Builder SSR per definire trigger, condizioni in AND e azioni sequenziali.",
        submit_label="Crea regola",
        selected_source_code=selected_source_code,
        rule=None,
    )
    return render(request, "automazioni/pages/rule_form.html", context)


@legacy_admin_required
def rule_edit_page(request, rule_id: int):
    rule = get_object_or_404(AutomationRule, pk=rule_id)
    selected_source_code = _get_rule_source_code(request, rule)

    if request.method == "POST":
        rule_form = AutomationRuleForm(request.POST, instance=rule)
        selected_source_code = str(request.POST.get("source_code") or "").strip() or rule.source_code or _get_default_source_code()
        condition_formset = AutomationConditionFormSet(
            request.POST,
            instance=rule,
            prefix="conditions",
            form_kwargs={"source_code": selected_source_code},
        )
        action_formset = AutomationActionFormSet(
            request.POST,
            instance=rule,
            prefix="actions",
            form_kwargs={"source_code": selected_source_code},
        )
        if rule_form.is_valid() and condition_formset.is_valid() and action_formset.is_valid():
            with transaction.atomic():
                saved_rule = rule_form.save(commit=False)
                saved_rule.updated_by = request.user
                saved_rule.save()
                condition_formset.instance = saved_rule
                action_formset.instance = saved_rule
                condition_formset.save()
                action_formset.save()
            messages.success(request, f"Regola {saved_rule.name} aggiornata.")
            return redirect("admin_portale:automazioni_rule_detail", rule_id=saved_rule.id)
    else:
        rule_form = AutomationRuleForm(instance=rule)
        condition_formset = AutomationConditionFormSet(
            instance=rule,
            prefix="conditions",
            form_kwargs={"source_code": selected_source_code},
        )
        action_formset = AutomationActionFormSet(
            instance=rule,
            prefix="actions",
            form_kwargs={"source_code": selected_source_code},
        )

    context = _build_rule_form_context(
        rule_form=rule_form,
        condition_formset=condition_formset,
        action_formset=action_formset,
        page_title=f"Automazioni - Modifica Regola #{rule.id}",
        page_subtitle="Aggiorna configurazione regola mantenendo visibile il catalogo campi della sorgente selezionata.",
        submit_label="Salva modifiche",
        selected_source_code=selected_source_code,
        rule=rule,
    )
    return render(request, "automazioni/pages/rule_form.html", context)


@legacy_admin_required
def rule_designer_create_page(request):
    rule = AutomationRule()
    selected_source_code = _get_rule_source_code(request, rule)

    if request.method == "POST":
        rule_form = AutomationRuleForm(request.POST, instance=rule)
        selected_source_code = str(request.POST.get("source_code") or "").strip() or _get_default_source_code()
        condition_formset = AutomationConditionFormSet(
            request.POST,
            instance=rule,
            prefix="conditions",
            form_kwargs={"source_code": selected_source_code},
        )
        action_formset = AutomationActionFormSet(
            request.POST,
            instance=rule,
            prefix="actions",
            form_kwargs={"source_code": selected_source_code},
        )
        if rule_form.is_valid() and condition_formset.is_valid() and action_formset.is_valid():
            with transaction.atomic():
                saved_rule = rule_form.save(commit=False)
                saved_rule.created_by = request.user
                saved_rule.updated_by = request.user
                saved_rule.save()
                condition_formset.instance = saved_rule
                action_formset.instance = saved_rule
                condition_formset.save()
                action_formset.save()
            messages.success(request, f"Regola {saved_rule.name} creata dal designer visuale.")
            return redirect("admin_portale:automazioni_rule_designer", rule_id=saved_rule.id)
    else:
        rule_form = AutomationRuleForm(instance=rule, initial={"source_code": selected_source_code})
        condition_formset = AutomationConditionFormSet(
            instance=rule,
            prefix="conditions",
            form_kwargs={"source_code": selected_source_code},
        )
        action_formset = AutomationActionFormSet(
            instance=rule,
            prefix="actions",
            form_kwargs={"source_code": selected_source_code},
        )

    context = _build_rule_designer_context(
        rule=rule,
        rule_form=rule_form,
        condition_formset=condition_formset,
        action_formset=action_formset,
        selected_source_code=selected_source_code,
    )
    return render(request, "automazioni/pages/rule_designer.html", context)


@legacy_admin_required
def rule_designer_page(request, rule_id: int):
    rule = get_object_or_404(AutomationRule, pk=rule_id)
    selected_source_code = _get_rule_source_code(request, rule)

    if request.method == "POST":
        rule_form = AutomationRuleForm(request.POST, instance=rule)
        selected_source_code = str(request.POST.get("source_code") or "").strip() or rule.source_code or _get_default_source_code()
        condition_formset = AutomationConditionFormSet(
            request.POST,
            instance=rule,
            prefix="conditions",
            form_kwargs={"source_code": selected_source_code},
        )
        action_formset = AutomationActionFormSet(
            request.POST,
            instance=rule,
            prefix="actions",
            form_kwargs={"source_code": selected_source_code},
        )
        if rule_form.is_valid() and condition_formset.is_valid() and action_formset.is_valid():
            with transaction.atomic():
                saved_rule = rule_form.save(commit=False)
                saved_rule.updated_by = request.user
                saved_rule.save()
                condition_formset.instance = saved_rule
                action_formset.instance = saved_rule
                condition_formset.save()
                action_formset.save()
            messages.success(request, f"Designer visuale aggiornato per la regola {saved_rule.name}.")
            return redirect("admin_portale:automazioni_rule_designer", rule_id=saved_rule.id)
    else:
        rule_form = AutomationRuleForm(instance=rule)
        condition_formset = AutomationConditionFormSet(
            instance=rule,
            prefix="conditions",
            form_kwargs={"source_code": selected_source_code},
        )
        action_formset = AutomationActionFormSet(
            instance=rule,
            prefix="actions",
            form_kwargs={"source_code": selected_source_code},
        )

    context = _build_rule_designer_context(
        rule=rule,
        rule_form=rule_form,
        condition_formset=condition_formset,
        action_formset=action_formset,
        selected_source_code=selected_source_code,
    )
    return render(request, "automazioni/pages/rule_designer.html", context)


@legacy_admin_required
@require_POST
def rule_toggle_view(request, rule_id: int):
    rule = get_object_or_404(AutomationRule, pk=rule_id)
    rule.is_active = not rule.is_active
    if rule.is_active:
        rule.is_draft = False
    rule.updated_by = request.user
    rule.save(update_fields=["is_active", "is_draft", "updated_by", "updated_at"])
    status_label = "attivata" if rule.is_active else "disattivata"
    messages.success(request, f"Regola {rule.name} {status_label}.")
    next_url = str(request.POST.get("next") or "").strip()
    if next_url:
        return redirect(next_url)
    return redirect("admin_portale:automazioni_rule_detail", rule_id=rule.id)


@legacy_admin_required
@require_POST
def rule_delete_view(request, rule_id: int):
    rule = get_object_or_404(AutomationRule, pk=rule_id)
    rule_name = rule.name
    rule_code = rule.code
    # Le condizioni/azioni hanno FK on_delete=CASCADE: vengono rimosse con la regola.
    rule.delete()
    try:
        log_action(
            request,
            azione="automazione_regola_eliminata",
            modulo="automazioni",
            dettaglio={"rule_id": rule_id, "code": rule_code, "name": rule_name},
        )
    except Exception:
        pass
    messages.success(request, f"Regola «{rule_name}» eliminata.")
    next_url = str(request.POST.get("next") or "").strip()
    if next_url:
        return redirect(next_url)
    return redirect("admin_portale:automazioni_rule_list")


@legacy_admin_required
@require_POST
def rule_condition_reorder_view(request, rule_id: int):
    rule = get_object_or_404(AutomationRule, pk=rule_id)
    try:
        ordered_ids = _extract_ordered_ids(request)
        _reorder_rule_items(rule=rule, model=AutomationCondition, ordered_ids=ordered_ids)
    except (ValueError, json.JSONDecodeError) as exc:
        return JsonResponse({"ok": False, "message": str(exc)}, status=400)
    return JsonResponse({"ok": True, "ordered_ids": ordered_ids})


@legacy_admin_required
@require_POST
def rule_action_reorder_view(request, rule_id: int):
    rule = get_object_or_404(AutomationRule, pk=rule_id)
    try:
        ordered_ids = _extract_ordered_ids(request)
        _reorder_rule_items(rule=rule, model=AutomationAction, ordered_ids=ordered_ids)
    except (ValueError, json.JSONDecodeError) as exc:
        return JsonResponse({"ok": False, "message": str(exc)}, status=400)
    return JsonResponse({"ok": True, "ordered_ids": ordered_ids})


@legacy_admin_required
def rule_test_page(request, rule_id: int):
    rule = get_object_or_404(AutomationRule, pk=rule_id)
    run_log = None
    example_payload_json = _build_example_payload(rule.source_code)
    example_old_payload = _build_example_old_payload(rule)
    example_old_payload_json = (
        json.dumps(example_old_payload, indent=2, ensure_ascii=False, sort_keys=True)
        if isinstance(example_old_payload, dict) else ""
    )

    if request.method == "POST":
        form = AutomationRuleTestForm(request.POST)
        if form.is_valid():
            run_log = run_rule(
                rule,
                form.cleaned_data["payload_json"],
                old_payload=form.cleaned_data["old_payload_json"],
                queue_event_id=None,
                initiated_by=request.user,
                is_test=True,
            )
            if run_log.status == AutomationRunLogStatus.ERROR:
                messages.error(request, f"Test completato con errori. Run log #{run_log.id}.")
            else:
                messages.success(request, f"Test eseguito correttamente. Run log #{run_log.id}.")
    else:
        from_log_id = request.GET.get("from_log")
        prefill_payload = example_payload_json
        prefill_old_payload = example_old_payload_json
        if from_log_id:
            try:
                source_log = AutomationRunLog.objects.get(pk=from_log_id, rule=rule)
                prefill_payload = json.dumps(source_log.payload_json, indent=2, ensure_ascii=False)
                prefill_old_payload = (
                    json.dumps(source_log.old_payload_json, indent=2, ensure_ascii=False)
                    if source_log.old_payload_json is not None else ""
                )
            except AutomationRunLog.DoesNotExist:
                pass
        form = AutomationRuleTestForm(
            initial={
                "payload_json": prefill_payload,
                "old_payload_json": prefill_old_payload,
                "is_test": True,
            }
        )

    context = {
        **_base_context(),
        **_build_source_catalog_context(rule.source_code),
        "enable_smart_field_panel": True,
        "rule": rule,
        "form": form,
        "run_log": run_log,
        "selected_source_code": rule.source_code,
        "source_fields_json": _build_all_source_fields_json(),
        "sample_payload_json": example_payload_json,
        "sample_old_payload_json": example_old_payload_json,
    }
    return render(request, "automazioni/pages/rule_test.html", context)


def _format_display_datetime(value) -> str:
    if not value:
        return "-"
    parsed = value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return "-"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return raw
    if isinstance(parsed, datetime):
        if parsed.year < 1901:
            return "-"
        current_tz = timezone.get_current_timezone()
        if timezone.is_naive(parsed):
            # Alcuni backend/driver restituiscono datetime naive pur usando USE_TZ.
            # Li trattiamo come orario del progetto prima della formattazione finale.
            parsed = timezone.make_aware(parsed, current_tz)
        parsed = timezone.localtime(parsed, current_tz)
        return parsed.strftime("%d-%m-%Y %H:%M:%S")
    return str(parsed)


def _run_powershell_json(script: str) -> dict[str, object]:
    if os.name != "nt":
        return {"ok": False, "error": "Task Scheduler disponibile solo su Windows."}
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0:
        return {"ok": False, "error": stderr or stdout or f"exit code {completed.returncode}"}
    if not stdout:
        return {"ok": False, "error": "Il comando non ha restituito output JSON."}
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"JSON non valido dal comando PowerShell: {exc}"}
    return {"ok": True, "data": data if isinstance(data, dict) else {}}


def _build_queue_poller_task_snapshot() -> dict[str, object]:
    snapshot = {
        "task_name": QUEUE_POLLER_TASK_NAME,
        "task_path": "\\",
        "task_exists": False,
        "task_state": "missing",
        "task_state_label": "Non registrato",
        "task_last_run_label": "-",
        "task_next_run_label": "-",
        "task_last_result_label": "-",
        "task_message": "Il task Windows locale non e registrato.",
    }
    escaped_name = QUEUE_POLLER_TASK_NAME.replace("'", "''")
    ps_query = f"""
$task = Get-ScheduledTask -TaskName '{escaped_name}' -ErrorAction SilentlyContinue
if ($null -eq $task) {{
  [pscustomobject]@{{
    exists = $false
    task_name = '{escaped_name}'
    task_path = '\\'
    state = 'missing'
    description = ''
    last_run_time = ''
    next_run_time = ''
    last_task_result = ''
  }} | ConvertTo-Json -Compress
  exit 0
}}
$info = Get-ScheduledTaskInfo -TaskName '{escaped_name}' -ErrorAction SilentlyContinue
[pscustomobject]@{{
  exists = $true
  task_name = [string]$task.TaskName
  task_path = [string]$task.TaskPath
  state = [string]$task.State
  description = [string]$task.Description
  last_run_time = $(if ($info -and $info.LastRunTime -gt [datetime]'1900-01-01') {{ $info.LastRunTime.ToString('o') }} else {{ '' }})
  next_run_time = $(if ($info -and $info.NextRunTime -gt [datetime]'1900-01-01') {{ $info.NextRunTime.ToString('o') }} else {{ '' }})
  last_task_result = $(if ($info) {{ [string]$info.LastTaskResult }} else {{ '' }})
}} | ConvertTo-Json -Compress
"""
    ps_result = _run_powershell_json(ps_query)
    if not ps_result.get("ok"):
        snapshot["task_state"] = "unknown"
        snapshot["task_state_label"] = "Stato non leggibile"
        snapshot["task_message"] = str(ps_result.get("error") or "Impossibile interrogare Task Scheduler.")
        return snapshot

    data = ps_result.get("data") or {}
    state_code = str(data.get("state") or "missing").strip().lower()
    state_labels = {
        "missing": "Non registrato",
        "ready": "Pronto",
        "running": "In esecuzione",
        "queued": "In coda",
        "disabled": "Disabilitato",
        "unknown": "Sconosciuto",
    }
    last_result = str(data.get("last_task_result") or "").strip()
    snapshot.update(
        {
            "task_name": str(data.get("task_name") or QUEUE_POLLER_TASK_NAME),
            "task_path": str(data.get("task_path") or "\\"),
            "task_exists": bool(data.get("exists")),
            "task_state": state_code,
            "task_state_label": state_labels.get(state_code, state_code.upper() or "Sconosciuto"),
            "task_last_run_label": _format_display_datetime(data.get("last_run_time")),
            "task_next_run_label": _format_display_datetime(data.get("next_run_time")),
            "task_last_result_label": "0 (ultimo avvio ok)" if last_result == "0" else (last_result or "-"),
        }
    )
    if snapshot["task_exists"]:
        snapshot["task_message"] = (
            "Task registrato localmente."
            if snapshot["task_state"] in {"ready", "running", "queued"}
            else "Task presente ma non in stato operativo."
        )
    return snapshot


def _build_queue_poller_log_snapshot() -> dict[str, object]:
    exists = QUEUE_POLLER_LOG_PATH.exists()
    size_label = "-"
    last_write_label = "-"
    if exists:
        stat = QUEUE_POLLER_LOG_PATH.stat()
        size_kb = stat.st_size / 1024 if stat.st_size else 0
        size_label = f"{size_kb:.1f} KB"
        last_write_label = _format_display_datetime(datetime.fromtimestamp(stat.st_mtime))
    return {
        "log_path": str(QUEUE_POLLER_LOG_PATH),
        "log_exists": exists,
        "log_size_label": size_label,
        "log_last_write_label": last_write_label,
    }


def _build_queue_poller_health_snapshot() -> dict[str, object]:
    now = timezone.now()
    task_snapshot = _build_queue_poller_task_snapshot()
    log_snapshot = _build_queue_poller_log_snapshot()
    job = AutomationJob.objects.filter(code=QUEUE_POLLER_JOB_CODE).first()
    executions = list(job.executions.order_by("-started_at", "-id")[:10]) if job else []
    last_execution = executions[0] if executions else None
    consecutive_failures = 0
    for execution in executions:
        if execution.status != AutomationExecution.Status.FAILED:
            break
        consecutive_failures += 1

    missing_alert = None
    stuck_alert = None
    next_expected_at_label = "-"
    if job is not None:
        missing_alert = {
            item["job"].pk: item for item in detect_missed_jobs(now=now, create_issues=False)
        }.get(job.pk)
        stuck_alert = {
            item["job"].pk: item for item in detect_stuck_jobs(now=now, create_issues=False)
        }.get(job.pk)
        if job.expected_max_interval_minutes:
            reference_time = last_execution.started_at if last_execution else job.created_at
            next_expected_at_label = _format_display_datetime(
                reference_time + timedelta(minutes=int(job.expected_max_interval_minutes))
            )

    summary_state = "healthy"
    summary_label = "Attivo"
    summary_message = "Task registrato e job monitorato nei tempi attesi."
    if not task_snapshot["task_exists"]:
        summary_state = "error"
        summary_label = "Task mancante"
        summary_message = (
            "Gli eventi possono restare pending perche il consumatore automatico non e registrato sul server."
        )
    elif task_snapshot["task_state"] == "disabled":
        summary_state = "error"
        summary_label = "Task disabilitato"
        summary_message = "Il task Windows esiste ma e disabilitato, quindi la queue non viene consumata."
    elif stuck_alert:
        summary_state = "error"
        summary_label = "Worker bloccato"
        summary_message = "L'ultima esecuzione risulta oltre la durata massima attesa."
    elif missing_alert:
        overdue_minutes = int(missing_alert.get("overdue_minutes") or 0)
        summary_state = "warning"
        summary_label = "In ritardo"
        summary_message = f"Il job non risulta eseguito nei tempi attesi ed e in ritardo di {overdue_minutes} minuti."
    elif last_execution is None:
        summary_state = "warning"
        summary_label = "Mai eseguito"
        summary_message = "Il task esiste ma non risultano ancora esecuzioni monitorate del queue processor."
    elif last_execution.status == AutomationExecution.Status.FAILED:
        summary_state = "warning"
        summary_label = "Ultimo run fallito"
        summary_message = "Il task parte, ma l'ultima esecuzione monitorata del queue processor e fallita."
    elif task_snapshot["task_state"] not in {"ready", "running", "queued"}:
        summary_state = "warning"
        summary_label = "Stato task anomalo"
        summary_message = "Il task esiste ma non risulta pronto o in esecuzione."

    return {
        **task_snapshot,
        **log_snapshot,
        "summary_state": summary_state,
        "summary_label": summary_label,
        "summary_message": summary_message,
        "display_timezone_label": timezone.get_current_timezone_name(),
        "job_exists": job is not None,
        "job_id": getattr(job, "pk", None),
        "job_code": QUEUE_POLLER_JOB_CODE,
        "job_name": getattr(job, "name", "Processo queue automazioni"),
        "job_last_execution_label": _format_display_datetime(getattr(last_execution, "started_at", None)),
        "job_status_label": getattr(last_execution, "get_status_display", lambda: "-")(),
        "job_status_code": str(getattr(last_execution, "status", "") or "").lower(),
        "job_trigger_type_label": getattr(last_execution, "get_trigger_type_display", lambda: "-")(),
        "job_message": str(getattr(last_execution, "message", "") or "").strip() or "-",
        "job_consecutive_failures": consecutive_failures,
        "job_next_expected_label": next_expected_at_label,
        "job_missing_alert": bool(missing_alert),
        "job_missing_detail": (
            f"In ritardo di {int(missing_alert.get('overdue_minutes') or 0)} minuti."
            if missing_alert else "-"
        ),
        "job_stuck_alert": bool(stuck_alert),
        "job_stuck_detail": (
            f"Oltre soglia di {int(stuck_alert.get('delay_seconds') or 0)} secondi."
            if stuck_alert else "-"
        ),
    }


def _queue_table_exists() -> bool:
    try:
        table_name = "automation_event_queue" if connection.vendor == "sqlite" else "dbo.automation_event_queue"
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT 1 FROM {table_name} WHERE 1=0;")
        return True
    except (DjangoProgrammingError, DjangoOperationalError):
        return False


@legacy_admin_required
@require_GET
def queue_list_page(request):
    status = _get_filter_value(request, "status")
    source_code = _get_filter_value(request, "source_code")
    operation_type = _get_filter_value(request, "operation_type")
    poller_health = _build_queue_poller_health_snapshot()

    if not _queue_table_exists():
        context = {
            **_base_context(),
            "queue_table_missing": True,
            "poller_health": poller_health,
            "queue_events": [],
            "queue_counts": {},
            "filters": {"status": status, "source_code": source_code, "operation_type": operation_type},
            "queue_status_choices": QUEUE_STATUS_CHOICES,
            "queue_operation_choices": QUEUE_OPERATION_CHOICES,
            "source_choices": [],
        }
        return render(request, "automazioni/pages/queue_list.html", context)

    queue_events = list_queue_events(
        status=status or None,
        source_code=source_code or None,
        operation_type=operation_type or None,
        limit=200,
    )
    queue_ids = [int(event["id"]) for event in queue_events]
    run_log_counts = {
        row["queue_event_id"]: row["total"]
        for row in AutomationRunLog.objects.filter(queue_event_id__in=queue_ids)
        .order_by()
        .values("queue_event_id")
        .annotate(total=Count("id"))
    }
    for event in queue_events:
        event["run_log_count"] = int(run_log_counts.get(event["id"], 0))
        event["error_message_short"] = str(event.get("error_message") or "")[:180]
        event["can_reset"] = event.get("status") == "error"
        event["can_retry"] = event.get("status") in {"error", "pending"}
        event["can_stop"] = event.get("status") == "pending"
        event["can_delete"] = event.get("status") in {"pending", "error"} and event["run_log_count"] == 0

    context = {
        **_base_context(),
        "queue_table_missing": False,
        "poller_health": poller_health,
        "queue_events": queue_events,
        "queue_counts": count_queue_by_status(
            source_code=source_code or None,
            operation_type=operation_type or None,
        ),
        "filters": {
            "status": status,
            "source_code": source_code,
            "operation_type": operation_type,
        },
        "queue_status_choices": QUEUE_STATUS_CHOICES,
        "queue_operation_choices": QUEUE_OPERATION_CHOICES,
        "source_choices": [(source["code"], source["label"]) for source in get_registered_sources()],
    }
    return render(request, "automazioni/pages/queue_list.html", context)


@legacy_admin_required
@require_GET
def queue_detail_page(request, queue_id: int):
    queue_event = get_queue_event_detail(queue_id)
    if queue_event is None:
        raise Http404("Evento queue non trovato.")
    poller_health = _build_queue_poller_health_snapshot()

    run_logs = list(
        AutomationRunLog.objects.filter(queue_event_id=queue_id)
        .select_related("rule", "initiated_by")
        .prefetch_related("action_logs__action")
        .order_by("-started_at", "-id")
    )
    action_logs = list(
        AutomationActionLog.objects.filter(run_log__queue_event_id=queue_id)
        .select_related("action", "run_log", "run_log__rule")
        .order_by("created_at", "id")
    )

    queue_event["payload_pretty"] = _json_pretty(queue_event.get("payload_json"))
    queue_event["old_payload_pretty"] = _json_pretty(queue_event.get("old_payload_json"))
    queue_event["can_reset"] = queue_event.get("status") == "error"
    queue_event["can_retry"] = queue_event.get("status") in {"error", "pending"}
    queue_event["run_log_count"] = len(run_logs)
    queue_event["can_stop"] = queue_event.get("status") == "pending"
    queue_event["can_delete"] = queue_event.get("status") in {"pending", "error"} and not run_logs

    context = {
        **_base_context(),
        "poller_health": poller_health,
        "queue_event": queue_event,
        "run_logs": run_logs,
        "action_logs": action_logs,
    }
    return render(request, "automazioni/pages/queue_detail.html", context)


@legacy_admin_required
@require_POST
def queue_reset_view(request, queue_id: int):
    if reset_queue_event_to_pending(queue_id):
        messages.success(request, f"Evento queue {queue_id} riportato a pending.")
    else:
        messages.error(request, f"Reset non consentito per l'evento queue {queue_id}.")
    return redirect("admin_portale:automazioni_queue_detail", queue_id=queue_id)


@legacy_admin_required
@require_POST
def queue_retry_view(request, queue_id: int):
    result = process_single_queue_event_by_id(queue_id)
    if result["status"] == "done":
        messages.success(
            request,
            f"Retry completato per evento queue {queue_id}. Regole eseguite: {result['rule_runs']}.",
        )
    else:
        messages.error(request, f"Retry fallito per evento queue {queue_id}: {result['message']}")
    return redirect("admin_portale:automazioni_queue_detail", queue_id=queue_id)


@legacy_admin_required
@require_POST
def queue_stop_view(request, queue_id: int):
    if stop_queue_event(queue_id):
        log_action(
            request,
            "queue_stop",
            "automazioni",
            {"queue_event_id": int(queue_id), "source": "queue_admin"},
        )
        messages.success(request, f"Evento queue {queue_id} stoppato manualmente.")
    else:
        messages.error(
            request,
            f"Stop non consentito per l'evento queue {queue_id}. Sono stoppabili solo eventi ancora pending.",
        )
    return redirect("admin_portale:automazioni_queue_detail", queue_id=queue_id)


@legacy_admin_required
@require_POST
def queue_delete_view(request, queue_id: int):
    if delete_queue_event(queue_id):
        log_action(
            request,
            "queue_delete",
            "automazioni",
            {"queue_event_id": int(queue_id), "source": "queue_admin"},
        )
        messages.success(request, f"Evento queue {queue_id} eliminato.")
    else:
        messages.error(
            request,
            (
                f"Eliminazione non consentita per l'evento queue {queue_id}. "
                "Puoi eliminare solo eventi pending/error senza run log collegati."
            ),
        )
    return redirect("admin_portale:automazioni_queue_list")


@legacy_admin_required
@require_GET
def run_log_list_page(request):
    from datetime import timedelta
    from django.utils import timezone as _tz

    status = _get_filter_value(request, "status")
    source_code = _get_filter_value(request, "source_code")
    is_test = _get_filter_value(request, "is_test")
    rule_id = _get_filter_value(request, "rule")
    queue_event_id = _get_filter_value(request, "queue_event_id")
    recent = _get_filter_value(request, "recent")  # "24h" o vuoto

    queryset = AutomationRunLog.objects.select_related("rule", "initiated_by").order_by("-started_at", "-id")
    if status:
        queryset = queryset.filter(status=status)
    if source_code:
        queryset = queryset.filter(source_code=source_code)
    if is_test in {"true", "false"}:
        queryset = queryset.filter(is_test=is_test == "true")
    if rule_id:
        queryset = queryset.filter(rule_id=rule_id)
    if queue_event_id:
        queryset = queryset.filter(queue_event_id=queue_event_id)
    if recent == "24h":
        queryset = queryset.filter(started_at__gte=_tz.now() - timedelta(hours=24))

    run_logs = list(queryset[:200])
    # Max ms per la sparkbar (sui run mostrati). Evita divisioni per 0 sui chart.
    max_execution_ms = max((rl.execution_ms or 0 for rl in run_logs), default=0)

    # Conteggi rapidi per i chip (globali sulla queryset NON filtrata da status/is_test/recent,
    # così i chip mostrano "quanti ce ne sarebbero" anche quando un filtro è attivo).
    _global = AutomationRunLog.objects.all()
    if source_code:
        _global = _global.filter(source_code=source_code)
    if rule_id:
        _global = _global.filter(rule_id=rule_id)
    if queue_event_id:
        _global = _global.filter(queue_event_id=queue_event_id)
    chip_counts = {
        "errors": _global.filter(status__in=("failed", "error")).count(),
        "tests": _global.filter(is_test=True).count(),
        "recent_24h": _global.filter(started_at__gte=_tz.now() - timedelta(hours=24)).count(),
    }

    context = {
        **_base_context(),
        "run_logs": run_logs,
        "max_execution_ms": max_execution_ms,
        "chip_counts": chip_counts,
        "filters": {
            "status": status,
            "source_code": source_code,
            "is_test": is_test,
            "rule": rule_id,
            "queue_event_id": queue_event_id,
            "recent": recent,
        },
        "status_choices": AutomationRunLogStatus.values,
        "source_choices": _run_log_source_choices(),
        "rules": list(AutomationRule.objects.filter(run_logs__isnull=False).values("id", "name").distinct().order_by("name")),
    }
    return render(request, "automazioni/pages/run_log_list.html", context)


def _run_log_source_choices() -> list[tuple[str, str]]:
    """Opzioni del filtro 'Sorgente' del Run-log: sorgenti registrate + job di sistema.

    I job di sistema (task django-q tracciati con source_code 'system:<job>') non
    sono nel source registry; vengono aggiunti dinamicamente in base ai run effettivi
    cosi' restano filtrabili dalla UI.
    """
    choices = [(source["code"], source["label"]) for source in get_registered_sources()]
    known = {c[0] for c in choices}
    system_codes = (
        AutomationRunLog.objects.filter(source_code__startswith="system:")
        .values_list("source_code", flat=True)
        .distinct()
    )
    for code in sorted(set(system_codes)):
        if code in known:
            continue
        label = "Sistema: " + code.split(":", 1)[1].replace("_", " ")
        choices.append((code, label))
    return choices


@legacy_admin_required
@require_GET
def run_log_detail_page(request, run_log_id: int):
    run_log = get_object_or_404(
        AutomationRunLog.objects.select_related("rule", "initiated_by").prefetch_related("action_logs__action"),
        pk=run_log_id,
    )
    queue_event = get_queue_event_detail(run_log.queue_event_id) if run_log.queue_event_id else None
    action_logs = list(run_log.action_logs.select_related("action").order_by("created_at", "id"))

    context = {
        **_base_context(),
        "run_log": run_log,
        "queue_event": queue_event,
        "action_logs": action_logs,
        "payload_pretty": _json_pretty(run_log.payload_json),
        "old_payload_pretty": _json_pretty(run_log.old_payload_json),
    }
    return render(request, "automazioni/pages/run_log_detail.html", context)


# ---------------------------------------------------------------------------
# API: gestione whitelist tabelle (AutomationTableConfig)
# ---------------------------------------------------------------------------

@legacy_admin_required
@require_GET
def api_table_config_list(request):
    """GET /automazioni/api/table-configs/ — lista configs + tabelle disponibili per il picker."""
    configs = list(
        AutomationTableConfig.objects.values("id", "action_type", "table_name", "allowed_fields", "where_fields", "notes")
    )
    available = discover_module_tables()
    return JsonResponse({"ok": True, "configs": configs, "available": available})


@legacy_admin_required
@require_POST
def api_table_config_save(request):
    """POST /automazioni/api/table-configs/ — crea o aggiorna una voce."""
    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON non valido"}, status=400)

    action_type = str(body.get("action_type") or "").strip()
    table_name = str(body.get("table_name") or "").strip()
    allowed_fields = body.get("allowed_fields") or []
    where_fields = body.get("where_fields") or []
    notes = str(body.get("notes") or "")

    if action_type not in ("insert_record", "update_record"):
        return JsonResponse({"ok": False, "error": "action_type non valido"}, status=400)
    if not table_name:
        return JsonResponse({"ok": False, "error": "table_name obbligatorio"}, status=400)
    available = discover_module_tables()
    table_meta = available.get(table_name)
    if not table_meta:
        return JsonResponse(
            {"ok": False, "error": "table_name non valido: seleziona una tabella del catalogo moduli."},
            status=400,
        )

    def _normalize_string_list(raw_values) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_value in raw_values or []:
            text = _string_value(raw_value)
            if not text or text in seen:
                continue
            normalized.append(text)
            seen.add(text)
        return normalized

    allowed_fields = _normalize_string_list(allowed_fields)
    where_fields = _normalize_string_list(where_fields)

    writable_pool = {str(value) for value in (table_meta.get("fields") or [])}
    where_pool = {str(value) for value in (table_meta.get("all_fields") or table_meta.get("fields") or [])}
    invalid_allowed_fields = sorted(set(allowed_fields) - writable_pool)
    invalid_where_fields = sorted(set(where_fields) - where_pool)
    if invalid_allowed_fields:
        return JsonResponse(
            {
                "ok": False,
                "error": "allowed_fields contiene colonne non valide per la tabella selezionata: "
                + ", ".join(invalid_allowed_fields),
            },
            status=400,
        )
    if invalid_where_fields:
        return JsonResponse(
            {
                "ok": False,
                "error": "where_fields contiene colonne non valide per la tabella selezionata: "
                + ", ".join(invalid_where_fields),
            },
            status=400,
        )
    if action_type == AutomationActionType.INSERT_RECORD:
        where_fields = []

    obj, created = AutomationTableConfig.objects.update_or_create(
        action_type=action_type,
        table_name=table_name,
        defaults={"allowed_fields": list(allowed_fields), "where_fields": list(where_fields), "notes": notes},
    )
    return JsonResponse({"ok": True, "id": obj.pk, "created": created})


@legacy_admin_required
@require_POST
def api_table_config_delete(request, config_id: int):
    """POST /automazioni/api/table-configs/<id>/delete/ — elimina una voce."""
    deleted, _ = AutomationTableConfig.objects.filter(pk=config_id).delete()
    return JsonResponse({"ok": True, "deleted": deleted})


@legacy_admin_required
@require_GET
def api_recent_records(request, source_code: str):
    """GET /api/sorgenti/<source_code>/record-recenti/ — record recenti per il picker del test live."""
    records = list_recent_source_records(source_code, limit=20)
    return JsonResponse({"ok": True, "records": records})


@legacy_admin_required
@require_GET
def api_source_field_values(request, source_code: str, field_name: str):
    field_definition = _get_source_field_definition(source_code, field_name)
    if field_definition is None:
        return JsonResponse({"ok": False, "message": "Campo non registrato per questa sorgente."}, status=404)

    distinct_state = _fetch_source_field_distinct_values(source_code, field_name)
    allowed_values = [
        _string_value(value)
        for value in (field_definition.get("allowed_values") or [])
        if _string_value(value)
    ]
    return JsonResponse(
        {
            "ok": True,
            "source_code": _string_value(source_code),
            "field_name": _string_value(field_name),
            "field_label": _string_value(field_definition.get("label")) or _string_value(field_name),
            "ui_control": _string_value(field_definition.get("ui_control")),
            "value_source_label": _string_value(field_definition.get("value_source_label")),
            "allowed_values": allowed_values,
            "distinct_values": distinct_state["values"],
            "queryable": bool(distinct_state["queryable"]),
            "message": _string_value(distinct_state["message"]),
        }
    )


@legacy_admin_required
@require_GET
def api_record_payload(request, source_code: str, record_id: str):
    """GET /api/sorgenti/<source_code>/record/<record_id>/payload/ — payload completo di un record."""
    payload = load_source_record_payload(source_code, record_id)
    if payload is None:
        return JsonResponse({"ok": False, "message": "Record non disponibile per questa sorgente."}, status=404)
    return JsonResponse({"ok": True, "payload": payload})


@legacy_admin_required
@require_POST
def api_test_rule_ajax(request, rule_id: int):
    """POST /api/regole/<rule_id>/test-ajax/ — esegue un test della regola e restituisce i risultati JSON."""
    rule = get_object_or_404(AutomationRule, pk=rule_id)
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "message": "Body JSON non valido."}, status=400)
    payload_data = body.get("payload") or {}
    old_payload_data = body.get("old_payload") or None
    if not isinstance(payload_data, dict):
        return JsonResponse({"ok": False, "message": "Il campo 'payload' deve essere un oggetto JSON."}, status=400)
    run_log = run_rule(
        rule,
        payload_data,
        old_payload=old_payload_data,
        queue_event_id=None,
        initiated_by=request.user,
        is_test=True,
    )
    action_logs = []
    for alog in AutomationActionLog.objects.filter(run_log=run_log).order_by("id").select_related("action"):
        action_type = str(getattr(alog.action, "action_type", "") or "")
        action_desc = str(getattr(alog.action, "description", "") or "")
        action_logs.append({
            "status": str(alog.status or ""),
            "result_message": str(alog.result_message or ""),
            "error_trace": str(alog.error_trace or ""),
            "action_type": action_type,
            "action_desc": action_desc,
        })
    return JsonResponse({
        "ok": True,
        "run_log_id": run_log.id,
        "status": str(run_log.status or ""),
        "result_message": str(run_log.result_message or ""),
        "error_trace": str(run_log.error_trace or ""),
        "execution_ms": run_log.execution_ms,
        "action_logs": action_logs,
        "trigger_event_label": str(run_log.trigger_event_label or ""),
    })


# ─────────────────────────────────────────────────────────────────────────────
# Approval Decision Views (accessibili senza login, protetti da token UUID)
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
def approval_decision_page(request, token: str, decision: str):
    """
    Pagina di approvazione/rifiuto accessibile tramite link email o Teams Actionable Message.
    Non richiede login: il token UUID è la credenziale.
    decision deve essere 'approva' o 'rifiuta'.

    Quando chiamata da Teams (POST con Content-Type: application/json), risponde con
    HTTP 200 e l'header CARD-ACTION-STATUS che Teams mostra al posto dei bottoni.
    """
    from .models import AutomationApproval

    # Rileva chiamata Teams / API: POST con body JSON, senza form browser
    is_teams_call = (
        request.method == "POST"
        and "application/json" in (request.content_type or "").lower()
    )

    normalized = "approved" if decision == "approva" else "rejected" if decision == "rifiuta" else None
    if normalized is None:
        if is_teams_call:
            resp = HttpResponse("Azione non valida.", status=400, content_type="text/plain")
            resp["CARD-ACTION-STATUS"] = "Azione non valida."
            return resp
        return render(request, "automazioni/pages/approval_decision.html", {
            "error": "Azione non valida.",
            "token": token,
        })

    try:
        approval = AutomationApproval.objects.select_related("run_log__rule").get(token=token)
    except AutomationApproval.DoesNotExist:
        if is_teams_call:
            resp = HttpResponse("Richiesta non trovata.", status=404, content_type="text/plain")
            resp["CARD-ACTION-STATUS"] = "Richiesta di approvazione non trovata."
            return resp
        return render(request, "automazioni/pages/approval_decision.html", {
            "error": "Richiesta di approvazione non trovata o link non valido.",
            "token": token,
        })

    # Mostra form di conferma su GET; processa su POST
    if request.method == "GET":
        already = approval.status != AutomationApproval.Status.PENDING
        just_done = already and request.GET.get("done") == "1"
        return render(request, "automazioni/pages/approval_decision.html", {
            "approval": approval,
            "decision": normalized,
            "decision_label": "Approvare" if normalized == "approved" else "Rifiutare",
            "decision_verb": "approva" if normalized == "approved" else "rifiuta",
            "token": token,
            "is_expired": approval.is_expired(),
            "already_decided": already and not just_done,
            "just_done": just_done,
        })

    # POST: esegui la decisione
    if is_teams_call:
        # La decisione è nell'URL; il body JSON di Teams non è necessario
        decided_by = "Teams"
    else:
        decided_by = ""
        if request.user.is_authenticated:
            decided_by = str(getattr(request.user, "email", "") or request.user.username or "")

    result = process_approval_decision(str(token), normalized, decided_by_email=decided_by)

    if is_teams_call:
        if result.get("ok"):
            status_msg = "Approvato con successo." if normalized == "approved" else "Rifiutato con successo."
        else:
            status_msg = str(result.get("message") or "Impossibile processare la richiesta.")
        resp = HttpResponse("1", content_type="text/plain", status=200)
        resp["CARD-ACTION-STATUS"] = status_msg
        return resp

    if result.get("ok"):
        return redirect(request.path + "?done=1")

    return render(request, "automazioni/pages/approval_decision.html", {
        "approval": approval,
        "decision": normalized,
        "token": token,
        "result": result,
        "already_decided": not result.get("ok") and "già" in str(result.get("message") or ""),
    })


def approval_status_page(request, token: str):
    """Stato attuale di una richiesta di approvazione (link publico tramite token)."""
    from .models import AutomationApproval

    try:
        approval = AutomationApproval.objects.select_related("run_log__rule").get(token=token)
    except AutomationApproval.DoesNotExist:
        return render(request, "automazioni/pages/approval_decision.html", {
            "error": "Richiesta non trovata.",
            "token": token,
        })
    return render(request, "automazioni/pages/approval_decision.html", {
        "approval": approval,
        "token": token,
        "status_only": True,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Approval Proxy — endpoint GET ottimizzati per Entra Application Proxy
#
# Sicurezza: prima di chiamare process_approval_decision(), l'endpoint
# valida l'attore tramite validate_approval_actor() (approval_security.py),
# lo stesso helper usato dal canale mailbox Graph. Fail-closed.
#
# Identità approvatore (ordine di priorità):
#   1. request.user.email / username  (sessione Django / SSO passthrough)
#   2. HTTP_X_MS_CLIENT_PRINCIPAL_NAME  (Entra Application Proxy)
#   3. HTTP_X_FORWARDED_EMAIL           (altri proxy compatibili)
#   4. stringa vuota → bloccato con NO_IDENTITY
# ─────────────────────────────────────────────────────────────────────────────

import logging as _logging

_proxy_logger = _logging.getLogger(__name__)


def _extract_approver_identity(request) -> str:
    """Restituisce l'email dell'approvatore dal contesto della request."""
    if getattr(request, "user", None) and request.user.is_authenticated:
        return str(
            getattr(request.user, "email", "") or getattr(request.user, "username", "") or ""
        ).strip()
    # Entra Application Proxy standard headers
    for header in ("HTTP_X_MS_CLIENT_PRINCIPAL_NAME", "HTTP_X_FORWARDED_EMAIL"):
        value = request.META.get(header, "").strip()
        if value:
            return value
    return ""


@csrf_exempt
@require_http_methods(["GET", "POST"])
def approval_proxy_approve(request, token):
    """GET conferma, POST approva (Entra Proxy)."""
    return _handle_approval_proxy(request, token, "approved")


@csrf_exempt
@require_http_methods(["GET", "POST"])
def approval_proxy_reject(request, token):
    """GET conferma, POST rifiuta (Entra Proxy)."""
    return _handle_approval_proxy(request, token, "rejected")


def _handle_approval_proxy(request, token, decision: str):
    """
    Gestisce una decisione di approvazione via GET (Entra Application Proxy).

    Pipeline:
      1. Estrai identità approvatore (sessione → Entra headers → vuota)
      2. Valida identità e token via validate_approval_actor()  ← fail-closed
      3. Solo se validazione ok: chiama process_approval_decision()
      4. Scrivi AuditLog con identità effettiva
      5. Ritorna pagina esito con stato distinto per ogni tipo di errore
    """
    from .approval_security import validate_approval_actor, ErrorCode

    token_str = str(token)
    decided_by = _extract_approver_identity(request)

    # ── Validazione attore (fail-closed) ─────────────────────────────────────
    validation = validate_approval_actor(token_str, decided_by)

    if not validation.allowed:
        _proxy_logger.warning(
            "approval_proxy: validazione fallita token=%s decision=%s code=%s actor=%r reason=%s",
            token_str, decision, validation.error_code, decided_by or "(vuoto)", validation.error_message,
        )
        log_action(
            request,
            "approval_proxy_denied",
            "automazioni",
            {
                "token": token_str,
                "decision": decision,
                "actor": decided_by or "(vuoto)",
                "error_code": validation.error_code,
                "message": validation.error_message,
                "via": "entra_proxy",
                "phase": request.method.lower(),
            },
        )
        return render(request, "automazioni/pages/approval_proxy_result.html", {
            "denied": True,
            "error_code": validation.error_code,
            "error_message": validation.error_message,
            "decision": decision,
            "token": token_str,
            "decided_by": decided_by,
            # Flag distinti per il template
            "is_no_identity":     validation.error_code == ErrorCode.NO_IDENTITY,
            "is_not_found":       validation.error_code == ErrorCode.NOT_FOUND,
            "is_already_decided": validation.error_code == ErrorCode.ALREADY_DECIDED,
            "is_expired":         validation.error_code == ErrorCode.EXPIRED,
            "is_unauthorized":    validation.error_code == ErrorCode.UNAUTHORIZED,
            "is_no_approvers":    validation.error_code == ErrorCode.NO_APPROVERS,
        })

    # ── Decisione (validazione passata) ──────────────────────────────────────
    if request.method == "GET":
        return render(request, "automazioni/pages/approval_proxy_result.html", {
            "requires_confirmation": True,
            "decision": decision,
            "token": token_str,
            "decided_by": decided_by,
            "approval_id": validation.approval_id,
        })

    result = process_approval_decision(token_str, decision, decided_by_email=decided_by)

    log_action(
        request,
        "approval_proxy_decision",
        "automazioni",
        {
            "token": token_str,
            "decision": decision,
            "actor": decided_by,
            "ok": result.get("ok"),
            "approval_id": result.get("approval_id"),
            "message": result.get("message"),
            "via": "entra_proxy",
        },
    )

    if not result.get("ok"):
        _proxy_logger.warning(
            "approval_proxy: process_approval_decision ko token=%s decision=%s reason=%s",
            token_str, decision, result.get("message"),
        )

    return render(request, "automazioni/pages/approval_proxy_result.html", {
        "result": result,
        "decision": decision,
        "token": token_str,
        "decided_by": decided_by,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Canali Teams — gestione TeamsWebhookPreset
# ─────────────────────────────────────────────────────────────────────────────

@legacy_admin_required
def settings_page(request):
    from core.models import SiteConfig

    poll_result = None
    approval_imap_form = get_approval_imap_form_defaults()
    approval_graph_form = get_approval_graph_form_defaults()

    if request.method == "POST":
        action = _string_value(request.POST.get("action"))

        if action == "save_scadenze_config":
            from .scadenze_config import save_scadenze_config

            try:
                posted_giorni = int(_string_value(request.POST.get("scadenze_giorni")) or "30")
            except (TypeError, ValueError):
                posted_giorni = 30
            saved = save_scadenze_config(
                attivo=_bool_value(request.POST.get("scadenze_attivo")),
                giorni=posted_giorni,
                email_visite=_string_value(request.POST.get("scadenze_email_visite")),
                email_contratti=_string_value(request.POST.get("scadenze_email_contratti")),
                includi_visite=_bool_value(request.POST.get("scadenze_includi_visite")),
                includi_contratti=_bool_value(request.POST.get("scadenze_includi_contratti")),
            )
            if saved:
                messages.success(request, "Configurazione report scadenze salvata.")
            else:
                messages.error(request, "Impossibile salvare la configurazione report scadenze.")
            return redirect("admin_portale:automazioni_settings")

        if action == "save_runlog_retention":
            from .runlog_retention import set_retention_days

            try:
                saved_days = set_retention_days(_string_value(request.POST.get("runlog_retention_days")))
                messages.success(
                    request,
                    f"Retention RunLog impostata a {saved_days} giorni.",
                )
            except Exception:
                messages.error(request, "Impossibile salvare la retention RunLog.")
            return redirect("admin_portale:automazioni_settings")

        if action == "run_runlog_cleanup":
            from django.core.management import call_command
            from io import StringIO

            try:
                buf = StringIO()
                call_command("cleanup_run_logs", apply=True, stdout=buf, verbosity=1)
                messages.success(request, "Pulizia RunLog eseguita. " + buf.getvalue().strip().splitlines()[-1])
            except Exception as exc:
                messages.error(request, f"Pulizia RunLog fallita: {exc}")
            return redirect("admin_portale:automazioni_settings")

        if action == "save_default_approval_mailbox":
            from .approval_email_templates import APPROVAL_MAILBOX_SITE_CONFIG_KEY

            mailbox_value = _string_value(request.POST.get("approval_mailbox"))
            saved = SiteConfig.set(
                APPROVAL_MAILBOX_SITE_CONFIG_KEY,
                mailbox_value,
                "Mailbox tecnica globale usata dai template approvazione mail_reply/hybrid.",
            )
            if saved:
                messages.success(request, "Mailbox tecnica predefinita aggiornata.")
            else:
                messages.error(request, "Impossibile salvare la mailbox tecnica in SiteConfig.")
            return redirect("admin_portale:automazioni_settings")

        # ── Azioni Graph backend ──────────────────────────────────────────────
        if action == "save_approval_graph_config":
            try:
                posted_page_size = max(1, min(int(_string_value(request.POST.get("approval_graph_page_size")) or "25"), 50))
            except (TypeError, ValueError):
                posted_page_size = 25

            approval_graph_form = {
                "mailbox": _string_value(request.POST.get("approval_graph_mailbox")),
                "folder": _string_value(request.POST.get("approval_graph_folder")) or "Inbox",
                "only_unread": _bool_value(request.POST.get("approval_graph_only_unread")),
                "page_size": posted_page_size,
                "mark_read": _bool_value(request.POST.get("approval_graph_mark_read")),
            }
            ok, message = save_approval_graph_settings(
                mailbox=str(approval_graph_form["mailbox"]),
                folder=str(approval_graph_form["folder"]),
                only_unread=bool(approval_graph_form["only_unread"]),
                page_size=int(approval_graph_form["page_size"]),
                mark_read=bool(approval_graph_form["mark_read"]),
            )
            poll_result = {"ok": ok, "message": message, "output": "", "stats": {}}
            if ok:
                approval_graph_form = get_approval_graph_form_defaults()
                messages.success(request, message)
            else:
                messages.error(request, message)

        if action == "run_approval_graph_poll":
            poll_result = run_approval_poll_now(limit=25)
            if poll_result.get("ok"):
                messages.success(request, str(poll_result.get("message") or "Polling Graph completato."))
            else:
                messages.error(request, str(poll_result.get("message") or "Polling Graph fallito."))

        # ── Azioni IMAP backend (retrocompat) ────────────────────────────────
        if action == "save_approval_imap_config":
            posted_port = _string_value(request.POST.get("approval_imap_port"))
            try:
                parsed_port = max(int(posted_port or approval_imap_form["port"]), 1)
            except (TypeError, ValueError):
                parsed_port = int(approval_imap_form["port"])

            approval_imap_form = {
                "host": _string_value(request.POST.get("approval_imap_host")),
                "port": parsed_port,
                "user": _string_value(request.POST.get("approval_imap_user")),
                "password": "",
                "folder": _string_value(request.POST.get("approval_imap_folder")) or "INBOX",
                "use_ssl": _bool_value(request.POST.get("approval_imap_use_ssl")),
                "password_configured": bool(_string_value(request.POST.get("approval_imap_password")))
                or bool(approval_imap_form.get("password_configured")),
            }
            ok, message = save_approval_imap_settings(
                host=str(approval_imap_form["host"]),
                port=int(approval_imap_form["port"]),
                user=str(approval_imap_form["user"]),
                password=_string_value(request.POST.get("approval_imap_password")),
                use_ssl=bool(approval_imap_form["use_ssl"]),
                folder=str(approval_imap_form["folder"]),
            )
            poll_result = {"ok": ok, "message": message, "output": "", "stats": {}}
            if ok:
                approval_imap_form = get_approval_imap_form_defaults()
                messages.success(request, message)
            else:
                messages.error(request, message)

        if action == "run_approval_imap_poll":
            poll_result = run_approval_imap_poll_now()
            if poll_result.get("ok"):
                messages.success(request, str(poll_result.get("message") or "Polling IMAP completato."))
            else:
                messages.error(request, str(poll_result.get("message") or "Polling IMAP fallito."))

    return render(
        request,
        "automazioni/pages/impostazioni.html",
        _build_automation_settings_context(
            poll_result=poll_result,
            approval_imap_form=approval_imap_form,
            approval_graph_form=approval_graph_form,
        ),
    )


def _get_trigger_sources() -> list[dict]:
    """Restituisce le sorgenti con table_name definito, con campi non-virtual."""
    from .source_registry import get_registered_sources
    result = []
    for src in get_registered_sources():
        table_name = src.get("table_name")
        if not table_name:
            continue
        pk_field = str(src.get("pk_field") or "id")
        fields = [
            f for f in (src.get("fields") or [])
            if not f.get("is_virtual") and f.get("db_column")
        ]
        result.append({
            "code": src["code"],
            "label": src["label"],
            "table_name": table_name,
            "pk_field": pk_field,
            "supported_operations": src.get("supported_operations", ["insert", "update"]),
            "fields": fields,
        })
    return result


def _generate_trigger_sql(
    *,
    source_code: str,
    table_name: str,
    pk_field: str,
    operations: list[str],
    fields: list[dict],
) -> dict[str, str]:
    """Genera il testo SQL dei trigger INSERT e/o UPDATE per la sorgente."""

    def _col(f: dict) -> str:
        return str(f.get("db_column") or f["name"])

    def _select_block(alias: str, field_list: list[dict]) -> str:
        lines = []
        for f in field_list:
            col = _col(f)
            name = f["name"]
            if col == name:
                lines.append(f"            {alias}.{col}")
            else:
                lines.append(f"            {alias}.{col} AS {name}")
        return ",\n".join(lines)

    pk_col = next((f for f in fields if f["name"] == pk_field), None)
    pk_db_col = pk_col["db_column"] if pk_col else pk_field

    result: dict[str, str] = {}

    if "insert" in operations:
        select_block = _select_block("i", fields)
        result["insert"] = f"""-- Trigger INSERT per sorgente '{source_code}'
-- Generato da NOVICROM HUB - Generatore Trigger SQL
CREATE TRIGGER [dbo].[trg_{source_code}_automation_after_insert]
ON [dbo].[{table_name}]
AFTER INSERT
AS
BEGIN
    SET NOCOUNT ON;

    IF NOT EXISTS (SELECT 1 FROM inserted)
    BEGIN
        RETURN;
    END;

    INSERT INTO [dbo].[automation_event_queue] (
        source_code, source_table, source_pk, operation_type,
        event_code, watched_field, payload_json, old_payload_json, status
    )
    SELECT
        N'{source_code}',
        N'{table_name}',
        CAST(i.{pk_db_col} AS NVARCHAR(100)),
        N'INSERT',
        N'{source_code}_insert',
        NULL,
        (
            SELECT
{select_block}
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
        ),
        NULL,
        N'pending'
    FROM inserted AS i;
END;
GO
"""

    if "update" in operations:
        select_new = _select_block("i", fields)
        select_old = _select_block("d", fields)
        result["update"] = f"""-- Trigger UPDATE per sorgente '{source_code}'
-- Generato da NOVICROM HUB - Generatore Trigger SQL
CREATE TRIGGER [dbo].[trg_{source_code}_automation_after_update]
ON [dbo].[{table_name}]
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    IF NOT EXISTS (SELECT 1 FROM inserted)
    BEGIN
        RETURN;
    END;

    INSERT INTO [dbo].[automation_event_queue] (
        source_code, source_table, source_pk, operation_type,
        event_code, watched_field, payload_json, old_payload_json, status
    )
    SELECT
        N'{source_code}',
        N'{table_name}',
        CAST(i.{pk_db_col} AS NVARCHAR(100)),
        N'UPDATE',
        N'{source_code}_update',
        NULL,
        (
            SELECT
{select_new}
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
        ),
        (
            SELECT
{select_old}
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
        ),
        N'pending'
    FROM inserted AS i
    INNER JOIN deleted AS d
        ON d.{pk_db_col} = i.{pk_db_col};
END;
GO
"""

    return result


def _apply_trigger_sql(sql: str) -> dict[str, object]:
    """Esegue DROP + CREATE TRIGGER sul DB (compatibile con tutte le versioni SQL Server)."""
    import re
    if not getattr(settings, "AUTOMAZIONI_TRIGGER_DB_APPLY_ENABLED", False):
        return {"ok": False, "message": "Applicazione diretta al DB disabilitata da configurazione."}
    vendor = getattr(connection, "vendor", "")
    if vendor != "microsoft" and "mssql" not in vendor.lower():
        return {"ok": False, "message": "Database non è SQL Server — impossibile applicare trigger."}
    try:
        # Estrae nome trigger dal SQL
        match = re.search(r"CREATE\s+TRIGGER\s+\[?dbo\]?\.\[?(\w+)\]?", sql, re.IGNORECASE)
        if not match:
            return {"ok": False, "message": "Nome trigger non trovato nel SQL generato."}
        trigger_name = match.group(1)
        table_match = re.search(r"\bON\s+((?:\[?\w+\]?\.)?\[?\w+\]?)", sql, re.IGNORECASE)
        target_table = (table_match.group(1).replace("[", "").replace("]", "") if table_match else "")
        # Estrae solo il blocco CREATE (senza commenti iniziali e senza GO)
        ddl_match = re.search(r"(CREATE\s+TRIGGER\s+.+?)(?:^\s*GO\s*$|$)", sql, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        ddl = ddl_match.group(1).strip() if ddl_match else sql
        with connection.cursor() as cursor:
            cursor.execute(
                f"IF OBJECT_ID('[dbo].[{trigger_name}]', 'TR') IS NOT NULL "
                f"DROP TRIGGER [dbo].[{trigger_name}]"
            )
            cursor.execute(ddl)
        return {"ok": True, "trigger_name": trigger_name, "target_table": target_table}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


@legacy_admin_required
def trigger_generator_page(request):
    """Generatore visuale trigger SQL Server per le sorgenti automazioni."""
    all_sources = _get_trigger_sources()
    sources_by_code = {s["code"]: s for s in all_sources}

    selected_code = _string_value(request.POST.get("source_code") or request.GET.get("source_code"))
    if selected_code not in sources_by_code:
        selected_code = all_sources[0]["code"] if all_sources else ""

    selected_source = sources_by_code.get(selected_code)
    generated: dict[str, str] = {}
    apply_results: dict[str, dict] = {}
    action = _string_value(request.POST.get("action"))

    if request.method == "POST" and selected_source:
        selected_field_names = set(request.POST.getlist("fields"))
        selected_operations = [
            op for op in ["insert", "update"]
            if request.POST.get(f"op_{op}") == "on"
            and op in selected_source["supported_operations"]
        ]
        chosen_fields = [f for f in selected_source["fields"] if f["name"] in selected_field_names]

        if not chosen_fields:
            chosen_fields = selected_source["fields"]

        if selected_operations:
            generated = _generate_trigger_sql(
                source_code=selected_source["code"],
                table_name=selected_source["table_name"],
                pk_field=selected_source["pk_field"],
                operations=selected_operations,
                fields=chosen_fields,
            )

        if action == "apply" and generated:
            if not request.user.is_superuser:
                messages.error(request, "Solo un superuser puo applicare trigger al DB.")
                return redirect("admin_portale:automazioni_trigger_generator")
            if not getattr(settings, "AUTOMAZIONI_TRIGGER_DB_APPLY_ENABLED", False):
                messages.error(request, "Applicazione diretta al DB disabilitata da configurazione.")
                return redirect("admin_portale:automazioni_trigger_generator")
            for op, sql in generated.items():
                apply_results[op] = _apply_trigger_sql(sql)
                result = apply_results[op]
                log_action(
                    request,
                    "apply_sql_trigger",
                    "automazioni",
                    {
                        "actor": str(getattr(request.user, "email", "") or request.user.username or ""),
                        "applied_at": timezone.now().isoformat(),
                        "source_code": selected_code,
                        "operation": op,
                        "mode": "apply",
                        "ok": bool(result.get("ok")),
                        "trigger_name": result.get("trigger_name") or f"trg_{selected_source['code']}_automation_after_{op}",
                        "target_table": result.get("target_table") or f"dbo.{selected_source['table_name']}",
                        "error": str(result.get("message") or "")[:500],
                    },
                )
            if all(r["ok"] for r in apply_results.values()):
                messages.success(request, f"Trigger applicati con successo per '{selected_source['label']}'.")
            else:
                errors = [r["message"] for r in apply_results.values() if not r["ok"]]
                messages.error(request, f"Errori nell'applicazione: {'; '.join(errors)}")

    is_sql_server = getattr(connection, "vendor", "") == "microsoft" or "mssql" in getattr(connection, "vendor", "").lower()
    can_apply_to_db = bool(
        is_sql_server
        and request.user.is_superuser
        and getattr(settings, "AUTOMAZIONI_TRIGGER_DB_APPLY_ENABLED", False)
    )

    return render(request, "automazioni/pages/trigger_generator.html", {
        **_base_context(),
        "page_title": "Generatore Trigger SQL",
        "all_sources": all_sources,
        "selected_source": selected_source,
        "generated": generated,
        "apply_results": apply_results,
        "is_sql_server": is_sql_server,
        "can_apply_to_db": can_apply_to_db,
    })


@legacy_admin_required
def teams_presets_page(request):
    return render(request, "automazioni/pages/teams_presets.html", _build_teams_delivery_context())


@legacy_admin_required
def approval_mailbox_log_page(request):
    """Diagnostica: ultimi messaggi letti dalla mailbox approvazioni."""
    from .models import ApprovalMailboxMessage

    page_size = 40
    try:
        qs = ApprovalMailboxMessage.objects.select_related("linked_approval").order_by(
            "-received_at", "-created_at"
        )[:page_size]
        log_entries = list(qs)
        table_missing = False
    except Exception:
        log_entries = []
        table_missing = True

    return render(
        request,
        "automazioni/pages/approval_mailbox_log.html",
        {
            **_base_context(),
            "log_entries": log_entries,
            "table_missing": table_missing,
            "graph_status": None,  # lazy — caricato nella template se necessario
        },
    )


@legacy_admin_required
def teams_preset_create(request):
    if request.method == "POST":
        form = TeamsWebhookPresetForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Canale Teams creato.")
            return redirect("admin_portale:automazioni_teams_presets")
    else:
        form = TeamsWebhookPresetForm()
    return render(
        request,
        "automazioni/pages/teams_presets.html",
        _build_teams_delivery_context(preset_form=form, preset_form_mode="create"),
    )


@legacy_admin_required
def teams_preset_edit(request, pk: int):
    preset = get_object_or_404(TeamsWebhookPreset, pk=pk)
    if request.method == "POST":
        form = TeamsWebhookPresetForm(request.POST, instance=preset)
        if form.is_valid():
            form.save()
            messages.success(request, f"Canale '{preset.name}' aggiornato.")
            return redirect("admin_portale:automazioni_teams_presets")
    else:
        form = TeamsWebhookPresetForm(instance=preset)
    return render(
        request,
        "automazioni/pages/teams_presets.html",
        _build_teams_delivery_context(
            preset_form=form,
            preset_form_mode="edit",
            edit_preset=preset,
        ),
    )


@legacy_admin_required
@require_POST
def teams_preset_delete(request, pk: int):
    preset = get_object_or_404(TeamsWebhookPreset, pk=pk)
    name = preset.name
    preset.delete()
    messages.success(request, f"Canale '{name}' eliminato.")
    return redirect("admin_portale:automazioni_teams_presets")


@legacy_admin_required
def teams_flow_endpoint_create(request):
    _flow_endpoints, flow_endpoints_warning = _get_teams_flow_endpoints_context(active_only=None)
    if flow_endpoints_warning:
        messages.warning(request, flow_endpoints_warning)
        return redirect("admin_portale:automazioni_teams_presets")
    if request.method == "POST":
        form = AutomationDeliveryEndpointForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Endpoint Teams Flow creato.")
            return redirect("admin_portale:automazioni_teams_presets")
    else:
        form = AutomationDeliveryEndpointForm()
    return render(
        request,
        "automazioni/pages/teams_presets.html",
        _build_teams_delivery_context(flow_form=form, flow_form_mode="create"),
    )


@legacy_admin_required
def teams_flow_endpoint_edit(request, pk: int):
    _flow_endpoints, flow_endpoints_warning = _get_teams_flow_endpoints_context(active_only=None)
    if flow_endpoints_warning:
        messages.warning(request, flow_endpoints_warning)
        return redirect("admin_portale:automazioni_teams_presets")
    endpoint = get_object_or_404(
        AutomationDeliveryEndpoint,
        pk=pk,
        endpoint_type=AutomationDeliveryEndpointType.TEAMS_FLOW_WEBHOOK,
    )
    if request.method == "POST":
        form = AutomationDeliveryEndpointForm(request.POST, instance=endpoint)
        if form.is_valid():
            form.save()
            messages.success(request, f"Endpoint '{endpoint.name}' aggiornato.")
            return redirect("admin_portale:automazioni_teams_presets")
    else:
        form = AutomationDeliveryEndpointForm(instance=endpoint)
    return render(
        request,
        "automazioni/pages/teams_presets.html",
        _build_teams_delivery_context(
            flow_form=form,
            flow_form_mode="edit",
            edit_flow_endpoint=endpoint,
        ),
    )


@legacy_admin_required
@require_POST
def teams_flow_endpoint_delete(request, pk: int):
    _flow_endpoints, flow_endpoints_warning = _get_teams_flow_endpoints_context(active_only=None)
    if flow_endpoints_warning:
        messages.warning(request, flow_endpoints_warning)
        return redirect("admin_portale:automazioni_teams_presets")
    endpoint = get_object_or_404(
        AutomationDeliveryEndpoint,
        pk=pk,
        endpoint_type=AutomationDeliveryEndpointType.TEAMS_FLOW_WEBHOOK,
    )
    name = endpoint.name
    endpoint.delete()
    messages.success(request, f"Endpoint '{name}' eliminato.")
    return redirect("admin_portale:automazioni_teams_presets")


# ═══════════════════════════════════════════════════════════════════════════════
# Template Email Approvazioni — CRUD + Preview + Clone
# ═══════════════════════════════════════════════════════════════════════════════

def _get_approval_templates_context() -> dict:
    """Contesto comune: lista template + warning schema drift."""
    templates, unavailable = list_approval_email_templates(enabled_only=False)
    return {
        "approval_templates": templates,
        "approval_templates_unavailable": APPROVAL_EMAIL_TEMPLATE_UNAVAILABLE_MESSAGE if unavailable else "",
    }


@legacy_admin_required
def approval_templates_list_page(request):
    ctx = _get_approval_templates_context()
    return render(request, "automazioni/pages/approval_template_list.html", ctx)


@legacy_admin_required
def approval_template_create_page(request):
    from .approval_email_templates import get_default_approval_mailbox

    if request.method == "POST":
        form = ApprovalEmailTemplateForm(request.POST)
        if form.is_valid():
            tpl = form.save(commit=False)
            tpl.created_by = request.user
            tpl.updated_by = request.user
            tpl.save()
            messages.success(request, f"Template '{tpl.name}' creato.")
            return redirect("admin_portale:automazioni_approval_template_edit", pk=tpl.pk)
    else:
        form = ApprovalEmailTemplateForm(
            initial={"mailto_mailbox": get_default_approval_mailbox()}
        )

    _placeholders = ["id", "dipendente_nome", "tipo_assenza", "data_inizio", "data_fine", "note", "reparto", "capo_email", "approval_token", "approval_id", "approve_url", "reject_url"]
    return render(request, "automazioni/pages/approval_template_form.html", {
        "form": form,
        "is_create": True,
        "page_title": "Crea template email approvazione",
        "available_placeholders": _placeholders,
    })


@legacy_admin_required
def approval_template_edit_page(request, pk: int):
    tpl = get_object_or_404(ApprovalEmailTemplate, pk=pk)
    if request.method == "POST":
        form = ApprovalEmailTemplateForm(request.POST, instance=tpl)
        if form.is_valid():
            tpl = form.save(commit=False)
            tpl.updated_by = request.user
            tpl.save()
            messages.success(request, f"Template '{tpl.name}' aggiornato.")
            return redirect("admin_portale:automazioni_approval_template_edit", pk=tpl.pk)
    else:
        form = ApprovalEmailTemplateForm(instance=tpl)

    _placeholders = ["id", "dipendente_nome", "tipo_assenza", "data_inizio", "data_fine", "note", "reparto", "capo_email", "approval_token", "approval_id", "approve_url", "reject_url"]
    return render(request, "automazioni/pages/approval_template_form.html", {
        "form": form,
        "template": tpl,
        "is_create": False,
        "page_title": f"Modifica — {tpl.name}",
        "available_placeholders": _placeholders,
    })


@legacy_admin_required
@require_POST
def approval_template_delete_page(request, pk: int):
    tpl = get_object_or_404(ApprovalEmailTemplate, pk=pk)
    name = tpl.name
    tpl.delete()
    messages.success(request, f"Template '{name}' eliminato.")
    return redirect("admin_portale:automazioni_approval_templates")


@legacy_admin_required
@require_POST
def approval_template_clone_page(request, pk: int):
    """Clona un template esistente con nuovo code/name."""
    import uuid as _uuid
    source = get_object_or_404(ApprovalEmailTemplate, pk=pk)
    new_code_base = f"{source.code}-copia"
    suffix = str(_uuid.uuid4())[:6]
    new_code = f"{new_code_base}-{suffix}"

    clone = ApprovalEmailTemplate(
        code=new_code,
        name=f"{source.name} (copia)",
        description=source.description,
        is_enabled=False,
        delivery_mode=source.delivery_mode,
        subject_template=source.subject_template,
        title_template=source.title_template,
        intro_template=source.intro_template,
        body_template=source.body_template,
        include_facts=source.include_facts,
        facts_lines=source.facts_lines,
        approval_label=source.approval_label,
        rejection_label=source.rejection_label,
        include_mailto_actions=source.include_mailto_actions,
        mailto_mailbox=source.mailto_mailbox,
        approval_mailto_subject_template=source.approval_mailto_subject_template,
        approval_mailto_body_template=source.approval_mailto_body_template,
        rejection_mailto_subject_template=source.rejection_mailto_subject_template,
        rejection_mailto_body_template=source.rejection_mailto_body_template,
        created_by=request.user,
        updated_by=request.user,
    )
    clone.save()
    messages.success(request, f"Template clonato come '{clone.name}' (disabilitato, codice: {clone.code}).")
    return redirect("admin_portale:automazioni_approval_template_edit", pk=clone.pk)


@legacy_admin_required
def approval_template_preview_page(request, pk: int):
    """
    Preview HTML del template con dati mock o payload custom via GET params.
    Supporta ?raw=1 per restituire solo il corpo HTML (iframe-friendly).
    """
    from .approval_email_templates import (
        DEMO_PAYLOAD,
        find_unresolved_placeholders,
        render_approval_email_preview,
    )

    tpl = get_object_or_404(ApprovalEmailTemplate, pk=pk)

    # Payload personalizzato opzionale via query string (JSON encoded)
    custom_payload_raw = request.GET.get("payload", "")
    custom_payload: dict = {}
    payload_error = ""
    if custom_payload_raw:
        try:
            parsed = json.loads(custom_payload_raw)
            if isinstance(parsed, dict):
                custom_payload = parsed
            else:
                payload_error = "Il payload deve essere un oggetto JSON."
        except Exception:
            payload_error = "JSON non valido nel parametro 'payload'."

    rendered = render_approval_email_preview(tpl, custom_payload or None)
    unresolved = find_unresolved_placeholders(rendered["html_body"] + rendered["subject"])

    if request.GET.get("raw") == "1":
        return HttpResponse(rendered["html_body"], content_type="text/html; charset=utf-8")

    return render(request, "automazioni/pages/approval_template_preview.html", {
        "template": tpl,
        "rendered": rendered,
        "unresolved": unresolved,
        "demo_payload": DEMO_PAYLOAD,
        "custom_payload_raw": custom_payload_raw,
        "payload_error": payload_error,
    })
