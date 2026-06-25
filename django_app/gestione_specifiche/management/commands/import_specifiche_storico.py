"""Import storico specifiche (solo "In validità") — F8.

Dry-run di default: NON scrive nulla finché non si passa --apply.
Valida ogni riga contro il template e riporta righe valide/scartate con motivo.
Idempotente: salta le specifiche già presenti (stesso codice+revisione).

Esempi::

    # genera il template (CSV + XLSX)
    python manage.py import_specifiche_storico --genera-template docs/specs/gestione_specifiche/template_import_storico.csv

    # validazione (dry-run, default)
    python manage.py import_specifiche_storico percorso/dati.csv

    # import reale
    python manage.py import_specifiche_storico percorso/dati.csv --apply
"""
from __future__ import annotations

import csv
import os

from django.core.management.base import BaseCommand, CommandError

from gestione_specifiche import import_storico as imp


class Command(BaseCommand):
    help = "Importa specifiche storiche In validità da CSV (dry-run di default; --apply per scrivere)."

    def add_arguments(self, parser):
        parser.add_argument("file", nargs="?", help="Percorso del file CSV da importare.")
        parser.add_argument("--apply", action="store_true",
                            help="Esegue la scrittura su DB (senza, è solo validazione/dry-run).")
        parser.add_argument("--delimiter", default=";", help="Delimitatore CSV (default ';').")
        parser.add_argument("--encoding", default="utf-8-sig", help="Encoding del file (default utf-8-sig).")
        parser.add_argument("--genera-template", metavar="PATH",
                            help="Genera il template CSV (+ XLSX affiancato) al percorso indicato e termina.")

    def handle(self, *args, **opts):
        template_path = opts.get("genera_template")
        if template_path:
            imp.scrivi_template_csv(template_path, delimiter=opts["delimiter"])
            xlsx_path = os.path.splitext(template_path)[0] + ".xlsx"
            try:
                imp.scrivi_template_xlsx(xlsx_path)
                self.stdout.write(self.style.SUCCESS(f"Template generato: {template_path} e {xlsx_path}"))
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"Template CSV generato: {template_path} (XLSX non generato: {exc})"))
            return

        path = opts.get("file")
        if not path:
            raise CommandError("Specificare il file CSV oppure usare --genera-template PATH.")
        if not os.path.exists(path):
            raise CommandError(f"File non trovato: {path}")

        with open(path, newline="", encoding=opts["encoding"]) as fh:
            reader = csv.DictReader(fh, delimiter=opts["delimiter"])
            mancanti = [c for c in imp.REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
            if mancanti:
                raise CommandError(f"Colonne obbligatorie mancanti nell'intestazione: {', '.join(mancanti)}")
            rows = list(reader)

        risultato = imp.importa_righe(rows, apply=opts["apply"])
        c = risultato["counters"]
        modo = "APPLY (scrittura)" if opts["apply"] else "DRY-RUN (nessuna scrittura)"
        self.stdout.write(self.style.MIGRATE_HEADING(f"Import specifiche storiche — {modo}"))
        self.stdout.write(
            f"  righe totali: {len(rows)} | creati: {c['creato']} | "
            f"validi(dry-run): {c['valido']} | duplicati: {c['duplicato']} | scartati: {c['scartato']}"
        )
        for idx, motivo in risultato["scarti"]:
            self.stdout.write(self.style.WARNING(f"  riga {idx}: {motivo}"))

        if not opts["apply"] and (c["valido"] or c["duplicato"]):
            self.stdout.write(self.style.NOTICE("Esegui di nuovo con --apply per scrivere su DB."))
