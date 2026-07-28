"""Importa un MOD.174 SGI (Excel compilato) nel registro OFI centralizzato.

Uso:
    manage.py import_mod174 <file.xlsx>              # DRY-RUN (default): nessuna scrittura
    manage.py import_mod174 <file.xlsx> --apply      # esegue l'import
    manage.py import_mod174 <file.xlsx> --apply --modulo sgi_27001
    manage.py import_mod174 <file.xlsx> --sheet "PDCA 27001"

Idempotente: rilanciarlo aggiorna le voci esistenti (upsert sul N. REF), non le
duplica. La fase PDCA è derivata dalle X di P/D/C/A del foglio.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from gestione_specifiche.mod174_import import importa_voci, leggi_righe_mod174


class Command(BaseCommand):
    help = "Importa un MOD.174 SGI (Excel compilato) nel registro OFI."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Percorso del file .xlsx (MOD.174 compilato).")
        parser.add_argument("--apply", action="store_true",
                            help="Esegue l'import (senza questo flag è un DRY-RUN).")
        parser.add_argument("--modulo", default="",
                            help="Chiave modulo d'origine da assegnare alle voci importate.")
        parser.add_argument("--sheet", default=None,
                            help="Nome del foglio (default: il primo del workbook).")

    def handle(self, *args, **opts):
        path = opts["path"]
        apply = opts["apply"]
        try:
            with open(path, "rb") as f:
                righe = leggi_righe_mod174(f, sheet=opts["sheet"])
        except FileNotFoundError:
            raise CommandError(f"File non trovato: {path}")
        except ValueError as exc:
            raise CommandError(str(exc))

        if not righe:
            self.stdout.write(self.style.WARNING("Nessuna OFI compilata trovata nel foglio."))
            return

        res = importa_voci(righe, modulo_origine=opts["modulo"], dry_run=not apply)

        for d in res["dettagli"]:
            verbo = "CREA" if d["azione"] == "creati" else "AGGIORNA"
            self.stdout.write(
                f"  [{verbo}] OFI {d['numero']:>4}  {d['tipo']:<3}  {d['fase']:<7}  {d['processo']}")

        self.stdout.write("")
        self.stdout.write(
            f"OFI lette: {len(righe)} · creati: {res['creati']} · "
            f"aggiornati: {res['aggiornati']} · saltati: {res['saltati']}")
        if apply:
            self.stdout.write(self.style.SUCCESS("Import eseguito."))
        else:
            self.stdout.write(self.style.WARNING(
                "DRY-RUN: nessuna scrittura. Aggiungi --apply per importare davvero."))
