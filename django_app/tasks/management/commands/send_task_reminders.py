"""Materializza i TaskReminder pendenti in Notifica utente.

Schedulare come task Windows quotidiano (suggerito alle 07:30):

    python manage.py send_task_reminders

Esegue in modo idempotente: un `TaskReminder.fired=True` non viene mai
rielaborato. Il comando scorre i reminder con `fire_at <= oggi, fired=False`,
crea una `core.Notifica` per l'utente legacy e marca il reminder come fired.
Se l'utente legacy e' disattivo o non esiste, il reminder viene scartato
comunque per evitare retry infiniti.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from core.models import Notifica
from tasks.models import TaskReminder, TaskStatus


class Command(BaseCommand):
    help = "Materializza i TaskReminder in scadenza come Notifica portale."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Non modifica nulla, stampa solo cosa farebbe.")
        parser.add_argument("--limit", type=int, default=0, help="Limita il numero di reminder processati (0 = nessun limite).")

    def handle(self, *args, **options):
        dry_run: bool = bool(options.get("dry_run"))
        limit: int = int(options.get("limit") or 0)
        today = timezone.localdate()

        qs = (
            TaskReminder.objects.filter(fired=False, fire_at__lte=today)
            .select_related("task", "task__project", "task__assigned_to")
            .order_by("fire_at", "id")
        )
        if limit:
            qs = qs[:limit]

        total = 0
        fired = 0
        skipped = 0
        for reminder in qs:
            total += 1
            task = reminder.task
            # Salta reminder per task chiuse
            if task.status in {TaskStatus.DONE, TaskStatus.CANCELED}:
                skipped += 1
                if not dry_run:
                    reminder.fired = True
                    reminder.fired_at = timezone.now()
                    reminder.save(update_fields=["fired", "fired_at"])
                continue

            project_label = ""
            if task.project_id and task.project:
                project_label = f" [{task.project.name}]"
            message = (
                f"Promemoria scadenza attivita kickoff: \"{task.title}\"{project_label} "
                f"in scadenza il {task.due_date:%d-%m-%Y}."
            )[:500]
            url_action = reverse("tasks:detail", args=[task.id])

            if dry_run:
                self.stdout.write(f"[DRY] user={reminder.legacy_user_id} task={task.id} msg={message!r}")
                continue

            with transaction.atomic():
                Notifica.objects.create(
                    legacy_user_id=int(reminder.legacy_user_id),
                    tipo="generico",
                    messaggio=message,
                    url_azione=url_action,
                )
                reminder.fired = True
                reminder.fired_at = timezone.now()
                reminder.save(update_fields=["fired", "fired_at"])
            fired += 1

        summary = f"Processed={total} fired={fired} skipped={skipped}"
        if dry_run:
            self.stdout.write(self.style.WARNING(f"[DRY-RUN] {summary}"))
        else:
            self.stdout.write(self.style.SUCCESS(summary))
