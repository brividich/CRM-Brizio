"""Pre-carica il modello chat Ollama in memoria per azzerare il cold start.

Richiama ``services.warmup_ollama()``: Ollama carica il modello (load-only,
nessun token generato) rispettando ``OLLAMA_KEEP_ALIVE``. Pensato per essere
schedulato a intervalli inferiori al keep_alive (es. ogni 25 min se
``keep_alive=30m``) cosi' la prima richiesta utente non paga mai il caricamento.

Esempi:
    python manage.py warmup_ollama --settings=config.settings.dev
    python manage.py warmup_ollama --json
    python manage.py warmup_ollama --timeout 420 --fail-on-error

Schedulazione (Ollama nativo): aggancialo allo stesso cluster/Task Scheduler che
gira QCluster, oppure a un Task Scheduler dedicato a intervalli < keep_alive.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from ai_assistant import services


class Command(BaseCommand):
    help = "Pre-carica il modello chat Ollama in memoria per evitare il cold start sulla prima richiesta."

    def add_arguments(self, parser):
        parser.add_argument(
            "--timeout",
            type=int,
            default=None,
            help="Timeout in secondi per il caricamento (default: max(OLLAMA_REQUEST_TIMEOUT_SECONDS, 300)).",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="Stampa l'esito come JSON (utile per monitoraggio/log).",
        )
        parser.add_argument(
            "--fail-on-error",
            action="store_true",
            help="Esce con codice 1 se il warmup fallisce (skip non e' considerato errore).",
        )

    def handle(self, *args, **options):
        result = services.warmup_ollama(timeout=options.get("timeout"))

        if options.get("as_json"):
            self.stdout.write(json.dumps(result, ensure_ascii=False))
        else:
            message = str(result.get("message") or "")
            if result.get("ok"):
                self.stdout.write(self.style.SUCCESS(message))
            elif result.get("skipped"):
                self.stdout.write(self.style.WARNING(message))
            else:
                self.stderr.write(self.style.ERROR(message))

        if options.get("fail_on_error") and not result.get("ok") and not result.get("skipped"):
            raise SystemExit(1)
