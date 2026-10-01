import json
from django.core.management.base import BaseCommand
from automazioni.flow_health import broker_health


class Command(BaseCommand):
    help = "Salute worker/broker; --notify registra il controllo e invia allarmi fuori dal qcluster."

    def add_arguments(self, parser):
        parser.add_argument("--notify", action="store_true")

    def handle(self, *args, **options):
        health = broker_health()
        if options["notify"]:
            from automazioni.cluster_watchdog import report_health
            health["notification"] = report_health(health)
        self.stdout.write(json.dumps(health, default=lambda value: value.isoformat()))
        if health["unhealthy"]:
            raise SystemExit(2)
