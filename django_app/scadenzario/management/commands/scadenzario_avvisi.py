"""Anteprima del prossimo invio degli avvisi: non spedisce e non scrive nulla.

    python manage.py scadenzario_avvisi
    python manage.py scadenzario_avvisi --giorno 2026-12-01
"""
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Mostra quali avvisi delle scadenze generiche partirebbero, senza inviarli."

    def add_arguments(self, parser):
        parser.add_argument("--prova", action="store_true", help="Sempre attiva: il comando non invia mai.")
        parser.add_argument("--giorno", default="", help="Giorno da simulare, AAAA-MM-GG (predefinito: il prossimo invio).")

    def handle(self, *args, **opts):
        from scadenzario.avvisi import anteprima

        giorno = None
        if opts["giorno"]:
            try:
                giorno = date.fromisoformat(opts["giorno"])
            except ValueError as exc:
                raise CommandError("Giorno non valido: usa AAAA-MM-GG.") from exc
        esito = anteprima(oggi=giorno)
        self.stdout.write(f"Invio del {esito['giorno']:%d/%m/%Y}: {len(esito['partono'])} mail")
        for r in esito["partono"]:
            s = r["scadenza"]
            self.stdout.write(f"  - {s.data_scadenza:%d/%m/%Y} {s.titolo} ({r['stato']}) -> {', '.join(r['destinatari'])}")
        self.stdout.write(f"Nel preavviso senza destinatari (solo riepilogo): {len(esito['senza'])}")
        for r in esito["senza"]:
            s = r["scadenza"]
            self.stdout.write(f"  - {s.data_scadenza:%d/%m/%Y} {s.titolo} ({r['stato']})")
        self.stdout.write(f"Già avvisate, ripartono più avanti: {len(esito['aspettano'])}")
        self.stdout.write("Anteprima: nessuna mail inviata.")
