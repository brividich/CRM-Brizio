from __future__ import annotations

import json
from typing import Any

from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from core.upload_mime import (
    UploadMimeValidationError,
    safe_filename,
    validate_filename,
)

from .models import (
    AutomationAction,
    AutomationActionType,
    ApprovalDeliveryMode,
    AUTOMATION_DELIVERY_ENDPOINT_UNAVAILABLE_MESSAGE,
    APPROVAL_EMAIL_TEMPLATE_UNAVAILABLE_MESSAGE,
    AutomationDeliveryEndpoint,
    AutomationDeliveryEndpointType,
    AutomationCondition,
    AutomationConditionOperator,
    AutomationConditionValueType,
    AutomationRule,
    AutomationRuleTriggerScope,
    TeamsWebhookPreset,
    list_teams_flow_endpoints,
    list_approval_email_templates,
)
from .services import discover_module_tables, get_action_table_whitelist
from .source_registry import (
    get_action_mapping_fields,
    get_condition_fields,
    get_source_choices,
    get_source_definition,
    get_source_fields,
    get_trigger_fields,
)


METRIC_OPERATION_CHOICES = (
    ("set", "Set"),
    ("increment", "Increment"),
    ("decrement", "Decrement"),
)

DELAY_MODE_CHOICES = (
    ("relative", "Dopo intervallo"),
    ("until", "Fino a data/ora"),
)

DELAY_UNIT_CHOICES = (
    ("minutes", "Minuti"),
    ("hours", "Ore"),
    ("days", "Giorni"),
)

OPERATORS_WITHOUT_EXPECTED_VALUE = {
    AutomationConditionOperator.IS_TRUE,
    AutomationConditionOperator.IS_FALSE,
    AutomationConditionOperator.IS_EMPTY,
    AutomationConditionOperator.IS_NOT_EMPTY,
    AutomationConditionOperator.CHANGED,
}


def _get_default_source_code() -> str:
    choices = get_source_choices()
    return choices[0][0] if choices else ""


def _field_choices_from_registry(source_code: str | None, *, mode: str) -> list[tuple[str, str]]:
    if mode == "trigger":
        fields = get_trigger_fields(source_code)
    elif mode == "action_mapping":
        fields = get_action_mapping_fields(source_code)
    else:
        fields = get_condition_fields(source_code)
    return [("", "---------"), *[(field["name"], f"{field['label']} ({field['name']})") for field in fields]]


def _set_widget_attr(field: forms.Field | None, key: str, value: str) -> None:
    if field is None:
        return
    field.widget.attrs[key] = value


def _append_help_text(field: forms.Field | None, extra_text: str) -> None:
    if field is None or not extra_text:
        return
    existing = str(getattr(field, "help_text", "") or "").strip()
    field.help_text = f"{existing} {extra_text}".strip() if existing else extra_text


def _mark_smart_target(
    field: forms.Field | None,
    *,
    mode: str,
    role: str = "",
    source_role: str = "",
) -> None:
    if field is None:
        return
    _set_widget_attr(field, "data-smart-target", "1")
    _set_widget_attr(field, "data-smart-mode", mode)
    if role:
        _set_widget_attr(field, "data-smart-role", role)
    if source_role:
        _set_widget_attr(field, "data-smart-source-role", source_role)


def _serialize_mapping_for_textarea(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    lines: list[str] = []
    for key, item_value in value.items():
        lines.append(f"{key} = {item_value}")
    return "\n".join(lines)


def _serialize_approval_facts_inline(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""

    lines: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        fact_name = str(item.get("name") or "").strip()
        fact_value = str(item.get("value_template") or item.get("value") or "").strip()
        if fact_name:
            lines.append(f"{fact_name} | {fact_value}")
    return "\n".join(lines)


def _infer_approval_delivery_mode(config: dict[str, Any]) -> str:
    explicit_mode = str(config.get("delivery_mode") or "").strip()
    if explicit_mode:
        return explicit_mode

    has_flow = any(
        [
            str(config.get("teams_flow_endpoint_id") or "").strip(),
            str(config.get("teams_flow_url") or "").strip(),
            str(config.get("teams_recipient_email_template") or "").strip(),
        ]
    )
    has_legacy = any(
        [
            str(config.get("teams_preset_id") or "").strip(),
            str(config.get("teams_webhook_url") or "").strip(),
        ]
    )
    has_email = bool(str(config.get("to_template") or "").strip())

    if has_flow and has_email:
        return ApprovalDeliveryMode.EMAIL_AND_TEAMS_CHAT_FLOW
    if has_flow:
        return ApprovalDeliveryMode.TEAMS_CHAT_FLOW
    if has_legacy:
        return ApprovalDeliveryMode.TEAMS_WEBHOOK_LEGACY
    return ApprovalDeliveryMode.EMAIL


def _parse_mapping_text(raw_value: str, *, field_label: str) -> dict[str, Any]:
    text = str(raw_value or "").strip()
    if not text:
        return {}

    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"{field_label}: JSON non valido.") from exc
        if not isinstance(parsed, dict):
            raise forms.ValidationError(f"{field_label}: il JSON deve essere un oggetto chiave/valore.")
        return parsed

    result: dict[str, Any] = {}
    for index, line in enumerate(text.splitlines(), start=1):
        normalized = line.strip()
        if not normalized:
            continue
        if "=" not in normalized:
            raise forms.ValidationError(
                f"{field_label}: riga {index} non valida. Usa il formato `campo = valore template`."
            )
        key, value = normalized.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise forms.ValidationError(f"{field_label}: riga {index} senza nome campo.")
        result[key] = value
    return result


def _parse_json_array_text(raw_value: str, *, field_label: str) -> list[dict[str, Any]]:
    text = str(raw_value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise forms.ValidationError(f"{field_label}: JSON non valido.") from exc
    if not isinstance(parsed, list):
        raise forms.ValidationError(f"{field_label}: il JSON deve essere un array.")
    if not all(isinstance(item, dict) for item in parsed):
        raise forms.ValidationError(f"{field_label}: ogni elemento deve essere un oggetto JSON.")
    return parsed


def _serialize_json_array_text(raw_value: Any) -> str:
    if not isinstance(raw_value, list):
        return ""
    return json.dumps(raw_value, indent=2, ensure_ascii=False)


def _safe_json_array_length(raw_value: Any) -> int:
    if isinstance(raw_value, list):
        return len([item for item in raw_value if isinstance(item, dict)])
    text = str(raw_value or "").strip()
    if not text:
        return 0
    try:
        parsed = json.loads(text)
    except Exception:
        return 0
    if not isinstance(parsed, list):
        return 0
    return len([item for item in parsed if isinstance(item, dict)])


def _split_approval_branch_actions(actions: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Divide la lista azioni di un ramo approval in:
    - update_fields: dict estratto dall'eventuale azione update_trigger_record
    - remaining: lista delle azioni non-update_trigger_record
    """
    update_fields: dict[str, Any] = {}
    remaining: list[dict[str, Any]] = []
    for act in (actions or []):
        if isinstance(act, dict) and act.get("action_type") == "update_trigger_record":
            update_fields.update((act.get("config_json") or {}).get("update_fields") or {})
        else:
            remaining.append(act)
    return update_fields, remaining


def _build_approval_branch_actions(
    form_instance: Any,
    *,
    update_fields_key: str,
    extra_json_key: str,
    branch_label: str,
    source_code: str | None,
    cleaned_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Costruisce la lista azioni inline per un ramo approval (approved/rejected).
    Antepone un'azione update_trigger_record se il campo `campo = valore` è valorizzato,
    poi concatena le eventuali azioni JSON aggiuntive.
    """
    actions: list[dict[str, Any]] = []

    update_text = str(cleaned_data.get(update_fields_key) or "").strip()
    if update_text:
        allowed_fields = _get_source_update_allowed_fields(source_code)
        try:
            update_fields = _parse_mapping_text(update_text, field_label=f"Aggiorna record ({branch_label})")
        except forms.ValidationError as exc:
            form_instance.add_error(update_fields_key, exc)
            update_fields = {}
        if update_fields:
            invalid = sorted(set(update_fields.keys()) - allowed_fields) if allowed_fields else []
            if invalid:
                form_instance.add_error(
                    update_fields_key,
                    "Campi non aggiornabili sulla sorgente selezionata: " + ", ".join(invalid) + ".",
                )
            else:
                actions.append({
                    "action_type": "update_trigger_record",
                    "description": f"Aggiorna record ({branch_label})",
                    "config_json": {"update_fields": update_fields},
                })

    extra_text = str(cleaned_data.get(extra_json_key) or "").strip()
    if extra_text:
        try:
            extra = _parse_json_array_text(extra_text, field_label=f"Azioni aggiuntive ({branch_label})")
            actions.extend(extra)
        except forms.ValidationError as exc:
            form_instance.add_error(extra_json_key, exc)

    return actions


def _parse_inline_actions_field(
    form_instance: forms.Form,
    *,
    raw_value: Any,
    field_name: str,
    field_label: str,
) -> list[dict[str, Any]]:
    try:
        return _parse_json_array_text(raw_value, field_label=field_label)
    except forms.ValidationError as exc:
        form_instance.add_error(field_name, exc)
        return []


def _validate_simple_condition_fields(
    form: forms.Form,
    *,
    field_name: str,
    operator: str,
    value_type: str,
    expected_value: str,
    field_name_key: str,
    operator_key: str,
    value_type_key: str,
    expected_value_key: str,
    label: str,
) -> None:
    if not field_name:
        form.add_error(field_name_key, f"Il campo della {label} e' obbligatorio.")
    if not operator:
        form.add_error(operator_key, f"L'operatore della {label} e' obbligatorio.")
    if not value_type:
        form.add_error(value_type_key, f"Il tipo valore della {label} e' obbligatorio.")
    if operator and operator not in OPERATORS_WITHOUT_EXPECTED_VALUE and not str(expected_value or "").strip():
        form.add_error(
            expected_value_key,
            f"Il valore atteso della {label} e' obbligatorio per l'operatore selezionato.",
        )


def _build_whitelist_help(action_type: str) -> str:
    whitelist = get_action_table_whitelist().get(action_type, {})
    catalog = discover_module_tables()
    available_count = len(catalog)
    if not whitelist:
        if available_count:
            return (
                "Nessuna tabella abilitata al momento. Il picker mostra comunque le tabelle dei moduli: "
                "usa `+ Tabella` per abilitarle e scegliere campi scrivibili / where."
            )
        return "Nessuna tabella whitelistata."

    rows = []
    for index, (table_name, table_config) in enumerate(sorted(whitelist.items())):
        if index >= 3:
            break
        fields = ", ".join(sorted(table_config.get("fields", set())))
        where_fields = ", ".join(sorted(table_config.get("where_fields", set())))
        if where_fields:
            rows.append(f"{table_name}: fields [{fields}] | where [{where_fields}]")
        else:
            rows.append(f"{table_name}: fields [{fields}]")
    extra_count = max(len(whitelist) - len(rows), 0)
    prefix = (
        f"Tabelle abilitate: {len(whitelist)}"
        + (f" su {available_count} tabelle modulo disponibili." if available_count else ".")
        + " Usa `+ Tabella` per abilitarne altre o cambiare i campi esposti."
    )
    if rows:
        prefix = f"{prefix} Esempi: " + " | ".join(rows)
    if extra_count:
        prefix = f"{prefix} | +{extra_count} altre"
    return prefix


def _build_action_table_choices(action_type: str) -> list[tuple[str, str]]:
    whitelist = get_action_table_whitelist().get(action_type, {})
    catalog = discover_module_tables()
    table_names = sorted(set(catalog.keys()) | set(whitelist.keys()))
    choices: list[tuple[str, str]] = [("", "---------")]
    for table_name in table_names:
        label = str((catalog.get(table_name) or {}).get("label") or table_name)
        if table_name not in whitelist:
            label = f"{label} [da abilitare]"
        choices.append((table_name, label))
    return choices


def _build_source_update_help(source_code: str | None) -> str:
    source = get_source_definition(source_code)
    if source is None:
        return "Seleziona una sorgente valida per vedere i campi aggiornabili del record triggerante."

    pk_field = str(source.get("pk_field") or "id")
    allowed_fields = [
        f"{field['name']} ({field['db_column']})"
        for field in get_action_mapping_fields(source_code)
        if field.get("db_column") and not field.get("is_virtual") and str(field.get("name")) != pk_field
    ]
    if not allowed_fields:
        return "Nessun campo aggiornabile disponibile per questa sorgente."
    return "Campi aggiornabili del record triggerante: " + ", ".join(allowed_fields)


def _get_source_update_allowed_fields(source_code: str | None) -> set[str]:
    source = get_source_definition(source_code)
    if source is None:
        return set()
    pk_field = str(source.get("pk_field") or "id")
    return {
        str(field["name"])
        for field in get_action_mapping_fields(source_code)
        if field.get("db_column") and not field.get("is_virtual") and str(field.get("name")) != pk_field
    }


def _select_approval_template_from_choices(
    raw_value: str,
    *,
    by_id: dict[str, Any],
    by_code: dict[str, Any],
):
    selector = str(raw_value or "").strip()
    if not selector:
        return None
    return by_id.get(selector) or by_code.get(selector)


def _normalize_run_if_config(cleaned_data: dict[str, Any]) -> dict[str, Any]:
    field_name = str(cleaned_data.get("run_if_field_name") or "").strip()
    operator = str(cleaned_data.get("run_if_operator") or "").strip()
    expected_value = str(cleaned_data.get("run_if_expected_value") or "")
    value_type = str(cleaned_data.get("run_if_value_type") or "").strip()
    compare_with_old = bool(cleaned_data.get("run_if_compare_with_old"))
    negate = bool(cleaned_data.get("run_if_negate"))

    if not any([field_name, operator, expected_value.strip(), value_type, compare_with_old, negate]):
        return {}

    return {
        "field_name": field_name,
        "operator": operator,
        "expected_value": expected_value,
        "value_type": value_type,
        "compare_with_old": compare_with_old,
        "negate": negate,
    }


def _validate_run_if(form: forms.Form, run_if_config: dict[str, Any], *, field_prefix: str = "run_if") -> None:
    if not run_if_config:
        return

    field_name = str(run_if_config.get("field_name") or "").strip()
    operator = str(run_if_config.get("operator") or "").strip()
    value_type = str(run_if_config.get("value_type") or "").strip()
    expected_value = str(run_if_config.get("expected_value") or "").strip()

    if not field_name:
        form.add_error(f"{field_prefix}_field_name", "Se imposti un branch, il campo run_if e' obbligatorio.")
    if not operator:
        form.add_error(f"{field_prefix}_operator", "Se imposti un branch, l'operatore run_if e' obbligatorio.")
    if not value_type:
        form.add_error(f"{field_prefix}_value_type", "Se imposti un branch, il value_type run_if e' obbligatorio.")
    if operator and operator not in OPERATORS_WITHOUT_EXPECTED_VALUE and not expected_value:
        form.add_error(
            f"{field_prefix}_expected_value",
            "Il valore atteso run_if e' obbligatorio per l'operatore selezionato.",
        )


class AutomationRuleForm(forms.ModelForm):
    source_code = forms.ChoiceField(choices=(), label="Sorgente")
    watched_field = forms.ChoiceField(choices=(), required=False, label="Campo osservato")

    class Meta:
        model = AutomationRule
        fields = [
            "code",
            "name",
            "description",
            "source_code",
            "operation_type",
            "trigger_scope",
            "watched_field",
            "is_active",
            "is_draft",
            "stop_on_first_failure",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "trigger_scope": "Per insert usa `all_inserts`; per update puoi usare `all_updates`, `any_change` o `specific_field`.",
            "is_draft": "Una regola bozza non viene eseguita dal worker.",
            "is_active": "Una regola attiva e non bozza e' eseguibile dal runtime.",
            "stop_on_first_failure": "Interrompe la sequenza azioni alla prima action in errore.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["source_code"].choices = get_source_choices()
        _mark_smart_target(self.fields.get("watched_field"), mode="field-select", role="watched-field", source_role="trigger")

        if not self.is_bound and not self.instance.pk:
            self.initial.setdefault("source_code", _get_default_source_code())
            self.initial.setdefault("operation_type", "update")
            self.initial.setdefault("trigger_scope", "all_updates")
            self.initial.setdefault("is_active", False)
            self.initial.setdefault("is_draft", True)

        source_code = (
            self.data.get("source_code")
            if self.is_bound
            else self.initial.get("source_code") or self.instance.source_code or _get_default_source_code()
        )
        self.fields["watched_field"].choices = _field_choices_from_registry(source_code, mode="trigger")
        self.fields["watched_field"].help_text = "Disponibile solo quando il trigger scope e' `specific_field`."

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("trigger_scope") != AutomationRuleTriggerScope.SPECIFIC_FIELD:
            cleaned_data["watched_field"] = ""

        if cleaned_data.get("is_active") and cleaned_data.get("is_draft"):
            self.add_error("is_active", "Una regola bozza non puo' essere anche attiva.")
            self.add_error("is_draft", "Una regola attiva deve essere pubblicata, non bozza.")

        return cleaned_data

    def save(self, commit: bool = True):
        instance = super().save(commit=False)
        instance.watched_field = (self.cleaned_data.get("watched_field") or "").strip() or None
        if commit:
            instance.save()
        return instance


class AutomationConditionForm(forms.ModelForm):
    field_name = forms.ChoiceField(choices=(), label="Campo")

    class Meta:
        model = AutomationCondition
        fields = [
            "order",
            "field_name",
            "operator",
            "expected_value",
            "value_type",
            "compare_with_old",
            "is_enabled",
        ]
        widgets = {
            "expected_value": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, source_code: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["order"].required = False
        _mark_smart_target(self.fields.get("field_name"), mode="field-select", role="condition-field", source_role="condition")
        if not self.instance.pk:
            self.fields["order"].initial = ""
            self.fields["is_enabled"].initial = True
        effective_source_code = source_code or getattr(getattr(self.instance, "rule", None), "source_code", None)
        self.fields["field_name"].choices = _field_choices_from_registry(effective_source_code, mode="condition")
        self.fields["expected_value"].help_text = (
            "Per `changed_from_to` usa il formato `vecchio|nuovo`. Per `in_csv` usa valori separati da virgola."
        )


class AutomationActionForm(forms.ModelForm):
    run_if_field_name = forms.ChoiceField(required=False, choices=(), label="Esegui solo se - campo")
    run_if_operator = forms.ChoiceField(
        required=False,
        choices=(("", "---------"), *AutomationConditionOperator.choices),
        label="Esegui solo se - operatore",
    )
    run_if_expected_value = forms.CharField(
        required=False,
        label="Esegui solo se - valore atteso",
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    run_if_value_type = forms.ChoiceField(
        required=False,
        choices=(("", "---------"), *AutomationConditionValueType.choices),
        label="Esegui solo se - tipo valore",
    )
    run_if_compare_with_old = forms.BooleanField(required=False, label="Esegui solo se - usa old payload")
    run_if_negate = forms.BooleanField(required=False, label="Esegui solo se - inverti risultato")

    email_from_email = forms.CharField(required=False, label="From email")
    email_to = forms.CharField(required=False, label="To", widget=forms.Textarea(attrs={"rows": 2}))
    email_cc = forms.CharField(required=False, label="CC", widget=forms.Textarea(attrs={"rows": 2}))
    email_bcc = forms.CharField(required=False, label="BCC", widget=forms.Textarea(attrs={"rows": 2}))
    email_reply_to = forms.CharField(required=False, label="Reply-to", widget=forms.Textarea(attrs={"rows": 2}))
    email_subject_template = forms.CharField(required=False, label="Subject template")
    email_body_text_template = forms.CharField(
        required=False,
        label="Body text template",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    email_body_html_template = forms.CharField(
        required=False,
        label="Body HTML template",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    email_fail_silently = forms.BooleanField(required=False, label="Fail silently")

    write_log_message_template = forms.CharField(
        required=False,
        label="Message template",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    metric_code = forms.CharField(required=False, label="Metric code")
    metric_operation = forms.ChoiceField(required=False, choices=(("", "---------"), *METRIC_OPERATION_CHOICES))
    metric_value_template = forms.CharField(required=False, label="Value template")

    insert_target_table = forms.ChoiceField(required=False, choices=(), label="Target table")
    insert_field_mappings_text = forms.CharField(
        required=False,
        label="Field mappings",
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Un mapping per riga: `campo_destinazione = valore template`. Supportato anche JSON object.",
    )

    update_target_table = forms.ChoiceField(required=False, choices=(), label="Target table")
    update_where_field = forms.CharField(required=False, label="Where field")
    update_where_value_template = forms.CharField(required=False, label="Where value template")
    update_fields_text = forms.CharField(
        required=False,
        label="Update fields",
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Un mapping per riga: `campo_destinazione = valore template`. Supportato anche JSON object.",
    )

    trigger_update_fields_text = forms.CharField(
        required=False,
        label="Campi record triggerante",
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Un mapping per riga: `campo_sorgente = valore template`. Supportato anche JSON object.",
    )

    split_start_field = forms.CharField(required=False, label="Campo data inizio")
    split_end_field = forms.CharField(required=False, label="Campo data fine")
    split_days_count_fields = forms.CharField(required=False, label="Campi numero giorni")
    split_max_days = forms.IntegerField(required=False, label="Max giorni creati", min_value=1, max_value=366)
    split_tipo_assenza_template = forms.CharField(required=False, label="Tipo assenza righe create")
    split_moderation_status = forms.IntegerField(required=False, label="Moderation status righe create")
    split_consenso_template = forms.CharField(required=False, label="Consenso righe create")
    split_salta_approvazione = forms.BooleanField(required=False, label="Salta approvazione sulle righe create")
    split_include_first_day = forms.BooleanField(required=False, label="Crea anche il primo giorno")
    split_dedupe = forms.BooleanField(required=False, label="Evita duplicati")

    delay_mode = forms.ChoiceField(required=False, choices=DELAY_MODE_CHOICES, label="Modalita' delay")
    delay_value_template = forms.CharField(required=False, label="Valore delay")
    delay_unit = forms.ChoiceField(required=False, choices=DELAY_UNIT_CHOICES, label="Unita' delay")
    delay_until_template = forms.CharField(required=False, label="Data/ora target")

    http_method = forms.ChoiceField(
        required=False,
        label="Metodo HTTP",
        choices=(("", "---------"), ("GET", "GET"), ("POST", "POST"), ("PUT", "PUT"), ("PATCH", "PATCH"), ("DELETE", "DELETE")),
    )
    http_url_template = forms.CharField(required=False, label="URL template")
    http_headers_text = forms.CharField(
        required=False,
        label="Headers",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Un mapping per riga: `Header-Name = valore template`. Supportato anche JSON object.",
    )
    http_body_template = forms.CharField(
        required=False,
        label="Body template",
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    http_timeout_seconds = forms.IntegerField(required=False, label="Timeout secondi", min_value=1)
    http_expected_status_csv = forms.CharField(
        required=False,
        label="Status attesi",
        help_text="CSV opzionale di status code ammessi, es. `200,201,204`.",
    )

    # ── SEND_ANOMALIE_MAIL_ACTION ─────────────────────────────────────────
    anomalie_mail_to = forms.CharField(required=False, label="Destinatario (email o template)")
    anomalie_mail_recipient_display = forms.CharField(required=False, label="Nome destinatario (template)")
    anomalie_mail_action = forms.ChoiceField(
        required=False,
        label="Azione mail-action",
        choices=[
            ("visualizza", "Visualizza"),
            ("prendi_in_carico", "Prendi in carico"),
            ("approva", "Approva"),
            ("respingi", "Respingi"),
            ("richiedi_modifica", "Richiedi modifica"),
            ("chiudi", "Chiudi"),
        ],
    )
    anomalie_mail_expires_hours = forms.IntegerField(
        required=False, label="Scadenza link (ore)", initial=48,
        widget=forms.NumberInput(attrs={"min": 1}),
    )
    anomalie_mail_source_automation = forms.CharField(required=False, label="Label audit (source_automation)")

    # ── SEND_ANOMALIE_MAIL_ACTION_BY_OP ───────────────────────────────────
    anomalie_op_benestare_field = forms.CharField(
        required=False, label="Campo benestare nel payload",
        widget=forms.TextInput(attrs={"placeholder": "es. benestare"}),
    )
    anomalie_op_action = forms.ChoiceField(
        required=False,
        label="Azione mail-action",
        choices=[
            ("prendi_in_carico", "Prendi in carico"),
            ("conferma", "Conferma"),
            ("rifiuta", "Rifiuta"),
            ("richiedi_info", "Richiedi informazioni"),
        ],
    )
    anomalie_op_expires_hours = forms.IntegerField(
        required=False, label="Scadenza link (ore)", initial=48,
        widget=forms.NumberInput(attrs={"min": 1}),
    )
    anomalie_op_source_automation = forms.CharField(required=False, label="Label audit (source_automation)")

    teams_webhook_url = forms.CharField(required=False, label="Teams webhook URL")
    teams_title_template = forms.CharField(required=False, label="Titolo card")
    teams_summary_template = forms.CharField(required=False, label="Summary")
    teams_text_template = forms.CharField(
        required=False,
        label="Testo card",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    teams_theme_color = forms.CharField(required=False, label="Theme color")
    teams_facts_text = forms.CharField(
        required=False,
        label="Facts",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Un mapping per riga: `Etichetta = valore template`. Supportato anche JSON object.",
    )

    # ── SEND_APPROVAL (usati solo nel designer) ────────────────────────────
    approval_delivery_mode = forms.ChoiceField(
        required=False,
        label="Modalita' recapito approvazione",
        choices=ApprovalDeliveryMode.choices,
        initial=ApprovalDeliveryMode.EMAIL,
    )
    approval_to_template = forms.CharField(
        required=False, label="Email approvatori",
        widget=forms.TextInput(attrs={"placeholder": "{capo_email} oppure manager@azienda.com"}),
    )
    approval_subject_template = forms.CharField(
        required=False, label="Oggetto email",
        widget=forms.TextInput(attrs={"placeholder": "Approvazione richiesta #{id}"}),
    )
    approval_message_template = forms.CharField(
        required=False, label="Testo del messaggio",
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Si richiede la tua approvazione per la richiesta #{id}..."}),
    )
    approval_expiry_days = forms.IntegerField(
        required=False, min_value=1, max_value=365, label="Scadenza (giorni)", initial=7,
    )
    approval_approve_label = forms.CharField(
        required=False, label='Label "Approva"',
        widget=forms.TextInput(attrs={"placeholder": "Approva"}),
    )
    approval_reject_label = forms.CharField(
        required=False, label='Label "Rifiuta"',
        widget=forms.TextInput(attrs={"placeholder": "Rifiuta"}),
    )
    approval_teams_preset_id = forms.ChoiceField(
        required=False, label="Canale Teams legacy",
        choices=[("", "— non inviare su Teams —")],
    )
    approval_teams_flow_endpoint_id = forms.ChoiceField(
        required=False,
        label="Endpoint Teams Flow",
        choices=[("", "â€” seleziona endpoint Flow â€”")],
    )
    approval_teams_recipient_email_template = forms.CharField(
        required=False,
        label="Email destinatario Teams",
        widget=forms.TextInput(attrs={"placeholder": "{capo_email} oppure utente@azienda.it"}),
    )
    approval_teams_title_template = forms.CharField(
        required=False, label="Titolo card Teams",
        widget=forms.TextInput(attrs={"placeholder": "Approvazione richiesta #{id} — {dipendente_nome}"}),
    )
    approval_teams_facts_inline = forms.CharField(
        required=False, label="Fatti (una riga: Etichetta | {valore})",
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Tipo | {tipo_assenza}\nInizio | {data_inizio}\nFine | {data_fine}"}),
    )
    approval_strict_teams_flow = forms.BooleanField(
        required=False,
        label="Errore se Teams Flow fallisce",
        help_text="Usato solo per `email_and_teams_chat_flow`: se attivo, email inviata ma Teams KO rende l'action in errore.",
    )
    approval_email_template_id = forms.ChoiceField(
        required=False,
        label="Template email approvazione",
        choices=[("", "— nessun template (comportamento standard) —")],
        help_text=(
            "Seleziona un template per personalizzare il contenuto della mail. "
            "Se lasciato vuoto, viene usato il corpo base definito direttamente nella regola."
        ),
    )
    approval_approved_update_fields_text = forms.CharField(
        required=False,
        label="Aggiorna record (se approvato)",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Un mapping per riga: `campo = valore template`. Aggiorna il record che ha avviato il flusso.",
    )
    approval_rejected_update_fields_text = forms.CharField(
        required=False,
        label="Aggiorna record (se rifiutato)",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Un mapping per riga: `campo = valore template`. Aggiorna il record che ha avviato il flusso.",
    )
    approval_approved_actions_json = forms.CharField(
        required=False,
        label="Azioni aggiuntive (JSON array)",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text='Altre azioni inline oltre all\'aggiornamento record, es. [{"action_type":"write_log","config_json":{"message_template":"OK"}}].',
    )
    approval_rejected_actions_json = forms.CharField(
        required=False,
        label="Azioni aggiuntive (JSON array)",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text='Altre azioni inline oltre all\'aggiornamento record, es. [{"action_type":"write_log","config_json":{"message_template":"KO"}}].',
    )

    loop_check_field = forms.ChoiceField(required=False, choices=(), label="Campo da controllare")
    loop_check_operator = forms.ChoiceField(
        required=False,
        choices=(("", "---------"), *AutomationConditionOperator.choices),
        label="Operatore condizione uscita",
    )
    loop_check_value = forms.CharField(required=False, label="Valore atteso", widget=forms.TextInput())
    loop_check_value_type = forms.ChoiceField(
        required=False,
        choices=(("", "---------"), *AutomationConditionValueType.choices),
        label="Tipo valore",
    )
    loop_retry_delay_value = forms.IntegerField(required=False, min_value=1, label="Ritardo retry")
    loop_retry_delay_unit = forms.ChoiceField(required=False, choices=DELAY_UNIT_CHOICES, label="Unita' ritardo")
    loop_max_iterations = forms.IntegerField(required=False, min_value=1, max_value=100, label="Max iterazioni")
    loop_loop_actions_json = forms.CharField(
        required=False,
        label="Azioni corpo loop",
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text='Array JSON di azioni inline eseguite a ogni iterazione, es. [{"action_type":"write_log","config_json":{"message_template":"Reminder {id}"}}].',
    )
    loop_on_success_actions_json = forms.CharField(
        required=False,
        label="Azioni se condizione soddisfatta",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text='Array JSON di azioni inline eseguite quando il loop termina con successo.',
    )
    loop_on_timeout_actions_json = forms.CharField(
        required=False,
        label="Azioni se max iterazioni raggiunto",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text='Array JSON di azioni inline eseguite quando il loop va in timeout.',
    )

    each_source_code = forms.ChoiceField(required=False, choices=(), label="Sorgente dati")
    each_filter_field = forms.CharField(required=False, label="Campo filtro")
    each_filter_value_template = forms.CharField(required=False, label="Valore filtro (template)")
    each_max_items = forms.IntegerField(required=False, min_value=1, max_value=500, label="Max elementi")
    each_actions_json = forms.CharField(
        required=False,
        label="Azioni per ogni record",
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text='Array JSON di azioni inline eseguite per ogni record trovato.',
    )

    branch_condition_field = forms.ChoiceField(required=False, choices=(), label="Campo")
    branch_condition_operator = forms.ChoiceField(
        required=False,
        choices=(("", "---------"), *AutomationConditionOperator.choices),
        label="Operatore",
    )
    branch_condition_value = forms.CharField(required=False, label="Valore", widget=forms.TextInput())
    branch_condition_value_type = forms.ChoiceField(
        required=False,
        choices=(("", "---------"), *AutomationConditionValueType.choices),
        label="Tipo valore",
    )
    branch_compare_with_old = forms.BooleanField(required=False, label="Confronta con old payload")
    branch_if_true_actions_json = forms.CharField(
        required=False,
        label="Azioni se vero",
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text='Array JSON di azioni inline eseguite nel ramo true.',
    )
    branch_if_false_actions_json = forms.CharField(
        required=False,
        label="Azioni se falso",
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text='Array JSON di azioni inline eseguite nel ramo false.',
    )

    class Meta:
        model = AutomationAction
        fields = [
            "order",
            "action_type",
            "is_enabled",
            "description",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, source_code: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._effective_source_code = source_code or getattr(getattr(self.instance, "rule", None), "source_code", None)
        self.fields["order"].required = False
        if not self.instance.pk:
            if not self.is_bound:
                self.fields["order"].initial = ""
                self.fields["is_enabled"].initial = True
                self.fields["delay_mode"].initial = "relative"
                self.fields["delay_unit"].initial = "days"
                self.fields["split_start_field"].initial = "data_inizio"
                self.fields["split_end_field"].initial = "data_fine"
                self.fields["split_days_count_fields"].initial = "giorni_permesso,giornipermesso,Giornipermesso,giorni"
                self.fields["split_max_days"].initial = 60
                self.fields["split_tipo_assenza_template"].initial = "Permesso"
                self.fields["split_moderation_status"].initial = 0
                self.fields["split_consenso_template"].initial = "Approvato"
                self.fields["split_salta_approvazione"].initial = True
                self.fields["split_dedupe"].initial = True
                self.fields["http_method"].initial = "POST"
                self.fields["http_timeout_seconds"].initial = 20
                self.fields["loop_check_operator"].initial = AutomationConditionOperator.EQUALS
                self.fields["loop_check_value_type"].initial = AutomationConditionValueType.STRING
                self.fields["loop_retry_delay_value"].initial = 24
                self.fields["loop_retry_delay_unit"].initial = "hours"
                self.fields["loop_max_iterations"].initial = 10
                self.fields["each_max_items"].initial = 50
                self.fields["branch_condition_operator"].initial = AutomationConditionOperator.EQUALS
                self.fields["branch_condition_value_type"].initial = AutomationConditionValueType.STRING

        self.fields["insert_target_table"].choices = _build_action_table_choices(AutomationActionType.INSERT_RECORD)
        self.fields["update_target_table"].choices = _build_action_table_choices(AutomationActionType.UPDATE_RECORD)
        self.fields["run_if_field_name"].choices = _field_choices_from_registry(self._effective_source_code, mode="condition")
        self.fields["loop_check_field"].choices = _field_choices_from_registry(self._effective_source_code, mode="condition")
        self.fields["branch_condition_field"].choices = _field_choices_from_registry(self._effective_source_code, mode="condition")
        self.fields["each_source_code"].choices = get_source_choices()
        _mark_smart_target(self.fields.get("run_if_field_name"), mode="field-select", role="run-if-field", source_role="condition")
        _mark_smart_target(self.fields.get("loop_check_field"), mode="field-select", role="loop-check-field", source_role="condition")
        _mark_smart_target(self.fields.get("branch_condition_field"), mode="field-select", role="branch-condition-field", source_role="condition")
        _mark_smart_target(self.fields.get("email_from_email"), mode="template-input", role="email-from", source_role="template")
        _mark_smart_target(self.fields.get("email_to"), mode="template-input", role="email-to", source_role="template")
        _mark_smart_target(self.fields.get("email_cc"), mode="template-input", role="email-cc", source_role="template")
        _mark_smart_target(self.fields.get("email_bcc"), mode="template-input", role="email-bcc", source_role="template")
        _mark_smart_target(self.fields.get("email_reply_to"), mode="template-input", role="email-reply-to", source_role="template")
        _mark_smart_target(self.fields.get("email_subject_template"), mode="template-input", role="email-subject", source_role="template")
        _mark_smart_target(self.fields.get("email_body_text_template"), mode="template-input", role="email-body-text", source_role="template")
        _mark_smart_target(self.fields.get("email_body_html_template"), mode="template-input", role="email-body-html", source_role="template")
        _mark_smart_target(self.fields.get("write_log_message_template"), mode="template-input", role="write-log-message", source_role="template")
        _mark_smart_target(self.fields.get("metric_value_template"), mode="template-input", role="metric-value", source_role="template")
        _mark_smart_target(self.fields.get("insert_field_mappings_text"), mode="mapping-input", role="insert-mapping", source_role="template")
        _mark_smart_target(self.fields.get("update_where_value_template"), mode="template-input", role="update-where-value", source_role="template")
        _mark_smart_target(self.fields.get("update_fields_text"), mode="mapping-input", role="update-fields", source_role="template")
        _mark_smart_target(self.fields.get("trigger_update_fields_text"), mode="mapping-input", role="trigger-update-fields", source_role="template")
        _mark_smart_target(self.fields.get("split_tipo_assenza_template"), mode="template-input", role="split-tipo-assenza", source_role="template")
        _mark_smart_target(self.fields.get("split_consenso_template"), mode="template-input", role="split-consenso", source_role="template")
        _mark_smart_target(self.fields.get("delay_value_template"), mode="template-input", role="delay-value", source_role="template")
        _mark_smart_target(self.fields.get("delay_until_template"), mode="template-input", role="delay-until", source_role="template")
        _mark_smart_target(self.fields.get("http_url_template"), mode="template-input", role="http-url", source_role="template")
        _mark_smart_target(self.fields.get("http_headers_text"), mode="mapping-input", role="http-headers", source_role="template")
        _mark_smart_target(self.fields.get("http_body_template"), mode="template-input", role="http-body", source_role="template")
        _mark_smart_target(self.fields.get("teams_webhook_url"), mode="template-input", role="teams-webhook-url", source_role="template")
        _mark_smart_target(self.fields.get("teams_title_template"), mode="template-input", role="teams-title", source_role="template")
        _mark_smart_target(self.fields.get("teams_summary_template"), mode="template-input", role="teams-summary", source_role="template")
        _mark_smart_target(self.fields.get("teams_text_template"), mode="template-input", role="teams-text", source_role="template")
        _mark_smart_target(self.fields.get("teams_facts_text"), mode="mapping-input", role="teams-facts", source_role="template")
        _mark_smart_target(self.fields.get("approval_to_template"), mode="template-input", role="approval-email-to", source_role="template")
        _mark_smart_target(self.fields.get("approval_subject_template"), mode="template-input", role="approval-subject", source_role="template")
        _mark_smart_target(self.fields.get("approval_message_template"), mode="template-input", role="approval-message", source_role="template")
        _mark_smart_target(self.fields.get("approval_teams_recipient_email_template"), mode="template-input", role="approval-teams-recipient", source_role="template")
        _mark_smart_target(self.fields.get("approval_teams_title_template"), mode="template-input", role="approval-teams-title", source_role="template")
        _mark_smart_target(self.fields.get("approval_teams_facts_inline"), mode="template-input", role="approval-teams-facts", source_role="template")
        _mark_smart_target(self.fields.get("approval_approved_update_fields_text"), mode="mapping-input", role="approval-approved-update-fields", source_role="template")
        _mark_smart_target(self.fields.get("approval_rejected_update_fields_text"), mode="mapping-input", role="approval-rejected-update-fields", source_role="template")
        _mark_smart_target(self.fields.get("approval_approved_actions_json"), mode="json-editor", role="approval-approved-actions", source_role="template")
        _mark_smart_target(self.fields.get("approval_rejected_actions_json"), mode="json-editor", role="approval-rejected-actions", source_role="template")
        _mark_smart_target(self.fields.get("loop_loop_actions_json"), mode="json-editor", role="loop-actions", source_role="template")
        _mark_smart_target(self.fields.get("loop_on_success_actions_json"), mode="json-editor", role="loop-success-actions", source_role="template")
        _mark_smart_target(self.fields.get("loop_on_timeout_actions_json"), mode="json-editor", role="loop-timeout-actions", source_role="template")
        _mark_smart_target(self.fields.get("each_actions_json"), mode="json-editor", role="each-actions", source_role="template")
        _mark_smart_target(self.fields.get("branch_if_true_actions_json"), mode="json-editor", role="branch-true-actions", source_role="template")
        _mark_smart_target(self.fields.get("branch_if_false_actions_json"), mode="json-editor", role="branch-false-actions", source_role="template")
        source_update_help = _build_source_update_help(self._effective_source_code)
        self.fields["approval_approved_update_fields_text"].help_text = source_update_help or self.fields["approval_approved_update_fields_text"].help_text
        self.fields["approval_rejected_update_fields_text"].help_text = source_update_help or self.fields["approval_rejected_update_fields_text"].help_text
        self.fields["run_if_expected_value"].help_text = (
            "Per `changed_from_to` usa `vecchio|nuovo`. Se spunti `inverti risultato`, il branch diventa un ELSE."
        )
        self.fields["insert_target_table"].help_text = (
            "Il picker mostra le tabelle dei moduli. Quelle marcate `da abilitare` vanno prima configurate con `+ Tabella`."
        )
        self.fields["update_target_table"].help_text = (
            "Il picker mostra le tabelle dei moduli. Quelle marcate `da abilitare` vanno prima configurate con `+ Tabella`."
        )
        self.fields["insert_field_mappings_text"].help_text = _build_whitelist_help(AutomationActionType.INSERT_RECORD)
        self.fields["update_fields_text"].help_text = _build_whitelist_help(AutomationActionType.UPDATE_RECORD)
        self.fields["trigger_update_fields_text"].help_text = _build_source_update_help(self._effective_source_code)
        self.fields["split_days_count_fields"].help_text = (
            "CSV opzionale di campi payload da usare come numero giorni. "
            "Se non disponibili, lo split usa la differenza tra data_inizio e data_fine."
        )
        self.fields["split_tipo_assenza_template"].help_text = "Template o valore fisso; per replicare il flow storico usa `Permesso`."
        self.fields["delay_value_template"].help_text = "Numero o placeholder, es. `1`, `4`, `{giorni}`."
        self.fields["delay_until_template"].help_text = "Data/ora ISO o placeholder, es. `2026-04-10T15:30:00`."
        self.fields["branch_if_true_actions_json"].help_text = (
            "Per aggiungere una seconda condizione dentro il ramo, inserisci un'altra azione `branch`."
        )
        self.fields["branch_if_false_actions_json"].help_text = (
            "Puoi usare questo ramo come vero ELSE oppure annidare un altro `branch`."
        )

        config = self.instance.config_json if isinstance(getattr(self.instance, "config_json", None), dict) else {}

        # Populate approval_teams_preset_id choices from DB
        try:
            preset_choices = [("", "— non inviare su Teams —")] + [
                (str(p.pk), p.name + (f" — {p.description}" if p.description else ""))
                for p in TeamsWebhookPreset.objects.filter(is_active=True).order_by("name")
            ]
        except Exception:
            preset_choices = [("", "— non inviare su Teams —")]
        self.fields["approval_teams_preset_id"].choices = preset_choices

        try:
            endpoint_choices = [("", "â€” seleziona endpoint Flow â€”")] + [
                (str(endpoint.pk), endpoint.name + (f" â€” {endpoint.description}" if endpoint.description else ""))
                for endpoint in AutomationDeliveryEndpoint.objects.filter(
                    endpoint_type=AutomationDeliveryEndpointType.TEAMS_FLOW_WEBHOOK,
                    is_active=True,
                ).order_by("name")
            ]
        except Exception:
            endpoint_choices = [("", "â€” seleziona endpoint Flow â€”")]
        endpoint_choices = [(value, str(label).replace("Ã¢â‚¬â€", "--")) for value, label in endpoint_choices]
        self.fields["approval_teams_flow_endpoint_id"].choices = endpoint_choices

        flow_endpoints, self._teams_flow_endpoints_unavailable = list_teams_flow_endpoints(active_only=True)
        self.fields["approval_teams_flow_endpoint_id"].choices = [
            ("", "-- seleziona endpoint Flow --"),
            *[
                (str(endpoint.pk), endpoint.name + (f" -- {endpoint.description}" if endpoint.description else ""))
                for endpoint in flow_endpoints
            ],
        ]
        if self._teams_flow_endpoints_unavailable:
            _append_help_text(
                self.fields.get("approval_teams_flow_endpoint_id"),
                AUTOMATION_DELIVERY_ENDPOINT_UNAVAILABLE_MESSAGE,
            )

        # Popola scelte template email approvazione
        approval_templates, self._approval_templates_unavailable = list_approval_email_templates(enabled_only=True)
        self._approval_templates_by_id = {str(tpl.pk): tpl for tpl in approval_templates}
        self._approval_templates_by_code = {str(tpl.code): tpl for tpl in approval_templates}
        self.fields["approval_email_template_id"].choices = [
            ("", "— nessun template (comportamento standard) —"),
            *[
                (
                    str(tpl.pk),
                    tpl.name + (f" [{tpl.get_delivery_mode_display()}]" if tpl.delivery_mode else ""),
                )
                for tpl in approval_templates
            ],
        ]
        if self._approval_templates_unavailable:
            _append_help_text(
                self.fields.get("approval_email_template_id"),
                APPROVAL_EMAIL_TEMPLATE_UNAVAILABLE_MESSAGE,
            )

        if config:
            run_if = config.get("run_if") if isinstance(config.get("run_if"), dict) else {}
            self.initial.setdefault("run_if_field_name", run_if.get("field_name", ""))
            self.initial.setdefault("run_if_operator", run_if.get("operator", ""))
            self.initial.setdefault("run_if_expected_value", run_if.get("expected_value", ""))
            self.initial.setdefault("run_if_value_type", run_if.get("value_type", ""))
            self.initial.setdefault("run_if_compare_with_old", bool(run_if.get("compare_with_old")))
            self.initial.setdefault("run_if_negate", bool(run_if.get("negate")))
            self.initial.setdefault("email_from_email", config.get("from_email", ""))
            self.initial.setdefault("email_to", config.get("to", ""))
            self.initial.setdefault("email_cc", config.get("cc", ""))
            self.initial.setdefault("email_bcc", config.get("bcc", ""))
            self.initial.setdefault("email_reply_to", config.get("reply_to", ""))
            self.initial.setdefault("email_subject_template", config.get("subject_template", ""))
            self.initial.setdefault("email_body_text_template", config.get("body_text_template", ""))
            self.initial.setdefault("email_body_html_template", config.get("body_html_template", ""))
            self.initial.setdefault("email_fail_silently", bool(config.get("fail_silently")))
            self.initial.setdefault("write_log_message_template", config.get("message_template", ""))
            self.initial.setdefault("metric_code", config.get("metric_code", ""))
            self.initial.setdefault("metric_operation", config.get("operation", ""))
            self.initial.setdefault("metric_value_template", config.get("value_template", ""))
            self.initial.setdefault("insert_target_table", config.get("target_table", ""))
            self.initial.setdefault("insert_field_mappings_text", _serialize_mapping_for_textarea(config.get("field_mappings")))
            self.initial.setdefault("update_target_table", config.get("target_table", ""))
            self.initial.setdefault("update_where_field", config.get("where_field", ""))
            self.initial.setdefault("update_where_value_template", config.get("where_value_template", ""))
            self.initial.setdefault("update_fields_text", _serialize_mapping_for_textarea(config.get("update_fields")))
            self.initial.setdefault(
                "trigger_update_fields_text",
                _serialize_mapping_for_textarea(config.get("update_fields")),
            )
            self.initial.setdefault("split_start_field", config.get("start_field", "data_inizio"))
            self.initial.setdefault("split_end_field", config.get("end_field", "data_fine"))
            split_days_count_fields = config.get("days_count_fields", config.get("days_count_field", "giorni_permesso,giornipermesso,Giornipermesso,giorni"))
            if isinstance(split_days_count_fields, list):
                split_days_count_fields = ",".join(str(item) for item in split_days_count_fields if str(item).strip())
            self.initial.setdefault("split_days_count_fields", split_days_count_fields)
            self.initial.setdefault("split_max_days", config.get("max_days", 60))
            self.initial.setdefault("split_tipo_assenza_template", config.get("tipo_assenza_template", config.get("created_type_template", "Permesso")))
            self.initial.setdefault("split_moderation_status", config.get("moderation_status", config.get("set_moderation_status", 0)))
            self.initial.setdefault("split_consenso_template", config.get("consenso_template", config.get("set_consenso", "Approvato")))
            self.initial.setdefault("split_salta_approvazione", config.get("salta_approvazione", config.get("set_salta_approvazione", True)))
            self.initial.setdefault("split_include_first_day", bool(config.get("include_first_day")))
            self.initial.setdefault("split_dedupe", config.get("dedupe", True))
            self.initial.setdefault("delay_mode", config.get("mode", "relative"))
            self.initial.setdefault("delay_value_template", config.get("value_template", config.get("giorni", "")))
            self.initial.setdefault("delay_unit", config.get("unit", "days"))
            self.initial.setdefault("delay_until_template", config.get("until_template", ""))
            self.initial.setdefault("http_method", config.get("method", "POST"))
            self.initial.setdefault("http_url_template", config.get("url_template", ""))
            self.initial.setdefault("http_headers_text", _serialize_mapping_for_textarea(config.get("headers")))
            self.initial.setdefault("http_body_template", config.get("body_template", ""))
            self.initial.setdefault("http_timeout_seconds", config.get("timeout_seconds", 20))
            expected_statuses = config.get("expected_statuses")
            if isinstance(expected_statuses, list):
                self.initial.setdefault(
                    "http_expected_status_csv",
                    ",".join(str(status) for status in expected_statuses if str(status).strip()),
                )
            self.initial.setdefault("anomalie_mail_to", config.get("to", ""))
            self.initial.setdefault("anomalie_mail_recipient_display", config.get("recipient_display", ""))
            self.initial.setdefault("anomalie_mail_action", config.get("action", "prendi_in_carico"))
            self.initial.setdefault("anomalie_mail_expires_hours", config.get("expires_hours", 48))
            self.initial.setdefault("anomalie_mail_source_automation", config.get("source_automation", ""))
            self.initial.setdefault("anomalie_op_benestare_field", config.get("benestare_field", ""))
            self.initial.setdefault("anomalie_op_action", config.get("action", "prendi_in_carico"))
            self.initial.setdefault("anomalie_op_expires_hours", config.get("expires_hours", 48))
            self.initial.setdefault("anomalie_op_source_automation", config.get("source_automation", ""))
            self.initial.setdefault("teams_webhook_url", config.get("webhook_url", ""))
            self.initial.setdefault("teams_title_template", config.get("title_template", ""))
            self.initial.setdefault("teams_summary_template", config.get("summary_template", ""))
            self.initial.setdefault("teams_text_template", config.get("text_template", ""))
            self.initial.setdefault("teams_theme_color", config.get("theme_color", ""))
            self.initial.setdefault("teams_facts_text", _serialize_mapping_for_textarea(config.get("facts")))
            # send_approval fields
            self.initial.setdefault("approval_delivery_mode", _infer_approval_delivery_mode(config))
            self.initial.setdefault("approval_to_template", config.get("to_template", ""))
            self.initial.setdefault("approval_subject_template", config.get("subject_template", ""))
            self.initial.setdefault("approval_message_template", config.get("message_template", ""))
            self.initial.setdefault("approval_expiry_days", config.get("expiry_days", 7))
            self.initial.setdefault("approval_approve_label", config.get("approve_label", "Approva"))
            self.initial.setdefault("approval_reject_label", config.get("reject_label", "Rifiuta"))
            self.initial.setdefault("approval_teams_preset_id", str(config.get("teams_preset_id") or ""))
            self.initial.setdefault("approval_teams_flow_endpoint_id", str(config.get("teams_flow_endpoint_id") or ""))
            self.initial.setdefault("approval_teams_recipient_email_template", config.get("teams_recipient_email_template", ""))
            self.initial.setdefault("approval_teams_title_template", config.get("teams_title_template", ""))
            self.initial.setdefault(
                "approval_teams_facts_inline",
                _serialize_approval_facts_inline(config.get("teams_facts_inline") or config.get("teams_facts")),
            )
            self.initial.setdefault("approval_strict_teams_flow", bool(config.get("strict_teams_flow")))
            approved_update, approved_extra = _split_approval_branch_actions(config.get("approved_actions"))
            rejected_update, rejected_extra = _split_approval_branch_actions(config.get("rejected_actions"))
            self.initial.setdefault("approval_approved_update_fields_text", _serialize_mapping_for_textarea(approved_update))
            self.initial.setdefault("approval_rejected_update_fields_text", _serialize_mapping_for_textarea(rejected_update))
            self.initial.setdefault("approval_approved_actions_json", _serialize_json_array_text(approved_extra))
            self.initial.setdefault("approval_rejected_actions_json", _serialize_json_array_text(rejected_extra))
            self.initial.setdefault("loop_check_field", config.get("check_field", ""))
            self.initial.setdefault("loop_check_operator", config.get("check_operator", "equals"))
            self.initial.setdefault("loop_check_value", config.get("check_value", ""))
            self.initial.setdefault("loop_check_value_type", config.get("check_value_type", "string"))
            self.initial.setdefault("loop_retry_delay_value", config.get("retry_delay_value", 24))
            self.initial.setdefault("loop_retry_delay_unit", config.get("retry_delay_unit", "hours"))
            self.initial.setdefault("loop_max_iterations", config.get("max_iterations", 10))
            self.initial.setdefault("loop_loop_actions_json", _serialize_json_array_text(config.get("loop_actions")))
            self.initial.setdefault("loop_on_success_actions_json", _serialize_json_array_text(config.get("on_success_actions")))
            self.initial.setdefault("loop_on_timeout_actions_json", _serialize_json_array_text(config.get("on_timeout_actions")))
            self.initial.setdefault("each_source_code", config.get("source_code", ""))
            self.initial.setdefault("each_filter_field", config.get("filter_field", ""))
            self.initial.setdefault("each_filter_value_template", config.get("filter_value_template", ""))
            self.initial.setdefault("each_max_items", config.get("max_items", 50))
            self.initial.setdefault("each_actions_json", _serialize_json_array_text(config.get("each_actions")))
            self.initial.setdefault("branch_condition_field", config.get("condition_field", ""))
            self.initial.setdefault("branch_condition_operator", config.get("condition_operator", "equals"))
            self.initial.setdefault("branch_condition_value", config.get("condition_value", ""))
            self.initial.setdefault("branch_condition_value_type", config.get("condition_value_type", "string"))
            self.initial.setdefault("branch_compare_with_old", bool(config.get("compare_with_old")))
            self.initial.setdefault("branch_if_true_actions_json", _serialize_json_array_text(config.get("if_true_actions")))
            self.initial.setdefault("branch_if_false_actions_json", _serialize_json_array_text(config.get("if_false_actions")))
            template_initial = ""
            template_code = str(config.get("approval_email_template_code") or "").strip()
            template_id = str(config.get("approval_email_template_id") or "").strip()
            if template_code and template_code in self._approval_templates_by_code:
                template_initial = str(self._approval_templates_by_code[template_code].pk)
            elif template_id and template_id in self._approval_templates_by_id:
                template_initial = template_id
            elif template_code:
                _append_help_text(
                    self.fields.get("approval_email_template_id"),
                    f"Template salvato non disponibile localmente: `{template_code}`.",
                )
            self.initial.setdefault("approval_email_template_id", template_initial)

    def clean(self):
        cleaned_data = super().clean()
        action_type = cleaned_data.get("action_type")
        run_if_config = _normalize_run_if_config(cleaned_data)
        _validate_run_if(self, run_if_config)

        config_json: dict[str, Any] = {}

        if action_type == AutomationActionType.SEND_EMAIL:
            config_json = {
                "from_email": cleaned_data.get("email_from_email", ""),
                "to": cleaned_data.get("email_to", ""),
                "cc": cleaned_data.get("email_cc", ""),
                "bcc": cleaned_data.get("email_bcc", ""),
                "reply_to": cleaned_data.get("email_reply_to", ""),
                "subject_template": cleaned_data.get("email_subject_template", ""),
                "body_text_template": cleaned_data.get("email_body_text_template", ""),
                "body_html_template": cleaned_data.get("email_body_html_template", ""),
                "fail_silently": bool(cleaned_data.get("email_fail_silently")),
            }
            if not any(
                [
                    config_json["to"].strip(),
                    config_json["cc"].strip(),
                    config_json["bcc"].strip(),
                ]
            ):
                self.add_error("email_to", "Specifica almeno un destinatario in to, cc o bcc.")
            if not config_json["subject_template"].strip():
                self.add_error("email_subject_template", "Il subject template e' obbligatorio.")
            if not config_json["body_text_template"].strip():
                self.add_error("email_body_text_template", "Il body text template e' obbligatorio.")

        elif action_type == AutomationActionType.WRITE_LOG:
            config_json = {
                "message_template": cleaned_data.get("write_log_message_template", ""),
            }
            if not config_json["message_template"].strip():
                self.add_error("write_log_message_template", "Il message template e' obbligatorio.")

        elif action_type == AutomationActionType.UPDATE_DASHBOARD_METRIC:
            config_json = {
                "metric_code": cleaned_data.get("metric_code", ""),
                "operation": cleaned_data.get("metric_operation", ""),
                "value_template": cleaned_data.get("metric_value_template", ""),
            }
            if not config_json["metric_code"].strip():
                self.add_error("metric_code", "Il metric code e' obbligatorio.")
            if not config_json["operation"].strip():
                self.add_error("metric_operation", "L'operazione e' obbligatoria.")
            if not config_json["value_template"].strip():
                self.add_error("metric_value_template", "Il value template e' obbligatorio.")

        elif action_type == AutomationActionType.INSERT_RECORD:
            config_json = {
                "target_table": cleaned_data.get("insert_target_table", ""),
                "field_mappings": {},
            }
            try:
                config_json["field_mappings"] = _parse_mapping_text(
                    cleaned_data.get("insert_field_mappings_text", ""),
                    field_label="Field mappings",
                )
            except forms.ValidationError as exc:
                self.add_error("insert_field_mappings_text", exc)

            if not config_json["target_table"].strip():
                self.add_error("insert_target_table", "La tabella target e' obbligatoria.")
            if not config_json["field_mappings"]:
                self.add_error("insert_field_mappings_text", "Serve almeno un mapping campo -> valore.")

            whitelist = get_action_table_whitelist().get(AutomationActionType.INSERT_RECORD, {})
            target_config = whitelist.get(config_json["target_table"], {})
            if config_json["target_table"].strip() and not target_config:
                self.add_error(
                    "insert_target_table",
                    "La tabella selezionata non e' ancora abilitata per insert_record. Usa `+ Tabella` per configurarla.",
                )
            else:
                allowed_fields = target_config.get("fields", set())
                invalid_fields = sorted(set(config_json["field_mappings"].keys()) - set(allowed_fields))
                if invalid_fields:
                    self.add_error(
                        "insert_field_mappings_text",
                        f"Campi non whitelistati per {config_json['target_table']}: {', '.join(invalid_fields)}.",
                    )

        elif action_type == AutomationActionType.UPDATE_RECORD:
            config_json = {
                "target_table": cleaned_data.get("update_target_table", ""),
                "where_field": (cleaned_data.get("update_where_field", "") or "").strip(),
                "where_value_template": cleaned_data.get("update_where_value_template", ""),
                "update_fields": {},
            }
            try:
                config_json["update_fields"] = _parse_mapping_text(
                    cleaned_data.get("update_fields_text", ""),
                    field_label="Update fields",
                )
            except forms.ValidationError as exc:
                self.add_error("update_fields_text", exc)

            if not config_json["target_table"].strip():
                self.add_error("update_target_table", "La tabella target e' obbligatoria.")
            if not config_json["where_field"]:
                self.add_error("update_where_field", "Il where field e' obbligatorio.")
            if not config_json["where_value_template"].strip():
                self.add_error("update_where_value_template", "Il where value template e' obbligatorio.")
            if not config_json["update_fields"]:
                self.add_error("update_fields_text", "Serve almeno un campo da aggiornare.")

            whitelist = get_action_table_whitelist().get(AutomationActionType.UPDATE_RECORD, {})
            target_config = whitelist.get(config_json["target_table"], {})
            if config_json["target_table"].strip() and not target_config:
                self.add_error(
                    "update_target_table",
                    "La tabella selezionata non e' ancora abilitata per update_record. Usa `+ Tabella` per configurarla.",
                )
            else:
                allowed_fields = set(target_config.get("fields", set()))
                allowed_where_fields = set(target_config.get("where_fields", set()))
                invalid_fields = sorted(set(config_json["update_fields"].keys()) - allowed_fields)
                if invalid_fields:
                    self.add_error(
                        "update_fields_text",
                        f"Campi non whitelistati per {config_json['target_table']}: {', '.join(invalid_fields)}.",
                    )
                if config_json["where_field"] and config_json["where_field"] not in allowed_where_fields:
                    self.add_error(
                        "update_where_field",
                        f"Campo where non whitelistato per {config_json['target_table']}: {config_json['where_field']}.",
                    )

        elif action_type == AutomationActionType.UPDATE_TRIGGER_RECORD:
            config_json = {"update_fields": {}}
            try:
                config_json["update_fields"] = _parse_mapping_text(
                    cleaned_data.get("trigger_update_fields_text", ""),
                    field_label="Campi record triggerante",
                )
            except forms.ValidationError as exc:
                self.add_error("trigger_update_fields_text", exc)

            if not config_json["update_fields"]:
                self.add_error("trigger_update_fields_text", "Serve almeno un campo da aggiornare sul record triggerante.")

            allowed_fields = _get_source_update_allowed_fields(self._effective_source_code)
            invalid_fields = sorted(set(config_json["update_fields"].keys()) - allowed_fields)
            if invalid_fields:
                self.add_error(
                    "trigger_update_fields_text",
                    "Campi non aggiornabili sulla sorgente selezionata: " + ", ".join(invalid_fields) + ".",
                )

        elif action_type == AutomationActionType.SPLIT_ASSENZA_GIORNALIERA:
            days_count_fields = [
                chunk.strip()
                for chunk in str(cleaned_data.get("split_days_count_fields") or "").split(",")
                if chunk.strip()
            ]
            config_json = {
                "source_code": "assenze",
                "start_field": str(cleaned_data.get("split_start_field") or "data_inizio").strip(),
                "end_field": str(cleaned_data.get("split_end_field") or "data_fine").strip(),
                "days_count_fields": days_count_fields,
                "max_days": cleaned_data.get("split_max_days") or 60,
                "tipo_assenza_template": str(cleaned_data.get("split_tipo_assenza_template") or "Permesso").strip(),
                "salta_approvazione": bool(cleaned_data.get("split_salta_approvazione")),
                "moderation_status": cleaned_data.get("split_moderation_status") if cleaned_data.get("split_moderation_status") is not None else 0,
                "consenso_template": str(cleaned_data.get("split_consenso_template") or "Approvato").strip(),
                "include_first_day": bool(cleaned_data.get("split_include_first_day")),
                "dedupe": bool(cleaned_data.get("split_dedupe")),
                "set_approval_datetime": True,
            }
            if self._effective_source_code != "assenze":
                self.add_error("action_type", "Lo split giornaliero e' disponibile solo per la sorgente Assenze.")
            if not config_json["start_field"]:
                self.add_error("split_start_field", "Il campo data inizio e' obbligatorio.")
            if not config_json["end_field"]:
                self.add_error("split_end_field", "Il campo data fine e' obbligatorio.")
            if not config_json["tipo_assenza_template"]:
                self.add_error("split_tipo_assenza_template", "Il tipo assenza delle righe create e' obbligatorio.")

        elif action_type == AutomationActionType.DELAY_SCHEDULE:
            config_json = {
                "mode": str(cleaned_data.get("delay_mode") or "").strip(),
                "value_template": cleaned_data.get("delay_value_template", ""),
                "unit": str(cleaned_data.get("delay_unit") or "").strip(),
                "until_template": cleaned_data.get("delay_until_template", ""),
            }
            if config_json["mode"] == "until":
                if not str(config_json["until_template"]).strip():
                    self.add_error("delay_until_template", "La data/ora target e' obbligatoria.")
            else:
                config_json["mode"] = "relative"
                if not str(config_json["value_template"]).strip():
                    self.add_error("delay_value_template", "Il valore delay e' obbligatorio.")
                if not config_json["unit"]:
                    self.add_error("delay_unit", "L'unita' delay e' obbligatoria.")
            if config_json["mode"] == "relative" and config_json["unit"] == "days":
                config_json["giorni"] = config_json["value_template"]

        elif action_type == AutomationActionType.HTTP_REQUEST:
            config_json = {
                "method": str(cleaned_data.get("http_method") or "").strip().upper(),
                "url_template": cleaned_data.get("http_url_template", ""),
                "headers": {},
                "body_template": cleaned_data.get("http_body_template", ""),
                "timeout_seconds": cleaned_data.get("http_timeout_seconds") or 20,
                "expected_statuses": [],
            }
            try:
                config_json["headers"] = _parse_mapping_text(
                    cleaned_data.get("http_headers_text", ""),
                    field_label="Headers",
                )
            except forms.ValidationError as exc:
                self.add_error("http_headers_text", exc)

            raw_statuses = str(cleaned_data.get("http_expected_status_csv") or "").strip()
            if raw_statuses:
                try:
                    config_json["expected_statuses"] = [
                        int(chunk.strip())
                        for chunk in raw_statuses.split(",")
                        if str(chunk).strip()
                    ]
                except (TypeError, ValueError):
                    self.add_error("http_expected_status_csv", "Gli status attesi devono essere un CSV di interi.")

            if not config_json["method"]:
                self.add_error("http_method", "Il metodo HTTP e' obbligatorio.")
            if not str(config_json["url_template"]).strip():
                self.add_error("http_url_template", "L'URL template e' obbligatorio.")

        elif action_type == AutomationActionType.SEND_ANOMALIE_MAIL_ACTION:
            to_val = str(cleaned_data.get("anomalie_mail_to") or "").strip()
            if not to_val:
                self.add_error("anomalie_mail_to", "Il destinatario è obbligatorio.")
            config_json = {
                "to": to_val,
                "recipient_display": str(cleaned_data.get("anomalie_mail_recipient_display") or "").strip(),
                "action": str(cleaned_data.get("anomalie_mail_action") or "prendi_in_carico").strip(),
                "expires_hours": int(cleaned_data.get("anomalie_mail_expires_hours") or 48),
                "source_automation": str(cleaned_data.get("anomalie_mail_source_automation") or "").strip(),
            }

        elif action_type == AutomationActionType.SEND_ANOMALIE_MAIL_ACTION_BY_OP:
            config_json = {
                "benestare_field": str(cleaned_data.get("anomalie_op_benestare_field") or "").strip(),
                "action": str(cleaned_data.get("anomalie_op_action") or "prendi_in_carico").strip(),
                "expires_hours": int(cleaned_data.get("anomalie_op_expires_hours") or 48),
                "source_automation": str(cleaned_data.get("anomalie_op_source_automation") or "").strip(),
            }

        elif action_type == AutomationActionType.TEAMS_WEBHOOK:
            config_json = {
                "webhook_url": cleaned_data.get("teams_webhook_url", ""),
                "title_template": cleaned_data.get("teams_title_template", ""),
                "summary_template": cleaned_data.get("teams_summary_template", ""),
                "text_template": cleaned_data.get("teams_text_template", ""),
                "theme_color": cleaned_data.get("teams_theme_color", ""),
                "facts": {},
            }
            try:
                config_json["facts"] = _parse_mapping_text(
                    cleaned_data.get("teams_facts_text", ""),
                    field_label="Facts",
                )
            except forms.ValidationError as exc:
                self.add_error("teams_facts_text", exc)

            if not str(config_json["webhook_url"]).strip():
                self.add_error("teams_webhook_url", "Il webhook URL Teams e' obbligatorio.")
            if not any(
                [
                    str(config_json["title_template"]).strip(),
                    str(config_json["summary_template"]).strip(),
                    str(config_json["text_template"]).strip(),
                    bool(config_json["facts"]),
                ]
            ):
                self.add_error(
                    "teams_text_template",
                    "Compila almeno titolo, summary, testo o facts per la card Teams.",
                )

        elif action_type == AutomationActionType.SEND_APPROVAL:
            existing_config = self.instance.config_json if isinstance(getattr(self.instance, "config_json", None), dict) else {}
            delivery_mode = str(cleaned_data.get("approval_delivery_mode") or ApprovalDeliveryMode.EMAIL).strip()
            preset_id_raw = str(cleaned_data.get("approval_teams_preset_id") or "").strip()
            flow_endpoint_id_raw = str(cleaned_data.get("approval_teams_flow_endpoint_id") or "").strip()
            teams_flow_endpoints_unavailable = bool(getattr(self, "_teams_flow_endpoints_unavailable", False))
            teams_recipient_email_template = str(
                cleaned_data.get("approval_teams_recipient_email_template") or ""
            ).strip()
            approved_actions = _build_approval_branch_actions(
                self,
                update_fields_key="approval_approved_update_fields_text",
                extra_json_key="approval_approved_actions_json",
                branch_label="approvato",
                source_code=self._effective_source_code,
                cleaned_data=cleaned_data,
            )
            rejected_actions = _build_approval_branch_actions(
                self,
                update_fields_key="approval_rejected_update_fields_text",
                extra_json_key="approval_rejected_actions_json",
                branch_label="rifiutato",
                source_code=self._effective_source_code,
                cleaned_data=cleaned_data,
            )
            config_json = {
                "delivery_mode": delivery_mode or ApprovalDeliveryMode.EMAIL,
                "to_template": str(cleaned_data.get("approval_to_template") or "").strip(),
                "subject_template": str(cleaned_data.get("approval_subject_template") or "").strip(),
                "message_template": str(cleaned_data.get("approval_message_template") or "").strip(),
                "expiry_days": cleaned_data.get("approval_expiry_days") or 7,
                "approve_label": str(cleaned_data.get("approval_approve_label") or "Approva").strip() or "Approva",
                "reject_label": str(cleaned_data.get("approval_reject_label") or "Rifiuta").strip() or "Rifiuta",
                "teams_title_template": str(cleaned_data.get("approval_teams_title_template") or "").strip(),
                "teams_facts_inline": str(cleaned_data.get("approval_teams_facts_inline") or "").strip(),
                "approved_actions": approved_actions,
                "rejected_actions": rejected_actions,
            }
            if delivery_mode == ApprovalDeliveryMode.EMAIL:
                if not config_json["to_template"]:
                    self.add_error("approval_to_template", "Per la consegna email serve almeno un'email approvatore.")
            elif delivery_mode == ApprovalDeliveryMode.TEAMS_WEBHOOK_LEGACY:
                if not config_json["to_template"]:
                    self.add_error("approval_to_template", "Per il recapito legacy serve almeno un'email approvatore.")
                if preset_id_raw:
                    config_json["teams_preset_id"] = preset_id_raw
                elif str(existing_config.get("teams_webhook_url") or "").strip():
                    config_json["teams_webhook_url"] = str(existing_config.get("teams_webhook_url") or "").strip()
                else:
                    self.add_error(
                        "approval_teams_preset_id",
                        "Per `teams_webhook_legacy` seleziona un canale Teams legacy.",
                    )
            elif delivery_mode == ApprovalDeliveryMode.TEAMS_CHAT_FLOW:
                if not teams_recipient_email_template:
                    self.add_error(
                        "approval_teams_recipient_email_template",
                        "Per `teams_chat_flow` l'email destinatario Teams e' obbligatoria.",
                    )
                if teams_flow_endpoints_unavailable:
                    self.add_error(
                        "approval_teams_flow_endpoint_id",
                        AUTOMATION_DELIVERY_ENDPOINT_UNAVAILABLE_MESSAGE,
                    )
                elif not flow_endpoint_id_raw:
                    self.add_error(
                        "approval_teams_flow_endpoint_id",
                        "Per `teams_chat_flow` seleziona un endpoint Teams Flow.",
                    )
                if teams_recipient_email_template:
                    config_json["teams_recipient_email_template"] = teams_recipient_email_template
                if flow_endpoint_id_raw:
                    config_json["teams_flow_endpoint_id"] = flow_endpoint_id_raw
            elif delivery_mode == ApprovalDeliveryMode.EMAIL_AND_TEAMS_CHAT_FLOW:
                if not config_json["to_template"]:
                    self.add_error("approval_to_template", "Per `email_and_teams_chat_flow` serve almeno un'email approvatore.")
                if not teams_recipient_email_template:
                    self.add_error(
                        "approval_teams_recipient_email_template",
                        "Per `email_and_teams_chat_flow` l'email destinatario Teams e' obbligatoria.",
                    )
                if teams_flow_endpoints_unavailable:
                    self.add_error(
                        "approval_teams_flow_endpoint_id",
                        AUTOMATION_DELIVERY_ENDPOINT_UNAVAILABLE_MESSAGE,
                    )
                elif not flow_endpoint_id_raw:
                    self.add_error(
                        "approval_teams_flow_endpoint_id",
                        "Per `email_and_teams_chat_flow` seleziona un endpoint Teams Flow.",
                    )
                if teams_recipient_email_template:
                    config_json["teams_recipient_email_template"] = teams_recipient_email_template
                if flow_endpoint_id_raw:
                    config_json["teams_flow_endpoint_id"] = flow_endpoint_id_raw
                config_json["strict_teams_flow"] = bool(cleaned_data.get("approval_strict_teams_flow"))
            else:
                self.add_error("approval_delivery_mode", "Modalita' recapito non valida.")

            if preset_id_raw and delivery_mode == ApprovalDeliveryMode.TEAMS_WEBHOOK_LEGACY:
                config_json["teams_preset_id"] = preset_id_raw

            # Template email approvazione (opzionale): persisti sempre il code.
            tpl_selector_raw = str(cleaned_data.get("approval_email_template_id") or "").strip()
            selected_template = _select_approval_template_from_choices(
                tpl_selector_raw,
                by_id=getattr(self, "_approval_templates_by_id", {}),
                by_code=getattr(self, "_approval_templates_by_code", {}),
            )
            if selected_template is not None:
                config_json["approval_email_template_code"] = str(selected_template.code)
                config_json["approval_email_template_id"] = str(selected_template.pk)
            elif not tpl_selector_raw:
                existing_template_code = str(existing_config.get("approval_email_template_code") or "").strip()
                existing_template_id = str(existing_config.get("approval_email_template_id") or "").strip()
                if existing_template_code:
                    config_json["approval_email_template_code"] = existing_template_code
                if existing_template_id:
                    config_json["approval_email_template_id"] = existing_template_id

        elif action_type == AutomationActionType.DO_UNTIL:
            check_field = str(cleaned_data.get("loop_check_field") or "").strip()
            check_operator = str(cleaned_data.get("loop_check_operator") or "").strip()
            check_value = str(cleaned_data.get("loop_check_value") or "")
            check_value_type = str(cleaned_data.get("loop_check_value_type") or "").strip()
            loop_actions = _parse_inline_actions_field(
                self,
                raw_value=cleaned_data.get("loop_loop_actions_json", ""),
                field_name="loop_loop_actions_json",
                field_label="Azioni corpo loop",
            )
            on_success_actions = _parse_inline_actions_field(
                self,
                raw_value=cleaned_data.get("loop_on_success_actions_json", ""),
                field_name="loop_on_success_actions_json",
                field_label="Azioni successo loop",
            )
            on_timeout_actions = _parse_inline_actions_field(
                self,
                raw_value=cleaned_data.get("loop_on_timeout_actions_json", ""),
                field_name="loop_on_timeout_actions_json",
                field_label="Azioni timeout loop",
            )
            config_json = {
                "check_field": check_field,
                "check_operator": check_operator or AutomationConditionOperator.EQUALS,
                "check_value": check_value,
                "check_value_type": check_value_type or AutomationConditionValueType.STRING,
                "retry_delay_value": cleaned_data.get("loop_retry_delay_value") or 24,
                "retry_delay_unit": str(cleaned_data.get("loop_retry_delay_unit") or "hours").strip() or "hours",
                "max_iterations": cleaned_data.get("loop_max_iterations") or 10,
                "loop_actions": loop_actions,
                "on_success_actions": on_success_actions,
                "on_timeout_actions": on_timeout_actions,
            }
            _validate_simple_condition_fields(
                self,
                field_name=check_field,
                operator=check_operator,
                value_type=check_value_type,
                expected_value=check_value,
                field_name_key="loop_check_field",
                operator_key="loop_check_operator",
                value_type_key="loop_check_value_type",
                expected_value_key="loop_check_value",
                label="condizione di uscita",
            )

        elif action_type == AutomationActionType.FOR_EACH:
            each_actions = _parse_inline_actions_field(
                self,
                raw_value=cleaned_data.get("each_actions_json", ""),
                field_name="each_actions_json",
                field_label="Azioni for each",
            )
            config_json = {
                "source_code": str(cleaned_data.get("each_source_code") or "").strip(),
                "filter_field": str(cleaned_data.get("each_filter_field") or "").strip(),
                "filter_value_template": str(cleaned_data.get("each_filter_value_template") or ""),
                "max_items": cleaned_data.get("each_max_items") or 50,
                "each_actions": each_actions,
            }
            if not config_json["source_code"]:
                self.add_error("each_source_code", "La sorgente dati del for_each e' obbligatoria.")

        elif action_type == AutomationActionType.BRANCH:
            branch_condition_field = str(cleaned_data.get("branch_condition_field") or "").strip()
            branch_condition_operator = str(cleaned_data.get("branch_condition_operator") or "").strip()
            branch_condition_value = str(cleaned_data.get("branch_condition_value") or "")
            branch_condition_value_type = str(cleaned_data.get("branch_condition_value_type") or "").strip()
            if_true_actions = _parse_inline_actions_field(
                self,
                raw_value=cleaned_data.get("branch_if_true_actions_json", ""),
                field_name="branch_if_true_actions_json",
                field_label="Azioni ramo vero",
            )
            if_false_actions = _parse_inline_actions_field(
                self,
                raw_value=cleaned_data.get("branch_if_false_actions_json", ""),
                field_name="branch_if_false_actions_json",
                field_label="Azioni ramo falso",
            )
            config_json = {
                "condition_field": branch_condition_field,
                "condition_operator": branch_condition_operator or AutomationConditionOperator.EQUALS,
                "condition_value": branch_condition_value,
                "condition_value_type": branch_condition_value_type or AutomationConditionValueType.STRING,
                "compare_with_old": bool(cleaned_data.get("branch_compare_with_old")),
                "if_true_actions": if_true_actions,
                "if_false_actions": if_false_actions,
            }
            _validate_simple_condition_fields(
                self,
                field_name=branch_condition_field,
                operator=branch_condition_operator,
                value_type=branch_condition_value_type,
                expected_value=branch_condition_value,
                field_name_key="branch_condition_field",
                operator_key="branch_condition_operator",
                value_type_key="branch_condition_value_type",
                expected_value_key="branch_condition_value",
                label="condizione del branch",
            )

        if run_if_config:
            config_json["run_if"] = run_if_config
        self._config_json = config_json
        return cleaned_data

    def save(self, commit: bool = True):
        instance = super().save(commit=False)
        instance.config_json = getattr(self, "_config_json", {})
        if commit:
            instance.save()
        return instance


class AutomationRuleTestForm(forms.Form):
    payload_json = forms.CharField(
        label="Payload JSON",
        widget=forms.Textarea(attrs={"rows": 8}),
        help_text="Inserisci un oggetto JSON coerente con la sorgente della regola.",
    )
    old_payload_json = forms.CharField(
        label="Old payload JSON",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="Opzionale. Utile per regole update con `any_change`, `specific_field` o condizioni `changed`.",
    )
    is_test = forms.BooleanField(
        label="Esegui come test",
        required=False,
        initial=True,
        help_text="La pagina salva comunque il run log in modalita' test.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _mark_smart_target(self.fields.get("payload_json"), mode="json-editor", role="payload-json", source_role="template")
        _mark_smart_target(self.fields.get("old_payload_json"), mode="json-editor", role="old-payload-json", source_role="template")

    def clean_payload_json(self):
        raw_value = self.cleaned_data["payload_json"]
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError("Payload JSON non valido.") from exc
        if not isinstance(parsed, dict):
            raise forms.ValidationError("Il payload deve essere un oggetto JSON.")
        return parsed

    def clean_old_payload_json(self):
        raw_value = str(self.cleaned_data.get("old_payload_json") or "").strip()
        if not raw_value:
            return None
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError("Old payload JSON non valido.") from exc
        if not isinstance(parsed, dict):
            raise forms.ValidationError("L'old payload deve essere un oggetto JSON.")
        return parsed


class AutomationPackageUploadForm(forms.Form):
    package_file = forms.FileField(
        label="Package automazione",
        help_text="Accetta `.automation_package.json` e `.json` con shape compatibile.",
        widget=forms.ClearableFileInput(attrs={"accept": ".json,.automation_package.json"}),
    )

    def clean_package_file(self):
        uploaded_file = self.cleaned_data["package_file"]
        try:
            filename = validate_filename(getattr(uploaded_file, "name", ""), label="Package")
        except UploadMimeValidationError as exc:
            raise forms.ValidationError(str(exc))
        lower = filename.lower()
        if not (lower.endswith(".automation_package.json") or lower.endswith(".json")):
            raise forms.ValidationError("Carica un file `.automation_package.json` o `.json` compatibile.")
        size = int(getattr(uploaded_file, "size", 0) or 0)
        if size <= 0:
            raise forms.ValidationError("Package vuoto: caricamento bloccato.")
        if size > 10 * 1024 * 1024:
            raise forms.ValidationError("Package: supera il limite di 10 MB.")
        return uploaded_file


class PowerAutomateFlowUploadForm(forms.Form):
    flow_file = forms.FileField(
        label="Export Power Automate",
        help_text="Accetta export `.zip` e definition `.json` di Power Automate.",
        widget=forms.ClearableFileInput(attrs={"accept": ".zip,.json"}),
    )
    target_table = forms.ChoiceField(
        label="Tabella target modulo",
        required=False,
        choices=(("", "Nessuna tabella target (solo runtime portale)"),),
        help_text="Opzionale. Se selezionata, il converter suggerisce anche mapping verso una tabella Django del portale.",
    )
    approval_email_template_code = forms.ChoiceField(
        label="Template approvazione",
        required=False,
        choices=(("", "Nessun template approval selezionato"),),
        help_text=(
            "Usato quando il flow contiene approval Power Automate. "
            "Per la conversione approval via mail servono template attivi `hybrid` o `mail_reply`."
        ),
    )

    def __init__(
        self,
        *args,
        target_table_choices: list[tuple[str, str]] | None = None,
        approval_template_choices: list[tuple[str, str]] | None = None,
        default_approval_template_code: str = "",
        approval_template_warning: str = "",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.fields["target_table"].choices = [
            ("", "Nessuna tabella target (solo runtime portale)"),
            *(target_table_choices or []),
        ]
        self.fields["approval_email_template_code"].choices = [
            ("", "Nessun template approval selezionato"),
            *(approval_template_choices or []),
        ]
        if default_approval_template_code and not self.is_bound:
            self.initial.setdefault("approval_email_template_code", default_approval_template_code)
        if approval_template_warning:
            existing_help = str(self.fields["approval_email_template_code"].help_text or "").strip()
            self.fields["approval_email_template_code"].help_text = f"{existing_help} {approval_template_warning}".strip()

    def clean_flow_file(self):
        uploaded_file = self.cleaned_data["flow_file"]
        try:
            filename = validate_filename(getattr(uploaded_file, "name", ""), label="Flow")
        except UploadMimeValidationError as exc:
            raise forms.ValidationError(str(exc))
        lower = filename.lower()
        if not (lower.endswith(".zip") or lower.endswith(".json")):
            raise forms.ValidationError("Carica un export Power Automate `.zip` oppure un file `.json`.")
        size = int(getattr(uploaded_file, "size", 0) or 0)
        if size <= 0:
            raise forms.ValidationError("File vuoto: caricamento bloccato.")
        if size > 25 * 1024 * 1024:
            raise forms.ValidationError("Flow: supera il limite di 25 MB.")
        return uploaded_file


PACKAGE_DRY_RUN_SAMPLE_CHOICES = (
    ("example", "Payload di esempio"),
    ("json", "JSON incollato"),
    ("record", "Record esistente"),
)


class AutomationPackageDryRunForm(forms.Form):
    sample_mode = forms.ChoiceField(
        label="Modalita' simulazione",
        choices=PACKAGE_DRY_RUN_SAMPLE_CHOICES,
        initial="example",
    )
    payload_json = forms.CharField(
        label="Payload JSON",
        required=False,
        widget=forms.Textarea(attrs={"rows": 8}),
        help_text="Usato in modalita' `JSON incollato`. Deve essere un oggetto JSON.",
    )
    old_payload_json = forms.CharField(
        label="Old payload JSON",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="Opzionale. Utile per trigger update, `changed` e `specific_field`.",
    )
    source_record_id = forms.ChoiceField(
        label="Record sorgente",
        required=False,
        choices=(("", "---------"),),
        help_text="Usato in modalita' `Record esistente`.",
    )

    def __init__(self, *args, record_choices: list[tuple[str, str]] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["source_record_id"].choices = [("", "---------"), *(record_choices or [])]

    def clean_payload_json(self):
        raw_value = str(self.cleaned_data.get("payload_json") or "").strip()
        if not raw_value:
            return None
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError("Payload JSON non valido.") from exc
        if not isinstance(parsed, dict):
            raise forms.ValidationError("Il payload deve essere un oggetto JSON.")
        return parsed

    def clean_old_payload_json(self):
        raw_value = str(self.cleaned_data.get("old_payload_json") or "").strip()
        if not raw_value:
            return None
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError("Old payload JSON non valido.") from exc
        if not isinstance(parsed, dict):
            raise forms.ValidationError("L'old payload deve essere un oggetto JSON.")
        return parsed

    def clean(self):
        cleaned_data = super().clean()
        sample_mode = cleaned_data.get("sample_mode")
        if sample_mode == "json" and cleaned_data.get("payload_json") is None:
            self.add_error("payload_json", "Inserisci un payload JSON valido per la simulazione.")
        if sample_mode == "record" and not str(cleaned_data.get("source_record_id") or "").strip():
            self.add_error("source_record_id", "Seleziona un record esistente da usare nel dry-run.")
        return cleaned_data


class _AutomationOrderedInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        next_order = 1
        used_orders: set[int] = set()

        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.cleaned_data:
                continue
            if form.cleaned_data.get("DELETE"):
                continue
            order_value = form.cleaned_data.get("order")
            if order_value in (None, ""):
                continue
            try:
                normalized = int(order_value)
            except (TypeError, ValueError):
                continue
            used_orders.add(normalized)
            if normalized >= next_order:
                next_order = normalized + 1

        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.cleaned_data:
                continue
            if form.cleaned_data.get("DELETE"):
                continue
            if not form.instance.pk and not form.has_changed():
                continue
            order_value = form.cleaned_data.get("order")
            if order_value not in (None, ""):
                continue
            while next_order in used_orders:
                next_order += 1
            form.cleaned_data["order"] = next_order
            form.instance.order = next_order
            used_orders.add(next_order)
            next_order += 1


AutomationConditionFormSet = inlineformset_factory(
    AutomationRule,
    AutomationCondition,
    form=AutomationConditionForm,
    formset=_AutomationOrderedInlineFormSet,
    extra=0,
    can_delete=True,
)


AutomationActionFormSet = inlineformset_factory(
    AutomationRule,
    AutomationAction,
    form=AutomationActionForm,
    formset=_AutomationOrderedInlineFormSet,
    extra=0,
    can_delete=True,
)


class TeamsWebhookPresetForm(forms.ModelForm):
    class Meta:
        model = TeamsWebhookPreset
        fields = ["name", "webhook_url", "description", "is_active"]
        widgets = {
            "webhook_url": forms.Textarea(attrs={"rows": 3, "placeholder": "https://cnovicrom.webhook.office.com/..."}),
            "description": forms.TextInput(attrs={"placeholder": "es. Canale IT, HR - Assenze..."}),
        }
        labels = {
            "name": "Nome canale",
            "webhook_url": "Webhook URL",
            "description": "Descrizione",
            "is_active": "Attivo",
        }


class ApprovalEmailTemplateForm(forms.ModelForm):
    """Form per creare / modificare un ApprovalEmailTemplate."""

    class Meta:
        from .models import ApprovalEmailTemplate
        model = ApprovalEmailTemplate
        fields = [
            "code", "name", "description", "is_enabled", "delivery_mode",
            "subject_template", "title_template", "intro_template", "body_template",
            "include_facts", "facts_lines",
            "approval_label", "rejection_label",
            "include_mailto_actions", "mailto_mailbox",
            "approval_mailto_subject_template", "approval_mailto_body_template",
            "rejection_mailto_subject_template", "rejection_mailto_body_template",
        ]
        widgets = {
            "code": forms.TextInput(attrs={"placeholder": "assenze-approvazione-ferie"}),
            "name": forms.TextInput(attrs={"placeholder": "Approvazione Ferie — Standard"}),
            "description": forms.Textarea(attrs={"rows": 2, "placeholder": "Breve descrizione dell'utilizzo previsto..."}),
            "subject_template": forms.TextInput(attrs={"placeholder": "Approvazione richiesta #{id} — {dipendente_nome}"}),
            "title_template": forms.TextInput(attrs={"placeholder": "Richiesta Approvazione Ferie"}),
            "intro_template": forms.Textarea(attrs={"rows": 3, "placeholder": "È pervenuta una richiesta di {tipo_assenza} da {dipendente_nome}..."}),
            "body_template": forms.Textarea(attrs={"rows": 6, "placeholder": "HTML libero. Se compilato, intro e facts vengono ignorati."}),
            "facts_lines": forms.Textarea(attrs={
                "rows": 5,
                "placeholder": "Tipo | {tipo_assenza}\nDal | {data_inizio}\nAl | {data_fine}\nDipendente | {dipendente_nome}\nReparto | {reparto}",
            }),
            "mailto_mailbox": forms.TextInput(attrs={"placeholder": "approvazioni@cnovicrom.local"}),
            "approval_mailto_subject_template": forms.TextInput(attrs={"placeholder": "CMD APPROVO RID {approval_token}"}),
            "approval_mailto_body_template": forms.Textarea(attrs={"rows": 3}),
            "rejection_mailto_subject_template": forms.TextInput(attrs={"placeholder": "CMD RIFIUTO RID {approval_token}"}),
            "rejection_mailto_body_template": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_code(self):
        from django.utils.text import slugify
        code = str(self.cleaned_data.get("code") or "").strip()
        if not code:
            raise forms.ValidationError("Il codice è obbligatorio.")
        slugified = slugify(code)
        if slugified != code:
            raise forms.ValidationError(
                f"Il codice deve essere uno slug valido (lettere minuscole, numeri, trattini). "
                f"Suggerimento: '{slugified}'."
            )
        return code

    def clean(self):
        cleaned = super().clean()
        delivery_mode = cleaned.get("delivery_mode", "")
        include_mailto = cleaned.get("include_mailto_actions", False)
        from .models import ApprovalEmailTemplateDeliveryMode
        if include_mailto and delivery_mode == ApprovalEmailTemplateDeliveryMode.PORTAL_LINKS:
            self.add_error(
                "include_mailto_actions",
                "Le azioni mailto: sono disponibili solo per le modalità 'mail_reply' o 'hybrid'.",
            )
        return cleaned


class AutomationDeliveryEndpointForm(forms.ModelForm):
    class Meta:
        model = AutomationDeliveryEndpoint
        fields = ["code", "name", "endpoint_type", "endpoint_url", "description", "is_active"]
        widgets = {
            "code": forms.TextInput(attrs={"placeholder": "teams-flow-assenze"}),
            "name": forms.TextInput(attrs={"placeholder": "Teams Flow - Assenze"}),
            "endpoint_type": forms.HiddenInput(),
            "endpoint_url": forms.Textarea(attrs={"rows": 3, "placeholder": "https://prod-00.westeurope.logic.azure.com/..."}),
            "description": forms.TextInput(attrs={"placeholder": "Webhook Power Automate / Teams Workflow per recapito al singolo utente"}),
        }
        labels = {
            "code": "Codice",
            "name": "Nome endpoint",
            "endpoint_type": "Tipo endpoint",
            "endpoint_url": "Endpoint URL",
            "description": "Descrizione",
            "is_active": "Attivo",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["endpoint_type"].initial = AutomationDeliveryEndpointType.TEAMS_FLOW_WEBHOOK
        self.fields["endpoint_type"].required = False

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data["endpoint_type"] = AutomationDeliveryEndpointType.TEAMS_FLOW_WEBHOOK
        return cleaned_data
