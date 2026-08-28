"""Import elenco aziende/agenzie formative (TrainingProvider) da xlsx.

Formato atteso: colonne Nome | Descrizione | Indirizzo | Telefono | Contatto |
Telefono del contatto (un foglio unico).

Vedi `anagrafica/services/formazione_import.py::import_training_providers_xlsx`
per la mappatura puntuale colonne → campi modello.

Default **dry-run**: nessuna scrittura, solo conteggio di cosa verrebbe
creato/aggiornato. Passare `--commit` per applicare.

Esempi:
    # Anteprima (dry-run)
    python manage.py import_training_providers --file "C:\\...\\training-agencies.xlsx"

    # Applica le modifiche
    python manage.py import_training_providers --file "C:\\...\\training-agencies.xlsx" --commit
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from anagrafica.services.formazione_import import import_training_providers_xlsx


class Command(BaseCommand):
    help = "Importa aziende/agenzie formative (TrainingProvider) da un xlsx."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file", type=str, required=True,
            help="Percorso del file xlsx (es. 'training-agencies.xlsx').",
        )
        parser.add_argument(
            "--commit", action="store_true",
            help="Applica le modifiche al DB. Senza questo flag il comando è dry-run.",
        )

    def handle(self, *args, **opts):
        xlsx_path = Path(opts["file"])
        if not xlsx_path.is_file():
            raise CommandError(f"File non trovato: {xlsx_path}")

        commit = bool(opts.get("commit"))

        self.stdout.write(self.style.NOTICE(
            f"Import aziende formative — file: {xlsx_path.name} — modalità: "
            f"{'COMMIT' if commit else 'DRY-RUN'}"
        ))

        report = import_training_providers_xlsx(xlsx_path, commit=commit)

        self.stdout.write("")
        for chiave in ("righe_lette", "created", "updated", "skipped"):
            self.stdout.write(f"  {chiave:12s} {report.get(chiave, 0)}")

        errors = report.get("errors") or []
        if errors:
            self.stdout.write(self.style.ERROR(f"  errori ({len(errors)}):"))
            for e in errors[:15]:
                self.stdout.write(f"    - {e}")
            if len(errors) > 15:
                self.stdout.write(f"    ... e altri {len(errors) - 15}")

        self.stdout.write("")
        if not commit:
            self.stdout.write(self.style.NOTICE(
                "DRY-RUN: nessuna scrittura effettuata. Rilanciare con --commit per applicare."
            ))
        elif errors:
            self.stdout.write(self.style.WARNING(
                f"Import completato con {len(errors)} errore/i — controllare il dettaglio sopra."
            ))
        else:
            self.stdout.write(self.style.SUCCESS("Import completato senza errori."))
