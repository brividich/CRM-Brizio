"""Un passaggio sulla cartella di pescaggio dei fogli di verifica periodica.

    manage.py intake_verifiche_periodiche              # rispetta «attiva»
    manage.py intake_verifiche_periodiche --forza      # anche se l'acquisizione e' spenta
    manage.py intake_verifiche_periodiche --limite 5

Stesso lavoro del task django-q ``intake_verifiche_periodiche`` (ogni 2 minuti):
utile per provarlo a mano o recuperare un arretrato.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from assets.models import PeriodicCheckIntakeConfig
from assets.services.periodic_intake import process_folder


class Command(BaseCommand):
    help = "Legge i fogli di verifica depositati nella cartella di pescaggio."

    def add_arguments(self, parser):
        parser.add_argument("--forza", action="store_true", help="Anche se l'acquisizione e' spenta.")
        parser.add_argument("--limite", type=int, default=None, help="File massimi in questo passaggio.")

    def handle(self, *args, **options):
        config = PeriodicCheckIntakeConfig.load()
        self.stdout.write(f"Cartella: {config.cartella or '(non configurata)'}")
        result = process_folder(config, limit=options["limite"], force=options["forza"])
        self.stdout.write(self.style.SUCCESS(result["riepilogo"]))
