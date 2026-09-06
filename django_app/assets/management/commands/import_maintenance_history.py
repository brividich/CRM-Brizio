"""Import dello storico manutenzioni da Excel/CSV (specifica §34 / §62).

    python manage.py import_maintenance_history --template modello.xlsx
    python manage.py import_maintenance_history storico.xlsx            # anteprima
    python manage.py import_maintenance_history storico.xlsx --apply    # scrive

Di default NON scrive: stampa l'anteprima riga per riga, esattamente come la pagina
"Importa storico". Serve a dare al motore la data dell'ultima esecuzione, altrimenti
al primo avvio ogni piano risulta dovuto subito.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from assets.services import maintenance_history_import as importer


class Command(BaseCommand):
    help = "Importa lo storico manutenzioni (asset | piano | ultima esecuzione | note)."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", help="File .xlsx o .csv da importare.")
        parser.add_argument("--apply", action="store_true", help="Scrive davvero (default: anteprima).")
        parser.add_argument("--template", help="Scrive il modello Excel nel percorso indicato ed esce.")
        parser.add_argument("--max-errors", type=int, default=40, help="Righe in errore da stampare.")

    def handle(self, *args, **options):
        template_path = options.get("template")
        if template_path:
            importer.build_template_workbook().save(template_path)
            self.stdout.write(self.style.SUCCESS(f"Modello scritto in {template_path}"))
            return

        path = options.get("path")
        if not path:
            raise CommandError("Indicare il file da importare, oppure usare --template.")
        source = Path(path)
        if not source.exists():
            raise CommandError(f"File non trovato: {source}")

        with source.open("rb") as handle:
            # handle.name e' gia' il percorso del file: read_table ne guarda l'estensione.
            table = importer.read_table(handle)

        report = importer.analyze(table)
        if report.header_error:
            raise CommandError(report.header_error)

        for row in report.error_rows[: options["max_errors"]]:
            self.stdout.write(self.style.ERROR(f"  riga {row.number}: {row.error}"))
        extra = len(report.error_rows) - options["max_errors"]
        if extra > 0:
            self.stdout.write(self.style.ERROR(f"  ... e altre {extra} righe in errore."))

        summary = (
            f"Importabili={len(report.valid_rows)} "
            f"GiaPresenti={len(report.duplicate_rows)} "
            f"Errori={len(report.error_rows)}"
        )

        if not options["apply"]:
            for row in report.valid_rows[:20]:
                self.stdout.write(
                    f"  [DRY] {row.asset_tag} — {row.plan_label} — eseguita {row.last_execution:%d-%m-%Y}"
                    + (f", prossima {row.next_due:%d-%m-%Y}" if row.next_due else "")
                )
            self.stdout.write(self.style.WARNING(f"[ANTEPRIMA] {summary} (usare --apply per scrivere)"))
            return

        importer.apply_report(report)
        self.stdout.write(
            self.style.SUCCESS(
                f"{summary} StoricoCreato={report.created_history} "
                f"ProssimeScadenze={report.created_next} GiaAperte={report.kept_open}"
            )
        )
