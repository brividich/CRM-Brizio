"""Consolida in blocco le bozze complete del registro RENTRI fino a una data.

    python manage.py rentri_consolida_bozze --fino-al 2026-09-30            (anteprima)
    python manage.py rentri_consolida_bozze --fino-al 2026-09-30 --applica

Le bozze incomplete (senza quantità o senza movimento collegato) restano bozze.
Stessa logica del pulsante dello Scadenzario (``servizi.consolida_in_blocco``).
"""
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from rentri.servizi import consolida_in_blocco


class Command(BaseCommand):
    help = "Consolida le bozze RENTRI complete con data fino a --fino-al (anteprima senza --applica)."

    def add_arguments(self, parser):
        parser.add_argument("--fino-al", required=True, help="Data AAAA-MM-GG, compresa.")
        parser.add_argument("--applica", action="store_true", help="Scrive davvero; senza, solo anteprima.")
        parser.add_argument("--utente", default="comando rentri_consolida_bozze")

    def handle(self, *args, **options):
        try:
            fino_al = date.fromisoformat(options["fino_al"])
        except ValueError as exc:
            raise CommandError("--fino-al: data non valida, usa AAAA-MM-GG") from exc
        esito = consolida_in_blocco(None, fino_al, options["utente"], applica=options["applica"])
        verbo = "Consolidate" if options["applica"] else "Da consolidare (anteprima)"
        self.stdout.write(f"{verbo}: {esito['consolidabili']} · restano bozze incomplete: {esito['incomplete']}")
        for motivo, n in esito["mancanze"].items():
            self.stdout.write(f"  {motivo}: {n}")
        if not options["applica"]:
            self.stdout.write(self.style.WARNING("Nessuna scrittura: aggiungi --applica per consolidare."))
