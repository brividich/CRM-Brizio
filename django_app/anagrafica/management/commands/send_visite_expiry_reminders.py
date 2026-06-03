"""Invia promemoria email per le visite mediche scadute o in scadenza.

Pattern speculare a ``dpi/management/commands/send_dpi_expiry_reminders.py``.
Per ogni dipendente attivo calcola lo stato delle visite richieste in base
ai ruoli operativi assegnati (``anagrafica.services.visite.stato_visite``)
e produce un digest email per i responsabili + notifica al dipendente.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import SiteConfig
from core.notifiche import invia_notifica

from anagrafica.models import DipendenteAnagraficaAziendale, DipendenteRuoloOperativo
from anagrafica.services.visite import STATO_IN_SCADENZA, STATO_SCADUTA, stato_visite


def _split_emails(raw: str) -> list[str]:
    cleaned = (raw or "").replace("\r", "\n").replace(",", "\n").replace(";", "\n")
    return [email.strip() for email in cleaned.split("\n") if email.strip()]


def _get_recipients(override: list[str] | None) -> list[str]:
    if override:
        return [email.strip() for email in override if email.strip()]

    recipients: list[str] = []
    recipients.extend(_split_emails(SiteConfig.get("visite_reminder_emails", "")))

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


def _dipendenti_attivi_legacy_ids() -> list[int]:
    """Restituisce gli ID legacy dei dipendenti con almeno un ruolo operativo
    e non cessati (``data_cessazione=None``)."""
    legacy_ids_con_ruoli = set(
        DipendenteRuoloOperativo.objects.values_list("legacy_anagrafica_id", flat=True).distinct()
    )
    if not legacy_ids_con_ruoli:
        return []
    cessati = set(
        DipendenteAnagraficaAziendale.objects
        .filter(data_cessazione__isnull=False, legacy_anagrafica_id__in=legacy_ids_con_ruoli)
        .values_list("legacy_anagrafica_id", flat=True)
    )
    return sorted(legacy_ids_con_ruoli - cessati)


class Command(BaseCommand):
    help = "Digest email delle visite mediche scadute o in scadenza."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=60,
            help="Giorni di anticipo per visite in scadenza (default: 60).",
        )
        parser.add_argument(
            "--recipients", nargs="*",
            help="Email destinatari (sovrascrive SiteConfig/ADMINS).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Stampa senza inviare email.")

    def handle(self, *args, **options):
        today = timezone.localdate()
        days = max(1, int(options.get("days") or 60))
        dry_run = bool(options.get("dry_run"))
        recipients = _get_recipients(options.get("recipients") or [])

        legacy_ids = _dipendenti_attivi_legacy_ids()

        scadute: list[tuple[int, dict]] = []
        in_scadenza: list[tuple[int, dict]] = []
        for legacy_id in legacy_ids:
            try:
                stato = stato_visite(legacy_id, soglia_giorni_avviso=days)
            except Exception:
                continue
            for row in stato:
                if row["stato"] == STATO_SCADUTA:
                    scadute.append((legacy_id, row))
                elif row["stato"] == STATO_IN_SCADENZA:
                    in_scadenza.append((legacy_id, row))

        if not scadute and not in_scadenza:
            self.stdout.write("Nessuna visita medica scaduta o in scadenza.")
            return

        lines = [
            f"NOVICROM HUB - Promemoria visite mediche del {today:%d/%m/%Y}",
            "=" * 60,
            "",
        ]

        if scadute:
            lines.append(f"VISITE SCADUTE ({len(scadute)}):")
            for legacy_id, row in scadute:
                tipo = row["tipo"]
                scad = row["data_scadenza"]
                days_over = (today - scad).days if scad else 0
                lines.append(
                    f"  [{days_over}gg] dipendente #{legacy_id} - {tipo.nome}"
                    f" - scaduta il {scad:%d/%m/%Y}" if scad else
                    f"  dipendente #{legacy_id} - {tipo.nome} - scaduta"
                )
                if not dry_run:
                    invia_notifica(
                        legacy_id,
                        "visita_scadenza",
                        f"Visita medica scaduta: {tipo.nome}"
                        + (f" dal {scad:%d/%m/%Y}." if scad else "."),
                        "/anagrafica/dipendenti/",
                    )
            lines.append("")

        if in_scadenza:
            lines.append(f"VISITE IN SCADENZA entro {days} giorni ({len(in_scadenza)}):")
            for legacy_id, row in in_scadenza:
                tipo = row["tipo"]
                scad = row["data_scadenza"]
                days_left = row.get("giorni_a_scadenza") or 0
                lines.append(
                    f"  [{days_left}gg] dipendente #{legacy_id} - {tipo.nome}"
                    f" - scadenza {scad:%d/%m/%Y}"
                )
                if not dry_run:
                    invia_notifica(
                        legacy_id,
                        "visita_scadenza",
                        f"Visita medica in scadenza tra {days_left} giorni: {tipo.nome}.",
                        "/anagrafica/dipendenti/",
                    )
            lines.append("")

        body = "\n".join(lines)
        subject = (
            f"[VISITE MEDICHE] {len(scadute)} scadute + {len(in_scadenza)}"
            f" in scadenza - {today:%d/%m/%Y}"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] Nessuna email inviata."))
            self.stdout.write(f"Destinatari: {recipients}")
            self.stdout.write(body)
            return

        if not recipients:
            self.stdout.write(self.style.ERROR(
                "Nessun destinatario configurato (SiteConfig 'visite_reminder_emails' / ADMINS vuoti)."
            ))
            return

        from core.email_utils import send_hub_mail
        send_hub_mail(
            subject, body, recipients,
            email_type="Anagrafica HR",
            section_label="Reminder visite mediche",
            fail_silently=False,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Email inviata a {len(recipients)} destinatari."
            f" Scadute={len(scadute)} In_scadenza={len(in_scadenza)}"
        ))
