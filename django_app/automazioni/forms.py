from __future__ import annotations

import json
from typing import Any

from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from .models import (
    AutomationAction,
    AutomationActionType,
    AutomationCondition,
    AutomationConditionOperator,
    AutomationConditionValueType,
    AutomationRule,
    AutomationRuleTriggerScope,
)
from .services import get_action_table_whitelist
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


def _serialize_mapping_for_textarea(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    lines: list[str] = []
    for key, item_value in value.items():
        lines.append(f"{key} = {item_value}")
    return "\n".join(lines)


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


def _build_whitelist_help(action_type: str) -> str:
    whitelist = get_action_table_whitelist().get(action_type, {})
    if not whitelist:
        return "Nessuna tabella whitelistata."

    rows = []
    for table_name, table_config in sorted(whitelist.items()):
        fields = ", ".join(sorted(table_config.get("fields", set())))
        where_fields = ", ".join(sorted(table_config.get("where_fields", set())))
        if where_fields:
            rows.append(f"{table_name}: fields [{fields}] | where [{where_fields}]")
        else:
            rows.append(f"{table_name}: fields [{fields}]")
    return " | ".join(rows)


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
        if not self.instance.pk:
            self.fields["order"].initial = ""
            self.fields["is_enabled"].initial = False
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
                self.fields["is_enabled"].initial = False
                self.fields["delay_mode"].initial = "relative"
                self.fields["delay_unit"].initial = "days"
                self.fields["http_method"].initial = "POST"
                self.fields["http_timeout_seconds"].initial = 20

        insert_tables = sorted(get_action_table_whitelist().get(AutomationActionType.INSERT_RECORD, {}).keys())
        update_tables = sorted(get_action_table_whitelist().get(AutomationActionType.UPDATE_RECORD, {}).keys())
        self.fields["insert_target_table"].choices = [("", "---------"), *[(table, table) for table in insert_tables]]
        self.fields["update_target_table"].choices = [("", "---------"), *[(table, table) for table in update_tables]]
        self.fields["run_if_field_name"].choices = _field_choices_from_registry(self._effective_source_code, mode="condition")
        self.fields["run_if_expected_value"].help_text = (
            "Per `changed_from_to` usa `vecchio|nuovo`. Se spunti `inverti risultato`, il branch diventa un ELSE."
        )
        self.fields["insert_field_mappings_text"].help_text = _build_whitelist_help(AutomationActionType.INSERT_RECORD)
        self.fields["update_fields_text"].help_text = _build_whitelist_help(AutomationActionType.UPDATE_RECORD)
        self.fields["trigger_update_fields_text"].help_text = _build_source_update_help(self._effective_source_code)
        self.fields["delay_value_template"].help_text = "Numero o placeholder, es. `1`, `4`, `{giorni}`."
        self.fields["delay_until_template"].help_text = "Data/ora ISO o placeholder, es. `2026-04-10T15:30:00`."

        config = self.instance.config_json if self.instance.pk and isinstance(self.instance.config_json, dict) else {}
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
            self.initial.setdefault("teams_webhook_url", config.get("webhook_url", ""))
            self.initial.setdefault("teams_title_template", config.get("title_template", ""))
            self.initial.setdefault("teams_summary_template", config.get("summary_template", ""))
            self.initial.setdefault("teams_text_template", config.get("text_template", ""))
            self.initial.setdefault("teams_theme_color", config.get("theme_color", ""))
            self.initial.setdefault("teams_facts_text", _serialize_mapping_for_textarea(config.get("facts")))

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
            allowed_fields = whitelist.get(config_json["target_table"], {}).get("fields", set())
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
        filename = str(getattr(uploaded_file, "name", "") or "").strip().lower()
        if not (filename.endswith(".automation_package.json") or filename.endswith(".json")):
            raise forms.ValidationError("Carica un file `.automation_package.json` o `.json` compatibile.")
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
    extra=2,
    can_delete=True,
)


AutomationActionFormSet = inlineformset_factory(
    AutomationRule,
    AutomationAction,
    form=AutomationActionForm,
    formset=_AutomationOrderedInlineFormSet,
    extra=2,
    can_delete=True,
)
