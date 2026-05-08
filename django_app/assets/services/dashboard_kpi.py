from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Avg, Count, Sum
from django.utils import timezone

from assets.models import (
    Asset,
    AssetAdministrativeDeadline,
    AssetAdministrativeDeadlineCompletion,
    AssetCategory,
    WorkOrder,
)
from tickets.models import StatoTicket, Ticket, TipoTicket


UNCATEGORIZED_LABEL = "Senza famiglia"
FIRE_SAFETY_CATEGORY_CODE = "antincendio"

# Raggruppamento famiglie per asset_type (livello alto, non per categoria singola)
_ASSET_TYPE_FAMILY_MAP: list[tuple[str, str, list[str]]] = [
    ("it", "Asset IT", ["PC", "NOTEBOOK", "SERVER", "VM", "FIREWALL", "STAMPANTE", "HW", "FONIA"]),
    ("produzione", "Produzione", ["CNC", "WORK_MACHINE", "CARROPONTE"]),
    ("videosorveglianza", "Videosorveglianza", ["CCTV"]),
    ("altro", "Altro", ["OTHER"]),
]
_TYPE_TO_FAMILY: dict[str, str] = {
    t: key
    for key, _, types in _ASSET_TYPE_FAMILY_MAP
    for t in types
}


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


def get_maintenance_kpis_for_types(
    asset_types: list[str],
    today: date | None = None,
    window_days: int = 90,
) -> dict:
    """
    Versione single-family di get_maintenance_status_by_family.
    Restituisce coinvolti / manutentati / da_manutentare / percent_done
    per l'insieme di asset_type passato.
    """
    today = today or timezone.localdate()
    horizon = today + timedelta(days=window_days)
    lookback = today - timedelta(days=365)

    coinvolti_ids: set[int] = set(
        AssetAdministrativeDeadline.objects
        .filter(is_active=True, due_date__lte=horizon, asset__asset_type__in=asset_types)
        .exclude(asset__status=Asset.STATUS_RETIRED)
        .values_list("asset_id", flat=True)
        .distinct()
    )
    if not coinvolti_ids:
        return {"coinvolti": 0, "manutentati": 0, "da_manutentare": 0, "percent_done": 0}

    maintained_ids: set[int] = set(
        AssetAdministrativeDeadlineCompletion.objects
        .filter(completed_on__gte=lookback, deadline__asset__asset_type__in=asset_types)
        .exclude(deadline__asset__status=Asset.STATUS_RETIRED)
        .values_list("deadline__asset_id", flat=True)
        .distinct()
    )
    coinvolti = len(coinvolti_ids)
    manutentati = len(coinvolti_ids & maintained_ids)
    return {
        "coinvolti": coinvolti,
        "manutentati": manutentati,
        "da_manutentare": coinvolti - manutentati,
        "percent_done": int(manutentati / coinvolti * 100),
    }


def get_maintenance_status_by_family(
    today: date | None = None,
    window_days: int = 90,
) -> list[dict]:
    """
    Per ogni famiglia di asset_type restituisce:
      coinvolti      – asset con almeno una scadenza attiva entro window_days gg
      manutentati    – sottoinsieme di coinvolti con almeno un'esecuzione negli ultimi 365 gg
      da_manutentare – coinvolti - manutentati
      percent_done   – int 0-100

    Famiglie vuote (coinvolti=0) non vengono incluse nel risultato.
    """
    today = today or timezone.localdate()
    horizon = today + timedelta(days=window_days)
    lookback = today - timedelta(days=365)

    upcoming_pairs = list(
        AssetAdministrativeDeadline.objects.filter(is_active=True, due_date__lte=horizon)
        .exclude(asset__status=Asset.STATUS_RETIRED)
        .values_list("asset_id", "asset__asset_type")
        .distinct()
    )

    maintained_ids: set[int] = set(
        AssetAdministrativeDeadlineCompletion.objects.filter(completed_on__gte=lookback)
        .exclude(deadline__asset__status=Asset.STATUS_RETIRED)
        .values_list("deadline__asset_id", flat=True)
        .distinct()
    )

    family_assets: dict[str, set[int]] = {key: set() for key, _, _ in _ASSET_TYPE_FAMILY_MAP}
    for asset_id, asset_type in upcoming_pairs:
        family_key = _TYPE_TO_FAMILY.get(asset_type or "")
        if family_key:
            family_assets[family_key].add(asset_id)

    results: list[dict] = []
    for key, label, _ in _ASSET_TYPE_FAMILY_MAP:
        coinvolti_set = family_assets[key]
        if not coinvolti_set:
            continue
        manutentati_set = coinvolti_set & maintained_ids
        coinvolti_n = len(coinvolti_set)
        manutentati_n = len(manutentati_set)
        results.append({
            "key": key,
            "label": label,
            "coinvolti": coinvolti_n,
            "manutentati": manutentati_n,
            "da_manutentare": coinvolti_n - manutentati_n,
            "percent_done": int(manutentati_n / coinvolti_n * 100),
        })
    return results


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


def get_maintenance_performance_kpis(today: date | None = None, lookback_days: int = 30) -> dict:
    """
    KPI di performance manutenzione: MTTR, downtime, costi, backlog per tipo.

    Parametri:
        today        – data di riferimento (default: oggi)
        lookback_days – finestra temporale per il calcolo MTTR (default 30 giorni)

    Chiavi restituite:
        mttr_hours              Decimal  – media ore di risoluzione OdL correttivi chiusi
        downtime_hours_month    Decimal  – somma ore di fermo OdL chiusi nel mese corrente
        maintenance_cost_month  Decimal  – somma costi OdL chiusi nel mese con costo valorizzato
        wo_open_by_kind         dict     – {kind_code: {"label": str, "count": int}}, solo kind > 0
        wo_open_total           int      – totale OdL aperti
        ticket_man_open         int      – ticket manutenzione aperti
        wo_closed_month         int      – OdL chiusi nel mese corrente
        has_data                bool     – True se almeno un aggregato > 0
    """
    today = today or timezone.localdate()
    first_day, next_month = _month_bounds(today)
    lookback_from = today - timedelta(days=lookback_days)

    # --- mttr_hours: media minuti/60 degli OdL correttivi chiusi nella finestra --------
    mttr_hours: Decimal = Decimal("0")
    try:
        result = (
            WorkOrder.objects
            .filter(
                kind=WorkOrder.KIND_CORRECTIVE,
                status=WorkOrder.STATUS_DONE,
                closed_at__date__gte=lookback_from,
                closed_at__date__lte=today,
                intervention_duration_minutes__gt=0,
            )
            .aggregate(avg_min=Avg("intervention_duration_minutes"))
        )
        avg_min = result.get("avg_min")
        if avg_min is not None:
            mttr_hours = Decimal(str(avg_min)) / Decimal("60")
    except Exception:
        pass

    # --- downtime_hours_month: somma minuti/60 degli OdL chiusi nel mese ---------------
    downtime_hours_month: Decimal = Decimal("0")
    try:
        wo_closed_month_qs = WorkOrder.objects.filter(
            status=WorkOrder.STATUS_DONE,
            closed_at__date__gte=first_day,
            closed_at__date__lt=next_month,
        )
        raw = wo_closed_month_qs.aggregate(total_min=Sum("downtime_minutes")).get("total_min")
        if raw is not None:
            downtime_hours_month = Decimal(str(raw)) / Decimal("60")
    except Exception:
        pass

    # --- maintenance_cost_month: somma costi OdL chiusi nel mese -----------------------
    maintenance_cost_month: Decimal = Decimal("0")
    try:
        wo_cost_qs = WorkOrder.objects.filter(
            status=WorkOrder.STATUS_DONE,
            closed_at__date__gte=first_day,
            closed_at__date__lt=next_month,
            cost_eur__isnull=False,
        )
        raw_cost = wo_cost_qs.aggregate(total=Sum("cost_eur")).get("total")
        if raw_cost is not None:
            maintenance_cost_month = Decimal(str(raw_cost))
    except Exception:
        pass

    # --- wo_closed_month: conteggio OdL chiusi nel mese --------------------------------
    wo_closed_month: int = 0
    try:
        wo_closed_month = int(
            WorkOrder.objects.filter(
                status=WorkOrder.STATUS_DONE,
                closed_at__date__gte=first_day,
                closed_at__date__lt=next_month,
            ).count()
        )
    except Exception:
        pass

    # --- wo_open_by_kind: distribuzione OdL aperti per tipo ----------------------------
    wo_open_by_kind: dict[str, dict] = {}
    wo_open_total: int = 0
    try:
        kind_counts = {
            row["kind"]: int(row["count"] or 0)
            for row in (
                WorkOrder.objects
                .filter(status=WorkOrder.STATUS_OPEN)
                .order_by()
                .values("kind")
                .annotate(count=Count("id"))
            )
        }
        for kind_code, kind_label in WorkOrder.KIND_CHOICES:
            count = kind_counts.get(kind_code, 0)
            if count > 0:
                wo_open_by_kind[kind_code] = {"label": kind_label, "count": count}
        wo_open_total = sum(entry["count"] for entry in wo_open_by_kind.values())
        if wo_open_total:
            for entry in wo_open_by_kind.values():
                entry["percent"] = int(entry["count"] / wo_open_total * 100)
    except Exception:
        pass

    # --- ticket_man_open: ticket manutenzione aperti -----------------------------------
    ticket_man_open: int = 0
    try:
        ticket_man_open = int(
            _base_ticket_man_qs().filter(stato__in=_ticket_open_statuses()).count()
        )
    except Exception:
        pass

    has_data: bool = (
        wo_open_total > 0
        or downtime_hours_month > Decimal("0")
        or wo_closed_month > 0
    )

    return {
        "mttr_hours": mttr_hours,
        "downtime_hours_month": downtime_hours_month,
        "maintenance_cost_month": maintenance_cost_month,
        "wo_open_by_kind": wo_open_by_kind,
        "wo_open_total": wo_open_total,
        "ticket_man_open": ticket_man_open,
        "wo_closed_month": wo_closed_month,
        "has_data": has_data,
    }


def get_asset_maintenance_costs(asset_id: int, today: date | None = None) -> dict:
    """P3.4 — Costi manutenzione per asset, per periodo e per tipo intervento.

    Calcola per l'asset indicato:
    - costo totale per mese corrente, trimestre corrente, anno corrente
    - breakdown per tipo OdL (PREVENTIVE/CORRECTIVE/SAFETY/CALIBRATION/OTHER)
    - confronto anno corrente vs anno precedente
    - costo da completamenti scadenze amministrative (stesso asset, anno corrente)
    - totale interventi (chiusi) per periodo

    Ogni aggregazione è in try/except indipendente: nessuna eccezione fa saltare il blocco.
    Compatibile con mssql-django (no ExpressionWrapper/DurationField).
    """
    _today = today or timezone.localdate()

    # Bounds temporali
    month_start = _today.replace(day=1)
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)

    quarter = (_today.month - 1) // 3
    quarter_start = _today.replace(month=quarter * 3 + 1, day=1)
    if quarter_start.month + 3 > 12:
        quarter_end = quarter_start.replace(year=quarter_start.year + 1, month=(quarter_start.month + 3) % 12 or 12)
    else:
        quarter_end = quarter_start.replace(month=quarter_start.month + 3)

    year_start = _today.replace(month=1, day=1)
    year_end = year_start.replace(year=year_start.year + 1)
    prev_year_start = year_start.replace(year=year_start.year - 1)
    prev_year_end = year_start

    ZERO = Decimal("0")

    def _wo_cost(start: date, end: date, kind: str | None = None) -> Decimal:
        try:
            qs = WorkOrder.objects.filter(
                asset_id=asset_id,
                status=WorkOrder.STATUS_DONE,
                closed_at__date__gte=start,
                closed_at__date__lt=end,
                cost_eur__isnull=False,
            )
            if kind:
                qs = qs.filter(kind=kind)
            val = qs.aggregate(total=Sum("cost_eur")).get("total")
            return Decimal(str(val)) if val is not None else ZERO
        except Exception:
            return ZERO

    def _wo_count(start: date, end: date) -> int:
        try:
            return int(WorkOrder.objects.filter(
                asset_id=asset_id,
                status=WorkOrder.STATUS_DONE,
                closed_at__date__gte=start,
                closed_at__date__lt=end,
            ).count())
        except Exception:
            return 0

    def _deadline_cost(start: date, end: date) -> Decimal:
        try:
            val = (
                AssetAdministrativeDeadlineCompletion.objects
                .filter(
                    deadline__asset_id=asset_id,
                    completed_on__gte=start,
                    completed_on__lt=end,
                    cost_eur__isnull=False,
                )
                .aggregate(total=Sum("cost_eur"))
                .get("total")
            )
            return Decimal(str(val)) if val is not None else ZERO
        except Exception:
            return ZERO

    # --- Costi per periodo ---
    cost_month = _wo_cost(month_start, month_end)
    cost_quarter = _wo_cost(quarter_start, quarter_end)
    cost_year = _wo_cost(year_start, year_end)
    cost_prev_year = _wo_cost(prev_year_start, prev_year_end)

    # --- TCO cumulato (tutti gli anni, OdL chiusi) ---
    tco_workorders = ZERO
    try:
        val = (
            WorkOrder.objects
            .filter(asset_id=asset_id, status=WorkOrder.STATUS_DONE, cost_eur__isnull=False)
            .aggregate(total=Sum("cost_eur"))
            .get("total")
        )
        tco_workorders = Decimal(str(val)) if val is not None else ZERO
    except Exception:
        pass

    tco_deadlines = ZERO
    try:
        val = (
            AssetAdministrativeDeadlineCompletion.objects
            .filter(deadline__asset_id=asset_id, cost_eur__isnull=False)
            .aggregate(total=Sum("cost_eur"))
            .get("total")
        )
        tco_deadlines = Decimal(str(val)) if val is not None else ZERO
    except Exception:
        pass

    tco_cumulative = tco_workorders + tco_deadlines

    # --- Deadline cost anno corrente ---
    deadline_cost_year = _deadline_cost(year_start, year_end)

    # --- Breakdown per tipo (anno corrente) ---
    kind_breakdown: list[dict] = []
    try:
        rows = (
            WorkOrder.objects
            .filter(
                asset_id=asset_id,
                status=WorkOrder.STATUS_DONE,
                closed_at__date__gte=year_start,
                closed_at__date__lt=year_end,
            )
            .values("kind")
            .annotate(total=Sum("cost_eur"), count=Count("id"))
            .order_by("-total")
        )
        total_year_for_pct = cost_year or ZERO
        for row in rows:
            val = Decimal(str(row["total"])) if row["total"] is not None else ZERO
            pct = round(float(val / total_year_for_pct * 100), 1) if total_year_for_pct else 0.0
            kind_label_map = {
                WorkOrder.KIND_PREVENTIVE: "Preventiva",
                WorkOrder.KIND_CORRECTIVE: "Correttiva",
                WorkOrder.KIND_SAFETY: "Sicurezza",
                WorkOrder.KIND_CALIBRATION: "Taratura",
                WorkOrder.KIND_OTHER: "Altro",
            }
            kind_breakdown.append({
                "kind": row["kind"],
                "label": kind_label_map.get(row["kind"], row["kind"]),
                "cost": val,
                "count": int(row["count"] or 0),
                "percent": pct,
            })
    except Exception:
        pass

    # --- Conteggi interventi per periodo ---
    count_month = _wo_count(month_start, month_end)
    count_quarter = _wo_count(quarter_start, quarter_end)
    count_year = _wo_count(year_start, year_end)

    # --- Confronto anno vs anno precedente ---
    yoy_delta: Decimal | None = None
    yoy_pct: float | None = None
    if cost_prev_year > ZERO:
        yoy_delta = cost_year - cost_prev_year
        yoy_pct = round(float(yoy_delta / cost_prev_year * 100), 1)

    has_data = (cost_year > ZERO or deadline_cost_year > ZERO or count_year > 0)

    return {
        # Costi per periodo (solo OdL)
        "cost_month": cost_month,
        "cost_quarter": cost_quarter,
        "cost_year": cost_year,
        "cost_prev_year": cost_prev_year,
        # Costi scadenze amministrative (anno corrente)
        "deadline_cost_year": deadline_cost_year,
        # Totale combinato anno corrente
        "total_cost_year": cost_year + deadline_cost_year,
        # TCO cumulato (tutti gli anni)
        "tco_cumulative": tco_cumulative,
        # Breakdown per tipo (anno corrente)
        "kind_breakdown": kind_breakdown,
        # Conteggi interventi per periodo
        "count_month": count_month,
        "count_quarter": count_quarter,
        "count_year": count_year,
        # Confronto YoY
        "yoy_delta": yoy_delta,
        "yoy_pct": yoy_pct,
        # Meta
        "year": _today.year,
        "prev_year": _today.year - 1,
        "quarter_label": f"T{quarter + 1} {_today.year}",
        "has_data": has_data,
    }
