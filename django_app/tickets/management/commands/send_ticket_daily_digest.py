"""AU52 - Digest manutentore giornaliero: "i miei ticket di oggi".

Job schedulato (NON regola del designer automazioni): da lanciare ogni mattina via
Task Scheduler di Windows, sul pattern di `send_sla_reminders`.

Esempio schedulazione (Task Windows):
    python manage.py send_ticket_daily_digest

Invia a ciascun assegnatario (raggruppando per `assegnato_email`) i ticket ancora aperti
con scadenza prevista oggi o già scaduta. Stato: SCAFFOLD funzionante.
"""
from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.utils import timezone

from tickets.models import StatoTicket, Ticket

_OPEN_STATES = [StatoTicket.APERTA, StatoTicket.IN_CARICO, StatoTicket.IN_ATTESA]


class Command(BaseCommand):
    help = "AU52 - Digest giornaliero dei ticket assegnati in scadenza/scaduti, per assegnatario."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Stampa senza inviare email.")

    def handle(self, *args, **options):
        today = timezone.localdate()
        dry_run = bool(options.get("dry_run"))

        tickets = list(
            Ticket.objects.filter(
                stato__in=_OPEN_STATES,
                data_prevista_risoluzione__isnull=False,
                data_prevista_risoluzione__lte=today,
            )
            .exclude(assegnato_email="")
            .order_by("assegnato_email", "data_prevista_risoluzione")
        )
        if not tickets:
            self.stdout.write("Nessun ticket assegnato in scadenza/scaduto oggi.")
            return

        by_assignee: dict[str, list[Ticket]] = defaultdict(list)
        for t in tickets:
            by_assignee[t.assegnato_email.strip()].append(t)

        from core.email_utils import send_hub_mail
        sent = 0
        for email, items in by_assignee.items():
            if not email:
                continue
            lines = [
                f"NOVICROM HUB - I tuoi ticket di oggi ({today:%d-%m-%Y})",
                "=" * 60,
                f"Ticket assegnati in scadenza o scaduti ({len(items)}):",
                "",
            ]
            for t in items:
                days_over = (today - t.data_prevista_risoluzione).days
                tag = "SCADUTO" if days_over > 0 else "OGGI"
                lines.append(
                    f"  [{tag}] {t.numero_ticket} - {t.titolo} - stato {t.stato} - "
                    f"prevista {t.data_prevista_risoluzione:%d-%m-%Y}"
                )
            body = "\n".join(lines)
            subject = f"[Ticket] {len(items)} da gestire oggi - {today:%d-%m-%Y}"

            if dry_run:
                self.stdout.write(self.style.WARNING(f"[DRY-RUN] -> {email} ({len(items)} ticket)"))
                self.stdout.write(body)
                continue
            from core.notifiche_prefs import should_notify

            if not should_notify(tipo="ticket_sla"):
                continue
            send_hub_mail(
                subject, body, [email],
                email_type="Tickets", section_label="Digest giornaliero", fail_silently=True,
            )
            sent += 1

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"Digest inviato a {sent} assegnatari ({len(tickets)} ticket totali)."))
