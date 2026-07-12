import json

from django.core.management.base import BaseCommand

from security.services.diagnostics import run_security_center_diagnostics


class Command(BaseCommand):
    help = "Run Security Center AI operational diagnostics."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json")
        parser.add_argument("--fail-on-warning", action="store_true")
        parser.add_argument("--fail-on-error", action="store_true")

    def handle(self, *args, **options):
        try:
            result = run_security_center_diagnostics()
        except Exception as exc:
            if options["as_json"]:
                self.stdout.write(json.dumps({"status": "error", "checks": [], "fatal_error": str(exc)}))
            raise SystemExit(2)

        if options["as_json"]:
            self.stdout.write(json.dumps(result, default=str, sort_keys=True))
        else:
            self.stdout.write(f"Security Center diagnostics: {result['status']}")
            for check in result["checks"]:
                self.stdout.write(f"[{check['status']}] {check['label']}: {check['message']}")

        if result["status"] == "error" and options["fail_on_error"]:
            raise SystemExit(2)
        if result["status"] == "warning" and options["fail_on_warning"]:
            raise SystemExit(1)
