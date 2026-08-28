"""Import catalogo Corsi/Sessioni/Docenti da "N Estrazioni Corsi.xlsx".

Formato diverso da `import_formazione_gestionale`: qui il file è un export
del gestionale con un foglio "Corsi" (storico) e un foglio
"Corsi AGGIORNAMENTI" (più recente, quasi sovrapposto al primo) — una riga
per sessione erogata/pianificata, senza dati di iscrizione per persona.
I fogli "PROVA ..." dello stesso workbook sono bozze/QA e vengono ignorati.

Vedi `anagrafica/services/formazione_import.py::import_estrazioni_corsi`
per la mappatura puntuale colonne → campi modello.

Default **dry-run**: nessuna scrittura, solo conteggio di cosa verrebbe
creato/aggiornato. Passare `--commit` per applicare.

Esempi:
    # Anteprima (dry-run)
    python manage.py import_estrazioni_corsi --file "C:\\...\\1 Estrazioni Corsi.xlsx"

    # Applica le modifiche
    python manage.py import_estrazioni_corsi --file "C:\\...\\1 Estrazioni Corsi.xlsx" --commit
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from anagrafica.services.formazione_import import (
    ESTRAZIONI_CORSI_SHEETS_DEFAULT,
    import_estrazioni_corsi,
)


class Command(BaseCommand):
    help = "Importa catalogo Corsi/Sessioni/Docenti da un export 'N Estrazioni Corsi.xlsx' del gestionale."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file", type=str, required=True,
            help="Percorso del file xlsx (es. '1 Estrazioni Corsi.xlsx').",
        )
        parser.add_argument(
            "--sheets", type=str, default="",
            help="Fogli da leggere, separati da virgola (default: 'Corsi,Corsi AGGIORNAMENTI').",
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
        sheets_raw = (opts.get("sheets") or "").strip()
        sheets = [s.strip() for s in sheets_raw.split(",") if s.strip()] if sheets_raw else ESTRAZIONI_CORSI_SHEETS_DEFAULT

        self.stdout.write(self.style.NOTICE(
            f"Import estrazioni corsi — file: {xlsx_path.name}\n"
            f"Fogli: {', '.join(sheets)} — modalità: {'COMMIT' if commit else 'DRY-RUN'}"
        ))

        report = import_estrazioni_corsi(xlsx_path, commit=commit, sheets=sheets)

        self.stdout.write("")
        ordine_chiavi = [
            "righe_lette", "righe_saltate",
            "piani_created", "corsi_created", "corsi_updated",
            "docenti_created", "sessioni_created", "sessioni_updated",
        ]
        for chiave in ordine_chiavi:
            if chiave in report and report[chiave]:
                self.stdout.write(f"  {chiave:24s} {report[chiave]}")

        warnings = report.get("warnings") or []
        if warnings:
            self.stdout.write(self.style.WARNING(f"  warnings ({len(warnings)}):"))
            for w in warnings[:15]:
                self.stdout.write(f"    - {w}")
            if len(warnings) > 15:
                self.stdout.write(f"    ... e altri {len(warnings) - 15}")

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
