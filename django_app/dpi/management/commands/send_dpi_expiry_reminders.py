"""Invia promemoria email per DPI scaduti o in scadenza."""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import SiteConfig
from core.notifiche import invia_notifica
from dpi.models import ConsegnaDPI, DPIImpostazioni, StatoRichiesta


def _split_emails(raw: str) -> list[str]:
    cleaned = raw.replace("\r", "\n").replace(",", "\n").replace(";", "\n")
    return [email.strip() for email in cleaned.split("\n") if email.strip()]


def _get_recipients(override: list[str] | None) -> list[str]:
    if override:
        return [email.strip() for email in override if email.strip()]

    recipients: list[str] = []
    impost = DPIImpostazioni.get_singleton()
    recipients.extend(
        person.get("email", "").strip()
        for person in (impost.responsabili or [])
        if isinstance(person, dict) and person.get("email")
    )
    if impost.responsabile_email:
        recipients.append(impost.responsabile_email.strip())
    recipients.extend(_split_emails(impost.notifica_email_extra))
    recipients.extend(_split_emails(SiteConfig.get("dpi_reminder_emails", "")))

    if not recipients:
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
    help = "Invia un digest email dei DPI scaduti o in scadenza."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Giorni di anticipo per DPI in scadenza (default: 30).",
        )
        parser.add_argument(
            "--recipients",
            nargs="*",
            help="Email destinatari (sovrascrive impostazioni DPI/SiteConfig/ADMINS).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Stampa senza inviare email.")

    def handle(self, *args, **options):
        today = timezone.localdate()
        days = max(1, int(options.get("days") or 30))
        horizon = today + timedelta(days=days)
        dry_run = bool(options.get("dry_run"))
        recipients = _get_recipients(options.get("recipients") or [])

        scaduti = list(
            ConsegnaDPI.objects.filter(
                richiesta__stato=StatoRichiesta.CONSEGNATA,
                data_scadenza_stimata__isnull=False,
                data_scadenza_stimata__lt=today,
            )
            .select_related("richiesta", "richiesta__categoria", "richiesta__tipo_dpi", "richiesta__modello_dpi", "richiesta__taglia_dpi")
            .order_by("data_scadenza_stimata")
        )
        in_scadenza = list(
            ConsegnaDPI.objects.filter(
                richiesta__stato=StatoRichiesta.CONSEGNATA,
                data_scadenza_stimata__isnull=False,
                data_scadenza_stimata__gte=today,
                data_scadenza_stimata__lte=horizon,
            )
            .select_related("richiesta", "richiesta__categoria", "richiesta__tipo_dpi", "richiesta__modello_dpi", "richiesta__taglia_dpi")
            .order_by("data_scadenza_stimata")
        )

        if not scaduti and not in_scadenza:
            self.stdout.write("Nessun DPI scaduto o in scadenza.")
            return

        lines = [
            f"NOVICROM HUB - Promemoria DPI del {today:%d-%m-%Y}",
            "=" * 60,
            "",
        ]
        if scaduti:
            lines.append(f"DPI SCADUTI ({len(scaduti)}):")
            for consegna in scaduti:
                r = consegna.richiesta
                days_over = (today - consegna.data_scadenza_stimata).days
                lines.append(
                    f"  [{days_over}gg] {r.numero} - {r.richiedente_nome} - "
                    f"{r.categoria.nome} - scaduto il {consegna.data_scadenza_stimata:%d-%m-%Y}"
                )
                if not dry_run and r.richiedente_legacy_id:
                    invia_notifica(
                        r.richiedente_legacy_id,
                        "dpi_scadenza",
                        f"DPI scaduto: {r.numero} - {r.categoria.nome} dal {consegna.data_scadenza_stimata:%d-%m-%Y}.",
                        f"/dpi/{r.pk}/",
                    )
            lines.append("")

        if in_scadenza:
            lines.append(f"DPI IN SCADENZA entro {days} giorni ({len(in_scadenza)}):")
            for consegna in in_scadenza:
                r = consegna.richiesta
                days_left = (consegna.data_scadenza_stimata - today).days
                lines.append(
                    f"  [{days_left}gg] {r.numero} - {r.richiedente_nome} - "
                    f"{r.categoria.nome} - scadenza {consegna.data_scadenza_stimata:%d-%m-%Y}"
                )
                if not dry_run and r.richiedente_legacy_id:
                    invia_notifica(
                        r.richiedente_legacy_id,
                        "dpi_scadenza",
                        f"DPI in scadenza tra {days_left} giorni: {r.numero} - {r.categoria.nome}.",
                        f"/dpi/{r.pk}/",
                    )
            lines.append("")

        body = "\n".join(lines)
        subject = f"[DPI] {len(scaduti)} scaduti + {len(in_scadenza)} in scadenza - {today:%d-%m-%Y}"

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] Nessuna email inviata."))
            self.stdout.write(f"Destinatari: {recipients}")
            self.stdout.write(body)
            return

        if not recipients:
            self.stdout.write(self.style.ERROR("Nessun destinatario configurato per i reminder DPI."))
            return

        from core.email_utils import send_hub_mail
        send_hub_mail(
            subject, body, recipients,
            email_type="DPI",
            section_label="Reminder scadenze",
            fail_silently=False,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Email inviata a {len(recipients)} destinatari. Scaduti={len(scaduti)} In_scadenza={len(in_scadenza)}"
        ))
