from django.core.management.base import BaseCommand

from security.models import SourceType
from security.services.ingestion import get_or_create_source, ingest_mailbox_message, ingest_source_file


class Command(BaseCommand):
    help = "Load sample Security Center AI data."

    def handle(self, *args, **options):
        defender = get_or_create_source("Microsoft Defender Demo", "Microsoft", SourceType.EMAIL)
        synology = get_or_create_source("Synology Active Backup Demo", "Synology", SourceType.EMAIL)
        watchguard = get_or_create_source("WatchGuard Firebox Demo", "WatchGuard", SourceType.CSV)

        ingest_mailbox_message(
            defender,
            "Microsoft Defender vulnerability notification",
            "CVE-2025-12345\nAffected product: Contoso VPN Gateway\nCVSS: 9.8\nExposed devices: 3\nSeverity: Critical",
            sender="defender@example.test",
            external_id="sample-defender-cve",
        )
        ingest_mailbox_message(
            synology,
            "Synology Active Backup completed",
            "Task: Daily Server Backup\nStatus: Completed\nProtected items: 12",
            sender="synology@example.test",
            external_id="sample-synology-ok",
        )
        ingest_mailbox_message(
            synology,
            "Synology Active Backup failed",
            "Task: ERP VM Backup\nStatus: Failed\nProtected items: 1",
            sender="synology@example.test",
            external_id="sample-synology-failed",
        )
        ingest_source_file(
            watchguard,
            "watchguard_authentication_denied.csv",
            "user,ip,timestamp\nalice,198.51.100.10,2026-04-26T08:00:00Z\nbob,198.51.100.11,2026-04-26T08:01:00Z\n",
        )
        self.stdout.write(self.style.SUCCESS("Sample security data ingested."))
