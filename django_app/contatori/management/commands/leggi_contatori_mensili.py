"""Raccolta mensile MFC idempotente, anche per recuperi manuali."""
from django.core.management.base import BaseCommand, CommandError

from contatori.models import Macchina
from contatori.services import leggi_mensile_macchina
from contatori.snmp import SNMPError


class Command(BaseCommand):
    help = "Salva le letture MFC mancanti del mese corrente, usando la configurazione SNMP del portale"

    def handle(self, *args, **options):
        nuove = presenti = errori = 0
        for macchina in Macchina.objects.filter(attiva=True, host__isnull=False):
            try:
                _, creata = leggi_mensile_macchina(macchina)
                nuove += int(creata)
                presenti += int(not creata)
            except (SNMPError, ValueError):
                errori += 1
                self.stderr.write(f"MFC {macchina.pk}: lettura fallita; consultare lo stato SNMP.")
        self.stdout.write(f"Nuove: {nuove}; già presenti: {presenti}; errori: {errori}.")
        if errori:
            raise CommandError("Raccolta mensile incompleta: rieseguire per recuperare le macchine mancanti.")
