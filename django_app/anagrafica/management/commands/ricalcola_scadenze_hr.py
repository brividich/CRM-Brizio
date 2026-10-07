"""Ricalcola le scadenze HR dal motore unico dei requisiti (formazione + visite).

Uso:
    python manage.py ricalcola_scadenze_hr              # tutto il personale in forza
    python manage.py ricalcola_scadenze_hr --legacy-id 42
    python manage.py ricalcola_scadenze_hr --anteprima  # conta, non scrive

Gira anche ogni notte (schedule ``anagrafica_ricalcolo_scadenze``). Va lanciato a
mano dopo il deploy che lo introduce: la cache della formazione era ferma
all'ultimo ricalcolo manuale.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction


class _Anteprima(Exception):
    pass


class Command(BaseCommand):
    help = "Ricalcola cache scadenze formazione e scadenze effettive delle visite."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--legacy-id", type=int, action="append", dest="legacy_ids",
                            help="Solo questa persona (ripetibile).")
        parser.add_argument("--anteprima", action="store_true",
                            help="Calcola e riporta i numeri, poi annulla le scritture.")

    def handle(self, *args, **options) -> None:
        from anagrafica.services.scadenze import ricalcola_tutto

        esito = {}
        try:
            with transaction.atomic():
                esito = ricalcola_tutto(options["legacy_ids"])
                if options["anteprima"]:
                    raise _Anteprima
        except _Anteprima:
            self.stdout.write(self.style.WARNING("Anteprima: nessuna modifica salvata."))
        for nome, dati in esito.items():
            self.stdout.write(f"{nome}: " + ", ".join(f"{k} {v}" for k, v in dati.items()))
        if not options["anteprima"]:
            self.stdout.write(self.style.SUCCESS("Scadenze HR ricalcolate."))
