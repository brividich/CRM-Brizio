"""QR ed etichette: designer, landing QR (privata e pubblica), upload dal QR, PDF etichette.

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
    ASSET_DOCUMENT_CATEGORY_LABELS,
    _as_int,
    _asset_label_field_catalog,
    _asset_label_field_catalog_map,
    _clean_string,
    _draw_asset_label_pdf,
    _find_asset_override_label_template,
    _find_asset_type_label_template,
    _format_asset_label_value,
    _get_default_asset_label_template,
    _is_assets_admin,
    _maintenance_schedule_page_url,
    _normalize_asset_label_fields,
    _resolve_asset_label_template,
)
from ._helpers_c import (  # noqa: F401
    _assets_shell_context,
)

LABEL_TEMPLATE_COPY_FIELDS = [
    "page_width_mm",
    "page_height_mm",
    "qr_size_mm",
    "qr_position",
    "show_logo",
    "logo_height_mm",
    "logo_alignment",
    "title_font_size_pt",
    "body_font_size_pt",
    "show_border",
    "border_radius_mm",
    "show_field_labels",
    "show_target_label",
    "show_help_text",
    "show_target_url",
    "background_color",
    "border_color",
    "text_color",
    "accent_color",
    "title_primary_field",
    "title_secondary_field",
]


def _asset_label_field_choices() -> list[tuple[str, str]]:
    return [(row["key"], f"{row['label']} [{row['group']}]") for row in _asset_label_field_catalog()]


def _asset_type_label(asset_type: str | None) -> str:
    return dict(Asset.TYPE_CHOICES).get(_clean_string(asset_type), _clean_string(asset_type) or "Generale")


def _default_asset_label_logo_url() -> str:
    return static("core/img/logo_novicrom.png")


def _asset_label_logo_preview_url(template: AssetLabelTemplate) -> str:
    if template.logo_file and getattr(template.logo_file, "name", ""):
        try:
            return template.logo_file.url
        except Exception:
            return ""
    return _default_asset_label_logo_url()


def _asset_label_logo_meta(template: AssetLabelTemplate) -> dict[str, str]:
    has_custom = bool(template.logo_file and getattr(template.logo_file, "name", ""))
    return {
        "url": _asset_label_logo_preview_url(template),
        "default_url": _default_asset_label_logo_url(),
        "source": "custom" if has_custom else "default",
        "name": Path(template.logo_file.name).name if has_custom else "logo_novicrom.png",
    }


def _clone_asset_label_template(
    source: AssetLabelTemplate,
    *,
    asset: Asset | None = None,
    asset_type: str = "",
) -> AssetLabelTemplate:
    template = AssetLabelTemplate()
    for field_name in LABEL_TEMPLATE_COPY_FIELDS:
        value = getattr(source, field_name)
        if field_name == "body_fields":
            value = list(value or [])
        setattr(template, field_name, value)
    template.body_fields = list(getattr(source, "body_fields", []) or [])
    if source.logo_file and getattr(source.logo_file, "name", ""):
        template.logo_file = source.logo_file.name
    template.asset = asset
    template.asset_type = _clean_string(asset_type)
    base_name = _clean_string(getattr(source, "name", "")) or "Etichetta"
    if asset is not None:
        scope_name = asset.asset_tag or asset.name or f"Asset {asset.pk}"
        template.name = f"{base_name} - {scope_name}"[:120]
    elif template.asset_type:
        template.name = f"{base_name} - {_asset_type_label(template.asset_type)}"[:120]
    else:
        template.name = base_name[:120]
    return template


def _get_asset_label_template_for_scope(
    *,
    scope: str,
    asset: Asset | None = None,
    asset_type: str = "",
) -> tuple[AssetLabelTemplate, bool]:
    if scope == AssetLabelTemplate.SCOPE_ASSET and asset is not None:
        template = _find_asset_override_label_template(asset)
        if template is not None:
            return template, True
        base_template = _find_asset_type_label_template(asset.asset_type) or _get_default_asset_label_template()
        return _clone_asset_label_template(base_template, asset=asset), False

    if scope == AssetLabelTemplate.SCOPE_ASSET_TYPE and _clean_string(asset_type):
        template = _find_asset_type_label_template(asset_type)
        if template is not None:
            return template, True
        return _clone_asset_label_template(_get_default_asset_label_template(), asset_type=asset_type), False

    return _get_default_asset_label_template(), True


def _default_asset_label_preview_values() -> dict[str, str]:
    return {
        "asset_tag": "ML-000001",
        "name": "Centro di lavoro 5 assi",
        "asset_type": "Macchina di lavoro",
        "status": "In uso",
        "reparto": "CN5",
        "manufacturer": "DMG Mori",
        "model": "DMC 85",
        "serial_number": "DMG-550",
        "assignment_to": "Officina",
        "assignment_reparto": "CN5",
        "assignment_location": "Corsia A",
        "year": "2022",
        "x_mm": "850 mm",
        "y_mm": "700 mm",
        "z_mm": "500 mm",
        "diameter_mm": "120 mm",
        "spindle_mm": "180 mm",
        "tmc": "48",
        "tcr_enabled": "Si",
        "pressure_bar": "6,5 bar",
        "cnc_controlled": "Si",
        "five_axes": "Si",
        "accuracy_from": "0.010",
        "next_maintenance_date": (timezone.localdate() + timedelta(days=30)).strftime("%d-%m-%Y"),
        "maintenance_reminder_days": "15 gg",
    }


def _build_asset_label_preview_context(
    request: HttpRequest,
    *,
    template: AssetLabelTemplate,
    asset: Asset | None,
    target: str = "detail",
) -> dict[str, object]:
    catalog_map = _asset_label_field_catalog_map()
    field_values = _default_asset_label_preview_values()
    preview_asset_name = "Anteprima generica"
    preview_asset_tag = "Nessun asset selezionato"
    target_url = _portal_absolute_uri(request, reverse("assets:asset_list"))
    target_label = "Elenco asset"
    if asset is not None:
        preview_asset_name = asset.name or "Asset"
        preview_asset_tag = asset.asset_tag or "Asset"
        target_url, target_label = _asset_qr_target_url(request, asset, target=target)
        for key in catalog_map:
            field_values[key] = _format_asset_label_value(asset, key, catalog_map)

    selected_body_fields = _normalize_asset_label_fields(template.body_fields, catalog_map)
    title_primary_key = template.title_primary_field if template.title_primary_field in catalog_map else "asset_tag"
    title_secondary_key = template.title_secondary_field if template.title_secondary_field in catalog_map else "name"

    return {
        "catalog": [
            {
                "key": row["key"],
                "label": row["label"],
                "group": row["group"],
                "value": field_values.get(row["key"], ""),
            }
            for row in _asset_label_field_catalog()
        ],
        "catalog_map": catalog_map,
        "field_values": field_values,
        "selected_body_fields": selected_body_fields,
        "title_primary_key": title_primary_key,
        "title_secondary_key": title_secondary_key,
        "preview_asset_name": preview_asset_name,
        "preview_asset_tag": preview_asset_tag,
        "target_url": target_url,
        "target_label": target_label,
    }


def _asset_qr_target_url(request: HttpRequest, asset: Asset, *, target: str = "detail") -> tuple[str, str]:
    from ..services import asset_qr

    desired = _clean_string(target).lower()
    # "sharepoint" e' un valore legacy (link e template etichetta salvati prima
    # della rimozione dell'archivio SharePoint): vale come "landing".
    if desired in {"sharepoint", "landing"}:
        # Landing pubblica solo se il link e' stato abilitato esplicitamente,
        # altrimenti landing interna dietro login (services/asset_qr.py).
        dest = asset_qr.destinazione(request, asset)
        return dest.url, dest.label
    detail_url = reverse("assets:asset_view", kwargs={"id": asset.id})
    return _portal_absolute_uri(request, detail_url), "Scheda asset"


def _portal_absolute_uri(request: HttpRequest, path: str) -> str:
    site_url = _clean_string(getattr(settings, "SITE_URL", "")).rstrip("/")
    if site_url:
        normalized_path = _clean_string(path)
        if not normalized_path.startswith("/"):
            normalized_path = f"/{normalized_path}"
        return f"{site_url}{normalized_path}"
    return request.build_absolute_uri(path)


@login_required
def asset_label_designer(request: HttpRequest) -> HttpResponse:
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo personalizzare l'etichetta QR.")
        return redirect("assets:asset_list")

    field_choices = _asset_label_field_choices()
    scope_raw = request.POST.get("scope") if request.method == "POST" else request.GET.get("scope")
    scope = _clean_string(scope_raw).upper() or AssetLabelTemplate.SCOPE_DEFAULT
    if scope not in {AssetLabelTemplate.SCOPE_DEFAULT, AssetLabelTemplate.SCOPE_ASSET_TYPE, AssetLabelTemplate.SCOPE_ASSET}:
        scope = AssetLabelTemplate.SCOPE_DEFAULT

    raw_scope_asset_id = request.POST.get("scope_asset_id") if request.method == "POST" else request.GET.get("asset_id")
    scope_asset_id = _as_int(raw_scope_asset_id, default=0)
    scope_asset = None
    if scope_asset_id:
        scope_asset = Asset.objects.filter(pk=scope_asset_id).select_related("work_machine").first()
    if scope == AssetLabelTemplate.SCOPE_ASSET and scope_asset is None:
        messages.error(request, "Seleziona un asset valido per l'override etichetta.")
        return redirect("assets:gestione_admin")

    raw_scope_asset_type = request.POST.get("scope_asset_type") if request.method == "POST" else request.GET.get("asset_type")
    scope_asset_type = _clean_string(raw_scope_asset_type).upper()
    valid_asset_types = {code for code, _label in Asset.TYPE_CHOICES}
    if scope == AssetLabelTemplate.SCOPE_ASSET and scope_asset is not None:
        scope_asset_type = scope_asset.asset_type
    elif scope == AssetLabelTemplate.SCOPE_ASSET_TYPE and scope_asset_type not in valid_asset_types:
        messages.error(request, "Seleziona una tipologia asset valida per il template.")
        return redirect(f"{reverse('assets:gestione_admin')}?tab=config")
    elif scope == AssetLabelTemplate.SCOPE_DEFAULT:
        scope_asset_type = ""

    template, template_exists = _get_asset_label_template_for_scope(
        scope=scope,
        asset=scope_asset,
        asset_type=scope_asset_type,
    )

    raw_preview_asset_id = request.POST.get("preview_asset_id") if request.method == "POST" else request.GET.get("preview_asset_id")
    preview_asset_id = _as_int(raw_preview_asset_id, default=0)
    preview_asset = None
    if preview_asset_id:
        preview_asset = Asset.objects.filter(pk=preview_asset_id).select_related("work_machine").first()
    if preview_asset is not None and scope == AssetLabelTemplate.SCOPE_ASSET_TYPE and preview_asset.asset_type != scope_asset_type:
        preview_asset = None
    if scope == AssetLabelTemplate.SCOPE_ASSET and scope_asset is not None:
        preview_asset = scope_asset
    elif preview_asset is None and scope == AssetLabelTemplate.SCOPE_ASSET_TYPE and scope_asset_type:
        preview_asset = (
            Asset.objects.filter(asset_type=scope_asset_type)
            .select_related("work_machine")
            .order_by("name", "asset_tag")
            .first()
        )
    if preview_asset is None:
        preview_asset = (
            Asset.objects.filter(asset_type__in=PRODUCTION_ASSET_TYPES)
            .select_related("work_machine")
            .order_by("name", "asset_tag")
            .first()
        )
    if preview_asset is None:
        preview_asset = Asset.objects.select_related("work_machine").order_by("name", "asset_tag").first()

    if request.method == "POST":
        form = AssetLabelTemplateForm(request.POST, request.FILES, instance=template, field_choices=field_choices)
        if form.is_valid():
            template = form.save()
            if scope == AssetLabelTemplate.SCOPE_ASSET and scope_asset is not None:
                messages.success(request, f"Override etichetta salvato per {scope_asset.asset_tag}.")
            elif scope == AssetLabelTemplate.SCOPE_ASSET_TYPE and scope_asset_type:
                messages.success(request, f"Template etichetta salvato per {_asset_type_label(scope_asset_type)}.")
            else:
                messages.success(request, "Template etichetta generale aggiornato.")
            next_url = reverse("assets:asset_label_designer")
            query_parts = [f"scope={scope}"]
            if scope == AssetLabelTemplate.SCOPE_ASSET and scope_asset is not None:
                query_parts.append(f"asset_id={scope_asset.id}")
            elif scope == AssetLabelTemplate.SCOPE_ASSET_TYPE and scope_asset_type:
                query_parts.append(f"asset_type={scope_asset_type}")
            if preview_asset is not None:
                query_parts.append(f"preview_asset_id={preview_asset.id}")
            if query_parts:
                next_url = f"{next_url}?{'&'.join(query_parts)}"
            return redirect(next_url)
    else:
        form = AssetLabelTemplateForm(instance=template, field_choices=field_choices)

    preview_context = _build_asset_label_preview_context(request, template=template, asset=preview_asset)
    preview_asset_qr_url = ""
    logo_meta = _asset_label_logo_meta(template)
    if preview_asset is not None:
        preview_asset_qr_url = reverse("assets:asset_qr_label", kwargs={"id": preview_asset.id})

    if scope == AssetLabelTemplate.SCOPE_ASSET and scope_asset is not None:
        scope_title = f"Override asset - {scope_asset.asset_tag}"
        scope_description = "Template personale applicato solo a questo asset."
        back_url = reverse("assets:asset_view", kwargs={"id": scope_asset.id})
    elif scope == AssetLabelTemplate.SCOPE_ASSET_TYPE and scope_asset_type:
        scope_title = f"Template tipologia - {_asset_type_label(scope_asset_type)}"
        scope_description = "Template generale applicato a tutti gli asset di questa tipologia, salvo override del singolo asset."
        back_url = f"{reverse('assets:gestione_admin')}?tab=config"
    else:
        scope_title = "Template generale"
        scope_description = "Fallback usato quando non esiste un template dedicato per tipologia o per asset."
        back_url = f"{reverse('assets:gestione_admin')}?tab=config"

    return render(
        request,
        "assets/pages/asset_label_designer.html",
        {
            "page_title": "Designer etichetta QR",
            "form": form,
            "scope": scope,
            "scope_title": scope_title,
            "scope_description": scope_description,
            "scope_asset": scope_asset,
            "scope_asset_type": scope_asset_type,
            "scope_asset_type_label": _asset_type_label(scope_asset_type),
            "template_exists": template_exists,
            "back_url": back_url,
            "preview_asset": preview_asset,
            "preview_asset_qr_url": preview_asset_qr_url,
            "preview_catalog": preview_context["catalog"],
            "preview_selected_body_fields": preview_context["selected_body_fields"],
            "preview_field_values": preview_context["field_values"],
            "preview_title_primary_key": preview_context["title_primary_key"],
            "preview_title_secondary_key": preview_context["title_secondary_key"],
            "preview_target_url": preview_context["target_url"],
            "preview_target_label": preview_context["target_label"],
            "preview_target_meta": {
                "label": preview_context["target_label"],
                "url": preview_context["target_url"],
                "fallbackPrimary": preview_context["preview_asset_tag"],
                "fallbackSecondary": preview_context["preview_asset_name"],
            },
            "preview_logo_meta": logo_meta,
            "preview_asset_name": preview_context["preview_asset_name"],
            "preview_asset_tag": preview_context["preview_asset_tag"],
            "preview_asset_id": preview_asset.id if preview_asset is not None else "",
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


@login_required
def asset_qr_landing(request: HttpRequest, asset_tag: str) -> HttpResponse:
    """P3.3 — Landing mobile-first raggiungibile via QR code fisico sull'asset.
    Mostra: nome asset, stato, OdL aperti, ultima manutenzione, link segnalazione.
    """
    asset = Asset.objects.filter(asset_tag=asset_tag).select_related("asset_category").first()
    if asset is None:
        return render(
            request,
            "assets/pages/asset_qr_landing.html",
            {
                "page_title": "Asset non trovato",
                "asset": None,
                "asset_tag": asset_tag,
                "base_template": "core/base.html",
                **_assets_shell_context(request, rows=25),
            },
        )
    return _render_asset_qr_landing(request, asset, public=False)


@risposta_pubblica
def asset_qr_public_landing(request: HttpRequest, public_qr_token: str) -> HttpResponse:
    """Landing QR pubblica (token opaco): consultabile senza login da tecnici/ispettori esterni.

    Sola lettura: le azioni (segnalazione, registrazione intervento, scheda interna)
    restano dietro login tramite i decoratori delle rispettive view.
    """
    token = _clean_string(public_qr_token)
    if not token:
        raise Http404("Link non disponibile.")
    asset = (
        Asset.objects.filter(public_qr_token=token, public_qr_enabled=True)
        .select_related("asset_category")
        .first()
    )
    if asset is None:
        raise Http404("Link non disponibile.")
    return _render_asset_qr_landing(request, asset, public=True)


def _qr_landing_tickets(request: HttpRequest, asset: Asset, *, public: bool, qr_token: str) -> list[dict[str, object]]:
    """Ticket non chiusi dell'asset per la landing QR (max 10, piu' recenti prima)."""
    from tickets.allegati import ticket_aperti_asset
    from tickets.views import _can_manage_tickets

    rows: list[dict[str, object]] = []
    can_manage: dict[str, bool] = {}
    for t in ticket_aperti_asset(asset.id)[:10]:
        row: dict[str, object] = {
            "id": t.pk,
            "numero": t.numero_ticket,
            "titolo": t.titolo,
            "stato": t.stato,
            "stato_label": t.label_stato,
            "priorita": t.priorita,
            "priorita_label": t.label_priorita,
            "tipo_label": t.label_tipo,
            "incide_sicurezza": t.incide_sicurezza,
            "created_at": t.created_at,
            "n_allegati": t.n_allegati,
            "n_da_validare": t.n_allegati_da_validare,
            "detail_url": "",
        }
        if public:
            row["upload_url"] = (
                reverse("assets:asset_qr_ticket_upload", kwargs={"public_qr_token": qr_token, "ticket_id": t.pk})
                if qr_token
                else ""
            )
        else:
            row["upload_url"] = reverse("tickets:carica_allegati", args=[t.pk])
            if t.tipo not in can_manage:
                can_manage[t.tipo] = _can_manage_tickets(request, t.tipo)
            if can_manage[t.tipo]:
                row["detail_url"] = reverse("tickets:gestione_detail", args=[t.pk])
        rows.append(row)
    return rows


@risposta_pubblica
def asset_qr_ticket_upload(request: HttpRequest, public_qr_token: str, ticket_id: int) -> HttpResponse:
    """Upload di rapportino/foto su un ticket aperto dal QR pubblico dell'asset.

    Il token QR e' la chiave: il ticket deve appartenere esattamente all'asset del
    token ed essere ancora aperto. Solo foto/PDF, tetto per IP e per macchina,
    file sempre "da validare" dal team gestore. Nessun dato del ticket viene
    restituito oltre a quanto gia' mostrato dalla landing.
    """
    from tickets.allegati import (
        QR_MAX_FILES,
        AllegatoError,
        carica_allegato,
        qr_rate_limited,
        registra_caricamento,
        ticket_accetta_allegati,
    )
    from tickets.models import OrigineAllegato, Ticket

    if request.method != "POST":
        raise Http404("Pagina non disponibile.")
    token = _clean_string(public_qr_token)
    asset = (
        Asset.objects.filter(public_qr_token=token, public_qr_enabled=True).first() if token else None
    )
    if asset is None or not getattr(settings, "ASSETS_QR_PUBLIC_TICKET_UPLOAD", True):
        raise Http404("Link non disponibile.")
    landing_url = reverse("assets:asset_qr_public_landing", kwargs={"public_qr_token": token}) + "#ticket"

    ticket = Ticket.objects.filter(pk=ticket_id, asset_id=asset.id).first()
    if ticket is None:
        # Ticket inesistente o di un'altra macchina: nessun oracolo.
        log_action(
            request,
            "ticket_allegato_qr",
            "assets",
            {"asset_id": asset.id, "ticket_id": ticket_id, "qr_token_prefix": token[:8],
             "esito": "denied", "motivo": "ticket_not_in_asset"},
        )
        raise Http404("Ticket non disponibile.")
    if not ticket_accetta_allegati(ticket):
        messages.error(request, f"Il ticket {ticket.numero_ticket} è chiuso: non accetta nuovi allegati.")
        return redirect(landing_url)

    # Honeypot: i bot compilano tutto, le persone non vedono il campo.
    if _clean_string(request.POST.get("sito_web")):
        return redirect(landing_url)

    nome = _clean_string(request.POST.get("nome"))[:200]
    ditta = _clean_string(request.POST.get("ditta"))[:200]
    files = request.FILES.getlist("file")
    if len(nome) < 3:
        messages.error(request, "Indica nome e cognome di chi carica il documento.")
        return redirect(landing_url)
    if not files:
        messages.error(request, "Scatta una foto o scegli un file da allegare.")
        return redirect(landing_url)
    if len(files) > QR_MAX_FILES:
        messages.error(request, f"Puoi allegare al massimo {QR_MAX_FILES} file per invio.")
        return redirect(landing_url)
    if qr_rate_limited(request, asset.id):
        log_action(
            request,
            "ticket_allegato_qr",
            "assets",
            {"asset_id": asset.id, "ticket_id": ticket.pk, "qr_token_prefix": token[:8],
             "esito": "denied", "motivo": "rate_limited"},
        )
        messages.error(request, "Troppi invii ravvicinati da questo dispositivo. Riprova tra qualche minuto.")
        return redirect(landing_url)

    email = ""
    if request.user.is_authenticated:
        email = (request.user.email or "").strip().lower()
    caricati = []
    errori = []
    for f in files:
        try:
            caricati.append(
                carica_allegato(
                    ticket,
                    f,
                    caricato_da_nome=nome,
                    caricato_da_email=email,
                    ditta=ditta,
                    origine=OrigineAllegato.QR,
                    tipo_documento=_clean_string(request.POST.get("tipo_documento")).upper(),
                    descrizione=_clean_string(request.POST.get("descrizione")),
                    da_validare=True,
                )
            )
        except AllegatoError as exc:
            errori.append(f"{safe_filename(getattr(f, 'name', '')) or 'file'}: {exc}")

    registra_caricamento(ticket, caricati)
    log_action(
        request,
        "ticket_allegato_qr",
        "assets",
        {
            "asset_id": asset.id,
            "asset_tag": asset.asset_tag,
            "ticket_id": ticket.pk,
            "numero_ticket": ticket.numero_ticket,
            "qr_token_prefix": token[:8],
            "allegati": [a.pk for a in caricati],
            "scartati": len(errori),
            "caricato_da": nome,
            "ditta": ditta,
            "esito": "success" if caricati else "rejected",
        },
        oggetto=ticket,
    )
    if caricati:
        messages.success(
            request,
            f"Grazie! {len(caricati)} file allegat{'o' if len(caricati) == 1 else 'i'} al ticket "
            f"{ticket.numero_ticket}. Il team manutenzione {'lo' if len(caricati) == 1 else 'li'} verificherà a breve.",
        )
    for err in errori:
        messages.error(request, err)
    return redirect(landing_url)


def _qr_can_record_meter(request: HttpRequest) -> bool:
    from ..views_maintenance import can_execute_maintenance

    return can_execute_maintenance(request)


def _render_asset_qr_landing(request: HttpRequest, asset: Asset, *, public: bool) -> HttpResponse:
    asset_tag = asset.asset_tag
    today = timezone.localdate()

    # OdL aperti per questo asset (max 5)
    open_workorders = list(
        WorkOrder.objects.filter(asset=asset, status=WorkOrder.STATUS_OPEN)
        .select_related("maintenance_rule__intervention_template")
        .order_by("opened_at")[:5]
    )

    # Ultimo intervento chiuso
    last_wo = (
        WorkOrder.objects.filter(asset=asset, status=WorkOrder.STATUS_DONE)
        .order_by("-closed_at")
        .values("id", "title", "closed_at", "kind")
        .first()
    )

    # Prossima scadenza amministrativa (campo corretto: due_date; niente flag 'completed').
    next_deadline = (
        AssetAdministrativeDeadline.objects.filter(asset=asset, is_active=True)
        .order_by("due_date")
        .values("id", "title", "due_date")
        .first()
    )

    # Stato manutenzione: giorni dall'ultimo intervento
    days_since_last = None
    if last_wo and last_wo["closed_at"]:
        closed_date = last_wo["closed_at"].date() if hasattr(last_wo["closed_at"], "date") else last_wo["closed_at"]
        days_since_last = (today - closed_date).days

    # Manutenzioni programmate in scadenza per questa macchina (dalle regole) — solo azionabili.
    # Manutenzioni e adempimenti dell'asset dalle occorrenze (stessa fonte di
    # Scadenzario e Calendario): prima la pagina QR leggeva il motore a regole.
    # Solo ordinarie e amministrative: licenze e contratti non riguardano chi
    # inquadra la macchina.
    from ..services import deadline_feed as feed

    _status_order = {"overdue": 0, "warning": 1, "upcoming": 2, "missing": 3}
    _feed_status = {feed.STATE_OVERDUE: "overdue", feed.STATE_DUE_SOON: "warning"}
    qr_schedule_rows: list[dict[str, object]] = []
    for row in feed.collect(
        start=None,
        end=today + timedelta(days=365),
        filters=feed.FeedFilters(
            kinds=frozenset({feed.KIND_ORDINARY, feed.KIND_ADMINISTRATIVE}), asset_id=asset.id
        ),
        today=today,
    ):
        qr_schedule_rows.append(
            {
                "label": row.title or "Manutenzione",
                "due_date": row.due_date,
                "status": _feed_status.get(row.state, "upcoming"),
                "schedule_label": row.state_label,
                "is_external": row.is_external,
                "supplier": row.supplier if row.is_external else "",
                "record_url": row.detail_url,
            }
        )
    qr_schedule_rows.sort(key=lambda r: (_status_order.get(r["status"], 9), r["due_date"] or today))
    qr_schedule_rows = qr_schedule_rows[:12]
    qr_overdue_count = sum(1 for r in qr_schedule_rows if r["status"] == "overdue")

    # Documenti dell'asset (manuali, specifiche, interventi).
    # I file non sono mai raggiungibili via /media/ (deny IIS): il link passa dalla
    # view a token per il QR pubblico, dalla view autenticata per l'utente loggato.
    asset_documents = []
    qr_token = _clean_string(asset.public_qr_token) if asset.public_qr_enabled else ""
    for doc in asset.documents.all()[:15]:
        if public:
            # Il visitatore anonimo ha in mano solo il token: download a token dei
            # file locali, nessun altro percorso esposto.
            open_url = (
                reverse(
                    "assets:asset_document_qr_download",
                    kwargs={"public_qr_token": qr_token, "document_id": doc.id},
                )
                if (qr_token and doc.file)
                else ""
            )
        else:
            open_url = (
                reverse("assets:asset_document_download", kwargs={"document_id": doc.id})
                if doc.file
                else ""
            )
        asset_documents.append(
            {
                "name": doc.original_name or "Documento",
                "category_label": ASSET_DOCUMENT_CATEGORY_LABELS.get(doc.category, doc.category),
                "document_date": doc.document_date,
                "open_url": open_url,
            }
        )
    # Ticket aperti della macchina, con il caricamento di rapportini/foto.
    # Dal QR pubblico il visitatore vede solo numero, titolo, stato e priorita'
    # (niente richiedente, note o allegati) e puo' solo AGGIUNGERE file, che
    # nascono "da validare" per il team MAN.
    qr_tickets = _qr_landing_tickets(request, asset, public=public, qr_token=qr_token)
    qr_upload_enabled = bool(
        qr_tickets
        and (not public or (qr_token and getattr(settings, "ASSETS_QR_PUBLIC_TICKET_UPLOAD", True)))
    )
    qr_uploader_name = ""
    if request.user.is_authenticated:
        qr_uploader_name = request.user.get_full_name() or request.user.get_username()

    # URL azioni
    detail_url = reverse("assets:asset_view", kwargs={"id": asset.id})
    report_url = f"{reverse('assets:asset_quick_report')}?asset={asset.id}&from=qr"
    wo_list_url = f"{reverse('assets:wo_list')}?asset={asset.id}"
    schedule_url = _maintenance_schedule_page_url(asset_id=asset.id)

    context: dict[str, object] = {
        "page_title": f"{asset.asset_tag} — {asset.name}",
        "asset": asset,
        "asset_tag": asset_tag,
        "open_workorders": open_workorders,
        "last_wo": last_wo,
        "next_deadline": next_deadline,
        "days_since_last": days_since_last,
        "today": today,
        "qr_schedule_rows": qr_schedule_rows,
        "qr_overdue_count": qr_overdue_count,
        "asset_documents": asset_documents,
        "detail_url": detail_url,
        "report_url": report_url,
        "wo_list_url": wo_list_url,
        "schedule_url": schedule_url,
        "qr_public": public,
        "qr_tickets": qr_tickets,
        "qr_upload_enabled": qr_upload_enabled,
        "qr_uploader_name": qr_uploader_name,
        "qr_landing_url": request.path,
        "qr_meters": [] if public else list(AssetMeter.objects.filter(asset=asset).order_by("meter_type")),
        "qr_can_record_meter": False if public else _qr_can_record_meter(request),
    }
    if public:
        # Nessuna shell applicativa (sidebar/nav/ACL) per i visitatori non autenticati.
        context["base_template"] = "core/base_public.html"
    else:
        context["base_template"] = "core/base.html"
        context.update(_assets_shell_context(request, rows=25))
    response = render(request, "assets/pages/asset_qr_landing.html", context)
    if public and qr_upload_enabled:
        # Il form di caricamento e' un POST: con "no-referrer" Chromium manda
        # Origin: null e il CSRF lo rifiuta. same-origin non fa uscire il token.
        response["Referrer-Policy"] = "same-origin"
    return response


@login_required
def asset_qr_label(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:asset_list")
    asset = get_object_or_404(Asset, pk=id)
    target_value = _clean_string(request.GET.get("target")).lower() or "landing"
    target_url, target_label = _asset_qr_target_url(request, asset, target=target_value)
    template = _resolve_asset_label_template(asset)
    width = float(template.page_width_mm or 100) * mm
    height = float(template.page_height_mm or 62) * mm
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{asset.asset_tag or "asset"}-qr-label.pdf"'

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(width, height))
    pdf.setTitle(f"QR {asset.asset_tag}")
    pdf.setAuthor("Portale Applicativo")

    _draw_asset_label_pdf(
        pdf,
        asset=asset,
        template=template,
        target_url=target_url,
        target_label=target_label,
    )

    pdf.showPage()
    pdf.save()
    response.write(buffer.getvalue())
    return response
