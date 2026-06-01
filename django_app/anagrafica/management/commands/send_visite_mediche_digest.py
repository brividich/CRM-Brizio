"""AU45 - Digest mensile visite mediche in scadenza (HR + medico competente).

Job schedulato (NON regola del designer automazioni): da lanciare il 1° del mese via
Task Scheduler di Windows, sul pattern di `send_dpi_expiry_reminders` / `send_sla_reminders`.

Esempio schedulazione (Task Windows):
    python manage.py send_visite_mediche_digest --days 60

Stato: SCAFFOLD funzionante (query reale su VisitaMedica). Rifinire i destinatari
(HR / medico competente per reparto) secondo la configurazione aziendale prima di schedularlo.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from anagrafica.models import VisitaMedica


def _get_recipients(override: list[str] | None) -> list[str]:
    if override:
        return [e.strip() for e in override if e.strip()]
    # TODO: sostituire con la fonte HR/medico competente reale (SiteConfig o impostazioni anagrafica).
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
    help = "AU45 - Digest mensile delle visite mediche in scadenza (HR + medico competente)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=60, help="Anticipo scadenza in giorni (default: 60).")
        parser.add_argument("--recipients", nargs="*", help="Email destinatari (sovrascrive la fonte di default).")
        parser.add_argument("--dry-run", action="store_true", help="Stampa senza inviare email.")

    def handle(self, *args, **options):
        today = timezone.localdate()
        days = max(1, int(options.get("days") or 60))
        horizon = today + timedelta(days=days)
        dry_run = bool(options.get("dry_run"))
        recipients = _get_recipients(options.get("recipients") or [])

        in_scadenza = list(
            VisitaMedica.objects.filter(
                data_scadenza__isnull=False,
                data_scadenza__gte=today,
                data_scadenza__lte=horizon,
            ).order_by("data_scadenza")
        )
        if not in_scadenza:
            self.stdout.write("Nessuna visita medica in scadenza nella finestra.")
            return

        lines = [
            f"NOVICROM HUB - Digest visite mediche del {today:%d/%m/%Y}",
            "=" * 60,
            f"Visite in scadenza entro {days} giorni ({len(in_scadenza)}):",
            "",
        ]
        for v in in_scadenza:
            days_left = (v.data_scadenza - today).days
            lines.append(
                f"  [{days_left}gg] dipendente legacy_id={v.legacy_anagrafica_id} - "
                f"esito {v.esito} - scadenza {v.data_scadenza:%d/%m/%Y}"
            )
        body = "\n".join(lines)
        subject = f"[Visite mediche] {len(in_scadenza)} in scadenza entro {days}gg - {today:%d/%m/%Y}"

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
            email_type="Anagrafica", section_label="Digest visite mediche", fail_silently=False,
        )
        self.stdout.write(self.style.SUCCESS(f"Digest inviato a {len(recipients)} destinatari ({len(in_scadenza)} visite)."))
