"""Dispositivi IT.

Estratto meccanicamente da assets/views.py (refactor C4): nessun cambio di comportamento.
"""

from __future__ import annotations


from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse


# Etichetta con cui le voci di audit si agganciano all'asset: e' la stessa che
# `core.audit.storico_oggetto` usa per ripescarle sulla scheda. Costante e non
# stringa sparsa perche' un refuso qui non romperebbe nulla — semplicemente la
# voce non comparirebbe mai nello storico, e non se ne accorgerebbe nessuno.
AUDIT_OGGETTO_ASSET = "assets.asset"
from ..forms import (
    DeviceFilterForm,
    IT_DEVICE_TYPES,
)
from ..models import (
    Asset,
    AssetCategory,
    AssetListOption,
)
from ..services.dashboard_kpi import (
    get_maintenance_kpis_for_types,
)

from ._helpers import (  # noqa: F401
    _as_int,
    _clean_string,
)
from ._helpers_c import (  # noqa: F401
    _assets_shell_context,
    _query_url,
)

@login_required
def device_list(request: HttpRequest) -> HttpResponse:
    """Lista dispositivi IT (PC, portatili, server, ecc.) con card layout."""
    form = DeviceFilterForm(request.GET or None)
    devices_qs = (
        Asset.objects
        .filter(asset_type__in=IT_DEVICE_TYPES)
        .select_related("asset_category")
        .order_by("asset_type", "reparto", "name", "asset_tag")
    )

    if form.is_valid():
        q = _clean_string(form.cleaned_data.get("q"))
        asset_type = _clean_string(form.cleaned_data.get("asset_type"))
        status = _clean_string(form.cleaned_data.get("status"))
        reparto = _clean_string(form.cleaned_data.get("reparto"))

        if q:
            devices_qs = devices_qs.filter(
                Q(asset_tag__icontains=q)
                | Q(internal_number__icontains=q)
                | Q(name__icontains=q)
                | Q(reparto__icontains=q)
                | Q(manufacturer__icontains=q)
                | Q(model__icontains=q)
                | Q(serial_number__icontains=q)
                | Q(assignment_to__icontains=q)
            )
        if asset_type:
            devices_qs = devices_qs.filter(asset_type=asset_type)
        if status:
            devices_qs = devices_qs.filter(status=status)
        if reparto:
            devices_qs = devices_qs.filter(
                Q(reparto__icontains=reparto) | Q(assignment_reparto__icontains=reparto)
            )

    from ..services.it_coverage import COVERAGE_FILTERS, apply_coverage_filter, coverage_for_assets, coverage_totals

    coverage_filter = _clean_string(request.GET.get("copertura"))
    if coverage_filter not in COVERAGE_FILTERS:
        coverage_filter = ""
    devices_qs = apply_coverage_filter(devices_qs, coverage_filter)

    device_base_qs = Asset.objects.filter(asset_type__in=IT_DEVICE_TYPES)
    total = device_base_qs.count()
    in_use_total = device_base_qs.filter(status=Asset.STATUS_IN_USE).count()
    in_stock_total = device_base_qs.filter(status=Asset.STATUS_IN_STOCK).count()
    in_repair_total = device_base_qs.filter(status=Asset.STATUS_IN_REPAIR).count()

    type_totals = list(
        device_base_qs
        .values("asset_type")
        .annotate(total=Count("id"))
        .order_by("asset_type")
    )
    type_label_map = dict(Asset.TYPE_CHOICES)
    for row in type_totals:
        row["label"] = type_label_map.get(row["asset_type"], row["asset_type"])

    visible_count = devices_qs.count()

    allowed_rows = [12, 24, 48, 96]
    rows = _as_int(request.GET.get("rows"), default=24)
    if rows not in allowed_rows:
        rows = 24
    paginator = Paginator(devices_qs, rows)
    page_number = _as_int(request.GET.get("page"), default=1)
    page_obj = paginator.get_page(page_number)
    devices = list(page_obj.object_list)
    coverage = coverage_for_assets(request, [device.id for device in devices])
    for device in devices:
        device.coverage = coverage.get(device.id)
    coverage_counts = coverage_totals(device_base_qs.exclude(status=Asset.STATUS_RETIRED))
    coverage_options = [
        {
            "value": value,
            "label": label,
            "count": coverage_counts.get(value),
            "active": value == coverage_filter,
            "url": _query_url(request, copertura=value or None, page=1),
        }
        for value, label in COVERAGE_FILTERS.items()
    ]
    page_start = ((page_obj.number - 1) * rows + 1) if visible_count else 0
    page_end = (page_start + len(devices) - 1) if visible_count else 0

    rows_options = [
        {"value": v, "active": v == rows, "url": _query_url(request, rows=v, page=1)}
        for v in allowed_rows
    ]
    page_links = []
    if paginator.num_pages > 0:
        start_page = max(1, page_obj.number - 2)
        end_page = min(paginator.num_pages, page_obj.number + 2)
        for number in range(start_page, end_page + 1):
            page_links.append({
                "number": number,
                "active": number == page_obj.number,
                "url": _query_url(request, page=number, rows=rows),
            })
    prev_page_url = _query_url(request, page=page_obj.previous_page_number(), rows=rows) if page_obj.has_previous() else ""
    next_page_url = _query_url(request, page=page_obj.next_page_number(), rows=rows) if page_obj.has_next() else ""

    bulk_list_options = list(AssetListOption.objects.filter(is_active=True).order_by("field_key", "sort_order", "value", "id"))
    bulk_asset_categories = list(AssetCategory.objects.filter(is_active=True).order_by("sort_order", "label", "id"))
    maint_kpis = get_maintenance_kpis_for_types(IT_DEVICE_TYPES)
    return render(request, "assets/pages/device_list.html", {
        "page_title": "Dispositivi IT",
        "filters_form": form,
        "devices": devices,
        "coverage_options": coverage_options,
        "coverage_filter": coverage_filter,
        "visible_count": visible_count,
        "total": total,
        "in_use_total": in_use_total,
        "in_stock_total": in_stock_total,
        "in_repair_total": in_repair_total,
        "type_totals": type_totals,
        "rows": rows,
        "rows_options": rows_options,
        "page_links": page_links,
        "prev_page_url": prev_page_url,
        "next_page_url": next_page_url,
        "page_start": page_start,
        "page_end": page_end,
        "bulk_list_options": bulk_list_options,
        "bulk_asset_categories": bulk_asset_categories,
        "asset_type_choices": Asset.TYPE_CHOICES,
        "maint_kpis": maint_kpis,
        **_assets_shell_context(
            request,
            rows=rows,
            search_action=reverse("assets:device_list"),
            new_url=reverse("assets:asset_create"),
            new_label="+ Nuovo dispositivo",
            search_placeholder="Ricerca per tag, nome, utente, reparto o seriale",
        ),
    })
