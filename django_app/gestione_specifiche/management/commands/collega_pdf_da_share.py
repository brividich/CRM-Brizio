"""Collega le Specifiche ai PDF sulla share UNC (modalità "single source of truth").

Legge la mappa `allegati_spte.csv` (codice;revisione;path) e per ogni riga imposta
`Specifica.percorso_esterno` al percorso UNC: **non copia** il file, lo lascia sul master
aziendale (che tutti aggiornano, PDF protetti da Adobe). La view protetta lo serve on-demand
con allowlist + anti-traversal.

Dry-run di DEFAULT. Idempotente (salta chi è già collegato; `--forza` per ri-collegare).
Collega solo file **realmente presenti** sulla share (niente link morti). Va eseguito su una
macchina che vede la share e DOPO l'import delle specifiche.

Esempi::

    python manage.py collega_pdf_da_share "C:/import/csv/allegati_spte.csv"           # dry-run
    python manage.py collega_pdf_da_share "C:/import/csv/allegati_spte.csv" --apply
"""
from __future__ import annotations

import csv
import os
from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from gestione_specifiche.models import Specifica
from gestione_specifiche.share_link import (
    collega_specifica,
    costruisci_indice_nomi,
    radici_consentite,
)


class Command(BaseCommand):
    help = "Collega le Specifiche ai PDF sulla share (percorso_esterno). Dry-run di default; --apply per scrivere."

    def add_arguments(self, parser):
        parser.add_argument("mappa", help="CSV codice;revisione;path (allegati_spte.csv).")
        parser.add_argument("--apply", action="store_true", help="Scrive i collegamenti (senza e' dry-run).")
        parser.add_argument("--forza", action="store_true", help="Ri-collega anche le specifiche gia' collegate.")
        parser.add_argument("--fallback-nome", action="store_true",
                            help="Se il path esatto manca, cerca il PDF per NOME sulla share (escluse le cartelle superate); collega solo su match unico.")
        parser.add_argument("--delimiter", default=";", help="Delimitatore CSV (default ';').")
        parser.add_argument("--limit", type=int, default=0, help="Processa al piu' N righe (0 = tutte).")

    def handle(self, *args, **opts):
        path = opts["mappa"]
        if not os.path.exists(path):
            raise CommandError(f"Mappa non trovata: {path}")
        radici = radici_consentite()
        if not radici:
            raise CommandError("GESTIONE_SPECIFICHE_SHARE_ROOTS non configurata: nessuna radice consentita.")

        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh, delimiter=opts["delimiter"])
            for c in ("codice", "revisione", "path"):
                if c not in (reader.fieldnames or []):
                    raise CommandError(f"Colonna mancante nella mappa: {c}")
            rows = list(reader)
        if opts["limit"]:
            rows = rows[:opts["limit"]]

        indice = None
        if opts["fallback_nome"]:
            self.stdout.write("  Indicizzo la share per nome file (escluse le cartelle superate)...")
            indice = costruisci_indice_nomi()
            self.stdout.write(f"  PDF indicizzati: {sum(len(v) for v in indice.values())} nomi distinti: {len(indice)}")

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
            esito = collega_specifica(spec, fpath, forza=opts["forza"], apply=opts["apply"], indice=indice)
            cnt[esito] += 1
            if esito in ("file_mancante", "path_non_consentito", "ambiguo") and len(problemi) < 40:
                problemi.append(f"  {esito}: {codice} rev {rev} -> {fpath}")

        modo = "APPLY (scrittura)" if opts["apply"] else "DRY-RUN (nessuna scrittura)"
        self.stdout.write(self.style.MIGRATE_HEADING(f"Collegamento allegati (share) - {modo}"))
        self.stdout.write(f"  radici consentite: {radici}")
        self.stdout.write(f"  righe: {len(rows)} | {dict(cnt)}")
        for p in problemi:
            self.stdout.write(self.style.WARNING(p))
        if not opts["apply"] and (cnt.get("da_collegare") or cnt.get("da_collegare_nome")):
            self.stdout.write(self.style.NOTICE("Esegui di nuovo con --apply per scrivere i collegamenti."))
