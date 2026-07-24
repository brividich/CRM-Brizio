"""Reminder delle voci OFI in scadenza/scadute (registro MOD.174, 4.2).

Schedulabile via django-q (pattern scadenze già in casa). Fail-safe: l'invio
email non blocca; marca ``reminder_inviato`` sulle voci trattate.

Esempi:
    manage.py send_ofi_reminders --dry-run
    manage.py send_ofi_reminders --days 7
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from ...registro_ofi import invia_reminder_ofi


class Command(BaseCommand):
    help = "Invia i reminder per le voci del registro OFI in scadenza o scadute."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=0,
            help="Sollecita anche le voci in scadenza entro N giorni (default: solo scadute).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Non invia nulla e non marca: mostra solo quante voci verrebbero sollecitate.",
        )

    def handle(self, *args, **opts):
        res = invia_reminder_ofi(giorni=opts["days"], dry_run=opts["dry_run"])
        if res["dry_run"]:
            self.stdout.write(self.style.WARNING(
                f"[dry-run] {res['candidate']} voci OFI da sollecitare (nessun invio)."))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Reminder OFI: {res['inviati']}/{res['candidate']} voci sollecitate."))
