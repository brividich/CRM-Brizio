"""Viste SQL ``bi_*`` per Power BI (``dati_bi.viste``).

    python manage.py bi_viste                 # elenco e controllo (ogni vista si legge?)
    python manage.py bi_viste --applica       # crea/aggiorna le viste
    python manage.py bi_viste --sql           # stampa l'SQL senza eseguirlo
    python manage.py bi_viste --grant LOGIN   # T-SQL dei permessi per l'utente di Power BI

Le viste nascono con la migrazione ``dati_bi``; ``--applica`` serve dopo un
ripristino o se qualcuno le ha toccate a mano.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from dati_bi import viste


class Command(BaseCommand):
    help = "Controlla, crea o stampa le viste SQL bi_* per Power BI."

    def add_arguments(self, parser):
        parser.add_argument("--applica", action="store_true", help="Crea o aggiorna le viste.")
        parser.add_argument("--sql", action="store_true", help="Stampa l'SQL senza eseguirlo.")
        parser.add_argument("--grant", default="", help="Stampa i GRANT SELECT per questo login SQL.")

    def handle(self, *args, **options):
        if options["grant"]:
            try:
                for stmt in viste.statements_grant(options["grant"]):
                    self.stdout.write(stmt + ";")
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            return
        if options["sql"]:
            for stmt in viste.statements_crea(connection.vendor):
                self.stdout.write(stmt + "\n" + ("GO" if connection.vendor == "microsoft" else ";"))
            return
        if options["applica"]:
            n = viste.crea_viste(connection)
            self.stdout.write(self.style.SUCCESS(f"{n} viste create/aggiornate."))
        errori = 0
        with connection.cursor() as cursor:
            for nome in viste.VISTE:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {nome}")
                    righe = cursor.fetchone()[0]
                    self.stdout.write(f"  {nome}: {righe} righe")
                except Exception as exc:
                    errori += 1
                    self.stdout.write(self.style.ERROR(f"  {nome}: NON LEGGIBILE ({exc.__class__.__name__})"))
        if errori:
            raise CommandError(f"{errori} viste non leggibili: esegui bi_viste --applica.")
