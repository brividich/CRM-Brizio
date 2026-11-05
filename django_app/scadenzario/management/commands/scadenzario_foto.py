"""Fotografia dei numeri dello scadenzario di oggi (vista «Andamento»).

Gira da sola ogni mattina (schedule ``scadenzario_foto_giornaliera``); lanciala a
mano dopo il deploy per avere subito il primo punto. Rilanciabile: sovrascrive oggi.
"""
from django.core.management.base import BaseCommand

from scadenzario.calendario import scatta_foto


class Command(BaseCommand):
    help = "Fotografa i numeri dello scadenzario di oggi, per fonte (andamento nel tempo)."

    def handle(self, *args, **options):
        esito = scatta_foto()
        self.stdout.write(self.style.SUCCESS(
            f"Fotografia del {esito['data']}: {esito['scadute']} scadute in {esito['fonti']} fonti."
        ))
