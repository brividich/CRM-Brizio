"""Carica la struttura della Qualità (MEGA SKILL MATRIX v8) nel portale.

Di default gira IN PROVA: fa tutto dentro una transazione e la annulla, stampa
il rapporto. Con ``--applica`` scrive. Idempotente: si può rilanciare.

    python manage.py carica_struttura_v8                 # prova
    python manage.py carica_struttura_v8 --applica       # scrive
    python manage.py carica_struttura_v8 --senza-aree-persone
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from anagrafica.services import struttura_v8


class Command(BaseCommand):
    help = "Carica la struttura della Qualità (v8): reparti/aree, ruoli, processi, mansioni. Prova di default."

    def add_arguments(self, parser):
        parser.add_argument("--applica", action="store_true", help="Scrive (senza: prova, nulla salvato).")
        parser.add_argument("--senza-aree-persone", action="store_true",
                            help="Non assegna l'area alle persone che non ce l'hanno.")
        parser.add_argument("--solo-da-decidere", action="store_true", help="Stampa solo i punti da decidere.")

    def handle(self, *args, **opts):
        r = struttura_v8.carica(applica=opts["applica"], aree_persone=not opts["senza_aree_persone"])
        righe = r.da_decidere if opts["solo_da_decidere"] else r.righe
        fase = None
        for riga in righe:
            if riga.fase != fase:
                fase = riga.fase
                self.stdout.write(self.style.MIGRATE_HEADING(f"\n== {fase.upper()} =="))
            testo = f"  [{riga.azione}] {riga.oggetto}" + (f" — {riga.dettaglio}" if riga.dettaglio else "")
            self.stdout.write(self.style.WARNING(testo) if riga.azione == "segnala" else testo)
        self.stdout.write("")
        for k, v in sorted(r.conteggi().items()):
            self.stdout.write(f"  {k}: {v}")
        self.stdout.write(self.style.SUCCESS("\nApplicato.") if r.applicato
                          else self.style.NOTICE("\nPROVA: nulla è stato salvato. Rilancia con --applica per scrivere."))
