from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, Sum
from django.utils import timezone

from assets.models import Asset, AssetAdministrativeDeadline, AssetCategory, WorkOrder
from tickets.models import StatoTicket, Ticket, TipoTicket


UNCATEGORIZED_LABEL = "Senza famiglia"
FIRE_SAFETY_CATEGORY_CODE = "antincendio"


def _month_bounds(today: date) -> tuple[date, date]:
    first_day = today.replace(day=1)
    if first_day.month == 12:
        next_month = first_day.replace(year=first_day.year + 1, month=1)
    else:
        next_month = first_day.replace(month=first_day.month + 1)
    return first_day, next_month


def _active_assets_qs():
    return Asset.objects.exclude(status=Asset.STATUS_RETIRED)


def _resolve_family_id(family_id: Any) -> int | None:
    if family_id in (None, ""):
        return None
    try:
        clean_id = int(family_id)
    except (TypeError, ValueError):
        return None
    if not AssetCategory.objects.filter(pk=clean_id, is_active=True).exists():
        return None
    return clean_id


def _apply_family(qs, family_id: int | None, *, asset_prefix: str = ""):
    if family_id is None:
        return qs
    lookup = f"{asset_prefix}asset_category_id"
    return qs.filter(**{lookup: family_id})


def _base_ticket_man_qs():
    return Ticket.objects.filter(
        tipo=TipoTicket.MAN,
        asset__isnull=False,
        include_in_maintenance_register=True,
    ).exclude(asset__status=Asset.STATUS_RETIRED)


def _ticket_closed_statuses() -> tuple[str, str]:
    return (StatoTicket.CHIUSO, StatoTicket.RISOLTO)


def _ticket_open_statuses() -> tuple[str, str, str]:
    return (StatoTicket.APERTA, StatoTicket.IN_CARICO, StatoTicket.IN_ATTESA)


def _safe_count(qs) -> int:
    try:
        return int(qs.count())
    except Exception:
        return 0


def _safe_decimal_sum(qs, field_name: str) -> Decimal:
    try:
        value = qs.aggregate(total=Sum(field_name)).get("total")
    except Exception:
        return Decimal("0")
    return value or Decimal("0")


def _sorted_rows(rows: list[dict[str, Any]], value_key: str) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (-row[value_key], row["label"]))


def _add_percent(rows: list[dict[str, Any]], value_key: str) -> list[dict[str, Any]]:
    max_value = max((row[value_key] for row in rows), default=0)
    if not max_value:
        for row in rows:
            row["percent"] = 0
        return rows
    for row in rows:
        row["percent"] = int((row[value_key] / max_value) * 100)
    return rows


def get_family_dashboard_kpis(family_id=None, today: date | None = None) -> dict:
    today = today or timezone.localdate()
    first_day, next_month = _month_bounds(today)
    resolved_family_id = _resolve_family_id(family_id)

    assets_qs = _apply_family(_active_assets_qs(), resolved_family_id)

    workorders_qs = _apply_family(
        WorkOrder.objects.exclude(asset__status=Asset.STATUS_RETIRED),
        resolved_family_id,
        asset_prefix="asset__",
    )
    tickets_qs = _apply_family(_base_ticket_man_qs(), resolved_family_id, asset_prefix="asset__")

    ticket_closed_month_qs = tickets_qs.filter(
        stato__in=_ticket_closed_statuses(),
        closed_at__date__gte=first_day,
        closed_at__date__lt=next_month,
    )

    return {
        "totale_asset_famiglia": _safe_count(assets_qs),
        "asset_in_uso_famiglia": _safe_count(assets_qs.filter(status=Asset.STATUS_IN_USE)),
        "asset_in_riparazione_famiglia": _safe_count(assets_qs.filter(status=Asset.STATUS_IN_REPAIR)),
        "wo_aperte_famiglia": _safe_count(workorders_qs.filter(status=WorkOrder.STATUS_OPEN)),
        "wo_chiuse_mese_famiglia": _safe_count(
            workorders_qs.filter(
                status=WorkOrder.STATUS_DONE,
                closed_at__date__gte=first_day,
                closed_at__date__lt=next_month,
            )
        ),
        "ticket_man_aperti_famiglia": _safe_count(tickets_qs.filter(stato__in=_ticket_open_statuses())),
        "ticket_man_chiusi_mese_famiglia": _safe_count(ticket_closed_month_qs),
        "fermi_ore_mese_famiglia": _safe_decimal_sum(ticket_closed_month_qs, "ore_fermo_macchina"),
    }


def get_families_distribution(today: date | None = None) -> list[dict]:
    rows = []
    qs = (
        _active_assets_qs()
        .order_by()
        .values("asset_category_id", "asset_category__label")
        .annotate(count=Count("id"))
    )
    for row in qs:
        rows.append(
            {
                "id": row["asset_category_id"],
                "label": row["asset_category__label"] or UNCATEGORIZED_LABEL,
                "count": int(row["count"] or 0),
            }
        )
    return _add_percent(_sorted_rows(rows, "count"), "count")


def get_maintenance_by_family(today: date | None = None) -> list[dict]:
    today = today or timezone.localdate()
    first_day, next_month = _month_bounds(today)
    grouped: dict[int | None, dict[str, Any]] = {}

    workorder_rows = (
        WorkOrder.objects.exclude(asset__status=Asset.STATUS_RETIRED)
        .filter(
            status=WorkOrder.STATUS_DONE,
            closed_at__date__gte=first_day,
            closed_at__date__lt=next_month,
        )
        .order_by()
        .values("asset__asset_category_id", "asset__asset_category__label")
        .annotate(count=Count("id"))
    )
    for row in workorder_rows:
        category_id = row["asset__asset_category_id"]
        grouped[category_id] = {
            "id": category_id,
            "label": row["asset__asset_category__label"] or UNCATEGORIZED_LABEL,
            "count": int(row["count"] or 0),
        }

    ticket_rows = (
        _base_ticket_man_qs()
        .filter(
            stato__in=_ticket_closed_statuses(),
            closed_at__date__gte=first_day,
            closed_at__date__lt=next_month,
        )
        .order_by()
        .values("asset__asset_category_id", "asset__asset_category__label")
        .annotate(count=Count("id"))
    )
    for row in ticket_rows:
        category_id = row["asset__asset_category_id"]
        current = grouped.setdefault(
            category_id,
            {
                "id": category_id,
                "label": row["asset__asset_category__label"] or UNCATEGORIZED_LABEL,
                "count": 0,
            },
        )
        current["count"] += int(row["count"] or 0)

    return _add_percent(_sorted_rows(list(grouped.values()), "count"), "count")


def get_downtime_by_family(today: date | None = None) -> list[dict]:
    today = today or timezone.localdate()
    first_day, next_month = _month_bounds(today)
    rows = []
    qs = (
        _base_ticket_man_qs()
        .filter(
            stato__in=_ticket_closed_statuses(),
            closed_at__date__gte=first_day,
            closed_at__date__lt=next_month,
        )
        .order_by()
        .values("asset__asset_category_id", "asset__asset_category__label")
        .annotate(hours=Sum("ore_fermo_macchina"))
    )
    for row in qs:
        rows.append(
            {
                "id": row["asset__asset_category_id"],
                "label": row["asset__asset_category__label"] or UNCATEGORIZED_LABEL,
                "hours": row["hours"] or Decimal("0"),
            }
        )
    return _add_percent(_sorted_rows(rows, "hours"), "hours")


def get_fire_safety_kpis(today: date | None = None) -> dict:
    today = today or timezone.localdate()
    in_30 = today + timedelta(days=30)
    category = AssetCategory.objects.filter(code=FIRE_SAFETY_CATEGORY_CODE).first()
    if not category:
        return {
            "has_fire_safety": False,
            "antincendio_asset_totali": 0,
            "antincendio_scadenze_scadute": 0,
            "antincendio_scadenze_30gg": 0,
            "antincendio_wo_aperte": 0,
        }

    assets_qs = _active_assets_qs().filter(asset_category=category)
    deadlines_qs = AssetAdministrativeDeadline.objects.filter(
        is_active=True,
        asset__asset_category=category,
    ).exclude(asset__status=Asset.STATUS_RETIRED)

    # Le scadenze Antincendio usano le scadenze amministrative manuali asset.
    # Se non vengono censite dall'admin, i KPI restano correttamente a 0.
    return {
        "has_fire_safety": True,
        "antincendio_asset_totali": _safe_count(assets_qs),
        "antincendio_scadenze_scadute": _safe_count(deadlines_qs.filter(due_date__lt=today)),
        "antincendio_scadenze_30gg": _safe_count(deadlines_qs.filter(due_date__gte=today, due_date__lte=in_30)),
        "antincendio_wo_aperte": _safe_count(
            WorkOrder.objects.filter(
                asset__asset_category=category,
                status=WorkOrder.STATUS_OPEN,
            ).exclude(asset__status=Asset.STATUS_RETIRED)
        ),
    }
