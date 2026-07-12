import json
import re

from django.db.models import Q
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_time
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status as http_status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils.decorators import method_decorator



from .models import (
    SecurityAlert,
    SecurityAlertRuleConfig,
    SecurityAlertSuppressionRule,
    SecurityCenterSetting,
    SecurityMailboxIngestionRun,
    SecurityMailboxSource,
    SecurityParserConfig,
    SecuritySource,
    SecuritySourceConfig,
    SettingValueType,
    Severity,
    Status,
)
from .permissions import CanViewSecurityCenter, CanManageSecurityCenter
from .services.addon_registry import ACTIVE_ALERT_STATUSES, ADDONS
from .services.configuration import audit_config_change, can_manage_security_config, get_setting, set_setting
from .services.mailbox_ingestion import run_mailbox_ingestion
from .services.rule_simulation import simulate_alert_rule
from .parsers import parser_registry


class ConfigurationOverviewApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        sources = SecurityMailboxSource.objects.filter(enabled=True)
        sources_with_warnings = sources.filter(
            Q(last_error_at__isnull=False) | Q(last_success_at__isnull=True)
        ).count()

        rules = SecurityAlertRuleConfig.objects.all()
        active_rules = rules.filter(enabled=True).count()

        suppressions = SecurityAlertSuppressionRule.objects.filter(is_active=True).count()

        latest_run = SecurityMailboxIngestionRun.objects.order_by("-started_at").first()
        latest_status = latest_run.status if latest_run else None
        latest_at = latest_run.started_at.isoformat() if latest_run else None

        open_alerts = SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES).count()
        critical_open = SecurityAlert.objects.filter(
            status__in=ACTIVE_ALERT_STATUSES, severity=Severity.CRITICAL
        ).count()

        return Response({
            "monitored_sources_count": sources.count(),
            "active_sources_count": sources.count(),
            "sources_with_warnings_count": sources_with_warnings,
            "alert_rules_count": rules.count(),
            "active_alert_rules_count": active_rules,
            "notification_channels_count": 4,
            "active_notification_channels_count": 3,
            "active_suppressions_count": suppressions,
            "latest_ingestion_status": latest_status,
            "latest_ingestion_at": latest_at,
            "open_alerts_count": open_alerts,
            "critical_open_alerts_count": critical_open,
        })


class ConfigurationSourcesApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        sources = SecurityMailboxSource.objects.all().order_by("-last_run_at", "name")

        result = []
        for source in sources:
            latest_run = source.ingestion_runs.order_by("-started_at").first()

            category = _detect_category(source)
            status = _detect_status(source, latest_run)
            origin = _map_origin(source.source_type)
            parser_names = _detect_parsers(source)
            warnings = _collect_warnings(source, latest_run)

            mailbox_safe = _mask_email(source.mailbox_address) if source.mailbox_address else None

            dto = {
                "id": source.id,
                "code": source.code,
                "name": source.name,
                "source_type": source.source_type,
                "category": category,
                "status": status,
                "origin": origin,
                "parser_names": parser_names,
                "mailbox_address": mailbox_safe,
                "last_import_at": source.last_run_at.isoformat() if source.last_run_at else None,
                "last_success_at": source.last_success_at.isoformat() if source.last_success_at else None,
                "last_error_at": source.last_error_at.isoformat() if source.last_error_at else None,
                "last_error_message": _truncate_safe(source.last_error_message, 200),
                "latest_run": _build_run_counters(latest_run) if latest_run else None,
                "warning_messages": warnings,
                "links": {
                    "configuration_url": f"/configuration?tab=sources&source={source.code}",
                    "inbox_url": "/inbox",
                    "reports_url": "/reports",
                    "diagnostics_url": "/configuration?tab=test",
                },
            }
            result.append(dto)

        for source_config in SecuritySourceConfig.objects.all().order_by("vendor", "name"):
            result.append(_build_source_config_studio_dto(source_config))

        return Response(result)


class ConfigurationRulesApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanManageSecurityCenter()]
        return super().get_permissions()

    def get(self, request):
        db_rules = SecurityAlertRuleConfig.objects.all().order_by("-enabled", "name")

        result = []
        for rule in db_rules:
            dto = {
                "code": rule.code,
                "title": rule.name,
                "group": rule.source_type or "general",
                "enabled": rule.enabled,
                "severity": rule.severity,
                "when_summary": _build_when_summary(rule),
                "then_summary": _build_then_summary(rule),
                "dedup_summary": f"{rule.dedup_window_minutes} min",
                "aggregation_summary": rule.metric_name or "N/A",
                "last_match_at": rule.last_triggered_at.isoformat() if rule.last_triggered_at else None,
                "matches_count": rule.trigger_count,
                "generated_alerts_count": None,
                "status": "active" if rule.enabled else "disabled",
                "warning_messages": [],
            }
            result.append(dto)

        conceptual_rules = _get_conceptual_rules()
        result.extend(conceptual_rules)

        return Response(result)

    def post(self, request):
        data = request.data

        if _is_structured_rule_payload(data):
            return _create_alert_rule_config(request)

        rule_name = data.get("rule_name", "").strip()
        condition = data.get("condition", "").strip()
        severity = data.get("severity", "medium").strip().lower()
        description = data.get("description", "").strip()
        recommended_actions = data.get("recommended_actions", [])
        rationale = data.get("rationale", "").strip()

        if not rule_name:
            return Response({"error": "rule_name required"}, status=http_status.HTTP_400_BAD_REQUEST)
        if not condition:
            return Response({"error": "condition required"}, status=http_status.HTTP_400_BAD_REQUEST)

        valid_severities = ["critical", "high", "medium", "low", "info"]
        if severity not in valid_severities:
            return Response(
                {"error": f"severity must be one of: {', '.join(valid_severities)}"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        code = _generate_rule_code(rule_name)
        if SecurityAlertRuleConfig.objects.filter(code=code).exists():
            return Response({"error": "rule with this code already exists"}, status=http_status.HTTP_400_BAD_REQUEST)

        rule = SecurityAlertRuleConfig.objects.create(
            code=code,
            name=rule_name,
            enabled=True,
            source_type="ai_generated",
            metric_name="ai_condition",
            condition_operator="contains",
            threshold_value=condition,
            severity=severity,
            cooldown_minutes=60,
            dedup_window_minutes=1440,
            auto_create_ticket=False,
            auto_create_evidence_container=True,
            description=description,
        )

        return Response({
            "success": True,
            "rule": {
                "code": rule.code,
                "title": rule.name,
                "enabled": rule.enabled,
                "severity": rule.severity,
                "when_summary": _build_when_summary(rule),
                "then_summary": _build_then_summary(rule),
                "dedup_summary": f"{rule.dedup_window_minutes} min",
                "aggregation_summary": rule.metric_name or "N/A",
                "last_match_at": rule.last_triggered_at.isoformat() if rule.last_triggered_at else None,
                "matches_count": rule.trigger_count,
                "status": "active" if rule.enabled else "disabled",
                "warning_messages": [],
            }
        }, status=http_status.HTTP_201_CREATED)


class ConfigurationNotificationsApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        channels = [
            {
                "code": "dashboard",
                "name": "Dashboard Security Center",
                "enabled": True,
                "configured": True,
                "status": "active",
                "destination_summary": "Inbox interno",
                "last_delivery_at": None,
                "last_error_at": None,
                "last_error_message": None,
                "warning_messages": [],
            },
            {
                "code": "email",
                "name": "Email operativa",
                "enabled": True,
                "configured": True,
                "status": "active",
                "destination_summary": "sec***@example.local",
                "last_delivery_at": None,
                "last_error_at": None,
                "last_error_message": None,
                "warning_messages": [],
            },
            {
                "code": "teams",
                "name": "Microsoft Teams",
                "enabled": False,
                "configured": False,
                "status": "not_configured",
                "destination_summary": "Non configurato",
                "last_delivery_at": None,
                "last_error_at": None,
                "last_error_message": None,
                "warning_messages": ["Webhook non configurato"],
            },
            {
                "code": "ticket",
                "name": "Sistema ticket operativo",
                "enabled": True,
                "configured": True,
                "status": "active",
                "destination_summary": "Coda Security",
                "last_delivery_at": None,
                "last_error_at": None,
                "last_error_message": None,
                "warning_messages": [],
            },
        ]
        return Response(channels)


class ConfigurationSuppressionsApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanManageSecurityCenter()]
        return super().get_permissions()

    def get(self, request):
        suppressions = SecurityAlertSuppressionRule.objects.filter(is_active=True).order_by("-created_at")

        result = []
        for supp in suppressions:
            now = timezone.now()
            is_expired = supp.expires_at and supp.expires_at < now

            dto = {
                "id": supp.id,
                "code": f"supp-{supp.id}",
                "type": _map_suppression_type(supp),
                "title": supp.name,
                "active": supp.is_active and not is_expired,
                "reason": supp.reason or "N/A",
                "owner": _safe_owner(supp),
                "scope_summary": _build_scope_summary(supp),
                "expires_at": supp.expires_at.isoformat() if supp.expires_at else None,
                "matches_suppressed_count": supp.hit_count,
                "created_at": supp.created_at.isoformat() if supp.created_at else None,
                "updated_at": supp.updated_at.isoformat() if supp.updated_at else None,
                "status": "expired" if is_expired else ("active" if supp.is_active else "disabled"),
            }
            result.append(dto)

        return Response(result)

    def post(self, request):
        return _create_suppression_config(request)


@method_decorator(ensure_csrf_cookie, name="dispatch")
class ConfigurationTestApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        return Response({
            "status": "ok",
            "csrfToken": get_token(request),
        })

    def post(self, request):
        source_type = request.data.get("source_type", "")
        parser_code = request.data.get("parser_code", "")
        sample_text = request.data.get("sample_text", "")
        filename = request.data.get("filename", "")

        if not sample_text:
            return Response({"error": "sample_text required"}, status=400)

        detected_parser = None
        confidence = 0.0

        if parser_code:
            if parser_code in parser_registry:
                detected_parser = parser_code
                confidence = 1.0
        else:
            detected_parser, confidence = _detect_parser_from_sample(sample_text, filename)

        metrics_preview = _simulate_metrics(sample_text, detected_parser)
        findings_preview = _simulate_findings(sample_text, detected_parser)

        would_alert = "critical" in sample_text.lower() or "cvss" in sample_text.lower()
        would_evidence = would_alert
        would_ticket = would_alert and "cve" in sample_text.lower()

        warnings = []
        errors = []

        if not detected_parser:
            warnings.append("Nessun parser rilevato automaticamente")
        if confidence < 0.5:
            warnings.append(f"Confidenza parser bassa: {confidence:.0%}")

        return Response({
            "parser_detected": detected_parser or "unknown",
            "parser_name": detected_parser or "N/A",
            "confidence": confidence,
            "metrics_preview": metrics_preview,
            "findings_preview": findings_preview,
            "would_generate_alert": would_alert,
            "would_create_evidence_container": would_evidence,
            "would_create_ticket": would_ticket,
            "warnings": warnings,
            "errors": errors,
        })


def _detect_category(source):
    name_lower = source.name.lower()
    code_lower = source.code.lower()

    for addon in ADDONS:
        for token in addon.source_tokens:
            if token in name_lower or token in code_lower:
                return addon.code

    return "custom"


def _detect_status(source, latest_run):
    if not source.enabled:
        return "disabled"
    if source.last_error_at:
        return "error"
    if not source.last_success_at:
        return "not_configured"
    if latest_run and latest_run.status in ["failed", "partial"]:
        return "warning"
    return "active"


def _map_origin(source_type):
    mapping = {
        "manual": "manual",
        "mock": "manual",
        "graph": "graph",
        "imap": "imap_future",
    }
    return mapping.get(source_type, "mailbox")


def _detect_parsers(source):
    name_lower = source.name.lower()
    code_lower = source.code.lower()

    parsers = []
    for addon in ADDONS:
        for token in addon.source_tokens:
            if token in name_lower or token in code_lower:
                parsers.extend(addon.parser_names)
                break

    return list(set(parsers)) if parsers else ["unknown"]


def _collect_warnings(source, latest_run):
    warnings = []
    if source.last_error_message:
        warnings.append(_truncate_safe(source.last_error_message, 100))
    if latest_run and latest_run.status == "failed":
        warnings.append("Ultima esecuzione fallita")
    if source.source_type == "graph":
        warnings.append("Verifica prerequisiti Microsoft Graph lato server prima dell'importazione live")
    if not source.last_success_at:
        warnings.append("Nessuna importazione riuscita")
    return warnings


def _mask_email(email):
    if not email or "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 3:
        masked_local = local[0] + "***"
    else:
        masked_local = local[:3] + "***"
    return f"{masked_local}@{domain}"


def _truncate_safe(text, max_len):
    if not text:
        return ""
    text = str(text)
    return text[:max_len] + "..." if len(text) > max_len else text


def _build_run_counters(run):
    return {
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "imported": run.imported_messages_count,
        "skipped": run.skipped_messages_count,
        "duplicates": run.duplicate_messages_count,
        "files": run.imported_files_count,
        "processed": run.processed_items_count,
        "alerts": run.generated_alerts_count,
        "error_message": _truncate_safe(run.error_message, 200),
    }


def _build_run_response(run):
    return {
        "id": run.id,
        "source_code": run.source.code,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "imported_messages_count": run.imported_messages_count,
        "skipped_messages_count": run.skipped_messages_count,
        "duplicate_messages_count": run.duplicate_messages_count,
        "imported_files_count": run.imported_files_count,
        "processed_items_count": run.processed_items_count,
        "generated_alerts_count": run.generated_alerts_count,
        "error_message": _truncate_safe(run.error_message, 200),
        "details": run.details or {},
    }


def _build_mailbox_ingestion_service_status(user=None):
    expected_interval_seconds = 120
    stale_after_seconds = expected_interval_seconds * 3
    now = timezone.now()
    sources = list(SecurityMailboxSource.objects.all().order_by("-enabled", "name"))
    enabled_sources = [source for source in sources if source.enabled]
    latest_run = SecurityMailboxIngestionRun.objects.select_related("source").order_by("-started_at").first()
    recent_runs = list(SecurityMailboxIngestionRun.objects.select_related("source").order_by("-started_at")[:12])
    source_items = [_build_service_source_status(source, now, stale_after_seconds) for source in sources]

    failed_sources = [item for item in source_items if item["health"] == "error"]
    warning_sources = [item for item in source_items if item["health"] == "warning"]
    polling_recent = False
    if latest_run and latest_run.started_at:
        polling_recent = (now - latest_run.started_at).total_seconds() <= stale_after_seconds

    if not enabled_sources:
        service_status = "not_configured"
        status_label = "Nessuna sorgente abilitata"
    elif latest_run and latest_run.status == "running":
        service_status = "running"
        status_label = "In esecuzione"
    elif failed_sources:
        service_status = "error"
        status_label = "Errori da verificare"
    elif warning_sources or not polling_recent:
        service_status = "warning"
        status_label = "Da monitorare"
    else:
        service_status = "active"
        status_label = "Operativo"

    return {
        "name": "Mailbox / Graph ingestion",
        "status": service_status,
        "status_label": status_label,
        "expected_interval_seconds": expected_interval_seconds,
        "stale_after_seconds": stale_after_seconds,
        "polling_observed": polling_recent,
        "polling_command": "python manage.py ingest_security_mailbox --loop --interval 120",
        "can_manage": can_manage_security_config(user),
        "totals": {
            "sources": len(sources),
            "enabled_sources": len(enabled_sources),
            "graph_sources": len([source for source in sources if source.source_type == "graph"]),
            "sources_with_errors": len(failed_sources),
            "sources_with_warnings": len(warning_sources),
            "recent_runs": len(recent_runs),
        },
        "latest_run": _build_service_run_status(latest_run) if latest_run else None,
        "sources": source_items,
        "recent_runs": [_build_service_run_status(run) for run in recent_runs],
    }


def _build_service_source_status(source, now, stale_after_seconds):
    latest_run = source.ingestion_runs.order_by("-started_at").first()
    seconds_since_run = None
    if latest_run and latest_run.started_at:
        seconds_since_run = int((now - latest_run.started_at).total_seconds())

    if not source.enabled:
        health = "disabled"
        health_label = "Disabilitata"
    elif source.last_error_message or (latest_run and latest_run.status == "failed"):
        health = "error"
        health_label = "Errore"
    elif not latest_run:
        health = "warning"
        health_label = "Mai eseguita"
    elif seconds_since_run is not None and seconds_since_run > stale_after_seconds:
        health = "warning"
        health_label = "Non recente"
    elif latest_run.status in ["partial", "pending", "running"]:
        health = "warning"
        health_label = latest_run.get_status_display()
    else:
        health = "active"
        health_label = "Operativa"

    return {
        "code": source.code,
        "name": source.name,
        "enabled": source.enabled,
        "source_type": source.source_type,
        "source_type_label": source.get_source_type_display(),
        "category": _detect_category(source),
        "mailbox_address": _mask_email(source.mailbox_address) if source.mailbox_address else None,
        "health": health,
        "health_label": health_label,
        "last_run_at": source.last_run_at.isoformat() if source.last_run_at else None,
        "last_success_at": source.last_success_at.isoformat() if source.last_success_at else None,
        "last_error_at": source.last_error_at.isoformat() if source.last_error_at else None,
        "last_error_message": _truncate_safe(source.last_error_message, 200),
        "seconds_since_run": seconds_since_run,
        "latest_run": _build_service_run_status(latest_run) if latest_run else None,
    }


def _build_service_run_status(run):
    if not run:
        return None
    return {
        "id": run.id,
        "source_code": run.source.code,
        "source_name": run.source.name,
        "status": run.status,
        "status_label": run.get_status_display(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "imported": run.imported_messages_count,
        "skipped": run.skipped_messages_count,
        "duplicates": run.duplicate_messages_count,
        "files": run.imported_files_count,
        "processed": run.processed_items_count,
        "alerts": run.generated_alerts_count,
        "error_message": _truncate_safe(run.error_message, 200),
    }


def _build_graph_settings_response(user=None):
    tenant_setting = SecurityCenterSetting.objects.filter(key="GRAPH_TENANT_ID").first()
    client_setting = SecurityCenterSetting.objects.filter(key="GRAPH_CLIENT_ID").first()
    secret_setting = SecurityCenterSetting.objects.filter(key="GRAPH_CLIENT_SECRET").first()
    folder = get_setting("GRAPH_MAIL_FOLDER", "Inbox") or "Inbox"
    updated_values = [setting.updated_at for setting in [tenant_setting, client_setting, secret_setting] if setting]
    return {
        "tenant_configured": bool(tenant_setting and tenant_setting.value),
        "client_configured": bool(client_setting and client_setting.value),
        "secret_configured": bool(secret_setting and secret_setting.value),
        "mail_folder": str(folder),
        "can_save": can_manage_security_config(user),
        "configured": bool(
            tenant_setting
            and tenant_setting.value
            and client_setting
            and client_setting.value
            and secret_setting
            and secret_setting.value
        ),
        "updated_at": max(updated_values).isoformat() if updated_values else None,
    }


def _build_when_summary(rule):
    parts = []
    if rule.metric_name:
        parts.append(rule.metric_name)
    if rule.condition_operator:
        parts.append(rule.condition_operator)
    if rule.threshold_value:
        parts.append(rule.threshold_value)
    return " ".join(parts) if parts else "N/A"


def _build_then_summary(rule):
    actions = []
    actions.append(f"Alert {rule.severity}")
    if rule.auto_create_evidence_container:
        actions.append("Evidence")
    if rule.auto_create_ticket:
        actions.append("Ticket")
    return " + ".join(actions)


def _get_conceptual_rules():
    return [
        {
            "code": "malware_detection_planned",
            "title": "Rilevamento Malware / PUP",
            "group": "watchguard",
            "enabled": False,
            "severity": "high",
            "when_summary": "Tipo = Malware o PUP e stato != Quarantined",
            "then_summary": "Alert High + Evidence",
            "dedup_summary": "Hash + hostname",
            "aggregation_summary": "Per malware family",
            "last_match_at": None,
            "matches_count": 0,
            "generated_alerts_count": 0,
            "status": "warning",
            "warning_messages": ["Regola pianificata, non ancora implementata"],
        },
        {
            "code": "vpn_anomaly_planned",
            "title": "Accesso VPN anomalo",
            "group": "watchguard",
            "enabled": False,
            "severity": "medium",
            "when_summary": "Accesso VPN da IP non noto o paese non autorizzato",
            "then_summary": "Alert Medium + Evidence",
            "dedup_summary": "Utente + IP + timestamp",
            "aggregation_summary": "Per utente",
            "last_match_at": None,
            "matches_count": 0,
            "generated_alerts_count": 0,
            "status": "warning",
            "warning_messages": ["Regola pianificata, non ancora implementata"],
        },
    ]


def _map_suppression_type(supp):
    if supp.expires_at:
        return "snooze"
    if "false" in supp.reason.lower() or "positiv" in supp.reason.lower():
        return "false_positive"
    return "suppression_rule"


def _safe_owner(supp):
    if supp.created_by:
        return supp.created_by.email or supp.created_by.username
    return "system"


def _build_scope_summary(supp):
    parts = []
    if supp.event_type:
        parts.append(f"event_type={supp.event_type}")
    if supp.severity:
        parts.append(f"severity={supp.severity}")
    if supp.scope_type:
        parts.append(f"scope={supp.scope_type}")
    return ", ".join(parts) if parts else "Tutti gli eventi"


def _detect_parser_from_sample(text, filename):
    text_lower = text.lower()

    if "watchguard" in text_lower or "epdr" in text_lower:
        return "watchguard_report_parser", 0.8
    if "defender" in text_lower or "microsoft" in text_lower:
        return "microsoft_defender_vulnerability_notification_email_parser", 0.7
    if "synology" in text_lower or "backup" in text_lower:
        return "synology_active_backup_email_parser", 0.6

    return None, 0.0


def _simulate_metrics(text, parser):
    if not parser:
        return []

    return [
        {"name": "events_count", "value": 42},
        {"name": "severity_high", "value": 3},
        {"name": "severity_critical", "value": 1},
    ]


def _simulate_findings(text, parser):
    if not parser:
        return []

    return [
        {"type": "vulnerability", "count": 2},
        {"type": "malware", "count": 0},
    ]


class ConfigurationSourcePresetsApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        presets = [
            {
                "preset_code": "watchguard_epdr",
                "title": "WatchGuard EPDR Executive Report",
                "description": "Report esecutivo settimanale WatchGuard EPDR con riepilogo minacce e stato endpoint",
                "module": "watchguard",
                "recommended_origin": "mailbox",
                "default_name": "WatchGuard EPDR Executive Report",
                "code_prefix": "watchguard-epdr",
                "source_type": "manual",
                "sender_allowlist_text": "noreply@watchguard.com\nsupport@watchguard.com",
                "subject_include_text": "EPDR Executive Report\nExecutive Report",
                "subject_exclude_text": "",
                "body_include_text": "",
                "attachment_extensions": "pdf",
                "max_messages_per_run": 50,
                "mark_as_read_after_import": False,
                "process_attachments": True,
                "process_email_body": False,
                "parser_hints": ["watchguard_epdr_parser"],
                "warning_messages": [],
            },
            {
                "preset_code": "watchguard_threatsync",
                "title": "WatchGuard ThreatSync Summary",
                "description": "Report ThreatSync con riepilogo incidenti e minacce rilevate",
                "module": "watchguard",
                "recommended_origin": "mailbox",
                "default_name": "WatchGuard ThreatSync Summary",
                "code_prefix": "watchguard-threatsync",
                "source_type": "manual",
                "sender_allowlist_text": "noreply@watchguard.com",
                "subject_include_text": "ThreatSync\nThreat Sync",
                "subject_exclude_text": "",
                "body_include_text": "",
                "attachment_extensions": "pdf,html",
                "max_messages_per_run": 50,
                "mark_as_read_after_import": False,
                "process_attachments": True,
                "process_email_body": True,
                "parser_hints": ["watchguard_threatsync_parser"],
                "warning_messages": [],
            },
            {
                "preset_code": "watchguard_dimension",
                "title": "WatchGuard Dimension / Firebox Report",
                "description": "Report firewall WatchGuard Dimension con statistiche traffico e eventi sicurezza",
                "module": "watchguard",
                "recommended_origin": "mailbox",
                "default_name": "WatchGuard Dimension Report",
                "code_prefix": "watchguard-dimension",
                "source_type": "manual",
                "sender_allowlist_text": "noreply@watchguard.com",
                "subject_include_text": "Dimension\nFirebox",
                "subject_exclude_text": "",
                "body_include_text": "",
                "attachment_extensions": "pdf",
                "max_messages_per_run": 50,
                "mark_as_read_after_import": False,
                "process_attachments": True,
                "process_email_body": False,
                "parser_hints": ["watchguard_dimension_parser"],
                "warning_messages": [],
            },
            {
                "preset_code": "defender_vulnerability",
                "title": "Microsoft Defender Vulnerability Notification",
                "description": "Notifiche vulnerabilità Microsoft Defender con CVE e dispositivi esposti",
                "module": "defender",
                "recommended_origin": "mailbox",
                "default_name": "Microsoft Defender Vulnerability",
                "code_prefix": "defender-vuln",
                "source_type": "manual",
                "sender_allowlist_text": "no-reply@microsoft.com\nalerts@microsoft.com",
                "subject_include_text": "vulnerability\nCVE-",
                "subject_exclude_text": "",
                "body_include_text": "Microsoft Defender\nvulnerability",
                "attachment_extensions": "",
                "max_messages_per_run": 100,
                "mark_as_read_after_import": True,
                "process_attachments": False,
                "process_email_body": True,
                "parser_hints": ["microsoft_defender_vulnerability_notification_email_parser"],
                "warning_messages": [],
            },
            {
                "preset_code": "synology_backup",
                "title": "NAS / Synology Active Backup",
                "description": "Report backup Synology Active Backup con stato job e spazio utilizzato",
                "module": "backup",
                "recommended_origin": "mailbox",
                "default_name": "Synology Active Backup",
                "code_prefix": "synology-backup",
                "source_type": "manual",
                "sender_allowlist_text": "",
                "subject_include_text": "Active Backup\nbackup",
                "subject_exclude_text": "",
                "body_include_text": "Synology\nActive Backup",
                "attachment_extensions": "",
                "max_messages_per_run": 50,
                "mark_as_read_after_import": False,
                "process_attachments": False,
                "process_email_body": True,
                "parser_hints": ["synology_active_backup_email_parser"],
                "warning_messages": [],
            },
            {
                "preset_code": "custom",
                "title": "Sorgente custom",
                "description": "Sorgente personalizzata per report non standard",
                "module": "custom",
                "recommended_origin": "manual",
                "default_name": "Sorgente Custom",
                "code_prefix": "custom",
                "source_type": "manual",
                "sender_allowlist_text": "",
                "subject_include_text": "",
                "subject_exclude_text": "",
                "body_include_text": "",
                "attachment_extensions": "",
                "max_messages_per_run": 50,
                "mark_as_read_after_import": False,
                "process_attachments": True,
                "process_email_body": True,
                "parser_hints": [],
                "warning_messages": ["Richiede configurazione manuale parser"],
            },
        ]
        return Response(presets)


class ConfigurationSourceCreateApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get_permissions(self):
        if self.request.method == "POST" and _is_source_config_payload(self.request.data or {}):
            return [CanManageSecurityCenter()]
        return super().get_permissions()

    def post(self, request):
        data = request.data

        if _is_source_config_payload(data):
            return _create_source_config(request)

        name = data.get("name", "").strip()
        code = data.get("code", "").strip()
        source_type = data.get("source_type", "manual")

        if not name:
            return Response({"error": "name required"}, status=http_status.HTTP_400_BAD_REQUEST)
        if not code:
            return Response({"error": "code required"}, status=http_status.HTTP_400_BAD_REQUEST)

        if not _is_valid_code(code):
            return Response(
                {"error": "code must be slug-like (lowercase, alphanumeric, hyphens only)"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        if SecurityMailboxSource.objects.filter(code=code).exists():
            return Response({"error": "code already exists"}, status=http_status.HTTP_400_BAD_REQUEST)

        if SecurityMailboxSource.objects.filter(name=name).exists():
            return Response({"error": "name already exists"}, status=http_status.HTTP_400_BAD_REQUEST)

        allowed_source_types = ["manual", "graph", "imap"]
        if source_type not in allowed_source_types:
            return Response(
                {"error": f"source_type must be one of: {', '.join(allowed_source_types)}"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        max_messages = data.get("max_messages_per_run", 50)
        if not isinstance(max_messages, int) or max_messages < 1 or max_messages > 500:
            return Response(
                {"error": "max_messages_per_run must be between 1 and 500"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        if _contains_secret_like_field(data):
            return Response(
                {"error": "suspicious secret-like field detected, rejected for safety"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        attachment_ext = data.get("attachment_extensions", "").strip()
        normalized_ext = _normalize_extensions(attachment_ext)

        source = SecurityMailboxSource.objects.create(
            name=name,
            code=code,
            enabled=data.get("enabled", True),
            source_type=source_type,
            mailbox_address=data.get("mailbox_address", "").strip(),
            description=data.get("description", "").strip(),
            sender_allowlist_text=data.get("sender_allowlist_text", "").strip(),
            subject_include_text=data.get("subject_include_text", "").strip(),
            subject_exclude_text=data.get("subject_exclude_text", "").strip(),
            body_include_text=data.get("body_include_text", "").strip(),
            attachment_extensions=normalized_ext,
            max_messages_per_run=max_messages,
            mark_as_read_after_import=data.get("mark_as_read_after_import", False),
            process_attachments=data.get("process_attachments", True),
            process_email_body=data.get("process_email_body", True),
        )

        return Response(_build_source_dto(source), status=http_status.HTTP_201_CREATED)


class ConfigurationSourceUpdateApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def patch(self, request, code):
        try:
            source = SecurityMailboxSource.objects.get(code=code)
        except SecurityMailboxSource.DoesNotExist:
            return Response({"error": "source not found"}, status=http_status.HTTP_404_NOT_FOUND)

        data = request.data

        if _contains_secret_like_field(data):
            return Response(
                {"error": "suspicious secret-like field detected, rejected for safety"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        if "name" in data:
            new_name = data["name"].strip()
            if new_name and new_name != source.name:
                if SecurityMailboxSource.objects.filter(name=new_name).exists():
                    return Response({"error": "name already exists"}, status=http_status.HTTP_400_BAD_REQUEST)
                source.name = new_name

        if "enabled" in data:
            source.enabled = bool(data["enabled"])

        if "source_type" in data:
            allowed_source_types = ["manual", "graph", "imap"]
            if data["source_type"] not in allowed_source_types:
                return Response(
                    {"error": f"source_type must be one of: {', '.join(allowed_source_types)}"},
                    status=http_status.HTTP_400_BAD_REQUEST,
                )
            source.source_type = data["source_type"]

        if "mailbox_address" in data:
            source.mailbox_address = data["mailbox_address"].strip()

        if "description" in data:
            source.description = data["description"].strip()

        if "sender_allowlist_text" in data:
            source.sender_allowlist_text = data["sender_allowlist_text"].strip()

        if "subject_include_text" in data:
            source.subject_include_text = data["subject_include_text"].strip()

        if "subject_exclude_text" in data:
            source.subject_exclude_text = data["subject_exclude_text"].strip()

        if "body_include_text" in data:
            source.body_include_text = data["body_include_text"].strip()

        if "attachment_extensions" in data:
            source.attachment_extensions = _normalize_extensions(data["attachment_extensions"])

        if "max_messages_per_run" in data:
            max_messages = data["max_messages_per_run"]
            if not isinstance(max_messages, int) or max_messages < 1 or max_messages > 500:
                return Response(
                    {"error": "max_messages_per_run must be between 1 and 500"},
                    status=http_status.HTTP_400_BAD_REQUEST,
                )
            source.max_messages_per_run = max_messages

        if "mark_as_read_after_import" in data:
            source.mark_as_read_after_import = bool(data["mark_as_read_after_import"])

        if "process_attachments" in data:
            source.process_attachments = bool(data["process_attachments"])

        if "process_email_body" in data:
            source.process_email_body = bool(data["process_email_body"])

        source.save()

        return Response(_build_source_dto(source))


class ConfigurationSourceToggleApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def post(self, request, code):
        try:
            source = SecurityMailboxSource.objects.get(code=code)
        except SecurityMailboxSource.DoesNotExist:
            return Response({"error": "source not found"}, status=http_status.HTTP_404_NOT_FOUND)

        source.enabled = not source.enabled
        source.save()

        return Response({"enabled": source.enabled})


class ConfigurationSourceIngestApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def post(self, request, code):
        try:
            source = SecurityMailboxSource.objects.get(code=code)
        except SecurityMailboxSource.DoesNotExist:
            return Response({"error": "source not found"}, status=http_status.HTTP_404_NOT_FOUND)

        if not source.enabled:
            return Response({"error": "source disabled"}, status=http_status.HTTP_400_BAD_REQUEST)

        limit = request.data.get("limit")
        if limit is not None:
            if not isinstance(limit, int) or limit < 1 or limit > 500:
                return Response(
                    {"error": "limit must be between 1 and 500"},
                    status=http_status.HTTP_400_BAD_REQUEST,
                )

        process_pipeline = bool(request.data.get("process_pipeline", True))
        force_reprocess = bool(request.data.get("force_reprocess", False))

        run = run_mailbox_ingestion(
            source,
            limit=limit,
            dry_run=False,
            process_pipeline=process_pipeline,
            force_reprocess=force_reprocess,
        )

        if run is None:
            return Response({"error": "source disabled"}, status=http_status.HTTP_400_BAD_REQUEST)

        return Response(_build_run_response(run), status=http_status.HTTP_200_OK)


class MailboxIngestionServiceStatusApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        return Response(_build_mailbox_ingestion_service_status(request.user))


class MailboxIngestionServiceRunApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def post(self, request):
        data = request.data or {}
        source_code = str(data.get("source_code", "") or "").strip()
        limit = data.get("limit")
        if limit is not None:
            if not isinstance(limit, int) or limit < 1 or limit > 500:
                return Response({"error": "limit must be between 1 and 500"}, status=http_status.HTTP_400_BAD_REQUEST)

        if source_code:
            try:
                sources = [SecurityMailboxSource.objects.get(code=source_code)]
            except SecurityMailboxSource.DoesNotExist:
                return Response({"error": "source not found"}, status=http_status.HTTP_404_NOT_FOUND)
        else:
            sources = list(SecurityMailboxSource.objects.filter(enabled=True).order_by("name"))

        if not sources:
            return Response({"error": "no enabled sources found"}, status=http_status.HTTP_400_BAD_REQUEST)

        results = []
        for source in sources:
            if not source.enabled:
                results.append({"source_code": source.code, "status": "skipped", "error": "source disabled"})
                continue
            run = run_mailbox_ingestion(source, limit=limit, dry_run=False, process_pipeline=True, force_reprocess=False)
            if run:
                results.append(_build_run_response(run))

        return Response(
            {
                "runs": results,
                "service": _build_mailbox_ingestion_service_status(request.user),
            },
            status=http_status.HTTP_200_OK,
        )


class GraphSettingsApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        get_token(request)
        return Response(_build_graph_settings_response(request.user))

    def post(self, request):
        if not can_manage_security_config(request.user):
            return Response(
                {"error": "Permesso gestione configurazione richiesto per salvare Microsoft Graph."},
                status=http_status.HTTP_403_FORBIDDEN,
            )

        data = request.data or {}
        tenant_id = str(data.get("tenant_id", "") or "").strip()
        client_id = str(data.get("client_id", "") or "").strip()
        client_secret = str(data.get("client_secret", "") or "").strip()
        mail_folder = str(data.get("mail_folder", "") or "").strip() or "Inbox"

        existing_tenant = str(get_setting("GRAPH_TENANT_ID", "") or "").strip()
        existing_client = str(get_setting("GRAPH_CLIENT_ID", "") or "").strip()
        existing_secret = str(get_setting("GRAPH_CLIENT_SECRET", "") or "").strip()
        tenant_id = tenant_id or existing_tenant
        client_id = client_id or existing_client
        if not tenant_id:
            return Response({"error": "tenant_id required"}, status=http_status.HTTP_400_BAD_REQUEST)
        if not client_id:
            return Response({"error": "client_id required"}, status=http_status.HTTP_400_BAD_REQUEST)
        if not client_secret and not existing_secret:
            return Response({"error": "client_secret required"}, status=http_status.HTTP_400_BAD_REQUEST)

        set_setting("GRAPH_TENANT_ID", tenant_id, actor=request.user, value_type=SettingValueType.STRING, category="integrations.graph", description="Microsoft Graph tenant id for mailbox ingestion.", is_secret=True)
        set_setting("GRAPH_CLIENT_ID", client_id, actor=request.user, value_type=SettingValueType.STRING, category="integrations.graph", description="Microsoft Graph application client id for mailbox ingestion.", is_secret=True)
        if client_secret:
            set_setting("GRAPH_CLIENT_SECRET", client_secret, actor=request.user, value_type=SettingValueType.STRING, category="integrations.graph", description="Microsoft Graph client credential for mailbox ingestion.", is_secret=True)
        set_setting("GRAPH_MAIL_FOLDER", mail_folder, actor=request.user, value_type=SettingValueType.STRING, category="integrations.graph", description="Microsoft Graph mail folder used by mailbox ingestion.", is_secret=False)

        return Response(_build_graph_settings_response(request.user))


def _is_valid_code(code):
    import re
    return bool(re.match(r"^[a-z0-9-]+$", code))


def _normalize_extensions(ext_string):
    if not ext_string:
        return ""
    parts = [p.strip().lower().lstrip(".") for p in ext_string.replace(" ", ",").split(",")]
    return ",".join([p for p in parts if p])


def _contains_secret_like_field(data):
    suspicious_keys = [
        "password",
        "secret",
        "token",
        "api_key",
        "client_secret",
        "private_key",
        "authorization",
        "credential",
        "connection_string",
        "webhook",
    ]
    safe_operational_keys = {"match_tokens"}
    for key, value in data.items():
        key_lower = key.lower()
        if key_lower in safe_operational_keys:
            continue
        if any(suspect in key_lower for suspect in suspicious_keys):
            return True
        if isinstance(value, dict) and _contains_secret_like_field(value):
            return True
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and _contains_secret_like_field(item):
                    return True
    return False


SOURCE_CONFIG_ALLOWED_FIELDS = {
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
}

RULE_CONFIG_ALLOWED_FIELDS = {
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
}

SUPPRESSION_ALLOWED_FIELDS = {
    "name",
    "source",
    "source_id",
    "event_type",
    "severity",
    "match_payload",
    "scope_type",
    "conditions_json",
    "reason",
    "owner",
    "is_active",
    "starts_at",
    "expires_at",
}


def _is_source_config_payload(data):
    source_config_markers = {
        "expected_frequency",
        "expected_time_window_start",
        "expected_time_window_end",
        "mailbox_sender_patterns",
        "mailbox_subject_patterns",
        "parser_name",
        "severity_mapping_json",
        "metadata_json",
    }
    return any(field in data for field in source_config_markers)


def _is_structured_rule_payload(data):
    structured_markers = {
        "code",
        "name",
        "condition_operator",
        "threshold_json",
        "cooldown_minutes",
        "dedup_window_minutes",
        "auto_create_ticket",
        "auto_create_evidence_container",
    }
    return any(field in data for field in structured_markers)


def _create_source_config(request):
    data = request.data or {}
    if _contains_secret_like_field(data):
        return Response(
            {"error": "suspicious secret-like field detected, rejected for safety"},
            status=http_status.HTTP_400_BAD_REQUEST,
        )

    payload = _allowed_payload(data, SOURCE_CONFIG_ALLOWED_FIELDS)
    name = _clean_string(payload.get("name"))
    source_type = _clean_string(payload.get("source_type"))
    expected_frequency = _clean_string(payload.get("expected_frequency")) or "daily"

    if not name:
        return Response({"error": "name required"}, status=http_status.HTTP_400_BAD_REQUEST)
    if not source_type:
        return Response({"error": "source_type required"}, status=http_status.HTTP_400_BAD_REQUEST)
    if not _is_valid_source_type(source_type):
        return Response(
            {"error": "source_type must be slug-like (lowercase, alphanumeric, hyphen, underscore or dot)"},
            status=http_status.HTTP_400_BAD_REQUEST,
        )
    valid_frequencies = {choice[0] for choice in SecuritySourceConfig.FREQUENCY_CHOICES}
    if expected_frequency not in valid_frequencies:
        return Response(
            {"error": f"expected_frequency must be one of: {', '.join(sorted(valid_frequencies))}"},
            status=http_status.HTTP_400_BAD_REQUEST,
        )
    if SecuritySourceConfig.objects.filter(name=name).exists():
        return Response({"error": "name already exists"}, status=http_status.HTTP_400_BAD_REQUEST)

    sender_patterns, error = _as_json_list(payload, "mailbox_sender_patterns")
    if error:
        return Response({"error": error}, status=http_status.HTTP_400_BAD_REQUEST)
    subject_patterns, error = _as_json_list(payload, "mailbox_subject_patterns")
    if error:
        return Response({"error": error}, status=http_status.HTTP_400_BAD_REQUEST)
    severity_mapping, error = _as_json_dict(payload, "severity_mapping_json")
    if error:
        return Response({"error": error}, status=http_status.HTTP_400_BAD_REQUEST)
    metadata, error = _as_json_dict(payload, "metadata_json")
    if error:
        return Response({"error": error}, status=http_status.HTTP_400_BAD_REQUEST)

    start_time, error = _as_time(payload.get("expected_time_window_start"), "expected_time_window_start")
    if error:
        return Response({"error": error}, status=http_status.HTTP_400_BAD_REQUEST)
    end_time, error = _as_time(payload.get("expected_time_window_end"), "expected_time_window_end")
    if error:
        return Response({"error": error}, status=http_status.HTTP_400_BAD_REQUEST)

    source = SecuritySourceConfig.objects.create(
        name=name,
        source_type=source_type,
        vendor=_clean_string(payload.get("vendor")),
        enabled=bool(payload.get("enabled", True)),
        description=_clean_string(payload.get("description")),
        expected_frequency=expected_frequency,
        expected_time_window_start=start_time,
        expected_time_window_end=end_time,
        mailbox_sender_patterns=sender_patterns,
        mailbox_subject_patterns=subject_patterns,
        parser_name=_clean_string(payload.get("parser_name")),
        severity_mapping_json=severity_mapping,
        metadata_json=metadata,
        updated_by=request.user if getattr(request.user, "is_authenticated", False) else None,
    )

    _audit_ai_config_create(request, "ai_copilot_create_source", source, payload.keys())
    return Response(_build_source_config_dto(source), status=http_status.HTTP_201_CREATED)


def _create_alert_rule_config(request):
    data = request.data or {}
    if _contains_secret_like_field(data):
        return Response(
            {"error": "suspicious secret-like field detected, rejected for safety"},
            status=http_status.HTTP_400_BAD_REQUEST,
        )

    payload = _allowed_payload(data, RULE_CONFIG_ALLOWED_FIELDS)
    code = _clean_string(payload.get("code")).lower()
    name = _clean_string(payload.get("name"))
    condition_operator = _clean_string(payload.get("condition_operator")) or "gte"
    severity = _clean_string(payload.get("severity")).lower() or Severity.WARNING

    if not code:
        return Response({"error": "code required"}, status=http_status.HTTP_400_BAD_REQUEST)
    if not _is_valid_rule_code(code):
        return Response(
            {"error": "code must be slug-like (lowercase, alphanumeric, hyphen or underscore)"},
            status=http_status.HTTP_400_BAD_REQUEST,
        )
    if not name:
        return Response({"error": "name required"}, status=http_status.HTTP_400_BAD_REQUEST)
    if SecurityAlertRuleConfig.objects.filter(code=code).exists():
        return Response({"error": "rule with this code already exists"}, status=http_status.HTTP_400_BAD_REQUEST)

    valid_operators = {choice[0] for choice in SecurityAlertRuleConfig.OPERATOR_CHOICES}
    if condition_operator not in valid_operators:
        return Response(
            {"error": f"condition_operator must be one of: {', '.join(sorted(valid_operators))}"},
            status=http_status.HTTP_400_BAD_REQUEST,
        )
    valid_severities = {choice[0] for choice in Severity.choices}
    if severity not in valid_severities:
        return Response(
            {"error": f"severity must be one of: {', '.join(sorted(valid_severities))}"},
            status=http_status.HTTP_400_BAD_REQUEST,
        )

    threshold_json, error = _as_json_dict(payload, "threshold_json")
    if error:
        return Response({"error": error}, status=http_status.HTTP_400_BAD_REQUEST)
    cooldown_minutes, error = _as_non_negative_int(payload.get("cooldown_minutes", 60), "cooldown_minutes")
    if error:
        return Response({"error": error}, status=http_status.HTTP_400_BAD_REQUEST)
    dedup_window_minutes, error = _as_non_negative_int(payload.get("dedup_window_minutes", 1440), "dedup_window_minutes")
    if error:
        return Response({"error": error}, status=http_status.HTTP_400_BAD_REQUEST)

    threshold_value = _clean_string(payload.get("threshold_value"))
    if _looks_like_defender_critical_rule(payload, threshold_json):
        cooldown_minutes = max(cooldown_minutes, 1440)
        dedup_window_minutes = max(dedup_window_minutes, 1440)
        payload["auto_create_ticket"] = True
        payload["auto_create_evidence_container"] = True

    rule = SecurityAlertRuleConfig.objects.create(
        code=code,
        name=name,
        enabled=bool(payload.get("enabled", True)),
        source_type=_clean_string(payload.get("source_type")),
        metric_name=_clean_string(payload.get("metric_name")),
        condition_operator=condition_operator,
        threshold_value=threshold_value,
        threshold_json=threshold_json,
        severity=severity,
        cooldown_minutes=cooldown_minutes,
        dedup_window_minutes=dedup_window_minutes,
        auto_create_ticket=bool(payload.get("auto_create_ticket", False)),
        auto_create_evidence_container=bool(payload.get("auto_create_evidence_container", True)),
        description=_clean_string(payload.get("description")),
        updated_by=request.user if getattr(request.user, "is_authenticated", False) else None,
    )

    _audit_ai_config_create(request, "ai_copilot_create_rule", rule, payload.keys())
    return Response({"success": True, "rule": _build_rule_dto(rule)}, status=http_status.HTTP_201_CREATED)


def _create_suppression_config(request):
    data = request.data or {}
    if _contains_secret_like_field(data):
        return Response(
            {"error": "suspicious secret-like field detected, rejected for safety"},
            status=http_status.HTTP_400_BAD_REQUEST,
        )

    payload = _allowed_payload(data, SUPPRESSION_ALLOWED_FIELDS)
    name = _clean_string(payload.get("name"))
    reason = _clean_string(payload.get("reason"))
    owner = _clean_string(payload.get("owner"))
    scope_type = _clean_string(payload.get("scope_type")) or "alert_type"
    event_type = _clean_string(payload.get("event_type"))
    severity = _clean_string(payload.get("severity")).lower()

    if not name:
        return Response({"error": "name required"}, status=http_status.HTTP_400_BAD_REQUEST)
    if not reason:
        return Response({"error": "reason required"}, status=http_status.HTTP_400_BAD_REQUEST)
    if not owner:
        return Response({"error": "owner required"}, status=http_status.HTTP_400_BAD_REQUEST)
    if not _is_valid_source_type(scope_type):
        return Response({"error": "scope_type must be slug-like"}, status=http_status.HTTP_400_BAD_REQUEST)
    if severity:
        valid_severities = {choice[0] for choice in Severity.choices}
        if severity not in valid_severities:
            return Response(
                {"error": f"severity must be one of: {', '.join(sorted(valid_severities))}"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

    match_payload, error = _as_json_dict(payload, "match_payload")
    if error:
        return Response({"error": error}, status=http_status.HTTP_400_BAD_REQUEST)
    conditions_json, error = _as_json_dict(payload, "conditions_json")
    if error:
        return Response({"error": error}, status=http_status.HTTP_400_BAD_REQUEST)

    source, error = _resolve_security_source(payload)
    if error:
        return Response({"error": error}, status=http_status.HTTP_400_BAD_REQUEST)

    if not any([source, event_type, severity, match_payload, conditions_json]):
        return Response(
            {"error": "suppression too broad: add source, event_type, severity, match_payload or conditions_json"},
            status=http_status.HTTP_400_BAD_REQUEST,
        )

    starts_at, error = _as_datetime(payload.get("starts_at"), "starts_at")
    if error:
        return Response({"error": error}, status=http_status.HTTP_400_BAD_REQUEST)
    expires_at, error = _as_datetime(payload.get("expires_at"), "expires_at")
    if error:
        return Response({"error": error}, status=http_status.HTTP_400_BAD_REQUEST)
    if starts_at and expires_at and expires_at <= starts_at:
        return Response({"error": "expires_at must be after starts_at"}, status=http_status.HTTP_400_BAD_REQUEST)

    suppression = SecurityAlertSuppressionRule.objects.create(
        name=name,
        source=source,
        event_type=event_type,
        severity=severity,
        match_payload=match_payload,
        scope_type=scope_type,
        conditions_json=conditions_json,
        reason=reason,
        owner=owner,
        is_active=bool(payload.get("is_active", True)),
        starts_at=starts_at,
        expires_at=expires_at,
        created_by=request.user if getattr(request.user, "is_authenticated", False) else None,
    )

    _audit_ai_config_create(request, "ai_copilot_create_suppression", suppression, payload.keys())
    response = _build_suppression_dto(suppression)
    if not expires_at:
        response["warnings"] = ["expires_at missing: suppression has no scheduled expiration"]
    return Response(response, status=http_status.HTTP_201_CREATED)


def _allowed_payload(data, allowed_fields):
    return {field: data[field] for field in allowed_fields if field in data}


def _clean_string(value):
    if value is None:
        return ""
    return str(value).strip()


def _is_valid_source_type(value):
    return bool(re.match(r"^[a-z0-9_.-]+$", value or ""))


def _is_valid_rule_code(value):
    return bool(re.match(r"^[a-z0-9_-]+$", value or ""))


def _as_json_dict(payload, field):
    value = payload.get(field, {})
    if value in (None, ""):
        return {}, None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}, f"{field} must be a valid JSON object"
    if not isinstance(value, dict):
        return {}, f"{field} must be a JSON object"
    return value, None


def _as_json_list(payload, field):
    value = payload.get(field, [])
    if value in (None, ""):
        return [], None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                return [], f"{field} must be a valid JSON list"
        else:
            value = [item.strip() for item in re.split(r"[\n,]+", value) if item.strip()]
    if not isinstance(value, list):
        return [], f"{field} must be a JSON list"
    return [str(item).strip() for item in value if str(item).strip()], None


def _as_time(value, field):
    if value in (None, ""):
        return None, None
    parsed = parse_time(str(value))
    if parsed is None:
        return None, f"{field} must be HH:MM"
    return parsed, None


def _as_datetime(value, field):
    if value in (None, ""):
        return None, None
    parsed = parse_datetime(str(value))
    if parsed is None:
        return None, f"{field} must be a valid datetime"
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed, None


def _as_non_negative_int(value, field):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0, f"{field} must be a non-negative integer"
    if parsed < 0:
        return 0, f"{field} must be a non-negative integer"
    return parsed, None


def _looks_like_defender_critical_rule(payload, threshold_json):
    combined = " ".join(
        [
            _clean_string(payload.get("source_type")),
            _clean_string(payload.get("metric_name")),
            _clean_string(payload.get("threshold_value")),
            json.dumps(threshold_json, sort_keys=True),
        ]
    ).lower()
    return (
        _clean_string(payload.get("severity")).lower() == Severity.CRITICAL
        and "defender" in combined
        and ("cvss" in combined or "exposed" in combined)
    )


def _resolve_security_source(payload):
    source_id = payload.get("source_id") or payload.get("source")
    if source_id in (None, ""):
        return None, None
    try:
        return SecuritySource.objects.get(pk=int(source_id)), None
    except (TypeError, ValueError):
        return None, "source_id must be numeric"
    except SecuritySource.DoesNotExist:
        return None, "source not found"


def _audit_ai_config_create(request, action, instance, fields):
    summary = {
        "source": "ai_copilot",
        "reviewed": True,
        "fields": sorted(str(field) for field in fields),
    }
    audit_config_change(
        request.user,
        action,
        instance,
        field_name="reviewed_fields",
        old_value="",
        new_value=json.dumps(summary, sort_keys=True),
        request=request,
    )


def _build_source_config_dto(source):
    return {
        "id": source.id,
        "code": f"source-config-{source.id}",
        "name": source.name,
        "source_type": source.source_type,
        "vendor": source.vendor,
        "enabled": source.enabled,
        "expected_frequency": source.expected_frequency,
        "expected_time_window_start": source.expected_time_window_start.isoformat() if source.expected_time_window_start else None,
        "expected_time_window_end": source.expected_time_window_end.isoformat() if source.expected_time_window_end else None,
        "parser_name": source.parser_name,
        "status": "active" if source.enabled else "disabled",
        "origin": "manual",
        "parser_names": [source.parser_name] if source.parser_name else ["unknown"],
        "warning_messages": [],
    }


def _build_source_config_studio_dto(source):
    warnings = []
    if source.enabled and not source.parser_name:
        warnings.append("Parser non configurato")
    return {
        "id": source.id,
        "code": f"source-config-{source.id}",
        "name": source.name,
        "source_type": source.source_type,
        "category": source.vendor.lower().replace(" ", "_") if source.vendor else "custom",
        "status": "active" if source.enabled else "disabled",
        "origin": "manual",
        "parser_names": [source.parser_name] if source.parser_name else ["unknown"],
        "mailbox_address": None,
        "last_import_at": None,
        "last_success_at": None,
        "last_error_at": None,
        "last_error_message": "",
        "latest_run": None,
        "warning_messages": warnings,
        "managed_by": "admin_config",
        "links": {
            "configuration_url": "/security/admin/config/sources/",
            "diagnostics_url": "/configuration?tab=test",
        },
    }


def _build_rule_dto(rule):
    return {
        "code": rule.code,
        "title": rule.name,
        "enabled": rule.enabled,
        "severity": rule.severity,
        "when_summary": _build_when_summary(rule),
        "then_summary": _build_then_summary(rule),
        "dedup_summary": f"{rule.dedup_window_minutes} min",
        "aggregation_summary": rule.metric_name or "N/A",
        "last_match_at": rule.last_triggered_at.isoformat() if rule.last_triggered_at else None,
        "matches_count": rule.trigger_count,
        "status": "active" if rule.enabled else "disabled",
        "warning_messages": [],
    }


def _build_suppression_dto(supp):
    now = timezone.now()
    is_expired = supp.expires_at and supp.expires_at < now
    return {
        "id": supp.id,
        "code": f"supp-{supp.id}",
        "type": _map_suppression_type(supp),
        "title": supp.name,
        "active": supp.is_active and not is_expired,
        "reason": supp.reason or "N/A",
        "owner": _safe_owner(supp),
        "scope_summary": _build_scope_summary(supp),
        "expires_at": supp.expires_at.isoformat() if supp.expires_at else None,
        "matches_suppressed_count": supp.hit_count,
        "created_at": supp.created_at.isoformat() if supp.created_at else None,
        "updated_at": supp.updated_at.isoformat() if supp.updated_at else None,
        "status": "expired" if is_expired else ("active" if supp.is_active else "disabled"),
    }


def _build_source_dto(source):
    latest_run = source.ingestion_runs.order_by("-started_at").first()
    category = _detect_category(source)
    status = _detect_status(source, latest_run)
    origin = _map_origin(source.source_type)
    parser_names = _detect_parsers(source)
    warnings = _collect_warnings(source, latest_run)
    mailbox_safe = _mask_email(source.mailbox_address) if source.mailbox_address else None

    return {
        "id": source.id,
        "code": source.code,
        "name": source.name,
        "enabled": source.enabled,
        "source_type": source.source_type,
        "category": category,
        "status": status,
        "origin": origin,
        "parser_names": parser_names,
        "mailbox_address": mailbox_safe,
        "attachment_extensions": source.attachment_extensions,
        "max_messages_per_run": source.max_messages_per_run,
        "mark_as_read_after_import": source.mark_as_read_after_import,
        "process_attachments": source.process_attachments,
        "process_email_body": source.process_email_body,
        "last_import_at": source.last_run_at.isoformat() if source.last_run_at else None,
        "last_success_at": source.last_success_at.isoformat() if source.last_success_at else None,
        "last_error_at": source.last_error_at.isoformat() if source.last_error_at else None,
        "last_error_message": _truncate_safe(source.last_error_message, 200),
        "latest_run": _build_run_counters(latest_run) if latest_run else None,
        "warning_messages": warnings,
        "links": {
            "configuration_url": f"/configuration?tab=sources&source={source.code}",
            "inbox_url": "/inbox",
            "reports_url": "/reports",
            "diagnostics_url": "/configuration?tab=test",
        },
    }


class LoginApiView(APIView):
    permission_classes = []

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return Response({
            "csrfToken": get_token(request),
            "authenticated": request.user.is_authenticated,
            "user": {
                "username": request.user.username,
                "email": request.user.email,
            } if request.user.is_authenticated else None,
        })

    def post(self, request):
        username = request.data.get("username", "").strip()
        password = request.data.get("password", "")

        if not username or not password:
            return Response(
                {"error": "username and password required"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        from django.contrib.auth import authenticate, login

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(
                {"error": "Invalid credentials"},
                status=http_status.HTTP_401_UNAUTHORIZED,
            )

        login(request, user)
        return Response({
            "authenticated": True,
            "user": {
                "username": user.username,
                "email": user.email,
            },
        })


class LogoutApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def post(self, request):
        from django.contrib.auth import logout
        logout(request)
        return Response({"authenticated": False})


class UsersListApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        from django.contrib.auth.models import User

        users = User.objects.all().order_by("username")
        result = []
        for user in users:
            groups = [g.name for g in user.groups.all()]
            result.append({
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_active": user.is_active,
                "is_staff": user.is_staff,
                "is_superuser": user.is_superuser,
                "groups": groups,
                "date_joined": user.date_joined.isoformat() if user.date_joined else None,
            })
        return Response(result)

    def post(self, request):
        from django.contrib.auth.models import User

        username = request.data.get("username", "").strip()
        email = request.data.get("email", "").strip()
        password = request.data.get("password", "")
        first_name = request.data.get("first_name", "").strip()
        last_name = request.data.get("last_name", "").strip()
        groups = request.data.get("groups", [])

        if not username:
            return Response({"error": "username required"}, status=400)
        if not password:
            return Response({"error": "password required"}, status=400)

        if User.objects.filter(username=username).exists():
            return Response({"error": "username already exists"}, status=400)

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )

        for group_name in groups:
            from django.contrib.auth.models import Group
            try:
                group = Group.objects.get(name=group_name)
                user.groups.add(group)
            except Group.DoesNotExist:
                pass

        return Response({"id": user.id, "username": user.username}, status=201)


class UserDetailApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request, user_id):
        from django.contrib.auth.models import User

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "user not found"}, status=404)

        groups = [g.name for g in user.groups.all()]
        return Response({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_active": user.is_active,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
            "groups": groups,
            "date_joined": user.date_joined.isoformat() if user.date_joined else None,
        })

    def patch(self, request, user_id):
        from django.contrib.auth.models import User, Group

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "user not found"}, status=404)

        if "email" in request.data:
            user.email = request.data["email"].strip()
        if "first_name" in request.data:
            user.first_name = request.data["first_name"].strip()
        if "last_name" in request.data:
            user.last_name = request.data["last_name"].strip()
        if "is_active" in request.data:
            user.is_active = bool(request.data["is_active"])
        if "is_staff" in request.data:
            user.is_staff = bool(request.data["is_staff"])
        if "is_superuser" in request.data:
            user.is_superuser = bool(request.data["is_superuser"])

        if "password" in request.data and request.data["password"]:
            user.set_password(request.data["password"])

        if "groups" in request.data:
            user.groups.clear()
            for group_name in request.data["groups"]:
                try:
                    group = Group.objects.get(name=group_name)
                    user.groups.add(group)
                except Group.DoesNotExist:
                    pass

        user.save()
        return Response({"id": user.id, "username": user.username})

    def delete(self, request, user_id):
        from django.contrib.auth.models import User

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "user not found"}, status=404)

        if user.id == request.user.id:
            return Response({"error": "cannot delete yourself"}, status=400)

        user.delete()
        return Response({"deleted": True})


class GroupsListApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        from django.contrib.auth.models import Group

        groups = Group.objects.all().order_by("name")
        result = []
        for group in groups:
            result.append({
                "id": group.id,
                "name": group.name,
                "user_count": group.user_set.count(),
            })
        return Response(result)

    def post(self, request):
        from django.contrib.auth.models import Group

        name = request.data.get("name", "").strip()

        if not name:
            return Response({"error": "name required"}, status=400)

        if Group.objects.filter(name=name).exists():
            return Response({"error": "group already exists"}, status=400)

        group = Group.objects.create(name=name)
        return Response({"id": group.id, "name": group.name}, status=201)


class GroupDetailApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request, group_id):
        from django.contrib.auth.models import Group

        try:
            group = Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            return Response({"error": "group not found"}, status=404)

        users = [{"id": u.id, "username": u.username, "email": u.email} for u in group.user_set.all()]
        return Response({
            "id": group.id,
            "name": group.name,
            "users": users,
        })

    def patch(self, request, group_id):
        from django.contrib.auth.models import Group

        try:
            group = Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            return Response({"error": "group not found"}, status=404)

        if "name" in request.data:
            new_name = request.data["name"].strip()
            if new_name and new_name != group.name:
                if Group.objects.filter(name=new_name).exists():
                    return Response({"error": "group name already exists"}, status=400)
                group.name = new_name
                group.save()

        return Response({"id": group.id, "name": group.name})

    def delete(self, request, group_id):
        from django.contrib.auth.models import Group

        try:
            group = Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            return Response({"error": "group not found"}, status=404)

        group.delete()
        return Response({"deleted": True})


class ConfigurationRuleSimulateApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def post(self, request):
        data = request.data or {}
        rule = data.get("rule", {})
        options = data.get("options", {})

        if not rule:
            return Response(
                {"error": "rule required"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        # Validate options
        lookback_days = options.get("lookback_days", 30)
        max_examples = options.get("max_examples", 10)

        if not isinstance(lookback_days, int) or lookback_days < 1 or lookback_days > 365:
            return Response(
                {"error": "lookback_days must be between 1 and 365"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(max_examples, int) or max_examples < 1 or max_examples > 100:
            return Response(
                {"error": "max_examples must be between 1 and 100"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        # Run simulation
        try:
            result = simulate_alert_rule(rule, options)
        except Exception as e:
            return Response(
                {"error": f"Simulation failed: {str(e)}"},
                status=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(result, status=http_status.HTTP_200_OK)


def _generate_rule_code(rule_name):
    import re
    base = re.sub(r"[^a-z0-9]+", "-", rule_name.lower()).strip("-")
    base = base[:50]
    code = f"ai-{base}"
    counter = 1
    while SecurityAlertRuleConfig.objects.filter(code=code).exists():
        code = f"ai-{base}-{counter}"
        counter += 1
    return code
