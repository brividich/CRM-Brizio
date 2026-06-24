"""Import idempotente del foglio Carichi_macchina.xlsx.

Uso:
    python manage.py import_carichi <path.xlsx>
    python manage.py import_carichi <path.xlsx> --dry-run

Mappa i codici-officina verso gli asset esistenti (cascata in asset_resolver) e
stampa un REPORT dei codici NON mappati, da risolvere a mano (tabella MacchinaAlias).
NON inventa l'aggancio agli asset.
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ...importer import importa, leggi_workbook


class Command(BaseCommand):
    help = "Importa Carichi_macchina.xlsx (idempotente) nel modulo carichi."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Percorso del file .xlsx")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Esegue il parsing e mostra il report SENZA scrivere sul DB.",
        )

    def handle(self, *args, **opts):
        path = Path(opts["path"])
        if not path.exists():
            raise CommandError(f"File non trovato: {path}")

        self.stdout.write(f"Lettura {path} ...")
        voci, titoli, backlog, cicli_lines = leggi_workbook(str(path))
        if not voci:
            self.stdout.write(self.style.WARNING(
                "Nessuna voce letta: verificare il layout del foglio "
                "(fogli 'AGG ...', riga-header con le date)."
            ))
        self.stdout.write(f"Snapshot: {len(titoli)} | voci grezze: {len(voci)} | backlog: {len(backlog)} | righe CICLI: {len(cicli_lines)}")

        report = importa(voci, titoli, backlog=backlog, cicli_lines=cicli_lines, dry_run=opts["dry_run"])

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Report import"))
        self.stdout.write(f"  Codici macchina nel foglio : {report['codici']}")
        self.stdout.write(f"  Macchine mappate ad asset   : {report['macchine_mappate']}")
        self.stdout.write(f"  Famiglie                    : {report['famiglie']}")
        self.stdout.write(f"  Affinita' (macchina/fam)    : {report['affinita']}")
        self.stdout.write(f"  Pool di equivalenza         : {report['pool']}")
        self.stdout.write(f"  Pianificazioni (piano vivo) : {report['pianificazioni_live']}")
        self.stdout.write(f"  Commesse (backlog)          : {report['commesse']}")
        self.stdout.write(f"  Cicli / Operazioni          : {report['cicli']} / {report['operazioni']}")

        non_mappati = report["non_mappati"]
        if non_mappati:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                f"CODICI NON MAPPATI: {len(non_mappati)} (risolvere a mano via MacchinaAlias)"
            ))
            for codice, conf, motivo in sorted(non_mappati):
                self.stdout.write(f"  - {codice:<12} [{conf}] {motivo}")
        else:
            self.stdout.write(self.style.SUCCESS("  Tutti i codici risolti."))

        if opts["dry_run"]:
            self.stdout.write(self.style.NOTICE("\nDRY-RUN: nessuna scrittura sul DB."))
