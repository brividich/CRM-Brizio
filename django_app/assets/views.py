from __future__ import annotations

import io
import json
import logging
import os
import re
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from html import escape
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.paginator import Paginator
from django.db import DatabaseError, IntegrityError, connections, transaction
from django.db.models import Avg, Count, Q
from django.http import HttpRequest, HttpResponse, JsonResponse
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

from admin_portale.decorators import legacy_admin_required
from config.env_config import get_first_env_value, load_env_file_values, resolve_env_value, update_env_file_values
from core.acl import user_can_modulo_action
from core.audit import log_action
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
from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime
from .forms import (
    AssistanceContractForm,
    AssetAdministrativeDeadlineForm,
    AssetAssignmentForm,
    AssetComponentForm,
    AssetFilterForm,
    AssetForm,
    AssetLabelTemplateForm,
    MaintenanceInterventionTemplateForm,
    MaintenanceRuleForm,
    MaintenanceRuleAssetOverrideForm,
    PeriodicVerificationForm,
    PlantLayoutForm,
    SoftwareLicenseForm,
    WorkMachineAssetForm,
    WorkMachineFilterForm,
    WorkOrderCloseForm,
    WorkOrderForm,
)
from .models import (
    Asset,
    AssetActionButton,
    AssetAdministrativeDeadline,
    AssetCategory,
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
    AssetMaintenanceRuleState,
    AssetCalendarEvent,
    AssistanceContract,
    AssetReportDefinition,
    AssetReportTemplate,
    AssetSidebarButton,
    SoftwareLicense,
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
    WorkOrderLog,
)
from .maintenance import (
    build_workorder_prefill_payload,
    build_day_based_maintenance_schedule_rows,
    contract_state_payload,
    get_applicable_assistance_contracts,
    get_primary_assistance_contract,
    normalize_workorder_source,
    resolve_asset_maintenance_rules,
    sync_workorder_maintenance_state,
    upsert_asset_maintenance_rule_state,
)

logger = logging.getLogger(__name__)

DEFAULT_IMPORT_SHEETS = ",".join(
    [
        "LAN A 203.0.113.x",
        "LAN B 198.51.100.x",
        "LAN C 192.0.2.x",
    ]
)
ASSET_DOCUMENT_ALLOWED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".csv",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}
ASSET_DOCUMENT_ALLOWED_MIMES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroenabled.12",
    "text/csv",
    "application/csv",
    "text/plain",
    "image/jpeg",
    "image/png",
    "image/webp",
}
ASSET_DOCUMENT_MAX_BYTES = 20 * 1024 * 1024
ASSET_DOCUMENT_UPLOAD_FIELDS = {
    AssetDocument.CATEGORY_SPECIFICHE: "upload_specs_files",
    AssetDocument.CATEGORY_MANUALI: "upload_manuals_files",
    AssetDocument.CATEGORY_INTERVENTI: "upload_interventions_files",
}
ASSET_DOCUMENT_CATEGORY_LABELS = dict(AssetDocument.CATEGORY_CHOICES)
REPORT_TEMPLATE_ALLOWED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".ppt",
    ".pptx",
    ".html",
    ".htm",
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

LIST_ACTIONS = {
    "create_list_option",
    "update_list_option",
    "delete_list_option",
}

BUTTON_ACTIONS = {
    "create_action_button",
    "update_action_button",
    "delete_action_button",
}

DETAIL_FIELD_ACTIONS = {
    "seed_detail_fields",
    "create_detail_field",
    "update_detail_field",
    "update_detail_field_bulk",
    "delete_detail_field",
}

DETAIL_LAYOUT_ACTIONS = {
    "update_detail_section_layout",
    "update_detail_section_layout_bulk",
    "move_detail_section_layout",
}

LIST_LAYOUT_ACTIONS = {
    "update_asset_list_layout",
    "reset_asset_list_layout",
}

CATEGORY_ACTIONS = {
    "create_asset_category",
    "update_asset_category",
    "delete_asset_category",
    "create_asset_category_field",
    "update_asset_category_field",
    "delete_asset_category_field",
}

HEADER_TOOL_ACTIONS = {"update_header_tool"}

SIDEBAR_ACTIONS = {
    "seed_sidebar_buttons",
    "create_sidebar_button",
    "update_sidebar_button",
    "delete_sidebar_button",
    "reset_sidebar_buttons",
    "clear_sidebar_buttons",
}

UI_LABEL_TRANSLATIONS = {
    "Dashboard": "Cruscotto",
    "Hardware": "Dispositivi",
    "Servers": "Server",
    "Workstations": "Postazioni di lavoro",
    "Networking": "Rete",
    "Software Licenses": "Licenze software",
    "Lifecycle Tracking": "Tracciamento ciclo di vita",
    "Compliance Reports": "Report conformita",
    "Main Navigation": "Navigazione principale",
    "Analytics & Risk": "Analisi e rischio",
    "Operations": "Operativita",
    "Print Label": "Stampa etichetta",
    "Edit Details": "Modifica dettagli",
    "Reassign": "Riassegna",
    "Log Repair": "Registra intervento",
    "Refresh Data": "Aggiorna dati",
    "Retire Asset": "Dismetti bene",
    "Manufacturer": "Produttore",
    "Model": "Modello",
    "Assignment to": "Assegnato a",
    "Assignment reparto": "Reparto assegnazione",
    "Assignment location": "Posizione assegnazione",
    "Header": "Intestazione",
    "Quick Actions": "Azioni rapide",
    "Link": "Collegamento",
    "Print": "Stampa",
    "Refresh": "Aggiorna",
    "Default": "Predefinito",
    "Primary": "Primario",
    "Secondary": "Secondario",
    "Danger": "Pericolo",
}

ASSET_LIST_BASE_COLUMN_CHOICES = [
    ("name", "Nome & Tag"),
    ("status", "Stato"),
    ("category", "Categoria"),
    ("assigned", "Assegnato a"),
    ("last_seen", "Ultimo aggiornamento"),
    ("reparto", "Reparto"),
    ("serial_number", "Seriale"),
    ("manufacturer", "Produttore"),
    ("model", "Modello"),
    ("vlan", "VLAN"),
    ("ip", "IP"),
    ("assignment_location", "Posizione assegnazione"),
]
ITALIAN_MONTH_NAMES = [
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
]
OUTLOOK_CALENDAR_TIMEZONE = "W. Europe Standard Time"
OUTLOOK_CALENDAR_START_HOUR = 8
OUTLOOK_CALENDAR_DURATION_MINUTES = 60


def _clean_string(value: str | None) -> str:
    return (value or "").strip()


def _ui_label(value: str | None) -> str:
    label = _clean_string(value)
    if not label:
        return ""
    return UI_LABEL_TRANSLATIONS.get(label, label)


def _ui_choices(raw_choices) -> list[tuple[str, str]]:
    return [(code, _ui_label(label)) for code, label in raw_choices]


def _coalesce_str(*values) -> str:
    for value in values:
        row = _clean_string(str(value)) if value is not None else ""
        if row:
            return row
    return ""


def _format_filesize(num_bytes: int | None) -> str:
    try:
        size = int(num_bytes or 0)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return ""


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


def _model_table_exists(model_class) -> bool:
    connection = connections[model_class.objects.db]
    try:
        with connection.cursor() as cursor:
            table_names = connection.introspection.table_names(cursor)
    except DatabaseError:
        return False
    return model_class._meta.db_table in table_names


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

LABEL_TEMPLATE_DEFAULT_CODE = "default"
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
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


def _normalize_label_hex(value: str | None, fallback: str) -> str:
    row = _clean_string(value).upper()
    if HEX_COLOR_RE.match(row):
        return row
    return fallback


def _asset_label_field_catalog() -> list[dict[str, str]]:
    catalog = [
        {"key": "asset_tag", "label": "Tag asset", "group": "Asset"},
        {"key": "name", "label": "Nome bene", "group": "Asset"},
        {"key": "asset_category", "label": "Categoria asset", "group": "Asset"},
        {"key": "asset_type", "label": "Tipo bene", "group": "Asset"},
        {"key": "status", "label": "Stato", "group": "Asset"},
        {"key": "reparto", "label": "Reparto", "group": "Asset"},
        {"key": "manufacturer", "label": "Produttore", "group": "Asset"},
        {"key": "model", "label": "Modello", "group": "Asset"},
        {"key": "serial_number", "label": "Numero seriale", "group": "Asset"},
        {"key": "assignment_to", "label": "Assegnato a", "group": "Assegnazione"},
        {"key": "assignment_reparto", "label": "Reparto assegnazione", "group": "Assegnazione"},
        {"key": "assignment_location", "label": "Posizione assegnazione", "group": "Assegnazione"},
        {"key": "sharepoint_folder_path", "label": "Percorso SharePoint", "group": "SharePoint"},
        {"key": "sharepoint_folder_url", "label": "URL SharePoint", "group": "SharePoint"},
        {"key": "year", "label": "Anno macchina", "group": "Macchina"},
        {"key": "x_mm", "label": "Corsa X", "group": "Macchina"},
        {"key": "y_mm", "label": "Corsa Y", "group": "Macchina"},
        {"key": "z_mm", "label": "Corsa Z", "group": "Macchina"},
        {"key": "diameter_mm", "label": "Diametro", "group": "Macchina"},
        {"key": "spindle_mm", "label": "Mandrino", "group": "Macchina"},
        {"key": "tmc", "label": "TMC", "group": "Macchina"},
        {"key": "tcr_enabled", "label": "TCR", "group": "Macchina"},
        {"key": "pressure_bar", "label": "Pressione", "group": "Macchina"},
        {"key": "cnc_controlled", "label": "Controllo CNC", "group": "Macchina"},
        {"key": "five_axes", "label": "5 assi", "group": "Macchina"},
        {"key": "accuracy_from", "label": "Accuracy from", "group": "Macchina"},
        {"key": "next_maintenance_date", "label": "Prossima manutenzione", "group": "Macchina"},
        {"key": "maintenance_reminder_days", "label": "Soglia reminder", "group": "Macchina"},
    ]
    for field_def in AssetCustomField.objects.filter(is_active=True).order_by("sort_order", "id"):
        catalog.append(
            {
                "key": f"extra__{field_def.code}",
                "label": field_def.label,
                "group": "Campi personalizzati",
            }
        )
    return catalog


def _asset_label_field_catalog_map() -> dict[str, dict[str, str]]:
    return {row["key"]: row for row in _asset_label_field_catalog()}


def _asset_label_field_choices() -> list[tuple[str, str]]:
    return [(row["key"], f"{row['label']} [{row['group']}]") for row in _asset_label_field_catalog()]


def _asset_type_label(asset_type: str | None) -> str:
    return dict(Asset.TYPE_CHOICES).get(_clean_string(asset_type), _clean_string(asset_type) or "Generale")


def _get_default_asset_label_template() -> AssetLabelTemplate:
    template, _created = AssetLabelTemplate.objects.get_or_create(
        code=LABEL_TEMPLATE_DEFAULT_CODE,
        defaults={"scope": AssetLabelTemplate.SCOPE_DEFAULT, "asset_type": "", "name": "Etichetta predefinita"},
    )
    changed = False
    if template.scope != AssetLabelTemplate.SCOPE_DEFAULT:
        template.scope = AssetLabelTemplate.SCOPE_DEFAULT
        changed = True
    if template.asset_type:
        template.asset_type = ""
        changed = True
    if template.asset_id is not None:
        template.asset = None
        changed = True
    if changed:
        template.save()
    return template


def _default_asset_label_logo_path() -> Path:
    return Path(__file__).resolve().parents[1] / "core" / "static" / "core" / "img" / "logo_novicrom.png"


def _default_asset_label_logo_url() -> str:
    return static("core/img/logo_novicrom.png")


def _asset_label_logo_source_path(template: AssetLabelTemplate) -> str:
    if template.logo_file and getattr(template.logo_file, "path", ""):
        logo_path = Path(template.logo_file.path)
        if logo_path.exists():
            return str(logo_path)
    default_logo = _default_asset_label_logo_path()
    if default_logo.exists():
        return str(default_logo)
    return ""


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


def _find_asset_type_label_template(asset_type: str | None) -> AssetLabelTemplate | None:
    asset_type_value = _clean_string(asset_type)
    if not asset_type_value:
        return None
    return (
        AssetLabelTemplate.objects.filter(
            scope=AssetLabelTemplate.SCOPE_ASSET_TYPE,
            asset_type=asset_type_value,
            asset__isnull=True,
        )
        .order_by("id")
        .first()
    )


def _find_asset_override_label_template(asset: Asset | None) -> AssetLabelTemplate | None:
    if asset is None or not getattr(asset, "pk", None):
        return None
    return (
        AssetLabelTemplate.objects.filter(
            scope=AssetLabelTemplate.SCOPE_ASSET,
            asset=asset,
        )
        .order_by("id")
        .first()
    )


def _resolve_asset_label_template(asset: Asset | None = None) -> AssetLabelTemplate:
    if asset is not None:
        template = _find_asset_override_label_template(asset)
        if template is not None:
            return template
        template = _find_asset_type_label_template(asset.asset_type)
        if template is not None:
            return template
    return _get_default_asset_label_template()


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


def _normalize_asset_label_fields(keys: list[str] | tuple[str, ...] | None, catalog_map: dict[str, dict[str, str]]) -> list[str]:
    cleaned: list[str] = []
    for row in keys or []:
        key = _clean_string(row)
        if key and key in catalog_map and key not in cleaned:
            cleaned.append(key)
    return cleaned


def _format_label_number(value) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _format_asset_label_value(asset: Asset | None, field_key: str, catalog_map: dict[str, dict[str, str]] | None = None) -> str:
    if asset is None:
        return ""
    work_machine = getattr(asset, "work_machine", None)
    extra = asset.extra_columns if isinstance(asset.extra_columns, dict) else {}

    if field_key.startswith("extra__"):
        raw_value = extra.get(field_key.replace("extra__", ""), "")
    elif field_key == "asset_category":
        raw_value = asset.category_label
    elif field_key == "asset_type":
        raw_value = asset.get_asset_type_display()
    elif field_key == "status":
        raw_value = asset.get_status_display()
    elif field_key == "sharepoint_folder_path":
        raw_value = _normalize_sharepoint_path(asset.sharepoint_folder_path)
    elif field_key == "sharepoint_folder_url":
        raw_value = _clean_string(asset.sharepoint_folder_url)
    elif field_key in {
        "year",
        "x_mm",
        "y_mm",
        "z_mm",
        "diameter_mm",
        "spindle_mm",
        "tmc",
        "tcr_enabled",
        "pressure_bar",
        "cnc_controlled",
        "five_axes",
        "accuracy_from",
        "next_maintenance_date",
        "maintenance_reminder_days",
    }:
        raw_value = getattr(work_machine, field_key, "") if work_machine is not None else ""
    else:
        raw_value = getattr(asset, field_key, "")

    if raw_value in (None, ""):
        return ""
    if isinstance(raw_value, bool):
        return "Si" if raw_value else "No"
    if isinstance(raw_value, datetime):
        raw_value = raw_value.date()
    if isinstance(raw_value, date):
        return raw_value.strftime("%d/%m/%Y")

    if field_key in {"x_mm", "y_mm", "z_mm", "diameter_mm", "spindle_mm"}:
        return f"{_format_label_number(raw_value)} mm"
    if field_key == "pressure_bar":
        return f"{_format_label_number(raw_value)} bar"
    if field_key == "maintenance_reminder_days":
        return f"{_format_label_number(raw_value)} gg"
    return _clean_string(_format_label_number(raw_value) if field_key in {"year", "tmc"} else str(raw_value))


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
        "sharepoint_folder_path": "Macchine/CN5/ML-000001",
        "sharepoint_folder_url": "https://contoso.sharepoint.com/sites/example/Shared%20Documents/CN5/ML-000001",
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
        "next_maintenance_date": (timezone.localdate() + timedelta(days=30)).strftime("%d/%m/%Y"),
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
    target_url = request.build_absolute_uri(reverse("assets:asset_list"))
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


def _truncate_pdf_text(pdf: canvas.Canvas, text: str, *, font_name: str, font_size: float, max_width: float) -> str:
    row = _clean_string(text)
    if not row:
        return ""
    if pdf.stringWidth(row, font_name, font_size) <= max_width:
        return row
    suffix = "..."
    while row and pdf.stringWidth(f"{row}{suffix}", font_name, font_size) > max_width:
        row = row[:-1]
    return f"{row.rstrip()}{suffix}" if row else suffix


def _month_start_from_value(raw_value: str | None, *, today: date | None = None) -> date:
    reference = today or timezone.localdate()
    month_value = _clean_string(raw_value)
    if month_value:
        try:
            return datetime.strptime(month_value, "%Y-%m").date().replace(day=1)
        except ValueError:
            pass
    return reference.replace(day=1)


def _month_end(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1) - timedelta(days=1)
    return date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)


def _month_label(month_start: date) -> str:
    return f"{ITALIAN_MONTH_NAMES[month_start.month - 1]} {month_start.year}"


def _work_machine_maintenance_month_pdf_url(*, month_code: str, reparto_filter: str = "") -> str:
    params = [f"month={quote(month_code)}"]
    reparto_value = _clean_string(reparto_filter)
    if reparto_value:
        params.append(f"reparto={quote(reparto_value)}")
    return f'{reverse("assets:work_machine_maintenance_month_pdf")}?{"&".join(params)}'


def _periodic_verifications_page_url(*, asset_id: int = 0, edit_id: int = 0) -> str:
    params: list[str] = []
    if asset_id:
        params.append(f"asset={int(asset_id)}")
    if edit_id:
        params.append(f"edit={int(edit_id)}")
    base_url = reverse("assets:periodic_verifications")
    return f"{base_url}?{'&'.join(params)}" if params else base_url


def _asset_component_page_url(*, asset_id: int = 0) -> str:
    if asset_id:
        return reverse("assets:asset_component_list_for_asset", kwargs={"asset_id": int(asset_id)})
    return reverse("assets:asset_component_list")


def _asset_component_create_page_url(*, asset_id: int = 0) -> str:
    base_url = reverse("assets:asset_component_create")
    if asset_id:
        return f"{base_url}?asset={int(asset_id)}"
    return base_url


def _asset_administrative_deadline_page_url(
    *,
    asset_id: int = 0,
    component_id: int = 0,
    deadline_type: str = "",
    status: str = "",
    q: str = "",
) -> str:
    params: list[str] = []
    if asset_id:
        params.append(f"asset={int(asset_id)}")
    if component_id:
        params.append(f"component={int(component_id)}")
    deadline_type_value = _clean_string(deadline_type).upper()
    if deadline_type_value:
        params.append(f"deadline_type={quote(deadline_type_value)}")
    status_value = _clean_string(status).lower()
    if status_value:
        params.append(f"status={quote(status_value)}")
    q_value = _clean_string(q)
    if q_value:
        params.append(f"q={quote(q_value)}")
    base_url = reverse("assets:asset_administrative_deadline_list")
    return f"{base_url}?{'&'.join(params)}" if params else base_url


def _asset_administrative_deadline_create_page_url(*, asset_id: int = 0, component_id: int = 0) -> str:
    params: list[str] = []
    if asset_id:
        params.append(f"asset={int(asset_id)}")
    if component_id:
        params.append(f"component={int(component_id)}")
    base_url = reverse("assets:asset_administrative_deadline_create")
    return f"{base_url}?{'&'.join(params)}" if params else base_url


def _maintenance_template_list_page_url(*, category_id: int = 0, active: str = "") -> str:
    params: list[str] = []
    if category_id:
        params.append(f"category={int(category_id)}")
    active_value = _clean_string(active).lower()
    if active_value:
        params.append(f"active={quote(active_value)}")
    base_url = reverse("assets:maintenance_template_list")
    return f"{base_url}?{'&'.join(params)}" if params else base_url


def _maintenance_rule_list_page_url(
    *,
    category_id: int = 0,
    template_id: int = 0,
    threshold_type: str = "",
    active: str = "",
) -> str:
    params: list[str] = []
    if category_id:
        params.append(f"category={int(category_id)}")
    if template_id:
        params.append(f"template={int(template_id)}")
    threshold_value = _clean_string(threshold_type).upper()
    if threshold_value:
        params.append(f"threshold_type={quote(threshold_value)}")
    active_value = _clean_string(active).lower()
    if active_value:
        params.append(f"active={quote(active_value)}")
    base_url = reverse("assets:maintenance_rule_list")
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


def _asset_maintenance_rule_list_page_url(asset_id: int, *, focus_rule_id: int = 0) -> str:
    base_url = reverse("assets:asset_maintenance_rule_list", kwargs={"asset_id": int(asset_id)})
    if focus_rule_id:
        return f"{base_url}?focus_rule={int(focus_rule_id)}#rule-{int(focus_rule_id)}"
    return base_url


def _maintenance_schedule_page_url(
    *,
    asset_id: int = 0,
    status: str = "",
    category_id: int = 0,
    reparto: str = "",
    coverage: str = "",
    q: str = "",
) -> str:
    params = []
    if asset_id:
        params.append(f"asset={int(asset_id)}")
    status_value = _clean_string(status)
    if status_value:
        params.append(f"status={quote(status_value)}")
    if category_id:
        params.append(f"category={int(category_id)}")
    reparto_value = _clean_string(reparto)
    if reparto_value:
        params.append(f"reparto={quote(reparto_value)}")
    coverage_value = _clean_string(coverage)
    if coverage_value:
        params.append(f"coverage={quote(coverage_value)}")
    q_value = _clean_string(q)
    if q_value:
        params.append(f"q={quote(q_value)}")
    base_url = reverse("assets:maintenance_schedule")
    return f"{base_url}?{'&'.join(params)}" if params else base_url


def _workorder_create_page_url(*, asset_id: int, rule_id: int = 0, source: str = "") -> str:
    params: list[str] = []
    if rule_id:
        params.append(f"rule={int(rule_id)}")
    normalized_source = normalize_workorder_source(source)
    if normalized_source and normalized_source != "manual":
        params.append(f"source={quote(normalized_source)}")
    base_url = reverse("assets:wo_create", kwargs={"id": int(asset_id)})
    return f"{base_url}?{'&'.join(params)}" if params else base_url


def _assistance_contracts_page_url(
    *,
    asset_id: int = 0,
    edit_id: int = 0,
    supplier_filter: int = 0,
    state: str = "",
    scope: str = "",
    q: str = "",
) -> str:
    params = []
    if asset_id:
        params.append(f"asset={int(asset_id)}")
    if edit_id:
        params.append(f"edit={int(edit_id)}")
    if supplier_filter:
        params.append(f"supplier={int(supplier_filter)}")
    state_value = _clean_string(state)
    if state_value:
        params.append(f"state={quote(state_value)}")
    scope_value = _clean_string(scope)
    if scope_value:
        params.append(f"scope={quote(scope_value)}")
    q_value = _clean_string(q)
    if q_value:
        params.append(f"q={quote(q_value)}")
    base_url = reverse("assets:assistance_contract_list")
    return f"{base_url}?{'&'.join(params)}" if params else base_url


def _software_licenses_page_url(
    *,
    asset_id: int = 0,
    anagrafica_id: int = 0,
    edit_id: int = 0,
    category: str = "",
    status: str = "",
    assignee: str = "",
    q: str = "",
) -> str:
    params: list[str] = []
    if asset_id:
        params.append(f"asset={int(asset_id)}")
    if anagrafica_id:
        params.append(f"anagrafica={int(anagrafica_id)}")
    if edit_id:
        params.append(f"edit={int(edit_id)}")
    category_value = _clean_string(category)
    if category_value:
        params.append(f"category={quote(category_value)}")
    status_value = _clean_string(status)
    if status_value:
        params.append(f"status={quote(status_value)}")
    assignee_value = _clean_string(assignee)
    if assignee_value:
        params.append(f"assignee={quote(assignee_value)}")
    q_value = _clean_string(q)
    if q_value:
        params.append(f"q={quote(q_value)}")
    base_url = reverse("assets:software_license_list")
    return f"{base_url}?{'&'.join(params)}" if params else base_url


def _asset_maintenance_rule_override_create_page_url(*, asset_id: int, rule_id: int) -> str:
    return reverse(
        "assets:asset_maintenance_rule_override_create",
        kwargs={"asset_id": int(asset_id), "rule_id": int(rule_id)},
    )


def _asset_maintenance_rule_override_edit_page_url(*, asset_id: int, override_id: int) -> str:
    return reverse(
        "assets:asset_maintenance_rule_override_edit",
        kwargs={"asset_id": int(asset_id), "id": int(override_id)},
    )


def _asset_maintenance_rule_override_reset_page_url(*, asset_id: int, override_id: int) -> str:
    return reverse(
        "assets:asset_maintenance_rule_override_reset",
        kwargs={"asset_id": int(asset_id), "id": int(override_id)},
    )


def _asset_report_pdf_url(asset_id: int) -> str:
    return reverse("assets:asset_report_pdf", kwargs={"id": int(asset_id)})


def _asset_administrative_deadline_state(
    deadline: AssetAdministrativeDeadline,
    *,
    today: date | None = None,
) -> dict[str, object]:
    current_day = today or timezone.localdate()
    days_until_due = deadline.days_until_due(reference_date=current_day)
    if not deadline.is_active:
        return {
            "status": "inactive",
            "label": "Disattiva",
            "badge_class": "muted",
            "days_until_due": days_until_due,
            "days_label": "Monitoraggio disattivato",
        }
    if days_until_due is None:
        return {
            "status": "upcoming",
            "label": "Programmato",
            "badge_class": "ok",
            "days_until_due": None,
            "days_label": "Data non disponibile",
        }
    warning_days = max(0, int(deadline.warning_days or 0))
    if days_until_due < 0:
        overdue_days = abs(days_until_due)
        return {
            "status": "overdue",
            "label": "Scaduta",
            "badge_class": "danger",
            "days_until_due": days_until_due,
            "days_label": f"Scaduta da {overdue_days} gg",
        }
    if days_until_due <= warning_days:
        if days_until_due == 0:
            day_label = "Scade oggi"
        else:
            day_label = f"Scade tra {days_until_due} gg"
        return {
            "status": "warning",
            "label": "In scadenza",
            "badge_class": "warn",
            "days_until_due": days_until_due,
            "days_label": day_label,
        }
    return {
        "status": "upcoming",
        "label": "Programmato",
        "badge_class": "ok",
        "days_until_due": days_until_due,
        "days_label": f"Scade tra {days_until_due} gg",
    }


def _asset_status_payload(asset: Asset) -> dict[str, str]:
    if asset.status == Asset.STATUS_IN_USE:
        badge_class = "ok"
    elif asset.status == Asset.STATUS_IN_REPAIR:
        badge_class = "danger"
    else:
        badge_class = "muted"
    return {
        "label": asset.get_status_display(),
        "badge_class": badge_class,
    }


def _workorder_status_payload(status: str) -> dict[str, str]:
    if status == WorkOrder.STATUS_DONE:
        return {"label": "Chiuso", "badge_class": "ok"}
    if status == WorkOrder.STATUS_CANCELED:
        return {"label": "Annullato", "badge_class": "muted"}
    return {"label": "Aperto", "badge_class": "info"}


def _workorder_kind_payload(kind: str) -> dict[str, str]:
    mapping = {
        WorkOrder.KIND_PREVENTIVE: "ok",
        WorkOrder.KIND_CORRECTIVE: "warn",
        WorkOrder.KIND_SAFETY: "danger",
        WorkOrder.KIND_CALIBRATION: "info",
        WorkOrder.KIND_OTHER: "muted",
    }
    return {
        "label": dict(WorkOrder.KIND_CHOICES).get(kind, kind),
        "badge_class": mapping.get(kind, "muted"),
    }


def _coverage_status_payload(*, is_covered: bool, contract: AssistanceContract | None = None) -> dict[str, str]:
    if is_covered or contract is not None:
        label = "Coperto da contratto"
        if contract is not None:
            label = "Contratto collegato"
        return {"label": label, "badge_class": "info"}
    return {"label": "Copertura non disponibile", "badge_class": "muted"}


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


def _maintenance_row_primary_action(
    *,
    asset: Asset,
    base_rule: MaintenanceRule | None,
    schedule_status: str,
    source: str,
) -> dict[str, str]:
    base_rule_id = getattr(base_rule, "id", 0)
    if schedule_status == "missing" and base_rule_id:
        return {
            "label": "Imposta prima esecuzione",
            "url": _asset_maintenance_rule_list_page_url(asset_id=asset.id, focus_rule_id=base_rule_id),
        }
    return {
        "label": "Crea intervento",
        "url": _workorder_create_page_url(asset_id=asset.id, rule_id=base_rule_id, source=source),
    }


def _contract_scope_payload(contract: AssistanceContract) -> dict[str, str]:
    if contract.asset_id and contract.asset:
        return {
            "label": "Asset",
            "detail": f"{contract.asset.asset_tag} - {contract.asset.name}",
            "badge_class": "info",
        }
    if contract.asset_category_id and contract.asset_category:
        return {
            "label": "Categoria",
            "detail": f"Categoria {contract.asset_category.label}",
            "badge_class": "info",
        }
    return {
        "label": "Generale",
        "detail": "Copertura trasversale",
        "badge_class": "muted",
    }


def _software_license_state_payload(license_row: SoftwareLicense, *, today: date | None = None) -> dict[str, object]:
    current_day = today or timezone.localdate()
    expiry_date = license_row.expiry_date
    if not license_row.is_active:
        return {"status": "inactive", "label": "Disattiva", "badge_class": "muted", "days_label": "Monitoraggio spento"}
    if isinstance(expiry_date, date):
        delta_days = (expiry_date - current_day).days
        if delta_days < 0:
            return {
                "status": "expired",
                "label": "Scaduta",
                "badge_class": "danger",
                "days_label": f"Scaduta da {abs(delta_days)} gg",
            }
        if delta_days <= 30:
            return {
                "status": "expiring",
                "label": "In scadenza",
                "badge_class": "warn",
                "days_label": f"Scade tra {delta_days} gg" if delta_days else "Scade oggi",
            }
    return {"status": "active", "label": "Attiva", "badge_class": "ok", "days_label": "In uso"}


def _anagrafica_employee_options() -> tuple[list[tuple[str, str]], dict[str, dict[str, str]]]:
    try:
        rows = list(
            AnagraficaDipendente.objects.all()
            .values(
                "id",
                "nome",
                "cognome",
                "aliasusername",
                "reparto",
                "email",
                "email_notifica",
                "utente_id",
            )
        )
    except DatabaseError:
        return [], {}

    options: list[tuple[str, str]] = []
    details: dict[str, dict[str, str]] = {}
    for row in rows:
        anagrafica_id = int(row.get("id") or 0)
        if anagrafica_id <= 0:
            continue
        nome = _clean_string(row.get("nome"))
        cognome = _clean_string(row.get("cognome"))
        alias = _clean_string(row.get("aliasusername"))
        display_name = " ".join([value for value in [cognome, nome] if value]).strip() or alias
        email = _clean_string(row.get("email"))
        notification_email = _clean_string(row.get("email_notifica"))
        label_email = notification_email or email
        label = f"{display_name} - {label_email}" if label_email else display_name or f"Dipendente #{anagrafica_id}"
        options.append((str(anagrafica_id), label))
        details[str(anagrafica_id)] = {
            "display_name": display_name or f"Dipendente #{anagrafica_id}",
            "email": email,
            "notification_email": notification_email,
            "reparto": _clean_string(row.get("reparto")),
            "legacy_user_id": str(row.get("utente_id") or "").strip(),
        }
    options.sort(key=lambda item: item[1].casefold())
    return options, details


def _build_work_machine_maintenance_month_dataset(
    *,
    month_value: str | None = None,
    reparto_filter: str = "",
    today: date | None = None,
) -> dict[str, object]:
    current_day = today or timezone.localdate()
    month_start = _month_start_from_value(month_value, today=current_day)
    month_end = _month_end(month_start)
    reparto_value = _clean_string(reparto_filter)

    queryset = (
        Asset.objects.filter(
            asset_type=Asset.TYPE_WORK_MACHINE,
            work_machine__next_maintenance_date__gte=month_start,
            work_machine__next_maintenance_date__lte=month_end,
        )
        .select_related("work_machine")
        .order_by("work_machine__next_maintenance_date", "reparto", "name", "asset_tag")
    )
    if reparto_value:
        queryset = queryset.filter(reparto=reparto_value)

    rows: list[dict[str, object]] = []
    status_counts = {"overdue": 0, "warning": 0, "ok": 0}
    for asset in queryset:
        machine = getattr(asset, "work_machine", None)
        if not isinstance(machine, WorkMachine):
            continue
        state = _work_machine_maintenance_state(machine, current_day)
        rows.append({"asset": asset, "machine": machine, "state": state})
        if state["status"] in status_counts:
            status_counts[state["status"]] += 1

    return {
        "month_start": month_start,
        "month_end": month_end,
        "month_code": month_start.strftime("%Y-%m"),
        "month_label": _month_label(month_start),
        "period_label": f'{month_start.strftime("%d/%m/%Y")} - {month_end.strftime("%d/%m/%Y")}',
        "reparto_filter": reparto_value,
        "rows": rows,
        "total_count": len(rows),
        "overdue_count": status_counts["overdue"],
        "warning_count": status_counts["warning"],
        "ok_count": status_counts["ok"],
    }


def _draw_work_machine_maintenance_month_report_header(
    pdf: canvas.Canvas,
    *,
    page_width: float,
    page_height: float,
    dataset: dict[str, object],
    generated_at: datetime,
    page_number: int,
) -> float:
    margin_x = 14 * mm
    top_y = page_height - (10 * mm)
    reparto_filter = _clean_string(str(dataset.get("reparto_filter") or ""))
    text_x = margin_x
    header_content_bottom = top_y - 30

    logo_path = _default_asset_label_logo_path()
    if logo_path.exists():
        try:
            logo_reader = ImageReader(str(logo_path))
            logo_width_px, logo_height_px = logo_reader.getSize()
            target_logo_height = 13 * mm
            target_logo_width = target_logo_height * (float(logo_width_px) / max(1.0, float(logo_height_px)))
            logo_y = top_y - target_logo_height
            pdf.drawImage(
                logo_reader,
                margin_x,
                logo_y,
                width=target_logo_width,
                height=target_logo_height,
                preserveAspectRatio=True,
                mask="auto",
            )
            text_x = margin_x + target_logo_width + (7 * mm)
            header_content_bottom = min(header_content_bottom, logo_y)
        except Exception:
            text_x = margin_x

    pdf.setFillColor(HexColor("#1d4ed8"))
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(text_x, top_y - 3, "Example Organization")
    pdf.setFillColor(HexColor("#0f172a"))
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(text_x, top_y - 18, "Report manutenzioni macchine")

    pdf.setFillColor(HexColor("#475569"))
    pdf.setFont("Helvetica", 9)
    pdf.drawString(
        text_x,
        top_y - 30,
        f'Periodo: {dataset["month_label"]} ({dataset["period_label"]})',
    )
    pdf.drawRightString(
        page_width - margin_x,
        top_y - 4,
        f'Generato il {generated_at.strftime("%d/%m/%Y %H:%M")} - Pagina {page_number}',
    )
    if reparto_filter:
        pdf.drawRightString(page_width - margin_x, top_y - 18, f"Filtro reparto: {reparto_filter}")

    line_y = min(header_content_bottom, top_y - 38) - (3 * mm)
    pdf.setStrokeColor(HexColor("#cbd5e1"))
    pdf.setLineWidth(1)
    pdf.line(margin_x, line_y, page_width - margin_x, line_y)

    cards_top = line_y - (5 * mm)
    cards_height = 16 * mm
    cards_gap = 4 * mm
    cards_width = (page_width - (2 * margin_x) - (3 * cards_gap)) / 4
    cards = [
        ("Totale mese", int(dataset.get("total_count") or 0), "#1d4ed8"),
        ("Scadute", int(dataset.get("overdue_count") or 0), "#dc2626"),
        ("In soglia", int(dataset.get("warning_count") or 0), "#d97706"),
        ("Pianificate", int(dataset.get("ok_count") or 0), "#15803d"),
    ]
    for idx, (label, value, accent) in enumerate(cards):
        left = margin_x + idx * (cards_width + cards_gap)
        pdf.setFillColor(HexColor("#ffffff"))
        pdf.setStrokeColor(HexColor("#dbe1ea"))
        pdf.roundRect(left, cards_top - cards_height, cards_width, cards_height, 6, fill=1, stroke=1)
        pdf.setFillColor(HexColor(accent))
        pdf.rect(left, cards_top - 4, cards_width, 4, fill=1, stroke=0)
        pdf.setFillColor(HexColor("#64748b"))
        pdf.setFont("Helvetica", 8)
        pdf.drawString(left + 10, cards_top - 15, label.upper())
        pdf.setFillColor(HexColor("#0f172a"))
        pdf.setFont("Helvetica-Bold", 19)
        pdf.drawString(left + 10, cards_top - 31, str(value))

    return cards_top - cards_height - (8 * mm)


def _draw_work_machine_maintenance_month_report_footer(
    pdf: canvas.Canvas,
    *,
    margin_x: float,
    bottom_limit: float,
    total_width: float,
) -> None:
    pdf.setStrokeColor(HexColor("#e2e8f0"))
    pdf.line(margin_x, bottom_limit, margin_x + total_width, bottom_limit)
    pdf.setFillColor(HexColor("#64748b"))
    pdf.setFont("Helvetica", 8)
    pdf.drawString(margin_x, bottom_limit - 10, "Example Organization - Portale Asset")
    pdf.drawRightString(margin_x + total_width, bottom_limit - 10, "Uso tecnico")


def _draw_work_machine_maintenance_month_table_header(
    pdf: canvas.Canvas,
    *,
    start_x: float,
    table_y: float,
    column_defs: list[tuple[str, float]],
) -> float:
    total_width = sum(width for _, width in column_defs)
    row_height = 10 * mm
    pdf.setFillColor(HexColor("#f8fafc"))
    pdf.setStrokeColor(HexColor("#e2e8f0"))
    pdf.rect(start_x, table_y - row_height, total_width, row_height, fill=1, stroke=1)
    pdf.setFillColor(HexColor("#475569"))
    pdf.setFont("Helvetica-Bold", 8)

    current_x = start_x
    for label, width in column_defs:
        pdf.drawString(current_x + 6, table_y - 18, label.upper())
        current_x += width
    return table_y - row_height


def _draw_work_machine_maintenance_month_pdf(
    pdf: canvas.Canvas,
    *,
    dataset: dict[str, object],
    generated_at: datetime,
) -> None:
    page_width, page_height = landscape(A4)
    margin_x = 14 * mm
    bottom_limit = 16 * mm
    row_height = 9 * mm
    column_defs = [
        ("Data", 24 * mm),
        ("Tag", 28 * mm),
        ("Macchina", 82 * mm),
        ("Reparto", 32 * mm),
        ("Stato", 62 * mm),
        ("Soglia", 20 * mm),
    ]
    total_width = sum(width for _, width in column_defs)
    status_colors = {
        "overdue": HexColor("#b91c1c"),
        "warning": HexColor("#a16207"),
        "ok": HexColor("#15803d"),
    }

    page_number = 1
    table_y = _draw_work_machine_maintenance_month_report_header(
        pdf,
        page_width=page_width,
        page_height=page_height,
        dataset=dataset,
        generated_at=generated_at,
        page_number=page_number,
    )
    table_y = _draw_work_machine_maintenance_month_table_header(
        pdf,
        start_x=margin_x,
        table_y=table_y,
        column_defs=column_defs,
    )
    current_y = table_y

    rows = list(dataset.get("rows") or [])
    if not rows:
        pdf.setFillColor(HexColor("#64748b"))
        pdf.setFont("Helvetica", 11)
        pdf.drawString(
            margin_x,
            current_y - 22,
            "Nessuna macchina con manutenzione pianificata nel periodo selezionato.",
        )
        _draw_work_machine_maintenance_month_report_footer(
            pdf,
            margin_x=margin_x,
            bottom_limit=bottom_limit,
            total_width=total_width,
        )
        return

    for index, row in enumerate(rows):
        if current_y - row_height < bottom_limit:
            _draw_work_machine_maintenance_month_report_footer(
                pdf,
                margin_x=margin_x,
                bottom_limit=bottom_limit,
                total_width=total_width,
            )
            pdf.showPage()
            page_number += 1
            table_y = _draw_work_machine_maintenance_month_report_header(
                pdf,
                page_width=page_width,
                page_height=page_height,
                dataset=dataset,
                generated_at=generated_at,
                page_number=page_number,
            )
            table_y = _draw_work_machine_maintenance_month_table_header(
                pdf,
                start_x=margin_x,
                table_y=table_y,
                column_defs=column_defs,
            )
            current_y = table_y

        asset = row["asset"]
        machine = row["machine"]
        state = row["state"]
        pdf.setFillColor(HexColor("#ffffff" if index % 2 == 0 else "#fbfdff"))
        pdf.setStrokeColor(HexColor("#eef2f7"))
        pdf.rect(margin_x, current_y - row_height, total_width, row_height, fill=1, stroke=1)

        values = [
            machine.next_maintenance_date.strftime("%d/%m/%Y") if machine.next_maintenance_date else "-",
            _coalesce_str(asset.asset_tag, "-"),
            _coalesce_str(asset.name, "-"),
            _coalesce_str(asset.reparto, "-"),
            _coalesce_str(str(state.get("label") or ""), "-"),
            f"{int(machine.maintenance_reminder_days or 0)} gg",
        ]
        font_name = "Helvetica"
        font_size = 8.5
        text_y = current_y - 17
        current_x = margin_x
        for value_idx, value in enumerate(values):
            width = column_defs[value_idx][1]
            pdf.setFillColor(HexColor("#0f172a"))
            if value_idx == 4:
                pdf.setFillColor(status_colors.get(str(state.get("status") or ""), HexColor("#0f172a")))
            pdf.setFont(font_name, font_size)
            pdf.drawString(
                current_x + 6,
                text_y,
                _truncate_pdf_text(
                    pdf,
                    value,
                    font_name=font_name,
                    font_size=font_size,
                    max_width=width - 12,
                ),
            )
            current_x += width

        current_y -= row_height

    _draw_work_machine_maintenance_month_report_footer(
        pdf,
        margin_x=margin_x,
        bottom_limit=bottom_limit,
        total_width=total_width,
    )


def _draw_asset_label_pdf(
    pdf: canvas.Canvas,
    *,
    asset: Asset,
    template: AssetLabelTemplate,
    target_url: str,
    target_label: str,
) -> None:
    catalog_map = _asset_label_field_catalog_map()
    body_field_keys = _normalize_asset_label_fields(template.body_fields, catalog_map)
    title_primary_key = template.title_primary_field if template.title_primary_field in catalog_map else "asset_tag"
    title_secondary_key = template.title_secondary_field if template.title_secondary_field in catalog_map else "name"

    width = float(template.page_width_mm or 100) * mm
    height = float(template.page_height_mm or 62) * mm
    margin = 6 * mm
    qr_size = float(template.qr_size_mm or 24) * mm
    qr_gap = 5 * mm
    qr_on_left = template.qr_position == AssetLabelTemplate.QR_POSITION_LEFT
    qr_x = margin if qr_on_left else max(margin, width - margin - qr_size)
    qr_y = max(margin, (height - qr_size) / 2)
    text_x = qr_x + qr_size + qr_gap if qr_on_left else margin
    text_width = width - (margin * 2) - qr_size - qr_gap

    background_color = HexColor(_normalize_label_hex(template.background_color, "#FFFFFF"))
    border_color = HexColor(_normalize_label_hex(template.border_color, "#111827"))
    text_color = HexColor(_normalize_label_hex(template.text_color, "#0F172A"))
    accent_color = HexColor(_normalize_label_hex(template.accent_color, "#1D4ED8"))

    pdf.setFillColor(background_color)
    pdf.setStrokeColor(border_color if template.show_border else background_color)
    pdf.roundRect(
        3 * mm,
        3 * mm,
        width - (6 * mm),
        height - (6 * mm),
        float(template.border_radius_mm or 0) * mm,
        stroke=1 if template.show_border else 0,
        fill=1,
    )
    _draw_pdf_qr(pdf, target_url, x=qr_x, y=qr_y, size=qr_size)

    cursor_y = height - margin - 2 * mm
    title_size = float(template.title_font_size_pt or 16)
    body_size = float(template.body_font_size_pt or 8)
    secondary_size = max(10.0, title_size - 4.0)
    line_gap = body_size + 3

    primary_text = _format_asset_label_value(asset, title_primary_key, catalog_map) or asset.asset_tag or "Asset"
    secondary_text = _format_asset_label_value(asset, title_secondary_key, catalog_map) if title_secondary_key else ""

    if template.show_logo:
        logo_path = _asset_label_logo_source_path(template)
        if logo_path:
            try:
                logo_reader = ImageReader(logo_path)
                logo_width_px, logo_height_px = logo_reader.getSize()
                target_logo_height = max(6 * mm, float(template.logo_height_mm or 10) * mm)
                target_logo_width = target_logo_height * (float(logo_width_px) / max(1.0, float(logo_height_px)))
                if target_logo_width > text_width:
                    scale_ratio = text_width / target_logo_width
                    target_logo_width = text_width
                    target_logo_height = target_logo_height * scale_ratio
                if template.logo_alignment == AssetLabelTemplate.LOGO_ALIGNMENT_CENTER:
                    logo_x = text_x + max(0, (text_width - target_logo_width) / 2)
                elif template.logo_alignment == AssetLabelTemplate.LOGO_ALIGNMENT_RIGHT:
                    logo_x = text_x + max(0, text_width - target_logo_width)
                else:
                    logo_x = text_x
                logo_y = cursor_y - target_logo_height
                pdf.drawImage(
                    logo_reader,
                    logo_x,
                    logo_y,
                    width=target_logo_width,
                    height=target_logo_height,
                    preserveAspectRatio=True,
                    mask="auto",
                )
                cursor_y = logo_y - 3 * mm
            except Exception:
                pass

    pdf.setFillColor(accent_color)
    pdf.setFont("Helvetica-Bold", title_size)
    pdf.drawString(
        text_x,
        cursor_y,
        _truncate_pdf_text(pdf, primary_text, font_name="Helvetica-Bold", font_size=title_size, max_width=text_width),
    )
    cursor_y -= title_size + 2

    if secondary_text:
        pdf.setFillColor(text_color)
        pdf.setFont("Helvetica-Bold", secondary_size)
        pdf.drawString(
            text_x,
            cursor_y,
            _truncate_pdf_text(pdf, secondary_text, font_name="Helvetica-Bold", font_size=secondary_size, max_width=text_width),
        )
        cursor_y -= secondary_size + 2

    pdf.setFillColor(text_color)
    pdf.setFont("Helvetica", body_size)
    reserved_lines = 0
    if template.show_target_label:
        reserved_lines += 1
    if template.show_help_text:
        reserved_lines += 1
    if template.show_target_url:
        reserved_lines += 1
    min_bottom = margin + (reserved_lines * line_gap)

    for field_key in body_field_keys:
        if cursor_y <= min_bottom:
            break
        meta = catalog_map.get(field_key)
        value = _format_asset_label_value(asset, field_key, catalog_map)
        if not meta or not value:
            continue
        row_text = f"{meta['label']}: {value}" if template.show_field_labels else value
        pdf.drawString(
            text_x,
            cursor_y,
            _truncate_pdf_text(pdf, row_text, font_name="Helvetica", font_size=body_size, max_width=text_width),
        )
        cursor_y -= line_gap

    if template.show_target_label and cursor_y > margin:
        row_text = f"Target QR: {target_label}"
        pdf.drawString(
            text_x,
            cursor_y,
            _truncate_pdf_text(pdf, row_text, font_name="Helvetica", font_size=body_size, max_width=text_width),
        )
        cursor_y -= line_gap
    if template.show_help_text and cursor_y > margin:
        help_text = "Scansiona per aprire la scheda o la cartella."
        pdf.drawString(
            text_x,
            cursor_y,
            _truncate_pdf_text(pdf, help_text, font_name="Helvetica", font_size=body_size, max_width=text_width),
        )
        cursor_y -= line_gap
    if template.show_target_url and cursor_y > (margin - 1):
        url_size = max(6.5, body_size - 1.0)
        pdf.setFont("Helvetica", url_size)
        pdf.drawString(
            text_x,
            max(margin, cursor_y),
            _truncate_pdf_text(pdf, target_url, font_name="Helvetica", font_size=url_size, max_width=text_width),
        )


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
        ("Reparto", _coalesce_str(asset.reparto, "-")),
        ("Produttore", _coalesce_str(asset.manufacturer, "-")),
        ("Modello", _coalesce_str(asset.model, "-")),
        ("Seriale", _coalesce_str(asset.serial_number, "-")),
        ("Assegnato a", _coalesce_str(asset.assignment_to, "Non assegnato")),
        ("Posizione", _coalesce_str(asset.assignment_location, "-")),
        ("SharePoint", _coalesce_str(_normalize_sharepoint_path(asset.sharepoint_folder_path), "-")),
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
            wo.opened_at.strftime("%d/%m/%Y") if wo.opened_at else "-",
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
            doc.created_at.strftime("%d/%m/%Y") if doc.created_at else "-",
            _format_filesize(getattr(doc.file, "size", 0)),
        )
        for doc in asset.documents.all().order_by("category", "-created_at", "-id")[:12]
    ]
    periodic_rows = [
        (
            _coalesce_str(verification.name, "-"),
            _coalesce_str(
                verification.next_verification_date.strftime("%d/%m/%Y") if verification.next_verification_date else "",
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


def _draw_asset_report_pdf(
    pdf: canvas.Canvas,
    *,
    asset: Asset,
    snapshot: dict[str, object],
    generated_at: datetime,
    template_name: str = "",
) -> None:
    page_width, page_height = A4
    margin_x = 14 * mm
    top_y = page_height - (12 * mm)
    bottom_y = 15 * mm
    current_y = top_y
    page_number = 1

    def draw_header() -> None:
        nonlocal current_y
        pdf.setFillColor(HexColor("#0f172a"))
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawString(margin_x, page_height - (12 * mm), "Report asset")
        pdf.setFillColor(HexColor("#475569"))
        pdf.setFont("Helvetica", 9)
        pdf.drawString(
            margin_x,
            page_height - (18 * mm),
            f"{_coalesce_str(asset.asset_tag, '-')} - {_coalesce_str(asset.name, '-')}",
        )
        pdf.drawRightString(
            page_width - margin_x,
            page_height - (12 * mm),
            f'Generato il {generated_at.strftime("%d/%m/%Y %H:%M")} - Pagina {page_number}',
        )
        if template_name:
            pdf.drawRightString(
                page_width - margin_x,
                page_height - (18 * mm),
                f"Template report attivo: {template_name}",
            )
        pdf.setStrokeColor(HexColor("#dbe3ef"))
        pdf.line(margin_x, page_height - (22 * mm), page_width - margin_x, page_height - (22 * mm))
        current_y = page_height - (28 * mm)

    def draw_footer() -> None:
        pdf.setStrokeColor(HexColor("#dbe3ef"))
        pdf.line(margin_x, bottom_y + (4 * mm), page_width - margin_x, bottom_y + (4 * mm))
        pdf.setFillColor(HexColor("#64748b"))
        pdf.setFont("Helvetica", 8)
        pdf.drawString(margin_x, bottom_y, "Example Organization - Portale Asset")

    def ensure_space(height_needed: float) -> None:
        nonlocal current_y, page_number
        if current_y - height_needed >= bottom_y + (8 * mm):
            return
        draw_footer()
        pdf.showPage()
        page_number += 1
        draw_header()

    def draw_key_value_section(title: str, rows: list[tuple[str, str]]) -> None:
        nonlocal current_y
        if not rows:
            return
        ensure_space(22)
        pdf.setFillColor(HexColor("#1d4ed8"))
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(margin_x, current_y, title)
        current_y -= 8
        row_height = 11
        total_width = page_width - (margin_x * 2)
        key_width = 54 * mm
        for key, value in rows:
            ensure_space(row_height + 4)
            pdf.setFillColor(HexColor("#ffffff"))
            pdf.setStrokeColor(HexColor("#e5edf5"))
            pdf.roundRect(margin_x, current_y - row_height + 2, total_width, row_height + 2, 4, fill=1, stroke=1)
            pdf.setFillColor(HexColor("#64748b"))
            pdf.setFont("Helvetica-Bold", 8)
            pdf.drawString(margin_x + 6, current_y - 5, _truncate_pdf_text(pdf, key, font_name="Helvetica-Bold", font_size=8, max_width=key_width - 12))
            pdf.setFillColor(HexColor("#0f172a"))
            pdf.setFont("Helvetica", 8.5)
            pdf.drawString(
                margin_x + key_width,
                current_y - 5,
                _truncate_pdf_text(
                    pdf,
                    _coalesce_str(value, "-"),
                    font_name="Helvetica",
                    font_size=8.5,
                    max_width=total_width - key_width - 10,
                ),
            )
            current_y -= row_height + 2
        current_y -= 6

    def draw_list_section(title: str, headers: list[str], rows: list[tuple[str, ...]]) -> None:
        nonlocal current_y
        if not rows:
            return
        ensure_space(28)
        pdf.setFillColor(HexColor("#1d4ed8"))
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(margin_x, current_y, title)
        current_y -= 8
        total_width = page_width - (margin_x * 2)
        col_width = total_width / max(1, len(headers))
        pdf.setFillColor(HexColor("#f8fbff"))
        pdf.setStrokeColor(HexColor("#dbe3ef"))
        pdf.rect(margin_x, current_y - 10, total_width, 12, fill=1, stroke=1)
        for idx, header in enumerate(headers):
            pdf.setFillColor(HexColor("#64748b"))
            pdf.setFont("Helvetica-Bold", 8)
            pdf.drawString(margin_x + (idx * col_width) + 4, current_y - 2, header.upper())
        current_y -= 14
        for row in rows:
            ensure_space(14)
            pdf.setFillColor(HexColor("#ffffff"))
            pdf.setStrokeColor(HexColor("#eef2f7"))
            pdf.rect(margin_x, current_y - 9, total_width, 11, fill=1, stroke=1)
            for idx, value in enumerate(row):
                pdf.setFillColor(HexColor("#0f172a"))
                pdf.setFont("Helvetica", 8)
                pdf.drawString(
                    margin_x + (idx * col_width) + 4,
                    current_y - 2,
                    _truncate_pdf_text(pdf, _coalesce_str(value, "-"), font_name="Helvetica", font_size=8, max_width=col_width - 8),
                )
            current_y -= 12
        current_y -= 6

    draw_header()
    draw_key_value_section("Riepilogo asset", list(snapshot.get("summary_rows") or []))
    draw_key_value_section("Dati tecnici", list(snapshot.get("technical_rows") or []))
    draw_key_value_section("Campi categoria", list(snapshot.get("category_rows") or []))
    draw_key_value_section("Campi personalizzati", list(snapshot.get("custom_rows") or []))
    draw_list_section("Documenti", ["Categoria", "File", "Data", "Peso"], list(snapshot.get("document_rows") or []))
    draw_list_section("Work order recenti", ["Data", "Tipo", "Titolo", "Stato"], list(snapshot.get("workorder_rows") or []))
    draw_list_section("Ticket collegati", ["Ticket", "Tipo", "Titolo", "Stato"], list(snapshot.get("ticket_rows") or []))
    draw_list_section("Manutenzione periodica", ["Piano", "Prossima data", "Fornitore"], list(snapshot.get("periodic_rows") or []))
    draw_footer()


def _sharepoint_runtime_value(*env_keys: str, setting_keys: tuple[str, ...] = ()) -> tuple[str, str]:
    value, source = resolve_env_value(*env_keys, dotenv_values=load_env_file_values())
    if value and not is_placeholder_value(value):
        if source == "process_env":
            return value, "ambiente processo"
        if source == "dotenv":
            return value, ".env"
    for key in setting_keys:
        value = str(getattr(settings, key, "") or "").strip()
        if value and not is_placeholder_value(value):
            return value, "settings"
    return "", "missing"


def _sharepoint_graph_settings() -> dict[str, str]:
    tenant_id = get_first_env_value("GRAPH_TENANT_ID", "AZURE_TENANT_ID")
    client_id = get_first_env_value("GRAPH_CLIENT_ID", "AZURE_CLIENT_ID")
    client_secret = get_first_env_value("GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET")
    site_id = get_first_env_value("GRAPH_SITE_ID")
    return {
        "tenant_id": tenant_id,
        "client_id": client_id,
        "client_secret": client_secret,
        "site_id": site_id,
    }


def _sharepoint_assets_defaults() -> dict[str, str]:
    dotenv_values = load_env_file_values()
    return {
        "library_url": _clean_string(dotenv_values.get("ASSETS_SHAREPOINT_LIBRARY_URL", ""))[:1000],
        "asset_root_path": _normalize_sharepoint_path(dotenv_values.get("ASSETS_SHAREPOINT_ASSET_ROOT_PATH", "")),
        "work_machine_root_path": _normalize_sharepoint_path(dotenv_values.get("ASSETS_SHAREPOINT_WORK_MACHINE_ROOT_PATH", "")),
    }


def _sharepoint_admin_config() -> dict[str, object]:
    dotenv_values = load_env_file_values()
    runtime_tenant_id, tenant_source = _sharepoint_runtime_value("GRAPH_TENANT_ID", "AZURE_TENANT_ID")
    runtime_client_id, client_source = _sharepoint_runtime_value("GRAPH_CLIENT_ID", "AZURE_CLIENT_ID")
    runtime_client_secret, secret_source = _sharepoint_runtime_value("GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET")
    runtime_site_id, site_source = _sharepoint_runtime_value("GRAPH_SITE_ID")
    defaults = _sharepoint_assets_defaults()
    return {
        "tenant_id": _clean_string(dotenv_values.get("GRAPH_TENANT_ID") or dotenv_values.get("AZURE_TENANT_ID", "")),
        "client_id": _clean_string(dotenv_values.get("GRAPH_CLIENT_ID") or dotenv_values.get("AZURE_CLIENT_ID", "")),
        "site_id": _clean_string(dotenv_values.get("GRAPH_SITE_ID", "")),
        "client_secret_configured": bool(
            _clean_string(dotenv_values.get("GRAPH_CLIENT_SECRET") or dotenv_values.get("AZURE_CLIENT_SECRET", ""))
        ),
        "runtime_ready": all([runtime_tenant_id, runtime_client_id, runtime_client_secret, runtime_site_id]),
        "runtime_sources": {
            "tenant_id": tenant_source,
            "client_id": client_source,
            "client_secret": secret_source,
            "site_id": site_source,
        },
        "env_override_active": any(
            source == "ambiente processo"
            for source in [tenant_source, client_source, secret_source, site_source]
        ),
        "library_url": defaults["library_url"],
        "asset_root_path": defaults["asset_root_path"],
        "work_machine_root_path": defaults["work_machine_root_path"],
    }


def _sanitize_sharepoint_segment(value: str | None) -> str:
    row = _clean_string(value).replace("\\", "-").replace("/", "-")
    return row.strip(" .")


def _default_asset_sharepoint_path(asset: Asset) -> str:
    defaults = _sharepoint_assets_defaults()
    root = defaults["work_machine_root_path"] if asset.asset_type == Asset.TYPE_WORK_MACHINE else defaults["asset_root_path"]
    root = _normalize_sharepoint_path(root)
    if not root:
        return ""
    parts = [root]
    reparto = _sanitize_sharepoint_segment(asset.reparto)
    if reparto:
        parts.append(reparto)
    if asset.asset_tag:
        parts.append(asset.asset_tag)
    return _normalize_sharepoint_path("/".join(parts))


def _ensure_asset_sharepoint_defaults(asset: Asset) -> None:
    if _clean_string(asset.sharepoint_folder_path):
        return
    default_path = _default_asset_sharepoint_path(asset)
    if not default_path:
        return
    Asset.objects.filter(pk=asset.pk).update(sharepoint_folder_path=default_path)
    asset.sharepoint_folder_path = default_path


def _sharepoint_graph_ready() -> bool:
    config = _sharepoint_graph_settings()
    return all(config.values())


def _sharepoint_graph_token() -> str:
    config = _sharepoint_graph_settings()
    if not all(config.values()):
        raise RuntimeError("Configurazione Graph assente o incompleta.")
    return acquire_graph_token(config["tenant_id"], config["client_id"], config["client_secret"])


def _sharepoint_drive_base_url() -> str:
    config = _sharepoint_graph_settings()
    if not config.get("site_id"):
        raise RuntimeError("GRAPH_SITE_ID non configurato.")
    return f"https://graph.microsoft.com/v1.0/sites/{config['site_id']}/drive"


def _normalize_sharepoint_path(value: str | None) -> str:
    text = _clean_string(value).replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.strip("/")


def _sharepoint_headers(*, binary: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {_sharepoint_graph_token()}"}
    headers["Content-Type"] = "application/octet-stream" if binary else "application/json"
    return headers


def _sharepoint_graph_healthcheck() -> tuple[bool, str]:
    if not _sharepoint_graph_ready():
        return False, "Configurazione SharePoint incompleta: verifica tenant, client, secret e site id."
    try:
        url = f"{_sharepoint_drive_base_url()}/root"
        response = requests.get(url, headers=_sharepoint_headers(), timeout=20)
        if response.status_code == 200:
            payload = response.json()
            drive_name = _coalesce_str(payload.get("name"), "Drive SharePoint")
            return True, f"Connessione SharePoint OK. Drive raggiunto: {drive_name}."
        return False, response.text or f"Errore SharePoint {response.status_code}"
    except Exception as exc:
        return False, f"Test SharePoint fallito: {exc}"


def _sharepoint_graph_get_item(path: str) -> dict | None:
    normalized = _normalize_sharepoint_path(path)
    if not normalized:
        return None
    url = f"{_sharepoint_drive_base_url()}/root:/{quote(normalized, safe='/')}"
    response = requests.get(url, headers=_sharepoint_headers(), timeout=20)
    if response.status_code == 200:
        return response.json()
    if response.status_code == 404:
        return None
    raise RuntimeError(response.text or f"Errore Graph {response.status_code}")


def _sharepoint_graph_create_folder(parent_path: str, folder_name: str) -> dict:
    normalized_parent = _normalize_sharepoint_path(parent_path)
    if normalized_parent:
        url = f"{_sharepoint_drive_base_url()}/root:/{quote(normalized_parent, safe='/')}:/children"
    else:
        url = f"{_sharepoint_drive_base_url()}/root/children"
    payload = {
        "name": folder_name,
        "folder": {},
        "@microsoft.graph.conflictBehavior": "rename",
    }
    response = requests.post(url, headers=_sharepoint_headers(), json=payload, timeout=20)
    if response.status_code in (200, 201):
        return response.json()
    raise RuntimeError(response.text or f"Errore creazione cartella SharePoint {response.status_code}")


def _ensure_sharepoint_folder(path: str) -> dict[str, str]:
    normalized = _normalize_sharepoint_path(path)
    if not normalized:
        return {"path": "", "url": ""}
    current_path = ""
    item = None
    for part in [chunk for chunk in normalized.split("/") if chunk]:
        current_path = f"{current_path}/{part}".strip("/")
        item = _sharepoint_graph_get_item(current_path)
        if item is None:
            item = _sharepoint_graph_create_folder("/".join(current_path.split("/")[:-1]), part)
    return {"path": normalized, "url": _coalesce_str((item or {}).get("webUrl"))}


def _ensure_asset_sharepoint_folder(asset: Asset) -> list[str]:
    _ensure_asset_sharepoint_defaults(asset)
    folder_path = _normalize_sharepoint_path(asset.sharepoint_folder_path)
    if not folder_path:
        return []
    if not _sharepoint_graph_ready():
        if not _clean_string(asset.sharepoint_folder_url):
            return ["Cartella SharePoint salvata ma sync file inattiva: configurazione Graph mancante."]
        return []
    try:
        info = _ensure_sharepoint_folder(folder_path)
    except Exception as exc:
        return [f"SharePoint non raggiungibile per {asset.asset_tag}: {exc}"]
    folder_url = _clean_string(info.get("url"))
    if folder_url and folder_url != _clean_string(asset.sharepoint_folder_url):
        Asset.objects.filter(pk=asset.pk).update(sharepoint_folder_url=folder_url)
        asset.sharepoint_folder_url = folder_url
    return []


def _upload_asset_document_to_sharepoint(asset: Asset, document: AssetDocument) -> str:
    folder_path = _normalize_sharepoint_path(asset.sharepoint_folder_path)
    if not folder_path:
        return ""
    if not _sharepoint_graph_ready():
        return "File salvato nel portale ma non sincronizzato su SharePoint: configurazione Graph mancante."

    category_folder = f"{folder_path}/{document.category.lower()}".strip("/")
    try:
        category_info = _ensure_sharepoint_folder(category_folder)
        filename = _clean_string(document.original_name) or Path(document.file.name).name
        remote_path = f"{category_info['path']}/{filename}".strip("/")
        url = f"{_sharepoint_drive_base_url()}/root:/{quote(remote_path, safe='/')}:/content"
        with document.file.open("rb") as handle:
            response = requests.put(url, headers=_sharepoint_headers(binary=True), data=handle, timeout=60)
        if response.status_code not in (200, 201):
            raise RuntimeError(response.text or f"Errore upload SharePoint {response.status_code}")
        payload = response.json() if response.text else {}
        document.sharepoint_url = _coalesce_str(payload.get("webUrl"))
        document.sharepoint_path = remote_path[:500]
        document.save(update_fields=["sharepoint_url", "sharepoint_path"])
        root_url = _clean_string(asset.sharepoint_folder_url) or _coalesce_str(category_info.get("url"))
        if root_url and root_url != _clean_string(asset.sharepoint_folder_url):
            Asset.objects.filter(pk=asset.pk).update(sharepoint_folder_url=root_url)
            asset.sharepoint_folder_url = root_url
        return ""
    except Exception as exc:
        return f"Upload SharePoint non riuscito per {document.original_name or document.file.name}: {exc}"


def _asset_qr_target_url(request: HttpRequest, asset: Asset, *, target: str = "detail") -> tuple[str, str]:
    desired = _clean_string(target).lower()
    if desired == "sharepoint" and _clean_string(asset.sharepoint_folder_url):
        return asset.sharepoint_folder_url, "Cartella SharePoint"
    detail_url = reverse("assets:asset_view", kwargs={"id": asset.id})
    return request.build_absolute_uri(detail_url), "Scheda asset"


def _draw_pdf_qr(pdf: canvas.Canvas, value: str, *, x: float, y: float, size: float) -> None:
    widget = qr.QrCodeWidget(value)
    bounds = widget.getBounds()
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    drawing = Drawing(size, size, transform=[size / width, 0, 0, size / height, 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, pdf, x, y)


def _shorten_text(value: str, limit: int = 56) -> str:
    text = _clean_string(value)
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}…"


def _build_asset_documents_by_category(asset: Asset) -> tuple[dict[str, str], dict[str, list[dict]]]:
    documents_by_category: dict[str, list[dict]] = defaultdict(list)
    extra = asset.extra_columns if isinstance(asset.extra_columns, dict) else {}
    raw_docs = extra.get("documents")
    if isinstance(raw_docs, list):
        for row in raw_docs:
            if not isinstance(row, dict):
                continue
            name = _coalesce_str(row.get("name"), row.get("filename"))
            if not name:
                continue
            category = _coalesce_str(row.get("category"), AssetDocument.CATEGORY_SPECIFICHE).upper()
            if category not in ASSET_DOCUMENT_CATEGORY_LABELS:
                category = AssetDocument.CATEGORY_SPECIFICHE
            documents_by_category[category].append(
                {
                    "name": name,
                    "size": _coalesce_str(row.get("size"), ""),
                    "date": _coalesce_str(row.get("date"), ""),
                    "url": _coalesce_str(row.get("url"), ""),
                    "kind": "external",
                    "meta": "",
                }
            )

    for uploaded in asset.documents.all():
        size_text = ""
        try:
            size_text = _format_filesize(uploaded.file.size)
        except Exception:
            size_text = ""
        meta_parts = []
        if _clean_string(uploaded.notes):
            meta_parts.append(_clean_string(uploaded.notes))
        if _clean_string(uploaded.sharepoint_path):
            meta_parts.append(f"SP: {uploaded.sharepoint_path}")
        documents_by_category[uploaded.category].append(
            {
                "name": uploaded.original_name or Path(uploaded.file.name).name,
                "size": size_text,
                "date": uploaded.document_date.strftime("%d/%m/%Y") if uploaded.document_date else uploaded.created_at.strftime("%d/%m/%Y"),
                "url": uploaded.sharepoint_url or (uploaded.file.url if uploaded.file else ""),
                "kind": "uploaded",
                "meta": " | ".join(meta_parts),
            }
        )

    for category in ASSET_DOCUMENT_CATEGORY_LABELS:
        documents_by_category.setdefault(category, [])
    return ASSET_DOCUMENT_CATEGORY_LABELS, dict(documents_by_category)


def _build_uploaded_documents_context(asset: Asset | None) -> dict[str, list[AssetDocument]]:
    grouped: dict[str, list[AssetDocument]] = {key: [] for key in ASSET_DOCUMENT_CATEGORY_LABELS}
    if not asset or not asset.pk:
        return grouped
    for document in asset.documents.all():
        grouped.setdefault(document.category, []).append(document)
    return grouped


def _validate_asset_document_uploads(request: HttpRequest) -> tuple[dict[str, list], list[str]]:
    uploads: dict[str, list] = {}
    errors: list[str] = []
    for category, field_name in ASSET_DOCUMENT_UPLOAD_FIELDS.items():
        valid_files = []
        for upload in request.FILES.getlist(field_name):
            filename = getattr(upload, "name", "") or ""
            if not filename:
                continue
            try:
                validate_extension_and_mime(
                    upload,
                    allowed_extensions=ASSET_DOCUMENT_ALLOWED_EXTENSIONS,
                    allowed_mimes=ASSET_DOCUMENT_ALLOWED_MIMES,
                    max_bytes=ASSET_DOCUMENT_MAX_BYTES,
                    label=filename,
                )
            except UploadMimeValidationError as exc:
                errors.append(str(exc))
                continue
            valid_files.append(upload)
        uploads[category] = valid_files
    return uploads, errors


def _apply_asset_document_changes(
    asset: Asset,
    *,
    uploads: dict[str, list],
    remove_ids: set[int],
    actor,
) -> list[str]:
    warnings: list[str] = []
    if remove_ids:
        for document in asset.documents.filter(id__in=remove_ids):
            document.delete()

    for category, files in uploads.items():
        for upload in files:
            document = AssetDocument.objects.create(
                asset=asset,
                category=category,
                file=upload,
                original_name=getattr(upload, "name", "")[:255],
                uploaded_by=actor if getattr(actor, "is_authenticated", False) else None,
            )
            warning = _upload_asset_document_to_sharepoint(asset, document)
            if warning:
                warnings.append(warning)
    return warnings


def _work_machine_maintenance_state(machine: WorkMachine, today) -> dict[str, object]:
    next_date = getattr(machine, "next_maintenance_date", None)
    reminder_days = int(getattr(machine, "maintenance_reminder_days", 30) or 0)
    if not next_date:
        return {"status": "missing", "label": "Da pianificare", "days": None, "date": None}
    delta_days = (next_date - today).days
    if delta_days < 0:
        return {"status": "overdue", "label": f"Scaduta da {abs(delta_days)} gg", "days": delta_days, "date": next_date}
    if delta_days <= reminder_days:
        return {"status": "warning", "label": f"In soglia ({delta_days} gg)", "days": delta_days, "date": next_date}
    return {"status": "ok", "label": f"Pianificata tra {delta_days} gg", "days": delta_days, "date": next_date}


def _periodic_verification_state(verification: PeriodicVerification, today=None) -> dict[str, object]:
    current_day = today or timezone.localdate()
    if not verification.is_active:
        return {"status": "inactive", "label": "Disattivata", "date": verification.next_verification_date}
    next_date = verification.next_verification_date
    if not next_date:
        return {"status": "missing", "label": "Da pianificare", "date": None}
    delta_days = (next_date - current_day).days
    if delta_days < 0:
        return {"status": "overdue", "label": f"Scaduta da {abs(delta_days)} gg", "date": next_date}
    if delta_days <= 30:
        return {"status": "warning", "label": f"In scadenza ({delta_days} gg)", "date": next_date}
    return {"status": "ok", "label": f"Pianificata tra {delta_days} gg", "date": next_date}


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
    assignment_reparto = next(
        (row.get("value") for row in assignment_rows if row.get("label") == "Reparto" and row.get("value")),
        "",
    )
    assignment_location = next(
        (row.get("value") for row in assignment_rows if row.get("label") == "Posizione" and row.get("value")),
        "",
    )
    assignment_meta = " / ".join(value for value in [assignment_reparto, assignment_location] if value and value != "-")
    contract_value = str(primary_contract.supplier) if primary_contract is not None else "Copertura non disponibile"
    contract_meta = "Copertura non disponibile"
    if primary_contract is not None:
        contract_meta = primary_contract.coverage_summary or primary_contract.target_label
    maintenance_meta = "Nessuna regola a giorni disponibile."
    maintenance_badge_class = "muted"
    maintenance_badge_label = "Non pianificato"
    maintenance_value = "Nessuna regola attiva"
    if next_maintenance_row is not None:
        maintenance_template_label = str(next_maintenance_row["effective_intervention_template"].label)
        maintenance_value = "Prima esecuzione da pianificare"
        maintenance_meta = f"{maintenance_template_label} | Nessuna esecuzione registrata"
        if next_maintenance_row.get("due_date"):
            maintenance_meta = (
                f"{maintenance_meta} · scadenza {next_maintenance_row['due_date']:%d/%m/%Y}"
            )
        maintenance_badge_class = str(next_maintenance_row.get("schedule_badge_class") or "muted")
        maintenance_badge_label = str(next_maintenance_row.get("schedule_label") or "Da pianificare")
        if next_maintenance_row.get("due_date"):
            maintenance_value = f"{next_maintenance_row['due_date']:%d/%m/%Y}"
            maintenance_meta = f"{maintenance_template_label} | {next_maintenance_row['schedule_label']}"
    deadline_badge_class = "muted"
    deadline_badge_label = "Nessuna"
    deadline_value = "Nessuna scadenza"
    deadline_meta = "Nessuna scadenza amministrativa registrata."
    if next_deadline_row is not None:
        deadline = next_deadline_row["deadline"]
        deadline_state = next_deadline_row["state"]
        deadline_value = str(deadline.title)
        deadline_meta = str(deadline_state.get("days_label") or "")
        deadline_badge_class = str(deadline_state.get("badge_class") or "muted")
        deadline_badge_label = str(deadline_state.get("label") or "Programmato")

    default_cards = [
        {
            "label": "Stato asset",
            "value": asset_status["label"],
            "meta": assignment_meta or "Asset operativo nel portale.",
            "badge_label": asset_status["label"],
            "badge_class": asset_status["badge_class"],
            "link_label": "",
            "link_url": "",
            "size_class": "af-span-third",
        },
        {
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
            "size_class": "af-span-third",
        },
        {
            "label": "Prossima manutenzione",
            "value": maintenance_value,
            "meta": maintenance_meta,
            "badge_label": maintenance_badge_label,
            "badge_class": maintenance_badge_class,
            "link_label": "Apri scadenzario",
            "link_url": asset_maintenance_schedule_url,
            "size_class": "af-span-third",
        },
        {
            "label": "Scadenze amministrative",
            "value": deadline_value,
            "meta": deadline_meta,
            "badge_label": deadline_badge_label,
            "badge_class": deadline_badge_class,
            "link_label": "Apri scadenze",
            "link_url": asset_administrative_deadline_list_url,
            "size_class": "af-span-third",
        },
    ]

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


def _is_assets_admin(request: HttpRequest) -> bool:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    return bool(request.user.is_superuser or (legacy_user and is_legacy_admin(legacy_user)))


def _can_manage_asset_detail_layout(request: HttpRequest) -> bool:
    if _is_assets_admin(request):
        return True
    return bool(
        user_can_modulo_action(request, "assets", "admin_assets")
        or user_can_modulo_action(request, "assets", "asset_detail_layout")
    )


def _can_manage_asset_list_layout(request: HttpRequest) -> bool:
    if _is_assets_admin(request):
        return True
    return bool(
        user_can_modulo_action(request, "assets", "admin_assets")
        or user_can_modulo_action(request, "assets", "asset_list_layout")
    )


def _legacy_employee_options() -> tuple[list[tuple[str, str]], dict[str, dict[str, str]]]:
    try:
        users = list(
            UtenteLegacy.objects.filter(attivo=True)
            .exclude(id__isnull=True)
            .order_by("nome", "email", "id")
        )
    except DatabaseError:
        return [], {}

    user_ids = [int(u.id) for u in users if getattr(u, "id", None)]
    anagrafica_map: dict[int, AnagraficaDipendente] = {}
    extra_map: dict[int, UserExtraInfo] = {}

    if user_ids:
        try:
            for row in AnagraficaDipendente.objects.filter(utente_id__in=user_ids):
                if row.utente_id is not None:
                    anagrafica_map[int(row.utente_id)] = row
        except DatabaseError:
            anagrafica_map = {}
        try:
            for row in UserExtraInfo.objects.filter(legacy_user_id__in=user_ids):
                extra_map[int(row.legacy_user_id)] = row
        except Exception:
            extra_map = {}

    options: list[tuple[str, str]] = []
    details: dict[str, dict[str, str]] = {}
    for user in users:
        uid = int(user.id)
        anagrafica = anagrafica_map.get(uid)
        extra = extra_map.get(uid)
        nome = _clean_string(user.nome)
        email = _clean_string(user.email)
        notification_email = _clean_string(getattr(anagrafica, "email_notifica", ""))
        calendar_user_id = email or notification_email
        if not nome and anagrafica:
            nome = " ".join(
                [
                    _clean_string(getattr(anagrafica, "nome", "")),
                    _clean_string(getattr(anagrafica, "cognome", "")),
                ]
            ).strip()
        display_name = nome or email or f"Utente #{uid}"
        reparto = _clean_string(getattr(extra, "reparto", "")) or _clean_string(getattr(anagrafica, "reparto", ""))
        label_email = calendar_user_id
        label = f"{display_name} - {label_email}" if label_email else display_name
        options.append((str(uid), label))
        details[str(uid)] = {
            "display_name": display_name,
            "email": email,
            "notification_email": notification_email,
            "calendar_user_id": calendar_user_id,
            "reparto": reparto,
        }
    return options, details


def _outlook_calendar_graph_settings() -> dict[str, str]:
    return {
        "tenant_id": _clean_string(get_first_env_value("GRAPH_TENANT_ID", "AZURE_TENANT_ID")),
        "client_id": _clean_string(get_first_env_value("GRAPH_CLIENT_ID", "AZURE_CLIENT_ID")),
        "client_secret": _clean_string(get_first_env_value("GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET")),
    }


def _outlook_calendar_graph_ready() -> bool:
    config = _outlook_calendar_graph_settings()
    return all(config.values()) and not any(is_placeholder_value(value) for value in config.values())


def _outlook_calendar_graph_token() -> str:
    config = _outlook_calendar_graph_settings()
    if not _outlook_calendar_graph_ready():
        raise RuntimeError("Configurazione Graph incompleta: tenant, client o secret mancanti.")
    return acquire_graph_token(config["tenant_id"], config["client_id"], config["client_secret"])


def _outlook_calendar_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_outlook_calendar_graph_token()}",
        "Content-Type": "application/json",
    }


def _asset_calendar_target_email(target_details: dict[str, str]) -> str:
    return _clean_string(target_details.get("calendar_user_id") or target_details.get("email"))


def _asset_calendar_default_user_id(
    asset: Asset | None,
    calendar_user_details: dict[str, dict[str, str]],
) -> str:
    suggested_user_id = str(getattr(asset, "assigned_legacy_user_id", "") or "")
    if suggested_user_id and suggested_user_id not in calendar_user_details:
        return ""
    return suggested_user_id


def _asset_calendar_source_key(
    *,
    event_kind: str,
    asset_id: int,
    source_id: int,
    due_date: date,
    target_legacy_user_id: int,
) -> str:
    return (
        f"{_clean_string(event_kind)}:{int(asset_id or 0)}:{int(source_id or 0)}:"
        f"{due_date.isoformat()}:{int(target_legacy_user_id or 0)}"
    )


def _asset_calendar_transaction_id(*, source_key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"https://novicrom.local/assets/calendar/{source_key}"))


def _outlook_event_time_window(due_date: date) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(due_date, datetime.min.time()).replace(hour=OUTLOOK_CALENDAR_START_HOUR)
    end_dt = start_dt + timedelta(minutes=OUTLOOK_CALENDAR_DURATION_MINUTES)
    return start_dt, end_dt


def _build_outlook_event_payload(
    *,
    subject: str,
    body_html: str,
    location_label: str,
    due_date: date,
    transaction_id: str,
) -> dict[str, object]:
    start_dt, end_dt = _outlook_event_time_window(due_date)
    return {
        "subject": _clean_string(subject)[:255],
        "body": {
            "contentType": "HTML",
            "content": body_html,
        },
        "start": {
            "dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": OUTLOOK_CALENDAR_TIMEZONE,
        },
        "end": {
            "dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": OUTLOOK_CALENDAR_TIMEZONE,
        },
        "location": {
            "displayName": _clean_string(location_label) or "Promemoria assets",
        },
        "showAs": "busy",
        "responseRequested": False,
        "transactionId": transaction_id,
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


def _deadline_list_redirect_from_request(request: HttpRequest) -> str:
    return _asset_administrative_deadline_page_url(
        asset_id=_as_int(request.POST.get("filter_asset"), default=0),
        component_id=_as_int(request.POST.get("filter_component"), default=0),
        deadline_type=_clean_string(request.POST.get("filter_deadline_type")),
        status=_clean_string(request.POST.get("filter_status")),
        q=_clean_string(request.POST.get("filter_q")),
    )


def _periodic_verification_redirect_from_request(request: HttpRequest) -> str:
    return _periodic_verifications_page_url(
        asset_id=_as_int(request.POST.get("filter_asset"), default=0),
        edit_id=_as_int(request.POST.get("filter_edit"), default=0),
    )


def _assistance_contract_redirect_from_request(request: HttpRequest) -> str:
    return _assistance_contracts_page_url(
        asset_id=_as_int(request.POST.get("filter_asset"), default=0),
        supplier_filter=_as_int(request.POST.get("filter_supplier"), default=0),
        state=_clean_string(request.POST.get("filter_state")),
        scope=_clean_string(request.POST.get("filter_scope")),
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


def _maintenance_schedule_row_for_asset_rule(*, asset: Asset, base_rule_id: int) -> dict[str, object] | None:
    rows = build_day_based_maintenance_schedule_rows(
        asset_queryset=Asset.objects.filter(pk=asset.id).select_related("asset_category"),
    )
    for row in rows:
        if getattr(row.get("base_rule"), "id", 0) == int(base_rule_id or 0):
            return row
    return None


def _build_maintenance_outlook_event_payload(
    *,
    request: HttpRequest,
    asset: Asset,
    schedule_row: dict[str, object],
    target_display_name: str,
    transaction_id: str,
) -> dict[str, object]:
    due_date = schedule_row.get("due_date")
    if not isinstance(due_date, date):
        raise RuntimeError("La regola selezionata non ha una scadenza calendarizzabile.")

    template = schedule_row["effective_intervention_template"]
    template_label = _clean_string(getattr(template, "label", "Intervento manutentivo")) or "Intervento manutentivo"
    threshold_label = _clean_string(schedule_row.get("effective_threshold_label"))
    threshold_value = schedule_row.get("effective_threshold_value")
    warning_days = int(schedule_row.get("effective_warning_days") or 0)
    contract = get_primary_assistance_contract(asset)
    asset_url = request.build_absolute_uri(reverse("assets:asset_view", kwargs={"id": asset.id}))
    workorder_url = request.build_absolute_uri(
        _workorder_create_page_url(asset_id=asset.id, rule_id=schedule_row["base_rule"].id, source="maintenance_schedule")
    )
    due_date_label = due_date.strftime("%d/%m/%Y")
    subject = f"Manutenzione {asset.asset_tag} - {template_label}"[:255]

    start_dt = datetime.combine(due_date, datetime.min.time()).replace(hour=OUTLOOK_CALENDAR_START_HOUR)
    end_dt = start_dt + timedelta(minutes=OUTLOOK_CALENDAR_DURATION_MINUTES)
    contract_label = (
        escape(_clean_string(getattr(contract, "title", "")) or str(getattr(contract, "supplier", "")))
        if contract is not None
        else "Nessuna copertura contrattuale attiva"
    )
    body_html = (
        "<p>Promemoria manutenzione generato dal modulo Assets.</p>"
        f"<p><strong>Destinatario:</strong> {escape(target_display_name or 'Utente selezionato')}<br>"
        f"<strong>Asset:</strong> {escape(asset.asset_tag)} - {escape(asset.name)}<br>"
        f"<strong>Reparto:</strong> {escape(_clean_string(asset.reparto) or '-')}<br>"
        f"<strong>Intervento:</strong> {escape(template_label)}<br>"
        f"<strong>Scadenza:</strong> {escape(due_date_label)}<br>"
        f"<strong>Periodicita:</strong> {escape(str(threshold_value or 0))} {escape(threshold_label.lower() or 'giorni')}<br>"
        f"<strong>Warning:</strong> {warning_days} gg<br>"
        f"<strong>Contratto:</strong> {contract_label}</p>"
        f"<p><a href=\"{escape(asset_url)}\">Apri scheda asset</a><br>"
        f"<a href=\"{escape(workorder_url)}\">Apri creazione intervento</a></p>"
    )
    return _build_outlook_event_payload(
        subject=subject,
        body_html=body_html,
        location_label=_clean_string(asset.reparto) or "Manutenzione asset",
        due_date=due_date,
        transaction_id=transaction_id,
    )


def _build_deadline_outlook_event_payload(
    *,
    request: HttpRequest,
    deadline: AssetAdministrativeDeadline,
    target_display_name: str,
    transaction_id: str,
) -> dict[str, object]:
    asset = deadline.asset
    component_label = (
        f"{deadline.component.name} ({deadline.component.code})"
        if deadline.component_id and deadline.component and deadline.component.code
        else getattr(deadline.component, "name", "")
    )
    asset_url = request.build_absolute_uri(reverse("assets:asset_view", kwargs={"id": asset.id}))
    edit_url = request.build_absolute_uri(reverse("assets:asset_administrative_deadline_edit", kwargs={"id": deadline.id}))
    body_html = (
        "<p>Promemoria scadenza amministrativa/tecnica generato dal modulo Assets.</p>"
        f"<p><strong>Destinatario:</strong> {escape(target_display_name or 'Utente selezionato')}<br>"
        f"<strong>Asset:</strong> {escape(asset.asset_tag)} - {escape(asset.name)}<br>"
        f"<strong>Scadenza:</strong> {escape(deadline.title)}<br>"
        f"<strong>Tipo:</strong> {escape(deadline.get_deadline_type_display())}<br>"
        f"<strong>Data:</strong> {deadline.due_date:%d/%m/%Y}<br>"
        f"<strong>Preavviso:</strong> {int(deadline.warning_days or 0)} gg<br>"
        f"<strong>Riferimento:</strong> {escape(_clean_string(deadline.reference_code) or '-')}<br>"
        f"<strong>Ente/Rilasciato da:</strong> {escape(_clean_string(deadline.issuer) or '-')}<br>"
        f"<strong>Componente:</strong> {escape(_clean_string(component_label) or '-')}</p>"
        f"<p><a href=\"{escape(asset_url)}\">Apri scheda asset</a><br>"
        f"<a href=\"{escape(edit_url)}\">Apri scadenza amministrativa</a></p>"
    )
    subject = f"Scadenza {asset.asset_tag} - {deadline.title}"[:255]
    return _build_outlook_event_payload(
        subject=subject,
        body_html=body_html,
        location_label=_clean_string(asset.reparto) or "Scadenza asset",
        due_date=deadline.due_date,
        transaction_id=transaction_id,
    )


def _build_periodic_verification_outlook_event_payload(
    *,
    request: HttpRequest,
    asset: Asset,
    verification: PeriodicVerification,
    target_display_name: str,
    transaction_id: str,
) -> dict[str, object]:
    next_date = verification.next_verification_date
    if not isinstance(next_date, date):
        raise RuntimeError("La manutenzione periodica non ha una prossima data calendarizzabile.")
    asset_url = request.build_absolute_uri(reverse("assets:asset_view", kwargs={"id": asset.id}))
    verification_url = request.build_absolute_uri(_periodic_verifications_page_url(asset_id=asset.id, edit_id=verification.id))
    supplier_label = _clean_string(str(getattr(verification, "supplier", "") or "")) or "Fornitore non impostato"
    body_html = (
        "<p>Promemoria manutenzione periodica generato dal modulo Assets.</p>"
        f"<p><strong>Destinatario:</strong> {escape(target_display_name or 'Utente selezionato')}<br>"
        f"<strong>Asset:</strong> {escape(asset.asset_tag)} - {escape(asset.name)}<br>"
        f"<strong>Manutenzione periodica:</strong> {escape(verification.name)}<br>"
        f"<strong>Prossima data:</strong> {next_date:%d/%m/%Y}<br>"
        f"<strong>Cadenza:</strong> {int(verification.frequency_months or 0)} mesi<br>"
        f"<strong>Fornitore:</strong> {escape(supplier_label)}</p>"
        f"<p><a href=\"{escape(asset_url)}\">Apri scheda asset</a><br>"
        f"<a href=\"{escape(verification_url)}\">Apri manutenzione periodica</a></p>"
    )
    subject = f"Manutenzione periodica {asset.asset_tag} - {verification.name}"[:255]
    return _build_outlook_event_payload(
        subject=subject,
        body_html=body_html,
        location_label=_clean_string(asset.reparto) or "Manutenzione periodica asset",
        due_date=next_date,
        transaction_id=transaction_id,
    )


def _build_assistance_contract_outlook_event_payload(
    *,
    request: HttpRequest,
    asset: Asset,
    contract: AssistanceContract,
    target_display_name: str,
    transaction_id: str,
) -> dict[str, object]:
    if not isinstance(contract.end_date, date):
        raise RuntimeError("Il contratto selezionato non ha una data scadenza calendarizzabile.")
    supplier_label = _clean_string(str(getattr(contract, "supplier", "") or "")) or "Fornitore non impostato"
    asset_url = request.build_absolute_uri(reverse("assets:asset_view", kwargs={"id": asset.id}))
    contracts_url = request.build_absolute_uri(_assistance_contracts_page_url(asset_id=asset.id, edit_id=contract.id))
    scope_payload = _contract_scope_payload(contract)
    body_html = (
        "<p>Promemoria scadenza contratto assistenza generato dal modulo Assets.</p>"
        f"<p><strong>Destinatario:</strong> {escape(target_display_name or 'Utente selezionato')}<br>"
        f"<strong>Asset di contesto:</strong> {escape(asset.asset_tag)} - {escape(asset.name)}<br>"
        f"<strong>Contratto:</strong> {escape(contract.title)}<br>"
        f"<strong>Fornitore:</strong> {escape(supplier_label)}<br>"
        f"<strong>Codice:</strong> {escape(_clean_string(contract.code) or '-')}<br>"
        f"<strong>Scadenza:</strong> {contract.end_date:%d/%m/%Y}<br>"
        f"<strong>Ambito:</strong> {escape(scope_payload.get('label') or '-')}<br>"
        f"<strong>Dettaglio:</strong> {escape(scope_payload.get('detail') or '-')}</p>"
        f"<p><a href=\"{escape(asset_url)}\">Apri scheda asset</a><br>"
        f"<a href=\"{escape(contracts_url)}\">Apri contratti assistenza</a></p>"
    )
    subject = f"Scadenza contratto {asset.asset_tag} - {contract.title}"[:255]
    return _build_outlook_event_payload(
        subject=subject,
        body_html=body_html,
        location_label=_clean_string(asset.reparto) or "Contratto assistenza",
        due_date=contract.end_date,
        transaction_id=transaction_id,
    )


def _outlook_calendar_create_event(*, target_email: str, payload: dict[str, object]) -> dict[str, object]:
    if not _outlook_calendar_graph_ready():
        raise RuntimeError("Integrazione Outlook non configurata: mancano le credenziali Graph valide.")
    target_value = _clean_string(target_email)
    if not target_value:
        raise RuntimeError("Utente Outlook non valido.")
    url = f"https://graph.microsoft.com/v1.0/users/{quote(target_value, safe='')}/calendar/events"
    response = requests.post(url, headers=_outlook_calendar_headers(), json=payload, timeout=20)
    if response.status_code in {200, 201}:
        return response.json()
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    graph_error = payload.get("error") if isinstance(payload, dict) else None
    message = ""
    if isinstance(graph_error, dict):
        message = _clean_string(graph_error.get("message"))
    raise RuntimeError(message or response.text or f"Errore Outlook Calendar {response.status_code}")


def _create_asset_calendar_event_record(
    *,
    asset: Asset,
    event_kind: str,
    source_key: str,
    due_date: date,
    target_legacy_user_id: int,
    target_details: dict[str, str],
    payload: dict[str, object],
    request_user,
    maintenance_rule: MaintenanceRule | None = None,
    administrative_deadline: AssetAdministrativeDeadline | None = None,
    periodic_verification: PeriodicVerification | None = None,
    assistance_contract: AssistanceContract | None = None,
) -> tuple[AssetCalendarEvent, bool]:
    target_email = _asset_calendar_target_email(target_details)
    if not target_email:
        raise RuntimeError("L'utente selezionato non ha un identificatore Outlook configurato.")
    existing = AssetCalendarEvent.objects.filter(source_key=source_key).order_by("id").first()
    if existing is not None:
        return existing, False

    target_display_name = _clean_string(target_details.get("display_name")) or target_email
    graph_event = _outlook_calendar_create_event(target_email=target_email, payload=payload)
    try:
        entry = AssetCalendarEvent.objects.create(
            asset=asset,
            event_kind=event_kind,
            source_key=source_key,
            maintenance_rule=maintenance_rule,
            administrative_deadline=administrative_deadline,
            periodic_verification=periodic_verification,
            assistance_contract=assistance_contract,
            due_date=due_date,
            target_legacy_user_id=int(target_legacy_user_id),
            target_display_name=target_display_name,
            target_email=target_email,
            subject=_clean_string(payload.get("subject")),
            transaction_id=_clean_string(payload.get("transactionId")),
            graph_event_id=_clean_string(graph_event.get("id")),
            graph_event_web_link=_clean_string(graph_event.get("webLink")),
            created_by=request_user if getattr(request_user, "is_authenticated", False) else None,
        )
    except IntegrityError:
        entry = AssetCalendarEvent.objects.get(source_key=source_key)
        return entry, False
    return entry, True


def _create_asset_maintenance_calendar_event(
    *,
    request: HttpRequest,
    asset: Asset,
    schedule_row: dict[str, object],
    target_legacy_user_id: int,
    target_details: dict[str, str],
) -> tuple[AssetCalendarEvent, bool]:
    due_date = schedule_row.get("due_date")
    if not isinstance(due_date, date):
        raise RuntimeError("La manutenzione selezionata non ha una scadenza impostata.")
    source_key = _asset_calendar_source_key(
        event_kind=AssetCalendarEvent.KIND_MAINTENANCE,
        asset_id=asset.id,
        source_id=schedule_row["base_rule"].id,
        due_date=due_date,
        target_legacy_user_id=target_legacy_user_id,
    )
    payload = _build_maintenance_outlook_event_payload(
        request=request,
        asset=asset,
        schedule_row=schedule_row,
        target_display_name=_clean_string(target_details.get("display_name")),
        transaction_id=_asset_calendar_transaction_id(source_key=source_key),
    )
    return _create_asset_calendar_event_record(
        asset=asset,
        event_kind=AssetCalendarEvent.KIND_MAINTENANCE,
        source_key=source_key,
        due_date=due_date,
        target_legacy_user_id=target_legacy_user_id,
        target_details=target_details,
        payload=payload,
        request_user=request.user,
        maintenance_rule=schedule_row["base_rule"],
    )


def _create_asset_deadline_calendar_event(
    *,
    request: HttpRequest,
    deadline: AssetAdministrativeDeadline,
    target_legacy_user_id: int,
    target_details: dict[str, str],
) -> tuple[AssetCalendarEvent, bool]:
    due_date = deadline.due_date
    source_key = _asset_calendar_source_key(
        event_kind=AssetCalendarEvent.KIND_ADMINISTRATIVE_DEADLINE,
        asset_id=deadline.asset_id,
        source_id=deadline.id,
        due_date=due_date,
        target_legacy_user_id=target_legacy_user_id,
    )
    payload = _build_deadline_outlook_event_payload(
        request=request,
        deadline=deadline,
        target_display_name=_clean_string(target_details.get("display_name")),
        transaction_id=_asset_calendar_transaction_id(source_key=source_key),
    )
    return _create_asset_calendar_event_record(
        asset=deadline.asset,
        event_kind=AssetCalendarEvent.KIND_ADMINISTRATIVE_DEADLINE,
        source_key=source_key,
        due_date=due_date,
        target_legacy_user_id=target_legacy_user_id,
        target_details=target_details,
        payload=payload,
        request_user=request.user,
        administrative_deadline=deadline,
    )


def _create_asset_periodic_verification_calendar_event(
    *,
    request: HttpRequest,
    asset: Asset,
    verification: PeriodicVerification,
    target_legacy_user_id: int,
    target_details: dict[str, str],
) -> tuple[AssetCalendarEvent, bool]:
    next_date = verification.next_verification_date
    if not isinstance(next_date, date):
        raise RuntimeError("La manutenzione periodica selezionata non ha una prossima data impostata.")
    source_key = _asset_calendar_source_key(
        event_kind=AssetCalendarEvent.KIND_PERIODIC_VERIFICATION,
        asset_id=asset.id,
        source_id=verification.id,
        due_date=next_date,
        target_legacy_user_id=target_legacy_user_id,
    )
    payload = _build_periodic_verification_outlook_event_payload(
        request=request,
        asset=asset,
        verification=verification,
        target_display_name=_clean_string(target_details.get("display_name")),
        transaction_id=_asset_calendar_transaction_id(source_key=source_key),
    )
    return _create_asset_calendar_event_record(
        asset=asset,
        event_kind=AssetCalendarEvent.KIND_PERIODIC_VERIFICATION,
        source_key=source_key,
        due_date=next_date,
        target_legacy_user_id=target_legacy_user_id,
        target_details=target_details,
        payload=payload,
        request_user=request.user,
        periodic_verification=verification,
    )


def _create_asset_assistance_contract_calendar_event(
    *,
    request: HttpRequest,
    asset: Asset,
    contract: AssistanceContract,
    target_legacy_user_id: int,
    target_details: dict[str, str],
) -> tuple[AssetCalendarEvent, bool]:
    if not isinstance(contract.end_date, date):
        raise RuntimeError("Il contratto selezionato non ha una data scadenza impostata.")
    source_key = _asset_calendar_source_key(
        event_kind=AssetCalendarEvent.KIND_ASSISTANCE_CONTRACT,
        asset_id=asset.id,
        source_id=contract.id,
        due_date=contract.end_date,
        target_legacy_user_id=target_legacy_user_id,
    )
    payload = _build_assistance_contract_outlook_event_payload(
        request=request,
        asset=asset,
        contract=contract,
        target_display_name=_clean_string(target_details.get("display_name")),
        transaction_id=_asset_calendar_transaction_id(source_key=source_key),
    )
    return _create_asset_calendar_event_record(
        asset=asset,
        event_kind=AssetCalendarEvent.KIND_ASSISTANCE_CONTRACT,
        source_key=source_key,
        due_date=contract.end_date,
        target_legacy_user_id=target_legacy_user_id,
        target_details=target_details,
        payload=payload,
        request_user=request.user,
        assistance_contract=contract,
    )


def _as_int(value, default: int = 100) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _unique_custom_field_code(label: str, requested_code: str | None = None) -> str:
    seed = _clean_string(requested_code) or _clean_string(label)
    base = slugify(seed)[:70]
    if not base:
        base = f"campo-{uuid4().hex[:8]}"
    candidate = base
    index = 2
    while AssetCustomField.objects.filter(code=candidate).exists():
        suffix = f"-{index}"
        candidate = f"{base[: max(1, 80 - len(suffix))]}{suffix}"
        index += 1
    return candidate


def _update_custom_field_values_after_delete(field_code: str) -> int:
    updated_count = 0
    for asset in Asset.objects.only("id", "extra_columns").iterator():
        if not isinstance(asset.extra_columns, dict):
            continue
        if field_code not in asset.extra_columns:
            continue
        next_extra = dict(asset.extra_columns)
        next_extra.pop(field_code, None)
        asset.extra_columns = next_extra
        asset.save(update_fields=["extra_columns"])
        updated_count += 1
    return updated_count


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


def _handle_list_option_request(request: HttpRequest) -> tuple[bool, str]:
    action = _clean_string(request.POST.get("action"))
    valid_field_keys = {key for key, _ in AssetListOption.FIELD_CHOICES}

    if action == "create_list_option":
        field_key = _clean_string(request.POST.get("field_key"))
        value = _clean_string(request.POST.get("value"))
        if field_key not in valid_field_keys:
            return False, "Campo lista non valido."
        if not value:
            return False, "Inserisci il valore lista."
        sort_order = _as_int(request.POST.get("sort_order"), default=100)
        is_active = bool(request.POST.get("is_active"))
        option, created = AssetListOption.objects.get_or_create(
            field_key=field_key,
            value=value,
            defaults={"sort_order": sort_order, "is_active": is_active},
        )
        if created:
            return True, f"Valore \"{value}\" aggiunto."
        option.sort_order = sort_order
        option.is_active = is_active
        option.save(update_fields=["sort_order", "is_active", "updated_at"])
        return True, f"Valore \"{value}\" aggiornato."

    if action == "update_list_option":
        option_id = _as_int(request.POST.get("option_id"), default=0)
        option = AssetListOption.objects.filter(pk=option_id).first()
        if not option:
            return False, "Valore lista non trovato."
        field_key = _clean_string(request.POST.get("field_key")) or option.field_key
        value = _clean_string(request.POST.get("value"))
        if field_key not in valid_field_keys:
            return False, "Campo lista non valido."
        if not value:
            return False, "Il valore lista non puo essere vuoto."
        sort_order = _as_int(request.POST.get("sort_order"), default=option.sort_order)
        is_active = bool(request.POST.get("is_active"))
        duplicate_qs = AssetListOption.objects.filter(field_key=field_key, value=value).exclude(pk=option.pk)
        if duplicate_qs.exists():
            return False, "Valore gia presente per questo campo."
        option.field_key = field_key
        option.value = value
        option.sort_order = sort_order
        option.is_active = is_active
        option.save(update_fields=["field_key", "value", "sort_order", "is_active", "updated_at"])
        return True, f"Valore \"{value}\" salvato."

    if action == "delete_list_option":
        option_id = _as_int(request.POST.get("option_id"), default=0)
        option = AssetListOption.objects.filter(pk=option_id).first()
        if not option:
            return False, "Valore lista non trovato."
        label = option.value
        option.delete()
        return True, f"Valore \"{label}\" eliminato."

    return False, "Azione lista non valida."


def _unique_action_button_code(label: str, requested_code: str | None = None) -> str:
    seed = _clean_string(requested_code) or _clean_string(label)
    base = slugify(seed)[:70]
    if not base:
        base = f"button-{uuid4().hex[:8]}"
    candidate = base
    index = 2
    while AssetActionButton.objects.filter(code=candidate).exists():
        suffix = f"-{index}"
        candidate = f"{base[: max(1, 80 - len(suffix))]}{suffix}"
        index += 1
    return candidate


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
            "grid_size": AssetDetailSectionLayout.SIZE_HALF,
            "sort_order": 240,
            "is_visible": True,
        },
        {
            "code": AssetDetailSectionLayout.SECTION_QUICK_ACTIONS,
            "grid_size": AssetDetailSectionLayout.SIZE_HALF,
            "sort_order": 250,
            "is_visible": True,
        },
        {
            "code": AssetDetailSectionLayout.SECTION_SHAREPOINT,
            "grid_size": AssetDetailSectionLayout.SIZE_HALF,
            "sort_order": 260,
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


def _detail_field_matches_asset_scope(detail_field: AssetDetailField, work_machine: WorkMachine | None) -> bool:
    if detail_field.asset_scope == AssetDetailField.SCOPE_ALL:
        return True
    if detail_field.asset_scope == AssetDetailField.SCOPE_WORK_MACHINE:
        return isinstance(work_machine, WorkMachine)
    if detail_field.asset_scope == AssetDetailField.SCOPE_STANDARD:
        return not isinstance(work_machine, WorkMachine)
    return False


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
        return _coalesce_str(extra.get("storage_free"), extra.get("free_storage"), getattr(it_details, "disco", ""), "")
    if source_key == "purchase_date":
        return _coalesce_str(extra.get("purchase_date"), asset.created_at.strftime("%d/%m/%Y") if asset.created_at else "", "")
    if source_key == "sync_text":
        return sync_text
    return ""


def _format_asset_detail_value(value, value_format: str) -> str:
    if value_format == AssetDetailField.FORMAT_BOOL:
        return "Si" if bool(value) else "No"
    if value_format == AssetDetailField.FORMAT_DATE:
        if isinstance(value, datetime):
            return timezone.localtime(value).strftime("%d/%m/%Y")
        if isinstance(value, date):
            return value.strftime("%d/%m/%Y")
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
        return timezone.localtime(value).strftime("%d/%m/%Y")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    cleaned = _clean_string(str(value) if value not in (None, "") else "")
    return cleaned or "N/D"


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
    sections: dict[str, list[dict[str, str]]] = defaultdict(list)
    has_matching_config = False
    for detail_field in configured:
        if not _detail_field_matches_asset_scope(detail_field, work_machine):
            continue
        has_matching_config = True
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
        if formatted_value == "N/D" and not detail_field.show_if_empty:
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
        if formatted_value == "N/D" and not field_def.show_if_empty:
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
    active_match = _clean_string(button.active_match)
    full_path = request.get_full_path()
    if active_match:
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

    for key, values in target_qs.items():
        current_value = request.GET.get(key, "")
        if current_value not in values:
            return False
    return True


def _default_sidebar_buttons(request: HttpRequest, rows: int = 25) -> list[dict]:
    base_list = reverse("assets:asset_list")
    asset_dashboard = reverse("assets:asset_dashboard")
    asset_components = reverse("assets:asset_component_list")
    asset_deadlines = reverse("assets:asset_administrative_deadline_list")
    maintenance_templates = reverse("assets:maintenance_template_list")
    maintenance_rules = reverse("assets:maintenance_rule_list")
    maintenance_schedule = reverse("assets:maintenance_schedule")
    assistance_contracts = reverse("assets:assistance_contract_list")
    software_licenses = reverse("assets:software_license_list")
    work_machine_list = reverse("assets:work_machine_list")
    work_machine_dashboard = reverse("assets:work_machine_dashboard")
    periodic_verifications = reverse("assets:periodic_verifications")
    plant_layout_map = reverse("assets:plant_layout_map")
    reports = reverse("assets:reports")
    wo_list = reverse("assets:wo_list")
    current_type = _clean_string(request.GET.get("asset_type"))
    current_route = getattr(getattr(request, "resolver_match", None), "url_name", "")
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
            "label": "Cruscotto",
            "url": f"{base_list}?rows={rows}",
            "is_subitem": False,
            "active": not current_type and current_route == "asset_list",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Dispositivi",
            "url": f"{base_list}?asset_type=HW&rows={rows}",
            "is_subitem": False,
            "active": current_type == Asset.TYPE_HW and current_route == "asset_list",
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
            "label": "Postazioni di lavoro",
            "url": f"{base_list}?asset_type={Asset.TYPE_PC}&rows={rows}",
            "is_subitem": True,
            "active": current_type in {Asset.TYPE_PC, Asset.TYPE_NOTEBOOK} and current_route == "asset_list",
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
            "url": maintenance_templates,
            "is_subitem": False,
            "active": current_route in {
                "maintenance_template_list", "maintenance_template_create", "maintenance_template_edit",
                "maintenance_rule_list", "maintenance_rule_create", "maintenance_rule_edit",
                "periodic_verifications",
                "reports",
            },
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Template manutenzione",
            "url": maintenance_templates,
            "is_subitem": True,
            "active": current_route in {"maintenance_template_list", "maintenance_template_create", "maintenance_template_edit"},
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Regole manutenzione",
            "url": maintenance_rules,
            "is_subitem": True,
            "active": current_route in {"maintenance_rule_list", "maintenance_rule_create", "maintenance_rule_edit"},
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Manutenzione periodica",
            "url": periodic_verifications,
            "is_subitem": True,
            "active": current_route == "periodic_verifications",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Report manutenzione",
            "url": reports,
            "is_subitem": True,
            "active": current_route == "reports",
        },
        {
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Macchine di lavoro",
            "url": work_machine_list,
            "is_subitem": False,
            "active": current_route in {"work_machine_list", "work_machine_create", "work_machine_edit"},
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
            "label": "Interventi",
            "url": wo_list,
            "is_subitem": False,
            "active": current_route == "wo_list",
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
            "label": "Cruscotto",
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
            "label": "Dispositivi",
            "target_url": "django:assets:asset_list?asset_type=HW&rows={rows}",
            "active_match": "asset_type=HW",
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
            "label": "Postazioni di lavoro",
            "target_url": "django:assets:asset_list?asset_type=PC&rows={rows}",
            "active_match": "asset_type=PC",
            "is_subitem": True,
            "parent_code": "hardware",
            "sort_order": 40,
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
            "code": "work_machines",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Macchine di lavoro",
            "target_url": "django:assets:work_machine_list",
            "active_match": "/assets/work-machines/",
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
            "sort_order": 61,
            "is_visible": True,
        },
        {
            "code": "periodic_verifications",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Manutenzione periodica",
            "target_url": "django:assets:periodic_verifications",
            "active_match": "/assets/manutenzione/verifiche/",
            "is_subitem": True,
            "parent_code": "manutenzione_hub",
            "sort_order": 57,
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
            "target_url": "django:assets:maintenance_template_list",
            "active_match": "/assets/manutenzione/",
            "is_subitem": False,
            "parent_code": "",
            "sort_order": 54,
            "is_visible": True,
        },
        {
            "code": "maintenance_templates",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Template manutenzione",
            "target_url": "django:assets:maintenance_template_list",
            "active_match": "/assets/manutenzione/templates/",
            "is_subitem": True,
            "parent_code": "manutenzione_hub",
            "sort_order": 55,
            "is_visible": True,
        },
        {
            "code": "maintenance_rules",
            "section": AssetSidebarButton.SECTION_MAIN,
            "label": "Regole manutenzione",
            "target_url": "django:assets:maintenance_rule_list",
            "active_match": "/assets/manutenzione/regole/",
            "is_subitem": True,
            "parent_code": "manutenzione_hub",
            "sort_order": 56,
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
            "label": "Prossime manutenzioni",
            "target_url": "django:assets:maintenance_schedule",
            "active_match": "/assets/manutenzione/prossime/",
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
            "label": "Report manutenzione",
            "target_url": "django:assets:reports",
            "active_match": "/assets/reports/",
            "is_subitem": True,
            "parent_code": "manutenzione_hub",
            "sort_order": 58,
            "is_visible": True,
        },
        {
            "code": "compliance_reports",
            "section": AssetSidebarButton.SECTION_ANALYTICS,
            "label": "Scadenzario operativo",
            "target_url": "django:assets:maintenance_schedule",
            "active_match": "/assets/manutenzione/prossime/",
            "is_subitem": False,
            "parent_code": "",
            "sort_order": 80,
            "is_visible": True,
        },
    ]


def _sidebar_input_suggestions() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    target_suggestions: list[dict[str, str]] = []
    active_match_suggestions: list[dict[str, str]] = []
    seen_targets: set[str] = set()
    seen_active_matches: set[str] = set()

    def add_target(value: str, label: str = "") -> None:
        normalized = _clean_string(value)
        if not normalized or normalized in seen_targets:
            return
        seen_targets.add(normalized)
        target_suggestions.append({"value": normalized, "label": label})

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
        ("django:assets:periodic_verifications", "Manutenzione periodica"),
        ("django:assets:plant_layout_map", "Mappa officina"),
        ("django:assets:wo_list", "Interventi / Work order"),
        ("django:assets:software_license_list", "Licenze software"),
        ("django:assets:maintenance_schedule", "Prossime manutenzioni"),
        ("django:assets:assistance_contract_list", "Contratti assistenza"),
        ("django:assets:reports", "Report manutenzione"),
        ("django:assets:gestione_admin", "Impostazioni assets"),
    ]
    for value, label in route_targets:
        add_target(value, label)

    for asset_type_code, asset_type_label in Asset.TYPE_CHOICES:
        add_target(
            f"django:assets:asset_list?asset_type={asset_type_code}&rows={{rows}}",
            f"Lista asset: {asset_type_label}",
        )
        add_active_match(f"asset_type={asset_type_code}", f"Filtro asset_type: {asset_type_label}")

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
        ("assets:reports", "Report manutenzione"),
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
        ("rows={rows}", "Placeholder righe per pagina"),
    ]:
        add_active_match(value, label)

    for button in AssetSidebarButton.objects.exclude(target_url="").only("target_url"):
        add_target(button.target_url, "Gia configurato")
    for button in AssetSidebarButton.objects.exclude(active_match="").only("active_match"):
        add_active_match(button.active_match, "Gia configurato")

    return target_suggestions, active_match_suggestions


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
    }


def _build_sidebar_groups(request: HttpRequest, rows: int = 25) -> list[dict]:
    section_label = dict(AssetSidebarButton.SECTION_CHOICES)
    section_order = {
        AssetSidebarButton.SECTION_MAIN: 0,
        AssetSidebarButton.SECTION_ANALYTICS: 1,
        AssetSidebarButton.SECTION_OPERATIONS: 2,
    }
    configured = list(
        AssetSidebarButton.objects.filter(is_visible=True)
        .select_related("parent")
        .order_by("section", "sort_order", "id")
    )
    grouped: dict[str, list[dict]] = defaultdict(list)

    if configured:
        visible_by_id = {button.id: button for button in configured}
        roots_by_section: dict[str, list[AssetSidebarButton]] = defaultdict(list)
        children_by_parent: dict[int, list[AssetSidebarButton]] = defaultdict(list)

        for button in configured:
            if button.parent_id and button.parent_id in visible_by_id:
                children_by_parent[button.parent_id].append(button)
            else:
                roots_by_section[button.section].append(button)

        for section, root_buttons in roots_by_section.items():
            for button in root_buttons:
                grouped[section].append(_sidebar_button_payload(request, button, rows=rows, force_subitem=button.is_subitem))
                for child in children_by_parent.get(button.id, []):
                    grouped[section].append(_sidebar_button_payload(request, child, rows=rows, force_subitem=True))
    else:
        for payload in _default_sidebar_buttons(request, rows=rows):
            grouped[payload["section"]].append(payload)

    output = []
    for section, items in sorted(grouped.items(), key=lambda row: section_order.get(row[0], 99)):
        output.append({"section": section, "label": section_label.get(section, section), "items": items})
    return output


def _sidebar_parent_choices() -> list[AssetSidebarButton]:
    return list(
        AssetSidebarButton.objects.filter(parent__isnull=True)
        .order_by("section", "sort_order", "label", "id")
    )


def _header_tool_visibility(is_admin: bool) -> dict[str, bool]:
    """Restituisce can_hdr_<code> per ogni strumento header in base ai settings DB."""
    tools = {t.code: t for t in AssetHeaderTool.objects.all()}

    def _visible(code: str) -> bool:
        t = tools.get(code)
        if t is None:
            return True  # default: visibile se non ancora in DB
        if not t.is_active:
            return False
        if t.admin_only and not is_admin:
            return False
        return True

    return {
        "can_hdr_avvisi": _visible(AssetHeaderTool.TOOL_AVVISI),
        "can_hdr_widget": _visible(AssetHeaderTool.TOOL_WIDGET),
        "can_hdr_sync": _visible(AssetHeaderTool.TOOL_SYNC),
    }


def _handle_header_tool_request(request: HttpRequest) -> tuple[bool, str]:
    action = _clean_string(request.POST.get("action"))
    if action == "update_header_tool":
        tool_id = _as_int(request.POST.get("tool_id"), default=0)
        tool = AssetHeaderTool.objects.filter(pk=tool_id).first()
        if not tool:
            return False, "Strumento non trovato."
        tool.is_active = request.POST.get("is_active") == "1"
        tool.admin_only = request.POST.get("admin_only") == "1"
        tool.save(update_fields=["is_active", "admin_only"])
        return True, f"Strumento «{tool.label}» aggiornato."
    return False, "Azione non riconosciuta."


def _handle_sidebar_button_request(request: HttpRequest) -> tuple[bool, str]:
    action = _clean_string(request.POST.get("action"))
    valid_sections = {key for key, _ in AssetSidebarButton.SECTION_CHOICES}

    if action == "seed_sidebar_buttons":
        if AssetSidebarButton.objects.exists():
            return False, "Menu sidebar già configurato."
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
        return True, f"Menu sidebar inizializzato ({created} voci)."

    if action == "create_sidebar_button":
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Inserisci etichetta menu."
        parent_id = _as_int(
            request.POST.get("parent_sidebar_button_id") or request.POST.get("parent_id"),
            default=0,
        )
        parent_button = AssetSidebarButton.objects.filter(pk=parent_id).first() if parent_id else None
        if parent_button and parent_button.parent_id:
            return False, "La voce padre deve essere di primo livello."
        section = _clean_string(request.POST.get("section")) or AssetSidebarButton.SECTION_MAIN
        if section not in valid_sections:
            section = AssetSidebarButton.SECTION_MAIN
        if parent_button is not None:
            section = parent_button.section
        code = _unique_sidebar_button_code(label, request.POST.get("code"))
        AssetSidebarButton.objects.create(
            code=code,
            section=section,
            parent=parent_button,
            label=label[:120],
            target_url=_clean_string(request.POST.get("target_url")),
            active_match=_clean_string(request.POST.get("active_match")),
            is_subitem=True if parent_button is not None else bool(request.POST.get("is_subitem")),
            sort_order=_as_int(request.POST.get("sort_order"), default=100),
            is_visible=bool(request.POST.get("is_visible")),
        )
        return True, f"Voce menu \"{label}\" creata."

    if action == "update_sidebar_button":
        button_id = _as_int(request.POST.get("sidebar_button_id"), default=0)
        button = AssetSidebarButton.objects.filter(pk=button_id).first()
        if not button:
            return False, "Voce menu non trovata."
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Etichetta menu obbligatoria."
        parent_id = _as_int(
            request.POST.get("parent_sidebar_button_id") or request.POST.get("parent_id"),
            default=0,
        )
        parent_button = AssetSidebarButton.objects.filter(pk=parent_id).first() if parent_id else None
        if parent_button and parent_button.id == button.id:
            return False, "Una voce non puo essere padre di se stessa."
        if parent_button and parent_button.parent_id:
            return False, "La voce padre deve essere di primo livello."
        section = _clean_string(request.POST.get("section")) or button.section
        if section not in valid_sections:
            section = button.section
        if parent_button is not None:
            section = parent_button.section
        button.section = section
        button.parent = parent_button
        button.label = label[:120]
        button.target_url = _clean_string(request.POST.get("target_url"))
        button.active_match = _clean_string(request.POST.get("active_match"))
        button.is_subitem = True if parent_button is not None else bool(request.POST.get("is_subitem"))
        button.sort_order = _as_int(request.POST.get("sort_order"), default=button.sort_order)
        button.is_visible = bool(request.POST.get("is_visible"))
        button.save(
            update_fields=[
                "section",
                "parent",
                "label",
                "target_url",
                "active_match",
                "is_subitem",
                "sort_order",
                "is_visible",
                "updated_at",
            ]
        )
        return True, f"Voce menu \"{button.label}\" aggiornata."

    if action == "delete_sidebar_button":
        button_id = _as_int(request.POST.get("sidebar_button_id"), default=0)
        button = AssetSidebarButton.objects.filter(pk=button_id).first()
        if not button:
            return False, "Voce menu non trovata."
        label = button.label
        button.delete()
        return True, f"Voce menu \"{label}\" eliminata."

    if action == "reset_sidebar_buttons":
        deleted, _ = AssetSidebarButton.objects.all().delete()
        payload = _default_sidebar_seed_rows()
        created = 0
        created_by_code: dict[str, AssetSidebarButton] = {}
        for row in payload:
            button, _ = AssetSidebarButton.objects.get_or_create(
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
            btn = created_by_code.get(row["code"])
            parent = created_by_code.get(parent_code)
            if btn is None or parent is None or btn.parent_id == parent.id:
                continue
            btn.parent = parent
            btn.is_subitem = True
            btn.section = parent.section
            btn.save(update_fields=["parent", "is_subitem", "section", "updated_at"])
        return True, f"Menu sidebar reimpostato ai valori predefiniti ({created} voci, {deleted} eliminate)."

    if action == "clear_sidebar_buttons":
        deleted, _ = AssetSidebarButton.objects.all().delete()
        return True, f"Menu sidebar svuotato ({deleted} voci eliminate). Il portale usa ora il menu predefinito aggiornato."

    return False, "Azione menu non valida."


def _assets_shell_context(
    request: HttpRequest,
    *,
    rows: int = 25,
    search_action: str | None = None,
    new_url: str | None = None,
    new_label: str | None = None,
    search_placeholder: str | None = None,
) -> dict[str, object]:
    logo_url = resolve_module_logo("assets", legacy_logo_keys=("assets_logo_image",)) or None
    display_label = resolve_module_label("assets", fallback="Assets", surface="display")
    return {
        "assets_sidebar_groups": _build_sidebar_groups(request, rows=rows),
        "assets_shell_search_action": search_action or reverse("assets:asset_list"),
        "assets_shell_new_url": new_url or reverse("assets:asset_create"),
        "assets_shell_new_label": new_label or "+ Nuovo asset",
        "assets_shell_search_placeholder": search_placeholder or "Ricerca rapida per asset, seriali o utenti (Ctrl + K)",
        "can_gestione_admin": user_can_modulo_action(request, "assets", "admin_assets"),
        "assets_logo_url": logo_url,
        "assets_brand_label": display_label,
    }


def _safe_editor_json_rows(raw_value) -> list[dict[str, object]]:
    if not raw_value:
        return []
    try:
        payload = json.loads(raw_value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _plant_layout_editor_area_rows(layout: PlantLayout | None) -> list[dict[str, object]]:
    if layout is None:
        return []
    return [
        {
            "id": area.id,
            "name": area.name,
            "reparto_code": area.reparto_code,
            "color": area.color,
            "notes": area.notes,
            "x_percent": float(area.x_percent),
            "y_percent": float(area.y_percent),
            "width_percent": float(area.width_percent),
            "height_percent": float(area.height_percent),
            "sort_order": area.sort_order,
        }
        for area in layout.areas.all().order_by("sort_order", "id")
    ]


def _plant_layout_editor_marker_rows(layout: PlantLayout | None) -> list[dict[str, object]]:
    if layout is None:
        return []
    return [
        {
            "id": marker.id,
            "asset_id": marker.asset_id,
            "label": marker.label,
            "x_percent": float(marker.x_percent),
            "y_percent": float(marker.y_percent),
            "sort_order": marker.sort_order,
        }
        for marker in layout.markers.select_related("asset").all().order_by("sort_order", "id")
    ]


def _plant_layout_machine_catalog() -> list[dict[str, object]]:
    machines = (
        Asset.objects.filter(asset_type=Asset.TYPE_WORK_MACHINE)
        .select_related("work_machine")
        .order_by("reparto", "name", "asset_tag", "id")
    )
    catalog: list[dict[str, object]] = []
    for asset in machines:
        machine = getattr(asset, "work_machine", None)
        catalog.append(
            {
                "id": asset.id,
                "asset_tag": asset.asset_tag,
                "name": asset.name,
                "reparto": _clean_string(asset.reparto),
                "status": asset.get_status_display(),
                "status_code": asset.status,
                "location": _clean_string(asset.assignment_location),
                "manufacturer": _clean_string(asset.manufacturer),
                "model": _clean_string(asset.model),
                "detail_url": reverse("assets:asset_view", kwargs={"id": asset.id}),
                "next_maintenance_date": (
                    machine.next_maintenance_date.strftime("%d/%m/%Y")
                    if isinstance(machine, WorkMachine) and machine.next_maintenance_date
                    else ""
                ),
                "cnc_controlled": bool(getattr(machine, "cnc_controlled", False)),
                "five_axes": bool(getattr(machine, "five_axes", False)),
            }
        )
    return catalog


def _plant_layout_queryset():
    return PlantLayout.objects.prefetch_related("areas", "markers", "markers__asset", "markers__asset__work_machine")


def _preferred_plant_layout_category(
    active_layouts: list[PlantLayout],
    *,
    requested_category: str = "",
    fallback_category: str = PlantLayout.DEFAULT_CATEGORY,
) -> str:
    requested = _clean_string(requested_category)
    if requested:
        for layout in active_layouts:
            if _clean_string(layout.category).casefold() == requested.casefold():
                return layout.category
    for layout in active_layouts:
        if _clean_string(layout.category).casefold() == _clean_string(fallback_category).casefold():
            return layout.category
    return active_layouts[0].category if active_layouts else ""


def _plant_layout_category_switches(
    *,
    active_layouts: list[PlantLayout],
    selected_category: str,
    focus_asset_id: int = 0,
) -> list[dict[str, object]]:
    try:
        base_url = reverse("assets:plant_layout_map")
    except NoReverseMatch:
        base_url = "/assets/work-machines/map/"
    switches: list[dict[str, object]] = []
    seen_categories: set[str] = set()
    for layout in active_layouts:
        category_key = _clean_string(layout.category).casefold()
        if category_key in seen_categories:
            continue
        seen_categories.add(category_key)
        params = [f"category={quote(layout.category)}"]
        if focus_asset_id:
            params.append(f"asset={focus_asset_id}")
        switches.append(
            {
                "category": layout.category,
                "active": _clean_string(layout.category).casefold() == _clean_string(selected_category).casefold(),
                "url": f"{base_url}?{'&'.join(params)}",
                "layout_name": layout.name,
            }
        )
    return switches


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert #RRGGBB to rgba(r,g,b,alpha) for CSS compatibility without color-mix()."""
    h = str(hex_color or "").strip().lstrip("#")
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, IndexError):
        r, g, b = 37, 99, 235  # fallback #2563EB
    return f"rgba({r},{g},{b},{alpha})"


def _plant_layout_public_payload(layout: PlantLayout | None) -> dict[str, object]:
    if layout is None:
        return {"layout": None, "areas": [], "markers": [], "machine_catalog": []}

    machine_catalog = _plant_layout_machine_catalog()
    machines_by_id = {row["id"]: row for row in machine_catalog}
    reparto_machine_rows: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in machine_catalog:
        reparto_machine_rows[_clean_string(str(row.get("reparto") or ""))].append(dict(row))

    reparto_area_ids: dict[str, list[int]] = defaultdict(list)
    area_payload: list[dict[str, object]] = []
    for area in layout.areas.all().order_by("sort_order", "id"):
        reparto_code = _clean_string(area.reparto_code)
        reparto_area_ids[reparto_code].append(area.id)
        area_payload.append(
            {
                "id": area.id,
                "name": area.name,
                "reparto_code": reparto_code,
                "color": area.color,
                "bg_color": _hex_to_rgba(area.color, 0.22),
                "active_bg_color": _hex_to_rgba(area.color, 0.40),
                "notes": area.notes,
                "x_percent": float(area.x_percent),
                "y_percent": float(area.y_percent),
                "width_percent": float(area.width_percent),
                "height_percent": float(area.height_percent),
                "machine_count": len(reparto_machine_rows.get(reparto_code, [])),
                "machines": list(reparto_machine_rows.get(reparto_code, [])),
            }
        )

    marker_payload: list[dict[str, object]] = []
    for marker in layout.markers.select_related("asset", "asset__work_machine").all().order_by("sort_order", "id"):
        asset_payload = dict(machines_by_id.get(marker.asset_id) or {})
        asset_payload["marker_id"] = marker.id
        marker_payload.append(
            {
                "id": marker.id,
                "asset_id": marker.asset_id,
                "label": marker.label or asset_payload.get("asset_tag") or asset_payload.get("name") or f"Marker {marker.id}",
                "x_percent": float(marker.x_percent),
                "y_percent": float(marker.y_percent),
                "area_ids": list(reparto_area_ids.get(_clean_string(str(asset_payload.get("reparto") or "")), [])),
                "machine": asset_payload,
            }
        )

    return {
        "layout": {
            "id": layout.id,
            "name": layout.name,
            "description": layout.description,
            "image_url": layout.image.url if layout.image else "",
            "is_active": layout.is_active,
        },
        "areas": area_payload,
        "markers": marker_payload,
        "machine_catalog": machine_catalog,
    }


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

    return {
        AssetActionButton.ZONE_HEADER: [
            {"label": "Etichetta QR", "style": AssetActionButton.STYLE_DEFAULT, "href": qr_url, "data_action": "", "new_tab": True},
            {"label": "Modifica dettagli", "style": AssetActionButton.STYLE_PRIMARY, "href": edit_url, "data_action": "", "new_tab": False},
        ],
        AssetActionButton.ZONE_QUICK: [
            {"label": "Riassegna", "style": AssetActionButton.STYLE_DEFAULT, "href": assign_url, "data_action": "", "new_tab": False},
            {"label": "Crea intervento", "style": AssetActionButton.STYLE_DEFAULT, "href": wo_url, "data_action": "", "new_tab": False},
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


def _handle_action_button_request(request: HttpRequest) -> tuple[bool, str]:
    action = _clean_string(request.POST.get("action"))
    valid_zones = {key for key, _ in AssetActionButton.ZONE_CHOICES}
    valid_action_types = {key for key, _ in AssetActionButton.ACTION_CHOICES}
    valid_styles = {key for key, _ in AssetActionButton.STYLE_CHOICES}

    if action == "create_action_button":
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Inserisci etichetta pulsante."
        zone = _clean_string(request.POST.get("zone")) or AssetActionButton.ZONE_QUICK
        if zone not in valid_zones:
            zone = AssetActionButton.ZONE_QUICK
        action_type = _clean_string(request.POST.get("action_type")) or AssetActionButton.TYPE_LINK
        if action_type not in valid_action_types:
            action_type = AssetActionButton.TYPE_LINK
        style = _clean_string(request.POST.get("style")) or AssetActionButton.STYLE_DEFAULT
        if style not in valid_styles:
            style = AssetActionButton.STYLE_DEFAULT
        target = _clean_string(request.POST.get("target"))
        if action_type == AssetActionButton.TYPE_LINK and not target:
            return False, "Per i pulsanti LINK devi inserire un target."
        code = _unique_action_button_code(label, request.POST.get("code"))
        AssetActionButton.objects.create(
            code=code,
            zone=zone,
            label=label[:120],
            action_type=action_type,
            target=target,
            style=style,
            sort_order=_as_int(request.POST.get("sort_order"), default=100),
            open_in_new_tab=bool(request.POST.get("open_in_new_tab")),
            is_active=bool(request.POST.get("is_active")),
        )
        return True, f"Pulsante \"{label}\" creato."

    if action == "update_action_button":
        button_id = _as_int(request.POST.get("button_id"), default=0)
        button = AssetActionButton.objects.filter(pk=button_id).first()
        if not button:
            return False, "Pulsante non trovato."
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Etichetta pulsante obbligatoria."
        zone = _clean_string(request.POST.get("zone")) or button.zone
        if zone not in valid_zones:
            zone = button.zone
        action_type = _clean_string(request.POST.get("action_type")) or button.action_type
        if action_type not in valid_action_types:
            action_type = button.action_type
        style = _clean_string(request.POST.get("style")) or button.style
        if style not in valid_styles:
            style = button.style
        target = _clean_string(request.POST.get("target"))
        if action_type == AssetActionButton.TYPE_LINK and not target:
            return False, "Per i pulsanti LINK devi inserire un target."
        button.zone = zone
        button.label = label[:120]
        button.action_type = action_type
        button.target = target
        button.style = style
        button.sort_order = _as_int(request.POST.get("sort_order"), default=button.sort_order)
        button.open_in_new_tab = bool(request.POST.get("open_in_new_tab"))
        button.is_active = bool(request.POST.get("is_active"))
        button.save(
            update_fields=[
                "zone",
                "label",
                "action_type",
                "target",
                "style",
                "sort_order",
                "open_in_new_tab",
                "is_active",
                "updated_at",
            ]
        )
        return True, f"Pulsante \"{button.label}\" aggiornato."

    if action == "delete_action_button":
        button_id = _as_int(request.POST.get("button_id"), default=0)
        button = AssetActionButton.objects.filter(pk=button_id).first()
        if not button:
            return False, "Pulsante non trovato."
        label = button.label
        button.delete()
        return True, f"Pulsante \"{label}\" eliminato."

    return False, "Azione pulsante non valida."


def _handle_detail_field_request(request: HttpRequest) -> tuple[bool, str]:
    action = _clean_string(request.POST.get("action"))
    valid_sections = {key for key, _ in AssetDetailField.SECTION_CHOICES}
    valid_scopes = {key for key, _ in AssetDetailField.SCOPE_CHOICES}
    valid_formats = {key for key, _ in AssetDetailField.FORMAT_CHOICES}
    valid_card_sizes = {key for key, _ in AssetDetailField.CARD_SIZE_CHOICES}

    if action == "seed_detail_fields":
        created = _seed_default_asset_detail_fields(create_only_if_empty=True)
        if created <= 0:
            return False, "Campi dettaglio gia configurati."
        return True, f"Schema dettaglio asset inizializzato ({created} campi)."

    if action == "create_detail_field":
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Inserisci etichetta campo dettaglio."
        section = _clean_string(request.POST.get("section")) or AssetDetailField.SECTION_SPECS
        if section not in valid_sections:
            section = AssetDetailField.SECTION_SPECS
        asset_scope = _clean_string(request.POST.get("asset_scope")) or AssetDetailField.SCOPE_ALL
        if asset_scope not in valid_scopes:
            asset_scope = AssetDetailField.SCOPE_ALL
        value_format = _clean_string(request.POST.get("value_format")) or AssetDetailField.FORMAT_AUTO
        if value_format not in valid_formats:
            value_format = AssetDetailField.FORMAT_AUTO
        card_size = _clean_string(request.POST.get("card_size")) or AssetDetailField.CARD_THIRD
        if card_size not in valid_card_sizes:
            card_size = AssetDetailField.CARD_THIRD
        source_ref = _clean_string(request.POST.get("source_ref"))
        if not source_ref:
            return False, "Seleziona il dato da mostrare."
        AssetDetailField.objects.create(
            code=_unique_detail_field_code(label, request.POST.get("code")),
            label=label[:120],
            section=section,
            asset_scope=asset_scope,
            source_ref=source_ref[:120],
            value_format=value_format,
            card_size=card_size,
            sort_order=_as_int(request.POST.get("sort_order"), default=100),
            show_if_empty=bool(request.POST.get("show_if_empty")),
            is_active=bool(request.POST.get("is_active")),
        )
        return True, f"Campo dettaglio \"{label}\" creato."

    if action == "update_detail_field_bulk":
        bulk_field = _clean_string(request.POST.get("bulk_field"))
        apply_scope = _clean_string(request.POST.get("apply_scope")) or "selected"
        selected_ids = [
            row
            for row in {
                _as_int(value, default=0)
                for value in request.POST.getlist("selected_detail_field_ids")
            }
            if row > 0
        ]

        if apply_scope == "all":
            detail_fields = list(
                AssetDetailField.objects.order_by("section", "asset_scope", "sort_order", "label", "id")
            )
        else:
            detail_fields = list(
                AssetDetailField.objects.filter(pk__in=selected_ids).order_by(
                    "section", "asset_scope", "sort_order", "label", "id"
                )
            )

        if not detail_fields:
            return False, "Seleziona almeno un campo oppure usa l'opzione per applicare a tutti."

        if bulk_field == "section":
            bulk_value = _clean_string(request.POST.get("bulk_section"))
            if bulk_value not in valid_sections:
                return False, "Sezione bulk non valida."
            for detail_field in detail_fields:
                detail_field.section = bulk_value
                detail_field.save(update_fields=["section", "updated_at"])
            return True, f"Sezione aggiornata per {len(detail_fields)} campi."

        if bulk_field == "asset_scope":
            bulk_value = _clean_string(request.POST.get("bulk_asset_scope"))
            if bulk_value not in valid_scopes:
                return False, "Ambito bulk non valido."
            for detail_field in detail_fields:
                detail_field.asset_scope = bulk_value
                detail_field.save(update_fields=["asset_scope", "updated_at"])
            return True, f"Ambito aggiornato per {len(detail_fields)} campi."

        if bulk_field == "value_format":
            bulk_value = _clean_string(request.POST.get("bulk_value_format"))
            if bulk_value not in valid_formats:
                return False, "Formato bulk non valido."
            for detail_field in detail_fields:
                detail_field.value_format = bulk_value
                detail_field.save(update_fields=["value_format", "updated_at"])
            return True, f"Formato aggiornato per {len(detail_fields)} campi."

        if bulk_field == "card_size":
            bulk_value = _clean_string(request.POST.get("bulk_card_size"))
            if bulk_value not in valid_card_sizes:
                return False, "Dimensione bulk non valida."
            for detail_field in detail_fields:
                detail_field.card_size = bulk_value
                detail_field.save(update_fields=["card_size", "updated_at"])
            return True, f"Dimensione aggiornata per {len(detail_fields)} campi."

        if bulk_field == "show_if_empty":
            bulk_value = _clean_string(request.POST.get("bulk_show_if_empty"))
            if bulk_value not in {"show", "hide"}:
                return False, "Valore bulk per campi vuoti non valido."
            show_if_empty = bulk_value == "show"
            for detail_field in detail_fields:
                detail_field.show_if_empty = show_if_empty
                detail_field.save(update_fields=["show_if_empty", "updated_at"])
            return True, f"Visibilita campi vuoti aggiornata per {len(detail_fields)} campi."

        if bulk_field == "is_active":
            bulk_value = _clean_string(request.POST.get("bulk_is_active"))
            if bulk_value not in {"active", "inactive"}:
                return False, "Stato attivo bulk non valido."
            is_active = bulk_value == "active"
            for detail_field in detail_fields:
                detail_field.is_active = is_active
                detail_field.save(update_fields=["is_active", "updated_at"])
            return True, f"Stato attivo aggiornato per {len(detail_fields)} campi."

        return False, "Parametro bulk non valido."

    if action == "update_detail_field":
        detail_field_id = _as_int(request.POST.get("detail_field_id"), default=0)
        detail_field = AssetDetailField.objects.filter(pk=detail_field_id).first()
        if not detail_field:
            return False, "Campo dettaglio non trovato."
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Etichetta campo dettaglio obbligatoria."
        section = _clean_string(request.POST.get("section")) or detail_field.section
        if section not in valid_sections:
            section = detail_field.section
        asset_scope = _clean_string(request.POST.get("asset_scope")) or detail_field.asset_scope
        if asset_scope not in valid_scopes:
            asset_scope = detail_field.asset_scope
        value_format = _clean_string(request.POST.get("value_format")) or detail_field.value_format
        if value_format not in valid_formats:
            value_format = detail_field.value_format
        card_size = _clean_string(request.POST.get("card_size")) or detail_field.card_size
        if card_size not in valid_card_sizes:
            card_size = detail_field.card_size
        source_ref = _clean_string(request.POST.get("source_ref"))
        if not source_ref:
            return False, "Seleziona il dato da mostrare."
        detail_field.label = label[:120]
        detail_field.section = section
        detail_field.asset_scope = asset_scope
        detail_field.source_ref = source_ref[:120]
        detail_field.value_format = value_format
        detail_field.card_size = card_size
        detail_field.sort_order = _as_int(request.POST.get("sort_order"), default=detail_field.sort_order)
        detail_field.show_if_empty = bool(request.POST.get("show_if_empty"))
        detail_field.is_active = bool(request.POST.get("is_active"))
        detail_field.save(
            update_fields=[
                "label",
                "section",
                "asset_scope",
                "source_ref",
                "value_format",
                "card_size",
                "sort_order",
                "show_if_empty",
                "is_active",
                "updated_at",
            ]
        )
        return True, f"Campo dettaglio \"{detail_field.label}\" aggiornato."

    if action == "delete_detail_field":
        detail_field_id = _as_int(request.POST.get("detail_field_id"), default=0)
        detail_field = AssetDetailField.objects.filter(pk=detail_field_id).first()
        if not detail_field:
            return False, "Campo dettaglio non trovato."
        label = detail_field.label
        detail_field.delete()
        return True, f"Campo dettaglio \"{label}\" eliminato."

    return False, "Azione dettaglio asset non valida."


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


def _handle_asset_list_layout_request(request: HttpRequest) -> tuple[bool, str]:
    action = _clean_string(request.POST.get("action"))
    if action not in LIST_LAYOUT_ACTIONS:
        return False, "Azione layout lista non valida."

    try:
        layout_id = _as_int(request.POST.get("layout_id"), default=0)
        layout = AssetListLayout.objects.filter(pk=layout_id).first()
        if not layout:
            return False, "Preset lista non trovato."

        definition = _asset_list_context_definition_map().get(layout.context_key, {})
        default_columns = list(definition.get("visible_columns", []) or definition.get("default_columns", []) or [])
        custom_fields = list(AssetCustomField.objects.filter(is_active=True).order_by("sort_order", "id"))
        valid_keys = _asset_list_valid_column_keys(custom_fields)

        if action == "reset_asset_list_layout":
            layout.visible_columns = list(default_columns)
            layout.is_customized = False
            layout.save(update_fields=["visible_columns", "is_customized", "updated_at"])
            return True, f"Vista \"{layout.get_context_key_display()}\" ripristinata."

        selected_columns = _sanitize_asset_list_visible_columns(
            request.POST.getlist("visible_columns"),
            valid_keys,
            fallback=[],
        )
        if not selected_columns:
            return False, "Seleziona almeno una colonna per il preset centrale."

        layout.visible_columns = selected_columns
        layout.is_customized = True
        layout.save(update_fields=["visible_columns", "is_customized", "updated_at"])
        return True, f"Vista \"{layout.get_context_key_display()}\" aggiornata."
    except DatabaseError:
        return False, "Preset lista non disponibile finche il database non e' allineato con le migration."


def _handle_asset_category_request(request: HttpRequest) -> tuple[bool, str]:
    action = _clean_string(request.POST.get("action"))
    valid_asset_types = {key for key, _ in Asset.TYPE_CHOICES}
    valid_field_types = {key for key, _ in AssetCategoryField.TYPE_CHOICES}
    valid_sections = {key for key, _ in AssetDetailField.SECTION_CHOICES}
    valid_formats = {key for key, _ in AssetDetailField.FORMAT_CHOICES}
    valid_card_sizes = {key for key, _ in AssetDetailField.CARD_SIZE_CHOICES}

    if action == "create_asset_category":
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Inserisci il nome categoria."
        base_asset_type = _clean_string(request.POST.get("base_asset_type")) or Asset.TYPE_OTHER
        if base_asset_type not in valid_asset_types:
            base_asset_type = Asset.TYPE_OTHER
        AssetCategory.objects.create(
            code=_unique_asset_category_code(label, request.POST.get("code")),
            label=label[:120],
            base_asset_type=base_asset_type,
            description=_clean_string(request.POST.get("description")),
            detail_specs_title=_clean_string(request.POST.get("detail_specs_title"))[:120],
            detail_profile_title=_clean_string(request.POST.get("detail_profile_title"))[:120],
            detail_assignment_title=_clean_string(request.POST.get("detail_assignment_title"))[:120],
            detail_timeline_title=_clean_string(request.POST.get("detail_timeline_title"))[:120],
            detail_maintenance_title=_clean_string(request.POST.get("detail_maintenance_title"))[:120],
            sort_order=_as_int(request.POST.get("sort_order"), default=100),
            is_active=bool(request.POST.get("is_active")),
        )
        return True, f"Categoria asset \"{label}\" creata."

    if action == "update_asset_category":
        category_id = _as_int(request.POST.get("category_id"), default=0)
        category = AssetCategory.objects.filter(pk=category_id).first()
        if not category:
            return False, "Categoria asset non trovata."
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Il nome categoria e obbligatorio."
        base_asset_type = _clean_string(request.POST.get("base_asset_type")) or category.base_asset_type
        if base_asset_type not in valid_asset_types:
            base_asset_type = category.base_asset_type
        category.label = label[:120]
        category.base_asset_type = base_asset_type
        category.description = _clean_string(request.POST.get("description"))
        category.detail_specs_title = _clean_string(request.POST.get("detail_specs_title"))[:120]
        category.detail_profile_title = _clean_string(request.POST.get("detail_profile_title"))[:120]
        category.detail_assignment_title = _clean_string(request.POST.get("detail_assignment_title"))[:120]
        category.detail_timeline_title = _clean_string(request.POST.get("detail_timeline_title"))[:120]
        category.detail_maintenance_title = _clean_string(request.POST.get("detail_maintenance_title"))[:120]
        category.sort_order = _as_int(request.POST.get("sort_order"), default=category.sort_order)
        category.is_active = bool(request.POST.get("is_active"))
        category.save(
            update_fields=[
                "label",
                "base_asset_type",
                "description",
                "detail_specs_title",
                "detail_profile_title",
                "detail_assignment_title",
                "detail_timeline_title",
                "detail_maintenance_title",
                "sort_order",
                "is_active",
                "updated_at",
            ]
        )
        return True, f"Categoria asset \"{category.label}\" aggiornata."

    if action == "delete_asset_category":
        category_id = _as_int(request.POST.get("category_id"), default=0)
        category = AssetCategory.objects.filter(pk=category_id).first()
        if not category:
            return False, "Categoria asset non trovata."
        linked_assets = category.assets.count()
        if linked_assets:
            return False, f"La categoria \"{category.label}\" e assegnata a {linked_assets} asset: rimuovila prima dagli asset collegati."
        label = category.label
        category.delete()
        return True, f"Categoria asset \"{label}\" eliminata."

    if action == "create_asset_category_field":
        category_id = _as_int(request.POST.get("category_id"), default=0)
        category = AssetCategory.objects.filter(pk=category_id).first()
        if not category:
            return False, "Seleziona una categoria valida."
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Inserisci il nome campo categoria."
        field_type = _clean_string(request.POST.get("field_type")) or AssetCategoryField.TYPE_TEXT
        if field_type not in valid_field_types:
            field_type = AssetCategoryField.TYPE_TEXT
        detail_section = _clean_string(request.POST.get("detail_section")) or AssetDetailField.SECTION_SPECS
        if detail_section not in valid_sections:
            detail_section = AssetDetailField.SECTION_SPECS
        detail_value_format = _clean_string(request.POST.get("detail_value_format")) or AssetDetailField.FORMAT_AUTO
        if detail_value_format not in valid_formats:
            detail_value_format = AssetDetailField.FORMAT_AUTO
        detail_card_size = _clean_string(request.POST.get("detail_card_size")) or AssetDetailField.CARD_THIRD
        if detail_card_size not in valid_card_sizes:
            detail_card_size = AssetDetailField.CARD_THIRD
        AssetCategoryField.objects.create(
            category=category,
            code=_unique_asset_category_field_code(label, request.POST.get("code")),
            label=label[:120],
            field_type=field_type,
            detail_section=detail_section,
            detail_value_format=detail_value_format,
            detail_card_size=detail_card_size,
            placeholder=_clean_string(request.POST.get("placeholder"))[:160],
            help_text=_clean_string(request.POST.get("help_text"))[:255],
            sort_order=_as_int(request.POST.get("sort_order"), default=100),
            is_required=bool(request.POST.get("is_required")),
            show_in_form=bool(request.POST.get("show_in_form", "1")),
            show_in_detail=bool(request.POST.get("show_in_detail", "1")),
            show_if_empty=bool(request.POST.get("show_if_empty")),
            is_active=bool(request.POST.get("is_active", "1")),
        )
        return True, f"Campo categoria \"{label}\" creato."

    if action == "update_asset_category_field":
        field_id = _as_int(request.POST.get("category_field_id"), default=0)
        field = AssetCategoryField.objects.select_related("category").filter(pk=field_id).first()
        if not field:
            return False, "Campo categoria non trovato."
        category_id = _as_int(request.POST.get("category_id"), default=field.category_id)
        category = AssetCategory.objects.filter(pk=category_id).first()
        if not category:
            return False, "Categoria asset non valida."
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Il nome campo categoria e obbligatorio."
        field_type = _clean_string(request.POST.get("field_type")) or field.field_type
        if field_type not in valid_field_types:
            field_type = field.field_type
        detail_section = _clean_string(request.POST.get("detail_section")) or field.detail_section
        if detail_section not in valid_sections:
            detail_section = field.detail_section
        detail_value_format = _clean_string(request.POST.get("detail_value_format")) or field.detail_value_format
        if detail_value_format not in valid_formats:
            detail_value_format = field.detail_value_format
        detail_card_size = _clean_string(request.POST.get("detail_card_size")) or field.detail_card_size
        if detail_card_size not in valid_card_sizes:
            detail_card_size = field.detail_card_size
        field.category = category
        field.label = label[:120]
        field.field_type = field_type
        field.detail_section = detail_section
        field.detail_value_format = detail_value_format
        field.detail_card_size = detail_card_size
        field.placeholder = _clean_string(request.POST.get("placeholder"))[:160]
        field.help_text = _clean_string(request.POST.get("help_text"))[:255]
        field.sort_order = _as_int(request.POST.get("sort_order"), default=field.sort_order)
        field.is_required = bool(request.POST.get("is_required"))
        field.show_in_form = bool(request.POST.get("show_in_form"))
        field.show_in_detail = bool(request.POST.get("show_in_detail"))
        field.show_if_empty = bool(request.POST.get("show_if_empty"))
        field.is_active = bool(request.POST.get("is_active"))
        field.save(
            update_fields=[
                "category",
                "label",
                "field_type",
                "detail_section",
                "detail_value_format",
                "detail_card_size",
                "placeholder",
                "help_text",
                "sort_order",
                "is_required",
                "show_in_form",
                "show_in_detail",
                "show_if_empty",
                "is_active",
                "updated_at",
            ]
        )
        return True, f"Campo categoria \"{field.label}\" aggiornato."

    if action == "delete_asset_category_field":
        field_id = _as_int(request.POST.get("category_field_id"), default=0)
        field = AssetCategoryField.objects.filter(pk=field_id).first()
        if not field:
            return False, "Campo categoria non trovato."
        label = field.label
        code = field.code
        field.delete()
        touched = _update_asset_category_values_after_delete(code)
        return True, f"Campo categoria \"{label}\" eliminato ({touched} asset ripuliti)."

    return False, "Azione categoria asset non valida."


def _query_url(request: HttpRequest, **overrides) -> str:
    params = request.GET.copy()
    for key, value in overrides.items():
        if value is None:
            params.pop(key, None)
            continue
        params[key] = str(value)
    query = params.urlencode()
    return f"?{query}" if query else ""


def _asset_list_context_definitions() -> list[dict[str, object]]:
    return [
        {
            "key": AssetListLayout.CONTEXT_ALL,
            "label": "Inventario completo",
            "asset_type": "",
            "sort_order": 100,
        },
        {
            "key": AssetListLayout.CONTEXT_DEVICES,
            "label": "Dispositivi",
            "asset_type": Asset.TYPE_HW,
            "sort_order": 110,
        },
        {
            "key": AssetListLayout.CONTEXT_SERVERS,
            "label": "Server",
            "asset_type": Asset.TYPE_SERVER,
            "sort_order": 120,
        },
        {
            "key": AssetListLayout.CONTEXT_WORKSTATIONS,
            "label": "Postazioni di lavoro",
            "asset_type": Asset.TYPE_PC,
            "sort_order": 130,
        },
        {
            "key": AssetListLayout.CONTEXT_NETWORK,
            "label": "Rete",
            "asset_type": Asset.TYPE_FIREWALL,
            "sort_order": 140,
        },
        {
            "key": AssetListLayout.CONTEXT_VIRTUAL_MACHINES,
            "label": "Macchine virtuali",
            "asset_type": Asset.TYPE_VM,
            "sort_order": 150,
        },
        {
            "key": AssetListLayout.CONTEXT_CCTV,
            "label": "Videosorveglianza",
            "asset_type": Asset.TYPE_CCTV,
            "sort_order": 160,
        },
    ]


def _asset_list_context_definition_map() -> dict[str, dict[str, object]]:
    return {
        str(row["key"]): row
        for row in _asset_list_context_definitions()
    }


def _asset_list_context(asset_type: str) -> tuple[str, str]:
    normalized = _clean_string(asset_type).upper()
    if normalized in {Asset.TYPE_PC, Asset.TYPE_NOTEBOOK}:
        return AssetListLayout.CONTEXT_WORKSTATIONS, "Postazioni di lavoro"
    if normalized == Asset.TYPE_SERVER:
        return AssetListLayout.CONTEXT_SERVERS, "Server"
    if normalized == Asset.TYPE_FIREWALL:
        return AssetListLayout.CONTEXT_NETWORK, "Rete"
    if normalized == Asset.TYPE_HW:
        return AssetListLayout.CONTEXT_DEVICES, "Dispositivi"
    if normalized == Asset.TYPE_VM:
        return AssetListLayout.CONTEXT_VIRTUAL_MACHINES, "Macchine virtuali"
    if normalized == Asset.TYPE_CCTV:
        return AssetListLayout.CONTEXT_CCTV, "Videosorveglianza"
    return AssetListLayout.CONTEXT_ALL, "Inventario completo"


def _asset_list_default_columns(asset_type: str) -> list[str]:
    normalized = _clean_string(asset_type).upper()
    shared = ["name", "status", "category"]
    if normalized == Asset.TYPE_FIREWALL:
        return [*shared, "reparto", "serial_number", "manufacturer", "model", "vlan", "ip", "last_seen"]
    if normalized == Asset.TYPE_SERVER:
        return [*shared, "reparto", "serial_number", "manufacturer", "model", "ip", "assigned", "last_seen"]
    if normalized in {Asset.TYPE_PC, Asset.TYPE_NOTEBOOK}:
        return [*shared, "assigned", "reparto", "serial_number", "manufacturer", "model", "ip", "last_seen"]
    if normalized == Asset.TYPE_HW:
        return [*shared, "assigned", "reparto", "serial_number", "manufacturer", "model", "assignment_location", "last_seen"]
    return [*shared, "assigned", "last_seen", "reparto", "serial_number", "manufacturer", "model", "assignment_location"]


def _default_asset_list_layout_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for definition in _asset_list_context_definitions():
        asset_type = _clean_string(definition.get("asset_type"))
        rows.append(
            {
                "context_key": str(definition["key"]),
                "sort_order": int(definition["sort_order"]),
                "visible_columns": _asset_list_default_columns(asset_type),
                "is_customized": False,
            }
        )
    return rows


def _default_asset_list_layout_instances() -> list[AssetListLayout]:
    return [
        AssetListLayout(
            context_key=str(item["context_key"]),
            sort_order=int(item["sort_order"]),
            visible_columns=list(item["visible_columns"]),
            is_customized=bool(item["is_customized"]),
        )
        for item in _default_asset_list_layout_rows()
    ]


def _ensure_default_asset_list_layouts() -> list[AssetListLayout]:
    defaults = _default_asset_list_layout_rows()
    try:
        existing = {
            row.context_key: row
            for row in AssetListLayout.objects.all()
        }
        for item in defaults:
            context_key = str(item["context_key"])
            if context_key in existing:
                row = existing[context_key]
                if not isinstance(row.visible_columns, list) or not row.visible_columns:
                    row.visible_columns = list(item["visible_columns"])
                    row.save(update_fields=["visible_columns", "updated_at"])
                continue
            existing[context_key] = AssetListLayout.objects.create(
                context_key=context_key,
                sort_order=int(item["sort_order"]),
                visible_columns=list(item["visible_columns"]),
                is_customized=bool(item["is_customized"]),
            )
        return list(AssetListLayout.objects.order_by("sort_order", "id"))
    except DatabaseError:
        return _default_asset_list_layout_instances()


def _asset_list_valid_column_keys(custom_fields: list[AssetCustomField]) -> set[str]:
    keys = {key for key, _ in ASSET_LIST_BASE_COLUMN_CHOICES}
    keys.update(f"custom_{field.code}" for field in custom_fields)
    return keys


def _sanitize_asset_list_visible_columns(columns: object, valid_keys: set[str], fallback: list[str] | None = None) -> list[str]:
    cleaned: list[str] = []
    for value in columns if isinstance(columns, list) else []:
        key = _clean_string(value)
        if key and key in valid_keys and key not in cleaned:
            cleaned.append(key)
    if cleaned:
        return cleaned
    return list(fallback or [])


def _asset_list_layout_revision(layout: AssetListLayout | None) -> str:
    if layout is None or layout.updated_at is None:
        return "default"
    return layout.updated_at.strftime("%Y%m%d%H%M%S")


def _asset_list_layout_manage_url(request: HttpRequest, context_key: str) -> str:
    if not _can_manage_asset_list_layout(request):
        return ""
    try:
        return f"{reverse('assets:asset_list_layout_admin')}?context={quote(context_key)}"
    except NoReverseMatch:
        return ""


def _asset_table_layout_storage_user_id(request: HttpRequest) -> int | None:
    if not getattr(request.user, "is_authenticated", False):
        return None
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    try:
        if legacy_user is not None and getattr(legacy_user, "id", None) is not None:
            return int(legacy_user.id)
        user_id = getattr(request.user, "pk", None)
        return -int(user_id) if user_id is not None else None
    except (TypeError, ValueError):
        return None


def _load_user_dashboard_layout_payload(storage_user_id: int | None) -> dict[str, object]:
    if storage_user_id is None:
        return {}
    try:
        row = UserDashboardLayout.objects.filter(legacy_user_id=storage_user_id).first()
    except DatabaseError:
        return {}
    payload = getattr(row, "layout", {})
    return payload if isinstance(payload, dict) else {}


def _sanitize_asset_table_column_order(value: object, valid_keys: set[str]) -> list[str]:
    cleaned: list[str] = []
    for item in value if isinstance(value, list) else []:
        key = _clean_string(item)
        if key and key in valid_keys and key not in cleaned:
            cleaned.append(key)
    return cleaned


def _sanitize_asset_table_column_widths(value: object, valid_keys: set[str]) -> dict[str, int]:
    cleaned: dict[str, int] = {}
    if not isinstance(value, dict):
        return cleaned
    for raw_key, raw_width in value.items():
        key = _clean_string(raw_key)
        if not key or key not in valid_keys or key in cleaned:
            continue
        try:
            width = int(raw_width)
        except (TypeError, ValueError):
            continue
        if 90 <= width <= 1600:
            cleaned[key] = width
    return cleaned


def _sanitize_asset_table_layout(value: object, valid_keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {
        "visible_columns": _sanitize_asset_list_visible_columns(value.get("visible_columns"), valid_keys, fallback=[]),
        "column_order": _sanitize_asset_table_column_order(value.get("column_order"), valid_keys),
        "column_widths": _sanitize_asset_table_column_widths(value.get("column_widths"), valid_keys),
    }


def _load_user_asset_table_layout(request: HttpRequest, context_key: str, valid_keys: set[str]) -> dict[str, object]:
    payload = _load_user_dashboard_layout_payload(_asset_table_layout_storage_user_id(request))
    contexts = payload.get("assets_table")
    if not isinstance(contexts, dict):
        return {}
    return _sanitize_asset_table_layout(contexts.get(context_key), valid_keys)


def _persist_user_asset_table_layout(
    request: HttpRequest,
    context_key: str,
    payload: dict[str, object],
    valid_keys: set[str],
) -> dict[str, object] | None:
    storage_user_id = _asset_table_layout_storage_user_id(request)
    if storage_user_id is None:
        return None
    sanitized = _sanitize_asset_table_layout(payload, valid_keys)
    try:
        current = _load_user_dashboard_layout_payload(storage_user_id)
        updated = dict(current)
        contexts = updated.get("assets_table")
        if not isinstance(contexts, dict):
            contexts = {}

        has_payload = bool(
            sanitized.get("visible_columns") or sanitized.get("column_order") or sanitized.get("column_widths")
        )
        if has_payload:
            contexts[context_key] = sanitized
        else:
            contexts.pop(context_key, None)

        if contexts:
            updated["assets_table"] = contexts
        else:
            updated.pop("assets_table", None)

        if updated:
            UserDashboardLayout.objects.update_or_create(
                legacy_user_id=storage_user_id,
                defaults={"layout": updated},
            )
        else:
            UserDashboardLayout.objects.filter(legacy_user_id=storage_user_id).delete()
        return sanitized
    except DatabaseError:
        return None


def _handle_asset_table_layout_request(request: HttpRequest, payload: dict[str, object]) -> JsonResponse:
    context_key = _clean_string(payload.get("context_key"))
    if context_key not in _asset_list_context_definition_map():
        return JsonResponse({"ok": False, "error": "Contesto layout non valido."}, status=400)

    custom_fields = list(AssetCustomField.objects.filter(is_active=True).order_by("sort_order", "id"))
    valid_keys = _asset_list_valid_column_keys(custom_fields)
    saved_layout = _persist_user_asset_table_layout(
        request,
        context_key,
        {
            "visible_columns": payload.get("visible_columns"),
            "column_order": payload.get("column_order"),
            "column_widths": payload.get("column_widths"),
        },
        valid_keys,
    )
    if saved_layout is None:
        return JsonResponse({"ok": False, "error": "Impossibile salvare le preferenze tabella."}, status=400)
    return JsonResponse({"ok": True, "layout": saved_layout})


def _asset_list_preview_url(context_key: str, rows: int = 25) -> str:
    definition = _asset_list_context_definition_map().get(context_key, {})
    base_url = reverse("assets:asset_list")
    asset_type = _clean_string(definition.get("asset_type"))
    if asset_type:
        return f"{base_url}?asset_type={quote(asset_type)}&rows={rows}"
    return f"{base_url}?rows={rows}"


def _asset_extra_has_custom_value(extra: object, field: AssetCustomField) -> bool:
    if not isinstance(extra, dict) or field is None:
        return False
    sentinel = object()
    value = extra.get(field.code, sentinel)
    if value is sentinel:
        value = extra.get(field.label, sentinel)
    if value is sentinel:
        return False
    if value in ("", None, [], {}):
        return False
    return True


def _asset_list_relevant_custom_columns(assets_qs, custom_fields: list[AssetCustomField], sample_size: int = 250) -> list[str]:
    if not custom_fields:
        return []
    relevant_codes: list[str] = []
    remaining = {field.code: field for field in custom_fields}
    for asset in assets_qs[:sample_size]:
        extra = asset.extra_columns if isinstance(asset.extra_columns, dict) else {}
        for code, field in list(remaining.items()):
            if _asset_extra_has_custom_value(extra, field):
                relevant_codes.append(code)
                remaining.pop(code, None)
        if not remaining:
            break
    return relevant_codes


def _asset_endpoint_column_summary(asset: Asset) -> dict[str, str]:
    endpoints = list(asset.endpoints.all())

    def _join_unique(values: list[str]) -> str:
        seen: list[str] = []
        for value in values:
            normalized = _clean_string(value)
            if normalized and normalized not in seen:
                seen.append(normalized)
        return ", ".join(seen) if seen else "-"

    vlan_values = []
    ip_values = []
    for endpoint in endpoints:
        if endpoint.vlan is not None:
            vlan_values.append(str(endpoint.vlan))
        if endpoint.ip:
            ip_values.append(str(endpoint.ip))
    return {
        "vlan": _join_unique(vlan_values),
        "ip": _join_unique(ip_values),
    }


def _handle_custom_field_request(request: HttpRequest) -> tuple[bool, str]:
    action = _clean_string(request.POST.get("action"))
    allowed_types = {choice[0] for choice in AssetCustomField.TYPE_CHOICES}

    if action == "create_custom_field":
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Inserisci il nome del campo."
        field_type = _clean_string(request.POST.get("field_type")) or AssetCustomField.TYPE_TEXT
        if field_type not in allowed_types:
            field_type = AssetCustomField.TYPE_TEXT
        sort_order = _as_int(request.POST.get("sort_order"), default=100)
        code = _unique_custom_field_code(label, requested_code=request.POST.get("code"))
        is_active = bool(request.POST.get("is_active"))
        AssetCustomField.objects.create(
            code=code,
            label=label[:120],
            field_type=field_type,
            sort_order=sort_order,
            is_active=is_active,
        )
        return True, f"Campo \"{label}\" creato."

    if action == "update_custom_field":
        field_id = _as_int(request.POST.get("field_id"), default=0)
        field = AssetCustomField.objects.filter(pk=field_id).first()
        if not field:
            return False, "Campo non trovato."
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Il nome campo non puo essere vuoto."
        field_type = _clean_string(request.POST.get("field_type")) or field.field_type
        if field_type not in allowed_types:
            field_type = field.field_type
        field.label = label[:120]
        field.field_type = field_type
        field.sort_order = _as_int(request.POST.get("sort_order"), default=field.sort_order)
        field.is_active = bool(request.POST.get("is_active"))
        field.save(update_fields=["label", "field_type", "sort_order", "is_active", "updated_at"])
        return True, f"Campo \"{field.label}\" aggiornato."

    if action == "delete_custom_field":
        field_id = _as_int(request.POST.get("field_id"), default=0)
        field = AssetCustomField.objects.filter(pk=field_id).first()
        if not field:
            return False, "Campo non trovato."
        field_code = field.code
        field_label = field.label
        field.delete()
        touched = _update_custom_field_values_after_delete(field_code)
        return True, f"Campo \"{field_label}\" eliminato ({touched} asset aggiornati)."

    return False, "Azione non valida."


def _handle_excel_import_request(request: HttpRequest) -> tuple[bool, str]:
    uploaded_file = request.FILES.get("excel_file")
    if not uploaded_file:
        return False, "Seleziona un file Excel prima di avviare l'import."

    file_name = (uploaded_file.name or "").lower()
    if not file_name.endswith((".xlsx", ".xlsm")):
        return False, "Formato non supportato. Usa file .xlsx oppure .xlsm."

    sheets_csv = _clean_string(request.POST.get("import_sheets")) or DEFAULT_IMPORT_SHEETS
    dry_run = bool(request.POST.get("dry_run"))
    include_optional = bool(request.POST.get("include_optional"))
    all_sheets = bool(request.POST.get("all_sheets"))
    update_existing = bool(request.POST.get("update_existing", "1") == "1")

    tmp_path = ""
    output = io.StringIO()
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as temp_file:
            for chunk in uploaded_file.chunks():
                temp_file.write(chunk)
            tmp_path = temp_file.name

        call_command(
            "import_assets_excel",
            file=tmp_path,
            sheets=sheets_csv,
            dry_run=dry_run,
            include_optional=include_optional,
            all_sheets=all_sheets,
            update=update_existing,
            stdout=output,
            stderr=output,
        )
        command_output = output.getvalue().strip()
        mode = "DRY-RUN" if dry_run else "IMPORT REALE"
        if command_output:
            return True, f"{mode} completato. {command_output.splitlines()[-1]}"
        return True, f"{mode} completato con successo."
    except Exception as exc:
        command_output = output.getvalue().strip()
        if command_output:
            return False, f"{exc} | {command_output}"
        return False, str(exc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _build_assets_admin_snapshot() -> dict:
    return {
        "generated_at": timezone.now().isoformat(),
        "asset_categories": list(
            AssetCategory.objects.order_by("sort_order", "label", "id").values(
                "code",
                "label",
                "base_asset_type",
                "description",
                "detail_specs_title",
                "detail_profile_title",
                "detail_assignment_title",
                "detail_timeline_title",
                "detail_maintenance_title",
                "sort_order",
                "is_active",
            )
        ),
        "asset_category_fields": list(
            AssetCategoryField.objects.select_related("category")
            .order_by("category__sort_order", "category__label", "sort_order", "label", "id")
            .values(
                "code",
                "category__code",
                "category__label",
                "label",
                "field_type",
                "detail_section",
                "detail_value_format",
                "detail_card_size",
                "placeholder",
                "help_text",
                "sort_order",
                "is_required",
                "show_in_form",
                "show_in_detail",
                "show_if_empty",
                "is_active",
            )
        ),
        "custom_fields": list(
            AssetCustomField.objects.order_by("sort_order", "id").values(
                "code",
                "label",
                "field_type",
                "sort_order",
                "is_active",
            )
        ),
        "list_options": list(
            AssetListOption.objects.order_by("field_key", "sort_order", "value", "id").values(
                "field_key",
                "value",
                "sort_order",
                "is_active",
            )
        ),
        "action_buttons": list(
            AssetActionButton.objects.order_by("zone", "sort_order", "label", "id").values(
                "code",
                "label",
                "zone",
                "action_type",
                "target",
                "style",
                "sort_order",
                "open_in_new_tab",
                "is_active",
            )
        ),
        "detail_fields": list(
            AssetDetailField.objects.order_by("section", "asset_scope", "sort_order", "label", "id").values(
                "code",
                "label",
                "section",
                "asset_scope",
                "source_ref",
                "value_format",
                "card_size",
                "sort_order",
                "show_if_empty",
                "is_active",
            )
        ),
        "detail_section_layouts": list(
            AssetDetailSectionLayout.objects.order_by("sort_order", "id").values(
                "code",
                "grid_size",
                "sort_order",
                "is_visible",
            )
        ),
        "sidebar_buttons": list(
            AssetSidebarButton.objects.order_by("section", "sort_order", "label", "id").values(
                "code",
                "label",
                "section",
                "parent_id",
                "parent__code",
                "target_url",
                "active_match",
                "is_subitem",
                "sort_order",
                "is_visible",
            )
        ),
    }


@login_required
def asset_list(request: HttpRequest) -> HttpResponse:
    can_manage_custom_fields = _is_assets_admin(request)

    if request.method == "POST":
        json_payload: dict[str, object] = {}
        if "application/json" in str(getattr(request, "content_type", "") or "").lower():
            try:
                decoded = json.loads((request.body or b"{}").decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                decoded = {}
            if isinstance(decoded, dict):
                json_payload = decoded
        action = _clean_string(json_payload.get("action")) if json_payload else _clean_string(request.POST.get("action"))
        if action == "save_asset_table_layout":
            return _handle_asset_table_layout_request(request, json_payload)
        if action == "import_excel":
            ok, text = _handle_excel_import_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, f"Import Excel fallito: {text}")
            return redirect("assets:asset_list")
        if action in {"create_custom_field", "update_custom_field", "delete_custom_field"}:
            if not can_manage_custom_fields:
                messages.error(request, "Solo admin puo modificare i campi personalizzati.")
                return redirect("assets:asset_list")
            ok, text = _handle_custom_field_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return redirect("assets:asset_list")
        if action in LIST_ACTIONS:
            if not can_manage_custom_fields:
                messages.error(request, "Solo admin puo modificare le liste.")
                return redirect("assets:asset_list")
            ok, text = _handle_list_option_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return redirect("assets:asset_list")
        if action in BUTTON_ACTIONS:
            if not can_manage_custom_fields:
                messages.error(request, "Solo admin puo modificare i pulsanti.")
                return redirect("assets:asset_list")
            ok, text = _handle_action_button_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return redirect("assets:asset_list")
        if action in DETAIL_FIELD_ACTIONS:
            if not can_manage_custom_fields:
                messages.error(request, "Solo admin puo modificare il dettaglio asset.")
                return redirect("assets:asset_list")
            ok, text = _handle_detail_field_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return redirect("assets:asset_list")
        if action in CATEGORY_ACTIONS:
            if not can_manage_custom_fields:
                messages.error(request, "Solo admin puo modificare categorie e campi asset.")
                return redirect("assets:asset_list")
            ok, text = _handle_asset_category_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return redirect("assets:asset_list")
        if action in SIDEBAR_ACTIONS:
            if not can_manage_custom_fields:
                messages.error(request, "Solo admin puo modificare il menu sidebar.")
                return redirect("assets:asset_list")
            ok, text = _handle_sidebar_button_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return redirect("assets:asset_list")
        if action in HEADER_TOOL_ACTIONS:
            if not can_manage_custom_fields:
                messages.error(request, "Solo admin puo modificare gli strumenti header.")
                return redirect("assets:asset_list")
            ok, text = _handle_header_tool_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return redirect("assets:asset_list")
        if action == "export_admin_snapshot":
            if not can_manage_custom_fields:
                messages.error(request, "Solo admin puo esportare la configurazione.")
                return redirect("assets:asset_list")
            payload = _build_assets_admin_snapshot()
            content = json.dumps(payload, ensure_ascii=False, indent=2)
            response = HttpResponse(content, content_type="application/json; charset=utf-8")
            response["Content-Disposition"] = (
                f'attachment; filename=\"assets_admin_snapshot_{timezone.now().strftime("%Y%m%d_%H%M%S")}.json\"'
            )
            return response

    form = AssetFilterForm(request.GET or None)
    assets = Asset.objects.select_related("asset_category").all().prefetch_related("endpoints")

    if form.is_valid():
        q = _clean_string(form.cleaned_data.get("q"))
        asset_type = _clean_string(form.cleaned_data.get("asset_type"))
        reparto = _clean_string(form.cleaned_data.get("reparto"))
        vlan = form.cleaned_data.get("vlan")
        ip = _clean_string(form.cleaned_data.get("ip"))

        if q:
            assets = assets.filter(
                Q(asset_tag__icontains=q)
                | Q(name__icontains=q)
                | Q(serial_number__icontains=q)
                | Q(manufacturer__icontains=q)
                | Q(model__icontains=q)
                | Q(endpoints__endpoint_name__icontains=q)
                | Q(endpoints__ip__icontains=q)
            )
        if asset_type:
            assets = assets.filter(asset_type=asset_type)
        if reparto:
            assets = assets.filter(reparto__icontains=reparto)
        if vlan is not None:
            assets = assets.filter(endpoints__vlan=vlan)
        if ip:
            assets = assets.filter(endpoints__ip__icontains=ip)

    assets_filtered = assets.distinct().order_by("name", "asset_tag")

    allowed_rows = [10, 25, 50, 100]
    rows = _as_int(request.GET.get("rows"), default=25)
    if rows not in allowed_rows:
        rows = 25
    paginator = Paginator(assets_filtered, rows)
    page_number = _as_int(request.GET.get("page"), default=1)
    page_obj = paginator.get_page(page_number)
    assets = page_obj.object_list
    visible_count = assets_filtered.count()
    page_start = ((page_obj.number - 1) * rows + 1) if visible_count else 0
    page_end = (page_start + len(assets) - 1) if visible_count else 0

    rows_options = [
        {
            "value": value,
            "active": value == rows,
            "url": _query_url(request, rows=value, page=1),
        }
        for value in allowed_rows
    ]

    page_links = []
    if paginator.num_pages > 0:
        start_page = max(1, page_obj.number - 2)
        end_page = min(paginator.num_pages, page_obj.number + 2)
        for number in range(start_page, end_page + 1):
            page_links.append(
                {
                    "number": number,
                    "active": number == page_obj.number,
                    "url": _query_url(request, page=number, rows=rows),
                }
            )

    prev_page_url = _query_url(request, page=page_obj.previous_page_number(), rows=rows) if page_obj.has_previous() else ""
    next_page_url = _query_url(request, page=page_obj.next_page_number(), rows=rows) if page_obj.has_next() else ""
    current_asset_type = _clean_string(request.GET.get("asset_type"))
    asset_list_context_key, asset_list_context_label = _asset_list_context(current_asset_type)
    custom_fields = list(AssetCustomField.objects.filter(is_active=True).order_by("sort_order", "id"))
    all_custom_fields = list(AssetCustomField.objects.order_by("sort_order", "id"))
    list_layouts_by_context = {
        row.context_key: row
        for row in _ensure_default_asset_list_layouts()
    }
    current_list_layout = list_layouts_by_context.get(asset_list_context_key)
    valid_list_column_keys = _asset_list_valid_column_keys(custom_fields)
    user_asset_table_layout = _load_user_asset_table_layout(request, asset_list_context_key, valid_list_column_keys)
    relevant_custom_field_codes = _asset_list_relevant_custom_columns(assets_filtered, custom_fields)
    suggested_visible_columns = _asset_list_default_columns(current_asset_type)
    suggested_visible_columns.extend(f"custom_{code}" for code in relevant_custom_field_codes)
    suggested_visible_columns = list(dict.fromkeys(suggested_visible_columns))
    if current_list_layout and current_list_layout.is_customized:
        asset_list_default_visible_columns = _sanitize_asset_list_visible_columns(
            current_list_layout.visible_columns,
            valid_list_column_keys,
            fallback=suggested_visible_columns,
        )
    else:
        asset_list_default_visible_columns = _sanitize_asset_list_visible_columns(
            suggested_visible_columns,
            valid_list_column_keys,
            fallback=suggested_visible_columns,
        )
    if user_asset_table_layout.get("visible_columns"):
        asset_list_default_visible_columns = _sanitize_asset_list_visible_columns(
            user_asset_table_layout.get("visible_columns"),
            valid_list_column_keys,
            fallback=asset_list_default_visible_columns,
        )
    asset_list_layout_revision = _asset_list_layout_revision(current_list_layout)
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
    total_assets = Asset.objects.count()
    in_use_count = Asset.objects.filter(status=Asset.STATUS_IN_USE).count()
    in_repair_count = Asset.objects.filter(status=Asset.STATUS_IN_REPAIR).count()
    open_wo_count = WorkOrder.objects.filter(status=WorkOrder.STATUS_OPEN).count()
    assigned_count = Asset.objects.exclude(assignment_to__isnull=True).exclude(assignment_to="").count()
    maintenance_due_count = WorkOrder.objects.filter(
        status=WorkOrder.STATUS_OPEN,
        opened_at__lt=timezone.now() - timedelta(days=21),
    ).count()
    work_machine_total = Asset.objects.filter(asset_type=Asset.TYPE_WORK_MACHINE).count()

    health_percent = 0.0
    in_use_percent = 0.0
    if total_assets > 0:
        health_percent = max(0.0, round((1 - (in_repair_count / total_assets)) * 100, 1))
        in_use_percent = max(0.0, min(100.0, round((in_use_count / total_assets) * 100, 1)))
    risk_count = in_repair_count + open_wo_count

    phase_1_count = Asset.objects.filter(
        asset_type__in=[
            Asset.TYPE_PC,
            Asset.TYPE_NOTEBOOK,
            Asset.TYPE_STAMPANTE,
            Asset.TYPE_HW,
        ]
    ).count()
    phase_2_count = Asset.objects.filter(
        asset_type__in=[
            Asset.TYPE_SERVER,
            Asset.TYPE_VM,
            Asset.TYPE_FIREWALL,
            Asset.TYPE_CCTV,
        ]
    ).count()
    phase_3_count = Asset.objects.filter(
        asset_type__in=[Asset.TYPE_CNC, Asset.TYPE_WORK_MACHINE, Asset.TYPE_OTHER],
    ).count()
    lifecycle_total = phase_1_count + phase_2_count + phase_3_count
    if lifecycle_total <= 0:
        lifecycle_total = 1
    lifecycle_phase_1 = int(round((phase_1_count / lifecycle_total) * 100))
    lifecycle_phase_2 = int(round((phase_2_count / lifecycle_total) * 100))
    lifecycle_phase_3 = int(round((phase_3_count / lifecycle_total) * 100))

    for asset in assets:
        endpoint_summary = _asset_endpoint_column_summary(asset)
        asset.endpoint_vlan_display = endpoint_summary["vlan"]
        asset.endpoint_ip_display = endpoint_summary["ip"]

    recent_alerts: list[dict[str, str]] = []
    open_wo_alerts = _dashboard_open_workorder_alert_rows(limit=4)
    for workorder in open_wo_alerts:
        is_critical = workorder.opened_at < timezone.now() - timedelta(days=14)
        recent_alerts.append(
            {
                "title": workorder.title or f"Intervento su {workorder.asset.asset_tag}",
                "message": _coalesce_str(workorder.description, f"Asset {workorder.asset.asset_tag} richiede attenzione."),
                "time": workorder.opened_at.strftime("%d/%m/%Y %H:%M"),
                "level": "critical" if is_critical else "warning",
            }
        )
    if len(recent_alerts) < 5:
        repair_assets = list(
            Asset.objects.filter(status=Asset.STATUS_IN_REPAIR)
            .order_by("-updated_at")
            .values("asset_tag", "name", "updated_at")[: (5 - len(recent_alerts))]
        )
        for row in repair_assets:
            recent_alerts.append(
                {
                    "title": f"Asset in riparazione: {row.get('asset_tag')}",
                    "message": _coalesce_str(row.get("name"), "Asset segnalato in riparazione."),
                    "time": row["updated_at"].strftime("%d/%m/%Y %H:%M") if row.get("updated_at") else "-",
                    "level": "warning",
                }
            )
    if not recent_alerts:
        recent_alerts.append(
            {
                "title": "Nessun alert critico",
                "message": "La situazione asset e stabile.",
                "time": timezone.now().strftime("%d/%m/%Y %H:%M"),
                "level": "ok",
            }
        )

    return render(
        request,
        "assets/pages/asset_list.html",
        {
            "page_title": "Inventario asset",
            "filters_form": form,
            "assets": assets,
            "total_assets": total_assets,
            "in_use_count": in_use_count,
            "in_repair_count": in_repair_count,
            "open_wo_count": open_wo_count,
            "visible_count": visible_count,
            "rows": rows,
            "rows_options": rows_options,
            "page_obj": page_obj,
            "page_links": page_links,
            "prev_page_url": prev_page_url,
            "next_page_url": next_page_url,
            "page_start": page_start,
            "page_end": page_end,
            "default_import_sheets": DEFAULT_IMPORT_SHEETS,
            "custom_fields": custom_fields,
            "all_custom_fields": all_custom_fields,
            "asset_list_context_key": asset_list_context_key,
            "asset_list_context_label": asset_list_context_label,
            "asset_list_default_visible_columns": asset_list_default_visible_columns,
            "asset_list_default_visible_columns_json": json.dumps(asset_list_default_visible_columns),
            "asset_table_saved_layout_json": json.dumps(user_asset_table_layout),
            "asset_table_layout_can_persist": bool(_asset_table_layout_storage_user_id(request) is not None),
            "asset_list_layout_revision": asset_list_layout_revision,
            "asset_list_layout_manage_url": _asset_list_layout_manage_url(request, asset_list_context_key),
            "asset_list_layout_is_customized": bool(current_list_layout and current_list_layout.is_customized),
            "custom_type_choices": _ui_choices(AssetCustomField.TYPE_CHOICES),
            "list_options": list_options,
            "list_option_choices": _ui_choices(AssetListOption.FIELD_CHOICES),
            "action_buttons": action_buttons,
            "button_zone_choices": _ui_choices(AssetActionButton.ZONE_CHOICES),
            "button_action_choices": _ui_choices(AssetActionButton.ACTION_CHOICES),
            "button_style_choices": _ui_choices(AssetActionButton.STYLE_CHOICES),
            "detail_fields": detail_fields,
            "asset_categories": asset_categories,
            "asset_category_fields": asset_category_fields,
            "asset_category_type_choices": _ui_choices(Asset.TYPE_CHOICES),
            "asset_category_field_type_choices": _ui_choices(AssetCategoryField.TYPE_CHOICES),
            "detail_section_choices": _ui_choices(AssetDetailField.SECTION_CHOICES),
            "detail_scope_choices": _ui_choices(AssetDetailField.SCOPE_CHOICES),
            "detail_format_choices": _ui_choices(AssetDetailField.FORMAT_CHOICES),
            "detail_source_choices": _asset_detail_source_choices(),
            "sidebar_buttons": sidebar_buttons,
            "sidebar_parent_choices": sidebar_parent_choices,
            "sidebar_section_choices": _ui_choices(AssetSidebarButton.SECTION_CHOICES),
            "sidebar_target_suggestions": sidebar_target_suggestions,
            "sidebar_active_match_suggestions": sidebar_active_match_suggestions,
            "can_manage_custom_fields": can_manage_custom_fields,
            "can_gestione_admin": user_can_modulo_action(request, "assets", "admin_assets"),
            "header_tools": list(AssetHeaderTool.objects.order_by("sort_order", "code")),
            **_header_tool_visibility(can_manage_custom_fields),
            "admin_metrics": admin_metrics,
            "admin_checks": admin_checks,
            "table_colspan": 7 + len(custom_fields),
            "health_percent": health_percent,
            "in_use_percent": in_use_percent,
            "risk_count": risk_count,
            "maintenance_due_count": maintenance_due_count,
            "assigned_count": assigned_count,
            "work_machine_total": work_machine_total,
            "phase_1_count": phase_1_count,
            "phase_2_count": phase_2_count,
            "phase_3_count": phase_3_count,
            "lifecycle_phase_1": lifecycle_phase_1,
            "lifecycle_phase_2": lifecycle_phase_2,
            "lifecycle_phase_3": lifecycle_phase_3,
            "recent_alerts": recent_alerts,
            **_assets_shell_context(request, rows=rows),
        },
    )


@login_required
def asset_detail_layout_admin(request: HttpRequest) -> HttpResponse:
    if not _can_manage_asset_detail_layout(request):
        messages.error(request, "Non hai i permessi per configurare il layout del dettaglio asset.")
        return redirect("assets:asset_list")

    preview_asset_id = _as_int(request.POST.get("asset_id") if request.method == "POST" else request.GET.get("asset"), default=0)
    preview_asset = (
        Asset.objects.select_related("asset_category")
        .filter(pk=preview_asset_id)
        .first()
    )

    if request.method == "POST":
        action = _clean_string(request.POST.get("action"))
        if action in DETAIL_LAYOUT_ACTIONS:
            ok, text = _handle_detail_section_layout_request(request)
        elif action in DETAIL_FIELD_ACTIONS:
            ok, text = _handle_detail_field_request(request)
        elif action == "update_asset_category_field":
            ok, text = _handle_asset_category_request(request)
        else:
            ok, text = False, "Azione layout dettaglio non riconosciuta."
        if ok:
            messages.success(request, text)
        else:
            messages.error(request, text)
        redirect_url = reverse("assets:asset_detail_layout_admin")
        if preview_asset_id:
            redirect_url = f"{redirect_url}?asset={preview_asset_id}"
        return redirect(redirect_url)

    section_layouts = _ensure_default_asset_detail_section_layouts()
    detail_fields = list(AssetDetailField.objects.order_by("section", "asset_scope", "sort_order", "label", "id"))
    asset_categories = list(
        AssetCategory.objects.prefetch_related("category_fields").order_by("sort_order", "label", "id")
    )
    detail_source_help = [
        "asset:manufacturer",
        "asset:model",
        "asset:serial_number",
        "it:cpu",
        "work_machine:x_mm",
        "custom:centro_costo",
        "computed:travel_xyz",
    ]

    return render(
        request,
        "assets/pages/asset_detail_layout_admin.html",
        {
            "page_title": "Configura dettaglio asset",
            "section_layouts": section_layouts,
            "detail_fields": detail_fields,
            "asset_categories": asset_categories,
            "detail_section_choices": _ui_choices(AssetDetailField.SECTION_CHOICES),
            "detail_scope_choices": _ui_choices(AssetDetailField.SCOPE_CHOICES),
            "detail_format_choices": _ui_choices(AssetDetailField.FORMAT_CHOICES),
            "detail_card_size_choices": _ui_choices(AssetDetailField.CARD_SIZE_CHOICES),
            "detail_section_layout_choices": _ui_choices(AssetDetailSectionLayout.SECTION_CHOICES),
            "detail_source_help": detail_source_help,
            "preview_asset": preview_asset,
            "preview_asset_url": reverse("assets:asset_view", kwargs={"id": preview_asset.id}) if preview_asset else "",
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


def _build_asset_detail_section_cards(
    *,
    detail_specs_title: str,
    detail_timeline_title: str,
    detail_maintenance_title: str,
    detail_tickets_title: str,
    profile_card_title: str,
    detail_assignment_title: str,
    quick_action_buttons: list[dict],
    sharepoint_folder_url: str,
    sharepoint_folder_path: str,
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
            "render": bool(spec_pairs),
        },
        AssetDetailSectionLayout.SECTION_TIMELINE: {
            "code": AssetDetailSectionLayout.SECTION_TIMELINE,
            "title": detail_timeline_title,
            "render": True,
        },
        AssetDetailSectionLayout.SECTION_MAINTENANCE: {
            "code": AssetDetailSectionLayout.SECTION_MAINTENANCE,
            "title": detail_maintenance_title,
            "render": True,
        },
        AssetDetailSectionLayout.SECTION_TICKETS: {
            "code": AssetDetailSectionLayout.SECTION_TICKETS,
            "title": detail_tickets_title,
            "render": True,
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
            "render": True,
        },
        AssetDetailSectionLayout.SECTION_QR: {
            "code": AssetDetailSectionLayout.SECTION_QR,
            "title": "QR asset",
            "render": True,
        },
        AssetDetailSectionLayout.SECTION_SHAREPOINT: {
            "code": AssetDetailSectionLayout.SECTION_SHAREPOINT,
            "title": "Archivio SharePoint",
            "render": bool(sharepoint_folder_url or sharepoint_folder_path),
        },
        AssetDetailSectionLayout.SECTION_QUICK_ACTIONS: {
            "code": AssetDetailSectionLayout.SECTION_QUICK_ACTIONS,
            "title": "Azioni rapide",
            "render": bool(quick_action_buttons) and len(quick_action_buttons) <= 2,
        },
        AssetDetailSectionLayout.SECTION_ASSIGNMENT: {
            "code": AssetDetailSectionLayout.SECTION_ASSIGNMENT,
            "title": detail_assignment_title,
            "render": True,
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


@login_required
def asset_detail(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:asset_list")
    asset = get_object_or_404(
        Asset.objects.select_related("asset_category", "it_details", "work_machine").prefetch_related(
            "components",
            "administrative_deadlines",
            "administrative_deadlines__component",
            "endpoints",
            "workorders",
            "documents",
            "tickets",
            "periodic_verifications",
            "periodic_verifications__supplier",
            "software_licenses",
        ),
        pk=id,
    )
    recent_workorders = asset.workorders.select_related("asset").all()[:10]
    component_rows = list(asset.components.all())
    administrative_deadlines = list(
        asset.administrative_deadlines.all().order_by("due_date", "title", "id")
    )
    custom_fields = list(AssetCustomField.objects.filter(is_active=True).order_by("sort_order", "id"))
    custom_fields_by_code = {field.code: field for field in custom_fields}
    extra = asset.extra_columns if isinstance(asset.extra_columns, dict) else {}
    mapped_keys = {field.code for field in custom_fields} | {field.label for field in custom_fields}
    unmapped_extra = [(k, v) for k, v in extra.items() if k not in mapped_keys]

    now = timezone.now()
    today = timezone.localdate()
    age = max(0, int((now - asset.updated_at).total_seconds() // 60)) if asset.updated_at else 0
    if age < 1:
        sync_text = "Ultimo sync: adesso"
    elif age < 60:
        sync_text = f"Ultimo sync: {age} minuti fa"
    else:
        hours = age // 60
        sync_text = f"Ultimo sync: {hours} ore fa"

    it_details = getattr(asset, "it_details", None)
    work_machine = getattr(asset, "work_machine", None)
    travel_xyz = "N/D"
    machine_flags: list[str] = []
    if isinstance(work_machine, WorkMachine):
        travel_parts = [str(value) for value in [work_machine.x_mm, work_machine.y_mm, work_machine.z_mm] if value is not None]
        travel_xyz = " x ".join(travel_parts) + " mm" if travel_parts else "N/D"
        if work_machine.tcr_enabled:
            machine_flags.append("TCR")
        if work_machine.cnc_controlled:
            machine_flags.append("CNC")
        if work_machine.five_axes:
            machine_flags.append("5 assi")

    if isinstance(work_machine, WorkMachine):
        default_detail_metrics = [
            {"label": "Corse XYZ", "value": travel_xyz, "size": AssetDetailField.CARD_THIRD},
            {"label": "Anno macchina", "value": _coalesce_str(work_machine.year, "N/D"), "size": AssetDetailField.CARD_THIRD},
            {
                "label": "Configurazione",
                "value": ", ".join(machine_flags) if machine_flags else "Standard",
                "size": AssetDetailField.CARD_THIRD,
            },
        ]
        default_spec_pairs = [
            ("Produttore", _coalesce_str(asset.manufacturer, "N/D")),
            ("Modello", _coalesce_str(asset.model, asset.name, "N/D")),
            ("Numero seriale", _coalesce_str(asset.serial_number, "N/D")),
            ("Reparto", _coalesce_str(asset.reparto, "N/D")),
            ("Corsa X", _format_asset_detail_value(work_machine.x_mm, AssetDetailField.FORMAT_MM)),
            ("Corsa Y", _format_asset_detail_value(work_machine.y_mm, AssetDetailField.FORMAT_MM)),
            ("Corsa Z", _format_asset_detail_value(work_machine.z_mm, AssetDetailField.FORMAT_MM)),
            ("Diametro", _format_asset_detail_value(work_machine.diameter_mm, AssetDetailField.FORMAT_MM)),
            ("Mandrino", _format_asset_detail_value(work_machine.spindle_mm, AssetDetailField.FORMAT_MM)),
            ("Anno", _coalesce_str(work_machine.year, "N/D")),
            ("TMC", _coalesce_str(work_machine.tmc, "N/D")),
            ("TCR", _format_asset_detail_value(work_machine.tcr_enabled, AssetDetailField.FORMAT_BOOL)),
            ("Pressione", _format_asset_detail_value(work_machine.pressure_bar, AssetDetailField.FORMAT_BAR)),
            ("CNC", _format_asset_detail_value(work_machine.cnc_controlled, AssetDetailField.FORMAT_BOOL)),
            ("5 assi", _format_asset_detail_value(work_machine.five_axes, AssetDetailField.FORMAT_BOOL)),
            ("Accuracy from", _coalesce_str(work_machine.accuracy_from, "N/D")),
            ("Prossima manutenzione", _format_asset_detail_value(work_machine.next_maintenance_date, AssetDetailField.FORMAT_DATE)),
            ("Soglia reminder", f"{work_machine.maintenance_reminder_days} gg"),
        ]
        default_profile_rows = [
            {"label": "Tag asset", "value": asset.asset_tag},
            {"label": "Reparto", "value": _coalesce_str(asset.reparto, "-")},
            {"label": "TCR", "value": _format_asset_detail_value(work_machine.tcr_enabled, AssetDetailField.FORMAT_BOOL)},
            {"label": "CNC", "value": _format_asset_detail_value(work_machine.cnc_controlled, AssetDetailField.FORMAT_BOOL)},
            {"label": "5 assi", "value": _format_asset_detail_value(work_machine.five_axes, AssetDetailField.FORMAT_BOOL)},
            {"label": "Prossima manutenzione", "value": _format_asset_detail_value(work_machine.next_maintenance_date, AssetDetailField.FORMAT_DATE)},
            {"label": "Soglia reminder", "value": f"{work_machine.maintenance_reminder_days} gg"},
            {"label": "Accuracy from", "value": _coalesce_str(work_machine.accuracy_from, "-")},
        ]
        profile_card_title = "Profilo macchina"
    else:
        metric_battery = _coalesce_str(extra.get("battery_health"), extra.get("batteria"), "N/D")
        metric_cpu = _coalesce_str(extra.get("avg_cpu_load"), extra.get("cpu_load"), "N/D")
        metric_storage = _coalesce_str(extra.get("storage_free"), extra.get("free_storage"), it_details.disco if it_details else "", "N/D")
        default_detail_metrics = [
            {"label": "Salute batteria", "value": metric_battery, "size": AssetDetailField.CARD_THIRD},
            {"label": "Carico medio CPU", "value": metric_cpu, "size": AssetDetailField.CARD_THIRD},
            {"label": "Spazio libero", "value": metric_storage, "size": AssetDetailField.CARD_THIRD},
        ]
        default_spec_pairs = [
            ("Processore", _coalesce_str(it_details.cpu if it_details else "", asset.model, "N/D")),
            ("Numero seriale", _coalesce_str(asset.serial_number, "N/D")),
            ("Memoria", _coalesce_str(it_details.ram if it_details else "", "N/D")),
            ("Sistema operativo", _coalesce_str(it_details.os if it_details else "", "N/D")),
            ("Archiviazione", _coalesce_str(it_details.disco if it_details else "", "N/D")),
            ("Grafica", _coalesce_str(extra.get("graphics"), "N/D")),
            ("Schermo", _coalesce_str(extra.get("display"), "N/D")),
            ("Data acquisto", _coalesce_str(extra.get("purchase_date"), asset.created_at.strftime("%d/%m/%Y") if asset.created_at else "", "N/D")),
        ]
        default_profile_rows = [
            {"label": "Tag asset", "value": asset.asset_tag},
            {"label": "Produttore", "value": _coalesce_str(asset.manufacturer, "-")},
            {"label": "Modello", "value": _coalesce_str(asset.model, "-")},
            {"label": "Ultimo sync", "value": sync_text},
        ]
        profile_card_title = "Profilo asset"

    default_assignment_rows = [
        {"label": "Reparto", "value": _coalesce_str(asset.assignment_reparto, "-")},
        {"label": "Posizione", "value": _coalesce_str(asset.assignment_location, "-")},
        {"label": "Assegnato a", "value": _coalesce_str(asset.assignment_to, "Non assegnato")},
        {"label": "Assegnato dal", "value": asset.updated_at.strftime("%d/%m/%Y") if asset.updated_at else "-"},
    ]
    category_detail_sections = _build_asset_category_detail_sections(asset, extra)

    configured_sections, has_matching_detail_layout = _build_configured_asset_detail_sections(
        asset=asset,
        it_details=it_details,
        work_machine=work_machine,
        extra=extra,
        custom_fields_by_code=custom_fields_by_code,
        sync_text=sync_text,
    )
    if has_matching_detail_layout:
        detail_metrics = configured_sections.get(AssetDetailField.SECTION_METRICS, [])
        spec_rows = configured_sections.get(AssetDetailField.SECTION_SPECS, [])
        profile_rows = configured_sections.get(AssetDetailField.SECTION_PROFILE, [])
        assignment_rows = configured_sections.get(AssetDetailField.SECTION_ASSIGNMENT, [])
    else:
        detail_metrics = default_detail_metrics
        spec_rows = [{"label": key, "value": value} for key, value in default_spec_pairs]
        profile_rows = default_profile_rows
        assignment_rows = default_assignment_rows
    detail_metrics = [*detail_metrics, *category_detail_sections.get(AssetDetailField.SECTION_METRICS, [])]
    spec_rows = [*spec_rows, *category_detail_sections.get(AssetDetailField.SECTION_SPECS, [])]
    profile_rows = [*profile_rows, *category_detail_sections.get(AssetDetailField.SECTION_PROFILE, [])]
    assignment_rows = [*assignment_rows, *category_detail_sections.get(AssetDetailField.SECTION_ASSIGNMENT, [])]
    for metric in detail_metrics:
        metric["size_class"] = _detail_grid_size_class(str(metric.get("size") or ""))
    spec_pairs = [(row["label"], row["value"]) for row in spec_rows]
    detail_specs_title = _coalesce_str(getattr(asset.asset_category, "detail_specs_title", ""), "Specifiche tecniche")
    profile_card_title = _coalesce_str(getattr(asset.asset_category, "detail_profile_title", ""), profile_card_title)
    detail_assignment_title = _coalesce_str(getattr(asset.asset_category, "detail_assignment_title", ""), "Responsabile attuale")
    detail_timeline_title = _coalesce_str(getattr(asset.asset_category, "detail_timeline_title", ""), "Timeline ciclo di vita")
    detail_maintenance_title = _coalesce_str(
        getattr(asset.asset_category, "detail_maintenance_title", ""),
        "Registro manutenzione",
    )
    detail_tickets_title = "Ticket collegati"

    timeline_events: list[dict] = []
    if asset.assignment_to:
        timeline_events.append(
            {
                "title": f"Assegnato a {asset.assignment_to}",
                "tag": "ASSEGNAZIONE",
                "description": _coalesce_str(asset.assignment_location, "Asset in uso"),
                "date": asset.updated_at,
                "meta": _coalesce_str(asset.assignment_reparto, "Inventario"),
                "color": "green",
            }
        )
    timeline_events.append(
        {
            "title": "Registrazione inventario",
            "tag": "AMMINISTRAZIONE",
            "description": _coalesce_str(asset.source_key, "Asset aggiunto al sistema."),
            "date": asset.created_at,
            "meta": "Sistema",
            "color": "blue",
        }
    )
    if asset.created_at:
        timeline_events.append(
            {
                "title": "Acquisto / Provisioning",
                "tag": "APPROVVIGIONAMENTO",
                "description": _coalesce_str(extra.get("po_ref"), "Asset provisionato"),
                "date": asset.created_at - timedelta(days=3),
                "meta": _coalesce_str(extra.get("owner_dept"), "Approvvigionamenti"),
                "color": "amber",
            }
        )
    if isinstance(work_machine, WorkMachine) and work_machine.year:
        try:
            machine_start = timezone.make_aware(datetime(int(work_machine.year), 1, 1, 8, 0, 0), timezone.get_current_timezone())
        except (TypeError, ValueError):
            machine_start = None
        if machine_start is not None:
            timeline_events.append(
                {
                    "title": "Messa in servizio macchina",
                    "tag": "OFFICINA",
                    "description": _coalesce_str(asset.reparto, "Macchina operativa"),
                    "date": machine_start,
                    "meta": _coalesce_str(asset.manufacturer, "Produzione"),
                    "color": "blue",
                }
            )
    timeline_events.sort(key=lambda item: item.get("date") or now, reverse=True)

    maintenance_rows = list(
        asset.workorders.select_related(
            "asset",
            "supplier",
            "maintenance_rule",
            "maintenance_rule__intervention_template",
            "assistance_contract",
        ).all()[:10]
    )
    from tickets.models import TipoTicket
    manageable_ticket_types = {
        ticket_type
        for ticket_type in (TipoTicket.IT, TipoTicket.MAN)
        if _can_manage_ticket_type_for_asset_view(request, ticket_type)
    }
    ticket_rows = [
        {
            "numero_ticket": ticket.numero_ticket,
            "tipo_label": ticket.label_tipo,
            "titolo": ticket.titolo,
            "stato_label": ticket.label_stato,
            "priorita_label": ticket.label_priorita,
            "componente": ticket.componente,
            "created_at": ticket.created_at,
            "closed_at": ticket.closed_at,
            "detail_url": _asset_ticket_detail_url(request, ticket, manageable_ticket_types),
        }
        for ticket in asset.tickets.all()
    ]
    ticket_kpi = _compute_ticket_kpi_for_asset(asset)
    doc_category_labels, documents_by_category = _build_asset_documents_by_category(asset)
    periodic_verification_rows = [
        {"verification": verification, "state": _periodic_verification_state(verification, today=today)}
        for verification in asset.periodic_verifications.all().order_by("name", "id")
    ]
    active_component_count = sum(1 for component in component_rows if component.is_active)
    active_deadline_rows = [deadline for deadline in administrative_deadlines if deadline.is_active]
    deadline_state_rows = [
        {"deadline": deadline, "state": _asset_administrative_deadline_state(deadline, today=today)}
        for deadline in administrative_deadlines
    ]
    overdue_deadline_count = sum(1 for row in deadline_state_rows if row["state"]["status"] == "overdue")
    warning_deadline_count = sum(1 for row in deadline_state_rows if row["state"]["status"] == "warning")
    next_deadline_row = next(
        (row for row in deadline_state_rows if row["deadline"].is_active),
        None,
    )
    resolved_maintenance_rule_rows = resolve_asset_maintenance_rules(asset)
    asset_schedule_rows = build_day_based_maintenance_schedule_rows(
        asset_queryset=Asset.objects.filter(pk=asset.id).select_related("asset_category"),
        today=today,
    )
    next_maintenance_row = next(
        (
            row
            for row in asset_schedule_rows
            if row["schedule_status"] in {"overdue", "warning", "upcoming", "missing"}
        ),
        None,
    )
    primary_contract = get_primary_assistance_contract(asset, today=today)
    primary_contract_state = contract_state_payload(primary_contract, today=today) if primary_contract is not None else None
    asset_license_rows = [
        {
            "license": license_row,
            "state": _software_license_state_payload(license_row, today=today),
            "asset_url": reverse("assets:asset_view", kwargs={"id": asset.id}),
            "employee_url": (
                reverse("anagrafica:dipendente_detail", args=[license_row.assigned_anagrafica_id])
                if license_row.assigned_anagrafica_id
                else ""
            ),
        }
        for license_row in asset.software_licenses.all().order_by("category", "vendor", "product_name", "id")
    ]
    asset_create_workorder_url = _workorder_create_page_url(
        asset_id=asset.id,
        rule_id=getattr(next_maintenance_row.get("base_rule"), "id", 0) if next_maintenance_row else 0,
        source="asset_detail",
    )
    maintenance_suggestions = _contextual_maintenance_suggestions(
        asset=asset,
        schedule_row=next_maintenance_row,
        contract=primary_contract,
        source="asset_detail",
    )
    asset_status = _asset_status_payload(asset)
    can_manage_asset_maintenance_rules = _is_assets_admin(request)
    asset_assign_url = reverse("assets:asset_assign", kwargs={"id": asset.id})

    buttons_by_zone = _build_action_buttons_for_asset(asset, create_workorder_url=asset_create_workorder_url)
    buttons_by_zone = _promote_asset_detail_actions(
        buttons_by_zone,
        assign_url=asset_assign_url,
        qr_url=reverse("assets:asset_qr_label", kwargs={"id": asset.id}),
    )
    quick_action_buttons = [
        button
        for button in buttons_by_zone.get(AssetActionButton.ZONE_QUICK, [])
        if _clean_string(button.get("label")) not in {"Riassegna", "Crea intervento", "Etichetta QR"}
    ]

    assigned_user_admin_url = ""
    if asset.assigned_legacy_user_id:
        try:
            anag = AnagraficaDipendente.objects.filter(
                utente_id=int(asset.assigned_legacy_user_id)
            ).values_list("id", flat=True).first()
            if anag:
                assigned_user_admin_url = reverse(
                    "anagrafica:dipendente_detail",
                    kwargs={"legacy_id": anag},
                )
        except (NoReverseMatch, ValueError, TypeError):
            assigned_user_admin_url = ""
    collection_url = reverse("assets:work_machine_list") if asset.asset_type == Asset.TYPE_WORK_MACHINE else reverse("assets:asset_list")
    collection_label = "Macchine di lavoro" if asset.asset_type == Asset.TYPE_WORK_MACHINE else "Inventario"

    map_marker = (
        PlantLayoutMarker.objects.filter(asset=asset, layout__is_active=True)
        .select_related("layout")
        .order_by("layout__category", "layout__name", "id")
        .first()
    )
    if map_marker:
        map_url = reverse("assets:plant_layout_map") + f"?asset={asset.id}&category={quote(map_marker.layout.category)}"
    else:
        map_url = ""

    shell_kwargs = {}
    if asset.asset_type == Asset.TYPE_WORK_MACHINE:
        shell_kwargs = {
            "search_action": reverse("assets:work_machine_list"),
            "new_url": reverse("assets:work_machine_create"),
            "new_label": "+ Nuova macchina",
            "search_placeholder": "Ricerca rapida per macchina, tag, reparto o seriale",
        }

    linked_task_rows: list[dict] = []
    upcoming_task_rows: list[dict] = []
    try:
        from tasks.models import TaskExtraRef, TaskStatus
        refs = (
            TaskExtraRef.objects.filter(asset=asset)
            .select_related("task", "task__category", "task__project", "task__assigned_to")
            .order_by("-task__updated_at", "-task_id")[:50]
        )
        today = timezone.localdate()
        seen_task_ids = set()
        for ref in refs:
            if not ref.task_id or ref.task_id in seen_task_ids:
                continue
            seen_task_ids.add(ref.task_id)
            t = ref.task
            cat_field_label = ""
            if t.category_id:
                cat_field = next((f for f in t.category.fields.all() if f.code == ref.field_code), None)
                if cat_field:
                    cat_field_label = cat_field.label
            base_row = {
                "id": t.id,
                "title": t.title,
                "status": t.get_status_display(),
                "status_code": t.status,
                "due_date": t.due_date,
                "start_date": getattr(t, "next_step_due", None),
                "assignee": (t.assigned_to.get_full_name() or t.assigned_to.username) if t.assigned_to_id else "",
                "category_name": t.category.name if t.category_id else "",
                "field_label": cat_field_label or ref.field_code,
                "project_name": t.project.name if t.project_id else "",
                "url": reverse("tasks:detail", args=[t.id]),
            }
            linked_task_rows.append(base_row)
            # "AdL previste": solo task attive con finestra temporale rilevante (in corso oppure futura)
            if t.status in {TaskStatus.TODO, TaskStatus.IN_PROGRESS}:
                start = base_row["start_date"]
                end = base_row["due_date"]
                effective_end = end or start
                if effective_end and effective_end >= today:
                    upcoming_task_rows.append(base_row)
        upcoming_task_rows.sort(
            key=lambda r: (
                r.get("start_date") or r.get("due_date") or today,
                r.get("due_date") or today,
                r.get("id") or 0,
            )
        )
    except Exception:
        linked_task_rows = []
        upcoming_task_rows = []
    detail_section_cards = _build_asset_detail_section_cards(
        detail_specs_title=detail_specs_title,
        detail_timeline_title=detail_timeline_title,
        detail_maintenance_title=detail_maintenance_title,
        detail_tickets_title=detail_tickets_title,
        profile_card_title=profile_card_title,
        detail_assignment_title=detail_assignment_title,
        quick_action_buttons=quick_action_buttons,
        sharepoint_folder_url=_clean_string(asset.sharepoint_folder_url),
        sharepoint_folder_path=_normalize_sharepoint_path(asset.sharepoint_folder_path),
        map_marker=map_marker,
        doc_category_labels=doc_category_labels,
        spec_pairs=spec_pairs,
        profile_rows=profile_rows,
        license_rows=asset_license_rows,
        ticket_rows=ticket_rows,
    )
    asset_primary_kpis = _build_asset_primary_kpis(
        asset=asset,
        asset_status=asset_status,
        assignment_rows=assignment_rows,
        primary_contract=primary_contract,
        primary_contract_state=primary_contract_state,
        next_maintenance_row=next_maintenance_row,
        next_deadline_row=next_deadline_row,
        preferred_detail_metrics=_preferred_asset_detail_metrics(detail_metrics),
        detail_metrics=detail_metrics,
        asset_assign_url=asset_assign_url,
        asset_assistance_contracts_url=_assistance_contracts_page_url(asset_id=asset.id),
        asset_maintenance_schedule_url=_maintenance_schedule_page_url(asset_id=asset.id),
        asset_administrative_deadline_list_url=_asset_administrative_deadline_page_url(asset_id=asset.id),
    )
    return render(
        request,
        "assets/pages/asset_detail.html",
        {
            "page_title": f"Dettaglio asset {asset.asset_tag}",
            "asset": asset,
            "asset_status": asset_status,
            "recent_workorders": recent_workorders,
            "custom_fields": custom_fields,
            "unmapped_extra": unmapped_extra,
            "assigned_user_admin_url": assigned_user_admin_url,
            "sync_text": sync_text,
            "detail_metrics": detail_metrics,
            "asset_primary_kpis": asset_primary_kpis,
            "detail_specs_title": detail_specs_title,
            "spec_pairs": spec_pairs,
            "profile_rows": profile_rows,
            "profile_card_title": profile_card_title,
            "assignment_rows": assignment_rows,
            "detail_assignment_title": detail_assignment_title,
            "timeline_events": timeline_events,
            "detail_timeline_title": detail_timeline_title,
            "maintenance_rows": maintenance_rows,
            "detail_maintenance_title": detail_maintenance_title,
            "ticket_rows": ticket_rows,
            "ticket_kpi": ticket_kpi,
            "detail_tickets_title": detail_tickets_title,
            "work_machine": work_machine,
            "collection_url": collection_url,
            "collection_label": collection_label,
            "asset_license_rows": asset_license_rows,
            "asset_license_manage_url": _software_licenses_page_url(asset_id=asset.id),
            "doc_category_labels": doc_category_labels,
            "documents_by_category": dict(documents_by_category),
            "sharepoint_folder_url": _clean_string(asset.sharepoint_folder_url),
            "sharepoint_folder_path": _normalize_sharepoint_path(asset.sharepoint_folder_path),
            "asset_report_pdf_url": _asset_report_pdf_url(asset.id),
            "asset_qr_url": reverse("assets:asset_qr_label", kwargs={"id": asset.id}),
            "asset_qr_sharepoint_url": (
                reverse("assets:asset_qr_label", kwargs={"id": asset.id}) + "?target=sharepoint"
                if _clean_string(asset.sharepoint_folder_url)
                else ""
            ),
            "asset_label_designer_url": (
                reverse("assets:asset_label_designer") + f"?scope=asset&asset_id={asset.id}"
                if _is_assets_admin(request)
                else ""
            ),
            "periodic_verification_rows": periodic_verification_rows,
            "periodic_verification_manage_url": _periodic_verifications_page_url(asset_id=asset.id),
            "asset_component_count": len(component_rows),
            "asset_active_component_count": active_component_count,
            "asset_component_list_url": _asset_component_page_url(asset_id=asset.id),
            "asset_component_create_url": _asset_component_create_page_url(asset_id=asset.id),
            "asset_administrative_deadline_count": len(administrative_deadlines),
            "asset_active_administrative_deadline_count": len(active_deadline_rows),
            "asset_overdue_administrative_deadline_count": overdue_deadline_count,
            "asset_warning_administrative_deadline_count": warning_deadline_count,
            "asset_next_administrative_deadline": next_deadline_row["deadline"] if next_deadline_row else None,
            "asset_next_administrative_deadline_state": next_deadline_row["state"] if next_deadline_row else None,
            "asset_administrative_deadline_list_url": _asset_administrative_deadline_page_url(asset_id=asset.id),
            "asset_administrative_deadline_create_url": _asset_administrative_deadline_create_page_url(asset_id=asset.id),
            "asset_maintenance_rule_count": len(resolved_maintenance_rule_rows),
            "asset_overridden_maintenance_rule_count": sum(
                1 for row in resolved_maintenance_rule_rows if row["status"] == "overridden"
            ),
            "asset_disabled_maintenance_rule_count": sum(
                1 for row in resolved_maintenance_rule_rows if row["status"] == "disabled"
            ),
            "asset_maintenance_rule_list_url": _asset_maintenance_rule_list_page_url(asset_id=asset.id),
            "can_manage_asset_maintenance_rules": can_manage_asset_maintenance_rules,
            "asset_linked_task_rows": linked_task_rows,
            "asset_upcoming_task_rows": upcoming_task_rows,
            "asset_maintenance_schedule_url": _maintenance_schedule_page_url(asset_id=asset.id),
            "asset_assistance_contracts_url": _assistance_contracts_page_url(asset_id=asset.id),
            "asset_primary_contract": primary_contract,
            "asset_primary_contract_state": primary_contract_state,
            "asset_next_maintenance_row": next_maintenance_row,
            "asset_create_workorder_url": asset_create_workorder_url,
            "maintenance_suggestions": maintenance_suggestions,
            "can_manage_licenses": _is_assets_admin(request),
            "asset_assign_url": asset_assign_url,
            "header_action_buttons": buttons_by_zone.get(AssetActionButton.ZONE_HEADER, []),
            "quick_action_buttons": quick_action_buttons,
            "detail_section_cards": detail_section_cards,
            "layout_manage_url": (
                reverse("assets:asset_detail_layout_admin") + f"?asset={asset.id}"
                if _can_manage_asset_detail_layout(request)
                else ""
            ),
            "map_marker": map_marker,
            "map_url": map_url,
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25), **shell_kwargs),
        },
    )


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
            Asset.objects.filter(asset_type=Asset.TYPE_WORK_MACHINE)
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
    preview_asset_sharepoint_qr_url = ""
    logo_meta = _asset_label_logo_meta(template)
    if preview_asset is not None:
        preview_asset_qr_url = reverse("assets:asset_qr_label", kwargs={"id": preview_asset.id})
        if _clean_string(preview_asset.sharepoint_folder_url):
            preview_asset_sharepoint_qr_url = f"{preview_asset_qr_url}?target=sharepoint"

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
            "preview_asset_sharepoint_qr_url": preview_asset_sharepoint_qr_url,
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
def asset_qr_label(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:asset_list")
    asset = get_object_or_404(Asset, pk=id)
    target_value = _clean_string(request.GET.get("target")).lower() or "detail"
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


@login_required
def asset_create(request: HttpRequest) -> HttpResponse:
    if _clean_string(request.GET.get("asset_type")) == Asset.TYPE_WORK_MACHINE:
        return redirect("assets:work_machine_create")
    custom_fields = list(AssetCustomField.objects.filter(is_active=True).order_by("sort_order", "id"))
    list_suggestions = _build_asset_list_suggestions()
    if request.method == "POST":
        form = AssetForm(request.POST, custom_fields=custom_fields, list_suggestions=list_suggestions)
        if form.is_valid():
            asset = form.save()
            for warning in _ensure_asset_sharepoint_folder(asset):
                messages.warning(request, warning)
            messages.success(request, "Asset creato correttamente.")
            return redirect("assets:asset_view", id=asset.id)
    else:
        form = AssetForm(custom_fields=custom_fields, list_suggestions=list_suggestions)
    return render(
        request,
        "assets/pages/asset_form.html",
        {
            "page_title": "Nuovo asset",
            "form": form,
            "is_edit": False,
            "base_field_names": form.base_field_names,
            "category_field_groups": form.category_field_groups,
            "category_dynamic_field_names": form.category_dynamic_field_names,
            "dynamic_field_names": form.dynamic_field_names,
            "verification_field_names": form.verification_field_names,
            "list_suggestions": list_suggestions,
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


@login_required
def asset_edit(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:asset_list")
    asset = get_object_or_404(Asset, pk=id)
    if asset.asset_type == Asset.TYPE_WORK_MACHINE:
        return redirect("assets:work_machine_edit", id=asset.id)
    custom_fields = list(AssetCustomField.objects.filter(is_active=True).order_by("sort_order", "id"))
    list_suggestions = _build_asset_list_suggestions()
    if request.method == "POST":
        form = AssetForm(
            request.POST,
            instance=asset,
            custom_fields=custom_fields,
            list_suggestions=list_suggestions,
        )
        if form.is_valid():
            asset = form.save()
            for warning in _ensure_asset_sharepoint_folder(asset):
                messages.warning(request, warning)
            messages.success(request, "Asset aggiornato.")
            return redirect("assets:asset_view", id=asset.id)
    else:
        form = AssetForm(instance=asset, custom_fields=custom_fields, list_suggestions=list_suggestions)
    return render(
        request,
        "assets/pages/asset_form.html",
        {
            "page_title": f"Modifica {asset.asset_tag}",
            "form": form,
            "asset": asset,
            "is_edit": True,
            "base_field_names": form.base_field_names,
            "category_field_groups": form.category_field_groups,
            "category_dynamic_field_names": form.category_dynamic_field_names,
            "dynamic_field_names": form.dynamic_field_names,
            "verification_field_names": form.verification_field_names,
            "list_suggestions": list_suggestions,
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


@login_required
def asset_component_list(request: HttpRequest, asset_id: int | None = None) -> HttpResponse:
    selected_asset = None
    selected_asset_id = asset_id if asset_id is not None else _as_int(request.GET.get("asset"), default=0)
    if asset_id is not None:
        selected_asset = get_object_or_404(
            Asset.objects.only("id", "asset_tag", "name", "reparto", "asset_type"),
            pk=asset_id,
        )
    elif selected_asset_id:
        selected_asset = (
            Asset.objects.only("id", "asset_tag", "name", "reparto", "asset_type")
            .filter(pk=selected_asset_id)
            .first()
        )

    q = _clean_string(request.GET.get("q"))
    active_filter = _clean_string(request.GET.get("active")).lower() or "active"
    if active_filter not in {"active", "inactive", "all"}:
        active_filter = "active"

    component_qs = (
        AssetComponent.objects.select_related("asset")
        .prefetch_related("administrative_deadlines")
        .order_by("-is_active", "asset__name", "name", "code", "id")
    )
    if selected_asset is not None:
        component_qs = component_qs.filter(asset_id=selected_asset.id)
    if q:
        component_qs = component_qs.filter(
            Q(code__icontains=q)
            | Q(name__icontains=q)
            | Q(component_type__icontains=q)
            | Q(serial_number__icontains=q)
            | Q(manufacturer__icontains=q)
            | Q(model__icontains=q)
            | Q(notes__icontains=q)
            | Q(asset__asset_tag__icontains=q)
            | Q(asset__name__icontains=q)
        )
    if active_filter == "active":
        component_qs = component_qs.filter(is_active=True)
    elif active_filter == "inactive":
        component_qs = component_qs.filter(is_active=False)

    component_rows: list[dict[str, object]] = []
    for component in component_qs:
        deadlines = list(component.administrative_deadlines.all())
        active_deadline_count = sum(1 for deadline in deadlines if deadline.is_active)
        component_rows.append(
            {
                "component": component,
                "deadline_total": len(deadlines),
                "active_deadline_count": active_deadline_count,
                "edit_url": reverse("assets:asset_component_edit", kwargs={"id": component.id}),
                "deadline_list_url": _asset_administrative_deadline_page_url(
                    asset_id=component.asset_id,
                    component_id=component.id,
                ),
            }
        )

    asset_options = list(
        Asset.objects.only("id", "asset_tag", "name").order_by("name", "asset_tag", "id")
    )
    selected_asset_component_count = sum(1 for row in component_rows if row["component"].is_active)
    create_url = _asset_component_create_page_url(asset_id=selected_asset.id if selected_asset else 0)

    return render(
        request,
        "assets/pages/asset_component_list.html",
        {
            "page_title": "Componenti asset",
            "component_rows": component_rows,
            "component_total": len(component_rows),
            "active_component_count": sum(1 for row in component_rows if row["component"].is_active),
            "inactive_component_count": sum(1 for row in component_rows if not row["component"].is_active),
            "selected_asset": selected_asset,
            "selected_asset_component_count": selected_asset_component_count,
            "asset_options": asset_options,
            "active_filter": active_filter,
            "q": q,
            "create_url": create_url,
            "clear_filters_url": _asset_component_page_url(asset_id=selected_asset.id if asset_id is not None and selected_asset else 0),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=_asset_component_page_url(asset_id=selected_asset.id if asset_id is not None and selected_asset else 0),
                new_url=create_url,
                new_label="+ Nuovo componente",
                search_placeholder="Ricerca rapida per componente, codice, seriale o asset",
            ),
        },
    )


@login_required
def asset_component_create(request: HttpRequest, asset_id: int | None = None) -> HttpResponse:
    selected_asset = None
    selected_asset_id = asset_id if asset_id is not None else _as_int(request.GET.get("asset"), default=0)
    if asset_id is not None:
        selected_asset = get_object_or_404(
            Asset.objects.only("id", "asset_tag", "name", "reparto", "asset_type"),
            pk=asset_id,
        )
    elif selected_asset_id:
        selected_asset = (
            Asset.objects.only("id", "asset_tag", "name", "reparto", "asset_type")
            .filter(pk=selected_asset_id)
            .first()
        )

    if request.method == "POST":
        form = AssetComponentForm(request.POST, locked_asset=selected_asset)
        if form.is_valid():
            component = form.save()
            log_action(
                request,
                "create_asset_component",
                "assets",
                {"component_id": component.id, "asset_id": component.asset_id, "code": component.code, "name": component.name},
            )
            messages.success(request, "Componente salvato correttamente.")
            return redirect(_asset_component_page_url(asset_id=component.asset_id))
    else:
        form = AssetComponentForm(
            locked_asset=selected_asset,
            initial={"asset": selected_asset.id} if selected_asset else None,
        )

    return render(
        request,
        "assets/pages/asset_component_form.html",
        {
            "page_title": "Nuovo componente",
            "form": form,
            "selected_asset": selected_asset,
            "is_edit": False,
            "back_url": _asset_component_page_url(asset_id=selected_asset.id if selected_asset else 0),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=_asset_component_page_url(asset_id=selected_asset.id if selected_asset else 0),
                new_url=_asset_component_create_page_url(asset_id=selected_asset.id if selected_asset else 0),
                new_label="+ Nuovo componente",
                search_placeholder="Ricerca rapida per componente, codice, seriale o asset",
            ),
        },
    )


@login_required
def asset_component_edit(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:asset_component_list")
    component = get_object_or_404(
        AssetComponent.objects.select_related("asset"),
        pk=id,
    )
    selected_asset = component.asset

    if request.method == "POST":
        form = AssetComponentForm(request.POST, instance=component, locked_asset=selected_asset)
        if form.is_valid():
            component = form.save()
            log_action(
                request,
                "update_asset_component",
                "assets",
                {"component_id": component.id, "asset_id": component.asset_id, "code": component.code, "name": component.name},
            )
            messages.success(request, "Componente aggiornato.")
            return redirect(_asset_component_page_url(asset_id=component.asset_id))
    else:
        form = AssetComponentForm(instance=component, locked_asset=selected_asset)

    return render(
        request,
        "assets/pages/asset_component_form.html",
        {
            "page_title": f"Modifica componente {component.name}",
            "form": form,
            "component": component,
            "selected_asset": selected_asset,
            "is_edit": True,
            "back_url": _asset_component_page_url(asset_id=selected_asset.id),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=_asset_component_page_url(asset_id=selected_asset.id),
                new_url=_asset_component_create_page_url(asset_id=selected_asset.id),
                new_label="+ Nuovo componente",
                search_placeholder="Ricerca rapida per componente, codice, seriale o asset",
            ),
        },
    )


@login_required
def asset_administrative_deadline_list(request: HttpRequest) -> HttpResponse:
    can_manage_outlook_calendar = _is_assets_admin(request)
    calendar_user_choices: list[tuple[str, str]] = []
    calendar_user_details: dict[str, dict[str, str]] = {}
    if can_manage_outlook_calendar:
        calendar_user_choices, calendar_user_details = _legacy_employee_options()

    if request.method == "POST":
        action = _clean_string(request.POST.get("action"))
        if action == "create_outlook_calendar_event":
            redirect_url = _deadline_list_redirect_from_request(request)
            if not can_manage_outlook_calendar:
                messages.error(request, "Solo gli admin assets possono creare eventi Outlook su calendari utente.")
                return redirect(redirect_url)

            deadline_id = _as_int(request.POST.get("deadline_id"), default=0)
            target_legacy_user_id = _as_int(request.POST.get("target_legacy_user_id"), default=0)
            deadline = (
                AssetAdministrativeDeadline.objects.select_related("asset", "component")
                .filter(pk=deadline_id)
                .first()
            )
            target_details = calendar_user_details.get(str(target_legacy_user_id))
            if deadline is None:
                messages.error(request, "Scadenza amministrativa non trovata.")
                return redirect(redirect_url)
            if target_details is None:
                messages.error(request, "Seleziona un utente valido per il calendario Outlook.")
                return redirect(redirect_url)

            try:
                entry, created = _create_asset_deadline_calendar_event(
                    request=request,
                    deadline=deadline,
                    target_legacy_user_id=target_legacy_user_id,
                    target_details=target_details,
                )
                target_label = entry.target_display_name or entry.target_email or f"utente {entry.target_legacy_user_id}"
                if created:
                    log_action(
                        request,
                        "create_deadline_calendar_event",
                        "assets",
                        {
                            "deadline_id": deadline.id,
                            "asset_id": deadline.asset_id,
                            "component_id": deadline.component_id,
                            "due_date": str(deadline.due_date),
                            "target_legacy_user_id": entry.target_legacy_user_id,
                            "target_email": entry.target_email,
                            "graph_event_id": entry.graph_event_id,
                        },
                    )
                    messages.success(
                        request,
                        f"Evento Outlook creato per {target_label} sulla scadenza del {entry.due_date:%d/%m/%Y}.",
                    )
                else:
                    messages.info(
                        request,
                        f"Esiste gia un evento Outlook per {target_label} su questa stessa scadenza.",
                    )
            except Exception as exc:
                messages.error(request, f"Creazione evento Outlook fallita: {exc}")
            return redirect(redirect_url)

    today = timezone.localdate()
    selected_asset_id = _as_int(request.GET.get("asset"), default=0)
    selected_component_id = _as_int(request.GET.get("component"), default=0)
    selected_asset = None
    selected_component = None

    if selected_component_id:
        selected_component = (
            AssetComponent.objects.select_related("asset")
            .filter(pk=selected_component_id)
            .first()
        )
        if selected_component is not None and not selected_asset_id:
            selected_asset_id = selected_component.asset_id
    if selected_asset_id:
        selected_asset = (
            Asset.objects.only("id", "asset_tag", "name", "reparto", "asset_type")
            .filter(pk=selected_asset_id)
            .first()
        )
    if selected_component is not None and selected_asset is None:
        selected_asset = selected_component.asset

    q = _clean_string(request.GET.get("q"))
    deadline_type = _clean_string(request.GET.get("deadline_type")).upper()
    valid_deadline_types = {code for code, _label in AssetAdministrativeDeadline.TYPE_CHOICES}
    if deadline_type not in valid_deadline_types:
        deadline_type = ""
    status_filter = _clean_string(request.GET.get("status")).lower() or "all"
    if status_filter not in {"all", "overdue", "warning", "upcoming", "inactive"}:
        status_filter = "all"

    deadline_qs = (
        AssetAdministrativeDeadline.objects.select_related("asset", "component")
        .order_by("due_date", "asset__name", "title", "id")
    )
    if selected_asset is not None:
        deadline_qs = deadline_qs.filter(asset_id=selected_asset.id)
    if selected_component is not None:
        deadline_qs = deadline_qs.filter(component_id=selected_component.id)
    if deadline_type:
        deadline_qs = deadline_qs.filter(deadline_type=deadline_type)
    if q:
        deadline_qs = deadline_qs.filter(
            Q(title__icontains=q)
            | Q(reference_code__icontains=q)
            | Q(issuer__icontains=q)
            | Q(notes__icontains=q)
            | Q(asset__asset_tag__icontains=q)
            | Q(asset__name__icontains=q)
            | Q(component__name__icontains=q)
            | Q(component__code__icontains=q)
        )

    deadline_rows_all: list[dict[str, object]] = []
    for deadline in deadline_qs:
        state = _asset_administrative_deadline_state(deadline, today=today)
        deadline_rows_all.append(
            {
                "deadline": deadline,
                "state": state,
                "edit_url": reverse("assets:asset_administrative_deadline_edit", kwargs={"id": deadline.id}),
                "asset_url": reverse("assets:asset_view", kwargs={"id": deadline.asset_id}),
                "component_url": _asset_component_page_url(asset_id=deadline.asset_id),
            }
        )

    calendar_event_map: dict[int, list[AssetCalendarEvent]] = defaultdict(list)
    deadline_ids = [row["deadline"].id for row in deadline_rows_all]
    if deadline_ids:
        for entry in (
            AssetCalendarEvent.objects.select_related("administrative_deadline")
            .filter(
                event_kind=AssetCalendarEvent.KIND_ADMINISTRATIVE_DEADLINE,
                administrative_deadline_id__in=deadline_ids,
            )
            .order_by("target_display_name", "target_email", "created_at", "id")
        ):
            if entry.administrative_deadline_id:
                calendar_event_map[entry.administrative_deadline_id].append(entry)

    if status_filter == "all":
        deadline_rows = deadline_rows_all
    else:
        deadline_rows = [row for row in deadline_rows_all if row["state"]["status"] == status_filter]

    for row in deadline_rows:
        deadline = row["deadline"]
        row["calendar_event_rows"] = list(calendar_event_map.get(deadline.id, []))
        row["default_calendar_user_id"] = _asset_calendar_default_user_id(deadline.asset, calendar_user_details)

    component_options = []
    if selected_asset is not None:
        component_options = list(
            AssetComponent.objects.filter(asset_id=selected_asset.id)
            .order_by("-is_active", "name", "code", "id")
        )
    elif selected_component is not None:
        component_options = [selected_component]

    create_url = _asset_administrative_deadline_create_page_url(
        asset_id=selected_asset.id if selected_asset else 0,
        component_id=selected_component.id if selected_component else 0,
    )

    return render(
        request,
        "assets/pages/asset_admin_deadline_list.html",
        {
            "page_title": "Scadenze amministrative",
            "deadline_rows": deadline_rows,
            "deadline_total": len(deadline_rows),
            "deadline_total_all": len(deadline_rows_all),
            "active_deadline_count": sum(1 for row in deadline_rows_all if row["deadline"].is_active),
            "overdue_deadline_count": sum(1 for row in deadline_rows_all if row["state"]["status"] == "overdue"),
            "warning_deadline_count": sum(1 for row in deadline_rows_all if row["state"]["status"] == "warning"),
            "selected_asset": selected_asset,
            "selected_component": selected_component,
            "asset_options": list(Asset.objects.only("id", "asset_tag", "name").order_by("name", "asset_tag", "id")),
            "component_options": component_options,
            "deadline_type_choices": AssetAdministrativeDeadline.TYPE_CHOICES,
            "selected_deadline_type": deadline_type,
            "status_filter": status_filter,
            "q": q,
            "create_url": create_url,
            "clear_filters_url": _asset_administrative_deadline_page_url(),
            "periodic_verification_url": (
                _periodic_verifications_page_url(asset_id=selected_asset.id if selected_asset else 0)
                if selected_asset
                else reverse("assets:periodic_verifications")
            ),
            "can_manage_outlook_calendar": can_manage_outlook_calendar,
            "outlook_calendar_ready": _outlook_calendar_graph_ready() if can_manage_outlook_calendar else False,
            "calendar_user_choices": calendar_user_choices,
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:asset_administrative_deadline_list"),
                new_url=create_url,
                new_label="+ Nuova scadenza",
                search_placeholder="Ricerca rapida per scadenza, riferimento, asset o componente",
            ),
        },
    )


@login_required
def asset_administrative_deadline_create(request: HttpRequest) -> HttpResponse:
    selected_asset_id = _as_int(request.GET.get("asset"), default=0)
    selected_component_id = _as_int(request.GET.get("component"), default=0)
    selected_component = None
    selected_asset = None

    if selected_component_id:
        selected_component = (
            AssetComponent.objects.select_related("asset")
            .filter(pk=selected_component_id)
            .first()
        )
        if selected_component is not None and not selected_asset_id:
            selected_asset_id = selected_component.asset_id
    if selected_asset_id:
        selected_asset = (
            Asset.objects.only("id", "asset_tag", "name", "reparto", "asset_type")
            .filter(pk=selected_asset_id)
            .first()
        )
    if selected_component is not None and selected_asset is None:
        selected_asset = selected_component.asset

    if request.method == "POST":
        form = AssetAdministrativeDeadlineForm(
            request.POST,
            locked_asset=selected_asset,
            preselected_component=selected_component,
        )
        if form.is_valid():
            deadline = form.save()
            log_action(
                request,
                "create_asset_deadline",
                "assets",
                {
                    "deadline_id": deadline.id,
                    "asset_id": deadline.asset_id,
                    "component_id": deadline.component_id,
                    "deadline_type": deadline.deadline_type,
                    "due_date": deadline.due_date.isoformat() if deadline.due_date else "",
                },
            )
            messages.success(request, "Scadenza salvata correttamente.")
            return redirect(
                _asset_administrative_deadline_page_url(
                    asset_id=deadline.asset_id,
                    component_id=deadline.component_id or 0,
                )
            )
    else:
        initial = {}
        if selected_asset is not None:
            initial["asset"] = selected_asset.id
        if selected_component is not None:
            initial["component"] = selected_component.id
        form = AssetAdministrativeDeadlineForm(
            initial=initial,
            locked_asset=selected_asset,
            preselected_component=selected_component,
        )

    return render(
        request,
        "assets/pages/asset_admin_deadline_form.html",
        {
            "page_title": "Nuova scadenza amministrativa",
            "form": form,
            "selected_asset": selected_asset,
            "selected_component": selected_component,
            "is_edit": False,
            "back_url": _asset_administrative_deadline_page_url(
                asset_id=selected_asset.id if selected_asset else 0,
                component_id=selected_component.id if selected_component else 0,
            ),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:asset_administrative_deadline_list"),
                new_url=_asset_administrative_deadline_create_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    component_id=selected_component.id if selected_component else 0,
                ),
                new_label="+ Nuova scadenza",
                search_placeholder="Ricerca rapida per scadenza, riferimento, asset o componente",
            ),
        },
    )


@login_required
def asset_administrative_deadline_edit(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:asset_administrative_deadline_list")
    deadline = get_object_or_404(
        AssetAdministrativeDeadline.objects.select_related("asset", "component"),
        pk=id,
    )
    selected_asset = deadline.asset
    selected_component = deadline.component

    if request.method == "POST":
        form = AssetAdministrativeDeadlineForm(
            request.POST,
            instance=deadline,
            locked_asset=selected_asset,
        )
        if form.is_valid():
            deadline = form.save()
            log_action(
                request,
                "update_asset_deadline",
                "assets",
                {
                    "deadline_id": deadline.id,
                    "asset_id": deadline.asset_id,
                    "component_id": deadline.component_id,
                    "deadline_type": deadline.deadline_type,
                    "due_date": deadline.due_date.isoformat() if deadline.due_date else "",
                },
            )
            messages.success(request, "Scadenza aggiornata.")
            return redirect(
                _asset_administrative_deadline_page_url(
                    asset_id=deadline.asset_id,
                    component_id=deadline.component_id or 0,
                )
            )
    else:
        form = AssetAdministrativeDeadlineForm(instance=deadline, locked_asset=selected_asset)

    return render(
        request,
        "assets/pages/asset_admin_deadline_form.html",
        {
            "page_title": f"Modifica scadenza {deadline.title}",
            "form": form,
            "deadline": deadline,
            "selected_asset": selected_asset,
            "selected_component": selected_component,
            "is_edit": True,
            "back_url": _asset_administrative_deadline_page_url(
                asset_id=selected_asset.id,
                component_id=selected_component.id if selected_component else 0,
            ),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:asset_administrative_deadline_list"),
                new_url=_asset_administrative_deadline_create_page_url(asset_id=selected_asset.id),
                new_label="+ Nuova scadenza",
                search_placeholder="Ricerca rapida per scadenza, riferimento, asset o componente",
            ),
        },
    )


@login_required
def maintenance_template_list(request: HttpRequest) -> HttpResponse:
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo gestire i template manutenzione.")
        return redirect("assets:asset_list")

    selected_category_id = _as_int(request.GET.get("category"), default=0)
    selected_category = None
    if selected_category_id:
        selected_category = AssetCategory.objects.filter(pk=selected_category_id).first()

    active_filter = _clean_string(request.GET.get("active")).lower() or "active"
    if active_filter not in {"active", "inactive", "all"}:
        active_filter = "active"
    q = _clean_string(request.GET.get("q"))

    template_qs = MaintenanceInterventionTemplate.objects.select_related("asset_category").order_by(
        "sort_order",
        "label",
        "id",
    )
    if selected_category is not None:
        template_qs = template_qs.filter(Q(asset_category__isnull=True) | Q(asset_category_id=selected_category.id))
    if active_filter == "active":
        template_qs = template_qs.filter(is_active=True)
    elif active_filter == "inactive":
        template_qs = template_qs.filter(is_active=False)
    if q:
        template_qs = template_qs.filter(
            Q(code__icontains=q)
            | Q(label__icontains=q)
            | Q(description__icontains=q)
            | Q(asset_category__label__icontains=q)
        )

    template_rows: list[dict[str, object]] = []
    for template in template_qs:
        template_rows.append(
            {
                "template": template,
                "rule_count": template.maintenance_rules.count(),
                "edit_url": reverse("assets:maintenance_template_edit", kwargs={"id": template.id}),
                "rules_url": _maintenance_rule_list_page_url(
                    category_id=template.asset_category_id or 0,
                    template_id=template.id,
                ),
            }
        )

    create_url = reverse("assets:maintenance_template_create")
    if selected_category is not None:
        create_url = f"{create_url}?category={selected_category.id}"

    return render(
        request,
        "assets/pages/maintenance_template_list.html",
        {
            "page_title": "Template manutenzione",
            "template_rows": template_rows,
            "template_total": len(template_rows),
            "active_template_count": sum(1 for row in template_rows if row["template"].is_active),
            "general_template_count": sum(1 for row in template_rows if row["template"].asset_category_id is None),
            "selected_category": selected_category,
            "category_options": list(AssetCategory.objects.order_by("sort_order", "label", "id")),
            "active_filter": active_filter,
            "q": q,
            "create_url": create_url,
            "clear_filters_url": reverse("assets:maintenance_template_list"),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:maintenance_template_list"),
                new_url=create_url,
                new_label="+ Nuovo template",
                search_placeholder="Ricerca rapida per template manutenzione, codice o categoria",
            ),
        },
    )


@login_required
def maintenance_template_create(request: HttpRequest) -> HttpResponse:
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo gestire i template manutenzione.")
        return redirect("assets:asset_list")

    selected_category_id = _as_int(request.GET.get("category"), default=0)
    initial = {"asset_category": selected_category_id} if selected_category_id else None

    if request.method == "POST":
        form = MaintenanceInterventionTemplateForm(request.POST)
        if form.is_valid():
            template = form.save()
            log_action(
                request,
                "create_maintenance_template",
                "assets",
                {"template_id": template.id, "code": template.code, "asset_category_id": template.asset_category_id},
            )
            messages.success(request, "Template manutenzione creato.")
            return redirect(
                _maintenance_template_list_page_url(
                    category_id=template.asset_category_id or 0,
                )
            )
    else:
        form = MaintenanceInterventionTemplateForm(initial=initial)

    return render(
        request,
        "assets/pages/maintenance_template_form.html",
        {
            "page_title": "Nuovo template manutenzione",
            "form": form,
            "is_edit": False,
            "back_url": _maintenance_template_list_page_url(category_id=selected_category_id),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:maintenance_template_list"),
                new_url=reverse("assets:maintenance_template_create"),
                new_label="+ Nuovo template",
                search_placeholder="Ricerca rapida per template manutenzione, codice o categoria",
            ),
        },
    )


@login_required
def maintenance_template_edit(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo gestire i template manutenzione.")
        return redirect("assets:asset_list")
    if id is None:
        return redirect("assets:maintenance_template_list")

    template = get_object_or_404(MaintenanceInterventionTemplate.objects.select_related("asset_category"), pk=id)
    if request.method == "POST":
        form = MaintenanceInterventionTemplateForm(request.POST, instance=template)
        if form.is_valid():
            template = form.save()
            log_action(
                request,
                "update_maintenance_template",
                "assets",
                {"template_id": template.id, "code": template.code, "asset_category_id": template.asset_category_id},
            )
            messages.success(request, "Template manutenzione aggiornato.")
            return redirect(_maintenance_template_list_page_url(category_id=template.asset_category_id or 0))
    else:
        form = MaintenanceInterventionTemplateForm(instance=template)

    return render(
        request,
        "assets/pages/maintenance_template_form.html",
        {
            "page_title": f"Modifica template {template.label}",
            "form": form,
            "template": template,
            "is_edit": True,
            "back_url": _maintenance_template_list_page_url(category_id=template.asset_category_id or 0),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:maintenance_template_list"),
                new_url=reverse("assets:maintenance_template_create"),
                new_label="+ Nuovo template",
                search_placeholder="Ricerca rapida per template manutenzione, codice o categoria",
            ),
        },
    )


@login_required
def maintenance_rule_list(request: HttpRequest) -> HttpResponse:
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo gestire le regole manutenzione.")
        return redirect("assets:asset_list")

    selected_category_id = _as_int(request.GET.get("category"), default=0)
    selected_template_id = _as_int(request.GET.get("template"), default=0)
    threshold_type = _clean_string(request.GET.get("threshold_type")).upper()
    valid_threshold_types = {code for code, _label in MaintenanceRule.THRESHOLD_TYPE_CHOICES}
    if threshold_type not in valid_threshold_types:
        threshold_type = ""
    active_filter = _clean_string(request.GET.get("active")).lower() or "active"
    if active_filter not in {"active", "inactive", "all"}:
        active_filter = "active"
    q = _clean_string(request.GET.get("q"))

    rule_qs = MaintenanceRule.objects.select_related("asset_category", "intervention_template").order_by(
        "asset_category__sort_order",
        "asset_category__label",
        "sort_order",
        "id",
    )
    if selected_category_id:
        rule_qs = rule_qs.filter(asset_category_id=selected_category_id)
    if selected_template_id:
        rule_qs = rule_qs.filter(intervention_template_id=selected_template_id)
    if threshold_type:
        rule_qs = rule_qs.filter(threshold_type=threshold_type)
    if active_filter == "active":
        rule_qs = rule_qs.filter(is_active=True)
    elif active_filter == "inactive":
        rule_qs = rule_qs.filter(is_active=False)
    if q:
        rule_qs = rule_qs.filter(
            Q(asset_category__label__icontains=q)
            | Q(intervention_template__label__icontains=q)
            | Q(intervention_template__code__icontains=q)
            | Q(notes__icontains=q)
        )

    rule_rows = [
        {
            "rule": rule,
            "edit_url": reverse("assets:maintenance_rule_edit", kwargs={"id": rule.id}),
            "template_url": reverse("assets:maintenance_template_edit", kwargs={"id": rule.intervention_template_id}),
        }
        for rule in rule_qs
    ]

    create_url = reverse("assets:maintenance_rule_create")
    params = []
    if selected_category_id:
        params.append(f"category={selected_category_id}")
    if selected_template_id:
        params.append(f"template={selected_template_id}")
    if params:
        create_url = f"{create_url}?{'&'.join(params)}"

    return render(
        request,
        "assets/pages/maintenance_rule_list.html",
        {
            "page_title": "Regole manutenzione",
            "rule_rows": rule_rows,
            "rule_total": len(rule_rows),
            "active_rule_count": sum(1 for row in rule_rows if row["rule"].is_active),
            "days_rule_count": sum(1 for row in rule_rows if row["rule"].threshold_type == MaintenanceRule.THRESHOLD_DAYS),
            "category_options": list(AssetCategory.objects.order_by("sort_order", "label", "id")),
            "template_options": list(
                MaintenanceInterventionTemplate.objects.select_related("asset_category").order_by("sort_order", "label", "id")
            ),
            "selected_category_id": selected_category_id,
            "selected_template_id": selected_template_id,
            "selected_threshold_type": threshold_type,
            "threshold_type_choices": MaintenanceRule.THRESHOLD_TYPE_CHOICES,
            "active_filter": active_filter,
            "q": q,
            "create_url": create_url,
            "clear_filters_url": reverse("assets:maintenance_rule_list"),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:maintenance_rule_list"),
                new_url=create_url,
                new_label="+ Nuova regola",
                search_placeholder="Ricerca rapida per regola, template o categoria",
            ),
        },
    )


@login_required
def maintenance_rule_create(request: HttpRequest) -> HttpResponse:
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo gestire le regole manutenzione.")
        return redirect("assets:asset_list")

    selected_category_id = _as_int(request.GET.get("category"), default=0)
    selected_template_id = _as_int(request.GET.get("template"), default=0)
    initial = {}
    if selected_category_id:
        initial["asset_category"] = selected_category_id
    if selected_template_id:
        initial["intervention_template"] = selected_template_id

    if request.method == "POST":
        form = MaintenanceRuleForm(request.POST)
        if form.is_valid():
            rule = form.save()
            log_action(
                request,
                "create_maintenance_rule",
                "assets",
                {
                    "rule_id": rule.id,
                    "asset_category_id": rule.asset_category_id,
                    "template_id": rule.intervention_template_id,
                    "threshold_type": rule.threshold_type,
                    "threshold_value": rule.threshold_value,
                },
            )
            messages.success(request, "Regola manutenzione creata.")
            return redirect(
                _maintenance_rule_list_page_url(
                    category_id=rule.asset_category_id,
                    template_id=rule.intervention_template_id,
                )
            )
    else:
        form = MaintenanceRuleForm(initial=initial)

    form_state = _maintenance_rule_form_state(form, is_edit=False)

    return render(
        request,
        "assets/pages/maintenance_rule_form.html",
        {
            "page_title": "Nuova regola manutenzione",
            "form": form,
            "maintenance_rule_form_state": form_state,
            "is_edit": False,
            "back_url": _maintenance_rule_list_page_url(
                category_id=selected_category_id,
                template_id=selected_template_id,
            ),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:maintenance_rule_list"),
                new_url=reverse("assets:maintenance_rule_create"),
                new_label="+ Nuova regola",
                search_placeholder="Ricerca rapida per regola, template o categoria",
            ),
        },
    )


@login_required
def maintenance_rule_edit(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo gestire le regole manutenzione.")
        return redirect("assets:asset_list")
    if id is None:
        return redirect("assets:maintenance_rule_list")

    rule = get_object_or_404(
        MaintenanceRule.objects.select_related("asset_category", "intervention_template"),
        pk=id,
    )
    if request.method == "POST":
        form = MaintenanceRuleForm(request.POST, instance=rule)
        if form.is_valid():
            rule = form.save()
            log_action(
                request,
                "update_maintenance_rule",
                "assets",
                {
                    "rule_id": rule.id,
                    "asset_category_id": rule.asset_category_id,
                    "template_id": rule.intervention_template_id,
                    "threshold_type": rule.threshold_type,
                    "threshold_value": rule.threshold_value,
                },
            )
            messages.success(request, "Regola manutenzione aggiornata.")
            return redirect(
                _maintenance_rule_list_page_url(
                    category_id=rule.asset_category_id,
                    template_id=rule.intervention_template_id,
                )
            )
    else:
        form = MaintenanceRuleForm(instance=rule)

    form_state = _maintenance_rule_form_state(form, is_edit=True)

    return render(
        request,
        "assets/pages/maintenance_rule_form.html",
        {
            "page_title": f"Modifica regola {rule.intervention_template.label}",
            "form": form,
            "maintenance_rule_form_state": form_state,
            "rule": rule,
            "is_edit": True,
            "back_url": _maintenance_rule_list_page_url(
                category_id=rule.asset_category_id,
                template_id=rule.intervention_template_id,
            ),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:maintenance_rule_list"),
                new_url=reverse("assets:maintenance_rule_create"),
                new_label="+ Nuova regola",
                search_placeholder="Ricerca rapida per regola, template o categoria",
            ),
        },
    )


def _asset_maintenance_status_payload(status: str) -> dict[str, str]:
    if status == "disabled":
        return {"label": "Disabilitata", "badge_class": "muted"}
    if status == "overridden":
        return {"label": "Personalizzata", "badge_class": "warn"}
    return {"label": "Ereditata", "badge_class": "ok"}


@login_required
def asset_maintenance_rule_list(request: HttpRequest, asset_id: int) -> HttpResponse:
    asset = get_object_or_404(Asset.objects.select_related("asset_category"), pk=asset_id)
    focus_rule_id = _as_int(request.GET.get("focus_rule"), default=0)
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo gestire le regole manutenzione per asset.")
        return redirect("assets:asset_view", id=asset.id)

    if request.method == "POST":
        action = _clean_string(request.POST.get("action"))
        base_rule = get_object_or_404(
            MaintenanceRule.objects.select_related("asset_category", "intervention_template"),
            pk=_as_int(request.POST.get("base_rule_id"), default=0),
            asset_category_id=asset.asset_category_id,
        )
        if action == "update_rule_execution":
            raw_execution_date = _clean_string(request.POST.get("last_execution_date"))
            execution_notes = _clean_string(request.POST.get("last_execution_notes"))
            try:
                execution_date = datetime.strptime(raw_execution_date, "%Y-%m-%d").date()
            except ValueError:
                execution_date = None
            if execution_date is None:
                messages.error(request, "Inserisci una data valida per l'ultima esecuzione.")
            else:
                upsert_asset_maintenance_rule_state(
                    asset=asset,
                    base_rule=base_rule,
                    executed_on=execution_date,
                    notes=execution_notes,
                )
                log_action(
                    request,
                    "update_asset_maintenance_execution",
                    "assets",
                    {
                        "asset_id": asset.id,
                        "base_rule_id": base_rule.id,
                        "last_execution_date": execution_date.isoformat(),
                    },
                )
                messages.success(request, "Storico manutenzione aggiornato.")
            return redirect(_asset_maintenance_rule_list_page_url(asset_id=asset.id, focus_rule_id=base_rule.id))
        if action == "clear_rule_execution":
            AssetMaintenanceRuleState.objects.filter(asset=asset, base_rule=base_rule).delete()
            log_action(
                request,
                "clear_asset_maintenance_execution",
                "assets",
                {
                    "asset_id": asset.id,
                    "base_rule_id": base_rule.id,
                },
            )
            messages.success(request, "Storico manutenzione azzerato.")
            return redirect(_asset_maintenance_rule_list_page_url(asset_id=asset.id, focus_rule_id=base_rule.id))

    resolved_rows = resolve_asset_maintenance_rules(asset)
    schedule_rows = build_day_based_maintenance_schedule_rows(
        asset_queryset=Asset.objects.filter(pk=asset.id).select_related("asset_category"),
    )
    schedule_by_rule_id = {row["base_rule"].id: row for row in schedule_rows}
    rule_rows: list[dict[str, object]] = []
    for row in resolved_rows:
        status_payload = _asset_maintenance_status_payload(str(row["status"]))
        override = row["override"]
        schedule_row = schedule_by_rule_id.get(row["base_rule"].id)
        row_payload = {
            **row,
            "status_label": status_payload["label"],
            "status_badge_class": status_payload["badge_class"],
            "last_execution_date": schedule_row["last_execution_date"] if schedule_row else None,
            "last_execution_notes": schedule_row["last_execution_notes"] if schedule_row else "",
            "last_execution_workorder": schedule_row["last_execution_workorder"] if schedule_row else None,
            "due_date": schedule_row["due_date"] if schedule_row else None,
            "schedule_status": schedule_row["schedule_status"] if schedule_row else "",
            "schedule_label": schedule_row["schedule_label"] if schedule_row else "Non operativo",
            "schedule_badge_class": schedule_row["schedule_badge_class"] if schedule_row else "muted",
            "effective_warning_days": row.get("effective_warning_days") or 0,
            "create_url": _asset_maintenance_rule_override_create_page_url(asset_id=asset.id, rule_id=row["base_rule"].id),
            "workorder_create_url": _workorder_create_page_url(
                asset_id=asset.id,
                rule_id=row["base_rule"].id,
                source="maintenance_rules",
            ),
            "focus_url": _asset_maintenance_rule_list_page_url(asset_id=asset.id, focus_rule_id=row["base_rule"].id),
            "edit_url": (
                _asset_maintenance_rule_override_edit_page_url(asset_id=asset.id, override_id=override.id)
                if override is not None
                else ""
            ),
            "reset_url": (
                _asset_maintenance_rule_override_reset_page_url(asset_id=asset.id, override_id=override.id)
                if override is not None
                else ""
            ),
            "is_focus": row["base_rule"].id == focus_rule_id,
        }
        rule_rows.append(row_payload)

    return render(
        request,
        "assets/pages/maintenance_asset_rule_list.html",
        {
            "page_title": f"Regole manutenzione asset {asset.asset_tag}",
            "asset": asset,
            "rule_rows": rule_rows,
            "rule_total": len(rule_rows),
            "overridden_rule_count": sum(1 for row in rule_rows if row["status"] == "overridden"),
            "disabled_rule_count": sum(1 for row in rule_rows if row["status"] == "disabled"),
            "scheduled_rule_count": sum(1 for row in rule_rows if row.get("schedule_status") not in {"", "missing"}),
            "missing_execution_count": sum(1 for row in rule_rows if row.get("schedule_status") == "missing"),
            "focus_rule_id": focus_rule_id,
            "asset_detail_url": reverse("assets:asset_view", kwargs={"id": asset.id}),
            "asset_has_category": bool(asset.asset_category_id),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=_asset_maintenance_rule_list_page_url(asset_id=asset.id),
                search_placeholder="Ricerca contestuale disponibile dal dettaglio asset",
            ),
        },
    )


@login_required
def asset_maintenance_rule_override_create(request: HttpRequest, asset_id: int, rule_id: int) -> HttpResponse:
    asset = get_object_or_404(Asset.objects.select_related("asset_category"), pk=asset_id)
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo personalizzare le regole manutenzione degli asset.")
        return redirect("assets:asset_view", id=asset.id)

    base_rule = get_object_or_404(
        MaintenanceRule.objects.select_related("asset_category", "intervention_template"),
        pk=rule_id,
    )
    if not asset.asset_category_id or asset.asset_category_id != base_rule.asset_category_id:
        messages.error(request, "La regola selezionata non appartiene alla categoria dell'asset.")
        return redirect(_asset_maintenance_rule_list_page_url(asset_id=asset.id))

    existing_override = MaintenanceRuleAssetOverride.objects.filter(asset=asset, base_rule=base_rule).first()
    if existing_override is not None:
        messages.info(request, "Esiste gia una personalizzazione per questa regola. Puoi modificarla direttamente.")
        return redirect(_asset_maintenance_rule_override_edit_page_url(asset_id=asset.id, override_id=existing_override.id))

    if request.method == "POST":
        form = MaintenanceRuleAssetOverrideForm(
            request.POST,
            locked_asset=asset,
            locked_base_rule=base_rule,
        )
        if form.is_valid():
            override = form.save()
            log_action(
                request,
                "create_asset_maintenance_override",
                "assets",
                {
                    "override_id": override.id,
                    "asset_id": override.asset_id,
                    "base_rule_id": override.base_rule_id,
                    "is_disabled": override.is_disabled,
                },
            )
            messages.success(request, "Personalizzazione regola salvata.")
            return redirect(_asset_maintenance_rule_list_page_url(asset_id=asset.id))
    else:
        form = MaintenanceRuleAssetOverrideForm(
            locked_asset=asset,
            locked_base_rule=base_rule,
        )

    return render(
        request,
        "assets/pages/maintenance_asset_rule_override_form.html",
        {
            "page_title": f"Personalizza regola {base_rule.intervention_template.label}",
            "asset": asset,
            "base_rule": base_rule,
            "form": form,
            "is_edit": False,
            "back_url": _asset_maintenance_rule_list_page_url(asset_id=asset.id),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=_asset_maintenance_rule_list_page_url(asset_id=asset.id),
                search_placeholder="Ricerca contestuale disponibile dal dettaglio asset",
            ),
        },
    )


@login_required
def asset_maintenance_rule_override_edit(request: HttpRequest, asset_id: int, id: int) -> HttpResponse:
    asset = get_object_or_404(Asset.objects.select_related("asset_category"), pk=asset_id)
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo personalizzare le regole manutenzione degli asset.")
        return redirect("assets:asset_view", id=asset.id)

    override = get_object_or_404(
        MaintenanceRuleAssetOverride.objects.select_related(
            "asset",
            "base_rule",
            "base_rule__asset_category",
            "base_rule__intervention_template",
            "override_intervention_template",
        ),
        pk=id,
        asset_id=asset.id,
    )

    if request.method == "POST":
        form = MaintenanceRuleAssetOverrideForm(
            request.POST,
            instance=override,
            locked_asset=asset,
            locked_base_rule=override.base_rule,
        )
        if form.is_valid():
            override = form.save()
            log_action(
                request,
                "update_asset_maintenance_override",
                "assets",
                {
                    "override_id": override.id,
                    "asset_id": override.asset_id,
                    "base_rule_id": override.base_rule_id,
                    "is_disabled": override.is_disabled,
                },
            )
            messages.success(request, "Personalizzazione regola aggiornata.")
            return redirect(_asset_maintenance_rule_list_page_url(asset_id=asset.id))
    else:
        form = MaintenanceRuleAssetOverrideForm(
            instance=override,
            locked_asset=asset,
            locked_base_rule=override.base_rule,
        )

    return render(
        request,
        "assets/pages/maintenance_asset_rule_override_form.html",
        {
            "page_title": f"Modifica personalizzazione {override.base_rule.intervention_template.label}",
            "asset": asset,
            "base_rule": override.base_rule,
            "override": override,
            "form": form,
            "is_edit": True,
            "back_url": _asset_maintenance_rule_list_page_url(asset_id=asset.id),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=_asset_maintenance_rule_list_page_url(asset_id=asset.id),
                search_placeholder="Ricerca contestuale disponibile dal dettaglio asset",
            ),
        },
    )


@login_required
def asset_maintenance_rule_override_reset(request: HttpRequest, asset_id: int, id: int) -> HttpResponse:
    asset = get_object_or_404(Asset.objects.only("id"), pk=asset_id)
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo ripristinare le regole manutenzione degli asset.")
        return redirect("assets:asset_view", id=asset.id)

    override = get_object_or_404(
        MaintenanceRuleAssetOverride.objects.select_related("base_rule"),
        pk=id,
        asset_id=asset.id,
    )
    if request.method != "POST":
        messages.error(request, "Usa l'azione di ripristino dalla pagina delle regole asset.")
        return redirect(_asset_maintenance_rule_list_page_url(asset_id=asset.id))

    log_action(
        request,
        "reset_asset_maintenance_override",
        "assets",
        {
            "override_id": override.id,
            "asset_id": override.asset_id,
            "base_rule_id": override.base_rule_id,
        },
    )
    override.delete()
    messages.success(request, "Override rimosso. La regola e tornata ereditata.")
    return redirect(_asset_maintenance_rule_list_page_url(asset_id=asset.id))


def _maintenance_schedule_status_choices() -> list[tuple[str, str]]:
    return [
        ("all", "Tutte"),
        ("due", "Solo da gestire"),
        ("overdue", "Scadute"),
        ("warning", "In warning"),
        ("upcoming", "Programmate"),
        ("missing", "Senza storico"),
    ]


@login_required
def maintenance_schedule(request: HttpRequest) -> HttpResponse:
    can_manage_outlook_calendar = _is_assets_admin(request)
    calendar_user_choices: list[tuple[str, str]] = []
    calendar_user_details: dict[str, dict[str, str]] = {}
    if can_manage_outlook_calendar:
        calendar_user_choices, calendar_user_details = _legacy_employee_options()

    if request.method == "POST":
        action = _clean_string(request.POST.get("action"))
        if action == "create_outlook_calendar_event":
            redirect_url = _maintenance_schedule_redirect_from_request(request)
            if not can_manage_outlook_calendar:
                messages.error(request, "Solo gli admin assets possono creare eventi Outlook su calendari utente.")
                return redirect(redirect_url)

            asset_id = _as_int(request.POST.get("asset_id"), default=0)
            base_rule_id = _as_int(request.POST.get("base_rule_id"), default=0)
            target_legacy_user_id = _as_int(request.POST.get("target_legacy_user_id"), default=0)
            asset = Asset.objects.select_related("asset_category").filter(pk=asset_id).first()
            target_details = calendar_user_details.get(str(target_legacy_user_id))
            if asset is None:
                messages.error(request, "Asset non trovato.")
                return redirect(redirect_url)
            if not base_rule_id:
                messages.error(request, "Regola manutenzione non valida.")
                return redirect(redirect_url)
            if target_details is None:
                messages.error(request, "Seleziona un utente valido per il calendario Outlook.")
                return redirect(redirect_url)

            schedule_row = _maintenance_schedule_row_for_asset_rule(asset=asset, base_rule_id=base_rule_id)
            if schedule_row is None:
                messages.error(request, "Scadenza manutenzione non trovata per l'asset selezionato.")
                return redirect(redirect_url)
            if not isinstance(schedule_row.get("due_date"), date):
                messages.error(request, "Questa manutenzione non ha ancora una data scadenza calendarizzabile.")
                return redirect(redirect_url)

            try:
                entry, created = _create_asset_maintenance_calendar_event(
                    request=request,
                    asset=asset,
                    schedule_row=schedule_row,
                    target_legacy_user_id=target_legacy_user_id,
                    target_details=target_details,
                )
                target_label = entry.target_display_name or entry.target_email or f"utente {entry.target_legacy_user_id}"
                if created:
                    log_action(
                        request,
                        "create_maintenance_calendar_event",
                        "assets",
                        {
                            "asset_id": asset.id,
                            "base_rule_id": schedule_row["base_rule"].id,
                            "due_date": str(schedule_row["due_date"]),
                            "target_legacy_user_id": entry.target_legacy_user_id,
                            "target_email": entry.target_email,
                            "graph_event_id": entry.graph_event_id,
                        },
                    )
                    messages.success(
                        request,
                        f"Evento Outlook creato per {target_label} sulla scadenza del {entry.due_date:%d/%m/%Y}.",
                    )
                else:
                    messages.info(
                        request,
                        f"Esiste gia un evento Outlook per {target_label} su questa stessa scadenza.",
                    )
            except Exception as exc:
                messages.error(request, f"Creazione evento Outlook fallita: {exc}")
            return redirect(redirect_url)

    selected_asset_id = _as_int(request.GET.get("asset"), default=0)
    selected_asset = None
    if selected_asset_id:
        selected_asset = Asset.objects.select_related("asset_category").filter(pk=selected_asset_id).first()
    status_filter = _clean_string(request.GET.get("status")) or "all"
    category_id = _as_int(request.GET.get("category"), default=0)
    reparto_filter = _clean_string(request.GET.get("reparto"))
    coverage_filter = _clean_string(request.GET.get("coverage")) or "all"
    q = _clean_string(request.GET.get("q"))

    asset_qs = Asset.objects.select_related("asset_category").exclude(status=Asset.STATUS_RETIRED).order_by(
        "reparto",
        "name",
        "asset_tag",
    )
    if selected_asset is not None:
        asset_qs = asset_qs.filter(pk=selected_asset.id)
    if category_id:
        asset_qs = asset_qs.filter(asset_category_id=category_id)
    if reparto_filter:
        asset_qs = asset_qs.filter(reparto__iexact=reparto_filter)
    if q:
        asset_qs = asset_qs.filter(
            Q(asset_tag__icontains=q)
            | Q(name__icontains=q)
            | Q(reparto__icontains=q)
            | Q(asset_category__label__icontains=q)
        )

    schedule_rows = build_day_based_maintenance_schedule_rows(asset_queryset=asset_qs)
    primary_contract_by_asset_id: dict[int, AssistanceContract | None] = {}
    filtered_rows: list[dict[str, object]] = []
    for row in schedule_rows:
        asset = row["asset"]
        if asset.id not in primary_contract_by_asset_id:
            primary_contract_by_asset_id[asset.id] = get_primary_assistance_contract(asset)
        primary_contract = primary_contract_by_asset_id[asset.id]
        row["primary_contract"] = primary_contract
        row["contract_state"] = contract_state_payload(primary_contract) if primary_contract else None
        row["is_covered"] = primary_contract is not None
        row["asset_detail_url"] = reverse("assets:asset_view", kwargs={"id": asset.id})
        row["workorder_create_url"] = _workorder_create_page_url(
            asset_id=asset.id,
            rule_id=row["base_rule"].id,
            source="maintenance_schedule",
        )
        row["first_execution_url"] = _asset_maintenance_rule_list_page_url(
            asset_id=asset.id,
            focus_rule_id=row["base_rule"].id,
        )
        primary_action = _maintenance_row_primary_action(
            asset=asset,
            base_rule=row["base_rule"],
            schedule_status=str(row.get("schedule_status") or ""),
            source="maintenance_schedule",
        )
        row["primary_action_label"] = primary_action["label"]
        row["primary_action_url"] = primary_action["url"]
        row["contracts_url"] = _assistance_contracts_page_url(asset_id=asset.id)
        row["suggestions"] = _contextual_maintenance_suggestions(
            asset=asset,
            schedule_row=row,
            contract=primary_contract,
            source="maintenance_schedule",
        )

        if status_filter == "due" and row["schedule_status"] not in {"overdue", "warning", "missing"}:
            continue
        if status_filter in {"overdue", "warning", "upcoming", "missing"} and row["schedule_status"] != status_filter:
            continue
        if coverage_filter == "covered" and not row["is_covered"]:
            continue
        if coverage_filter == "uncovered" and row["is_covered"]:
            continue
        if q:
            q_value = q.casefold()
            searchable_chunks = [
                asset.asset_tag,
                asset.name,
                asset.reparto,
                getattr(getattr(asset, "asset_category", None), "label", ""),
                row["effective_intervention_template"].label,
            ]
            if not any(q_value in _clean_string(chunk).casefold() for chunk in searchable_chunks):
                continue
        filtered_rows.append(row)

    calendar_event_map: dict[tuple[int, int, date], list[AssetCalendarEvent]] = defaultdict(list)
    if filtered_rows:
        asset_ids = set()
        base_rule_ids = set()
        due_dates = set()
        for row in filtered_rows:
            due_date = row.get("due_date")
            if not isinstance(due_date, date):
                continue
            asset_ids.add(row["asset"].id)
            base_rule_ids.add(row["base_rule"].id)
            due_dates.add(due_date)
        if asset_ids and base_rule_ids and due_dates:
            for entry in (
                AssetCalendarEvent.objects.filter(
                    event_kind=AssetCalendarEvent.KIND_MAINTENANCE,
                    asset_id__in=asset_ids,
                    maintenance_rule_id__in=base_rule_ids,
                    due_date__in=due_dates,
                )
                .order_by("target_display_name", "target_email", "created_at", "id")
            ):
                if entry.maintenance_rule_id:
                    calendar_event_map[(entry.asset_id, entry.maintenance_rule_id, entry.due_date)].append(entry)

    for row in filtered_rows:
        due_date = row.get("due_date")
        if isinstance(due_date, date):
            row["calendar_event_rows"] = list(
                calendar_event_map.get((row["asset"].id, row["base_rule"].id, due_date), [])
            )
        else:
            row["calendar_event_rows"] = []
        row["default_calendar_user_id"] = _asset_calendar_default_user_id(row["asset"], calendar_user_details)

    reparto_options = [
        value
        for value in Asset.objects.exclude(reparto="")
        .order_by("reparto")
        .values_list("reparto", flat=True)
        .distinct()
    ]

    return render(
        request,
        "assets/pages/maintenance_schedule.html",
        {
            "page_title": "Prossime manutenzioni",
            "selected_asset": selected_asset,
            "schedule_rows": filtered_rows,
            "schedule_total": len(filtered_rows),
            "overdue_count": sum(1 for row in filtered_rows if row["schedule_status"] == "overdue"),
            "warning_count": sum(1 for row in filtered_rows if row["schedule_status"] == "warning"),
            "upcoming_count": sum(1 for row in filtered_rows if row["schedule_status"] == "upcoming"),
            "missing_count": sum(1 for row in filtered_rows if row["schedule_status"] == "missing"),
            "covered_count": sum(1 for row in filtered_rows if row["is_covered"]),
            "uncovered_count": sum(1 for row in filtered_rows if not row["is_covered"]),
            "category_options": AssetCategory.objects.filter(is_active=True).order_by("sort_order", "label", "id"),
            "selected_category_id": category_id,
            "reparto_options": reparto_options,
            "reparto_filter": reparto_filter,
            "status_filter": status_filter,
            "status_choices": _maintenance_schedule_status_choices(),
            "coverage_filter": coverage_filter,
            "q": q,
            "clear_filters_url": _maintenance_schedule_page_url(asset_id=selected_asset.id if selected_asset else 0),
            "can_manage_outlook_calendar": can_manage_outlook_calendar,
            "outlook_calendar_ready": _outlook_calendar_graph_ready() if can_manage_outlook_calendar else False,
            "calendar_user_choices": calendar_user_choices,
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=_maintenance_schedule_page_url(asset_id=selected_asset.id if selected_asset else 0),
                new_url=reverse("assets:asset_create"),
                new_label="+ Nuovo asset",
                search_placeholder="Ricerca manutenzioni per asset, reparto o intervento",
            ),
        },
    )


@login_required
def assistance_contract_list(request: HttpRequest) -> HttpResponse:
    from anagrafica.models import Fornitore

    today = timezone.localdate()
    can_manage_contracts = _is_assets_admin(request)
    can_manage_outlook_calendar = can_manage_contracts
    calendar_user_choices: list[tuple[str, str]] = []
    calendar_user_details: dict[str, dict[str, str]] = {}
    if can_manage_outlook_calendar:
        calendar_user_choices, calendar_user_details = _legacy_employee_options()

    selected_asset_id = _as_int(request.POST.get("asset_id") or request.GET.get("asset"), default=0)
    supplier_filter = _as_int(request.GET.get("supplier"), default=0)
    state_filter = _clean_string(request.GET.get("state")) or "all"
    scope_filter = _clean_string(request.GET.get("scope")) or "all"
    q = _clean_string(request.GET.get("q"))
    selected_asset = None
    if selected_asset_id:
        selected_asset = Asset.objects.select_related("asset_category").filter(pk=selected_asset_id).first()

    edit_id = _as_int(request.POST.get("edit_id") or request.GET.get("edit"), default=0)
    edit_contract = None
    if edit_id:
        edit_contract = (
            AssistanceContract.objects.select_related("supplier", "asset", "asset_category", "document")
            .filter(pk=edit_id)
            .first()
        )

    form = AssistanceContractForm(
        instance=edit_contract,
        locked_asset=selected_asset if selected_asset is not None and edit_contract is None else None,
    )

    if request.method == "POST":
        action = _clean_string(request.POST.get("action"))
        if action == "create_outlook_calendar_event":
            redirect_url = _assistance_contract_redirect_from_request(request)
            if not can_manage_outlook_calendar:
                messages.error(request, "Solo gli admin assets possono creare eventi Outlook su calendari utente.")
                return redirect(redirect_url)
            if selected_asset is None:
                messages.error(
                    request,
                    "Per i contratti assistenza seleziona prima un asset: l'evento Outlook viene creato sul contesto asset.",
                )
                return redirect(redirect_url)

            contract_id = _as_int(request.POST.get("contract_id"), default=0)
            target_legacy_user_id = _as_int(request.POST.get("target_legacy_user_id"), default=0)
            contract = (
                AssistanceContract.objects.select_related("supplier", "asset", "asset_category", "document")
                .filter(pk=contract_id)
                .first()
            )
            target_details = calendar_user_details.get(str(target_legacy_user_id))
            if contract is None:
                messages.error(request, "Contratto assistenza non trovato.")
                return redirect(redirect_url)
            if target_details is None:
                messages.error(request, "Seleziona un utente valido per il calendario Outlook.")
                return redirect(redirect_url)
            if not contract.applies_to_asset(selected_asset):
                messages.error(request, "Il contratto selezionato non si applica all'asset attualmente filtrato.")
                return redirect(redirect_url)
            if not isinstance(contract.end_date, date):
                messages.error(request, "Questo contratto non ha una scadenza calendarizzabile.")
                return redirect(redirect_url)

            try:
                entry, created = _create_asset_assistance_contract_calendar_event(
                    request=request,
                    asset=selected_asset,
                    contract=contract,
                    target_legacy_user_id=target_legacy_user_id,
                    target_details=target_details,
                )
                target_label = entry.target_display_name or entry.target_email or f"utente {entry.target_legacy_user_id}"
                if created:
                    log_action(
                        request,
                        "create_assistance_contract_calendar_event",
                        "assets",
                        {
                            "contract_id": contract.id,
                            "asset_id": selected_asset.id,
                            "due_date": str(contract.end_date),
                            "target_legacy_user_id": entry.target_legacy_user_id,
                            "target_email": entry.target_email,
                            "graph_event_id": entry.graph_event_id,
                        },
                    )
                    messages.success(
                        request,
                        f"Evento Outlook creato per {target_label} sulla scadenza del {entry.due_date:%d/%m/%Y}.",
                    )
                else:
                    messages.info(
                        request,
                        f"Esiste gia un evento Outlook per {target_label} su questa stessa scadenza.",
                    )
            except Exception as exc:
                messages.error(request, f"Creazione evento Outlook fallita: {exc}")
            return redirect(redirect_url)

        if action in {"create_assistance_contract", "update_assistance_contract", "delete_assistance_contract"} and not can_manage_contracts:
            messages.error(request, "Solo admin puo gestire i contratti assistenza.")
            return redirect(
                _assistance_contracts_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    supplier_filter=supplier_filter,
                    state=state_filter,
                    scope=scope_filter,
                    q=q,
                )
            )

        if action in {"create_assistance_contract", "update_assistance_contract"}:
            instance = edit_contract if action == "update_assistance_contract" else None
            form = AssistanceContractForm(
                request.POST,
                instance=instance,
                locked_asset=selected_asset if selected_asset is not None and instance is None else None,
            )
            if form.is_valid():
                contract = form.save()
                log_action(
                    request,
                    "update_assistance_contract" if instance is not None else "create_assistance_contract",
                    "assets",
                    {
                        "contract_id": contract.id,
                        "supplier_id": contract.supplier_id,
                        "asset_id": contract.asset_id,
                        "asset_category_id": contract.asset_category_id,
                    },
                )
                messages.success(
                    request,
                    "Contratto assistenza aggiornato." if instance is not None else "Contratto assistenza creato.",
                )
                return redirect(
                    _assistance_contracts_page_url(
                        asset_id=selected_asset.id if selected_asset else 0,
                        supplier_filter=supplier_filter,
                        state=state_filter,
                        scope=scope_filter,
                        q=q,
                    )
                )
        elif action == "delete_assistance_contract":
            contract = AssistanceContract.objects.filter(
                pk=_as_int(request.POST.get("contract_id"), default=0)
            ).first()
            if contract is None:
                messages.error(request, "Contratto assistenza non trovato.")
            else:
                log_action(
                    request,
                    "delete_assistance_contract",
                    "assets",
                    {
                        "contract_id": contract.id,
                        "supplier_id": contract.supplier_id,
                    },
                )
                contract.delete()
                messages.success(request, "Contratto assistenza eliminato.")
            return redirect(
                _assistance_contracts_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    supplier_filter=supplier_filter,
                    state=state_filter,
                    scope=scope_filter,
                    q=q,
                )
            )

    contract_rows: list[dict[str, object]] = []
    contract_qs = AssistanceContract.objects.select_related("supplier", "asset", "asset_category", "document").order_by(
        "-is_active",
        "end_date",
        "supplier__ragione_sociale",
        "title",
        "id",
    )
    if supplier_filter:
        contract_qs = contract_qs.filter(supplier_id=supplier_filter)
    if q:
        contract_qs = contract_qs.filter(
            Q(title__icontains=q)
            | Q(code__icontains=q)
            | Q(supplier__ragione_sociale__icontains=q)
            | Q(coverage_summary__icontains=q)
        )

    for contract in contract_qs:
        state = contract_state_payload(contract, today=today)
        scope = "asset" if contract.asset_id else "category" if contract.asset_category_id else "global"
        if selected_asset is not None and not contract.applies_to_asset(selected_asset):
            continue
        if state_filter != "all" and state["status"] != state_filter:
            continue
        if scope_filter != "all" and scope != scope_filter:
            continue
        scope_payload = _contract_scope_payload(contract)
        contract_rows.append(
            {
                "contract": contract,
                "state": state,
                "scope": scope,
                "scope_payload": scope_payload,
                "edit_url": _assistance_contracts_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    edit_id=contract.id,
                    supplier_filter=supplier_filter,
                    state=state_filter,
                    scope=scope_filter,
                    q=q,
                ),
                "supplier_url": reverse("anagrafica:fornitore_detail", kwargs={"fornitore_id": contract.supplier_id}),
                "asset_url": (
                    reverse("assets:asset_view", kwargs={"id": contract.asset_id})
                    if contract.asset_id
                    else ""
                ),
            }
        )

    contract_event_map: dict[int, list[AssetCalendarEvent]] = defaultdict(list)
    if selected_asset is not None and contract_rows:
        contract_ids = [row["contract"].id for row in contract_rows if isinstance(row["contract"].end_date, date)]
        if contract_ids:
            for entry in (
                AssetCalendarEvent.objects.select_related("assistance_contract")
                .filter(
                    event_kind=AssetCalendarEvent.KIND_ASSISTANCE_CONTRACT,
                    asset_id=selected_asset.id,
                    assistance_contract_id__in=contract_ids,
                )
                .order_by("target_display_name", "target_email", "created_at", "id")
            ):
                if entry.assistance_contract_id:
                    contract_event_map[entry.assistance_contract_id].append(entry)

    default_calendar_user_id = _asset_calendar_default_user_id(selected_asset, calendar_user_details)
    for row in contract_rows:
        contract = row["contract"]
        row["can_create_calendar_event"] = bool(
            selected_asset is not None
            and isinstance(contract.end_date, date)
            and contract.applies_to_asset(selected_asset)
        )
        row["calendar_event_rows"] = list(contract_event_map.get(contract.id, []))
        row["default_calendar_user_id"] = default_calendar_user_id

    periodic_cost_total = Decimal("0")
    for row in contract_rows:
        if row["state"]["status"] in {"active", "expiring"} and row["contract"].periodic_cost_eur is not None:
            periodic_cost_total += row["contract"].periodic_cost_eur

    return render(
        request,
        "assets/pages/assistance_contract_list.html",
        {
            "page_title": "Contratti assistenza",
            "form": form,
            "contract_rows": contract_rows,
            "contract_total": len(contract_rows),
            "active_count": sum(1 for row in contract_rows if row["state"]["status"] == "active"),
            "expiring_count": sum(1 for row in contract_rows if row["state"]["status"] == "expiring"),
            "expired_count": sum(1 for row in contract_rows if row["state"]["status"] == "expired"),
            "periodic_cost_total": periodic_cost_total,
            "can_manage_contracts": can_manage_contracts,
            "is_edit": edit_contract is not None,
            "edit_contract": edit_contract,
            "selected_asset": selected_asset,
            "supplier_filter": supplier_filter,
            "state_filter": state_filter,
            "scope_filter": scope_filter,
            "q": q,
            "supplier_options": Fornitore.objects.filter(is_active=True).order_by("ragione_sociale", "id"),
            "state_choices": [
                ("all", "Tutti"),
                ("active", "Attivi"),
                ("expiring", "In scadenza"),
                ("expired", "Scaduti"),
                ("inactive", "Disattivi"),
                ("scheduled", "Non ancora attivi"),
            ],
            "scope_choices": [
                ("all", "Tutti"),
                ("global", "Generali"),
                ("category", "Per categoria"),
                ("asset", "Per asset"),
            ],
            "clear_filters_url": _assistance_contracts_page_url(asset_id=selected_asset.id if selected_asset else 0),
            "can_manage_outlook_calendar": can_manage_outlook_calendar,
            "outlook_calendar_ready": _outlook_calendar_graph_ready() if can_manage_outlook_calendar else False,
            "calendar_user_choices": calendar_user_choices,
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=_assistance_contracts_page_url(asset_id=selected_asset.id if selected_asset else 0),
                search_placeholder="Ricerca contratti per fornitore, codice o copertura",
            ),
        },
        )


@login_required
def software_license_list(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    can_manage_licenses = _is_assets_admin(request)

    selected_asset_id = _as_int(request.POST.get("asset_id") or request.GET.get("asset"), default=0)
    selected_anagrafica_id = _as_int(request.POST.get("anagrafica_id") or request.GET.get("anagrafica"), default=0)
    category_filter = _clean_string(request.GET.get("category")) or "all"
    status_filter = _clean_string(request.GET.get("status")) or "all"
    assignee_filter = _clean_string(request.GET.get("assignee")) or "all"
    q = _clean_string(request.GET.get("q"))

    selected_asset = None
    if selected_asset_id:
        selected_asset = Asset.objects.select_related("asset_category").filter(pk=selected_asset_id).first()

    employee_choices, employee_details = _anagrafica_employee_options()
    selected_employee = None
    if selected_anagrafica_id:
        selected_employee = employee_details.get(str(selected_anagrafica_id))
        if selected_employee is None:
            try:
                row = (
                    AnagraficaDipendente.objects.filter(pk=selected_anagrafica_id)
                    .values(
                        "id",
                        "nome",
                        "cognome",
                        "aliasusername",
                        "reparto",
                        "email",
                        "email_notifica",
                        "utente_id",
                    )
                    .first()
                )
            except DatabaseError:
                row = None
            if row:
                display_name = " ".join(
                    [value for value in [_clean_string(row.get("cognome")), _clean_string(row.get("nome"))] if value]
                ).strip() or _clean_string(row.get("aliasusername")) or f"Dipendente #{selected_anagrafica_id}"
                selected_employee = {
                    "display_name": display_name,
                    "email": _clean_string(row.get("email")),
                    "notification_email": _clean_string(row.get("email_notifica")),
                    "reparto": _clean_string(row.get("reparto")),
                    "legacy_user_id": str(row.get("utente_id") or "").strip(),
                }
                if str(selected_anagrafica_id) not in employee_details:
                    employee_details[str(selected_anagrafica_id)] = dict(selected_employee)
                    employee_choices.append((str(selected_anagrafica_id), display_name))

    edit_id = _as_int(request.POST.get("edit_id") or request.GET.get("edit"), default=0)
    edit_license = None
    if edit_id:
        edit_license = (
            SoftwareLicense.objects.select_related("asset")
            .filter(pk=edit_id)
            .first()
        )

    form = SoftwareLicenseForm(
        instance=edit_license,
        locked_asset=selected_asset if selected_asset is not None and edit_license is None else None,
        locked_employee_id=str(selected_anagrafica_id) if selected_anagrafica_id and edit_license is None else "",
        employee_choices=employee_choices,
        employee_details=employee_details,
    )

    if request.method == "POST":
        action = _clean_string(request.POST.get("action"))
        if action in {"create_software_license", "update_software_license", "delete_software_license"} and not can_manage_licenses:
            messages.error(request, "Solo admin puo gestire le licenze software.")
            return redirect(
                _software_licenses_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    anagrafica_id=selected_anagrafica_id,
                    category=category_filter,
                    status=status_filter,
                    assignee=assignee_filter,
                    q=q,
                )
            )

        if action in {"create_software_license", "update_software_license"}:
            instance = edit_license if action == "update_software_license" else None
            form = SoftwareLicenseForm(
                request.POST,
                instance=instance,
                locked_asset=selected_asset if selected_asset is not None and instance is None else None,
                locked_employee_id=str(selected_anagrafica_id) if selected_anagrafica_id and instance is None else "",
                employee_choices=employee_choices,
                employee_details=employee_details,
            )
            if form.is_valid():
                license_row = form.save()
                log_action(
                    request,
                    "update_software_license" if instance is not None else "create_software_license",
                    "assets",
                    {
                        "license_id": license_row.id,
                        "asset_id": license_row.asset_id,
                        "assigned_anagrafica_id": license_row.assigned_anagrafica_id,
                        "assigned_legacy_user_id": license_row.assigned_legacy_user_id,
                    },
                )
                messages.success(
                    request,
                    "Licenza software aggiornata." if instance is not None else "Licenza software creata.",
                )
                return redirect(
                    _software_licenses_page_url(
                        asset_id=selected_asset.id if selected_asset else 0,
                        anagrafica_id=selected_anagrafica_id,
                        category=category_filter,
                        status=status_filter,
                        assignee=assignee_filter,
                        q=q,
                    )
                )
        elif action == "delete_software_license":
            license_row = SoftwareLicense.objects.filter(
                pk=_as_int(request.POST.get("license_id"), default=0)
            ).first()
            if license_row is None:
                messages.error(request, "Licenza software non trovata.")
            else:
                log_action(
                    request,
                    "delete_software_license",
                    "assets",
                    {
                        "license_id": license_row.id,
                        "asset_id": license_row.asset_id,
                        "assigned_anagrafica_id": license_row.assigned_anagrafica_id,
                    },
                )
                license_row.delete()
                messages.success(request, "Licenza software eliminata.")
            return redirect(
                _software_licenses_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    anagrafica_id=selected_anagrafica_id,
                    category=category_filter,
                    status=status_filter,
                    assignee=assignee_filter,
                    q=q,
                )
            )

    license_qs = SoftwareLicense.objects.select_related("asset").order_by(
        "category",
        "vendor",
        "product_name",
        "id",
    )
    if selected_asset is not None:
        license_qs = license_qs.filter(asset_id=selected_asset.id)
    if selected_anagrafica_id:
        legacy_user_id = 0
        if selected_employee is not None:
            try:
                legacy_user_id = int(selected_employee.get("legacy_user_id") or 0)
            except (TypeError, ValueError):
                legacy_user_id = 0
        if legacy_user_id:
            license_qs = license_qs.filter(
                Q(assigned_anagrafica_id=selected_anagrafica_id) | Q(assigned_legacy_user_id=legacy_user_id)
            )
        else:
            license_qs = license_qs.filter(assigned_anagrafica_id=selected_anagrafica_id)
    if category_filter != "all":
        license_qs = license_qs.filter(category=category_filter)
    if assignee_filter == "asset":
        license_qs = license_qs.filter(asset_id__isnull=False)
    elif assignee_filter == "user":
        license_qs = license_qs.filter(assigned_anagrafica_id__isnull=False)
    elif assignee_filter == "unassigned":
        license_qs = license_qs.filter(asset_id__isnull=True, assigned_anagrafica_id__isnull=True)

    if status_filter != "all":
        if status_filter == "inactive":
            license_qs = license_qs.filter(is_active=False)
        else:
            license_qs = license_qs.filter(is_active=True)
            if status_filter == "expired":
                license_qs = license_qs.filter(expiry_date__lt=today)
            elif status_filter == "expiring":
                license_qs = license_qs.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=30))
            elif status_filter == "active":
                license_qs = license_qs.filter(
                    Q(expiry_date__isnull=True) | Q(expiry_date__gt=today + timedelta(days=30))
                )

    if q:
        license_qs = license_qs.filter(
            Q(product_name__icontains=q)
            | Q(vendor__icontains=q)
            | Q(edition__icontains=q)
            | Q(license_reference__icontains=q)
            | Q(account_email__icontains=q)
            | Q(assigned_to_display__icontains=q)
            | Q(asset__asset_tag__icontains=q)
            | Q(asset__name__icontains=q)
        )

    license_rows: list[dict[str, object]] = []
    for license_row in license_qs:
        state = _software_license_state_payload(license_row, today=today)
        license_rows.append(
            {
                "license": license_row,
                "state": state,
                "asset_url": (
                    reverse("assets:asset_view", kwargs={"id": license_row.asset_id})
                    if license_row.asset_id
                    else ""
                ),
                "employee_url": (
                    reverse("anagrafica:dipendente_detail", args=[license_row.assigned_anagrafica_id])
                    if license_row.assigned_anagrafica_id
                    else ""
                ),
                "edit_url": _software_licenses_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    anagrafica_id=selected_anagrafica_id,
                    edit_id=license_row.id,
                    category=category_filter,
                    status=status_filter,
                    assignee=assignee_filter,
                    q=q,
                ),
            }
        )

    return render(
        request,
        "assets/pages/software_license_list.html",
        {
            "page_title": "Licenze software",
            "form": form,
            "license_rows": license_rows,
            "license_total": len(license_rows),
            "active_count": sum(1 for row in license_rows if row["state"]["status"] == "active"),
            "expiring_count": sum(1 for row in license_rows if row["state"]["status"] == "expiring"),
            "expired_count": sum(1 for row in license_rows if row["state"]["status"] == "expired"),
            "inactive_count": sum(1 for row in license_rows if row["state"]["status"] == "inactive"),
            "unassigned_count": sum(
                1
                for row in license_rows
                if row["license"].assignment_scope == "unassigned"
            ),
            "can_manage_licenses": can_manage_licenses,
            "is_edit": edit_license is not None,
            "edit_license": edit_license,
            "selected_asset": selected_asset,
            "selected_employee": selected_employee,
            "selected_anagrafica_id": selected_anagrafica_id,
            "category_filter": category_filter,
            "status_filter": status_filter,
            "assignee_filter": assignee_filter,
            "q": q,
            "category_choices": [("all", "Tutte"), *SoftwareLicense.CATEGORY_CHOICES],
            "status_choices": [
                ("all", "Tutte"),
                ("active", "Attive"),
                ("expiring", "In scadenza"),
                ("expired", "Scadute"),
                ("inactive", "Disattive"),
            ],
            "assignee_choices": [
                ("all", "Tutte"),
                ("asset", "Assegnate a asset"),
                ("user", "Assegnate a dipendente"),
                ("unassigned", "Da assegnare"),
            ],
            "clear_filters_url": _software_licenses_page_url(
                asset_id=selected_asset.id if selected_asset else 0,
                anagrafica_id=selected_anagrafica_id,
            ),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=_software_licenses_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    anagrafica_id=selected_anagrafica_id,
                ),
                search_placeholder="Ricerca per prodotto, vendor, codice o asset",
            ),
        },
    )


@login_required
def work_machine_list(request: HttpRequest) -> HttpResponse:
    form = WorkMachineFilterForm(request.GET or None)
    machines_qs = Asset.objects.filter(asset_type=Asset.TYPE_WORK_MACHINE).select_related("work_machine")

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
                | Q(work_machine__accuracy_from__icontains=q)
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

    machines_filtered = machines_qs.order_by("reparto", "name", "asset_tag")

    allowed_rows = [10, 25, 50, 100]
    rows = _as_int(request.GET.get("rows"), default=25)
    if rows not in allowed_rows:
        rows = 25
    paginator = Paginator(machines_filtered, rows)
    page_number = _as_int(request.GET.get("page"), default=1)
    page_obj = paginator.get_page(page_number)
    machines = page_obj.object_list
    visible_count = machines_filtered.count()
    page_start = ((page_obj.number - 1) * rows + 1) if visible_count else 0
    page_end = (page_start + len(machines) - 1) if visible_count else 0

    rows_options = [
        {
            "value": value,
            "active": value == rows,
            "url": _query_url(request, rows=value, page=1),
        }
        for value in allowed_rows
    ]

    page_links = []
    if paginator.num_pages > 0:
        start_page = max(1, page_obj.number - 2)
        end_page = min(paginator.num_pages, page_obj.number + 2)
        for number in range(start_page, end_page + 1):
            page_links.append(
                {
                    "number": number,
                    "active": number == page_obj.number,
                    "url": _query_url(request, page=number, rows=rows),
                }
            )

    prev_page_url = _query_url(request, page=page_obj.previous_page_number(), rows=rows) if page_obj.has_previous() else ""
    next_page_url = _query_url(request, page=page_obj.next_page_number(), rows=rows) if page_obj.has_next() else ""

    machine_base_qs = Asset.objects.filter(asset_type=Asset.TYPE_WORK_MACHINE).select_related("work_machine")
    machine_total = machine_base_qs.count()
    reparto_totals = list(
        machine_base_qs.exclude(reparto="")
        .values("reparto")
        .annotate(total=Count("id"))
        .order_by("reparto")
    )
    reparto_suggestions = [row["reparto"] for row in reparto_totals if _clean_string(row.get("reparto"))]
    cnc_total = machine_base_qs.filter(work_machine__cnc_controlled=True).count()
    five_axes_total = machine_base_qs.filter(work_machine__five_axes=True).count()
    tcr_total = machine_base_qs.filter(work_machine__tcr_enabled=True).count()

    active_layouts = list(_plant_layout_queryset().filter(is_active=True).order_by("category", "name", "id"))
    selected_preview_category = _preferred_plant_layout_category(active_layouts)
    active_layout = next(
        (row for row in active_layouts if _clean_string(row.category).casefold() == _clean_string(selected_preview_category).casefold()),
        active_layouts[0] if active_layouts else None,
    )
    plant_layout_payload = _plant_layout_public_payload(active_layout)

    return render(
        request,
        "assets/pages/work_machine_list.html",
        {
            "page_title": "Macchine di lavoro",
            "filters_form": form,
            "machines": machines,
            "visible_count": visible_count,
            "machine_total": machine_total,
            "cnc_total": cnc_total,
            "five_axes_total": five_axes_total,
            "tcr_total": tcr_total,
            "reparto_totals": reparto_totals,
            "reparto_suggestions": reparto_suggestions,
            "today": timezone.localdate(),
            "rows": rows,
            "rows_options": rows_options,
            "page_obj": page_obj,
            "page_links": page_links,
            "prev_page_url": prev_page_url,
            "next_page_url": next_page_url,
            "page_start": page_start,
            "page_end": page_end,
            "active_layout": active_layout,
            "plant_layout_payload": plant_layout_payload,
            **_assets_shell_context(
                request,
                rows=rows,
                search_action=reverse("assets:work_machine_list"),
                new_url=reverse("assets:work_machine_create"),
                new_label="+ Nuova macchina",
                search_placeholder="Ricerca rapida per macchina, tag, reparto o seriale",
            ),
        },
    )


@login_required
def work_machine_dashboard(request: HttpRequest) -> HttpResponse:
    now = timezone.now()
    today = timezone.localdate()
    reparto_filter = _clean_string(request.GET.get("reparto"))
    report_month_value = _clean_string(request.GET.get("month"))
    maintenance_month_dataset = _build_work_machine_maintenance_month_dataset(
        month_value=report_month_value,
        reparto_filter=reparto_filter,
        today=today,
    )

    machine_base_qs = Asset.objects.filter(asset_type=Asset.TYPE_WORK_MACHINE).select_related("work_machine").prefetch_related("documents")
    if reparto_filter:
        machine_base_qs = machine_base_qs.filter(reparto=reparto_filter)

    workorders_base = WorkOrder.objects.select_related("asset").filter(asset__asset_type=Asset.TYPE_WORK_MACHINE)
    if reparto_filter:
        workorders_base = workorders_base.filter(asset__reparto=reparto_filter)

    open_workorders = workorders_base.filter(status=WorkOrder.STATUS_OPEN).order_by("opened_at", "id")
    overdue_workorders = open_workorders.filter(opened_at__lt=now - timedelta(days=21))
    recent_done_workorders = workorders_base.filter(
        status=WorkOrder.STATUS_DONE,
        closed_at__gte=now - timedelta(days=60),
    ).order_by("-closed_at", "-id")

    machine_rows = list(machine_base_qs.order_by("reparto", "name", "asset_tag"))
    manuals_count = 0
    specs_count = 0
    overdue_maintenance: list[dict[str, object]] = []
    warning_maintenance: list[dict[str, object]] = []
    missing_maintenance: list[dict[str, object]] = []
    for asset in machine_rows:
        extra = asset.extra_columns if isinstance(asset.extra_columns, dict) else {}
        raw_docs = extra.get("documents")
        categories = set()
        if isinstance(raw_docs, list):
            for row in raw_docs:
                if not isinstance(row, dict):
                    continue
                categories.add(_clean_string(str(row.get("category") or "SPECIFICHE")).upper())
        for uploaded in asset.documents.all():
            categories.add(uploaded.category)
        if "MANUALI" in categories:
            manuals_count += 1
        if "SPECIFICHE" in categories:
            specs_count += 1
        machine = getattr(asset, "work_machine", None)
        if not isinstance(machine, WorkMachine):
            continue
        maintenance_state = _work_machine_maintenance_state(machine, today)
        payload = {"asset": asset, "machine": machine, "state": maintenance_state}
        if maintenance_state["status"] == "overdue":
            overdue_maintenance.append(payload)
        elif maintenance_state["status"] == "warning":
            warning_maintenance.append(payload)
        elif maintenance_state["status"] == "missing":
            missing_maintenance.append(payload)

    overdue_maintenance.sort(key=lambda row: row["state"]["date"] or today)
    warning_maintenance.sort(key=lambda row: row["state"]["date"] or today)
    missing_maintenance.sort(key=lambda row: (row["asset"].reparto or "", row["asset"].name or ""))

    total_machines = len(machine_rows)
    reparto_totals = list(
        Asset.objects.filter(asset_type=Asset.TYPE_WORK_MACHINE)
        .exclude(reparto="")
        .values("reparto")
        .annotate(total=Count("id"))
        .order_by("reparto")
    )

    return render(
        request,
        "assets/pages/work_machine_dashboard.html",
        {
            "page_title": "Dashboard officina",
            "reparto_filter": reparto_filter,
            "reparto_totals": reparto_totals,
            "total_machines": total_machines,
            "in_use_machines": sum(1 for asset in machine_rows if asset.status == Asset.STATUS_IN_USE),
            "in_repair_machines": sum(1 for asset in machine_rows if asset.status == Asset.STATUS_IN_REPAIR),
            "manuals_count": manuals_count,
            "specs_count": specs_count,
            "open_workorders": open_workorders[:10],
            "open_count": open_workorders.count(),
            "overdue_workorders": overdue_workorders[:10],
            "overdue_count": overdue_workorders.count(),
            "overdue_workorder_ids": set(overdue_workorders.values_list("id", flat=True)),
            "recent_done_workorders": recent_done_workorders[:10],
            "recent_done_count": recent_done_workorders.count(),
            "overdue_maintenance": overdue_maintenance[:12],
            "overdue_maintenance_count": len(overdue_maintenance),
            "warning_maintenance": warning_maintenance[:12],
            "warning_maintenance_count": len(warning_maintenance),
            "missing_maintenance": missing_maintenance[:12],
            "missing_maintenance_count": len(missing_maintenance),
            "due_count": len(overdue_maintenance) + len(warning_maintenance),
            "maintenance_month_count": maintenance_month_dataset["total_count"],
            "maintenance_month_label": maintenance_month_dataset["month_label"],
            "maintenance_month_code": maintenance_month_dataset["month_code"],
            "maintenance_month_pdf_url": _work_machine_maintenance_month_pdf_url(
                month_code=str(maintenance_month_dataset["month_code"]),
                reparto_filter=reparto_filter,
            ),
            "today": today,
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:work_machine_list"),
                new_url=reverse("assets:work_machine_create"),
                new_label="+ Nuova macchina",
                search_placeholder="Ricerca rapida per macchina, tag, reparto o seriale",
            ),
        },
    )


@login_required
def periodic_verification_list(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    can_manage_periodic_verifications = _is_assets_admin(request)
    can_manage_outlook_calendar = can_manage_periodic_verifications
    calendar_user_choices: list[tuple[str, str]] = []
    calendar_user_details: dict[str, dict[str, str]] = {}
    if can_manage_outlook_calendar:
        calendar_user_choices, calendar_user_details = _legacy_employee_options()

    selected_asset_id = _as_int(request.POST.get("asset_id") or request.GET.get("asset"), default=0)
    selected_asset = None
    if selected_asset_id:
        selected_asset = Asset.objects.filter(pk=selected_asset_id).only("id", "asset_tag", "name", "reparto").first()

    edit_id = _as_int(request.POST.get("edit_id") or request.GET.get("edit"), default=0)
    edit_verification = None
    if edit_id:
        edit_verification = (
            PeriodicVerification.objects.select_related("supplier", "created_by")
            .prefetch_related("assets")
            .filter(pk=edit_id)
            .first()
        )

    form = PeriodicVerificationForm(
        instance=edit_verification,
        actor=request.user,
        preselected_asset_id=selected_asset.id if selected_asset else 0,
    )

    if request.method == "POST":
        action = _clean_string(request.POST.get("action"))
        if action == "create_outlook_calendar_event":
            redirect_url = _periodic_verification_redirect_from_request(request)
            if not can_manage_outlook_calendar:
                messages.error(request, "Solo gli admin assets possono creare eventi Outlook su calendari utente.")
                return redirect(redirect_url)
            if selected_asset is None:
                messages.error(
                    request,
                    "Per la manutenzione periodica seleziona prima un asset: l'evento Outlook viene creato sul contesto asset.",
                )
                return redirect(redirect_url)

            verification_id = _as_int(request.POST.get("verification_id"), default=0)
            target_legacy_user_id = _as_int(request.POST.get("target_legacy_user_id"), default=0)
            verification = (
                PeriodicVerification.objects.select_related("supplier", "created_by")
                .prefetch_related("assets")
                .filter(pk=verification_id)
                .first()
            )
            target_details = calendar_user_details.get(str(target_legacy_user_id))
            if verification is None:
                messages.error(request, "Piano di manutenzione periodica non trovato.")
                return redirect(redirect_url)
            if target_details is None:
                messages.error(request, "Seleziona un utente valido per il calendario Outlook.")
                return redirect(redirect_url)
            if not verification.assets.filter(pk=selected_asset.id).exists():
                messages.error(request, "La manutenzione periodica selezionata non e collegata all'asset attualmente filtrato.")
                return redirect(redirect_url)
            if not isinstance(verification.next_verification_date, date):
                messages.error(request, "Questa manutenzione periodica non ha una prossima data calendarizzabile.")
                return redirect(redirect_url)

            try:
                entry, created = _create_asset_periodic_verification_calendar_event(
                    request=request,
                    asset=selected_asset,
                    verification=verification,
                    target_legacy_user_id=target_legacy_user_id,
                    target_details=target_details,
                )
                target_label = entry.target_display_name or entry.target_email or f"utente {entry.target_legacy_user_id}"
                if created:
                    log_action(
                        request,
                        "create_periodic_verification_calendar_event",
                        "assets",
                        {
                            "verification_id": verification.id,
                            "asset_id": selected_asset.id,
                            "due_date": str(verification.next_verification_date),
                            "target_legacy_user_id": entry.target_legacy_user_id,
                            "target_email": entry.target_email,
                            "graph_event_id": entry.graph_event_id,
                        },
                    )
                    messages.success(
                        request,
                        f"Evento Outlook creato per {target_label} sulla scadenza del {entry.due_date:%d/%m/%Y}.",
                    )
                else:
                    messages.info(
                        request,
                        f"Esiste gia un evento Outlook per {target_label} su questa stessa scadenza.",
                    )
            except Exception as exc:
                messages.error(request, f"Creazione evento Outlook fallita: {exc}")
            return redirect(redirect_url)

        if action in {"create_periodic_verification", "update_periodic_verification", "delete_periodic_verification"} and not can_manage_periodic_verifications:
            messages.error(request, "Solo admin puo gestire la manutenzione periodica.")
            return redirect(_periodic_verifications_page_url(asset_id=selected_asset.id if selected_asset else 0))

        if action in {"create_periodic_verification", "update_periodic_verification"}:
            instance = edit_verification if action == "update_periodic_verification" else None
            if action == "update_periodic_verification" and instance is None:
                messages.error(request, "Piano di manutenzione periodica non trovato.")
                return redirect(_periodic_verifications_page_url(asset_id=selected_asset.id if selected_asset else 0))
            form = PeriodicVerificationForm(
                request.POST,
                instance=instance,
                actor=request.user,
                preselected_asset_id=selected_asset.id if selected_asset else 0,
            )
            if form.is_valid():
                verification = form.save()
                message = (
                    "Manutenzione periodica aggiornata."
                    if instance is not None
                    else "Manutenzione periodica creata."
                )
                messages.success(request, message)
                return redirect(_periodic_verifications_page_url(asset_id=selected_asset.id if selected_asset else 0))
        elif action == "delete_periodic_verification":
            verification_id = _as_int(request.POST.get("verification_id"), default=0)
            verification = PeriodicVerification.objects.filter(pk=verification_id).first()
            if verification is None:
                messages.error(request, "Piano di manutenzione periodica non trovato.")
            else:
                verification_name = verification.name
                verification.delete()
                messages.success(request, f'Manutenzione periodica "{verification_name}" eliminata.')
            return redirect(_periodic_verifications_page_url(asset_id=selected_asset.id if selected_asset else 0))

    verification_rows: list[dict[str, object]] = []
    verification_event_map: dict[int, list[AssetCalendarEvent]] = defaultdict(list)
    if selected_asset is not None:
        linked_ids = list(
            PeriodicVerification.objects.filter(assets__id=selected_asset.id).values_list("id", flat=True).distinct()
        )
        if linked_ids:
            for entry in (
                AssetCalendarEvent.objects.select_related("periodic_verification")
                .filter(
                    event_kind=AssetCalendarEvent.KIND_PERIODIC_VERIFICATION,
                    asset_id=selected_asset.id,
                    periodic_verification_id__in=linked_ids,
                )
                .order_by("target_display_name", "target_email", "created_at", "id")
            ):
                if entry.periodic_verification_id:
                    verification_event_map[entry.periodic_verification_id].append(entry)

    default_calendar_user_id = _asset_calendar_default_user_id(selected_asset, calendar_user_details)
    for verification in (
        PeriodicVerification.objects.select_related("supplier", "created_by")
        .prefetch_related("assets")
        .order_by("-is_active", "next_verification_date", "name", "id")
    ):
        linked_assets = list(verification.assets.all())
        is_selected_asset_linked = bool(selected_asset and any(asset.id == selected_asset.id for asset in linked_assets))
        verification_rows.append(
            {
                "verification": verification,
                "state": _periodic_verification_state(verification, today=today),
                "linked_assets": linked_assets,
                "linked_assets_count": len(linked_assets),
                "is_selected_asset_linked": is_selected_asset_linked,
                "can_create_calendar_event": bool(
                    selected_asset is not None
                    and is_selected_asset_linked
                    and isinstance(verification.next_verification_date, date)
                ),
                "calendar_event_rows": list(verification_event_map.get(verification.id, [])),
                "default_calendar_user_id": default_calendar_user_id,
                "edit_url": _periodic_verifications_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    edit_id=verification.id,
                ),
            }
        )

    selected_asset_linked_count = (
        sum(1 for row in verification_rows if row["is_selected_asset_linked"])
        if selected_asset is not None
        else 0
    )

    return render(
        request,
        "assets/pages/periodic_verification_list.html",
        {
            "page_title": "Manutenzione periodica",
            "form": form,
            "verification_rows": verification_rows,
            "verification_total": len(verification_rows),
            "active_verification_count": sum(1 for row in verification_rows if row["verification"].is_active),
            "due_verification_count": sum(
                1 for row in verification_rows if row["state"]["status"] in {"overdue", "warning"}
            ),
            "selected_asset": selected_asset,
            "selected_asset_linked_count": selected_asset_linked_count,
            "can_manage_periodic_verifications": can_manage_periodic_verifications,
            "can_manage_outlook_calendar": can_manage_outlook_calendar,
            "outlook_calendar_ready": _outlook_calendar_graph_ready() if can_manage_outlook_calendar else False,
            "calendar_user_choices": calendar_user_choices,
            "is_edit": edit_verification is not None,
            "edit_verification": edit_verification,
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


@login_required
def plant_layout_map(request: HttpRequest) -> HttpResponse:
    focus_asset_id = _as_int(request.GET.get("asset"), default=0)
    requested_category = _clean_string(request.GET.get("category"))
    if not requested_category and focus_asset_id:
        focus_marker = (
            PlantLayoutMarker.objects.filter(asset_id=focus_asset_id, layout__is_active=True)
            .select_related("layout")
            .order_by("layout__category", "layout__name", "id")
            .first()
        )
        if focus_marker is not None:
            requested_category = focus_marker.layout.category

    active_layouts = list(_plant_layout_queryset().filter(is_active=True).order_by("category", "name", "id"))
    selected_category = _preferred_plant_layout_category(active_layouts, requested_category=requested_category)
    layout = next(
        (row for row in active_layouts if _clean_string(row.category).casefold() == _clean_string(selected_category).casefold()),
        active_layouts[0] if active_layouts else None,
    )
    payload = _plant_layout_public_payload(layout)
    category_switches = _plant_layout_category_switches(
        active_layouts=active_layouts,
        selected_category=selected_category,
        focus_asset_id=focus_asset_id,
    )

    return render(
        request,
        "assets/pages/plant_layout_map.html",
        {
            "page_title": "Planimetrie impianti",
            "layout": layout,
            "plant_layout_payload": payload,
            "focus_asset_id": focus_asset_id,
            "selected_layout_category": selected_category,
            "layout_category_switches": category_switches,
            "can_manage_map": user_can_modulo_action(request, "assets", "admin_assets"),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:work_machine_list"),
                new_url=reverse("assets:work_machine_create"),
                new_label="+ Nuova macchina",
                search_placeholder="Ricerca rapida per macchina, tag, reparto o seriale",
            ),
        },
    )


@legacy_admin_required
def plant_layout_editor(request: HttpRequest) -> HttpResponse:
    all_layouts = list(
        _plant_layout_queryset().all().order_by("category", "-is_active", "-updated_at", "name", "id")
    )
    current_category = _clean_string(
        request.POST.get("category_filter") or request.POST.get("category") or request.GET.get("category")
    )
    current_layout_id = _as_int(request.POST.get("layout_id") or request.GET.get("layout"), default=0)
    create_new = _clean_string(request.POST.get("layout_mode") or request.GET.get("new")) in {"1", "new", "true"}
    selected_layout = None
    filtered_layouts = [
        row for row in all_layouts if not current_category or _clean_string(row.category).casefold() == current_category.casefold()
    ]
    if not create_new:
        selected_layout = next((row for row in all_layouts if row.id == current_layout_id), None)
        if selected_layout is not None and not current_category:
            current_category = selected_layout.category
            filtered_layouts = [
                row for row in all_layouts if _clean_string(row.category).casefold() == current_category.casefold()
            ]
        if selected_layout is None and filtered_layouts:
            selected_layout = next((row for row in filtered_layouts if row.is_active), None) or filtered_layouts[0]
        if selected_layout is None and all_layouts:
            selected_layout = next((row for row in all_layouts if row.is_active), None) or all_layouts[0]
            current_category = current_category or getattr(selected_layout, "category", "")
            filtered_layouts = [
                row for row in all_layouts
                if not current_category or _clean_string(row.category).casefold() == current_category.casefold()
            ]

    area_rows = _plant_layout_editor_area_rows(selected_layout)
    marker_rows = _plant_layout_editor_marker_rows(selected_layout)

    if request.method == "POST":
        action = _clean_string(request.POST.get("action")) or "save_layout"
        if action == "activate_layout":
            if selected_layout is None:
                messages.error(request, "Planimetria non trovata.")
            else:
                selected_layout.is_active = True
                selected_layout.save()
                messages.success(request, f"Planimetria \"{selected_layout.name}\" pubblicata nella categoria {selected_layout.category}.")
            layout_id = selected_layout.id if selected_layout else ""
            category_qs = f"&category={quote(selected_layout.category)}" if selected_layout else ""
            return redirect(f"{reverse('assets:plant_layout_editor')}?layout={layout_id}{category_qs}")

        if action == "delete_layout":
            if selected_layout is None:
                messages.error(request, "Planimetria non trovata.")
            else:
                deleted_name = selected_layout.name
                deleted_category = selected_layout.category
                selected_layout.delete()
                messages.success(request, f"Planimetria \"{deleted_name}\" eliminata.")
            if current_category:
                return redirect(f"{reverse('assets:plant_layout_editor')}?category={quote(current_category or deleted_category)}")
            return redirect("assets:plant_layout_editor")

        form = PlantLayoutForm(
            request.POST,
            request.FILES,
            instance=None if create_new else selected_layout,
        )
        if form.is_valid():
            layout = form.save()
            messages.success(request, f"Planimetria \"{layout.name}\" aggiornata nella categoria {layout.category}.")
            return redirect(f"{reverse('assets:plant_layout_editor')}?layout={layout.id}&category={quote(layout.category)}")
        area_rows = _safe_editor_json_rows(request.POST.get("areas_payload"))
        marker_rows = _safe_editor_json_rows(request.POST.get("markers_payload"))
    else:
        form = PlantLayoutForm(
            instance=selected_layout,
            initial={"category": current_category or getattr(selected_layout, "category", "") or PlantLayout.DEFAULT_CATEGORY},
        )

    editor_payload = {
        "layout": {
            "id": getattr(selected_layout, "id", None),
            "category": getattr(selected_layout, "category", current_category or PlantLayout.DEFAULT_CATEGORY),
            "name": getattr(selected_layout, "name", ""),
            "description": getattr(selected_layout, "description", ""),
            "image_url": (
                selected_layout.image.url
                if selected_layout is not None and selected_layout.image
                else ""
            ),
            "is_active": bool(getattr(selected_layout, "is_active", False)),
        },
        "areas": area_rows,
        "markers": marker_rows,
        "machines": _plant_layout_machine_catalog(),
    }
    available_categories = []
    seen_categories: set[str] = set()
    for row in all_layouts:
        category_key = _clean_string(row.category).casefold()
        if category_key in seen_categories:
            continue
        seen_categories.add(category_key)
        available_categories.append(row.category)
    layout_choices = [
        {
            "id": row.id,
            "category": row.category,
            "name": row.name,
            "is_active": row.is_active,
            "updated_at": timezone.localtime(row.updated_at).strftime("%d/%m/%Y %H:%M"),
            "edit_url": f"{reverse('assets:plant_layout_editor')}?layout={row.id}&category={quote(row.category)}",
        }
        for row in (filtered_layouts if current_category else all_layouts)
    ]
    layout_category_filters = [
        {
            "label": "Tutte",
            "active": not current_category,
            "url": reverse("assets:plant_layout_editor"),
        }
    ]
    for category in available_categories:
        layout_category_filters.append(
            {
                "label": category,
                "active": _clean_string(category).casefold() == current_category.casefold(),
                "url": f"{reverse('assets:plant_layout_editor')}?category={quote(category)}",
            }
        )

    return render(
        request,
        "assets/pages/plant_layout_editor.html",
        {
            "page_title": "Editor planimetrie impianti",
            "form": form,
            "selected_layout": selected_layout,
            "layout_choices": layout_choices,
            "layout_category_filters": layout_category_filters,
            "current_layout_category": current_category or getattr(selected_layout, "category", PlantLayout.DEFAULT_CATEGORY),
            "create_new": create_new,
            "editor_payload": editor_payload,
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:work_machine_list"),
                new_url=(
                    f"{reverse('assets:plant_layout_editor')}?new=1&category={quote(current_category)}"
                    if current_category
                    else f"{reverse('assets:plant_layout_editor')}?new=1"
                ),
                new_label="+ Nuova planimetria",
                search_placeholder="Ricerca rapida per macchina, tag, reparto o seriale",
            ),
        },
    )


@login_required
def work_machine_create(request: HttpRequest) -> HttpResponse:
    list_suggestions = _build_asset_list_suggestions()
    if request.method == "POST":
        uploads, upload_errors = _validate_asset_document_uploads(request)
        form = WorkMachineAssetForm(request.POST, list_suggestions=list_suggestions)
        if form.is_valid() and not upload_errors:
            asset = form.save()
            sharepoint_warnings = _ensure_asset_sharepoint_folder(asset)
            sharepoint_warnings.extend(
                _apply_asset_document_changes(asset, uploads=uploads, remove_ids=set(), actor=request.user)
            )
            for warning in sharepoint_warnings:
                messages.warning(request, warning)
            messages.success(request, "Macchina di lavoro creata correttamente.")
            return redirect("assets:asset_view", id=asset.id)
        for error in upload_errors:
            form.add_error(None, error)
    else:
        form = WorkMachineAssetForm(
            initial={"status": Asset.STATUS_IN_USE},
            list_suggestions=list_suggestions,
        )

    return render(
        request,
        "assets/pages/work_machine_form.html",
        {
            "page_title": "Nuova macchina di lavoro",
            "form": form,
            "is_edit": False,
            "list_suggestions": list_suggestions,
            "asset_field_names": form.asset_field_names,
            "category_field_groups": form.category_field_groups,
            "category_dynamic_field_names": form.category_dynamic_field_names,
            "sharepoint_field_names": form.sharepoint_field_names,
            "machine_field_names": form.machine_field_names,
            "assignment_field_names": form.assignment_field_names,
            "verification_field_names": form.verification_field_names,
            "document_field_map": form.document_field_map,
            "uploaded_documents_by_category": _build_uploaded_documents_context(None),
            "document_upload_field_map": ASSET_DOCUMENT_UPLOAD_FIELDS,
            "asset_label_designer_url": reverse("assets:asset_label_designer") + f"?scope=asset_type&asset_type={Asset.TYPE_WORK_MACHINE}",
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:work_machine_list"),
                new_url=reverse("assets:work_machine_create"),
                new_label="+ Nuova macchina",
                search_placeholder="Ricerca rapida per macchina, tag, reparto o seriale",
            ),
        },
    )


@login_required
def work_machine_edit(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:work_machine_list")
    asset = get_object_or_404(
        Asset.objects.select_related("work_machine").prefetch_related("documents"),
        pk=id,
        asset_type=Asset.TYPE_WORK_MACHINE,
    )
    list_suggestions = _build_asset_list_suggestions()

    if request.method == "POST":
        uploads, upload_errors = _validate_asset_document_uploads(request)
        remove_ids = {_as_int(value, default=0) for value in request.POST.getlist("remove_document_ids")}
        remove_ids = {value for value in remove_ids if value > 0}
        form = WorkMachineAssetForm(
            request.POST,
            instance=asset,
            work_machine=getattr(asset, "work_machine", None),
            list_suggestions=list_suggestions,
        )
        if form.is_valid() and not upload_errors:
            asset = form.save()
            sharepoint_warnings = _ensure_asset_sharepoint_folder(asset)
            sharepoint_warnings.extend(
                _apply_asset_document_changes(asset, uploads=uploads, remove_ids=remove_ids, actor=request.user)
            )
            for warning in sharepoint_warnings:
                messages.warning(request, warning)
            messages.success(request, "Macchina di lavoro aggiornata.")
            return redirect("assets:asset_view", id=asset.id)
        for error in upload_errors:
            form.add_error(None, error)
    else:
        form = WorkMachineAssetForm(
            instance=asset,
            work_machine=getattr(asset, "work_machine", None),
            list_suggestions=list_suggestions,
        )

    return render(
        request,
        "assets/pages/work_machine_form.html",
        {
            "page_title": f"Modifica {asset.asset_tag}",
            "form": form,
            "asset": asset,
            "is_edit": True,
            "list_suggestions": list_suggestions,
            "asset_field_names": form.asset_field_names,
            "category_field_groups": form.category_field_groups,
            "category_dynamic_field_names": form.category_dynamic_field_names,
            "sharepoint_field_names": form.sharepoint_field_names,
            "machine_field_names": form.machine_field_names,
            "assignment_field_names": form.assignment_field_names,
            "verification_field_names": form.verification_field_names,
            "document_field_map": form.document_field_map,
            "uploaded_documents_by_category": _build_uploaded_documents_context(asset),
            "document_upload_field_map": ASSET_DOCUMENT_UPLOAD_FIELDS,
            "asset_label_designer_url": reverse("assets:asset_label_designer") + f"?scope=asset&asset_id={asset.id}",
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:work_machine_list"),
                new_url=reverse("assets:work_machine_create"),
                new_label="+ Nuova macchina",
                search_placeholder="Ricerca rapida per macchina, tag, reparto o seriale",
            ),
        },
    )


@login_required
def assignment_set(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:asset_list")
    asset = get_object_or_404(Asset, pk=id)
    user_choices, user_details = _legacy_employee_options()
    list_suggestions = _build_asset_list_suggestions(employee_details=user_details)
    selected_user_id = asset.assigned_legacy_user_id if asset.assigned_legacy_user_id else ""

    if request.method == "POST":
        form = AssetAssignmentForm(
            request.POST,
            instance=asset,
            user_choices=user_choices,
            selected_user_id=selected_user_id,
            list_suggestions=list_suggestions,
        )
        if form.is_valid():
            selected_raw = _clean_string(form.cleaned_data.get("assigned_user_id"))
            saved_asset: Asset = form.save(commit=False)
            if selected_raw:
                selected_info = user_details.get(selected_raw, {})
                saved_asset.assigned_legacy_user_id = int(selected_raw)
                selected_name = _clean_string(selected_info.get("display_name"))
                if selected_name:
                    saved_asset.assignment_to = selected_name
                selected_reparto = _clean_string(selected_info.get("reparto"))
                if selected_reparto:
                    saved_asset.assignment_reparto = selected_reparto
            else:
                saved_asset.assigned_legacy_user_id = None
            saved_asset.save()
            messages.success(request, "Assegnazione aggiornata.")
            return redirect("assets:asset_view", id=asset.id)
    else:
        form = AssetAssignmentForm(
            instance=asset,
            user_choices=user_choices,
            selected_user_id=selected_user_id,
            list_suggestions=list_suggestions,
        )

    selected_user_admin_url = ""
    try:
        selected_id = int(form.initial.get("assigned_user_id") or 0)
    except (TypeError, ValueError):
        selected_id = 0
    if selected_id:
        try:
            anag_id = AnagraficaDipendente.objects.filter(
                utente_id=selected_id
            ).values_list("id", flat=True).first()
            if anag_id:
                selected_user_admin_url = reverse(
                    "anagrafica:dipendente_detail",
                    kwargs={"legacy_id": anag_id},
                )
        except (NoReverseMatch, ValueError, TypeError):
            selected_user_admin_url = ""

    return render(
        request,
        "assets/pages/asset_assignment.html",
        {
            "page_title": f"Assegna {asset.asset_tag}",
            "asset": asset,
            "form": form,
            "selected_user_admin_url": selected_user_admin_url,
            "list_suggestions": list_suggestions,
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


def _workorder_attachment_accept_attr() -> str:
    return ",".join(sorted(ASSET_DOCUMENT_ALLOWED_EXTENSIONS))


def _validate_workorder_attachment_uploads(request: HttpRequest) -> tuple[list, list[str]]:
    uploads = []
    errors: list[str] = []
    for upload in request.FILES.getlist("attachments"):
        file_name = Path(getattr(upload, "name", "") or "").name
        try:
            validate_extension_and_mime(
                upload,
                allowed_extensions=ASSET_DOCUMENT_ALLOWED_EXTENSIONS,
                allowed_mimes=ASSET_DOCUMENT_ALLOWED_MIMES,
                max_bytes=ASSET_DOCUMENT_MAX_BYTES,
                label=file_name or "Allegato",
            )
        except UploadMimeValidationError as exc:
            errors.append(str(exc))
            continue
        uploads.append(upload)
    return uploads, errors


def _save_workorder_attachments(*, workorder: WorkOrder, uploads: list, user) -> list[WorkOrderAttachment]:
    created: list[WorkOrderAttachment] = []
    for upload in uploads:
        created.append(
            WorkOrderAttachment.objects.create(
                work_order=workorder,
                file=upload,
                original_name=Path(getattr(upload, "name", "") or "").name[:255],
                uploaded_by=user if getattr(user, "is_authenticated", False) else None,
            )
        )
    return created


def _add_form_validation_errors(form, exc: ValidationError) -> None:
    if hasattr(exc, "message_dict"):
        for field_name, field_errors in exc.message_dict.items():
            target_field = field_name if field_name in form.fields else None
            for error in field_errors:
                form.add_error(target_field, error)
        return
    for error in list(getattr(exc, "messages", []) or [str(exc)]):
        form.add_error(None, error)


@login_required
def workorder_list(request: HttpRequest) -> HttpResponse:
    status = _clean_string(request.GET.get("status"))
    kind = _clean_string(request.GET.get("kind"))
    q = _clean_string(request.GET.get("q"))

    workorders = WorkOrder.objects.select_related("asset", "periodic_verification", "supplier").all()
    if status:
        workorders = workorders.filter(status=status)
    if kind:
        workorders = workorders.filter(kind=kind)
    if q:
        workorders = workorders.filter(
            Q(title__icontains=q)
            | Q(asset__asset_tag__icontains=q)
            | Q(asset__name__icontains=q)
            | Q(description__icontains=q)
        )

    return render(
        request,
        "assets/pages/workorder_list.html",
        {
            "page_title": "Interventi",
            "workorders": workorders,
            "status_filter": status,
            "kind_filter": kind,
            "q_filter": q,
            "status_choices": WorkOrder.STATUS_CHOICES,
            "kind_choices": WorkOrder.KIND_CHOICES,
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


@login_required
def workorder_create(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:wo_list")
    asset = get_object_or_404(Asset, pk=id)
    source = normalize_workorder_source(request.GET.get("source"))
    prefill_payload = build_workorder_prefill_payload(
        asset=asset,
        base_rule_id=_as_int(request.GET.get("rule"), default=0),
        source=source,
    )
    selected_rule_id = getattr(prefill_payload.get("maintenance_rule"), "id", 0)
    form_kwargs = {
        "asset": asset,
        "prefill_payload": prefill_payload,
    }
    if request.method == "POST":
        form = WorkOrderForm(request.POST, **form_kwargs)
        uploads, upload_errors = _validate_workorder_attachment_uploads(request)
        form_is_valid = form.is_valid()
        for error in upload_errors:
            form.add_error(None, error)
        if form_is_valid and not upload_errors:
            workorder = form.save(commit=False)
            workorder.asset = asset
            workorder.status = WorkOrder.STATUS_OPEN
            if not workorder.opened_at:
                workorder.opened_at = timezone.now()
            try:
                workorder.full_clean()
            except ValidationError as exc:
                _add_form_validation_errors(form, exc)
            else:
                with transaction.atomic():
                    workorder.save()
                    created_attachments = _save_workorder_attachments(
                        workorder=workorder,
                        uploads=uploads,
                        user=request.user,
                    )
                    log_note = "Intervento creato."
                    if created_attachments:
                        log_note = f"{log_note} Allegati caricati: {len(created_attachments)}."
                    WorkOrderLog.objects.create(
                        work_order=workorder,
                        note=log_note,
                        author=request.user if request.user.is_authenticated else None,
                    )
                messages.success(request, "Intervento creato.")
                return redirect("assets:wo_view", id=workorder.id)
    else:
        initial = {"status": WorkOrder.STATUS_OPEN}
        kind_param = request.GET.get("kind", "").strip().upper()
        if kind_param in {c[0] for c in WorkOrder.KIND_CHOICES}:
            initial["kind"] = kind_param
        form = WorkOrderForm(initial=initial, **form_kwargs)
    periodic_verification_supplier_map = {
        str(verification.id): {
            "supplier_id": str(verification.supplier_id or ""),
            "supplier_label": str(verification.supplier) if verification.supplier_id else "",
        }
        for verification in form.fields["periodic_verification"].queryset
    }
    maintenance_rule_suggestion_map = form.build_rule_suggestion_map()
    contract_suggestion_map = form.build_contract_suggestion_map()
    initial_rule = None
    rule_value = form["maintenance_rule"].value()
    if rule_value:
        initial_rule = form.fields["maintenance_rule"].queryset.filter(pk=_as_int(rule_value, default=0)).first()
    initial_contract = None
    contract_value = form["assistance_contract"].value()
    if contract_value:
        initial_contract = form.fields["assistance_contract"].queryset.filter(pk=_as_int(contract_value, default=0)).first()
    return render(
        request,
        "assets/pages/workorder_form.html",
        {
            "page_title": f"Nuovo intervento - {asset.asset_tag}",
            "asset": asset,
            "form": form,
            "selected_rule_id": selected_rule_id,
            "initial_rule": initial_rule,
            "initial_contract": initial_contract,
            "workorder_prefill": prefill_payload,
            "available_contract_count": form.fields["assistance_contract"].queryset.count(),
            "attachment_accept": _workorder_attachment_accept_attr(),
            "attachment_max_mb": int(ASSET_DOCUMENT_MAX_BYTES / (1024 * 1024)),
            "periodic_verification_supplier_map_json": json.dumps(periodic_verification_supplier_map),
            "maintenance_rule_suggestion_map_json": json.dumps(maintenance_rule_suggestion_map),
            "contract_suggestion_map_json": json.dumps(contract_suggestion_map),
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


@login_required
def workorder_detail(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:wo_list")
    workorder = get_object_or_404(
        WorkOrder.objects.select_related(
            "asset",
            "periodic_verification",
            "supplier",
            "maintenance_rule",
            "maintenance_rule__intervention_template",
            "assistance_contract",
            "assistance_contract__supplier",
        ),
        pk=id,
    )

    if request.method == "POST":
        log_note = _clean_string(request.POST.get("log_note"))
        if log_note:
            WorkOrderLog.objects.create(
                work_order=workorder,
                note=log_note,
                author=request.user if request.user.is_authenticated else None,
            )
            messages.success(request, "Nota aggiunta.")
            return redirect("assets:wo_view", id=workorder.id)

    logs = workorder.logs.select_related("author").all()
    attachments = workorder.attachments.all()
    return render(
        request,
        "assets/pages/workorder_detail.html",
        {
            "page_title": f"Intervento #{workorder.id}",
            "workorder": workorder,
            "logs": logs,
            "attachments": attachments,
            "workorder_asset_url": reverse("assets:asset_view", kwargs={"id": workorder.asset_id}),
            "workorder_rule_url": (
                _asset_maintenance_rule_list_page_url(
                    asset_id=workorder.asset_id,
                    focus_rule_id=workorder.maintenance_rule_id or 0,
                )
                if workorder.maintenance_rule_id
                else ""
            ),
            "workorder_contract_url": (
                _assistance_contracts_page_url(
                    asset_id=workorder.asset_id,
                    edit_id=workorder.assistance_contract_id or 0,
                )
                if workorder.assistance_contract_id
                else _assistance_contracts_page_url(asset_id=workorder.asset_id)
            ),
            "workorder_contract_label": "Apri contratto" if workorder.assistance_contract_id else "Apri contratti",
            "workorder_status": _workorder_status_payload(workorder.status),
            "workorder_kind": _workorder_kind_payload(workorder.kind),
            "workorder_coverage": _coverage_status_payload(
                is_covered=bool(workorder.covered_by_contract),
                contract=workorder.assistance_contract,
            ),
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


@login_required
def workorder_close(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:wo_list")
    workorder = get_object_or_404(
        WorkOrder.objects.select_related("asset", "maintenance_rule", "assistance_contract", "assistance_contract__supplier"),
        pk=id,
    )

    if request.method == "POST":
        form = WorkOrderCloseForm(request.POST, asset=workorder.asset, workorder=workorder)
        if form.is_valid():
            resolved_supplier = form.cleaned_data.get("resolved_supplier")
            if resolved_supplier is not None and workorder.supplier_id is None:
                workorder.supplier = resolved_supplier
            try:
                workorder.close(
                    status=form.cleaned_data["status"],
                    resolution=form.cleaned_data.get("resolution") or "",
                    intervention_duration=form.cleaned_data.get("intervention_duration_minutes"),
                    downtime=form.cleaned_data.get("downtime_minutes"),
                    labor_cost=form.cleaned_data.get("labor_cost_eur"),
                    materials_cost=form.cleaned_data.get("materials_cost_eur"),
                    cost=form.cleaned_data.get("cost_eur"),
                    covered_by_contract=form.cleaned_data.get("covered_by_contract"),
                    assistance_contract=form.cleaned_data.get("assistance_contract"),
                )
            except ValidationError as exc:
                _add_form_validation_errors(form, exc)
            else:
                if workorder.status == WorkOrder.STATUS_DONE and workorder.maintenance_rule_id:
                    sync_workorder_maintenance_state(workorder)
                log_note = _clean_string(form.cleaned_data.get("log_note"))
                closure_note = "Intervento chiuso." if workorder.status == WorkOrder.STATUS_DONE else "Intervento annullato."
                if log_note:
                    closure_note = f"{closure_note} {log_note}"
                WorkOrderLog.objects.create(
                    work_order=workorder,
                    note=closure_note,
                    author=request.user if request.user.is_authenticated else None,
                )
                messages.success(
                    request,
                    "Intervento chiuso." if workorder.status == WorkOrder.STATUS_DONE else "Intervento annullato.",
                )
                return redirect("assets:wo_view", id=workorder.id)
    else:
        form = WorkOrderCloseForm(
            initial={
                "status": WorkOrder.STATUS_DONE,
                "intervention_duration_minutes": workorder.intervention_duration_minutes,
                "downtime_minutes": workorder.downtime_minutes,
                "labor_cost_eur": workorder.labor_cost_eur,
                "materials_cost_eur": workorder.materials_cost_eur,
                "cost_eur": workorder.cost_eur,
                "assistance_contract": workorder.assistance_contract_id,
                "covered_by_contract": workorder.covered_by_contract,
            },
            asset=workorder.asset,
            workorder=workorder,
        )

    return render(
        request,
        "assets/pages/workorder_close.html",
        {
            "page_title": f"Chiudi intervento #{workorder.id}",
            "workorder": workorder,
            "form": form,
            "close_submit_label": (
                "Conferma annullamento"
                if (form["status"].value() or WorkOrder.STATUS_DONE) == WorkOrder.STATUS_CANCELED
                else "Conferma chiusura"
            ),
            "workorder_status": _workorder_status_payload(workorder.status),
            "workorder_kind": _workorder_kind_payload(workorder.kind),
            "workorder_coverage": _coverage_status_payload(
                is_covered=bool(workorder.covered_by_contract),
                contract=workorder.assistance_contract,
            ),
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


@login_required
def reports_dashboard(request: HttpRequest) -> HttpResponse:
    now = timezone.now()
    today = timezone.localdate()
    period_start = now - timedelta(days=90)
    schedule_rows = build_day_based_maintenance_schedule_rows(today=today)

    open_workorders = WorkOrder.objects.select_related("asset", "supplier").filter(status=WorkOrder.STATUS_OPEN)
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
        .order_by("-closed_at", "-id")
    )
    maintenance_month_dataset = _build_work_machine_maintenance_month_dataset(
        month_value=request.GET.get("month"),
        today=today,
    )
    done_rows = list(recent_done_workorders)
    total_cost = sum((workorder.resolved_total_cost_eur or Decimal("0")) for workorder in done_rows)
    duration_values = [
        workorder.intervention_duration_minutes
        for workorder in done_rows
        if workorder.intervention_duration_minutes is not None
    ]
    avg_duration_minutes = round(sum(duration_values) / len(duration_values), 1) if duration_values else None
    avg_downtime_minutes = (
        WorkOrder.objects.filter(status=WorkOrder.STATUS_DONE, closed_at__gte=period_start)
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

    overdue_rows = [row for row in schedule_rows if row["schedule_status"] == "overdue"]
    warning_rows = [row for row in schedule_rows if row["schedule_status"] == "warning"]
    upcoming_rows = [row for row in schedule_rows if row["schedule_status"] == "upcoming"]
    missing_rows = [row for row in schedule_rows if row["schedule_status"] == "missing"]
    critical_count = len(overdue_rows) + len(warning_rows) + len(missing_rows)
    critical_rows: list[dict[str, object]] = []
    for row in schedule_rows:
        if row["schedule_status"] not in {"overdue", "warning", "missing"}:
            continue
        asset = row["asset"]
        critical_rows.append(
            {
                **row,
                "asset_detail_url": reverse("assets:asset_view", kwargs={"id": asset.id}),
                "workorder_create_url": _workorder_create_page_url(
                    asset_id=asset.id,
                    rule_id=row["base_rule"].id,
                    source="maintenance_reports",
                ),
                "primary_action": _maintenance_row_primary_action(
                    asset=asset,
                    base_rule=row["base_rule"],
                    schedule_status=str(row.get("schedule_status") or ""),
                    source="maintenance_reports",
                ),
            }
        )

    return render(
        request,
        "assets/pages/reports_dashboard.html",
        {
            "page_title": "Report manutenzione",
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
            "open_workorders_url": f"{reverse('assets:wo_list')}?status={quote(WorkOrder.STATUS_OPEN)}",
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
    generated_at = timezone.localtime()
    active_template = _active_asset_report_template(AssetReportTemplate.REPORT_ASSET_DETAIL)
    snapshot = _build_asset_report_snapshot(asset)

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{asset.asset_tag or "asset"}-report.pdf"'

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle(f'Report asset {asset.asset_tag}')
    pdf.setAuthor("Portale Applicativo")
    pdf.setSubject(f'Scheda PDF asset {asset.asset_tag}')
    _draw_asset_report_pdf(
        pdf,
        asset=asset,
        snapshot=snapshot,
        generated_at=generated_at,
        template_name=active_template.name if active_template else "",
    )
    pdf.showPage()
    pdf.save()
    response.write(buffer.getvalue())
    return response


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


@login_required
def work_machine_maintenance_month_pdf(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    reparto_filter = _clean_string(request.GET.get("reparto"))
    dataset = _build_work_machine_maintenance_month_dataset(
        month_value=request.GET.get("month"),
        reparto_filter=reparto_filter,
        today=today,
    )
    generated_at = timezone.localtime()
    filename_parts = ["report", "macchine", "manutenzione", str(dataset["month_code"])]
    if reparto_filter:
        reparto_slug = slugify(reparto_filter)
        if reparto_slug:
            filename_parts.append(reparto_slug)

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{"_".join(filename_parts)}.pdf"'

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=landscape(A4))
    pdf.setTitle(f'Report manutenzioni macchine {dataset["month_label"]}')
    pdf.setAuthor("Portale Applicativo")
    pdf.setSubject(f'Macchine con manutenzione pianificata nel periodo {dataset["period_label"]}')

    _draw_work_machine_maintenance_month_pdf(pdf, dataset=dataset, generated_at=generated_at)

    pdf.showPage()
    pdf.save()
    response.write(buffer.getvalue())
    return response


def _handle_sharepoint_config_request(request: HttpRequest) -> tuple[bool, str]:
    tenant_id = _clean_string(request.POST.get("sharepoint_tenant_id"))[:200]
    client_id = _clean_string(request.POST.get("sharepoint_client_id"))[:200]
    site_id = _clean_string(request.POST.get("sharepoint_site_id"))[:500]
    client_secret = _clean_string(request.POST.get("sharepoint_client_secret"))
    asset_root_path = _normalize_sharepoint_path(request.POST.get("sharepoint_asset_root_path"))[:500]
    work_machine_root_path = _normalize_sharepoint_path(request.POST.get("sharepoint_work_machine_root_path"))[:500]
    library_url = _clean_string(request.POST.get("sharepoint_library_url"))[:1000]

    try:
        dotenv_values = load_env_file_values()
        current_secret = str(dotenv_values.get("GRAPH_CLIENT_SECRET") or dotenv_values.get("AZURE_CLIENT_SECRET") or "").strip()
        updates = {
            "GRAPH_TENANT_ID": tenant_id,
            "GRAPH_CLIENT_ID": client_id,
            "GRAPH_SITE_ID": site_id,
            "ASSETS_SHAREPOINT_ASSET_ROOT_PATH": asset_root_path,
            "ASSETS_SHAREPOINT_WORK_MACHINE_ROOT_PATH": work_machine_root_path,
            "ASSETS_SHAREPOINT_LIBRARY_URL": library_url,
        }
        if client_secret:
            updates["GRAPH_CLIENT_SECRET"] = client_secret
        elif not current_secret and not get_first_env_value("GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET"):
            updates["GRAPH_CLIENT_SECRET"] = ""
        update_env_file_values(
            updates,
            delete_keys=["AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"],
        )
    except Exception as exc:
        return False, f"Errore scrittura .env: {exc}"
    return True, "Configurazione SharePoint aggiornata."


@legacy_admin_required
def gestione_admin(request: HttpRequest) -> HttpResponse:
    """Pagina di gestione interna Assets — accesso solo admin."""

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
    for sidebar_item in sidebar_buttons:
        sidebar_item.label = _ui_label(sidebar_item.label)
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

        if action == "save_sharepoint_config":
            ok, text = _handle_sharepoint_config_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return config_redirect

        if action == "test_sharepoint_config":
            ok, text = _sharepoint_graph_healthcheck()
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return config_redirect

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
            return config_redirect

        if action == "save_assets_logo":
            logo_file = request.FILES.get("logo_file")
            logo_url = request.POST.get("logo_url", "").strip()
            if logo_file:
                _LOGO_ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".webp"}
                _LOGO_ALLOWED_MIMES = {"image/png", "image/jpeg", "image/svg+xml", "image/webp"}
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
    if tab == "categorie":
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
            "sharepoint_admin_config": _sharepoint_admin_config(),
            "asset_categories": asset_categories,
            "asset_category_fields": asset_category_fields,
            "asset_category_type_choices": _ui_choices(Asset.TYPE_CHOICES),
            "asset_category_field_type_choices": _ui_choices(AssetCategoryField.TYPE_CHOICES),
            "detail_section_choices": _ui_choices(AssetDetailField.SECTION_CHOICES),
            "detail_format_choices": _ui_choices(AssetDetailField.FORMAT_CHOICES),
            "asset_categories_active_count": sum(1 for row in asset_categories if row.is_active),
            "asset_category_fields_active_count": sum(1 for row in asset_category_fields if row.is_active),
            "categorie_ticket": categorie_ticket,
            "ticket_tipo_choices": _TipoTicket.choices,
            **_assets_shell_context(request),
        },
    )


@login_required
def asset_bulk_update(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Metodo non consentito"}, status=405)
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON non valido"}, status=400)

    ids = data.get("ids", [])
    fields = data.get("fields", {})

    if not ids:
        return JsonResponse({"ok": False, "error": "Nessun asset selezionato"}, status=400)
    if not fields:
        return JsonResponse({"ok": False, "error": "Nessun campo da aggiornare"}, status=400)

    _ALLOWED_BULK_FIELDS = {"status", "reparto", "notes", "manufacturer", "model"}
    _valid_statuses = {k for k, _ in Asset.STATUS_CHOICES}

    update_kwargs: dict[str, str] = {}
    for field, value in fields.items():
        if field not in _ALLOWED_BULK_FIELDS:
            continue
        if field == "status" and value not in _valid_statuses:
            return JsonResponse({"ok": False, "error": f"Stato non valido: {value}"}, status=400)
        update_kwargs[field] = str(value)

    if not update_kwargs:
        return JsonResponse({"ok": False, "error": "Nessun campo valido da aggiornare"}, status=400)

    try:
        clean_ids = [int(i) for i in ids]
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "error": "ID asset non validi"}, status=400)

    updated = Asset.objects.filter(pk__in=clean_ids).update(**update_kwargs)
    return JsonResponse({"ok": True, "updated": updated})


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
    "verifiche_scadute": {"label": "Verifiche scadute", "icon": "shield-alert", "color": "red"},
    "verifiche_30gg": {"label": "Verifiche 30 gg", "icon": "shield-check", "color": "yellow"},
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

    # Scadenze amministrative
    dl_qs = AssetAdministrativeDeadline.objects.filter(is_active=True)
    dl_scadute = dl_qs.filter(due_date__lt=today).count()
    dl_30 = dl_qs.filter(due_date__gte=today, due_date__lte=in_30).count()
    dl_90 = dl_qs.filter(due_date__gt=in_30, due_date__lte=in_90).count()

    # OdL
    wo_aperte = WorkOrder.objects.filter(status=WorkOrder.STATUS_OPEN).count()
    wo_chiuse_mese = WorkOrder.objects.filter(
        status=WorkOrder.STATUS_DONE, closed_at__date__gte=first_day_month
    ).count()

    # Verifiche periodiche
    pv_qs = PeriodicVerification.objects.filter(is_active=True, next_verification_date__isnull=False)
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
    prossime_scadenze = list(
        AssetAdministrativeDeadline.objects.filter(is_active=True, due_date__gte=today, due_date__lte=in_30)
        .select_related("asset")
        .order_by("due_date")[:8]
    )
    prossime_verifiche = list(
        PeriodicVerification.objects.filter(is_active=True, next_verification_date__gte=today, next_verification_date__lte=in_30)
        .order_by("next_verification_date")[:8]
    )
    scadenze_arretrate = list(
        AssetAdministrativeDeadline.objects.filter(is_active=True, due_date__lt=today)
        .select_related("asset")
        .order_by("due_date")[:8]
    )

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


@login_required
def asset_dashboard(request: HttpRequest) -> HttpResponse:
    """Dashboard principale del modulo Assets con KPI personalizzabili."""
    legacy_list_redirect = _legacy_asset_dashboard_list_redirect_url(request)
    if legacy_list_redirect:
        return redirect(legacy_list_redirect)

    today = timezone.localdate()

    # Configurazione widget utente
    cfg, _ = AssetDashboardConfig.objects.get_or_create(user=request.user)
    enabled = cfg.get_enabled_widgets()

    kpis = _compute_dashboard_kpis(today)

    # Categorie asset attive (solo principali, per i link in cima)
    categories = list(AssetCategory.objects.filter(is_active=True).order_by("sort_order", "label"))

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
        "branding": branding,
        "page_title": "Dashboard Assets",
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
