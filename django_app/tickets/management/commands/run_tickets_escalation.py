"""Promemoria + escalation ticket urgenti non assegnati.

Utilizzo:
    python manage.py run_tickets_escalation                 # reminder + email se in finestra
    python manage.py run_tickets_escalation --dry-run       # mostra i ticket, no scrittura
    python manage.py run_tickets_escalation --force-email   # invia il resoconto a prescindere
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Promemoria dashboard + resoconto email per i ticket URGENTI aperti e non assegnati."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra i ticket da escalare senza creare notifiche né inviare email.",
        )
        parser.add_argument(
            "--force-email",
            action="store_true",
            help="Invia il resoconto email a prescindere da giorno/ora/attivazione.",
        )

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))
        force_email = bool(options.get("force_email"))

        from tickets.escalation_config import get_escalation_config
        from tickets.tasks import _fetch_tickets_da_escalare

        cfg = get_escalation_config()
        soglia = int(cfg["soglia_ore"])

        if dry_run:
            tickets = list(_fetch_tickets_da_escalare(soglia))
            self.stdout.write(
                f"[dry-run] attivo={cfg['attivo']} soglia={soglia}h ora_invio={cfg['ora_invio']} "
                f"giorni={cfg['cadenza_label']}"
            )
            self.stdout.write(f"[dry-run] ticket urgenti non assegnati: {len(tickets)}")
            from django.utils import timezone
            for t in tickets:
                ore = int((timezone.now() - t.created_at).total_seconds() // 3600) if t.created_at else 0
                self.stdout.write(f"  • [{t.numero_ticket}] {t.titolo} — aperto da {ore}h")
            return

        from tickets.tasks import run_tickets_escalation

        result = run_tickets_escalation(force_email=force_email)
        self.stdout.write(
            self.style.SUCCESS(
                f"Promemoria creati: {result['reminders']} · email inviata: {result['email_sent']} · "
                f"ticket urgenti non assegnati: {result['tickets']}"
            )
        )
