"""Import idempotente del foglio Carichi_macchina.xlsx.

Uso:
    python manage.py import_carichi <path.xlsx>
    python manage.py import_carichi <path.xlsx> --dry-run

Import CUMULATIVO da più edizioni del foglio (apprendimento dagli snapshot storici):
    python manage.py import_carichi <recente.xlsx> <vecchia1.xlsx> <vecchia2.xlsx> ...

Con più file, l'edizione PIÙ RECENTE (per data degli snapshot 'AGG') fornisce il piano
vivo/backlog/cicli; le edizioni più vecchie contribuiscono SOLO allo storico (affinità,
recency, pool) senza ridefinire il piano corrente né ridoppiare le settimane in comune
(il dedup su macchina/data/testo le riconcilia).

Mappa i codici-officina verso gli asset esistenti (cascata in asset_resolver) e
stampa un REPORT dei codici NON mappati, da risolvere a mano (tabella MacchinaAlias).
NON inventa l'aggancio agli asset.
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ...importer import fondi_edizioni, importa, leggi_workbook


class Command(BaseCommand):
    help = "Importa una o più edizioni di Carichi_macchina.xlsx (idempotente, cumulativo)."

    def add_arguments(self, parser):
        parser.add_argument(
            "paths", nargs="+",
            help="Uno o più file .xlsx. Più file = import cumulativo "
                 "(il più recente è il piano vivo, gli altri solo storico).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Esegue il parsing e mostra il report SENZA scrivere sul DB.",
        )

    def handle(self, *args, **opts):
        paths = [Path(p) for p in opts["paths"]]
        for p in paths:
            if not p.exists():
                raise CommandError(f"File non trovato: {p}")

        letture = []
        for p in paths:
            self.stdout.write(f"Lettura {p} ...")
            voci, titoli, backlog, cicli_lines = leggi_workbook(str(p))
            ds = [v.snapshot_date for v in voci if v.snapshot_date]
            periodo = f"{min(ds):%d/%m/%Y}–{max(ds):%d/%m/%Y}" if ds else "date non rilevate"
            self.stdout.write(
                f"  snapshot: {len(titoli)} | voci: {len(voci)} | backlog: {len(backlog)} "
                f"| righe CICLI: {len(cicli_lines)} | periodo: {periodo}"
            )
            letture.append((voci, titoli, backlog, cicli_lines))

        if len(letture) == 1:
            voci, titoli, backlog, cicli_lines = letture[0]
        else:
            voci, titoli, backlog, cicli_lines = fondi_edizioni(letture)
            self.stdout.write(self.style.NOTICE(
                f"Import CUMULATIVO da {len(letture)} edizioni: il piano vivo è l'edizione "
                "più recente; le altre arricchiscono solo lo storico (affinità/recency/pool)."
            ))

        if not voci:
            self.stdout.write(self.style.WARNING(
                "Nessuna voce letta: verificare il layout del foglio "
                "(fogli 'AGG ...', riga-header con le date)."
            ))
        self.stdout.write(f"Voci totali da elaborare: {len(voci)}")

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
