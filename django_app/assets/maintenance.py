from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    Asset,
    AssetMaintenanceRuleState,
    AssistanceContract,
    MaintenanceChecklistStep,
    MaintenanceRule,
    MaintenanceRuleAssetOverride,
    WorkOrder,
    WorkOrderChecklist,
)

STATUS_INHERITED = "inherited"
STATUS_OVERRIDDEN = "overridden"
STATUS_DISABLED = "disabled"
SCHEDULE_UPCOMING = "upcoming"
SCHEDULE_WARNING = "warning"
SCHEDULE_OVERDUE = "overdue"
SCHEDULE_MISSING = "missing"

WORKORDER_SOURCE_MANUAL = "manual"
WORKORDER_SOURCE_ASSET = "asset_detail"
WORKORDER_SOURCE_SCHEDULE = "maintenance_schedule"
WORKORDER_SOURCE_RULES = "maintenance_rules"
WORKORDER_SOURCE_REPORTS = "maintenance_reports"
WORKORDER_SOURCE_LIST = "workorder_list"

WORKORDER_SOURCE_LABELS = {
    WORKORDER_SOURCE_MANUAL: "Apertura manuale",
    WORKORDER_SOURCE_ASSET: "Dettaglio asset",
    WORKORDER_SOURCE_SCHEDULE: "Prossime manutenzioni",
    WORKORDER_SOURCE_RULES: "Regole manutenzione asset",
    WORKORDER_SOURCE_REPORTS: "Report manutenzione",
    WORKORDER_SOURCE_LIST: "Lista interventi",
}

# Un contatore fermo produce una scadenza falsa presentata come verde ("restano 320 h" su un
# valore vecchio di mesi). Oltre questa soglia il contatore è considerato non aggiornato.

# Anzianità oltre la quale un OdL ancora aperto è "in ritardo". Era ricopiata a mano in cinque
# punti (cockpit, KPI, dashboard macchine, reminder): fonte unica.
WORKORDER_OVERDUE_DAYS_DEFAULT = 21


def get_workorder_overdue_days() -> int:
    """Giorni oltre i quali un OdL aperto è in ritardo (SiteConfig 'assets_wo_overdue_days')."""
    from core.models import SiteConfig

    try:
        value = int(
            SiteConfig.get("assets_wo_overdue_days", str(WORKORDER_OVERDUE_DAYS_DEFAULT))
            or WORKORDER_OVERDUE_DAYS_DEFAULT
        )
    except (TypeError, ValueError):
        return WORKORDER_OVERDUE_DAYS_DEFAULT
    return value if value > 0 else WORKORDER_OVERDUE_DAYS_DEFAULT


def _resolved_rule_row(
    *,
    asset: Asset,
    base_rule: MaintenanceRule,
    override: MaintenanceRuleAssetOverride | None,
    threshold_labels: dict[str, str],
) -> dict[str, Any]:
    effective_threshold_type = (
        override.override_threshold_type if override and override.override_threshold_type else base_rule.threshold_type
    )
    effective_threshold_value = (
        override.override_threshold_value
        if override and override.override_threshold_value is not None
        else base_rule.threshold_value
    )
    effective_intervention_template = (
        override.override_intervention_template
        if override and override.override_intervention_template_id
        else base_rule.intervention_template
    )
    effective_notes = (override.notes or "").strip() if override and (override.notes or "").strip() else base_rule.notes
    effective_warning_days = int(getattr(base_rule, "warning_days", 0) or 0)

    if override and override.is_disabled:
        status = STATUS_DISABLED
    elif override and override.has_effective_override:
        status = STATUS_OVERRIDDEN
    else:
        status = STATUS_INHERITED

    return {
        "asset": asset,
        "base_rule": base_rule,
        "override": override,
        "status": status,
        "is_disabled": status == STATUS_DISABLED,
        "is_overridden": status == STATUS_OVERRIDDEN,
        "is_inherited": status == STATUS_INHERITED,
        "has_override_record": override is not None,
        "is_redundant_override": bool(override and override.is_redundant),
        "effective_threshold_type": effective_threshold_type,
        "effective_threshold_label": threshold_labels.get(effective_threshold_type, effective_threshold_type),
        "effective_threshold_value": effective_threshold_value,
        "effective_warning_days": effective_warning_days,
        "effective_intervention_template": effective_intervention_template,
        "effective_notes": effective_notes,
    }


def resolve_asset_maintenance_rules(asset: Asset) -> list[dict[str, Any]]:
    if not getattr(asset, "asset_category_id", None):
        return []

    base_rules = list(
        MaintenanceRule.objects.select_related("asset_category", "intervention_template")
        .filter(asset_category_id=asset.asset_category_id)
        .filter(Q(scope_type=MaintenanceRule.SCOPE_CATEGORY) | Q(assets=asset))
        .distinct()
        .order_by("sort_order", "id")
    )
    overrides = list(
        MaintenanceRuleAssetOverride.objects.select_related(
            "asset",
            "base_rule",
            "base_rule__intervention_template",
            "override_intervention_template",
        )
        .filter(asset_id=asset.id, base_rule__asset_category_id=asset.asset_category_id)
        .order_by("base_rule__sort_order", "id")
    )
    override_by_rule_id = {override.base_rule_id: override for override in overrides}
    threshold_labels = dict(MaintenanceRule.THRESHOLD_TYPE_CHOICES)

    resolved_rows: list[dict[str, Any]] = []
    for base_rule in base_rules:
        override = override_by_rule_id.get(base_rule.id)
        resolved_rows.append(
            _resolved_rule_row(
                asset=asset,
                base_rule=base_rule,
                override=override,
                threshold_labels=threshold_labels,
            )
        )

    return resolved_rows


def get_effective_asset_maintenance_rule(asset: Asset | None, *, base_rule_id: int) -> dict[str, Any] | None:
    if asset is None or not int(base_rule_id or 0):
        return None

    for row in resolve_asset_maintenance_rules(asset):
        if row["base_rule"].id != int(base_rule_id):
            continue
        if not row["base_rule"].is_active or row["is_disabled"]:
            return None
        return row
    return None


def normalize_workorder_source(source: str) -> str:
    value = str(source or "").strip().lower()
    if value in WORKORDER_SOURCE_LABELS:
        return value
    return WORKORDER_SOURCE_MANUAL


def build_workorder_prefill_payload(
    *,
    asset: Asset | None,
    base_rule_id: int = 0,
    source: str = WORKORDER_SOURCE_MANUAL,
    today: date | None = None,
) -> dict[str, Any]:
    normalized_source = normalize_workorder_source(source)
    contract = get_primary_assistance_contract(asset, today=today) if asset is not None else None
    rule_row = get_effective_asset_maintenance_rule(asset, base_rule_id=int(base_rule_id or 0))
    template = rule_row["effective_intervention_template"] if rule_row is not None else None
    template_description = (getattr(template, "description", "") or "").strip()
    rule_notes = (str(rule_row.get("effective_notes") or "").strip() if rule_row is not None else "")
    description_parts: list[str] = []
    if template_description:
        description_parts.append(template_description)
    if rule_notes and rule_notes not in description_parts:
        description_parts.append(rule_notes)

    return {
        "source": normalized_source,
        "source_label": WORKORDER_SOURCE_LABELS.get(normalized_source, WORKORDER_SOURCE_LABELS[WORKORDER_SOURCE_MANUAL]),
        "is_from_maintenance": rule_row is not None,
        "maintenance_rule": rule_row["base_rule"] if rule_row is not None else None,
        "maintenance_rule_row": rule_row,
        "maintenance_template": template,
        "template_label": (getattr(template, "label", "") or "").strip(),
        "template_description": template_description,
        "notes": rule_notes,
        "title": (getattr(template, "label", "") or "").strip(),
        "description": "\n\n".join(description_parts).strip(),
        "kind": getattr(template, "workorder_kind", WorkOrder.KIND_PREVENTIVE) if rule_row is not None else "",
        "contract": contract,
        "covered_by_contract": bool(contract),
        "supplier": getattr(contract, "supplier", None),
    }


def upsert_asset_maintenance_rule_state(
    *,
    asset: Asset,
    base_rule: MaintenanceRule,
    executed_on: date | None,
    workorder: WorkOrder | None = None,
    notes: str = "",
) -> AssetMaintenanceRuleState:
    state, _created = AssetMaintenanceRuleState.objects.get_or_create(asset=asset, base_rule=base_rule)
    cleaned_notes = (notes or "").strip()
    changed_fields: list[str] = []
    if state.last_execution_date != executed_on:
        state.last_execution_date = executed_on
        changed_fields.append("last_execution_date")
    if state.last_work_order_id != getattr(workorder, "id", None):
        state.last_work_order = workorder
        changed_fields.append("last_work_order")
    if state.notes != cleaned_notes:
        state.notes = cleaned_notes
        changed_fields.append("notes")
    if changed_fields:
        state.save(update_fields=[*changed_fields, "updated_at"])
    return state


def sync_workorder_maintenance_state(workorder: WorkOrder | None) -> AssetMaintenanceRuleState | None:
    if workorder is None or workorder.status != WorkOrder.STATUS_DONE or not workorder.maintenance_rule_id or not workorder.asset_id:
        return None
    closed_at = workorder.closed_at or timezone.now()
    executed_on = timezone.localtime(closed_at).date() if timezone.is_aware(closed_at) else closed_at.date()
    return upsert_asset_maintenance_rule_state(
        asset=workorder.asset,
        base_rule=workorder.maintenance_rule,
        executed_on=executed_on,
        workorder=workorder,
    )


def _schedule_status_payload(*, due_date: date | None, warning_days: int, today: date) -> dict[str, Any]:
    if due_date is None:
        # Mai eseguita: il generatore la considera dovuta subito, quindi non è un'informazione
        # neutra da relegare in fondo alla lista in grigio.
        return {
            "status": SCHEDULE_MISSING,
            "label": "Prima esecuzione da pianificare",
            "badge_class": "danger",
            "days_until_due": None,
        }

    days_until_due = (due_date - today).days
    if days_until_due < 0:
        return {
            "status": SCHEDULE_OVERDUE,
            "label": f"Scaduta da {abs(days_until_due)} gg",
            "badge_class": "danger",
            "days_until_due": days_until_due,
        }
    if days_until_due <= max(0, int(warning_days or 0)):
        if days_until_due == 0:
            due_label = "Scade oggi"
        else:
            due_label = f"In scadenza ({days_until_due} gg)"
        return {
            "status": SCHEDULE_WARNING,
            "label": due_label,
            "badge_class": "warn",
            "days_until_due": days_until_due,
        }
    return {
        "status": SCHEDULE_UPCOMING,
        "label": f"Pianificata tra {days_until_due} gg",
        "badge_class": "ok",
        "days_until_due": days_until_due,
    }


def _fmt_units(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "0"
    if number == int(number):
        return str(int(number))
    return f"{number:.1f}"


def build_maintenance_schedule_rows(
    *,
    asset_queryset=None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    current_day = today or timezone.localdate()
    queryset = asset_queryset or Asset.objects.select_related("asset_category").all()
    assets = [asset for asset in list(queryset) if getattr(asset, "asset_category_id", None)]
    if not assets:
        return []

    asset_ids = [asset.id for asset in assets]
    category_ids = {asset.asset_category_id for asset in assets if asset.asset_category_id}
    base_rules = list(
        MaintenanceRule.objects.select_related("asset_category", "intervention_template", "supplier")
        .prefetch_related("assets")
        .filter(asset_category_id__in=category_ids)
        .order_by("asset_category__sort_order", "sort_order", "id")
    )
    base_rules_by_category: dict[int, list[MaintenanceRule]] = {}
    targeted_asset_ids_by_rule: dict[int, set[int]] = {}
    for base_rule in base_rules:
        base_rules_by_category.setdefault(base_rule.asset_category_id, []).append(base_rule)
        if base_rule.scope_type == MaintenanceRule.SCOPE_ASSETS:
            targeted_asset_ids_by_rule[base_rule.id] = {asset.id for asset in base_rule.assets.all()}

    overrides = list(
        MaintenanceRuleAssetOverride.objects.select_related(
            "asset",
            "base_rule",
            "base_rule__intervention_template",
            "override_intervention_template",
        )
        .filter(asset_id__in=asset_ids, base_rule__asset_category_id__in=category_ids)
        .order_by("base_rule__sort_order", "id")
    )
    override_by_asset_rule = {(override.asset_id, override.base_rule_id): override for override in overrides}
    state_by_asset_rule = {
        (state.asset_id, state.base_rule_id): state
        for state in AssetMaintenanceRuleState.objects.select_related("last_work_order").filter(
            asset_id__in=asset_ids,
            base_rule__asset_category_id__in=category_ids,
        )
    }
    threshold_labels = dict(MaintenanceRule.THRESHOLD_TYPE_CHOICES)

    rows: list[dict[str, Any]] = []
    for asset in assets:
        for base_rule in base_rules_by_category.get(asset.asset_category_id, []):
            if (
                base_rule.scope_type == MaintenanceRule.SCOPE_ASSETS
                and asset.id not in targeted_asset_ids_by_rule.get(base_rule.id, set())
            ):
                continue
            override = override_by_asset_rule.get((asset.id, base_rule.id))
            resolved_row = _resolved_rule_row(
                asset=asset,
                base_rule=base_rule,
                override=override,
                threshold_labels=threshold_labels,
            )
            if not base_rule.is_active or resolved_row["is_disabled"]:
                continue

            effective_type = resolved_row["effective_threshold_type"]
            state = state_by_asset_rule.get((asset.id, base_rule.id))
            last_execution_date = state.last_execution_date if state else None
            common = {
                **resolved_row,
                "state": state,
                "last_execution_date": last_execution_date,
                "last_execution_notes": (state.notes or "").strip() if state else "",
                "last_execution_workorder": state.last_work_order if state else None,
                "last_execution_source": (
                    "workorder"
                    if state and state.last_work_order_id
                    else "manual"
                    if state and state.last_execution_date
                    else ""
                ),
            }

            if effective_type == MaintenanceRule.THRESHOLD_DAYS:
                due_date = None
                if last_execution_date is not None:
                    due_date = last_execution_date + timedelta(days=int(resolved_row["effective_threshold_value"] or 0))
                elif base_rule.first_due_date is not None:
                    due_date = base_rule.first_due_date
                schedule = _schedule_status_payload(
                    due_date=due_date,
                    warning_days=int(resolved_row.get("effective_warning_days") or 0),
                    today=current_day,
                )
                rows.append(
                    {
                        **common,
                        "due_date": due_date,
                        "schedule_status": schedule["status"],
                        "schedule_label": schedule["label"],
                        "schedule_badge_class": schedule["badge_class"],
                        "days_until_due": schedule["days_until_due"],
                    }
                )
            # Le soglie a contatore (ore/km/cicli) non producono piu' righe: senza
            # letture attendibili davano scadenze false presentate come verdi. Restano
            # fuori dallo scadenzario, non convertite in silenzio.
            else:
                continue

    # "missing" in cima: contatore assente o manutenzione mai eseguita significa che non
    # sappiamo nemmeno se è scaduta. Prima stava in fondo, in grigio: il segnale più debole
    # sul rischio più alto.
    status_order = {
        SCHEDULE_MISSING: 0,
        SCHEDULE_OVERDUE: 1,
        SCHEDULE_WARNING: 2,
        SCHEDULE_UPCOMING: 3,
    }
    rows.sort(
        key=lambda row: (
            status_order.get(str(row.get("schedule_status") or ""), 9),
            row.get("due_date") or date.max,
            _clean_sort_value(getattr(row.get("asset"), "reparto", "")),
            _clean_sort_value(getattr(row.get("asset"), "name", "")),
            getattr(row.get("asset"), "id", 0),
            row["base_rule"].id,
        )
    )
    return rows


# Compat: il nome storico restituiva solo righe a giorni; ora il motore include anche
# le regole a contatore (ore/km/cicli). I chiamanti che filtrano per due_date data
# ignorano automaticamente le righe a contatore.
build_day_based_maintenance_schedule_rows = build_maintenance_schedule_rows


def preview_maintenance_rule_impact(
    *,
    asset_category_id: int | None,
    scope_type: str,
    asset_ids: list[int] | None,
    threshold_type: str,
    threshold_value: int | None,
    warning_days: int | None,
    first_due_date: date | None,
    rule_pk: int | None = None,
    today: date | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Anteprima non persistita dell'impatto di una regola in fase di compilazione nel form:
    quanti asset copre lo scope scelto e le prime scadenze che ne deriverebbero.

    Non tocca ``MaintenanceRule.objects``: legge solo lo stato di esecuzione già salvato
    (``AssetMaintenanceRuleState``) quando ``rule_pk`` è dato (form di modifica) — una regola
    nuova non ha ancora stato per definizione, quindi ogni asset risulta "prima esecuzione".
    Ignora deliberatamente gli override per asset: sono un dettaglio della regola già salvata,
    non della bozza in corso di compilazione.
    """
    current_day = today or timezone.localdate()
    if not asset_category_id:
        return {"asset_count": 0, "upcoming": []}

    assets_qs = Asset.objects.filter(status=Asset.STATUS_IN_USE, asset_category_id=asset_category_id)
    if scope_type == MaintenanceRule.SCOPE_ASSETS:
        assets_qs = assets_qs.filter(id__in=asset_ids or [])
    assets = list(assets_qs.only("id", "name", "asset_tag", "reparto", "asset_category_id"))
    if not assets:
        return {"asset_count": 0, "upcoming": []}

    asset_ids_resolved = [asset.id for asset in assets]
    threshold_value = int(threshold_value or 0)
    warning_days = int(warning_days or 0)

    rows: list[dict[str, Any]] = []

    if threshold_type == MaintenanceRule.THRESHOLD_DAYS:
        state_by_asset = {}
        if rule_pk:
            state_by_asset = {
                state.asset_id: state
                for state in AssetMaintenanceRuleState.objects.filter(
                    asset_id__in=asset_ids_resolved, base_rule_id=rule_pk
                )
            }
        for asset in assets:
            state = state_by_asset.get(asset.id)
            due_date = None
            if state and state.last_execution_date:
                due_date = state.last_execution_date + timedelta(days=threshold_value)
            elif first_due_date:
                due_date = first_due_date
            schedule = _schedule_status_payload(due_date=due_date, warning_days=warning_days, today=current_day)
            rows.append({"asset": asset, "due_date": due_date, "schedule_label": schedule["label"], "schedule_status": schedule["status"]})
    else:
        return {"asset_count": len(assets), "upcoming": []}

    status_order = {SCHEDULE_MISSING: 0, SCHEDULE_OVERDUE: 1, SCHEDULE_WARNING: 2, SCHEDULE_UPCOMING: 3}
    rows.sort(
        key=lambda row: (
            status_order.get(str(row.get("schedule_status") or ""), 9),
            row.get("due_date") or date.max,
            getattr(row["asset"], "name", "") or "",
        )
    )
    return {"asset_count": len(assets), "upcoming": rows[:limit]}


def distribute_campaign_due_dates(
    *,
    count: int,
    window_days: int,
    start_date: date | None = None,
    assigned_to=None,
    max_per_day: int = 3,
) -> list[date]:
    """Distribuisce ``count`` scadenze su una finestra di ``window_days`` giorni (round-robin),
    invece di metterle tutte sulla stessa data come farebbe una singola ``MaintenanceRule``
    category-wide. Se ``assigned_to`` è dato, evita — quando possibile — di superare
    ``max_per_day`` OdL aperti nello stesso giorno per quel tecnico, sommando il carico già
    esistente a quello che si sta per creare. Se la finestra è troppo stretta per rispettare
    il tetto, lo supera piuttosto che rifiutarsi di distribuire (nessun asset resta escluso)."""
    start_date = start_date or timezone.localdate()
    window_days = max(1, int(window_days or 1))
    day_candidates = [start_date + timedelta(days=i) for i in range(window_days)]

    load = {day: 0 for day in day_candidates}
    if assigned_to is not None:
        end_date = day_candidates[-1]
        existing = (
            WorkOrder.objects.filter(
                assigned_to=assigned_to,
                status=WorkOrder.STATUS_OPEN,
                due_at__date__gte=start_date,
                due_at__date__lte=end_date,
            )
            .values("due_at__date")
            .annotate(n=Count("id"))
        )
        for row in existing:
            day = row["due_at__date"]
            if day in load:
                load[day] = row["n"]

    dates: list[date] = []
    cursor = 0
    for _ in range(max(0, int(count or 0))):
        attempts = 0
        while attempts < window_days and load[day_candidates[cursor % window_days]] >= max_per_day:
            cursor += 1
            attempts += 1
        chosen = day_candidates[cursor % window_days]
        load[chosen] += 1
        dates.append(chosen)
        cursor += 1
    return dates


def _clean_sort_value(value) -> str:
    return str(value or "").strip().casefold()


def contract_state_payload(contract: AssistanceContract, *, today: date | None = None) -> dict[str, str]:
    current_day = today or timezone.localdate()
    if not contract.is_active:
        return {"status": "inactive", "label": "Disattivo", "badge_class": "muted"}
    if contract.start_date and contract.start_date > current_day:
        return {"status": "scheduled", "label": "Non ancora attivo", "badge_class": "warn"}
    if contract.end_date and contract.end_date < current_day:
        return {"status": "expired", "label": "Scaduto", "badge_class": "danger"}
    if contract.end_date and contract.end_date <= current_day + timedelta(days=30):
        return {"status": "expiring", "label": "In scadenza", "badge_class": "warn"}
    return {"status": "active", "label": "Attivo", "badge_class": "ok"}


def get_applicable_assistance_contracts(asset: Asset | None, *, today: date | None = None) -> list[AssistanceContract]:
    if asset is None:
        return []
    current_day = today or timezone.localdate()
    target_filter = Q(asset_id=asset.id) | Q(asset__isnull=True, asset_category__isnull=True)
    if getattr(asset, "asset_category_id", None):
        target_filter |= Q(asset__isnull=True, asset_category_id=asset.asset_category_id)

    contracts = list(
        AssistanceContract.objects.select_related("supplier", "asset", "asset_category", "document")
        .filter(target_filter)
        .order_by("supplier__ragione_sociale", "title", "id")
    )
    current_contracts = [contract for contract in contracts if contract.is_current(current_day)]
    current_contracts.sort(
        key=lambda contract: (
            _contract_specificity(contract=contract, asset=asset),
            contract.end_date.toordinal() if contract.end_date else date.max.toordinal(),
            -(contract.start_date.toordinal() if contract.start_date else 0),
            contract.id,
        )
    )
    return current_contracts


def get_primary_assistance_contract(asset: Asset | None, *, today: date | None = None) -> AssistanceContract | None:
    contracts = get_applicable_assistance_contracts(asset, today=today)
    return contracts[0] if contracts else None


def _contract_specificity(*, contract: AssistanceContract, asset: Asset) -> int:
    if contract.asset_id == asset.id:
        return 0
    if contract.asset_id is None and contract.asset_category_id and contract.asset_category_id == getattr(asset, "asset_category_id", None):
        return 1
    return 2


def copy_template_checklist_to_workorder(workorder: WorkOrder | None, *, template_id: int | None = None) -> int:
    """Copia gli step di checklist del template intervento come ``WorkOrderChecklist``.

    Usata sia dalla creazione manuale dell'OdL (view) sia dalla generazione periodica
    automatica (``generate_scheduled_workorders``), così il comportamento è unico.
    Se ``template_id`` è passato (es. template effettivo da override) usa quello,
    altrimenti deriva dal template della regola collegata al WorkOrder.
    Idempotente: se l'OdL ha già una checklist non duplica nulla. Ritorna il numero di
    step creati.
    """
    if workorder is None or not workorder.pk:
        return 0
    if template_id is None:
        if not workorder.maintenance_rule_id:
            return 0
        template_id = getattr(workorder.maintenance_rule, "intervention_template_id", None)
    if not template_id:
        return 0
    if WorkOrderChecklist.objects.filter(work_order=workorder).exists():
        return 0
    steps = list(
        MaintenanceChecklistStep.objects.filter(intervention_template_id=template_id).order_by("step_number", "id")
    )
    if not steps:
        return 0
    WorkOrderChecklist.objects.bulk_create(
        [
            WorkOrderChecklist(
                work_order=workorder,
                step_number=step.step_number,
                description=step.description,
                step_type=step.step_type,
                is_mandatory=step.is_mandatory,
                unit=step.unit,
                range_min=step.range_min,
                range_max=step.range_max,
            )
            for step in steps
        ]
    )
    return len(steps)
