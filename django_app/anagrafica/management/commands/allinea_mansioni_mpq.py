"""Assegnazione e livello sulle mansioni collegate ai ruoli dei processi MOD.128.

    python manage.py allinea_mansioni_mpq [--dry-run]

Gira già con il ricalcolo delle scadenze (dopo i salvataggi e la notte): a mano
serve dopo il deploy o per controllo. In prova elenca i cambi senza scrivere.
"""
from django.core.management.base import BaseCommand

from anagrafica.services.mpq_competenze import allinea


class Command(BaseCommand):
    help = "Allinea assegnazioni e livelli delle mansioni collegate ai ruoli MOD.128."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Elenca i cambi senza scrivere.")

    def handle(self, *args, **opts):
        esito = allinea(applica=not opts["dry_run"])
        for lid, mansione, prima, dopo in esito["cambi"]:
            self.stdout.write(f"#{lid} · {mansione}: {prima or '—'} → {dopo}")
        self.stdout.write(self.style.SUCCESS(
            f"{'In prova: ' if opts['dry_run'] else ''}assegnate {esito['assegnate']}, "
            f"alzate {esito['alzate']}, abbassate {esito['abbassate']}"))
