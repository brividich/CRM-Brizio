"""Legge i report CMM della share nell'archivio delle quote (Controllo dimensionale).

    manage.py leggi_report_cmm                 # un giro come quello pianificato
    manage.py leggi_report_cmm --pn PN-ESEMPIO-1
    manage.py leggi_report_cmm --minuti 120     # primo caricamento, più lungo
"""
from django.core.management.base import BaseCommand, CommandError

from produzione import report_cmm_indice as indice


class Command(BaseCommand):
    help = "Legge i report CMM (PDF) della share nell'archivio delle quote."

    def add_arguments(self, parser):
        parser.add_argument("--pn", default="", help="Solo la cartella di questo P/N.")
        parser.add_argument("--minuti", type=int, default=0, help="Durata massima del giro.")

    def handle(self, *args, **opt):
        if not indice.attivo():
            raise CommandError("PRODUZIONE_REPORT_CMM_ROOT non è impostata.")
        esito = indice.leggi_pn(opt["pn"]) if opt["pn"] else indice.giro(opt["minuti"] or None)
        self.stdout.write(str(esito))
