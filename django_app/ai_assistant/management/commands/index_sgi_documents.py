"""Indicizza/scalda il corpus documentale SGI nel RAG dell'assistente.

Richiama ``services.index_sgi_documents()``: forza la ricostruzione dell'indice
di conoscenza (file + KB curata + corpus SGI = specifiche in vigore + procedure
correnti) e, se gli embeddings sono attivi (``OLLAMA_EMBED_ENABLED``), ne
precalcola e cachea i vettori. La prima build e' la piu' costosa (estrazione PDF
+ embedding); le successive riusano la cache per ``file_hash``/content-hash.

Tutto fail-safe: se Ollama/embeddings non sono disponibili l'indice resta
BM25-only e il comando non fallisce (a meno di ``--fail-on-error``).

Esempi:
    python manage.py index_sgi_documents --settings=config.settings.dev
    python manage.py index_sgi_documents --json
    python manage.py index_sgi_documents --fail-on-error

Schedulazione (django-q2): aggancia ``ai_assistant.tasks.run_index_sgi_documents``
allo stesso cluster che gira QCluster, a bassa frequenza (es. notturna): l'indice
si rigenera comunque on-demand alla scadenza di OLLAMA_RAG_CACHE_SECONDS, ma il
warm anticipato evita che sia la prima chat della giornata a pagare la build.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from ai_assistant import services


class Command(BaseCommand):
    help = "Forza la build dell'indice RAG e il warm degli embeddings del corpus documentale SGI."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="Stampa l'esito come JSON (utile per monitoraggio/log).",
        )
        parser.add_argument(
            "--fail-on-error",
            action="store_true",
            help="Esce con codice 1 se l'indicizzazione fallisce (skip non e' considerato errore).",
        )

    def handle(self, *args, **options):
        result = services.index_sgi_documents()

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
