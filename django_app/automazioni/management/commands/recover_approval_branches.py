"""Riprende i rami di approvazione rimasti a meta'.

Dopo una decisione le azioni del ramo vengono eseguite fuori dalla transazione
della decisione. Se il processo si interrompe (riavvio IIS, crash) l'approvazione
resta con ``branch_status=running``: questo comando la riprende da
``branch_progress`` senza rieseguire le azioni gia' completate.

Uso:
    python manage.py recover_approval_branches [--older-than-minutes 15] [--dry-run]
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Riprende i rami di approvazione interrotti (branch_status=running)."

    def add_arguments(self, parser):
        parser.add_argument("--older-than-minutes", type=int, default=15)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        from automazioni.models import AutomationApproval
        from automazioni.services import run_approval_branch

        threshold = timezone.now() - timedelta(minutes=max(1, options["older_than_minutes"]))
        stuck = list(
            AutomationApproval.objects.select_related("run_log__rule", "action")
            .filter(branch_status=AutomationApproval.BranchStatus.RUNNING, branch_updated_at__lt=threshold)
            .order_by("branch_updated_at")
        )
        if not stuck:
            self.stdout.write("Nessun ramo interrotto.")
            return

        for approval in stuck:
            label = f"#{approval.pk} ({approval.status}, {approval.branch_progress} azioni gia' eseguite)"
            if options["dry_run"]:
                self.stdout.write(f"[dry-run] da riprendere: {label}")
                continue
            # Presa in carico condizionata: evita che due esecuzioni riprendano lo stesso ramo.
            claimed = AutomationApproval.objects.filter(
                pk=approval.pk,
                branch_status=AutomationApproval.BranchStatus.RUNNING,
                branch_updated_at=approval.branch_updated_at,
            ).update(branch_updated_at=timezone.now())
            if not claimed:
                continue
            result = run_approval_branch(approval)
            self.stdout.write(
                f"Ripreso {label}: eseguite {result['actions_run']}, errori {result['actions_errors']}."
            )
