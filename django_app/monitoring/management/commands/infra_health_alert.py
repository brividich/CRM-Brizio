"""Controlli del server (qcluster, coda, disco, certificato https) con allarme.

    python manage.py infra_health_alert            # esegue, apre/chiude le segnalazioni, mail per i guasti
    python manage.py infra_health_alert --solo-mostra

Lo stesso controllo gira dal qcluster ogni 30 minuti (schedule ``infra_health_alert``).
Ma se il qcluster è fermo, da lì non parte niente: registrare questo comando anche
in Utilità di pianificazione di Windows (ogni 30 minuti, utente del servizio) perché
la mail «qcluster fermo» arrivi davvero.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from monitoring import health


class Command(BaseCommand):
    help = "Controlla qcluster, coda, disco e certificato https; avvisa gli amministratori per i guasti."

    def add_arguments(self, parser):
        parser.add_argument("--solo-mostra", action="store_true", help="Mostra l'esito senza segnalazioni né mail.")

    def handle(self, *args, **opts):
        if opts["solo_mostra"]:
            checks = health.run_infra_checks()
        else:
            esito = health.run_infra_health_alert()
            checks = [health.CheckResult(**c) for c in esito["checks"]]
            if esito["emailed"]:
                self.stdout.write(self.style.WARNING("Mail di allarme inviata agli amministratori."))
        for c in checks:
            stile = {"ok": self.style.SUCCESS, "warn": self.style.WARNING, "fail": self.style.ERROR}.get(c.status, str)
            self.stdout.write(stile(f"{c.name:15} {c.status.upper():8} {c.message}"))
