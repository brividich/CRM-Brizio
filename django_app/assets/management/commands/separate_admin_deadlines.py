"""Riporta le scadenze amministrative fuori dai piani di manutenzione.

Le scadenze amministrative (``AssetAdministrativeDeadline``: revisioni,
certificati, garanzie...) sono un registro separato dai piani. Le versioni
precedenti di ``migrate_maintenance_to_plans`` le copiavano in un piano
amministrativo + occorrenza, e ``close_migrated_admin_deadlines`` disattivava poi
l'originale: la scadenza finiva dentro i piani e spariva dalla sua pagina.

Questo comando rimette le cose com'erano, senza cancellare nulla:

1. riattiva le scadenze disattivate da ``close_migrated_admin_deadlines`` e toglie
   la nota che quel comando aveva aggiunto;
2. le esecuzioni registrate sulla copia (non quelle migrate dallo storico, che
   vengono gia' dalla scadenza) diventano esecuzioni della scadenza;
3. annulla le occorrenze aperte delle copie;
4. spegne le applicazioni delle copie, e il piano se non gli resta altro.

La copia si riconosce come in ``deadline_feed``: piano amministrativo con
l'etichetta uguale al titolo della scadenza, sullo stesso asset. Una voce di
audit per ogni modifica. Di default e' una prova a vuoto; scrive solo con
``--apply``. Ripetibile.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from assets.models import (
    AssetAdministrativeDeadline,
    AssetAdministrativeDeadlineCompletion,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenancePlanAssignment,
)

# Nota scritta da close_migrated_admin_deadlines: identifica le scadenze da riattivare.
CLOSE_MARKER = "Chiusa: la scadenza vive nell'occorrenza"
AUDIT_ACTION = "ASSET_SCADENZA_AMMINISTRATIVA_SEPARATA_DAI_PIANI"


def _strip_close_note(notes: str) -> str:
    return "\n".join(line for line in (notes or "").splitlines() if CLOSE_MARKER not in line).strip()


class Command(BaseCommand):
    help = "Riporta le scadenze amministrative fuori dai piani di manutenzione (default: prova a vuoto)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Scrive davvero (senza: solo elenco).")

    def handle(self, *args, **options):
        apply = bool(options.get("apply"))
        today = timezone.localdate()
        admin_type = MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE

        deadlines = list(AssetAdministrativeDeadline.objects.select_related("asset").order_by("id"))
        by_key = {(d.title, d.asset_id): d for d in deadlines}

        to_reactivate = [d for d in deadlines if not d.is_active and CLOSE_MARKER in (d.notes or "")]

        copies = [
            occ
            for occ in MaintenanceOccurrence.objects.filter(plan__maintenance_type=admin_type)
            .select_related("plan", "asset", "completed_by")
            .order_by("due_date", "id")
            if (occ.plan.label, occ.asset_id) in by_key
        ]
        open_copies = [occ for occ in copies if occ.status == MaintenanceOccurrence.STATUS_OPEN]
        done_to_transfer = [
            occ
            for occ in copies
            if occ.status == MaintenanceOccurrence.STATUS_DONE
            and occ.source != MaintenanceOccurrence.SOURCE_MIGRATION
            and occ.completed_on
            and not AssetAdministrativeDeadlineCompletion.objects.filter(
                deadline=by_key[(occ.plan.label, occ.asset_id)], completed_on=occ.completed_on
            ).exists()
        ]
        assignments = [
            a
            for a in MaintenancePlanAssignment.objects.filter(
                plan__maintenance_type=admin_type,
                is_active=True,
                target_type=MaintenancePlanAssignment.TARGET_ASSET,
                asset__isnull=False,
            )
            .select_related("plan", "asset")
            .order_by("id")
            if (a.plan.label, a.asset_id) in by_key
        ]

        mode = "APPLICA" if apply else "PROVA A VUOTO"
        self.stdout.write(f"[{mode}] Scadenze amministrative da riattivare: {len(to_reactivate)}")
        for d in to_reactivate:
            self.stdout.write(f"  #{d.id} {d.asset.asset_tag} — {d.title} — {d.due_date:%d/%m/%Y}")
        self.stdout.write(f"Esecuzioni registrate sulle copie da riportare sulla scadenza: {len(done_to_transfer)}")
        for occ in done_to_transfer:
            self.stdout.write(
                f"  occorrenza #{occ.id} {occ.asset.asset_tag} — {occ.plan.label} — eseguita {occ.completed_on:%d/%m/%Y}"
            )
        self.stdout.write(f"Occorrenze aperte delle copie da annullare: {len(open_copies)}")
        for occ in open_copies:
            self.stdout.write(f"  #{occ.id} {occ.asset.asset_tag} — {occ.plan.label} — {occ.due_date:%d/%m/%Y}")
        self.stdout.write(f"Applicazioni dei piani copia da spegnere: {len(assignments)}")
        for a in assignments:
            self.stdout.write(f"  #{a.id} piano «{a.plan.label}» su {a.asset.asset_tag}")

        if not apply:
            if to_reactivate or done_to_transfer or open_copies or assignments:
                self.stdout.write("Nessuna modifica. Rilanciare con --apply.")
            return

        from core.audit import log_action

        def audit(operazione: str, oggetto, **dettagli):
            log_action(
                None,
                AUDIT_ACTION,
                "assets",
                {"operazione": operazione, "comando": "separate_admin_deadlines", **dettagli},
                oggetto=oggetto,
            )

        nota = f"[{today:%d/%m/%Y}] Annullata: le scadenze amministrative sono separate dai piani di manutenzione."
        plans_touched = {}
        with transaction.atomic():
            for d in to_reactivate:
                d.is_active = True
                d.notes = _strip_close_note(d.notes)
                d.save(update_fields=["is_active", "notes", "updated_at"])
                audit("riattivata", d, deadline_id=d.id, asset_id=d.asset_id)
            for occ in done_to_transfer:
                deadline = by_key[(occ.plan.label, occ.asset_id)]
                completion = AssetAdministrativeDeadlineCompletion.objects.create(
                    deadline=deadline,
                    completed_on=occ.completed_on,
                    completed_by=occ.completed_by,
                    notes=(occ.completion_notes or f"Registrata sull'occorrenza #{occ.id} del piano.")[:2000],
                )
                audit(
                    "esecuzione_riportata", deadline,
                    deadline_id=deadline.id, occurrence_id=occ.id, completion_id=completion.id,
                )
            for occ in open_copies:
                occ.status = MaintenanceOccurrence.STATUS_CANCELED
                occ.completion_notes = f"{occ.completion_notes}\n{nota}".strip()
                occ.save(update_fields=["status", "completion_notes", "updated_at"])
                audit("copia_annullata", occ, occurrence_id=occ.id, asset_id=occ.asset_id)
            for a in assignments:
                a.is_active = False
                a.save(update_fields=["is_active", "updated_at"])
                plans_touched[a.plan_id] = a.plan
                audit("applicazione_spenta", a, assignment_id=a.id, plan_id=a.plan_id)
            for plan in plans_touched.values():
                if plan.is_active and not plan.assignments.filter(is_active=True).exists():
                    plan.is_active = False
                    plan.save(update_fields=["is_active", "updated_at"])
                    audit("piano_spento", plan, plan_id=plan.id)
        self.stdout.write(self.style.SUCCESS(
            f"Fatto: {len(to_reactivate)} riattivate, {len(done_to_transfer)} esecuzioni riportate, "
            f"{len(open_copies)} occorrenze annullate, {len(assignments)} applicazioni spente."
        ))
        if done_to_transfer:
            self.stdout.write(self.style.WARNING(
                "Controllare la scadenza delle voci con esecuzioni riportate: il comando non la sposta."
            ))
