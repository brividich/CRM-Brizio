from __future__ import annotations

import configparser
import csv
import io
import logging
import os
import re
from urllib.parse import unquote
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db import DatabaseError, connections, transaction
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse, HttpResponseForbidden, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.acl import user_can_modulo_action
from core.audit import log_action
from core.graph_utils import acquire_graph_token, is_placeholder_value
from core.legacy_anagrafica import ensure_anagrafica_schema
from core.legacy_utils import get_legacy_user, is_legacy_admin, legacy_table_columns
from core.models import AuditLog

from .forms import RegistroTimbroForm, save_variant_image
from .models import OperatoreTimbri, RegistroTimbro, RegistroTimbroImmagine

logger = logging.getLogger(__name__)

_READ_ROLE_NAMES = {"admin", "amministrazione", "caporeparto", "hr"}
_EDIT_ROLE_NAMES = {"admin", "amministrazione"}
_TIMBRI_CONFIG_SECTION = "TIMBRI"
_TIMBRI_IMAGE_MAX_DIM = 1600
_TIMBRI_REQUIRED_TABLES = {
    "timbri_operatoretimbri",
    "timbri_registrotimbro",
    "timbri_registrotimbroimmagine",
}
_GUID_RE = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")

TIMBRI_CONFIG_FIELDS = [
    ("list_id", "List ID SharePoint", "GUID della lista SharePoint 'Registro timbri'."),
    ("field_operatore_lookup", "Campo operatore lookup", "Nome interno del lookup operatore."),
    ("field_operatore_label", "Campo operatore label", "Etichetta/nominativo operatore."),
    ("field_matricola", "Campo matricola", "Matricola operatore."),
    ("field_reparto", "Campo reparto", "Reparto operatore."),
    ("field_qualifica", "Campo qualifica", "Qualifica collegata al record."),
    ("field_codice_timbro", "Campo codice timbro", "Codice o nome timbro."),
    ("field_data_consegna", "Campo data consegna", "Data consegna timbro."),
    ("field_data_ritiro", "Campo data ritiro", "Data ritiro / superato."),
    ("field_note", "Campo note", "Note del registro."),
    ("field_firma_testo", "Campo firma testo", "Campo testuale firma/note firma."),
    ("field_attivo", "Campo attivo", "Flag attivo in SharePoint."),
    ("field_tipo_timbro", "Campo tipo timbro", "Fisico, digitale o fisico e digitale."),
    ("field_image_1", "Campo immagine 1", "Prima immagine: Timbro."),
    ("field_image_2", "Campo immagine 2", "Seconda immagine: Firma."),
    ("field_image_3", "Campo immagine 3", "Terza immagine: Sigla."),
]

_FIELD_CANDIDATES = {
    "field_operatore_lookup": ["OperatoreLookupId", "operatorelookupid", "Operatore Lookup"],
    "field_operatore_label": ["Operatore", "OPERATORE CON...", "OPERATORE CONTATTO", "Nominativo"],
    "field_matricola": ["Operatore: Matricola", "Matricola", "matricola"],
    "field_reparto": ["Operatore: Reparto", "Reparto"],
    "field_qualifica": ["Qualifica"],
    "field_codice_timbro": ["Timbro", "Codice Timbro"],
    "field_data_consegna": ["Consegna Timbro", "Data consegna timbro"],
    "field_data_ritiro": ["Data ritiro timbro", "Data ritiro"],
    "field_note": ["Note"],
    "field_firma_testo": ["Firma"],
    "field_attivo": ["Attivo"],
    "field_tipo_timbro": ["Tipo timbro"],
    "field_image_1": ["Timbro digitale", "URL Timbro1", "URL Timbro"],
    "field_image_2": ["Timbro digitale 2", "URL Timbro2"],
    "field_image_3": ["Timbro digitale 3", "URL Timbro3"],
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _config_ini_path() -> Path:
    return _repo_root() / "config.ini"


def _load_app_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(_config_ini_path(), encoding="utf-8")
    return cfg


def _set_ini_option_preserve(section: str, option: str, value: str) -> None:
    path = _config_ini_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    section_key = str(section or "").strip().casefold()
    sec_idx = None
    sec_end = len(lines)
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].strip().casefold()
            if current == section_key:
                sec_idx = idx
                for j in range(idx + 1, len(lines)):
                    nxt = lines[j].strip()
                    if nxt.startswith("[") and nxt.endswith("]"):
                        sec_end = j
                        break
                break
    new_line = f"{option} = {value}"
    if sec_idx is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([f"[{section}]", new_line])
    else:
        option_key = str(option or "").strip().casefold()
        found = None
        for idx in range(sec_idx + 1, sec_end):
            stripped = lines[idx].strip()
            if "=" not in stripped or stripped.startswith("#") or stripped.startswith(";"):
                continue
            key = stripped.split("=", 1)[0].strip().casefold()
            if key == option_key:
                found = idx
                break
        if found is not None:
            lines[found] = new_line
        else:
            lines.insert(sec_end, new_line)
    out = "\n".join(lines)
    if out and not out.endswith("\n"):
        out += "\n"
    path.write_text(out, encoding="utf-8")


def _legacy_user(request):
    return getattr(request, "legacy_user", None) or get_legacy_user(request.user)


def _legacy_role_name(legacy_user) -> str:
    return " ".join(str(getattr(legacy_user, "ruolo", "") or "").strip().lower().split())


def _can_view_timbri(request) -> bool:
    if getattr(request.user, "is_superuser", False):
        return True
    legacy_user = _legacy_user(request)
    if not legacy_user:
        return False
    if is_legacy_admin(legacy_user):
        return True
    if _legacy_role_name(legacy_user) in _READ_ROLE_NAMES:
        return True
    return any(
        user_can_modulo_action(request, "timbri", action)
        for action in ["timbri_home", "timbri_view", "admin_timbri"]
    )


def _can_edit_timbri(request) -> bool:
    if getattr(request.user, "is_superuser", False):
        return True
    legacy_user = _legacy_user(request)
    if not legacy_user:
        return False
    if is_legacy_admin(legacy_user):
        return True
    if _legacy_role_name(legacy_user) in _EDIT_ROLE_NAMES:
        return True
    return user_can_modulo_action(request, "timbri", "timbri_edit")


def _can_manage_timbri_config(request) -> bool:
    return _can_edit_timbri(request)


def _graph_runtime_value(*env_keys: str, option: str) -> tuple[str, str]:
    cfg = _load_app_config()
    az = cfg["AZIENDA"] if cfg.has_section("AZIENDA") else {}
    tim = cfg[_TIMBRI_CONFIG_SECTION] if cfg.has_section(_TIMBRI_CONFIG_SECTION) else {}
    section_obj = tim if option == "list_id" else az
    for key in env_keys:
        raw = (os.getenv(key) or "").strip()
        if raw:
            if option == "list_id":
                raw = _normalize_graph_list_id(raw)
            return raw, "env"
    if hasattr(section_obj, "get"):
        raw = str(section_obj.get(option, "") or "").strip()
        if option == "list_id":
            raw = _normalize_graph_list_id(raw)
        return raw, "config.ini"
    return "", "config.ini"


def _graph_settings() -> dict[str, str]:
    tenant_id, _ = _graph_runtime_value("GRAPH_TENANT_ID", "AZURE_TENANT_ID", option="tenant_id")
    client_id, _ = _graph_runtime_value("GRAPH_CLIENT_ID", "AZURE_CLIENT_ID", option="client_id")
    client_secret, _ = _graph_runtime_value("GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET", option="client_secret")
    site_id, _ = _graph_runtime_value("GRAPH_SITE_ID", option="site_id")
    list_id, _ = _graph_runtime_value("GRAPH_LIST_ID_TIMBRI", option="list_id")
    return {
        "tenant_id": tenant_id,
        "client_id": client_id,
        "client_secret": client_secret,
        "site_id": site_id,
        "list_id": list_id,
    }


def _graph_config_issue() -> str:
    gs = _graph_settings()
    missing = [key for key in ["tenant_id", "client_id", "client_secret", "site_id", "list_id"] if is_placeholder_value(gs.get(key, ""))]
    if not missing:
        return ""
    return "Configurazione Graph timbri incompleta: " + ", ".join(missing)


def _graph_token() -> str:
    issue = _graph_config_issue()
    if issue:
        raise RuntimeError(issue)
    gs = _graph_settings()
    return acquire_graph_token(gs["tenant_id"], gs["client_id"], gs["client_secret"])


def _graph_list_base_url() -> str:
    gs = _graph_settings()
    return f"https://graph.microsoft.com/v1.0/sites/{gs['site_id']}/lists/{gs['list_id']}"


def _graph_healthcheck() -> tuple[bool, str]:
    issue = _graph_config_issue()
    if issue:
        return False, issue
    try:
        response = requests.get(
            f"{_graph_list_base_url()}/items?expand=fields&$top=1",
            headers={"Authorization": f"Bearer {_graph_token()}", "Content-Type": "application/json"},
            timeout=20,
        )
        if response.status_code == 200:
            return True, "Connessione Graph timbri OK."
        return False, f"Graph timbri {response.status_code}: {response.text[:300]}"
    except Exception as exc:
        return False, f"Test Graph timbri fallito: {exc}"


def _config_value(section: str, option: str, default: str = "") -> str:
    cfg = _load_app_config()
    if cfg.has_section(section):
        return str(cfg.get(section, option, fallback=default) or default).strip()
    return default


def _mapping_value(key: str) -> str:
    return _config_value(_TIMBRI_CONFIG_SECTION, key, "")


def _normalize_graph_list_id(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    decoded = unquote(text).strip()
    if decoded.startswith("{") and decoded.endswith("}"):
        decoded = decoded[1:-1].strip()
    match = _GUID_RE.search(decoded) or _GUID_RE.search(text)
    if match:
        return match.group(1).lower()
    return decoded


def _sharepoint_admin_config() -> dict[str, object]:
    tenant_id, tenant_source = _graph_runtime_value("GRAPH_TENANT_ID", "AZURE_TENANT_ID", option="tenant_id")
    client_id, client_source = _graph_runtime_value("GRAPH_CLIENT_ID", "AZURE_CLIENT_ID", option="client_id")
    secret, secret_source = _graph_runtime_value("GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET", option="client_secret")
    site_id, site_source = _graph_runtime_value("GRAPH_SITE_ID", option="site_id")
    list_id, list_source = _graph_runtime_value("GRAPH_LIST_ID_TIMBRI", option="list_id")
    return {
        "tenant_id": _config_value("AZIENDA", "tenant_id", ""),
        "client_id": _config_value("AZIENDA", "client_id", ""),
        "site_id": _config_value("AZIENDA", "site_id", ""),
        "list_id": _normalize_graph_list_id(_config_value(_TIMBRI_CONFIG_SECTION, "list_id", "")),
        "client_secret_configured": bool(_config_value("AZIENDA", "client_secret", "")),
        "runtime_ready": not _graph_config_issue(),
        "runtime_sources": {
            "tenant_id": tenant_source,
            "client_id": client_source,
            "client_secret": secret_source,
            "site_id": site_source,
            "list_id": list_source,
        },
        "env_override_active": any(src == "env" for src in [tenant_source, client_source, secret_source, site_source, list_source]),
        "sync_issue": _graph_config_issue(),
        "mapping": {key: _mapping_value(key) for key, _label, _help in TIMBRI_CONFIG_FIELDS if key.startswith("field_")},
    }


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _is_all_caps_text(value: str) -> bool:
    text = "".join(ch for ch in str(value or "") if ch.isalpha())
    return bool(text) and text == text.upper()


def _legacy_row_identity(row: dict) -> str:
    full_name = f"{_field_to_text(row.get('nome'))} {_field_to_text(row.get('cognome'))}".strip()
    key = _normalized_key(full_name)
    if key:
        return key
    return _normalized_key(_field_to_text(row.get("aliasusername")))


def _legacy_row_score(row: dict) -> tuple[int, int, int, int, int, int]:
    nome = _field_to_text(row.get("nome"))
    cognome = _field_to_text(row.get("cognome"))
    return (
        1 if row.get("utente_id") else 0,
        1 if nome and not _is_all_caps_text(nome) else 0,
        1 if cognome and not _is_all_caps_text(cognome) else 0,
        1 if _field_to_text(row.get("aliasusername")) else 0,
        1 if row.get("attivo") else 0,
        int(row.get("id") or 0),
    )


def _merge_duplicate_legacy_rows(rows: list[dict]) -> list[dict]:
    merged_by_key: dict[str, dict] = {}
    ordered: list[dict] = []
    merge_fields = ["matricola", "reparto", "mansione", "ruolo", "email_notifica", "email", "aliasusername", "attivo"]

    for row in rows:
        key = _legacy_row_identity(row)
        if not key:
            ordered.append(row)
            continue
        current = merged_by_key.get(key)
        if current is None:
            clone = dict(row)
            clone["_merged_ids"] = [int(row.get("id") or 0)]
            merged_by_key[key] = clone
            ordered.append(clone)
            continue

        preferred = current
        alternate = row
        if _legacy_row_score(row) > _legacy_row_score(current):
            preferred = dict(row)
            preferred["_merged_ids"] = list(current.get("_merged_ids") or [])
            alternate = current
            merged_by_key[key] = preferred
            ordered[ordered.index(current)] = preferred

        merged_ids = {int(value) for value in list(preferred.get("_merged_ids") or []) if int(value or 0) > 0}
        merged_ids.add(int(alternate.get("id") or 0))
        preferred["_merged_ids"] = sorted(merged_ids)
        for field_name in merge_fields:
            if _field_to_text(preferred.get(field_name)):
                continue
            value = alternate.get(field_name)
            if value not in {None, ""}:
                preferred[field_name] = value

    return ordered


def _resolve_field_name(fields: dict, configured_value: str, candidates: list[str]) -> str:
    if configured_value:
        if configured_value in fields:
            return configured_value
        norm = _normalized_key(configured_value)
        for key in fields.keys():
            if _normalized_key(key) == norm:
                return str(key)
    normalized_map = {_normalized_key(key): str(key) for key in fields.keys()}
    for candidate in candidates:
        found = normalized_map.get(_normalized_key(candidate))
        if found:
            return found
    return ""


def _extract_field_value(fields: dict, mapping_key: str):
    field_name = _resolve_field_name(fields, _mapping_value(mapping_key), _FIELD_CANDIDATES.get(mapping_key, []))
    if not field_name:
        return None
    return fields.get(field_name)


def _field_to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ["displayValue", "description", "url", "serverUrl", "text", "Value", "value"]:
            raw = value.get(key)
            if raw:
                return str(raw).strip()
        return ""
    if isinstance(value, list):
        return " ".join([str(x).strip() for x in value if str(x or "").strip()])
    return str(value).strip()


def _field_to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    text = _field_to_text(value).lower()
    return text in {"1", "true", "yes", "si", "s", "x"}


def _field_to_date(value):
    text = _field_to_text(value)
    if not text:
        return None
    for fmt in ["%Y-%m-%d", "%d/%m/%Y"]:
        try:
            return datetime.strptime(text[:10], fmt).date()
        except Exception:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except Exception:
        return None


def _tipo_from_text(raw_value: str) -> str:
    text = _field_to_text(raw_value).lower()
    if not text:
        return RegistroTimbro.TIPO_FISICO_E_DIGITALE
    if "fisico" in text and "digit" in text:
        return RegistroTimbro.TIPO_FISICO_E_DIGITALE
    if "digit" in text:
        return RegistroTimbro.TIPO_DIGITALE
    if "fisico" in text:
        return RegistroTimbro.TIPO_FISICO
    return RegistroTimbro.TIPO_ALTRO


def _legacy_employee_rows(*, legacy_id: int | None = None) -> list[dict]:
    cols = legacy_table_columns("anagrafica_dipendenti")
    if not cols:
        return []
    wanted = [
        c
        for c in ["id", "aliasusername", "nome", "cognome", "matricola", "reparto", "mansione", "ruolo", "email_notifica", "attivo"]
        if c in cols
    ]
    if not wanted:
        return []
    with connections["default"].cursor() as cursor:
        sql = f"SELECT {', '.join(wanted)} FROM anagrafica_dipendenti"
        params: list[object] = []
        if legacy_id is not None and "id" in wanted:
            sql += " WHERE id = %s"
            params.append(int(legacy_id))
        sql += " ORDER BY cognome, nome"
        cursor.execute(sql, params)
        headers = [str(col[0]).lower() for col in cursor.description]
        rows = [dict(zip(headers, row)) for row in cursor.fetchall()]
    if legacy_id is not None:
        return rows
    return _merge_duplicate_legacy_rows(rows)


def _legacy_role_value(row: dict) -> str:
    return _field_to_text(row.get("mansione") or row.get("ruolo"))[:200]


def _legacy_full_name(row: dict) -> str:
    text = f"{_field_to_text(row.get('cognome'))} {_field_to_text(row.get('nome'))}".strip()
    return " ".join(text.split()) or _field_to_text(row.get("aliasusername")) or f"anagrafica:{row.get('id')}"


def _load_legacy_employee(legacy_id: int) -> dict | None:
    rows = _legacy_employee_rows(legacy_id=legacy_id)
    return rows[0] if rows else None


def _normalize_text_key(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _find_legacy_employee(*, lookup_value, label_value, matricola_value) -> dict | None:
    lookup_text = _field_to_text(lookup_value)
    label = _field_to_text(label_value)
    matricola = _field_to_text(matricola_value)

    if lookup_text.isdigit():
        row = _load_legacy_employee(int(lookup_text))
        if row:
            return row

    rows = _legacy_employee_rows()
    if matricola:
        search_matricola = matricola.casefold()
        for row in rows:
            if _field_to_text(row.get("matricola")).casefold() == search_matricola:
                return row

    if label:
        search_label = _normalize_text_key(label)
        for row in rows:
            options = {
                _normalize_text_key(_legacy_full_name(row)),
                _normalize_text_key(f"{_field_to_text(row.get('nome'))} {_field_to_text(row.get('cognome'))}"),
                _normalize_text_key(f"{_field_to_text(row.get('cognome'))} {_field_to_text(row.get('nome'))}"),
            }
            if search_label in options:
                return row
    return None


def _ensure_legacy_operatore(row: dict) -> OperatoreTimbri:
    legacy_id = int(row.get("id") or 0)
    if legacy_id <= 0:
        raise RuntimeError("ID anagrafica non valido.")

    defaults = {
        "nome": _field_to_text(row.get("nome"))[:200] or "Operatore",
        "cognome": _field_to_text(row.get("cognome"))[:200],
        "matricola": _field_to_text(row.get("matricola"))[:100],
        "reparto": _field_to_text(row.get("reparto"))[:200],
        "ruolo": _legacy_role_value(row),
        "email_notifica": _field_to_text(row.get("email_notifica"))[:200],
        "is_active_legacy": bool(row.get("attivo")) if row.get("attivo") is not None else True,
    }
    obj = OperatoreTimbri.objects.filter(legacy_anagrafica_id=legacy_id).first()
    if obj is None:
        return OperatoreTimbri.objects.create(legacy_anagrafica_id=legacy_id, **defaults)

    updates: list[str] = []
    for field_name, value in defaults.items():
        if getattr(obj, field_name) != value:
            setattr(obj, field_name, value)
            updates.append(field_name)
    if updates:
        obj.save(update_fields=updates + ["updated_at"])
    return obj


def cleanup_orphan_operatori() -> dict[str, int]:
    summary = {
        "orphans": 0,
        "deleted_empty": 0,
        "relinked_operatori": 0,
        "records_relinked": 0,
        "unmatched_with_records": 0,
    }
    orphans = list(
        OperatoreTimbri.objects.filter(legacy_anagrafica_id__isnull=True).annotate(record_count=Count("registri")).order_by("id")
    )
    for operatore in orphans:
        summary["orphans"] += 1
        row = _find_legacy_employee(
            lookup_value="",
            label_value=operatore.full_name,
            matricola_value=operatore.matricola,
        )
        if row is not None:
            target = _ensure_legacy_operatore(row)
            moved = RegistroTimbro.objects.filter(operatore=operatore).update(operatore=target)
            summary["records_relinked"] += int(moved)
            operatore.delete()
            summary["relinked_operatori"] += 1
            continue
        if int(getattr(operatore, "record_count", 0) or 0) > 0:
            summary["unmatched_with_records"] += 1
            continue
        operatore.delete()
        summary["deleted_empty"] += 1
    return summary


def reset_timbri_table() -> dict[str, int]:
    ensure_anagrafica_schema()
    summary = {
        "deleted_images": 0,
        "deleted_records": 0,
        "deleted_operatori": 0,
        "imported_operatori": 0,
    }
    employee_rows = _legacy_employee_rows()
    with transaction.atomic():
        summary["deleted_images"], _ = RegistroTimbroImmagine.objects.all().delete()
        summary["deleted_records"], _ = RegistroTimbro.objects.all().delete()
        summary["deleted_operatori"], _ = OperatoreTimbri.objects.all().delete()
        for row in employee_rows:
            _ensure_legacy_operatore(row)
            summary["imported_operatori"] += 1
    return summary


def _employee_row_payload(row: dict, bridge: OperatoreTimbri | None = None) -> dict:
    legacy_id = int(row.get("id") or 0)
    active_records = int(getattr(bridge, "active_records", 0) or 0)
    historical_records = int(getattr(bridge, "historical_records", 0) or 0)
    return {
        "legacy_id": legacy_id,
        "full_name": _legacy_full_name(row),
        "nome": _field_to_text(row.get("nome")),
        "cognome": _field_to_text(row.get("cognome")),
        "aliasusername": _field_to_text(row.get("aliasusername")),
        "matricola": _field_to_text(row.get("matricola")),
        "reparto": _field_to_text(row.get("reparto")),
        "ruolo": _legacy_role_value(row),
        "email_notifica": _field_to_text(row.get("email_notifica")),
        "is_active_legacy": bool(row.get("attivo")) if row.get("attivo") is not None else True,
        "active_records": active_records,
        "historical_records": historical_records,
        "timbri_count": active_records + historical_records,
        "bridge_id": getattr(bridge, "id", None),
    }


def _resolve_operatore(lookup_value, label_value, matricola_value, reparto_value, ruolo_value) -> OperatoreTimbri:
    row = _find_legacy_employee(
        lookup_value=lookup_value,
        label_value=label_value,
        matricola_value=matricola_value,
    )
    if row is None:
        reparto = _field_to_text(reparto_value)
        ruolo = _field_to_text(ruolo_value)
        raise LookupError(
            "Operatore non trovato nell'anagrafica centrale"
            + (f" (matricola {matricola_value})" if _field_to_text(matricola_value) else "")
            + (f" [reparto {reparto}]" if reparto else "")
            + (f" [ruolo {ruolo}]" if ruolo else "")
        )
    return _ensure_legacy_operatore(row)


def _attach_image_maps(registri: list[RegistroTimbro]) -> None:
    for registro in registri:
        registro.image_map = {img.variante: img for img in registro.immagini.all()}
        registro.image_slots = [
            {"key": RegistroTimbroImmagine.VARIANTE_TIMBRO, "label": "Timbro", "image": registro.image_map.get(RegistroTimbroImmagine.VARIANTE_TIMBRO)},
            {"key": RegistroTimbroImmagine.VARIANTE_FIRMA, "label": "Firma", "image": registro.image_map.get(RegistroTimbroImmagine.VARIANTE_FIRMA)},
            {"key": RegistroTimbroImmagine.VARIANTE_SIGLA, "label": "Sigla", "image": registro.image_map.get(RegistroTimbroImmagine.VARIANTE_SIGLA)},
        ]


def _normalize_png(content: bytes) -> bytes:
    image = Image.open(io.BytesIO(content))
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "A" in image.mode else "RGB")
    if max(image.size or (0, 0)) > _TIMBRI_IMAGE_MAX_DIM:
        image.thumbnail((_TIMBRI_IMAGE_MAX_DIM, _TIMBRI_IMAGE_MAX_DIM))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _extract_image_url(value) -> str:
    if not value:
        return ""
    if isinstance(value, dict):
        for key in ["url", "serverUrl", "serverRelativeUrl", "webUrl", "fileUrl"]:
            raw = value.get(key)
            if raw:
                return str(raw).strip()
        for key in ["value", "Value"]:
            nested = value.get(key)
            if nested:
                return _extract_image_url(nested)
        return ""
    text = _field_to_text(value)
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return ""


def _download_image(url: str) -> bytes:
    if not url:
        raise RuntimeError("URL immagine mancante")
    token = None
    try:
        token = _graph_token()
    except Exception:
        token = None
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code == 401 and headers:
        response = requests.get(url, timeout=30)
    response.raise_for_status()
    return _normalize_png(response.content)


def _save_remote_variant(registro: RegistroTimbro, variante: str, raw_value) -> bool:
    image_url = _extract_image_url(raw_value)
    if not image_url:
        return False
    existing = RegistroTimbroImmagine.objects.filter(registro=registro, variante=variante).first()
    if existing and existing.source_url == image_url and existing.image:
        return False
    content = _download_image(image_url)
    uploaded = ContentFile(content, name=f"{variante.lower()}_{registro.pk}.png")
    image_obj = save_variant_image(registro=registro, variante=variante, uploaded_file=uploaded)
    image_obj.source_url = image_url[:1000]
    image_obj.save(update_fields=["source_url", "updated_at"])
    return True


def _graph_list_items() -> list[dict]:
    token = _graph_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    next_url = f"{_graph_list_base_url()}/items?expand=fields&$top=200"
    items: list[dict] = []
    iterations = 0
    while next_url and iterations < 20:
        response = requests.get(next_url, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json() if response.text else {}
        items.extend(list(payload.get("value") or []))
        next_url = str(payload.get("@odata.nextLink") or "").strip()
        iterations += 1
    return items


def _import_sharepoint_records(request) -> dict[str, int]:
    summary = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "images": 0}
    now = timezone.now()
    items = _graph_list_items()
    for item in items:
        fields = item.get("fields") if isinstance(item, dict) else {}
        if not isinstance(fields, dict):
            summary["failed"] += 1
            continue
        sharepoint_item_id = str(item.get("id") or "").strip()
        try:
            operatore = _resolve_operatore(
                _extract_field_value(fields, "field_operatore_lookup"),
                _extract_field_value(fields, "field_operatore_label"),
                _extract_field_value(fields, "field_matricola"),
                _extract_field_value(fields, "field_reparto"),
                _extract_field_value(fields, "field_qualifica"),
            )
            existing = RegistroTimbro.objects.filter(sharepoint_item_id=sharepoint_item_id).order_by("-id").first()
            if existing and existing.edited_in_portal:
                summary["skipped"] += 1
                continue

            registro = existing or RegistroTimbro(operatore=operatore, sharepoint_item_id=sharepoint_item_id)
            registro.operatore = operatore
            registro.codice_timbro = _field_to_text(_extract_field_value(fields, "field_codice_timbro"))[:120]
            registro.qualifica = _field_to_text(_extract_field_value(fields, "field_qualifica"))[:200]
            registro.tipo_timbro = _tipo_from_text(_extract_field_value(fields, "field_tipo_timbro"))
            registro.data_consegna = _field_to_date(_extract_field_value(fields, "field_data_consegna"))
            registro.data_ritiro = _field_to_date(_extract_field_value(fields, "field_data_ritiro"))
            registro.note = _field_to_text(_extract_field_value(fields, "field_note"))
            registro.firma_testo = _field_to_text(_extract_field_value(fields, "field_firma_testo"))
            attivo_raw = _extract_field_value(fields, "field_attivo")
            registro.is_attivo = _field_to_bool(attivo_raw) if attivo_raw is not None else not bool(registro.data_ritiro)
            registro.is_archived = not registro.is_attivo and bool(registro.data_ritiro)
            registro.last_import_at = now
            if not existing:
                registro.imported_at = now
            registro.edited_in_portal = False
            registro.save()

            for variante, key in [
                (RegistroTimbroImmagine.VARIANTE_TIMBRO, "field_image_1"),
                (RegistroTimbroImmagine.VARIANTE_FIRMA, "field_image_2"),
                (RegistroTimbroImmagine.VARIANTE_SIGLA, "field_image_3"),
            ]:
                try:
                    if _save_remote_variant(registro, variante, _extract_field_value(fields, key)):
                        summary["images"] += 1
                except Exception:
                    logger.exception("[timbri] download immagine fallito item=%s variante=%s", sharepoint_item_id, variante)

            summary["updated" if existing else "created"] += 1
        except Exception:
            summary["failed"] += 1
            logger.exception("[timbri] import item failed id=%s", sharepoint_item_id)

    log_action(request, "timbri_import_sharepoint", "timbri", summary)
    return summary


def _forbidden():
    return HttpResponseForbidden("Permesso negato.")


def _timbri_schema_issue() -> str:
    try:
        with connections["default"].cursor() as cursor:
            existing_tables = {
                str(name).strip().lower()
                for name in connections["default"].introspection.table_names(cursor)
            }
    except DatabaseError as exc:
        logger.warning("[timbri] verifica schema fallita: %s", exc)
        return "Impossibile verificare lo schema SQL del modulo Timbri."

    missing_tables = sorted(table for table in _TIMBRI_REQUIRED_TABLES if table not in existing_tables)
    if not missing_tables:
        return ""
    return (
        "Modulo Timbri non inizializzato sul database SQL Server. "
        "Mancano le tabelle: "
        + ", ".join(missing_tables)
        + ". Esegui `manage.py migrate timbri`."
    )


def _empty_page(page_number):
    return Paginator([], 30).get_page(page_number)


def _base_context(request, **extra):
    legacy_user = _legacy_user(request)
    display_name = (
        (legacy_user.nome if legacy_user else None)
        or request.user.get_full_name()
        or request.user.username
    )
    base = {
        "page_title": "Registro timbri",
        "current": extra.get("current", "timbri:index"),
        "username": display_name,
        "can_edit_timbri": _can_edit_timbri(request),
        "can_manage_timbri_config": _can_manage_timbri_config(request),
    }
    base.update(extra)
    return base


@login_required
def index(request):
    if not _can_view_timbri(request):
        return _forbidden()

    schema_issue = _timbri_schema_issue()
    if schema_issue:
        return render(
            request,
            "timbri/pages/index.html",
            _base_context(
                request,
                current="timbri:index",
                page_obj=_empty_page(request.GET.get("page")),
                q=str(request.GET.get("q") or "").strip(),
                reparto=str(request.GET.get("reparto") or "").strip(),
                reparti=[],
                schema_issue=schema_issue,
                stats={
                    "dipendenti": 0,
                    "con_timbri": 0,
                    "record_attivi": 0,
                },
            ),
        )

    q = str(request.GET.get("q") or "").strip()
    reparto = str(request.GET.get("reparto") or "").strip()
    rows = _legacy_employee_rows()
    reparti = sorted({_field_to_text(row.get("reparto")) for row in rows if _field_to_text(row.get("reparto"))})
    if q:
        q_norm = q.casefold()
        rows = [
            row
            for row in rows
            if any(
                q_norm in value.casefold()
                for value in [
                    _legacy_full_name(row),
                    _field_to_text(row.get("aliasusername")),
                    _field_to_text(row.get("matricola")),
                    _field_to_text(row.get("reparto")),
                    _legacy_role_value(row),
                ]
                if value
            )
        ]
    if reparto:
        rows = [row for row in rows if _field_to_text(row.get("reparto")).casefold() == reparto.casefold()]

    legacy_ids = [int(row.get("id") or 0) for row in rows if int(row.get("id") or 0) > 0]
    bridge_map = {
        int(obj.legacy_anagrafica_id): obj
        for obj in (
            OperatoreTimbri.objects.filter(legacy_anagrafica_id__in=legacy_ids)
            .annotate(
                active_records=Count("registri", filter=Q(registri__is_attivo=True, registri__is_archived=False), distinct=True),
                historical_records=Count("registri", filter=Q(registri__is_attivo=False) | Q(registri__is_archived=True), distinct=True),
            )
        )
        if obj.legacy_anagrafica_id
    }
    entries = [_employee_row_payload(row, bridge_map.get(int(row.get("id") or 0))) for row in rows]
    paginator = Paginator(entries, 30)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "timbri/pages/index.html",
        _base_context(
            request,
            current="timbri:index",
            page_obj=page_obj,
            q=q,
            reparto=reparto,
            reparti=reparti,
            stats={
                "dipendenti": len(rows),
                "con_timbri": sum(1 for item in entries if item["timbri_count"] > 0),
                "record_attivi": RegistroTimbro.objects.filter(is_attivo=True, is_archived=False).count(),
            },
        ),
    )


@login_required
def operatore_delete(request, operatore_id: int):
    if not _can_edit_timbri(request):
        return _forbidden()
    schema_issue = _timbri_schema_issue()
    if schema_issue:
        messages.error(request, schema_issue)
        return redirect("timbri:index")
    if request.method != "POST":
        return HttpResponseForbidden("Metodo non consentito.")

    operatore = get_object_or_404(OperatoreTimbri, pk=operatore_id)
    if operatore.legacy_anagrafica_id:
        messages.error(request, "I dipendenti collegati all'anagrafica centrale non si eliminano dal modulo timbri.")
        return redirect("timbri:operatore_detail_by_legacy", legacy_id=int(operatore.legacy_anagrafica_id))
    operatore_label = operatore.full_name
    registri = list(
        RegistroTimbro.objects.filter(operatore=operatore).prefetch_related(
            Prefetch("immagini", queryset=RegistroTimbroImmagine.objects.all())
        )
    )
    record_count = len(registri)
    image_count = sum(record.immagini.count() for record in registri)

    for record in registri:
        for image in list(record.immagini.all()):
            image.delete()
        record.delete()
    operatore.delete()

    log_action(
        request,
        "timbri_operatore_delete",
        "timbri",
        {"operatore_id": operatore_id, "record_count": record_count, "image_count": image_count},
    )
    messages.success(request, f"Operatore {operatore_label} eliminato.")
    return redirect("timbri:index")


@login_required
def operatore_create(request):
    if not _can_edit_timbri(request):
        return _forbidden()
    messages.info(request, "Gli operatori si gestiscono dall'anagrafica centrale. Da timbri puoi solo aggiungere record ai dipendenti esistenti.")
    return redirect("anagrafica:dipendenti_list")


@login_required
def operatore_detail(request, operatore_id: int):
    if not _can_view_timbri(request):
        return _forbidden()
    schema_issue = _timbri_schema_issue()
    if schema_issue:
        messages.error(request, schema_issue)
        return redirect("timbri:index")

    operatore = get_object_or_404(OperatoreTimbri, pk=operatore_id)
    if operatore.legacy_anagrafica_id:
        return redirect("timbri:operatore_detail_by_legacy", legacy_id=int(operatore.legacy_anagrafica_id))

    registri_qs = RegistroTimbro.objects.filter(operatore=operatore).prefetch_related(
        Prefetch("immagini", queryset=RegistroTimbroImmagine.objects.order_by("variante"))
    )
    active_records = list(registri_qs.filter(is_attivo=True, is_archived=False))
    historical_records = list(registri_qs.exclude(is_attivo=True, is_archived=False))
    _attach_image_maps(active_records)
    _attach_image_maps(historical_records)

    return render(
        request,
        "timbri/pages/operatore_detail.html",
        _base_context(
            request,
            current="timbri:index",
            operatore=operatore,
            employee={
                "legacy_id": None,
                "full_name": operatore.full_name,
                "matricola": operatore.matricola,
                "reparto": operatore.reparto,
                "ruolo": operatore.ruolo,
                "email_notifica": operatore.email_notifica,
                "source_label": "bridge locale",
            },
            is_central_profile=False,
            active_records=active_records,
            historical_records=historical_records,
            stats={
                "totale": registri_qs.count(),
                "attivi": len(active_records),
                "storico": len(historical_records),
            },
        ),
    )


@login_required
def operatore_detail_by_legacy(request, legacy_id: int):
    if not _can_view_timbri(request):
        return _forbidden()
    schema_issue = _timbri_schema_issue()
    if schema_issue:
        messages.error(request, schema_issue)
        return redirect("timbri:index")

    row = _load_legacy_employee(legacy_id)
    if row is None:
        messages.error(request, "Dipendente non trovato nell'anagrafica centrale.")
        return redirect("timbri:index")

    operatore = _ensure_legacy_operatore(row)
    registri_qs = RegistroTimbro.objects.filter(operatore=operatore).prefetch_related(
        Prefetch("immagini", queryset=RegistroTimbroImmagine.objects.order_by("variante"))
    )
    active_records = list(registri_qs.filter(is_attivo=True, is_archived=False))
    historical_records = list(registri_qs.exclude(is_attivo=True, is_archived=False))
    _attach_image_maps(active_records)
    _attach_image_maps(historical_records)

    return render(
        request,
        "timbri/pages/operatore_detail.html",
        _base_context(
            request,
            current="timbri:index",
            operatore=operatore,
            employee={
                "legacy_id": int(row.get("id") or 0),
                "full_name": _legacy_full_name(row),
                "matricola": _field_to_text(row.get("matricola")),
                "reparto": _field_to_text(row.get("reparto")),
                "ruolo": _legacy_role_value(row),
                "email_notifica": _field_to_text(row.get("email_notifica")),
                "source_label": "anagrafica centrale",
            },
            is_central_profile=True,
            active_records=active_records,
            historical_records=historical_records,
            stats={
                "totale": registri_qs.count(),
                "attivi": len(active_records),
                "storico": len(historical_records),
            },
        ),
    )


def _save_record_from_form(request, form: RegistroTimbroForm, *, operatore: OperatoreTimbri) -> RegistroTimbro:
    registro = form.save(commit=False)
    registro.operatore = operatore
    registro.updated_by = request.user
    registro.edited_in_portal = True
    registro.is_archived = False
    if not registro.pk:
        registro.created_by = request.user
    registro.save()
    for field_name, variante in [
        ("image_timbro", RegistroTimbroImmagine.VARIANTE_TIMBRO),
        ("image_firma", RegistroTimbroImmagine.VARIANTE_FIRMA),
        ("image_sigla", RegistroTimbroImmagine.VARIANTE_SIGLA),
    ]:
        uploaded = form.cleaned_data.get(field_name)
        if uploaded:
            save_variant_image(registro=registro, variante=variante, uploaded_file=uploaded)
    return registro


@login_required
def registro_create(request, operatore_id: int):
    if not _can_edit_timbri(request):
        return _forbidden()
    schema_issue = _timbri_schema_issue()
    if schema_issue:
        messages.error(request, schema_issue)
        return redirect("timbri:index")
    operatore = get_object_or_404(OperatoreTimbri, pk=operatore_id)
    if operatore.legacy_anagrafica_id:
        return redirect("timbri:registro_create_by_legacy", legacy_id=int(operatore.legacy_anagrafica_id))
    if request.method == "POST":
        form = RegistroTimbroForm(request.POST, request.FILES)
        if form.is_valid():
            registro = _save_record_from_form(request, form, operatore=operatore)
            log_action(request, "timbri_registro_create", "timbri", {"operatore_id": operatore.id, "registro_id": registro.id})
            messages.success(request, "Registro timbro salvato.")
            return redirect("timbri:operatore_detail", operatore_id=operatore.id)
    else:
        form = RegistroTimbroForm(initial={"is_attivo": True, "tipo_timbro": RegistroTimbro.TIPO_FISICO_E_DIGITALE})
    return render(
        request,
        "timbri/pages/record_form.html",
        _base_context(
            request,
            current="timbri:index",
            operatore=operatore,
            employee={"legacy_id": None, "full_name": operatore.full_name},
            form=form,
            form_title="Nuovo record timbro",
            record=None,
        ),
    )


@login_required
def registro_create_by_legacy(request, legacy_id: int):
    if not _can_edit_timbri(request):
        return _forbidden()
    schema_issue = _timbri_schema_issue()
    if schema_issue:
        messages.error(request, schema_issue)
        return redirect("timbri:index")

    row = _load_legacy_employee(legacy_id)
    if row is None:
        messages.error(request, "Dipendente non trovato nell'anagrafica centrale.")
        return redirect("timbri:index")

    operatore = _ensure_legacy_operatore(row)
    if request.method == "POST":
        form = RegistroTimbroForm(request.POST, request.FILES)
        if form.is_valid():
            registro = _save_record_from_form(request, form, operatore=operatore)
            log_action(request, "timbri_registro_create", "timbri", {"operatore_id": operatore.id, "registro_id": registro.id})
            messages.success(request, "Registro timbro salvato.")
            return redirect("timbri:operatore_detail_by_legacy", legacy_id=legacy_id)
    else:
        form = RegistroTimbroForm(initial={"is_attivo": True, "tipo_timbro": RegistroTimbro.TIPO_FISICO_E_DIGITALE})
    return render(
        request,
        "timbri/pages/record_form.html",
        _base_context(
            request,
            current="timbri:index",
            operatore=operatore,
            employee={"legacy_id": int(row.get("id") or 0), "full_name": _legacy_full_name(row)},
            form=form,
            form_title="Nuovo record timbro",
            record=None,
        ),
    )


@login_required
def registro_edit(request, record_id: int):
    if not _can_edit_timbri(request):
        return _forbidden()
    schema_issue = _timbri_schema_issue()
    if schema_issue:
        messages.error(request, schema_issue)
        return redirect("timbri:index")
    record = get_object_or_404(
        RegistroTimbro.objects.prefetch_related(Prefetch("immagini", queryset=RegistroTimbroImmagine.objects.order_by("variante"))),
        pk=record_id,
    )
    _attach_image_maps([record])
    if request.method == "POST" and str(request.POST.get("action") or "").strip() == "archive":
        record.is_attivo = False
        record.is_archived = True
        if not record.data_ritiro:
            record.data_ritiro = timezone.now().date()
        record.edited_in_portal = True
        record.updated_by = request.user
        record.save(update_fields=["is_attivo", "is_archived", "data_ritiro", "edited_in_portal", "updated_by", "updated_at"])
        log_action(request, "timbri_registro_archive", "timbri", {"registro_id": record.id, "operatore_id": record.operatore_id})
        messages.success(request, "Record archiviato.")
        if record.operatore.legacy_anagrafica_id:
            return redirect("timbri:operatore_detail_by_legacy", legacy_id=int(record.operatore.legacy_anagrafica_id))
        return redirect("timbri:operatore_detail", operatore_id=record.operatore_id)

    if request.method == "POST":
        form = RegistroTimbroForm(request.POST, request.FILES, instance=record)
        if form.is_valid():
            registro = _save_record_from_form(request, form, operatore=record.operatore)
            log_action(request, "timbri_registro_update", "timbri", {"registro_id": registro.id, "operatore_id": registro.operatore_id})
            messages.success(request, "Record aggiornato.")
            if registro.operatore.legacy_anagrafica_id:
                return redirect("timbri:operatore_detail_by_legacy", legacy_id=int(registro.operatore.legacy_anagrafica_id))
            return redirect("timbri:operatore_detail", operatore_id=registro.operatore_id)
    else:
        form = RegistroTimbroForm(instance=record)

    employee = {
        "legacy_id": None,
        "full_name": record.operatore.full_name,
    }
    if record.operatore.legacy_anagrafica_id:
        row = _load_legacy_employee(int(record.operatore.legacy_anagrafica_id))
        employee = {
            "legacy_id": int(record.operatore.legacy_anagrafica_id),
            "full_name": _legacy_full_name(row) if row else record.operatore.full_name,
        }
    return render(
        request,
        "timbri/pages/record_form.html",
        _base_context(
            request,
            current="timbri:index",
            operatore=record.operatore,
            employee=employee,
            form=form,
            form_title="Modifica record timbro",
            record=record,
        ),
    )


@login_required
def configurazione_page(request):
    if not _can_manage_timbri_config(request):
        return _forbidden()

    schema_issue = _timbri_schema_issue()
    tab = str(request.GET.get("tab") or "config").strip() or "config"
    if request.method == "POST":
        action = str(request.POST.get("action") or "").strip()
        redirect_url = f"{reverse('timbri:configurazione')}?tab={tab}"
        if action == "save_sharepoint_config":
            try:
                for field_name, _label, _help in TIMBRI_CONFIG_FIELDS:
                    value = str(request.POST.get(field_name) or "").strip()[:1000]
                    if field_name == "list_id":
                        value = _normalize_graph_list_id(value)
                    _set_ini_option_preserve(_TIMBRI_CONFIG_SECTION, field_name, value)
                messages.success(request, "Configurazione timbri aggiornata.")
                log_action(request, "timbri_config_save", "timbri", {"fields": [x[0] for x in TIMBRI_CONFIG_FIELDS]})
            except Exception as exc:
                messages.error(request, f"Errore scrittura config.ini: {exc}")
            return redirect(redirect_url)
        if action == "test_sharepoint_config":
            ok, message = _graph_healthcheck()
            if ok:
                messages.success(request, message)
            else:
                messages.error(request, message)
            return redirect(redirect_url)
        if action == "import_sharepoint":
            if schema_issue:
                messages.error(request, schema_issue)
                return redirect(redirect_url)
            try:
                result = _import_sharepoint_records(request)
                messages.success(
                    request,
                    f"Import completato. Creati={result['created']} Aggiornati={result['updated']} Skippati={result['skipped']} Falliti={result['failed']} Immagini={result['images']}",
                )
            except Exception as exc:
                logger.exception("[timbri] import sharepoint fallito")
                messages.error(request, f"Import SharePoint fallito: {exc}")
            return redirect(f"{reverse('timbri:configurazione')}?tab=import")
        if action == "cleanup_orphans":
            if schema_issue:
                messages.error(request, schema_issue)
                return redirect(redirect_url)
            try:
                result = cleanup_orphan_operatori()
                messages.success(
                    request,
                    "Bonifica completata. "
                    f"Orfani={result['orphans']} "
                    f"Riallineati={result['relinked_operatori']} "
                    f"Record spostati={result['records_relinked']} "
                    f"Vuoti eliminati={result['deleted_empty']} "
                    f"Non agganciati con record={result['unmatched_with_records']}",
                )
                log_action(request, "timbri_cleanup_orphans", "timbri", result)
            except Exception as exc:
                logger.exception("[timbri] bonifica orfani fallita")
                messages.error(request, f"Bonifica operatori orfani fallita: {exc}")
            return redirect(redirect_url)
        if action == "reset_table":
            if schema_issue:
                messages.error(request, schema_issue)
                return redirect(redirect_url)
            try:
                result = reset_timbri_table()
                messages.success(
                    request,
                    "Reset tabella completato. "
                    f"Immagini eliminate={result['deleted_images']} "
                    f"Registri eliminati={result['deleted_records']} "
                    f"Operatori eliminati={result['deleted_operatori']} "
                    f"Nominativi reimportati={result['imported_operatori']}",
                )
                log_action(request, "timbri_reset_table", "timbri", result)
            except Exception as exc:
                logger.exception("[timbri] reset tabella fallito")
                messages.error(request, f"Reset tabella timbri fallito: {exc}")
            return redirect(f"{reverse('timbri:configurazione')}?tab=import")

    audit_entries = AuditLog.objects.filter(modulo="timbri").order_by("-created_at")[:100]
    sharepoint_config = _sharepoint_admin_config()
    mapping = dict(sharepoint_config.get("mapping") or {})
    config_rows = [
        {
            "name": field_name,
            "label": field_label,
            "help": field_help,
            "value": mapping.get(field_name, "") if field_name.startswith("field_") else sharepoint_config.get(field_name, ""),
        }
        for field_name, field_label, field_help in TIMBRI_CONFIG_FIELDS
    ]
    return render(
        request,
        "timbri/pages/configurazione.html",
        _base_context(
            request,
            current="timbri:configurazione",
            tab=tab,
            sharepoint_admin_config=sharepoint_config,
            config_rows=config_rows,
            audit_entries=audit_entries,
            schema_issue=schema_issue,
            local_stats={
                "linked_anagrafica": 0 if schema_issue else OperatoreTimbri.objects.filter(legacy_anagrafica_id__isnull=False).count(),
                "registri": 0 if schema_issue else RegistroTimbro.objects.count(),
                "orphan_operatori": 0 if schema_issue else OperatoreTimbri.objects.filter(legacy_anagrafica_id__isnull=True).count(),
            },
        ),
    )


class _Echo:
    def write(self, value):
        return value


@login_required
def export_csv(request):
    if not _can_manage_timbri_config(request):
        return _forbidden()
    schema_issue = _timbri_schema_issue()
    if schema_issue:
        return HttpResponse(schema_issue, status=503, content_type="text/plain; charset=utf-8")

    def stream():
        writer = csv.writer(_Echo())
        headers = [
            "operatore",
            "matricola",
            "reparto",
            "ruolo",
            "codice_timbro",
            "qualifica",
            "tipo_timbro",
            "data_consegna",
            "data_ritiro",
            "is_attivo",
            "is_archived",
            "sharepoint_item_id",
            "edited_in_portal",
        ]
        yield writer.writerow(headers)
        qs = RegistroTimbro.objects.select_related("operatore").order_by("operatore__cognome", "operatore__nome", "-created_at")
        for row in qs.iterator():
            yield writer.writerow(
                [
                    row.operatore.full_name,
                    row.operatore.matricola,
                    row.operatore.reparto,
                    row.operatore.ruolo,
                    row.codice_timbro,
                    row.qualifica,
                    row.get_tipo_timbro_display(),
                    row.data_consegna.isoformat() if row.data_consegna else "",
                    row.data_ritiro.isoformat() if row.data_ritiro else "",
                    "1" if row.is_attivo else "0",
                    "1" if row.is_archived else "0",
                    row.sharepoint_item_id,
                    "1" if row.edited_in_portal else "0",
                ]
            )

    log_action(request, "timbri_export_csv", "timbri", {"count": RegistroTimbro.objects.count()})
    response = StreamingHttpResponse(stream(), content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = 'attachment; filename="registro_timbri.csv"'
    return response
