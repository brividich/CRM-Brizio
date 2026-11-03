"""
Management command: rentri_promemoria

Invia (o con --dry-run conta) i promemoria in-app per gli scarichi originali
ancora senza scarico effettivo. Lo stesso lavoro gira ogni mattina dallo
schedule ``rentri_promemoria_scarico_effettivo``.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from rentri.promemoria import invia_promemoria


class Command(BaseCommand):
    help = "Promemoria in-app: scarichi originali RENTRI senza scarico effettivo oltre soglia."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Conta senza inviare né segnare.")

    def handle(self, *args, **options):
        esito = invia_promemoria(dry_run=options["dry_run"])
        self.stdout.write(
            f"Soglia {esito['soglia_giorni']} giorni: {esito['scarichi']} scarichi, {esito['notifiche']} notifiche"
            + (" (prova, niente inviato)" if options["dry_run"] else "")
        )
