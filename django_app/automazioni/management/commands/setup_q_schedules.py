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
        from automazioni.schedules import SCHEDULES

        dry_run: bool = bool(options.get("dry_run"))
        delete: bool = bool(options.get("delete"))
        mode = "[dry-run]" if dry_run else "[run]"

        for spec in SCHEDULES:
            name = spec["name"]

            if delete:
                if dry_run:
                    self.stdout.write(f"{mode} Eliminerei schedule '{name}'")
                else:
                    deleted, _ = Schedule.objects.filter(name=name).delete()
                    if deleted:
                        self.stdout.write(self.style.WARNING(f"  ✗ eliminato: {name}"))
                    else:
                        self.stdout.write(f"  – non trovato: {name}")
                continue

            kwargs_repr = json.dumps(spec.get("kwargs") or {})
            defaults = {
                "func": spec["func"],
                "schedule_type": spec["schedule_type"],
                "minutes": spec["minutes"],
                "repeats": spec.get("repeats", -1),
                "kwargs": kwargs_repr,
            }

            if dry_run:
                self.stdout.write(
                    f"{mode} Creerei/aggiornerei schedule '{name}': "
                    f"func={spec['func']} type={spec['schedule_type']} "
                    f"minutes={spec['minutes']} repeats={spec.get('repeats', -1)}"
                )
            else:
                _obj, created = Schedule.objects.update_or_create(name=name, defaults=defaults)
                verb = "creato" if created else "aggiornato"
                self.stdout.write(self.style.SUCCESS(f"  ✓ {verb}: {name} → {spec['func']}"))

        if not delete and not dry_run:
            count = Schedule.objects.filter(
                name__in=[s["name"] for s in SCHEDULES]
            ).count()
            self.stdout.write(f"\nSchedule attivi registrati: {count}/{len(SCHEDULES)}")
