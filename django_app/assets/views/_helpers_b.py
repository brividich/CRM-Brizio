"""Helper condivisi delle viste Asset (estratti meccanicamente da views.py, refactor C4)."""

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
    PERIODIC_EXECUTION_WINDOW_DEFAULT,
    _as_int,
    _clean_string,
    _coalesce_str,
    _format_filesize,
    _maintenance_schedule_page_url,
    _maintenance_template_list_page_url,
    _normalize_periodic_execution_window,
    _software_licenses_page_url,
    _ui_label,
    logger,
)

def _periodic_verifications_page_url(
    *,
    asset_id: int = 0,
    edit_id: int = 0,
    scope: str = "",
    window: str = "",
    view: str = "",
    q: str = "",
    create: bool = False,
) -> str:
    params: list[str] = []
    scope_value = _normalize_reports_scope(scope) if scope else ""
    if scope_value:
        params.append(f"scope={quote(scope_value)}")
    if asset_id:
        params.append(f"asset={int(asset_id)}")
    if edit_id:
        params.append(f"edit={int(edit_id)}")
    if window:
        normalized_window = _normalize_periodic_execution_window(window)
        if normalized_window != PERIODIC_EXECUTION_WINDOW_DEFAULT:
            params.append(f"window={quote(normalized_window)}")
    view_value = _clean_string(view).lower()
    if view_value in {"active", "attention", "planned", "archive"} and view_value != "active":
        params.append(f"view={quote(view_value)}")
    q_value = _clean_string(q)
    if q_value:
        params.append(f"q={quote(q_value)}")
    if create:
        params.append("create=1")
    base_url = reverse("assets:periodic_verifications")
    return f"{base_url}?{'&'.join(params)}" if params else base_url


def _maintenance_rule_form_state(form: MaintenanceRuleForm, *, is_edit: bool) -> dict[str, object]:
    selected_category_id = _as_int(form["asset_category"].value(), default=0)
    selected_category = None
    if selected_category_id:
        selected_category = AssetCategory.objects.filter(pk=selected_category_id).only("id", "label").first()

    category_option_count = form.fields["asset_category"].queryset.count()
    available_template_count = form.fields["intervention_template"].queryset.count()
    active_template_count = MaintenanceInterventionTemplate.objects.filter(is_active=True).count()
    general_template_count = MaintenanceInterventionTemplate.objects.filter(
        is_active=True,
        asset_category__isnull=True,
    ).count()

    no_categories_available = category_option_count == 0
    no_templates_available = active_template_count == 0
    no_templates_for_selected_category = selected_category is not None and available_template_count == 0

    alert_level = ""
    alert_message = ""
    if no_categories_available:
        alert_level = "warning"
        alert_message = "Non ci sono categorie asset attive. Prima crea almeno una categoria asset."
    elif no_templates_available:
        alert_level = "warning"
        alert_message = "Non ci sono template manutenzione attivi. Crea prima almeno un template generale o associato a una categoria."
    elif no_templates_for_selected_category:
        alert_message = (
            f'Nessun template compatibile con la categoria "{selected_category.label}". '
            "Puoi creare un template generale oppure dedicato a questa categoria."
        )

    template_list_base_url = reverse("assets:maintenance_template_list")
    template_create_base_url = reverse("assets:maintenance_template_create")
    template_list_url = _maintenance_template_list_page_url(category_id=selected_category_id)
    template_create_url = template_create_base_url
    if selected_category_id:
        template_create_url = f"{template_create_base_url}?category={selected_category_id}"

    return {
        "category_option_count": category_option_count,
        "active_template_count": active_template_count,
        "general_template_count": general_template_count,
        "available_template_count": available_template_count,
        "available_template_scope_label": (
            f'Compatibili con "{selected_category.label}"' if selected_category is not None else "Visibili nel form"
        ),
        "selected_category": selected_category,
        "alert_level": alert_level,
        "alert_message": alert_message,
        "disable_submit": not is_edit and (no_categories_available or available_template_count == 0),
        "template_list_base_url": template_list_base_url,
        "template_create_base_url": template_create_base_url,
        "template_list_url": template_list_url,
        "template_create_url": template_create_url,
        "category_admin_url": f"{reverse('assets:gestione_admin')}?tab=categorie",
    }


def _build_asset_report_snapshot(asset: Asset) -> dict[str, object]:
    extra = asset.extra_columns if isinstance(asset.extra_columns, dict) else {}
    it_details = getattr(asset, "it_details", None)
    work_machine = getattr(asset, "work_machine", None)
    category_field_values = extra.get("_category_fields") if isinstance(extra.get("_category_fields"), dict) else {}

    summary_rows = [
        ("Tag asset", _coalesce_str(asset.asset_tag, "-")),
        ("Nome", _coalesce_str(asset.name, "-")),
        ("Categoria", _coalesce_str(asset.category_label, "-")),
        ("Tipologia", _coalesce_str(asset.get_asset_type_display(), "-")),
        ("Stato", _coalesce_str(asset.get_status_display(), "-")),
        ("PART 145", "Sì" if getattr(asset, "part_145", False) else "No"),
        ("Reparto", _coalesce_str(asset.reparto, "-")),
        ("Produttore", _coalesce_str(asset.manufacturer, "-")),
        ("Modello", _coalesce_str(asset.model, "-")),
        ("Seriale", _coalesce_str(asset.serial_number, "-")),
        ("Assegnato a", _coalesce_str(asset.assignment_to, "Non assegnato")),
        ("Posizione", _coalesce_str(asset.assignment_location, "-")),
    ]

    technical_rows: list[tuple[str, str]] = []
    if isinstance(work_machine, WorkMachine):
        technical_rows.extend(
            [
                ("Anno macchina", _coalesce_str(work_machine.year, "-")),
                ("Corsa X", _format_asset_detail_value(work_machine.x_mm, AssetDetailField.FORMAT_MM)),
                ("Corsa Y", _format_asset_detail_value(work_machine.y_mm, AssetDetailField.FORMAT_MM)),
                ("Corsa Z", _format_asset_detail_value(work_machine.z_mm, AssetDetailField.FORMAT_MM)),
                ("Diametro", _format_asset_detail_value(work_machine.diameter_mm, AssetDetailField.FORMAT_MM)),
                ("Mandrino", _format_asset_detail_value(work_machine.spindle_mm, AssetDetailField.FORMAT_MM)),
                ("TMC", _coalesce_str(work_machine.tmc, "-")),
                ("TCR", _format_asset_detail_value(work_machine.tcr_enabled, AssetDetailField.FORMAT_BOOL)),
                ("Pressione", _format_asset_detail_value(work_machine.pressure_bar, AssetDetailField.FORMAT_BAR)),
                ("CNC", _format_asset_detail_value(work_machine.cnc_controlled, AssetDetailField.FORMAT_BOOL)),
                ("5 assi", _format_asset_detail_value(work_machine.five_axes, AssetDetailField.FORMAT_BOOL)),
                ("Accuracy from", _coalesce_str(work_machine.accuracy_from, "-")),
                ("Prossima manutenzione", _format_asset_detail_value(work_machine.next_maintenance_date, AssetDetailField.FORMAT_DATE)),
            ]
        )
    elif it_details is not None:
        technical_rows.extend(
            [
                ("CPU", _coalesce_str(it_details.cpu, "-")),
                ("RAM", _coalesce_str(it_details.ram, "-")),
                ("Sistema operativo", _coalesce_str(it_details.os, "-")),
                ("Disco", _coalesce_str(it_details.disco, "-")),
            ]
        )

    category_rows: list[tuple[str, str]] = []
    if asset.asset_category_id:
        for field_def in asset.asset_category.category_fields.filter(is_active=True).order_by("sort_order", "label", "id"):
            value = _coalesce_str(category_field_values.get(field_def.code), "-")
            category_rows.append((field_def.label, value))

    custom_rows: list[tuple[str, str]] = []
    for field_def in AssetCustomField.objects.filter(is_active=True).order_by("sort_order", "id"):
        value = extra.get(field_def.code, extra.get(field_def.label, ""))
        if value in ("", None, [], {}):
            continue
        custom_rows.append((field_def.label, _coalesce_str(str(value), "-")))

    workorder_rows = [
        (
            wo.opened_at.strftime("%d-%m-%Y") if wo.opened_at else "-",
            _coalesce_str(wo.get_kind_display(), "-"),
            _coalesce_str(wo.title, "-"),
            _coalesce_str(wo.get_status_display(), "-"),
        )
        for wo in asset.workorders.all().order_by("-opened_at", "-id")[:8]
    ]
    ticket_rows = [
        (
            _coalesce_str(ticket.numero_ticket, "-"),
            _coalesce_str(ticket.label_tipo, "-"),
            _coalesce_str(ticket.titolo, "-"),
            _coalesce_str(ticket.label_stato, "-"),
        )
        for ticket in asset.tickets.all().order_by("-created_at", "-id")[:8]
    ]
    document_rows = [
        (
            _coalesce_str(doc.get_category_display(), "-"),
            _coalesce_str(doc.original_name or Path(doc.file.name).name, "-"),
            doc.created_at.strftime("%d-%m-%Y") if doc.created_at else "-",
            _format_filesize(getattr(doc.file, "size", 0)),
        )
        for doc in asset.documents.all().order_by("category", "-created_at", "-id")[:12]
    ]
    periodic_rows = [
        (
            _coalesce_str(verification.name, "-"),
            _coalesce_str(
                verification.next_verification_date.strftime("%d-%m-%Y") if verification.next_verification_date else "",
                "-",
            ),
            _coalesce_str(getattr(getattr(verification, "supplier", None), "ragione_sociale", ""), "-"),
        )
        for verification in asset.periodic_verifications.all().order_by("name", "id")
    ]
    return {
        "summary_rows": summary_rows,
        "technical_rows": technical_rows,
        "category_rows": category_rows,
        "custom_rows": custom_rows,
        "workorder_rows": workorder_rows,
        "ticket_rows": ticket_rows,
        "document_rows": document_rows,
        "periodic_rows": periodic_rows,
    }


def _maintenance_schedule_redirect_from_request(request: HttpRequest) -> str:
    return _maintenance_schedule_page_url(
        asset_id=_as_int(request.POST.get("filter_asset"), default=0),
        status=_clean_string(request.POST.get("filter_status")),
        category_id=_as_int(request.POST.get("filter_category"), default=0),
        reparto=_clean_string(request.POST.get("filter_reparto")),
        coverage=_clean_string(request.POST.get("filter_coverage")),
        q=_clean_string(request.POST.get("filter_q")),
    )


def _software_license_redirect_from_request(request: HttpRequest) -> str:
    return _software_licenses_page_url(
        asset_id=_as_int(request.POST.get("filter_asset"), default=0),
        anagrafica_id=_as_int(request.POST.get("filter_anagrafica"), default=0),
        edit_id=_as_int(request.POST.get("filter_edit"), default=0),
        category=_clean_string(request.POST.get("filter_category")),
        status=_clean_string(request.POST.get("filter_status")),
        assignee=_clean_string(request.POST.get("filter_assignee")),
        q=_clean_string(request.POST.get("filter_q")),
    )


def _update_asset_category_values_after_delete(field_code: str) -> int:
    updated_count = 0
    for asset in Asset.objects.only("id", "extra_columns").iterator():
        if not isinstance(asset.extra_columns, dict):
            continue
        category_values = asset.extra_columns.get("_category_fields", {})
        if not isinstance(category_values, dict) or field_code not in category_values:
            continue
        next_extra = dict(asset.extra_columns)
        next_category_values = dict(category_values)
        next_category_values.pop(field_code, None)
        if next_category_values:
            next_extra["_category_fields"] = next_category_values
        else:
            next_extra.pop("_category_fields", None)
        asset.extra_columns = next_extra
        asset.save(update_fields=["extra_columns"])
        updated_count += 1
    return updated_count


def _build_asset_list_suggestions(
    employee_details: dict[str, dict[str, str]] | None = None,
) -> dict[str, list[str]]:
    field_keys = [key for key, _ in AssetListOption.FIELD_CHOICES]
    merged: dict[str, set[str]] = {key: set() for key in field_keys}

    option_qs = AssetListOption.objects.filter(is_active=True).order_by("field_key", "sort_order", "value")
    for option in option_qs:
        cleaned_value = _clean_string(option.value)
        if cleaned_value:
            merged.setdefault(option.field_key, set()).add(cleaned_value)

    for field_key in field_keys:
        if not hasattr(Asset, field_key):
            continue
        db_values = (
            Asset.objects.exclude(**{f"{field_key}__isnull": True})
            .exclude(**{field_key: ""})
            .values_list(field_key, flat=True)
            .distinct()[:300]
        )
        for value in db_values:
            cleaned_value = _clean_string(str(value))
            if cleaned_value:
                merged.setdefault(field_key, set()).add(cleaned_value)

    if employee_details:
        for details in employee_details.values():
            display_name = _clean_string(details.get("display_name"))
            reparto = _clean_string(details.get("reparto"))
            if display_name:
                merged.setdefault(AssetListOption.FIELD_ASSIGNMENT_TO, set()).add(display_name)
            if reparto:
                merged.setdefault(AssetListOption.FIELD_ASSIGNMENT_REPARTO, set()).add(reparto)

    normalized: dict[str, list[str]] = {}
    for key, values in merged.items():
        if values:
            normalized[key] = sorted(values, key=lambda row: row.lower())
    return normalized


def _unique_sidebar_button_code(label: str, requested_code: str | None = None) -> str:
    seed = _clean_string(requested_code) or _clean_string(label)
    base = slugify(seed)[:70]
    if not base:
        base = f"menu-{uuid4().hex[:8]}"
    candidate = base
    index = 2
    while AssetSidebarButton.objects.filter(code=candidate).exists():
        suffix = f"-{index}"
        candidate = f"{base[: max(1, 80 - len(suffix))]}{suffix}"
        index += 1
    return candidate


def _unique_detail_field_code(label: str, requested_code: str | None = None) -> str:
    seed = _clean_string(requested_code) or _clean_string(label)
    base = slugify(seed)[:70]
    if not base:
        base = f"dettaglio-{uuid4().hex[:8]}"
    candidate = base
    index = 2
    while AssetDetailField.objects.filter(code=candidate).exists():
        suffix = f"-{index}"
        candidate = f"{base[: max(1, 80 - len(suffix))]}{suffix}"
        index += 1
    return candidate


def _unique_asset_category_code(label: str, requested_code: str | None = None) -> str:
    seed = _clean_string(requested_code) or _clean_string(label)
    base = slugify(seed)[:70]
    if not base:
        base = f"categoria-{uuid4().hex[:8]}"
    candidate = base
    index = 2
    while AssetCategory.objects.filter(code=candidate).exists():
        suffix = f"-{index}"
        candidate = f"{base[: max(1, 80 - len(suffix))]}{suffix}"
        index += 1
    return candidate


def _unique_asset_category_field_code(label: str, requested_code: str | None = None) -> str:
    seed = _clean_string(requested_code) or _clean_string(label)
    base = slugify(seed)[:70]
    if not base:
        base = f"categoria-campo-{uuid4().hex[:8]}"
    candidate = base
    index = 2
    while AssetCategoryField.objects.filter(code=candidate).exists():
        suffix = f"-{index}"
        candidate = f"{base[: max(1, 80 - len(suffix))]}{suffix}"
        index += 1
    return candidate


ASSET_DETAIL_SOURCE_PRESETS: list[tuple[str, str]] = [
    ("computed:travel_xyz", "Calcolato · Corse XYZ"),
    ("computed:machine_configuration", "Calcolato · Configurazione macchina"),
    ("computed:battery_health", "Calcolato · Salute batteria"),
    ("computed:cpu_load", "Calcolato · Carico medio CPU"),
    ("computed:storage_free", "Calcolato · Spazio libero"),
    ("computed:purchase_date", "Calcolato · Data acquisto"),
    ("computed:production_date", "Calcolato · Data produzione"),
    ("computed:sync_text", "Calcolato · Ultimo sync"),
    ("asset:asset_tag", "Asset · Tag asset"),
    ("asset:name", "Asset · Nome"),
    ("asset:asset_category", "Asset · Categoria asset"),
    ("asset:asset_type", "Asset · Tipo asset"),
    ("asset:reparto", "Asset · Reparto"),
    ("asset:manufacturer", "Asset · Produttore"),
    ("asset:model", "Asset · Modello"),
    ("asset:serial_number", "Asset · Numero seriale"),
    ("asset:status", "Asset · Stato"),
    ("asset:assignment_to", "Asset · Assegnato a"),
    ("asset:assignment_reparto", "Asset · Reparto assegnazione"),
    ("asset:assignment_location", "Asset · Posizione assegnazione"),
    ("asset:updated_at", "Asset · Ultimo aggiornamento"),
    ("it:cpu", "IT · Processore"),
    ("it:ram", "IT · Memoria RAM"),
    ("it:os", "IT · Sistema operativo"),
    ("it:disco", "IT · Archiviazione"),
    ("work_machine:x_mm", "Macchina · Corsa X"),
    ("work_machine:y_mm", "Macchina · Corsa Y"),
    ("work_machine:z_mm", "Macchina · Corsa Z"),
    ("work_machine:diameter_mm", "Macchina · Diametro"),
    ("work_machine:spindle_mm", "Macchina · Mandrino"),
    ("work_machine:year", "Macchina · Anno"),
    ("work_machine:tmc", "Macchina · TMC"),
    ("work_machine:tcr_enabled", "Macchina · TCR"),
    ("work_machine:pressure_bar", "Macchina · Pressione"),
    ("work_machine:cnc_controlled", "Macchina · CNC"),
    ("work_machine:five_axes", "Macchina · 5 assi"),
    ("work_machine:accuracy_from", "Macchina · Accuracy from"),
    ("work_machine:next_maintenance_date", "Macchina · Prossima manutenzione"),
    ("work_machine:maintenance_reminder_days", "Macchina · Soglia reminder"),
    ("extra:graphics", "Extra · Grafica"),
    ("extra:display", "Extra · Schermo"),
    ("extra:po_ref", "Extra · Riferimento ordine"),
    ("extra:owner_dept", "Extra · Reparto owner"),
    ("extra:purchase_date", "Extra · Data acquisto"),
]


def _asset_detail_source_choices() -> list[tuple[str, str]]:
    choices = list(ASSET_DETAIL_SOURCE_PRESETS)
    for field in AssetCustomField.objects.order_by("sort_order", "label", "id"):
        choices.append((f"custom:{field.code}", f"Campo custom · {field.label}"))
    for field in AssetCategoryField.objects.select_related("category").order_by(
        "category__sort_order",
        "category__label",
        "sort_order",
        "label",
        "id",
    ):
        choices.append((f"category:{field.code}", f"Campo categoria · {field.category.label} · {field.label}"))
    return choices


def _asset_detail_source_refs() -> set[str]:
    return {value for value, _label in _asset_detail_source_choices()}


def _default_asset_detail_field_seed_rows() -> list[dict[str, object]]:
    return [
        {
            "label": "Corse XYZ",
            "section": AssetDetailField.SECTION_METRICS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "computed:travel_xyz",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 10,
        },
        {
            "label": "Anno macchina",
            "section": AssetDetailField.SECTION_METRICS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:year",
            "value_format": AssetDetailField.FORMAT_AUTO,
            "sort_order": 20,
        },
        {
            "label": "Configurazione",
            "section": AssetDetailField.SECTION_METRICS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "computed:machine_configuration",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 30,
        },
        {
            "label": "Salute batteria",
            "section": AssetDetailField.SECTION_METRICS,
            "asset_scope": AssetDetailField.SCOPE_STANDARD,
            "source_ref": "computed:battery_health",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 10,
        },
        {
            "label": "Carico medio CPU",
            "section": AssetDetailField.SECTION_METRICS,
            "asset_scope": AssetDetailField.SCOPE_STANDARD,
            "source_ref": "computed:cpu_load",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 20,
        },
        {
            "label": "Spazio libero",
            "section": AssetDetailField.SECTION_METRICS,
            "asset_scope": AssetDetailField.SCOPE_STANDARD,
            "source_ref": "computed:storage_free",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 30,
        },
        {
            "label": "Produttore",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "asset:manufacturer",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 10,
        },
        {
            "label": "Modello",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "asset:model",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 20,
        },
        {
            "label": "Numero seriale",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "asset:serial_number",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 30,
        },
        {
            "label": "Reparto",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "asset:reparto",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 40,
        },
        {
            "label": "Corsa X",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:x_mm",
            "value_format": AssetDetailField.FORMAT_MM,
            "sort_order": 50,
        },
        {
            "label": "Corsa Y",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:y_mm",
            "value_format": AssetDetailField.FORMAT_MM,
            "sort_order": 60,
        },
        {
            "label": "Corsa Z",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:z_mm",
            "value_format": AssetDetailField.FORMAT_MM,
            "sort_order": 70,
        },
        {
            "label": "Diametro",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:diameter_mm",
            "value_format": AssetDetailField.FORMAT_MM,
            "sort_order": 80,
        },
        {
            "label": "Mandrino",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:spindle_mm",
            "value_format": AssetDetailField.FORMAT_MM,
            "sort_order": 90,
        },
        {
            "label": "Anno",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:year",
            "value_format": AssetDetailField.FORMAT_AUTO,
            "sort_order": 100,
        },
        {
            "label": "TMC",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:tmc",
            "value_format": AssetDetailField.FORMAT_AUTO,
            "sort_order": 110,
        },
        {
            "label": "TCR",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:tcr_enabled",
            "value_format": AssetDetailField.FORMAT_BOOL,
            "sort_order": 120,
        },
        {
            "label": "Pressione",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:pressure_bar",
            "value_format": AssetDetailField.FORMAT_BAR,
            "sort_order": 130,
        },
        {
            "label": "CNC",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:cnc_controlled",
            "value_format": AssetDetailField.FORMAT_BOOL,
            "sort_order": 140,
        },
        {
            "label": "5 assi",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:five_axes",
            "value_format": AssetDetailField.FORMAT_BOOL,
            "sort_order": 150,
        },
        {
            "label": "Accuracy from",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:accuracy_from",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 160,
        },
        {
            "label": "Prossima manutenzione",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:next_maintenance_date",
            "value_format": AssetDetailField.FORMAT_DATE,
            "sort_order": 170,
        },
        {
            "label": "Soglia reminder",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:maintenance_reminder_days",
            "value_format": AssetDetailField.FORMAT_AUTO,
            "sort_order": 180,
        },
        {
            "label": "Processore",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_STANDARD,
            "source_ref": "it:cpu",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 10,
        },
        {
            "label": "Numero seriale",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_STANDARD,
            "source_ref": "asset:serial_number",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 20,
        },
        {
            "label": "Memoria",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_STANDARD,
            "source_ref": "it:ram",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 30,
        },
        {
            "label": "Sistema operativo",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_STANDARD,
            "source_ref": "it:os",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 40,
        },
        {
            "label": "Archiviazione",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_STANDARD,
            "source_ref": "it:disco",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 50,
        },
        {
            "label": "Grafica",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_STANDARD,
            "source_ref": "extra:graphics",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 60,
        },
        {
            "label": "Schermo",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_STANDARD,
            "source_ref": "extra:display",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 70,
        },
        {
            "label": "Data acquisto",
            "section": AssetDetailField.SECTION_SPECS,
            "asset_scope": AssetDetailField.SCOPE_STANDARD,
            "source_ref": "computed:purchase_date",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 80,
        },
        {
            "label": "Tag asset",
            "section": AssetDetailField.SECTION_PROFILE,
            "asset_scope": AssetDetailField.SCOPE_ALL,
            "source_ref": "asset:asset_tag",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 10,
        },
        {
            "label": "Reparto",
            "section": AssetDetailField.SECTION_PROFILE,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "asset:reparto",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 20,
        },
        {
            "label": "TCR",
            "section": AssetDetailField.SECTION_PROFILE,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:tcr_enabled",
            "value_format": AssetDetailField.FORMAT_BOOL,
            "sort_order": 30,
        },
        {
            "label": "CNC",
            "section": AssetDetailField.SECTION_PROFILE,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:cnc_controlled",
            "value_format": AssetDetailField.FORMAT_BOOL,
            "sort_order": 40,
        },
        {
            "label": "5 assi",
            "section": AssetDetailField.SECTION_PROFILE,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:five_axes",
            "value_format": AssetDetailField.FORMAT_BOOL,
            "sort_order": 50,
        },
        {
            "label": "Prossima manutenzione",
            "section": AssetDetailField.SECTION_PROFILE,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:next_maintenance_date",
            "value_format": AssetDetailField.FORMAT_DATE,
            "sort_order": 60,
        },
        {
            "label": "Soglia reminder",
            "section": AssetDetailField.SECTION_PROFILE,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:maintenance_reminder_days",
            "value_format": AssetDetailField.FORMAT_AUTO,
            "sort_order": 70,
        },
        {
            "label": "Accuracy from",
            "section": AssetDetailField.SECTION_PROFILE,
            "asset_scope": AssetDetailField.SCOPE_WORK_MACHINE,
            "source_ref": "work_machine:accuracy_from",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 80,
        },
        {
            "label": "Produttore",
            "section": AssetDetailField.SECTION_PROFILE,
            "asset_scope": AssetDetailField.SCOPE_STANDARD,
            "source_ref": "asset:manufacturer",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 20,
        },
        {
            "label": "Modello",
            "section": AssetDetailField.SECTION_PROFILE,
            "asset_scope": AssetDetailField.SCOPE_STANDARD,
            "source_ref": "asset:model",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 30,
        },
        {
            "label": "Ultimo sync",
            "section": AssetDetailField.SECTION_PROFILE,
            "asset_scope": AssetDetailField.SCOPE_STANDARD,
            "source_ref": "computed:sync_text",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 40,
        },
        {
            "label": "Reparto",
            "section": AssetDetailField.SECTION_ASSIGNMENT,
            "asset_scope": AssetDetailField.SCOPE_ALL,
            "source_ref": "asset:assignment_reparto",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 10,
        },
        {
            "label": "Posizione",
            "section": AssetDetailField.SECTION_ASSIGNMENT,
            "asset_scope": AssetDetailField.SCOPE_ALL,
            "source_ref": "asset:assignment_location",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 20,
        },
        {
            "label": "Assegnato a",
            "section": AssetDetailField.SECTION_ASSIGNMENT,
            "asset_scope": AssetDetailField.SCOPE_ALL,
            "source_ref": "asset:assignment_to",
            "value_format": AssetDetailField.FORMAT_TEXT,
            "sort_order": 30,
        },
        {
            "label": "Ultimo aggiornamento",
            "section": AssetDetailField.SECTION_ASSIGNMENT,
            "asset_scope": AssetDetailField.SCOPE_ALL,
            "source_ref": "asset:updated_at",
            "value_format": AssetDetailField.FORMAT_DATE,
            "sort_order": 40,
        },
    ]


def _seed_default_asset_detail_fields(*, create_only_if_empty: bool = True) -> int:
    if create_only_if_empty and AssetDetailField.objects.exists():
        return 0
    created = 0
    for row in _default_asset_detail_field_seed_rows():
        label = _clean_string(row.get("label"))
        code_seed = row.get("code") or f"{row.get('section')}-{row.get('asset_scope')}-{row.get('source_ref')}"
        defaults = {
            "section": row["section"],
            "asset_scope": row["asset_scope"],
            "source_ref": row["source_ref"],
            "value_format": row["value_format"],
            "sort_order": row["sort_order"],
            "show_if_empty": bool(row.get("show_if_empty", True)),
            "is_active": bool(row.get("is_active", True)),
        }
        code = _unique_detail_field_code(label, code_seed)
        _obj, created_flag = AssetDetailField.objects.get_or_create(
            code=code,
            defaults={"label": label[:120], **defaults},
        )
        if created_flag:
            created += 1
    return created


def _default_asset_detail_section_layout_rows() -> list[dict[str, object]]:
    return [
        {
            "code": AssetDetailSectionLayout.SECTION_SPECS,
            "grid_size": AssetDetailSectionLayout.SIZE_WIDE,
            "sort_order": 100,
            "is_visible": True,
        },
        {
            "code": AssetDetailSectionLayout.SECTION_TIMELINE,
            "grid_size": AssetDetailSectionLayout.SIZE_WIDE,
            "sort_order": 110,
            "is_visible": True,
        },
        {
            "code": AssetDetailSectionLayout.SECTION_MAINTENANCE,
            "grid_size": AssetDetailSectionLayout.SIZE_FULL,
            "sort_order": 120,
            "is_visible": True,
        },
        {
            "code": AssetDetailSectionLayout.SECTION_TICKETS,
            "grid_size": AssetDetailSectionLayout.SIZE_WIDE,
            "sort_order": 130,
            "is_visible": True,
        },
        {
            "code": AssetDetailSectionLayout.SECTION_PROFILE,
            "grid_size": AssetDetailSectionLayout.SIZE_HALF,
            "sort_order": 200,
            "is_visible": True,
        },
        {
            "code": AssetDetailSectionLayout.SECTION_ASSIGNMENT,
            "grid_size": AssetDetailSectionLayout.SIZE_HALF,
            "sort_order": 210,
            "is_visible": True,
        },
        {
            "code": AssetDetailSectionLayout.SECTION_LICENSES,
            "grid_size": AssetDetailSectionLayout.SIZE_HALF,
            "sort_order": 215,
            "is_visible": True,
        },
        {
            "code": AssetDetailSectionLayout.SECTION_PERIODIC,
            "grid_size": AssetDetailSectionLayout.SIZE_HALF,
            "sort_order": 220,
            "is_visible": True,
        },
        {
            "code": AssetDetailSectionLayout.SECTION_DOCUMENTS,
            "grid_size": AssetDetailSectionLayout.SIZE_WIDE,
            "sort_order": 230,
            "is_visible": True,
        },
        {
            "code": AssetDetailSectionLayout.SECTION_QR,
            "grid_size": AssetDetailSectionLayout.SIZE_THIRD,
            "sort_order": 280,
            "is_visible": True,
        },
        {
            "code": AssetDetailSectionLayout.SECTION_QUICK_ACTIONS,
            "grid_size": AssetDetailSectionLayout.SIZE_HALF,
            "sort_order": 250,
            "is_visible": True,
        },
        {
            "code": AssetDetailSectionLayout.SECTION_MAP,
            "grid_size": AssetDetailSectionLayout.SIZE_HALF,
            "sort_order": 270,
            "is_visible": True,
        },
    ]


def _ensure_default_asset_detail_section_layouts() -> list[AssetDetailSectionLayout]:
    rows = _default_asset_detail_section_layout_rows()
    existing = {
        row.code: row
        for row in AssetDetailSectionLayout.objects.all()
    }
    for item in rows:
        code = str(item["code"])
        if code in existing:
            continue
        existing[code] = AssetDetailSectionLayout.objects.create(
            code=code,
            grid_size=str(item["grid_size"]),
            sort_order=int(item["sort_order"]),
            is_visible=bool(item["is_visible"]),
        )
    return list(AssetDetailSectionLayout.objects.order_by("sort_order", "id"))


def _resolve_asset_detail_source_value(
    *,
    source_ref: str,
    asset: Asset,
    it_details: AssetITDetails | None,
    work_machine: WorkMachine | None,
    extra: dict[str, object],
    custom_fields_by_code: dict[str, AssetCustomField],
    sync_text: str,
) -> object:
    source_kind, _, source_key = _clean_string(source_ref).partition(":")
    source_kind = source_kind.lower()
    source_key = _clean_string(source_key)
    category_values = extra.get("_category_fields", {}) if isinstance(extra.get("_category_fields"), dict) else {}
    if not source_kind or not source_key:
        return ""

    if source_kind == "asset":
        if source_key == "asset_category":
            return asset.category_label
        value = getattr(asset, source_key, "")
        if source_key == "asset_type" and value:
            return asset.get_asset_type_display()
        if source_key == "status" and value:
            return asset.get_status_display()
        return value
    if source_kind == "it":
        return getattr(it_details, source_key, "") if it_details is not None else ""
    if source_kind == "work_machine":
        return getattr(work_machine, source_key, "") if isinstance(work_machine, WorkMachine) else ""
    if source_kind == "extra":
        return extra.get(source_key, "")
    if source_kind == "custom":
        field = custom_fields_by_code.get(source_key)
        if field and field.label and field.label in extra:
            return extra.get(source_key, extra.get(field.label, ""))
        return extra.get(source_key, "")
    if source_kind == "category":
        return category_values.get(source_key, "")
    if source_kind != "computed":
        return ""

    if source_key == "travel_xyz":
        if not isinstance(work_machine, WorkMachine):
            return ""
        travel_parts = [str(value) for value in [work_machine.x_mm, work_machine.y_mm, work_machine.z_mm] if value is not None]
        return " x ".join(travel_parts) + " mm" if travel_parts else ""
    if source_key == "machine_configuration":
        if not isinstance(work_machine, WorkMachine):
            return ""
        machine_flags: list[str] = []
        if work_machine.tcr_enabled:
            machine_flags.append("TCR")
        if work_machine.cnc_controlled:
            machine_flags.append("CNC")
        if work_machine.five_axes:
            machine_flags.append("5 assi")
        return ", ".join(machine_flags) if machine_flags else "Standard"
    if source_key == "battery_health":
        return _coalesce_str(extra.get("battery_health"), extra.get("batteria"), "")
    if source_key == "cpu_load":
        return _coalesce_str(extra.get("avg_cpu_load"), extra.get("cpu_load"), "")
    if source_key == "storage_free":
        from ..services.it_presentation import it_profile
        capacity_fallback = "" if it_profile(asset) else getattr(it_details, "disco", "")
        return _coalesce_str(extra.get("storage_free"), extra.get("free_storage"), capacity_fallback, "")
    if source_key == "purchase_date":
        from ..services.it_presentation import it_profile
        return _coalesce_str(
            asset.purchase_date.strftime("%d-%m-%Y") if asset.purchase_date else "",
            extra.get("purchase_date"),
            asset.created_at.strftime("%d-%m-%Y") if asset.created_at and not it_profile(asset) else "",
            "",
        )
    if source_key == "production_date":
        return _coalesce_str(
            asset.production_date.strftime("%d-%m-%Y") if asset.production_date else "",
            extra.get("production_date"),
            "",
        )
    if source_key == "sync_text":
        return sync_text
    return ""


def _format_asset_detail_value(value, value_format: str) -> str:
    if value_format == AssetDetailField.FORMAT_BOOL:
        if value in (None, ""):
            return "N/D"
        return "Si" if bool(value) else "No"
    if value_format == AssetDetailField.FORMAT_DATE:
        if isinstance(value, datetime):
            return timezone.localtime(value).strftime("%d-%m-%Y")
        if isinstance(value, date):
            return value.strftime("%d-%m-%Y")
        cleaned = _clean_string(value)
        return cleaned or "N/D"
    if value_format == AssetDetailField.FORMAT_MM:
        if value in (None, ""):
            return "N/D"
        return f"{value} mm"
    if value_format == AssetDetailField.FORMAT_BAR:
        if value in (None, ""):
            return "N/D"
        return f"{value} bar"

    if isinstance(value, bool):
        return "Si" if value else "No"
    if isinstance(value, datetime):
        return timezone.localtime(value).strftime("%d-%m-%Y")
    if isinstance(value, date):
        return value.strftime("%d-%m-%Y")
    cleaned = _clean_string(str(value) if value not in (None, "") else "")
    return cleaned or "N/D"


def _resolve_sidebar_url(raw_url: str, rows: int = 25) -> str:
    target = _clean_string(raw_url).replace("{rows}", str(rows))
    if not target:
        return reverse("assets:asset_list")
    if target.startswith("django:"):
        route_expr = target.split("django:", 1)[1]
        route_name, _, query = route_expr.partition("?")
        try:
            base_url = reverse(route_name)
            return f"{base_url}?{query}" if query else base_url
        except NoReverseMatch:
            return "#"
    return target


def _is_sidebar_button_active(request: HttpRequest, button: AssetSidebarButton, resolved_url: str) -> bool:
    # Le voci della Manutenzione si accendono per nome di rotta, dalla stessa
    # definizione della barra di sezione: un pezzo di URL non basta, perche'
    # Configurazione e Manutenzione condividono il prefisso /assets/manutenzione/.
    from ..maintenance_nav import sidebar_code_routes

    nav_routes = sidebar_code_routes().get(_clean_string(button.code))
    if nav_routes is not None:
        current_route = getattr(getattr(request, "resolver_match", None), "url_name", "") or ""
        return current_route in nav_routes

    active_match = _clean_string(button.active_match)
    full_path = request.get_full_path()
    if active_match:
        if "=" in active_match and not active_match.startswith("/"):
            active_qs = parse_qs(active_match.lstrip("?"), keep_blank_values=True)
            if active_qs:
                return all(request.GET.get(key, "") in values for key, values in active_qs.items())
        return active_match in full_path

    parsed = urlsplit(resolved_url)
    if parsed.path and parsed.path != request.path:
        return False

    target_qs = parse_qs(parsed.query, keep_blank_values=True)
    if not target_qs:
        return parsed.path == request.path

    # Per la lista asset evitiamo che "Dashboard" risulti attivo insieme ai filtri tipo.
    try:
        asset_list_path = reverse("assets:asset_list")
    except NoReverseMatch:
        asset_list_path = "/assets/"
    if parsed.path == asset_list_path and "asset_type" not in target_qs and _clean_string(request.GET.get("asset_type")):
        return False
    if parsed.path == asset_list_path and "asset_category" not in target_qs and _clean_string(request.GET.get("asset_category")):
        return False
    # "Asset produzione" (?group=production) e' una lista a se': un target
    # asset_list senza group non deve risultare attivo quando il gruppo e' attivo.
    if parsed.path == asset_list_path and "group" not in target_qs and _clean_string(request.GET.get("group")):
        return False

    for key, values in target_qs.items():
        current_value = request.GET.get(key, "")
        if current_value not in values:
            return False
    return True


def _normalize_reports_scope(value: str | None) -> str:
    normalized = _clean_string(value).casefold()
    if normalized in {"it", "device", "devices", "dispositivi", "dispositivi_it"}:
        return "it"
    return "production"


def _default_sidebar_buttons(request: HttpRequest, rows: int = 25) -> list[dict]:
    base_list = reverse("assets:asset_list")
    asset_dashboard = reverse("assets:asset_dashboard")
    asset_components = reverse("assets:asset_component_list")
    asset_deadlines = reverse("assets:asset_administrative_deadline_list")
    maintenance_hub = reverse("assets:maintenance_hub")
    maintenance_templates = reverse("assets:maintenance_template_list")
    maintenance_rules = reverse("assets:maintenance_rule_list")
    maintenance_schedule = reverse("assets:maintenance_schedule")
    assistance_contracts = reverse("assets:assistance_contract_list")
    software_licenses = reverse("assets:software_license_list")
    production_assets_url = f"{reverse('assets:asset_list')}?group=production"
    work_machine_dashboard = reverse("assets:work_machine_dashboard")
    it_periodic_verifications = f"{reverse('assets:periodic_verifications')}?scope=it"
    production_periodic_verifications = f"{reverse('assets:periodic_verifications')}?scope=production"
    plant_layout_map = reverse("assets:plant_layout_map")
    reports = reverse("assets:reports")
    it_reports = f"{reports}?scope=it"
    production_reports = f"{reports}?scope=production"
    wo_list = reverse("assets:wo_list")
    asset_quick_report = reverse("assets:asset_quick_report")
    maintenance_todo = reverse("assets:maintenance_todo")
    maintenance_da_fare = reverse("assets:maintenance_da_fare")
    maintenance_scadenze = reverse("assets:maintenance_scadenze")
    maintenance_quadro = reverse("assets:maintenance_responsabile")
    maintenance_plans = reverse("assets:maintenance_plan_list")
    asset_groups = reverse("assets:asset_group_list")
    il_mio_turno_url = f"{maintenance_da_fare}?mio=1"
    current_type = _clean_string(request.GET.get("asset_type"))
    current_group = _clean_string(request.GET.get("group")).lower()
    current_route = getattr(getattr(request, "resolver_match", None), "url_name", "")
    current_report_scope = _normalize_reports_scope(request.GET.get("scope")) if current_route == "reports" else ""
    current_periodic_scope = _normalize_reports_scope(request.GET.get("scope")) if current_route == "periodic_verifications" else ""
    return [
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Dashboard",
            "url": asset_dashboard,
            "is_subitem": False,
            "active": current_route == "asset_dashboard",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Il mio lavoro",
            "url": il_mio_turno_url,
            "is_subitem": False,
            "active": current_route == "maintenance_da_fare" and request.GET.get("mio") == "1",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Inventario completo",
            "url": f"{base_list}?rows={rows}",
            "is_subitem": False,
            "active": not current_type and current_route == "asset_list",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Inventario IT",
            "url": reverse("assets:device_list"),
            "is_subitem": False,
            "active": current_route == "device_list" or current_type in {
                Asset.TYPE_PC, Asset.TYPE_NOTEBOOK, Asset.TYPE_SERVER, Asset.TYPE_VM,
                Asset.TYPE_FIREWALL, Asset.TYPE_STAMPANTE, Asset.TYPE_HW,
            },
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Server",
            "url": f"{base_list}?asset_type={Asset.TYPE_SERVER}&rows={rows}",
            "is_subitem": True,
            "active": current_type == Asset.TYPE_SERVER and current_route == "asset_list",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "PC e portatili",
            "url": f"{base_list}?asset_type={Asset.TYPE_PC}&rows={rows}",
            "is_subitem": True,
            "active": current_type in {Asset.TYPE_PC, Asset.TYPE_NOTEBOOK} and current_route == "asset_list",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Macchine virtuali",
            "url": f"{base_list}?asset_type={Asset.TYPE_VM}&rows={rows}",
            "is_subitem": True,
            "active": current_type == Asset.TYPE_VM and current_route == "asset_list",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Rete",
            "url": f"{base_list}?asset_type={Asset.TYPE_FIREWALL}&rows={rows}",
            "is_subitem": True,
            "active": current_type == Asset.TYPE_FIREWALL and current_route == "asset_list",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Stampanti",
            "url": f"{base_list}?asset_type={Asset.TYPE_STAMPANTE}&rows={rows}",
            "is_subitem": True,
            "active": current_type == Asset.TYPE_STAMPANTE and current_route == "asset_list",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Altri dispositivi",
            "url": f"{base_list}?asset_type={Asset.TYPE_HW}&rows={rows}",
            "is_subitem": True,
            "active": current_type == Asset.TYPE_HW and current_route == "asset_list",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Scadenze amministrative",
            "url": asset_deadlines,
            "is_subitem": False,
            "active": current_route in {"asset_administrative_deadline_list", "asset_administrative_deadline_create", "asset_administrative_deadline_edit"},
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Componenti",
            "url": asset_components,
            "is_subitem": False,
            "active": current_route in {"asset_component_list", "asset_component_list_for_asset", "asset_component_create", "asset_component_edit"},
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Manutenzione",
            "url": maintenance_hub,
            "is_subitem": False,
            "active": current_route in {
                "maintenance_hub",
                "maintenance_template_list", "maintenance_template_create", "maintenance_template_edit",
                "maintenance_rule_list", "maintenance_rule_create", "maintenance_rule_edit",
                "maintenance_schedule", "maintenance_todo", "maintenance_history",
                "wo_list", "wo_view", "wo_create", "wo_close",
                "assistance_contract_list",
                # Superfici del nuovo dominio: senza queste il ramo "Manutenzione"
                # si chiudeva proprio mentre ci si stava lavorando dentro.
                "maintenance_da_fare", "maintenance_scadenze", "maintenance_responsabile",
                "maintenance_plan_list", "maintenance_plan_detail", "maintenance_plan_create",
                "maintenance_plan_edit", "maintenance_assignment_create", "maintenance_assignment_edit",
                "maintenance_coverage", "maintenance_history_import",
                "asset_group_list", "asset_group_create", "asset_group_edit",
                "occurrence_complete", "occurrence_followup_create",
            },
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Da fare",
            "url": maintenance_da_fare,
            "is_subitem": True,
            # Le rotte ritirate rimandano qui: la voce resta accesa anche per chi
            # arriva da un vecchio segnalibro, altrimenti atterrerebbe su una pagina
            # senza nessuna voce di menu evidenziata.
            "active": current_route in {"maintenance_da_fare", "maintenance_todo"},
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Scadenze",
            "url": maintenance_scadenze,
            "is_subitem": True,
            "active": current_route in {
                "maintenance_scadenze", "maintenance_schedule", "maintenance_scadenzario",
                "occurrence_complete", "occurrence_followup_create",
            },
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Cruscotto",
            "url": maintenance_quadro,
            "is_subitem": True,
            "active": current_route == "maintenance_responsabile",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Piani",
            "url": maintenance_plans,
            "is_subitem": True,
            "active": current_route in {
                "maintenance_plan_list", "maintenance_plan_detail", "maintenance_plan_create",
                "maintenance_plan_edit", "maintenance_assignment_create", "maintenance_assignment_edit",
                "maintenance_coverage", "maintenance_history_import",
                "maintenance_rule_list", "maintenance_rule_create", "maintenance_rule_edit",
                "maintenance_coverage_matrix",
            },
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Gruppi asset",
            "url": asset_groups,
            "is_subitem": True,
            "active": current_route in {"asset_group_list", "asset_group_create", "asset_group_edit"},
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Catalogo attivita",
            "url": maintenance_templates,
            "is_subitem": True,
            "active": current_route in {"maintenance_template_list", "maintenance_template_create", "maintenance_template_edit"},
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Archivio piani IT",
            "url": it_periodic_verifications,
            "is_subitem": True,
            "active": current_route == "periodic_verifications" and current_periodic_scope == "it",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Report dispositivi IT",
            "url": it_reports,
            "is_subitem": True,
            "active": current_route == "reports" and current_report_scope == "it",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Officina",
            "url": production_assets_url,
            "is_subitem": False,
            "active": (current_route == "asset_list" and current_group == "production")
            or current_route in {"work_machine_list", "work_machine_create", "work_machine_edit"},
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Dashboard officina",
            "url": work_machine_dashboard,
            "is_subitem": True,
            "active": current_route == "work_machine_dashboard",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Mappa officina",
            "url": plant_layout_map,
            "is_subitem": True,
            "active": current_route in {"plant_layout_map", "plant_layout_editor"},
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Archivio piani produzione",
            "url": production_periodic_verifications,
            "is_subitem": True,
            "active": current_route == "periodic_verifications" and current_periodic_scope == "production",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Report asset produzione",
            "url": production_reports,
            "is_subitem": True,
            "active": current_route == "reports" and current_report_scope == "production",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Interventi",
            "url": wo_list,
            "is_subitem": True,
            "active": current_route in {"wo_list", "wo_view", "wo_create", "wo_close"},
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Segnala un problema",
            "url": asset_quick_report,
            "is_subitem": True,
            "active": current_route == "asset_quick_report",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Licenze software",
            "url": software_licenses,
            "is_subitem": False,
            "active": current_route == "software_license_list",
        },
        {
            "section": AssetSidebarButton.SECTION_OPERATIONS,
            "label": "Prossime manutenzioni",
            "url": maintenance_schedule,
            "is_subitem": False,
            "active": current_route == "maintenance_schedule",
        },
        {
            "section": AssetSidebarButton.SECTION_OPERATIONS,
            "label": "Contratti assistenza",
            "url": assistance_contracts,
            "is_subitem": False,
            "active": current_route == "assistance_contract_list",
        },
        {
            "section": AssetSidebarButton.SECTION_ANALYTICS,
            "label": "Scadenzario operativo",
            "url": maintenance_schedule,
            "is_subitem": False,
            "active": current_route == "maintenance_schedule",
        },
    ]


def _default_sidebar_seed_rows() -> list[dict]:
    return [
        {
            "code": "dashboard",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Inventario completo",
            "target_url": "django:assets:asset_list?rows={rows}",
            "active_match": "",
            "is_subitem": False,
            "parent_code": "",
            "sort_order": 10,
            "is_visible": True,
        },
        {
            "code": "hardware",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Inventario IT",
            "target_url": "django:assets:device_list",
            "active_match": "/assets/dispositivi/",
            "is_subitem": False,
            "parent_code": "",
            "sort_order": 20,
            "is_visible": True,
        },
        {
            "code": "servers",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Server",
            "target_url": "django:assets:asset_list?asset_type=SERVER&rows={rows}",
            "active_match": "asset_type=SERVER",
            "is_subitem": True,
            "parent_code": "hardware",
            "sort_order": 30,
            "is_visible": True,
        },
        {
            "code": "workstations",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "PC e portatili",
            "target_url": "django:assets:asset_list?asset_type=PC&rows={rows}",
            "active_match": "asset_type=PC",
            "is_subitem": True,
            "parent_code": "hardware",
            "sort_order": 40,
            "is_visible": True,
        },
        {
            "code": "virtual_machines",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Macchine virtuali",
            "target_url": "django:assets:asset_list?asset_type=VM&rows={rows}",
            "active_match": "asset_type=VM",
            "is_subitem": True,
            "parent_code": "hardware",
            "sort_order": 45,
            "is_visible": True,
        },
        {
            "code": "networking",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Rete",
            "target_url": "django:assets:asset_list?asset_type=FIREWALL&rows={rows}",
            "active_match": "asset_type=FIREWALL",
            "is_subitem": True,
            "parent_code": "hardware",
            "sort_order": 50,
            "is_visible": True,
        },
        {
            "code": "printers",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Stampanti",
            "target_url": "django:assets:asset_list?asset_type=STAMPANTE&rows={rows}",
            "active_match": "asset_type=STAMPANTE",
            "is_subitem": True,
            "parent_code": "hardware",
            "sort_order": 55,
            "is_visible": True,
        },
        {
            "code": "hardware_devices",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Altri dispositivi",
            "target_url": "django:assets:asset_list?asset_type=HW&rows={rows}",
            "active_match": "asset_type=HW",
            "is_subitem": True,
            "parent_code": "hardware",
            "sort_order": 60,
            "is_visible": True,
        },
        {
            "code": "work_machines",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Officina",
            # Confluita nell'inventario unico: stessa pagina/lista, filtrata al
            # gruppo produzione (?group=production).
            "target_url": "django:assets:asset_list?group=production&rows={rows}",
            "active_match": "group=production",
            "is_subitem": False,
            "parent_code": "",
            "sort_order": 60,
            "is_visible": True,
        },
        {
            "code": "work_machines_dashboard",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Dashboard officina",
            "target_url": "django:assets:work_machine_dashboard",
            "active_match": "/assets/work-machines/dashboard/",
            "is_subitem": True,
            "parent_code": "work_machines",
            "sort_order": 60,
            "is_visible": True,
        },
        {
            "code": "periodic_verifications",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Manutenzione periodica produzione",
            "target_url": "django:assets:periodic_verifications?scope=production",
            "active_match": "",
            "is_subitem": True,
            "parent_code": "manutenzione_hub",
            "sort_order": 80,
            "is_visible": True,
        },
        {
            "code": "asset_deadlines",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Scadenze amministrative",
            "target_url": "django:assets:asset_administrative_deadline_list",
            "active_match": "/assets/scadenze/",
            "is_subitem": False,
            "parent_code": "",
            "sort_order": 52,
            "is_visible": True,
        },
        {
            "code": "asset_components",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Componenti",
            "target_url": "django:assets:asset_component_list",
            "active_match": "/componenti/",
            "is_subitem": False,
            "parent_code": "",
            "sort_order": 53,
            "is_visible": True,
        },
        {
            "code": "manutenzione_hub",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Manutenzione",
            "target_url": "django:assets:maintenance_hub",
            "active_match": "/assets/manutenzione/",
            "is_subitem": False,
            "parent_code": "",
            "sort_order": 54,
            "is_visible": True,
        },
        {
            "code": "manutenzione_config",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Configurazione",
            "target_url": "django:assets:maintenance_template_list",
            "active_match": "",
            "is_subitem": False,
            "parent_code": "",
            "sort_order": 55,
            "is_visible": True,
        },
        {
            "code": "maintenance_copertura",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Copertura",
            "target_url": "django:assets:maintenance_coverage",
            "active_match": "/assets/manutenzione/copertura/",
            "is_subitem": True,
            "parent_code": "manutenzione_config",
            "sort_order": 40,
            "is_visible": True,
        },
        {
            "code": "maintenance_templates",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Catalogo attivita",
            "target_url": "django:assets:maintenance_template_list",
            "active_match": "/assets/manutenzione/templates/",
            "is_subitem": True,
            "parent_code": "manutenzione_hub",
            "sort_order": 120,
            "is_visible": False,
        },
        {
            "code": "maintenance_da_fare",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Da fare",
            "target_url": "django:assets:maintenance_da_fare",
            "active_match": "/assets/manutenzione/da-fare/",
            "is_subitem": True,
            "parent_code": "manutenzione_hub",
            "sort_order": 10,
            "is_visible": True,
        },
        {
            "code": "maintenance_scadenzario",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Scadenze",
            "target_url": "django:assets:maintenance_scadenze",
            "active_match": "/assets/manutenzione/scadenze/",
            "is_subitem": True,
            "parent_code": "manutenzione_hub",
            "sort_order": 20,
            "is_visible": True,
        },
        {
            "code": "maintenance_quadro",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Cruscotto",
            "target_url": "django:assets:maintenance_responsabile",
            "active_match": "/assets/manutenzione/quadro/",
            "is_subitem": True,
            "parent_code": "manutenzione_hub",
            "sort_order": 50,
            "is_visible": True,
        },
        {
            "code": "maintenance_interventi",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Interventi",
            "target_url": "django:assets:wo_list",
            "active_match": "/assets/workorders/",
            "is_subitem": True,
            "parent_code": "manutenzione_hub",
            "sort_order": 30,
            "is_visible": True,
        },
        {
            "code": "maintenance_piani",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Piani",
            "target_url": "django:assets:maintenance_plan_list",
            "active_match": "/assets/manutenzione/piani/",
            "is_subitem": True,
            "parent_code": "manutenzione_hub",
            "sort_order": 40,
            "is_visible": True,
        },
        {
            "code": "maintenance_asset_groups",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Gruppi asset",
            "target_url": "django:assets:asset_group_list",
            "active_match": "/assets/manutenzione/gruppi/",
            "is_subitem": True,
            "parent_code": "manutenzione_config",
            "sort_order": 20,
            "is_visible": True,
        },
        {
            "code": "maintenance_storico",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Storico",
            "target_url": "django:assets:maintenance_history",
            "active_match": "/assets/manutenzione/storico/",
            "is_subitem": True,
            "parent_code": "manutenzione_hub",
            "sort_order": 60,
            "is_visible": True,
        },
        {
            "code": "maintenance_fornitori",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Fornitori",
            "target_url": "django:assets:maintenance_suppliers",
            "active_match": "/assets/manutenzione/fornitori/",
            "is_subitem": True,
            "parent_code": "manutenzione_config",
            "sort_order": 30,
            "is_visible": True,
        },
        {
            "code": "maintenance_impostazioni",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Attività",
            "target_url": "django:assets:maintenance_impostazioni",
            "active_match": "/assets/manutenzione/impostazioni/",
            "is_subitem": True,
            "parent_code": "manutenzione_config",
            "sort_order": 10,
            "is_visible": True,
        },
        {
            "code": "plant_layout_map",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Mappa officina",
            "target_url": "django:assets:plant_layout_map",
            "active_match": "/assets/work-machines/map/",
            "is_subitem": True,
            "parent_code": "work_machines",
            "sort_order": 61,
            "is_visible": True,
        },
        {
            "code": "software_licenses",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Licenze software",
            "target_url": "django:assets:software_license_list",
            "active_match": "/assets/licenze/",
            "is_subitem": False,
            "parent_code": "",
            "sort_order": 63,
            "is_visible": True,
        },
        {
            "code": "maintenance_schedule",
            "section": AssetSidebarButton.SECTION_OPERATIONS,
            "label": "Scadenze manutenzione",
            "target_url": "django:assets:maintenance_scadenze",
            "active_match": "/assets/manutenzione/scadenze/",
            "is_subitem": False,
            "parent_code": "",
            "sort_order": 66,
            "is_visible": True,
        },
        {
            "code": "assistance_contracts",
            "section": AssetSidebarButton.SECTION_OPERATIONS,
            "label": "Contratti assistenza",
            "target_url": "django:assets:assistance_contract_list",
            "active_match": "/assets/manutenzione/contratti/",
            "is_subitem": False,
            "parent_code": "",
            "sort_order": 67,
            "is_visible": True,
        },
        {
            "code": "lifecycle_tracking",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Report asset produzione",
            "target_url": "django:assets:reports?scope=production",
            "active_match": "",
            "is_subitem": True,
            "parent_code": "manutenzione_hub",
            "sort_order": 85,
            "is_visible": True,
        },
        {
            "code": "compliance_reports",
            "section": AssetSidebarButton.SECTION_ANALYTICS,
            "label": "Scadenze manutenzione",
            "target_url": "django:assets:maintenance_scadenze",
            "active_match": "/assets/manutenzione/scadenze/",
            "is_subitem": False,
            "parent_code": "",
            "sort_order": 80,
            "is_visible": True,
        },
        {
            "code": "guida_asset",
            "section": AssetSidebarButton.SECTION_OPERATIONS,
            "label": "Guida Asset",
            "target_url": "django:assets:guida",
            "active_match": "/assets/guida/",
            "is_subitem": False,
            "parent_code": "",
            "sort_order": 99,
            "is_visible": True,
        },
    ]


def _create_default_sidebar_buttons() -> int:
    payload = _default_sidebar_seed_rows()
    created = 0
    created_by_code: dict[str, AssetSidebarButton] = {}
    for row in payload:
        button, _created = AssetSidebarButton.objects.get_or_create(
            code=row["code"],
            defaults={
                "section": row["section"],
                "label": row["label"],
                "target_url": row["target_url"],
                "active_match": row["active_match"],
                "is_subitem": row["is_subitem"],
                "sort_order": row["sort_order"],
                "is_visible": row["is_visible"],
            },
        )
        created_by_code[row["code"]] = button
        created += 1
    for row in payload:
        parent_code = _clean_string(row.get("parent_code"))
        if not parent_code:
            continue
        button = created_by_code.get(row["code"])
        parent = created_by_code.get(parent_code)
        if button is None or parent is None or button.parent_id == parent.id:
            continue
        button.parent = parent
        button.is_subitem = True
        button.section = parent.section
        button.save(update_fields=["parent", "is_subitem", "section", "updated_at"])
    return created


def _sidebar_input_suggestions() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    target_suggestions: list[dict[str, str]] = []
    active_match_suggestions: list[dict[str, str]] = []
    seen_targets: set[str] = set()
    seen_active_matches: set[str] = set()

    def add_target(value: str, label: str = "", group: str = "Pagine del modulo") -> None:
        normalized = _clean_string(value)
        if not normalized or normalized in seen_targets:
            return
        seen_targets.add(normalized)
        target_suggestions.append({"value": normalized, "label": label, "group": group})

    def add_active_match(value: str, label: str = "") -> None:
        normalized = _clean_string(value)
        if not normalized or normalized in seen_active_matches:
            return
        seen_active_matches.add(normalized)
        active_match_suggestions.append({"value": normalized, "label": label})

    route_targets = [
        ("django:assets:asset_list?rows={rows}", "Cruscotto inventario"),
        ("django:assets:asset_component_list", "Componenti"),
        ("django:assets:asset_administrative_deadline_list", "Scadenze amministrative"),
        ("django:assets:maintenance_template_list", "Template manutenzione"),
        ("django:assets:maintenance_rule_list", "Regole manutenzione"),
        ("django:assets:work_machine_list", "Macchine di lavoro"),
        ("django:assets:work_machine_dashboard", "Dashboard officina"),
        ("django:assets:periodic_verifications?scope=it", "Manutenzione periodica dispositivi IT"),
        ("django:assets:periodic_verifications?scope=production", "Manutenzione periodica asset produzione"),
        ("django:assets:plant_layout_map", "Mappa officina"),
        ("django:assets:wo_list", "Interventi / Work order"),
        ("django:assets:software_license_list", "Licenze software"),
        ("django:assets:maintenance_schedule", "Prossime manutenzioni"),
        ("django:assets:assistance_contract_list", "Contratti assistenza"),
        ("django:assets:reports", "Report asset"),
        ("django:assets:reports?scope=it", "Report dispositivi IT"),
        ("django:assets:reports?scope=production", "Report asset produzione"),
        ("django:assets:gestione_admin", "Impostazioni assets"),
    ]
    for value, label in route_targets:
        add_target(value, label)

    for asset_type_code, asset_type_label in Asset.TYPE_CHOICES:
        add_target(
            f"django:assets:asset_list?asset_type={asset_type_code}&rows={{rows}}",
            f"Lista asset: {asset_type_label}",
            "Inventario per tipo",
        )
        add_active_match(f"asset_type={asset_type_code}", f"Filtro asset_type: {asset_type_label}")

    for category in AssetCategory.objects.filter(is_active=True).only("id", "label").order_by("sort_order", "label", "id"):
        add_target(
            f"django:assets:asset_list?asset_category={category.id}&rows={{rows}}",
            f"Lista categoria: {category.label}",
            "Inventario per categoria",
        )
        add_active_match(f"asset_category={category.id}", f"Filtro categoria: {category.label}")

    route_active_matches = [
        ("assets:asset_list", "Lista inventario"),
        ("assets:asset_component_list", "Componenti"),
        ("assets:asset_administrative_deadline_list", "Scadenze amministrative"),
        ("assets:maintenance_template_list", "Template manutenzione"),
        ("assets:maintenance_rule_list", "Regole manutenzione"),
        ("assets:work_machine_list", "Macchine di lavoro"),
        ("assets:work_machine_dashboard", "Dashboard officina"),
        ("assets:periodic_verifications", "Manutenzione periodica"),
        ("assets:plant_layout_map", "Mappa officina"),
        ("assets:wo_list", "Interventi / Work order"),
        ("assets:software_license_list", "Licenze software"),
        ("assets:maintenance_schedule", "Prossime manutenzioni"),
        ("assets:assistance_contract_list", "Contratti assistenza"),
        ("assets:reports", "Report asset"),
        ("assets:gestione_admin", "Impostazioni assets"),
    ]
    for route_name, label in route_active_matches:
        try:
            add_active_match(reverse(route_name), label)
        except NoReverseMatch:
            continue

    for value, label in [
        ("q=", "Filtro ricerca libera"),
        ("reparto=", "Filtro reparto"),
        ("vlan=", "Filtro VLAN"),
        ("ip=", "Filtro IP"),
        ("scope=it", "Report dispositivi IT"),
        ("scope=production", "Report asset produzione"),
        ("rows={rows}", "Placeholder righe per pagina"),
    ]:
        add_active_match(value, label)

    # Le pagine del menu predefinito portano gia' un nome leggibile.
    for row in _default_sidebar_seed_rows():
        add_target(row["target_url"], row["label"])

    known_labels = {row["value"]: row["label"] for row in target_suggestions}
    for button in AssetSidebarButton.objects.exclude(target_url="").only("target_url", "label"):
        if button.target_url in known_labels:
            continue
        # Pagina fuori catalogo: il nome della voce che la usa e' piu'
        # parlante del percorso, che resta come riferimento.
        path = _resolve_sidebar_url(button.target_url)
        add_target(button.target_url, f"{button.label} · {path}", "Già usati nel menu")
    for button in AssetSidebarButton.objects.exclude(active_match="").only("active_match"):
        add_active_match(button.active_match, "Gia configurato")

    # Gruppi contigui: il template li rende come <optgroup> con {% regroup %}.
    group_order = ["Pagine del modulo", "Inventario per tipo", "Inventario per categoria", "Già usati nel menu"]
    target_suggestions.sort(key=lambda row: group_order.index(row["group"]) if row["group"] in group_order else len(group_order))
    return target_suggestions, active_match_suggestions


def _sidebar_target_label(target_url: str, known_labels: dict[str, str]) -> str:
    """Nome leggibile di una destinazione sidebar al posto di ``django:assets:...``."""
    target = _clean_string(target_url)
    if not target:
        return "Nessuna destinazione (solo contenitore)"
    if known_labels.get(target):
        return known_labels[target]
    if target.startswith("django:"):
        route_part, _, query = target.partition("?")
        base_label = known_labels.get(route_part)
        if base_label:
            return f"{base_label} (con filtro)" if query else base_label
        resolved = _resolve_sidebar_url(target)
        return f"Pagina {resolved}" if resolved != "#" else "Pagina non trovata"
    return f"Indirizzo {target}"


def _dashboard_open_workorder_alert_rows(limit: int = 4) -> list[WorkOrder]:
    try:
        return list(
            WorkOrder.objects.select_related("asset")
            .only(
                "id",
                "asset_id",
                "status",
                "opened_at",
                "title",
                "description",
                "asset__id",
                "asset__asset_tag",
                "asset__name",
            )
            .filter(status=WorkOrder.STATUS_OPEN)
            .order_by("-opened_at")[:limit]
        )
    except DatabaseError:
        logger.warning("Impossibile caricare gli alert work order per la dashboard assets: schema WorkOrder non allineato.", exc_info=True)
        return []


def _sidebar_button_payload(
    request: HttpRequest,
    button: AssetSidebarButton,
    *,
    rows: int = 25,
    force_subitem: bool | None = None,
) -> dict[str, object]:
    url = _resolve_sidebar_url(button.target_url, rows=rows)
    return {
        "id": button.id,
        "label": _ui_label(button.label),
        "url": url,
        "is_subitem": button.is_subitem if force_subitem is None else force_subitem,
        "active": _is_sidebar_button_active(request, button, url),
        # Voce senza destinazione (es. area categorie): il clic apre le sotto-voci.
        "is_container": not _clean_string(button.target_url),
        "badge": _da_fare_badge(request) if button.code == "maintenance_da_fare" else None,
    }


def _da_fare_badge(request: HttpRequest) -> int | None:
    """Manutenzioni scadute ancora aperte, accanto a "Da fare": si vede che c'e'
    lavoro arretrato senza aprire la pagina. Una count indicizzata
    (status, due_date), una volta per richiesta."""
    cached = getattr(request, "_assets_da_fare_badge", "unset")
    if cached != "unset":
        return cached
    from ..models import MaintenanceOccurrence

    try:
        count = MaintenanceOccurrence.objects.filter(
            status=MaintenanceOccurrence.STATUS_OPEN, due_date__lt=timezone.localdate()
        ).count()
    except Exception:
        count = None
    request._assets_da_fare_badge = count or None
    return request._assets_da_fare_badge
