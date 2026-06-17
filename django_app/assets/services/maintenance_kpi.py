from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from django.utils import timezone

from assets.models import Asset, AssetCategory, AssetMaintenanceBudget, WorkOrder


def _as_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _percent(numerator: Decimal | int, denominator: Decimal | int) -> float | None:
    denominator_dec = _as_decimal(denominator)
    if denominator_dec <= 0:
        return None
    return round(float(_as_decimal(numerator) / denominator_dec * Decimal("100")), 1)


def _asset_queryset_ids(asset_queryset) -> tuple[list[int], list[int]]:
    if hasattr(asset_queryset, "values_list"):
        asset_ids = list(asset_queryset.values_list("id", flat=True))
        category_ids = list(
            asset_queryset
            .exclude(asset_category_id=None)
            .values_list("asset_category_id", flat=True)
            .distinct()
        )
        return asset_ids, category_ids

    assets = list(asset_queryset or [])
    asset_ids = [int(asset.id) for asset in assets if getattr(asset, "id", None)]
    category_ids = sorted(
        {
            int(asset.asset_category_id)
            for asset in assets
            if getattr(asset, "asset_category_id", None)
        }
    )
    return asset_ids, category_ids


def _workorder_cost(workorder: WorkOrder) -> Decimal:
    return _as_decimal(workorder.resolved_total_cost_eur)


def build_maintenance_report_kpis(
    *,
    asset_queryset=None,
    schedule_rows: Iterable[dict[str, Any]] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """KPI manutenzione condivisi per reportistica.

    Il servizio resta volutamente read-only: aggrega lo stato dello scadenzario
    manutentivo e il confronto budget/consuntivo anno corrente senza creare dati.
    """
    current_day = today or timezone.localdate()
    if asset_queryset is None:
        asset_queryset = Asset.objects.all()
    asset_ids, category_ids = _asset_queryset_ids(asset_queryset)
    schedule_rows_list = list(schedule_rows or [])

    schedule_counts = Counter(str(row.get("schedule_status") or "") for row in schedule_rows_list)
    pm_applicable = (
        schedule_counts["overdue"]
        + schedule_counts["warning"]
        + schedule_counts["upcoming"]
    )
    pm_compliant = schedule_counts["warning"] + schedule_counts["upcoming"]
    pm_compliance_pct = _percent(pm_compliant, pm_applicable)

    year_start = date(current_day.year, 1, 1)
    next_year_start = date(current_day.year + 1, 1, 1)
    actual_by_category: dict[int, Decimal] = {}
    actual_total = Decimal("0")

    if asset_ids:
        workorders = (
            WorkOrder.objects
            .select_related("asset", "asset__asset_category")
            .filter(
                asset_id__in=asset_ids,
                status=WorkOrder.STATUS_DONE,
                closed_at__date__gte=year_start,
                closed_at__date__lt=next_year_start,
            )
        )
        for workorder in workorders:
            cost = _workorder_cost(workorder)
            if cost <= 0:
                continue
            category_id = getattr(workorder.asset, "asset_category_id", None)
            if not category_id:
                continue
            actual_by_category[int(category_id)] = actual_by_category.get(int(category_id), Decimal("0")) + cost
            actual_total += cost

    budget_rows: list[dict[str, Any]] = []
    budget_total = Decimal("0")
    seen_budget_category_ids: set[int] = set()
    budgets = (
        AssetMaintenanceBudget.objects
        .select_related("asset_category")
        .filter(year=current_day.year, asset_category_id__in=category_ids)
        .order_by("asset_category__sort_order", "asset_category__label", "asset_category_id")
    )
    for budget in budgets:
        actual = actual_by_category.get(int(budget.asset_category_id), Decimal("0"))
        budget_value = _as_decimal(budget.budget_eur)
        residual = budget_value - actual
        percent_used = _percent(actual, budget_value)
        if actual > budget_value:
            status = "over"
        elif percent_used is not None and percent_used >= 80:
            status = "warn"
        else:
            status = "ok"
        budget_rows.append(
            {
                "category": budget.asset_category,
                "budget": budget_value,
                "actual": actual,
                "residual": residual,
                "percent_used": percent_used,
                "has_percent_used": percent_used is not None,
                "status": status,
                "has_budget": True,
            }
        )
        budget_total += budget_value
        seen_budget_category_ids.add(int(budget.asset_category_id))

    missing_budget_category_ids = sorted(set(actual_by_category) - seen_budget_category_ids)
    if missing_budget_category_ids:
        category_map = {
            int(category.id): category
            for category in AssetCategory.objects.filter(pk__in=missing_budget_category_ids)
        }
        for category_id in missing_budget_category_ids:
            actual = actual_by_category.get(category_id, Decimal("0"))
            budget_rows.append(
                {
                    "category": category_map.get(category_id),
                    "category_label": getattr(category_map.get(category_id), "label", "Categoria non indicata"),
                    "budget": None,
                    "actual": actual,
                    "residual": None,
                    "percent_used": None,
                    "has_percent_used": False,
                    "status": "missing",
                    "has_budget": False,
                }
            )

    budget_rows.sort(
        key=lambda row: (
            0 if row["status"] == "over" else 1 if row["status"] == "warn" else 2 if row["status"] == "missing" else 3,
            -_as_decimal(row["actual"]),
            str(getattr(row.get("category"), "label", row.get("category_label", ""))).casefold(),
        )
    )
    residual_total = budget_total - actual_total if budget_total else None
    budget_percent = _percent(actual_total, budget_total)

    return {
        "pm": {
            "total_rules": len(schedule_rows_list),
            "applicable_rules": pm_applicable,
            "compliant_rules": pm_compliant,
            "overdue_rules": schedule_counts["overdue"],
            "warning_rules": schedule_counts["warning"],
            "upcoming_rules": schedule_counts["upcoming"],
            "missing_baseline_rules": schedule_counts["missing"],
            "compliance_pct": pm_compliance_pct,
            "has_compliance": pm_compliance_pct is not None,
        },
        "budget": {
            "year": current_day.year,
            "budget_total": budget_total,
            "actual_total": actual_total,
            "residual_total": residual_total,
            "percent_used": budget_percent,
            "has_percent": budget_percent is not None,
            "has_budget": bool(budget_rows),
            "over_budget_count": sum(1 for row in budget_rows if row["status"] == "over"),
            "missing_budget_count": sum(1 for row in budget_rows if row["status"] == "missing"),
            "rows": budget_rows,
        },
    }
