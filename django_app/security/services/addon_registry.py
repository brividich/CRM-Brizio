from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db.models import Max, Q
from django.urls import reverse

from security.models import (
    BackupExpectedJobConfig,
    SecurityAlert,
    SecurityAlertRuleConfig,
    SecurityAlertSuppressionRule,
    SecurityParserConfig,
    SecurityRemediationTicket,
    SecurityReport,
    SecuritySource,
    SecuritySourceConfig,
    Severity,
    Status,
)
from security.parsers.load import *  # noqa: F403,F401
from security.parsers import parser_registry


ACTIVE_ALERT_STATUSES = [
    Status.NEW,
    Status.OPEN,
    Status.ACKNOWLEDGED,
    Status.IN_PROGRESS,
    Status.SNOOZED,
    Status.MUTED,
]
ACTIVE_TICKET_STATUSES = [Status.NEW, Status.OPEN, Status.IN_PROGRESS]


@dataclass(frozen=True)
class AddonDefinition:
    code: str
    name: str
    vendor: str
    description: str
    documentation_file: str
    source_tokens: tuple[str, ...]
    parser_tokens: tuple[str, ...]
    parser_names: tuple[str, ...]
    rule_prefixes: tuple[str, ...]
    source_systems: tuple[str, ...] = ()
    important_parser_names: tuple[str, ...] = ()
    important_rule_codes: tuple[str, ...] = ()
    include_backup_jobs: bool = False


ADDONS = [
    AddonDefinition(
        code="watchguard",
        name="WatchGuard",
        vendor="WatchGuard",
        description="Report operativi WatchGuard Dimension, Firebox, EPDR e ThreatSync.",
        documentation_file="04_WATCHGUARD_ADDON.md",
        source_tokens=("watchguard", "firebox", "dimension", "epdr", "threatsync"),
        parser_tokens=("watchguard",),
        parser_names=(
            "watchguard_report_parser",
            "watchguard_firebox_authentication_denied_csv_parser",
            "watchguard_firebox_authentication_allowed_csv_parser",
            "watchguard_epdr_executive_report_parser",
        ),
        rule_prefixes=("watchguard_",),
        important_parser_names=("watchguard_report_parser",),
        important_rule_codes=("watchguard_vpn_denied_gt_0",),
    ),
    AddonDefinition(
        code="microsoft_defender",
        name="Microsoft Defender",
        vendor="Microsoft",
        description="Notifiche vulnerabilita Microsoft Defender, evidenze CVE e ticket di remediation.",
        documentation_file="05_DEFENDER_ADDON.md",
        source_tokens=("microsoft", "defender"),
        parser_tokens=("microsoft_defender", "defender"),
        parser_names=("microsoft_defender_vulnerability_notification_email_parser",),
        rule_prefixes=("defender_",),
        source_systems=("microsoft_defender",),
        important_parser_names=("microsoft_defender_vulnerability_notification_email_parser",),
        important_rule_codes=("defender_critical_cve_cvss_gte_9", "defender_critical_cve_exposed_devices_gt_0"),
    ),
    AddonDefinition(
        code="backup_nas",
        name="Backup/NAS",
        vendor="Synology / NAS",
        description="Monitoraggio backup e NAS, inclusi i report email Synology Active Backup.",
        documentation_file="06_BACKUP_ADDON.md",
        source_tokens=("backup", "nas", "synology"),
        parser_tokens=("backup", "nas", "synology"),
        parser_names=("synology_active_backup_email_parser",),
        rule_prefixes=("backup_",),
        important_parser_names=("synology_active_backup_email_parser",),
        important_rule_codes=("backup_failed_gt_0", "backup_missing_expected_job"),
        include_backup_jobs=True,
    ),
    AddonDefinition(
        code="microsoft_365",
        name="Microsoft 365",
        vendor="Microsoft",
        description="Segnaposto per futuri segnali operativi Microsoft 365.",
        documentation_file="03_ADDONS.md",
        source_tokens=("microsoft 365", "m365", "office 365"),
        parser_tokens=("microsoft_365", "m365", "office365"),
        parser_names=(),
        rule_prefixes=("m365_", "microsoft_365_"),
    ),
    AddonDefinition(
        code="manual_upload",
        name="Caricamento manuale",
        vendor="Security Center AI",
        description="Segnaposto per report e file caricati manualmente.",
        documentation_file="03_ADDONS.md",
        source_tokens=("manual", "upload"),
        parser_tokens=("manual", "upload"),
        parser_names=(),
        rule_prefixes=("manual_",),
    ),
    AddonDefinition(
        code="generic_email",
        name="Email generica",
        vendor="Security Center AI",
        description="Segnaposto per ingestione mailbox generica senza logica parser specifica per sorgente.",
        documentation_file="03_ADDONS.md",
        source_tokens=("generic", "email"),
        parser_tokens=("generic", "email"),
        parser_names=(),
        rule_prefixes=("generic_",),
    ),
]


def get_addon_registry():
    return [_build_addon(definition, include_detail=False) for definition in ADDONS]


def get_addon_detail(code):
    definition = next((addon for addon in ADDONS if addon.code == code), None)
    if not definition:
        return None
    return _build_addon(definition, include_detail=True)


def _build_addon(definition, include_detail):
    sources = list(SecuritySourceConfig.objects.filter(_source_config_q(definition)).order_by("vendor", "name"))
    runtime_sources = list(SecuritySource.objects.filter(_runtime_source_q(definition)).order_by("vendor", "name"))
    parsers = list(SecurityParserConfig.objects.filter(_parser_q(definition)).order_by("priority", "parser_name"))
    rules = list(SecurityAlertRuleConfig.objects.filter(_rule_q(definition)).order_by("code"))
    reports = SecurityReport.objects.filter(_report_q(definition))
    suppressions = SecurityAlertSuppressionRule.objects.filter(_suppression_q(definition)).order_by("name")
    alerts = SecurityAlert.objects.filter(_alert_q(definition))
    tickets = SecurityRemediationTicket.objects.filter(_ticket_q(definition))
    backup_jobs = _backup_jobs(definition)

    enabled_source_count = sum(1 for source in sources if source.enabled)
    enabled_parser_count = sum(1 for parser in parsers if parser.enabled)
    enabled_rule_count = sum(1 for rule in rules if rule.enabled)
    warnings, misconfigurations = _find_configuration_issues(definition, sources, parsers, rules, reports, suppressions, backup_jobs)
    status = _status(enabled_source_count, enabled_parser_count, warnings, misconfigurations)
    status_reason = _status_reason(status, warnings, misconfigurations)
    parser_names = sorted({parser.parser_name for parser in parsers} | set(definition.parser_names))
    source_types = sorted({source.source_type for source in sources} | {source.source_type for source in runtime_sources if source.source_type})
    warning_count = len(warnings)

    data = {
        "code": definition.code,
        "name": definition.name,
        "vendor": definition.vendor,
        "description": definition.description,
        "status": status,
        "status_label": _status_label(status),
        "status_class": _status_class(status),
        "status_reason": status_reason,
        "source_types": source_types,
        "parser_names": parser_names,
        "total_source_count": len(sources),
        "enabled_source_count": enabled_source_count,
        "total_parser_count": len(parsers),
        "enabled_parser_count": enabled_parser_count,
        "total_rule_count": len(rules),
        "enabled_rule_count": enabled_rule_count,
        "total_backup_expected_job_count": len(backup_jobs),
        "enabled_backup_expected_job_count": sum(1 for job in backup_jobs if job.enabled),
        "open_alert_count": alerts.filter(status__in=ACTIVE_ALERT_STATUSES).count(),
        "critical_alert_count": alerts.filter(status__in=ACTIVE_ALERT_STATUSES, severity=Severity.CRITICAL).count(),
        "open_ticket_count": tickets.filter(status__in=ACTIVE_TICKET_STATUSES).count(),
        "last_report_at": _iso(reports.aggregate(value=Max("created_at"))["value"]),
        "last_parser_warning_at": _iso(reports.filter(parsed_payload__parse_warnings__isnull=False).aggregate(value=Max("created_at"))["value"]),
        "last_parser_error_at": _iso(reports.filter(parse_status="failed").aggregate(value=Max("created_at"))["value"]),
        "warning_count": warning_count,
        "documentation_file": definition.documentation_file,
        "warnings": warnings,
        "misconfigurations": misconfigurations,
        "links": _links(definition),
    }
    if include_detail:
        data.update(
            {
                "sources": [_source_config_dto(source) for source in sources],
                "runtime_sources": [_runtime_source_dto(source) for source in runtime_sources],
                "parsers": [_parser_dto(parser) for parser in parsers],
                "alert_rules": [_rule_dto(rule) for rule in rules],
                "suppressions": [_suppression_dto(rule) for rule in suppressions],
                "alerts_summary": _alerts_summary(alerts),
                "tickets_summary": _tickets_summary(tickets),
                "last_reports": [_report_dto(report) for report in reports.select_related("source").order_by("-created_at")[:10]],
                "backup_expected_jobs": [_backup_job_dto(job) for job in backup_jobs],
            }
        )
    return data


def _find_configuration_issues(definition, sources, parsers, rules, reports, suppressions, backup_jobs):
    warnings = []
    misconfigurations = []
    registry_names = {parser.name for parser in parser_registry.all()}
    parser_names = {parser.parser_name for parser in parsers}
    enabled_parser_names = {parser.parser_name for parser in parsers if parser.enabled}

    if not sources:
        warnings.append("Nessuna configurazione sorgente e associata a questo modulo.")
    for source in sources:
        if source.enabled and source.parser_name and source.parser_name not in parser_names:
            misconfigurations.append(f"La sorgente '{source.name}' fa riferimento al parser mancante '{source.parser_name}'.")
        if source.enabled and source.parser_name and source.parser_name not in enabled_parser_names:
            misconfigurations.append(f"La sorgente '{source.name}' e attiva ma il parser '{source.parser_name}' e disattivato o mancante.")
        if source.enabled and not source.parser_name and definition.important_parser_names:
            misconfigurations.append(f"La sorgente '{source.name}' e attiva senza parser.")

    if parser_names and not any(source.enabled for source in sources):
        misconfigurations.append("Esiste una configurazione parser, ma tutte le sorgenti correlate sono disattivate o mancanti.")
    for parser in parsers:
        if parser.enabled and parser.parser_name not in registry_names:
            misconfigurations.append(f"La configurazione parser '{parser.parser_name}' fa riferimento a un parser assente dal registro codice.")
    for parser_name in definition.important_parser_names:
        parser = next((item for item in parsers if item.parser_name == parser_name), None)
        if not parser:
            warnings.append(f"Il parser importante '{parser_name}' non e configurato.")
        elif not parser.enabled:
            warnings.append(f"Il parser importante '{parser_name}' e disattivato.")
    for rule_code in definition.important_rule_codes:
        rule = next((item for item in rules if item.code == rule_code), None)
        if not rule:
            misconfigurations.append(f"La regola alert critica '{rule_code}' e mancante.")
        elif not rule.enabled:
            warnings.append(f"La regola alert importante '{rule_code}' e disattivata.")

    if reports.filter(parsed_payload__parse_warnings__isnull=False).exists():
        warnings.append("Sono presenti avvisi parser recenti per questo modulo.")
    if suppressions.filter(is_active=True).exists():
        warnings.append("Regole di soppressione attive influenzano questo modulo.")
    if definition.include_backup_jobs and not backup_jobs:
        warnings.append("Nessun job backup atteso e configurato per il monitoraggio Backup/NAS.")
    if not _documentation_exists(definition.documentation_file):
        warnings.append("Il file di documentazione e mancante.")
    return sorted(set(warnings)), sorted(set(misconfigurations))


def _status(enabled_source_count, enabled_parser_count, warnings, misconfigurations):
    if misconfigurations:
        return "misconfigured"
    if enabled_source_count == 0 and enabled_parser_count == 0:
        return "disabled"
    if warnings or enabled_source_count == 0 or enabled_parser_count == 0:
        return "warning"
    return "enabled"


def _status_reason(status, warnings, misconfigurations):
    if status == "misconfigured":
        return misconfigurations[0] if misconfigurations else "La configurazione del modulo richiede attenzione."
    if status == "warning":
        return warnings[0] if warnings else "Il modulo e configurato parzialmente."
    if status == "disabled":
        return "Nessuna sorgente attiva e nessun parser attivo configurati."
    return "Sono disponibili sorgente, parser e copertura regole alert attivi."


def _status_label(status):
    return {
        "enabled": "OK",
        "warning": "Attenzione",
        "disabled": "Disattivato",
        "misconfigured": "Configurazione errata",
    }.get(status, status)


def _status_class(status):
    return "ok" if status == "enabled" else status


def _source_config_q(definition):
    query = Q()
    for token in definition.source_tokens:
        query |= Q(vendor__icontains=token) | Q(source_type__icontains=token) | Q(name__icontains=token) | Q(parser_name__icontains=token)
    for parser_name in definition.parser_names:
        query |= Q(parser_name=parser_name)
    return query


def _runtime_source_q(definition):
    query = Q()
    for token in definition.source_tokens:
        query |= Q(vendor__icontains=token) | Q(source_type__icontains=token) | Q(name__icontains=token)
    return query


def _parser_q(definition):
    query = Q(parser_name__in=definition.parser_names)
    for token in definition.parser_tokens:
        query |= Q(parser_name__icontains=token) | Q(source_type__icontains=token)
    return query


def _rule_q(definition):
    query = Q()
    for prefix in definition.rule_prefixes:
        query |= Q(code__startswith=prefix)
    for token in definition.source_tokens:
        query |= Q(source_type__icontains=token)
    return query


def _report_q(definition):
    query = Q(parser_name__in=definition.parser_names)
    for token in definition.parser_tokens:
        query |= Q(parser_name__icontains=token) | Q(source__vendor__icontains=token) | Q(source__source_type__icontains=token)
    return query


def _alert_q(definition):
    query = Q(pk__isnull=True)
    for token in definition.source_tokens:
        query |= Q(source__vendor__icontains=token) | Q(source__source_type__icontains=token) | Q(source__name__icontains=token)
    for prefix in definition.rule_prefixes:
        query |= Q(decision_trace__rule_code__startswith=prefix)
    return query


def _ticket_q(definition):
    query = Q()
    for token in definition.source_tokens:
        query |= Q(source__vendor__icontains=token) | Q(source__source_type__icontains=token) | Q(source__name__icontains=token)
    for source_system in definition.source_systems:
        query |= Q(source_system=source_system)
    return query


def _suppression_q(definition):
    query = Q()
    for token in definition.source_tokens:
        query |= Q(source__vendor__icontains=token) | Q(source__source_type__icontains=token) | Q(source__name__icontains=token)
        query |= Q(event_type__icontains=token) | Q(name__icontains=token)
    return query


def _links(definition):
    detail_url = reverse("security:admin_addon_detail", kwargs={"code": definition.code})
    config_url = reverse("security:admin_config")
    diagnostics_url = reverse("security:admin_diagnostics")
    docs_url = f"{reverse('security:admin_docs')}?file={definition.documentation_file}"
    return {
        "detail": detail_url,
        "config": config_url,
        "diagnostics": diagnostics_url,
        "docs": docs_url,
        "api_detail": reverse("security:api_addon_detail", kwargs={"code": definition.code}),
        "django_config": config_url,
        "django_diagnostics": diagnostics_url,
        "django_docs": docs_url,
    }


def _source_config_dto(source):
    return {
        "name": source.name,
        "vendor": source.vendor,
        "source_type": source.source_type,
        "enabled": source.enabled,
        "parser_name": source.parser_name,
        "expected_frequency": source.expected_frequency,
        "updated_at": _iso(source.updated_at),
    }


def _runtime_source_dto(source):
    return {"name": source.name, "vendor": source.vendor, "source_type": source.source_type, "is_active": source.is_active}


def _parser_dto(parser):
    return {
        "parser_name": parser.parser_name,
        "enabled": parser.enabled,
        "priority": parser.priority,
        "source_type": parser.source_type,
        "input_type": parser.input_type,
        "description": parser.description,
        "updated_at": _iso(parser.updated_at),
    }


def _rule_dto(rule):
    return {
        "code": rule.code,
        "name": rule.name,
        "enabled": rule.enabled,
        "source_type": rule.source_type,
        "metric_name": rule.metric_name,
        "condition_operator": rule.condition_operator,
        "threshold_value": rule.threshold_value,
        "severity": rule.severity,
        "auto_create_ticket": rule.auto_create_ticket,
        "updated_at": _iso(rule.updated_at),
    }


def _suppression_dto(rule):
    return {
        "name": rule.name,
        "source": rule.source.name if rule.source_id else "",
        "event_type": rule.event_type,
        "severity": rule.severity,
        "is_active": rule.is_active,
        "expires_at": _iso(rule.expires_at),
        "hit_count": rule.hit_count,
        "last_hit_at": _iso(rule.last_hit_at),
    }


def _alerts_summary(alerts):
    return {
        "total": alerts.count(),
        "open": alerts.filter(status__in=ACTIVE_ALERT_STATUSES).count(),
        "critical_open": alerts.filter(status__in=ACTIVE_ALERT_STATUSES, severity=Severity.CRITICAL).count(),
    }


def _tickets_summary(tickets):
    return {"total": tickets.count(), "open": tickets.filter(status__in=ACTIVE_TICKET_STATUSES).count()}


def _report_dto(report):
    return {
        "id": report.id,
        "title": report.title,
        "source": report.source.name,
        "report_type": report.report_type,
        "parser_name": report.parser_name,
        "parse_status": report.parse_status,
        "report_date": report.report_date.isoformat() if report.report_date else None,
        "created_at": _iso(report.created_at),
    }


def _backup_jobs(definition):
    if not definition.include_backup_jobs:
        return []
    return list(BackupExpectedJobConfig.objects.order_by("-enabled", "nas_name", "device_name", "job_name"))


def _backup_job_dto(job):
    return {
        "job_name": job.job_name,
        "device_name": job.device_name,
        "nas_name": job.nas_name,
        "enabled": job.enabled,
        "critical_asset": job.critical_asset,
        "missing_after_hours": job.missing_after_hours,
        "alert_on_missing": job.alert_on_missing,
        "alert_on_failure": job.alert_on_failure,
        "updated_at": _iso(job.updated_at),
    }


def _documentation_exists(filename):
    return (Path(settings.BASE_DIR) / "docs" / "security-center" / filename).exists()


def _iso(value):
    return value.isoformat() if value else None
