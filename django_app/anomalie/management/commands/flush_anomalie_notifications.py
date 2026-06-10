"""Invia le mail di conferma anomalie in coda (debounce) oltre la soglia.

Utilizzo:
    python manage.py flush_anomalie_notifications
    python manage.py flush_anomalie_notifications --threshold-minutes 5
    python manage.py flush_anomalie_notifications --dry-run
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Invia le mail di conferma aggiornamenti anomalie per gli OP fermi oltre la soglia."

    def add_arguments(self, parser):
        parser.add_argument("--threshold-minutes", type=int, default=5)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra gli OP in coda senza inviare nulla.",
        )

    def handle(self, *args, **options):
        threshold = int(options.get("threshold_minutes") or 5)
        dry_run = bool(options.get("dry_run"))

        if dry_run:
            from anomalie.mail_action_models import AnomaliaPendingNotification
            from django.utils import timezone
            from datetime import timedelta

            cutoff = timezone.now() - timedelta(minutes=threshold)
            pending = AnomaliaPendingNotification.objects.filter(
                notified=False, last_modified_at__lte=cutoff
            )
            self.stdout.write(f"[dry-run] OP in coda oltre {threshold} min: {pending.count()}")
            for p in pending:
                n = len(p.updates_snapshot or [])
                self.stdout.write(f"  • {p.op_id} ({n} modifiche) ultima: {p.last_modified_at:%d/%m %H:%M}")
            return

        from anomalie.mail_action_service import flush_pending_update_notifications

        result = flush_pending_update_notifications(threshold_minutes=threshold)
        self.stdout.write(
            self.style.SUCCESS(
                f"Conferme inviate: {result.get('sent')} / controllate: {result.get('checked')}"
            )
        )
