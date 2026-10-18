"""Alert di Microsoft Defender nel SOC (``security.services.defender_alerts``).

    python manage.py defender_alerts --prova      # verifica permesso Graph: legge l'ultimo giorno, non salva
    python manage.py defender_alerts --esegui     # un giro completo (come il security_cycle)
    python manage.py defender_alerts              # esito dell'ultimo giro
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from security.services import defender_alerts as svc


class Command(BaseCommand):
    help = "Prova o esegue la lettura degli alert di Microsoft Defender per il SOC."

    def add_arguments(self, parser):
        parser.add_argument("--prova", action="store_true", help="Legge l'ultimo giorno da Graph senza salvare nulla.")
        parser.add_argument("--esegui", action="store_true", help="Esegue un giro completo (serve l'opzione accesa).")

    def handle(self, *args, **options):
        if options["prova"]:
            try:
                alerts = svc.fetch_alerts(timezone.now() - timedelta(days=1))
            except Exception as exc:  # noqa: BLE001 - messaggio per chi configura
                raise CommandError(f"Lettura non riuscita: {exc}") from exc
            self.stdout.write(self.style.SUCCESS(f"Permesso OK: {len(alerts)} alert aggiornati nelle ultime 24 ore."))
            return
        if options["esegui"]:
            esito = svc.run()
            if not esito.get("attivo"):
                raise CommandError("Lettura spenta: accendi «Leggi gli alert di Defender» in /soc/impostazioni/.")
            self.stdout.write(str(esito))
            return
        self.stdout.write(str(svc.last_run() or "Nessun giro registrato."))
