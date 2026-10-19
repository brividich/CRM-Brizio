"""Dispositivi da Microsoft Intune (``assets.services.intune``).

    python manage.py intune_sync --prova   # verifica il permesso e conta i dispositivi, senza salvare
    python manage.py intune_sync           # sincronizza adesso
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Legge i dispositivi gestiti da Microsoft Intune e aggiorna l'inventario IT."

    def add_arguments(self, parser):
        parser.add_argument("--prova", action="store_true", help="Solo lettura: conta i dispositivi e i problemi.")

    def handle(self, *args, **options):
        from django.utils import timezone

        from assets.services import intune
        from core import m365_graph

        if not m365_graph.configurato():
            raise CommandError("Credenziali Graph non configurate.")
        try:
            devices = m365_graph.get_all(intune.URL, permesso=intune.PERMESSO,
                                         params={"$select": intune._SELECT, "$top": "1000"})
        except m365_graph.GraphError as exc:
            raise CommandError(str(exc))
        if options["prova"]:
            now = timezone.now()
            con_problemi = sum(1 for d in devices if intune.problemi_di(intune.normalizza(d), now))
            self.stdout.write(self.style.SUCCESS(
                f"{intune.PERMESSO} OK: {len(devices)} dispositivi in Intune, {con_problemi} con problemi."
            ))
            return
        self.stdout.write(self.style.SUCCESS(str(intune.sincronizza(devices=devices))))
