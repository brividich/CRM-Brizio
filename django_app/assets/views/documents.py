"""Download protetti di documenti, allegati di OdL e di scadenze amministrative.

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
    _can_download_asset_document,
    _can_view_workorder,
    _clean_string,
    _is_assets_admin,
)

# Content-type per cui l'apertura inline e' sicura: nessuno di questi puo'
# eseguire script nell'origine del portale. Tutto il resto (html, svg, ...) va
# servito come allegato, altrimenti un upload diventa una XSS same-origin.
_INLINE_SAFE_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/bmp",
        "text/plain",
    }
)


def _document_file_response(storage, file_name: str, filename: str) -> FileResponse:
    """FileResponse con Content-Disposition inline solo per i tipi sicuri."""
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    inline = content_type in _INLINE_SAFE_CONTENT_TYPES
    response = FileResponse(
        storage.open(file_name, "rb"),
        as_attachment=not inline,
        filename=filename,
        content_type=content_type,
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def asset_document_download(request, document_id: int):
    document = get_object_or_404(
        AssetDocument.objects.select_related("asset", "uploaded_by"),
        pk=document_id,
    )
    if not _can_download_asset_document(request):
        log_action(
            request,
            "download_asset_document",
            "assets",
            {
                "document_id": document.id,
                "asset_id": document.asset_id,
                "category": document.category,
                "esito": "denied",
                "motivo": "permission_denied",
            },
        )
        return render(request, "core/pages/forbidden.html", status=403)
    storage = document.file.storage if document.file else None
    file_name = document.file.name if document.file else ""
    if not storage or not file_name or not storage.exists(file_name):
        log_action(
            request,
            "download_asset_document",
            "assets",
            {
                "document_id": document.id,
                "asset_id": document.asset_id,
                "category": document.category,
                "esito": "not_found",
            },
        )
        return HttpResponse("Documento non trovato.", status=404)
    filename = document.original_name or Path(file_name).name
    log_action(
        request,
        "download_asset_document",
        "assets",
        {
            "document_id": document.id,
            "asset_id": document.asset_id,
            "category": document.category,
            "filename": filename,
            "esito": "success",
        },
    )
    # Stessa resa del QR: anteprima nel browser per i tipi che non possono
    # eseguire script (era il comportamento con l'URL /media/ diretto), allegato
    # per tutti gli altri.
    return _document_file_response(storage, file_name, filename)


@risposta_pubblica
def asset_document_qr_download(request: HttpRequest, public_qr_token: str, document_id: int):
    """Download di un documento asset tramite il token QR stampato sulla macchina.

    Il token e' la chiave d'accesso: i file NON sono raggiungibili via /media/
    (deny IIS su media/assets_documents). Nessun filtro di categoria — dal QR si
    vedono tutti i documenti dell'asset — ma il documento deve appartenere
    esattamente all'asset di quel token: nessun accesso cross-asset.
    """
    token = _clean_string(public_qr_token)
    if not token:
        raise Http404("Link non disponibile.")
    asset = Asset.objects.filter(public_qr_token=token, public_qr_enabled=True).first()
    if asset is None:
        raise Http404("Link non disponibile.")

    document = AssetDocument.objects.filter(pk=document_id, asset_id=asset.id).first()
    if document is None:
        # Documento inesistente o di un altro asset: stessa risposta, nessun oracolo.
        log_action(
            request,
            "download_asset_document_qr",
            "assets",
            {
                "document_id": document_id,
                "asset_id": asset.id,
                "asset_tag": asset.asset_tag,
                "qr_token_prefix": token[:8],
                "esito": "denied",
                "motivo": "document_not_in_asset",
            },
        )
        raise Http404("Documento non disponibile.")

    storage = document.file.storage if document.file else None
    file_name = document.file.name if document.file else ""
    if not storage or not file_name or not storage.exists(file_name):
        log_action(
            request,
            "download_asset_document_qr",
            "assets",
            {
                "document_id": document.id,
                "asset_id": asset.id,
                "asset_tag": asset.asset_tag,
                "qr_token_prefix": token[:8],
                "esito": "not_found",
            },
        )
        raise Http404("Documento non disponibile.")

    filename = document.original_name or Path(file_name).name
    log_action(
        request,
        "download_asset_document_qr",
        "assets",
        {
            "document_id": document.id,
            "asset_id": asset.id,
            "asset_tag": asset.asset_tag,
            "category": document.category,
            "filename": filename,
            "qr_token_prefix": token[:8],
            "esito": "success",
        },
    )
    return _document_file_response(storage, file_name, filename)


def _can_download_workorder_attachment(request: HttpRequest, attachment) -> bool:
    """Controllo per oggetto sugli allegati OdL, parallelo a ``_can_download_asset_document``.

    Un allegato si scarica se si vede l'OdL a cui appartiene; l'OdL deve avere un asset.
    """
    work_order = getattr(attachment, "work_order", None)
    if work_order is None:
        return False
    return _can_view_workorder(request, work_order)


@login_required
def workorder_attachment_download(request: HttpRequest, attachment_id: int):
    """Allegati OdL: serviti solo da qui (deny IIS su media/assets_workorders)."""
    attachment = get_object_or_404(
        WorkOrderAttachment.objects.select_related("work_order__asset"),
        pk=attachment_id,
    )
    if not _can_download_workorder_attachment(request, attachment):
        log_action(
            request,
            "download_workorder_attachment",
            "assets",
            {
                "attachment_id": attachment.id,
                "work_order_id": attachment.work_order_id,
                "asset_id": attachment.work_order.asset_id,
                "esito": "denied",
                "motivo": "permission_denied",
            },
        )
        return render(request, "core/pages/forbidden.html", status=403)
    storage = attachment.file.storage if attachment.file else None
    file_name = attachment.file.name if attachment.file else ""
    if not storage or not file_name or not storage.exists(file_name):
        log_action(
            request,
            "download_workorder_attachment",
            "assets",
            {
                "attachment_id": attachment.id,
                "work_order_id": attachment.work_order_id,
                "asset_id": attachment.work_order.asset_id,
                "esito": "not_found",
            },
        )
        return HttpResponse("Allegato non trovato.", status=404)
    filename = attachment.original_name or Path(file_name).name
    log_action(
        request,
        "download_workorder_attachment",
        "assets",
        {
            "attachment_id": attachment.id,
            "work_order_id": attachment.work_order_id,
            "asset_id": attachment.work_order.asset_id,
            "filename": filename,
            "esito": "success",
        },
    )
    return _document_file_response(storage, file_name, filename)


@login_required
def admin_deadline_attachment_download(request, attachment_id: int):
    attachment = get_object_or_404(
        AssetAdministrativeDeadlineCompletionAttachment.objects.select_related("completion__deadline__asset"),
        pk=attachment_id,
    )
    if not _is_assets_admin(request):
        log_action(
            request,
            "download_admin_deadline_attachment",
            "assets",
            {
                "attachment_id": attachment.id,
                "completion_id": attachment.completion_id,
                "deadline_id": attachment.completion.deadline_id,
                "asset_id": attachment.completion.deadline.asset_id,
                "esito": "denied",
                "motivo": "permission_denied",
            },
        )
        return render(request, "core/pages/forbidden.html", status=403)
    storage = attachment.file.storage
    if not attachment.file or not attachment.file.name or not storage.exists(attachment.file.name):
        log_action(
            request,
            "download_admin_deadline_attachment",
            "assets",
            {
                "attachment_id": attachment.id,
                "completion_id": attachment.completion_id,
                "deadline_id": attachment.completion.deadline_id,
                "asset_id": attachment.completion.deadline.asset_id,
                "esito": "not_found",
            },
        )
        return HttpResponse("Allegato non trovato.", status=404)
    filename = attachment.original_name or Path(attachment.file.name).name
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    log_action(
        request,
        "download_admin_deadline_attachment",
        "assets",
        {
            "attachment_id": attachment.id,
            "completion_id": attachment.completion_id,
            "deadline_id": attachment.completion.deadline_id,
            "asset_id": attachment.completion.deadline.asset_id,
            "filename": filename,
            "esito": "success",
        },
    )
    return FileResponse(
        storage.open(attachment.file.name, "rb"),
        as_attachment=True,
        filename=filename,
        content_type=content_type,
    )
