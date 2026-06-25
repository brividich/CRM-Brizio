"""Valida la predizione delle ore confrontandola con le ore REALI scritte nel piano.

Uso: python manage.py previsioni_backtest
Misura su tutte le pianificazioni che hanno `ore` esplicite: copertura, MAE e % entro +/-20%.
Nota: l'affinita' storica include anche il job stesso (lieve leakage) -> stima ottimistica,
ma utile come baseline confrontabile nel tempo.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from ...previsioni import costruisci_indici, prevedi_ore


class Command(BaseCommand):
    help = "Backtest dell'accuratezza della predizione ore sullo storico."

    def handle(self, *args, **opts):
        from ...models import Pianificazione

        ciclo_tempi, affinita_ore, famiglia_ore = costruisci_indici()
        reali = Pianificazione.objects.filter(ore__isnull=False)
        totale = reali.count()

        n = coperti = entro20 = 0
        somma_err = somma_err_pct = 0.0
        per_fonte: dict[str, int] = {}

        for p in reali.iterator():
            pred, fonte, _conf = prevedi_ore(
                qta=p.qta, macchina_id=p.macchina_id, famiglia_id=p.famiglia_id,
                ciclo_tempi=ciclo_tempi, affinita_ore=affinita_ore, famiglia_ore=famiglia_ore,
            )
            if pred is None:
                continue
            coperti += 1
            per_fonte[fonte] = per_fonte.get(fonte, 0) + 1
            actual = float(p.ore)
            err = abs(pred - actual)
            somma_err += err
            if actual > 0:
                pct = err / actual
                somma_err_pct += pct
                if pct <= 0.20:
                    entro20 += 1
            n += 1

        self.stdout.write(self.style.MIGRATE_HEADING("Backtest predizione ore"))
        self.stdout.write(f"  Pianificazioni con ore reali : {totale}")
        if not n:
            self.stdout.write(self.style.WARNING("  Nessuna predizione possibile (mancano cicli/affinita')."))
            return
        self.stdout.write(f"  Coperte da una predizione    : {coperti} ({100*coperti/max(totale,1):.0f}%)")
        self.stdout.write(f"  MAE (ore)                    : {somma_err/n:.2f}")
        self.stdout.write(f"  Errore medio %               : {100*somma_err_pct/n:.0f}%")
        self.stdout.write(f"  Entro +/-20%                 : {entro20} ({100*entro20/n:.0f}%)")
        self.stdout.write(f"  Per fonte                    : {per_fonte}")
