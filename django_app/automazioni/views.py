from __future__ import annotations

import json

from django.contrib import messages
from django.db.models import Count
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from admin_portale.decorators import legacy_admin_required

from .forms import (
    AutomationActionFormSet,
    AutomationConditionFormSet,
    AutomationPackageDryRunForm,
    AutomationPackageUploadForm,
    AutomationRuleForm,
    AutomationRuleTestForm,
)
from .models import (
    AutomationAction,
    AutomationActionLog,
    AutomationActionType,
    AutomationCondition,
    AutomationConditionOperator,
    AutomationConditionValueType,
    AutomationRule,
    AutomationRuleOperationType,
    AutomationRuleTriggerScope,
    AutomationRunLog,
    AutomationRunLogStatus,
)
from .services import (
    count_queue_by_status,
    get_action_table_whitelist,
    get_queue_event_detail,
    list_queue_events,
    process_single_queue_event_by_id,
    reset_queue_event_to_pending,
    run_rule,
)
from .package_importer import (
    PackageImportError,
    analyze_package_bytes,
    build_example_payload_json,
    import_analyzed_package,
    list_recent_source_records,
    load_source_record_payload,
    run_package_dry_run,
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
PACKAGE_IMPORT_SESSION_KEY = "automazioni_package_import_state"
PACKAGE_IMPORT_RESULT_SESSION_KEY = "automazioni_package_import_result"


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
    payload = {}
    for field in get_source_fields(source_code):
        data_type = _string_value(field.get("data_type"))
        payload[_string_value(field.get("name"))] = SAMPLE_VALUE_BY_TYPE.get(data_type, "esempio")
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)


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
        "field_label": field_label,
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
    if action_type == AutomationActionType.SEND_EMAIL:
        recipients = _truncate_text(_bound_or_instance_value(form, "email_to"), 80) or "-"
        subject = _truncate_text(_bound_or_instance_value(form, "email_subject_template"), 80) or "-"
        body = _truncate_text(_bound_or_instance_value(form, "email_body_text_template"), 90) or "-"
        return [
            f"Destinatari: {recipients}",
            f"Subject: {subject}",
            f"Body: {body}",
        ]
    if action_type == AutomationActionType.WRITE_LOG:
        return [f"Messaggio: {_truncate_text(_bound_or_instance_value(form, 'write_log_message_template'), 120) or '-'}"]
    if action_type == AutomationActionType.UPDATE_DASHBOARD_METRIC:
        metric_code = _truncate_text(_bound_or_instance_value(form, "metric_code"), 80) or "-"
        operation = _truncate_text(_bound_or_instance_value(form, "metric_operation"), 80) or "-"
        value_template = _truncate_text(_bound_or_instance_value(form, "metric_value_template"), 80) or "-"
        return [
            f"Metrica: {metric_code}",
            f"Operazione: {operation}",
            f"Valore: {value_template}",
        ]
    if action_type == AutomationActionType.INSERT_RECORD:
        target_table = _truncate_text(_bound_or_instance_value(form, "insert_target_table"), 80) or "-"
        mappings_text = _string_value(_bound_or_instance_value(form, "insert_field_mappings_text"))
        mappings_count = len([line for line in mappings_text.splitlines() if _string_value(line)])
        return [
            f"Tabella: {target_table}",
            f"Field mappings: {mappings_count}",
        ]
    if action_type == AutomationActionType.UPDATE_RECORD:
        target_table = _truncate_text(_bound_or_instance_value(form, "update_target_table"), 80) or "-"
        where_field = _truncate_text(_bound_or_instance_value(form, "update_where_field"), 80) or "-"
        update_fields_text = _string_value(_bound_or_instance_value(form, "update_fields_text"))
        update_fields_count = len([line for line in update_fields_text.splitlines() if _string_value(line)])
        return [
            f"Tabella: {target_table}",
            f"Where field: {where_field}",
            f"Update fields: {update_fields_count}",
        ]
    return ["Configurazione non disponibile."]


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
                    ("is_enabled", "Si" if is_enabled else "No"),
                ],
            }
        )
    return entries


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


def _build_source_catalog_context(selected_source_code: str | None) -> dict[str, object]:
    selected = str(selected_source_code or "").strip() or _get_default_source_code()
    panels = []
    for source in get_registered_sources():
        code = str(source["code"])
        panels.append(
            {
                **source,
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
    return {
        **_base_context(),
        **_build_source_catalog_context(source_code),
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
        "human_rule_summary": _build_human_rule_summary(trigger_descriptor, condition_entries, action_entries),
        "source_definition": get_source_definition(source_code),
        "sample_payload_json": _build_example_payload(source_code),
        "condition_suggestions_json": json.dumps(_build_condition_suggestions(source_code), ensure_ascii=False),
        "action_suggestions_json": json.dumps(_build_action_suggestions(source_code), ensure_ascii=False),
    }


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
        AutomationRule.objects.select_related("created_by", "updated_by").order_by("name", "id"),
        filters,
    )
    context = {
        **_base_context(),
        "rules": list(queryset[:200]),
        "filters": filters,
        "source_choices": [(source["code"], source["label"]) for source in get_registered_sources()],
        "operation_choices": AutomationRuleOperationType.choices,
        "trigger_scope_choices": AutomationRuleTriggerScope.choices,
        "boolean_filter_choices": RULE_BOOLEAN_FILTER_CHOICES,
    }
    return render(request, "automazioni/pages/rule_list.html", context)


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
    context = {
        **_base_context(),
        "rule": rule,
        "conditions": list(rule.conditions.order_by("order", "id")),
        "actions": list(rule.actions.order_by("order", "id")),
        "recent_run_logs": recent_run_logs,
        "latest_test_log": latest_test_log,
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
        action_formset = AutomationActionFormSet(instance=rule, prefix="actions")

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
        action_formset = AutomationActionFormSet(instance=rule, prefix="actions")

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
        action_formset = AutomationActionFormSet(instance=rule, prefix="actions")

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
        action_formset = AutomationActionFormSet(instance=rule, prefix="actions")

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
        form = AutomationRuleTestForm(
            initial={
                "payload_json": json.dumps({}, indent=2),
                "old_payload_json": "",
                "is_test": True,
            }
        )

    context = {
        **_base_context(),
        **_build_source_catalog_context(rule.source_code),
        "rule": rule,
        "form": form,
        "run_log": run_log,
    }
    return render(request, "automazioni/pages/rule_test.html", context)


@legacy_admin_required
@require_GET
def queue_list_page(request):
    status = _get_filter_value(request, "status")
    source_code = _get_filter_value(request, "source_code")
    operation_type = _get_filter_value(request, "operation_type")

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

    context = {
        **_base_context(),
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

    context = {
        **_base_context(),
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
@require_GET
def run_log_list_page(request):
    status = _get_filter_value(request, "status")
    source_code = _get_filter_value(request, "source_code")
    is_test = _get_filter_value(request, "is_test")
    rule_id = _get_filter_value(request, "rule")
    queue_event_id = _get_filter_value(request, "queue_event_id")

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

    context = {
        **_base_context(),
        "run_logs": list(queryset[:200]),
        "filters": {
            "status": status,
            "source_code": source_code,
            "is_test": is_test,
            "rule": rule_id,
            "queue_event_id": queue_event_id,
        },
        "status_choices": AutomationRunLogStatus.values,
        "source_choices": [(source["code"], source["label"]) for source in get_registered_sources()],
        "rules": list(AutomationRule.objects.filter(run_logs__isnull=False).values("id", "name").distinct().order_by("name")),
    }
    return render(request, "automazioni/pages/run_log_list.html", context)


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
