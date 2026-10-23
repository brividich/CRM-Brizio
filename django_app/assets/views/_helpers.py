"""Helper condivisi delle viste Asset (estratti meccanicamente da views.py, refactor C4)."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from html import escape
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

import requests
from django.db import DatabaseError, IntegrityError, connections
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from config.env_config import get_first_env_value
from core import naming
from core.acl import user_can_modulo_action
from core.upload_limits import DOCUMENT_MAX_BYTES

# Etichetta con cui le voci di audit si agganciano all'asset: e' la stessa che
# `core.audit.storico_oggetto` usa per ripescarle sulla scheda. Costante e non
# stringa sparsa perche' un refuso qui non romperebbe nulla — semplicemente la
# voce non comparirebbe mai nello storico, e non se ne accorgerebbe nessuno.
AUDIT_OGGETTO_ASSET = "assets.asset"
from core.graph_utils import acquire_graph_token, is_placeholder_value
from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.legacy_utils import get_legacy_user, is_legacy_admin
from core.models import UserExtraInfo
from core.upload_mime import UploadMimeValidationError, safe_filename, validate_extension_and_mime
from ..forms import (
    PRODUCTION_ASSET_TYPES,
)
from ..models import (
    Asset,
    AssetAdministrativeDeadline,
    AssetCustomField,
    AssetDocument,
    AssetLabelTemplate,
    AssetCalendarEvent,
    AssistanceContract,
    SoftwareLicense,
    MaintenanceRule,
    PeriodicVerification,
    PlantLayout,
    PlantLayoutMarker,
    WorkMachine,
    WorkOrder,
)
from ..maintenance import (
    get_primary_assistance_contract,
    normalize_workorder_source,
)


logger = logging.getLogger(__name__)
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
    ".msg",
    ".avi",
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
    # File messaggio Outlook (.msg): contenitore OLE Compound Document.
    # libmagic puo riportarlo con diverse etichette a seconda della versione.
    "application/vnd.ms-outlook",
    "application/x-ole-storage",
    "application/cdfv2",
    # Video AVI (contenitore RIFF): etichette diverse a seconda della versione di libmagic.
    "video/x-msvideo",
    "video/avi",
    "video/msvideo",
    "video/vnd.avi",
}
# File di sistema da ignorare silenziosamente negli upload di intere cartelle.
ASSET_DOCUMENT_IGNORED_FILENAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
ASSET_DOCUMENT_MAX_BYTES = DOCUMENT_MAX_BYTES
ASSET_DOCUMENT_UPLOAD_FIELDS = {
    AssetDocument.CATEGORY_SPECIFICHE: "upload_specs_files",
    AssetDocument.CATEGORY_MANUALI: "upload_manuals_files",
    AssetDocument.CATEGORY_INTERVENTI: "upload_interventions_files",
}
ASSET_DOCUMENT_CATEGORY_LABELS = dict(AssetDocument.CATEGORY_CHOICES)
# Prefisso del campo upload per le cartelle documento extra (oltre alle 3 di base).
ASSET_DOCUMENT_CUSTOM_FIELD_PREFIX = "upload_cat_"
REPORT_TEMPLATE_ALLOWED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".ppt",
    ".pptx",
    # Niente .html/.htm: il file e' servito da MEDIA sullo stesso dominio (audit A9).
}

DETAIL_FIELD_ACTIONS = {
    "seed_detail_fields",
    "create_detail_field",
    "update_detail_field",
    "update_detail_field_bulk",
    "delete_detail_field",
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
    "create_sidebar_button_for_category",
}

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
    ("assignment_location", "Collocazione"),
    ("manufacturer", "Produttore"),
    ("model", "Modello"),
    ("serial_number", "Seriale"),
    ("last_seen", "Ultimo aggiornamento"),
    ("reparto", "Reparto"),
    ("vlan", "VLAN"),
    ("ip", "IP"),
    ("switch_port", "Porta SW"),
    ("patch_panel_port", "Porta patch panel"),
    ("qr", "QR"),
]
ASSET_LIST_IT_COLUMNS = ["ip", "switch_port", "patch_panel_port"]
ASSET_LIST_COMMON_COLUMNS = [
    "name",
    "status",
    "category",
    "assigned",
    "assignment_location",
    "manufacturer",
    "model",
    "serial_number",
    "last_seen",
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


def _model_table_exists(model_class) -> bool:
    connection = connections[model_class.objects.db]
    try:
        with connection.cursor() as cursor:
            table_names = connection.introspection.table_names(cursor)
    except DatabaseError:
        return False
    return model_class._meta.db_table in table_names

LABEL_TEMPLATE_DEFAULT_CODE = "default"
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


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
        {"key": "purchase_date", "label": "Data acquisto", "group": "Asset"},
        {"key": "production_date", "label": "Data produzione", "group": "Asset"},
        {"key": "assignment_to", "label": "Assegnato a", "group": "Assegnazione"},
        {"key": "assignment_reparto", "label": "Reparto assegnazione", "group": "Assegnazione"},
        {"key": "assignment_location", "label": "Posizione assegnazione", "group": "Assegnazione"},
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


def _asset_label_logo_source_path(template: AssetLabelTemplate) -> str:
    if template.logo_file and getattr(template.logo_file, "path", ""):
        logo_path = Path(template.logo_file.path)
        if logo_path.exists():
            return str(logo_path)
    default_logo = _default_asset_label_logo_path()
    if default_logo.exists():
        return str(default_logo)
    return ""


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
        return raw_value.strftime("%d-%m-%Y")

    if field_key in {"x_mm", "y_mm", "z_mm", "diameter_mm", "spindle_mm"}:
        return f"{_format_label_number(raw_value)} mm"
    if field_key == "pressure_bar":
        return f"{_format_label_number(raw_value)} bar"
    if field_key == "maintenance_reminder_days":
        return f"{_format_label_number(raw_value)} gg"
    return _clean_string(_format_label_number(raw_value) if field_key in {"year", "tmc"} else str(raw_value))


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


PERIODIC_EXECUTION_WINDOW_CHOICES: tuple[tuple[str, str], ...] = (
    ("12", "Ultimi 12 mesi"),
    ("24", "Ultimi 24 mesi"),
    ("all", "Tutto lo storico"),
)
PERIODIC_EXECUTION_WINDOW_DEFAULT = "12"


def _normalize_periodic_execution_window(value: str | None) -> str:
    candidate = _clean_string(value).lower()
    valid = {key for key, _ in PERIODIC_EXECUTION_WINDOW_CHOICES}
    if candidate in valid:
        return candidate
    return PERIODIC_EXECUTION_WINDOW_DEFAULT


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


def _maintenance_template_list_page_url(*, category_id: int = 0, **_ignored) -> str:
    """Dopo aver salvato checklist e istruzioni si torna alla lista unica dei Piani."""
    return reverse("assets:maintenance_plan_list")


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


def _asset_maintenance_rule_list_page_url(asset_id: int, *, focus_rule_id: int = 0) -> str:
    """I piani dell'asset (le vecchie "regole asset" rimandavano li' con un redirect)."""
    return reverse("assets:asset_maintenance_plans", kwargs={"asset_id": int(asset_id)})


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
    # Porta allo Scadenzario (il vecchio /prossime/ rimandava li' perdendo i filtri).
    # Lo stato del vecchio motore diventa la finestra: "due" = scadute + 30 giorni.
    params = [p for p in params if not p.startswith(("status=", "coverage="))]
    window = {"due": "30", "overdue": "overdue", "warning": "30"}.get(status_value.lower(), "")
    params.append(f"window={window}")
    base_url = reverse("assets:maintenance_scadenze")
    return f"{base_url}?{'&'.join(params)}"


def _workorder_create_page_url(
    *,
    asset_id: int,
    rule_id: int = 0,
    periodic_verification_id: int = 0,
    source: str = "",
) -> str:
    params: list[str] = []
    if rule_id:
        params.append(f"rule={int(rule_id)}")
    if periodic_verification_id:
        params.append(f"periodic={int(periodic_verification_id)}")
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


def _asset_maintenance_rule_override_reset_page_url(*, asset_id: int, override_id: int) -> str:
    return reverse(
        "assets:asset_maintenance_rule_override_reset",
        kwargs={"asset_id": int(asset_id), "id": int(override_id)},
    )


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

    # Dalle scadenze pianificate (occorrenze), come Scadenzario e Calendario:
    # WorkMachine.next_maintenance_date non si aggiorna piu' alla chiusura e dava
    # un mese diverso da quello delle pagine. Una riga per manutenzione.
    from ..models import MaintenanceOccurrence

    queryset = (
        MaintenanceOccurrence.objects.filter(
            asset__asset_type__in=PRODUCTION_ASSET_TYPES,
            due_date__gte=month_start,
            due_date__lte=month_end,
        )
        .exclude(status=MaintenanceOccurrence.STATUS_CANCELED)
        .select_related("asset", "plan")
        .order_by("due_date", "asset__reparto", "asset__name", "asset__asset_tag")
    )
    if reparto_value:
        queryset = queryset.filter(asset__reparto=reparto_value)

    rows: list[dict[str, object]] = []
    status_counts = {"overdue": 0, "warning": 0, "ok": 0}
    for occ in queryset:
        delta_days = (occ.due_date - current_day).days
        if occ.status == MaintenanceOccurrence.STATUS_DONE:
            state = {"status": "ok", "label": f"Eseguita il {occ.completed_on:%d-%m-%Y}" if occ.completed_on else "Eseguita"}
        elif delta_days < 0:
            state = {"status": "overdue", "label": f"Scaduta da {abs(delta_days)} gg"}
        elif delta_days <= int(occ.warning_days or 0):
            state = {"status": "warning", "label": f"In scadenza ({delta_days} gg)"}
        else:
            state = {"status": "ok", "label": f"Pianificata tra {delta_days} gg"}
        rows.append({"asset": occ.asset, "occurrence": occ, "state": state})
        status_counts[state["status"]] += 1

    return {
        "month_start": month_start,
        "month_end": month_end,
        "month_code": month_start.strftime("%Y-%m"),
        "month_label": _month_label(month_start),
        "period_label": f'{month_start.strftime("%d-%m-%Y")} - {month_end.strftime("%d-%m-%Y")}',
        "reparto_filter": reparto_value,
        "rows": rows,
        "total_count": len(rows),
        "overdue_count": status_counts["overdue"],
        "warning_count": status_counts["warning"],
        "ok_count": status_counts["ok"],
    }


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


def _sanitize_document_segment(value: str | None) -> str:
    row = re.sub(r'[\\/:*?"<>|#%{}~&]+', "-", _clean_string(value))
    row = re.sub(r"\s+", " ", row)
    return row.strip(" .")


def _sanitize_document_filename(value: str | None, *, fallback: str = "documento") -> str:
    filename = safe_filename(value, max_length=180)
    if not filename:
        filename = fallback
    filename = re.sub(r'["*:<>?|#%{}~&]', "-", filename)
    filename = re.sub(r"\s+", " ", filename).strip(" .")
    return filename or fallback


def _asset_document_upload_basename(value: str | None) -> str:
    normalized = _clean_string(value).replace("\\", "/")
    return PurePosixPath(normalized).name if normalized else ""


def _asset_document_relative_path_field(field_name: str) -> str:
    return f"{field_name}_relative_path"


def _asset_document_custom_field_name(slug: str) -> str:
    """Nome del campo upload HTML per una cartella documento extra."""
    return f"{ASSET_DOCUMENT_CUSTOM_FIELD_PREFIX}{slug}_files"


def _asset_document_folder_specs(asset: "Asset | None" = None) -> list[dict]:
    """Cartelle documento disponibili: le 3 di base piu le extra della AssetCategory.

    Ogni spec contiene: ``code`` (chiave salvata in ``AssetDocument.category``),
    ``label`` visibile,
    ``field`` nome del campo upload, ``removable`` (True solo per le extra) e
    ``folder_id`` (pk della ``AssetCategoryDocumentFolder`` o ``None`` per le base).
    """
    specs: list[dict] = []
    for code, label in AssetDocument.CATEGORY_CHOICES:
        specs.append(
            {
                "code": code,
                "label": label,
                "field": ASSET_DOCUMENT_UPLOAD_FIELDS[code],
                "removable": False,
                "folder_id": None,
            }
        )
    category = getattr(asset, "asset_category", None)
    if category is not None:
        for folder in category.document_folders.filter(is_active=True):
            specs.append(
                {
                    "code": folder.slug,
                    "label": folder.name,
                    "field": _asset_document_custom_field_name(folder.slug),
                    "removable": True,
                    "folder_id": folder.id,
                }
            )
    return specs


def _asset_document_category_label(specs: list[dict], code: str) -> str:
    """Etichetta visibile di una cartella documento dato il suo codice."""
    for spec in specs:
        if spec["code"] == code:
            return spec["label"]
    return ASSET_DOCUMENT_CATEGORY_LABELS.get(code, code)


def _sanitize_document_relative_path(value: str | None, *, fallback_filename: str = "") -> str:
    normalized = _normalize_document_path(value)
    if not normalized:
        return ""
    parts = [part for part in normalized.split("/") if part and part not in {".", ".."}]
    if not parts:
        return ""
    folders = [_sanitize_document_segment(part) for part in parts[:-1]]
    folders = [part for part in folders if part]
    filename = _sanitize_document_filename(parts[-1], fallback=fallback_filename or "documento")
    if not folders:
        return filename
    return "/".join([*folders, filename])


def _normalize_document_path(value: str | None) -> str:
    text = _clean_string(value).replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.strip("/")


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
    """Costruisce i documenti asset raggruppati per categoria e cartella.

    Per ogni categoria ritorna una lista di gruppi ``{"folder": ..., "documents": [...]}``;
    il gruppo con ``folder`` vuoto raccoglie i file singoli (loose), gli altri
    raggruppano i file caricati con "Carica cartella" mantenendo la cartella visibile.
    """
    flat: dict[str, list[dict]] = defaultdict(list)
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
            flat[category].append(
                {
                    "name": name,
                    "size": _coalesce_str(row.get("size"), ""),
                    "date": _coalesce_str(row.get("date"), ""),
                    "url": _coalesce_str(row.get("url"), ""),
                    "kind": "external",
                    "meta": "",
                    "folder": "",
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
        flat[uploaded.category].append(
            {
                "id": uploaded.id,
                "name": uploaded.original_name or Path(uploaded.file.name).name,
                "size": size_text,
                "date": uploaded.document_date.strftime("%d-%m-%Y") if uploaded.document_date else uploaded.created_at.strftime("%d-%m-%Y"),
                "url": reverse("assets:asset_document_download", args=[uploaded.id]),
                "kind": "uploaded",
                "meta": " | ".join(meta_parts),
                "folder": _normalize_document_path(uploaded.relative_folder),
            }
        )

    # Categorie da mostrare: le 3 di base + le extra della AssetCategory, piu
    # eventuali codici "orfani" presenti solo su documenti gia esistenti.
    specs = _asset_document_folder_specs(asset)
    category_labels: dict[str, str] = {spec["code"]: spec["label"] for spec in specs}
    for code in flat:
        category_labels.setdefault(code, ASSET_DOCUMENT_CATEGORY_LABELS.get(code, code))

    documents_by_category: dict[str, list[dict]] = {}
    for category in category_labels:
        groups_map: dict[str, list[dict]] = {}
        for doc in flat.get(category, []):
            groups_map.setdefault(doc.get("folder", ""), []).append(doc)
        groups: list[dict] = []
        if groups_map.get(""):
            groups.append({"folder": "", "documents": groups_map.pop("")})
        else:
            groups_map.pop("", None)
        for folder in sorted(groups_map.keys(), key=str.lower):
            groups.append({"folder": folder, "documents": groups_map[folder]})
        documents_by_category[category] = groups
    return category_labels, documents_by_category


def _can_download_asset_document(request: HttpRequest) -> bool:
    """Chi puo' scaricare un documento asset da sessione autenticata.

    Policy: **qualunque utente autenticato**. I documenti asset (manuali,
    specifiche, procedure di intervento) sono per scelta di prodotto leggibili
    da chiunque abbia accesso fisico alla macchina, via il token QR stampato
    sopra (``asset_document_qr_download``, senza login). Il QR e' quindi il
    *pavimento* dell'accessibilita', non il tetto: un utente autenticato non puo'
    vedere meno di un anonimo con il QR in mano.

    Cio' che rendeva pericoloso il vecchio ``@login_required`` nudo non era
    questa apertura, ma il fatto che gli stessi file fossero **anche** serviti da
    IIS su ``/media/assets_documents/`` in anonimo, senza alcun controllo ne'
    traccia. Chiuso quello (deny IIS) e passato tutto da view con audit, l'accesso
    autenticato universale e' una decisione consapevole, non un IDOR.

    Il tetto resta comunque l'ACL di modulo: questa rotta sta sotto ``/assets/``,
    quindi ``ACLMiddleware`` la gatea con il binding canonico del modulo — chi non
    ha accesso ad assets non arriva nemmeno qui. Restringere la policy significa
    toccare solo questo predicato (il diniego e' gia' cablato e auditato).
    """
    return bool(getattr(request.user, "is_authenticated", False))


def _can_view_workorder(request: HttpRequest, work_order) -> bool:
    """Stesso accesso della scheda dell'OdL (audit B3).

    La rotta degli allegati sta sotto un prefisso diverso da ``wo_view``: senza
    questo controllo bastava l'accesso al modulo assets per scaricare gli allegati
    di qualsiasi OdL cambiando l'id. Si valuta la decisione ACL della pagina
    dell'OdL a cui l'allegato appartiene.
    """
    if not getattr(request.user, "is_authenticated", False):
        return False
    if getattr(request.user, "is_superuser", False) or _is_assets_admin(request):
        return True
    from core.middleware import acl_allows_path

    # Stessa politica dell'ACLMiddleware sulla pagina dell'OdL (bypass, strict-mode
    # e binding canonico inclusi): un solo predicato, come per i documenti asset.
    return acl_allows_path(
        reverse("assets:wo_view", args=[work_order.pk]),
        django_user=request.user,
        legacy_user=getattr(request, "legacy_user", None),
        request=request,
    )


def _validate_asset_document_uploads(
    request: HttpRequest, asset: Asset | None = None
) -> tuple[dict[str, list], list[str]]:
    uploads: dict[str, list] = {}
    errors: list[str] = []
    for spec in _asset_document_folder_specs(asset):
        category = spec["code"]
        field_name = spec["field"]
        valid_files = []
        relative_paths = request.POST.getlist(_asset_document_relative_path_field(field_name))
        for index, upload in enumerate(request.FILES.getlist(field_name)):
            filename = getattr(upload, "name", "") or ""
            basename = _asset_document_upload_basename(filename)
            if not basename:
                continue
            # Upload di intere cartelle: ignora i file di sistema senza errore.
            if basename.lower() in ASSET_DOCUMENT_IGNORED_FILENAMES:
                continue
            relative_path = relative_paths[index] if index < len(relative_paths) else ""
            try:
                validate_extension_and_mime(
                    upload,
                    allowed_extensions=ASSET_DOCUMENT_ALLOWED_EXTENSIONS,
                    allowed_mimes=ASSET_DOCUMENT_ALLOWED_MIMES,
                    max_bytes=ASSET_DOCUMENT_MAX_BYTES,
                    label=relative_path or basename,
                    allow_empty=False,
                )
            except UploadMimeValidationError as exc:
                errors.append(str(exc))
                continue
            upload.name = _sanitize_document_filename(basename)
            upload._document_relative_path = _sanitize_document_relative_path(
                relative_path,
                fallback_filename=upload.name,
            )
            valid_files.append(upload)
        uploads[category] = valid_files
    return uploads, errors


def _apply_asset_document_changes(
    asset: Asset,
    *,
    uploads: dict[str, list],
    remove_ids: set[int],
    actor,
) -> None:
    """Applica rimozioni e nuovi upload sull'archivio documenti locale dell'asset."""
    if remove_ids:
        for document in asset.documents.filter(id__in=remove_ids):
            document.delete()

    for category, files in uploads.items():
        for upload in files:
            relative_path = getattr(upload, "_document_relative_path", "")
            relative_folder = "/".join(relative_path.split("/")[:-1]) if "/" in relative_path else ""
            AssetDocument.objects.create(
                asset=asset,
                category=category,
                file=upload,
                original_name=_sanitize_document_filename(getattr(upload, "name", ""))[:255],
                relative_folder=relative_folder[:400],
                uploaded_by=actor if getattr(actor, "is_authenticated", False) else None,
            )


def _planned_maintenance_status(asset_queryset, today) -> dict[str, object]:
    """Stato manutentivo di ogni asset dalle scadenze pianificate (occorrenze).

    Stessa fonte di Scadenzario, Calendario e KPI: prima Dashboard officina e
    Report leggevano la data sulla macchina e il vecchio motore a regole, e davano
    numeri diversi. Per asset: la prossima occorrenza aperta decide lo stato
    (scaduta / in soglia di preavviso / in linea); gli asset in uso senza alcun
    piano applicato sono "senza piano".
    """
    from ..models import MaintenanceOccurrence
    from ..services import maintenance_domain as maintenance_dom

    assets = list(asset_queryset)
    asset_ids = [asset.id for asset in assets]
    next_by_asset: dict[int, MaintenanceOccurrence] = {}
    for occurrence in (
        MaintenanceOccurrence.objects.filter(asset_id__in=asset_ids, status=MaintenanceOccurrence.STATUS_OPEN)
        .select_related("plan", "asset")
        .order_by("due_date", "id")
    ):
        next_by_asset.setdefault(occurrence.asset_id, occurrence)
    in_use_ids = [asset.id for asset in assets if asset.status == Asset.STATUS_IN_USE]
    resolutions = maintenance_dom.build_plan_resolutions(asset_queryset=Asset.objects.filter(pk__in=in_use_ids))
    with_plan = {asset_id for (_plan_id, asset_id), res in resolutions.items() if res.is_applied}

    rows = {"overdue": [], "warning": [], "ok": [], "missing": []}
    for asset in assets:
        occurrence = next_by_asset.get(asset.id)
        if occurrence is None:
            if asset.id in with_plan or asset.status != Asset.STATUS_IN_USE:
                continue
            rows["missing"].append({"asset": asset, "occurrence": None,
                                    "state": {"status": "missing", "label": "Senza piano", "days": None, "date": None}})
            continue
        days = (occurrence.due_date - today).days
        if days < 0:
            status, label = "overdue", f"Scaduta da {abs(days)} gg"
        elif days <= int(occurrence.warning_days or 0):
            status, label = "warning", f"In soglia ({days} gg)"
        else:
            status, label = "ok", f"Tra {days} gg"
        rows[status].append({"asset": asset, "occurrence": occurrence,
                             "state": {"status": status, "label": label, "days": days, "date": occurrence.due_date}})
    for key in ("overdue", "warning", "ok"):
        rows[key].sort(key=lambda row: row["state"]["date"])
    rows["missing"].sort(key=lambda row: (row["asset"].reparto or "", row["asset"].name or ""))
    with_occ = len(rows["overdue"]) + len(rows["warning"]) + len(rows["ok"])
    in_line = len(rows["ok"]) + len(rows["warning"])
    rows["kpi"] = {
        "has_compliance": bool(with_occ),
        "compliance_pct": round(100 * in_line / with_occ) if with_occ else 0,
        "compliant_rules": in_line,
        "applicable_rules": with_occ,
        "overdue_rules": len(rows["overdue"]),
        "warning_rules": len(rows["warning"]),
        "missing_baseline_rules": len(rows["missing"]),
    }
    return rows


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


def _periodic_execution_window_cutoff(window: str, today=None) -> "date | None":
    current_day = today or timezone.localdate()
    normalized = _normalize_periodic_execution_window(window)
    if normalized == "all":
        return None
    months = int(normalized)
    cutoff = current_day - timedelta(days=months * 31)
    return cutoff


def _parse_execution_cost_input(raw_value: str | None) -> "Decimal | None":
    cleaned = _clean_string(raw_value)
    if not cleaned:
        return None
    try:
        value = Decimal(cleaned.replace(",", "."))
    except (ArithmeticError, ValueError) as exc:
        raise ValueError("invalid cost") from exc
    if value < 0:
        raise ValueError("negative cost")
    return value


def _serialize_execution_workorder(workorder: WorkOrder) -> dict[str, object]:
    return {
        "workorder": workorder,
        "asset": workorder.asset,
        "asset_label": f"{workorder.asset.asset_tag} - {workorder.asset.name}",
        "supplier_label": str(workorder.supplier) if workorder.supplier else "",
        "executed_at": workorder.closed_at,
        "duration_minutes": workorder.intervention_duration_minutes,
        "downtime_minutes": workorder.downtime_minutes,
        "cost_eur": workorder.resolved_total_cost_eur,
        "resolution": workorder.resolution,
        "title": workorder.title,
        "url": reverse("assets:wo_view", kwargs={"id": workorder.id}),
    }


def _periodic_execution_rows_for_verification(
    *,
    verification_id: int,
    asset_id: int = 0,
    cutoff_date: "date | None" = None,
    limit: int = 25,
) -> list[dict[str, object]]:
    qs = (
        WorkOrder.objects.select_related("asset", "supplier")
        .filter(periodic_verification_id=verification_id, status=WorkOrder.STATUS_DONE)
    )
    if asset_id:
        qs = qs.filter(asset_id=int(asset_id))
    if cutoff_date is not None:
        qs = qs.filter(closed_at__date__gte=cutoff_date)
    qs = qs.order_by("-closed_at", "-id")[: max(1, int(limit))]
    return [_serialize_execution_workorder(workorder) for workorder in qs]


def _maintenance_rule_execution_rows(
    *,
    asset_id: int,
    base_rule_id: int,
    cutoff_date: "date | None" = None,
    limit: int = 10,
) -> list[dict[str, object]]:
    qs = (
        WorkOrder.objects.select_related("asset", "supplier")
        .filter(asset_id=int(asset_id), maintenance_rule_id=int(base_rule_id), status=WorkOrder.STATUS_DONE)
    )
    if cutoff_date is not None:
        qs = qs.filter(closed_at__date__gte=cutoff_date)
    qs = qs.order_by("-closed_at", "-id")[: max(1, int(limit))]
    return [_serialize_execution_workorder(workorder) for workorder in qs]


def _is_assets_admin(request: HttpRequest) -> bool:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if request.user.is_superuser or (legacy_user and is_legacy_admin(legacy_user)):
        return True
    from core.permessi import decisione, sistema_ruoli_attivo

    if sistema_ruoli_attivo():
        # Ruoli: amministra il modulo chi lo «gestisce» su tutti gli asset (IT, Manutenzione).
        esito = decisione(request, "assets", "gestire")
        return bool(esito.consentito and esito.ambito == "tutti")
    return False


def _can_asset_lifecycle_action(request: HttpRequest, *, azione_ruoli: str, azione_acl: str) -> bool:
    """Dismetti/elimina dalla scheda: admin del modulo, oppure chi ha il permesso dedicato.

    Il permesso (``assets/asset_retire``, ``assets/asset_delete``) nasce gia' concesso ai
    ruoli della manutenzione (migrazione 0133) e si estende ad altri ruoli da Accessi.
    Con il sistema dei ruoli attivo decide la matrice («modificare» / «cancellare» su tutti).
    """
    if _is_assets_admin(request):
        return True
    from core.permessi import decisione, sistema_ruoli_attivo

    if sistema_ruoli_attivo():
        esito = decisione(request, "assets", azione_ruoli)
        return bool(esito.consentito and esito.ambito == "tutti")
    return bool(user_can_modulo_action(request, "assets", azione_acl))


def _can_retire_asset(request: HttpRequest) -> bool:
    return _can_asset_lifecycle_action(request, azione_ruoli="modificare", azione_acl="asset_retire")


def _can_delete_asset(request: HttpRequest) -> bool:
    return _can_asset_lifecycle_action(request, azione_ruoli="cancellare", azione_acl="asset_delete")


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
        nome = naming.normalizza_parte(user.nome)
        email = _clean_string(user.email)
        notification_email = _clean_string(getattr(anagrafica, "email_notifica", ""))
        calendar_user_id = email or notification_email
        if not nome and anagrafica:
            nome = naming.nome_completo(getattr(anagrafica, "nome", ""), getattr(anagrafica, "cognome", ""))
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


def _anagrafica_assignment_options() -> tuple[list[tuple[str, str]], dict[str, dict[str, str]], list[str]]:
    try:
        rows = list(
            AnagraficaDipendente.objects.all()
            .order_by("cognome", "nome", "id")[:1000]
        )
    except DatabaseError:
        return [], {}, []

    choices: list[tuple[str, str]] = []
    details: dict[str, dict[str, str]] = {}
    departments: set[str] = set()
    for row in rows:
        display_name = (
            naming.nome_completo(getattr(row, "nome", ""), getattr(row, "cognome", ""))
            or _clean_string(getattr(row, "aliasusername", ""))
            or f"Dipendente #{row.id}"
        )
        reparto = _clean_string(getattr(row, "reparto", ""))
        mansione = _clean_string(getattr(row, "mansione", ""))
        label_bits = [display_name]
        if reparto:
            label_bits.append(reparto)
            departments.add(reparto)
        if mansione:
            label_bits.append(mansione)
        label = " - ".join(label_bits)
        key = str(row.id)
        choices.append((key, label))
        details[key] = {
            "display_name": display_name,
            "reparto": reparto,
            "mansione": mansione,
            "legacy_user_id": str(getattr(row, "utente_id", "") or ""),
        }

    for value in (
        Asset.objects.exclude(reparto="")
        .values_list("reparto", flat=True)
        .distinct()[:300]
    ):
        cleaned = _clean_string(value)
        if cleaned:
            departments.add(cleaned)
    return choices, details, sorted(departments, key=lambda row: row.lower())


def _assignment_form_kwargs(asset: Asset | None = None) -> dict[str, object]:
    employee_choices, employee_details, department_choices = _anagrafica_assignment_options()
    include_in_layout = bool(asset and PlantLayoutMarker.objects.filter(asset=asset).exists())
    return {
        "assignment_employee_choices": employee_choices,
        "assignment_employee_details": employee_details,
        "assignment_department_choices": department_choices,
        "default_include_in_plant_layout": include_in_layout,
    }


def _resolve_asset_plant_layout(asset: Asset) -> tuple["PlantLayout | None", bool]:
    """Sceglie la planimetria attiva più coerente con il reparto dell'asset.

    Ritorna ``(layout, is_specific)``:
      - (a) layout attivo la cui ``category`` coincide col reparto dell'asset;
      - (b) layout attivo con un'area il cui ``reparto_code`` coincide col reparto;
      - (c) fallback: primo layout attivo per (category, name, id).
    ``is_specific`` è True solo per (a)/(b). ``layout`` è ``None`` se non esiste
    alcuna planimetria attiva.
    """
    active = PlantLayout.objects.filter(is_active=True)
    reparto = _clean_string(getattr(asset, "reparto", ""))
    if reparto:
        specific = active.filter(category__iexact=reparto).order_by("category", "name", "id").first()
        if specific is not None:
            return specific, True
        by_area = (
            active.filter(areas__reparto_code__iexact=reparto)
            .order_by("category", "name", "id")
            .first()
        )
        if by_area is not None:
            return by_area, True
    return active.order_by("category", "name", "id").first(), False


def _ensure_asset_plant_layout_marker(asset: Asset) -> str:
    from ..services.plant_layout_image import marker_is_unplaced

    layout, is_specific = _resolve_asset_plant_layout(asset)
    if layout is None:
        return "Asset salvato, ma non inserito in piantina: nessuna planimetria attiva disponibile."

    existing = list(PlantLayoutMarker.objects.filter(asset=asset))
    on_layout = next((m for m in existing if m.layout_id == layout.id), None)
    if on_layout is not None:
        if not on_layout.is_visible:
            on_layout.is_visible = True
            on_layout.save(update_fields=["is_visible", "updated_at"])
        return ""

    # Una macchina già posizionata a mano su un'altra pianta resta dov'è: la
    # scelta dell'utente vale più della pianta dedotta dal reparto. Niente
    # marker di cortesia in più, che finirebbe «da posizionare» altrove.
    if any(not marker_is_unplaced(m) for m in existing):
        return ""

    strays = [m for m in existing if marker_is_unplaced(m)]
    if strays:
        if not is_specific:
            return ""
        # Pianta del reparto trovata e marker mai posizionato altrove: lo
        # spostiamo lì (vincolo unico layout+asset) e togliamo i doppioni.
        moved = strays.pop(0)
        moved.layout = layout
        moved.is_visible = True
        moved.save(update_fields=["layout", "is_visible", "updated_at"])
        for stray in strays:
            stray.delete()
        return ""

    PlantLayoutMarker.objects.create(
        layout=layout,
        asset=asset,
        label=asset.name[:120],
        x_percent=50,
        y_percent=50,
        is_visible=True,
        sort_order=100,
    )
    return ""


def _asset_plant_layout_marker(asset: Asset) -> "PlantLayoutMarker | None":
    """Il marker da mostrare per l'asset. Solo lettura.

    Vince la posizione data a mano: prima un marker posizionato sulla pianta del
    reparto, poi uno posizionato su qualunque pianta attiva; solo se non ce ne
    sono, il marker «da posizionare» (preferendo la pianta del reparto)."""
    from ..services.plant_layout_image import marker_is_unplaced

    markers = list(
        PlantLayoutMarker.objects.filter(asset=asset, layout__is_active=True)
        .select_related("layout")
        .order_by("layout__category", "layout__name", "id")
    )
    if not markers:
        return None
    resolved_layout, specific = _resolve_asset_plant_layout(asset)
    resolved_id = resolved_layout.id if resolved_layout is not None and specific else None
    placed = [m for m in markers if not marker_is_unplaced(m)]
    for group in (placed, markers):
        for marker in group:
            if marker.layout_id == resolved_id:
                return marker
        if group:
            return group[0]
    return None


def _plant_layout_image_size(layout: "PlantLayout | None") -> tuple[int, int]:
    if layout is None or not layout.image:
        return (0, 0)
    try:
        return (int(layout.image.width or 0), int(layout.image.height or 0))
    except (OSError, ValueError, TypeError):
        return (0, 0)


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
    due_date_label = due_date.strftime("%d-%m-%Y")
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


def _as_int(value, default: int = 100) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default
