"""Retention dei RunLog automazioni: elimina i log piu' vecchi della finestra
di conservazione (GDPR - limitazione conservazione).

La finestra (giorni) si legge da SiteConfig via ``runlog_retention.get_retention_days``
(default 90), oppure si forza con ``--days``. Dry-run di default: serve ``--apply``
per cancellare davvero. Cancellazione a batch per non saturare il log SQL Server.

Esempi:
    python manage.py cleanup_run_logs                # dry-run, finestra da config
    python manage.py cleanup_run_logs --apply        # esegue, finestra da config
    python manage.py cleanup_run_logs --days 30 --apply
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Cancella i RunLog automazioni oltre la finestra di retention (GDPR)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Esegue la cancellazione effettiva. Senza questo flag e' dry-run.",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Override dei giorni di retention (altrimenti da SiteConfig/default).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=2000,
            help="Righe eliminate per batch (default 2000).",
        )

    def handle(self, *args, **options):
        from automazioni.models import AutomationRunLog
        from automazioni.runlog_retention import get_retention_days

        apply: bool = bool(options.get("apply"))
        days_opt = options.get("days")
        batch_size = max(100, int(options.get("batch_size") or 2000))

        days = int(days_opt) if days_opt is not None else get_retention_days()
        cutoff = timezone.now() - timedelta(days=days)
        mode = "[apply]" if apply else "[dry-run]"

        base_qs = AutomationRunLog.objects.filter(started_at__lt=cutoff)
        total = base_qs.count()

        self.stdout.write(
            f"{mode} Retention RunLog: {days} giorni -> cutoff {cutoff.isoformat()} "
            f"| candidati alla cancellazione: {total}"
        )

        if total == 0 or not apply:
            if total and not apply:
                self.stdout.write("Esegui con --apply per cancellare.")
            return

        # Cancellazione a batch (gli AutomationActionLog figli cadono via CASCADE).
        deleted_total = 0
        while True:
            ids = list(
                AutomationRunLog.objects.filter(started_at__lt=cutoff)
                .values_list("id", flat=True)[:batch_size]
            )
            if not ids:
                break
            deleted, _ = AutomationRunLog.objects.filter(id__in=ids).delete()
            deleted_total += len(ids)
            self.stdout.write(f"  ... eliminati {deleted_total}/{total}")

        logger.info("cleanup_run_logs: eliminati %s RunLog oltre %s giorni", deleted_total, days)
        self.stdout.write(self.style.SUCCESS(f"Completato: {deleted_total} RunLog eliminati."))
