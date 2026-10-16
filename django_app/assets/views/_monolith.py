"""Parte di assets/views.py non ancora spezzata (refactor C4, transitorio)."""

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
    ASSET_DOCUMENT_ALLOWED_MIMES,
    ASSET_DOCUMENT_MAX_BYTES,
    CATEGORY_ACTIONS,
    REPORT_TEMPLATE_ALLOWED_EXTENSIONS,
    SIDEBAR_ACTIONS,
    _as_int,
    _build_work_machine_maintenance_month_dataset,
    _clean_string,
    _get_default_asset_label_template,
    _is_assets_admin,
    _model_table_exists,
    _month_end,
    _month_label,
    _month_start_from_value,
    _planned_maintenance_status,
    _ui_choices,
    _ui_label,
    _work_machine_maintenance_month_pdf_url,
)
from ._helpers_b import (  # noqa: F401
    _asset_detail_source_choices,
    _build_asset_report_snapshot,
    _normalize_reports_scope,
    _sidebar_input_suggestions,
    _sidebar_target_label,
)
from ._helpers_c import (  # noqa: F401
    _apply_workorder_list_filters,
    _apply_workorder_operational_view,
    _assets_shell_context,
    _category_sidebar_active_match,
    _category_sidebar_target,
    _category_subtree_ids,
    _handle_asset_category_request,
    _handle_sidebar_button_request,
    _resolve_workorder_operational_view,
    _workorder_list_page_url,
    _xl_write_sheet,
)

REPORT_TEMPLATE_ALLOWED_MIMES = ASSET_DOCUMENT_ALLOWED_MIMES | {
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
DEFAULT_REPORT_DEFINITIONS = [
    {
        "code": AssetReportTemplate.REPORT_ASSET_DETAIL,
        "label": "Scheda asset PDF",
        "description": "Report PDF del singolo asset con riepilogo, documenti e storico.",
        "sort_order": 10,
    },
    {
        "code": AssetReportTemplate.REPORT_WORK_MACHINE_MAINTENANCE,
        "label": "Manutenzioni macchine mese",
        "description": "Report mensile delle manutenzioni pianificate per le macchine di lavoro.",
        "sort_order": 20,
    },
]

DOCUMENT_FOLDER_ACTIONS = {
    "create_asset_category_document_folder",
    "rename_asset_category_document_folder",
    "toggle_asset_category_document_folder",
    "update_asset_category_document_folder_order",
    "delete_asset_category_document_folder",
}


def _default_asset_report_definition_objects() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id=0,
            code=str(item["code"]),
            label=str(item["label"]),
            description=str(item["description"]),
            sort_order=int(item["sort_order"]),
            is_active=True,
        )
        for item in DEFAULT_REPORT_DEFINITIONS
    ]


def _active_asset_report_template(report_code: str) -> AssetReportTemplate | None:
    report_value = _clean_string(report_code)
    if not report_value or not _model_table_exists(AssetReportTemplate):
        return None
    try:
        return (
            AssetReportTemplate.objects.filter(report_code=report_value, is_active=True)
            .select_related("uploaded_by")
            .order_by("-updated_at", "-id")
            .first()
        )
    except DatabaseError:
        return None


def _ensure_default_asset_report_definitions() -> list[AssetReportDefinition | SimpleNamespace]:
    if not _model_table_exists(AssetReportDefinition):
        return _default_asset_report_definition_objects()
    try:
        existing = {row.code: row for row in AssetReportDefinition.objects.all()}
        for item in DEFAULT_REPORT_DEFINITIONS:
            code = str(item["code"])
            row = existing.get(code)
            if row is None:
                row = AssetReportDefinition.objects.create(
                    code=code,
                    label=str(item["label"]),
                    description=str(item["description"]),
                    sort_order=int(item["sort_order"]),
                    is_active=True,
                )
                existing[code] = row
                continue
            changed = False
            if not row.label:
                row.label = str(item["label"])
                changed = True
            if not row.description:
                row.description = str(item["description"])
                changed = True
            if row.sort_order != int(item["sort_order"]):
                row.sort_order = int(item["sort_order"])
                changed = True
            if changed:
                row.save(update_fields=["label", "description", "sort_order", "updated_at"])
        return list(AssetReportDefinition.objects.order_by("sort_order", "label", "id"))
    except DatabaseError:
        return _default_asset_report_definition_objects()


def _asset_report_definition_map() -> dict[str, AssetReportDefinition | SimpleNamespace]:
    return {row.code: row for row in _ensure_default_asset_report_definitions()}


def _report_templates_grouped() -> list[dict[str, object]]:
    grouped: list[dict[str, object]] = []
    templates_table_exists = _model_table_exists(AssetReportTemplate)
    for definition in _ensure_default_asset_report_definitions():
        report_code = definition.code
        if not templates_table_exists:
            rows = []
        else:
            try:
                rows = list(
                    AssetReportTemplate.objects.filter(report_code=report_code)
                    .select_related("uploaded_by")
                    .order_by("-is_active", "-updated_at", "-id")
                )
            except DatabaseError:
                rows = []
        grouped.append(
            {
                "code": report_code,
                "label": definition.label,
                "description": definition.description,
                "definition": definition,
                "active": next((row for row in rows if row.is_active), None),
                "rows": rows,
            }
        )
    return grouped


def render_asset_report_pdf(asset: Asset, snapshot: dict[str, object], *, template_name: str = "") -> bytes:
    """Report PDF della scheda asset col template standard del portale (``core.pdf``).

    Allinea la veste a tutti gli altri report (header/footer branded via
    ``header_footer_callback``, tabelle zebra col colore primario) e mette in
    evidenza il flag PART 145.
    """
    import io as _io
    from html import escape as _escape

    from reportlab.lib import colors as _colors
    from reportlab.lib.styles import ParagraphStyle as _ParagraphStyle
    from reportlab.lib.units import mm as _mm
    from reportlab.platypus import Paragraph as _Paragraph, Spacer as _Spacer, Table as _Table, TableStyle as _TableStyle

    from core.pdf import build_styles, data_table, header_footer_callback, make_document, section_heading

    theme = PdfTheme.from_branding()
    styles = build_styles(theme)
    buf = _io.BytesIO()
    doc = make_document(buf, title=f"Report asset {asset.asset_tag or ''}".strip())
    page_w = doc.pagesize[0] - doc.leftMargin - doc.rightMargin
    story: list = []

    # Evidenza PART 145 (rosso) in testa quando applicabile.
    if getattr(asset, "part_145", False):
        badge_style = _ParagraphStyle(
            "p145Badge", fontName="Helvetica-Bold", fontSize=11, textColor=_colors.white, alignment=1,
        )
        note_style = _ParagraphStyle(
            "p145Note", fontName="Helvetica-Bold", fontSize=9.5, textColor=_colors.HexColor("#7f1d1d"),
        )
        banner = _Table(
            [[
                _Paragraph("PART 145", badge_style),
                _Paragraph("Asset soggetto al regolamento aeronautico PART 145", note_style),
            ]],
            colWidths=[30 * _mm, page_w - 30 * _mm],
        )
        banner.setStyle(_TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), _colors.HexColor("#dc2626")),
            ("BACKGROUND", (1, 0), (1, 0), _colors.HexColor("#fef2f2")),
            ("BOX", (0, 0), (-1, -1), 0.8, _colors.HexColor("#dc2626")),
            ("INNERGRID", (0, 0), (-1, -1), 0.8, _colors.HexColor("#dc2626")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.append(banner)
        story.append(_Spacer(1, 5 * _mm))

    def kv_section(title: str, rows) -> None:
        rows = list(rows or [])
        if not rows:
            return
        story.extend(section_heading(title, theme, styles))
        table_rows = [
            [
                _Paragraph(_escape(str(key)), styles["label"]),
                _Paragraph(_escape(str(value)).replace("\n", "<br/>"), styles["value"]),
            ]
            for key, value in rows
        ]
        story.append(data_table(table_rows, theme, header=False, col_widths=[54 * _mm, page_w - 54 * _mm]))
        story.append(_Spacer(1, 3 * _mm))

    def list_section(title: str, headers, rows) -> None:
        rows = list(rows or [])
        if not rows:
            return
        story.extend(section_heading(title, theme, styles))
        col_w = page_w / max(1, len(headers))
        table_rows = [[_Paragraph(_escape(str(h)), styles["table_header"]) for h in headers]]
        for row in rows:
            table_rows.append([_Paragraph(_escape(str(cell)), styles["cell"]) for cell in row])
        story.append(data_table(table_rows, theme, col_widths=[col_w] * len(headers), repeat_rows=1))
        story.append(_Spacer(1, 3 * _mm))

    kv_section("Riepilogo asset", snapshot.get("summary_rows"))
    kv_section("Dati tecnici", snapshot.get("technical_rows"))
    kv_section("Campi categoria", snapshot.get("category_rows"))
    kv_section("Campi personalizzati", snapshot.get("custom_rows"))
    list_section("Documenti", ["Categoria", "File", "Data", "Peso"], snapshot.get("document_rows"))
    list_section("Work order recenti", ["Data", "Tipo", "Titolo", "Stato"], snapshot.get("workorder_rows"))
    list_section("Ticket collegati", ["Ticket", "Tipo", "Titolo", "Stato"], snapshot.get("ticket_rows"))
    list_section("Manutenzione periodica", ["Piano", "Prossima data", "Fornitore"], snapshot.get("periodic_rows"))

    if not story:
        story.append(_Paragraph("Nessun dato disponibile per questo asset.", styles["body"]))

    subtitle = f"{asset.asset_tag or '-'} — {asset.name or '-'}"
    if template_name:
        subtitle = f"{subtitle} | Template: {template_name}"
    draw = header_footer_callback(theme, title="REPORT ASSET", subtitle=subtitle)
    doc.build(story, onFirstPage=draw, onLaterPages=draw)
    return buf.getvalue()


def _reports_scope_context(scope: str) -> dict[str, object]:
    if scope == "it":
        return {
            "scope": "it",
            "title": "Report dispositivi IT",
            "subtitle": "KPI e interventi filtrati su PC, server, rete, fonia, TVCC e dispositivi IT.",
            "asset_types": IT_DEVICE_TYPES,
            "maintenance_month_enabled": False,
            "empty_month_message": "Il piano mese e il PDF mensile sono disponibili nei report asset produzione.",
        }
    return {
        "scope": "production",
        "title": "Report asset produzione",
        "subtitle": "KPI e interventi filtrati su CNC, macchine utensili e carroponti.",
        "asset_types": PRODUCTION_ASSET_TYPES,
        "maintenance_month_enabled": True,
        "empty_month_message": "",
    }


def _sidebar_parent_choices() -> list[AssetSidebarButton]:
    return list(
        AssetSidebarButton.objects.filter(parent__isnull=True)
        .order_by("section", "sort_order", "label", "id")
    )


def _category_inventory_url(category_id: int, rows: int = 25) -> str:
    return f"{reverse('assets:asset_list')}?asset_category={int(category_id)}&rows={int(rows)}"


def _build_asset_category_admin_rows(categories: list[AssetCategory]) -> list[dict[str, object]]:
    category_ids = [category.id for category in categories]
    if not category_ids:
        return []

    asset_stats = {
        row["asset_category_id"]: row
        for row in (
            Asset.objects.filter(asset_category_id__in=category_ids)
            .values("asset_category_id")
            .annotate(
                total=Count("id"),
                in_use=Count("id", filter=Q(status=Asset.STATUS_IN_USE)),
                in_repair=Count("id", filter=Q(status=Asset.STATUS_IN_REPAIR)),
                last_updated=Max("updated_at"),
            )
            .order_by()
        )
    }
    field_stats = {
        row["category_id"]: row
        for row in (
            AssetCategoryField.objects.filter(category_id__in=category_ids)
            .values("category_id")
            .annotate(
                total=Count("id"),
                active=Count("id", filter=Q(is_active=True)),
            )
            .order_by()
        )
    }
    child_counts = {
        row["parent_id"]: row["total"]
        for row in AssetCategory.objects.filter(parent_id__in=category_ids).values("parent_id").annotate(total=Count("id")).order_by()
    }
    open_workorders = {
        row["asset__asset_category_id"]: row["total"]
        for row in (
            WorkOrder.objects.filter(asset__asset_category_id__in=category_ids, status=WorkOrder.STATUS_OPEN)
            .values("asset__asset_category_id")
            .annotate(total=Count("id"))
            .order_by()
        )
    }
    sample_assets_by_category: dict[int, list[Asset]] = defaultdict(list)
    for asset in (
        Asset.objects.filter(asset_category_id__in=category_ids)
        .select_related("asset_category")
        .order_by("asset_category_id", "-updated_at", "name", "asset_tag")
    ):
        bucket = sample_assets_by_category[asset.asset_category_id]
        if len(bucket) < 6:
            bucket.append(asset)

    sidebar_targets = {_category_sidebar_target(category_id) for category_id in category_ids}
    sidebar_matches = {_category_sidebar_active_match(category_id) for category_id in category_ids}
    sidebar_by_target = {
        row.target_url: row
        for row in AssetSidebarButton.objects.filter(target_url__in=sidebar_targets)
    }
    sidebar_by_match = {
        row.active_match: row
        for row in AssetSidebarButton.objects.filter(active_match__in=sidebar_matches)
    }
    type_labels = dict(Asset.TYPE_CHOICES)
    rows: list[dict[str, object]] = []
    for category in categories:
        stats = asset_stats.get(category.id, {})
        fields = field_stats.get(category.id, {})
        sidebar_target = _category_sidebar_target(category.id)
        sidebar_match = _category_sidebar_active_match(category.id)
        rows.append(
            {
                "category": category,
                "base_asset_type_label": type_labels.get(category.base_asset_type, category.base_asset_type),
                "asset_count": int(stats.get("total") or 0),
                "in_use_count": int(stats.get("in_use") or 0),
                "in_repair_count": int(stats.get("in_repair") or 0),
                "open_workorder_count": int(open_workorders.get(category.id) or 0),
                "field_count": int(fields.get("total") or 0),
                "active_field_count": int(fields.get("active") or 0),
                "child_count": int(child_counts.get(category.id) or 0),
                "last_updated": stats.get("last_updated"),
                "sample_assets": sample_assets_by_category.get(category.id, []),
                "inventory_url": _category_inventory_url(category.id),
                "sidebar_target_url": sidebar_target,
                "sidebar_active_match": sidebar_match,
                "sidebar_button": sidebar_by_target.get(sidebar_target) or sidebar_by_match.get(sidebar_match),
            }
        )
    return rows


def _asset_document_folder_usage(folder: "AssetCategoryDocumentFolder") -> int:
    """Quanti documenti usano la cartella (chiave slug) nella sua categoria."""
    return AssetDocument.objects.filter(
        asset__asset_category_id=folder.category_id, category=folder.slug
    ).count()


def _handle_asset_document_folder_request(request: HttpRequest) -> tuple[bool, str]:
    """Gestione delle cartelle documento extra dalle impostazioni Assets.

    Stesse regole della scheda asset (``add_asset_document_folder`` /
    ``deactivate_asset_document_folder``): lo slug e' la chiave stabile salvata
    in ``AssetDocument.category`` e non cambia mai, e una cartella si disattiva
    o si elimina solo se non contiene documenti. Qui in piu' si puo' riattivare
    una cartella, cambiarne l'ordine e rinominarla (cambia solo l'etichetta
    mostrata: i documenti gia' archiviati restano sullo slug), perche' la pagina
    vede tutte le categorie insieme.
    """
    action = _clean_string(request.POST.get("action"))

    if action == "create_asset_category_document_folder":
        category_id = _as_int(request.POST.get("category_id"), default=0)
        category = AssetCategory.objects.filter(pk=category_id).first()
        if not category:
            return False, "Categoria asset non trovata."
        raw_name = _clean_string(request.POST.get("folder_name"))[:120]
        slug = slugify(raw_name)[:60]
        base_codes = {code.lower() for code, _ in AssetDocument.CATEGORY_CHOICES}
        if not raw_name or not slug:
            return False, "Nome cartella non valido."
        if slug in base_codes:
            return False, "Esiste gia una cartella di base con questo nome."
        if category.document_folders.filter(slug=slug).exists():
            return False, f'La categoria "{category.label}" ha gia una cartella documento con questo nome.'
        default_order = (category.document_folders.aggregate(m=Max("order"))["m"] or 0) + 1
        AssetCategoryDocumentFolder.objects.create(
            category=category,
            name=raw_name,
            slug=slug,
            order=max(0, _as_int(request.POST.get("sort_order"), default=default_order)),
        )
        log_action(
            request,
            "add_asset_document_folder",
            "assets",
            {"category_id": category.id, "slug": slug, "name": raw_name, "origine": "impostazioni"},
        )
        return True, f'Cartella documento "{raw_name}" aggiunta alla categoria {category.label}.'

    if action == "rename_asset_category_document_folder":
        folder = (
            AssetCategoryDocumentFolder.objects.filter(pk=_as_int(request.POST.get("folder_id"), default=0))
            .select_related("category")
            .first()
        )
        if not folder:
            return False, "Cartella documento non trovata."
        raw_name = _clean_string(request.POST.get("folder_name"))[:120]
        if not raw_name:
            return False, "Nome cartella non valido."
        if raw_name == folder.name:
            return True, f'Cartella documento "{folder.name}" invariata.'
        if (
            folder.category.document_folders.filter(name__iexact=raw_name)
            .exclude(pk=folder.pk)
            .exists()
        ):
            return False, f'La categoria "{folder.category.label}" ha gia una cartella documento con questo nome.'
        old_name = folder.name
        folder.name = raw_name
        folder.save(update_fields=["name"])
        log_action(
            request,
            "rename_asset_document_folder",
            "assets",
            {
                "folder_id": folder.id,
                "slug": folder.slug,
                "category_id": folder.category_id,
                "da": old_name,
                "a": raw_name,
            },
        )
        return True, f'Cartella documento "{old_name}" rinominata in "{raw_name}".'

    if action == "toggle_asset_category_document_folder":
        folder = (
            AssetCategoryDocumentFolder.objects.filter(pk=_as_int(request.POST.get("folder_id"), default=0))
            .select_related("category")
            .first()
        )
        if not folder:
            return False, "Cartella documento non trovata."
        if folder.is_active and _asset_document_folder_usage(folder):
            return False, "Impossibile disattivare: la cartella contiene ancora documenti."
        folder.is_active = not folder.is_active
        folder.save(update_fields=["is_active"])
        log_action(
            request,
            "activate_asset_document_folder" if folder.is_active else "deactivate_asset_document_folder",
            "assets",
            {
                "folder_id": folder.id,
                "slug": folder.slug,
                "category_id": folder.category_id,
                "origine": "impostazioni",
            },
        )
        stato = "riattivata" if folder.is_active else "disattivata"
        return True, f'Cartella documento "{folder.name}" {stato}.'

    if action == "update_asset_category_document_folder_order":
        folder = AssetCategoryDocumentFolder.objects.filter(
            pk=_as_int(request.POST.get("folder_id"), default=0)
        ).first()
        if not folder:
            return False, "Cartella documento non trovata."
        folder.order = max(0, _as_int(request.POST.get("sort_order"), default=folder.order))
        folder.save(update_fields=["order"])
        return True, f'Ordine della cartella "{folder.name}" aggiornato.'

    if action == "delete_asset_category_document_folder":
        folder = (
            AssetCategoryDocumentFolder.objects.filter(pk=_as_int(request.POST.get("folder_id"), default=0))
            .select_related("category")
            .first()
        )
        if not folder:
            return False, "Cartella documento non trovata."
        if _asset_document_folder_usage(folder):
            return False, "Impossibile eliminare: la cartella contiene ancora documenti."
        name = folder.name
        log_action(
            request,
            "delete_asset_document_folder",
            "assets",
            {"folder_id": folder.id, "slug": folder.slug, "category_id": folder.category_id},
        )
        folder.delete()
        return True, f'Cartella documento "{name}" eliminata.'

    return False, "Azione cartella documento non valida."


def _build_asset_document_folder_rows(categories: list[AssetCategory]) -> list[dict[str, object]]:
    """Righe della pagina impostazioni: per categoria, cartelle di base ed extra.

    Il conteggio dei documenti e' una sola query per tutte le categorie;
    ``.order_by()`` azzera il ``Meta.ordering`` di ``AssetDocument``, altrimenti
    SQL Server rifiuta l'aggregazione (errore 8127).
    """
    category_ids = [category.id for category in categories]
    if not category_ids:
        return []

    doc_counts: dict[tuple[int, str], int] = {}
    for row in (
        AssetDocument.objects.filter(asset__asset_category_id__in=category_ids)
        .values("asset__asset_category_id", "category")
        .annotate(total=Count("id"))
        .order_by()
    ):
        doc_counts[(row["asset__asset_category_id"], row["category"])] = int(row["total"] or 0)

    folders_by_category: dict[int, list[AssetCategoryDocumentFolder]] = defaultdict(list)
    for folder in AssetCategoryDocumentFolder.objects.filter(category_id__in=category_ids):
        folders_by_category[folder.category_id].append(folder)

    asset_counts = {
        row["asset_category_id"]: int(row["total"] or 0)
        for row in (
            Asset.objects.filter(asset_category_id__in=category_ids)
            .values("asset_category_id")
            .annotate(total=Count("id"))
            .order_by()
        )
    }

    rows: list[dict[str, object]] = []
    for category in categories:
        base_folders = [
            {"code": code, "label": label, "document_count": doc_counts.get((category.id, code), 0)}
            for code, label in AssetDocument.CATEGORY_CHOICES
        ]
        extra_folders = []
        for folder in folders_by_category.get(category.id, []):
            document_count = doc_counts.get((category.id, folder.slug), 0)
            extra_folders.append(
                {
                    "folder": folder,
                    "document_count": document_count,
                    "can_remove": document_count == 0,
                }
            )
        rows.append(
            {
                "category": category,
                "asset_count": asset_counts.get(category.id, 0),
                "base_folders": base_folders,
                "extra_folders": extra_folders,
                "extra_active_count": sum(1 for item in extra_folders if item["folder"].is_active),
                "document_count": sum(item["document_count"] for item in base_folders)
                + sum(item["document_count"] for item in extra_folders),
            }
        )
    return rows


def _part_145_export_dataset() -> tuple[list[str], list[list[str]]]:
    """Header + righe (stringhe) per l'export PART 145; stesso ordine della lista."""
    assets = (
        Asset.objects.filter(part_145=True)
        .select_related("asset_category")
        .order_by("name", "asset_tag", "id")
    )
    headers = ["Asset", "Tag", "Stato", "Categoria", "Reparto", "Produttore", "Modello", "Seriale"]
    rows = [
        [
            a.name or "",
            a.asset_tag or "",
            a.get_status_display(),
            a.category_label or "",
            a.reparto or "",
            a.manufacturer or "",
            a.model or "",
            a.serial_number or "",
        ]
        for a in assets
    ]
    return headers, rows


@login_required
def asset_part_145_export_pdf(request: HttpRequest) -> HttpResponse:
    """Esporta l'elenco PART 145 in PDF (report tabellare standard)."""
    headers, rows = _part_145_export_dataset()
    today = timezone.localdate().strftime("%Y%m%d")
    pdf_bytes = _report_table_pdf(title="Asset PART 145", headers=headers, rows=rows)
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="asset_part145_{today}.pdf"'
    return resp


@login_required
def asset_part_145_export_excel(request: HttpRequest) -> HttpResponse:
    """Esporta l'elenco PART 145 in Excel (.xlsx)."""
    import io

    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    from core.excel_export import write_cell, write_row

    headers, rows = _part_145_export_dataset()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Asset PART 145"

    header_fill = PatternFill(fill_type="solid", fgColor="DC2626")
    header_font = Font(bold=True, color="FFFFFF", name="Calibri", size=10)
    for col_idx, header in enumerate(headers, 1):
        cell = write_cell(ws, 1, col_idx, header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 20

    for row_idx, values in enumerate(rows, 2):
        write_row(ws, row_idx, values)

    for col in ws.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=0)
        ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 3, 10), 45)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    today_str = timezone.localdate().strftime("%Y%m%d")
    resp = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="asset_part145_{today_str}.xlsx"'
    return resp


def _inventory_studio_context(request: HttpRequest) -> dict[str, object]:
    """Dati dello «Studio inventario» (Impostazioni → tab «Studio inventario»).

    Prima vivevano nella lista asset, in un riquadro modale che duplicava le
    Impostazioni: ora li usa solo la tab dedicata. Le azioni restano sullo stesso
    endpoint di ``asset_list`` (vedi ``_studio_redirect``).
    """
    can_manage_custom_fields = _is_assets_admin(request)
    all_custom_fields = list(AssetCustomField.objects.order_by("sort_order", "id"))
    list_options = list(AssetListOption.objects.order_by("field_key", "sort_order", "value", "id"))
    action_buttons = list(AssetActionButton.objects.order_by("zone", "sort_order", "label", "id"))
    detail_fields = list(AssetDetailField.objects.order_by("section", "asset_scope", "sort_order", "label", "id"))
    asset_categories = list(AssetCategory.objects.order_by("sort_order", "label", "id"))
    asset_category_fields = list(
        AssetCategoryField.objects.select_related("category").order_by(
            "category__sort_order",
            "category__label",
            "sort_order",
            "label",
            "id",
        )
    )
    sidebar_buttons = list(AssetSidebarButton.objects.select_related("parent").order_by("section", "sort_order", "label", "id"))
    sidebar_parent_choices = _sidebar_parent_choices()
    sidebar_target_suggestions, sidebar_active_match_suggestions = _sidebar_input_suggestions()
    sidebar_target_labels = {row["value"]: row["label"] for row in sidebar_target_suggestions}
    for sidebar_item in sidebar_buttons:
        sidebar_item.target_label = _sidebar_target_label(sidebar_item.target_url, sidebar_target_labels)
    for button in action_buttons:
        button.label = _ui_label(button.label)
    for detail_item in detail_fields:
        detail_item.label = _ui_label(detail_item.label)
    for sidebar_item in sidebar_buttons:
        sidebar_item.label = _ui_label(sidebar_item.label)
    for parent_item in sidebar_parent_choices:
        parent_item.label = _ui_label(parent_item.label)
    admin_metrics = {
        "custom_fields_total": len(all_custom_fields),
        "custom_fields_active": sum(1 for row in all_custom_fields if row.is_active),
        "list_options_total": len(list_options),
        "list_options_active": sum(1 for row in list_options if row.is_active),
        "action_buttons_total": len(action_buttons),
        "action_buttons_active": sum(1 for row in action_buttons if row.is_active),
        "detail_fields_total": len(detail_fields),
        "detail_fields_active": sum(1 for row in detail_fields if row.is_active),
        "asset_categories_total": len(asset_categories),
        "asset_categories_active": sum(1 for row in asset_categories if row.is_active),
        "asset_category_fields_total": len(asset_category_fields),
        "asset_category_fields_active": sum(1 for row in asset_category_fields if row.is_active),
        "sidebar_total": len(sidebar_buttons),
        "sidebar_visible": sum(1 for row in sidebar_buttons if row.is_visible),
        "sidebar_hidden": sum(1 for row in sidebar_buttons if not row.is_visible),
    }
    admin_checks = []
    if can_manage_custom_fields:
        if admin_metrics["sidebar_total"] == 0:
            admin_checks.append("Menu laterale personalizzato non configurato: usa il caricamento iniziale.")
        if admin_metrics["action_buttons_active"] == 0:
            admin_checks.append("Nessun pulsante azione attivo sul dettaglio asset.")
        if admin_metrics["detail_fields_active"] == 0:
            admin_checks.append("Nessun campo dettaglio attivo: la scheda asset usera il fallback predefinito.")
        if admin_metrics["asset_categories_active"] == 0:
            admin_checks.append("Nessuna categoria asset attiva: il modulo usa solo le tipologie tecniche standard.")
        if admin_metrics["custom_fields_active"] == 0:
            admin_checks.append("Nessun campo personalizzato attivo: verifica se e voluto.")
        if not admin_checks:
            admin_checks.append("Configurazione amministratore completa e coerente.")
    return {
        "all_custom_fields": all_custom_fields,
        "custom_type_choices": _ui_choices(AssetCustomField.TYPE_CHOICES),
        "list_options": list_options,
        "list_option_choices": _ui_choices(AssetListOption.FIELD_CHOICES),
        "action_buttons": action_buttons,
        "button_zone_choices": _ui_choices(AssetActionButton.ZONE_CHOICES),
        "button_action_choices": _ui_choices(AssetActionButton.ACTION_CHOICES),
        "button_style_choices": _ui_choices(AssetActionButton.STYLE_CHOICES),
        "detail_fields": detail_fields,
        "detail_section_choices": _ui_choices(AssetDetailField.SECTION_CHOICES),
        "detail_scope_choices": _ui_choices(AssetDetailField.SCOPE_CHOICES),
        "detail_format_choices": _ui_choices(AssetDetailField.FORMAT_CHOICES),
        "detail_source_choices": _asset_detail_source_choices(),
        "header_tools": list(AssetHeaderTool.objects.order_by("sort_order", "code")),
        "admin_metrics": admin_metrics,
        "admin_checks": admin_checks,
        "studio_next_url": f"{reverse('assets:gestione_admin')}?tab=studio",
        "studio_can_manage": can_manage_custom_fields,
    }


FAILURE_CODE_ACTIONS = {"failure_code_create", "failure_code_update", "failure_code_delete"}


def _failure_code_admin_context(request: HttpRequest) -> dict[str, object]:
    """Tab «Codici guasto» delle Impostazioni: elenco per tipo e form di creazione."""
    from django.db.models import Count

    from ..models import FailureCode

    codes = list(
        FailureCode.objects.select_related("asset_category")
        .annotate(
            used=Count("workorders_as_problem", distinct=True)
            + Count("workorders_as_cause", distinct=True)
            + Count("workorders_as_remedy", distinct=True)
        )
        .order_by("kind", "sort_order", "label", "id")
    )
    groups = [
        {"kind": kind, "label": label, "codes": [code for code in codes if code.kind == kind]}
        for kind, label in FailureCode.KIND_CHOICES
    ]
    return {
        "failure_code_groups": groups,
        "failure_code_kind_choices": FailureCode.KIND_CHOICES,
        "failure_code_categories": list(AssetCategory.objects.filter(is_active=True).order_by("sort_order", "label")),
        "failure_code_can_manage": _is_assets_admin(request),
    }


def _handle_failure_code_request(request: HttpRequest) -> HttpResponse:
    """Crea / modifica / elimina un codice guasto. Solo amministratori del modulo Asset.

    Un codice usato da un intervento non si elimina (PROTECT): si disattiva.
    """
    from django.db.models import ProtectedError

    from ..models import FailureCode

    target = redirect(f"{reverse('assets:gestione_admin')}?tab=guasti")
    if not _is_assets_admin(request):
        messages.error(request, "Solo gli amministratori del modulo Asset gestiscono i codici guasto.")
        return target
    action = request.POST.get("action")
    if action == "failure_code_create":
        kind = _clean_string(request.POST.get("kind")).upper()
        label = _clean_string(request.POST.get("label"))[:150]
        code = slugify(_clean_string(request.POST.get("code")) or label)[:50]
        category_id = _as_int(request.POST.get("asset_category"), default=0) or None
        if kind not in dict(FailureCode.KIND_CHOICES) or not label or not code:
            messages.error(request, "Indica tipo ed etichetta del codice.")
            return target
        if FailureCode.objects.filter(kind=kind, code=code, asset_category_id=category_id).exists():
            messages.error(request, f"Esiste gia' un codice «{code}» di questo tipo per questa categoria.")
            return target
        FailureCode.objects.create(
            kind=kind, code=code, label=label, asset_category_id=category_id,
            sort_order=_as_int(request.POST.get("sort_order"), default=100),
        )
        log_action(request, "failure_code_create", "assets", {"kind": kind, "code": code})
        messages.success(request, f"Codice «{label}» creato.")
        return target
    code_obj = FailureCode.objects.filter(pk=_as_int(request.POST.get("code_id"), default=0)).first()
    if code_obj is None:
        messages.error(request, "Codice non trovato.")
        return target
    if action == "failure_code_update":
        code_obj.label = _clean_string(request.POST.get("label"))[:150] or code_obj.label
        code_obj.sort_order = _as_int(request.POST.get("sort_order"), default=code_obj.sort_order)
        code_obj.is_active = request.POST.get("is_active") == "1"
        code_obj.save(update_fields=["label", "sort_order", "is_active"])
        log_action(request, "failure_code_update", "assets", {"code_id": code_obj.pk, "attivo": code_obj.is_active})
        messages.success(request, f"Codice «{code_obj.label}» aggiornato.")
        return target
    try:
        code_obj.delete()
    except ProtectedError:
        messages.error(request, f"«{code_obj.label}» e' usato da almeno un intervento: disattivalo invece di eliminarlo.")
        return target
    log_action(request, "failure_code_delete", "assets", {"code_id": code_obj.pk})
    messages.success(request, "Codice eliminato.")
    return target


def _apply_asset_export_filters(get_params) -> "QuerySet[Asset]":
    form = AssetFilterForm(get_params or None)
    qs = Asset.objects.select_related("asset_category").prefetch_related("endpoints")
    if form.is_valid():
        q = _clean_string(form.cleaned_data.get("q"))
        asset_type = _clean_string(form.cleaned_data.get("asset_type"))
        asset_category = form.cleaned_data.get("asset_category")
        reparto = _clean_string(form.cleaned_data.get("reparto"))
        vlan = form.cleaned_data.get("vlan")
        ip = _clean_string(form.cleaned_data.get("ip"))
        if q:
            qs = qs.filter(
                Q(asset_tag__icontains=q) | Q(name__icontains=q) | Q(serial_number__icontains=q)
                | Q(manufacturer__icontains=q) | Q(model__icontains=q)
                | Q(endpoints__endpoint_name__icontains=q) | Q(endpoints__ip__icontains=q)
            )
        if asset_type:
            qs = qs.filter(asset_type=asset_type)
        if asset_category:
            qs = qs.filter(asset_category_id__in=_category_subtree_ids(asset_category))
        if reparto:
            qs = qs.filter(reparto__icontains=reparto)
        if vlan is not None:
            qs = qs.filter(endpoints__vlan=vlan)
        if ip:
            qs = qs.filter(endpoints__ip__icontains=ip)
    return qs.distinct().order_by("name", "asset_tag")


# ---------------------------------------------------------------------------
# EXPORT: asset list
# ---------------------------------------------------------------------------

_ASSET_EXPORT_HEADERS = [
    "Tag", "Nome", "Tipo", "Categoria", "Reparto", "Stato",
    "Produttore", "Modello", "Matricola", "Assegnato a", "Posizione", "Note",
]


def _asset_export_row(a: "Asset") -> list:
    return [
        a.asset_tag or "",
        a.name or "",
        a.get_asset_type_display(),
        a.asset_category.label if a.asset_category_id else "",
        a.reparto or "",
        a.get_status_display(),
        a.manufacturer or "",
        a.model or "",
        a.serial_number or "",
        a.assignment_to or "",
        a.assignment_location or "",
        a.notes or "",
    ]


@login_required
def asset_list_export(request: HttpRequest) -> HttpResponse:
    scope = request.GET.get("scope", "filtered")
    fmt = request.GET.get("format", "xlsx")
    if scope == "full":
        assets = list(Asset.objects.select_related("asset_category").distinct().order_by("name", "asset_tag"))
    else:
        assets = list(_apply_asset_export_filters(request.GET))

    today = timezone.localdate().strftime("%Y%m%d")
    rows = [_asset_export_row(a) for a in assets]

    if fmt == "pdf":
        pdf_bytes = _report_table_pdf(title="Inventario asset", headers=_ASSET_EXPORT_HEADERS, rows=rows)
        resp = HttpResponse(pdf_bytes, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="asset_{today}.pdf"'
        return resp

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Asset"
    _xl_write_sheet(ws, _ASSET_EXPORT_HEADERS, rows)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = HttpResponse(buf.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="asset_{today}.xlsx"'
    return resp


# ---------------------------------------------------------------------------
# EXPORT: workorder list
# ---------------------------------------------------------------------------

_WO_EXPORT_HEADERS = [
    "ID", "Asset Tag", "Asset Nome", "Reparto", "Categoria", "Titolo", "Tipo", "Origine", "Stato",
    "Assegnato a", "Eseguito da", "Fornitore", "Contratto", "Coperto da contratto",
    "Aperto il", "Chiuso il", "Durata min", "Fermo min", "Costo manodopera",
    "Costo materiali", "Costo totale", "Descrizione", "Risoluzione",
]


def _wo_export_row(wo: "WorkOrder") -> list:
    asset = wo.asset if wo.asset_id else None
    assigned = wo.assigned_to.get_full_name() or wo.assigned_to.username if wo.assigned_to_id else ""
    executed = wo.executed_by.get_full_name() or wo.executed_by.username if wo.executed_by_id else ""
    return [
        str(wo.id),
        asset.asset_tag if asset else "",
        asset.name if asset else "",
        asset.reparto if asset else "",
        asset.asset_category.label if asset and asset.asset_category_id else "",
        wo.title or "",
        wo.get_kind_display(),
        wo.get_origin_display(),
        wo.get_status_display(),
        assigned,
        executed,
        str(wo.supplier) if wo.supplier_id else "",
        wo.assistance_contract.title if wo.assistance_contract_id else "",
        "Si" if wo.covered_by_contract else "No",
        wo.opened_at.strftime("%d-%m-%Y %H:%M") if wo.opened_at else "",
        wo.closed_at.strftime("%d-%m-%Y %H:%M") if wo.closed_at else "",
        str(wo.intervention_duration_minutes or 0),
        str(wo.downtime_minutes or 0),
        str(wo.labor_cost_eur or ""),
        str(wo.materials_cost_eur or ""),
        str(wo.resolved_total_cost_eur or ""),
        wo.description or "",
        wo.resolution or "",
    ]


@login_required
def workorder_list_export(request: HttpRequest) -> HttpResponse:
    scope = request.GET.get("scope", "filtered")
    fmt = request.GET.get("format", "xlsx")
    qs = _apply_workorder_list_filters(request.GET, include_filters=(scope == "filtered"))
    if scope == "filtered" and _clean_string(request.GET.get("view")):
        qs = _apply_workorder_operational_view(
            qs,
            operational_view=_resolve_workorder_operational_view(request.GET),
            user=request.user,
        )
    workorders = list(qs.order_by("-opened_at"))
    today = timezone.localdate().strftime("%Y%m%d")
    rows = [_wo_export_row(wo) for wo in workorders]

    if fmt == "pdf":
        pdf_bytes = _report_table_pdf(title="Interventi / Work Orders", headers=_WO_EXPORT_HEADERS, rows=rows)
        resp = HttpResponse(pdf_bytes, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="workorders_{today}.pdf"'
        return resp

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Interventi"
    _xl_write_sheet(ws, _WO_EXPORT_HEADERS, rows)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = HttpResponse(buf.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="workorders_{today}.xlsx"'
    return resp


# ---------------------------------------------------------------------------
# EXPORT: work machine list PDF (XLSX già presente)
# ---------------------------------------------------------------------------

@login_required
def work_machine_export_pdf(request: HttpRequest) -> HttpResponse:
    scope = request.GET.get("scope", "filtered")
    if scope == "full":
        qs = Asset.objects.filter(asset_type__in=PRODUCTION_ASSET_TYPES).select_related("work_machine")
    else:
        form = WorkMachineFilterForm(request.GET or None)
        qs = Asset.objects.filter(asset_type__in=PRODUCTION_ASSET_TYPES).select_related("work_machine")
        if form.is_valid():
            q = _clean_string(form.cleaned_data.get("q"))
            reparto = _clean_string(form.cleaned_data.get("reparto"))
            status_f = _clean_string(form.cleaned_data.get("status"))
            cnc_only = bool(form.cleaned_data.get("cnc_only"))
            five_axes_only = bool(form.cleaned_data.get("five_axes_only"))
            tcr_only = bool(form.cleaned_data.get("tcr_only"))
            if q:
                qs = qs.filter(
                    Q(asset_tag__icontains=q) | Q(name__icontains=q) | Q(reparto__icontains=q)
                    | Q(manufacturer__icontains=q) | Q(model__icontains=q) | Q(serial_number__icontains=q)
                )
            if reparto:
                qs = qs.filter(reparto__icontains=reparto)
            if status_f:
                qs = qs.filter(status=status_f)
            if cnc_only:
                qs = qs.filter(work_machine__cnc_controlled=True)
            if five_axes_only:
                qs = qs.filter(work_machine__five_axes=True)
            if tcr_only:
                qs = qs.filter(work_machine__tcr_enabled=True)

    machines = list(qs.order_by("reparto", "name", "asset_tag"))
    headers = ["Tag", "Nome", "Reparto", "Stato", "Produttore", "Anno", "CNC", "5 assi", "TCR", "X mm", "Y mm", "Z mm"]
    rows = []
    for a in machines:
        wm = getattr(a, "work_machine", None)
        rows.append([
            a.asset_tag or "", a.name or "", a.reparto or "", a.get_status_display(),
            a.manufacturer or "",
            str(wm.year) if wm and wm.year else "",
            "Sì" if wm and wm.cnc_controlled else "No",
            "Sì" if wm and wm.five_axes else "No",
            "Sì" if wm and wm.tcr_enabled else "No",
            str(wm.x_mm) if wm and wm.x_mm else "",
            str(wm.y_mm) if wm and wm.y_mm else "",
            str(wm.z_mm) if wm and wm.z_mm else "",
        ])
    today = timezone.localdate().strftime("%Y%m%d")
    pdf_bytes = _report_table_pdf(title="Macchine di lavoro", headers=headers, rows=rows)
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="macchine_{today}.pdf"'
    return resp


@login_required
def work_machine_export_excel(request: HttpRequest) -> HttpResponse:
    """Esporta la lista macchine filtrata in formato Excel (.xlsx)."""
    import io
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment

    from core.excel_export import write_cell, write_row

    form = WorkMachineFilterForm(request.GET or None)
    machines_qs = Asset.objects.filter(asset_type__in=PRODUCTION_ASSET_TYPES).select_related("work_machine")

    if form.is_valid():
        q = _clean_string(form.cleaned_data.get("q"))
        reparto = _clean_string(form.cleaned_data.get("reparto"))
        status = _clean_string(form.cleaned_data.get("status"))
        cnc_only = bool(form.cleaned_data.get("cnc_only"))
        five_axes_only = bool(form.cleaned_data.get("five_axes_only"))
        tcr_only = bool(form.cleaned_data.get("tcr_only"))

        if q:
            machines_qs = machines_qs.filter(
                Q(asset_tag__icontains=q)
                | Q(name__icontains=q)
                | Q(reparto__icontains=q)
                | Q(manufacturer__icontains=q)
                | Q(model__icontains=q)
                | Q(serial_number__icontains=q)
            )
        if reparto:
            machines_qs = machines_qs.filter(reparto__icontains=reparto)
        if status:
            machines_qs = machines_qs.filter(status=status)
        if cnc_only:
            machines_qs = machines_qs.filter(work_machine__cnc_controlled=True)
        if five_axes_only:
            machines_qs = machines_qs.filter(work_machine__five_axes=True)
        if tcr_only:
            machines_qs = machines_qs.filter(work_machine__tcr_enabled=True)

    machines = list(machines_qs.order_by("reparto", "name", "asset_tag"))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Macchine officina"

    headers = [
        "Tag", "Nome macchina", "Reparto", "Stato asset",
        "Produttore", "Modello", "N. seriale",
        "Anno", "TMC (mesi)", "Prossima manutenzione",
        "CNC", "5 assi", "TCR",
        "Cursa X (mm)", "Corsa Y (mm)", "Corsa Z (mm)",
        "Diametro (mm)", "Mandrino (mm)", "Pressione (bar)", "Accuracy",
    ]

    header_fill = PatternFill(fill_type="solid", fgColor="2563EB")
    header_font = Font(bold=True, color="FFFFFF", name="Calibri", size=10)

    for col_idx, header in enumerate(headers, 1):
        cell = write_cell(ws, 1, col_idx, header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    ws.row_dimensions[1].height = 20

    for row_idx, asset in enumerate(machines, 2):
        wm = getattr(asset, "work_machine", None)
        values = [
            asset.asset_tag,
            asset.name,
            asset.reparto or "",
            asset.get_status_display(),
            asset.manufacturer or "",
            asset.model or "",
            asset.serial_number or "",
            wm.year if wm and wm.year else "",
            wm.tmc if wm and wm.tmc else "",
            wm.next_maintenance_date.strftime("%d-%m-%Y") if wm and wm.next_maintenance_date else "",
            "Sì" if wm and wm.cnc_controlled else "No",
            "Sì" if wm and wm.five_axes else "No",
            "Sì" if wm and wm.tcr_enabled else "No",
            wm.x_mm if wm and wm.x_mm else "",
            wm.y_mm if wm and wm.y_mm else "",
            wm.z_mm if wm and wm.z_mm else "",
            wm.diameter_mm if wm and wm.diameter_mm else "",
            wm.spindle_mm if wm and wm.spindle_mm else "",
            str(wm.pressure_bar) if wm and wm.pressure_bar else "",
            wm.accuracy_from if wm and wm.accuracy_from else "",
        ]
        write_row(ws, row_idx, values)

    for col in ws.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=0)
        ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 3, 10), 45)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    today_str = timezone.localdate().strftime("%Y%m%d")
    filename = f"macchine_officina_{today_str}.xlsx"
    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _default_man_category(categorie: list[tuple[str, str]]) -> str:
    """Categoria usata quando chi segnala non ne sceglie una.

    Nessuna impostazione nuova: «Generica» se e' fra le categorie MAN attive, poi
    «Altro Manutenzione», altrimenti la prima attiva (``get_categorie`` ripiega
    comunque sull'elenco predefinito, quindi un valore c'e' sempre).
    """
    codes = [code for code, _label in categorie]
    for preferred in ("GENERICA", "ALTRO_MAN"):
        if preferred in codes:
            return preferred
    return codes[0] if codes else "GENERICA"


# Priorita' proposte a chi segnala dal campo: tre scelte grandi, non quattro.
# «Urgente» resta accettata dal POST (link o form vecchi) ma non si propone: chi
# segnala da telefono dice quanto e' grave, l'urgenza la decide la manutenzione.
QUICK_REPORT_PRIORITIES = (("BASSA", "Bassa"), ("MEDIA", "Media"), ("ALTA", "Alta"))
QUICK_REPORT_MAX_PHOTOS = 3
QUICK_REPORT_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png"}
QUICK_REPORT_PHOTO_MIMES = {"image/jpeg", "image/png"}


@login_required
def asset_quick_report(request: HttpRequest) -> HttpResponse:
    """P3.2 — Segnalazione guasto per operatori non-admin (anche da telefono, dal QR).

    Crea un Ticket MAN con asset, descrizione, priorita' e fino a tre foto. Con
    ``?asset=<id>`` l'asset e' fissato (intestazione, niente elenco); con
    ``?from=qr`` la pagina e' quella minimale della landing QR, senza la shell del
    modulo. Il login resta obbligatorio anche arrivando dal QR pubblico.
    """
    from tickets.allegati import AllegatoError, carica_allegato, qr_rate_limited, registra_caricamento
    from tickets.models import TipoTicket, PrioritaTicket, Ticket, get_categorie

    from_qr = _clean_string(request.GET.get("from") or request.POST.get("from")).lower() == "qr"
    raw_asset = request.GET.get("asset") or request.POST.get("fixed_asset")
    fixed_asset = None
    if raw_asset:
        # Stessa regola della landing QR: un asset inesistente non si segnala.
        fixed_asset = get_object_or_404(Asset.objects.select_related("asset_category"), pk=_as_int(raw_asset, default=0))

    asset_choices = []
    if fixed_asset is None:
        # Asset selezionabili: macchine e asset di produzione (no IT puro)
        asset_choices = list(
            Asset.objects
            .filter(status=Asset.STATUS_IN_USE)
            .exclude(asset_type__in=IT_DEVICE_TYPES)
            .order_by("reparto", "name", "asset_tag")
            .values("id", "asset_tag", "name", "reparto")
        )

    categorie_man = get_categorie(TipoTicket.MAN)
    default_categoria = _default_man_category(categorie_man)
    valid_priorities = dict(PrioritaTicket.choices)

    error: str = ""
    success_ticket = None
    photo_notes: list[str] = []

    if request.method == "POST":
        asset_id = fixed_asset.id if fixed_asset is not None else _as_int(request.POST.get("asset_id"), default=0)
        asset_libera = "" if fixed_asset is not None else _clean_string(request.POST.get("asset_descrizione_libera"))
        categoria = _clean_string(request.POST.get("categoria"))
        titolo = _clean_string(request.POST.get("titolo"))
        descrizione = _clean_string(request.POST.get("descrizione"))
        priorita = _clean_string(request.POST.get("priorita")) or PrioritaTicket.MEDIA
        incide_sicurezza = request.POST.get("incide_sicurezza") == "1"
        photos = request.FILES.getlist("foto")

        if not titolo or not descrizione:
            error = "Titolo e descrizione sono obbligatori."
        elif not asset_id and not asset_libera:
            error = "Seleziona un asset o descrivi il punto di intervento."
        elif len(photos) > QUICK_REPORT_MAX_PHOTOS:
            error = f"Puoi allegare al massimo {QUICK_REPORT_MAX_PHOTOS} foto."
        else:
            if priorita not in valid_priorities:
                priorita = PrioritaTicket.MEDIA
            if categoria not in {code for code, _label in categorie_man}:
                categoria = default_categoria

            asset_obj = fixed_asset
            if asset_obj is None and asset_id:
                asset_obj = Asset.objects.filter(pk=asset_id).only("id").first()

            # Identità richiedente dal legacy user o dall'utente Django. UserExtraInfo e'
            # in core.models (importato in testa): l'import da anagrafica.models falliva
            # e ogni invio rispondeva 500.
            legacy_user = getattr(request, "legacy_user", None)
            if legacy_user is None:
                try:
                    extra = UserExtraInfo.objects.filter(user=request.user).select_related("user").first()
                    legacy_user = extra
                except Exception:
                    legacy_user = None

            if legacy_user and hasattr(legacy_user, "nome"):
                req_name = (_clean_string(getattr(legacy_user, "nome", "")) or request.user.get_full_name() or request.user.get_username())
                req_email = (_clean_string(getattr(legacy_user, "email", "")) or request.user.email or "").lower()
                req_legacy_id = getattr(legacy_user, "id", None)
            else:
                req_name = request.user.get_full_name() or request.user.get_username()
                req_email = (request.user.email or "").lower()
                req_legacy_id = None

            ticket = Ticket(
                tipo=TipoTicket.MAN,
                titolo=titolo,
                descrizione=descrizione,
                categoria=categoria,
                priorita=priorita,
                incide_sicurezza=incide_sicurezza,
                asset=asset_obj,
                asset_descrizione_libera=asset_libera if not asset_obj else "",
                richiedente_nome=req_name,
                richiedente_email=req_email,
                richiedente_legacy_user_id=req_legacy_id,
                include_in_maintenance_register=True,
            )
            try:
                ticket.save()
            except Exception as exc:
                error = f"Errore nella creazione del ticket: {exc}"
            else:
                # Foto: il ticket esiste gia'. Una foto rifiutata (formato, peso) si
                # scarta e si dice quale, senza perdere la segnalazione.
                saved_photos = []
                if photos and asset_obj is not None and qr_rate_limited(request, asset_obj.id):
                    photo_notes.append("Troppi invii ravvicinati: le foto non sono state salvate, la segnalazione si'.")
                    photos = []
                for photo in photos:
                    try:
                        saved_photos.append(
                            carica_allegato(
                                ticket,
                                photo,
                                caricato_da_nome=req_name,
                                caricato_da_email=req_email,
                                descrizione="Foto della segnalazione",
                                allowed_extensions=QUICK_REPORT_PHOTO_EXTENSIONS,
                                allowed_mimes=QUICK_REPORT_PHOTO_MIMES,
                            )
                        )
                    except AllegatoError as exc:
                        photo_notes.append(f"Foto «{getattr(photo, 'name', 'senza nome')}» scartata: {exc}")
                if saved_photos:
                    registra_caricamento(ticket, saved_photos)
                log_action(
                    request,
                    "asset_quick_report_create",
                    "assets",
                    {
                        "ticket_id": ticket.id,
                        "ticket_numero": ticket.numero_ticket,
                        "asset_id": asset_id,
                        "categoria": categoria,
                        "priorita": priorita,
                        "foto": len(saved_photos),
                        "da_qr": from_qr,
                    },
                )
                success_ticket = ticket

    landing_url = (
        reverse("assets:asset_qr_landing", kwargs={"asset_tag": fixed_asset.asset_tag}) if fixed_asset is not None else ""
    )
    again_url = reverse("assets:asset_quick_report")
    if fixed_asset is not None:
        again_url += f"?asset={fixed_asset.id}" + ("&from=qr" if from_qr else "")
    context = {
        "page_title": "Segnala un problema",
        "fixed_asset": fixed_asset,
        "asset_choices": asset_choices,
        "categorie_man": categorie_man,
        "default_categoria": default_categoria,
        "priorita_choices": QUICK_REPORT_PRIORITIES,
        "max_photos": QUICK_REPORT_MAX_PHOTOS,
        "error": error,
        "success_ticket": success_ticket,
        "success_ticket_id": success_ticket.id if success_ticket is not None else None,
        "photo_notes": photo_notes,
        "from_qr": from_qr,
        "landing_url": landing_url,
        "again_url": again_url,
    }
    if from_qr:
        # Come la landing QR: pagina minimale, niente sidebar/shell del modulo.
        return render(request, "assets/pages/asset_quick_report_qr.html", context)
    return render(
        request,
        "assets/pages/asset_quick_report.html",
        {**context, **_assets_shell_context(request, rows=25)},
    )


@login_required
def reports_dashboard(request: HttpRequest) -> HttpResponse:
    if "scope" not in request.GET:
        query = request.GET.copy()
        query["scope"] = "production"
        return redirect(f"{reverse('assets:reports')}?{query.urlencode()}")

    now = timezone.now()
    today = timezone.localdate()
    period_start = now - timedelta(days=90)
    reports_scope = _normalize_reports_scope(request.GET.get("scope"))
    reports_context = _reports_scope_context(reports_scope)
    report_asset_types = list(reports_context["asset_types"])
    scoped_asset_qs = Asset.objects.filter(asset_type__in=report_asset_types).select_related("asset_category")
    # Budget e costi dagli OdL; lo stato delle manutenzioni dalle occorrenze,
    # come Scadenzario e KPI (il vecchio motore a regole non entra piu' nel conto).
    maintenance_report_kpis = build_maintenance_report_kpis(
        asset_queryset=scoped_asset_qs,
        schedule_rows=[],
        today=today,
    )
    planned = _planned_maintenance_status(scoped_asset_qs, today)
    pm_kpi = planned["kpi"]
    budget_kpi = maintenance_report_kpis["budget"]
    budget_rows = []
    for row in budget_kpi["rows"][:8]:
        row = dict(row)
        category = row.get("category")
        category_id = getattr(category, "id", 0)
        row["workorders_url"] = (
            _workorder_list_page_url(status=WorkOrder.STATUS_DONE, category=category_id)
            if category_id
            else ""
        )
        budget_rows.append(row)

    open_workorders = WorkOrder.objects.select_related("asset", "supplier").filter(
        status=WorkOrder.STATUS_OPEN,
        asset__asset_type__in=report_asset_types,
    )
    late_open_workorders = open_workorders.filter(opened_at__lt=now - timedelta(days=30)).order_by("opened_at")
    open_workorder_rows: list[dict[str, object]] = []
    for workorder in open_workorders.order_by("opened_at", "id")[:12]:
        opened_at = workorder.opened_at
        opened_on = timezone.localtime(opened_at).date() if timezone.is_aware(opened_at) else opened_at.date()
        open_days = max((today - opened_on).days, 0)
        open_workorder_rows.append(
            {
                "workorder": workorder,
                "open_days": open_days,
                "is_late": open_days > 30,
            }
        )
    recent_done_workorders = (
        WorkOrder.objects.select_related(
            "asset",
            "asset__asset_category",
            "supplier",
            "assistance_contract",
        )
        .filter(status=WorkOrder.STATUS_DONE, closed_at__gte=period_start)
        .filter(asset__asset_type__in=report_asset_types)
        .order_by("-closed_at", "-id")
    )
    if reports_context["maintenance_month_enabled"]:
        maintenance_month_dataset = _build_work_machine_maintenance_month_dataset(
            month_value=request.GET.get("month"),
            today=today,
        )
    else:
        month_start = _month_start_from_value(request.GET.get("month"), today=today)
        month_end = _month_end(month_start)
        maintenance_month_dataset = {
            "rows": [],
            "total_count": 0,
            "overdue_count": 0,
            "warning_count": 0,
            "ok_count": 0,
            "month_code": month_start.strftime("%Y-%m"),
            "month_label": _month_label(month_start),
            "period_label": f'{month_start.strftime("%d-%m-%Y")} - {month_end.strftime("%d-%m-%Y")}',
        }
    done_rows = list(recent_done_workorders)
    total_cost = sum((workorder.resolved_total_cost_eur or Decimal("0")) for workorder in done_rows)
    duration_values = [
        workorder.intervention_duration_minutes
        for workorder in done_rows
        if workorder.intervention_duration_minutes is not None
    ]
    avg_duration_minutes = round(sum(duration_values) / len(duration_values), 1) if duration_values else None
    avg_downtime_minutes = (
        WorkOrder.objects.filter(
            status=WorkOrder.STATUS_DONE,
            closed_at__gte=period_start,
            asset__asset_type__in=report_asset_types,
        )
        .aggregate(value=Avg("downtime_minutes"))
        .get("value")
    )
    covered_count = sum(1 for workorder in done_rows if workorder.covered_by_contract)
    uncovered_count = len(done_rows) - covered_count

    def _summary_rows(key_builder, label_builder):
        grouped: dict[tuple, dict[str, object]] = {}
        for workorder in done_rows:
            key = key_builder(workorder)
            bucket = grouped.setdefault(
                key,
                {
                    "label": label_builder(workorder),
                    "count": 0,
                    "cost": Decimal("0"),
                    "covered_count": 0,
                },
            )
            bucket["count"] += 1
            bucket["cost"] += workorder.resolved_total_cost_eur or Decimal("0")
            if workorder.covered_by_contract:
                bucket["covered_count"] += 1
        rows = list(grouped.values())
        rows.sort(key=lambda row: (-int(row["cost"] > 0), -row["cost"], -row["count"], str(row["label"]).casefold()))
        return rows

    asset_summary_rows = _summary_rows(
        lambda workorder: (workorder.asset_id,),
        lambda workorder: f"{workorder.asset.asset_tag} - {workorder.asset.name}",
    )[:8]
    category_summary_rows = _summary_rows(
        lambda workorder: (getattr(workorder.asset, "asset_category_id", 0),),
        lambda workorder: (
            getattr(getattr(workorder.asset, "asset_category", None), "label", "")
            or "Senza categoria"
        ),
    )[:8]
    supplier_summary_rows = _summary_rows(
        lambda workorder: (workorder.supplier_id or 0,),
        lambda workorder: str(workorder.supplier) if workorder.supplier_id else "Fornitore non indicato",
    )[:8]

    overdue_rows = planned["overdue"]
    warning_rows = planned["warning"]
    upcoming_rows = planned["ok"]
    missing_rows = planned["missing"]
    critical_count = len(overdue_rows) + len(warning_rows) + len(missing_rows)
    critical_rows: list[dict[str, object]] = []
    for row in overdue_rows + warning_rows + missing_rows:
        asset = row["asset"]
        occurrence = row["occurrence"]
        critical_rows.append(
            {
                "asset": asset,
                "asset_detail_url": reverse("assets:asset_view", kwargs={"id": asset.id}),
                "effective_intervention_template": occurrence.plan if occurrence else None,
                "schedule_label": row["state"]["label"],
                "schedule_badge_class": {"overdue": "danger", "warning": "warning"}.get(row["state"]["status"], "muted"),
                "due_date": row["state"]["date"],
                "primary_action": (
                    {"label": "Registra", "url": reverse("assets:occurrence_complete", args=[occurrence.id])}
                    if occurrence
                    else {"label": "Applica un piano", "url": reverse("assets:asset_maintenance_plans", args=[asset.id])}
                ),
            }
        )

    return render(
        request,
        "assets/pages/reports_dashboard.html",
        {
            "page_title": reports_context["title"],
            "reports_scope": reports_context["scope"],
            "reports_page_title": reports_context["title"],
            "reports_page_subtitle": reports_context["subtitle"],
            "maintenance_month_enabled": reports_context["maintenance_month_enabled"],
            "maintenance_month_empty_message": reports_context["empty_month_message"],
            "open_workorders": open_workorders.order_by("opened_at", "id")[:8],
            "open_workorder_rows": open_workorder_rows,
            "late_open_workorders": late_open_workorders[:8],
            "recent_done_workorders": done_rows[:8],
            "asset_summary_rows": asset_summary_rows,
            "category_summary_rows": category_summary_rows,
            "supplier_summary_rows": supplier_summary_rows,
            "critical_rows": critical_rows[:12],
            "overdue_rows": overdue_rows[:8],
            "warning_rows": warning_rows[:8],
            "upcoming_rows": upcoming_rows[:8],
            "open_count": open_workorders.count(),
            "late_count": late_open_workorders.count(),
            "done_recent_count": len(done_rows),
            "total_cost": total_cost,
            "avg_duration_minutes": avg_duration_minutes,
            "avg_downtime_minutes": round(avg_downtime_minutes, 1) if avg_downtime_minutes is not None else None,
            "covered_count": covered_count,
            "uncovered_count": uncovered_count,
            "critical_count": critical_count,
            "overdue_count": len(overdue_rows),
            "warning_count": len(warning_rows),
            "upcoming_count": len(upcoming_rows),
            "missing_count": len(missing_rows),
            "pm_kpi": pm_kpi,
            "budget_kpi": budget_kpi,
            "budget_rows": budget_rows,
            "open_workorders_url": _workorder_list_page_url(status=WorkOrder.STATUS_OPEN),
            "late_workorders_url": _workorder_list_page_url(status=WorkOrder.STATUS_OPEN, open_age=30),
            "done_workorders_url": _workorder_list_page_url(status=WorkOrder.STATUS_DONE),
            "maintenance_schedule_due_url": f"{reverse('assets:maintenance_scadenze')}?window=overdue",
            "maintenance_schedule_missing_url": reverse("assets:maintenance_coverage"),
            "maintenance_month_rows": maintenance_month_dataset["rows"][:10],
            "maintenance_month_count": maintenance_month_dataset["total_count"],
            "maintenance_month_overdue_count": maintenance_month_dataset["overdue_count"],
            "maintenance_month_warning_count": maintenance_month_dataset["warning_count"],
            "maintenance_month_ok_count": maintenance_month_dataset["ok_count"],
            "maintenance_month_label": maintenance_month_dataset["month_label"],
            "maintenance_month_period_label": maintenance_month_dataset["period_label"],
            "maintenance_month_code": maintenance_month_dataset["month_code"],
            "maintenance_month_pdf_base_url": reverse("assets:work_machine_maintenance_month_pdf"),
            "maintenance_month_pdf_url": _work_machine_maintenance_month_pdf_url(
                month_code=str(maintenance_month_dataset["month_code"])
            ),
            "maintenance_schedule_url": reverse("assets:maintenance_schedule"),
            "assistance_contracts_url": reverse("assets:assistance_contract_list"),
            "report_templates_manage_url": (
                reverse("assets:report_template_admin")
                if _is_assets_admin(request)
                else ""
            ),
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


@login_required
def asset_report_pdf(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:asset_list")
    asset = get_object_or_404(
        Asset.objects.select_related("asset_category", "it_details", "work_machine")
        .prefetch_related(
            "workorders",
            "documents",
            "tickets",
            "periodic_verifications",
            "periodic_verifications__supplier",
            "asset_category__category_fields",
        ),
        pk=id,
    )
    active_template = _active_asset_report_template(AssetReportTemplate.REPORT_ASSET_DETAIL)
    snapshot = _build_asset_report_snapshot(asset)
    pdf_bytes = render_asset_report_pdf(
        asset,
        snapshot,
        template_name=active_template.name if active_template else "",
    )
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{asset.asset_tag or "asset"}-report.pdf"'
    return response


@login_required
def asset_detail_export_xlsx(request: HttpRequest, id: int) -> HttpResponse:
    import openpyxl
    import openpyxl.styles as xlst

    from core.excel_export import write_cell

    asset = get_object_or_404(
        Asset.objects.select_related("asset_category", "it_details", "work_machine"),
        pk=id,
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Scheda asset"

    hfill = xlst.PatternFill(fill_type="solid", fgColor="2563EB")
    hfont = xlst.Font(bold=True, color="FFFFFF", name="Calibri", size=10)
    sfill = xlst.PatternFill(fill_type="solid", fgColor="EFF6FF")
    sfont = xlst.Font(bold=True, name="Calibri", size=9)
    kfont = xlst.Font(bold=True, name="Calibri", size=9)
    vfont = xlst.Font(name="Calibri", size=9)

    r = 1
    for ci, h in enumerate(["Attributo", "Valore"], 1):
        cell = write_cell(ws, r, ci, h)
        cell.fill = hfill
        cell.font = hfont
        cell.alignment = xlst.Alignment(horizontal="center", vertical="center")
    r += 1

    def _sec(label):
        nonlocal r
        c = write_cell(ws, r, 1, label)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
        c.fill = sfill
        c.font = sfont
        r += 1

    def _kv(key, val):
        nonlocal r
        write_cell(ws, r, 1, key).font = kfont
        write_cell(ws, r, 2, str(val) if val is not None else "").font = vfont
        r += 1

    _sec("Anagrafica")
    _kv("Tag", asset.asset_tag)
    _kv("Nome", asset.name)
    _kv("Tipo", asset.get_asset_type_display())
    _kv("Categoria", asset.asset_category.label if asset.asset_category_id else "")
    _kv("Reparto", asset.reparto)
    _kv("Stato", asset.get_status_display())
    _kv("Produttore", asset.manufacturer)
    _kv("Modello", asset.model)
    _kv("Matricola", asset.serial_number)
    _kv("Note", asset.notes)

    _sec("Assegnazione")
    _kv("Assegnato a", asset.assignment_to)
    _kv("Reparto assegnazione", asset.assignment_reparto)
    _kv("Ubicazione", asset.assignment_location)

    it = getattr(asset, "it_details", None)
    if it:
        _sec("Dettagli IT")
        _kv("OS", it.os)
        _kv("CPU", it.cpu)
        _kv("RAM", it.ram)
        _kv("Disco", it.disco)
        _kv("Dominio", "Sì" if it.domain_joined else "No")
        _kv("EDR", "Sì" if it.edr_enabled else "No")
        _kv("2FA Office", "Sì" if it.office_2fa_enabled else "No")

    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 55

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    tag = asset.asset_tag or str(asset.pk)
    today = timezone.localdate().strftime("%Y%m%d")
    resp = HttpResponse(buf.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="asset_{tag}_{today}.xlsx"'
    return resp


@login_required
def report_template_admin(request: HttpRequest) -> HttpResponse:
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo gestire i template report.")
        return redirect("assets:reports")

    report_tables_ready = _model_table_exists(AssetReportDefinition) and _model_table_exists(AssetReportTemplate)
    _ensure_default_asset_report_definitions()

    if request.method == "POST":
        if not report_tables_ready:
            messages.error(request, "Le tabelle dei template report non sono ancora disponibili. Esegui prima le migrazioni.")
            return redirect("assets:report_template_admin")
        action = _clean_string(request.POST.get("action"))
        redirect_url = reverse("assets:report_template_admin")
        definition_map = _asset_report_definition_map()

        try:
            if action == "create_report_definition":
                code = slugify(request.POST.get("code", ""))[:80]
                label = _clean_string(request.POST.get("label"))[:120]
                description = _clean_string(request.POST.get("description"))[:255]
                sort_order = _as_int(request.POST.get("sort_order"), default=100)
                if not code or not label:
                    messages.error(request, "Inserisci codice e nome del report.")
                    return redirect(redirect_url)
                if AssetReportDefinition.objects.filter(code=code).exists():
                    messages.error(request, "Esiste gia un report con questo codice.")
                    return redirect(redirect_url)
                AssetReportDefinition.objects.create(
                    code=code,
                    label=label,
                    description=description,
                    sort_order=sort_order,
                    is_active=True,
                )
                messages.success(request, f'Report "{label}" creato.')
                return redirect(redirect_url)

            if action == "upload_report_template":
                report_code = _clean_string(request.POST.get("report_code"))
                name = _clean_string(request.POST.get("name"))[:120]
                version = _clean_string(request.POST.get("version"))[:40]
                description = _clean_string(request.POST.get("description"))[:255]
                uploaded_file = request.FILES.get("template_file")

                if report_code not in definition_map:
                    messages.error(request, "Tipo report non valido.")
                    return redirect(redirect_url)
                if not name:
                    messages.error(request, "Inserisci il nome del template.")
                    return redirect(redirect_url)
                if not uploaded_file:
                    messages.error(request, "Seleziona un file template.")
                    return redirect(redirect_url)

                suffix = Path(uploaded_file.name or "").suffix.lower()
                if suffix not in REPORT_TEMPLATE_ALLOWED_EXTENSIONS:
                    messages.error(request, "Formato template non supportato.")
                    return redirect(redirect_url)
                try:
                    validate_extension_and_mime(
                        uploaded_file,
                        allowed_extensions=REPORT_TEMPLATE_ALLOWED_EXTENSIONS,
                        allowed_mimes=REPORT_TEMPLATE_ALLOWED_MIMES,
                        max_bytes=ASSET_DOCUMENT_MAX_BYTES,
                        label="Template",
                    )
                except UploadMimeValidationError as exc:
                    messages.error(request, str(exc))
                    return redirect(redirect_url)
                finally:
                    uploaded_file.seek(0)

                should_activate = bool(request.POST.get("is_active")) or not AssetReportTemplate.objects.filter(
                    report_code=report_code
                ).exists()
                AssetReportTemplate.objects.create(
                    report_code=report_code,
                    name=name,
                    version=version,
                    description=description,
                    file=uploaded_file,
                    original_name=(uploaded_file.name or "")[:255],
                    is_active=should_activate,
                    uploaded_by=request.user,
                )
                messages.success(request, f'Template report "{name}" caricato.')
                return redirect(redirect_url)

            if action == "activate_report_template":
                template_id = _as_int(request.POST.get("template_id"), default=0)
                template = AssetReportTemplate.objects.filter(pk=template_id).first()
                if not template:
                    messages.error(request, "Template report non trovato.")
                    return redirect(redirect_url)
                template.is_active = True
                template.save(update_fields=["is_active", "updated_at"])
                report_label = getattr(definition_map.get(template.report_code), "label", template.report_code)
                messages.success(request, f"Template attivo aggiornato per {report_label.lower()}.")
                return redirect(redirect_url)

            if action == "delete_report_template":
                template_id = _as_int(request.POST.get("template_id"), default=0)
                template = AssetReportTemplate.objects.filter(pk=template_id).first()
                if not template:
                    messages.error(request, "Template report non trovato.")
                    return redirect(redirect_url)
                report_label = getattr(definition_map.get(template.report_code), "label", template.report_code)
                template_name = template.name
                template.delete()
                messages.success(request, f'Template "{template_name}" eliminato ({report_label}).')
                return redirect(redirect_url)

            if action == "delete_report_definition":
                report_id = _as_int(request.POST.get("report_definition_id"), default=0)
                definition = AssetReportDefinition.objects.filter(pk=report_id).first()
                if not definition:
                    messages.error(request, "Report non trovato.")
                    return redirect(redirect_url)
                if definition.code in {
                    AssetReportTemplate.REPORT_ASSET_DETAIL,
                    AssetReportTemplate.REPORT_WORK_MACHINE_MAINTENANCE,
                }:
                    messages.error(request, "I report base non possono essere eliminati.")
                    return redirect(redirect_url)
                AssetReportTemplate.objects.filter(report_code=definition.code).delete()
                report_label = definition.label
                definition.delete()
                messages.success(request, f'Report "{report_label}" eliminato.')
                return redirect(redirect_url)
        except DatabaseError:
            messages.error(request, "Le tabelle dei template report non sono ancora disponibili. Esegui prima le migrazioni.")
            return redirect(redirect_url)

    return render(
        request,
        "assets/pages/report_template_admin.html",
        {
            "page_title": "Gestione template report",
            "report_template_groups": _report_templates_grouped(),
            "report_template_choices": [
                (row.code, row.label) for row in _ensure_default_asset_report_definitions() if row.is_active
            ],
            "report_definitions": _ensure_default_asset_report_definitions(),
            "report_template_extensions": ", ".join(sorted(REPORT_TEMPLATE_ALLOWED_EXTENSIONS)),
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


@legacy_admin_or_acl_required("assets", "admin_assets")
def gestione_admin(request: HttpRequest) -> HttpResponse:
    """Pagina di gestione interna Assets — admin oppure permesso ACL esplicito.

    La voce di menu si accende gia' su ``admin_assets`` (vedi
    ``can_gestione_admin``): il gate deve leggere gli stessi permessi, altrimenti
    la voce compare ma la pagina risponde 403.
    """

    # --- Statistiche ---
    total_assets = Asset.objects.count()
    assets_by_status = dict(
        Asset.objects.values_list("status").annotate(n=Count("id")).order_by()
    )
    assets_by_type = list(
        Asset.objects.values("asset_type").annotate(n=Count("id")).order_by("-n")
    )
    total_wo = WorkOrder.objects.count()
    wo_by_status = dict(
        WorkOrder.objects.values_list("status").annotate(n=Count("id")).order_by()
    )

    # --- Configurazione: AssetListOption per campo ---
    list_options = {}
    for field_key, _ in AssetListOption.FIELD_CHOICES:
        list_options[field_key] = list(
            AssetListOption.objects.filter(field_key=field_key).order_by("sort_order", "value")
        )
    custom_fields = list(AssetCustomField.objects.all())
    default_label_template = _get_default_asset_label_template()
    type_template_map = {
        row.asset_type: row
        for row in AssetLabelTemplate.objects.filter(
            scope=AssetLabelTemplate.SCOPE_ASSET_TYPE,
            asset__isnull=True,
        )
    }
    asset_override_templates_qs = (
        AssetLabelTemplate.objects.filter(scope=AssetLabelTemplate.SCOPE_ASSET, asset__isnull=False)
        .select_related("asset")
        .order_by("asset__name", "asset__asset_tag")
    )
    asset_override_template_count = asset_override_templates_qs.count()
    asset_override_templates = list(asset_override_templates_qs[:30])
    asset_override_templates_limited = asset_override_template_count > len(asset_override_templates)
    asset_counts_by_type = {
        row["asset_type"]: row["n"]
        for row in Asset.objects.values("asset_type").annotate(n=Count("id")).order_by()
    }
    label_type_rows = []
    for asset_type_code, asset_type_label in Asset.TYPE_CHOICES:
        scoped_template = type_template_map.get(asset_type_code)
        effective_template = scoped_template or default_label_template
        label_type_rows.append(
            {
                "asset_type": asset_type_code,
                "asset_type_label": asset_type_label,
                "asset_count": asset_counts_by_type.get(asset_type_code, 0),
                "template": scoped_template,
                "effective_template": effective_template,
                "designer_url": reverse("assets:asset_label_designer") + f"?scope=asset_type&asset_type={asset_type_code}",
                "uses_default": scoped_template is None,
            }
        )
    sidebar_buttons = list(AssetSidebarButton.objects.select_related("parent").order_by("section", "sort_order", "label", "id"))
    sidebar_parent_choices = _sidebar_parent_choices()
    sidebar_target_suggestions, sidebar_active_match_suggestions = _sidebar_input_suggestions()
    sidebar_target_labels = {row["value"]: row["label"] for row in sidebar_target_suggestions}
    for sidebar_item in sidebar_buttons:
        sidebar_item.label = _ui_label(sidebar_item.label)
        sidebar_item.target_label = _sidebar_target_label(sidebar_item.target_url, sidebar_target_labels)
    for parent_item in sidebar_parent_choices:
        parent_item.label = _ui_label(parent_item.label)

    # --- Azioni POST sulla configurazione ---
    if request.method == "POST":
        branding_response = handle_module_branding_post(
            request,
            module_key="assets",
            redirect_to=request.get_full_path() or f"{reverse('assets:gestione_admin')}?tab=config",
            audit_module="assets",
            legacy_logo_keys=("assets_logo_image",),
            sync_legacy_logo_keys=("assets_logo_image",),
            fallback_label="Assets",
        )
        if branding_response is not None:
            return branding_response
        action = request.POST.get("action")
        config_redirect = redirect(f"{reverse('assets:gestione_admin')}?tab=config")
        category_redirect = redirect(f"{reverse('assets:gestione_admin')}?tab=categorie")
        if action in DOCUMENT_FOLDER_ACTIONS:
            ok, text = _handle_asset_document_folder_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            # Torna sulla categoria da cui e' partita l'azione: il ``cat`` tiene
            # aperto il <details> e l'ancora riporta la pagina allo stesso punto.
            folder_focus = _as_int(request.POST.get("cat_focus"), default=0)
            folder_url = f"{reverse('assets:gestione_admin')}?tab=cartelle"
            if folder_focus:
                folder_url += f"&cat={folder_focus}#cat-{folder_focus}"
            return redirect(folder_url)

        if action == "add_list_option":
            fk = request.POST.get("field_key", "").strip()
            val = request.POST.get("value", "").strip()
            if fk and val:
                AssetListOption.objects.get_or_create(field_key=fk, value=val)
                log_action(request, "add_list_option", "assets", {"field_key": fk, "value": val})
            return config_redirect

        if action == "delete_list_option":
            opt_id = _as_int(request.POST.get("opt_id"))
            if opt_id:
                AssetListOption.objects.filter(pk=opt_id).delete()
                log_action(request, "delete_list_option", "assets", {"opt_id": opt_id})
            return config_redirect

        if action == "add_custom_field":
            code = slugify(request.POST.get("code", ""))
            label = request.POST.get("label", "").strip()
            ftype = request.POST.get("field_type", AssetCustomField.TYPE_TEXT)
            if code and label:
                AssetCustomField.objects.get_or_create(code=code, defaults={"label": label, "field_type": ftype})
                log_action(request, "add_custom_field", "assets", {"code": code})
            return config_redirect

        if action == "delete_custom_field":
            cf_id = _as_int(request.POST.get("cf_id"))
            if cf_id:
                AssetCustomField.objects.filter(pk=cf_id).delete()
                log_action(request, "delete_custom_field", "assets", {"cf_id": cf_id})
            return config_redirect

        if action == "delete_label_template":
            template_id = _as_int(request.POST.get("template_id"))
            template = AssetLabelTemplate.objects.filter(pk=template_id).select_related("asset").first()
            if not template:
                messages.error(request, "Template etichetta non trovato.")
                return config_redirect
            if template.scope == AssetLabelTemplate.SCOPE_DEFAULT:
                messages.error(request, "Il template generale non puo essere eliminato.")
                return config_redirect
            scope_info = template.scope_display_label()
            template.delete()
            log_action(request, "delete_label_template", "assets", {"template_id": template_id, "scope": scope_info})
            messages.success(request, f"Template etichetta rimosso ({scope_info}).")
            return config_redirect

        if action in CATEGORY_ACTIONS:
            ok, text = _handle_asset_category_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return category_redirect

        if action in SIDEBAR_ACTIONS:
            ok, text = _handle_sidebar_button_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return redirect(f"{reverse('assets:gestione_admin')}?tab=sidebar")

        if action == "save_assets_logo":
            logo_file = request.FILES.get("logo_file")
            logo_url = request.POST.get("logo_url", "").strip()
            if logo_file:
                _LOGO_ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".webp"}  # niente SVG (audit A9)
                _LOGO_ALLOWED_MIMES = {"image/png", "image/jpeg", "image/webp"}
                if logo_file.size > 512 * 1024:
                    messages.error(request, "Immagine troppo grande (max 512 KB).")
                    return config_redirect
                try:
                    validate_extension_and_mime(
                        logo_file,
                        allowed_extensions=_LOGO_ALLOWED_EXTS,
                        allowed_mimes=_LOGO_ALLOWED_MIMES,
                        max_bytes=None,
                        label="Logo",
                    )
                except UploadMimeValidationError as exc:
                    messages.error(request, str(exc))
                    return config_redirect
                import os
                from django.core.files.storage import default_storage
                raw_ext = os.path.splitext(logo_file.name)[1].lower()
                ext = raw_ext if raw_ext in _LOGO_ALLOWED_EXTS else ".png"
                save_path = f"assets_logo/logo{ext}"
                if default_storage.exists(save_path):
                    default_storage.delete(save_path)
                saved = default_storage.save(save_path, logo_file)
                final_url = default_storage.url(saved)
                SiteConfig.set("assets_logo_image", final_url, "Logo personalizzato modulo Inventario Assets")
                log_action(request, "save_assets_logo", "assets", {"path": saved})
                messages.success(request, "Logo aggiornato.")
            elif logo_url:
                parsed = urlsplit(logo_url)
                if parsed.scheme not in ("http", "https"):
                    messages.error(request, "L'URL deve iniziare con http:// o https://")
                    return config_redirect
                SiteConfig.set("assets_logo_image", logo_url, "Logo personalizzato modulo Inventario Assets")
                log_action(request, "save_assets_logo_url", "assets", {"url": logo_url})
                messages.success(request, "Logo URL salvato.")
            else:
                messages.error(request, "Seleziona un file o inserisci un URL.")
            return config_redirect

        if action == "remove_assets_logo":
            SiteConfig.set("assets_logo_image", "", "Logo personalizzato modulo Inventario Assets")
            log_action(request, "remove_assets_logo", "assets", {})
            messages.success(request, "Logo personalizzato rimosso.")
            return config_redirect

        if action in FAILURE_CODE_ACTIONS:
            return _handle_failure_code_request(request)
        if action in ("add_categoria_ticket", "toggle_categoria_ticket", "delete_categoria_ticket"):
            from tickets.models import CategoriaTicket, Ticket as _Ticket, TipoTicket
            ticket_redirect = redirect(f"{reverse('assets:gestione_admin')}?tab=ticket")

            if action == "add_categoria_ticket":
                tipo = request.POST.get("cat_tipo", "").strip()
                codice = request.POST.get("cat_codice", "").strip().upper().replace(" ", "_")[:30]
                etichetta = request.POST.get("cat_etichetta", "").strip()[:100]
                ordine = _as_int(request.POST.get("cat_ordine"), default=0)
                if tipo in (TipoTicket.IT, TipoTicket.MAN) and codice and etichetta:
                    _, created = CategoriaTicket.objects.get_or_create(
                        codice=codice,
                        defaults={"tipo": tipo, "etichetta": etichetta, "ordine": ordine, "attivo": True},
                    )
                    if created:
                        log_action(request, "add_categoria_ticket", "tickets", {"tipo": tipo, "codice": codice})
                        messages.success(request, f"Categoria '{etichetta}' aggiunta.")
                    else:
                        messages.warning(request, f"Codice '{codice}' già esistente.")
                else:
                    messages.error(request, "Dati mancanti o non validi.")

            elif action == "toggle_categoria_ticket":
                cat_id = _as_int(request.POST.get("cat_id"))
                if cat_id:
                    cat = CategoriaTicket.objects.filter(pk=cat_id).first()
                    if cat:
                        cat.attivo = not cat.attivo
                        cat.save(update_fields=["attivo"])
                        log_action(request, "toggle_categoria_ticket", "tickets", {"id": cat_id, "attivo": cat.attivo})

            elif action == "delete_categoria_ticket":
                cat_id = _as_int(request.POST.get("cat_id"))
                if cat_id:
                    cat = CategoriaTicket.objects.filter(pk=cat_id).first()
                    if cat:
                        in_use = _Ticket.objects.filter(categoria=cat.codice).exists()
                        if in_use:
                            messages.error(request, f"Impossibile eliminare '{cat.etichetta}': è usata da ticket esistenti. Disattivala.")
                        else:
                            cat.delete()
                            log_action(request, "delete_categoria_ticket", "tickets", {"id": cat_id})
                            messages.success(request, "Categoria eliminata.")

            return ticket_redirect

    # --- Record / tab ---
    q_asset = request.GET.get("q_asset", "").strip()
    q_wo = request.GET.get("q_wo", "").strip()
    tab = request.GET.get("tab", "riepilogo")

    asset_categories = []
    asset_category_fields = []
    asset_category_rows = []
    if tab == "categorie":
        asset_categories = list(
            AssetCategory.objects.select_related("parent").prefetch_related("category_fields").order_by("sort_order", "label", "id")
        )
        asset_category_fields = list(
            AssetCategoryField.objects.select_related("category").order_by(
                "category__sort_order",
                "category__label",
                "sort_order",
                "label",
                "id",
            )
        )
        asset_category_rows = _build_asset_category_admin_rows(asset_categories)

    document_folder_rows = []
    document_folder_categories = []
    if tab == "cartelle":
        document_folder_categories = list(
            AssetCategory.objects.order_by("sort_order", "label", "id")
        )
        document_folder_rows = _build_asset_document_folder_rows(document_folder_categories)

    # --- Categorie ticket (solo tab ticket) ---
    from tickets.models import CategoriaTicket as _CategoriaTicket, TipoTicket as _TipoTicket
    categorie_ticket = (
        list(_CategoriaTicket.objects.order_by("tipo", "ordine", "etichetta"))
        if tab == "ticket" else []
    )

    assets_qs = Asset.objects.order_by("name")
    if q_asset:
        assets_qs = assets_qs.filter(Q(name__icontains=q_asset) | Q(asset_tag__icontains=q_asset))
    assets_page = Paginator(assets_qs, 50).get_page(request.GET.get("asset_page"))

    wo_qs = WorkOrder.objects.select_related("asset").order_by("-opened_at")
    if q_wo:
        wo_qs = wo_qs.filter(Q(title__icontains=q_wo) | Q(asset__name__icontains=q_wo))
    wo_page = Paginator(wo_qs, 50).get_page(request.GET.get("wo_page"))

    # --- Log ---
    audit_entries = AuditLog.objects.filter(modulo="assets").order_by("-created_at")[:100]
    studio_context = _inventory_studio_context(request) if tab == "studio" else {}
    failure_code_context = _failure_code_admin_context(request) if tab == "guasti" else {}

    return render(
        request,
        "assets/pages/gestione_admin.html",
        {
            **get_module_branding_context(
                "assets",
                fallback_label="Assets",
                legacy_logo_keys=("assets_logo_image",),
            ),
            "page_title": "Impostazioni Assets",
            "tab": tab,
            # stats
            "total_assets": total_assets,
            "assets_by_status": assets_by_status,
            "assets_by_type": assets_by_type,
            "total_wo": total_wo,
            "wo_by_status": wo_by_status,
            # config
            "list_options": list_options,
            "list_option_fields": AssetListOption.FIELD_CHOICES,
            "custom_fields": custom_fields,
            "cf_type_choices": AssetCustomField.TYPE_CHOICES,
            # records
            "assets_page": assets_page,
            "wo_page": wo_page,
            "q_asset": q_asset,
            "q_wo": q_wo,
            # log
            "audit_entries": audit_entries,
            "asset_status_labels": dict(Asset.STATUS_CHOICES),
            "asset_type_labels": dict(Asset.TYPE_CHOICES),
            "wo_status_labels": dict(WorkOrder.STATUS_CHOICES),
            "label_template": default_label_template,
            "label_template_default_designer_url": reverse("assets:asset_label_designer") + "?scope=default",
            "label_type_rows": label_type_rows,
            "asset_override_templates": asset_override_templates,
            "asset_override_templates_limited": asset_override_templates_limited,
            "label_template_override_count": asset_override_template_count,
            "sidebar_buttons": sidebar_buttons,
            "sidebar_parent_choices": sidebar_parent_choices,
            "sidebar_section_choices": _ui_choices(AssetSidebarButton.SECTION_CHOICES),
            "sidebar_target_suggestions": sidebar_target_suggestions,
            "sidebar_active_match_suggestions": sidebar_active_match_suggestions,
            "asset_categories": asset_categories,
            "asset_category_rows": asset_category_rows,
            "asset_category_fields": asset_category_fields,
            "asset_category_type_choices": _ui_choices(Asset.TYPE_CHOICES),
            "asset_category_field_type_choices": _ui_choices(AssetCategoryField.TYPE_CHOICES),
            "detail_section_choices": _ui_choices(AssetDetailField.SECTION_CHOICES),
            "detail_format_choices": _ui_choices(AssetDetailField.FORMAT_CHOICES),
            "asset_categories_active_count": sum(1 for row in asset_categories if row.is_active),
            "asset_category_fields_active_count": sum(1 for row in asset_category_fields if row.is_active),
            "categorie_ticket": categorie_ticket,
            "ticket_tipo_choices": _TipoTicket.choices,
            "document_folder_rows": document_folder_rows,
            "document_folder_categories": document_folder_categories,
            "document_folder_base_labels": [label for _, label in AssetDocument.CATEGORY_CHOICES],
            "document_folder_extra_total": sum(
                len(row["extra_folders"]) for row in document_folder_rows
            ),
            "document_folder_focus_id": _as_int(request.GET.get("cat"), default=0),
            **studio_context,
            **failure_code_context,
            **_assets_shell_context(request),
        },
    )


# ---------------------------------------------------------------------------
# Dashboard Assets
# ---------------------------------------------------------------------------

_WIDGET_META: dict[str, dict] = {
    "totale_asset": {"label": "Totale asset", "icon": "package", "color": "blue"},
    "asset_in_uso": {"label": "In uso", "icon": "check-circle", "color": "green"},
    "asset_in_riparazione": {"label": "In riparazione", "icon": "wrench", "color": "orange"},
    "scadenze_scadute": {"label": "Scadenze scadute", "icon": "alert-triangle", "color": "red"},
    "scadenze_30gg": {"label": "Scadenze 30 gg", "icon": "clock", "color": "yellow"},
    "scadenze_90gg": {"label": "Scadenze 90 gg", "icon": "calendar", "color": "slate"},
    "wo_aperte": {"label": "OdL aperte", "icon": "clipboard-list", "color": "blue"},
    "wo_chiuse_mese": {"label": "OdL chiuse (mese)", "icon": "clipboard-check", "color": "green"},
    "verifiche_scadute": {"label": "Piani scaduti", "icon": "shield-alert", "color": "red"},
    "verifiche_30gg": {"label": "Piani in scadenza 30 gg", "icon": "shield-check", "color": "yellow"},
    "asset_per_stato": {"label": "Asset per stato", "icon": "bar-chart", "color": "slate"},
    "asset_per_categoria": {"label": "Asset per categoria", "icon": "layers", "color": "slate"},
}


def _compute_dashboard_kpis(today: date) -> dict:
    """Calcola tutti i valori KPI per la dashboard assets."""
    from django.db.models import Min

    in_30 = today + timedelta(days=30)
    in_90 = today + timedelta(days=90)
    first_day_month = today.replace(day=1)

    total = Asset.objects.exclude(status=Asset.STATUS_RETIRED).count()
    in_uso = Asset.objects.filter(status=Asset.STATUS_IN_USE).count()
    in_repair = Asset.objects.filter(status=Asset.STATUS_IN_REPAIR).count()

    # Scadenze amministrative: registro separato dai piani, senza le copie
    # migrate (``deadline_feed``).
    from ..services import deadline_feed as feed

    admin_dues = feed.administrative_dues(due_to=in_90, exclude_retired=False)
    dl_scadute = sum(1 for due in admin_dues if due.due_date < today)
    dl_30 = sum(1 for due in admin_dues if today <= due.due_date <= in_30)
    dl_90 = sum(1 for due in admin_dues if in_30 < due.due_date <= in_90)

    # OdL
    wo_aperte = WorkOrder.objects.filter(status=WorkOrder.STATUS_OPEN).count()
    wo_chiuse_mese = WorkOrder.objects.filter(
        status=WorkOrder.STATUS_DONE, closed_at__date__gte=first_day_month
    ).count()

    # Verifiche periodiche
    pv_qs = PeriodicVerification.objects.filter(is_active=True, is_legacy=False, next_verification_date__isnull=False)
    pv_scadute = pv_qs.filter(next_verification_date__lt=today).count()
    pv_30 = pv_qs.filter(next_verification_date__gte=today, next_verification_date__lte=in_30).count()

    # Asset per stato
    status_map = dict(Asset.STATUS_CHOICES)
    per_stato_qs = Asset.objects.values("status").annotate(n=Count("id")).order_by("-n")
    per_stato = [
        {"status": r["status"], "label": status_map.get(r["status"], r["status"]), "count": r["n"]}
        for r in per_stato_qs
    ]

    # Asset per categoria (top 10 + "Altro")
    per_cat_qs = list(
        Asset.objects.values("asset_category__id", "asset_category__label")
        .annotate(n=Count("id"))
        .order_by("-n")[:12]
    )
    per_categoria = []
    for r in per_cat_qs:
        per_categoria.append({
            "id": r["asset_category__id"],
            "label": r["asset_category__label"] or "Senza categoria",
            "count": r["n"],
        })

    # Prossime scadenze (lista breve)
    prossime_scadenze = [due for due in admin_dues if today <= due.due_date <= in_30][:8]
    prossime_verifiche = list(
        PeriodicVerification.objects.filter(is_active=True, next_verification_date__gte=today, next_verification_date__lte=in_30)
        .order_by("next_verification_date")[:8]
    )
    scadenze_arretrate = [due for due in admin_dues if due.due_date < today][:8]

    return {
        "totale_asset": total,
        "asset_in_uso": in_uso,
        "asset_in_riparazione": in_repair,
        "scadenze_scadute": dl_scadute,
        "scadenze_30gg": dl_30,
        "scadenze_90gg": dl_90,
        "wo_aperte": wo_aperte,
        "wo_chiuse_mese": wo_chiuse_mese,
        "verifiche_scadute": pv_scadute,
        "verifiche_30gg": pv_30,
        "asset_per_stato": per_stato,
        "asset_per_categoria": per_categoria,
        # dati lista per le card detail
        "prossime_scadenze": prossime_scadenze,
        "prossime_verifiche": prossime_verifiche,
        "scadenze_arretrate": scadenze_arretrate,
    }


def _legacy_asset_dashboard_list_redirect_url(request: HttpRequest) -> str:
    if request.method != "GET" or not request.GET:
        return ""
    legacy_list_query_keys = {"q", "asset_type", "reparto", "vlan", "ip", "rows", "page"}
    if not any(key in request.GET for key in legacy_list_query_keys):
        return ""
    query_string = request.GET.urlencode()
    target_url = reverse("assets:asset_list")
    return f"{target_url}?{query_string}" if query_string else target_url


def _dashboard_workorders(request: HttpRequest, today: date, limit: int = 6) -> dict:
    """OdL aperti per il centro "Da fare": urgenti e in ritardo in testa."""
    from assets.maintenance import get_workorder_overdue_days

    now = timezone.now()
    age_threshold = today - timedelta(days=get_workorder_overdue_days())
    qs = (
        WorkOrder.objects.filter(status=WorkOrder.STATUS_OPEN)
        .exclude(asset__status=Asset.STATUS_RETIRED)
        .select_related("asset", "assigned_to")
    )
    open_rows = list(qs.order_by("opened_at", "id")[:400])

    def _late(wo) -> bool:
        if wo.due_at and wo.due_at < now:
            return True
        return bool(wo.opened_at and wo.opened_at.date() <= age_threshold)

    def _sort_key(wo):
        return (
            0 if wo.priority == WorkOrder.PRIORITY_URGENT else 1,
            0 if _late(wo) else 1,
            wo.opened_at or now,
        )

    items = []
    for wo in sorted(open_rows, key=_sort_key)[:limit]:
        assignee = ""
        if wo.assigned_to_id:
            assignee = wo.assigned_to.get_full_name() or wo.assigned_to.get_username()
        opened = wo.opened_at.date() if wo.opened_at else None
        items.append({
            "id": wo.id,
            "title": wo.title,
            "asset_tag": wo.asset.asset_tag if wo.asset_id else "",
            "asset_name": wo.asset.name if wo.asset_id else "",
            "kind_label": wo.get_kind_display(),
            "is_urgent": wo.priority == WorkOrder.PRIORITY_URGENT,
            "is_late": _late(wo),
            "state_label": wo.operational_state_label,
            "state": wo.operational_state or "",
            "assignee": assignee,
            "is_mine": wo.assigned_to_id == request.user.id,
            "age_days": (today - opened).days if opened else None,
        })
    return {
        "items": items,
        "total": qs.count(),
        "urgent": sum(1 for wo in open_rows if wo.priority == WorkOrder.PRIORITY_URGENT),
        "late": sum(1 for wo in open_rows if _late(wo)),
        "unassigned": sum(1 for wo in open_rows if not wo.assigned_to_id),
        "mine": sum(1 for wo in open_rows if wo.assigned_to_id == request.user.id),
    }


def _dashboard_deadlines(request: HttpRequest, today: date, limit: int = 8) -> dict:
    """Scadenze (piani, amministrative, licenze, contratti) + verifiche periodiche
    entro 30 giorni o gia' scadute, in una lista sola. Sola lettura: le azioni
    puntano alle pagine che gia' le gestiscono."""
    from ..services import deadline_feed as feed

    horizon = today + timedelta(days=30)
    rows: list[dict] = []
    try:
        deadlines = feed.collect(
            start=None,
            end=horizon,
            filters=feed.FeedFilters(kinds=feed.allowed_kinds(request)),
            today=today,
        )
    except Exception:
        deadlines = []
    for dl in deadlines:
        if dl.state == feed.STATE_DONE:
            continue
        rows.append({
            "source": dl.kind,
            "source_label": dl.kind_label,
            "title": dl.title,
            "due_date": dl.due_date,
            "days": (dl.due_date - today).days,
            "is_overdue": dl.due_date < today,
            "asset_tag": dl.asset_tag,
            "asset_name": dl.asset_name or dl.target_label,
            "url": dl.detail_url,
            "action_label": (dl.actions[0]["label"] if dl.actions else "Apri"),
            "work_order_id": dl.work_order_id,
        })
    verifications = PeriodicVerification.objects.filter(
        is_active=True, is_legacy=False, next_verification_date__isnull=False,
        next_verification_date__lte=horizon,
    ).order_by("next_verification_date")[:200]
    pv_url = reverse("assets:periodic_verifications")
    for pv in verifications:
        rows.append({
            "source": "verification",
            "source_label": "Verifica",
            "title": pv.name,
            "due_date": pv.next_verification_date,
            "days": (pv.next_verification_date - today).days,
            "is_overdue": pv.next_verification_date < today,
            "asset_tag": "",
            "asset_name": "",
            "url": pv_url,
            "action_label": "Gestisci",
            "work_order_id": None,
        })
    rows.sort(key=lambda r: (r["due_date"], r["title"]))
    overdue = [r for r in rows if r["is_overdue"]]
    plan_sources = {feed.KIND_ORDINARY, "verification"}
    return {
        "items": rows[:limit],
        "total": len(rows),
        "overdue": len(overdue),
        "due_soon": len(rows) - len(overdue),
        "maintenance_overdue": sum(1 for r in overdue if r["source"] == feed.KIND_ORDINARY),
        "maintenance_due_soon": sum(
            1 for r in rows if r["source"] == feed.KIND_ORDINARY and not r["is_overdue"]
        ),
        # Scadenze dei piani (regole + eventuali piani periodici non ancora
        # convertiti): alimentano i riquadri "Verifiche" della dashboard.
        "plan_overdue": sum(1 for r in overdue if r["source"] in plan_sources),
        "plan_due_soon": sum(1 for r in rows if r["source"] in plan_sources and not r["is_overdue"]),
        "plan_upcoming": [r for r in rows if r["source"] in plan_sources and not r["is_overdue"]][:8],
    }


def _dashboard_launcher(request: HttpRequest, counters: dict) -> list[dict]:
    """Collegamenti alle parti principali del modulo, filtrati con la stessa
    decisione ACL del middleware (fail-closed): non si mostrano porte chiuse."""
    from core.middleware import acl_allows_path

    tiles = [
        ("inventory", "Inventario", "Tutti gli asset, filtri ed export", reverse("assets:asset_list"), counters.get("assets"), ""),
        ("hub", "Centro manutenzione", "Punto di partenza del manutentore", reverse("assets:maintenance_hub"), None, ""),
        ("todo", "Da fare", "Manutenzioni programmate aperte", reverse("assets:maintenance_da_fare"), counters.get("maintenance_overdue"), "red"),
        ("workorders", "Ordini di lavoro", "Interventi aperti e chiusi", reverse("assets:wo_list"), counters.get("wo_open"), "amber"),
        ("shift", "Il mio lavoro", "Le manutenzioni e gli interventi tuoi e di nessuno", f"{reverse('assets:maintenance_da_fare')}?mio=1", counters.get("wo_mine"), "blue"),
        ("deadlines", "Scadenzario", "Scadenze di piani, adempimenti e contratti", reverse("assets:maintenance_scadenze"), counters.get("deadlines_overdue"), "red"),
        ("plans", "Piani di manutenzione", "Cicli e frequenze per asset", reverse("assets:maintenance_plan_list"), None, ""),
        ("checks", "Verifiche impianti", "Luci di emergenza, estintori, impianti", reverse("assets:periodic_check_list"), None, ""),
        ("map", "Mappa officina", "Stato delle macchine in planimetria", reverse("assets:plant_layout_map"), None, ""),
        ("machines", "Macchine di lavoro", "Cruscotto del parco produttivo", reverse("assets:work_machine_dashboard"), None, ""),
        ("tickets", "Segnalazioni", "Ticket di manutenzione dagli operatori", f"{reverse('tickets:gestione_list')}?tipo=MAN", counters.get("tickets_new"), "amber"),
        ("history", "Storico", "Interventi eseguiti e registro", reverse("assets:maintenance_history"), None, ""),
        ("reports", "Report", "Report e analisi del modulo", reverse("assets:reports"), None, ""),
    ]
    user = getattr(request, "user", None)
    output = []
    for code, label, hint, url, count, tone in tiles:
        try:
            allowed = acl_allows_path(url.split("?", 1)[0], django_user=user, request=request)
        except Exception:
            allowed = False
        if not allowed:
            continue
        output.append({
            "code": code, "label": label, "hint": hint, "url": url,
            "count": count or 0, "tone": tone if count else "",
        })
    return output


@login_required
def asset_dashboard(request: HttpRequest) -> HttpResponse:
    """Dashboard principale del modulo Assets con KPI personalizzabili."""
    legacy_list_redirect = _legacy_asset_dashboard_list_redirect_url(request)
    if legacy_list_redirect:
        return redirect(legacy_list_redirect)

    today = timezone.localdate()
    selected_family_id = None
    selected_family_label = ""
    raw_family_id = request.GET.get("family")
    if raw_family_id:
        try:
            candidate_family_id = int(raw_family_id)
        except (TypeError, ValueError):
            candidate_family_id = None
        if candidate_family_id:
            selected_family = AssetCategory.objects.filter(pk=candidate_family_id, is_active=True).first()
            if selected_family:
                selected_family_id = selected_family.id
                selected_family_label = selected_family.label

    # Configurazione widget utente
    cfg, _ = AssetDashboardConfig.objects.get_or_create(user=request.user)
    enabled = cfg.get_enabled_widgets()

    kpis = _compute_dashboard_kpis(today)
    family_kpis = get_family_dashboard_kpis(selected_family_id, today=today)
    family_distribution = get_families_distribution(today=today)
    maintenance_by_family = get_maintenance_by_family(today=today)
    downtime_by_family = get_downtime_by_family(today=today)
    fire_safety_kpis = get_fire_safety_kpis(today=today)
    try:
        maintenance_perf = get_maintenance_performance_kpis(today=today)
    except Exception:
        maintenance_perf = {
            "mttr_hours": 0, "downtime_hours_month": 0, "maintenance_cost_month": 0,
            "wo_open_by_kind": {}, "wo_open_total": 0, "ticket_man_open": 0,
            "wo_closed_month": 0, "has_data": False,
        }

    # Cruscotto operativo (cose da fare + segnalazioni arrivate), condiviso con il Centro Manutenzione
    from assets.services.dashboard_kpi import get_cose_da_fare_overview, get_segnalazioni_overview
    cose_da_fare = get_cose_da_fare_overview(today=today)
    segnalazioni = get_segnalazioni_overview(today=today)

    # Centro "Da fare": interventi, segnalazioni e scadenze con le azioni rapide
    dash_wo = _dashboard_workorders(request, today)
    dash_deadlines = _dashboard_deadlines(request, today)
    from tickets.views import _can_manage_tickets
    from tickets.models import TipoTicket

    try:
        can_manage_man = _can_manage_tickets(request, TipoTicket.MAN)
    except Exception:
        can_manage_man = False
    attention_total = (
        dash_wo["urgent"] + dash_wo["late"] + segnalazioni["urgenti"] + dash_deadlines["overdue"]
    )
    launcher = _dashboard_launcher(request, {
        "assets": kpis["totale_asset"],
        "maintenance_overdue": dash_deadlines["maintenance_overdue"],
        "wo_open": dash_wo["total"],
        "wo_mine": dash_wo["mine"],
        "deadlines_overdue": dash_deadlines["overdue"],
        "tickets_new": segnalazioni["nuove"],
    })
    # I piani periodici sono convertiti in regole: le "Verifiche" della
    # dashboard contano le scadenze dei piani, non piu' la vecchia tabella.
    kpis["verifiche_scadute"] = dash_deadlines["plan_overdue"]
    kpis["verifiche_30gg"] = dash_deadlines["plan_due_soon"]
    kpis["prossime_verifiche"] = dash_deadlines["plan_upcoming"]
    status_rows = [row for row in kpis["asset_per_stato"] if row["status"] != Asset.STATUS_RETIRED]
    categories = list(AssetCategory.objects.filter(is_active=True).order_by("sort_order", "label"))
    family_options = categories
    # Categorie per la barra "Inventario per categoria": le piu' popolose in vista,
    # le altre dietro "+ altre" (sono decine e coprivano la pagina).
    category_counts = dict(
        Asset.objects.exclude(status=Asset.STATUS_RETIRED)
        .values_list("asset_category_id")
        .annotate(n=Count("id"))
        .order_by()
    )
    for cat in categories:
        cat.asset_count = int(category_counts.get(cat.id) or 0)
    by_count = sorted(categories, key=lambda c: (-c.asset_count, c.label.lower()))
    categories_top = [c for c in by_count if c.asset_count][:10]
    top_ids = {c.id for c in categories_top}
    categories_rest = [c for c in categories if c.id not in top_ids]


    # Metadati widget arricchiti con valore
    widgets_all = []
    for code, meta in _WIDGET_META.items():
        widgets_all.append({
            "code": code,
            "label": meta["label"],
            "icon": meta["icon"],
            "color": meta["color"],
            "enabled": code in enabled,
            "order": enabled.index(code) if code in enabled else 999,
        })
    widgets_all.sort(key=lambda w: (0 if w["enabled"] else 1, w["order"]))

    branding = get_module_branding_context("assets")

    ctx = _assets_shell_context(request, search_action=reverse("assets:asset_list"))
    ctx.update({
        "today": today,
        "kpis": kpis,
        "enabled_widgets": enabled,
        "enabled_widgets_json": json.dumps(enabled),
        "widgets_all": widgets_all,
        "categories": categories,
        "selected_family_id": selected_family_id,
        "selected_family_label": selected_family_label,
        "family_options": family_options,
        "family_kpis": family_kpis,
        "family_distribution": family_distribution,
        "maintenance_by_family": maintenance_by_family,
        "downtime_by_family": downtime_by_family,
        "fire_safety_kpis": fire_safety_kpis,
        "maintenance_perf": maintenance_perf,
        "cose_da_fare": cose_da_fare,
        "segnalazioni": segnalazioni,
        "dash_wo": dash_wo,
        "dash_deadlines": dash_deadlines,
        "can_manage_man": can_manage_man,
        "attention_total": attention_total,
        "launcher": launcher,
        "status_rows": status_rows,
        "categories_top": categories_top,
        "categories_rest": categories_rest,
        "now": timezone.localtime(),
        "branding": branding,
        "page_title": "Dashboard",
    })
    return render(request, "assets/pages/asset_dashboard.html", ctx)


@login_required
def api_asset_dashboard_save_config(request: HttpRequest) -> JsonResponse:
    """Salva la configurazione widget dashboard per l'utente corrente."""
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Metodo non consentito"}, status=405)
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Payload non valido"}, status=400)

    widgets = payload.get("widgets")
    if not isinstance(widgets, list):
        return JsonResponse({"ok": False, "error": "Campo widgets obbligatorio (lista)"}, status=400)

    valid = set(AssetDashboardConfig.DEFAULT_WIDGETS)
    clean = [w for w in widgets if isinstance(w, str) and w in valid]

    cfg, _ = AssetDashboardConfig.objects.get_or_create(user=request.user)
    cfg.enabled_widgets = clean
    cfg.save(update_fields=["enabled_widgets", "updated_at"])
    return JsonResponse({"ok": True, "saved": len(clean)})


# ---------------------------------------------------------------------------
# Calendario Asset (lavori macchina + manutenzioni)
# ---------------------------------------------------------------------------

def _asset_calendar_events(asset_id: int) -> list[dict]:
    """Ritorna tutti gli eventi (lavori + manutenzioni) per un singolo asset."""
    events: list[dict] = []
    today = timezone.localdate()

    # -- Lavori macchina (Task con categoria is_machine_work=True) --
    try:
        from tasks.models import TaskExtraRef, TaskStatus
        refs = (
            TaskExtraRef.objects
            .filter(asset_id=asset_id, task__category__is_machine_work=True)
            .exclude(task__status__in=[TaskStatus.DONE, TaskStatus.CANCELED])
            .select_related("task__category", "task__assigned_to", "task__project")
        )
        for ref in refs:
            t = ref.task
            start = t.next_step_due or t.due_date
            end = t.due_date or t.next_step_due
            if not start:
                continue
            assignee = ""
            if t.assigned_to_id:
                assignee = t.assigned_to.get_full_name() or t.assigned_to.get_username()
            events.append({
                "id": f"task-{t.pk}",
                "title": t.title,
                "start": str(start),
                "end": str(end) if end else str(start),
                "kind": "lavoro",
                "status": t.status,
                "assignee": assignee,
                "project": t.project.name if t.project_id else "",
                "url": f"/tasks/detail/{t.pk}/",
                "color": "#2563eb" if t.status == TaskStatus.IN_PROGRESS else "#93c5fd",
                "textColor": "#fff",
            })
    except Exception:
        pass

    # -- Manutenzioni (WorkOrder aperti) --
    try:
        wos = (
            WorkOrder.objects
            .filter(asset_id=asset_id, status=WorkOrder.STATUS_OPEN)
            .select_related("asset")
        )
        for wo in wos:
            opened = wo.opened_at.date() if wo.opened_at else today
            events.append({
                "id": f"wo-{wo.pk}",
                "title": f"OdL: {wo.title}",
                "start": str(opened),
                "end": str(opened),
                "kind": "manutenzione",
                "status": wo.status,
                "assignee": "",
                "project": "",
                "url": f"/assets/workorders/view/{wo.pk}/",
                "color": "#f59e0b",
                "textColor": "#fff",
            })
    except Exception:
        pass

    # -- Verifiche periodiche pianificate --
    try:
        verifications = (
            AssetCalendarEvent.objects
            .filter(asset_id=asset_id, due_date__gte=today)
            .order_by("due_date")
        )
        for v in verifications:
            events.append({
                "id": f"ace-{v.pk}",
                "title": v.source_object_label or v.subject or "Scadenza",
                "start": str(v.due_date),
                "end": str(v.due_date),
                "kind": "scadenza",
                "status": "",
                "assignee": v.target_display_name,
                "project": "",
                "url": "",
                "color": "#10b981",
                "textColor": "#fff",
            })
    except Exception:
        pass

    # -- Manutenzioni e adempimenti pianificati (occorrenze: stessa fonte del
    #    Calendario manutenzione; prima si leggeva il motore a regole) --
    try:
        from ..services import deadline_feed as feed

        _pm_colors = {
            feed.STATE_OVERDUE: "#dc2626", feed.STATE_DUE_SOON: "#f59e0b",
            feed.STATE_PLANNED: "#2563eb", feed.STATE_OPEN: "#10b981",
        }
        for row in feed.collect(
            start=None,
            end=today + timedelta(days=400),
            filters=feed.FeedFilters(
                kinds=frozenset({feed.KIND_ORDINARY, feed.KIND_ADMINISTRATIVE}), asset_id=asset_id
            ),
            today=today,
        ):
            # Riempimento = urgenza (stato); bordo viola + marcatore 🏢 = manutenzione esterna (ditta terza).
            pm_event = {
                "id": row.key,
                "title": f"{'🏢 ' if row.is_external else ''}Manut.: {row.title}",
                "start": str(row.due_date),
                "end": str(row.due_date),
                "kind": "manutenzione_prog",
                "status": row.state,
                "assignee": row.supplier if row.is_external else row.assignee,
                "project": "",
                "url": row.detail_url,
                "color": _pm_colors.get(row.state, "#10b981"),
                "textColor": "#fff",
            }
            if row.is_external:
                pm_event["borderColor"] = "#6d28d9"
                pm_event["external"] = True
            events.append(pm_event)
    except Exception:
        pass

    return events


@login_required
def asset_calendar_json(request: HttpRequest, id: int) -> JsonResponse:
    """JSON eventi calendario per un singolo asset (usato da FullCalendar)."""
    asset = get_object_or_404(Asset, pk=id)
    events = _asset_calendar_events(asset.pk)
    return JsonResponse({"ok": True, "asset_id": asset.pk, "events": events})


@login_required
def calendario_asset(request: HttpRequest) -> HttpResponse:
    """Calendario della manutenzione: ordinarie, amministrative, licenze e contratti.

    Legge dallo stesso servizio dello Scadenzario (``services.deadline_feed``): i
    numeri del calendario e della lista sono gli stessi. Viste mese, settimana,
    elenco e per asset; i filtri vanno al server, le tipologie si accendono e
    spengono senza ricaricare.
    """
    from ..forms_maintenance import category_filter_choices
    from ..models import AssetGroup
    from ..services import deadline_feed as feed

    allowed = feed.allowed_kinds(request)
    kinds = [
        {"value": kind, "label": label}
        for kind, label in feed.KIND_LABELS.items()
        if kind in allowed
    ]
    kinds.append({"value": "machine_work", "label": "Lavori macchina"})
    reparti = list(
        Asset.objects.exclude(reparto="").values_list("reparto", flat=True).order_by("reparto").distinct()
    )
    from ..forms_maintenance import WorkOrderFromOccurrencesForm
    from ..views_maintenance import can_execute_maintenance, can_plan_maintenance

    can_plan = can_plan_maintenance(request)
    return render(request, "assets/pages/calendario_asset.html", {
        "page_title": "Calendario manutenzione",
        "can_plan": can_plan,
        "can_execute": can_plan and can_execute_maintenance(request),
        "workorder_form": WorkOrderFromOccurrencesForm() if can_plan else None,
        "kinds": kinds,
        "categories": category_filter_choices(),
        "reparti": reparti,
        "groups": AssetGroup.objects.filter(is_active=True).order_by("sort_order", "label"),
        **_assets_shell_context(request),
    })


def _calendar_range_date(raw) -> date | None:
    """FullCalendar manda ``2026-09-28T00:00:00+02:00``: interessa solo la data."""
    value = _clean_string(raw)[:10]
    try:
        return parse_date(value) if value else None
    except ValueError:
        return None


def _machine_work_events(start: date, end: date, filters) -> list[dict]:
    """Lavori macchina (attivita' KICK-OFF di categoria "lavoro macchina") sugli
    asset filtrati: non sono scadenze di manutenzione ma occupano la macchina, e
    chi pianifica deve vederli accanto. Una query per tutto il periodo."""
    try:
        from tasks.models import TaskExtraRef, TaskStatus
    except Exception:
        return []
    refs = (
        TaskExtraRef.objects.filter(asset_id__isnull=False, task__category__is_machine_work=True)
        .exclude(task__status__in=[TaskStatus.DONE, TaskStatus.CANCELED])
        .select_related("task", "task__assigned_to", "asset", "asset__asset_category")
    )
    if filters.category_ids is not None:
        refs = refs.filter(asset__asset_category_id__in=filters.category_ids)
    if filters.reparto:
        refs = refs.filter(asset__reparto=filters.reparto)
    if filters.group_id:
        refs = refs.filter(asset__group_memberships__group_id=filters.group_id)
    events = []
    for ref in refs[:1000]:
        task = ref.task
        begin = task.next_step_due or task.due_date
        finish = task.due_date or task.next_step_due
        if not begin or begin > end or (finish or begin) < start:
            continue
        asset = ref.asset
        assignee = ""
        if task.assigned_to_id:
            assignee = task.assigned_to.get_full_name() or task.assigned_to.get_username()
        events.append({
            "id": f"task-{task.pk}",
            "kind": "machine_work",
            "kind_label": "Lavoro macchina",
            "title": task.title,
            "start": begin.isoformat(),
            # FullCalendar: fine esclusiva, quindi il giorno dopo l'ultimo.
            "end": (finish + timedelta(days=1)).isoformat() if finish and finish > begin else None,
            "state": "open",
            "state_label": "In corso" if task.status == TaskStatus.IN_PROGRESS else "Pianificato",
            "asset_id": asset.id,
            "asset_tag": asset.asset_tag or "",
            "asset_name": asset.name or "",
            "category": asset.asset_category.label if asset.asset_category_id else "",
            "reparto": asset.reparto or "",
            "assignee": assignee,
            "url": f"/tasks/detail/{task.pk}/",
            "actions": [{"label": "Apri attività", "url": f"/tasks/detail/{task.pk}/"}],
        })
    return events


@login_required
def calendario_asset_json(request: HttpRequest) -> JsonResponse:
    """Eventi del Calendario manutenzione per il periodo visibile (``start``/``end``)."""
    from ..forms_maintenance import category_with_descendants
    from ..services import deadline_feed as feed

    today = timezone.localdate()
    start = _calendar_range_date(request.GET.get("start")) or today.replace(day=1) - timedelta(days=7)
    end = _calendar_range_date(request.GET.get("end")) or start + timedelta(days=42)
    # Il calendario non chiede mai piu' di qualche settimana: un periodo enorme e'
    # un errore o un abuso, e si tronca.
    if end <= start or (end - start).days > 400:
        end = start + timedelta(days=42)

    requested = [kind for kind in _clean_string(request.GET.get("kinds")).split(",") if kind]
    allowed = feed.allowed_kinds(request)
    category_id = _as_int(request.GET.get("category"), default=0)
    execution = _clean_string(request.GET.get("execution")).upper()
    filters = feed.FeedFilters(
        kinds=feed.parse_kinds(requested, allowed),
        category_ids=frozenset(category_with_descendants(category_id)) if category_id else None,
        reparto=_clean_string(request.GET.get("reparto")),
        group_id=_as_int(request.GET.get("group"), default=0) or None,
        execution_mode=execution if execution in {"INTERNAL", "EXTERNAL"} else "",
        include_done=_clean_string(request.GET.get("include_done")) in {"1", "true", "on"},
    )
    last_day = end - timedelta(days=1)  # FullCalendar tratta ``end`` come esclusivo.
    include_forecast = _clean_string(request.GET.get("forecast")) != "0"
    rows = feed.collect(start=start, end=last_day, filters=filters, today=today, include_forecast=include_forecast)
    events = [row.as_json(today) for row in rows]
    if not requested or "machine_work" in requested:
        events += _machine_work_events(start, last_day, filters)
    return JsonResponse({"ok": True, "today": today.isoformat(), "events": events})
