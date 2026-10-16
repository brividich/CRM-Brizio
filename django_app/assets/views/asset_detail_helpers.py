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
    _as_int,
    _asset_maintenance_rule_list_page_url,
    _assistance_contracts_page_url,
    _clean_string,
    _coalesce_str,
    _is_assets_admin,
    _ui_label,
    _workorder_create_page_url,
)
from ._helpers_b import (  # noqa: F401
    _default_asset_detail_field_seed_rows,
    _ensure_default_asset_detail_section_layouts,
    _format_asset_detail_value,
    _resolve_asset_detail_source_value,
)

DETAIL_LAYOUT_ACTIONS = {
    "update_detail_section_layout",
    "update_detail_section_layout_bulk",
    "move_detail_section_layout",
}


def _asset_report_pdf_url(asset_id: int) -> str:
    return reverse("assets:asset_report_pdf", kwargs={"id": int(asset_id)})


def _asset_status_payload(asset: Asset) -> dict[str, str]:
    return {
        "label": asset.get_status_display(),
        "badge_class": Asset.STATUS_TONES.get(asset.status, "muted"),
    }


def _contextual_maintenance_suggestions(
    *,
    asset: Asset,
    schedule_row: dict[str, object] | None,
    contract: AssistanceContract | None,
    source: str,
) -> list[dict[str, str]]:
    suggestions: list[dict[str, str]] = []
    if schedule_row is not None:
        base_rule = schedule_row.get("base_rule")
        base_rule_id = getattr(base_rule, "id", 0)
        schedule_status = str(schedule_row.get("schedule_status") or "")
        if schedule_status == "overdue" and base_rule_id:
            suggestions.append(
                {
                    "label": "Crea intervento",
                    "href": _workorder_create_page_url(asset_id=asset.id, rule_id=base_rule_id, source=source),
                    "description": "La manutenzione risulta scaduta e puo essere aperta gia collegata alla regola.",
                    "style": "primary",
                }
            )
        if schedule_status == "missing" and base_rule_id:
            suggestions.append(
                {
                    "label": "Imposta prima esecuzione",
                    "href": _asset_maintenance_rule_list_page_url(asset_id=asset.id, focus_rule_id=base_rule_id),
                    "description": "Manca una baseline: registra la prima esecuzione per calcolare la prossima scadenza.",
                    "style": "default",
                }
            )
    if contract is None:
        suggestions.append(
            {
                "label": "Verifica copertura",
                "href": _assistance_contracts_page_url(asset_id=asset.id),
                "description": "L'asset non ha un contratto attivo collegato.",
                "style": "secondary",
            }
        )
    return suggestions[:3]


def _asset_document_upload_count(uploads: dict[str, list]) -> int:
    return sum(len(files) for files in uploads.values())


def _compute_ticket_kpi_for_asset(asset: Asset) -> dict:
    """Calcola KPI ticket per il singolo asset.

    Restituisce un dizionario pronto per il template. Non genera N+1:
    carica tutti i ticket dell'asset in una query e tutti gli interventi
    in una seconda query, poi elabora in Python.
    """
    from tickets.models import StatoTicket, TicketIntervento

    tickets_qs = list(
        asset.tickets
        .only(
            "pk", "stato", "tipo", "categoria", "componente", "causa_radice",
            "tipo_fermo", "ore_fermo_macchina",
            "created_at", "closed_at", "data_presa_in_carico",
            "risolto_da_nome",
        )
    )
    if not tickets_qs:
        return {"has_tickets": False}

    stati_aperti = {StatoTicket.APERTA, StatoTicket.IN_CARICO, StatoTicket.IN_ATTESA}
    stati_chiusi = {StatoTicket.RISOLTO, StatoTicket.CHIUSO}

    totale = len(tickets_qs)
    aperti = sum(1 for t in tickets_qs if t.stato in stati_aperti)
    chiusi = sum(1 for t in tickets_qs if t.stato in stati_chiusi)

    # MTTR — media ore dalla creazione alla chiusura per ticket risolti/chiusi con closed_at
    durate_risoluzione = []
    for t in tickets_qs:
        if t.stato in stati_chiusi and t.closed_at and t.created_at:
            delta_h = (t.closed_at - t.created_at).total_seconds() / 3600
            durate_risoluzione.append(delta_h)
    mttr_ore = round(sum(durate_risoluzione) / len(durate_risoluzione), 1) if durate_risoluzione else None

    # Ore fermo macchina totali
    ore_fermo_totali = sum(
        float(t.ore_fermo_macchina)
        for t in tickets_qs
        if t.ore_fermo_macchina is not None
    )

    # Top 3 componenti per frequenza
    from collections import Counter
    componenti_counter = Counter(
        t.componente for t in tickets_qs if t.componente
    )
    top_componenti = componenti_counter.most_common(3)

    # Top 3 cause radice per frequenza
    cause_counter = Counter(
        t.causa_radice for t in tickets_qs if t.causa_radice
    )
    top_cause = cause_counter.most_common(3)

    # Interventi — ore per tecnico
    ticket_ids = [t.pk for t in tickets_qs]
    interventi_qs = list(
        TicketIntervento.objects
        .filter(ticket_id__in=ticket_ids)
        .only("tecnico_nome", "ore_lavorate", "data_inizio", "data_fine")
    )
    ore_per_tecnico: dict[str, float] = {}
    for interv in interventi_qs:
        ore = interv.durata_ore
        if ore:
            ore_per_tecnico[interv.tecnico_nome] = ore_per_tecnico.get(interv.tecnico_nome, 0.0) + ore
    top_tecnici = sorted(ore_per_tecnico.items(), key=lambda x: -x[1])[:3]
    ore_intervento_totali = round(sum(ore_per_tecnico.values()), 2)

    return {
        "has_tickets": True,
        "totale": totale,
        "aperti": aperti,
        "chiusi": chiusi,
        "mttr_ore": mttr_ore,
        "ore_fermo_totali": round(ore_fermo_totali, 2) if ore_fermo_totali else 0,
        "ore_intervento_totali": ore_intervento_totali,
        "top_componenti": top_componenti,
        "top_cause": top_cause,
        "top_tecnici": top_tecnici,
    }


def _build_asset_status_band(
    *,
    primary_contract: AssistanceContract | None,
    primary_contract_state: dict[str, str] | None,
    next_deadline_row: dict[str, object] | None,
    asset_assistance_contracts_url: str,
    asset_administrative_deadline_list_url: str,
) -> dict[str, dict[str, str]]:
    """Banda di stato del dettaglio asset: copertura assistenza + prossima scadenza
    amministrativa unite in un'unica card. Lo stato asset resta nella pill header e
    la prossima manutenzione viene mostrata nel Registro manutenzione."""
    contract_value = str(primary_contract.supplier) if primary_contract is not None else "Copertura non disponibile"
    contract_meta = "Copertura non disponibile"
    if primary_contract is not None:
        contract_meta = primary_contract.coverage_summary or primary_contract.target_label
    coverage = {
        "label": "Copertura assistenza",
        "value": contract_value,
        "meta": contract_meta or "Nessun contratto attivo collegato.",
        "badge_label": (
            str(primary_contract_state.get("label"))
            if primary_contract_state is not None
            else "Senza contratto"
        ),
        "badge_class": (
            str(primary_contract_state.get("badge_class"))
            if primary_contract_state is not None
            else "muted"
        ),
        "link_label": "Apri contratti",
        "link_url": asset_assistance_contracts_url,
    }
    deadline_value = "Nessuna scadenza"
    deadline_meta = "Nessuna scadenza amministrativa registrata."
    deadline_badge_class = "muted"
    deadline_badge_label = "Nessuna"
    if next_deadline_row is not None:
        deadline = next_deadline_row["deadline"]
        deadline_state = next_deadline_row["state"]
        deadline_value = str(deadline.title)
        deadline_meta = str(deadline_state.get("days_label") or "")
        deadline_badge_class = str(deadline_state.get("badge_class") or "muted")
        deadline_badge_label = str(deadline_state.get("label") or "Programmato")
    deadline_card = {
        "label": "Scadenze amministrative",
        "value": deadline_value,
        "meta": deadline_meta,
        "badge_label": deadline_badge_label,
        "badge_class": deadline_badge_class,
        "link_label": "Apri scadenze",
        "link_url": asset_administrative_deadline_list_url,
    }
    return {"coverage": coverage, "deadline": deadline_card}


def _build_asset_primary_kpis(
    *,
    asset: Asset,
    asset_status: dict[str, str],
    assignment_rows: list[dict[str, str]],
    primary_contract: AssistanceContract | None,
    primary_contract_state: dict[str, str] | None,
    next_maintenance_row: dict[str, object] | None,
    next_deadline_row: dict[str, object] | None,
    preferred_detail_metrics: list[dict[str, object]],
    detail_metrics: list[dict[str, object]],
    asset_assign_url: str,
    asset_assistance_contracts_url: str,
    asset_maintenance_schedule_url: str,
    asset_administrative_deadline_list_url: str,
) -> list[dict[str, str]]:
    # I KPI di default (stato/copertura/prossima manutenzione/scadenze) sono stati
    # ridistribuiti: stato nella pill header, copertura+scadenze nella status band,
    # prossima manutenzione nel Registro manutenzione. Qui restano solo le eventuali
    # metriche "preferite" configurate via AssetDetailField.
    default_cards: list[dict[str, str]] = []

    if not any(card["meta"] for card in default_cards) and detail_metrics:
        for index, metric in enumerate(detail_metrics[:4]):
            if index >= len(default_cards):
                break
            default_cards[index]["meta"] = str(metric.get("value") or "")

    cards: list[dict[str, str]] = []
    if preferred_detail_metrics:
        for metric in preferred_detail_metrics:
            label = _coalesce_str(metric.get("label"), "")
            if not label:
                continue
            cards.append(
                {
                    "label": label,
                    "value": _coalesce_str(metric.get("value"), "N/D"),
                    "meta": "",
                    "badge_label": "",
                    "badge_class": "info",
                    "link_label": "",
                    "link_url": "",
                    "size_class": str(metric.get("size_class") or "af-span-third"),
                }
            )
            if len(cards) >= 4:
                return cards[:4]

    used_labels = {str(card.get("label")) for card in cards}
    for card in default_cards:
        if str(card.get("label")) in used_labels:
            continue
        cards.append(card)
        if len(cards) >= 4:
            break

    return cards[:4]


def _can_manage_asset_detail_layout(request: HttpRequest) -> bool:
    if _is_assets_admin(request):
        return True
    return bool(
        user_can_modulo_action(request, "assets", "admin_assets")
        or user_can_modulo_action(request, "assets", "asset_detail_layout")
    )


def _can_manage_asset_document_folders(request: HttpRequest) -> bool:
    """Solo admin/gestori asset possono aggiungere o disattivare cartelle documento."""
    if _is_assets_admin(request):
        return True
    return bool(user_can_modulo_action(request, "assets", "admin_assets"))


def _can_manage_asset_timeline_entries(request: HttpRequest) -> bool:
    """Chi puo' aggiungere voci manuali alla timeline di vita di un asset.

    Di serie gli amministratori/gestori asset. La platea e' pero' "opzionabile":
    dal pannello Accessi si concede l'azione ``assets/asset_timeline_entry`` (per
    ruolo o come override utente) ai manutentori, senza toccare il codice. Senza
    grant il pulsante non compare e la POST viene rifiutata.
    """
    if _is_assets_admin(request):
        return True
    return bool(
        user_can_modulo_action(request, "assets", "admin_assets")
        or user_can_modulo_action(request, "assets", "asset_timeline_entry")
    )


def _asset_timeline_entry_payload(request: HttpRequest) -> tuple[dict | None, str]:
    """Legge dalla POST i campi di una voce manuale di timeline.

    Stessa lettura per inserimento e modifica: ritorna ``(payload, errore)``,
    con payload ``None`` quando manca un dato obbligatorio.
    """
    entry_title = _clean_string(request.POST.get("timeline_title"))[:160]
    raw_event_date = _clean_string(request.POST.get("timeline_date"))
    try:
        entry_date = date.fromisoformat(raw_event_date) if raw_event_date else None
    except ValueError:
        entry_date = None
    entry_color = _clean_string(request.POST.get("timeline_color")).lower()
    if entry_color not in {code for code, _ in AssetTimelineEntry.COLOR_CHOICES}:
        entry_color = AssetTimelineEntry.COLOR_BLUE
    if not entry_title:
        return None, "Inserisci il titolo dell'evento da registrare in timeline."
    if entry_date is None:
        return None, "Inserisci una data evento valida."
    return (
        {
            "event_date": entry_date,
            "title": entry_title,
            "tag": _clean_string(request.POST.get("timeline_tag"))[:40].upper(),
            "description": _clean_string(request.POST.get("timeline_description"))[:2000],
            "meta": _clean_string(request.POST.get("timeline_meta"))[:120],
            "color": entry_color,
        },
        "",
    )


def _asset_timeline_hidden_keys(asset: Asset) -> set[str]:
    """Chiavi degli eventi automatici che l'utente ha rimosso dalla timeline."""
    return set(asset.timeline_hidden_events.values_list("event_key", flat=True))


def _asset_timeline_manual_enabled(asset: Asset) -> bool:
    """L'inserimento manuale e' attivabile/disattivabile per categoria asset."""
    category = getattr(asset, "asset_category", None)
    if category is None:
        return True
    return bool(getattr(category, "detail_timeline_manual_enabled", True))


def _maintenance_schedule_row_for_asset_rule(*, asset: Asset, base_rule_id: int) -> dict[str, object] | None:
    rows = build_day_based_maintenance_schedule_rows(
        asset_queryset=Asset.objects.filter(pk=asset.id).select_related("asset_category"),
    )
    for row in rows:
        if getattr(row.get("base_rule"), "id", 0) == int(base_rule_id or 0):
            return row
    return None


def _detail_field_matches_asset_scope(detail_field: AssetDetailField, work_machine: WorkMachine | None) -> bool:
    if detail_field.asset_scope == AssetDetailField.SCOPE_ALL:
        return True
    if detail_field.asset_scope == AssetDetailField.SCOPE_WORK_MACHINE:
        return isinstance(work_machine, WorkMachine)
    if detail_field.asset_scope == AssetDetailField.SCOPE_STANDARD:
        return not isinstance(work_machine, WorkMachine)
    return False


def _is_empty_asset_detail_value(value) -> bool:
    if isinstance(value, bool):
        return False
    if value is None:
        return True
    if isinstance(value, (list, tuple, set, dict)):
        return not value
    cleaned = _clean_string(str(value))
    return cleaned.casefold() in {"", "n/d", "-"}


def _should_skip_asset_detail_row(section: str, formatted_value, show_if_empty: bool) -> bool:
    is_empty = _is_empty_asset_detail_value(formatted_value)
    if section == AssetDetailField.SECTION_SPECS:
        return is_empty
    return is_empty and not show_if_empty


def _build_configured_asset_detail_sections(
    *,
    asset: Asset,
    it_details: AssetITDetails | None,
    work_machine: WorkMachine | None,
    extra: dict[str, object],
    custom_fields_by_code: dict[str, AssetCustomField],
    sync_text: str,
) -> tuple[dict[str, list[dict[str, str]]], bool]:
    configured = list(AssetDetailField.objects.filter(is_active=True).order_by("section", "asset_scope", "sort_order", "id"))
    from ..services.it_presentation import it_profile
    profile = it_profile(asset)
    irrelevant_defaults = set()
    if profile in ("server", "vm", "printer"):
        irrelevant_defaults.update(("computed:battery_health", "extra:graphics", "extra:display"))
    if profile == "printer":
        irrelevant_defaults.update(("it:cpu", "it:ram", "it:os", "it:disco", "computed:cpu_load", "computed:storage_free"))
    seeds = {
        slugify(f"{row['section']}-{row['asset_scope']}-{row['source_ref']}")[:70]: row
        for row in _default_asset_detail_field_seed_rows()
        if row["source_ref"] in irrelevant_defaults
    }
    sections: dict[str, list[dict[str, str]]] = defaultdict(list)
    has_matching_config = False
    for detail_field in configured:
        if not _detail_field_matches_asset_scope(detail_field, work_machine):
            continue
        has_matching_config = True
        seed = seeds.get(detail_field.code)
        if seed and all(getattr(detail_field, key) == seed[key] for key in (
            "label", "section", "asset_scope", "source_ref", "value_format", "sort_order",
        )) and detail_field.show_if_empty == bool(seed.get("show_if_empty", True)) and detail_field.card_size == AssetDetailField.CARD_THIRD:
            # Only untouched generic defaults are suppressed. Explicit custom
            # fields and category definitions remain authoritative.
            continue
        raw_value = _resolve_asset_detail_source_value(
            source_ref=detail_field.source_ref,
            asset=asset,
            it_details=it_details,
            work_machine=work_machine,
            extra=extra,
            custom_fields_by_code=custom_fields_by_code,
            sync_text=sync_text,
        )
        formatted_value = _format_asset_detail_value(raw_value, detail_field.value_format)
        if _should_skip_asset_detail_row(detail_field.section, formatted_value, detail_field.show_if_empty):
            continue
        sections[detail_field.section].append(
            {
                "label": detail_field.label,
                "value": formatted_value,
                "size": detail_field.card_size,
                "source_ref": detail_field.source_ref,
            }
        )
    return sections, has_matching_config


def _build_asset_category_detail_sections(asset: Asset, extra: dict[str, object]) -> dict[str, list[dict[str, str]]]:
    category = getattr(asset, "asset_category", None)
    if category is None:
        return {}
    category_values = extra.get("_category_fields", {})
    if not isinstance(category_values, dict):
        category_values = {}

    sections: dict[str, list[dict[str, str]]] = defaultdict(list)
    field_qs = category.category_fields.filter(is_active=True, show_in_detail=True).order_by("sort_order", "label", "id")
    for field_def in field_qs:
        raw_value = category_values.get(field_def.code, "")
        formatted_value = _format_asset_detail_value(raw_value, field_def.detail_value_format)
        if _should_skip_asset_detail_row(field_def.detail_section, formatted_value, field_def.show_if_empty):
            continue
        sections[field_def.detail_section].append(
            {
                "label": field_def.label,
                "value": formatted_value,
                "size": field_def.detail_card_size,
                "source_ref": f"category:{field_def.code}",
            }
        )
    return sections


def _preferred_asset_detail_metrics(detail_metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    default_metric_signatures = {
        (_clean_string(row.get("label")), _clean_string(row.get("source_ref")))
        for row in _default_asset_detail_field_seed_rows()
        if row.get("section") == AssetDetailField.SECTION_METRICS
    }
    preferred_metrics: list[dict[str, object]] = []
    for metric in detail_metrics:
        label = _clean_string(metric.get("label"))
        source_ref = _clean_string(metric.get("source_ref"))
        size = _clean_string(metric.get("size")).upper()
        if not label:
            continue
        if source_ref.startswith("custom:") or source_ref.startswith("category:"):
            preferred_metrics.append(metric)
            continue
        if size in {AssetDetailField.CARD_HALF, AssetDetailField.CARD_WIDE, AssetDetailField.CARD_FULL}:
            preferred_metrics.append(metric)
            continue
        if (label, source_ref) not in default_metric_signatures:
            preferred_metrics.append(metric)
    return preferred_metrics


def _detail_grid_size_class(size_code: str) -> str:
    normalized = _clean_string(size_code).upper()
    if normalized == AssetDetailField.CARD_HALF:
        return "af-span-half"
    if normalized == AssetDetailField.CARD_WIDE:
        return "af-span-wide"
    if normalized == AssetDetailField.CARD_FULL:
        return "af-span-full"
    return "af-span-third"


def _asset_edit_route_name(asset: Asset) -> str:
    if asset.asset_type == Asset.TYPE_WORK_MACHINE:
        return "assets:work_machine_edit"
    return "assets:asset_edit"


def _resolve_button_target(button: AssetActionButton, asset: Asset) -> str:
    target = _clean_string(button.target)
    replacements = {
        "{asset_id}": str(asset.id),
        "{asset_tag}": asset.asset_tag or "",
        "{asset_name}": asset.name or "",
        "{asset_type}": asset.asset_type or "",
        "{assigned_user_id}": str(asset.assigned_legacy_user_id or ""),
    }
    for key, value in replacements.items():
        target = target.replace(key, value)
    return target


def _default_action_buttons(asset: Asset, *, create_workorder_url: str = "") -> dict[str, list[dict]]:
    try:
        edit_url = reverse(_asset_edit_route_name(asset), kwargs={"id": asset.id})
    except NoReverseMatch:
        edit_url = ""
    try:
        assign_url = reverse("assets:asset_assign", kwargs={"id": asset.id})
    except NoReverseMatch:
        assign_url = ""
    try:
        wo_url = create_workorder_url or reverse("assets:wo_create", kwargs={"id": asset.id})
    except NoReverseMatch:
        wo_url = create_workorder_url
    try:
        refresh_url = reverse("assets:asset_view", kwargs={"id": asset.id})
    except NoReverseMatch:
        refresh_url = ""
    try:
        qr_url = reverse("assets:asset_qr_label", kwargs={"id": asset.id})
    except NoReverseMatch:
        qr_url = ""
    try:
        qr_landing_url = reverse("assets:asset_qr_landing", kwargs={"asset_tag": asset.asset_tag})
    except NoReverseMatch:
        qr_landing_url = ""

    return {
        AssetActionButton.ZONE_HEADER: [
            {"label": "Etichetta QR", "style": AssetActionButton.STYLE_DEFAULT, "href": qr_url, "data_action": "", "new_tab": True},
            {"label": "Modifica dettagli", "style": AssetActionButton.STYLE_PRIMARY, "href": edit_url, "data_action": "", "new_tab": False},
        ],
        AssetActionButton.ZONE_QUICK: [
            {"label": "Riassegna", "style": AssetActionButton.STYLE_DEFAULT, "href": assign_url, "data_action": "", "new_tab": False},
            {"label": "Crea intervento", "style": AssetActionButton.STYLE_DEFAULT, "href": wo_url, "data_action": "", "new_tab": False},
            {"label": "Vista QR mobile", "style": AssetActionButton.STYLE_SECONDARY, "href": qr_landing_url, "data_action": "", "new_tab": False},
            {"label": "Aggiorna dati", "style": AssetActionButton.STYLE_SECONDARY, "href": refresh_url, "data_action": "", "new_tab": False},
            {"label": "Dismetti bene", "style": AssetActionButton.STYLE_DANGER, "href": edit_url, "data_action": "", "new_tab": False},
        ],
    }


def _system_action_buttons_for_asset(asset: Asset) -> dict[str, list[dict]]:
    buttons = {
        AssetActionButton.ZONE_HEADER: [],
        AssetActionButton.ZONE_QUICK: [],
    }
    try:
        buttons[AssetActionButton.ZONE_HEADER].append(
            {
                "label": "Etichetta QR",
                "style": AssetActionButton.STYLE_SECONDARY,
                "href": reverse("assets:asset_qr_label", kwargs={"id": asset.id}),
                "data_action": "",
                "new_tab": True,
            }
        )
    except NoReverseMatch:
        pass
    return buttons


def _append_unique_action_buttons(base: dict[str, list[dict]], extra: dict[str, list[dict]]) -> dict[str, list[dict]]:
    for zone, buttons in extra.items():
        seen = {
            (
                _clean_string(button.get("label")).lower(),
                _clean_string(button.get("href")),
                _clean_string(button.get("data_action")).lower(),
            )
            for button in base.get(zone, [])
        }
        for button in buttons:
            signature = (
                _clean_string(button.get("label")).lower(),
                _clean_string(button.get("href")),
                _clean_string(button.get("data_action")).lower(),
            )
            if signature in seen:
                continue
            base.setdefault(zone, []).append(button)
            seen.add(signature)
    return base


def _build_action_buttons_for_asset(asset: Asset, *, create_workorder_url: str = "") -> dict[str, list[dict]]:
    configured = list(AssetActionButton.objects.filter(is_active=True).order_by("zone", "sort_order", "id"))
    defaults = _default_action_buttons(asset, create_workorder_url=create_workorder_url)
    output: dict[str, list[dict]] = {
        AssetActionButton.ZONE_HEADER: [],
        AssetActionButton.ZONE_QUICK: [],
    }
    if not configured:
        return _append_unique_action_buttons(defaults, _system_action_buttons_for_asset(asset))

    for button in configured:
        if button.zone not in output:
            continue
        payload = {
            "label": _ui_label(button.label),
            "style": button.style,
            "href": "",
            "data_action": "",
            "new_tab": bool(button.open_in_new_tab),
        }
        if button.action_type == AssetActionButton.TYPE_PRINT:
            payload["data_action"] = "print"
        elif button.action_type == AssetActionButton.TYPE_REFRESH:
            payload["data_action"] = "refresh"
        else:
            payload["href"] = _resolve_button_target(button, asset)
        output[button.zone].append(payload)

    if not output[AssetActionButton.ZONE_HEADER]:
        output[AssetActionButton.ZONE_HEADER] = defaults[AssetActionButton.ZONE_HEADER]
    if not output[AssetActionButton.ZONE_QUICK]:
        output[AssetActionButton.ZONE_QUICK] = defaults[AssetActionButton.ZONE_QUICK]
    return _append_unique_action_buttons(output, _system_action_buttons_for_asset(asset))


def _match_action_button(button: dict, *, href: str = "", label: str = "") -> bool:
    href_value = _clean_string(href)
    label_value = _clean_string(label).casefold()
    button_href = _clean_string(button.get("href"))
    button_label = _clean_string(button.get("label")).casefold()
    if href_value and button_href == href_value:
        return True
    if label_value and button_label == label_value:
        return True
    return False


def _promote_asset_detail_actions(
    buttons_by_zone: dict[str, list[dict]],
    *,
    assign_url: str,
    qr_url: str,
) -> dict[str, list[dict]]:
    header_buttons = list(buttons_by_zone.get(AssetActionButton.ZONE_HEADER, []))
    quick_buttons = list(buttons_by_zone.get(AssetActionButton.ZONE_QUICK, []))

    if qr_url:
        header_buttons = [button for button in header_buttons if not _match_action_button(button, href=qr_url)]
        quick_buttons = [button for button in quick_buttons if not _match_action_button(button, href=qr_url)]

    if assign_url:
        quick_buttons = [button for button in quick_buttons if not _match_action_button(button, href=assign_url)]
        if not any(_match_action_button(button, href=assign_url) for button in header_buttons):
            header_buttons.insert(
                0,
                {
                    "label": "Riassegna",
                    "style": AssetActionButton.STYLE_SECONDARY,
                    "href": assign_url,
                    "data_action": "",
                    "new_tab": False,
                },
            )

    buttons_by_zone[AssetActionButton.ZONE_HEADER] = header_buttons
    buttons_by_zone[AssetActionButton.ZONE_QUICK] = quick_buttons
    return buttons_by_zone


def _handle_detail_section_layout_request(request: HttpRequest) -> tuple[bool, str]:
    action = _clean_string(request.POST.get("action"))
    valid_sizes = {key for key, _ in AssetDetailSectionLayout.SIZE_CHOICES}
    valid_codes = {key for key, _ in AssetDetailSectionLayout.SECTION_CHOICES}

    if action == "update_detail_section_layout_bulk":
        bulk_field = _clean_string(request.POST.get("bulk_field"))
        apply_scope = _clean_string(request.POST.get("apply_scope")) or "selected"
        selected_ids = [
            row
            for row in {
                _as_int(value, default=0)
                for value in request.POST.getlist("selected_layout_ids")
            }
            if row > 0
        ]

        if apply_scope == "all":
            layouts = list(AssetDetailSectionLayout.objects.order_by("sort_order", "id"))
        else:
            layouts = list(AssetDetailSectionLayout.objects.filter(pk__in=selected_ids).order_by("sort_order", "id"))

        if not layouts:
            return False, "Seleziona almeno un riquadro oppure usa l'opzione per applicare a tutti."

        if bulk_field == "grid_size":
            bulk_value = _clean_string(request.POST.get("bulk_grid_size"))
            if bulk_value not in valid_sizes:
                return False, "Dimensione bulk non valida."
            for layout in layouts:
                layout.grid_size = bulk_value
                layout.save(update_fields=["grid_size", "updated_at"])
            return True, f"Dimensione aggiornata per {len(layouts)} riquadri."

        if bulk_field == "is_visible":
            bulk_value = _clean_string(request.POST.get("bulk_is_visible"))
            if bulk_value not in {"visible", "hidden"}:
                return False, "Stato visibilita bulk non valido."
            is_visible = bulk_value == "visible"
            for layout in layouts:
                layout.is_visible = is_visible
                layout.save(update_fields=["is_visible", "updated_at"])
            return True, f"Visibilita aggiornata per {len(layouts)} riquadri."

        return False, "Parametro bulk non valido."

    if action == "move_detail_section_layout":
        layout_id = _as_int(request.POST.get("layout_id"), default=0)
        move_direction = _clean_string(request.POST.get("direction")).lower()
        if move_direction not in {"up", "down"}:
            return False, "Direzione di spostamento non valida."
        ordered_layouts = list(AssetDetailSectionLayout.objects.order_by("sort_order", "id"))
        current_index = next(
            (index for index, row in enumerate(ordered_layouts) if row.id == layout_id),
            -1,
        )
        if current_index < 0:
            return False, "Riquadro dettaglio non trovato."
        target_index = current_index - 1 if move_direction == "up" else current_index + 1
        if target_index < 0 or target_index >= len(ordered_layouts):
            return True, "Posizione riquadro invariata."
        moved_layout = ordered_layouts.pop(current_index)
        ordered_layouts.insert(target_index, moved_layout)
        changed_layouts: list[AssetDetailSectionLayout] = []
        for index, row in enumerate(ordered_layouts, start=1):
            expected_order = index * 10
            if row.sort_order != expected_order:
                row.sort_order = expected_order
                changed_layouts.append(row)
        if changed_layouts:
            AssetDetailSectionLayout.objects.bulk_update(changed_layouts, ["sort_order"])
        return True, f'Riquadro "{moved_layout.get_code_display()}" spostato.'

    if action != "update_detail_section_layout":
        return False, "Azione layout dettaglio non valida."

    layout_id = _as_int(request.POST.get("layout_id"), default=0)
    layout = AssetDetailSectionLayout.objects.filter(pk=layout_id).first()
    if not layout:
        return False, "Riquadro dettaglio non trovato."

    code = _clean_string(request.POST.get("code")) or layout.code
    if code not in valid_codes:
        code = layout.code
    grid_size = _clean_string(request.POST.get("grid_size")) or layout.grid_size
    if grid_size not in valid_sizes:
        grid_size = layout.grid_size

    layout.code = code
    layout.grid_size = grid_size
    layout.sort_order = _as_int(request.POST.get("sort_order"), default=layout.sort_order)
    layout.is_visible = bool(request.POST.get("is_visible"))
    layout.save(update_fields=["code", "grid_size", "sort_order", "is_visible", "updated_at"])
    return True, f"Riquadro \"{layout.get_code_display()}\" aggiornato."


def _build_asset_detail_section_cards(
    *,
    detail_specs_title: str,
    detail_timeline_title: str,
    detail_maintenance_title: str,
    detail_tickets_title: str,
    profile_card_title: str,
    detail_assignment_title: str,
    quick_action_buttons: list[dict],
    map_marker,
    doc_category_labels: dict,
    spec_pairs: list[tuple[str, str]],
    profile_rows: list[dict[str, str]],
    license_rows: list[dict[str, object]],
    ticket_rows: list[dict[str, object]],
) -> list[dict[str, str]]:
    cards_by_code = {
        AssetDetailSectionLayout.SECTION_SPECS: {
            "code": AssetDetailSectionLayout.SECTION_SPECS,
            "title": detail_specs_title,
            # Fusa nella card "Anagrafica e assegnazione" come gruppo Specifiche tecniche.
            "render": False,
        },
        AssetDetailSectionLayout.SECTION_TIMELINE: {
            "code": AssetDetailSectionLayout.SECTION_TIMELINE,
            "title": detail_timeline_title,
            # Fusa nella card "Anagrafica e assegnazione" (gruppo storico ciclo di vita).
            "render": False,
        },
        AssetDetailSectionLayout.SECTION_MAINTENANCE: {
            "code": AssetDetailSectionLayout.SECTION_MAINTENANCE,
            "title": detail_maintenance_title,
            "render": True,
        },
        AssetDetailSectionLayout.SECTION_TICKETS: {
            "code": AssetDetailSectionLayout.SECTION_TICKETS,
            "title": detail_tickets_title,
            # Il "Registro manutenzione" include SOLO i ticket MAN con
            # include_in_maintenance_register=True: i ticket IT (e i MAN non
            # marcati) non comparirebbero da nessuna parte. La card resta quindi
            # la vista completa dei ticket collegati all'asset.
            "render": bool(ticket_rows),
        },
        AssetDetailSectionLayout.SECTION_PROFILE: {
            "code": AssetDetailSectionLayout.SECTION_PROFILE,
            "title": profile_card_title,
            "render": bool(profile_rows),
        },
        AssetDetailSectionLayout.SECTION_LICENSES: {
            "code": AssetDetailSectionLayout.SECTION_LICENSES,
            "title": "Licenze software",
            "render": bool(license_rows),
        },
        AssetDetailSectionLayout.SECTION_PERIODIC: {
            "code": AssetDetailSectionLayout.SECTION_PERIODIC,
            "title": "Manutenzione periodica",
            # Fusa nel "Registro manutenzione" come accordion dedicato.
            "render": False,
        },
        AssetDetailSectionLayout.SECTION_QR: {
            "code": AssetDetailSectionLayout.SECTION_QR,
            "title": "QR asset",
            "render": True,
        },
        AssetDetailSectionLayout.SECTION_QUICK_ACTIONS: {
            "code": AssetDetailSectionLayout.SECTION_QUICK_ACTIONS,
            "title": "Azioni rapide",
            "render": bool(quick_action_buttons) and len(quick_action_buttons) <= 2,
        },
        AssetDetailSectionLayout.SECTION_ASSIGNMENT: {
            "code": AssetDetailSectionLayout.SECTION_ASSIGNMENT,
            "title": detail_assignment_title,
            # Fusa nella card PROFILE ("Anagrafica e assegnazione"): non renderizzata
            # come card a sé per evitare duplicazione (reparto/posizione/assegnatario).
            "render": False,
        },
        AssetDetailSectionLayout.SECTION_MAP: {
            "code": AssetDetailSectionLayout.SECTION_MAP,
            "title": "Posizione in officina",
            "render": bool(map_marker),
        },
        AssetDetailSectionLayout.SECTION_DOCUMENTS: {
            "code": AssetDetailSectionLayout.SECTION_DOCUMENTS,
            "title": "Documenti",
            "render": bool(doc_category_labels),
        },
    }

    cards: list[dict[str, str]] = []
    for layout in _ensure_default_asset_detail_section_layouts():
        payload = cards_by_code.get(layout.code)
        if payload is None or not layout.is_visible or not payload["render"]:
            continue
        cards.append(
            {
                **payload,
                "size_class": _detail_grid_size_class(layout.grid_size),
            }
        )
    return cards


def _can_manage_ticket_type_for_asset_view(request: HttpRequest, ticket_type: str) -> bool:
    from tickets.models import TicketImpostazioni
    if not request.user.is_authenticated:
        return False
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if request.user.is_superuser or is_legacy_admin(legacy_user):
        return True
    cfg = TicketImpostazioni.objects.filter(tipo=ticket_type).first()
    if not cfg:
        return False
    acl = cfg.acl_gestione or []
    username = request.user.get_username().strip().lower()
    email = (request.user.email or "").strip().lower()
    return any(str(value).strip().lower() in {username, email} for value in acl if value)


def _ticket_belongs_to_request_user(request: HttpRequest, ticket: Ticket) -> bool:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    request_name = (
        (getattr(legacy_user, "nome", "") or "").strip()
        or request.user.get_full_name()
        or request.user.get_username()
    )
    request_email = (
        (getattr(legacy_user, "email", "") or "").strip().lower()
        or (request.user.email or "").strip().lower()
    )
    request_legacy_id = getattr(legacy_user, "id", None)
    ticket_email = (ticket.richiedente_email or "").strip().lower()
    return bool(
        (request_legacy_id and ticket.richiedente_legacy_user_id == request_legacy_id)
        or (request_name and ticket.richiedente_nome == request_name)
        or (request_email and ticket_email == request_email)
    )


def _asset_ticket_detail_url(
    request: HttpRequest,
    ticket: Ticket,
    manageable_ticket_types: set[str],
) -> str:
    if ticket.tipo in manageable_ticket_types:
        return reverse("tickets:gestione_detail", kwargs={"pk": ticket.pk})
    if _ticket_belongs_to_request_user(request, ticket):
        return reverse("tickets:detail", kwargs={"pk": ticket.pk})
    return ""


def _asset_deadlines_context(request: HttpRequest, asset) -> dict[str, object]:
    """Tutte le scadenze aperte dell'asset nei prossimi 12 mesi, dalla stessa fonte
    di Calendario e Scadenzario: manutenzioni, adempimenti, licenze e contratti
    (anche quelli sulla sua categoria). Le scadute restano finche' sono aperte."""
    from ..services import deadline_feed as feed

    today = timezone.localdate()
    rows = feed.collect(
        start=None,
        end=today + timedelta(days=365),
        filters=feed.FeedFilters(kinds=feed.allowed_kinds(request), asset_id=asset.id),
        today=today,
    )
    for row in rows:
        row.days = row.days_until(today)
        row.days_late = -row.days if row.days < 0 else 0
    return {
        "asset_deadline_rows": rows[:12],
        "asset_deadline_total": len(rows),
        "asset_deadline_overdue": sum(1 for row in rows if row.state == feed.STATE_OVERDUE),
        "asset_deadline_list_url": f"{reverse('assets:maintenance_scadenze')}?window=&asset={asset.id}",
    }


def _asset_maintenance_plans_context(asset) -> dict[str, object]:
    """I piani del nuovo dominio che riguardano questo asset, per la sua scheda.

    Finche' vivevano solo in una pagina a parte, chi apriva la scheda di una
    macchina non poteva sapere quali manutenzioni la riguardassero: la domanda
    piu' ovvia davanti a un asset.
    """
    from ..models import MaintenanceOccurrence
    from ..services import maintenance_domain as maintenance_dom

    resolutions = maintenance_dom.resolve_asset_plans(asset)
    if not resolutions:
        return {"asset_plan_rows": [], "asset_plan_conflict_count": 0}

    next_by_plan: dict[int, MaintenanceOccurrence] = {}
    for occurrence in (
        MaintenanceOccurrence.objects.filter(
            asset=asset, status=MaintenanceOccurrence.STATUS_OPEN
        )
        .select_related("work_order")
        .order_by("due_date")
    ):
        next_by_plan.setdefault(occurrence.plan_id, occurrence)

    today = timezone.localdate()
    rows = []
    for resolution in resolutions:
        occurrence = next_by_plan.get(resolution.plan.pk)
        rows.append(
            {
                "resolution": resolution,
                "occurrence": occurrence,
                "state": maintenance_dom.occurrence_state_payload(occurrence, today=today)
                if occurrence is not None
                else None,
            }
        )
    return {
        "asset_plan_rows": rows,
        "asset_plan_conflict_count": sum(1 for row in rows if row["resolution"].is_conflict),
    }
