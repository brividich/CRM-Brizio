"""Estrae e persiste il testo dei documenti SGI correnti (fase A1 del database SGI).

Per ogni revisione corrente da file server (documento attivo e indicizzabile)
salva il testo in ``SgiTestoEstratto``. Idempotente su ``file_hash``: una
revisione già estratta con lo stesso hash viene saltata (``--forza`` per rifarla).
Sola lettura sulla share. Nessuna AI. L'assistente usa il testo persistito solo
con ``SGI_ESTRAZIONE_PERSISTITA_ENABLED``; dopo un'estrazione massiva rilanciare
``index_sgi_documents``.

Esempi:
    python manage.py sgi_estrai_testi --dry-run
    python manage.py sgi_estrai_testi --solo "MT CN 06" --forza
    python manage.py sgi_estrai_testi --limit 20
"""

from __future__ import annotations

import time
from collections import Counter

from django.core.management.base import BaseCommand

from procedure_refresh.sgi_testo import persisti_estrazione, revisioni_da_estrarre


class Command(BaseCommand):
    help = "Estrae e persiste il testo dei documenti SGI correnti (idempotente su file_hash)."

    def add_arguments(self, parser):
        parser.add_argument("--solo", default="", help="Solo il documento con questo codice.")
        parser.add_argument("--forza", action="store_true", help="Ri-estrae anche se l'hash non è cambiato.")
        parser.add_argument("--limit", type=int, default=0, help="Max revisioni da estrarre (0 = tutte).")
        parser.add_argument("--dry-run", action="store_true", dest="dry_run", help="Elenca soltanto, non estrae.")

    def handle(self, *args, **options):
        forza = bool(options.get("forza"))
        revisioni = revisioni_da_estrarre(forza=forza, solo=str(options.get("solo") or ""))
        limit = int(options.get("limit") or 0)
        if limit:
            revisioni = revisioni[:limit]
        self.stdout.write(f"Revisioni da estrarre: {len(revisioni)}{' (dry-run)' if options.get('dry_run') else ''}")
        if options.get("dry_run"):
            for rev in revisioni[:50]:
                self.stdout.write(f"  - {rev.document.code} Rev.{rev.revision_code}")
            if len(revisioni) > 50:
                self.stdout.write(f"  ... e altre {len(revisioni) - 50}")
            return

        esiti: Counter = Counter()
        inizio = time.monotonic()
        for i, rev in enumerate(revisioni, 1):
            try:
                stato = persisti_estrazione(rev, forza=forza)
            except Exception as exc:  # una revisione non blocca le altre
                stato = f"errore: {type(exc).__name__}"
            esiti[stato.split(":")[0]] += 1
            if stato != "estratto":
                self.stdout.write(f"  [{i}/{len(revisioni)}] {rev.document.code}: {stato}")
        durata = time.monotonic() - inizio
        self.stdout.write(
            self.style.SUCCESS(
                "Fatto in {:.0f}s: ".format(durata) + ", ".join(f"{k}={v}" for k, v in sorted(esiti.items()))
            )
        )
        if esiti.get("estratto"):
            self.stdout.write("Ora: python manage.py index_sgi_documents (con SGI_ESTRAZIONE_PERSISTITA_ENABLED=1).")
