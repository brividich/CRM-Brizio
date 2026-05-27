"""Invia promemoria email per i corsi formativi scaduti o in scadenza.

TODO PATCH-09: implementare invio email digest per HR + notifica dipendente.
Pattern speculare a ``send_visite_expiry_reminders.py`` — stub predisposto.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Invia promemoria email per scadenze formazione (stub — implementazione in PATCH-09). "
        "Attualmente non invia email."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run", action="store_true", default=False,
            help="Simula senza inviare email.",
        )

    def handle(self, *args, **options) -> None:
        # TODO PATCH-09: implementare logica di notifica.
        # Seguire il pattern di send_visite_expiry_reminders:
        #   1. Recuperare tutti i TrainingDeadline con stato SCADUTO / IN_SCADENZA_30
        #   2. Raggruppare per dipendente
        #   3. Inviare digest a HR (da SiteConfig "training_reminder_emails")
        #   4. Notifica in-app via core.notifiche.invia_notifica
        self.stdout.write(
            self.style.WARNING(
                "send_training_expiry_reminders: stub — nessuna email inviata. "
                "Implementazione prevista in PATCH-09."
            )
        )
