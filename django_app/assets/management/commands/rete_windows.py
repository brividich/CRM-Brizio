"""Indirizzi IP dal DHCP e dal DNS di Windows Server (``assets.services.rete_windows``).

    python manage.py rete_windows --prova     # legge DHCP e DNS e conta, senza salvare
    python manage.py rete_windows             # sincronizza adesso (come lo schedule rete_windows_sync)
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from assets.services import rete_windows as svc


class Command(BaseCommand):
    help = "Prova o esegue la lettura degli indirizzi IP dal DHCP e dal DNS di Windows Server."

    def add_arguments(self, parser):
        parser.add_argument("--prova", action="store_true", help="Legge DHCP e DNS senza salvare nulla.")

    def handle(self, *args, **options):
        cfg = svc.config()
        if not svc.configurato():
            raise CommandError("Mancano RETE_DHCP_SERVERS e/o RETE_DNS_SERVER + RETE_DNS_ZONES nel .env del portale.")
        if options["prova"]:
            errori = 0
            for server in cfg["dhcp"]:
                try:
                    dati = svc.leggi_dhcp(server)
                except svc.ReteError as exc:
                    errori += 1
                    self.stderr.write(f"DHCP {server}: {exc}")
                    continue
                self.stdout.write(self.style.SUCCESS(f"DHCP {server}: {len(dati['scopes'])} ambiti, {len(dati['leases'])} indirizzi."))
                for s in dati["scopes"]:
                    self.stdout.write(f"  {s.get('scope_id')} {s.get('name') or ''}: {s.get('in_use')} in uso, {s.get('free')} liberi")
            if cfg["dns"] and cfg["zone"]:
                try:
                    record = svc.leggi_dns(cfg["dns"], cfg["zone"])
                    self.stdout.write(self.style.SUCCESS(f"DNS {cfg['dns']} ({', '.join(cfg['zone'])}): {len(record)} record A."))
                except svc.ReteError as exc:
                    errori += 1
                    self.stderr.write(f"DNS {cfg['dns']}: {exc}")
            if errori:
                raise CommandError(f"{errori} letture non riuscite.")
            return
        esito = svc.sincronizza()
        for errore in esito["errori"]:
            self.stderr.write(errore)
        self.stdout.write(str({k: v for k, v in esito.items() if k != "errori"}))
