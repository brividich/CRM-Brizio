"""Import dati Formazione HR dai file Excel di estrazione del gestionale.

Orchestratore dei servizi in `anagrafica/services/formazione_import.py`.
Gli operatori HR depositano gli export del gestionale nella cartella
`docs/anagrafica/formazione/`; questo comando li legge e popola i modelli
formazione (e, per le qualifiche, le tabelle del modulo anagrafica).

Vedi `docs/anagrafica/formazione/MAPPING_IMPORT_GESTIONALE.md` per la
mappatura puntuale colonne Excel → campi modello.

I file vengono importati in **ordine di dipendenza**:
    1. training-plans.xlsx          → TrainingPlan
    2. courses-person.xlsx          → TrainingCourse / Session / Enrollment / Record
    3. Iscritti alle lezioni_*.xlsx → TrainingLesson / Attendance
    4. qualifications-person.xlsx   → TipoQualifica / DipendenteQualifica

Default **dry-run**: nessuna scrittura, solo conteggio di cosa verrebbe
creato/aggiornato. Passare `--commit` per applicare.

Esempi:
    # Anteprima (dry-run) di tutti i file nella cartella standard
    python manage.py import_formazione_gestionale

    # Applica le modifiche
    python manage.py import_formazione_gestionale --commit

    # Solo alcuni dataset, da una cartella custom
    python manage.py import_formazione_gestionale --dir C:\\export --only piani,corsi --commit
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from anagrafica.services import formazione_import


# Nome logico → (glob file atteso, funzione del servizio)
DATASETS: dict[str, tuple[str, str]] = {
    "piani":      ("training-plans.xlsx",      "import_piani_formativi"),
    "corsi":      ("courses-person.xlsx",      "import_courses_person"),
    "lezioni":    ("Iscritti alle lezioni_*.xlsx", "import_lezioni_presenze"),
    "qualifiche": ("qualifications-person.xlsx", "import_qualifications_person"),
}

# Ordine di dipendenza — non riordinare: corsi dipende da piani, lezioni da corsi.
ORDINE = ["piani", "corsi", "lezioni", "qualifiche"]


def _default_dir() -> Path:
    """`docs/anagrafica/formazione/` relativa alla root del repo.

    BASE_DIR punta a `django_app/`; la cartella docs sta un livello sopra.
    """
    return Path(settings.BASE_DIR).parent / "docs" / "anagrafica" / "formazione"


class Command(BaseCommand):
    help = "Importa i dati Formazione HR dagli Excel di estrazione del gestionale."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir", type=str, default="",
            help="Cartella con i file Excel (default: docs/anagrafica/formazione/).",
        )
        parser.add_argument(
            "--only", type=str, default="",
            help="Sottoinsieme di dataset separati da virgola: piani,corsi,lezioni,qualifiche.",
        )
        parser.add_argument(
            "--commit", action="store_true",
            help="Applica le modifiche al DB. Senza questo flag il comando è dry-run.",
        )

    def handle(self, *args, **opts):
        base_dir = Path(opts["dir"]) if opts.get("dir") else _default_dir()
        if not base_dir.is_dir():
            raise CommandError(f"Cartella non trovata: {base_dir}")

        commit = bool(opts.get("commit"))

        only_raw = (opts.get("only") or "").strip()
        if only_raw:
            selected = [d.strip().lower() for d in only_raw.split(",") if d.strip()]
            sconosciuti = [d for d in selected if d not in DATASETS]
            if sconosciuti:
                raise CommandError(
                    f"Dataset sconosciuti: {sconosciuti}. "
                    f"Disponibili: {', '.join(DATASETS)}"
                )
            datasets = [d for d in ORDINE if d in selected]
        else:
            datasets = list(ORDINE)

        self.stdout.write(self.style.NOTICE(
            f"Import formazione gestionale — cartella: {base_dir}\n"
            f"Dataset: {', '.join(datasets)} — "
            f"modalità: {'COMMIT' if commit else 'DRY-RUN'}"
        ))

        totale_errori = 0
        for nome in datasets:
            pattern, func_name = DATASETS[nome]
            xlsx_path = self._resolve_file(base_dir, pattern)

            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING(f"── {nome.upper()} ──"))

            if xlsx_path is None:
                self.stdout.write(self.style.WARNING(
                    f"  File non trovato ({pattern}) — dataset saltato."
                ))
                continue

            func = getattr(formazione_import, func_name)
            self.stdout.write(f"  File: {xlsx_path.name}")
            try:
                report = func(xlsx_path, commit=commit)
            except Exception as exc:  # noqa: BLE001
                totale_errori += 1
                self.stdout.write(self.style.ERROR(
                    f"  ERRORE durante l'import: {type(exc).__name__}: {exc}"
                ))
                continue

            totale_errori += self._print_report(report)

        self.stdout.write("")
        if not commit:
            self.stdout.write(self.style.NOTICE(
                "DRY-RUN: nessuna scrittura effettuata. Rilanciare con --commit per applicare."
            ))
        elif totale_errori:
            self.stdout.write(self.style.WARNING(
                f"Import completato con {totale_errori} errore/i — controllare il dettaglio sopra."
            ))
        else:
            self.stdout.write(self.style.SUCCESS("Import completato senza errori."))

    # ------------------------------------------------------------------

    def _resolve_file(self, base_dir: Path, pattern: str) -> Path | None:
        """Risolve il file: match esatto o glob (per i nomi con data variabile).

        Se il pattern contiene `*` e ci sono più match, prende il più recente
        per data di modifica.
        """
        if "*" in pattern:
            matches = sorted(
                base_dir.glob(pattern),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            return matches[0] if matches else None
        candidate = base_dir / pattern
        return candidate if candidate.is_file() else None

    def _print_report(self, report: dict) -> int:
        """Stampa il report di un singolo import. Ritorna il n. di errori."""
        ordine_chiavi = [
            "righe_lette", "dipendenti_non_trovati",
            "piani_created", "corsi_created", "corsi_accoppiati_per_titolo", "sessioni_created",
            "lezioni_created", "tipi_qualifica_created",
            "iscrizioni_created", "iscrizioni_updated",
            "presenze_created", "presenze_updated",
            "qualifiche_created", "qualifiche_updated",
            "record_created", "created", "updated", "skipped",
        ]
        for chiave in ordine_chiavi:
            if chiave in report and report[chiave]:
                self.stdout.write(f"    {chiave:24s} {report[chiave]}")

        warnings = report.get("warnings") or []
        if warnings:
            self.stdout.write(self.style.WARNING(f"    warnings ({len(warnings)}):"))
            for w in warnings[:15]:
                self.stdout.write(f"      - {w}")
            if len(warnings) > 15:
                self.stdout.write(f"      ... e altri {len(warnings) - 15}")

        errors = report.get("errors") or []
        if errors:
            self.stdout.write(self.style.ERROR(f"    errori ({len(errors)}):"))
            for e in errors[:15]:
                self.stdout.write(f"      - {e}")
            if len(errors) > 15:
                self.stdout.write(f"      ... e altri {len(errors) - 15}")
        return len(errors)
