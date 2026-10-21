"""Inventario: lista asset, creazione e modifica, componenti, PART 145, modifiche in blocco.

Estratto meccanicamente da assets/views.py (refactor C4): nessun cambio di comportamento.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
from datetime import timedelta
from urllib.parse import quote
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.text import slugify

from core.acl import user_can_modulo_action
from core.audit import log_action

# Etichetta con cui le voci di audit si agganciano all'asset: e' la stessa che
# `core.audit.storico_oggetto` usa per ripescarle sulla scheda. Costante e non
# stringa sparsa perche' un refuso qui non romperebbe nulla — semplicemente la
# voce non comparirebbe mai nello storico, e non se ne accorgerebbe nessuno.
AUDIT_OGGETTO_ASSET = "assets.asset"
from core.legacy_models import AnagraficaDipendente
from core.legacy_utils import get_legacy_user
from core.models import UserDashboardLayout
from ..forms import (
    AssetAssignmentForm,
    AssetComponentForm,
    AssetFilterForm,
    AssetForm,
    ChemicalAssetForm,
    PRODUCTION_ASSET_TYPES,
)
from ..models import (
    Asset,
    AssetActionButton,
    AssetCategory,
    AssetCategoryField,
    AssetComponent,
    AssetCustomField,
    AssetDetailField,
    AssetDetailSectionLayout,
    AssetHeaderTool,
    AssetListLayout,
    AssetListOption,
    AssetSidebarButton,
    WorkOrder,
)
from ..maintenance import (
    get_workorder_overdue_days,
)
from ..services import storico_asset
from ..models import AssetFieldHistory

from ._helpers import (  # noqa: F401
    ASSET_LIST_COMMON_COLUMNS,
    ASSET_LIST_IT_COLUMNS,
    CATEGORY_ACTIONS,
    DETAIL_FIELD_ACTIONS,
    SIDEBAR_ACTIONS,
    _as_int,
    _asset_administrative_deadline_page_url,
    _asset_component_create_page_url,
    _asset_component_page_url,
    _assignment_form_kwargs,
    _clean_string,
    _coalesce_str,
    _ensure_asset_plant_layout_marker,
    _is_assets_admin,
    _legacy_employee_options,
    _ui_choices,
)
from ._helpers_b import (  # noqa: F401
    _build_asset_list_suggestions,
    _dashboard_open_workorder_alert_rows,
)
from ._helpers_c import (  # noqa: F401
    _asset_list_context_definition_map,
    _asset_list_context_definitions,
    _asset_list_valid_column_keys,
    _assets_shell_context,
    _can_edit_asset,
    _category_subtree_ids,
    _handle_asset_category_request,
    _handle_detail_field_request,
    _handle_sidebar_button_request,
    _query_url,
    _sanitize_asset_list_visible_columns,
    _validate_asset_image,
)

DEFAULT_IMPORT_SHEETS = ",".join(
    [
        "LAN A 203.0.113.x",
        "LAN B 198.51.100.x",
        "LAN C 192.0.2.x",
    ]
)

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

HEADER_TOOL_ACTIONS = {"update_header_tool"}


def _can_manage_asset_list_layout(request: HttpRequest) -> bool:
    if _is_assets_admin(request):
        return True
    return bool(
        user_can_modulo_action(request, "assets", "admin_assets")
        or user_can_modulo_action(request, "assets", "asset_list_layout")
    )


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
    columns = list(ASSET_LIST_COMMON_COLUMNS)
    if _clean_string(asset_type).upper() in {Asset.TYPE_PC, Asset.TYPE_NOTEBOOK}:
        columns.extend(ASSET_LIST_IT_COLUMNS)
    return columns


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
                elif not row.is_customized and row.visible_columns != list(item["visible_columns"]):
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
    switch_port_values = []
    patch_panel_values = []
    for endpoint in endpoints:
        if endpoint.vlan is not None:
            vlan_values.append(str(endpoint.vlan))
        if endpoint.ip:
            ip_values.append(str(endpoint.ip))
        if endpoint.switch_port:
            switch_label = " · ".join(
                value for value in (_clean_string(endpoint.switch_name), _clean_string(endpoint.switch_port)) if value
            )
            switch_port_values.append(switch_label)
        if endpoint.punto:
            patch_panel_values.append(endpoint.punto)
    return {
        "vlan": _join_unique(vlan_values),
        "ip": _join_unique(ip_values),
        "switch_port": _join_unique(switch_port_values),
        "patch_panel_port": _join_unique(patch_panel_values),
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
            utente_id=request.user.pk,
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
                "detail_timeline_manual_enabled",
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
def asset_part_145_list(request: HttpRequest) -> HttpResponse:
    """Dossier PART 145: processo, attrezzature, personale, scadenze e situazioni aperte."""
    from ..services import part145_dossier

    context = {
        "page_title": "Dossier PART 145",
        "dossier": part145_dossier.costruisci(**part145_dossier.visibilita(request)),
        # Shell context: senza questo la sidebar del modulo asset resta vuota.
        **_assets_shell_context(request, search_action=reverse("assets:asset_list")),
    }
    return render(request, "assets/pages/part_145_list.html", context)


def _studio_redirect(request: HttpRequest) -> HttpResponse:
    """Dopo un'azione dello «Studio inventario» si torna da dove si e' partiti.

    Lo Studio vive in Impostazioni (tab «Studio inventario») ma le sue azioni
    restano su questo endpoint: i form mandano ``next``. Solo URL interni.
    """
    from django.utils.http import url_has_allowed_host_and_scheme

    candidate = _clean_string(request.POST.get("next"))
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(candidate)
    return redirect("assets:asset_list")


# Soglie del sottotitolo «Salute asset» nella lista (percentuale di asset non in
# riparazione): >= 90 Buona, 70-89 Da monitorare, < 70 Critica.
ASSET_HEALTH_GOOD_MIN = 90
ASSET_HEALTH_WATCH_MIN = 70


@login_required
def asset_list(request: HttpRequest) -> HttpResponse:
    can_manage_custom_fields = _is_assets_admin(request)

    if request.method == "GET" and request.GET.get("category") and not request.GET.get("asset_category"):
        next_query = request.GET.copy()
        next_query["asset_category"] = request.GET.get("category")
        next_query.pop("category", None)
        query_string = next_query.urlencode()
        target_url = reverse("assets:asset_list")
        return redirect(f"{target_url}?{query_string}" if query_string else target_url)

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
            # L'import crea e (update_existing default=1) SOVRASCRIVE asset in blocco:
            # e' una scrittura di massa, non un'azione operativa. Solo admin asset,
            # come tutte le altre azioni di questo dispatcher.
            if not can_manage_custom_fields:
                log_action(
                    request,
                    "import_assets_excel",
                    "assets",
                    {"esito": "denied", "motivo": "permission_denied"},
                )
                return render(request, "core/pages/forbidden.html", status=403)
            ok, text = _handle_excel_import_request(request)
            log_action(
                request,
                "import_assets_excel",
                "assets",
                {"esito": "success" if ok else "error", "messaggio": text[:500]},
            )
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, f"Import Excel fallito: {text}")
            return redirect("assets:asset_list")
        if action in {"create_custom_field", "update_custom_field", "delete_custom_field"}:
            if not can_manage_custom_fields:
                messages.error(request, "Solo admin puo modificare i campi personalizzati.")
                return _studio_redirect(request)
            ok, text = _handle_custom_field_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return _studio_redirect(request)
        if action in LIST_ACTIONS:
            if not can_manage_custom_fields:
                messages.error(request, "Solo admin puo modificare le liste.")
                return _studio_redirect(request)
            ok, text = _handle_list_option_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return _studio_redirect(request)
        if action in BUTTON_ACTIONS:
            if not can_manage_custom_fields:
                messages.error(request, "Solo admin puo modificare i pulsanti.")
                return _studio_redirect(request)
            ok, text = _handle_action_button_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return _studio_redirect(request)
        if action in DETAIL_FIELD_ACTIONS:
            if not can_manage_custom_fields:
                messages.error(request, "Solo admin puo modificare il dettaglio asset.")
                return _studio_redirect(request)
            ok, text = _handle_detail_field_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return _studio_redirect(request)
        if action in CATEGORY_ACTIONS:
            if not can_manage_custom_fields:
                messages.error(request, "Solo admin puo modificare categorie e campi asset.")
                return _studio_redirect(request)
            ok, text = _handle_asset_category_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return _studio_redirect(request)
        if action in SIDEBAR_ACTIONS:
            if not can_manage_custom_fields:
                messages.error(request, "Solo admin puo modificare il menu sidebar.")
                return _studio_redirect(request)
            ok, text = _handle_sidebar_button_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return _studio_redirect(request)
        if action in HEADER_TOOL_ACTIONS:
            if not can_manage_custom_fields:
                messages.error(request, "Solo admin puo modificare gli strumenti header.")
                return _studio_redirect(request)
            ok, text = _handle_header_tool_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return _studio_redirect(request)
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

    # Contesto "Asset produzione": la vecchia pagina dedicata (work_machine_list)
    # e' confluita qui. ?group=production restringe l'inventario ai soli asset
    # di produzione (CNC / macchine di lavoro / carroponte), riusando la stessa
    # lista, colonne e ricerca degli altri tipi.
    # IMPORTANTE: il filtro di gruppo vale solo per la VISTA di navigazione
    # (nessuna ricerca). Appena c'e' una query testuale la ricerca deve spaziare
    # su TUTTO l'inventario: l'utente cerca un asset ovunque sia classificato,
    # anche se il suo tipo non e' di produzione (es. una macchina registrata con
    # tipo generico). Confinare la ricerca al gruppo nasconderebbe risultati.
    production_group = _clean_string(request.GET.get("group")).lower() == "production"
    search_active = bool(_clean_string(request.GET.get("q")))
    if production_group:
        assets = assets.select_related("work_machine")
        if not search_active:
            assets = assets.filter(asset_type__in=PRODUCTION_ASSET_TYPES)

    if form.is_valid():
        q = _clean_string(form.cleaned_data.get("q"))
        asset_type = _clean_string(form.cleaned_data.get("asset_type"))
        asset_category = form.cleaned_data.get("asset_category")
        reparto = _clean_string(form.cleaned_data.get("reparto"))
        vlan = form.cleaned_data.get("vlan")
        ip = _clean_string(form.cleaned_data.get("ip"))
        cnc_only = bool(form.cleaned_data.get("cnc_only"))
        five_axes_only = bool(form.cleaned_data.get("five_axes_only"))
        tcr_only = bool(form.cleaned_data.get("tcr_only"))

        if q:
            assets = assets.filter(
                Q(asset_tag__icontains=q)
                | Q(internal_number__icontains=q)
                | Q(name__icontains=q)
                | Q(serial_number__icontains=q)
                | Q(manufacturer__icontains=q)
                | Q(model__icontains=q)
                | Q(endpoints__endpoint_name__icontains=q)
                | Q(endpoints__ip__icontains=q)
            )
        if asset_type:
            assets = assets.filter(asset_type=asset_type)
        if asset_category:
            # Filtro per sottoalbero: la categoria selezionata e tutte le sue
            # discendenti (clic su una radice mostra tutti i suoi asset).
            assets = assets.filter(asset_category_id__in=_category_subtree_ids(asset_category))
        if reparto:
            assets = assets.filter(reparto__icontains=reparto)
        if vlan is not None:
            assets = assets.filter(endpoints__vlan=vlan)
        if ip:
            assets = assets.filter(endpoints__ip__icontains=ip)
        # Filtri di produzione (capability del profilo WorkMachine): attivi solo
        # quando l'utente li spunta, indipendentemente dal gruppo selezionato.
        if cnc_only:
            assets = assets.filter(work_machine__cnc_controlled=True)
        if five_axes_only:
            assets = assets.filter(work_machine__five_axes=True)
        if tcr_only:
            assets = assets.filter(work_machine__tcr_enabled=True)

    assets_filtered = assets.distinct().order_by("name", "asset_tag")

    allowed_rows = [10, 25, 50, 100]
    rows = _as_int(request.GET.get("rows"), default=25)
    if rows not in allowed_rows:
        rows = 25
    paginator = Paginator(assets_filtered, rows)
    page_number = _as_int(request.GET.get("page"), default=1)
    page_obj = paginator.get_page(page_number)
    assets = page_obj.object_list
    from ..services.it_monitoring import monitoring_dots

    # Pallino del Monitor SNMP (stato salvato, nessuna interrogazione) accanto al nome.
    _dots = monitoring_dots(request, [a.id for a in assets])
    for _asset in assets:
        _asset.snmp_dot = _dots.get(_asset.id)
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
    selected_asset_category = form.cleaned_data.get("asset_category") if form.is_valid() else None
    asset_list_context_key, asset_list_context_label = _asset_list_context(current_asset_type)
    if production_group:
        asset_list_context_label = "Asset produzione"
    custom_fields = list(AssetCustomField.objects.filter(is_active=True).order_by("sort_order", "id"))
    all_custom_fields = list(AssetCustomField.objects.order_by("sort_order", "id"))
    list_layouts_by_context = {
        row.context_key: row
        for row in _ensure_default_asset_list_layouts()
    }
    current_list_layout = list_layouts_by_context.get(asset_list_context_key)
    valid_list_column_keys = _asset_list_valid_column_keys(custom_fields)
    user_asset_table_layout = _load_user_asset_table_layout(request, asset_list_context_key, valid_list_column_keys)
    suggested_visible_columns = _asset_list_default_columns(current_asset_type)
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
    # Valori lista e categorie servono solo alla modale «Modifica in blocco».
    list_options = list(AssetListOption.objects.filter(is_active=True).order_by("field_key", "sort_order", "value", "id"))
    asset_categories = list(AssetCategory.objects.filter(is_active=True).order_by("sort_order", "label", "id"))
    # KPI: scope by structural filters (category + type) to reflect the current view
    kpi_qs = Asset.objects.all()
    if form.is_valid():
        _kf_type = _clean_string(form.cleaned_data.get("asset_type"))
        _kf_cat = form.cleaned_data.get("asset_category")
        if _kf_type:
            kpi_qs = kpi_qs.filter(asset_type=_kf_type)
        if _kf_cat:
            kpi_qs = kpi_qs.filter(asset_category_id__in=_category_subtree_ids(_kf_cat))

    total_assets = kpi_qs.count()
    in_use_count = kpi_qs.filter(status=Asset.STATUS_IN_USE).count()
    in_repair_count = kpi_qs.filter(status=Asset.STATUS_IN_REPAIR).count()
    assigned_count = kpi_qs.exclude(assignment_to__isnull=True).exclude(assignment_to="").count()
    _kpi_wo_qs = WorkOrder.objects.filter(asset__in=kpi_qs)
    open_wo_count = _kpi_wo_qs.filter(status=WorkOrder.STATUS_OPEN).count()
    maintenance_due_count = _kpi_wo_qs.filter(
        status=WorkOrder.STATUS_OPEN,
        opened_at__lt=timezone.now() - timedelta(days=get_workorder_overdue_days()),
    ).count()
    work_machine_total = Asset.objects.filter(asset_type__in=PRODUCTION_ASSET_TYPES).count()

    # Salute = quota di asset NON in riparazione sul totale filtrato; rischio =
    # asset in riparazione + OdL aperti (unita' diverse: niente barra, solo numero).
    health_percent = 0.0
    in_use_percent = 0.0
    if total_assets > 0:
        health_percent = max(0.0, round((1 - (in_repair_count / total_assets)) * 100, 1))
        in_use_percent = max(0.0, min(100.0, round((in_use_count / total_assets) * 100, 1)))
    risk_count = in_repair_count + open_wo_count
    if health_percent >= ASSET_HEALTH_GOOD_MIN:
        health_label = "Buona"
    elif health_percent >= ASSET_HEALTH_WATCH_MIN:
        health_label = "Da monitorare"
    else:
        health_label = "Critica"
    if not total_assets:
        health_label = "Nessun asset"
    # Manutenzioni in scadenza = OdL aperti da oltre la soglia di ritardo: il
    # denominatore e' il totale degli OdL aperti dello stesso perimetro.
    due_percent = round(maintenance_due_count / open_wo_count * 100, 1) if open_wo_count else 0.0

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
        asset.endpoint_switch_port_display = endpoint_summary["switch_port"]
        asset.endpoint_patch_panel_display = endpoint_summary["patch_panel_port"]

    recent_alerts: list[dict[str, str]] = []
    open_wo_alerts = _dashboard_open_workorder_alert_rows(limit=4)
    for workorder in open_wo_alerts:
        is_critical = workorder.opened_at < timezone.now() - timedelta(days=14)
        recent_alerts.append(
            {
                "title": workorder.title or f"Intervento su {workorder.asset.asset_tag}",
                "message": _coalesce_str(workorder.description, f"Asset {workorder.asset.asset_tag} richiede attenzione."),
                "time": workorder.opened_at.strftime("%d-%m-%Y %H:%M"),
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
                    "time": row["updated_at"].strftime("%d-%m-%Y %H:%M") if row.get("updated_at") else "-",
                    "level": "warning",
                }
            )
    if not recent_alerts:
        recent_alerts.append(
            {
                "title": "Nessun alert critico",
                "message": "La situazione asset e stabile.",
                "time": timezone.now().strftime("%d-%m-%Y %H:%M"),
                "level": "ok",
            }
        )

    return render(
        request,
        "assets/pages/asset_list.html",
        {
            "page_title": "Asset produzione" if production_group else "Inventario asset",
            "production_group": production_group,
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
            "custom_fields": custom_fields,
            "all_custom_fields": all_custom_fields,
            "asset_list_context_key": asset_list_context_key,
            "asset_list_context_label": asset_list_context_label,
            "selected_asset_category": selected_asset_category,
            "asset_list_default_visible_columns": asset_list_default_visible_columns,
            "asset_list_default_visible_columns_json": json.dumps(asset_list_default_visible_columns),
            "asset_table_saved_layout_json": json.dumps(user_asset_table_layout),
            "asset_table_layout_can_persist": bool(_asset_table_layout_storage_user_id(request) is not None),
            "asset_list_layout_revision": asset_list_layout_revision,
            "asset_list_layout_manage_url": _asset_list_layout_manage_url(request, asset_list_context_key),
            "asset_list_layout_is_customized": bool(current_list_layout and current_list_layout.is_customized),
            "list_options": list_options,
            "asset_categories": asset_categories,
            "asset_category_type_choices": _ui_choices(Asset.TYPE_CHOICES),
            "can_manage_custom_fields": can_manage_custom_fields,
            "can_gestione_admin": user_can_modulo_action(request, "assets", "admin_assets"),
            **_header_tool_visibility(can_manage_custom_fields),
            # Lo Studio inventario e' in Impostazioni: la shell non mostra il suo
            # «+ Nuovo asset», la pagina ne ha uno con il menu (asset, macchina, chimico).
            "assets_shell_hide_new": True,
            "table_colspan": 7 + len(custom_fields),
            "health_percent": health_percent,
            "health_label": health_label,
            "due_percent": due_percent,
            "open_wo_count": open_wo_count,
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


#: Convenzione storica del numero interno asset in produzione: "Int.NNN".
INTERNAL_NUMBER_PREFIX = "Int"
INTERNAL_NUMBER_SEP = "."
INTERNAL_NUMBER_PAD = 3


@login_required
def asset_internal_number_next(request: HttpRequest) -> JsonResponse:
    """Prossimo numero interno progressivo (opt-in): il form lo richiede solo su
    click del bottone "Assegna progressivo". Non è una chiave univoca.

    Segue la convenzione storica "Int.NNN" (es. Int.263 = max Int.262 + 1),
    assorbendo nella stessa sequenza gli eventuali valori nudi legacy (es. 196/197)."""
    from core.numbering import next_prefixed

    value = next_prefixed(
        Asset.objects.values_list("internal_number", flat=True),
        prefix=INTERNAL_NUMBER_PREFIX,
        sep=INTERNAL_NUMBER_SEP,
        pad=INTERNAL_NUMBER_PAD,
    )
    return JsonResponse({"next": value})


@login_required
def chemical_asset_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ChemicalAssetForm(request.POST)
        if form.is_valid():
            with storico_asset.traccia(fonte=AssetFieldHistory.FONTE_FORM, utente=request.user,
                                       dettaglio="Nuovo prodotto chimico") as storico:
                asset = form.save()
                storico.aggiungi(asset.pk)
            messages.success(request, "Asset prodotto chimico creato.")
            return redirect("assets:asset_view", id=asset.id)
    else:
        form = ChemicalAssetForm()
    return render(
        request,
        "assets/pages/chemical_asset_form.html",
        {
            "page_title": "Nuovo prodotto chimico",
            "form": form,
            "is_edit": False,
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


@login_required
def chemical_asset_edit(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:asset_list")
    asset = get_object_or_404(Asset, pk=id)
    if request.method == "POST":
        form = ChemicalAssetForm(request.POST, instance=asset)
        if form.is_valid():
            with storico_asset.traccia([asset.pk], fonte=AssetFieldHistory.FONTE_FORM, utente=request.user,
                                       dettaglio="Modifica prodotto chimico"):
                asset = form.save()
            messages.success(request, "Asset prodotto chimico aggiornato.")
            return redirect("assets:asset_view", id=asset.id)
    else:
        initial = {}
        if asset.prodotto_chimico_id:
            initial = {"prodotto_mode": "existing", "prodotto_chimico": asset.prodotto_chimico_id}
        form = ChemicalAssetForm(instance=asset, initial=initial)
    return render(
        request,
        "assets/pages/chemical_asset_form.html",
        {
            "page_title": f"Modifica {asset.asset_tag}",
            "form": form,
            "asset": asset,
            "is_edit": True,
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


@login_required
def asset_create(request: HttpRequest) -> HttpResponse:
    if _clean_string(request.GET.get("asset_type")) == Asset.TYPE_WORK_MACHINE:
        return redirect("assets:work_machine_create")
    if _clean_string(request.GET.get("asset_type")) == Asset.TYPE_CHEMICAL:
        return redirect("assets:chemical_create")
    custom_fields = list(AssetCustomField.objects.filter(is_active=True).order_by("sort_order", "id"))
    list_suggestions = _build_asset_list_suggestions()
    assignment_kwargs = _assignment_form_kwargs()
    if request.method == "POST":
        form = AssetForm(request.POST, request.FILES, custom_fields=custom_fields, list_suggestions=list_suggestions, **assignment_kwargs)
        if form.is_valid():
            with storico_asset.traccia(fonte=AssetFieldHistory.FONTE_FORM, utente=request.user,
                                       dettaglio="Nuovo asset") as storico:
                asset = form.save()
                storico.aggiungi(asset.pk)
            if form.cleaned_data.get("include_in_plant_layout"):
                marker_warning = _ensure_asset_plant_layout_marker(asset)
                if marker_warning:
                    messages.warning(request, marker_warning)

            messages.success(request, "Asset creato correttamente.")
            return redirect("assets:asset_view", id=asset.id)
    else:
        form = AssetForm(custom_fields=custom_fields, list_suggestions=list_suggestions, **assignment_kwargs)
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
            "assignment_department_choices": assignment_kwargs["assignment_department_choices"],
            "assignment_employee_details": assignment_kwargs["assignment_employee_details"],

            "plant_layout_field_names": ["include_in_plant_layout"],
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


@login_required
def asset_image_upload(request: HttpRequest, id: int) -> HttpResponse:
    """Carica, sostituisce o rimuove l'immagine mostrata come icona della scheda."""
    if request.method != "POST":
        return HttpResponseForbidden("Metodo non consentito.")
    asset = get_object_or_404(Asset, pk=id)
    if not _can_edit_asset(request, asset.id):
        return HttpResponseForbidden("Non hai il permesso di modificare questo asset.")
    previous = asset.immagine.name if asset.immagine else ""
    if request.POST.get("clear_immagine") == "1":
        asset.immagine = None
        messages.success(request, "Immagine rimossa.")
    else:
        upload = request.FILES.get("immagine")
        if upload is None:
            messages.error(request, "Seleziona un'immagine da caricare.")
            return redirect("assets:asset_view", id=asset.id)
        error = _validate_asset_image(upload)
        if error:
            messages.error(request, error)
            return redirect("assets:asset_view", id=asset.id)
        asset.immagine = upload
        messages.success(request, "Immagine aggiornata.")
    asset.save(update_fields=["immagine"])
    if previous and previous != (asset.immagine.name if asset.immagine else ""):
        Asset._meta.get_field("immagine").storage.delete(previous)
    return redirect("assets:asset_view", id=asset.id)


@login_required
def asset_edit(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:asset_list")
    asset = get_object_or_404(Asset, pk=id)
    if asset.asset_type == Asset.TYPE_WORK_MACHINE:
        return redirect("assets:work_machine_edit", id=asset.id)
    if asset.asset_type == Asset.TYPE_CHEMICAL:
        return redirect("assets:chemical_edit", id=asset.id)
    custom_fields = list(AssetCustomField.objects.filter(is_active=True).order_by("sort_order", "id"))
    list_suggestions = _build_asset_list_suggestions()
    assignment_kwargs = _assignment_form_kwargs(asset)
    if request.method == "POST":
        form = AssetForm(
            request.POST,
            request.FILES,
            instance=asset,
            custom_fields=custom_fields,
            list_suggestions=list_suggestions,
            **assignment_kwargs,
        )
        if form.is_valid():
            with storico_asset.traccia([asset.pk], fonte=AssetFieldHistory.FONTE_FORM, utente=request.user,
                                       dettaglio="Modifica asset"):
                asset = form.save()
            if form.cleaned_data.get("include_in_plant_layout"):
                marker_warning = _ensure_asset_plant_layout_marker(asset)
                if marker_warning:
                    messages.warning(request, marker_warning)

            messages.success(request, "Asset aggiornato.")
            return redirect("assets:asset_view", id=asset.id)
    else:
        form = AssetForm(instance=asset, custom_fields=custom_fields, list_suggestions=list_suggestions, **assignment_kwargs)
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
            "assignment_department_choices": assignment_kwargs["assignment_department_choices"],
            "assignment_employee_details": assignment_kwargs["assignment_employee_details"],

            "plant_layout_field_names": ["include_in_plant_layout"],
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
            with storico_asset.traccia([asset.pk], fonte=AssetFieldHistory.FONTE_FORM, utente=request.user,
                                       dettaglio="Assegnazione"):
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


@login_required
def asset_bulk_update(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Metodo non consentito"}, status=405)
    # Scrittura di massa (stato, categoria, assegnazioni, note) su N asset: solo admin.
    # Endpoint JSON -> 403 JSON, mai redirect HTML.
    if not _is_assets_admin(request):
        log_action(
            request,
            "asset_bulk_update",
            "assets",
            {"esito": "denied", "motivo": "permission_denied"},
        )
        return JsonResponse({"ok": False, "error": "Permessi insufficienti."}, status=403)
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

    _ALLOWED_BULK_FIELDS = {
        "status", "asset_type", "asset_category_id",
        "reparto", "manufacturer", "model",
        "assignment_to", "assignment_reparto", "assignment_location",
        "notes",
    }
    _valid_statuses = {k for k, _ in Asset.STATUS_CHOICES}
    _valid_asset_types = {k for k, _ in Asset.TYPE_CHOICES}

    update_kwargs: dict = {}
    for field, value in fields.items():
        if field not in _ALLOWED_BULK_FIELDS:
            continue
        if field == "status":
            if value not in _valid_statuses:
                return JsonResponse({"ok": False, "error": f"Stato non valido: {value}"}, status=400)
            update_kwargs[field] = str(value)
        elif field == "asset_type":
            if value not in _valid_asset_types:
                return JsonResponse({"ok": False, "error": f"Tipo asset non valido: {value}"}, status=400)
            update_kwargs[field] = str(value)
        elif field == "asset_category_id":
            str_value = str(value).strip()
            if str_value in ("", "0", "null", "None"):
                update_kwargs["asset_category_id"] = None
            else:
                try:
                    cat_id = int(str_value)
                except (ValueError, TypeError):
                    return JsonResponse({"ok": False, "error": "ID categoria non valido"}, status=400)
                if not AssetCategory.objects.filter(pk=cat_id).exists():
                    return JsonResponse({"ok": False, "error": "Categoria non trovata"}, status=400)
                update_kwargs["asset_category_id"] = cat_id
        else:
            update_kwargs[field] = str(value)

    if not update_kwargs:
        return JsonResponse({"ok": False, "error": "Nessun campo valido da aggiornare"}, status=400)

    try:
        clean_ids = [int(i) for i in ids]
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "error": "ID asset non validi"}, status=400)

    # queryset.update() salta save(): lo storico lo fotografa il servizio, prima e dopo.
    # A blocchi: SQL Server non accetta piu' di 2.100 parametri per query.
    updated = 0
    with storico_asset.traccia(clean_ids, fonte=AssetFieldHistory.FONTE_BULK, utente=request.user,
                               dettaglio="Modifica in blocco"):
        for start in range(0, len(clean_ids), storico_asset.CHUNK):
            updated += Asset.objects.filter(pk__in=clean_ids[start:start + storico_asset.CHUNK]).update(**update_kwargs)
    log_action(
        request,
        "asset_bulk_update",
        "assets",
        {
            "asset_ids": clean_ids[:200],
            "asset_count": len(clean_ids),
            "campi": update_kwargs,
            "aggiornati": updated,
            "esito": "success",
        },
    )
    return JsonResponse({"ok": True, "updated": updated})
