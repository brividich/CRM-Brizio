"""Bulk-attach: allega i PDF dalla share UNC alle Specifiche già importate.

Legge la mappa `allegati_spte.csv` (codice;revisione;path) prodotta da
`converti_export_gestionale` e, per ogni riga, trova la `Specifica` per
(codice, revisione) e copia il PDF (dal percorso UNC) in `Specifica.allegato`
(storage privato cifrato).

Dry-run di DEFAULT: non scrive nulla finché non passi --apply. Idempotente: salta le
specifiche che hanno già un allegato (--forza per ri-attaccare). Va eseguito su una
macchina che vede la share `\\\\novisrv\\…` e DOPO l'import delle specifiche.

Esempi::

    python manage.py allega_pdf_da_share "C:/import/csv/allegati_spte.csv"           # dry-run
    python manage.py allega_pdf_da_share "C:/import/csv/allegati_spte.csv" --apply
"""
from __future__ import annotations

import csv
import os
from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from gestione_specifiche import intake_export as ix
from gestione_specifiche.models import Specifica


class Command(BaseCommand):
    help = "Allega i PDF dalla share UNC alle Specifiche (dry-run di default; --apply per scrivere)."

    def add_arguments(self, parser):
        parser.add_argument("mappa", help="CSV codice;revisione;path (allegati_spte.csv).")
        parser.add_argument("--apply", action="store_true", help="Scrive gli allegati (senza è dry-run).")
        parser.add_argument("--forza", action="store_true", help="Ri-attacca anche se la specifica ha già un allegato.")
        parser.add_argument("--delimiter", default=";", help="Delimitatore CSV (default ';').")
        parser.add_argument("--limit", type=int, default=0, help="Processa al più N righe (0 = tutte).")

    def handle(self, *args, **opts):
        path = opts["mappa"]
        if not os.path.exists(path):
            raise CommandError(f"Mappa non trovata: {path}")

        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh, delimiter=opts["delimiter"])
            for c in ("codice", "revisione", "path"):
                if c not in (reader.fieldnames or []):
                    raise CommandError(f"Colonna mancante nella mappa: {c}")
            rows = list(reader)
        if opts["limit"]:
            rows = rows[:opts["limit"]]

        cnt = Counter()
        problemi = []
        for r in rows:
            codice = (r.get("codice") or "").strip()
            rev = (r.get("revisione") or "").strip() or "0"
            fpath = (r.get("path") or "").strip()
            spec = Specifica.objects.filter(codice=codice, revisione=rev).first()
            if spec is None:
                cnt["specifica_assente"] += 1
                if len(problemi) < 40:
                    problemi.append(f"  specifica assente: {codice} rev {rev}")
                continue
            esito = ix.attacca_pdf(spec, fpath, forza=opts["forza"], apply=opts["apply"])
            cnt[esito] += 1
            if esito == "file_mancante" and len(problemi) < 40:
                problemi.append(f"  file mancante: {codice} rev {rev} -> {fpath}")

        modo = "APPLY (scrittura)" if opts["apply"] else "DRY-RUN (nessuna scrittura)"
        self.stdout.write(self.style.MIGRATE_HEADING(f"Bulk-attach allegati - {modo}"))
        self.stdout.write(f"  righe: {len(rows)} | {dict(cnt)}")
        for p in problemi:
            self.stdout.write(self.style.WARNING(p))
        if not opts["apply"] and cnt.get("da_allegare"):
            self.stdout.write(self.style.NOTICE("Esegui di nuovo con --apply per scrivere gli allegati."))
