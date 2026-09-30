"""Importa il Folder B EN 9100 dal MOD.035B; dry-run per impostazione predefinita."""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sistema_gestione.models import ChecklistDomanda, ChecklistModello, ChecklistSezione
from sistema_gestione.services.mod035b_import import Mod035BFormatoNonRiconosciuto, leggi_folder_b


class Command(BaseCommand):
    help = "Importa dal PDF MOD.035B il modello versionato della checklist EN 9100 Folder B."

    def add_arguments(self, parser):
        parser.add_argument("pdf", help="Percorso del PDF MOD.035B")
        parser.add_argument("--revisione", type=int, default=0, help="Revisione del modello (default: 0)")
        parser.add_argument("--apply", action="store_true", help="Scrive nel database (default: dry-run)")

    def handle(self, *args, **options):
        try:
            sezioni = leggi_folder_b(options["pdf"])
        except (FileNotFoundError, RuntimeError) as exc:
            raise CommandError(f"File non leggibile: {options['pdf']}") from exc
        except Mod035BFormatoNonRiconosciuto as exc:
            raise CommandError(str(exc)) from exc
        totale = sum(len(s.domande) for s in sezioni)
        self.stdout.write(f"Sezioni lette: {len(sezioni)}; domande: {totale}")
        for sezione in sezioni:
            self.stdout.write(f"  {sezione.codice} {sezione.titolo}: {len(sezione.domande)} domande")
        if not options["apply"]:
            self.stdout.write(self.style.NOTICE("DRY-RUN: nessuna scrittura. Rilancia con --apply."))
            return
        revisione = options["revisione"]
        if ChecklistModello.objects.filter(
            codice=ChecklistModello.CODICE_EN9100_FOLDER_B, revisione=revisione,
        ).exists():
            raise CommandError(f"Esiste già il modello EN 9100 Folder B Rev.{revisione}.")
        with transaction.atomic():
            ChecklistModello.objects.filter(
                codice=ChecklistModello.CODICE_EN9100_FOLDER_B, attivo=True,
            ).update(attivo=False)
            modello = ChecklistModello.objects.create(
                codice=ChecklistModello.CODICE_EN9100_FOLDER_B,
                norma="UNI EN 9100:2018",
                revisione=revisione,
                titolo="Folder B - Audit di sistema EN 9100:2018",
                origine=f"Import PDF: {Path(options['pdf']).name}"[:255],
                attivo=True,
            )
            for ordine_sezione, src in enumerate(sezioni, start=1):
                sezione = ChecklistSezione.objects.create(
                    modello=modello, codice=src.codice, titolo=src.titolo,
                    criteri=src.criteri, ordine=ordine_sezione * 10,
                )
                ChecklistDomanda.objects.bulk_create([
                    ChecklistDomanda(
                        sezione=sezione, punti=domanda.punti, testo=domanda.testo, ordine=ordine * 10,
                    )
                    for ordine, domanda in enumerate(src.domande, start=1)
                ])
        self.stdout.write(self.style.SUCCESS(
            f"Creato modello EN 9100 Folder B Rev.{revisione}: {len(sezioni)} sezioni, {totale} domande."
        ))
