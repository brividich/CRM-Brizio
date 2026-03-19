from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.db.models import Q
from django.utils import timezone

from .models import (
    Asset,
    AssetMaintenanceRuleState,
    AssistanceContract,
    MaintenanceRule,
    MaintenanceRuleAssetOverride,
    WorkOrder,
)

STATUS_INHERITED = "inherited"
STATUS_OVERRIDDEN = "overridden"
STATUS_DISABLED = "disabled"
SCHEDULE_UPCOMING = "upcoming"
SCHEDULE_WARNING = "warning"
SCHEDULE_OVERDUE = "overdue"
SCHEDULE_MISSING = "missing"


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


def upsert_asset_maintenance_rule_state(
    *,
    asset: Asset,
    base_rule: MaintenanceRule,
    executed_on: date | None,
    workorder: WorkOrder | None = None,
    notes: str = "",
) -> AssetMaintenanceRuleState:
    state, _created = AssetMaintenanceRuleState.objects.get_or_create(asset=asset, base_rule=base_rule)
    state.last_execution_date = executed_on
    state.last_work_order = workorder
    state.notes = (notes or "").strip()
    state.save()
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
        return {
            "status": SCHEDULE_MISSING,
            "label": "Prima esecuzione da pianificare",
            "badge_class": "muted",
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


def build_day_based_maintenance_schedule_rows(
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
        MaintenanceRule.objects.select_related("asset_category", "intervention_template")
        .filter(asset_category_id__in=category_ids)
        .order_by("asset_category__sort_order", "sort_order", "id")
    )
    base_rules_by_category: dict[int, list[MaintenanceRule]] = {}
    for base_rule in base_rules:
        base_rules_by_category.setdefault(base_rule.asset_category_id, []).append(base_rule)

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
            override = override_by_asset_rule.get((asset.id, base_rule.id))
            resolved_row = _resolved_rule_row(
                asset=asset,
                base_rule=base_rule,
                override=override,
                threshold_labels=threshold_labels,
            )
            if not base_rule.is_active or resolved_row["is_disabled"]:
                continue
            if resolved_row["effective_threshold_type"] != MaintenanceRule.THRESHOLD_DAYS:
                continue

            state = state_by_asset_rule.get((asset.id, base_rule.id))
            last_execution_date = state.last_execution_date if state else None
            due_date = None
            if last_execution_date is not None:
                due_date = last_execution_date + timedelta(days=int(resolved_row["effective_threshold_value"] or 0))
            schedule = _schedule_status_payload(
                due_date=due_date,
                warning_days=int(resolved_row.get("effective_warning_days") or 0),
                today=current_day,
            )
            rows.append(
                {
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
                    "due_date": due_date,
                    "schedule_status": schedule["status"],
                    "schedule_label": schedule["label"],
                    "schedule_badge_class": schedule["badge_class"],
                    "days_until_due": schedule["days_until_due"],
                }
            )

    status_order = {
        SCHEDULE_OVERDUE: 0,
        SCHEDULE_WARNING: 1,
        SCHEDULE_UPCOMING: 2,
        SCHEDULE_MISSING: 3,
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
