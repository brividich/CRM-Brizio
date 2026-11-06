"""Importa i numeri di badge da Solari nell'anagrafica aziendale del portale.

Il numero è l'ultimo con cui la persona ha timbrato; l'aggancio è per codice fiscale.

Uso:
    python manage.py importa_badge_solari                # mostra le differenze
    python manage.py importa_badge_solari --apply        # riempie i badge mancanti
    python manage.py importa_badge_solari --apply --sovrascrivi   # aggiorna anche quelli diversi

Non cancella niente. Lo stesso numero su due persone non si importa: va chiarito a mano.
Nell'output ci sono solo conteggi e id anagrafica, mai i numeri di badge.
"""
from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


def _codice(valore) -> str:
    """Come il form di Anagrafica: niente spazi né zeri a sinistra."""
    testo = str(valore or "").strip()
    return (testo.lstrip("0") or "0") if testo.isdigit() else testo


class Command(BaseCommand):
    help = "Importa i numeri di badge da Solari nell'anagrafica aziendale del portale."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Applica (senza: solo anteprima).")
        parser.add_argument("--sovrascrivi", action="store_true", help="Aggiorna anche i badge diversi da Solari.")

    def handle(self, *args, apply: bool, sovrascrivi: bool, **opts):
        from anagrafica.models import DipendenteAnagraficaAziendale, DipendenteAnagraficaCivile
        from presenti import solari

        try:
            da_solari = {cf: _codice(b) for cf, b in solari.leggi_badge().items() if _codice(b)}
        except solari.SolariNonConfigurato as exc:
            raise CommandError(str(exc)) from exc

        lid_per_cf = {
            (cf or "").strip().upper(): int(lid)
            for cf, lid in DipendenteAnagraficaCivile.objects.exclude(codice_fiscale="")
            .values_list("codice_fiscale", "legacy_anagrafica_id")
        }
        attuali = {
            int(lid): _codice(b)
            for lid, b in DipendenteAnagraficaAziendale.objects.values_list("legacy_anagrafica_id", "badge")
            if lid is not None
        }

        doppi = Counter(da_solari.values())
        non_nel_portale = 0
        doppi_solari: list[int] = []
        gia_uguali = 0
        diversi: list[tuple[int, str]] = []
        mancanti: list[tuple[int, str]] = []
        for cf, badge in da_solari.items():
            lid = lid_per_cf.get(cf)
            if lid is None:
                non_nel_portale += 1
            elif doppi[badge] > 1:
                doppi_solari.append(lid)
            elif attuali.get(lid) == badge:
                gia_uguali += 1
            elif attuali.get(lid):
                diversi.append((lid, badge))
            else:
                mancanti.append((lid, badge))

        da_scrivere = mancanti + (diversi if sovrascrivi else [])
        # Il numero non deve restare anche su un'altra persona del portale.
        scritti = {lid for lid, _ in da_scrivere}
        occupati = {b: lid for lid, b in attuali.items() if b and lid not in scritti}
        in_conflitto = sorted(lid for lid, b in da_scrivere if occupati.get(b, lid) != lid)
        da_scrivere = [(lid, b) for lid, b in da_scrivere if lid not in in_conflitto]

        self.stdout.write(f"Persone con badge in Solari: {len(da_solari)}")
        self.stdout.write(f"Già uguali: {gia_uguali}")
        self.stdout.write(f"Mancanti nel portale: {len(mancanti)}")
        self.stdout.write(f"Diversi da Solari: {len(diversi)}" + ("" if sovrascrivi else " (restano così, serve --sovrascrivi)"))
        self.stdout.write(f"Non presenti nel portale per codice fiscale: {non_nel_portale}")
        if diversi:
            self.stdout.write("Id anagrafica con badge diverso: " + ", ".join(str(lid) for lid, _ in sorted(diversi)))
        if doppi_solari:
            self.stdout.write("Stesso badge a più persone in Solari, non importati: " + ", ".join(map(str, sorted(doppi_solari))))
        if in_conflitto:
            self.stdout.write("Badge già di un'altra persona del portale, non importati: " + ", ".join(map(str, in_conflitto)))

        if not apply:
            self.stdout.write(f"Anteprima: scriverei {len(da_scrivere)} badge. Per applicare: --apply")
            return
        with transaction.atomic():
            for lid, badge in da_scrivere:
                DipendenteAnagraficaAziendale.objects.update_or_create(legacy_anagrafica_id=lid, defaults={"badge": badge})
        self.stdout.write(self.style.SUCCESS(f"Badge scritti: {len(da_scrivere)}"))
