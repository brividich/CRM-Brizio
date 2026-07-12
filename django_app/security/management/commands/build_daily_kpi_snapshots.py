from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_date

from security.services.kpi_service import build_daily_kpi_snapshots


class Command(BaseCommand):
    help = "Build daily KPI snapshots."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="Snapshot date in YYYY-MM-DD format.")

    def handle(self, *args, **options):
        snapshot_date = parse_date(options["date"]) if options.get("date") else None
        count = build_daily_kpi_snapshots(snapshot_date=snapshot_date)
        self.stdout.write(self.style.SUCCESS(f"Built {count} KPI snapshots."))
