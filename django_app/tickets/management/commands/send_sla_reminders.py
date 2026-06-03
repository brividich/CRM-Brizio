"""
Management command: send_sla_reminders

Trova tutti i ticket aperti con SLA scaduto e invia un reminder via SMTP
all'assegnatario. Nessuna dipendenza esterna oltre Django.

Uso:
    python manage.py send_sla_reminders [--dry-run]
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand

from core.notifiche import invia_notifica_email
from tickets.models import StatoTicket, Ticket


STATI_CHIUSI = {
    StatoTicket.RISOLTO,
    StatoTicket.CHIUSO,
    StatoTicket.ANNULLATO,
}


class Command(BaseCommand):
    help = "Invia reminder via SMTP per i ticket con SLA scaduto."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Mostra i reminder che sarebbero inviati senza spedire email.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]

        tickets_aperti = Ticket.objects.exclude(stato__in=STATI_CHIUSI).select_related("asset")

        inviati = 0
        errori = 0

        for ticket in tickets_aperti:
            tipo_scadenza = self._tipo_scadenza(ticket)
            if tipo_scadenza is None:
                continue

            dest = ticket.assegnato_email.strip() if ticket.assegnato_email else ""
            if not dest:
                self.stdout.write(
                    self.style.WARNING(
                        f"[SKIP] {ticket.numero_ticket} — nessuna email assegnatario"
                    )
                )
                continue

            subject = f"[SLA SCADUTO] Ticket {ticket.numero_ticket}"
            body = self._build_body(ticket, tipo_scadenza)
            from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@novicrom.local")
            notification_message = f"SLA {tipo_scadenza} scaduto per ticket {ticket.numero_ticket}: {ticket.titolo}"
            notification_url = f"/tickets/gestione/{ticket.pk}/"

            if dry_run:
                self.stdout.write(f"[DRY-RUN] Reminder → {dest} | {subject}")
                inviati += 1
                continue

            try:
                from core.email_utils import send_hub_mail
                send_hub_mail(
                    subject, body, [dest],
                    email_type="Tickets",
                    badge="SLA scaduto",
                    section_label="Reminder SLA",
                    from_email=from_email,
                    fail_silently=False,
                )
                invia_notifica_email(dest, "ticket_sla", notification_message, notification_url)
                self.stdout.write(
                    self.style.SUCCESS(f"[OK] Reminder inviato → {dest} | {ticket.numero_ticket}")
                )
                inviati += 1
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(
                    self.style.ERROR(f"[ERRORE] {ticket.numero_ticket} → {dest}: {exc}")
                )
                errori += 1

        label = "simulati" if dry_run else "inviati"
        self.stdout.write(
            self.style.SUCCESS(f"\nReminder {label}: {inviati}  |  Errori: {errori}")
        )

    def _tipo_scadenza(self, ticket: Ticket) -> str | None:
        if ticket.sla_risoluzione_scaduto:
            return "risoluzione"
        if ticket.sla_risposta_scaduto:
            return "risposta"
        return None

    def _build_body(self, ticket: Ticket, tipo_scadenza: str) -> str:
        link = f"/tickets/gestione/{ticket.pk}/"
        return (
            f"Gentile {ticket.assegnato_a or 'operatore'},\n\n"
            f"lo SLA di {tipo_scadenza} per il ticket seguente è SCADUTO:\n\n"
            f"  Numero:   {ticket.numero_ticket}\n"
            f"  Titolo:   {ticket.titolo}\n"
            f"  Stato:    {ticket.label_stato}\n"
            f"  Priorità: {ticket.label_priorita}\n"
            f"  Tipo SLA: {tipo_scadenza.capitalize()}\n\n"
            f"Accedi al ticket: {link}\n\n"
            "Si prega di aggiornare lo stato o prendere in carico il ticket al più presto.\n\n"
            "NOVICROM HUB — notifica automatica SLA"
        )
