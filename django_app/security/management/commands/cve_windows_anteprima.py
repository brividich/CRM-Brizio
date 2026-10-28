"""Anteprima dell'abbinamento delle CVE di Windows per build (sola lettura).

Dice cosa cambierebbe accendendo «Riconosci la release di Windows dalla build»
(Impostazioni -> Avvisi e automatismi -> Impatto CVE sugli asset): release dei PC Windows,
passaggi di esito (es. da verificare -> non impatta) e CVE che aprirebbero un alert nuovo.
Non scrive nulla. Output in solo ASCII (console cp1252 di produzione).

    manage.py cve_windows_anteprima
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from security.services import windows_build

ESITI = {"impacts": "impatta", "to_verify": "da verificare", "not_impacted": "non impatta", "assente": "nessun esito"}


class Command(BaseCommand):
    help = "Anteprima (sola lettura) dell'abbinamento delle CVE di Windows per build."

    def handle(self, *args, **options):
        d = windows_build.anteprima()
        out = self.stdout.write
        out(f"CVE con criteri Windows: {d['cve']}  -  PC Windows riconosciuti: {d['pc_windows']}")
        out("Release dei PC (righe di inventario):")
        for nome, n in d["release"]:
            out(f"  {n:5}  {nome}")
        out("Esiti che cambierebbero (prima -> dopo):")
        for (prima, dopo), n in d["passaggi"]:
            out(f"  {n:5}  {ESITI.get(prima, prima)} -> {ESITI.get(dopo, dopo)}")
        if d["da_verificare_motivi"]:
            out("Restano da verificare, perche':")
            for motivo, n in d["da_verificare_motivi"]:
                out(f"  {n:5}  {motivo}")
        out(f"CVE che aprirebbero un alert (PC nuovi che diventano 'impatta' su CVE critiche o KEV): {len(d['cve_con_nuovo_alert'])}")
        for cve in d["cve_con_nuovo_alert"]:
            out(f"  {cve}")
