"""Verifica la readiness dell'Assistente AI (+ opz. i servizi readyz) e invia un
alert email agli admin del monitoring su degrado. Pensato per la schedulazione
(django-q ``monitoring.tasks.run_ai_readiness_alert``) ma lanciabile a mano.

Esempi:
    python manage.py monitoring_ai_alert --json
    python manage.py monitoring_ai_alert --include-services
    python manage.py monitoring_ai_alert --force-email   # ignora rate-limit/stato
"""

import json

from django.core.management.base import BaseCommand

from monitoring import health


class Command(BaseCommand):
    help = "Health-check AI (Ollama/TEI) + alert email su degrado (rate-limited)."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json",
                            help="Stampa l'esito come JSON (per log/monitoraggio).")
        parser.add_argument("--include-services", action="store_true",
                            help="Includi anche i check readyz dei servizi (DB/cache/LDAP/SMTP/queue).")
        parser.add_argument("--force-email", action="store_true",
                            help="Invia la mail anche a parità di stato / entro il rate-limit.")

    def handle(self, *args, **options):
        result = health.run_ai_readiness_alert(
            include_services=bool(options.get("include_services")),
            force_email=bool(options.get("force_email")),
        )
        if options.get("as_json"):
            self.stdout.write(json.dumps(result, ensure_ascii=False))
            return

        status = str(result.get("status", "?"))
        style = {
            "ok": self.style.SUCCESS,
            "warn": self.style.WARNING,
            "fail": self.style.ERROR,
        }.get(status, self.style.NOTICE)
        self.stdout.write(style(f"AI readiness: {status.upper()} (email inviata: {result.get('emailed')})"))
        for c in result.get("checks", []):
            msg = c.get("message") or ""
            self.stdout.write(f"  - {c.get('name')}: {c.get('status')}{(' · ' + msg) if msg else ''}")
