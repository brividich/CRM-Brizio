"""Legge i contatori via SNMP e salva le letture del trimestre corrente."""
from django.core.management.base import BaseCommand

from contatori.services import salva_letture_trimestrali_snmp


class Command(BaseCommand):
    help = ("Legge via SNMP le MFC attive con IP e salva la lettura del trimestre corrente "
            "(stessi parametri e controlli di «Leggi MFC ora»)")

    def handle(self, *args, **o):
        esito = salva_letture_trimestrali_snmp()
        if esito["manuali"]:
            self.stdout.write("Lettura manuale già presente, non sovrascritta: " + ", ".join(esito["manuali"]))
        if esito["incoerenti"]:
            self.stderr.write(self.style.WARNING(
                "Più basse dell'ultima lettura salvata, non salvate: " + ", ".join(esito["incoerenti"])))
        for errore in esito["errori"]:
            self.stderr.write(self.style.WARNING(errore))
        self.stdout.write(f"\n{esito['lette']} macchine lette ({esito['trimestre']}).")
