"""Ricalcola il numero (DPI-AAAA-NNNN) dei record importati da
import_dpi_storico_materiale con l'anno sbagliato (anno di lancio del
comando invece dell'anno di consegna storica — bug corretto in
import_dpi_storico_materiale.py, questo comando ripara i record già creati).

Usage:
    python manage.py fix_dpi_storico_materiale_numero --dry-run
    python manage.py fix_dpi_storico_materiale_numero
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from dpi.models import ConsegnaDPI, RichiestaDPI, _next_numero_dpi

NOTE_MARKER = "[IMPORT storico MATERIALE ANTINFORTUNISTICO]"


class Command(BaseCommand):
    help = "Ricalcola il numero DPI-AAAA-NNNN dei record import_dpi_storico_materiale sull'anno di consegna reale."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Simula senza salvare nulla.")

    def handle(self, *args, **options):
        dry_run: bool = bool(options["dry_run"])
        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] Nessuna modifica verrà salvata.\n"))

        qs = (
            RichiestaDPI.objects.filter(note_gestione__startswith=NOTE_MARKER)
            .select_related("consegna")
            .order_by("consegna__data_consegna", "pk")
        )
        n_corretti = n_ok = n_saltati = 0

        for richiesta in qs:
            try:
                consegna = richiesta.consegna
            except ConsegnaDPI.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"  {richiesta.numero}: nessuna ConsegnaDPI collegata — saltato."))
                n_saltati += 1
                continue

            anno_reale = consegna.data_consegna.year
            anno_numero = richiesta.numero.split("-")[1] if richiesta.numero.count("-") >= 2 else None
            if anno_numero == str(anno_reale):
                n_ok += 1
                continue

            vecchio = richiesta.numero
            if not dry_run:
                with transaction.atomic():
                    richiesta.numero = _next_numero_dpi(year=anno_reale)
                    richiesta.save(update_fields=["numero"])
            n_corretti += 1
            self.stdout.write(f"  {vecchio} -> DPI-{anno_reale}-... ({'[DRY] ' if dry_run else ''}consegna {consegna.data_consegna})")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{'[DRY-RUN] ' if dry_run else ''}Completato: "
            f"{n_corretti} corretti, {n_ok} già corretti, {n_saltati} saltati."
        ))
