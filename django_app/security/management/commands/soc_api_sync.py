"""Letture del SOC dalle API esterne, a mano: WatchGuard Cloud, vulnerabilità Defender, tabella MAC degli switch.

    python manage.py soc_api_sync --prova                    # prova WatchGuard e Defender senza salvare nulla
    python manage.py soc_api_sync --solo watchguard          # PC, software e patch da WatchGuard (anche a interruttori spenti)
    python manage.py soc_api_sync --solo defender            # CVE viste da Defender
    python manage.py soc_api_sync --solo switch              # tabella MAC degli switch «Rete»
    python manage.py soc_api_sync                            # tutto
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Prova o forza le letture da WatchGuard Cloud, Defender (vulnerabilità) e switch (tabella MAC)."

    def add_arguments(self, parser):
        parser.add_argument("--prova", action="store_true", help="Prova le connessioni senza salvare nulla.")
        parser.add_argument("--solo", choices=("watchguard", "defender", "switch"), help="Una sola lettura.")

    def handle(self, *args, **options):
        if options["prova"]:
            self._prova()
            return
        solo = options["solo"]
        if solo in (None, "watchguard"):
            self._watchguard()
        if solo in (None, "defender"):
            self._defender()
        if solo in (None, "switch"):
            from contatori.tabella_mac import run

            self.stdout.write(f"Switch: {run()}")

    def _prova(self):
        from core import m365_graph
        from security.services import defender_vuln, watchguard_api

        if not watchguard_api.configurato():
            self.stdout.write(self.style.WARNING("WatchGuard: credenziali API non configurate (SOC › Impostazioni)."))
        else:
            try:
                self.stdout.write(self.style.SUCCESS(f"WatchGuard OK: {watchguard_api.prova()['pc']} PC sull'account."))
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"WatchGuard: {exc}"))
        if not m365_graph.configurato():
            self.stdout.write(self.style.WARNING("Defender: credenziali Graph non configurate."))
            return
        try:
            m365_graph.get(defender_vuln.URL_VULN, permesso=defender_vuln.PERMESSO, params={"$top": "1"})
            self.stdout.write(self.style.SUCCESS("Defender Vulnerability.Read.All OK."))
            m365_graph.get(defender_vuln.URL_PC, permesso=defender_vuln.PERMESSO, params={"$top": "1"})
            self.stdout.write(self.style.SUCCESS("Defender Machine.Read.All OK."))
        except m365_graph.GraphError as exc:
            self.stdout.write(self.style.ERROR(f"Defender: {exc}"))

    def _watchguard(self):
        from security.services import watchguard_api as wg

        if not wg.configurato():
            self.stdout.write(self.style.WARNING("WatchGuard: credenziali API non configurate."))
            return
        for nome, passo in (("PC", wg.sincronizza_dispositivi), ("software", wg.sincronizza_software),
                            ("patch", wg.sincronizza_patch), ("task", wg.sincronizza_task)):
            try:
                self.stdout.write(f"WatchGuard {nome}: {passo()}")
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"WatchGuard {nome}: {exc}"))

    def _defender(self):
        from core import m365_graph
        from security.services import defender_vuln

        try:
            self.stdout.write(f"Defender vulnerabilità: {defender_vuln.sincronizza()}")
        except m365_graph.GraphError as exc:
            self.stdout.write(self.style.ERROR(f"Defender: {exc}"))
