from django.core.management.base import BaseCommand

from security.services.rule_engine import evaluate_security_rules


class Command(BaseCommand):
    help = "Evaluate security rule engine."

    def handle(self, *args, **options):
        count = evaluate_security_rules()
        self.stdout.write(self.style.SUCCESS(f"Evaluated {count} events."))
