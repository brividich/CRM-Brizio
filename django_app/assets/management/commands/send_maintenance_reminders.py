"""Invia promemoria email per scadenze manutenzione imminenti.

Schedulare come task Windows quotidiano (suggerito alle 07:00):

    python manage.py send_maintenance_reminders

Controlla:
  1. AssetAdministrativeDeadline in scadenza entro --deadline-days (default: 30)
  2. PeriodicVerification in scadenza entro --deadline-days
  3. WorkOrder aperti da più di --wo-overdue-days (default: 21)

Destinatari: SiteConfig chiave "assets_reminder_emails" (lista separata da virgola),
  oppure settings.ADMINS, oppure utenti superuser con email.
Soglia giorni configurabile anche via SiteConfig chiave "assets_reminder_days" (default: 30).

Idempotente: eseguire più volte nello stesso giorno invia più email (nessun flag fired).
Per ambienti di test usare --dry-run.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from assets.models import AssetAdministrativeDeadline, PeriodicVerification, WorkOrder
from core.models import SiteConfig


def _get_recipients(override: list[str] | None) -> list[str]:
    if override:
        return [e.strip() for e in override if e.strip()]

    cfg = SiteConfig.get("assets_reminder_emails", "")
    if cfg.strip():
        return [e.strip() for e in cfg.split(",") if e.strip()]

    from django.conf import settings
    admins = getattr(settings, "ADMINS", ()) or ()
    admin_emails = [str(email).strip() for _name, email in admins if str(email).strip()]
    if admin_emails:
        return admin_emails

    User = get_user_model()
    return list(
        User.objects.filter(is_active=True, is_superuser=True)
        .exclude(email="")
        .values_list("email", flat=True)
        .distinct()
    )


class Command(BaseCommand):
    help = "Invia email promemoria per scadenze manutenzione e OdL aperti in ritardo."

    def add_arguments(self, parser):
        parser.add_argument(
            "--deadline-days",
            type=int,
            default=0,
            help="Giorni di anticipo per scadenze/verifiche (0 = legge da SiteConfig 'assets_reminder_days', default 30).",
        )
        parser.add_argument(
            "--wo-overdue-days",
            type=int,
            default=21,
            help="OdL aperti da più di N giorni (default: 21).",
        )
        parser.add_argument(
            "--recipients",
            nargs="*",
            help="Email destinatari (sovrascrive SiteConfig/ADMINS).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Stampa senza inviare email.")

    def handle(self, *args, **options):
        dry_run: bool = bool(options.get("dry_run"))
        wo_overdue_days: int = int(options.get("wo_overdue_days") or 21)
        recipients: list[str] = _get_recipients(options.get("recipients") or [])

        raw_days = int(options.get("deadline_days") or 0)
        if raw_days <= 0:
            try:
                raw_days = int(SiteConfig.get("assets_reminder_days", "30") or "30")
            except (ValueError, TypeError):
                raw_days = 30
        deadline_days = max(1, raw_days)

        today = timezone.localdate()
        horizon = today + timedelta(days=deadline_days)
        wo_threshold = today - timedelta(days=wo_overdue_days)

        # 1. Scadenze amministrative
        admin_deadlines = list(
            AssetAdministrativeDeadline.objects.filter(
                is_active=True,
                due_date__gte=today,
                due_date__lte=horizon,
            )
            .select_related("asset")
            .order_by("due_date")
        )

        # 2. Verifiche periodiche
        periodic = list(
            PeriodicVerification.objects.filter(
                is_active=True,
                next_verification_date__gte=today,
                next_verification_date__lte=horizon,
            )
            .order_by("next_verification_date")
        )

        # 3. OdL aperti in ritardo
        overdue_wo = list(
            WorkOrder.objects.filter(
                status=WorkOrder.STATUS_OPEN,
                opened_at__date__lte=wo_threshold,
            )
            .select_related("asset")
            .order_by("opened_at")
        )

        if not admin_deadlines and not periodic and not overdue_wo:
            self.stdout.write("Nessun promemoria da inviare.")
            return

        lines = [
            f"NOVICROM HUB — Promemoria manutenzione del {today:%d/%m/%Y}",
            "=" * 60,
            "",
        ]

        if admin_deadlines:
            lines.append(f"SCADENZE AMMINISTRATIVE nei prossimi {deadline_days} giorni ({len(admin_deadlines)}):")
            for d in admin_deadlines:
                days_left = (d.due_date - today).days
                lines.append(f"  [{days_left}gg] {d.asset.asset_tag} — {d.title} — scadenza {d.due_date:%d/%m/%Y}")
            lines.append("")

        if periodic:
            lines.append(f"VERIFICHE PERIODICHE nei prossimi {deadline_days} giorni ({len(periodic)}):")
            for v in periodic:
                days_left = (v.next_verification_date - today).days
                lines.append(f"  [{days_left}gg] {v.name} — {v.next_verification_date:%d/%m/%Y}")
            lines.append("")

        if overdue_wo:
            lines.append(f"OdL APERTI DA PIÙ DI {wo_overdue_days} GIORNI ({len(overdue_wo)}):")
            for wo in overdue_wo:
                age = (today - wo.opened_at.date()).days
                lines.append(f"  [{age}gg] #{wo.pk} {wo.asset.asset_tag} — {wo.title}")
            lines.append("")

        body = "\n".join(lines)
        subject = f"[Manutenzione] {len(admin_deadlines)} scad. + {len(periodic)} verif. + {len(overdue_wo)} OdL — {today:%d/%m/%Y}"

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] Nessuna email inviata."))
            self.stdout.write(f"Destinatari: {recipients}")
            self.stdout.write(body)
            return

        if not recipients:
            self.stdout.write(self.style.ERROR("Nessun destinatario configurato. Usare --recipients o impostare SiteConfig 'assets_reminder_emails'."))
            return

        try:
            from django.conf import settings
            send_mail(
                subject=subject,
                message=body,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "") or None,
                recipient_list=recipients,
                fail_silently=False,
            )
            self.stdout.write(self.style.SUCCESS(
                f"Email inviata a {len(recipients)} destinatari. "
                f"Scadenze={len(admin_deadlines)} Verifiche={len(periodic)} OdL_ritardo={len(overdue_wo)}"
            ))
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Invio email fallito: {exc}"))
