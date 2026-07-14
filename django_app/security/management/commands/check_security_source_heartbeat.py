"""Raise alerts for sources that have gone quiet.

Schedule this alongside the ingestion job. Without it the absence of a report is
invisible: every other check in the system reasons about data that arrived.

    python manage.py check_security_source_heartbeat
    python manage.py check_security_source_heartbeat --dry-run
"""
from django.core.management.base import BaseCommand

from security.models import SecurityMailboxSource
from security.services.rule_engine import evaluate_security_rules
from security.services.source_heartbeat import (
    _evaluate_one,
    evaluate_source_heartbeat,
    grace_hours,
)
from django.utils import timezone


class Command(BaseCommand):
    help = "Alert on security sources that stopped reporting within their expected cadence"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report without creating events or alerts")

    def handle(self, *args, **options):
        watched = SecurityMailboxSource.objects.filter(enabled=True).exclude(expected_every_hours=0)
        self.stdout.write(f"Sources with an expected cadence: {watched.count()} (grace: {grace_hours()}h)")

        if options["dry_run"]:
            now = timezone.now()
            silent = 0
            for source in watched:
                verdict = _evaluate_one(source, now)
                if verdict:
                    silent += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"SILENT {source.code}: {verdict['reason']} "
                            f"({verdict['hours_silent']}h, deadline {verdict['deadline_hours']}h)"
                        )
                    )
                else:
                    self.stdout.write(f"ok     {source.code}")
            self.stdout.write(f"\n{silent} silent source(s). Dry run: nothing written.")
            return

        events = evaluate_source_heartbeat()
        evaluate_security_rules()

        if events:
            for event in events:
                self.stdout.write(self.style.WARNING(f"SILENT {event.payload['source_code']}: {event.payload['reason']}"))
            self.stdout.write(self.style.WARNING(f"{len(events)} source(s) silent; alerts raised."))
        else:
            self.stdout.write(self.style.SUCCESS("All watched sources reported within their expected window."))
