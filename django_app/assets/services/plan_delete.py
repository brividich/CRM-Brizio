"""Eliminazione definitiva di un Piano di manutenzione.

Due modi, sempre in un'unica transazione:

* ``sposta``: tutto cio' che e' collegato al piano (applicazioni, scadenze con il
  loro storico, regole del vecchio motore, personalizzazioni, scadenze spostate nei
  piani, requisiti MPQ) passa a un altro piano; poi il piano viene cancellato.
* ``cancella``: si cancella tutto. Gli OdL restano (sono lavoro registrato), perdono
  solo il collegamento alla scadenza; il collegamento di una visita ditta passa
  all'OdL della scadenza quando c'e', altrimenti viene tolto (la visita resta in
  Reception).

La verifica guarda anche le relazioni non previste qui: se un modello nuovo punta
al piano con PROTECT e ha righe, l'eliminazione si ferma e lo dice.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import models, transaction

from ..models import (
    AssetAdministrativeDeadline,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenanceOccurrenceAttachment,
    MaintenanceOccurrencePostponement,
    MaintenancePlanAssignment,
    MaintenanceRule,
    MaintenanceRuleAssetOverride,
    WorkOrder,
)

MODE_MOVE = "sposta"
MODE_DELETE = "cancella"

# Relazioni (related_name sul piano) gestite esplicitamente qui sotto.
_KNOWN_RELATIONS = {
    "assignments",
    "occurrences",
    "maintenance_rules",
    "asset_rule_overrides",
    "checklist_steps",
    "requisiti_mpq",
}


class PlanDeleteError(Exception):
    """L'eliminazione non si puo' fare: il messaggio spiega perche'."""


@dataclass
class ImpactRow:
    key: str
    label: str
    count: int
    on_move: str
    on_delete: str


@dataclass
class PlanDeleteImpact:
    rows: list[ImpactRow] = field(default_factory=list)
    unknown_blockers: list[str] = field(default_factory=list)
    unknown_other: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(row.count for row in self.rows)

    @property
    def visible_rows(self) -> list[ImpactRow]:
        return [row for row in self.rows if row.count]


def _ingresso_model():
    try:
        from fornitori.models import IngressoIntervento
    except Exception:  # pragma: no cover - app fornitori sempre installata
        return None
    return IngressoIntervento


def _requisito_model():
    try:
        from anagrafica.models_mpq import RequisitoMacchina
    except Exception:  # pragma: no cover
        return None
    return RequisitoMacchina


def _unknown_relations(plan) -> tuple[list[str], list[str]]:
    """Relazioni verso il piano non gestite da questo modulo."""
    blockers: list[str] = []
    other: list[str] = []
    for rel in plan._meta.related_objects:
        accessor = rel.get_accessor_name()
        if rel.related_name in _KNOWN_RELATIONS or accessor in _KNOWN_RELATIONS:
            continue
        if rel.related_model is AssetAdministrativeDeadline:
            continue
        if not (rel.one_to_many or rel.one_to_one):
            continue
        count = rel.related_model._default_manager.filter(**{rel.field.name: plan}).count()
        if not count:
            continue
        label = f"{rel.related_model._meta.verbose_name_plural} ({count})"
        if rel.on_delete is models.PROTECT:
            blockers.append(label)
        else:
            other.append(label)
    return blockers, other


def plan_delete_impact(plan: MaintenanceInterventionTemplate) -> PlanDeleteImpact:
    occurrences = MaintenanceOccurrence.objects.filter(plan=plan)
    by_status = dict(occurrences.values_list("status").annotate(n=models.Count("id")))
    attachments = MaintenanceOccurrenceAttachment.objects.filter(occurrence__plan=plan).count()
    postponements = MaintenanceOccurrencePostponement.objects.filter(occurrence__plan=plan).count()
    workorders = (
        occurrences.exclude(work_order__isnull=True).values("work_order_id").distinct().count()
    )
    rules = MaintenanceRule.objects.filter(intervention_template=plan)
    Ingresso = _ingresso_model()
    Requisito = _requisito_model()

    rows = [
        ImpactRow(
            "assignments", "Applicazioni (dove si applica)",
            MaintenancePlanAssignment.objects.filter(plan=plan).count(),
            "passano al piano scelto (se c'e' gia' la stessa, si usa quella)",
            "cancellate",
        ),
        ImpactRow(
            "occ_open", "Scadenze aperte", by_status.get(MaintenanceOccurrence.STATUS_OPEN, 0),
            "passano al piano scelto", "cancellate",
        ),
        ImpactRow(
            "occ_done", "Manutenzioni eseguite (storico)", by_status.get(MaintenanceOccurrence.STATUS_DONE, 0),
            "passano al piano scelto con data, note e documenti", "cancellate: lo storico si perde",
        ),
        ImpactRow(
            "occ_canceled", "Scadenze annullate", by_status.get(MaintenanceOccurrence.STATUS_CANCELED, 0),
            "passano al piano scelto", "cancellate",
        ),
        ImpactRow(
            "attachments", "Documenti allegati alle scadenze", attachments,
            "restano sulle loro scadenze", "cancellati, file compresi",
        ),
        ImpactRow(
            "postponements", "Rinvii registrati", postponements,
            "restano sulle loro scadenze", "cancellati",
        ),
        ImpactRow(
            "workorders", "OdL collegati alle scadenze", workorders,
            "restano collegati", "restano, senza la scadenza collegata",
        ),
        ImpactRow(
            "ingressi", "Visite ditta collegate alle scadenze",
            Ingresso.objects.filter(occorrenza__plan=plan).count() if Ingresso else 0,
            "restano collegate",
            "passano all'OdL della scadenza se c'e', altrimenti il collegamento si toglie (la visita resta)",
        ),
        ImpactRow(
            "rules", "Regole del vecchio motore", rules.count(),
            "passano al piano scelto", "cancellate con stati e calendario",
        ),
        ImpactRow(
            "overrides", "Personalizzazioni asset che usano questo piano",
            MaintenanceRuleAssetOverride.objects.filter(override_intervention_template=plan).count(),
            "puntano al piano scelto", "tolgono il riferimento al piano",
        ),
        ImpactRow(
            "moved_deadlines", "Scadenze amministrative spostate in questo piano",
            AssetAdministrativeDeadline.objects.filter(moved_to_plan=plan).count(),
            "puntano al piano scelto", "restano, senza piano di destinazione",
        ),
        ImpactRow(
            "requisiti", "Requisiti macchina MPQ",
            Requisito.objects.filter(piano=plan).count() if Requisito else 0,
            "puntano al piano scelto", "restano, senza piano",
        ),
        ImpactRow(
            "checklist", "Step di checklist del piano", plan.checklist_steps.count(),
            "cancellati: il piano scelto tiene la sua checklist", "cancellati",
        ),
    ]
    blockers, other = _unknown_relations(plan)
    return PlanDeleteImpact(rows=rows, unknown_blockers=blockers, unknown_other=other)


def _same_target_q(assignment: MaintenancePlanAssignment) -> models.Q:
    field_name = {
        MaintenancePlanAssignment.TARGET_ASSET: "asset_id",
        MaintenancePlanAssignment.TARGET_GROUP: "asset_group_id",
        MaintenancePlanAssignment.TARGET_CATEGORY: "asset_category_id",
    }[assignment.target_type]
    return models.Q(target_type=assignment.target_type, **{field_name: getattr(assignment, field_name)})


def move_conflicts(plan, target) -> list[MaintenanceOccurrence]:
    """Scadenze non aperte che collidono con una del piano scelto (stesso asset e data).

    Una scadenza aperta che collide si fonde in quella del piano scelto; una gia'
    eseguita o annullata no, perche' i due storici direbbero cose diverse.
    """
    target_keys = set(
        MaintenanceOccurrence.objects.filter(plan=target).values_list("asset_id", "due_date")
    )
    if not target_keys:
        return []
    return [
        occ
        for occ in MaintenanceOccurrence.objects.filter(plan=plan)
        .exclude(status=MaintenanceOccurrence.STATUS_OPEN)
        .select_related("asset")
        if (occ.asset_id, occ.due_date) in target_keys
    ]


def _move_ingressi(Ingresso, source_occ, target_occ) -> None:
    for ingresso in Ingresso.objects.filter(occorrenza=source_occ):
        if Ingresso.objects.filter(visita_gp_id=ingresso.visita_gp_id, occorrenza=target_occ).exists():
            ingresso.delete()
        else:
            ingresso.occorrenza = target_occ
            ingresso.save(update_fields=["occorrenza"])


def _do_move(plan, target) -> dict:
    stats = {"applicazioni": 0, "applicazioni_unite": 0, "scadenze": 0, "scadenze_unite": 0}
    Ingresso = _ingresso_model()
    Requisito = _requisito_model()

    assignment_map: dict[int, int] = {}
    for assignment in MaintenancePlanAssignment.objects.filter(plan=plan):
        existing = MaintenancePlanAssignment.objects.filter(plan=target).filter(_same_target_q(assignment)).first()
        if existing is not None:
            assignment_map[assignment.pk] = existing.pk
        else:
            assignment.plan = target
            assignment.save(update_fields=["plan", "updated_at"])
            stats["applicazioni"] += 1

    target_occ = {
        (occ.asset_id, occ.due_date): occ for occ in MaintenanceOccurrence.objects.filter(plan=target)
    }
    for occ in MaintenanceOccurrence.objects.filter(plan=plan):
        clash = target_occ.get((occ.asset_id, occ.due_date))
        if clash is not None:
            # Solo le aperte arrivano qui (move_conflicts blocca le altre): si fondono.
            MaintenanceOccurrenceAttachment.objects.filter(occurrence=occ).update(occurrence=clash)
            MaintenanceOccurrencePostponement.objects.filter(occurrence=occ).update(occurrence=clash)
            if Ingresso is not None:
                _move_ingressi(Ingresso, occ, clash)
            if occ.work_order_id and not clash.work_order_id:
                clash.work_order_id = occ.work_order_id
                clash.save(update_fields=["work_order", "updated_at"])
            WorkOrder.objects.filter(follow_up_occurrence=occ).update(follow_up_occurrence=clash)
            occ.delete()
            stats["scadenze_unite"] += 1
            continue
        occ.plan = target
        if occ.assignment_id in assignment_map:
            occ.assignment_id = assignment_map[occ.assignment_id]
        occ.save(update_fields=["plan", "assignment", "updated_at"])
        stats["scadenze"] += 1

    # Le applicazioni doppione hanno passato le scadenze a quelle del piano scelto.
    MaintenancePlanAssignment.objects.filter(pk__in=assignment_map.keys()).delete()
    stats["applicazioni_unite"] = len(assignment_map)

    MaintenanceRule.objects.filter(intervention_template=plan).update(intervention_template=target)
    MaintenanceRuleAssetOverride.objects.filter(override_intervention_template=plan).update(
        override_intervention_template=target
    )
    AssetAdministrativeDeadline.objects.filter(moved_to_plan=plan).update(moved_to_plan=target)
    if Requisito is not None:
        Requisito.objects.filter(piano=plan).update(piano=target)
    return stats


def _do_delete(plan) -> dict:
    Ingresso = _ingresso_model()
    occurrences = MaintenanceOccurrence.objects.filter(plan=plan)
    stats = {"scadenze": occurrences.count()}

    if Ingresso is not None:
        for ingresso in Ingresso.objects.filter(occorrenza__plan=plan).select_related("occorrenza"):
            wo_id = ingresso.occorrenza.work_order_id
            if wo_id and not Ingresso.objects.filter(visita_gp_id=ingresso.visita_gp_id, work_order_id=wo_id).exists():
                ingresso.occorrenza = None
                ingresso.work_order_id = wo_id
                ingresso.save(update_fields=["occorrenza", "work_order"])
            else:
                ingresso.delete()

    files = [
        (att.file.storage, att.file.name)
        for att in MaintenanceOccurrenceAttachment.objects.filter(occurrence__plan=plan)
        if att.file
    ]

    MaintenanceRuleAssetOverride.objects.filter(override_intervention_template=plan).update(
        override_intervention_template=None
    )
    occurrences.delete()
    stats["applicazioni"], _ = MaintenancePlanAssignment.objects.filter(plan=plan).delete()
    rules = MaintenanceRule.objects.filter(intervention_template=plan)
    stats["regole"] = rules.count()
    rules.delete()

    def _remove_files():
        for storage, name in files:
            try:
                storage.delete(name)
            except Exception:  # noqa: BLE001 - un file mancante non deve rompere niente
                pass

    transaction.on_commit(_remove_files)
    stats["file"] = len(files)
    return stats


def delete_plan(plan: MaintenanceInterventionTemplate, *, mode: str, target=None) -> dict:
    """Elimina il piano. Ritorna i numeri di cosa e' stato spostato o cancellato."""
    if mode not in (MODE_MOVE, MODE_DELETE):
        raise PlanDeleteError("Scegli se spostare tutto su un altro piano o cancellare tutto.")
    blockers, _ = _unknown_relations(plan)
    if blockers:
        raise PlanDeleteError("Il piano e' ancora usato da: " + ", ".join(blockers) + ".")
    if mode == MODE_MOVE:
        if target is None:
            raise PlanDeleteError("Scegli il piano su cui spostare tutto.")
        if target.pk == plan.pk:
            raise PlanDeleteError("Il piano di destinazione deve essere diverso da quello da eliminare.")
        conflicts = move_conflicts(plan, target)
        if conflicts:
            raise PlanDeleteError(
                f"{len(conflicts)} manutenzioni gia' eseguite o annullate hanno la stessa data e lo stesso "
                f"asset di una scadenza di «{target.label}»: risolvile prima o scegli «Cancella tutto»."
            )

    with transaction.atomic():
        stats = _do_move(plan, target) if mode == MODE_MOVE else _do_delete(plan)
        plan.delete()
    return stats
