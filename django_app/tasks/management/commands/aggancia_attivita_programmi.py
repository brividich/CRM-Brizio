"""Una tantum: le righe di «Programmi e FAI» già assegnate diventano attività del kickoff.

Dal 09/11/2026 assegnare una riga crea la sua attività; le righe nate prima
restavano voci a parte. Il comando le aggancia senza mandare mail né notifiche.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from tasks.models import ProjectTechRef, TechRefStatus
from tasks.services.programmi import attivita_per_riga, tipo_per


class Command(BaseCommand):
    help = "Crea l'attività del kickoff per le righe CAM/CMM/FAI aperte e assegnate che non ne hanno una."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Elenca le righe senza creare nulla.")

    def handle(self, *args, **opts):
        righe = (
            ProjectTechRef.objects.filter(task__isnull=True, assigned_to__isnull=False, status=TechRefStatus.OPEN)
            .select_related("project", "assigned_to", "source_meeting")
            .order_by("project_id", "id")
        )
        create = saltate = 0
        for ref in righe:
            if tipo_per(ref.kind) is None:
                saltate += 1
                self.stdout.write(f"  saltata riga {ref.pk} ({ref.kind}): nessun tipo attività la richiede")
                continue
            if opts["dry_run"]:
                create += 1
                self.stdout.write(f"  riga {ref.pk} {ref.label} [{ref.project.name}] -> attività da creare")
                continue
            with transaction.atomic():
                task = attivita_per_riga(ref, None, notifica=False)
            if task is None:
                saltate += 1
                self.stdout.write(f"  saltata riga {ref.pk} {ref.label} [{ref.project.name}] (kickoff bloccato VRF?)")
            else:
                create += 1
                self.stdout.write(f"  riga {ref.pk} {ref.label} -> attività {task.pk}")
        verbo = "da creare" if opts["dry_run"] else "create"
        self.stdout.write(self.style.SUCCESS(f"Attività {verbo}: {create}. Righe saltate: {saltate}."))
