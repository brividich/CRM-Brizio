"""Controlli di integrità dei dati della formazione d'aula.

Di default è in sola lettura: stampa il report (o JSON con ``--json``).
``--correggi`` applica solo le correzioni deterministiche (date invertite,
giornate fuori intervallo, ore di assenze, ore oltre la durata della
giornata); tutto il resto richiede una persona e resta nel report.

    python manage.py verifica_integrita_formazione
    python manage.py verifica_integrita_formazione --json
    python manage.py verifica_integrita_formazione --correggi
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from anagrafica.services.formazione_integrita import controlli_integrita, correggi


class Command(BaseCommand):
    help = "Verifica (e su richiesta corregge) l'integrità dei dati della formazione."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Report in JSON.")
        parser.add_argument("--correggi", action="store_true",
                            help="Applica le sole correzioni deterministiche, poi ristampa il report.")

    def handle(self, *args, **opts):
        if opts["correggi"]:
            fatti = correggi()
            self.stdout.write(self.style.WARNING("Correzioni applicate: " + json.dumps(fatti)))
        controlli = controlli_integrita()
        if opts["json"]:
            self.stdout.write(json.dumps([
                {"codice": c.codice, "titolo": c.titolo, "riferimento": c.riferimento, "n": c.n,
                 "esempi": c.esempi, "correggibile": c.correggibile, "gravita": c.gravita}
                for c in controlli
            ], ensure_ascii=False, indent=2))
            return
        for c in controlli:
            segno = "OK " if c.n == 0 else ("FIX" if c.correggibile else "!! ")
            self.stdout.write(f"[{segno}] {c.titolo:<62} {c.n:>6}   {c.riferimento}")
            if c.n and c.esempi:
                self.stdout.write(f"        esempi id: {', '.join(str(x) for x in c.esempi)}")
        totale = sum(c.n for c in controlli)
        self.stdout.write(self.style.SUCCESS("Nessuna anomalia.") if not totale
                          else f"Totale anomalie: {totale} (correggibili da --correggi: "
                               f"{sum(c.n for c in controlli if c.correggibile)})")
