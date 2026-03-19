from django.core.management.base import BaseCommand

from monitoring.automation import run_monitoring_healthcheck


class Command(BaseCommand):
    help = "Esegue l'health check del modulo monitoring."

    def handle(self, *args, **options):
        result = run_monitoring_healthcheck(
            monitoring_trigger_type="manual",
            monitoring_run_identifier="management-command",
            monitoring_reraise=True,
        )
        message = ""
        if isinstance(result, dict):
            message = str(result.get("monitoring_message") or "")
        self.stdout.write(self.style.SUCCESS(message or "Monitoring health check completato."))

