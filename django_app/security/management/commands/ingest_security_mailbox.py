"""
Management command to ingest security reports from configured mailbox sources.
"""
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

from security.models import SecurityMailboxSource
from security.services.mailbox_ingestion import run_mailbox_ingestion


class Command(BaseCommand):
    help = "Ingest security reports from configured mailbox sources"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            help="Source code to ingest (if not specified, all enabled sources)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulate ingestion without creating records",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of messages to process per source",
        )
        parser.add_argument(
            "--process",
            action="store_true",
            default=True,
            help="Process imported messages through parser/rule pipeline (default: True)",
        )
        parser.add_argument(
            "--no-process",
            action="store_false",
            dest="process",
            help="Skip pipeline processing, only import messages",
        )
        parser.add_argument(
            "--force-reprocess",
            action="store_true",
            help="Reprocess already processed messages",
        )
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Keep polling configured mailbox sources until interrupted",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=120,
            help="Seconds to wait between polling runs when --loop is enabled (default: 120)",
        )
        parser.add_argument(
            "--max-runs",
            type=int,
            help="Stop loop mode after this many polling runs (useful for tests or controlled jobs)",
        )

    def handle(self, *args, **options):
        source_code = options.get("source")
        dry_run = options.get("dry_run", False)
        limit = options.get("limit")
        process = options.get("process", True)
        force_reprocess = options.get("force_reprocess", False)
        loop = options.get("loop", False)
        interval = options.get("interval", 120)
        max_runs = options.get("max_runs")

        if interval < 1:
            raise CommandError("--interval must be at least 1 second")
        if max_runs is not None and max_runs < 1:
            raise CommandError("--max-runs must be at least 1")
        if max_runs is not None and not loop:
            raise CommandError("--max-runs requires --loop")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No records will be created and no pipeline side effects will occur"))

        if not process and not dry_run:
            self.stdout.write(self.style.WARNING("PROCESSING DISABLED - Messages will be imported but not processed through the parser/rule pipeline"))

        if not loop:
            self._run_once(source_code, limit, dry_run, process, force_reprocess)
            return

        self.stdout.write(self.style.SUCCESS(f"Polling enabled: running every {interval} seconds"))
        run_number = 0
        try:
            while True:
                close_old_connections()
                run_number += 1
                timestamp = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S")
                self.stdout.write(f"\n--- Polling run {run_number} at {timestamp} ---")
                self._run_once(source_code, limit, dry_run, process, force_reprocess)

                if max_runs is not None and run_number >= max_runs:
                    self.stdout.write(self.style.SUCCESS(f"Polling complete after {run_number} run(s)"))
                    return

                self.stdout.write(f"Waiting {interval} seconds before next run...")
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Polling interrupted by operator"))

    def _run_once(self, source_code, limit, dry_run, process, force_reprocess):
        close_old_connections()

        if source_code:
            sources = SecurityMailboxSource.objects.filter(code=source_code)
            if not sources.exists():
                self.stdout.write(self.style.ERROR(f"Source '{source_code}' not found"))
                return
        else:
            sources = SecurityMailboxSource.objects.filter(enabled=True)

        if not sources.exists():
            self.stdout.write(self.style.WARNING("No enabled sources found"))
            return

        self.stdout.write(f"Processing {sources.count()} source(s)...")

        for source in sources:
            self.stdout.write(f"\n{'='*60}")
            self.stdout.write(f"Source: {source.name} ({source.code})")
            self.stdout.write(f"Type: {source.get_source_type_display()}")
            self.stdout.write(f"Mailbox: {_mask_mailbox(source.mailbox_address)}")

            try:
                run = run_mailbox_ingestion(
                    source,
                    limit=limit,
                    dry_run=dry_run,
                    process_pipeline=process,
                    force_reprocess=force_reprocess
                )

                if run:
                    self.stdout.write(self.style.SUCCESS(f"Status: {run.status}"))
                    self.stdout.write(f"Imported: {run.imported_messages_count}")
                    self.stdout.write(f"Duplicates: {run.duplicate_messages_count}")
                    self.stdout.write(f"Skipped: {run.skipped_messages_count}")
                    self.stdout.write(f"Files: {run.imported_files_count}")
                    self.stdout.write(f"Processed: {run.processed_items_count}")
                    self.stdout.write(f"Alerts: {run.generated_alerts_count}")

                    if run.error_message:
                        self.stdout.write(self.style.ERROR(f"Error: {run.error_message}"))
                else:
                    self.stdout.write(self.style.WARNING("Source disabled or no run created"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed: {e}"))

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(self.style.SUCCESS("Ingestion complete"))


def _mask_mailbox(value):
    if not value:
        return "N/A"
    local, separator, domain = str(value).partition("@")
    if not separator:
        return "***"
    if len(local) <= 2:
        masked_local = f"{local[:1]}***"
    else:
        masked_local = f"{local[:1]}***{local[-1:]}"
    return f"{masked_local}@{domain}"
