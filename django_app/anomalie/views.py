from __future__ import annotations

import configparser
import csv
import json
import logging
import mimetypes
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import requests
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, connections, transaction
from django.http import FileResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from core.acl import user_can_modulo_action
from core.audit import log_action
from core.graph_utils import acquire_graph_token, is_placeholder_value
from core.legacy_models import AnagraficaDipendente
from core.legacy_utils import get_legacy_user, is_legacy_admin, legacy_table_columns
from core.models import Notifica


logger = logging.getLogger(__name__)


ANOMALIE_LIST_KEYS = (
    "capi_reparto",
    "capi_commessa",
    "causali_doc",
    "stati_superficie",
    "avanzamenti",
    "autorizzati_modifica",
)
ANOMALIE_LIST_DEFAULTS = {
    "capi_reparto": [],
    "capi_commessa": [],
    "causali_doc": ["OP", "OG"],
    "stati_superficie": ["Finito macchinato", "Con sovrametallo", "Finito trattato"],
    "avanzamenti": ["Accetto lo stato", "In attesa", "Finito trattato"],
    "autorizzati_modifica": [
        "Benedetta Bellucci",
        "Serena Giani",
        "Luca Bova",
        "Simone Smarrella",
        "Sara Gentile",
    ],
}
ANOMALIE_NON_EMPTY_DEFAULT_KEYS = frozenset({"causali_doc", "stati_superficie", "avanzamenti"})
ANOMALIE_ATTACHMENTS_DIR_DEFAULT = r"media\anomalie_allegati"
ALLEGATI_ALLOWED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".csv",
}
ALLEGATI_MAX_FILE_SIZE = 20 * 1024 * 1024
_ALLEGATI_FILE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
ALLEGATI_SYNC_META_FILENAME = "__sync_meta__.json"
ALLEGATI_SYNC_PENDING = "pending"
ALLEGATI_SYNC_SYNCED = "synced"
ALLEGATI_SYNC_ERROR = "error"
ALLEGATI_SYNC_MAX_RETRY = 5
ALLEGATI_SYNC_MAX_PER_LOCAL = 20


def _json_error(msg: str, status: int = 400):
    return JsonResponse({"error": msg}, status=status)


def _has_table(table_name: str) -> bool:
    return bool(legacy_table_columns(table_name))


def _fetch_all_dict(sql: str, params: list | tuple | None = None) -> list[dict]:
    with connections["default"].cursor() as cursor:
        cursor.execute(sql, params or [])
        cols = [str(c[0]) for c in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _config_ini_path() -> Path:
    return _repo_root() / "config.ini"


def _load_app_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(_config_ini_path(), encoding="utf-8")
    return cfg


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_anomalie_attachments_path(raw_value: str | None = None) -> tuple[str, Path]:
    rel = str(raw_value or "").strip() or ANOMALIE_ATTACHMENTS_DIR_DEFAULT
    if len(rel) > 500:
        raise ValueError("Percorso allegati troppo lungo")
    path = Path(rel)
    if not path.is_absolute():
        path = _repo_root() / path
    return rel, path


def _anomalie_attachments_root() -> Path:
    cfg = _load_app_config()
    rel_cfg = ANOMALIE_ATTACHMENTS_DIR_DEFAULT
    if cfg.has_section("ANOMALIE"):
        rel_cfg = str(cfg.get("ANOMALIE", "attachments_dir", fallback=rel_cfg) or rel_cfg).strip() or rel_cfg
    _, path = _resolve_anomalie_attachments_path(rel_cfg)
    return path


def _anomalie_attachments_dir_value() -> str:
    cfg = _load_app_config()
    rel = ANOMALIE_ATTACHMENTS_DIR_DEFAULT
    if cfg.has_section("ANOMALIE"):
        rel = str(cfg.get("ANOMALIE", "attachments_dir", fallback=rel) or rel).strip() or rel
    return rel


def _set_ini_option_preserve(section: str, option: str, value: str) -> None:
    path = _config_ini_path()
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    sec_idx = None
    sec_end = len(lines)
    section_key = str(section or "").strip().casefold()
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
        lines.append(f"[{section}]")
        lines.append(new_line)
    else:
        opt_idx = None
        option_key = str(option or "").strip().casefold()
        for j in range(sec_idx + 1, sec_end):
            stripped = lines[j].strip()
            if not stripped or stripped.startswith(";") or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key = stripped.split("=", 1)[0].strip().casefold()
            if key == option_key:
                opt_idx = j
                break
        if opt_idx is not None:
            lines[opt_idx] = new_line
        else:
            lines.insert(sec_end, new_line)

    out = "\n".join(lines)
    if out and not out.endswith("\n"):
        out += "\n"
    path.write_text(out, encoding="utf-8")


def _save_anomalie_attachments_dir(value: str) -> str:
    cleaned, _ = _resolve_anomalie_attachments_path(value)
    _set_ini_option_preserve("ANOMALIE", "attachments_dir", cleaned)
    return cleaned


def _validate_anomalie_attachments_dir(value: str) -> str:
    cleaned, path = _resolve_anomalie_attachments_path(value)
    if not path.exists():
        raise ValueError(f"La cartella allegati non esiste: {path}")
    if not path.is_dir():
        raise ValueError(f"Il percorso allegati non è una cartella: {path}")

    probe = path / f".write_test_{uuid4().hex}.tmp"
    try:
        with probe.open("wb") as fh:
            fh.write(b"ok")
    except OSError as exc:
        raise ValueError(f"La cartella allegati non è scrivibile: {path} ({exc})") from exc
    finally:
        try:
            if probe.exists():
                probe.unlink()
        except OSError:
            pass
    return cleaned


def _safe_attachment_filename(raw_name: str) -> str:
    name = Path(str(raw_name or "").strip()).name
    if not name:
        return ""
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    clean = re.sub(r"_+", "_", clean).strip("._")
    if not clean:
        return ""
    if len(clean) > 120:
        stem = Path(clean).stem[:80]
        suffix = Path(clean).suffix[:20]
        clean = f"{stem}{suffix}"
    return clean


def _is_allowed_attachment(filename: str) -> bool:
    ext = Path(filename).suffix.lower()
    return bool(ext and ext in ALLEGATI_ALLOWED_EXTENSIONS)


def _is_image_attachment(filename: str, mime_type: str | None = None) -> bool:
    ext = Path(filename).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}:
        return True
    return bool(mime_type and str(mime_type).startswith("image/"))


def _anomaly_local_row(local_id: int) -> dict | None:
    if not _has_table("anomalie"):
        return None
    rows = _fetch_all_dict(
        "SELECT TOP 1 id, ex_op_nominativo FROM anomalie WHERE id = %s",
        [int(local_id)],
    )
    return rows[0] if rows else None


def _attachment_dir_for_local(local_id: int, *, create: bool = False) -> Path:
    base = _anomalie_attachments_root()
    if create:
        base.mkdir(parents=True, exist_ok=True)
    folder = base / str(int(local_id))
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def _attachment_display_name(file_id: str) -> str:
    if "__" in file_id:
        return file_id.split("__", 1)[1]
    return file_id


def _attachment_file_path(local_id: int, file_id: str) -> Path | None:
    token = str(file_id or "").strip()
    if not token or not _ALLEGATI_FILE_ID_RE.match(token):
        return None
    if token == ALLEGATI_SYNC_META_FILENAME:
        return None
    folder = _attachment_dir_for_local(local_id, create=False)
    if not folder.exists():
        return None
    path = folder / token
    try:
        resolved_folder = folder.resolve()
        resolved_path = path.resolve()
    except OSError:
        return None
    if resolved_folder not in resolved_path.parents:
        return None
    return resolved_path


def _attachment_sync_meta_path(local_id: int) -> Path:
    folder = _attachment_dir_for_local(local_id, create=False)
    return folder / ALLEGATI_SYNC_META_FILENAME


def _default_attachment_sync_state() -> dict:
    return {
        "status": ALLEGATI_SYNC_PENDING,
        "retry_count": 0,
        "last_error": "",
        "queued_at": _utcnow_iso(),
        "last_attempt_at": None,
        "last_synced_at": None,
    }


def _normalize_attachment_sync_state(raw_state) -> dict:
    base = _default_attachment_sync_state()
    if isinstance(raw_state, dict):
        status = str(raw_state.get("status") or "").strip().lower()
        if status in {ALLEGATI_SYNC_PENDING, ALLEGATI_SYNC_SYNCED, ALLEGATI_SYNC_ERROR}:
            base["status"] = status
        try:
            retry = int(raw_state.get("retry_count") or 0)
        except Exception:
            retry = 0
        base["retry_count"] = max(0, retry)
        base["last_error"] = str(raw_state.get("last_error") or "").strip()[:500]
        queued = str(raw_state.get("queued_at") or "").strip()
        if queued:
            base["queued_at"] = queued
        attempted = str(raw_state.get("last_attempt_at") or "").strip()
        if attempted:
            base["last_attempt_at"] = attempted
        synced = str(raw_state.get("last_synced_at") or "").strip()
        if synced:
            base["last_synced_at"] = synced
    return base


def _load_attachment_sync_meta(local_id: int) -> dict:
    path = _attachment_sync_meta_path(local_id)
    if not path.exists():
        return {"files": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("[anomalie] impossibile leggere meta allegati local_id=%s", local_id)
        return {"files": {}}
    if not isinstance(payload, dict):
        return {"files": {}}
    files_raw = payload.get("files")
    if not isinstance(files_raw, dict):
        return {"files": {}}
    files_clean: dict[str, dict] = {}
    for file_id, state in files_raw.items():
        token = str(file_id or "").strip()
        if token == ALLEGATI_SYNC_META_FILENAME:
            continue
        if not token or not _ALLEGATI_FILE_ID_RE.match(token):
            continue
        files_clean[token] = _normalize_attachment_sync_state(state)
    return {"files": files_clean}


def _save_attachment_sync_meta(local_id: int, meta_payload: dict) -> None:
    folder = _attachment_dir_for_local(local_id, create=True)
    path = folder / ALLEGATI_SYNC_META_FILENAME
    files_raw = meta_payload.get("files") if isinstance(meta_payload, dict) else {}
    files_clean: dict[str, dict] = {}
    if isinstance(files_raw, dict):
        for file_id, state in files_raw.items():
            token = str(file_id or "").strip()
            if token == ALLEGATI_SYNC_META_FILENAME:
                continue
            if not token or not _ALLEGATI_FILE_ID_RE.match(token):
                continue
            files_clean[token] = _normalize_attachment_sync_state(state)
    payload = {"files": files_clean}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _mark_attachment_pending(local_id: int, file_ids: list[str]) -> None:
    tokens = []
    for file_id in file_ids:
        token = str(file_id or "").strip()
        if token and _ALLEGATI_FILE_ID_RE.match(token) and token != ALLEGATI_SYNC_META_FILENAME:
            tokens.append(token)
    if not tokens:
        return
    meta = _load_attachment_sync_meta(local_id)
    files_meta = meta.setdefault("files", {})
    now_iso = _utcnow_iso()
    for token in tokens:
        rec = _normalize_attachment_sync_state(files_meta.get(token))
        rec["status"] = ALLEGATI_SYNC_PENDING
        rec["retry_count"] = 0
        rec["last_error"] = ""
        rec["queued_at"] = now_iso
        rec["last_attempt_at"] = None
        rec["last_synced_at"] = None
        files_meta[token] = rec
    _save_attachment_sync_meta(local_id, meta)


def _remove_attachment_sync_meta_entry(local_id: int, file_id: str) -> None:
    token = str(file_id or "").strip()
    if not token or not _ALLEGATI_FILE_ID_RE.match(token):
        return
    meta = _load_attachment_sync_meta(local_id)
    files_meta = meta.get("files", {})
    if token in files_meta:
        files_meta.pop(token, None)
        if files_meta:
            _save_attachment_sync_meta(local_id, meta)
        else:
            meta_path = _attachment_sync_meta_path(local_id)
            try:
                if meta_path.exists():
                    meta_path.unlink()
            except OSError:
                pass


def _pending_attachment_local_ids(limit_rows: int = 100) -> list[int]:
    root = _anomalie_attachments_root()
    if not root.exists():
        return []
    out: list[int] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        if len(out) >= max(1, int(limit_rows)):
            break
        if not child.is_dir():
            continue
        if not child.name.isdigit():
            continue
        local_id = int(child.name)
        meta = _load_attachment_sync_meta(local_id)
        files_meta = meta.get("files", {})
        needs_sync = False
        if files_meta:
            for state in files_meta.values():
                rec = _normalize_attachment_sync_state(state)
                if rec["status"] == ALLEGATI_SYNC_SYNCED:
                    continue
                if rec["status"] == ALLEGATI_SYNC_ERROR and rec["retry_count"] >= ALLEGATI_SYNC_MAX_RETRY:
                    continue
                needs_sync = True
                break
        if not needs_sync:
            for path in child.iterdir():
                if not path.is_file():
                    continue
                if path.name == ALLEGATI_SYNC_META_FILENAME:
                    continue
                if not _ALLEGATI_FILE_ID_RE.match(path.name):
                    continue
                needs_sync = True
                break
        if needs_sync:
            out.append(local_id)
    return out


def _list_attachments_for_local(local_id: int) -> list[dict]:
    folder = _attachment_dir_for_local(local_id, create=False)
    if not folder.exists():
        return []
    meta = _load_attachment_sync_meta(local_id)
    files_meta = meta.setdefault("files", {})
    dirty_meta = False

    paths: list[Path] = []
    for path in folder.iterdir():
        if not path.is_file():
            continue
        file_id = path.name
        if file_id == ALLEGATI_SYNC_META_FILENAME:
            continue
        if not _ALLEGATI_FILE_ID_RE.match(file_id):
            continue
        paths.append(path)
    paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    existing_ids: set[str] = set()
    items: list[dict] = []
    for path in paths:
        file_id = path.name
        existing_ids.add(file_id)
        rec = _normalize_attachment_sync_state(files_meta.get(file_id))
        if file_id not in files_meta:
            files_meta[file_id] = rec
            dirty_meta = True
        stat = path.stat()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        items.append(
            {
                "file_id": file_id,
                "name": _attachment_display_name(file_id),
                "size": int(stat.st_size),
                "mime_type": mime,
                "is_image": _is_image_attachment(path.name, mime),
                "modified": mtime,
                "sync_status": rec.get("status") or ALLEGATI_SYNC_PENDING,
                "sync_retry_count": int(rec.get("retry_count") or 0),
                "sync_last_error": rec.get("last_error") or "",
                "sync_last_attempt_at": rec.get("last_attempt_at"),
                "sync_last_synced_at": rec.get("last_synced_at"),
            }
        )

    for file_id in list(files_meta.keys()):
        if file_id not in existing_ids:
            files_meta.pop(file_id, None)
            dirty_meta = True

    if dirty_meta:
        _save_attachment_sync_meta(local_id, meta)
    return items


def _anomalie_lists_path() -> Path:
    return _repo_root() / "config" / "anomalie_liste.json"


def _normalize_choice_list(values) -> list[str]:
    if isinstance(values, str):
        source = values.splitlines()
    elif isinstance(values, (list, tuple)):
        source = values
    else:
        source = []
    out: list[str] = []
    seen: set[str] = set()
    for raw in source:
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _default_anomalie_lists() -> dict[str, list[str]]:
    return {k: list(v) for k, v in ANOMALIE_LIST_DEFAULTS.items()}


def _load_anomalie_lists() -> dict[str, list[str]]:
    data = _default_anomalie_lists()
    path = _anomalie_lists_path()
    if not path.exists():
        return data
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("[anomalie] impossibile leggere file liste: %s", path)
        return data
    if not isinstance(payload, dict):
        return data
    for key in ANOMALIE_LIST_KEYS:
        if key in payload:
            values = _normalize_choice_list(payload.get(key))
            if values or key not in ANOMALIE_NON_EMPTY_DEFAULT_KEYS:
                data[key] = values
            else:
                data[key] = list(ANOMALIE_LIST_DEFAULTS[key])
    return data


def _save_anomalie_lists(lists_payload: dict[str, list[str]]) -> None:
    path = _anomalie_lists_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned: dict[str, list[str]] = {}
    for key in ANOMALIE_LIST_KEYS:
        cleaned[key] = _normalize_choice_list(lists_payload.get(key, []))
    path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")


def _graph_settings() -> dict[str, str]:
    cfg = _load_app_config()
    az = cfg["AZIENDA"] if cfg.has_section("AZIENDA") else {}

    def _env_or_cfg(*env_keys: str, option: str) -> str:
        for key in env_keys:
            value = (os.getenv(key) or "").strip()
            if value:
                return value
        if hasattr(az, "get"):
            return str(az.get(option, "") or "").strip()
        return ""

    return {
        "tenant_id": _env_or_cfg("GRAPH_TENANT_ID", "AZURE_TENANT_ID", option="tenant_id"),
        "client_id": _env_or_cfg("GRAPH_CLIENT_ID", "AZURE_CLIENT_ID", option="client_id"),
        "client_secret": _env_or_cfg("GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET", option="client_secret"),
        "site_id": _env_or_cfg("GRAPH_SITE_ID", option="site_id"),
        "list_id_anomalie_db": _env_or_cfg("GRAPH_LIST_ID_ANOMALIE_DB", option="list_id_anomalie_db"),
    }


def _graph_runtime_value(*env_keys: str, option: str) -> tuple[str, str]:
    cfg = _load_app_config()
    az = cfg["AZIENDA"] if cfg.has_section("AZIENDA") else {}
    for key in env_keys:
        value = (os.getenv(key) or "").strip()
        if value:
            return value, "env"
    if hasattr(az, "get"):
        return str(az.get(option, "") or "").strip(), "config.ini"
    return "", "config.ini"


def _graph_config_issue() -> str:
    labels = {
        "tenant_id": "tenant_id",
        "client_id": "client_id",
        "client_secret": "client_secret",
        "site_id": "site_id",
        "list_id_anomalie_db": "list_id_anomalie_db",
    }
    gs = _graph_settings()
    missing = [labels[key] for key in labels if is_placeholder_value(gs.get(key, ""))]
    if not missing:
        return ""
    return "Configurazione Graph anomalie incompleta: " + ", ".join(missing)


def _graph_configured() -> bool:
    return not _graph_config_issue()


def _sharepoint_admin_config() -> dict[str, object]:
    cfg = _load_app_config()
    az = cfg["AZIENDA"] if cfg.has_section("AZIENDA") else {}
    runtime_tenant_id, tenant_source = _graph_runtime_value(
        "GRAPH_TENANT_ID",
        "AZURE_TENANT_ID",
        option="tenant_id",
    )
    runtime_client_id, client_source = _graph_runtime_value(
        "GRAPH_CLIENT_ID",
        "AZURE_CLIENT_ID",
        option="client_id",
    )
    runtime_client_secret, secret_source = _graph_runtime_value(
        "GRAPH_CLIENT_SECRET",
        "AZURE_CLIENT_SECRET",
        option="client_secret",
    )
    runtime_site_id, site_source = _graph_runtime_value(
        "GRAPH_SITE_ID",
        option="site_id",
    )
    runtime_list_id, list_source = _graph_runtime_value(
        "GRAPH_LIST_ID_ANOMALIE_DB",
        option="list_id_anomalie_db",
    )
    runtime_values = [
        runtime_tenant_id,
        runtime_client_id,
        runtime_client_secret,
        runtime_site_id,
        runtime_list_id,
    ]
    return {
        "tenant_id": str(getattr(az, "get", lambda *_args, **_kwargs: "")("tenant_id", "") or "").strip(),
        "client_id": str(getattr(az, "get", lambda *_args, **_kwargs: "")("client_id", "") or "").strip(),
        "site_id": str(getattr(az, "get", lambda *_args, **_kwargs: "")("site_id", "") or "").strip(),
        "list_id_anomalie_db": str(getattr(az, "get", lambda *_args, **_kwargs: "")("list_id_anomalie_db", "") or "").strip(),
        "client_secret_configured": bool(
            str(getattr(az, "get", lambda *_args, **_kwargs: "")("client_secret", "") or "").strip()
        ),
        "runtime_ready": all(not is_placeholder_value(value) for value in runtime_values),
        "runtime_sources": {
            "tenant_id": tenant_source,
            "client_id": client_source,
            "client_secret": secret_source,
            "site_id": site_source,
            "list_id_anomalie_db": list_source,
        },
        "env_override_active": any(
            source == "env"
            for source in [tenant_source, client_source, secret_source, site_source, list_source]
        ),
        "sync_issue": _graph_config_issue(),
    }


def _graph_token() -> str:
    if not _graph_configured():
        raise RuntimeError(_graph_config_issue())
    gs = _graph_settings()
    return acquire_graph_token(gs["tenant_id"], gs["client_id"], gs["client_secret"])


def _graph_base_anomalie_url() -> str:
    if not _graph_configured():
        raise RuntimeError(_graph_config_issue())
    gs = _graph_settings()
    return f"https://graph.microsoft.com/v1.0/sites/{gs['site_id']}/lists/{gs['list_id_anomalie_db']}/items"


def _graph_healthcheck() -> tuple[bool, str]:
    issue = _graph_config_issue()
    if issue:
        return False, issue
    try:
        response = requests.get(
            f"{_graph_base_anomalie_url()}?expand=fields&$top=1",
            headers={"Authorization": f"Bearer {_graph_token()}", "Content-Type": "application/json"},
            timeout=20,
        )
        if response.status_code == 200:
            return True, "Connessione Graph anomalie OK."
        return False, f"Graph anomalie {response.status_code}: {response.text[:300]}"
    except Exception as exc:
        return False, f"Test Graph anomalie fallito: {exc}"


def _handle_sharepoint_config_request(request) -> tuple[bool, str]:
    tenant_id = str(request.POST.get("sharepoint_tenant_id") or "").strip()[:200]
    client_id = str(request.POST.get("sharepoint_client_id") or "").strip()[:200]
    site_id = str(request.POST.get("sharepoint_site_id") or "").strip()[:500]
    client_secret = str(request.POST.get("sharepoint_client_secret") or "").strip()
    list_id_anomalie_db = str(request.POST.get("sharepoint_list_id_anomalie_db") or "").strip()[:500]

    try:
        _set_ini_option_preserve("AZIENDA", "tenant_id", tenant_id)
        _set_ini_option_preserve("AZIENDA", "client_id", client_id)
        _set_ini_option_preserve("AZIENDA", "site_id", site_id)
        _set_ini_option_preserve("AZIENDA", "list_id_anomalie_db", list_id_anomalie_db)
        if client_secret:
            _set_ini_option_preserve("AZIENDA", "client_secret", client_secret)
        else:
            cfg = _load_app_config()
            if not cfg.has_option("AZIENDA", "client_secret"):
                _set_ini_option_preserve("AZIENDA", "client_secret", "")
    except Exception as exc:
        return False, f"Errore scrittura config.ini: {exc}"

    return True, "Configurazione SharePoint anomalie aggiornata."


def _sp_create_anomalia(fields_dict: dict) -> tuple[bool, dict | str]:
    token = _graph_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.post(_graph_base_anomalie_url(), headers=headers, json={"fields": fields_dict}, timeout=20)
    if r.status_code in (200, 201):
        return True, r.json()
    return False, r.text


def _sp_update_anomalia(item_id: str, fields_dict: dict) -> tuple[bool, dict | str]:
    token = _graph_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.patch(f"{_graph_base_anomalie_url()}/{item_id}/fields", headers=headers, json=fields_dict, timeout=20)
    if r.status_code in (200, 204):
        try:
            return True, r.json() if r.text else {}
        except Exception:
            return True, {}
    return False, r.text


def _sp_upload_anomalia_attachment(item_id: str, file_path: Path, display_name: str) -> tuple[bool, dict | str]:
    token = _graph_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
    }
    safe_name = quote(str(display_name or file_path.name), safe="")
    url = f"{_graph_base_anomalie_url()}/{item_id}/driveItem:/{safe_name}:/content"
    with file_path.open("rb") as fh:
        r = requests.put(url, headers=headers, data=fh, timeout=60)
    if r.status_code in (200, 201):
        try:
            return True, r.json() if r.text else {}
        except Exception:
            return True, {}
    return False, r.text


def _sharepoint_ids_by_local_ids(local_ids: list[int]) -> dict[int, str]:
    ids: list[int] = []
    for value in local_ids:
        try:
            local_id = int(value)
        except (TypeError, ValueError):
            continue
        if local_id > 0:
            ids.append(local_id)
    if not ids or not _has_table("anomalie"):
        return {}
    placeholders = ", ".join(["%s"] * len(ids))
    rows = _fetch_all_dict(
        f"SELECT id, sharepoint_item_id FROM anomalie WHERE id IN ({placeholders})",
        ids,
    )
    out: dict[int, str] = {}
    for row in rows:
        local_id = row.get("id")
        sp_id = str(row.get("sharepoint_item_id") or "").strip()
        if local_id is None or not sp_id:
            continue
        out[int(local_id)] = sp_id
    return out


def _sync_attachments_for_local(local_id: int, sharepoint_item_id: str) -> dict:
    result = {
        "synced": 0,
        "failed": 0,
        "skipped": 0,
        "maxed_out": 0,
        "pending": 0,
        "details": [],
    }
    if not sharepoint_item_id:
        return result

    folder = _attachment_dir_for_local(local_id, create=False)
    if not folder.exists():
        return result

    meta = _load_attachment_sync_meta(local_id)
    files_meta = meta.setdefault("files", {})
    dirty_meta = False

    file_paths: list[Path] = []
    for path in folder.iterdir():
        if not path.is_file():
            continue
        file_id = path.name
        if file_id == ALLEGATI_SYNC_META_FILENAME:
            continue
        if not _ALLEGATI_FILE_ID_RE.match(file_id):
            continue
        file_paths.append(path)
        if file_id not in files_meta:
            files_meta[file_id] = _default_attachment_sync_state()
            dirty_meta = True

    file_paths.sort(key=lambda p: p.stat().st_mtime)
    existing_ids = {p.name for p in file_paths}
    for stale_id in list(files_meta.keys()):
        if stale_id not in existing_ids:
            files_meta.pop(stale_id, None)
            dirty_meta = True

    queue: list[Path] = []
    for path in file_paths:
        rec = _normalize_attachment_sync_state(files_meta.get(path.name))
        files_meta[path.name] = rec
        if rec["status"] == ALLEGATI_SYNC_SYNCED:
            continue
        if rec["status"] == ALLEGATI_SYNC_ERROR and int(rec.get("retry_count") or 0) >= ALLEGATI_SYNC_MAX_RETRY:
            result["maxed_out"] += 1
            continue
        queue.append(path)

    for path in queue[:ALLEGATI_SYNC_MAX_PER_LOCAL]:
        file_id = path.name
        display_name = _attachment_display_name(file_id)
        now_iso = _utcnow_iso()
        rec = _normalize_attachment_sync_state(files_meta.get(file_id))
        rec["last_attempt_at"] = now_iso
        try:
            ok, payload = _sp_upload_anomalia_attachment(str(sharepoint_item_id), path, display_name)
            if not ok:
                raise RuntimeError(str(payload))
            rec["status"] = ALLEGATI_SYNC_SYNCED
            rec["last_error"] = ""
            rec["last_synced_at"] = now_iso
            result["synced"] += 1
            result["details"].append({"file_id": file_id, "action": "attachment_synced"})
        except Exception as exc:
            rec["retry_count"] = int(rec.get("retry_count") or 0) + 1
            rec["last_error"] = str(exc)[:500]
            rec["status"] = (
                ALLEGATI_SYNC_ERROR
                if int(rec["retry_count"]) >= ALLEGATI_SYNC_MAX_RETRY
                else ALLEGATI_SYNC_PENDING
            )
            result["failed"] += 1
            result["details"].append({"file_id": file_id, "action": "attachment_failed", "error": rec["last_error"]})
        files_meta[file_id] = rec
        dirty_meta = True

    for rec in files_meta.values():
        state = _normalize_attachment_sync_state(rec)
        if state["status"] == ALLEGATI_SYNC_SYNCED:
            continue
        if state["status"] == ALLEGATI_SYNC_ERROR and int(state.get("retry_count") or 0) >= ALLEGATI_SYNC_MAX_RETRY:
            continue
        result["pending"] += 1

    if dirty_meta:
        _save_attachment_sync_meta(local_id, meta)
    return result


def _serialize_anomalie_rows(rows: list[dict]) -> list[dict]:
    return [
        {
            "item_id": _display_item_id(r),
            "local_id": r.get("id"),
            "op_id": r.get("ex_op_nominativo") or "",
            "sn": r.get("seriale") or "",
            "desc": r.get("descrizione") or "",
            "note": r.get("note_capocommessa") or "",
            "pezzi_prec": bool(r.get("pezzo_recuperato")),
            "aprire_rdc": bool(r.get("aprire_rdc")),
            "numero_rdc": r.get("numero_rdc") or "",
            "segnalare": bool(r.get("segnalare_cliente")),
            "chiudere": bool(r.get("chiudere")),
            "avanzamento": r.get("avanzamento") or "Accetto lo stato",
            "modified": str(r.get("modified_datetime")) if r.get("modified_datetime") else None,
        }
        for r in rows
    ]


def _as_bool_int(value) -> int:
    return 1 if bool(value) else 0


def _safe_text(value, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    if max_len:
        return text[:max_len]
    return text


def _display_item_id(row: dict) -> str:
    sp = str(row.get("sharepoint_item_id") or "").strip()
    if sp:
        return sp
    local_id = row.get("id")
    return f"local:{int(local_id)}" if local_id is not None else ""


def _resolve_op_lookup_id(op_item_id, op_title) -> int | None:
    if op_item_id is not None and str(op_item_id).strip():
        try:
            return int(str(op_item_id).strip())
        except ValueError:
            pass
    if not _has_table("ordini_produzione"):
        return None
    op_title_clean = _safe_text(op_title, 100)
    if not op_title_clean:
        return None
    try:
        rows = _fetch_all_dict(
            """
            SELECT TOP 1 sharepoint_item_id
            FROM ordini_produzione
            WHERE title = %s
            ORDER BY id DESC
            """,
            [op_title_clean],
        )
        if not rows:
            return None
        sp_id = str(rows[0].get("sharepoint_item_id") or "").strip()
        return int(sp_id) if sp_id.isdigit() else None
    except Exception:
        return None


def _legacy_role_name(request) -> str:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    return str(getattr(legacy_user, "ruolo", "") or "").strip().lower()


def _normalize_identity_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _current_user_identity(request) -> dict[str, str]:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    display_name = (
        (legacy_user.nome if legacy_user else None)
        or request.user.get_full_name()
        or request.user.username
        or ""
    )
    email = (
        (legacy_user.email if legacy_user else None)
        or request.user.email
        or ""
    )
    return {
        "name": str(display_name or "").strip(),
        "name_norm": _normalize_identity_text(display_name),
        "email": str(email or "").strip(),
        "email_norm": _normalize_identity_text(email),
    }


def _current_user_name_norms(request) -> set[str]:
    """Ritorna i nomi normalizzati dell'utente corrente da tabelle utenti/anagrafica."""
    names: set[str] = set()
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)

    if legacy_user and legacy_user.nome:
        names.add(_normalize_identity_text(legacy_user.nome))

    if legacy_user:
        try:
            ana = AnagraficaDipendente.objects.filter(utente_id=legacy_user.id).first()
            if not ana and getattr(legacy_user, "email", None):
                ana = AnagraficaDipendente.objects.filter(email__iexact=str(legacy_user.email).strip()).first()
            if ana:
                if ana.nome:
                    names.add(_normalize_identity_text(ana.nome))
                full_name = f"{ana.cognome or ''} {ana.nome or ''}".strip()
                if full_name:
                    names.add(_normalize_identity_text(full_name))
        except Exception:
            # Fail-open solo sul fallback legacy_user.nome già presente in names.
            pass

    return {n for n in names if n}


def _split_people_tokens(raw_value: str) -> list[str]:
    text = str(raw_value or "").strip()
    if not text:
        return []
    parts = re.split(r"[,\n;|]+", text)
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        token = str(part or "").strip().strip("\"'[]()")
        if not token:
            continue
        key = _normalize_identity_text(token)
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def _can_view_anomalie_for_op(request, op_id: str) -> bool:
    # Accesso in sola lettura: qualsiasi utente autenticato può consultare.
    # I permessi di modifica restano vincolati a _can_edit_anomalie_for_op.
    return bool(getattr(request.user, "is_authenticated", False))


def _can_edit_anomalie_for_op(request, op_id: str) -> bool:
    if bool(getattr(request.user, "is_superuser", False)):
        return True
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if legacy_user and is_legacy_admin(legacy_user):
        return True

    config_lists = _load_anomalie_lists()
    edit_whitelist = config_lists.get("autorizzati_modifica", []) if isinstance(config_lists, dict) else []
    current_name_norms = _current_user_name_norms(request)
    identity = _current_user_identity(request)
    if not current_name_norms and identity["name_norm"]:
        current_name_norms = {identity["name_norm"]}
    whitelist_norms = {_normalize_identity_text(v) for v in edit_whitelist}
    if current_name_norms.intersection(whitelist_norms):
        return True

    op_title = _safe_text(op_id, 100)
    if not op_title or not _has_table("ordini_produzione"):
        return False

    try:
        rows = _fetch_all_dict(
            "SELECT TOP 1 capocomessa, incaricato FROM ordini_produzione WHERE title = %s",
            [op_title],
        )
    except Exception:
        return False
    if not rows:
        return False

    capocomessa_raw = str(rows[0].get("capocomessa") or "").strip()
    incaricato_raw = str(rows[0].get("incaricato") or "").strip()
    if not capocomessa_raw and not incaricato_raw:
        return False

    for raw_people in (capocomessa_raw, incaricato_raw):
        tokens = _split_people_tokens(raw_people)
        if not tokens:
            continue
        token_norms = {_normalize_identity_text(t) for t in tokens}
        if current_name_norms.intersection(token_norms):
            return True
    return False


def _can_sync_anomalie(request) -> bool:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not legacy_user:
        return False
    if is_legacy_admin(legacy_user):
        return True
    return _legacy_role_name(request) in {"gestore"}


def _can_manage_anomalie_config(request) -> bool:
    if bool(getattr(request.user, "is_superuser", False)):
        return True
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not legacy_user:
        return False
    return bool(is_legacy_admin(legacy_user))


def _sp_fields_from_anomalia_row(row: dict) -> dict:
    # Mappa DB locale -> nomi interni colonna SharePoint (coerente con mapping storico del progetto)
    fields = {}
    op_lookup_id = row.get("op_lookup_id")
    if op_lookup_id is not None:
        try:
            fields["OP_x002d_IDLookupId"] = int(op_lookup_id)
        except (TypeError, ValueError):
            pass
    if row.get("ex_op_nominativo"):
        fields["exOPNominativo"] = str(row.get("ex_op_nominativo"))
    if row.get("seriale") is not None:
        fields["field_4"] = str(row.get("seriale") or "")
    if row.get("descrizione") is not None:
        fields["field_1"] = str(row.get("descrizione") or "")
    if row.get("note_capocommessa") is not None:
        fields["Notecapocommessa"] = str(row.get("note_capocommessa") or "")
    if row.get("numero_rdc") is not None:
        fields["NumeroRDC"] = str(row.get("numero_rdc") or "")
    fields["Pezzorecuperatoallafase"] = bool(row.get("pezzo_recuperato"))
    fields["aprireRDC"] = bool(row.get("aprire_rdc"))
    fields["Dasegnalareacliente"] = bool(row.get("segnalare_cliente"))
    fields["Chiudere_x003f_"] = bool(row.get("chiudere"))
    fields["field_3"] = str(row.get("avanzamento") or "Accetto lo stato")
    return fields


def _notify_anomalia_event(request, event: str, local_id: int | None, op_id: str, sn: str) -> None:
    """Invia notifica in-app (fire-and-forget) per eventi anomalia.

    event="segnalare": notifica capocommessa OP
    event="chiudere":  notifica autore anomalia
    """
    try:
        if event == "segnalare":
            # Tenta di trovare la capocommessa per l'OP e notificarla
            if not op_id or not _has_table("ordini_produzione"):
                return
            op_rows = _fetch_all_dict(
                "SELECT TOP 1 capocomessa FROM ordini_produzione WHERE title = %s",
                [op_id],
            )
            if not op_rows:
                return
            capo_val = str(op_rows[0].get("capocomessa") or "").strip()
            if not capo_val:
                return
            # Lookup capocommessa in utenti: prima per alias (email LIKE 'alias@%'), poi per nome
            capo_user = None
            try:
                alias_part = capo_val.split("@")[0].strip() if "@" in capo_val else capo_val
                from core.legacy_models import UtenteLegacy
                capo_user = UtenteLegacy.objects.filter(email__istartswith=f"{alias_part}@").first()
                if not capo_user:
                    capo_user = UtenteLegacy.objects.filter(nome__icontains=capo_val).first()
            except Exception:
                pass
            if capo_user:
                Notifica.objects.create(
                    legacy_user_id=capo_user.id,
                    tipo="anomalia_segnalata",
                    messaggio=f"Anomalia S/N {sn or '—'} (OP {op_id}) segnalata al cliente.",
                    url_azione="/gestione-anomalie",
                )

        elif event == "chiudere":
            # Notifica l'autore dell'anomalia (se diverso dall'utente corrente)
            if local_id is None or not _has_table("anomalie"):
                return
            cols = legacy_table_columns("anomalie")
            if "created_by_user_id" not in cols:
                return
            rows = _fetch_all_dict(
                "SELECT TOP 1 created_by_user_id FROM anomalie WHERE id = %s",
                [local_id],
            )
            if not rows:
                return
            creator_id = rows[0].get("created_by_user_id")
            if not creator_id:
                return
            current_legacy = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
            current_id = current_legacy.id if current_legacy else None
            if creator_id == current_id:
                return
            Notifica.objects.create(
                legacy_user_id=int(creator_id),
                tipo="anomalia_chiusa",
                messaggio=f"Anomalia S/N {sn or '—'} (OP {op_id}) è stata chiusa.",
                url_azione="/gestione-anomalie",
            )
    except Exception:
        logger.exception("[anomalie] notifica fallita: event=%s local_id=%s", event, local_id)


@login_required
@ensure_csrf_cookie
def gestione_anomalie_page(request):
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = user_can_modulo_action(request, "anomalie", "admin_anomalie")
    identity = _current_user_identity(request)
    lists_cfg = _load_anomalie_lists()
    sync_config_issue = _graph_config_issue()
    context = {
        "page_title": "Gestione Anomalie",
        "legacy_user": legacy_user,
        "is_admin": is_admin,
        "db_has_ordini": _has_table("ordini_produzione"),
        "db_has_anomalie": _has_table("anomalie"),
        "config_lists_json": json.dumps(lists_cfg, ensure_ascii=False),
        "current_user_name": identity["name"],
        "current_user_email": identity["email"],
        "sharepoint_sync_available": not sync_config_issue,
        "sharepoint_sync_error": sync_config_issue,
    }
    return render(request, "anomalie/pages/gestione_anomalie_react.html", context)


@login_required
def legacy_apertura_redirect(request):
    # Compat route legacy: /gestione-anomalie/apertura
    return redirect(f"{reverse('gestione_anomalie_page')}?view=apertura")


@login_required
def legacy_apertura_anomalie_redirect(request):
    # Compat route legacy: /gestione-anomalie/apertura/anomalie
    return redirect(f"{reverse('gestione_anomalie_page')}?view=apertura_anomalie")


@login_required
def api_db_ordini(request):
    if not _has_table("ordini_produzione"):
        return JsonResponse([])
    try:
        sql = """
            SELECT
                op.sharepoint_item_id AS item_id,
                op.title AS op_title,
                op.part_number,
                op.incaricato,
                op.capocomessa,
                op.stato,
                COUNT(a.id) AS anomalie_count,
                SUM(CASE WHEN COALESCE(a.chiudere, 0) = 0 THEN 1 ELSE 0 END) AS anomalie_aperte_count
            FROM ordini_produzione op
            LEFT JOIN anomalie a
                ON a.op_lookup_id = TRY_CAST(op.sharepoint_item_id AS INT)
            GROUP BY
                op.sharepoint_item_id, op.title, op.part_number,
                op.incaricato, op.capocomessa, op.stato
            ORDER BY op.title
        """
        rows = _fetch_all_dict(sql)
        result = [
            {
                "item_id": r.get("item_id"),
                "id": r.get("op_title") or "—",
                "pn": r.get("part_number") or "—",
                "capo": r.get("capocomessa") or "—",
                "car": r.get("incaricato") or "—",
                "stato": r.get("stato"),
                "anomalie_count": int(r.get("anomalie_count") or 0),
                "anomalie_aperte_count": int(r.get("anomalie_aperte_count") or 0),
            }
            for r in rows
        ]
        return JsonResponse(result, safe=False)
    except DatabaseError as exc:
        return _json_error(str(exc), status=500)


@login_required
def api_db_ordini_crea(request):
    if request.method != "POST":
        return _json_error("Metodo non consentito", status=405)
    if not _has_table("ordini_produzione"):
        return _json_error("Tabella ordini_produzione non disponibile", status=500)

    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return _json_error("Body JSON non valido", status=400)
    if not isinstance(data, dict):
        return _json_error("Body JSON non valido", status=400)

    causale_doc = (_safe_text(data.get("causale_doc"), 20) or "OP").upper()
    anno = _safe_text(data.get("anno"), 10)
    numero = _safe_text(data.get("numero"), 30)
    fase = _safe_text(data.get("fase"), 30)
    pn = _safe_text(data.get("pn"), 200)
    capocommessa = _safe_text(data.get("capocommessa"), 255)
    car = _safe_text(data.get("car"), 255)
    note = _safe_text(data.get("note"), 180)
    collaudo_benestare = bool(data.get("collaudo_benestare"))

    if not anno:
        return _json_error("anno obbligatorio", status=400)
    if not numero:
        return _json_error("numero obbligatorio", status=400)
    if not pn:
        return _json_error("P/N obbligatorio", status=400)
    if not capocommessa:
        return _json_error("Capocommessa obbligatorio", status=400)
    if not car:
        return _json_error("CAR obbligatorio", status=400)

    cols = legacy_table_columns("ordini_produzione")
    if "sharepoint_item_id" not in cols:
        return _json_error("Schema ordini_produzione non compatibile", status=500)

    op_title = _safe_text(f"{causale_doc}/{anno}/{numero}", 100)
    stato_val = "Benestare" if collaudo_benestare else "Aperto"

    info_chunks: list[str] = []
    if fase:
        info_chunks.append(f"Fase {fase}")
    if collaudo_benestare:
        info_chunks.append("Collaudo benestare: SI")
    if note:
        info_chunks.append(note)
    in1text_val = _safe_text(" | ".join(info_chunks), 255)

    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    display_name = _safe_text(
        (legacy_user.nome if legacy_user else None) or request.user.get_full_name() or request.user.username,
        255,
    )

    payload_map = {
        "title": op_title,
        "part_number": pn,
        "in1text": in1text_val,
        "capocomessa": capocommessa,
        "incaricato": car,
        "stato": _safe_text(stato_val, 50),
        "created_by": display_name,
        "modified_by": display_name,
    }
    insert_writable = {k: v for k, v in payload_map.items() if k in cols}
    if "created_datetime" in cols:
        insert_writable["created_datetime"] = ("__sql__", "SYSUTCDATETIME()")
    if "modified_datetime" in cols:
        insert_writable["modified_datetime"] = ("__sql__", "SYSUTCDATETIME()")

    try:
        with transaction.atomic(using="default"):
            with connections["default"].cursor() as cursor:
                # Gli OP locali usano item_id negativi per evitare collisioni future con SharePoint.
                cursor.execute(
                    """
                    SELECT COALESCE(MIN(TRY_CAST(sharepoint_item_id AS INT)), 0)
                    FROM ordini_produzione WITH (UPDLOCK, HOLDLOCK)
                    """
                )
                row_min = cursor.fetchone()
                min_numeric = int(row_min[0] or 0) if row_min else 0
                next_local_item_id = -1 if min_numeric >= 0 else (min_numeric - 1)
                insert_writable["sharepoint_item_id"] = str(next_local_item_id)

                insert_cols: list[str] = []
                insert_placeholders: list[str] = []
                insert_params: list = []
                for col, val in insert_writable.items():
                    insert_cols.append(col)
                    if isinstance(val, tuple) and val[0] == "__sql__":
                        insert_placeholders.append(val[1])
                    else:
                        insert_placeholders.append("%s")
                        insert_params.append(val)

                cursor.execute(
                    f"""
                    INSERT INTO ordini_produzione ({', '.join(insert_cols)})
                    OUTPUT
                        INSERTED.id,
                        INSERTED.sharepoint_item_id,
                        INSERTED.title,
                        INSERTED.part_number,
                        INSERTED.capocomessa,
                        INSERTED.incaricato,
                        INSERTED.stato
                    VALUES ({', '.join(insert_placeholders)})
                    """,
                    insert_params,
                )
                row = cursor.fetchone()

        if not row:
            return JsonResponse({"success": False, "error": "Inserimento OP non riuscito"}, status=500)

        local_id = int(row[0]) if row[0] is not None else None
        sp_item_id = str(row[1] or "").strip()
        op_row = {
            "item_id": sp_item_id,
            "id": row[2] or "—",
            "pn": row[3] or "—",
            "capo": row[4] or "—",
            "car": row[5] or "—",
            "stato": row[6] or "Aperto",
            "anomalie_count": 0,
        }

        try:
            log_action(
                request,
                "op_creato",
                "ordini_produzione",
                {"local_id": local_id, "item_id": sp_item_id, "title": op_row["id"]},
            )
        except Exception:
            pass

        return JsonResponse(
            {
                "success": True,
                "item_id": sp_item_id or (f"local:{local_id}" if local_id is not None else None),
                "local_id": local_id,
                "op": op_row,
            }
        )
    except DatabaseError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=500)


@login_required
def api_db_anomalie(request):
    sp_item_id = request.GET.get("sp_item_id")
    if not sp_item_id:
        return JsonResponse([], safe=False)
    try:
        sp_item_id_int = int(sp_item_id)
    except (TypeError, ValueError):
        return _json_error("sp_item_id non valido", status=400)

    if not _has_table("anomalie"):
        return JsonResponse([], safe=False)

    cols = legacy_table_columns("anomalie")
    rdc_col = ", numero_rdc" if "numero_rdc" in cols else ""

    try:
        sql = f"""
            SELECT
                id,
                sharepoint_item_id,
                ex_op_nominativo,
                seriale,
                descrizione,
                note_capocommessa,
                pezzo_recuperato,
                aprire_rdc{rdc_col},
                segnalare_cliente,
                chiudere,
                avanzamento,
                modified_datetime
            FROM anomalie
            WHERE op_lookup_id = %s
            ORDER BY seriale
        """
        rows = _fetch_all_dict(sql, [sp_item_id_int])
        result = _serialize_anomalie_rows(rows)
        return JsonResponse(result, safe=False)
    except DatabaseError as exc:
        return _json_error(str(exc), status=500)


@login_required
def api_ordini(request):
    # Compatibilita frontend legacy: per ora serviamo i dati dal DB locale.
    return api_db_ordini(request)


@login_required
def api_anomalie(request):
    # Compatibilita frontend legacy: accetta op_item_id o sp_item_id e usa il DB locale.
    sp_item_id = request.GET.get("sp_item_id") or request.GET.get("op_item_id")
    if not sp_item_id:
        op_title = request.GET.get("op_id")
        resolved = _resolve_op_lookup_id(None, op_title)
        if resolved is not None:
            sp_item_id = str(resolved)
    if not sp_item_id:
        return JsonResponse([], safe=False)
    try:
        sp_item_id_int = int(sp_item_id)
    except (TypeError, ValueError):
        return _json_error("sp_item_id non valido", status=400)
    if not _has_table("anomalie"):
        return JsonResponse([], safe=False)

    cols = legacy_table_columns("anomalie")
    rdc_col = ", numero_rdc" if "numero_rdc" in cols else ""

    try:
        rows = _fetch_all_dict(
            f"""
            SELECT
                id,
                sharepoint_item_id,
                ex_op_nominativo,
                seriale,
                descrizione,
                note_capocommessa,
                pezzo_recuperato,
                aprire_rdc{rdc_col},
                segnalare_cliente,
                chiudere,
                avanzamento,
                modified_datetime
            FROM anomalie
            WHERE op_lookup_id = %s
            ORDER BY seriale
            """,
            [sp_item_id_int],
        )
        return JsonResponse(_serialize_anomalie_rows(rows), safe=False)
    except DatabaseError as exc:
        return _json_error(str(exc), status=500)


@login_required
def api_anomalie_allegati(request):
    try:
        if request.method != "GET":
            return _json_error("Metodo non consentito", status=405)
        local_id_raw = str(request.GET.get("local_id") or "").strip()
        if not local_id_raw.isdigit():
            return _json_error("local_id non valido", status=400)
        local_id = int(local_id_raw)
        row = _anomaly_local_row(local_id)
        if not row:
            return _json_error("Anomalia non trovata", status=404)
        op_id = str(row.get("ex_op_nominativo") or "").strip()
        if not _can_view_anomalie_for_op(request, op_id):
            return _json_error("Permesso negato", status=403)
        can_edit = _can_edit_anomalie_for_op(request, op_id)
        return JsonResponse(
            {
                "success": True,
                "attachments": _list_attachments_for_local(local_id),
                "local_id": local_id,
                "can_edit": bool(can_edit),
            }
        )
    except Exception as exc:
        logger.exception("[anomalie] errore api_anomalie_allegati")
        return _json_error(f"Errore allegati: {exc}", status=500)


@login_required
def api_anomalie_allegati_upload(request):
    try:
        if request.method != "POST":
            return _json_error("Metodo non consentito", status=405)
        local_id_raw = str(request.POST.get("local_id") or "").strip()
        if not local_id_raw.isdigit():
            return _json_error("local_id non valido", status=400)
        local_id = int(local_id_raw)
        row = _anomaly_local_row(local_id)
        if not row:
            return _json_error("Anomalia non trovata", status=404)
        op_id = str(row.get("ex_op_nominativo") or "").strip()
        if not _can_edit_anomalie_for_op(request, op_id):
            return _json_error("Permesso negato", status=403)

        files = request.FILES.getlist("files")
        if not files:
            return _json_error("Nessun file caricato", status=400)

        folder = _attachment_dir_for_local(local_id, create=True)
        saved = 0
        saved_file_ids: list[str] = []
        saved_names: list[str] = []
        errors: list[str] = []
        for f in files:
            original = str(getattr(f, "name", "") or "").strip()
            safe_name = _safe_attachment_filename(original)
            if not safe_name:
                errors.append(f"{original or 'file'}: nome non valido")
                continue
            if not _is_allowed_attachment(safe_name):
                errors.append(f"{original}: formato non supportato")
                continue
            file_size = int(getattr(f, "size", 0) or 0)
            if file_size <= 0:
                errors.append(f"{original}: file vuoto")
                continue
            if file_size > ALLEGATI_MAX_FILE_SIZE:
                errors.append(f"{original}: supera 20 MB")
                continue
            file_id = f"{uuid4().hex}__{safe_name}"
            target = folder / file_id
            with target.open("wb") as dest:
                for chunk in f.chunks():
                    dest.write(chunk)
            saved += 1
            saved_file_ids.append(file_id)
            saved_names.append(safe_name)

        if saved_file_ids:
            _mark_attachment_pending(local_id, saved_file_ids)
            try:
                log_action(
                    request,
                    "anomalia_allegato_upload",
                    "anomalie",
                    {
                        "local_id": local_id,
                        "op_id": op_id,
                        "file_count": len(saved_file_ids),
                        "files": saved_names,
                    },
                )
            except Exception:
                pass

        return JsonResponse(
            {
                "success": saved > 0 and not errors,
                "saved": saved,
                "errors": errors,
                "attachments": _list_attachments_for_local(local_id),
                "local_id": local_id,
            },
            status=200 if saved > 0 else 400,
        )
    except Exception as exc:
        logger.exception("[anomalie] errore api_anomalie_allegati_upload")
        return _json_error(f"Errore upload allegati: {exc}", status=500)


@login_required
def api_anomalie_allegati_delete(request):
    try:
        if request.method != "POST":
            return _json_error("Metodo non consentito", status=405)
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except Exception:
            payload = {}
        local_id_raw = str(payload.get("local_id") or "").strip()
        file_id = str(payload.get("file_id") or "").strip()
        if not local_id_raw.isdigit():
            return _json_error("local_id non valido", status=400)
        local_id = int(local_id_raw)
        row = _anomaly_local_row(local_id)
        if not row:
            return _json_error("Anomalia non trovata", status=404)
        op_id = str(row.get("ex_op_nominativo") or "").strip()
        if not _can_edit_anomalie_for_op(request, op_id):
            return _json_error("Permesso negato", status=403)
        path = _attachment_file_path(local_id, file_id)
        if not path or not path.exists() or not path.is_file():
            return _json_error("Allegato non trovato", status=404)
        deleted_name = _attachment_display_name(path.name)
        try:
            path.unlink()
        except OSError as exc:
            return _json_error(str(exc), status=500)
        _remove_attachment_sync_meta_entry(local_id, file_id)
        try:
            log_action(
                request,
                "anomalia_allegato_delete",
                "anomalie",
                {"local_id": local_id, "op_id": op_id, "file_id": file_id, "file_name": deleted_name},
            )
        except Exception:
            pass
        return JsonResponse({"success": True, "attachments": _list_attachments_for_local(local_id), "local_id": local_id})
    except Exception as exc:
        logger.exception("[anomalie] errore api_anomalie_allegati_delete")
        return _json_error(f"Errore eliminazione allegato: {exc}", status=500)


@login_required
def api_anomalie_allegati_file(request):
    try:
        if request.method != "GET":
            return _json_error("Metodo non consentito", status=405)
        local_id_raw = str(request.GET.get("local_id") or "").strip()
        file_id = str(request.GET.get("file_id") or "").strip()
        if not local_id_raw.isdigit():
            return _json_error("local_id non valido", status=400)
        local_id = int(local_id_raw)
        row = _anomaly_local_row(local_id)
        if not row:
            return _json_error("Anomalia non trovata", status=404)
        op_id = str(row.get("ex_op_nominativo") or "").strip()
        if not _can_view_anomalie_for_op(request, op_id):
            return _json_error("Permesso negato", status=403)
        path = _attachment_file_path(local_id, file_id)
        if not path or not path.exists() or not path.is_file():
            return _json_error("Allegato non trovato", status=404)

        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        display_name = _attachment_display_name(path.name)
        force_download = str(request.GET.get("download") or "").strip() in {"1", "true", "yes", "on"}
        try:
            log_action(
                request,
                "anomalia_allegato_download" if force_download else "anomalia_allegato_open",
                "anomalie",
                {"local_id": local_id, "op_id": op_id, "file_id": file_id, "file_name": display_name},
            )
        except Exception:
            pass
        response = FileResponse(path.open("rb"), as_attachment=force_download, filename=display_name, content_type=mime)
        return response
    except Exception as exc:
        logger.exception("[anomalie] errore api_anomalie_allegati_file")
        return _json_error(f"Errore apertura allegato: {exc}", status=500)


@login_required
def api_campi(request):
    return JsonResponse(
        {
            "db_tables": {
                "ordini_produzione": sorted(list(legacy_table_columns("ordini_produzione"))),
                "anomalie": sorted(list(legacy_table_columns("anomalie"))),
            },
        }
    )


@login_required
def api_salva(request):
    if request.method != "POST":
        return _json_error("Metodo non consentito", status=405)
    if not _has_table("anomalie"):
        return _json_error("Tabella anomalie non disponibile", status=500)

    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return _json_error("Body JSON non valido", status=400)

    if not isinstance(data, dict):
        return _json_error("Body JSON non valido", status=400)

    item_id = _safe_text(data.get("item_id"), 100)
    op_id = _safe_text(data.get("op_id"), 100)
    if not op_id:
        return _json_error("op_id obbligatorio", status=400)
    if not _can_edit_anomalie_for_op(request, op_id):
        return _json_error("Permesso negato: non autorizzato a modificare questo OP", status=403)

    cols = legacy_table_columns("anomalie")
    if not cols:
        return _json_error("Schema tabella anomalie non rilevato", status=500)

    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)

    segnalare_val = _as_bool_int(data.get("segnalare"))
    chiudere_val = _as_bool_int(data.get("chiudere"))

    payload_map = {
        "ex_op_nominativo": op_id,
        "op_lookup_id": _resolve_op_lookup_id(data.get("op_item_id"), op_id),
        "seriale": _safe_text(data.get("sn"), 200),
        "descrizione": _safe_text(data.get("desc")),
        "note_capocommessa": _safe_text(data.get("note")),
        "pezzo_recuperato": _as_bool_int(data.get("pezzi_prec")),
        "aprire_rdc": _as_bool_int(data.get("aprire_rdc")),
        "numero_rdc": _safe_text(data.get("numero_rdc"), 100),
        "segnalare_cliente": segnalare_val,
        "chiudere": chiudere_val,
        "avanzamento": _safe_text(data.get("avanzamento"), 100) or "Accetto lo stato",
    }

    writable = {k: v for k, v in payload_map.items() if k in cols}
    insert_writable = dict(writable)
    update_writable = dict(writable)
    if "modified_datetime" in cols:
        insert_writable["modified_datetime"] = ("__sql__", "SYSUTCDATETIME()")
        update_writable["modified_datetime"] = ("__sql__", "SYSUTCDATETIME()")
    if "created_datetime" in cols:
        insert_writable.setdefault("created_datetime", ("__sql__", "SYSUTCDATETIME()"))
    if "created_by_user_id" in cols and legacy_user:
        insert_writable.setdefault("created_by_user_id", legacy_user.id)

    where_clause = None
    where_params: list = []
    use_sharepoint_key = False
    local_pk_id = None

    if item_id:
        if item_id.lower().startswith("local:"):
            try:
                local_pk_id = int(item_id.split(":", 1)[1])
                if "id" in cols:
                    where_clause = "id = %s"
                    where_params = [local_pk_id]
            except ValueError:
                pass
        else:
            use_sharepoint_key = "sharepoint_item_id" in cols
            if use_sharepoint_key:
                where_clause = "sharepoint_item_id = %s"
                where_params = [item_id]

    try:
        with connections["default"].cursor() as cursor:
            updated = 0
            if where_clause:
                set_sql_parts = []
                set_params: list = []
                for col, val in update_writable.items():
                    if isinstance(val, tuple) and val[0] == "__sql__":
                        set_sql_parts.append(f"{col} = {val[1]}")
                    else:
                        set_sql_parts.append(f"{col} = %s")
                        set_params.append(val)
                if set_sql_parts:
                    cursor.execute(
                        f"UPDATE anomalie SET {', '.join(set_sql_parts)} WHERE {where_clause}",
                        set_params + where_params,
                    )
                    updated = int(cursor.rowcount or 0)

            if updated <= 0:
                insert_cols = []
                insert_placeholders = []
                insert_params: list = []
                for col, val in insert_writable.items():
                    insert_cols.append(col)
                    if isinstance(val, tuple) and val[0] == "__sql__":
                        insert_placeholders.append(val[1])
                    else:
                        insert_placeholders.append("%s")
                        insert_params.append(val)
                # sharepoint_item_id rimane NULL per record locali non ancora sincronizzati
                cursor.execute(
                    f"""
                    INSERT INTO anomalie ({', '.join(insert_cols)})
                    OUTPUT INSERTED.id, INSERTED.sharepoint_item_id
                    VALUES ({', '.join(insert_placeholders)})
                    """,
                    insert_params,
                )
                row = cursor.fetchone()
                local_id = int(row[0]) if row and row[0] is not None else None
                sp_id = str(row[1] or "").strip() if row else ""
            else:
                if where_clause == "id = %s":
                    cursor.execute("SELECT id, sharepoint_item_id FROM anomalie WHERE id = %s", [where_params[0]])
                elif use_sharepoint_key:
                    cursor.execute("SELECT id, sharepoint_item_id FROM anomalie WHERE sharepoint_item_id = %s", [where_params[0]])
                else:
                    cursor.execute("SELECT TOP 1 id, sharepoint_item_id FROM anomalie ORDER BY id DESC")
                row = cursor.fetchone()
                local_id = int(row[0]) if row and row[0] is not None else None
                sp_id = str(row[1] or "").strip() if row else ""

        returned_item_id = sp_id or (f"local:{local_id}" if local_id is not None else None)

        # Audit log (fire-and-forget)
        try:
            log_action(request, "anomalia_creata" if updated <= 0 else "anomalia_modificata", "anomalie", {
                "local_id": local_id,
                "item_id": returned_item_id,
                "op_id": op_id,
                "sn": payload_map.get("seriale"),
            })
        except Exception:
            pass

        # Notifiche in-app (fire-and-forget)
        sn_val = _safe_text(data.get("sn")) or ""
        if segnalare_val:
            _notify_anomalia_event(request, "segnalare", local_id, op_id, sn_val)
        if chiudere_val:
            _notify_anomalia_event(request, "chiudere", local_id, op_id, sn_val)

        return JsonResponse(
            {
                "success": True,
                "item_id": returned_item_id,
                "local_id": local_id,
                "sync_status": "pending_local",
            }
        )
    except DatabaseError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=500)


@login_required
def api_sync(request):
    if request.method != "POST":
        return _json_error("Metodo non consentito", status=405)
    if not _can_sync_anomalie(request):
        return _json_error("Permesso negato", status=403)
    if not _graph_configured():
        return _json_error(_graph_config_issue(), status=503)
    if not _has_table("anomalie"):
        return _json_error("Tabella anomalie non disponibile", status=500)

    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}
    include_updates = bool(body.get("include_updates"))
    limit_rows = max(1, min(int(body.get("limit_rows", 20) or 20), 200))

    cols = legacy_table_columns("anomalie")
    rdc_col = ", numero_rdc" if "numero_rdc" in cols else ""

    try:
        where_sql = "NULLIF(LTRIM(RTRIM(COALESCE(sharepoint_item_id,''))), '') IS NULL"
        if include_updates:
            where_sql = "1=1"
        rows = _fetch_all_dict(
            f"""
            SELECT TOP {limit_rows}
                id,
                sharepoint_item_id,
                ex_op_nominativo,
                op_lookup_id,
                seriale,
                descrizione,
                note_capocommessa,
                pezzo_recuperato,
                aprire_rdc{rdc_col},
                segnalare_cliente,
                chiudere,
                avanzamento,
                created_datetime,
                modified_datetime
            FROM anomalie
            WHERE {where_sql}
            ORDER BY COALESCE(modified_datetime, created_datetime) ASC, id ASC
            """
        )
    except DatabaseError as exc:
        return _json_error(str(exc), status=500)

    inseriti = aggiornati = failed = 0
    att_synced = att_failed = att_skipped = att_maxed_out = att_pending = 0
    details: list[dict] = []
    processed_attachment_local_ids: set[int] = set()

    def _collect_attachment_result(local_id_val: int, sync_res: dict) -> None:
        nonlocal att_synced, att_failed, att_skipped, att_maxed_out, att_pending
        att_synced += int(sync_res.get("synced") or 0)
        att_failed += int(sync_res.get("failed") or 0)
        att_skipped += int(sync_res.get("skipped") or 0)
        att_maxed_out += int(sync_res.get("maxed_out") or 0)
        att_pending += int(sync_res.get("pending") or 0)
        for det in list(sync_res.get("details") or [])[:10]:
            row_det = {"local_id": local_id_val}
            row_det.update(det if isinstance(det, dict) else {"info": str(det)})
            details.append(row_det)

    for row in rows:
        local_id = int(row["id"])
        sp_id = str(row.get("sharepoint_item_id") or "").strip()
        try:
            fields = _sp_fields_from_anomalia_row(row)
            if not fields.get("OP_x002d_IDLookupId") and row.get("ex_op_nominativo"):
                raise RuntimeError("op_lookup_id mancante: impossibile creare lookup SharePoint")
            if sp_id:
                ok, payload = _sp_update_anomalia(sp_id, fields)
                if not ok:
                    raise RuntimeError(str(payload))
                aggiornati += 1
                details.append({"local_id": local_id, "sharepoint_item_id": sp_id, "action": "update"})
                target_sp_id = sp_id
            else:
                ok, payload = _sp_create_anomalia(fields)
                if not ok:
                    raise RuntimeError(str(payload))
                new_sp_id = str((payload or {}).get("id") or "").strip()
                if not new_sp_id:
                    raise RuntimeError("Risposta SharePoint senza item_id")
                with connections["default"].cursor() as cursor:
                    if "modified_datetime" in cols:
                        cursor.execute(
                            "UPDATE anomalie SET sharepoint_item_id = %s, modified_datetime = SYSUTCDATETIME() WHERE id = %s",
                            [new_sp_id, local_id],
                        )
                    else:
                        cursor.execute(
                            "UPDATE anomalie SET sharepoint_item_id = %s WHERE id = %s",
                            [new_sp_id, local_id],
                        )
                inseriti += 1
                details.append({"local_id": local_id, "sharepoint_item_id": new_sp_id, "action": "create"})
                target_sp_id = new_sp_id

            att_res = _sync_attachments_for_local(local_id, target_sp_id)
            processed_attachment_local_ids.add(local_id)
            _collect_attachment_result(local_id, att_res)
        except Exception as exc:
            failed += 1
            err_txt = str(exc)
            logger.exception("[anomalie:sync] errore sync local_id=%s", local_id)
            details.append({"local_id": local_id, "error": err_txt})

    extra_local_ids = [
        local_id
        for local_id in _pending_attachment_local_ids(limit_rows=max(20, limit_rows * 3))
        if local_id not in processed_attachment_local_ids
    ]
    if extra_local_ids:
        sp_map = _sharepoint_ids_by_local_ids(extra_local_ids)
        for local_id in extra_local_ids:
            sp_item_id = str(sp_map.get(local_id) or "").strip()
            if not sp_item_id:
                continue
            try:
                att_res = _sync_attachments_for_local(local_id, sp_item_id)
                _collect_attachment_result(local_id, att_res)
            except Exception as exc:
                att_failed += 1
                details.append(
                    {"local_id": local_id, "action": "attachment_failed", "error": str(exc)[:500]}
                )
                logger.exception("[anomalie:sync] errore sync allegati local_id=%s", local_id)

    try:
        log_action(request, "anomalie_sync", "anomalie", {
            "inseriti": inseriti,
            "aggiornati": aggiornati,
            "failed_anomalie": failed,
            "allegati_synced": att_synced,
            "allegati_failed": att_failed,
            "allegati_pending": att_pending,
        })
    except Exception:
        pass

    total_failed = failed + att_failed

    return JsonResponse(
        {
            "success": total_failed == 0,
            "ordini": {"inseriti": 0, "aggiornati": 0},
            "anomalie": {"inseriti": inseriti, "aggiornati": aggiornati},
            "attachments": {
                "synced": att_synced,
                "failed": att_failed,
                "pending": att_pending,
                "skipped": att_skipped,
                "maxed_out": att_maxed_out,
            },
            "failed": total_failed,
            "failed_anomalie": failed,
            "failed_allegati": att_failed,
            "details": details[:40],
            "mode": "db_to_sharepoint_push",
        }
    )


@login_required
@ensure_csrf_cookie
def anomalie_configurazione_page(request):
    if not _can_manage_anomalie_config(request):
        return _json_error("Permesso negato", status=403)
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    display_name = (
        (legacy_user.nome if legacy_user else None)
        or request.user.get_full_name()
        or request.user.username
    )

    if request.method == "POST":
        action = str(request.POST.get("action") or "").strip()
        config_redirect = redirect(f"{reverse('anomalie_configurazione_page')}?tab=config")
        if action == "save_sharepoint_config":
            ok, text = _handle_sharepoint_config_request(request)
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return config_redirect
        if action == "test_sharepoint_config":
            ok, text = _graph_healthcheck()
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return config_redirect

    tab = request.GET.get("tab", "config")

    # --- Statistiche ---
    stats = {"total": 0, "chiuse": 0, "aperte": 0}
    by_avanzamento = []
    anomalie_record = []
    tabella_ok = _has_table("anomalie")
    if tabella_ok:
        def _count(where=""):
            sql = "SELECT COUNT(*) FROM anomalie" + (f" WHERE {where}" if where else "")
            with connections["default"].cursor() as cur:
                cur.execute(sql)
                return cur.fetchone()[0]
        stats["total"] = _count()
        stats["chiuse"] = _count("chiudere = 1")
        stats["aperte"] = _count("COALESCE(chiudere, 0) = 0")
        try:
            by_avanzamento = _fetch_all_dict(
                "SELECT TOP 20 avanzamento, COUNT(*) AS n FROM anomalie GROUP BY avanzamento ORDER BY n DESC"
            )
        except Exception:
            by_avanzamento = []
        if tab == "record":
            q_anomalie = request.GET.get("q_anomalie", "").strip()
            where_q = ""
            params_q = []
            if q_anomalie:
                where_q = "WHERE (UPPER(COALESCE(ex_op_nominativo,'')) LIKE UPPER(%s) OR UPPER(COALESCE(seriale,'')) LIKE UPPER(%s))"
                params_q = [f"%{q_anomalie}%", f"%{q_anomalie}%"]
            sql_rec = f"SELECT TOP 100 id, ex_op_nominativo, seriale, avanzamento, chiudere, modified_datetime FROM anomalie {where_q} ORDER BY id DESC"
            try:
                anomalie_record = _fetch_all_dict(sql_rec, params_q)
            except Exception:
                anomalie_record = []
        else:
            q_anomalie = ""
    else:
        q_anomalie = ""

    # --- Log audit ---
    from core.models import AuditLog
    audit_entries = AuditLog.objects.filter(modulo="anomalie").order_by("-created_at")[:100]

    context = {
        "page_title": "Gestione Anomalie",
        "username": display_name,
        "config_lists_json": json.dumps(_load_anomalie_lists(), ensure_ascii=False),
        "attachments_dir": _anomalie_attachments_dir_value(),
        "tab": tab,
        "tabella_ok": tabella_ok,
        "stats": stats,
        "by_avanzamento": by_avanzamento,
        "anomalie_record": anomalie_record,
        "q_anomalie": q_anomalie,
        "audit_entries": audit_entries,
        "sharepoint_admin_config": _sharepoint_admin_config(),
    }
    return render(request, "anomalie/pages/anomalie_configurazione.html", context)


@login_required
def api_anomalie_config_liste(request):
    if request.method == "GET":
        return JsonResponse(
            {
                "success": True,
                "lists": _load_anomalie_lists(),
                "attachments_dir": _anomalie_attachments_dir_value(),
            }
        )

    if request.method != "POST":
        return _json_error("Metodo non consentito", status=405)
    if not _can_manage_anomalie_config(request):
        return _json_error("Permesso negato", status=403)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return _json_error("Body JSON non valido", status=400)
    if not isinstance(payload, dict):
        return _json_error("Body JSON non valido", status=400)

    current = _load_anomalie_lists()
    updated: dict[str, list[str]] = {}
    for key in ANOMALIE_LIST_KEYS:
        raw_val = payload.get(key, current.get(key, []))
        normalized = _normalize_choice_list(raw_val)
        if key in ANOMALIE_NON_EMPTY_DEFAULT_KEYS and not normalized:
            normalized = list(ANOMALIE_LIST_DEFAULTS[key])
        updated[key] = normalized

    attachments_dir_raw = str(payload.get("attachments_dir") or "").strip()
    try:
        validated_attachments_dir = _validate_anomalie_attachments_dir(attachments_dir_raw)
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)

    try:
        _save_anomalie_lists(updated)
        saved_attachments_dir = _save_anomalie_attachments_dir(validated_attachments_dir)
    except Exception as exc:
        logger.exception("[anomalie] salvataggio liste fallito")
        return JsonResponse({"success": False, "error": str(exc)}, status=500)

    try:
        log_action(
            request,
            "anomalie_config_liste_update",
            "anomalie",
            {"keys": list(updated.keys()), "attachments_dir": saved_attachments_dir},
        )
    except Exception:
        pass

    return JsonResponse({"success": True, "lists": updated, "attachments_dir": saved_attachments_dir})


@login_required
@ensure_csrf_cookie
def apertura_segnalazione_page(request):
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    display_name = (
        (legacy_user.nome if legacy_user else None)
        or request.user.get_full_name()
        or request.user.username
    )
    context = {
        "page_title": "Apertura Segnalazione",
        "legacy_user": legacy_user,
        "username": display_name,
        "db_has_ordini": _has_table("ordini_produzione"),
        "db_has_anomalie": _has_table("anomalie"),
        "can_manage_config": _can_manage_anomalie_config(request),
        "config_lists_json": json.dumps(_load_anomalie_lists(), ensure_ascii=False),
    }
    return render(request, "anomalie/pages/apertura_segnalazione.html", context)


# ─────────────────────────────────────────────────────────────────────────────
# Export CSV anomalie
# ─────────────────────────────────────────────────────────────────────────────


class _Echo:
    def write(self, value):
        return value


@login_required
def export_anomalie_csv(request):
    """Scarica le anomalie in formato CSV."""
    if not _has_table("anomalie"):
        from django.http import HttpResponse
        return HttpResponse("Tabella anomalie non disponibile.", status=503)

    cols = legacy_table_columns("anomalie")
    wanted = [c for c in ["id", "ex_op_nominativo", "seriale", "descrizione",
                           "note_capocommessa", "numero_rdc", "avanzamento",
                           "created_datetime", "modified_datetime", "sharepoint_item_id"] if c in cols]
    if not wanted:
        wanted = list(cols)[:10]

    def stream():
        writer = csv.writer(_Echo())
        yield writer.writerow(wanted)
        with connections["default"].cursor() as cur:
            cur.execute(f"SELECT TOP 5000 {', '.join(wanted)} FROM anomalie ORDER BY id DESC")
            for row in cur.fetchall():
                yield writer.writerow([str(v) if v is not None else "" for v in row])

    resp = StreamingHttpResponse(stream(), content_type="text/csv; charset=utf-8-sig")
    resp["Content-Disposition"] = 'attachment; filename="anomalie.csv"'
    return resp

