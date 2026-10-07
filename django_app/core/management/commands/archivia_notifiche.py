"""Archivia le notifiche in-app scadute ed elimina le archiviate oltre soglia.

Utilizzo:
    python manage.py archivia_notifiche --dry-run
    python manage.py archivia_notifiche

Le soglie sono in SiteConfig (Admin portale → Gestione notifiche). Lo stesso
lavoro gira ogni notte via django-q (schedule ``notifiche_archivio``).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Archivia le notifiche in-app scadute ed elimina le archiviate oltre la conservazione."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Conta soltanto, senza modificare il DB.")

    def handle(self, *args, **options):
        from core.notifiche_archivio import archivia_scadute, get_politica

        politica = get_politica()
        dry_run = bool(options.get("dry_run"))
        self.stdout.write(
            f"Soglie: non lette {politica.non_lette or 'mai'} gg · lette {politica.lette or 'mai'} gg · "
            f"eliminazione archiviate {politica.elimina or 'mai'} gg"
        )
        esito = archivia_scadute(dry_run=dry_run, politica=politica)
        prefisso = "[dry-run] " if dry_run else ""
        verbo = "da archiviare" if dry_run else "archiviate"
        self.stdout.write(self.style.SUCCESS(
            f"{prefisso}Non lette {verbo}: {esito['non_lette']} · lette {verbo}: {esito['lette']} · "
            f"{'da eliminare' if dry_run else 'eliminate'}: {esito['eliminate']}"
        ))
