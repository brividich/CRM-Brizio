"""Elenca i lavori a rischio ritardo: fine prevista (durata stimata) oltre la consegna.

Uso: python manage.py previsioni_ritardi
Richiede pianificazioni collegate a una commessa con data_consegna (vedi follow-up: link
commesse<->pianificazioni). Dove il collegamento manca, il lavoro non e' valutabile.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from ...previsioni import costruisci_indici, prevedi_ore, rischio_ritardo


class Command(BaseCommand):
    help = "Report dei lavori a rischio ritardo (fine prevista oltre la consegna)."

    def handle(self, *args, **opts):
        from ...models import Pianificazione

        ciclo_tempi, affinita_ore, famiglia_ore = costruisci_indici()
        qs = (
            Pianificazione.objects.filter(commessa__data_consegna__isnull=False)
            .select_related("macchina__asset", "commessa", "famiglia")
        )

        valutate = in_ritardo = 0
        rischi = []
        for p in qs.iterator():
            ore = float(p.ore) if p.ore else None
            if ore is None:
                ore, _f, _c = prevedi_ore(
                    qta=p.qta, macchina_id=p.macchina_id, famiglia_id=p.famiglia_id,
                    ciclo_tempi=ciclo_tempi, affinita_ore=affinita_ore, famiglia_ore=famiglia_ore,
                )
            ogg = float(p.macchina.ore_giorno_disponibili) if p.macchina_id else 8.0
            r = rischio_ritardo(
                data_inizio=p.data, ore_previste=ore, ore_giorno=ogg,
                data_consegna=p.commessa.data_consegna,
            )
            if not r["valutabile"]:
                continue
            valutate += 1
            if r["in_ritardo"]:
                in_ritardo += 1
                rischi.append((p, r))

        self.stdout.write(self.style.MIGRATE_HEADING("Rischio ritardo"))
        self.stdout.write(f"  Valutate (commessa+consegna) : {valutate}")
        self.stdout.write(f"  In ritardo previsto          : {in_ritardo}")
        for p, r in sorted(rischi, key=lambda x: x[1]["giorni_margine"])[:20]:
            cod = p.macchina.codice if p.macchina_id else "?"
            self.stdout.write(
                f"  - {cod:<12} {p.testo_originale[:30]:<30} fine~{r['fine_prevista']} "
                f"vs consegna {p.commessa.data_consegna} ({r['giorni_margine']} gg)"
            )
        if not valutate:
            self.stdout.write(self.style.WARNING(
                "  Nessun lavoro valutabile: servono commesse collegate con data_consegna."
            ))
