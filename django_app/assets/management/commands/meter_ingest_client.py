"""Crea (o rigenera) il token di un collector delle letture contatori.

    python manage.py meter_ingest_client "OPC UA officina" --tutti
    python manage.py meter_ingest_client "OPC UA officina" --asset CNC-01 --asset CNC-02
    python manage.py meter_ingest_client "OPC UA officina" --rigenera

Il token in chiaro si stampa una volta sola: a DB resta solo l'hash SHA-256.
"""

from django.core.management.base import BaseCommand, CommandError

from assets.models import Asset, MeterIngestClient


class Command(BaseCommand):
    help = "Crea o rigenera il token di un collector delle letture contatori (stampa il token una volta sola)."

    def add_arguments(self, parser):
        parser.add_argument("name")
        parser.add_argument("--tutti", action="store_true", help="Puo' scrivere su tutti gli asset con un contatore.")
        parser.add_argument("--asset", action="append", default=[], help="Tag asset consentito (ripetibile).")
        parser.add_argument("--rigenera", action="store_true", help="Sostituisce il token di un collector esistente.")

    def handle(self, *args, **options):
        name = options["name"].strip()
        client = MeterIngestClient.objects.filter(name=name).first()
        if client and not options["rigenera"]:
            raise CommandError(f"Il collector «{name}» esiste gia': usa --rigenera per un token nuovo.")
        if client is None:
            client = MeterIngestClient(name=name)
        token = MeterIngestClient.issue_token()
        client.set_token(token)
        if options["tutti"]:
            client.all_meter_assets = True
        client.save()
        tags = options["asset"]
        if tags:
            assets = list(Asset.objects.filter(asset_tag__in=tags))
            missing = sorted(set(tags) - {a.asset_tag for a in assets})
            if missing:
                raise CommandError(f"Asset sconosciuti: {', '.join(missing)}")
            client.allowed_assets.add(*assets)
        self.stdout.write(self.style.WARNING(f"Token di «{name}» (copialo ora, non verra' piu' mostrato):"))
        self.stdout.write(token)
