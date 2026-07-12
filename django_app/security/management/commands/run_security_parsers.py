from django.core.management.base import BaseCommand

from security.services.parser_engine import run_pending_parsers


class Command(BaseCommand):
    help = "Run pending security parsers."

    def handle(self, *args, **options):
        count = run_pending_parsers()
        self.stdout.write(self.style.SUCCESS(f"Parsed {count} pending items."))
