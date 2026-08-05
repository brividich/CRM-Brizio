"""Legge i contatori via SNMP e salva le letture del trimestre corrente."""
from django.core.management.base import BaseCommand
from django.utils import timezone
from contatori.models import Macchina, LetturaContatori
from contatori.snmp import leggi_macchina, SNMPError


class Command(BaseCommand):
    help = "Legge i contatori via SNMP di tutte le macchine attive con host"

    def add_arguments(self, parser):
        parser.add_argument("--community", default="novicromprinter")
        parser.add_argument("--timeout", type=int, default=3)
        parser.add_argument("--version", default="v1", choices=["v1", "v2c"])

    def handle(self, *args, **o):
        oggi = timezone.localdate()
        trim = f"{oggi.year}-Q{(oggi.month-1)//3+1}"
        ok = 0
        for m in Macchina.objects.filter(attiva=True).exclude(host__isnull=True):
            try:
                vals = leggi_macchina(m, community=o["community"],
                                      timeout=o["timeout"], version=o["version"])
                LetturaContatori.objects.update_or_create(
                    macchina=m, trimestre=trim,
                    defaults={**vals, "data": oggi, "fonte": "SNMP"})
                ok += 1
                self.stdout.write(self.style.SUCCESS(f"{m.reparto}: {vals}"))
            except SNMPError as e:
                self.stderr.write(self.style.WARNING(f"{m.reparto}: {e}"))
        self.stdout.write(f"\n{ok} macchine lette ({trim}).")
