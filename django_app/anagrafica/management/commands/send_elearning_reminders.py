"""Promemoria micro-corsi e-learning ancora da completare — STUB (D7).

In questa fase NON invia nulla: seleziona le iscrizioni e-learning non completate e
ne stampa il conteggio (utile per schedularlo a vuoto e verificare i numeri). La
logica di invio sarà aggiunta in una patch successiva, agganciandosi agli hook in
``anagrafica/services/elearning_notifications.py``.

Pattern allineato a ``send_formazione_session_reminders`` / ``send_visite_mediche_digest``.
Schedulare via Task Scheduler (QCluster) usando intervalli in MINUTI.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "STUB: elenca i micro-corsi e-learning non completati (nessun invio finché D7 non è implementata)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Sempre attivo: questo command non invia ancora.")

    def handle(self, *args, **options):
        from anagrafica.services.elearning_notifications import iter_corsi_da_completare

        n = 0
        for iscr in iter_corsi_da_completare():
            n += 1
            self.stdout.write(
                f"  [da completare] dip={iscr.legacy_anagrafica_id} corso={iscr.corso.codice} stato={iscr.stato}"
            )
        self.stdout.write(self.style.WARNING(
            f"Trovate {n} iscrizioni e-learning da completare. Invio non implementato (D7 — hook predisposti)."
        ))
