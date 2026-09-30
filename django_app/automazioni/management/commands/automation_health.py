import json
from django.core.management.base import BaseCommand
from automazioni.flow_health import broker_health


class Command(BaseCommand):
    help = "Controllo read-only del broker, utilizzabile da un watchdog esterno al worker."

    def handle(self, *args, **options):
        health = broker_health()
        latest = health["last_completed"]
        self.stdout.write(json.dumps({**health, "last_completed": latest.isoformat() if latest else None}))
        if health["stalled"]:
            raise SystemExit(2)
