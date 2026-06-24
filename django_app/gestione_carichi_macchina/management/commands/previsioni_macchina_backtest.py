"""Valida la predizione della macchina: per ogni lavoro storico con famiglia, controlla se la
macchina reale e' tra le piu' probabili previste per quella famiglia.

Uso: python manage.py previsioni_macchina_backtest
Riporta top-1 e top-3 accuracy. NB: l'indice frequenza include i lavori stessi (leakage) ->
stima ottimistica, utile come baseline confrontabile nel tempo.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from ...previsioni import costruisci_indice_macchine, prevedi_macchina


class Command(BaseCommand):
    help = "Backtest dell'accuratezza della predizione macchina (top-1 / top-3)."

    def handle(self, *args, **opts):
        from ...models import Pianificazione

        freq = costruisci_indice_macchine()
        rows = Pianificazione.objects.filter(famiglia__isnull=False)
        totale = rows.count()

        n = top1 = top3 = 0
        for p in rows.iterator():
            ranked = prevedi_macchina(p.famiglia_id, freq)
            if not ranked:
                continue
            n += 1
            ids = [r["macchina_id"] for r in ranked]
            if ids[0] == p.macchina_id:
                top1 += 1
            if p.macchina_id in ids[:3]:
                top3 += 1

        self.stdout.write(self.style.MIGRATE_HEADING("Backtest predizione macchina"))
        self.stdout.write(f"  Pianificazioni con famiglia  : {totale}")
        if not n:
            self.stdout.write(self.style.WARNING("  Nessuna predizione possibile (manca affinita')."))
            return
        self.stdout.write(f"  Valutate                     : {n}")
        self.stdout.write(f"  Top-1 (macchina esatta)      : {top1} ({100*top1/n:.0f}%)")
        self.stdout.write(f"  Top-3                        : {top3} ({100*top3/n:.0f}%)")
