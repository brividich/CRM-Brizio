"""Termini candidati per il glossario, estratti dal testo dei documenti SGI.

Deterministico: n-grammi di 1–3 parole presenti in almeno N documenti e non ancora
nel glossario (né come termine né come variante), ordinati per numero di documenti.
Con ``--ai`` chiede all'LLM una proposta per i primi candidati (un task django-q
per batch, < 90 s); le proposte restano in attesa nella coda di revisione e non
diventano termini finché una persona non le accetta.

Richiede il testo persistito dei documenti SGI (``sgi_estrai_testi``).

Esempi:
    python manage.py glossario_candidati --limit 30
    python manage.py glossario_candidati --limit 20 --ai
    python manage.py glossario_candidati --limit 5 --ai --sincrono
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from glossario_tecnico.services import candidati, proponi_con_ai, testi_corpus_sgi

BATCH_AI = 5


class Command(BaseCommand):
    help = "Elenca i termini candidati dal corpus SGI; con --ai accoda le proposte per la revisione."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=30, help="Quanti candidati (default 30).")
        parser.add_argument("--min-documenti", type=int, default=3, dest="min_documenti",
                            help="Documenti minimi in cui deve comparire (default 3).")
        parser.add_argument("--ai", action="store_true", help="Chiede all'AI una proposta per i candidati.")
        parser.add_argument("--sincrono", action="store_true",
                            help="Con --ai: esegue subito invece di accodare i task (solo per prove).")

    def handle(self, *args, **options):
        testi = testi_corpus_sgi()
        if not testi:
            self.stdout.write(self.style.WARNING(
                "Nessun testo SGI persistito: esegui prima `sgi_estrai_testi`."
            ))
            return
        elenco = candidati(testi, min_documenti=max(1, options["min_documenti"]), limit=max(1, options["limit"]))
        self.stdout.write(f"Documenti letti: {len(testi)} — candidati: {len(elenco)}")
        for c in elenco:
            self.stdout.write(f"  {c['documenti']:>4} doc  {c['testo']}")
        if not options.get("ai") or not elenco:
            return
        batches = [[c["testo"] for c in elenco[i:i + BATCH_AI]] for i in range(0, len(elenco), BATCH_AI)]
        if options.get("sincrono"):
            totale = sum(proponi_con_ai(b) for b in batches)
            self.stdout.write(self.style.SUCCESS(f"Proposte registrate: {totale} (coda di revisione del glossario)."))
            return
        from django_q.tasks import async_task

        for batch in batches:
            async_task("glossario_tecnico.tasks.run_glossario_proposte_ai", batch, timeout=90)
        self.stdout.write(self.style.SUCCESS(f"Accodati {len(batches)} task di proposta AI."))
