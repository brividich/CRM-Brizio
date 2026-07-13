from pathlib import Path

from django import forms
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.db.models import Count
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .forms import (
    BackupExpectedJobConfigForm,
    SecurityAlertRuleConfigForm,
    SecurityAlertSuppressionRuleForm,
    SecurityCenterSettingForm,
    SecurityNotificationChannelForm,
    SecurityParserConfigForm,
    SecuritySourceConfigForm,
    SecurityTicketConfigForm,
)
from .models import (
    BackupExpectedJobConfig,
    SecurityAlert,
    SecurityAlertRuleConfig,
    SecurityAlertSuppressionRule,
    SecurityCenterSetting,
    SecurityConfigurationAuditLog,
    SecurityEvidenceContainer,
    SecurityEventRecord,
    SecurityKpiSnapshot,
    SecurityMailboxMessage,
    SecurityMailboxSource,
    SecurityMailboxIngestionRun,
    SecurityNotificationChannel,
    SecurityParserConfig,
    SecurityRemediationTicket,
    ParseStatus,
    SecurityReport,
    SecurityReportMetric,
    SecuritySource,
    SecuritySourceConfig,
    SecuritySourceFile,
    SecurityTicketConfig,
    SecurityVulnerabilityFinding,
    Severity,
    SourceType,
    Status,
)
from .permissions import can_view_security_center
from .services.alert_lifecycle import (
    ACTIVE_ALERT_STATUSES,
    acknowledge_alert,
    close_alert,
    mark_false_positive,
    reopen_alert,
    snooze_alert,
)
from .services.kpi_service import build_daily_kpi_snapshots
from .services.parser_engine import _match_enabled_parser, run_pending_parsers
from .services.rule_engine import evaluate_security_rules, test_alert_rule
from .services.backup_monitoring import last_seen_backup_status, missing_backup_candidates
from .services.configuration import (
    audit_config_change,
    audit_model_form_changes,
    can_manage_security_config,
    masked_setting_value,
    snapshot_instance,
    source_matches_sample,
)
from .services.ingestion import get_or_create_source, ingest_mailbox_message, ingest_source_file
from .services.addon_registry import get_addon_detail, get_addon_registry
from .services.diagnostics import build_diagnostics_context
from .services.security_inbox_pipeline import process_mailbox_message, process_source_file


INBOX_ALLOWED_EXTENSIONS = {".pdf", ".csv", ".txt", ".eml", ".log"}
INBOX_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@ensure_csrf_cookie
def dashboard(request):
    today = timezone.localdate()
    context = {
        "open_alerts_count": SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES).count(),
        "critical_alerts_count": SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES, severity=Severity.CRITICAL).count(),
        "open_tickets_count": SecurityRemediationTicket.objects.filter(status__in=[Status.NEW, Status.OPEN, Status.IN_PROGRESS]).count(),
        "reports_today_count": SecurityReport.objects.filter(created_at__date=today).count(),
        "evidence_today_count": SecurityEvidenceContainer.objects.filter(created_at__date=today).count(),
        "latest_critical_cves": SecurityVulnerabilityFinding.objects.filter(severity=Severity.CRITICAL).order_by("-last_seen_at")[:8],
        "latest_defender_findings": _decorate_defender_findings(
            SecurityVulnerabilityFinding.objects.select_related("source", "report")
            .filter(payload__source="microsoft_defender")
            .order_by("-last_seen_at")[:8]
        ),
        "latest_alerts": _decorate_alerts(SecurityAlert.objects.select_related("source", "event").order_by("-updated_at")[:10]),
        "last_pipeline_run": request.session.get("last_pipeline_run"),
    }
    return render(request, "security/dashboard.html", context)


@ensure_csrf_cookie
def alerts_list(request):
    alerts = SecurityAlert.objects.select_related("source", "event").annotate(evidence_count=Count("evidence_containers")).order_by("-updated_at")

    # Validate and sanitize input
    severity = request.GET.get("severity")
    if severity and severity in [s[0] for s in Severity.choices]:
        alerts = alerts.filter(severity=severity)

    status = request.GET.get("status")
    if status and status in [s[0] for s in Status.choices]:
        alerts = alerts.filter(status=status)

    source_id = request.GET.get("source")
    if source_id and source_id.isdigit():
        alerts = alerts.filter(source_id=int(source_id))

    date_str = request.GET.get("date")
    if date_str:
        try:
            from datetime import datetime
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
            alerts = alerts.filter(created_at__date=date_obj)
        except ValueError:
            pass  # Invalid date format, ignore filter

    context = {
        "alerts": _decorate_alerts(alerts[:100]),
        "sources": SecuritySource.objects.order_by("name"),
        "severity_choices": Severity.choices,
        "status_choices": Status.choices,
        "filters": request.GET,
    }
    return render(request, "security/alerts_list.html", context)


@ensure_csrf_cookie
def alert_detail(request, pk):
    alert = get_object_or_404(SecurityAlert.objects.select_related("source", "event"), pk=pk)
    alert.short_dedup_hash = alert.dedup_hash[:12] if alert.dedup_hash else ""
    ticket = alert.tickets.order_by("-updated_at").first()
    evidence = alert.evidence_containers.prefetch_related("items").order_by("-created_at")
    occurrences = SecurityEventRecord.objects.filter(dedup_hash=alert.dedup_hash).select_related("report").order_by("-occurred_at")[:25]
    action_logs = alert.action_logs.select_related("ticket").order_by("-created_at")[:25]
    payload = alert.event.payload if alert.event_id else {}
    context = {
        "alert": alert,
        "ticket": ticket,
        "evidence": evidence,
        "occurrences": occurrences,
        "action_logs": action_logs,
        "source_report": alert.event.report if alert.event_id else None,
        "vulnerability": {
            "cve": payload.get("cve"),
            "cvss": payload.get("cvss"),
            "affected_product": payload.get("affected_product"),
            "exposed_devices": payload.get("exposed_devices"),
        },
    }
    context.update(_alert_lifecycle_context(alert))
    return render(request, "security/alert_detail.html", context)


@require_POST
def alert_action(request, pk, action):
    alert = get_object_or_404(SecurityAlert, pk=pk)
    action = "false_positive" if action == "false-positive" else action
    actor = request.user.username if request.user.is_authenticated else "ui"
    reason = request.POST.get("reason", "").strip()
    handlers = {
        "acknowledge": lambda: acknowledge_alert(alert, actor=actor, reason=reason),
        "close": lambda: close_alert(alert, actor=actor, reason=reason),
        "false_positive": lambda: mark_false_positive(alert, actor=actor, reason=reason),
        "snooze": lambda: snooze_alert(alert, _parse_snooze_until(request.POST.get("snooze_until")), actor=actor, reason=reason),
        "reopen": lambda: reopen_alert(alert, actor=actor, reason=reason),
    }
    if action not in handlers:
        messages.error(request, "Azione alert non supportata.")
        return redirect("security:alert_detail", pk=alert.pk)

    alert = handlers[action]()
    if request.headers.get("HX-Request"):
        context = _alert_lifecycle_context(alert)
        context.update(
            {
                "alert": alert,
                "action_result": f"Azione alert registrata: {action}.",
                "action_result_canonical": f"Alert action recorded: {action}.",
            }
        )
        return render(request, "security/partials/alert_lifecycle_panel.html", context)
    messages.success(request, f"Azione alert registrata: {action}.")
    return redirect("security:alert_detail", pk=alert.pk)


@ensure_csrf_cookie
def tickets_list(request):
    tickets = SecurityRemediationTicket.objects.select_related("source", "alert").order_by("-updated_at")
    return render(request, "security/tickets_list.html", {"tickets": tickets})


def kpis_page(request):
    selected_date = _parse_date(request.GET.get("date")) or timezone.localdate()
    snapshots = SecurityKpiSnapshot.objects.select_related("source").filter(snapshot_date=selected_date).order_by("source__name", "name")
    grouped = {}
    for snapshot in snapshots:
        source_name = snapshot.source.name if snapshot.source else "Global"
        grouped.setdefault(source_name, []).append(snapshot)
    context = {
        "selected_date": selected_date,
        "previous_date": selected_date - timezone.timedelta(days=1),
        "next_date": selected_date + timezone.timedelta(days=1),
        "grouped_kpis": grouped,
    }
    return render(request, "security/kpis.html", context)


def pipeline_page(request):
    return render(request, "security/pipeline.html", {"last_pipeline_run": request.session.get("last_pipeline_run")})


@ensure_csrf_cookie
def inbox_page(request):
    if not can_view_security_center(request.user):
        return _security_center_denied(request)

    result = None
    if request.method == "POST":
        result = _handle_inbox_post(request)
        if request.headers.get("HX-Request"):
            return render(request, "security/partials/inbox_result.html", {"inbox_result": result})

    context = _inbox_context(result)
    return render(request, "security/inbox.html", context)


def help_page(request):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), login_url="/admin/login/")
    return render(request, "security/help.html", {"docs": SECURITY_CENTER_DOCS})


@require_POST
def pipeline_run(request, action):
    started_at = timezone.now()
    result = {
        "action": action,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": None,
        "reports_parsed": 0,
        "rules_evaluated": 0,
        "alerts_created": 0,
        "alerts_deduplicated": 0,
        "kpis_built": 0,
        "errors": [],
    }
    alerts_before = SecurityAlert.objects.count()
    try:
        if action in {"run-parsers", "full"}:
            result["reports_parsed"] = run_pending_parsers()
            result["parsed_reports"] = _latest_pipeline_reports()
        if action in {"evaluate-rules", "full"}:
            evaluated_event_ids = list(SecurityEventRecord.objects.filter(decision_trace={}).values_list("id", flat=True))
            result["rules_evaluated"] = evaluate_security_rules()
            evaluated = SecurityEventRecord.objects.filter(id__in=evaluated_event_ids)
            result["alerts_deduplicated"] = sum(1 for event in evaluated if event.decision_trace.get("alert_created") is False)
        if action in {"build-kpis", "full"}:
            result["kpis_built"] = build_daily_kpi_snapshots()
    except Exception as exc:  # pragma: no cover - defensive UI reporting
        result["errors"].append(str(exc))
    result["alerts_created"] = max(SecurityAlert.objects.count() - alerts_before, 0)
    result["finished_at"] = timezone.now().isoformat(timespec="seconds")
    request.session["last_pipeline_run"] = result
    request.session.modified = True

    if request.headers.get("HX-Request"):
        return render(request, "security/partials/pipeline_result.html", {"last_pipeline_run": result})
    return redirect(reverse("security:pipeline"))


@ensure_csrf_cookie
def admin_config_dashboard(request):
    if not can_manage_security_config(request.user):
        return _security_config_denied(request)
    cards = [
        _config_card("General", "admin_config_general", SecurityCenterSetting.objects.count(), SecurityCenterSetting.objects.filter(is_secret=True).count(), SecurityCenterSetting.objects.order_by("-updated_at").first()),
        _config_card("Sources", "admin_config_sources", SecuritySourceConfig.objects.filter(enabled=True).count(), SecuritySourceConfig.objects.filter(enabled=False).count(), SecuritySourceConfig.objects.order_by("-updated_at").first()),
        _config_card("Parsers", "admin_config_parsers", SecurityParserConfig.objects.filter(enabled=True).count(), SecurityParserConfig.objects.filter(enabled=False).count(), SecurityParserConfig.objects.order_by("-updated_at").first()),
        _config_card("Alert Rules", "admin_config_alert_rules", SecurityAlertRuleConfig.objects.filter(enabled=True).count(), SecurityAlertRuleConfig.objects.filter(enabled=False).count(), SecurityAlertRuleConfig.objects.order_by("-updated_at").first()),
        _config_card("Suppression Rules", "admin_config_suppressions", SecurityAlertSuppressionRule.objects.filter(is_active=True).count(), SecurityAlertSuppressionRule.objects.filter(is_active=False).count(), SecurityAlertSuppressionRule.objects.order_by("-updated_at").first()),
        _config_card("Backup Monitoring", "admin_config_backups", BackupExpectedJobConfig.objects.filter(enabled=True).count(), len(missing_backup_candidates()), BackupExpectedJobConfig.objects.order_by("-updated_at").first()),
        _config_card("Notifications", "admin_config_notifications", SecurityNotificationChannel.objects.filter(enabled=True).count(), SecurityNotificationChannel.objects.filter(enabled=False).count(), SecurityNotificationChannel.objects.order_by("-updated_at").first()),
        _config_card("Ticketing", "admin_config_ticketing", SecurityTicketConfig.objects.count(), 0, SecurityTicketConfig.objects.order_by("-updated_at").first()),
        _config_card("Audit Log", "admin_config_audit", SecurityConfigurationAuditLog.objects.count(), 0, SecurityConfigurationAuditLog.objects.order_by("-created_at").first()),
    ]
    return render(request, "security/admin_config/dashboard.html", {"cards": cards, "recent_changes": SecurityConfigurationAuditLog.objects.select_related("actor").order_by("-created_at")[:8]})


@ensure_csrf_cookie
def admin_config_general(request):
    if not can_manage_security_config(request.user):
        return _security_config_denied(request)
    settings = SecurityCenterSetting.objects.order_by("category", "key")
    if request.method == "POST":
        setting = get_object_or_404(SecurityCenterSetting, pk=request.POST.get("setting_id"))
        old = snapshot_instance(setting)
        form = SecurityCenterSettingForm(request.POST, instance=setting)
        if form.is_valid():
            obj = form.save(commit=False)
            if setting.is_secret and form.cleaned_data.get("value") in ("", None):
                obj.value = setting.value
            obj.updated_by = request.user
            obj.save()
            audit_model_form_changes(request.user, obj, old, snapshot_instance(obj), request=request, secret_fields={"value"} if obj.is_secret else set())
            messages.success(request, "Impostazione aggiornata.")
            return redirect("security:admin_config_general")
    rows = []
    for setting in settings:
        form = SecurityCenterSettingForm(instance=setting)
        if setting.is_secret:
            form.initial["value"] = ""
        rows.append({"setting": setting, "display_value": masked_setting_value(setting), "form": form})
    return render(request, "security/admin_config/general.html", {"rows": rows})


@ensure_csrf_cookie
def admin_config_sources(request):
    if not can_manage_security_config(request.user):
        return _security_config_denied(request)
    test_result = None
    form = SecuritySourceConfigForm()
    if request.method == "POST":
        if request.POST.get("action") == "test-match":
            config = get_object_or_404(SecuritySourceConfig, pk=request.POST.get("source_id"))
            test_result = {
                "source": config,
                "matched": source_matches_sample(config, request.POST.get("sender"), request.POST.get("subject"), request.POST.get("body")),
            }
        else:
            instance = get_object_or_404(SecuritySourceConfig, pk=request.POST.get("object_id")) if request.POST.get("object_id") else None
            old = snapshot_instance(instance) if instance else {}
            form = SecuritySourceConfigForm(request.POST, instance=instance)
            if form.is_valid():
                obj = form.save(commit=False)
                obj.updated_by = request.user
                obj.save()
                audit_model_form_changes(request.user, obj, old, snapshot_instance(obj), request=request)
                messages.success(request, "Configurazione sorgente salvata.")
                return redirect("security:admin_config_sources")
    return render(request, "security/admin_config/sources.html", {"objects": SecuritySourceConfig.objects.order_by("vendor", "name"), "form": form, "test_result": test_result})


@ensure_csrf_cookie
def admin_config_parsers(request):
    return _config_model_page(request, SecurityParserConfig, SecurityParserConfigForm, "security/admin_config/parsers.html", "admin_config_parsers", extra_context=_parser_stats())


@ensure_csrf_cookie
def admin_config_alert_rules(request):
    if not can_manage_security_config(request.user):
        return _security_config_denied(request)
    test_result = None
    if request.method == "POST" and request.POST.get("action") == "test-rule":
        rule = get_object_or_404(SecurityAlertRuleConfig, pk=request.POST.get("rule_id"))
        import json

        try:
            metrics = json.loads(request.POST.get("metrics_json") or "{}")
            test_result = {"rule": rule, "matched": test_alert_rule(rule, metrics), "metrics": metrics}
        except json.JSONDecodeError:
            test_result = {"error": "Campione metriche JSON non valido."}
    elif request.method == "POST":
        return _save_config_form(request, SecurityAlertRuleConfig, SecurityAlertRuleConfigForm, "admin_config_alert_rules")
    return render(request, "security/admin_config/alert_rules.html", {"objects": SecurityAlertRuleConfig.objects.order_by("source_type", "code"), "form": SecurityAlertRuleConfigForm(), "test_result": test_result})


@ensure_csrf_cookie
def admin_config_suppressions(request):
    return _config_model_page(request, SecurityAlertSuppressionRule, SecurityAlertSuppressionRuleForm, "security/admin_config/suppressions.html", "admin_config_suppressions")


@ensure_csrf_cookie
def admin_config_backups(request):
    extra = {"last_seen": {obj.pk: last_seen_backup_status(obj) for obj in BackupExpectedJobConfig.objects.all()}}
    return _config_model_page(request, BackupExpectedJobConfig, BackupExpectedJobConfigForm, "security/admin_config/backups.html", "admin_config_backups", extra_context=extra)


@ensure_csrf_cookie
def admin_config_notifications(request):
    if not can_manage_security_config(request.user):
        return _security_config_denied(request)
    if request.method == "POST":
        instance = get_object_or_404(SecurityNotificationChannel, pk=request.POST.get("object_id")) if request.POST.get("object_id") else None
        old = snapshot_instance(instance) if instance else {}
        form = SecurityNotificationChannelForm(request.POST, instance=instance)
        if form.is_valid():
            obj = form.save(commit=False)
            replacement = form.cleaned_data.get("replace_webhook_secret")
            if replacement:
                obj.webhook_url_secret_ref = replacement
            obj.updated_by = request.user
            obj.save()
            audit_model_form_changes(request.user, obj, old, snapshot_instance(obj), request=request, secret_fields={"webhook_url_secret_ref"})
            messages.success(request, "Canale notifica salvato.")
            return redirect("security:admin_config_notifications")
    return render(request, "security/admin_config/notifications.html", {"objects": SecurityNotificationChannel.objects.order_by("channel_type", "name"), "form": SecurityNotificationChannelForm()})


@ensure_csrf_cookie
def admin_config_ticketing(request):
    return _config_model_page(request, SecurityTicketConfig, SecurityTicketConfigForm, "security/admin_config/ticketing.html", "admin_config_ticketing")


@ensure_csrf_cookie
def admin_config_audit(request):
    if not can_manage_security_config(request.user):
        return _security_config_denied(request)
    return render(request, "security/admin_config/audit.html", {"objects": SecurityConfigurationAuditLog.objects.select_related("actor").order_by("-created_at")[:200]})


@ensure_csrf_cookie
def admin_diagnostics(request):
    if not can_manage_security_config(request.user):
        return _security_config_denied(request)
    match_input = None
    if request.method == "POST":
        match_input = {
            "sender": request.POST.get("sender", "")[:320],
            "subject": request.POST.get("subject", "")[:500],
            "body": request.POST.get("body", "")[:5000],
        }
    return render(request, "security/admin_diagnostics.html", build_diagnostics_context(match_input))


@ensure_csrf_cookie
def admin_docs(request):
    if not can_manage_security_config(request.user):
        return _security_config_denied(request)
    return render(request, "security/admin_docs.html", {"docs": SECURITY_CENTER_DOCS})


@ensure_csrf_cookie
def admin_addons(request):
    if not can_manage_security_config(request.user):
        return _security_config_denied(request)
    return render(request, "security/admin_addons.html", {"addons": get_addon_registry()})


@ensure_csrf_cookie
def admin_addon_detail(request, code):
    if not can_manage_security_config(request.user):
        return _security_config_denied(request)
    addon = get_addon_detail(code)
    if addon is None:
        raise Http404("Modulo sconosciuto.")
    return render(request, "security/admin_addon_detail.html", {"addon": addon})


def _config_model_page(request, model, form_class, template, redirect_name, extra_context=None):
    if not can_manage_security_config(request.user):
        return _security_config_denied(request)
    if request.method == "POST":
        return _save_config_form(request, model, form_class, redirect_name)
    context = {"objects": model.objects.all(), "form": form_class()}
    context.update(extra_context or {})
    return render(request, template, context)


def _save_config_form(request, model, form_class, redirect_name):
    instance = get_object_or_404(model, pk=request.POST.get("object_id")) if request.POST.get("object_id") else None
    old = snapshot_instance(instance) if instance else {}
    form = form_class(request.POST, instance=instance)
    if form.is_valid():
        obj = form.save(commit=False)
        if hasattr(obj, "updated_by"):
            obj.updated_by = request.user
        if hasattr(obj, "created_by") and not obj.pk:
            obj.created_by = request.user
        obj.save()
        audit_model_form_changes(request.user, obj, old, snapshot_instance(obj), request=request)
        if not old:
            audit_config_change(request.user, "create", obj, request=request)
        messages.success(request, "Configurazione salvata.")
    else:
        messages.error(request, "Configurazione non salvata. Controlla campi richiesti e valori JSON.")
    return redirect(f"security:{redirect_name}")


def _security_config_denied(request):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), login_url="/admin/login/")
    return HttpResponseForbidden("L'accesso alla configurazione sicurezza richiede staff o permesso esplicito.")


def _security_center_denied(request):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), login_url="/admin/login/")
    return HttpResponseForbidden("L'accesso a Security Center richiede staff o permesso di visualizzazione.")


def _config_card(title, url_name, enabled_count, warning_count, latest):
    status = "ok"
    if warning_count:
        status = "warning"
    if enabled_count == 0 and title not in {"Audit Log"}:
        status = "disabled"
    title_labels = {
        "General": "Generale",
        "Sources": "Sorgenti",
        "Parsers": "Parser",
        "Alert Rules": "Regole alert",
        "Suppression Rules": "Soppressioni",
        "Backup Monitoring": "Backup",
        "Notifications": "Notifiche",
        "Ticketing": "Ticketing",
        "Audit Log": "Registro audit",
    }
    status_labels = {"ok": "OK", "warning": "Attenzione", "disabled": "Disattivato"}
    return {
        "title": title_labels.get(title, title),
        "url_name": url_name,
        "url": reverse(f"security:{url_name}"),
        "enabled_count": enabled_count,
        "warning_count": warning_count,
        "last_updated": getattr(latest, "updated_at", None) or getattr(latest, "created_at", None),
        "status": status,
        "status_label": status_labels.get(status, status),
    }


def _parser_stats():
    stats = {}
    for report in SecurityReport.objects.values("parser_name").annotate(total=Count("id")):
        stats[report["parser_name"]] = {"reports_parsed": report["total"]}
    for parser in SecurityParserConfig.objects.all():
        data = stats.setdefault(parser.parser_name, {})
        successes = SecurityReport.objects.filter(parser_name=parser.parser_name, parse_status="parsed").order_by("-created_at")
        failures = SecurityReport.objects.filter(parser_name=parser.parser_name, parse_status="failed").order_by("-created_at")
        data.update(
            {
                "last_successful_parse": successes.first(),
                "last_failed_parse": failures.first(),
                "warning_count": SecurityReport.objects.filter(parser_name=parser.parser_name, parsed_payload__parse_warnings__isnull=False).count(),
                "error_count": failures.count(),
            }
        )
    return {"parser_stats": stats}


def _latest_pipeline_reports():
    reports = []
    for report in SecurityReport.objects.prefetch_related("metrics", "events").order_by("-created_at")[:5]:
        payload = report.parsed_payload or {}
        reports.append(
            {
                "parser_name": report.parser_name,
                "report_type": report.report_type,
                "period_start": payload.get("period_start"),
                "period_end": payload.get("period_end"),
                "report_date": payload.get("report_date"),
                "kpis": list(report.metrics.order_by("name").values("name", "value")[:12]),
                "records_count": len(payload.get("records", [])),
                "alert_candidates": payload.get("alerts_candidates", [])[:8],
                "parse_warnings": payload.get("parse_warnings", []),
            }
        )
    return reports


def _inbox_context(result=None):
    return {
        "inbox_result": result,
        "recent_reports": SecurityReport.objects.select_related("source").order_by("-created_at")[:10],
        "recent_mailbox_messages": SecurityMailboxMessage.objects.select_related("source").order_by("-received_at")[:10],
        "recent_source_files": SecuritySourceFile.objects.select_related("source").order_by("-uploaded_at")[:10],
        "source_configs": SecuritySourceConfig.objects.order_by("-enabled", "vendor", "name")[:30],
        "parser_configs": SecurityParserConfig.objects.order_by("-enabled", "priority", "parser_name")[:30],
        "allowed_extensions": sorted(INBOX_ALLOWED_EXTENSIONS),
        "max_upload_mb": INBOX_MAX_UPLOAD_BYTES // (1024 * 1024),
    }


def _handle_inbox_post(request):
    started_at = timezone.now()
    result = {
        "action": "inbox-ingest",
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": None,
        "status": "success",
        "mode": "paste",
        "source_detected": "",
        "parser_used": "",
        "confidence": "",
        "report_reference": "",
        "reports_parsed": 0,
        "metrics_created": 0,
        "events_created": 0,
        "alerts_created": 0,
        "evidence_created": 0,
        "tickets_changed": 0,
        "warnings": [],
        "errors": [],
        "preview": "",
    }

    uploaded = request.FILES.get("report_file")
    if uploaded:
        item = _ingest_inbox_file(uploaded, request.POST, result)
    else:
        item = _ingest_inbox_paste(request.POST, result)

    if item is None:
        result["status"] = "error"
        result["finished_at"] = timezone.now().isoformat(timespec="seconds")
        return result

    try:
        if isinstance(item, SecuritySourceFile):
            pipeline_result = process_source_file(item, dry_run=False)
        else:
            pipeline_result = process_mailbox_message(item, dry_run=False)

        result["parser_used"] = pipeline_result.get("parser_name", "")
        result["confidence"] = "matched" if pipeline_result.get("parser_matched") else "no-parser"
        result["reports_parsed"] = pipeline_result.get("reports_parsed", 0)
        result["metrics_created"] = pipeline_result.get("metrics_created", 0)
        result["events_created"] = pipeline_result.get("events_created", 0)
        result["alerts_created"] = pipeline_result.get("alerts_created", 0)
        result["evidence_created"] = pipeline_result.get("evidence_created", 0)
        result["tickets_changed"] = pipeline_result.get("tickets_changed", 0)
        result["warnings"].extend(pipeline_result.get("warnings", []))
        result["errors"].extend(pipeline_result.get("errors", []))

        if pipeline_result.get("status") == "error":
            result["status"] = "error"
        elif pipeline_result.get("status") == "skipped":
            result["status"] = "skipped"

    except Exception as exc:  # pragma: no cover - defensive UI reporting
        result["status"] = "error"
        result["errors"].append(str(exc))

    linked_reports = _reports_for_inbox_item(item)
    if linked_reports:
        report = linked_reports[0]
        result["report_reference"] = f"#{report.pk} {report.title}"
        result["source_detected"] = report.source.name
    elif not result["source_detected"]:
        result["source_detected"] = getattr(getattr(item, "source", None), "name", "") or "No source matched"

    result["finished_at"] = timezone.now().isoformat(timespec="seconds")
    return result


def _ingest_inbox_paste(data, result):
    sender = (data.get("sender") or "").strip()
    subject = (data.get("subject") or "Manual inbox sample").strip()[:255]
    body = data.get("body") or ""
    source_hint = (data.get("source_hint") or "").strip()
    content_type = (data.get("content_type") or "").strip()
    if not body.strip() and not subject.strip():
        result["errors"].append("Paste mode requires a subject or body.")
        return None

    source, source_config = _resolve_inbox_source(sender=sender, subject=subject, body=body, source_hint=source_hint, fallback_type=SourceType.EMAIL)
    result["source_detected"] = source_config.name if source_config else "No source matched"
    result["preview"] = _safe_preview(body or subject)
    message = ingest_mailbox_message(source, subject, body, sender=sender)
    message.raw_payload = {
        "inbox_mode": "paste",
        "content_type": content_type,
        "source_hint": source_hint,
    }
    message.save(update_fields=["raw_payload"])
    return message


def _ingest_inbox_file(uploaded, data, result):
    original_name = Path(uploaded.name or "upload").name
    extension = Path(original_name).suffix.lower()
    result["mode"] = "file"
    if extension not in INBOX_ALLOWED_EXTENSIONS:
        result["errors"].append(f"Unsupported file extension: {extension or '(none)'}.")
        return None
    if uploaded.size > INBOX_MAX_UPLOAD_BYTES:
        result["errors"].append("Uploaded file is too large. Maximum size is 10 MB.")
        return None

    raw = uploaded.read()
    content = raw.decode("utf-8", errors="replace")
    source_hint = (data.get("source_hint") or "").strip()
    source, source_config = _resolve_inbox_source(subject=original_name, body=content, source_hint=source_hint, fallback_type=_source_type_for_extension(extension))
    result["source_detected"] = source_config.name if source_config else "No source matched"
    result["preview"] = _safe_preview(content)
    source_file = ingest_source_file(source, original_name, content, file_type=_source_type_for_extension(extension))
    source_file.raw_payload = {
        "inbox_mode": "file",
        "extension": extension,
        "size": uploaded.size,
        "source_hint": source_hint,
    }
    source_file.save(update_fields=["raw_payload"])
    return source_file


def _resolve_inbox_source(sender="", subject="", body="", source_hint="", fallback_type=SourceType.MANUAL):
    source_config = _source_config_from_hint(source_hint) or _matching_source_config(sender, subject, body)
    if source_config:
        return get_or_create_source(source_config.name, source_config.vendor, fallback_type), source_config
    return get_or_create_source("Manual Inbox", "", fallback_type), None


def _source_config_from_hint(source_hint):
    if not source_hint:
        return None
    configs = SecuritySourceConfig.objects.filter(enabled=True)
    if source_hint.isdigit():
        match = configs.filter(pk=int(source_hint)).first()
        if match:
            return match
    hint = source_hint.lower()
    for config in configs:
        values = [config.name, config.source_type, config.vendor, config.parser_name]
        if any(hint in (value or "").lower() for value in values):
            return config
    return None


def _matching_source_config(sender, subject, body):
    for config in SecuritySourceConfig.objects.filter(enabled=True).order_by("name"):
        if source_matches_sample(config, sender=sender, subject=subject, body=body):
            return config
    return None


def _source_type_for_extension(extension):
    if extension == ".csv":
        return SourceType.CSV
    if extension == ".pdf":
        return SourceType.PDF
    return SourceType.MANUAL


def _safe_preview(value):
    preview = " ".join(str(value or "").split())
    return preview[:500]


def _reports_for_inbox_item(item):
    reports = SecurityReport.objects.select_related("source").order_by("-created_at")
    if isinstance(item, SecuritySourceFile):
        return list(reports.filter(source_file=item)[:5])
    return list(reports.filter(mailbox_message=item)[:5])


def _decorate_alerts(alerts):
    decorated = []
    for alert in alerts:
        alert.short_dedup_hash = alert.dedup_hash[:12] if alert.dedup_hash else ""
        alert.linked_ticket = alert.tickets.order_by("-updated_at").first()
        alert.last_seen_at = alert.event.occurred_at if alert.event_id else alert.updated_at
        decorated.append(alert)
    return decorated


def _decorate_defender_findings(findings):
    decorated = []
    active_ticket_statuses = [Status.NEW, Status.OPEN, Status.IN_PROGRESS]
    for finding in findings:
        finding.linked_alert = SecurityAlert.objects.filter(
            source=finding.source,
            dedup_hash=finding.dedup_hash,
        ).order_by("-updated_at").first()
        ticket = (
            SecurityRemediationTicket.objects.filter(
                source=finding.source,
                affected_product=finding.affected_product,
                status__in=active_ticket_statuses,
            )
            .order_by("-updated_at")
            .first()
        )
        if ticket and finding.cve not in (ticket.cve_ids or [ticket.cve]):
            ticket = None
        finding.linked_ticket = ticket
        finding.linked_evidence = ticket.evidence.order_by("-created_at").first() if ticket else None
        decorated.append(finding)
    return decorated


def _alert_lifecycle_context(alert):
    terminal_statuses = [Status.CLOSED, Status.FALSE_POSITIVE, Status.RESOLVED, Status.SUPPRESSED]
    active_statuses = [Status.NEW, Status.OPEN, Status.ACKNOWLEDGED, Status.IN_PROGRESS, Status.SNOOZED, Status.MUTED]
    is_terminal = alert.status in terminal_statuses
    is_active = alert.status in active_statuses
    return {
        "can_acknowledge": alert.status in [Status.NEW, Status.OPEN],
        "can_snooze": is_active and alert.status != Status.SNOOZED,
        "can_close": is_active,
        "can_mark_false_positive": is_active,
        "can_reopen": is_terminal,
        "can_act": is_active,
    }


def _parse_date(value):
    if not value:
        return None
    try:
        return timezone.datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _parse_snooze_until(value):
    if not value:
        return timezone.now() + timezone.timedelta(hours=24)
    try:
        parsed = timezone.datetime.fromisoformat(value)
    except ValueError:
        return timezone.now() + timezone.timedelta(hours=24)
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


SECURITY_CENTER_DOCS = [
    {"file": "00_START_HERE.md", "title": "Da qui", "summary": "Ambito MVP, checklist primo setup e primi 30 minuti."},
    {"file": "01_ARCHITECTURE.md", "title": "Architettura", "summary": "Motore core, parser, regole, evidenze, KPI, configurazione admin, diagnostica e moduli."},
    {"file": "02_ADMIN_GUIDE.md", "title": "Guida admin", "summary": "Sorgenti, parser, regole alert, soppressioni, backup, notifiche, ticketing e registro audit."},
    {"file": "03_ADDONS.md", "title": "Moduli", "summary": "Modello core rispetto ai moduli e architettura target dei moduli."},
    {"file": "04_WATCHGUARD_ADDON.md", "title": "Modulo WatchGuard", "summary": "Input WatchGuard supportati, metriche, regole, riduzione rumore e limiti."},
    {"file": "05_DEFENDER_ADDON.md", "title": "Modulo Microsoft Defender", "summary": "Email vulnerabilita, evidenze CVE, deduplica ticket e ricorrenze."},
    {"file": "06_BACKUP_ADDON.md", "title": "Modulo Backup/NAS", "summary": "Sorgente Synology Active Backup, job attesi, logica backup mancanti e salute backup."},
    {"file": "07_ALERT_LIFECYCLE.md", "title": "Ciclo vita alert", "summary": "Stati alert e differenze tra presa in carico, posticipo, silenziamento, soppressione, risoluzione, falso positivo e chiusura."},
    {"file": "08_CONFIGURATION_GUIDE.md", "title": "Guida configurazione", "summary": "Configurazione seed e impostazioni DB per sorgenti, parser, regole, soppressioni, backup, notifiche e ticketing."},
    {"file": "09_TROUBLESHOOTING.md", "title": "Risoluzione problemi", "summary": "Problemi comuni su parser, sorgenti, alert, ticket, backup, notifiche, seed e permessi."},
    {"file": "10_DEVELOPER_GUIDE.md", "title": "Guida sviluppo", "summary": "Purezza parser, struttura output, avvisi, test, configurazione seed, regole alert e visibilita dashboard."},
    {"file": "11_OPERATIONS_RUNBOOK.md", "title": "Runbook operativo", "summary": "Checklist operative giornaliere, settimanali e mensili."},
    {"file": "MAILBOX_INGESTION.md", "title": "Mailbox Ingestion", "summary": "Ingestion schedulata da mailbox, provider, deduplicazione, configurazione e troubleshooting."},
]


@ensure_csrf_cookie
def admin_mailbox_sources_list(request):
    if not can_view_security_center(request.user):
        return HttpResponseForbidden("Accesso negato")

    sources = SecurityMailboxSource.objects.all().order_by("-created_at")

    for source in sources:
        source.latest_run = source.ingestion_runs.order_by("-started_at").first()

    context = {
        "sources": sources,
        "page_title": "Sorgenti Mail",
    }
    return render(request, "security/admin_mailbox_sources_list.html", context)


@ensure_csrf_cookie
def admin_mailbox_source_detail(request, code):
    if not can_view_security_center(request.user):
        return HttpResponseForbidden("Accesso negato")

    source = get_object_or_404(SecurityMailboxSource, code=code)
    recent_runs = source.ingestion_runs.order_by("-started_at")[:10]
    recent_messages = SecurityMailboxMessage.objects.filter(
        source__name=source.name
    ).order_by("-received_at")[:20]

    context = {
        "source": source,
        "recent_runs": recent_runs,
        "recent_messages": recent_messages,
        "page_title": f"Sorgente Mail: {source.name}",
    }
    return render(request, "security/admin_mailbox_source_detail.html", context)

