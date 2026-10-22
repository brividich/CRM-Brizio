"""Riscrive il vecchio nome di un reparto rinominato nei campi di testo degli altri moduli.

Serve per le rinomine fatte prima che la rinomina li aggiornasse da sola
(es. «CNC5 - ALESATRICI» -> CN5G del caricamento v8). Prova di default.

    python manage.py riallinea_nome_reparto "CNC5 - ALESATRICI" CN5G
    python manage.py riallinea_nome_reparto "CNC5 - ALESATRICI" CN5G --applica
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from anagrafica.models import Reparto
from anagrafica.services.struttura_aree import propaga_nome_reparto


class Command(BaseCommand):
    help = "Riscrive il vecchio nome di un reparto rinominato in macchine, timbri, utenti e pratiche aperte. Prova di default."

    def add_arguments(self, parser):
        parser.add_argument("vecchio", help="Nome che il reparto aveva prima.")
        parser.add_argument("nuovo", help="Nome attuale del reparto.")
        parser.add_argument("--applica", action="store_true", help="Scrive (senza: prova, nulla salvato).")

    def handle(self, *args, **opts):
        vecchio, nuovo = opts["vecchio"].strip(), opts["nuovo"].strip()
        reparto = Reparto.objects.filter(nome__iexact=nuovo).first()
        if reparto is None:
            raise CommandError(f"Nessun reparto «{nuovo}».")
        if Reparto.objects.filter(nome__iexact=vecchio).exclude(pk=reparto.pk).exists():
            raise CommandError(f"Esiste ancora un reparto «{vecchio}»: non è una rinomina.")
        with transaction.atomic():
            conteggi = propaga_nome_reparto(vecchio, reparto.nome, applica=opts["applica"])
        for chiave, n in conteggi.items():
            self.stdout.write(f"  {chiave}: {n}")
        if opts["applica"]:
            self.stdout.write(self.style.SUCCESS(f"Applicato: «{vecchio}» -> «{reparto.nome}»."))
        else:
            self.stdout.write(self.style.NOTICE("PROVA: nulla è stato salvato. Rilancia con --applica per scrivere."))
