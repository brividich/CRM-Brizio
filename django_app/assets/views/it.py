"""Dispositivi IT.

Estratto meccanicamente da assets/views.py (refactor C4): nessun cambio di comportamento.
"""

from __future__ import annotations

import io
import json
import logging
import mimetypes
import os
import re
import tempfile
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.paginator import Paginator
from django.db import DatabaseError, IntegrityError, connections, transaction
from django.db.models import Avg, Case, Count, IntegerField, Max, Prefetch, ProtectedError, Q, When
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.utils.dateparse import parse_date
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.text import slugify
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from admin_portale.decorators import legacy_admin_or_acl_required, legacy_admin_required
from config.env_config import get_first_env_value, load_env_file_values, resolve_env_value, update_env_file_values
from core.acl import user_can_modulo_action
from core.public_headers import risposta_pubblica
from core.audit import log_action, storico_oggetto
from core.upload_limits import DOCUMENT_MAX_BYTES

# Etichetta con cui le voci di audit si agganciano all'asset: e' la stessa che
# `core.audit.storico_oggetto` usa per ripescarle sulla scheda. Costante e non
# stringa sparsa perche' un refuso qui non romperebbe nulla — semplicemente la
# voce non comparirebbe mai nello storico, e non se ne accorgerebbe nessuno.
AUDIT_OGGETTO_ASSET = "assets.asset"
from core.graph_utils import acquire_graph_token, is_placeholder_value
from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.legacy_utils import get_legacy_user, is_legacy_admin
from core.models import AuditLog, SiteConfig, UserDashboardLayout, UserExtraInfo
from core.module_branding import (
    get_module_branding_context,
    handle_module_branding_post,
    resolve_module_logo,
)
from core.module_registry import resolve_module_label
from core.pdf import (
    PdfTheme,
    draw_canvas_footer,
    draw_canvas_header,
)
from core.table_pdf import render_table_pdf as _report_table_pdf
from core.upload_mime import UploadMimeValidationError, safe_filename, validate_extension_and_mime
from ..forms import (
    AssistanceContractForm,
    AssetAdministrativeDeadlineForm,
    AssetAssignmentForm,
    AssetComponentForm,
    AssetFilterForm,
    AssetForm,
    AssetLabelTemplateForm,
    ChemicalAssetForm,
    MaintenanceChecklistStepFormSet,
    MaintenanceInterventionTemplateForm,
    MaintenanceRuleForm,
    MaintenanceRuleAssetOverrideForm,
    PeriodicVerificationForm,
    PlantLayoutForm,
    SoftwareLicenseForm,
    SoftwareLicenseRenewalForm,
    WorkMachineAssetForm,
    DeviceFilterForm,
    IT_DEVICE_TYPES,
    NON_IT_ASSET_TYPES,
    PRODUCTION_ASSET_TYPES,
    WorkMachineFilterForm,
    WorkOrderCloseForm,
    WorkOrderForm,
)
from ..models import _add_months
from ..models import (
    Asset,
    AssetActionButton,
    AssetAdministrativeDeadline,
    AssetAdministrativeDeadlineCompletion,
    AssetAdministrativeDeadlineCompletionAttachment,
    AssetCategory,
    AssetCategoryDocumentFolder,
    AssetCategoryField,
    AssetComponent,
    AssetCustomField,
    AssetDashboardConfig,
    AssetDetailField,
    AssetDetailSectionLayout,
    AssetDocument,
    AssetHeaderTool,
    AssetLabelTemplate,
    AssetListLayout,
    AssetListOption,
    AssetMaintenanceBudget,
    AssetMaintenanceRuleState,
    AssetMeter,
    AssetMeterHistory,
    AssetCalendarEvent,
    AssistanceContract,
    AssetReportDefinition,
    AssetReportTemplate,
    AssetSidebarButton,
    AssetTimelineEntry,
    AssetTimelineHiddenEvent,
    SoftwareLicense,
    SoftwareLicenseRenewal,
    MaintenanceInterventionTemplate,
    MaintenanceRule,
    MaintenanceRuleAssetOverride,
    PeriodicVerification,
    PlantLayout,
    PlantLayoutArea,
    PlantLayoutMarker,
    WorkMachine,
    WorkOrder,
    WorkOrderAttachment,
    WorkOrderChecklist,
    WorkOrderExecutionDay,
    WorkOrderLog,
)
from ..maintenance import (
    build_workorder_prefill_payload,
    build_day_based_maintenance_schedule_rows,
    contract_state_payload,
    copy_template_checklist_to_workorder,
    distribute_campaign_due_dates,
    get_applicable_assistance_contracts,
    get_primary_assistance_contract,
    get_workorder_overdue_days,
    normalize_workorder_source,
    preview_maintenance_rule_impact,
    resolve_asset_maintenance_rules,
    upsert_asset_maintenance_rule_state,
)
from ..notifications import notify_workorder_assigned, notify_workorder_reassigned, notify_workorder_taken_over
from ..services.dashboard_kpi import (
    get_asset_maintenance_costs,
    get_downtime_by_family,
    get_families_distribution,
    get_family_dashboard_kpis,
    get_fire_safety_kpis,
    get_maintenance_by_family,
    get_maintenance_kpis_for_types,
    get_maintenance_performance_kpis,
)
from ..services.maintenance_kpi import build_maintenance_report_kpis
from ..services import storico_asset
from ..services.ciclo_vita_asset import blocchi_eliminazione
from ..models import AssetFieldHistory
from ..services.sidebar_categories import (
    category_sidebar_active_match as _service_category_sidebar_active_match,
    category_sidebar_target as _service_category_sidebar_target,
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
