from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from assenze.views import _maybe_pull


class Command(BaseCommand):
    help = "Sincronizza assenze da SharePoint verso DB locale (SQL/SQLite)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Forza il pull anche se non sono trascorsi i 5 minuti.",
        )

    def handle(self, *args, **options):
        result = _maybe_pull(force=bool(options.get("force")))
        payload = json.dumps(result, ensure_ascii=False)
        if result.get("ok", False):
            self.stdout.write(self.style.SUCCESS(payload))
            return
        self.stdout.write(self.style.ERROR(payload))
