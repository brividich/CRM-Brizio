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
    # MANUAL: regole eseguite solo on-demand (es. da un endpoint via run_rule).
    # Gli eventi di coda DB producono solo insert/update, quindi una regola manual
    # non viene mai agganciata automaticamente dal dispatcher (find_matching_rules).
    MANUAL = "manual", "Manuale (on-demand)"


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
    # Operatori temporali. Il valore del campo deve essere una data/datetime.
    # DAYS_FROM_NOW_*: confronta (campo - oggi) in giorni con expected_value (intero).
    #   Positivo = data nel futuro. Es. data_scadenza entro 30gg => days_from_now_lte 30.
    # DAYS_SPAN_*: confronta (campo - altro_campo) in giorni con expected_value nel
    #   formato "altro_campo:N" (es. "data_inizio:10" => (data_fine - data_inizio) > 10).
    DAYS_FROM_NOW_LTE = "days_from_now_lte", "Days from now ≤"
    DAYS_FROM_NOW_GTE = "days_from_now_gte", "Days from now ≥"
    DAYS_SPAN_GT = "days_span_gt", "Days span >"
    DAYS_SPAN_GTE = "days_span_gte", "Days span ≥"
    # Debounce per gruppo. La condizione è una LETTURA PURA (nessun side-effect): ritorna True
    # (regola eseguibile) solo se NON esiste un invio recente per la coppia namespace+valore.
    # Il valore del gruppo viene da field_name; expected_value nel formato "namespace:minuti"
    # (es. "mail_anomalie_op:5"). Il namespace è indipendente dalla regola (condivisibile fra
    # regole insert/update). La scrittura di last_fired_at (AutomationCooldownGroup) la fa il
    # motore SOLO dopo l'esecuzione riuscita delle azioni della regola (vedi run_rule).
    COOLDOWN_GROUP = "cooldown_group", "Cooldown per gruppo (debounce)"


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
    SPLIT_ASSENZA_GIORNALIERA = "split_assenza_giornaliera", "Split assenza giornaliera"
    UPDATE_DASHBOARD_METRIC = "update_dashboard_metric", "Update dashboard metric"
    WRITE_LOG = "write_log", "Write log"
    DELAY_SCHEDULE = "delay_schedule", "Delay / Schedule"
    HTTP_REQUEST = "http_request", "HTTP request"
    TEAMS_WEBHOOK = "teams_webhook", "Teams webhook"
    SEND_ANOMALIE_MAIL_ACTION = "send_anomalie_mail_action", "Invia mail-action anomalie (token sicuro)"
    SEND_ANOMALIE_MAIL_ACTION_BY_OP = "send_anomalie_mail_action_by_op", "Invia mail-action anomalie a CC/CAR dell'OP (risolti automaticamente)"
    # Controllo flusso
    SEND_APPROVAL = "send_approval", "Richiedi Approvazione"
    DO_UNTIL = "do_until", "Do Until (Ripeti fino a condizione)"
    FOR_EACH = "for_each", "Per Ogni Elemento (For Each)"
    BRANCH = "branch", "Branch / Condizione If-Else"
    COUNT_BRANCH = "count_branch", "Conta record e confronta soglia (Count Branch)"


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
    exclusion_group = models.CharField(
        max_length=80,
        blank=True,
        default="",
        db_index=True,
        help_text=(
            "Gruppo di esclusione: le regole con lo stesso gruppo che matchano "
            "lo stesso record si escludono a vicenda. Ne parte una sola, quella "
            "a priorita' piu' alta; se va in errore si prova la successiva del "
            "gruppo (fallback a cascata). Vuoto = nessuna esclusione."
        ),
    )
    priority = models.IntegerField(
        default=0,
        db_index=True,
        help_text=(
            "Priorita' nel gruppo di esclusione: valore piu' alto = valutata "
            "prima. Ignorata se exclusion_group e' vuoto."
        ),
    )
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


class AutomationCooldownGroup(models.Model):
    """Ultimo invio per chiave-logica+valore, usato dall'operatore `cooldown_group` (debounce).

    La chiave è ``(group_key, group_value)``, INDIPENDENTE dalla regola: più regole (es. una su
    insert e una su update) possono condividere lo stesso namespace e quindi lo stesso cooldown
    per la stessa entità (es. la stessa OP).

    La condizione `cooldown_group` legge soltanto questa tabella (predicato puro, sicuro in
    dry-run/test). La scrittura di ``last_fired_at`` la fa il motore (`run_rule`) SOLO dopo
    l'esecuzione riuscita delle azioni — così il cooldown non viene "bruciato" se l'invio fallisce.
    """

    group_key = models.CharField(max_length=120, db_index=True)   # namespace logico, es. "mail_anomalie_op"
    group_value = models.CharField(max_length=255, db_index=True)  # valore gruppo, es. "OP-2026-0312"
    last_fired_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "automazioni_cooldowngroup"
        unique_together = [("group_key", "group_value")]
        indexes = [
            models.Index(fields=["group_key", "last_fired_at"], name="autom_cdg_key_time_idx"),
        ]

    def __str__(self) -> str:
        return f"Cooldown {self.group_key}={self.group_value}"


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


class ApprovalEmailTemplateDeliveryMode(models.TextChoices):
    PORTAL_LINKS = "portal_links", "Link portale (HTTP)"
    MAIL_REPLY = "mail_reply", "Risposta email (mailto:)"
    HYBRID = "hybrid", "Ibrido (link portale + mailto:)"


class ApprovalEmailTemplate(models.Model):
    """
    Template riutilizzabile per le email di approvazione generate da `send_approval`.
    Supporta tre modalità di consegna:
    - portal_links: CTA con link HTTP al portale (comportamento classico)
    - mail_reply: CTA con link mailto: verso una mailbox tecnica interna
    - hybrid: entrambi
    """

    code = models.SlugField(max_length=120, unique=True, verbose_name="Codice univoco")
    name = models.CharField(max_length=255, verbose_name="Nome")
    description = models.TextField(blank=True, default="", verbose_name="Descrizione")
    is_enabled = models.BooleanField(default=True, db_index=True, verbose_name="Abilitato")
    delivery_mode = models.CharField(
        max_length=20,
        choices=ApprovalEmailTemplateDeliveryMode.choices,
        default=ApprovalEmailTemplateDeliveryMode.PORTAL_LINKS,
        verbose_name="Modalità recapito",
    )

    # ── Contenuto email ──────────────────────────────────────────────────────
    subject_template = models.CharField(
        max_length=512,
        default="Richiesta di approvazione #{id}",
        verbose_name="Oggetto email",
        help_text="Supporta placeholder {campo}.",
    )
    title_template = models.CharField(
        max_length=512,
        blank=True,
        default="",
        verbose_name="Titolo / intestazione mail",
        help_text="Titolo grande visualizzato in cima al corpo email.",
    )
    intro_template = models.TextField(
        blank=True,
        default="",
        verbose_name="Testo introduttivo",
        help_text="Paragrafo introduttivo sopra i facts. Supporta placeholder.",
    )
    body_template = models.TextField(
        blank=True,
        default="",
        verbose_name="Corpo libero (HTML)",
        help_text=(
            "Corpo HTML opzionale a sostituzione completa di intro+facts. "
            "Se compilato, intro_template e facts vengono ignorati."
        ),
    )

    # ── Facts ────────────────────────────────────────────────────────────────
    include_facts = models.BooleanField(
        default=True,
        verbose_name="Includi facts / riepilogo",
        help_text="Se attivo, mostra una tabella facts nella mail (ignorato se body_template è compilato).",
    )
    facts_lines = models.TextField(
        blank=True,
        default="",
        verbose_name="Righe facts",
        help_text="Una riga per fatto: Etichetta | {placeholder}",
    )

    # ── Bottoni CTA ──────────────────────────────────────────────────────────
    approval_label = models.CharField(max_length=100, default="Approva", verbose_name='Label "Approva"')
    rejection_label = models.CharField(max_length=100, default="Rifiuta", verbose_name='Label "Rifiuta"')

    # ── Azioni mailto: ───────────────────────────────────────────────────────
    include_mailto_actions = models.BooleanField(
        default=False,
        verbose_name="Includi CTA mailto:",
        help_text=(
            "Genera link mailto: verso la mailbox tecnica. "
            "Attivo solo per delivery_mode mail_reply o hybrid."
        ),
    )
    mailto_mailbox = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Mailbox tecnica approvazioni",
        help_text="Es. approvazioni@cnovicrom.local — sovrascrive il default globale se compilato.",
    )
    approval_mailto_subject_template = models.CharField(
        max_length=512,
        blank=True,
        default="CMD APPROVO RID {approval_token}",
        verbose_name="Oggetto mailto Approva",
        help_text="Deterministic subject per il parser. Usa {approval_token} come identificatore univoco.",
    )
    approval_mailto_body_template = models.TextField(
        blank=True,
        default="CMD: APPROVO\nRID: {approval_token}",
        verbose_name="Corpo mailto Approva",
    )
    rejection_mailto_subject_template = models.CharField(
        max_length=512,
        blank=True,
        default="CMD RIFIUTO RID {approval_token}",
        verbose_name="Oggetto mailto Rifiuta",
        help_text="Deterministic subject per il parser. Usa {approval_token} come identificatore univoco.",
    )
    rejection_mailto_body_template = models.TextField(
        blank=True,
        default="CMD: RIFIUTO\nRID: {approval_token}\nMOTIVO: ",
        verbose_name="Corpo mailto Rifiuta",
    )

    # ── Audit ────────────────────────────────────────────────────────────────
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_email_templates_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_email_templates_updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Template email approvazione"
        verbose_name_plural = "Template email approvazioni"

    def __str__(self) -> str:
        return f"{self.name} [{self.code}]"

    def uses_mailto(self) -> bool:
        return self.delivery_mode in (
            ApprovalEmailTemplateDeliveryMode.MAIL_REPLY,
            ApprovalEmailTemplateDeliveryMode.HYBRID,
        )

    def uses_portal_links(self) -> bool:
        return self.delivery_mode in (
            ApprovalEmailTemplateDeliveryMode.PORTAL_LINKS,
            ApprovalEmailTemplateDeliveryMode.HYBRID,
        )

    @staticmethod
    def _subject_has_command(template_value: str, *markers: str) -> bool:
        normalized = str(template_value or "").upper()
        return any(marker in normalized for marker in markers)

    def clean(self) -> None:
        super().clean()

        errors: dict[str, list[str]] = {}

        if (
            self.include_mailto_actions
            and self.delivery_mode == ApprovalEmailTemplateDeliveryMode.PORTAL_LINKS
        ):
            errors.setdefault("include_mailto_actions", []).append(
                "Le azioni mailto: sono disponibili solo per le modalita 'mail_reply' o 'hybrid'."
            )

        if self.uses_mailto():
            approval_subject = str(self.approval_mailto_subject_template or "")
            rejection_subject = str(self.rejection_mailto_subject_template or "")

            if "{approval_token}" not in approval_subject:
                errors.setdefault("approval_mailto_subject_template", []).append(
                    "Il subject mailto Approva deve contenere {approval_token}."
                )
            if not self._subject_has_command(approval_subject, "CMD APPROVO", "CMD: APPROVO"):
                errors.setdefault("approval_mailto_subject_template", []).append(
                    "Il subject mailto Approva deve contenere il comando CMD APPROVO."
                )

            if "{approval_token}" not in rejection_subject:
                errors.setdefault("rejection_mailto_subject_template", []).append(
                    "Il subject mailto Rifiuta deve contenere {approval_token}."
                )
            if not self._subject_has_command(rejection_subject, "CMD RIFIUTO", "CMD: RIFIUTO"):
                errors.setdefault("rejection_mailto_subject_template", []).append(
                    "Il subject mailto Rifiuta deve contenere il comando CMD RIFIUTO."
                )

        if errors:
            raise ValidationError(errors)


# ── Schema drift helpers per ApprovalEmailTemplate ──────────────────────────
APPROVAL_EMAIL_TEMPLATE_TABLE_NAME = "automazioni_approvalemailtemplate"
APPROVAL_EMAIL_TEMPLATE_UNAVAILABLE_MESSAGE = (
    "Template email approvazioni non disponibili: applicare la migration "
    "`automazioni.0011_approvalemailtemplate`."
)


def _is_approval_template_table_missing(exc: Exception) -> bool:
    message = _db_exception_text(exc)
    return (
        APPROVAL_EMAIL_TEMPLATE_TABLE_NAME in message
        and any(
            marker in message
            for marker in ("42s02", "no such table", "invalid object name", "nome di oggetto", "non è valido")
        )
    )


def list_approval_email_templates(*, enabled_only: bool = True) -> tuple[list["ApprovalEmailTemplate"], bool]:
    """Ritorna (lista_template, tabella_mancante). Safe rispetto a schema drift."""
    qs = ApprovalEmailTemplate.objects.all()
    if enabled_only:
        qs = qs.filter(is_enabled=True)
    try:
        return list(qs.order_by("name")), False
    except (OperationalError, ProgrammingError) as exc:
        if _is_approval_template_table_missing(exc):
            return [], True
        raise


def get_approval_email_template(
    *,
    template_id: object = None,
    template_code: object = None,
    enabled_only: bool = True,
) -> tuple["ApprovalEmailTemplate | None", bool]:
    """Risolve un template per ID o code. Ritorna (template | None, tabella_mancante)."""
    id_raw = str(template_id or "").strip()
    code_raw = str(template_code or "").strip()
    if not id_raw and not code_raw:
        return None, False
    try:
        qs = ApprovalEmailTemplate.objects.all()
        if enabled_only:
            qs = qs.filter(is_enabled=True)
        if id_raw:
            return qs.filter(pk=id_raw).first(), False
        return qs.filter(code=code_raw).first(), False
    except (OperationalError, ProgrammingError) as exc:
        if _is_approval_template_table_missing(exc):
            return None, True
        raise


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


# ── Tracking messaggi mailbox approvazioni (Graph / IMAP) ───────────────────

class ApprovalMailboxMessageStatus(models.TextChoices):
    PENDING = "pending", "In attesa"
    PROCESSED = "processed", "Processato"
    IGNORED = "ignored", "Ignorato"
    ERROR = "error", "Errore"


class ApprovalMailboxMessage(models.Model):
    """
    Tracking persistente di ogni messaggio letto dalla mailbox approvazioni.
    Chiave di deduplica: `internet_message_id` (header RFC 2822 Message-ID).
    Garantisce idempotenza forte: lo stesso messaggio non viene elaborato due volte
    anche se il polling viene rieseguito più volte prima della marcatura come letto.
    """

    internet_message_id = models.CharField(
        max_length=512,
        unique=True,
        db_index=True,
        help_text="Header RFC 2822 Message-ID. Chiave di deduplica globale.",
    )
    graph_message_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="ID opaco Graph API (usato per PATCH mark-as-read, move, ecc.).",
    )
    mailbox = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Indirizzo mailbox letta (es. avviso@costruzioninovicrom.it).",
    )
    folder_name = models.CharField(max_length=255, blank=True, default="", help_text="Cartella di provenienza.")
    subject_raw = models.TextField(blank=True, default="", help_text="Oggetto grezzo del messaggio.")
    from_email = models.CharField(max_length=255, blank=True, default="", help_text="Indirizzo mittente estratto.")
    received_at = models.DateTimeField(null=True, blank=True, db_index=True, help_text="Data/ora ricezione.")
    command_detected = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Comando rilevato: 'approvo', 'rifiuto' oppure vuoto se nessuno.",
    )
    token_found = models.CharField(
        max_length=36,
        blank=True,
        default="",
        help_text="UUID token approvazione estratto dal messaggio.",
    )
    processing_status = models.CharField(
        max_length=20,
        choices=ApprovalMailboxMessageStatus.choices,
        default=ApprovalMailboxMessageStatus.PENDING,
        db_index=True,
    )
    processing_error = models.TextField(blank=True, default="", help_text="Dettaglio errore se status=error.")
    excerpt = models.TextField(blank=True, default="", help_text="Estratto body (max 500 car.) per diagnostica.")
    linked_approval = models.ForeignKey(
        AutomationApproval,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mailbox_messages",
        help_text="Approvazione collegata, se il messaggio è stato processato con successo.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at", "-created_at"]
        verbose_name = "Messaggio mailbox approvazione"
        verbose_name_plural = "Messaggi mailbox approvazione"
        indexes = [
            models.Index(fields=["processing_status", "received_at"], name="autom_mbmsg_status_rcv_idx"),
        ]

    def __str__(self) -> str:
        return f"MailboxMsg<{self.from_email}:{self.command_detected}:{self.processing_status}>"
