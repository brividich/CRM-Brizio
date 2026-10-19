"""Genera la chiave VAPID per le notifiche push (``core.push``).

Stampa le righe da copiare nel ``.env`` del server: non scrive file e non
salva niente nel database. La chiave privata è un segreto come le altre del
``.env`` (resta nel Recovery Kit con il resto del file).

Cambiare la chiave invalida le iscrizioni esistenti: ogni utente deve
riattivare la push sui suoi dispositivi.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Genera VAPID_PRIVATE_KEY per le notifiche push (da copiare nel .env)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--subject", default="",
            help="Contatto per i servizi push, es. mailto:it@azienda.it (default: DEFAULT_FROM_EMAIL).",
        )
        parser.add_argument(
            "--verifica", action="store_true",
            help="Non genera: controlla la chiave già configurata e stampa la pubblica.",
        )

    def handle(self, *args, **options):
        from django.conf import settings

        from core import push

        if options["verifica"]:
            if push.push_configurato():
                self.stdout.write(self.style.SUCCESS("VAPID_PRIVATE_KEY valida."))
                self.stdout.write(f"Chiave pubblica: {push.chiave_pubblica()}")
                self.stdout.write(f"VAPID_SUBJECT: {getattr(settings, 'VAPID_SUBJECT', '') or '(vuoto)'}")
            else:
                self.stdout.write(self.style.WARNING("VAPID_PRIVATE_KEY assente o non valida: push spente."))
            return

        subject = options["subject"] or getattr(settings, "VAPID_SUBJECT", "") or "mailto:it@example.com"
        self.stdout.write("Aggiungi al .env del server (poi riavvia il sito e il qcluster):")
        self.stdout.write("")
        self.stdout.write(f"VAPID_PRIVATE_KEY={push.genera_chiave_privata()}")
        self.stdout.write(f"VAPID_SUBJECT={subject}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(
            "È un segreto: non metterlo in mail, ticket o repository. Cambiarlo disattiva le push già attivate."
        ))
