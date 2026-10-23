"""Backup letti dall'API REST di Veeam Backup & Replication (``security.services.veeam_api``).

    python manage.py veeam_api --prova      # verifica accesso e permessi: legge le ultime 24 ore, non salva
    python manage.py veeam_api --esegui     # un giro completo (come il security_cycle)
    python manage.py veeam_api              # esito dell'ultimo giro
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from security.services import veeam_api as svc


class Command(BaseCommand):
    help = "Prova o esegue la lettura dei backup dall'API REST di Veeam per il SOC."

    def add_arguments(self, parser):
        parser.add_argument("--prova", action="store_true", help="Legge le ultime 24 ore da Veeam senza salvare nulla.")
        parser.add_argument("--esegui", action="store_true", help="Esegue un giro completo (serve l'opzione accesa).")

    def handle(self, *args, **options):
        if options["prova"]:
            try:
                esito = svc.prova()
            except Exception as exc:  # noqa: BLE001 - messaggio per chi configura
                raise CommandError(f"Lettura non riuscita: {exc}") from exc
            self.stdout.write(self.style.SUCCESS(
                f"Accesso OK: {esito['sessioni_backup']} sessioni di backup nelle ultime 24 ore "
                f"({esito['concluse']} concluse) su {esito['sessioni']} sessioni totali."
            ))
            if esito["job"]:
                self.stdout.write("Job: " + ", ".join(esito["job"]))
            for row in esito["repository"]:
                libero = f"{row['free_pct']}% libero ({row['free_gb']} GB di {row['capacity_gb']} GB)" if row["free_pct"] is not None else "spazio non disponibile"
                self.stdout.write(f"Repository {row['name']}: {libero}")
            return
        if options["esegui"]:
            esito = svc.run()
            if not esito.get("attivo"):
                raise CommandError("Lettura spenta: accendi «Leggi i backup dall'API di Veeam» in /soc/impostazioni/.")
            self.stdout.write(str(esito))
            return
        self.stdout.write(str(svc.last_run() or "Nessun giro registrato."))
