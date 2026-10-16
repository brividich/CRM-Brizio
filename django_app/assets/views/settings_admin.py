"""Impostazioni del modulo (gestione_admin).

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
    CATEGORY_ACTIONS,
    SIDEBAR_ACTIONS,
    _as_int,
    _clean_string,
    _get_default_asset_label_template,
    _is_assets_admin,
    _ui_choices,
    _ui_label,
)
from ._helpers_b import (  # noqa: F401
    _asset_detail_source_choices,
    _sidebar_input_suggestions,
    _sidebar_target_label,
)
from ._helpers_c import (  # noqa: F401
    _assets_shell_context,
    _category_sidebar_active_match,
    _category_sidebar_target,
    _handle_asset_category_request,
    _handle_sidebar_button_request,
)

DOCUMENT_FOLDER_ACTIONS = {
    "create_asset_category_document_folder",
    "rename_asset_category_document_folder",
    "toggle_asset_category_document_folder",
    "update_asset_category_document_folder_order",
    "delete_asset_category_document_folder",
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
