"""AU47 - Digest trimestrale formazione per audit ISO (HR / RSPP).

Job schedulato (NON regola del designer automazioni): da lanciare trimestralmente via
Task Scheduler di Windows. Si aggancia al backlog P2 (matrice formazione).

Esempio schedulazione (Task Windows):
    python manage.py send_formazione_audit_digest --days 90

Stato: SCAFFOLD funzionante (query reale su TrainingEmployeeRecord). Rifinire l'aggregazione
% copertura per reparto e i destinatari HR/RSPP prima di schedularlo.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from anagrafica.models import TrainingEmployeeRecord


def _get_recipients(override: list[str] | None) -> list[str]:
    if override:
        return [e.strip() for e in override if e.strip()]
    # TODO: sostituire con la fonte HR/RSPP reale.
    recipients: list[str] = []
    admins = getattr(settings, "ADMINS", ()) or ()
    recipients.extend(str(email).strip() for _name, email in admins if str(email).strip())
    if not recipients:
        User = get_user_model()
        recipients.extend(
            User.objects.filter(is_active=True, is_superuser=True)
            .exclude(email="")
            .values_list("email", flat=True)
            .distinct()
        )
    return sorted(set(recipients))


class Command(BaseCommand):
    help = "AU47 - Digest trimestrale formazione (corsi in scadenza) per audit ISO."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=90, help="Finestra scadenza in giorni (default: 90).")
        parser.add_argument("--recipients", nargs="*", help="Email destinatari (sovrascrive la fonte di default).")
        parser.add_argument("--dry-run", action="store_true", help="Stampa senza inviare email.")

    def handle(self, *args, **options):
        today = timezone.localdate()
        days = max(1, int(options.get("days") or 90))
        horizon = today + timedelta(days=days)
        dry_run = bool(options.get("dry_run"))
        recipients = _get_recipients(options.get("recipients") or [])

        in_scadenza = list(
            TrainingEmployeeRecord.objects.filter(
                data_scadenza__isnull=False,
                data_scadenza__gte=today,
                data_scadenza__lte=horizon,
            ).order_by("data_scadenza")
        )
        if not in_scadenza:
            self.stdout.write("Nessun corso in scadenza nella finestra.")
            return

        lines = [
            f"NOVICROM HUB - Digest formazione (audit ISO) del {today:%d/%m/%Y}",
            "=" * 60,
            f"Abilitazioni in scadenza entro {days} giorni ({len(in_scadenza)}):",
            "",
        ]
        # TODO P2: aggregare % copertura per reparto (richiede join anagrafica reparto).
        for rec in in_scadenza:
            days_left = (rec.data_scadenza - today).days
            lines.append(
                f"  [{days_left}gg] dipendente legacy_id={rec.legacy_anagrafica_id} - "
                f"{rec.course_title_snapshot or rec.course_code_snapshot} - scadenza {rec.data_scadenza:%d/%m/%Y}"
            )
        body = "\n".join(lines)
        subject = f"[Formazione ISO] {len(in_scadenza)} abilitazioni in scadenza entro {days}gg - {today:%d/%m/%Y}"

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] Nessuna email inviata."))
            self.stdout.write(f"Destinatari: {recipients}")
            self.stdout.write(body)
            return
        if not recipients:
            self.stdout.write(self.style.ERROR("Nessun destinatario configurato."))
            return

        from core.email_utils import send_hub_mail
        send_hub_mail(
            subject, body, recipients,
            email_type="Anagrafica", section_label="Digest formazione ISO", fail_silently=False,
        )
        self.stdout.write(self.style.SUCCESS(f"Digest inviato a {len(recipients)} destinatari ({len(in_scadenza)} record)."))
