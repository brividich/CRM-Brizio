"""Verifica di coerenza del registro RENTRI (sola lettura).

    python manage.py rentri_verifica
    python manage.py rentri_verifica --solo-conteggi
    python manage.py rentri_verifica --format json
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from rentri.verifica import verifica_registro


class Command(BaseCommand):
    help = "Elenca le anomalie del registro RENTRI (catene, saldi, date, numeri doppi, termini). Non scrive nulla."

    def add_arguments(self, parser):
        parser.add_argument("--format", choices=["table", "json"], default="table")
        parser.add_argument("--solo-conteggi", action="store_true", help="Solo il numero di righe per controllo.")

    def handle(self, *args, **options):
        sezioni = verifica_registro()
        if options["format"] == "json":
            out = [
                {
                    "controllo": s["key"],
                    "titolo": s["label"],
                    "righe": len(s["righe"]) if options["solo_conteggi"] else [
                        {**r, "data": r["data"].isoformat() if r["data"] else None} for r in s["righe"]
                    ],
                }
                for s in sezioni
            ]
            self.stdout.write(json.dumps(out, ensure_ascii=False, indent=2))
            return
        totale = 0
        for s in sezioni:
            n = len(s["righe"])
            totale += n
            self.stdout.write(f"{s['label']}: {n}")
            if options["solo_conteggi"]:
                continue
            for r in s["righe"]:
                data = r["data"].strftime("%d/%m/%Y") if r["data"] else "—"
                self.stdout.write(f"  {r['tipo'] or '-'} {r['id_registrazione'] or '—'} {data} {r['codice']} · {r['dettaglio']}")
        stile = self.style.SUCCESS if totale == 0 else self.style.WARNING
        self.stdout.write(stile(f"Totale anomalie: {totale}"))
