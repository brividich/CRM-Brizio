"""Autoconfigurazione del Security Center (SOC IT - CN).

Fonte unica dei default di configurazione: la usano sia il comando
``seed_security_center_config`` sia la pagina ``/soc/admin/autoconfig/``.
Prima i default vivevano solo dentro il management command, quindi configurare
il SOC richiedeva l'accesso alla shell del server; la diagnostica sapeva dire
"manca la configurazione" ma non poteva porvi rimedio.

Regole di questo modulo:

- ogni scrittura e' idempotente (chiave naturale + ``get_or_create``);
- ogni scrittura passa da ``audit_config_change``: chi ha applicato cosa resta
  tracciato come per le modifiche fatte a mano nel Configuration Studio;
- l'apply dalla UI **non sovrascrive** i record esistenti (le personalizzazioni
  dell'operatore vincono); il riallineamento ai default e' un'azione esplicita
  (``overwrite=True``, che e' anche il comportamento storico del comando CLI);
- nessun fix cancella dati: al massimo disattiva (soppressioni scadute).
"""

from dataclasses import dataclass, field
from typing import Any, Callable

from django.utils import timezone

from ..models import (
    BackupExpectedJobConfig,
    SecurityAlertRuleConfig,
    SecurityAlertSuppressionRule,
    SecurityCenterSetting,
    SecurityNotificationChannel,
    SecurityParserConfig,
    SecuritySourceConfig,
    SecurityTicketConfig,
    SettingValueType,
    Severity,
)
from ..parsers.load import *  # noqa: F403,F401  (registra i parser nel registry)
from ..parsers import parser_registry
from .configuration import audit_config_change


# --------------------------------------------------------------------------
# Default di configurazione
# --------------------------------------------------------------------------

GENERAL_SETTINGS = [
    ("instance_name", "Security Center AI", SettingValueType.STRING, "general", "Instance display name"),
    ("organization_name", "Organization", SettingValueType.STRING, "general", "Organization name"),
    ("default_timezone", "Europe/Rome", SettingValueType.STRING, "general", "Default timezone"),
    ("default_dashboard_period", "week", SettingValueType.STRING, "dashboard", "Default dashboard period: day/week/month"),
    ("kpi_retention_days", 365, SettingValueType.INT, "retention", "KPI retention in days"),
    ("report_retention_days", 365, SettingValueType.INT, "retention", "Report retention in days"),
    ("evidence_retention_days", 730, SettingValueType.INT, "retention", "Evidence retention in days"),
    ("automatic_alert_generation_enabled", True, SettingValueType.BOOL, "alerts", "Generate alerts automatically"),
    ("ticket_auto_creation_enabled", False, SettingValueType.BOOL, "ticketing", "Create remediation tickets automatically"),
    ("email_notification_enabled", False, SettingValueType.BOOL, "notifications", "Enable email notifications"),
    ("teams_notification_enabled", False, SettingValueType.BOOL, "notifications", "Enable Teams notifications"),
    ("default_critical_sla_hours", 4, SettingValueType.INT, "sla", "Critical SLA hours"),
    ("default_high_sla_hours", 8, SettingValueType.INT, "sla", "High SLA hours"),
    ("default_medium_sla_hours", 24, SettingValueType.INT, "sla", "Medium SLA hours"),
    ("default_low_sla_hours", 72, SettingValueType.INT, "sla", "Low SLA hours"),
]

SOURCES = [
    {
        "name": "WatchGuard Dimension / Firebox",
        "source_type": "watchguard_dimension_firebox",
        "vendor": "WatchGuard",
        "parser_name": "watchguard_report_parser",
        "mailbox_sender_patterns": ["*watchguard*", "*firebox*"],
        "mailbox_subject_patterns": ["*WatchGuard*", "*Firebox*", "*Dimension*"],
    },
    {"name": "WatchGuard EPDR", "source_type": "watchguard_epdr", "vendor": "WatchGuard", "parser_name": "watchguard_report_parser", "mailbox_subject_patterns": ["*EPDR*"]},
    {"name": "WatchGuard ThreatSync", "source_type": "watchguard_threatsync", "vendor": "WatchGuard", "parser_name": "watchguard_report_parser", "mailbox_subject_patterns": ["*ThreatSync*"]},
    {"name": "Microsoft Defender", "source_type": "microsoft_defender", "vendor": "Microsoft", "parser_name": "microsoft_defender_vulnerability_notification_email_parser", "mailbox_sender_patterns": ["defender-noreply@microsoft.com", "*microsoft*"], "mailbox_subject_patterns": ["*Defender*", "*vulnerabilities*"]},
    {"name": "Synology/NAS Backup", "source_type": "synology_backup", "vendor": "Synology", "parser_name": "synology_active_backup_email_parser", "mailbox_subject_patterns": ["*Active Backup*", "*backup*"]},
    {"name": "Generic email source", "source_type": "generic_email", "vendor": "", "parser_name": "", "enabled": True},
    {"name": "Manual upload", "source_type": "manual_upload", "vendor": "", "parser_name": "", "enabled": True},
]

ALERT_RULES = [
    ("defender_critical_cve_cvss_gte_9", "Defender critical CVE CVSS >= 9", "microsoft_defender", "cvss", "gte", "9", "critical", True),
    ("defender_critical_cve_exposed_devices_gt_0", "Defender exposed devices > 0", "microsoft_defender", "exposed_devices", "gt", "0", "critical", True),
    ("watchguard_vpn_denied_gt_0", "WatchGuard VPN denied > 0", "watchguard", "vpn_denied_count", "gt", "0", "warning", False),
    ("watchguard_vpn_new_ip_detected", "WatchGuard VPN new IP detected", "watchguard", "new_ip_detected", "eq", "true", "warning", False),
    ("watchguard_botnet_detected_gt_baseline", "WatchGuard botnet above baseline", "watchguard", "botnet_detected_count", "baseline_deviation", "1", "high", False),
    ("watchguard_sdwan_loss_gt_threshold", "WatchGuard SD-WAN loss threshold", "watchguard", "packet_loss_percent", "gt", "5", "warning", False),
    ("backup_failed_gt_0", "Backup failed > 0", "synology_backup", "backup_failed_count", "gt", "0", "warning", True),
    ("backup_missing_expected_job", "Backup missing expected job", "synology_backup", "missing_jobs", "gt", "0", "warning", True),
    ("backup_duration_anomaly", "Backup duration anomaly", "synology_backup", "duration_minutes", "gt", "0", "warning", False),
    ("backup_transferred_size_anomaly", "Backup transferred size anomaly", "synology_backup", "transferred_size_gb", "baseline_deviation", "0", "warning", False),
]

DASHBOARD_CHANNEL_NAME = "Dashboard only"
DEFAULT_BACKUP_JOB_NAME = "Daily endpoint backup"


# --------------------------------------------------------------------------
# Sezioni
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DesiredRecord:
    """Riga di configurazione che l'autoconfig vuole veder esistere."""

    model: Any
    lookup: dict
    defaults: dict
    label: str


@dataclass(frozen=True)
class Section:
    key: str
    label: str
    description: str
    records: Callable[[], list]
    reset_models: tuple = field(default_factory=tuple)


def _general_records():
    return [
        DesiredRecord(
            model=SecurityCenterSetting,
            lookup={"key": key},
            defaults={"value": value, "value_type": value_type, "category": category, "description": description},
            label=key,
        )
        for key, value, value_type, category, description in GENERAL_SETTINGS
    ]


def _source_records():
    records = []
    for source in SOURCES:
        defaults = {"enabled": source.get("enabled", True), "expected_frequency": "daily", "description": source["name"], **source}
        name = defaults.pop("name")
        records.append(DesiredRecord(model=SecuritySourceConfig, lookup={"name": name}, defaults=defaults, label=name))
    return records


def _parser_records():
    records = []
    for priority, parser in enumerate(parser_registry.all(), start=10):
        records.append(
            DesiredRecord(
                model=SecurityParserConfig,
                lookup={"parser_name": parser.name},
                defaults={
                    "enabled": True,
                    "priority": priority,
                    "source_type": ",".join(getattr(parser, "supported_source_types", ()) or []),
                    "input_type": "email,pdf,csv,text",
                    "description": parser.__class__.__name__,
                },
                label=parser.name,
            )
        )
    return records


def _alert_rule_records():
    return [
        DesiredRecord(
            model=SecurityAlertRuleConfig,
            lookup={"code": code},
            defaults={
                "name": name,
                "enabled": True,
                "source_type": source_type,
                "metric_name": metric,
                "condition_operator": operator,
                "threshold_value": threshold,
                "severity": severity,
                "auto_create_ticket": ticket,
                "auto_create_evidence_container": True,
            },
            label=code,
        )
        for code, name, source_type, metric, operator, threshold, severity, ticket in ALERT_RULES
    ]


def _notification_records():
    return [
        DesiredRecord(
            model=SecurityNotificationChannel,
            lookup={"name": DASHBOARD_CHANNEL_NAME},
            defaults={"channel_type": "dashboard", "enabled": True, "severity_min": "info", "cooldown_minutes": 0},
            label=DASHBOARD_CHANNEL_NAME,
        )
    ]


def _ticketing_records():
    return [
        DesiredRecord(
            model=SecurityTicketConfig,
            lookup={"pk": 1},
            defaults={
                "aggregation_strategy": "per_product",
                "statuses": ["new", "open", "in_progress", "resolved", "closed"],
                "sla_by_severity": {"critical": 4, "high": 8, "medium": 24, "low": 72},
                "auto_close_enabled": False,
                "reopen_on_recurrence": True,
            },
            label="Configurazione ticketing",
        )
    ]


def _backup_records():
    return [
        DesiredRecord(
            model=BackupExpectedJobConfig,
            lookup={"job_name": DEFAULT_BACKUP_JOB_NAME, "device_name": "", "nas_name": ""},
            defaults={"enabled": False, "expected_days_of_week": [0, 1, 2, 3, 4], "missing_after_hours": 30},
            label=DEFAULT_BACKUP_JOB_NAME,
        )
    ]


SECTIONS = [
    Section("general", "Impostazioni generali", "Nome istanza, fusi orari, ritenzione dati e SLA di default.", _general_records, (SecurityCenterSetting,)),
    Section("sources", "Sorgenti", "Sorgenti WatchGuard, Defender, Synology, email generica e upload manuale.", _source_records, (SecuritySourceConfig,)),
    Section("parsers", "Parser", "Una riga di configurazione per ogni parser registrato nel registry.", _parser_records, (SecurityParserConfig,)),
    Section("alert_rules", "Regole alert", "Regole CVE critiche Defender, VPN/botnet WatchGuard e backup falliti.", _alert_rule_records, (SecurityAlertRuleConfig,)),
    Section("notifications", "Notifiche", "Canale dashboard, prerequisito per la copertura degli alert critici.", _notification_records, (SecurityNotificationChannel,)),
    Section("ticketing", "Ticketing", "Strategia di aggregazione, stati e SLA per severita.", _ticketing_records, (SecurityTicketConfig,)),
    Section("backups", "Backup attesi", "Job di backup atteso di esempio (creato disattivato).", _backup_records, (BackupExpectedJobConfig,)),
]

SECTION_KEYS = [section.key for section in SECTIONS]
SECTIONS_BY_KEY = {section.key: section for section in SECTIONS}


def _selected_sections(sections=None):
    if not sections:
        return list(SECTIONS)
    if isinstance(sections, str):
        sections = [sections]
    unknown = [key for key in sections if key not in SECTIONS_BY_KEY]
    if unknown:
        raise ValueError(f"Sezioni autoconfig sconosciute: {', '.join(unknown)}")
    return [SECTIONS_BY_KEY[key] for key in SECTION_KEYS if key in set(sections)]


# --------------------------------------------------------------------------
# Piano / applicazione
# --------------------------------------------------------------------------

def _differing_fields(instance, defaults):
    """Campi il cui valore a DB si discosta dal default dell'autoconfig."""
    differing = {}
    for name, expected in defaults.items():
        current = getattr(instance, name, None)
        if current != expected:
            differing[name] = (current, expected)
    return differing


def plan_autoconfig(sections=None):
    """Cosa farebbe l'autoconfig, senza scrivere nulla.

    Ritorna una riga per sezione con gli elementi da creare, quelli difformi dai
    default e quelli gia' allineati.
    """
    plan = []
    for section in _selected_sections(sections):
        to_create, to_align, aligned = [], [], []
        for record in section.records():
            instance = record.model.objects.filter(**record.lookup).first()
            if instance is None:
                to_create.append(record.label)
            elif _differing_fields(instance, record.defaults):
                to_align.append(record.label)
            else:
                aligned.append(record.label)
        plan.append(
            {
                "key": section.key,
                "label": section.label,
                "description": section.description,
                "to_create": to_create,
                "to_align": to_align,
                "aligned": aligned,
                "total": len(to_create) + len(to_align) + len(aligned),
                "status": "missing" if to_create else ("drifted" if to_align else "ok"),
            }
        )
    return plan


def plan_summary(plan):
    return {
        "to_create": sum(len(row["to_create"]) for row in plan),
        "to_align": sum(len(row["to_align"]) for row in plan),
        "aligned": sum(len(row["aligned"]) for row in plan),
        "sections_missing": sum(1 for row in plan if row["status"] == "missing"),
        "sections_drifted": sum(1 for row in plan if row["status"] == "drifted"),
    }


def apply_autoconfig(sections=None, *, actor=None, request=None, overwrite=False):
    """Crea la configurazione mancante (e, se ``overwrite``, riallinea l'esistente).

    Senza ``overwrite`` i record gia' presenti non vengono toccati: le soglie
    personalizzate dall'operatore non devono essere resettate da un click.
    """
    results = []
    for section in _selected_sections(sections):
        created, updated, skipped = [], [], []
        for record in section.records():
            instance = record.model.objects.filter(**record.lookup).first()
            if instance is None:
                instance = record.model.objects.create(**record.lookup, **record.defaults)
                audit_config_change(actor, "autoconfig_create", instance, request=request, new_value=record.label)
                created.append(record.label)
                continue
            differing = _differing_fields(instance, record.defaults)
            if not differing:
                continue
            if not overwrite:
                skipped.append(record.label)
                continue
            for name, (old_value, new_value) in differing.items():
                setattr(instance, name, new_value)
                audit_config_change(actor, "autoconfig_align", instance, name, old_value, new_value, request=request)
            instance.save(update_fields=list(differing))
            updated.append(record.label)
        results.append(
            {
                "key": section.key,
                "label": section.label,
                "created": created,
                "updated": updated,
                "skipped": skipped,
            }
        )
    return {
        "sections": results,
        "created": sum(len(row["created"]) for row in results),
        "updated": sum(len(row["updated"]) for row in results),
        "skipped": sum(len(row["skipped"]) for row in results),
        "overwrite": overwrite,
        "applied_at": timezone.now(),
    }


def reset_sections(sections=None):
    """Svuota le tabelle di configurazione delle sezioni indicate (solo CLI)."""
    deleted = 0
    for section in _selected_sections(sections):
        for model in section.reset_models:
            deleted += model.objects.all().delete()[0]
    return deleted


# --------------------------------------------------------------------------
# Fix guidati (derivati dai check diagnostici)
# --------------------------------------------------------------------------

def _fix_seed_missing_config(actor=None, request=None):
    result = apply_autoconfig(actor=actor, request=request)
    return {"message": f"{result['created']} elementi di configurazione creati.", "details": result}


def _fix_section(section_key):
    def handler(actor=None, request=None):
        result = apply_autoconfig([section_key], actor=actor, request=request)
        return {"message": f"{result['created']} elementi creati nella sezione {SECTIONS_BY_KEY[section_key].label}.", "details": result}

    return handler


def _enable_queryset(queryset, actor, request, field_name="enabled"):
    changed = []
    for instance in queryset:
        setattr(instance, field_name, True)
        instance.save(update_fields=[field_name])
        audit_config_change(actor, "autoconfig_fix", instance, field_name, False, True, request=request)
        changed.append(str(instance))
    return changed


def _fix_enable_sources(actor=None, request=None):
    if not SecuritySourceConfig.objects.exists():
        return _fix_section("sources")(actor=actor, request=request)
    changed = _enable_queryset(SecuritySourceConfig.objects.filter(enabled=False), actor, request)
    return {"message": f"{len(changed)} sorgenti attivate.", "details": {"changed": changed}}


def _fix_enable_parsers(actor=None, request=None):
    if not SecurityParserConfig.objects.exists():
        return _fix_section("parsers")(actor=actor, request=request)
    changed = _enable_queryset(SecurityParserConfig.objects.filter(enabled=False), actor, request)
    return {"message": f"{len(changed)} parser attivati.", "details": {"changed": changed}}


def _fix_critical_rules(actor=None, request=None):
    created = apply_autoconfig(["alert_rules"], actor=actor, request=request)
    changed = _enable_queryset(
        SecurityAlertRuleConfig.objects.filter(enabled=False, severity=Severity.CRITICAL), actor, request
    )
    return {
        "message": f"{created['created']} regole create, {len(changed)} regole critiche attivate.",
        "details": {"created": created, "enabled": changed},
    }


def _fix_defender_critical_tickets(actor=None, request=None):
    changed = []
    for rule in SecurityAlertRuleConfig.objects.filter(
        enabled=True, severity=Severity.CRITICAL, source_type__icontains="defender", auto_create_ticket=False
    ):
        rule.auto_create_ticket = True
        rule.save(update_fields=["auto_create_ticket"])
        audit_config_change(actor, "autoconfig_fix", rule, "auto_create_ticket", False, True, request=request)
        changed.append(rule.code)
    return {"message": f"{len(changed)} regole critiche Defender ora aprono ticket.", "details": {"changed": changed}}


def _fix_critical_notification_channel(actor=None, request=None):
    channel = SecurityNotificationChannel.objects.filter(channel_type="dashboard").first()
    if channel is None:
        return _fix_section("notifications")(actor=actor, request=request)
    if not channel.enabled:
        channel.enabled = True
        channel.save(update_fields=["enabled"])
        audit_config_change(actor, "autoconfig_fix", channel, "enabled", False, True, request=request)
        return {"message": f"Canale «{channel.name}» attivato.", "details": {"changed": [channel.name]}}
    return {"message": "Nessun canale da attivare.", "details": {"changed": []}}


def _fix_expired_suppressions(actor=None, request=None):
    changed = []
    for rule in SecurityAlertSuppressionRule.objects.filter(is_active=True, expires_at__lte=timezone.now()):
        rule.is_active = False
        rule.save(update_fields=["is_active"])
        audit_config_change(actor, "autoconfig_fix", rule, "is_active", True, False, request=request)
        changed.append(rule.name)
    return {"message": f"{len(changed)} soppressioni scadute disattivate.", "details": {"changed": changed}}


@dataclass(frozen=True)
class Fix:
    code: str
    check_code: str
    label: str
    description: str
    handler: Callable


FIXES = [
    Fix("seed_config", "security_config_seeded", "Semina la configurazione mancante", "Crea impostazioni, sorgenti, parser, regole, notifiche, ticketing e backup attesi assenti.", _fix_seed_missing_config),
    Fix("enable_sources", "enabled_sources", "Attiva le sorgenti", "Attiva le sorgenti disattivate; se non ne esiste nessuna, semina quelle di default.", _fix_enable_sources),
    Fix("enable_parsers", "enabled_parsers", "Attiva i parser", "Attiva i parser disattivati; se non ne esiste nessuno, semina quelli del registry.", _fix_enable_parsers),
    Fix("seed_parser_configs", "registry_parsers_have_config", "Configura i parser del registry", "Crea la riga di configurazione per i parser registrati che non ne hanno una.", _fix_section("parsers")),
    Fix("enable_critical_rules", "critical_alert_rules", "Attiva le regole alert critiche", "Semina le regole di default e attiva quelle con severita critica.", _fix_critical_rules),
    Fix("create_ticket_config", "ticket_auto_creation_config", "Crea la configurazione ticketing", "Crea la configurazione ticket con SLA per severita (4/8/24/72 ore).", _fix_section("ticketing")),
    Fix("create_dashboard_channel", "dashboard_notification_channel", "Crea il canale notifica dashboard", "Crea il canale «Dashboard only», prerequisito delle notifiche in-app.", _fix_section("notifications")),
    Fix("enable_critical_notifications", "critical_notification_channel", "Copri le notifiche critiche", "Attiva (o crea) un canale in grado di notificare gli alert critici.", _fix_critical_notification_channel),
    Fix("defender_critical_tickets", "defender_critical_auto_ticket", "Ticket automatici CVE critiche Defender", "Attiva la creazione automatica del ticket sulle regole critiche Defender.", _fix_defender_critical_tickets),
    Fix("expire_suppressions", "expired_active_suppressions", "Disattiva le soppressioni scadute", "Porta a non attive le regole di soppressione con scadenza passata.", _fix_expired_suppressions),
]

FIXES_BY_CODE = {fix.code: fix for fix in FIXES}


def available_fixes(diagnostics=None):
    """Fix applicabili adesso: solo quelli il cui check diagnostico non e' ok."""
    if diagnostics is None:
        from .diagnostics import run_security_center_diagnostics

        diagnostics = run_security_center_diagnostics()
    checks = {check["code"]: check for check in diagnostics.get("checks", [])}
    rows = []
    for fix in FIXES:
        check = checks.get(fix.check_code)
        if not check or check.get("status") == "ok":
            continue
        rows.append(
            {
                "code": fix.code,
                "label": fix.label,
                "description": fix.description,
                "check_code": fix.check_code,
                "check_label": check.get("label", fix.check_code),
                "check_status": check.get("status", "warning"),
                "check_message": check.get("message", ""),
            }
        )
    return rows


def apply_fix(code, *, actor=None, request=None):
    fix = FIXES_BY_CODE.get(code)
    if fix is None:
        raise ValueError(f"Fix autoconfig sconosciuto: {code}")
    result = fix.handler(actor=actor, request=request)
    result["code"] = fix.code
    result["label"] = fix.label
    return result
