import json
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from security.models import (
    ParseStatus,
    SecurityMailboxIngestionRun,
    SecurityMailboxMessage,
    SecurityMailboxSource,
    SecuritySource,
    SourceType,
)


DEMO_CODE_PREFIX = "uat-demo-"
DEMO_SOURCE_NAME_PREFIX = "[UAT DEMO]"
DEMO_SUBJECT_PREFIX = "[UAT DEMO]"
DEMO_RAW_BODY_MARKER = "UAT_RAW_BODY_MARKER"


DEMO_MAILBOX_SOURCES = [
    {
        "code": "uat-demo-watchguard-epdr",
        "name": f"{DEMO_SOURCE_NAME_PREFIX} WatchGuard EPDR Demo",
        "vendor": "WatchGuard",
        "mailbox_address": "uat-watchguard-epdr@example.local",
        "description": "Synthetic UAT mailbox source for WatchGuard EPDR demo validation.",
        "sender_allowlist_text": "watchguard-demo@example.com",
        "subject_include_text": "UAT DEMO\nEPDR",
    },
    {
        "code": "uat-demo-watchguard-threatsync",
        "name": f"{DEMO_SOURCE_NAME_PREFIX} WatchGuard ThreatSync Demo",
        "vendor": "WatchGuard",
        "mailbox_address": "uat-threatsync@example.local",
        "description": "Synthetic UAT mailbox source for WatchGuard ThreatSync demo validation.",
        "sender_allowlist_text": "watchguard-demo@example.com",
        "subject_include_text": "UAT DEMO\nThreatSync",
    },
    {
        "code": "uat-demo-watchguard-dimension-firebox",
        "name": f"{DEMO_SOURCE_NAME_PREFIX} WatchGuard Dimension / Firebox Demo",
        "vendor": "WatchGuard",
        "mailbox_address": "uat-firebox@example.local",
        "description": "Synthetic UAT mailbox source for WatchGuard Dimension and Firebox demo validation.",
        "sender_allowlist_text": "watchguard-demo@example.com",
        "subject_include_text": "UAT DEMO\nFirebox\nDimension",
        "attachment_extensions": "csv,txt",
    },
    {
        "code": "uat-demo-microsoft-defender-vulnerability",
        "name": f"{DEMO_SOURCE_NAME_PREFIX} Microsoft Defender Vulnerability Demo",
        "vendor": "Microsoft",
        "mailbox_address": "uat-defender@example.local",
        "description": "Synthetic UAT mailbox source for Microsoft Defender vulnerability demo validation.",
        "sender_allowlist_text": "defender-demo@example.com",
        "subject_include_text": "UAT DEMO\nDefender",
    },
    {
        "code": "uat-demo-nas-synology-backup",
        "name": f"{DEMO_SOURCE_NAME_PREFIX} NAS / Synology Backup Demo",
        "vendor": "Synology",
        "mailbox_address": "uat-backup@example.local",
        "description": "Synthetic UAT mailbox source for Synology backup demo validation.",
        "sender_allowlist_text": "backup-demo@example.com",
        "subject_include_text": "UAT DEMO\nBackup\nSynology",
    },
    {
        "code": "uat-demo-custom-report",
        "name": f"{DEMO_SOURCE_NAME_PREFIX} Custom Report Demo",
        "vendor": "Example Company",
        "mailbox_address": "uat-custom@example.local",
        "description": "Synthetic UAT mailbox source for custom report demo validation.",
        "sender_allowlist_text": "reports-demo@example.com",
        "subject_include_text": "UAT DEMO\nCustom",
    },
]


DEMO_MESSAGES = [
    {
        "source_code": "uat-demo-microsoft-defender-vulnerability",
        "external_id": "uat_demo_defender_critical_vulnerability",
        "sender": "defender-demo@example.com",
        "subject": f"{DEMO_SUBJECT_PREFIX} Defender critical vulnerability notification",
        "body": (
            f"{DEMO_RAW_BODY_MARKER}_DEFENDER\n"
            "Microsoft Defender synthetic vulnerability digest for Example Company.\n"
            "Finding: CVE-2099-FAKE-0001, severity Critical, CVSS 9.8.\n"
            "Affected asset: EXAMPLE-HOST-1.example.local.\n"
            "Observed address: 192.0.2.10.\n"
            "Remediation: install synthetic update KB-2099-0001 in the UAT environment."
        ),
        "parse_status": ParseStatus.PARSED,
        "pipeline_result": {
            "status": "success",
            "parser_matched": True,
            "parser_name": "microsoft_defender_vulnerability_notification_email_parser",
            "reports_parsed": 1,
            "metrics_created": 3,
            "events_created": 1,
            "alerts_created": 1,
            "evidence_created": 1,
            "tickets_changed": 1,
        },
    },
    {
        "source_code": "uat-demo-nas-synology-backup",
        "external_id": "uat_demo_synology_backup_completed",
        "sender": "backup-demo@example.com",
        "subject": f"{DEMO_SUBJECT_PREFIX} Synology backup completed notification",
        "body": (
            f"{DEMO_RAW_BODY_MARKER}_BACKUP_COMPLETED\n"
            "Synology Active Backup synthetic completion notice.\n"
            "Job: Example Endpoint Daily Backup.\n"
            "Device: EXAMPLE-HOST-2.example.local.\n"
            "Result: completed successfully.\n"
            "NAS: EXAMPLE-NAS-1.example.local."
        ),
        "parse_status": ParseStatus.PARSED,
        "pipeline_result": {
            "status": "success",
            "parser_matched": True,
            "parser_name": "synology_active_backup_email_parser",
            "reports_parsed": 1,
            "metrics_created": 2,
            "events_created": 1,
            "alerts_created": 0,
            "evidence_created": 0,
            "tickets_changed": 0,
        },
    },
    {
        "source_code": "uat-demo-nas-synology-backup",
        "external_id": "uat_demo_synology_backup_failed",
        "sender": "backup-demo@example.com",
        "subject": f"{DEMO_SUBJECT_PREFIX} Synology backup failed notification",
        "body": (
            f"{DEMO_RAW_BODY_MARKER}_BACKUP_FAILED\n"
            "Synology Active Backup synthetic failure notice.\n"
            "Job: Example Server Weekly Backup.\n"
            "Device: EXAMPLE-HOST-3.example.local.\n"
            "Result: failed.\n"
            "Diagnostic address: 198.51.100.10."
        ),
        "parse_status": ParseStatus.PARSED,
        "pipeline_result": {
            "status": "success",
            "parser_matched": True,
            "parser_name": "synology_active_backup_email_parser",
            "reports_parsed": 1,
            "metrics_created": 2,
            "events_created": 1,
            "alerts_created": 1,
            "evidence_created": 1,
            "tickets_changed": 1,
        },
    },
    {
        "source_code": "uat-demo-watchguard-threatsync",
        "external_id": "uat_demo_threatsync_low_closed_summary",
        "sender": "watchguard-demo@example.com",
        "subject": f"{DEMO_SUBJECT_PREFIX} WatchGuard ThreatSync low closed summary",
        "body": (
            f"{DEMO_RAW_BODY_MARKER}_THREATSYNC_LOW\n"
            "WatchGuard ThreatSync synthetic daily summary.\n"
            "Incidents: 4 low severity, all closed.\n"
            "Endpoint: EXAMPLE-HOST-4.example.local.\n"
            "No critical or high severity incidents in this synthetic report."
        ),
        "parse_status": ParseStatus.PARSED,
        "pipeline_result": {
            "status": "success",
            "parser_matched": True,
            "parser_name": "watchguard_report_parser",
            "reports_parsed": 1,
            "metrics_created": 1,
            "events_created": 4,
            "alerts_created": 0,
            "evidence_created": 0,
            "tickets_changed": 0,
        },
    },
    {
        "source_code": "uat-demo-watchguard-dimension-firebox",
        "external_id": "uat_demo_watchguard_vpn_authentication_csv",
        "sender": "watchguard-demo@example.com",
        "subject": f"{DEMO_SUBJECT_PREFIX} WatchGuard VPN authentication CSV-like content",
        "body": (
            f"{DEMO_RAW_BODY_MARKER}_VPN_CSV\n"
            "timestamp,user,src_ip,result,device\n"
            "2099-01-15T08:00:00Z,user1@example.local,203.0.113.10,allowed,ExampleFW\n"
            "2099-01-15T08:05:00Z,user2@example.local,192.0.2.20,denied,ExampleFW"
        ),
        "parse_status": ParseStatus.PARSED,
        "pipeline_result": {
            "status": "success",
            "parser_matched": True,
            "parser_name": "watchguard_firebox_authentication_denied_csv_parser",
            "reports_parsed": 1,
            "metrics_created": 2,
            "events_created": 2,
            "alerts_created": 1,
            "evidence_created": 1,
            "tickets_changed": 0,
        },
    },
    {
        "source_code": "uat-demo-custom-report",
        "external_id": "uat_demo_custom_report_text",
        "sender": "reports-demo@example.com",
        "subject": f"{DEMO_SUBJECT_PREFIX} Custom report text",
        "body": (
            f"{DEMO_RAW_BODY_MARKER}_CUSTOM\n"
            "Custom synthetic security report for Example Company.\n"
            "Source: Example Control.\n"
            "Host: EXAMPLE-HOST-5.example.local.\n"
            "Summary: no parser-specific mapping is expected for this UAT sample."
        ),
        "parse_status": ParseStatus.SKIPPED,
        "pipeline_result": {
            "status": "skipped",
            "parser_matched": False,
            "parser_name": "",
            "reports_parsed": 0,
            "metrics_created": 0,
            "events_created": 0,
            "alerts_created": 0,
            "evidence_created": 0,
            "tickets_changed": 0,
        },
    },
]


def demo_mailbox_source_codes():
    return [source["code"] for source in DEMO_MAILBOX_SOURCES]


def demo_counts():
    codes = demo_mailbox_source_codes()
    source_names = [source["name"] for source in DEMO_MAILBOX_SOURCES]
    return {
        "mailbox_sources": SecurityMailboxSource.objects.filter(code__in=codes).count(),
        "runtime_sources": SecuritySource.objects.filter(name__in=source_names).count(),
        "messages": SecurityMailboxMessage.objects.filter(
            source__name__in=source_names,
            subject__startswith=DEMO_SUBJECT_PREFIX,
        ).count(),
        "ingestion_runs": SecurityMailboxIngestionRun.objects.filter(source__code__in=codes).count(),
    }


def reset_demo_data():
    codes = demo_mailbox_source_codes()
    source_names = [source["name"] for source in DEMO_MAILBOX_SOURCES]
    counts = demo_counts()

    SecurityMailboxIngestionRun.objects.filter(source__code__in=codes).delete()
    SecurityMailboxMessage.objects.filter(
        source__name__in=source_names,
        subject__startswith=DEMO_SUBJECT_PREFIX,
    ).delete()
    SecuritySource.objects.filter(name__in=source_names).delete()
    SecurityMailboxSource.objects.filter(code__in=codes).delete()
    return counts


def seed_demo_data(stdout=None):
    now = timezone.now()
    mailbox_sources = {}
    runtime_sources = {}

    for source_data in DEMO_MAILBOX_SOURCES:
        source, _ = SecurityMailboxSource.objects.update_or_create(
            code=source_data["code"],
            defaults={
                "name": source_data["name"],
                "enabled": True,
                "source_type": "mock",
                "mailbox_address": source_data["mailbox_address"],
                "description": source_data["description"],
                "sender_allowlist_text": source_data["sender_allowlist_text"],
                "subject_include_text": source_data["subject_include_text"],
                "subject_exclude_text": "",
                "body_include_text": "",
                "attachment_extensions": source_data.get("attachment_extensions", ""),
                "max_messages_per_run": 10,
                "mark_as_read_after_import": False,
                "process_attachments": bool(source_data.get("attachment_extensions")),
                "process_email_body": True,
                "last_run_at": None,
                "last_success_at": None,
                "last_error_at": None,
                "last_error_message": "",
            },
        )
        mailbox_sources[source.code] = source

        runtime_source, _ = SecuritySource.objects.update_or_create(
            name=source.name,
            defaults={
                "vendor": source_data["vendor"],
                "source_type": SourceType.EMAIL,
                "is_active": True,
            },
        )
        runtime_sources[source.code] = runtime_source

    for index, message_data in enumerate(DEMO_MESSAGES, start=1):
        mailbox_source = mailbox_sources[message_data["source_code"]]
        runtime_source = runtime_sources[message_data["source_code"]]
        received_at = now - timedelta(hours=index)
        summary = _safe_pipeline_summary(message_data["pipeline_result"])

        SecurityMailboxMessage.objects.update_or_create(
            source=runtime_source,
            external_id=message_data["external_id"],
            defaults={
                "sender": message_data["sender"],
                "subject": message_data["subject"],
                "body": message_data["body"],
                "received_at": received_at,
                "parse_status": message_data["parse_status"],
                "raw_payload": {
                    "uat_demo": True,
                    "mailbox_source_code": mailbox_source.code,
                    "body_redacted_in_summaries": True,
                },
                "pipeline_result": summary,
            },
        )

    _recreate_demo_runs(mailbox_sources, now)

    if stdout:
        counts = demo_counts()
        stdout.write(
            "Seeded UAT demo pack: "
            f"{counts['mailbox_sources']} mailbox sources, "
            f"{counts['messages']} messages, "
            f"{counts['ingestion_runs']} ingestion runs."
        )


def _safe_pipeline_summary(result):
    safe = {
        "status": result.get("status", "unknown"),
        "parser_matched": bool(result.get("parser_matched")),
        "parser_name": result.get("parser_name", ""),
        "reports_parsed": int(result.get("reports_parsed", 0)),
        "metrics_created": int(result.get("metrics_created", 0)),
        "events_created": int(result.get("events_created", 0)),
        "alerts_created": int(result.get("alerts_created", 0)),
        "evidence_created": int(result.get("evidence_created", 0)),
        "tickets_changed": int(result.get("tickets_changed", 0)),
    }
    if result.get("short_error"):
        safe["short_error"] = str(result["short_error"])[:160]
    return safe


def _recreate_demo_runs(mailbox_sources, now):
    SecurityMailboxIngestionRun.objects.filter(source__code__in=mailbox_sources.keys()).delete()

    run_specs = [
        {
            "source_code": "uat-demo-microsoft-defender-vulnerability",
            "status": "success",
            "imported": 1,
            "skipped": 0,
            "duplicates": 0,
            "processed": 1,
            "alerts": 1,
            "details": {"latest_pipeline_status": "success", "summaries": ["Defender UAT summary only"]},
        },
        {
            "source_code": "uat-demo-nas-synology-backup",
            "status": "partial",
            "imported": 2,
            "skipped": 1,
            "duplicates": 0,
            "processed": 2,
            "alerts": 1,
            "details": {"latest_pipeline_status": "warning", "summaries": ["Backup UAT partial summary only"]},
            "warning": "UAT demo partial import: one synthetic message skipped by filter.",
        },
        {
            "source_code": "uat-demo-custom-report",
            "status": "failed",
            "imported": 0,
            "skipped": 1,
            "duplicates": 0,
            "processed": 0,
            "alerts": 0,
            "details": {"latest_pipeline_status": "error", "summaries": ["Custom UAT failed summary only"]},
            "error": "UAT demo provider unavailable; no external connection attempted.",
        },
        {
            "source_code": "uat-demo-watchguard-threatsync",
            "status": "success",
            "imported": 1,
            "skipped": 0,
            "duplicates": 0,
            "processed": 1,
            "alerts": 0,
            "details": {"latest_pipeline_status": "success", "summaries": ["ThreatSync UAT low closed summary only"]},
        },
        {
            "source_code": "uat-demo-watchguard-dimension-firebox",
            "status": "success",
            "imported": 1,
            "skipped": 0,
            "duplicates": 0,
            "processed": 1,
            "alerts": 1,
            "details": {"latest_pipeline_status": "success", "summaries": ["Firebox VPN UAT summary only"]},
        },
        {
            "source_code": "uat-demo-watchguard-epdr",
            "status": "success",
            "imported": 0,
            "skipped": 0,
            "duplicates": 0,
            "processed": 0,
            "alerts": 0,
            "details": {"latest_pipeline_status": "skipped", "summaries": ["EPDR UAT source configured; no sample imported"]},
        },
    ]

    for index, spec in enumerate(run_specs):
        source = mailbox_sources[spec["source_code"]]
        started_at = now - timedelta(minutes=15 + index)
        finished_at = started_at + timedelta(seconds=20)
        details = {"uat_demo": True, **spec["details"]}
        error = spec.get("error", "")

        run = SecurityMailboxIngestionRun.objects.create(
            source=source,
            status=spec["status"],
            finished_at=finished_at,
            imported_messages_count=spec["imported"],
            skipped_messages_count=spec["skipped"],
            duplicate_messages_count=spec["duplicates"],
            imported_files_count=0,
            processed_items_count=spec["processed"],
            generated_alerts_count=spec["alerts"],
            error_message=error[:200],
            details=details,
        )
        SecurityMailboxIngestionRun.objects.filter(pk=run.pk).update(started_at=started_at)

        source.last_run_at = started_at
        if spec["status"] in ("success", "partial"):
            source.last_success_at = finished_at
        if spec["status"] == "failed":
            source.last_error_at = finished_at
            source.last_error_message = error[:200]
        else:
            source.last_error_at = None
            source.last_error_message = spec.get("warning", "")
        source.save(update_fields=["last_run_at", "last_success_at", "last_error_at", "last_error_message"])


class Command(BaseCommand):
    help = "Seed or reset a synthetic UAT/demo dataset for Security Center AI."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete only UAT demo records created by this command.")
        parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing data.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        reset = options["reset"]

        if dry_run:
            current_counts = demo_counts()
            if reset:
                self.stdout.write("Dry run: would delete UAT demo records only.")
                self.stdout.write(json.dumps(current_counts, sort_keys=True))
            else:
                self.stdout.write("Dry run: would create or update the UAT demo pack.")
                self.stdout.write(
                    json.dumps(
                        {
                            "mailbox_sources": len(DEMO_MAILBOX_SOURCES),
                            "runtime_sources": len(DEMO_MAILBOX_SOURCES),
                            "messages": len(DEMO_MESSAGES),
                            "ingestion_runs": 6,
                        },
                        sort_keys=True,
                    )
                )
            return

        if reset:
            deleted_counts = reset_demo_data()
            self.stdout.write(
                "Deleted UAT demo records: "
                f"{deleted_counts['mailbox_sources']} mailbox sources, "
                f"{deleted_counts['runtime_sources']} runtime sources, "
                f"{deleted_counts['messages']} messages, "
                f"{deleted_counts['ingestion_runs']} ingestion runs."
            )
            return

        seed_demo_data(stdout=self.stdout)
