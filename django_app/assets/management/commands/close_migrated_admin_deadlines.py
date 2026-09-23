"""Chiude le vecchie scadenze amministrative gia' copiate nel nuovo dominio.

``migrate_maintenance_to_plans`` ha copiato ogni ``AssetAdministrativeDeadline``
in un piano amministrativo + occorrenza, ma ha lasciato attiva l'originale: la
stessa scadenza esisteva due volte (due promemoria, contatori diversi fra una
pagina e l'altra, e una modifica sulla vecchia pagina non arrivava all'occorrenza).

Questo comando disattiva SOLO le vecchie scadenze che hanno un'occorrenza
corrispondente (stesso asset, stessa data, piano amministrativo con lo stesso
titolo — la stessa regola con cui ``deadline_feed`` le deduplica). Non cancella
niente: ``is_active=False``, una nota sul record e una voce di audit per ciascuna.
Le scadenze senza corrispondenza restano attive e vengono elencate.

Di default e' una prova a vuoto; scrive solo con ``--apply``. Ripetibile.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from assets.models import MaintenanceInterventionTemplate, MaintenanceOccurrence
from assets.services import deadline_feed


class Command(BaseCommand):
    help = "Disattiva le vecchie scadenze amministrative gia' migrate in un'occorrenza (default: prova a vuoto)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Scrive davvero (senza: solo elenco).")

    def handle(self, *args, **options):
        apply = bool(options.get("apply"))
        today = timezone.localdate()
        doppioni = list(
            deadline_feed.migrated_legacy_deadlines_qs().select_related("asset").order_by("due_date", "id")
        )
        rimaste = list(deadline_feed.legacy_deadlines_qs().select_related("asset").order_by("due_date", "id"))

        mode = "APPLICA" if apply else "PROVA A VUOTO"
        self.stdout.write(f"[{mode}] Scadenze amministrative vecchie gia' migrate (da chiudere): {len(doppioni)}")
        for deadline in doppioni:
            self.stdout.write(
                f"  #{deadline.id} {deadline.asset.asset_tag} — {deadline.title} — {deadline.due_date:%d/%m/%Y}"
            )

        if apply and doppioni:
            from core.audit import log_action

            with transaction.atomic():
                for deadline in doppioni:
                    occurrence = (
                        MaintenanceOccurrence.objects.filter(
                            asset_id=deadline.asset_id,
                            due_date=deadline.due_date,
                            plan__maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE,
                            plan__label=deadline.title,
                        )
                        .exclude(status=MaintenanceOccurrence.STATUS_CANCELED)
                        .order_by("id")
                        .first()
                    )
                    nota = (
                        f"[{today:%d/%m/%Y}] Chiusa: la scadenza vive nell'occorrenza "
                        f"#{getattr(occurrence, 'id', '?')} del piano amministrativo. "
                        "Si gestisce da Manutenzione > Scadenzario."
                    )
                    deadline.is_active = False
                    deadline.notes = f"{deadline.notes}\n{nota}".strip() if deadline.notes else nota
                    deadline.save(update_fields=["is_active", "notes", "updated_at"])
                    log_action(
                        None,
                        "ASSET_SCADENZA_AMMINISTRATIVA_CHIUSA_MIGRATA",
                        "assets",
                        {
                            "deadline_id": deadline.id,
                            "asset_id": deadline.asset_id,
                            "due_date": deadline.due_date.isoformat(),
                            "occurrence_id": getattr(occurrence, "id", None),
                            "comando": "close_migrated_admin_deadlines",
                        },
                        oggetto=deadline,
                    )
            self.stdout.write(self.style.SUCCESS(f"Disattivate {len(doppioni)} scadenze (nota + audit su ognuna)."))
        elif doppioni:
            self.stdout.write("Nessuna modifica. Rilanciare con --apply per disattivarle.")

        self.stdout.write(f"Scadenze vecchie SENZA occorrenza (restano attive): {len(rimaste)}")
        for deadline in rimaste:
            self.stdout.write(
                f"  #{deadline.id} {deadline.asset.asset_tag} — {deadline.title} — {deadline.due_date:%d/%m/%Y}"
            )
        if rimaste:
            self.stdout.write(
                "Restano visibili in Calendario, Scadenzario e promemoria. Per portarle nei piani: "
                "manage.py migrate_maintenance_to_plans --dry-run, poi senza --dry-run, poi questo comando."
            )
