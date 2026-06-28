"""
Management command: setup_q_schedules

Registra in modo idempotente gli Schedule django-q2 per i background job
delle automazioni. Sicuro da ri-eseguire: aggiorna se già esiste, crea se manca.

Utilizzo:
    python manage.py setup_q_schedules
    python manage.py setup_q_schedules --dry-run
    python manage.py setup_q_schedules --delete
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Registra (o aggiorna) gli Schedule django-q2 per i background job delle automazioni."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra cosa verrebbe creato/aggiornato senza toccare il DB.",
        )
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Elimina gli schedule registrati da questo comando invece di crearli.",
        )

    def handle(self, *args, **options):
        from django_q.models import Schedule

        from automazioni.schedules import (
            SCHEDULES,
            delete_schedule,
            disabled_schedule_names,
            register_schedule,
        )

        dry_run: bool = bool(options.get("dry_run"))
        delete: bool = bool(options.get("delete"))
        mode = "[dry-run]" if dry_run else "[run]"
        # Schedule disabilitati dalla centrale di comando (monitoring.ScheduleControl):
        # non vengono registrati anche dopo un redeploy (l'abilitazione è durevole).
        disabled = set() if delete else disabled_schedule_names()

        for spec in SCHEDULES:
            name = spec["name"]

            if delete:
                if dry_run:
                    self.stdout.write(f"{mode} Eliminerei schedule '{name}'")
                else:
                    deleted = delete_schedule(name)
                    if deleted:
                        self.stdout.write(self.style.WARNING(f"  [x] eliminato: {name}"))
                    else:
                        self.stdout.write(f"  [-] non trovato: {name}")
                continue

            if name in disabled:
                if dry_run:
                    self.stdout.write(f"{mode} Salterei (disabilitato dalla centrale): '{name}'")
                else:
                    delete_schedule(name)
                    self.stdout.write(self.style.WARNING(f"  [off] disabilitato (non registrato): {name}"))
                continue

            if dry_run:
                cadence = (
                    f"cron={spec['cron']}" if spec.get("schedule_type") == "C"
                    else f"minutes={spec.get('minutes')}"
                )
                self.stdout.write(
                    f"{mode} Creerei/aggiornerei schedule '{name}': "
                    f"func={spec['func']} type={spec['schedule_type']} "
                    f"{cadence} repeats={spec.get('repeats', -1)}"
                )
            else:
                _obj, created = register_schedule(spec)
                verb = "creato" if created else "aggiornato"
                self.stdout.write(self.style.SUCCESS(f"  [ok] {verb}: {name} -> {spec['func']}"))

        if not delete and not dry_run:
            count = Schedule.objects.filter(
                name__in=[s["name"] for s in SCHEDULES]
            ).count()
            self.stdout.write(
                f"\nSchedule registrati: {count}/{len(SCHEDULES)} (disabilitati: {len(disabled)})"
            )
