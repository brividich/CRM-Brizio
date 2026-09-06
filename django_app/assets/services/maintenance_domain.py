"""Dominio del nuovo motore manutenzioni: Piano -> Applicazione -> Occorrenza -> OdL.

Tre responsabilita', tenute separate di proposito:

1. **Risoluzione** — dato un asset e un piano, quale applicazione vale? Precedenza
   ASSET > GRUPPO > CATEGORIA; due applicazioni pari merito con tempi diversi non
   vengono risolte d'ufficio, diventano un conflitto visibile.
2. **Generazione** — quali occorrenze devono esistere oggi. Idempotente: la chiave
   (piano, asset, scadenza) e' unica a DB, rilanciare non duplica.
3. **Chiusura** — completare un'occorrenza e far nascere la successiva secondo
   l'ancoraggio (esecuzione vs scadenza teorica).

La fonte di verita' della scadenza e' l'occorrenza: nessun ``next_due`` altrove.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import (
    Asset,
    AssetGroupMembership,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenancePlanAssignment,
    WorkOrder,
    WorkOrderLog,
)
from .recurrence import (
    ANCHOR_FIXED_CALENDAR,
    add_recurrence,
    compute_next_due,
    describe_recurrence,
    first_due_date_for,
    recurrence_spec,
)

# Esito della risoluzione di un piano su un asset.
RESOLUTION_APPLIED = "applied"
RESOLUTION_EXCLUDED = "excluded"
RESOLUTION_CONFLICT = "conflict"

SOURCE_ASSET = "asset"
SOURCE_GROUP = "group"
SOURCE_CATEGORY = "category"

_SOURCE_BY_TARGET = {
    MaintenancePlanAssignment.TARGET_ASSET: SOURCE_ASSET,
    MaintenancePlanAssignment.TARGET_GROUP: SOURCE_GROUP,
    MaintenancePlanAssignment.TARGET_CATEGORY: SOURCE_CATEGORY,
}

SOURCE_LABELS = {
    SOURCE_ASSET: "Personalizzato",
    SOURCE_GROUP: "Ereditato dal gruppo",
    SOURCE_CATEGORY: "Ereditato dalla categoria",
}


@dataclass
class PlanResolution:
    """Come un piano si applica a un asset, e da dove arriva la regola."""

    plan: MaintenanceInterventionTemplate
    asset: Asset
    assignment: MaintenancePlanAssignment | None
    status: str
    source: str = ""
    competing: list[MaintenancePlanAssignment] = field(default_factory=list)
    inherited_from: MaintenancePlanAssignment | None = None

    @property
    def is_applied(self) -> bool:
        return self.status == RESOLUTION_APPLIED

    @property
    def is_conflict(self) -> bool:
        return self.status == RESOLUTION_CONFLICT

    @property
    def is_excluded(self) -> bool:
        return self.status == RESOLUTION_EXCLUDED

    @property
    def source_label(self) -> str:
        if self.status == RESOLUTION_EXCLUDED:
            return "Escluso"
        if self.status == RESOLUTION_CONFLICT:
            return "Conflitto"
        return SOURCE_LABELS.get(self.source, "")

    @property
    def recurrence_label(self) -> str:
        return describe_recurrence(self.assignment) if self.assignment else ""

    @property
    def inherited_recurrence_label(self) -> str:
        """Periodicita' standard del gruppo, quando l'asset ha una personalizzazione."""
        return describe_recurrence(self.inherited_from) if self.inherited_from else ""

    def conflict_description(self) -> list[dict[str, str]]:
        return [
            {"target": item.target_label, "recurrence": describe_recurrence(item)}
            for item in self.competing
        ]


def _recurrence_signature(assignment: MaintenancePlanAssignment) -> tuple:
    """Due applicazioni sono "uguali" se dicono la stessa cosa sui tempi.

    Solo la differenza sui tempi genera conflitto: due gruppi che applicano lo
    stesso piano con gli stessi giorni non sono un problema da mostrare a nessuno.
    """
    spec = recurrence_spec(assignment)
    return (
        spec["frequency"],
        spec["interval"],
        spec["weekday"],
        spec["week_of_month"],
        spec["day_of_month"],
        spec["month_of_year"],
        int(assignment.warning_days or 0),
        assignment.effective_schedule_anchor,
    )


def _assignment_queryset(*, plan_ids: Iterable[int] | None = None):
    queryset = (
        MaintenancePlanAssignment.objects.filter(is_active=True, plan__is_active=True)
        .select_related("plan", "plan__default_supplier", "plan__default_assignee", "asset", "asset_group", "asset_category", "supplier", "assigned_to")
    )
    if plan_ids is not None:
        queryset = queryset.filter(plan_id__in=list(plan_ids))
    return queryset


def build_plan_resolutions(
    *,
    asset_queryset=None,
    plan_ids: Iterable[int] | None = None,
) -> dict[tuple[int, int], PlanResolution]:
    """Risolve in blocco tutte le coppie (piano, asset). Chiave: ``(plan_id, asset_id)``.

    Fa tre query indipendentemente da quanti asset e piani ci sono: la matrice di
    copertura e le dashboard chiamano questa funzione, un N+1 qui si sentirebbe
    ovunque.
    """
    assets = list(
        (asset_queryset if asset_queryset is not None else Asset.objects.all()).select_related("asset_category")
    )
    if not assets:
        return {}
    assets_by_id = {asset.id: asset for asset in assets}
    asset_ids = set(assets_by_id)

    assignments = list(_assignment_queryset(plan_ids=plan_ids))
    if not assignments:
        return {}

    group_ids = {a.asset_group_id for a in assignments if a.asset_group_id}
    members_by_group: dict[int, set[int]] = {}
    if group_ids:
        for group_id, asset_id in AssetGroupMembership.objects.filter(
            group_id__in=group_ids, asset_id__in=asset_ids
        ).values_list("group_id", "asset_id"):
            members_by_group.setdefault(group_id, set()).add(asset_id)

    assets_by_category: dict[int, set[int]] = {}
    for asset in assets:
        if asset.asset_category_id:
            assets_by_category.setdefault(asset.asset_category_id, set()).add(asset.id)

    # (plan_id, asset_id) -> applicazioni candidate
    candidates: dict[tuple[int, int], list[MaintenancePlanAssignment]] = {}
    for assignment in assignments:
        if assignment.target_type == MaintenancePlanAssignment.TARGET_ASSET:
            targets = {assignment.asset_id} & asset_ids
        elif assignment.target_type == MaintenancePlanAssignment.TARGET_GROUP:
            targets = members_by_group.get(assignment.asset_group_id, set())
        else:
            targets = assets_by_category.get(assignment.asset_category_id, set())
        for asset_id in targets:
            candidates.setdefault((assignment.plan_id, asset_id), []).append(assignment)

    resolutions: dict[tuple[int, int], PlanResolution] = {}
    for (plan_id, asset_id), items in candidates.items():
        asset = assets_by_id[asset_id]
        top_specificity = max(item.specificity for item in items)
        winners = [item for item in items if item.specificity == top_specificity]
        plan = winners[0].plan

        inherited = None
        if top_specificity == 3:
            lower = [item for item in items if item.specificity < 3]
            if lower:
                inherited = max(lower, key=lambda item: item.specificity)

        if any(item.is_excluded for item in winners):
            resolutions[(plan_id, asset_id)] = PlanResolution(
                plan=plan,
                asset=asset,
                assignment=next(item for item in winners if item.is_excluded),
                status=RESOLUTION_EXCLUDED,
                source=_SOURCE_BY_TARGET.get(winners[0].target_type, ""),
                inherited_from=inherited,
            )
            continue

        signatures = {_recurrence_signature(item) for item in winners}
        if len(signatures) > 1:
            resolutions[(plan_id, asset_id)] = PlanResolution(
                plan=plan,
                asset=asset,
                assignment=None,
                status=RESOLUTION_CONFLICT,
                source=_SOURCE_BY_TARGET.get(winners[0].target_type, ""),
                competing=sorted(winners, key=lambda item: item.id),
                inherited_from=inherited,
            )
            continue

        winner = min(winners, key=lambda item: item.id)
        resolutions[(plan_id, asset_id)] = PlanResolution(
            plan=plan,
            asset=asset,
            assignment=winner,
            status=RESOLUTION_APPLIED,
            source=_SOURCE_BY_TARGET.get(winner.target_type, ""),
            inherited_from=inherited,
        )
    return resolutions


def resolve_asset_plans(asset: Asset) -> list[PlanResolution]:
    """Piani che riguardano un singolo asset, per la scheda asset."""
    resolutions = build_plan_resolutions(asset_queryset=Asset.objects.filter(pk=asset.pk))
    rows = [resolution for (_, asset_id), resolution in resolutions.items() if asset_id == asset.pk]
    return sorted(rows, key=lambda row: (row.plan.sort_order, row.plan.label, row.plan.id))


def resolve_plan_for_asset(*, plan_id: int, asset: Asset) -> PlanResolution | None:
    resolutions = build_plan_resolutions(asset_queryset=Asset.objects.filter(pk=asset.pk), plan_ids=[plan_id])
    return resolutions.get((plan_id, asset.pk))


# ---------------------------------------------------------------------------
# Generazione delle occorrenze
# ---------------------------------------------------------------------------

def _last_completion(plan_id: int, asset_id: int, completed_map: dict) -> MaintenanceOccurrence | None:
    return completed_map.get((plan_id, asset_id))


def compute_due_date_for(
    resolution: PlanResolution,
    *,
    last_completed: MaintenanceOccurrence | None,
    today: date,
) -> date | None:
    """Scadenza da assicurare per una coppia (piano, asset) che non ha occorrenze aperte."""
    assignment = resolution.assignment
    if assignment is None:
        return None
    if last_completed is not None:
        return compute_next_due(
            assignment,
            anchor=assignment.effective_schedule_anchor,
            previous_due=last_completed.due_date,
            completion_date=last_completed.completed_on,
        )
    start = assignment.first_due_date
    if start is None:
        # Senza prima scadenza ne' storico la manutenzione e' dovuta subito: uno stato
        # "mai eseguita" senza data non e' operativamente risolvibile da nessuno.
        return today
    return first_due_date_for(assignment, start_date=start, today=start)


def generate_occurrences(
    *,
    today: date | None = None,
    plan_ids: Iterable[int] | None = None,
    asset_queryset=None,
    dry_run: bool = False,
    horizon_days: int | None = None,
) -> dict[str, Any]:
    """Crea le occorrenze entrate nella finestra di preavviso.

    Idempotente per costruzione: l'unicita' (piano, asset, scadenza) e' un vincolo
    DB, e una coppia con un'occorrenza gia' aperta viene saltata. Lanciare il
    comando due volte nello stesso giorno non produce doppioni.
    """
    current_day = today or timezone.localdate()

    base_assets = asset_queryset if asset_queryset is not None else Asset.objects.filter(status=Asset.STATUS_IN_USE)
    resolutions = build_plan_resolutions(asset_queryset=base_assets, plan_ids=plan_ids)
    if not resolutions:
        return {"created": 0, "skipped_open": 0, "skipped_not_due": 0, "conflicts": 0, "excluded": 0, "rows": []}

    pairs = list(resolutions)
    plan_id_set = {plan_id for plan_id, _ in pairs}
    asset_id_set = {asset_id for _, asset_id in pairs}

    open_pairs = set(
        MaintenanceOccurrence.objects.filter(
            status=MaintenanceOccurrence.STATUS_OPEN,
            plan_id__in=plan_id_set,
            asset_id__in=asset_id_set,
        ).values_list("plan_id", "asset_id")
    )

    # Ultimo completamento per coppia: e' l'unica memoria dell'esecuzione passata.
    completed_map: dict[tuple[int, int], MaintenanceOccurrence] = {}
    for occurrence in (
        MaintenanceOccurrence.objects.filter(
            status=MaintenanceOccurrence.STATUS_DONE,
            plan_id__in=plan_id_set,
            asset_id__in=asset_id_set,
        )
        .order_by("plan_id", "asset_id", "completed_on", "due_date", "id")
        .only("id", "plan_id", "asset_id", "due_date", "completed_on")
    ):
        completed_map[(occurrence.plan_id, occurrence.asset_id)] = occurrence

    created = 0
    skipped_open = 0
    skipped_not_due = 0
    conflicts = 0
    excluded = 0
    rows: list[dict[str, Any]] = []

    for (plan_id, asset_id), resolution in sorted(resolutions.items()):
        if resolution.is_conflict:
            conflicts += 1
            continue
        if resolution.is_excluded:
            excluded += 1
            continue
        assignment = resolution.assignment
        if assignment is None or not assignment.auto_generate:
            continue
        if (plan_id, asset_id) in open_pairs:
            skipped_open += 1
            continue

        last_completed = completed_map.get((plan_id, asset_id))
        due_date = compute_due_date_for(resolution, last_completed=last_completed, today=current_day)
        if due_date is None:
            continue

        warning_days = int(assignment.warning_days or 0)
        window = warning_days if horizon_days is None else max(warning_days, int(horizon_days))
        if (due_date - current_day).days > window:
            skipped_not_due += 1
            continue

        rows.append(
            {
                "plan": resolution.plan.label,
                "asset": getattr(resolution.asset, "asset_tag", "") or resolution.asset.name,
                "due_date": due_date,
                "warning_days": warning_days,
            }
        )
        if dry_run:
            created += 1
            continue

        try:
            with transaction.atomic():
                MaintenanceOccurrence.objects.create(
                    plan=resolution.plan,
                    assignment=assignment,
                    asset=resolution.asset,
                    due_date=due_date,
                    warning_days=warning_days,
                    schedule_anchor=assignment.effective_schedule_anchor,
                    previous_due_date=last_completed.due_date if last_completed else None,
                    supplier=assignment.effective_supplier,
                    source=MaintenanceOccurrence.SOURCE_SCHEDULER,
                )
        except IntegrityError:
            # Il vincolo unico ha fatto il suo mestiere: un'altra esecuzione
            # concorrente ha gia' creato questa occorrenza.
            skipped_open += 1
            continue
        created += 1

    return {
        "created": created,
        "skipped_open": skipped_open,
        "skipped_not_due": skipped_not_due,
        "conflicts": conflicts,
        "excluded": excluded,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Chiusura e avanzamento
# ---------------------------------------------------------------------------

class OccurrenceCompletionError(Exception):
    """Chiusura rifiutata (allegato obbligatorio mancante, occorrenza gia' chiusa...)."""


@transaction.atomic
def complete_occurrence(
    occurrence: MaintenanceOccurrence,
    *,
    completed_on: date | None = None,
    user=None,
    notes: str = "",
    downtime_minutes: int | None = None,
    create_next: bool = True,
) -> MaintenanceOccurrence | None:
    """Chiude un'occorrenza e crea la successiva. Ritorna la nuova occorrenza.

    Ogni asset avanza per conto suo: chiudere DM01 non chiude DM02, anche quando
    stanno nello stesso OdL.
    """
    if occurrence.status == MaintenanceOccurrence.STATUS_DONE:
        raise OccurrenceCompletionError("L'occorrenza risulta gia' eseguita.")
    if occurrence.attachment_required and not occurrence.attachments.exists():
        raise OccurrenceCompletionError(
            "Per completare questa scadenza e' obbligatorio allegare il documento aggiornato."
        )

    occurrence.status = MaintenanceOccurrence.STATUS_DONE
    occurrence.completed_on = completed_on or timezone.localdate()
    occurrence.completed_by = user if getattr(user, "is_authenticated", False) else None
    if notes:
        occurrence.completion_notes = notes
    if downtime_minutes is not None:
        occurrence.downtime_minutes = max(0, int(downtime_minutes))
    occurrence.save(
        update_fields=[
            "status",
            "completed_on",
            "completed_by",
            "completion_notes",
            "downtime_minutes",
            "updated_at",
        ]
    )

    if not create_next:
        return None
    assignment = occurrence.assignment
    if assignment is None or not assignment.is_active or assignment.is_excluded or not assignment.auto_generate:
        return None

    next_due = compute_next_due(
        assignment,
        anchor=occurrence.schedule_anchor or assignment.effective_schedule_anchor,
        previous_due=occurrence.due_date,
        completion_date=occurrence.completed_on,
    )
    if next_due is None:
        return None

    # Un'amministrativa chiusa con molto ritardo puo' avere la "prossima" gia'
    # passata: si avanza fino alla prima scadenza non ancora superata, senza
    # inventare occorrenze intermedie che nessuno eseguira'.
    if occurrence.schedule_anchor == ANCHOR_FIXED_CALENDAR:
        guard = 0
        while next_due < occurrence.completed_on and guard < 500:
            next_due = add_recurrence(assignment, next_due)
            guard += 1

    try:
        return MaintenanceOccurrence.objects.create(
            plan=occurrence.plan,
            assignment=assignment,
            asset=occurrence.asset,
            due_date=next_due,
            warning_days=occurrence.warning_days,
            schedule_anchor=occurrence.schedule_anchor,
            previous_due_date=occurrence.due_date,
            supplier=assignment.effective_supplier,
            source=MaintenanceOccurrence.SOURCE_SCHEDULER,
        )
    except IntegrityError:
        return MaintenanceOccurrence.objects.filter(
            plan=occurrence.plan, asset=occurrence.asset, due_date=next_due
        ).first()


def cancel_occurrence(occurrence: MaintenanceOccurrence, *, reason: str = "", user=None) -> None:
    occurrence.status = MaintenanceOccurrence.STATUS_CANCELED
    occurrence.cancel_reason = (reason or "").strip()[:255]
    occurrence.work_order = None
    occurrence.execution_day = None
    occurrence.save(
        update_fields=["status", "cancel_reason", "work_order", "execution_day", "updated_at"]
    )


# ---------------------------------------------------------------------------
# Stato visuale derivato
# ---------------------------------------------------------------------------

VIEW_STATE_LABELS = {
    MaintenanceOccurrence.VIEW_OVERDUE: "Scaduta",
    MaintenanceOccurrence.VIEW_DUE_SOON: "In scadenza",
    MaintenanceOccurrence.VIEW_TO_PLAN: "Da pianificare",
    MaintenanceOccurrence.VIEW_PLANNED: "Pianificata",
    MaintenanceOccurrence.VIEW_IN_PROGRESS: "In corso",
    MaintenanceOccurrence.VIEW_WAITING: "In attesa",
    MaintenanceOccurrence.VIEW_EXECUTED: "Eseguita",
    MaintenanceOccurrence.VIEW_REPORT_MISSING: "Rapporto mancante",
    MaintenanceOccurrence.VIEW_COMPLETED: "Completata",
    MaintenanceOccurrence.VIEW_CANCELED: "Annullata",
}

VIEW_STATE_BADGES = {
    MaintenanceOccurrence.VIEW_OVERDUE: "badge-danger",
    MaintenanceOccurrence.VIEW_DUE_SOON: "badge-warning",
    MaintenanceOccurrence.VIEW_TO_PLAN: "badge-info",
    MaintenanceOccurrence.VIEW_PLANNED: "badge-info",
    MaintenanceOccurrence.VIEW_IN_PROGRESS: "badge-primary",
    MaintenanceOccurrence.VIEW_WAITING: "badge-muted",
    MaintenanceOccurrence.VIEW_EXECUTED: "badge-success",
    MaintenanceOccurrence.VIEW_REPORT_MISSING: "badge-warning",
    MaintenanceOccurrence.VIEW_COMPLETED: "badge-success",
    MaintenanceOccurrence.VIEW_CANCELED: "badge-muted",
}

# Ordine operativo: prima cio' che e' gia' in ritardo, in fondo cio' che e' chiuso.
VIEW_STATE_ORDER = {
    MaintenanceOccurrence.VIEW_OVERDUE: 0,
    MaintenanceOccurrence.VIEW_DUE_SOON: 1,
    MaintenanceOccurrence.VIEW_TO_PLAN: 2,
    MaintenanceOccurrence.VIEW_IN_PROGRESS: 3,
    MaintenanceOccurrence.VIEW_WAITING: 4,
    MaintenanceOccurrence.VIEW_PLANNED: 5,
    MaintenanceOccurrence.VIEW_REPORT_MISSING: 6,
    MaintenanceOccurrence.VIEW_EXECUTED: 7,
    MaintenanceOccurrence.VIEW_COMPLETED: 8,
    MaintenanceOccurrence.VIEW_CANCELED: 9,
}


def occurrence_view_state(occurrence: MaintenanceOccurrence, *, today: date | None = None) -> str:
    """Stato mostrato all'utente. Derivato: a DB ci sono solo OPEN/DONE/CANCELED."""
    if occurrence.status == MaintenanceOccurrence.STATUS_CANCELED:
        return MaintenanceOccurrence.VIEW_CANCELED

    if occurrence.status == MaintenanceOccurrence.STATUS_DONE:
        # "Lavoro eseguito" e "pratica completa" sono due cose diverse: tra
        # l'intervento del fornitore e l'arrivo del rapportino l'occorrenza non e'
        # ancora chiusa a norma.
        if occurrence.attachment_required and not occurrence.attachments.exists():
            return MaintenanceOccurrence.VIEW_REPORT_MISSING
        if occurrence.is_external and occurrence.report_received_at is None and not occurrence.attachments.exists():
            return MaintenanceOccurrence.VIEW_REPORT_MISSING
        return MaintenanceOccurrence.VIEW_COMPLETED

    current_day = today or timezone.localdate()
    work_order = occurrence.work_order
    if work_order is not None and work_order.status == WorkOrder.STATUS_OPEN:
        if work_order.is_waiting:
            return MaintenanceOccurrence.VIEW_WAITING
        if work_order.started_at:
            return MaintenanceOccurrence.VIEW_IN_PROGRESS
        return MaintenanceOccurrence.VIEW_PLANNED

    if occurrence.due_date < current_day:
        return MaintenanceOccurrence.VIEW_OVERDUE
    if occurrence.warning_date and occurrence.warning_date <= current_day:
        return MaintenanceOccurrence.VIEW_DUE_SOON
    return MaintenanceOccurrence.VIEW_TO_PLAN


def occurrence_state_payload(occurrence: MaintenanceOccurrence, *, today: date | None = None) -> dict[str, Any]:
    state = occurrence_view_state(occurrence, today=today)
    return {
        "state": state,
        "label": VIEW_STATE_LABELS.get(state, ""),
        "badge_class": VIEW_STATE_BADGES.get(state, "badge-muted"),
        "order": VIEW_STATE_ORDER.get(state, 99),
        "days_until_due": occurrence.days_until_due(today),
    }


# ---------------------------------------------------------------------------
# OdL massivi
# ---------------------------------------------------------------------------

def _log(work_order: WorkOrder, note: str, user=None) -> None:
    WorkOrderLog.objects.create(
        work_order=work_order,
        note=note,
        author=user if getattr(user, "is_authenticated", False) else None,
    )


@transaction.atomic
def create_workorder_from_occurrences(
    occurrences: list[MaintenanceOccurrence],
    *,
    user=None,
    title: str = "",
    assigned_to=None,
    supplier=None,
    due_at=None,
) -> WorkOrder:
    """Raccoglie una o piu' occorrenze in un unico OdL, anche massivo.

    ``WorkOrder.asset`` resta valorizzato con l'asset capofila: tutte le viste
    storiche lo usano. L'elenco vero degli asset e' ``work_order.occurrences``.
    """
    if not occurrences:
        raise ValueError("Serve almeno un'occorrenza per aprire un ordine di lavoro.")
    already_planned = [occ for occ in occurrences if occ.work_order_id]
    if already_planned:
        raise ValueError("Alcune manutenzioni sono gia' inserite in un altro ordine di lavoro.")

    lead = occurrences[0]
    plan = lead.plan
    assignment = lead.assignment
    resolved_assignee = assigned_to or (assignment.effective_assignee if assignment else None)
    resolved_supplier = supplier or (assignment.effective_supplier if assignment else None)

    if not title:
        if len(occurrences) == 1:
            title = f"{plan.label} — {lead.asset.asset_tag}"
        else:
            title = f"{plan.label} — {len(occurrences)} asset"

    work_order = WorkOrder.objects.create(
        asset=lead.asset,
        maintenance_rule=None,
        origin=WorkOrder.ORIGIN_PERIODIC,
        kind=getattr(plan, "workorder_kind", WorkOrder.KIND_PREVENTIVE),
        status=WorkOrder.STATUS_OPEN,
        title=title[:255],
        description=plan.description or "",
        assigned_to=resolved_assignee,
        supplier=resolved_supplier,
        due_at=due_at,
        is_massive=len(occurrences) > 1,
    )

    from ..maintenance import copy_template_checklist_to_workorder

    copy_template_checklist_to_workorder(work_order, template_id=plan.pk)

    MaintenanceOccurrence.objects.filter(pk__in=[occ.pk for occ in occurrences]).update(
        work_order=work_order, updated_at=timezone.now()
    )
    # Le istanze passate restano in mano al chiamante, che tipicamente le riusa
    # subito (distribuzione sui giorni, rimozione): allinearle evita che continui
    # a lavorare su copie che si credono ancora non pianificate.
    for occurrence in occurrences:
        occurrence.work_order = work_order
    _log(
        work_order,
        "Ordine di lavoro creato da {n} manutenzione/i dovute: {assets}.".format(
            n=len(occurrences),
            assets=", ".join(occ.asset.asset_tag or occ.asset.name for occ in occurrences),
        ),
        user,
    )
    return work_order


@transaction.atomic
def add_occurrences_to_workorder(
    work_order: WorkOrder,
    occurrences: list[MaintenanceOccurrence],
    *,
    user=None,
) -> int:
    """Aggiunge manutenzioni a un OdL gia' organizzato. Mai in automatico: e' un'azione esplicita."""
    addable = [occ for occ in occurrences if not occ.work_order_id and occ.status == MaintenanceOccurrence.STATUS_OPEN]
    if not addable:
        return 0
    MaintenanceOccurrence.objects.filter(pk__in=[occ.pk for occ in addable]).update(
        work_order=work_order, updated_at=timezone.now()
    )
    for occurrence in addable:
        occurrence.work_order = work_order
    if not work_order.is_massive and work_order.occurrences.count() > 1:
        work_order.is_massive = True
        work_order.save(update_fields=["is_massive"])
    _log(
        work_order,
        "Aggiunte {n} manutenzioni: {assets}.".format(
            n=len(addable), assets=", ".join(occ.asset.asset_tag or occ.asset.name for occ in addable)
        ),
        user,
    )
    return len(addable)


@transaction.atomic
def remove_occurrence_from_workorder(
    occurrence: MaintenanceOccurrence,
    *,
    user=None,
    reason: str = "",
) -> None:
    """Toglie un asset dall'OdL SENZA chiudere ne' annullare la manutenzione.

    L'occorrenza torna da pianificare e continua a comparire tra le manutenzioni
    dovute: un asset che non si e' potuto fermare non e' un asset a posto.
    """
    work_order = occurrence.work_order
    if work_order is None:
        return
    occurrence.work_order = None
    occurrence.execution_day = None
    occurrence.save(update_fields=["work_order", "execution_day", "updated_at"])

    remaining = list(work_order.occurrences.select_related("asset").order_by("due_date", "id"))
    if remaining and work_order.asset_id == occurrence.asset_id:
        # L'asset capofila se n'e' andato: l'OdL prende il primo rimasto.
        work_order.asset = remaining[0].asset
        work_order.is_massive = len(remaining) > 1
        work_order.save(update_fields=["asset", "is_massive"])
    elif work_order.is_massive and len(remaining) <= 1:
        work_order.is_massive = False
        work_order.save(update_fields=["is_massive"])

    note = f"{occurrence.asset.asset_tag or occurrence.asset.name} rimosso dall'ordine di lavoro: la manutenzione torna da pianificare."
    if reason:
        note = f"{note} Motivo: {reason.strip()}"
    _log(work_order, note, user)


@transaction.atomic
def assign_occurrences_to_day(
    work_order: WorkOrder,
    occurrences: list[MaintenanceOccurrence],
    *,
    execution_date: date,
    user=None,
):
    """Distribuisce parte delle occorrenze di un OdL su una giornata di esecuzione."""
    from ..models import WorkOrderExecutionDay

    day, _created = WorkOrderExecutionDay.objects.get_or_create(
        work_order=work_order, execution_date=execution_date
    )
    valid = [occ for occ in occurrences if occ.work_order_id == work_order.pk]
    if valid:
        MaintenanceOccurrence.objects.filter(pk__in=[occ.pk for occ in valid]).update(
            execution_day=day, updated_at=timezone.now()
        )
        for occurrence in valid:
            occurrence.execution_day = day
        _log(
            work_order,
            "Programmate per il {d:%d-%m-%Y}: {assets}.".format(
                d=execution_date,
                assets=", ".join(occ.asset.asset_tag or occ.asset.name for occ in valid),
            ),
            user,
        )
    return day


def workorder_progress(work_order: WorkOrder) -> dict[str, int]:
    """Avanzamento di un OdL massivo: un OdL puo' essere parzialmente completato."""
    occurrences = list(work_order.occurrences.all())
    done = sum(1 for occ in occurrences if occ.status == MaintenanceOccurrence.STATUS_DONE)
    canceled = sum(1 for occ in occurrences if occ.status == MaintenanceOccurrence.STATUS_CANCELED)
    todo = len(occurrences) - done - canceled
    return {
        "total": len(occurrences),
        "done": done,
        "todo": todo,
        "canceled": canceled,
        "is_partial": bool(done and todo),
    }
