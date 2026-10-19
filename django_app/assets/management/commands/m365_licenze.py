"""Abbonamenti Microsoft 365 nel modulo Licenze (``assets.services.m365_licenze``).

    python manage.py m365_licenze --prova   # elenca gli abbonamenti letti, senza salvare
    python manage.py m365_licenze           # sincronizza adesso
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Legge gli abbonamenti Microsoft 365 e aggiorna il modulo Licenze software."

    def add_arguments(self, parser):
        parser.add_argument("--prova", action="store_true", help="Solo lettura: elenca abbonamenti e posti.")

    def handle(self, *args, **options):
        from assets.services import m365_licenze as svc
        from core import m365_graph

        if not m365_graph.configurato():
            raise CommandError("Credenziali Graph non configurate.")
        try:
            skus = m365_graph.get_all(f"{m365_graph.GRAPH}/subscribedSkus", permesso=svc.PERMESSO, max_pages=3)
        except m365_graph.GraphError as exc:
            raise CommandError(str(exc))
        if options["prova"]:
            self.stdout.write(self.style.SUCCESS(f"{svc.PERMESSO} OK: {len(skus)} abbonamenti."))
            for s in skus:
                posti = (s.get("prepaidUnits") or {}).get("enabled")
                self.stdout.write(f"  {svc.nome_leggibile(str(s.get('skuPartNumber') or ''))}: "
                                  f"{s.get('consumedUnits')} usati su {posti}")
            date = svc._scadenze({str(s.get("skuId") or "") for s in skus})
            self.stdout.write(f"Date di rinnovo lette: {len(date)} (servono {svc.PERMESSO_DATE} o Directory.Read.All).")
            return
        self.stdout.write(self.style.SUCCESS(str(svc.sincronizza(skus=skus))))
