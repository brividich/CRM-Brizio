"""Reinvia a SharePoint i movimenti RENTRI rimasti non allineati.

    python manage.py rentri_sync_riprova [--dry-run]

Il registro del portale fa fede: qui si ripete solo l'invio dei movimenti che
hanno ``sync_errore`` valorizzato, senza toccare i loro dati.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from rentri.models import RegistroRifiuti
from rentri.sharepoint import _graph_configured, sincronizza


class Command(BaseCommand):
    help = "Reinvia a SharePoint i movimenti RENTRI con un errore di sincronizzazione."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Elenca senza inviare.")

    def handle(self, *args, **options):
        qs = RegistroRifiuti.objects.exclude(sync_errore="").order_by("data", "id")
        self.stdout.write(f"Movimenti da reinviare: {qs.count()}")
        if options["dry_run"]:
            for r in qs:
                self.stdout.write(f"  {r.tipo} {r.id_registrazione} · {r.sync_errore}")
            return
        if not _graph_configured():
            self.stderr.write("Graph non configurato: nessun invio possibile.")
            return
        ok = ko = 0
        for r in qs:
            if sincronizza(r):
                ok += 1
            else:
                ko += 1
        self.stdout.write(self.style.SUCCESS(f"Allineati: {ok}") + (f" · ancora in errore: {ko}" if ko else ""))
