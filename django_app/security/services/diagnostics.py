import fnmatch
import re

from django.core.management import call_command
from django.db import connection
from django.db.models import Max, Q
from django.utils import timezone

from security.models import (
    BackupExpectedJobConfig,
    BackupJobRecord,
    ParseStatus,
    SecurityAlert,
    SecurityAlertRuleConfig,
    SecurityAlertSuppressionRule,
    SecurityCenterSetting,
    SecurityConfigurationAuditLog,
    SecurityEventRecord,
    SecurityMailboxMessage,
    SecurityNotificationChannel,
    SecurityParserConfig,
    SecurityRemediationTicket,
    SecurityReport,
    SecuritySourceConfig,
    SecuritySourceFile,
    SecurityTicketConfig,
    SettingValueType,
    Severity,
)
from security.parsers.load import *  # noqa: F403,F401
from security.ai.services.memory.diagnostics import ai_memory_diagnostic_check
from security.parsers import parser_registry
from security.services.backup_monitoring import last_seen_backup_status, missing_backup_candidates
from security.services.configuration import get_bool_setting


VALID_OPERATORS = {choice[0] for choice in SecurityAlertRuleConfig.OPERATOR_CHOICES}
SEVERITY_ORDER = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.WARNING: 3,
    Severity.HIGH: 4,
    Severity.CRITICAL: 5,
}


def run_security_center_diagnostics():
    checks = [
        _database_check(),
        _migrations_check(),
        _config_seeded_check(),
        _enabled_sources_check(),
        _enabled_parsers_check(),
        _defender_source_check(),
        _watchguard_sources_check(),
        _critical_alert_rules_check(),
        _ticket_config_check(),
        _dashboard_notification_check(),
        _notification_configuration_check(),
        _expired_suppression_check(),
        _backup_expectations_check(),
        _parser_config_reference_check(),
        _missing_parser_config_check(),
        _alert_rule_operator_check(),
        _setting_type_check(),
        _secret_rendering_check(),
        _recent_parse_failures_check(),
        _recent_alert_generation_check(),
        _defender_critical_ticket_check(),
        _broad_critical_suppression_check(),
        _critical_notification_check(),
        ai_memory_diagnostic_check(),
    ]
    return {"status": _rollup_status(checks), "checks": checks}


def build_diagnostics_context(match_input=None):
    diagnostics = run_security_center_diagnostics()
    return {
        "diagnostics": diagnostics,
        "health_cards": _health_cards(diagnostics["checks"]),
        "parser_diagnostics": parser_registry_diagnostics(),
        "source_match_result": match_source_sample(**(match_input or {})) if match_input else None,
        "alert_rule_diagnostics": alert_rule_diagnostics(),
        "suppression_diagnostics": suppression_diagnostics(),
        "backup_diagnostics": backup_diagnostics(),
        "notification_diagnostics": notification_diagnostics(),
        "recent_activity": recent_activity(),
    }


def parser_registry_diagnostics():
    registry_names = {parser.name for parser in parser_registry.all()}
    configured = {config.parser_name: config for config in SecurityParserConfig.objects.all()}
    rows = []
    for name in sorted(registry_names | set(configured)):
        config = configured.get(name)
        reports = SecurityReport.objects.filter(parser_name=name)
        failed_reports = reports.filter(parse_status=ParseStatus.FAILED)
        source_activity = _recent_source_activity(config.parser_name if config else name)
        flags = []
        if config and name not in registry_names:
            flags.append("Parser configurato assente dal registro codice")
        if name in registry_names and not config:
            flags.append("Parser del registro senza configurazione")
        if config and not config.enabled and source_activity:
            flags.append("Parser disattivato con attivita sorgente recente corrispondente")
        rows.append(
            {
                "parser_name": name,
                "configured_enabled": config.enabled if config else None,
                "exists_in_registry": name in registry_names,
                "last_successful_parse": reports.filter(parse_status=ParseStatus.PARSED).aggregate(value=Max("created_at"))["value"],
                "last_failed_parse": failed_reports.aggregate(value=Max("created_at"))["value"],
                "report_count": reports.count(),
                "warning_count": reports.filter(parsed_payload__parse_warnings__isnull=False).count(),
                "error_count": failed_reports.count(),
                "flags": flags,
            }
        )
    return rows


def match_source_sample(sender="", subject="", body=""):
    matches = []
    for source in SecuritySourceConfig.objects.order_by("-enabled", "name"):
        matched, reason = _source_match_reason(source, sender=sender, subject=subject, body=body)
        if matched:
            parser_config = SecurityParserConfig.objects.filter(parser_name=source.parser_name).first() if source.parser_name else None
            matches.append(
                {
                    "source": source.name,
                    "source_enabled": source.enabled,
                    "selected_parser": source.parser_name or "",
                    "parser_enabled": parser_config.enabled if parser_config else False,
                    "reason": reason,
                }
            )
    selected = next((match for match in matches if match["source_enabled"] and match["parser_enabled"]), matches[0] if matches else None)
    return {
        "sender": sender,
        "subject": subject,
        "body_provided": bool(body),
        "matching_sources": matches,
        "selected_parser": selected["selected_parser"] if selected else "",
        "selected_reason": selected["reason"] if selected else "Nessuna sorgente configurata corrisponde al campione.",
    }


def alert_rule_diagnostics():
    rows = []
    invalid = []
    for rule in SecurityAlertRuleConfig.objects.order_by("-enabled", "severity", "code"):
        flags = []
        if rule.condition_operator not in VALID_OPERATORS:
            flags.append("Operatore non supportato")
        if _invalid_threshold(rule):
            flags.append("Valore soglia non valido")
        if rule.severity == Severity.CRITICAL and not rule.auto_create_evidence_container:
            flags.append("Regola critica senza evidenza automatica")
        if _is_defender_critical_cve_rule(rule) and not rule.auto_create_ticket:
            flags.append("Regola CVE critica Defender senza ticket automatico")
        row = {
            "rule": rule,
            "last_triggered": rule.last_triggered_at,
            "trigger_count": rule.trigger_count,
            "flags": flags,
        }
        rows.append(row)
        if flags:
            invalid.append(row)
    return {
        "enabled": [row for row in rows if row["rule"].enabled],
        "disabled": [row for row in rows if not row["rule"].enabled],
        "invalid": invalid,
    }


def suppression_diagnostics():
    now = timezone.now()
    rules = list(SecurityAlertSuppressionRule.objects.order_by("-hit_count", "name"))
    rows = []
    for rule in rules:
        flags = []
        if rule.is_active and rule.severity == Severity.CRITICAL and not (rule.source_id or rule.event_type or rule.conditions_json or rule.match_payload):
            flags.append("Soppressione ampia su alert critici")
        if rule.is_active and not rule.expires_at:
            flags.append("Soppressione senza scadenza")
        if rule.hit_count >= 100:
            flags.append("Numero occorrenze molto alto")
        if not rule.owner:
            flags.append("Responsabile mancante")
        if not rule.reason:
            flags.append("Motivo mancante")
        rows.append({"rule": rule, "flags": flags})
    return {
        "active": [row for row in rows if row["rule"].is_active and not row["rule"].is_expired],
        "expired": [row for row in rows if row["rule"].expires_at and row["rule"].expires_at <= now],
        "top_by_hit_count": rows[:10],
        "without_expiration": [row for row in rows if not row["rule"].expires_at],
        "missing_owner_or_reason": [row for row in rows if not row["rule"].owner or not row["rule"].reason],
    }


def backup_diagnostics():
    expected = []
    for config in BackupExpectedJobConfig.objects.order_by("-enabled", "-critical_asset", "job_name"):
        flags = []
        if config.critical_asset and not config.enabled:
            flags.append("Job atteso disattivato per asset critico")
        expected.append({"config": config, "last_seen": last_seen_backup_status(config), "flags": flags})
    critical_without_enabled = [row for row in expected if row["config"].critical_asset and not row["config"].enabled]
    return {
        "enabled_expected_jobs": [row for row in expected if row["config"].enabled],
        "critical_assets": [row for row in expected if row["config"].critical_asset],
        "missing_candidates": missing_backup_candidates(),
        "critical_without_enabled_expectation": critical_without_enabled,
    }


def notification_diagnostics():
    rows = []
    for channel in SecurityNotificationChannel.objects.order_by("-enabled", "channel_type", "name"):
        flags = []
        if channel.enabled and channel.channel_type == "teams_webhook" and not channel.webhook_url_secret_ref:
            flags.append("Webhook Teams attivo senza segreto")
        if channel.enabled and channel.channel_type == "email" and not channel.recipients.strip():
            flags.append("Canale email attivo senza destinatari")
        rows.append(
            {
                "channel": channel,
                "masked_destination": _masked_channel_destination(channel),
                "flags": flags,
            }
        )
    return {"enabled": [row for row in rows if row["channel"].enabled], "all": rows}


def recent_activity():
    items = []
    for report in SecurityReport.objects.select_related("source").order_by("-created_at")[:20]:
        items.append(_activity(report.created_at, "Report ingested", report.title, report.source.name, ""))
    for report in SecurityReport.objects.filter(Q(parse_status=ParseStatus.FAILED) | Q(parsed_payload__parse_warnings__isnull=False)).select_related("source").order_by("-created_at")[:20]:
        items.append(_activity(report.created_at, "Parser warning/error", report.parser_name, report.source.name, "Body omitted"))
    for alert in SecurityAlert.objects.select_related("source").order_by("-created_at")[:20]:
        action = "Alert suppressed" if alert.status == "suppressed" else "Alert created"
        items.append(_activity(alert.created_at, action, alert.title, alert.source.name, alert.severity))
    for ticket in SecurityRemediationTicket.objects.select_related("source").order_by("-updated_at")[:20]:
        items.append(_activity(ticket.updated_at, "Ticket updated", ticket.title, ticket.source.name, ticket.status))
    for change in SecurityConfigurationAuditLog.objects.select_related("actor").order_by("-created_at")[:20]:
        items.append(_activity(change.created_at, "Config change", change.object_repr, change.model_name, change.action))
    return sorted(items, key=lambda item: item["when"], reverse=True)[:20]


def _database_check():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return _check("database", "Database", "ok", "Connessione database disponibile.")
    except Exception as exc:  # pragma: no cover - defensive diagnostics
        return _check("database", "Database", "error", "Connessione database fallita.", {"error": str(exc)}, "Verifica connettivita database e credenziali.")


def _migrations_check():
    try:
        call_command("migrate", check=True, dry_run=True, verbosity=0)
    except SystemExit as exc:
        return _check("migrations", "Migrazioni", "warning", "Migrazioni pendenti o non valide rilevate.", {"exit_code": exc.code}, "Esegui python manage.py migrate dopo aver verificato lo stato migrazioni.")
    except Exception as exc:
        return _check("migrations", "Migrazioni", "warning", "Migrazioni pendenti o non valide rilevate.", {"error": str(exc)}, "Esegui python manage.py migrate dopo aver verificato lo stato migrazioni.")
    return _check("migrations", "Migrazioni", "ok", "Nessuna migrazione pendente rilevata.")


def _config_seeded_check():
    counts = {
        "settings": SecurityCenterSetting.objects.count(),
        "sources": SecuritySourceConfig.objects.count(),
        "parsers": SecurityParserConfig.objects.count(),
        "alert_rules": SecurityAlertRuleConfig.objects.count(),
        "notifications": SecurityNotificationChannel.objects.count(),
    }
    missing = [name for name, count in counts.items() if count == 0]
    return _check(
        "security_config_seeded",
        "Configurazione seed",
        "warning" if missing else "ok",
        "Dati seed di configurazione presenti." if not missing else f"Sezioni configurazione mancanti: {', '.join(missing)}.",
        counts,
        "Esegui python manage.py seed_security_center_config." if missing else "",
    )


def _enabled_sources_check():
    count = SecuritySourceConfig.objects.filter(enabled=True).count()
    return _check("enabled_sources", "Sorgenti attive", "ok" if count else "warning", f"{count} sorgenti attive configurate.", {"enabled_count": count}, "Attiva almeno una sorgente.")


def _enabled_parsers_check():
    count = SecurityParserConfig.objects.filter(enabled=True).count()
    return _check("enabled_parsers", "Parser attivi", "ok" if count else "warning", f"{count} parser attivi configurati.", {"enabled_count": count}, "Attiva almeno un parser.")


def _defender_source_check():
    defender_parser = SecurityParserConfig.objects.filter(parser_name__icontains="defender").exists()
    defender_source = SecuritySourceConfig.objects.filter(Q(vendor__icontains="microsoft") | Q(source_type__icontains="defender") | Q(name__icontains="defender")).exists()
    status = "warning" if defender_parser and not defender_source else "ok"
    return _check("defender_source_for_parser", "Sorgente Microsoft Defender", status, "Copertura sorgente Microsoft Defender verificata.", {"defender_parser_exists": defender_parser, "defender_source_exists": defender_source}, "Crea una configurazione sorgente Microsoft Defender." if status == "warning" else "")


def _watchguard_sources_check():
    watchguard_parser = SecurityParserConfig.objects.filter(parser_name__icontains="watchguard").exists()
    watchguard_source = SecuritySourceConfig.objects.filter(Q(vendor__icontains="watchguard") | Q(source_type__icontains="watchguard") | Q(name__icontains="watchguard")).exists()
    status = "warning" if watchguard_parser and not watchguard_source else "ok"
    return _check("watchguard_sources_for_parsers", "Sorgenti WatchGuard", status, "Copertura sorgente WatchGuard verificata.", {"watchguard_parser_exists": watchguard_parser, "watchguard_source_exists": watchguard_source}, "Crea configurazioni sorgente WatchGuard." if status == "warning" else "")


def _critical_alert_rules_check():
    count = SecurityAlertRuleConfig.objects.filter(enabled=True, severity=Severity.CRITICAL).count()
    return _check("critical_alert_rules", "Regole alert critiche", "ok" if count else "warning", f"{count} regole alert critiche attive configurate.", {"enabled_critical_rules": count}, "Attiva le regole alert critiche.")


def _ticket_config_check():
    exists = SecurityTicketConfig.objects.exists()
    return _check("ticket_auto_creation_config", "Configurazione ticket automatici", "ok" if exists else "warning", "Configurazione ticket presente." if exists else "Configurazione ticket mancante.", {}, "Crea la configurazione ticketing.")


def _dashboard_notification_check():
    exists = SecurityNotificationChannel.objects.filter(channel_type="dashboard").exists()
    return _check("dashboard_notification_channel", "Canale notifica dashboard", "ok" if exists else "warning", "Canale notifica dashboard presente." if exists else "Canale notifica solo dashboard mancante.", {}, "Crea un canale notifica dashboard.")


def _notification_configuration_check():
    bad = []
    for channel in SecurityNotificationChannel.objects.filter(enabled=True):
        if channel.channel_type == "teams_webhook" and not channel.webhook_url_secret_ref:
            bad.append(channel.name)
        if channel.channel_type == "email" and not channel.recipients.strip():
            bad.append(channel.name)
    return _check("notification_required_configuration", "Configurazione canali notifica", "warning" if bad else "ok", "I canali notifica attivi hanno la configurazione richiesta." if not bad else f"{len(bad)} canali attivi non hanno la configurazione richiesta.", {"channels": bad}, "Compila destinazioni o riferimenti segreti richiesti.")


def _expired_suppression_check():
    count = SecurityAlertSuppressionRule.objects.filter(is_active=True, expires_at__lte=timezone.now()).count()
    return _check("expired_active_suppressions", "Soppressioni attive scadute", "warning" if count else "ok", f"{count} regole di soppressione scadute sono ancora attive.", {"count": count}, "Disattiva o rinnova le soppressioni scadute." if count else "")


def _backup_expectations_check():
    enabled = get_bool_setting("backup_monitoring_enabled", BackupExpectedJobConfig.objects.exists())
    count = BackupExpectedJobConfig.objects.filter(enabled=True).count()
    return _check("backup_expected_jobs", "Aspettative backup", "warning" if enabled and count == 0 else "ok", f"{count} job backup attesi attivi configurati.", {"backup_monitoring_enabled": enabled, "enabled_expected_jobs": count}, "Aggiungi job backup attesi o disattiva il monitoraggio backup." if enabled and count == 0 else "")


def _parser_config_reference_check():
    registry_names = {parser.name for parser in parser_registry.all()}
    missing = list(SecuritySourceConfig.objects.exclude(parser_name="").exclude(parser_name__in=registry_names).values_list("name", "parser_name"))
    return _check("parser_configs_reference_existing_names", "Riferimenti configurazione parser", "warning" if missing else "ok", "I riferimenti parser delle sorgenti sono validi." if not missing else f"{len(missing)} configurazioni sorgente fanno riferimento a parser mancanti.", {"missing": [{"source": source, "parser_name": parser} for source, parser in missing]}, "Aggiorna i nomi parser delle sorgenti o registra il parser mancante.")


def _missing_parser_config_check():
    configured = set(SecurityParserConfig.objects.values_list("parser_name", flat=True))
    missing = sorted(parser.name for parser in parser_registry.all() if parser.name not in configured)
    return _check("registry_parsers_have_config", "Configurazione registro parser", "warning" if missing else "ok", "Tutti i parser del registro hanno righe di configurazione." if not missing else f"{len(missing)} parser del registro non hanno configurazione.", {"missing": missing}, "Esegui il comando seed o crea righe di configurazione parser.")


def _alert_rule_operator_check():
    invalid = list(SecurityAlertRuleConfig.objects.exclude(condition_operator__in=VALID_OPERATORS).values_list("code", "condition_operator"))
    return _check("alert_rule_valid_operators", "Operatori regole alert", "warning" if invalid else "ok", "Gli operatori delle regole alert sono validi." if not invalid else f"{len(invalid)} regole alert usano operatori non supportati.", {"invalid": [{"code": code, "operator": operator} for code, operator in invalid]}, "Sostituisci gli operatori non supportati con scelte supportate.")


def _setting_type_check():
    invalid = []
    for setting in SecurityCenterSetting.objects.all():
        if not _setting_value_matches(setting.value, setting.value_type):
            invalid.append({"key": setting.key, "value_type": setting.value_type})
    return _check("setting_value_types", "Tipi valori impostazioni", "warning" if invalid else "ok", "I valori delle impostazioni corrispondono ai tipi dichiarati." if not invalid else f"{len(invalid)} impostazioni non corrispondono ai tipi dichiarati.", {"invalid": invalid}, "Correggi valori o tipi dichiarati delle impostazioni.")


def _secret_rendering_check():
    secret_count = SecurityCenterSetting.objects.filter(is_secret=True).exclude(value__in=["", None]).count()
    return _check("secret_values_redacted", "Mascheramento segreti", "ok", f"{secret_count} impostazioni segrete saranno mostrate solo come valori mascherati.", {"secret_settings": secret_count}, "")


def _recent_parse_failures_check():
    since = timezone.now() - timezone.timedelta(days=7)
    failed_items = SecurityMailboxMessage.objects.filter(parse_status=ParseStatus.FAILED, received_at__gte=since).count() + SecuritySourceFile.objects.filter(parse_status=ParseStatus.FAILED, uploaded_at__gte=since).count()
    failed_reports = SecurityReport.objects.filter(parse_status=ParseStatus.FAILED, created_at__gte=since).count()
    total = failed_items + failed_reports
    status = "error" if total >= 5 else "warning" if total else "ok"
    return _check("recent_parser_errors", "Errori parser recenti", status, f"{total} fallimenti parser recenti trovati.", {"failed_items": failed_items, "failed_reports": failed_reports}, "Verifica gli errori parser. I corpi completi dei report sono omessi intenzionalmente." if total else "")


def _recent_alert_generation_check():
    since = timezone.now() - timezone.timedelta(days=7)
    auto_enabled = get_bool_setting("automatic_alert_generation_enabled", True)
    events = SecurityEventRecord.objects.filter(created_at__gte=since).count()
    alerts = SecurityAlert.objects.filter(created_at__gte=since).count()
    status = "warning" if auto_enabled and events and alerts == 0 else "ok"
    return _check("recent_alert_generation", "Generazione alert recente", status, f"{alerts} alert creati da {events} eventi recenti.", {"recent_events": events, "recent_alerts": alerts}, "Esegui la valutazione regole alert e verifica le regole attive." if status == "warning" else "")


def _defender_critical_ticket_check():
    count = SecurityAlertRuleConfig.objects.filter(enabled=True, severity=Severity.CRITICAL, source_type__icontains="defender", auto_create_ticket=False).count()
    return _check("defender_critical_auto_ticket", "Ticket automatici critici Defender", "warning" if count else "ok", f"{count} regole critiche Defender non hanno creazione ticket automatica.", {"count": count}, "Attiva la creazione ticket automatica per regole CVE critiche Defender." if count else "")


def _broad_critical_suppression_check():
    count = SecurityAlertSuppressionRule.objects.filter(is_active=True, severity=Severity.CRITICAL, source__isnull=True, event_type="", conditions_json={}, match_payload={}).count()
    return _check("broad_critical_suppression", "Soppressioni critiche ampie", "warning" if count else "ok", f"{count} regole di soppressione critiche ampie trovate.", {"count": count}, "Restringi le soppressioni critiche e aggiungi una scadenza." if count else "")


def _critical_notification_check():
    enabled = [channel for channel in SecurityNotificationChannel.objects.filter(enabled=True) if SEVERITY_ORDER.get(channel.severity_min, 99) <= SEVERITY_ORDER[Severity.CRITICAL]]
    return _check("critical_notification_channel", "Copertura notifiche critiche", "ok" if enabled else "warning", f"{len(enabled)} canali attivi possono notificare alert critici.", {"enabled_channels": [channel.name for channel in enabled]}, "Attiva almeno un canale notifica per alert critici." if not enabled else "")


def _health_cards(checks):
    by_code = {check["code"]: check for check in checks}
    mapping = [
        ("Database", "database"),
        ("Migrations", "migrations"),
        ("Security config seeded", "security_config_seeded"),
        ("Parser registry", "registry_parsers_have_config"),
        ("Alert rules", "critical_alert_rules"),
        ("Suppression rules", "expired_active_suppressions"),
        ("Backup expectations", "backup_expected_jobs"),
        ("Notification channels", "notification_required_configuration"),
        ("Recent parser errors", "recent_parser_errors"),
        ("Recent alert generation", "recent_alert_generation"),
    ]
    return [{"label": label, **by_code.get(code, _check(code, label, "warning", "Controllo non disponibile."))} for label, code in mapping]


def _source_match_reason(source, sender="", subject="", body=""):
    sender_match = _first_matching_pattern(source.mailbox_sender_patterns, sender)
    subject_match = _first_matching_pattern(source.mailbox_subject_patterns, subject)
    if source.mailbox_sender_patterns and source.mailbox_subject_patterns:
        return (bool(sender_match and subject_match), f"pattern mittente {sender_match}; pattern oggetto {subject_match}" if sender_match and subject_match else "pattern mittente e oggetto non corrispondono entrambi")
    if sender_match:
        return True, f"pattern mittente {sender_match}"
    if subject_match:
        return True, f"pattern oggetto {subject_match}"
    tokens = (source.metadata_json or {}).get("match_tokens", []) if not source.mailbox_sender_patterns and not source.mailbox_subject_patterns else []
    token_match = _first_matching_pattern(tokens, f"{sender or ''}\n{subject or ''}\n{body or ''}")
    if token_match:
        return True, f"token metadati {token_match}"
    return False, "Nessun pattern mittente, oggetto o metadati corrisponde."


def _first_matching_pattern(patterns, value):
    value = value or ""
    for pattern in patterns or []:
        pattern = str(pattern or "").strip()
        if not pattern:
            continue
        if pattern.startswith("regex:") and re.search(pattern[6:], value, re.I):
            return pattern
        if fnmatch.fnmatch(value.lower(), pattern.lower()) or pattern.lower() in value.lower():
            return pattern
    return ""


def _recent_source_activity(parser_name):
    since = timezone.now() - timezone.timedelta(days=7)
    source_names = SecuritySourceConfig.objects.filter(parser_name=parser_name).values_list("name", flat=True)
    return SecurityReport.objects.filter(source__name__in=source_names, created_at__gte=since).exists()


def _invalid_threshold(rule):
    if rule.condition_operator in {"gt", "gte", "lt", "lte", "baseline_deviation"}:
        try:
            float(rule.threshold_value)
        except (TypeError, ValueError):
            return True
    return False


def _is_defender_critical_cve_rule(rule):
    text = f"{rule.code} {rule.name} {rule.source_type} {rule.metric_name}".lower()
    return rule.enabled and rule.severity == Severity.CRITICAL and "defender" in text and ("cve" in text or rule.metric_name in {"cvss", "exposed_devices"})


def _setting_value_matches(value, value_type):
    if value_type == SettingValueType.BOOL:
        return isinstance(value, bool)
    if value_type == SettingValueType.INT:
        return isinstance(value, int) and not isinstance(value, bool)
    if value_type == SettingValueType.FLOAT:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if value_type == SettingValueType.JSON:
        return isinstance(value, (dict, list))
    if value_type == SettingValueType.STRING:
        return isinstance(value, str)
    return False


def _masked_channel_destination(channel):
    if channel.channel_type == "teams_webhook":
        return "********" if channel.webhook_url_secret_ref else ""
    if channel.channel_type == "email":
        recipients = [part.strip() for part in channel.recipients.replace(";", ",").split(",") if part.strip()]
        return ", ".join(_mask_email(recipient) for recipient in recipients)
    return "dashboard"


def _mask_email(value):
    if "@" not in value:
        return "***"
    name, domain = value.split("@", 1)
    return f"{name[:1]}***@{domain}"


def _activity(when, activity_type, title, source, status):
    return {"when": when, "type": activity_type, "title": title[:255], "source": source, "status": status}


def _check(code, label, status, message, details=None, suggested_action=""):
    return {
        "code": code,
        "label": label,
        "status": status,
        "message": message,
        "details": details or {},
        "suggested_action": suggested_action,
    }


def _rollup_status(checks):
    if any(check["status"] == "error" for check in checks):
        return "error"
    if any(check["status"] == "warning" for check in checks):
        return "warning"
    return "ok"
