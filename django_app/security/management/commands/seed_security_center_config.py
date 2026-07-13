from django.core.management.base import BaseCommand

from security.models import (
    BackupExpectedJobConfig,
    SecurityAlertRuleConfig,
    SecurityCenterSetting,
    SecurityNotificationChannel,
    SecurityParserConfig,
    SecuritySourceConfig,
    SecurityTicketConfig,
    SettingValueType,
)
from security.parsers.load import *  # noqa: F403,F401
from security.parsers import parser_registry


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


class Command(BaseCommand):
    help = "Seed persistent Security Center AI admin configuration defaults."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--reset", action="store_true")
        parser.add_argument("--only", choices=["general", "sources", "parsers", "alert_rules", "notifications", "ticketing", "backups"])

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        section = options.get("only")
        if options["reset"] and not dry_run:
            self._reset(section)
        seeders = {
            "general": self._seed_general,
            "sources": self._seed_sources,
            "parsers": self._seed_parsers,
            "alert_rules": self._seed_alert_rules,
            "notifications": self._seed_notifications,
            "ticketing": self._seed_ticketing,
            "backups": self._seed_backups,
        }
        for name, seeder in seeders.items():
            if section and section != name:
                continue
            count = seeder(dry_run)
            self.stdout.write(f"{name}: {count} defaults {'would be seeded' if dry_run else 'seeded'}")

    def _reset(self, section):
        mapping = {
            "general": [SecurityCenterSetting],
            "sources": [SecuritySourceConfig],
            "parsers": [SecurityParserConfig],
            "alert_rules": [SecurityAlertRuleConfig],
            "notifications": [SecurityNotificationChannel],
            "ticketing": [SecurityTicketConfig],
            "backups": [BackupExpectedJobConfig],
        }
        models = mapping.get(section) if section else [model for group in mapping.values() for model in group]
        for model in models:
            model.objects.all().delete()

    def _seed_general(self, dry_run):
        if dry_run:
            return len(GENERAL_SETTINGS)
        for key, value, value_type, category, description in GENERAL_SETTINGS:
            SecurityCenterSetting.objects.update_or_create(
                key=key,
                defaults={"value": value, "value_type": value_type, "category": category, "description": description},
            )
        return len(GENERAL_SETTINGS)

    def _seed_sources(self, dry_run):
        if dry_run:
            return len(SOURCES)
        for source in SOURCES:
            defaults = {"enabled": source.get("enabled", True), "expected_frequency": "daily", "description": source["name"], **source}
            name = defaults.pop("name")
            SecuritySourceConfig.objects.update_or_create(name=name, defaults=defaults)
        return len(SOURCES)

    def _seed_parsers(self, dry_run):
        parsers = parser_registry.all()
        if dry_run:
            return len(parsers)
        for priority, parser in enumerate(parsers, start=10):
            SecurityParserConfig.objects.update_or_create(
                parser_name=parser.name,
                defaults={
                    "enabled": True,
                    "priority": priority,
                    "source_type": ",".join(getattr(parser, "supported_source_types", ()) or []),
                    "input_type": "email,pdf,csv,text",
                    "description": parser.__class__.__name__,
                },
            )
        return len(parsers)

    def _seed_alert_rules(self, dry_run):
        if dry_run:
            return len(ALERT_RULES)
        for code, name, source_type, metric, operator, threshold, severity, ticket in ALERT_RULES:
            SecurityAlertRuleConfig.objects.update_or_create(
                code=code,
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
            )
        return len(ALERT_RULES)

    def _seed_notifications(self, dry_run):
        if dry_run:
            return 1
        SecurityNotificationChannel.objects.update_or_create(
            name="Dashboard only",
            defaults={"channel_type": "dashboard", "enabled": True, "severity_min": "info", "cooldown_minutes": 0},
        )
        return 1

    def _seed_ticketing(self, dry_run):
        if dry_run:
            return 1
        SecurityTicketConfig.objects.update_or_create(
            pk=1,
            defaults={
                "aggregation_strategy": "per_product",
                "statuses": ["new", "open", "in_progress", "resolved", "closed"],
                "sla_by_severity": {"critical": 4, "high": 8, "medium": 24, "low": 72},
                "auto_close_enabled": False,
                "reopen_on_recurrence": True,
            },
        )
        return 1

    def _seed_backups(self, dry_run):
        if dry_run:
            return 1
        BackupExpectedJobConfig.objects.update_or_create(
            job_name="Daily endpoint backup",
            device_name="",
            nas_name="",
            defaults={"enabled": False, "expected_days_of_week": [0, 1, 2, 3, 4], "missing_after_hours": 30},
        )
        return 1
