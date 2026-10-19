"""Segnali di Microsoft Entra ID per il SOC (``security.services.entra_signals``).

    python manage.py entra_signals --prova    # verifica i permessi: utenti, ultimo accesso, audit e accessi recenti
    python manage.py entra_signals --esegui   # un giro completo (servono gli interruttori accesi)
    python manage.py entra_signals            # esito dell'ultimo giro
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Prova o esegue i controlli di Microsoft Entra ID per il SOC."

    def add_arguments(self, parser):
        parser.add_argument("--prova", action="store_true", help="Verifica i permessi Graph senza salvare nulla.")
        parser.add_argument("--esegui", action="store_true", help="Esegue un giro completo.")

    def handle(self, *args, **options):
        from security.services import entra_signals as svc

        if options["prova"]:
            self._prova()
            return
        if options["esegui"]:
            self.stdout.write(str(svc.run()))
            return
        self.stdout.write(str(svc.last_run() or "Nessun giro registrato."))

    def _prova(self):
        from core import account_m365, m365_graph

        if not m365_graph.configurato():
            self.stdout.write(self.style.ERROR("Credenziali Graph non configurate."))
            return
        try:
            utenti, con_accessi = account_m365.leggi_utenti()
            self.stdout.write(self.style.SUCCESS(f"User.Read.All OK: {len(utenti)} account membri."))
            if con_accessi:
                self.stdout.write(self.style.SUCCESS("AuditLog.Read.All OK: data dell'ultimo accesso disponibile."))
            else:
                self.stdout.write(self.style.WARNING("Ultimo accesso non disponibile: manca AuditLog.Read.All."))
        except m365_graph.GraphError as exc:
            self.stdout.write(self.style.ERROR(f"Utenti: {exc}"))
            return
        since = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            righe = m365_graph.get_all(
                svc_url(), permesso="AuditLog.Read.All",
                params={"$filter": f"activityDateTime ge {since}", "$top": "500"}, max_pages=5,
            )
        except m365_graph.GraphError as exc:
            self.stdout.write(self.style.ERROR(f"Audit: {exc}"))
            return
        from security.services.entra_signals import classifica

        sensibili = sum(1 for r in righe if classifica(str(r.get("activityDisplayName") or "")))
        self.stdout.write(self.style.SUCCESS(
            f"Audit OK: {len(righe)} righe nelle ultime 24 ore, di cui {sensibili} sorvegliate."
        ))
        from security.services.entra_signals import SIGNINS_URL, _paesi_ammessi, anomalie_accessi

        since_ora = (timezone.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            accessi = m365_graph.get_all(SIGNINS_URL, permesso="AuditLog.Read.All",
                                         params={"$filter": f"createdDateTime ge {since_ora}", "$top": "1000"}, max_pages=5)
        except m365_graph.GraphError as exc:
            self.stdout.write(self.style.ERROR(f"Accessi: {exc}"))
            return
        anomalie = anomalie_accessi(accessi, soglia_falliti=10, paesi=_paesi_ammessi())
        self.stdout.write(self.style.SUCCESS(
            f"Accessi OK: {len(accessi)} accessi nell'ultima ora, {len(anomalie)} anomalie con le impostazioni attuali."
        ))


def svc_url() -> str:
    from security.services.entra_signals import AUDIT_URL

    return AUDIT_URL
