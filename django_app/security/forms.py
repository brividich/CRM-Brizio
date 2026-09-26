from django import forms
from django.core.exceptions import ValidationError

from .models import (
    SecurityMailboxSource,
    BackupExpectedJobConfig,
    SecurityAlertRuleConfig,
    SecurityAlertSuppressionRule,
    SecurityCenterSetting,
    SecurityNotificationChannel,
    SecurityParserConfig,
    SecuritySourceConfig,
    SecurityTicketConfig,
)


JSON_TEXTAREA = forms.Textarea(attrs={"rows": 3})

COMMON_LABELS = {
    "aggregation_strategy": "Strategia aggregazione",
    "alert_on_duration_anomaly": "Alert su anomalia durata",
    "alert_on_failure": "Alert su fallimento",
    "alert_on_missing": "Alert su mancante",
    "alert_on_size_anomaly": "Alert su anomalia dimensione",
    "auto_close_enabled": "Chiusura automatica attiva",
    "auto_create_evidence_container": "Crea contenitore evidenze automatico",
    "auto_create_ticket": "Crea ticket automatico",
    "channel_type": "Tipo canale",
    "code": "Codice",
    "conditions_json": "Condizioni JSON",
    "config_json": "Configurazione JSON",
    "cooldown_minutes": "Cooldown minuti",
    "critical_asset": "Asset critico",
    "dedup_window_minutes": "Finestra dedup minuti",
    "default_assignee": "Assegnatario predefinito",
    "default_group": "Gruppo predefinito",
    "description": "Descrizione",
    "device_name": "Nome dispositivo",
    "enabled": "Attivo",
    "event_type": "Tipo evento",
    "expected_days_of_week": "Giorni attesi",
    "expected_frequency": "Frequenza attesa",
    "expected_start_time_from": "Ora inizio da",
    "expected_start_time_to": "Ora inizio a",
    "expires_at": "Scadenza",
    "input_type": "Tipo input",
    "is_active": "Attiva",
    "is_secret": "Segreto",
    "job_name": "Nome job",
    "mailbox_sender_patterns": "Pattern mittente mailbox",
    "mailbox_subject_patterns": "Pattern oggetto mailbox",
    "match_payload": "Payload matching",
    "max_duration_minutes": "Durata massima minuti",
    "max_transferred_gb": "GB massimi trasferiti",
    "metadata_json": "Metadati JSON",
    "metric_name": "Nome metrica",
    "min_transferred_gb": "GB minimi trasferiti",
    "missing_after_hours": "Mancante dopo ore",
    "name": "Nome",
    "nas_name": "Nome NAS",
    "notify_on_new_alert": "Notifica nuovo alert",
    "notify_on_sla_breach": "Notifica violazione SLA",
    "notify_on_ticket_created": "Notifica ticket creato",
    "owner": "Responsabile",
    "parser_name": "Nome parser",
    "priority": "Priorita",
    "reason": "Motivo",
    "recipients": "Destinatari",
    "reopen_on_recurrence": "Riapri su ricorrenza",
    "replace_webhook_secret": "Sostituisci segreto webhook",
    "scope_type": "Tipo ambito",
    "severity": "Severita",
    "severity_mapping_json": "Mappatura severità (JSON)",
    "severity_min": "Severita minima",
    "sla_by_severity": "SLA per severita",
    "source": "Sorgente",
    "source_type": "Tipo sorgente",
    "starts_at": "Inizia il",
    "statuses": "Stati",
    "threshold_json": "Soglia JSON",
    "threshold_value": "Valore soglia",
    "value": "Valore",
    "vendor": "Fornitore",
}


class SecurityCenterSettingForm(forms.ModelForm):
    class Meta:
        model = SecurityCenterSetting
        fields = ["value", "description", "is_secret"]
        labels = COMMON_LABELS
        widgets = {"value": JSON_TEXTAREA}


FREQUENCY_LABELS_IT = {
    "manual": "Manuale",
    "hourly": "Oraria",
    "daily": "Giornaliera",
    "weekly": "Settimanale",
    "monthly": "Mensile",
}


class PatternListField(forms.CharField):
    """Lista di pattern come testo «uno per riga» (prima: JSON grezzo da scrivere a mano)."""

    widget = forms.Textarea(attrs={"rows": 3, "placeholder": "Uno per riga, es. *watchguard*"})

    def prepare_value(self, value):
        if isinstance(value, (list, tuple)):
            return "\n".join(str(item) for item in value)
        return value

    def to_python(self, value):
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        text = super().to_python(value) or ""
        return [line.strip() for line in text.splitlines() if line.strip()]


class SecuritySourceConfigForm(forms.ModelForm):
    mailbox_sender_patterns = PatternListField(
        label="Pattern mittente", required=False,
        help_text="Uno per riga; * vale per qualsiasi testo (es. *@watchguard.com).",
    )
    mailbox_subject_patterns = PatternListField(
        label="Pattern oggetto", required=False,
        help_text="Uno per riga; basta che l'oggetto corrisponda a uno di essi.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["expected_frequency"].choices = [
            (value, FREQUENCY_LABELS_IT.get(value, label)) for value, label in self.fields["expected_frequency"].choices
        ]
        self.fields["expected_time_window_start"].label = "Finestra attesa: dalle"
        self.fields["expected_time_window_end"].label = "Finestra attesa: alle"

    class Meta:
        model = SecuritySourceConfig
        fields = [
            "name",
            "source_type",
            "vendor",
            "enabled",
            "description",
            "expected_frequency",
            "expected_time_window_start",
            "expected_time_window_end",
            "mailbox_sender_patterns",
            "mailbox_subject_patterns",
            "parser_name",
            "severity_mapping_json",
            "metadata_json",
        ]
        labels = COMMON_LABELS
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "mailbox_sender_patterns": JSON_TEXTAREA,
            "mailbox_subject_patterns": JSON_TEXTAREA,
            "severity_mapping_json": JSON_TEXTAREA,
            "metadata_json": JSON_TEXTAREA,
            "expected_time_window_start": forms.TimeInput(attrs={"type": "time"}),
            "expected_time_window_end": forms.TimeInput(attrs={"type": "time"}),
        }


class SecurityParserConfigForm(forms.ModelForm):
    class Meta:
        model = SecurityParserConfig
        fields = ["parser_name", "enabled", "priority", "source_type", "input_type", "description", "config_json"]
        labels = COMMON_LABELS
        widgets = {"description": forms.Textarea(attrs={"rows": 3}), "config_json": JSON_TEXTAREA}


class SecurityAlertRuleConfigForm(forms.ModelForm):
    class Meta:
        model = SecurityAlertRuleConfig
        fields = [
            "code",
            "name",
            "enabled",
            "source_type",
            "metric_name",
            "condition_operator",
            "threshold_value",
            "threshold_json",
            "severity",
            "cooldown_minutes",
            "dedup_window_minutes",
            "auto_create_ticket",
            "auto_create_evidence_container",
            "description",
        ]
        labels = COMMON_LABELS
        widgets = {"threshold_json": JSON_TEXTAREA, "description": forms.Textarea(attrs={"rows": 3})}


class SecurityAlertSuppressionRuleForm(forms.ModelForm):
    class Meta:
        model = SecurityAlertSuppressionRule
        fields = [
            "name",
            "is_active",
            "scope_type",
            "source",
            "event_type",
            "severity",
            "match_payload",
            "conditions_json",
            "starts_at",
            "expires_at",
            "reason",
            "owner",
        ]
        labels = COMMON_LABELS
        widgets = {
            "match_payload": JSON_TEXTAREA,
            "conditions_json": JSON_TEXTAREA,
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "reason": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("reason"):
            raise ValidationError("Le regole di soppressione richiedono un motivo.")
        if not cleaned.get("owner"):
            raise ValidationError("Le regole di soppressione richiedono un responsabile.")
        if cleaned.get("starts_at") and cleaned.get("expires_at") and cleaned["expires_at"] <= cleaned["starts_at"]:
            raise ValidationError("La scadenza deve essere successiva all'inizio.")
        return cleaned


class BackupExpectedJobConfigForm(forms.ModelForm):
    class Meta:
        model = BackupExpectedJobConfig
        fields = [
            "job_name",
            "device_name",
            "nas_name",
            "enabled",
            "critical_asset",
            "expected_days_of_week",
            "expected_start_time_from",
            "expected_start_time_to",
            "max_duration_minutes",
            "min_transferred_gb",
            "max_transferred_gb",
            "missing_after_hours",
            "alert_on_missing",
            "alert_on_failure",
            "alert_on_duration_anomaly",
            "alert_on_size_anomaly",
        ]
        labels = COMMON_LABELS
        widgets = {
            "expected_days_of_week": JSON_TEXTAREA,
            "expected_start_time_from": forms.TimeInput(attrs={"type": "time"}),
            "expected_start_time_to": forms.TimeInput(attrs={"type": "time"}),
        }


class SecurityNotificationChannelForm(forms.ModelForm):
    replace_webhook_secret = forms.CharField(label=COMMON_LABELS["replace_webhook_secret"], required=False, widget=forms.PasswordInput(render_value=False))

    class Meta:
        model = SecurityNotificationChannel
        fields = [
            "name",
            "channel_type",
            "enabled",
            "severity_min",
            "recipients",
            "notify_on_new_alert",
            "notify_on_ticket_created",
            "notify_on_sla_breach",
            "cooldown_minutes",
        ]
        labels = COMMON_LABELS
        widgets = {"recipients": forms.Textarea(attrs={"rows": 3})}


class SecurityTicketConfigForm(forms.ModelForm):
    class Meta:
        model = SecurityTicketConfig
        fields = [
            "aggregation_strategy",
            "default_assignee",
            "default_group",
            "statuses",
            "auto_close_enabled",
            "reopen_on_recurrence",
            "sla_by_severity",
        ]
        labels = COMMON_LABELS
        widgets = {"statuses": JSON_TEXTAREA, "sla_by_severity": JSON_TEXTAREA}


class SecurityMailboxSourceForm(forms.ModelForm):
    """Casella mail da leggere via Microsoft Graph (prima non creabile dall'HUB)."""

    SOURCE_TYPE_UI_CHOICES = [
        ("graph", "Microsoft 365 (Graph)"),
        ("manual", "Solo caricamento manuale (nessuna lettura)"),
    ]

    class Meta:
        model = SecurityMailboxSource
        fields = [
            "name",
            "enabled",
            "source_type",
            "mailbox_address",
            "description",
            "sender_allowlist_text",
            "require_verified_sender",
            "subject_include_text",
            "subject_exclude_text",
            "expected_every_hours",
            "max_messages_per_run",
            "process_attachments",
            "process_email_body",
        ]
        labels = {
            "name": "Nome",
            "enabled": "Attiva (lettura automatica)",
            "source_type": "Tipo",
            "mailbox_address": "Indirizzo della casella",
            "description": "Descrizione",
            "sender_allowlist_text": "Mittenti ammessi",
            "require_verified_sender": "Accetta solo mittenti verificati (DKIM/SPF)",
            "subject_include_text": "L'oggetto deve contenere",
            "subject_exclude_text": "Escludi se l'oggetto contiene",
            "expected_every_hours": "Report atteso almeno ogni (ore)",
            "max_messages_per_run": "Mail massime per lettura",
            "process_attachments": "Analizza gli allegati",
            "process_email_body": "Analizza il testo della mail",
        }
        help_texts = {
            "mailbox_address": "La casella che riceve i report (es. soc@azienda.it). L'app Entra del portale deve avere il permesso Mail.Read.",
            "sender_allowlist_text": "Uno per riga: indirizzo completo o dominio (es. microsoft.com). Vuoto = tutti.",
            "subject_include_text": "Uno per riga; vuoto = nessun filtro.",
            "subject_exclude_text": "Uno per riga.",
            "expected_every_hours": "0 = nessun controllo. Se non arriva nulla entro questo intervallo parte un alert «sorgente silenziosa».",
            "require_verified_sender": "Più sicuro, ma scarta le mail senza intestazione Authentication-Results.",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "sender_allowlist_text": forms.Textarea(attrs={"rows": 3, "placeholder": "microsoft.com, watchguard.com (uno per riga)"}),
            "subject_include_text": forms.Textarea(attrs={"rows": 2}),
            "subject_exclude_text": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["source_type"].choices = self.SOURCE_TYPE_UI_CHOICES
        if not self.instance.pk:
            self.initial.setdefault("source_type", "graph")
            self.initial.setdefault("expected_every_hours", 24)

    def clean(self):
        data = super().clean()
        if data.get("source_type") == "graph" and not data.get("mailbox_address"):
            self.add_error("mailbox_address", "Obbligatorio per leggere la casella con Microsoft Graph.")
        return data
