from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from sistema_gestione.models import Processo, ProcessoRevisione
from sistema_gestione.services.fonti import estrai_turtle


class Command(BaseCommand):
    help = "Anteprima/import di Turtle PDF come processi inattivi da validare. Mai sovrascrive il catalogo."

    def add_arguments(self, parser):
        parser.add_argument("cartella")
        parser.add_argument("--apply", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        cartella = Path(options["cartella"])
        if not cartella.is_dir():
            raise CommandError("Cartella non accessibile.")
        trovati = 0
        for path in sorted(cartella.iterdir()):
            if path.suffix.lower() != ".pdf":
                continue
            try:
                dati = estrai_turtle(path)
            except ValueError as exc:
                self.stderr.write(f"{path.name}: {exc}")
                continue
            trovati += 1
            presente = Processo.objects.filter(codice=dati["codice"]).exists()
            self.stdout.write(f"{dati['codice']}: {path.name} - {'gia presente, conservato' if presente else 'proposta inattiva'}")
            if options["apply"] and not presente:
                processo, creato = Processo.objects.get_or_create(codice=dati.pop("codice"), defaults=dati)
                if creato:
                    ProcessoRevisione.objects.create(processo=processo, numero=processo.revisione, dati=processo.snapshot(), motivo="Import Turtle: proposta da validare, nessuna approvazione documentale")
        self.stdout.write(f"Turtle riconosciuti: {trovati}. Modalita: {'applicata' if options['apply'] else 'anteprima, nessuna scrittura'}.")
