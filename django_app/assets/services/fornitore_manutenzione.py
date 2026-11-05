"""Rapporto di manutenzione con una ditta: contratti, piani, verifiche, ordini di lavoro.

Una sola funzione per la pagina «Manutenzione - ditta» di Assets e per la scheda «Manutenzione»
del fornitore: le due pagine devono dare gli stessi numeri.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.utils import timezone


def un_anno_prima(giorno: date) -> date:
    if (giorno.month, giorno.day) == (2, 29):
        return giorno.replace(year=giorno.year - 1, day=28)
    return giorno.replace(year=giorno.year - 1)


@dataclass
class RapportoDitta:
    contracts: list = field(default_factory=list)
    rules: list = field(default_factory=list)
    verifications: list = field(default_factory=list)
    workorders: list = field(default_factory=list)
    open_wos: list = field(default_factory=list)
    closed_wos: list = field(default_factory=list)
    closed_12m: list = field(default_factory=list)
    costo_12m: Decimal = Decimal("0")
    costo_12m_coverage: dict = field(default_factory=dict)


def rapporto_ditta(supplier, today: date | None = None) -> RapportoDitta:
    from assets.models import AssistanceContract, MaintenanceRule, PeriodicVerification, WorkOrder
    from assets.views._helpers_c import _copertura_dato

    today = today or timezone.localdate()
    contracts = list(
        AssistanceContract.objects.filter(supplier=supplier)
        .select_related("asset", "asset_category", "document")
        .order_by("-is_active", "-start_date", "id")
    )
    rules = list(
        MaintenanceRule.objects.filter(supplier=supplier)
        .select_related("intervention_template", "asset_category")
        .prefetch_related("assets")
        .order_by("-is_active", "asset_category__label", "sort_order", "id")
    )
    verifications = list(
        PeriodicVerification.objects.filter(supplier=supplier)
        .prefetch_related("assets")
        .order_by("-is_active", "next_verification_date", "id")
    )
    workorders = list(
        WorkOrder.objects.filter(supplier=supplier)
        .select_related("asset", "assigned_to")
        .order_by("-opened_at", "-id")
    )
    open_wos = [wo for wo in workorders if wo.status == WorkOrder.STATUS_OPEN]
    closed_wos = [wo for wo in workorders if wo.status == WorkOrder.STATUS_DONE]
    ultimo_anno = un_anno_prima(today)
    closed_12m = [wo for wo in closed_wos if wo.closed_at and wo.closed_at.date() >= ultimo_anno]
    return RapportoDitta(
        contracts=contracts,
        rules=rules,
        verifications=verifications,
        workorders=workorders,
        open_wos=open_wos,
        closed_wos=closed_wos,
        closed_12m=closed_12m,
        costo_12m=sum((wo.resolved_total_cost_eur or Decimal("0")) for wo in closed_12m),
        costo_12m_coverage=_copertura_dato(
            sum(1 for wo in closed_12m if (wo.resolved_total_cost_eur or Decimal("0")) > 0), len(closed_12m)
        ),
    )
