"""Calendario asset (lavori macchina e manutenzioni).

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
)

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
