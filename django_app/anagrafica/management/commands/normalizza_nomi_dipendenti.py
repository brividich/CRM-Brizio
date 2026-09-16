"""Normalizza NOME e COGNOME dei dipendenti nel formato canonico a iniziali maiuscole.

La tabella legacy ``anagrafica_dipendenti`` è stata popolata in momenti diversi:
l'import massivo ha scritto tutto MAIUSCOLO, gli inserimenti a mano hanno scritto
come capitava. Da qui in avanti la normalizzazione è garantita in scrittura da
``core.legacy_anagrafica.upsert_anagrafica_dipendente``; questo comando serve a
sistemare una volta sola le righe già presenti.

Uso:
    # Anteprima: mostra cosa cambierebbe, non tocca nulla
    python manage.py normalizza_nomi_dipendenti

    # Applica
    python manage.py normalizza_nomi_dipendenti --apply
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connections, transaction

from core import naming


class Command(BaseCommand):
    help = (
        "Uniforma nome e cognome dei dipendenti legacy nel formato a iniziali "
        "maiuscole (dry-run di default, --apply per scrivere)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Scrive le modifiche. Senza questo flag il comando è di sola lettura.",
        )

    def handle(self, *args, **options):
        applica = bool(options.get("apply"))

        with connections["default"].cursor() as cur:
            cur.execute(
                "SELECT id, nome, cognome FROM anagrafica_dipendenti ORDER BY cognome, nome"
            )
            righe = cur.fetchall()

        da_cambiare = []
        for row_id, nome, cognome in righe:
            nuovo_nome = naming.normalizza_parte(nome)
            nuovo_cognome = naming.normalizza_parte(cognome)
            if nuovo_nome != (nome or "") or nuovo_cognome != (cognome or ""):
                da_cambiare.append((row_id, nome, cognome, nuovo_nome, nuovo_cognome))

        self.stdout.write(f"Dipendenti esaminati: {len(righe)}")
        self.stdout.write(f"Da normalizzare: {len(da_cambiare)}")

        for row_id, nome, cognome, nuovo_nome, nuovo_cognome in da_cambiare:
            self.stdout.write(
                f"  [{row_id}] {nome or ''} {cognome or ''}"
                f"  ->  {nuovo_nome} {nuovo_cognome}"
            )

        if not da_cambiare:
            self.stdout.write(self.style.SUCCESS("Nessuna modifica necessaria."))
            return

        if not applica:
            self.stdout.write(
                self.style.WARNING("Dry-run: nessuna modifica scritta. Rilancia con --apply.")
            )
            return

        with transaction.atomic(using="default"):
            with connections["default"].cursor() as cur:
                for row_id, _nome, _cognome, nuovo_nome, nuovo_cognome in da_cambiare:
                    cur.execute(
                        "UPDATE anagrafica_dipendenti SET nome = %s, cognome = %s WHERE id = %s",
                        [nuovo_nome, nuovo_cognome, int(row_id)],
                    )

        self.stdout.write(
            self.style.SUCCESS(f"Normalizzati {len(da_cambiare)} dipendenti.")
        )
