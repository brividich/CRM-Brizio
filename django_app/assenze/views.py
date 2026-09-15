
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone as dt_timezone
import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core import signing
from django.db import connections, transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from config.env_config import get_first_env_value
from core.csv_export import CSV_CONTENT_TYPE, bom_first, safe_csv_writer
from core.acl import user_can_modulo_action
from core.caporeparto_utils import resolve_caporeparto_legacy_user

from admin_portale.decorators import legacy_admin_or_acl_required
from core.audit import log_action
from core.graph_utils import acquire_graph_token, is_placeholder_value
from core.legacy_utils import get_legacy_user, legacy_table_columns, legacy_table_has_column
from core.models import AuditLog
from core.module_branding import get_module_branding_context, handle_module_branding_post

from .constants import (
    AUTO_FINE_MINUTI,
    TIPI_ASSENZA_STORAGE,
    TIPI_ASSENZA_UI,
    SHORTCUT_PRESETS,
    SHORTCUT_CUSTOM,
    PERMESSO_MIN_MINUTES,
    PERMESSO_MAX_HOURS,
)

logger = logging.getLogger(__name__)

_SYNC_PULL_LOCK_KEY = "assenze:sync_pull:lock"
_SYNC_PULL_LAST_TS_KEY = "assenze:sync_pull:last_ts"
_SYNC_PULL_LOCK_TTL = 120
_SP_DELTA_LINK_KEY = "assenze:sp_delta_link"
_SP_PUSH_LOCK_KEY = "assenze:sp_push:lock"
_SP_PUSH_LOCK_TTL = 300
_SP_PUSH_BATCH = 50
_SP_MOTIVAZIONI_CACHE_KEY = "assenze:sp_motivazioni"
_SP_MOTIVAZIONI_CACHE_TTL = 2 * 60 * 60

_COLOR_CACHE_KEY_GLOBAL = "assenze:colors:global:v1"
_COLOR_CACHE_KEY_USER_PREFIX = "assenze:colors:user:v1:"
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_SELECT_RE = re.compile(r"^\s*SELECT\s", re.IGNORECASE)
_SELECT_DISTINCT_RE = re.compile(r"^\s*SELECT\s+DISTINCT\s", re.IGNORECASE)
_DEFAULT_COLORS = {
    "tipo_ferie": "#10b981",
    "tipo_permesso": "#3b82f6",
    "tipo_malattia": "#ef4444",
    "tipo_infortunio": "#f97316",
    "tipo_certifica_presenza": "#14b8a6",
    "tipo_altro": "#8b5cf6",
    "stato_in_attesa": "#60a5fa",
    "stato_rifiutato": "#94a3b8",
    "stato_approvato": "#34d399",
}
_COLOR_KEYS = set(_DEFAULT_COLORS.keys())

_TIPI_UI = set(TIPI_ASSENZA_UI)
_TIPI_STORAGE = set(TIPI_ASSENZA_STORAGE)
_CERTIFICA_PRESENZA_MARKER = "[CERTIFICA_PRESENZA]"
_CONSENSI = {"In attesa", "Approvato", "Rifiutato", "Bozza", "Programmato"}
_MOD_TO_CONSENSO = {"0": "Approvato", "1": "Rifiutato", "2": "In attesa", "3": "Bozza", "4": "Programmato"}
_CONSENSO_TO_MOD = {"Approvato": 0, "Rifiutato": 1, "In attesa": 2, "Bozza": 3, "Programmato": 4}
_APPROVAZIONE_DATETIME_COL = "approvazione_datetime"
_FORM_TOKEN_SALT = "assenze.form_submit"


def _json_error(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": msg}, status=status)


def _db_vendor() -> str:
    return str(connections["default"].vendor or "").lower()


def _quote_identifier(name: str) -> str:
    return connections["default"].ops.quote_name(str(name))


def _quoted_columns(columns: list[str], *, alias: str | None = None) -> str:
    if alias:
        return ", ".join(f"{alias}.{_quote_identifier(col)}" for col in columns)
    return ", ".join(_quote_identifier(col) for col in columns)


def _graph_settings() -> dict[str, str]:
    return {
        "tenant_id": get_first_env_value("GRAPH_TENANT_ID", "AZURE_TENANT_ID"),
        "client_id": get_first_env_value("GRAPH_CLIENT_ID", "AZURE_CLIENT_ID"),
        "client_secret": get_first_env_value("GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET"),
        "site_id": get_first_env_value("GRAPH_SITE_ID"),
        "list_id_assenze": get_first_env_value("GRAPH_LIST_ID_ASSENZE"),
    }


def _graph_configured() -> bool:
    gs = _graph_settings()
    required = ("tenant_id", "client_id", "client_secret", "site_id", "list_id_assenze")
    return all(not is_placeholder_value(gs.get(k, "")) for k in required)


def _graph_base_url() -> str:
    gs = _graph_settings()
    return f"https://graph.microsoft.com/v1.0/sites/{gs['site_id']}/lists/{gs['list_id_assenze']}/items"


def _graph_token() -> str:
    if not _graph_configured():
        raise RuntimeError("Configurazione Graph incompleta")
    gs = _graph_settings()
    return acquire_graph_token(gs["tenant_id"], gs["client_id"], gs["client_secret"])


def _graph_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_graph_token()}", "Content-Type": "application/json"}


def _graph_delta_changes(delta_link: str | None) -> tuple[list[dict], str]:
    """Elementi della lista cambiati dopo ``delta_link`` (tutti, se assente).

    Ritorna (elementi, nuovo deltaLink). Se il token non e' piu' valido Graph
    risponde 410: si riparte da un'enumerazione completa.
    """
    url = delta_link or f"{_graph_base_url()}/delta?$expand=fields"
    items: list[dict] = []
    new_link = ""
    while url:
        r = requests.get(url, headers=_graph_headers(), timeout=25)
        if r.status_code == 410 and delta_link:
            logger.warning("[assenze:sp_delta] token delta scaduto, enumerazione completa")
            return _graph_delta_changes(None)
        if r.status_code != 200:
            raise RuntimeError(f"Graph delta {r.status_code}: {r.text[:300]}")
        payload = r.json()
        items.extend(payload.get("value", []) or [])
        new_link = payload.get("@odata.deltaLink") or new_link
        url = payload.get("@odata.nextLink")
    return items, new_link


def _graph_create(fields_payload: dict) -> tuple[bool, dict | str]:
    r = requests.post(_graph_base_url(), headers=_graph_headers(), json={"fields": fields_payload}, timeout=20)
    if r.status_code in (200, 201):
        return True, r.json()
    return False, r.text


def _graph_update(item_id: str, fields_payload: dict) -> tuple[bool, dict | str]:
    r = requests.patch(f"{_graph_base_url()}/{item_id}/fields", headers=_graph_headers(), json=fields_payload, timeout=20)
    if r.status_code in (200, 204):
        if not r.text:
            return True, {}
        try:
            return True, r.json()
        except Exception:
            return True, {}
    return False, r.text


def _graph_delete(item_id: str) -> tuple[bool, str]:
    r = requests.delete(f"{_graph_base_url()}/{item_id}", headers=_graph_headers(), timeout=20)
    if r.status_code in (200, 202, 204):
        return True, ""
    if r.status_code == 404:
        try:
            payload = r.json()
        except ValueError:
            payload = {}
        error_code = str((payload.get("error") or {}).get("code") or "").strip()
        if error_code == "itemNotFound":
            # DELETE is effectively idempotent: if the remote item is already gone,
            # keep local cleanup moving instead of blocking the user.
            return True, ""
    return False, r.text


def _graph_get_item(item_id: str) -> dict | None:
    if not _graph_configured():
        return None
    rid = str(item_id or "").strip()
    if not rid:
        return None
    r = requests.get(f"{_graph_base_url()}/{rid}?expand=fields", headers=_graph_headers(), timeout=20)
    if r.status_code == 200:
        return r.json()
    return None


def _graph_get_motivazioni() -> list[str]:
    if not _graph_configured():
        return []
    gs = _graph_settings()
    url = f"https://graph.microsoft.com/v1.0/sites/{gs['site_id']}/lists/{gs['list_id_assenze']}/columns/Motivazionerichiesta"
    try:
        r = requests.get(url, headers=_graph_headers(), timeout=20)
        if r.status_code != 200:
            return []
        payload = r.json()
        raw = ((payload.get("choice") or {}).get("choices")) or []
        out: list[str] = []
        for item in raw:
            txt = str(item or "").strip()
            if txt:
                out.append(txt)
        return out
    except Exception:
        return []


def _as_int(value) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    try:
        return bool(int(value))
    except Exception:
        return str(value).strip().lower() in {"1", "true", "yes", "on", "si"}


def _parse_sp_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, dt_timezone.utc)
        dt_local = timezone.localtime(dt, timezone.get_current_timezone())
        return dt_local.replace(tzinfo=None)
    except Exception:
        return None


def _parse_input_dt(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt, timezone.get_current_timezone()).replace(tzinfo=None)
    return dt


def _to_isoz(value) -> str | None:
    dt = value
    if isinstance(dt, str):
        dt = _parse_sp_dt(dt)
    if not isinstance(dt, datetime):
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    dt = dt.astimezone(dt_timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _dt_label(value) -> str:
    dt = value if isinstance(value, datetime) else _parse_sp_dt(value)
    if not isinstance(dt, datetime):
        return ""
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return timezone.localtime(dt).strftime("%d-%m-%Y %H:%M")


def _norm_tipo(value) -> str:
    raw = str(value or "").strip()
    low = raw.lower()
    if low == "ferie":
        return "Ferie"
    if low == "permesso":
        return "Permesso"
    if low == "malattia":
        return "Malattia"
    if low in {"infortunio", "flessibilita", "flessibilità"}:
        return "Flessibilità"
    if low in {"certifica presenza", "certificapresenza", "certifica_presenza"}:
        return "Certifica presenza"
    if low == "altro":
        return "Altro"
    return "Altro"


def _has_certifica_presenza_marker(motivazione) -> bool:
    return str(motivazione or "").strip().startswith(_CERTIFICA_PRESENZA_MARKER)


def _strip_tipo_metadata_from_motivazione(motivazione) -> str:
    text = str(motivazione or "").strip()
    if not _has_certifica_presenza_marker(text):
        return text
    stripped = text[len(_CERTIFICA_PRESENZA_MARKER):].lstrip()
    return stripped.lstrip("-:| ").strip()


def _motivazione_for_storage(tipo, motivazione) -> str:
    clean = _strip_tipo_metadata_from_motivazione(motivazione)
    return clean


def _tipo_for_display(value, motivazione="") -> str:
    if _has_certifica_presenza_marker(motivazione):
        return "Certifica presenza"
    return _norm_tipo(value)


def _tipo_for_storage(value) -> str:
    tipo_ui = _norm_tipo(value)
    return tipo_ui if tipo_ui in _TIPI_STORAGE else "Altro"


def _tipo_for_graph(value, motivazione="") -> str:
    tipo_ui = _tipo_for_display(value, motivazione)
    return tipo_ui if tipo_ui in _TIPI_STORAGE else "Altro"


def _norm_consenso(value) -> str:
    text = str(value or "").strip()
    if text in _CONSENSI:
        return text
    low = text.lower()
    if "approv" in low:
        return "Approvato"
    if "rifiut" in low:
        return "Rifiutato"
    if "bozza" in low:
        return "Bozza"
    if "programm" in low:
        return "Programmato"
    return "In attesa"


def _has_assenze_column(column_name: str) -> bool:
    return legacy_table_has_column("assenze", column_name)


def _certificato_medico_for_tipo(tipo: str, value) -> str:
    if _norm_tipo(tipo) != "Malattia":
        return ""
    return str(value or "").strip()


def _moderation_label(value) -> str:
    parsed = _as_int(value)
    if parsed is None:
        return "N/D"
    return _MOD_TO_CONSENSO.get(str(parsed), "N/D")


def _status_from_moderation(value, *, default_pending: bool = False) -> tuple[int | None, str]:
    parsed = _as_int(value)
    if parsed is None and default_pending:
        parsed = 2
    if parsed is None:
        return None, "N/D"
    return parsed, _MOD_TO_CONSENSO.get(str(parsed), "N/D")


def _approval_timestamp_update(consenso, current: dict | None = None) -> dict:
    if not _has_assenze_column(_APPROVAZIONE_DATETIME_COL):
        return {}
    next_status = _norm_consenso(consenso)
    current_status = ""
    if current:
        _current_mod, current_label = _effective_status(
            current.get("consenso"),
            current.get("moderation_status"),
            default_pending=True,
        )
        current_status = current_label
    if next_status == "Approvato":
        if current_status != "Approvato":
            return {_APPROVAZIONE_DATETIME_COL: timezone.now()}
        return {}
    if not current:
        return {_APPROVAZIONE_DATETIME_COL: None}
    if current_status == "Approvato":
        return {_APPROVAZIONE_DATETIME_COL: None}
    return {}


def _table_exists(name: str) -> bool:
    return bool(legacy_table_columns(name))


def _fetch_all_dict(sql: str, params: list | tuple | None = None) -> list[dict]:
    with connections["default"].cursor() as cursor:
        cursor.execute(sql, params or [])
        cols = [str(c[0]) for c in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _select_limited(base_sql: str, order_by_sql: str, limit: int) -> str:
    limit = max(1, int(limit))
    if _db_vendor() == "sqlite":
        return f"{base_sql} {order_by_sql} LIMIT {limit}"
    if _SELECT_DISTINCT_RE.search(base_sql):
        # SQL Server: SELECT DISTINCT TOP N ... (TOP must come after DISTINCT)
        sql_with_top = _SELECT_DISTINCT_RE.sub(lambda m: f"{m.group(0)}TOP {limit} ", base_sql, count=1)
        return f"{sql_with_top} {order_by_sql}"
    if _SELECT_RE.search(base_sql):
        sql_with_top = _SELECT_RE.sub(lambda m: f"{m.group(0)}TOP {limit} ", base_sql, count=1)
        return f"{sql_with_top} {order_by_sql}"
    return f"SELECT TOP {limit} * FROM ({base_sql}) _q {order_by_sql}"


def _select_paginated(base_sql: str, order_by_sql: str, *, offset: int, limit: int) -> str:
    """Una pagina di risultati. Richiede un ORDER BY: senza, SQL Server rifiuta
    OFFSET/FETCH e l'ordine delle pagine sarebbe comunque arbitrario."""
    offset = max(0, int(offset))
    limit = max(1, int(limit))
    if not order_by_sql.strip():
        raise ValueError("_select_paginated richiede un ORDER BY")
    if _db_vendor() == "sqlite":
        return f"{base_sql} {order_by_sql} LIMIT {limit} OFFSET {offset}"
    return f"{base_sql} {order_by_sql} OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"


def _certificazione_presenza_dipendenti_attivi() -> list[str]:
    if not _table_exists("anagrafica_dipendenti"):
        return []

    cols = legacy_table_columns("anagrafica_dipendenti")
    select_cols = [c for c in ["cognome", "nome", "attivo"] if c in cols]
    if "nome" not in select_cols or "cognome" not in select_cols:
        return []

    where_parts = [
        "COALESCE(nome, '') <> ''",
        "COALESCE(cognome, '') <> ''",
    ]
    if "attivo" in select_cols:
        where_parts.append("attivo = 1")

    rows = _fetch_all_dict(
        f"""
        SELECT {_quoted_columns(select_cols)}
        FROM anagrafica_dipendenti
        WHERE {' AND '.join(where_parts)}
        ORDER BY cognome, nome
        """
    )

    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        full_name = f"{str(row.get('cognome') or '').strip()} {str(row.get('nome') or '').strip()}".strip()
        if not full_name:
            continue
        key = re.sub(r"\s+", " ", full_name).casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(full_name)
    return names


def _load_dipendenti_attivi_list() -> list[dict]:
    if not _table_exists("anagrafica_dipendenti"):
        return []
    cols = legacy_table_columns("anagrafica_dipendenti")
    if not {"id", "nome", "cognome"}.issubset(cols):
        return []
    where_parts = ["COALESCE(nome, '') <> ''", "COALESCE(cognome, '') <> ''"]
    if "attivo" in cols:
        where_parts.append("attivo = 1")
    rows = _fetch_all_dict(
        f"SELECT {_quoted_columns(['id', 'nome', 'cognome'])} FROM anagrafica_dipendenti "
        f"WHERE {' AND '.join(where_parts)} ORDER BY cognome, nome"
    )
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        ana_id = _as_int(row.get("id"))
        if ana_id is None:
            continue
        cognome = str(row.get("cognome") or "").strip()
        nome = str(row.get("nome") or "").strip()
        full_name = f"{cognome} {nome}".strip()
        key = re.sub(r"\s+", " ", full_name).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"id": ana_id, "full_name": full_name})
    return out


def _blank_expr(expr: str) -> str:
    if _db_vendor() == "sqlite":
        return f"NULLIF(TRIM(COALESCE({expr}, '')), '')"
    return f"NULLIF(LTRIM(RTRIM(COALESCE({expr}, ''))), '')"


def _resolve_request_display_name(
    *,
    legacy_user_id: int | None,
    email: str,
    username: str,
    fallback_name: str,
) -> str:
    fallback = str(fallback_name or "").strip()
    if not _table_exists("anagrafica_dipendenti"):
        return fallback

    cols = legacy_table_columns("anagrafica_dipendenti")
    if "nome" not in cols and "cognome" not in cols:
        return fallback

    select_cols = [c for c in ["id", "nome", "cognome"] if c in cols]
    clauses: list[str] = []
    params: list = []
    alias_candidates: list[str] = []

    if legacy_user_id is not None and "utente_id" in cols:
        clauses.append("utente_id = %s")
        params.append(int(legacy_user_id))
    if email and "email" in cols:
        clauses.append("UPPER(COALESCE(email,'')) = UPPER(%s)")
        params.append(str(email).strip())
    if "aliasusername" in cols:
        for candidate in [str(username or "").strip(), str(email or "").strip()]:
            if not candidate:
                continue
            alias_candidates.append(candidate)
            if "@" in candidate:
                alias_candidates.append(candidate.split("@", 1)[0].strip())
        seen_aliases: set[str] = set()
        for candidate in alias_candidates:
            alias = str(candidate or "").strip()
            if not alias:
                continue
            alias_key = alias.casefold()
            if alias_key in seen_aliases:
                continue
            seen_aliases.add(alias_key)
            clauses.append("UPPER(COALESCE(aliasusername,'')) = UPPER(%s)")
            params.append(alias)

    if not clauses:
        return fallback

    order_sql = " ORDER BY id DESC" if "id" in cols else ""
    rows = _fetch_all_dict(
        f"""
        SELECT {_quoted_columns(select_cols)}
        FROM anagrafica_dipendenti
        WHERE ({' OR '.join(clauses)}){order_sql}
        """,
        params,
    )
    for row in rows:
        nome = str(row.get("nome") or "").strip()
        cognome = str(row.get("cognome") or "").strip()
        full_name = f"{nome} {cognome}".strip()
        if full_name:
            return full_name
    return fallback


def _legacy_identity(request) -> tuple[str, str, int | None]:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if legacy_user:
        name = (legacy_user.nome or "").strip() or request.user.get_full_name() or request.user.get_username()
        email = (legacy_user.email or "").strip().lower() or (request.user.email or "").strip().lower()
        return name, email, _as_int(getattr(legacy_user, "id", None))
    return request.user.get_full_name() or request.user.get_username(), (request.user.email or "").strip().lower(), None


def _role_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _role_names(request, legacy_user) -> set[str]:
    names: set[str] = set()
    if legacy_user:
        role_txt = str(getattr(legacy_user, "ruolo", "") or "").strip()
        if role_txt:
            names.add(role_txt)
        role_id = _as_int(getattr(legacy_user, "ruolo_id", None))
        if role_id is not None and _table_exists("ruoli"):
            rows = _fetch_all_dict("SELECT nome FROM ruoli WHERE id = %s", [role_id])
            if rows:
                role_name = str(rows[0].get("nome") or "").strip()
                if role_name:
                    names.add(role_name)
    try:
        for group_name in request.user.groups.values_list("name", flat=True):
            txt = str(group_name or "").strip()
            if txt:
                names.add(txt)
    except Exception:
        pass
    return names


def _capo_assignment_where_clause(
    *,
    legacy_user_id: int | None,
    manager_name: str = "",
    manager_email: str = "",
    alias: str = "cr",
    cols: set[str] | None = None,
) -> tuple[str, list]:
    capi_cols = cols if cols is not None else legacy_table_columns("capi_reparto")
    clauses: list[str] = []
    params: list = []
    prefix = f"{alias}." if alias else ""

    if legacy_user_id is not None and "utente_id" in capi_cols:
        clauses.append(f"{prefix}utente_id = %s")
        params.append(int(legacy_user_id))

    manager_email = str(manager_email or "").strip()
    if manager_email and "indirizzo_email" in capi_cols:
        clauses.append(f"UPPER(COALESCE({prefix}indirizzo_email,'')) = UPPER(%s)")
        params.append(manager_email)
        # Fallback dominio: s.user@dominioA deve matchare s.user@dominioB.
        local_part = manager_email.split("@", 1)[0].strip()
        if local_part:
            clauses.append(f"UPPER(COALESCE({prefix}indirizzo_email,'')) LIKE UPPER(%s)")
            params.append(f"{local_part}@%")

    manager_name = str(manager_name or "").strip()
    if manager_name and "nome" in capi_cols:
        clauses.append(f"UPPER(COALESCE({prefix}nome,'')) = UPPER(%s)")
        params.append(manager_name)
        # Fallback ordine nome/cognome: "Smarrella Simone" vs "Simone Smarrella".
        name_tokens = [t for t in manager_name.split() if t]
        if len(name_tokens) >= 2:
            forward_pattern = "%" + "%".join(name_tokens) + "%"
            reverse_pattern = "%" + "%".join(reversed(name_tokens)) + "%"
            clauses.append(f"UPPER(COALESCE({prefix}nome,'')) LIKE UPPER(%s)")
            params.append(forward_pattern)
            if reverse_pattern != forward_pattern:
                clauses.append(f"UPPER(COALESCE({prefix}nome,'')) LIKE UPPER(%s)")
                params.append(reverse_pattern)

    if manager_name and "title" in capi_cols:
        clauses.append(f"UPPER(COALESCE({prefix}title,'')) = UPPER(%s)")
        params.append(manager_name)

    if not clauses:
        return "", []
    return f"({' OR '.join(clauses)})", params


def _local_manager_assignment_where_clause(
    *,
    legacy_user_id: int | None,
    alias: str = "a",
) -> tuple[str, list]:
    if legacy_user_id is None or "capo_reparto_id" not in legacy_table_columns("assenze"):
        return "", []
    prefix = f"{alias}." if alias else ""
    return f"{prefix}capo_reparto_id = %s", [int(legacy_user_id)]


def _combined_manager_assignment_where_clause(
    *,
    legacy_user_id: int | None,
    manager_name: str = "",
    manager_email: str = "",
    assenze_alias: str = "a",
    capi_alias: str = "cr",
) -> tuple[str, list, bool]:
    clauses: list[str] = []
    params: list = []

    local_where, local_params = _local_manager_assignment_where_clause(
        legacy_user_id=legacy_user_id,
        alias=assenze_alias,
    )
    if local_where:
        clauses.append(local_where)
        params.extend(local_params)

    use_legacy_join = _legacy_capi_table_exists()
    if use_legacy_join:
        legacy_where, legacy_params = _capo_assignment_where_clause(
            legacy_user_id=legacy_user_id,
            manager_name=manager_name,
            manager_email=manager_email,
            alias=capi_alias,
            cols=legacy_table_columns("capi_reparto"),
        )
        if legacy_where:
            clauses.append(legacy_where)
            params.extend(legacy_params)

    if not clauses:
        return "", [], use_legacy_join
    return f"({' OR '.join(clauses)})", params, use_legacy_join


def _capo_assignment_diagnostics(
    *,
    legacy_user_id: int | None,
    manager_name: str = "",
    manager_email: str = "",
) -> dict:
    """Ritorna diagnostica sul match tra utente corrente e capi_reparto."""
    if not _table_exists("capi_reparto"):
        return {"table_exists": False, "where_sql": "", "params": [], "matched": [], "match_count": 0}

    cols = legacy_table_columns("capi_reparto")
    where_sql, params = _capo_assignment_where_clause(
        legacy_user_id=legacy_user_id,
        manager_name=manager_name,
        manager_email=manager_email,
        alias="cr",
        cols=cols,
    )
    if not where_sql:
        return {"table_exists": True, "where_sql": "", "params": [], "matched": [], "match_count": 0}

    select_cols = [c for c in ["id", "title", "nome", "indirizzo_email", "sharepoint_item_id", "utente_id"] if c in cols]
    if not select_cols:
        return {"table_exists": True, "where_sql": where_sql, "params": params, "matched": [], "match_count": 0}

    rows = _fetch_all_dict(
        f"SELECT {_quoted_columns(select_cols, alias='cr')} FROM capi_reparto cr WHERE {where_sql} ORDER BY cr.title, cr.id",
        params,
    )
    return {
        "table_exists": True,
        "where_sql": where_sql,
        "params": params,
        "matched": rows,
        "match_count": len(rows),
    }


def _owned_capo_ids_for_legacy_user(
    legacy_user_id: int | None,
    *,
    manager_name: str = "",
    manager_email: str = "",
) -> tuple[set[int], set[int]]:
    local_ids: set[int] = set()
    lookup_ids: set[int] = set()
    if legacy_user_id is not None:
        local_ids.add(int(legacy_user_id))
    if not _legacy_capi_table_exists():
        return local_ids, lookup_ids
    cols = legacy_table_columns("capi_reparto")
    where_sql, where_params = _capo_assignment_where_clause(
        legacy_user_id=legacy_user_id,
        manager_name=manager_name,
        manager_email=manager_email,
        alias="c",
        cols=cols,
    )
    if not where_sql:
        return set(), set()

    select_cols = ["id"]
    if "sharepoint_item_id" in cols:
        select_cols.append("sharepoint_item_id")
    rows = _fetch_all_dict(
        f"SELECT {_quoted_columns(select_cols)} FROM capi_reparto c WHERE {where_sql}",
        where_params,
    )
    for row in rows:
        local_id = _as_int(row.get("id"))
        lookup_id = _as_int(row.get("sharepoint_item_id"))
        if local_id is not None:
            local_ids.add(local_id)
        if lookup_id is not None:
            lookup_ids.add(lookup_id)
    return local_ids, lookup_ids


def _assenze_permissions(request) -> dict:
    cached = getattr(request, "_assenze_perm_cache", None)
    if isinstance(cached, dict):
        return cached

    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    legacy_user_id = _as_int(getattr(legacy_user, "id", None)) if legacy_user else None
    role_labels = _role_names(request, legacy_user)
    role_keys = {_role_key(v) for v in role_labels if str(v or "").strip()}

    is_amministrazione = bool(getattr(request.user, "is_superuser", False)) or any(
        ("amministraz" in k) or (k in {"admin", "amministratore"}) for k in role_keys
    )
    is_car = any(("caporepart" in k) or (k == "car") for k in role_keys)
    is_utenti = any(k in {"utente", "utenti"} for k in role_keys)

    if is_amministrazione:
        group = "AMMINISTRAZIONE"
    elif is_car:
        group = "CAR"
    elif is_utenti:
        group = "UTENTI"
    else:
        group = "UTENTI"

    can_insert = group in {"UTENTI", "CAR", "AMMINISTRAZIONE"}
    can_insert_for_others = group in {"CAR", "AMMINISTRAZIONE"}
    can_view_calendar = group in {"CAR", "AMMINISTRAZIONE"}
    can_update_any = group == "AMMINISTRAZIONE"
    can_update_owned = group == "CAR"
    can_delete_any = group == "AMMINISTRAZIONE"
    can_skip_approval = group in {"CAR", "AMMINISTRAZIONE"}
    manager_name = ""
    manager_email = ""
    if legacy_user:
        manager_name = str(getattr(legacy_user, "nome", "") or "").strip()
        manager_email = str(getattr(legacy_user, "email", "") or "").strip()
    if not manager_name:
        manager_name = (request.user.get_full_name() or request.user.get_username() or "").strip()
    if not manager_email:
        manager_email = (request.user.email or "").strip()

    owned_local_ids, owned_lookup_ids = _owned_capo_ids_for_legacy_user(
        legacy_user_id,
        manager_name=manager_name,
        manager_email=manager_email,
    )

    # Ambito "inserimento per altri": Caporeparto e Amministrazione inseriscono per
    # TUTTI i dipendenti, non solo per i propri. Gli altri profili solo per se'
    # stessi. Il caporeparto che approva resta comunque quello del dipendente
    # scelto (vedi `_effective_capo_option`): poter inserire non vuol dire
    # approvare.
    insert_for_others_scope = "all" if can_insert_for_others else "none"

    perms = {
        "group": group,
        "legacy_user_id": legacy_user_id,
        "can_insert": can_insert,
        "can_insert_for_others": can_insert_for_others,
        "insert_for_others_scope": insert_for_others_scope,
        "can_view_calendar": can_view_calendar,
        "can_update_any": can_update_any,
        "can_update_owned": can_update_owned,
        "can_delete_any": can_delete_any,
        "can_skip_approval": can_skip_approval,
        "can_edit_events": can_update_any or can_update_owned,
        "owned_capo_local_ids": owned_local_ids,
        "owned_capo_lookup_ids": owned_lookup_ids,
        "role_labels": sorted(role_labels),
    }
    setattr(request, "_assenze_perm_cache", perms)
    return perms


def _insertable_dipendenti_for_request(request) -> list[dict]:
    """Elenco dipendenti per cui l'utente corrente può inserire una richiesta."""
    perms = _assenze_permissions(request)
    if perms.get("insert_for_others_scope") == "all":
        return _load_dipendenti_attivi_list()
    return []


def _can_insert_for_dipendente(request, anagrafica_id: int | None) -> bool:
    """True se l'utente può inserire una richiesta per il dipendente indicato."""
    if anagrafica_id is None:
        return False
    perms = _assenze_permissions(request)
    return perms.get("insert_for_others_scope") == "all"


def _template_perm_context(request) -> dict:
    perms = _assenze_permissions(request)
    return {
        "assenze_group": perms["group"],
        "assenze_can_insert": perms["can_insert"],
        "assenze_can_insert_for_others": perms["can_insert_for_others"],
        "assenze_can_view_calendar": perms["can_view_calendar"],
        "assenze_can_skip_approval": perms["can_skip_approval"],
        "assenze_can_edit_events": perms["can_edit_events"],
        "assenze_can_delete_events": perms["can_delete_any"],
        "assenze_can_reconcile": perms.get("can_update_any", False),
        "assenze_is_admin": user_can_modulo_action(request, "assenze", "admin_assenze"),
    }


def _can_manage_record(request, row: dict, *, require_delete: bool = False) -> bool:
    perms = _assenze_permissions(request)
    if require_delete:
        return bool(perms.get("can_delete_any"))
    if perms.get("can_update_any"):
        return True
    if not perms.get("can_update_owned"):
        return False

    lookup_id = _as_int(row.get("capo_reparto_lookup_id"))
    if lookup_id is not None and lookup_id in set(perms.get("owned_capo_lookup_ids") or set()):
        return True

    local_id = _as_int(row.get("capo_reparto_id"))
    if local_id is not None and local_id in set(perms.get("owned_capo_local_ids") or set()):
        return True

    return False


def _week_window(value: datetime) -> tuple[datetime, datetime]:
    monday = datetime.combine((value.date() - timedelta(days=value.weekday())), datetime.min.time())
    return monday, monday + timedelta(days=7)


def _count_flessibilita_week(
    *,
    person_name: str,
    person_email: str,
    week_start: datetime,
    week_end: datetime,
    exclude_item_id: int | None = None,
) -> int:
    if not _table_exists("assenze"):
        return 0

    who_clauses = []
    who_params: list = []
    if person_name:
        who_clauses.append("UPPER(COALESCE(copia_nome,'')) = UPPER(%s)")
        who_params.append(person_name)
    if person_email:
        who_clauses.append("UPPER(COALESCE(email_esterna,'')) = UPPER(%s)")
        who_params.append(person_email)
    if not who_clauses:
        return 0

    sql = f"""
        SELECT id, tipo_assenza
        FROM assenze
        WHERE ({' OR '.join(who_clauses)})
          AND data_inizio >= %s
          AND data_inizio < %s
    """
    rows = _fetch_all_dict(sql, [*who_params, week_start, week_end])
    count = 0
    for row in rows:
        rid = _as_int(row.get("id"))
        if exclude_item_id is not None and rid == int(exclude_item_id):
            continue
        if _norm_tipo(row.get("tipo_assenza")) == "Flessibilità":
            count += 1
    return count


def _anagrafica_id_for_assenza_row(row: dict) -> int | None:
    """Id anagrafica del dipendente di una riga `assenze` (per le regole per-persona)."""
    if not row:
        return None
    return _resolve_anagrafica_employee_id_for_user(
        legacy_user_id=_as_int(row.get("utente_id")),
        email=str(row.get("email_esterna") or ""),
        username=str(row.get("aliasusername") or ""),
        name=str(row.get("copia_nome") or ""),
    )


def _flessibilita_config():
    """Orari ammessi per la Flessibilita' (fail-safe sui default se il DB tace)."""
    from .models import FlessibilitaImpostazioni

    try:
        return FlessibilitaImpostazioni.get_solo()
    except Exception:
        logger.warning("[assenze] impostazioni flessibilita' non leggibili, uso i default", exc_info=True)
        return FlessibilitaImpostazioni(
            orari_entrata=FlessibilitaImpostazioni.ENTRATE_DEFAULT,
            orari_uscita=FlessibilitaImpostazioni.USCITE_DEFAULT,
        )


def _flessibilita_abilitati_ids() -> set[int]:
    from .models import FlessibilitaAbilitato

    try:
        return {
            int(v)
            for v in FlessibilitaAbilitato.objects.values_list("legacy_anagrafica_id", flat=True)
            if v is not None
        }
    except Exception:
        logger.warning("[assenze] elenco abilitati flessibilita' non leggibile", exc_info=True)
        return set()


def _flessibilita_abilitata_per(anagrafica_id: int | None) -> bool:
    """Fail-CLOSED: senza un id risolvibile la flessibilita' non si concede."""
    if anagrafica_id is None:
        return False
    return int(anagrafica_id) in _flessibilita_abilitati_ids()


def _autocorreggi_fine(dt_start: datetime | None, dt_end: datetime | None) -> tuple[datetime | None, str]:
    """Riallinea la fine quando non e' successiva all'inizio.

    Capitava di compilare l'orario al contrario (inizio 14:00, fine 09:00) e di
    ricevere solo un errore secco. Quando la fine non e' successiva all'inizio la
    si riporta a ``inizio + AUTO_FINE_MINUTI`` **sul giorno dell'inizio**, e si
    restituisce l'avviso da mostrare a chi compila: il dato non cambia in
    silenzio. Le richieste su piu' giorni (fine in una data successiva) non
    vengono toccate.
    """
    if dt_start is None or dt_end is None:
        return dt_end, ""
    if dt_end > dt_start:
        return dt_end, ""
    corretta = dt_start + timedelta(minutes=AUTO_FINE_MINUTI)
    return corretta, (
        f"L'ora di fine non era successiva all'inizio: impostata automaticamente "
        f"alle {corretta:%H:%M} del {corretta:%d/%m/%Y}."
    )


def _validate_business_rules(
    *,
    tipo: str,
    dt_start: datetime | None,
    dt_end: datetime | None,
    person_name: str = "",
    person_email: str = "",
    person_anagrafica_id: int | None = None,
    exclude_item_id: int | None = None,
    shortcut=None,
) -> tuple[str, str]:
    if dt_start is None or dt_end is None:
        return "Compila data e ora inizio/fine.", ""
    if dt_end <= dt_start:
        return "La data/ora di fine deve essere successiva all'inizio.", ""

    # Durata rapida: l'utente può cambiare solo la data, non l'orario.
    shortcut_key = str(shortcut or "").strip().lower()
    if shortcut_key and shortcut_key != SHORTCUT_CUSTOM:
        preset = SHORTCUT_PRESETS.get(shortcut_key)
        if preset is None:
            return "Durata rapida non valida.", ""
        if dt_start.date() != dt_end.date():
            return "Con una durata rapida la richiesta deve restare nello stesso giorno.", ""
        if (dt_start.strftime("%H:%M"), dt_end.strftime("%H:%M")) != preset:
            return "Con una durata rapida puoi modificare solo la data, non l'orario.", ""

    tipo_ui = _norm_tipo(tipo)
    warning = ""
    if tipo_ui == "Permesso":
        if dt_start.date() != dt_end.date():
            return "Il permesso deve iniziare e finire nello stesso giorno.", ""
        minutes = (dt_end - dt_start).total_seconds() / 60.0
        if minutes < PERMESSO_MIN_MINUTES or minutes > PERMESSO_MAX_HOURS * 60:
            return "Il permesso deve durare tra 30 minuti e 8 ore.", ""
    if tipo_ui == "Ferie":
        if dt_end.date() <= dt_start.date():
            return "Le ferie devono coprire più di un giorno.", ""
        if (dt_start.hour, dt_start.minute, dt_end.hour, dt_end.minute) != (0, 0, 23, 59):
            return "Le ferie devono coprire giornate intere: orario 00:00-23:59.", ""
    if tipo_ui == "Flessibilità":
        # La flessibilita' non spetta a tutti e non ha orari liberi: entrambe le
        # regole sono configurate in Impostazioni (vedi FlessibilitaAbilitato /
        # FlessibilitaImpostazioni).
        if not _flessibilita_abilitata_per(person_anagrafica_id):
            return (
                "La flessibilità non è abilitata per questo dipendente: "
                "l'Amministrazione può abilitarla dalle impostazioni del modulo.",
                "",
            )
        conf = _flessibilita_config()
        ora_inizio = dt_start.strftime("%H:%M")
        ora_fine = dt_end.strftime("%H:%M")
        if ora_inizio not in conf.entrate:
            return (
                "Orario di entrata non ammesso per la flessibilità: "
                f"scegli fra {', '.join(conf.entrate)}.",
                "",
            )
        if ora_fine not in conf.uscite:
            return (
                "Orario di uscita non ammesso per la flessibilità: "
                f"scegli fra {', '.join(conf.uscite)}.",
                "",
            )
        diff_hours = (dt_end - dt_start).total_seconds() / 3600.0
        if diff_hours < 9:
            return "Devi fare almeno 8 ore lavorative più 1 ora di pausa: altrimenti usa Permesso.", ""
        if diff_hours > 10:
            return "Orario non valido per Flessibilità: durata massima consentita 10 ore.", ""

        week_start, week_end = _week_window(dt_start)
        used = _count_flessibilita_week(
            person_name=person_name,
            person_email=person_email,
            week_start=week_start,
            week_end=week_end,
            exclude_item_id=exclude_item_id,
        )
        if used >= 2:
            return "Hai già richiesto 2 flessibilità in questa settimana.", ""
        if abs(diff_hours - 10.0) < 0.001:
            warning = "Con 10 ore, la pausa pranzo prevista è di 2 ore (12:00-14:00)."

    return "", warning


def _resolve_nome_lookup_id(legacy_user_id: int | None, display_name: str) -> int | None:
    if not _table_exists("dipendenti"):
        return None
    cols = legacy_table_columns("dipendenti")
    with connections["default"].cursor() as cursor:
        if legacy_user_id is not None and "utente_id" in cols:
            cursor.execute("SELECT id, sharepoint_item_id FROM dipendenti WHERE utente_id = %s ORDER BY id DESC", [legacy_user_id])
            row = cursor.fetchone()
            if row and row[1] is not None:
                return _as_int(row[1])
        if "title" in cols:
            if _db_vendor() == "sqlite":
                cursor.execute("SELECT sharepoint_item_id FROM dipendenti WHERE UPPER(COALESCE(title,'')) = UPPER(?) ORDER BY id DESC LIMIT 1", [display_name])
            else:
                cursor.execute("SELECT TOP 1 sharepoint_item_id FROM dipendenti WHERE UPPER(COALESCE(title,'')) = UPPER(%s) ORDER BY id DESC", [display_name])
            row = cursor.fetchone()
            if row and row[0] is not None:
                return _as_int(row[0])
    return None


def _resolve_capo_lookup_id(capo_value: str | None) -> int | None:
    raw = str(capo_value or "").strip()
    if not raw:
        return None
    numeric = _as_int(raw)
    if numeric is not None:
        return numeric
    return _resolve_legacy_capo_lookup_by_raw_value(raw)


def _find_local_capo_id_by_column(column_name: str, value) -> int | None:
    if value is None:
        return None
    sql = _select_limited(
        f"SELECT id FROM capi_reparto WHERE {column_name} = %s",
        "ORDER BY id DESC",
        1,
    )
    rows = _fetch_all_dict(sql, [value])
    if not rows:
        return None
    return _as_int(rows[0].get("id"))


def _resolve_capo_local_id_from_option_config(raw: str) -> int | None:
    try:
        from core.models import OptioneConfig
    except Exception:
        return None
    raw_lower = raw.strip().casefold()
    for option in OptioneConfig.objects.filter(tipo__iexact="caporeparto", is_active=True):
        if str(option.valore or "").strip().casefold() == raw_lower:
            legacy_user_id = _as_int(getattr(option, "legacy_user_id", None))
            if legacy_user_id is not None:
                return legacy_user_id
    return None


def _resolve_capo_local_id_from_anagrafica_hr(raw: str) -> int | None:
    raw_key = _norm_text_key(raw)
    if not raw_key:
        return None
    for option in _load_anagrafica_hr_capi_options():
        candidates = {
            _norm_text_key(_capo_option_value(option)),
            _norm_text_key(option.get("Email")),
            _norm_text_key(option.get("LookupId")),
            _norm_text_key(option.get("Value")),
            _norm_text_key(option.get("AnagraficaLegacyId")),
        }
        candidates.discard("")
        if raw_key in candidates:
            legacy_user_id = _as_int(option.get("LegacyUserId"))
            if legacy_user_id is not None:
                return legacy_user_id
    return None


def _resolve_capo_local_id(capo_value: str | None) -> int | None:
    raw = str(capo_value or "").strip()
    if not raw:
        return None
    anagrafica_hr_user_id = _resolve_capo_local_id_from_anagrafica_hr(raw)
    if not _legacy_capi_table_exists():
        return anagrafica_hr_user_id or _resolve_capo_local_id_from_option_config(raw)

    cols = legacy_table_columns("capi_reparto")
    if "id" not in cols:
        return anagrafica_hr_user_id

    legacy_user = _resolve_local_capo_legacy_user(raw)
    legacy_user_id = _as_int(getattr(legacy_user, "id", None)) if legacy_user is not None else None
    if legacy_user_id is not None and "utente_id" in cols:
        capo_id = _find_local_capo_id_by_column("utente_id", int(legacy_user_id))
        if capo_id is not None:
            return capo_id

    if "@" in raw and "indirizzo_email" in cols:
        capo_id = _find_local_capo_id_by_column("indirizzo_email", raw)
        if capo_id is not None:
            return capo_id

    if "title" in cols:
        capo_id = _find_local_capo_id_by_column("title", raw)
        if capo_id is not None:
            return capo_id

    numeric = _as_int(raw)
    if numeric is not None and "sharepoint_item_id" in cols:
        capo_id = _find_local_capo_id_by_column("sharepoint_item_id", int(numeric))
        if capo_id is not None:
            return capo_id

    if numeric is not None:
        capo_id = _find_local_capo_id_by_column("id", int(numeric))
        if capo_id is not None:
            return capo_id
    return anagrafica_hr_user_id


def _resolve_capo_option_value_from_ids(
    *,
    local_id: int | None,
    lookup_id: int | None,
    capi: list[dict],
) -> str:
    for capo in capi:
        if local_id is not None and _as_int(capo.get("LegacyUserId")) == local_id:
            return _capo_option_value(capo)
        legacy_lookup = _as_int(capo.get("LegacyLookupId"))
        if lookup_id is not None and legacy_lookup == lookup_id:
            return _capo_option_value(capo)
        option_lookup = _as_int(capo.get("LookupId"))
        if lookup_id is not None and option_lookup == lookup_id:
            return _capo_option_value(capo)

    if lookup_id is None or not _legacy_capi_table_exists():
        return ""
    cols = legacy_table_columns("capi_reparto")
    select_cols = []
    if "indirizzo_email" in cols:
        select_cols.append("indirizzo_email")
    if "title" in cols:
        select_cols.append("title")
    if not select_cols:
        return ""
    base_sql = f"SELECT {_quoted_columns(select_cols)} FROM capi_reparto WHERE sharepoint_item_id = %s"
    sql = _select_limited(base_sql, "ORDER BY id DESC", 1)
    rows = _fetch_all_dict(sql, [int(lookup_id)])
    if not rows:
        return ""
    row = rows[0]
    email = str(row.get("indirizzo_email") or "").strip()
    title = str(row.get("title") or "").strip()
    return email or title


def _prepare_row_data(data: dict) -> dict:
    cols = legacy_table_columns("assenze")
    return {k: v for k, v in data.items() if k in cols}


def _fetch_first_row_from_cursor(cursor):
    while True:
        if getattr(cursor, "description", None):
            try:
                return cursor.fetchone()
            except Exception:
                pass
        try:
            has_next = cursor.nextset()
        except Exception:
            return None
        if not has_next:
            return None


def _insert_row_and_return_id(cursor, table: str, cols: list[str], values: list[object]) -> int | None:
    placeholders = ", ".join(["%s"] * len(cols))
    quoted_table = _quote_identifier(table)
    quoted_cols = _quoted_columns(cols)
    vendor = _db_vendor()
    if vendor == "sqlite":
        cursor.execute(f"INSERT INTO {quoted_table} ({quoted_cols}) VALUES ({placeholders})", values)
        return int(cursor.lastrowid) if cursor.lastrowid else None
    if vendor in {"microsoft", "mssql", "sql_server"}:
        cursor.execute(
            (
                "DECLARE @inserted_ids TABLE (id int); "
                f"INSERT INTO {quoted_table} ({quoted_cols}) "
                f"OUTPUT INSERTED.id INTO @inserted_ids VALUES ({placeholders}); "
                "SELECT TOP 1 id FROM @inserted_ids;"
            ),
            values,
        )
        row_inserted = _fetch_first_row_from_cursor(cursor)
        if row_inserted and row_inserted[0] is not None:
            return int(row_inserted[0])
        return None
    cursor.execute(f"INSERT INTO {quoted_table} ({quoted_cols}) VALUES ({placeholders})", values)
    if getattr(cursor, "lastrowid", None):
        return int(cursor.lastrowid)
    cursor.execute("SELECT CAST(SCOPE_IDENTITY() AS int)")
    row_inserted = _fetch_first_row_from_cursor(cursor)
    if row_inserted and row_inserted[0] is not None:
        return int(row_inserted[0])
    return None


def _find_inserted_assenza_id(row: dict) -> int | None:
    match_fields = [
        "sharepoint_item_id",
        "nome_lookup_id",
        "copia_nome",
        "email_esterna",
        "tipo_assenza",
        "capo_reparto_id",
        "capo_reparto_lookup_id",
        "data_inizio",
        "data_fine",
        "motivazione_richiesta",
        "certificato_medico",
        "salta_approvazione",
        "consenso",
        "moderation_status",
        _APPROVAZIONE_DATETIME_COL,
    ]
    clauses: list[str] = []
    params: list[object] = []
    for field in match_fields:
        if field not in row:
            continue
        quoted_field = _quote_identifier(field)
        value = row.get(field)
        if value is None:
            clauses.append(f"{quoted_field} IS NULL")
        else:
            clauses.append(f"{quoted_field} = %s")
            params.append(value)
    if not clauses:
        return None
    sql = _select_limited(f"SELECT id FROM assenze WHERE {' AND '.join(clauses)}", "ORDER BY id DESC", 1)
    with connections["default"].cursor() as cursor:
        cursor.execute(sql, params)
        existing = cursor.fetchone()
    if existing and existing[0] is not None:
        return int(existing[0])
    return None


def _insert_assenza(data: dict) -> int | None:
    row = _prepare_row_data(data)
    if not row:
        return None
    cols = list(row.keys())
    values = [row[c] for c in cols]
    with connections["default"].cursor() as cursor:
        row_id = _insert_row_and_return_id(cursor, "assenze", cols, values)
    if row_id is not None:
        return row_id
    return _find_inserted_assenza_id(row)


def _update_assenza(item_id: int, updates: dict) -> bool:
    row = _prepare_row_data(updates)
    if not row:
        return False
    sets = ", ".join(f"{_quote_identifier(k)} = %s" for k in row.keys())
    with connections["default"].cursor() as cursor:
        cursor.execute(f"UPDATE assenze SET {sets} WHERE id = %s", [*list(row.values()), int(item_id)])
        return bool(cursor.rowcount)


def _delete_assenza(item_id: int) -> bool:
    from .models import AssenzaOrigineSharePoint

    with connections["default"].cursor() as cursor:
        cursor.execute("DELETE FROM assenze WHERE id = %s", [int(item_id)])
        deleted = bool(cursor.rowcount)
    if deleted:
        AssenzaOrigineSharePoint.objects.filter(assenza_id=int(item_id)).delete()
    return deleted


def _get_assenza(item_id: int) -> dict | None:
    if not _table_exists("assenze"):
        return None
    cols = legacy_table_columns("assenze")
    wanted = [
        "id",
        "sharepoint_item_id",
        "nome_lookup_id",
        "capo_reparto_id",
        "capo_reparto_lookup_id",
        "copia_nome",
        "email_esterna",
        "utente_id",
        "aliasusername",
        "tipo_assenza",
        "data_inizio",
        "data_fine",
        "motivazione_richiesta",
        "certificato_medico",
        "salta_approvazione",
        "consenso",
        "moderation_status",
        _APPROVAZIONE_DATETIME_COL,
        "note_gestione",
    ]
    selected = [col for col in wanted if col in cols]
    if "id" not in selected:
        return None
    rows = _fetch_all_dict(f"SELECT {_quoted_columns(selected)} FROM assenze WHERE id = %s", [int(item_id)])
    return rows[0] if rows else None


# ─── Persona e capo su SharePoint (colonne lookup) ────────────────────────────
# Nella lista assenze «Nome» punta alla lista DIPENDENTI e «Capo Reparto» alla
# lista Caporeparto: SharePoint vuole l'id dell'elemento, non il nome. Il portale
# sceglie il capo dall'anagrafica (responsabile dell'area aziendale), quindi l'id
# si cerca per email nella lista Caporeparto. Le tabelle locali dipendenti /
# capi_reparto sono copie storiche e non conoscono i responsabili d'area.

_SP_LOOKUP_MAPS_CACHE_KEY = "assenze:sp_lookup_maps:v1"
_SP_LOOKUP_MAPS_TTL = 60 * 60
_SP_NOME_LOOKUP_COLUMN = "Nome"
_SP_CAPO_LOOKUP_COLUMN = "C_x002e_Reparto"
_SP_CAPO_EMAIL_FIELD = "IndirizozEmail"  # sic: il nome interno della colonna SharePoint ha il refuso
_SP_DIPENDENTE_USERNAME_FIELD = "USERNAME"


def _graph_get_pages(url: str) -> list[dict]:
    rows: list[dict] = []
    while url:
        r = requests.get(url, headers=_graph_headers(), timeout=25)
        if r.status_code != 200:
            raise RuntimeError(f"Graph GET {r.status_code}: {r.text[:300]}")
        payload = r.json()
        rows.extend(payload.get("value", []) or [])
        url = payload.get("@odata.nextLink")
    return rows


def _name_tokens_key(value) -> str:
    """Nominativo come insieme di parole: «BOVA LUCA» e «Luca Bova» coincidono."""
    return " ".join(sorted(_sync_name_key(value).split()))


def _index_unique_sp_items(items: list[dict], key_fn) -> dict[str, int]:
    """Indice chiave -> id elemento. Una chiave presente su due elementi e' ambigua e si scarta."""
    index: dict[str, int] = {}
    ambiguous: set[str] = set()
    for item in items:
        item_id = _as_int(item.get("id"))
        key = key_fn(item.get("fields") or {})
        if item_id is None or not key:
            continue
        if key in index and index[key] != item_id:
            ambiguous.add(key)
        index[key] = item_id
    for key in ambiguous:
        index.pop(key, None)
    return index


def _sp_lookup_maps() -> dict:
    """Tabelle email/username/nominativo -> id delle liste Caporeparto e DIPENDENTI.

    Lette da Graph solo durante l'invio (job in background, mai dalle pagine) e
    tenute in cache un'ora. Le liste si ricavano dalle colonne lookup della lista
    assenze, senza configurazione. Un errore Graph si propaga: l'invio fallisce e
    la richiesta resta in coda per il giro successivo.
    """
    cached = cache.get(_SP_LOOKUP_MAPS_CACHE_KEY)
    if isinstance(cached, dict):
        return cached

    gs = _graph_settings()
    lists_url = f"https://graph.microsoft.com/v1.0/sites/{gs['site_id']}/lists"
    columns = _graph_get_pages(f"{lists_url}/{gs['list_id_assenze']}/columns")
    target = {str(c.get("name") or ""): str((c.get("lookup") or {}).get("listId") or "") for c in columns}

    maps: dict[str, dict[str, int]] = {"capi_email": {}, "dip_username": {}, "dip_nome": {}}
    capi_list = target.get(_SP_CAPO_LOOKUP_COLUMN)
    if capi_list:
        capi = _graph_get_pages(
            f"{lists_url}/{capi_list}/items?$expand=fields($select={_SP_CAPO_EMAIL_FIELD})&$top=999"
        )
        maps["capi_email"] = _index_unique_sp_items(
            capi, lambda f: str(f.get(_SP_CAPO_EMAIL_FIELD) or "").strip().lower()
        )
    nomi_list = target.get(_SP_NOME_LOOKUP_COLUMN)
    if nomi_list:
        dipendenti = _graph_get_pages(
            f"{lists_url}/{nomi_list}/items?$expand=fields($select=Title,{_SP_DIPENDENTE_USERNAME_FIELD})&$top=999"
        )
        maps["dip_username"] = _index_unique_sp_items(
            dipendenti, lambda f: str(f.get(_SP_DIPENDENTE_USERNAME_FIELD) or "").strip().lower()
        )
        maps["dip_nome"] = _index_unique_sp_items(dipendenti, lambda f: _name_tokens_key(f.get("Title")))

    cache.set(_SP_LOOKUP_MAPS_CACHE_KEY, maps, timeout=_SP_LOOKUP_MAPS_TTL)
    return maps


def _capo_email_for_row(row: dict) -> str:
    """Email del capo che approva la richiesta, con la stessa regola del form (area aziendale)."""
    capi = _load_capi_options()
    dt_start = row.get("data_inizio")
    request_day = dt_start.date() if isinstance(dt_start, datetime) else timezone.localdate()
    option = ""
    try:
        option, _escalated = _effective_capo_option(
            name=str(row.get("copia_nome") or ""),
            email=str(row.get("email_esterna") or ""),
            username=str(row.get("aliasusername") or ""),
            legacy_user_id=_as_int(row.get("utente_id")),
            capi=capi,
            request_day=request_day,
        )
    except Exception:
        logger.warning("[assenze:sp_push] assenza %s: capo non risolto", row.get("id"), exc_info=True)
    if "@" not in str(option or ""):
        # Il vecchio lookup salvato sulla riga puo' puntare al caporeparto storico: non lo si usa.
        option = _resolve_capo_option_value_from_ids(
            local_id=_as_int(row.get("capo_reparto_id")), lookup_id=None, capi=capi
        )
    option = str(option or "").strip().lower()
    return option if "@" in option else ""


def _sp_lookup_ids_for_row(row: dict, maps: dict) -> tuple[int | None, int | None]:
    """(id DIPENDENTI, id Caporeparto) per la richiesta."""
    dip_username = maps.get("dip_username") or {}
    email = str(row.get("email_esterna") or "").strip().lower()
    candidates = [
        str(row.get("aliasusername") or "").strip().lower(),
        email,
        email.split("@", 1)[0] if "@" in email else "",
    ]
    nome_id = next((dip_username[c] for c in candidates if c and c in dip_username), None)
    if nome_id is None:
        name_key = _name_tokens_key(row.get("copia_nome"))
        nome_id = (maps.get("dip_nome") or {}).get(name_key) if name_key else None

    capo_email = _capo_email_for_row(row)
    capo_id = (maps.get("capi_email") or {}).get(capo_email) if capo_email else None
    return nome_id, capo_id


def _fill_sp_lookups(item_id: int, row: dict) -> list[str]:
    """Compila persona e capo SharePoint della richiesta prima dell'invio.

    Aggiorna ``row`` e la tabella locale; ritorna i campi rimasti senza
    corrispondenza ("nome", "capo"), che il Run-log conta.
    """
    maps = _sp_lookup_maps()
    nome_id, capo_id = _sp_lookup_ids_for_row(row, maps)
    updates: dict = {}
    if nome_id is not None and nome_id != _as_int(row.get("nome_lookup_id")):
        updates["nome_lookup_id"] = nome_id
    if capo_id is not None and capo_id != _as_int(row.get("capo_reparto_lookup_id")):
        updates["capo_reparto_lookup_id"] = capo_id
    if updates:
        row.update(updates)
        _update_assenza(item_id, updates)

    missing = []
    if _as_int(row.get("nome_lookup_id")) is None:
        missing.append("nome")
    if capo_id is None:
        missing.append("capo")
    if missing:
        logger.warning("[assenze:sp_push] assenza %s: nessuna corrispondenza SharePoint per %s", item_id, ", ".join(missing))
    return missing


def _sp_fields_from_row(row: dict) -> dict:
    tipo = _tipo_for_graph(row.get("tipo_assenza"), row.get("motivazione_richiesta"))
    consenso = _norm_consenso(row.get("consenso"))
    fields = {
        "CopiaNome": str(row.get("copia_nome") or ""),
        "emailesterna": str(row.get("email_esterna") or ""),
        "Tipoassenza": tipo,
        "Motivazionerichiesta": _strip_tipo_metadata_from_motivazione(row.get("motivazione_richiesta")),
        "Salta_x0020_approvazione": bool(_as_bool(row.get("salta_approvazione"))),
        "Consenso": consenso,
    }
    nome_lookup = _as_int(row.get("nome_lookup_id"))
    capo_lookup = _as_int(row.get("capo_reparto_lookup_id"))
    if nome_lookup is not None:
        fields["NomeLookupId"] = nome_lookup
    if capo_lookup is not None:
        fields["C_x002e_RepartoLookupId"] = capo_lookup
    dt_start = _to_isoz(row.get("data_inizio"))
    dt_end = _to_isoz(row.get("data_fine"))
    if dt_start:
        fields["Data_x0020_inizio"] = dt_start
    if dt_end:
        fields["Datafine"] = dt_end
    return fields


def _sync_one_to_sharepoint(item_id: int, force_update: bool = True) -> dict:
    row = _get_assenza(item_id)
    if not row:
        return {"ok": False, "error": "Record non trovato"}
    if not _graph_configured():
        return {"ok": False, "error": "SharePoint non configurato"}

    sp_id = str(row.get("sharepoint_item_id") or "").strip()
    # Persona e capo ricalcolati a ogni invio; se Graph non risponde l'eccezione
    # risale e la richiesta resta in coda.
    lookup_missing = _fill_sp_lookups(item_id, row)
    fields = _sp_fields_from_row(row)

    if sp_id and force_update:
        ok, payload = _graph_update(sp_id, fields)
        if not ok:
            return {"ok": False, "error": str(payload)}
        _update_assenza(item_id, {"modified_datetime": timezone.now()})
        return {"ok": True, "action": "update", "sharepoint_item_id": sp_id, "lookup_missing": lookup_missing}

    ok, payload = _graph_create(fields)
    if not ok:
        return {"ok": False, "error": str(payload)}
    created_sp_id = str((payload or {}).get("id") or "").strip()
    if not created_sp_id:
        return {"ok": False, "error": "Risposta SharePoint senza item_id"}
    _update_assenza(item_id, {"sharepoint_item_id": created_sp_id, "modified_datetime": timezone.now()})
    # Creata dal portale: la gestisce il portale, il flusso SharePoint la ignora.
    _record_sp_origin(item_id, created_sp_id, creata_su_sharepoint=False, overwrite=True)
    return {"ok": True, "action": "create", "sharepoint_item_id": created_sp_id, "lookup_missing": lookup_missing}


def _sync_push(limit_rows: int = 30, include_updates: bool = False) -> dict:
    if not _table_exists("assenze"):
        return {"ok": False, "error": "Tabella assenze non disponibile"}
    if not _graph_configured():
        return {"ok": False, "error": "SharePoint non configurato"}
    # Stesso lock della coda: due invii paralleli creerebbero l'elemento due volte.
    if not cache.add(_SP_PUSH_LOCK_KEY, "1", timeout=_SP_PUSH_LOCK_TTL):
        return {"ok": False, "error": "Invio a SharePoint gia' in corso, riprova tra poco"}
    try:
        _set_automation_queue_skip(True)
        return _sync_push_locked(limit_rows=limit_rows, include_updates=include_updates)
    finally:
        _set_automation_queue_skip(False)
        cache.delete(_SP_PUSH_LOCK_KEY)


def _sync_push_locked(limit_rows: int, include_updates: bool) -> dict:

    limit_rows = max(1, min(int(limit_rows or 30), 300))
    where_sql = "1=1" if include_updates else f"{_blank_expr('sharepoint_item_id')} IS NULL"

    base_sql = f"""
        SELECT
            id,
            sharepoint_item_id,
            nome_lookup_id,
            capo_reparto_lookup_id,
            copia_nome,
            email_esterna,
            tipo_assenza,
            data_inizio,
            data_fine,
            motivazione_richiesta,
            salta_approvazione,
            consenso
        FROM assenze
        WHERE {where_sql}
    """
    sql = _select_limited(base_sql, "ORDER BY COALESCE(modified_datetime, created_datetime) ASC, id ASC", limit_rows)
    rows = _fetch_all_dict(sql)

    inserted = 0
    updated = 0
    failed = 0
    details: list[dict] = []

    for row in rows:
        local_id = int(row["id"])
        try:
            result = _sync_one_to_sharepoint(local_id, force_update=include_updates)
            if not result.get("ok"):
                raise RuntimeError(str(result.get("error") or "sync fallita"))
            if result.get("action") == "create":
                inserted += 1
            else:
                updated += 1
            details.append({"local_id": local_id, "sharepoint_item_id": result.get("sharepoint_item_id"), "action": result.get("action")})
        except Exception as exc:
            failed += 1
            details.append({"local_id": local_id, "error": str(exc)})
            logger.exception("[assenze:sync_push] errore local_id=%s", local_id)

    return {
        "ok": failed == 0,
        "mode": "db_to_sharepoint_push",
        "totals": {"inserted": inserted, "updated": updated, "failed": failed},
        "details": details[:30],
    }

def _sp_item_to_local(item: dict) -> tuple[str, dict]:
    fields = item.get("fields") or {}
    sp_id = str(item.get("id") or "").strip()
    if not sp_id:
        raise ValueError("SharePoint item senza id")

    consenso = _norm_consenso(fields.get("Consenso"))
    # SharePoint puo restituire un campo custom "Consenso" gia aggiornato mentre
    # il system field "_ModerationStatus" resta ancora a 2 ("In attesa").
    # In quel caso il valore esplicito scelto dal CAR deve vincere, altrimenti
    # il pull successivo rimette la riga tra le richieste pendenti.
    mod_status = _as_int(fields.get("_ModerationStatus"))
    if mod_status in {0, 1, 3, 4}:
        consenso = _MOD_TO_CONSENSO.get(str(mod_status), consenso)
    elif mod_status == 2 and consenso != "In attesa":
        mod_status = _CONSENSO_TO_MOD.get(consenso, 2)
    elif mod_status is None:
        mod_status = _CONSENSO_TO_MOD.get(consenso, 2)

    raw_tipo = fields.get("Tipoassenza")
    data = {
        "sharepoint_item_id": sp_id,
        "nome_lookup_id": _as_int(fields.get("NomeLookupId")),
        "copia_nome": str(fields.get("CopiaNome") or "").strip(),
        "email_esterna": str(fields.get("emailesterna") or "").strip().lower(),
        "tipo_assenza": _tipo_for_storage(raw_tipo),
        "capo_reparto_lookup_id": _as_int(fields.get("C_x002e_RepartoLookupId")),
        "data_inizio": _parse_sp_dt(fields.get("Data_x0020_inizio")),
        "data_fine": _parse_sp_dt(fields.get("Datafine")),
        "motivazione_richiesta": _motivazione_for_storage(raw_tipo, fields.get("Motivazionerichiesta")),
        "salta_approvazione": bool(_as_bool(fields.get("Salta_x0020_approvazione"))),
        "consenso": consenso,
        "moderation_status": mod_status,
        "created_datetime": _parse_sp_dt(item.get("createdDateTime")),
        "modified_datetime": _parse_sp_dt(item.get("lastModifiedDateTime")),
    }
    return sp_id, data


def _effective_status(consenso, moderation_status, *, default_pending: bool = False) -> tuple[int | None, str]:
    parsed, label = _status_from_moderation(moderation_status, default_pending=default_pending)
    if label != "N/D":
        return parsed, label
    consenso_norm = _norm_consenso(consenso)
    return _CONSENSO_TO_MOD.get(consenso_norm, 2), consenso_norm


def _diagnose_sharepoint_sync_item(item_id: int) -> dict | None:
    current = _get_assenza(item_id)
    if not current:
        return None

    local_status, local_label = _effective_status(current.get("consenso"), current.get("moderation_status"), default_pending=True)
    sp_id = str(current.get("sharepoint_item_id") or "").strip()
    row = {
        "id": int(item_id),
        "sharepoint_item_id": sp_id,
        "dipendente": str(current.get("copia_nome") or "N/D"),
        "inizio_label": _dt_label(current.get("data_inizio")),
        "fine_label": _dt_label(current.get("data_fine")),
        "local_status_label": local_label,
        "sp_consenso_field": "-",
        "sp_moderation_label": "-",
        "sp_resolved_status": "-",
        "level": "warn",
        "diagnostic": "",
    }

    if not sp_id:
        row["diagnostic"] = "Record solo locale: sharepoint_item_id assente."
        return row

    try:
        item = _graph_get_item(sp_id)
    except Exception as exc:
        row["level"] = "error"
        row["diagnostic"] = f"Errore Graph: {exc}"
        return row

    if not item:
        row["level"] = "error"
        row["diagnostic"] = "Item SharePoint non trovato."
        return row

    fields = item.get("fields") or {}
    sp_consenso_field = _norm_consenso(fields.get("Consenso"))
    sp_moderation_status = _as_int(fields.get("_ModerationStatus"))
    _, sp_payload = _sp_item_to_local(item)
    sp_resolved_status, sp_resolved_label = _effective_status(
        sp_payload.get("consenso"),
        sp_payload.get("moderation_status"),
        default_pending=True,
    )

    row["sp_consenso_field"] = sp_consenso_field
    row["sp_moderation_label"] = (
        _MOD_TO_CONSENSO.get(str(sp_moderation_status), "-") if sp_moderation_status is not None else "-"
    )
    row["sp_resolved_status"] = sp_resolved_label

    if sp_moderation_status == 2 and sp_consenso_field != "In attesa":
        row["level"] = "warn"
        row["diagnostic"] = (
            f'SharePoint incoerente: "_ModerationStatus" e In attesa ma "Consenso" e {sp_consenso_field}.'
        )
    elif sp_resolved_status != local_status or sp_resolved_label != local_label:
        row["level"] = "warn"
        row["diagnostic"] = "Locale e SharePoint non sono allineati."
    else:
        row["level"] = "ok"
        row["diagnostic"] = "Allineato."

    return row


def _build_sharepoint_sync_diagnostics(item_ids: list[int], limit: int = 12) -> dict:
    result = {
        "enabled": _graph_configured(),
        "reason": "",
        "rows": [],
        "checked_count": 0,
        "ok_count": 0,
        "warn_count": 0,
        "error_count": 0,
    }
    if not result["enabled"]:
        result["reason"] = "not_configured"
        return result

    unique_ids: list[int] = []
    seen: set[int] = set()
    for raw_id in item_ids:
        parsed = _as_int(raw_id)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        unique_ids.append(parsed)
        if len(unique_ids) >= max(1, int(limit)):
            break

    for item_id in unique_ids:
        row = _diagnose_sharepoint_sync_item(item_id)
        if not row:
            continue
        result["rows"].append(row)
        result["checked_count"] += 1
        if row["level"] == "ok":
            result["ok_count"] += 1
        elif row["level"] == "error":
            result["error_count"] += 1
        else:
            result["warn_count"] += 1

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Sincronizzazione SharePoint in background
#
# Nessuna chiamata Graph durante il caricamento delle pagine. Le modifiche locali
# entrano nella coda AssenzaSharePointOutbox; il job django-q
# "assenze_sharepoint_sync" (ogni 5 minuti) prima svuota la coda verso
# SharePoint, poi legge solo gli elementi cambiati (delta query). Un record con
# modifiche ancora in coda non viene sovrascritto dalla lettura: vince la
# modifica locale non ancora inviata.
# ─────────────────────────────────────────────────────────────────────────────


# ─── Chi gestisce la richiesta ───────────────────────────────────────────────
# Durante la convivenza ogni richiesta la gestisce il sistema in cui e' nata:
# quelle create su SharePoint le approva il flusso Power Automate (sul portale
# restano in sola lettura); quelle create sul portale le approva il portale (il
# flusso le ignora: autore "App di SharePoint"). Le scritture della
# sincronizzazione non fanno partire le automazioni del portale, altrimenti le
# mail partirebbero due volte.

_AUTOMATION_SKIP_SESSION_KEY = "hub_skip_automation"
_SP_APP_AUTHOR_NAMES = {"sharepoint app", "app di sharepoint"}
_SP_MANAGED_ERROR = (
    "Richiesta nata su SharePoint: approvazione, modifica ed eliminazione si fanno "
    "dall'app SharePoint. Sul portale è in sola lettura."
)
_SQLSERVER_IN_CHUNK = 1000  # SQL Server accetta al massimo 2100 parametri per query


def _set_automation_queue_skip(enabled: bool) -> None:
    """Accende o spegne il flag di sessione letto dai trigger ``trg_assenze_automation_*``.

    Solo SQL Server (su SQLite non ci sono trigger). Va sempre spento in un
    ``finally``: la connessione del worker django-q e' riusata dai task successivi.
    """
    if _db_vendor() != "microsoft":
        return
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "EXEC sys.sp_set_session_context @key = %s, @value = %s",
            [_AUTOMATION_SKIP_SESSION_KEY, 1 if enabled else None],
        )


def _sp_item_created_by_portal(item: dict) -> bool:
    """True se l'elemento SharePoint l'ha creato un'app (il portale), non una persona."""
    created_by = item.get("createdBy") or {}
    if created_by.get("application"):
        return True
    user_name = str((created_by.get("user") or {}).get("displayName") or "").strip().lower()
    return user_name in _SP_APP_AUTHOR_NAMES


def _record_sp_origin(assenza_id, sharepoint_item_id, *, creata_su_sharepoint: bool, overwrite: bool = False) -> None:
    """Registra dove e' nata una richiesta. Senza ``overwrite`` non corregge un'origine gia' nota."""
    from .models import AssenzaOrigineSharePoint as Origine

    local_id = _as_int(assenza_id)
    if local_id is None:
        return
    values = {
        "sharepoint_item_id": str(sharepoint_item_id or "")[:64],
        "creata_su_sharepoint": bool(creata_su_sharepoint),
    }
    if overwrite:
        Origine.objects.update_or_create(assenza_id=local_id, defaults=values)
    else:
        Origine.objects.get_or_create(assenza_id=local_id, defaults=values)


def _sharepoint_managed_ids(item_ids) -> set[int]:
    """Id delle richieste nate su SharePoint, in sola lettura sul portale."""
    from .models import AssenzaOrigineSharePoint as Origine

    ids = sorted({i for i in (_as_int(x) for x in item_ids) if i is not None})
    if not ids or not _graph_configured():
        return set()
    managed: set[int] = set()
    for start in range(0, len(ids), _SQLSERVER_IN_CHUNK):
        chunk = ids[start:start + _SQLSERVER_IN_CHUNK]
        managed.update(
            Origine.objects.filter(assenza_id__in=chunk, creata_su_sharepoint=True).values_list("assenza_id", flat=True)
        )
    return managed


def _mark_sharepoint_managed(rows: list[dict]) -> None:
    """Aggiunge ``gestita_sp`` a ogni riga: i template nascondono le azioni."""
    managed = _sharepoint_managed_ids(r.get("id") for r in rows)
    for row in rows:
        row["gestita_sp"] = _as_int(row.get("id")) in managed


def _sharepoint_managed_error(item_id):
    """Risposta 409 se la richiesta e' gestita su SharePoint, altrimenti None."""
    if _as_int(item_id) in _sharepoint_managed_ids([item_id]):
        return _json_error(_SP_MANAGED_ERROR, status=409)
    return None


def _sp_kick_push() -> None:
    """Chiede al cluster un invio immediato, a transazione confermata.

    Best-effort: se l'accodamento fallisce la coda la svuota il giro periodico.
    """

    def _enqueue():
        try:
            from django_q.tasks import async_task

            async_task("assenze.tasks.run_assenze_sharepoint_push")
        except Exception:
            logger.warning("[assenze:sp_push] invio immediato non accodato, provvede il job periodico", exc_info=True)

    transaction.on_commit(_enqueue)


def _sp_enqueue_upsert(item_id) -> dict:
    """Mette in coda l'invio a SharePoint di un record creato o modificato."""
    from django.db import IntegrityError
    from django.db.models import F

    from .models import AssenzaSharePointOutbox as Outbox

    local_id = _as_int(item_id)
    if local_id is None or not _graph_configured():
        return {"ok": False, "reason": "not_configured"}

    bump = {"azione": Outbox.AZIONE_UPSERT, "versione": F("versione") + 1, "updated_at": timezone.now()}
    if not Outbox.objects.filter(assenza_id=local_id).update(**bump):
        try:
            with transaction.atomic():
                Outbox.objects.create(assenza_id=local_id, azione=Outbox.AZIONE_UPSERT)
        except IntegrityError:
            # Accodato in parallelo da un'altra richiesta: basta alzare la versione.
            Outbox.objects.filter(assenza_id=local_id).update(**bump)
    _sp_kick_push()
    return {"ok": True, "queued": True}


def _sp_enqueue_delete(item_id, sharepoint_item_id) -> dict:
    """Mette in coda l'eliminazione su SharePoint di un record cancellato in locale.

    Va chiamata PRIMA di cancellare il record: se un invio di creazione e' in
    corso, la riga di coda raccoglie l'id SharePoint appena creato e il giro
    successivo lo elimina.
    """
    from django.db.models import F

    from .models import AssenzaSharePointOutbox as Outbox

    local_id = _as_int(item_id)
    sp_id = str(sharepoint_item_id or "").strip()
    if local_id is None or not _graph_configured():
        return {"ok": False, "reason": "not_configured"}

    updated = Outbox.objects.filter(assenza_id=local_id).update(
        azione=Outbox.AZIONE_DELETE,
        sharepoint_item_id=sp_id,
        versione=F("versione") + 1,
        updated_at=timezone.now(),
    )
    if not updated:
        if not sp_id:
            # Mai arrivato su SharePoint e nessun invio in coda: nulla da fare.
            return {"ok": True, "queued": False}
        Outbox.objects.create(assenza_id=local_id, azione=Outbox.AZIONE_DELETE, sharepoint_item_id=sp_id)
    _sp_kick_push()
    return {"ok": True, "queued": True}


def _sp_push_outbox(limit: int = _SP_PUSH_BATCH) -> dict:
    """Svuota la coda verso SharePoint. Un solo invio alla volta (lock in cache)."""
    from django.db.models import F

    from .models import AssenzaSharePointOutbox as Outbox

    if not _graph_configured():
        return {"ok": False, "skipped": True, "reason": "not_configured"}
    if not cache.add(_SP_PUSH_LOCK_KEY, "1", timeout=_SP_PUSH_LOCK_TTL):
        return {"ok": True, "skipped": True, "reason": "busy"}

    totals = {"created": 0, "updated": 0, "deleted": 0, "dropped": 0, "failed": 0, "senza_nome": 0, "senza_capo": 0}
    try:
        _set_automation_queue_skip(True)
        entries = list(Outbox.objects.order_by("tentativi", "updated_at")[: max(1, int(limit))])
        for entry in entries:
            try:
                if entry.azione == Outbox.AZIONE_DELETE:
                    if entry.sharepoint_item_id:
                        ok, err = _graph_delete(entry.sharepoint_item_id)
                        if not ok:
                            raise RuntimeError(str(err)[:500])
                        totals["deleted"] += 1
                    else:
                        totals["dropped"] += 1
                elif _get_assenza(entry.assenza_id) is None:
                    # Record cancellato senza passare dalla coda: niente da inviare.
                    totals["dropped"] += 1
                else:
                    result = _sync_one_to_sharepoint(entry.assenza_id, force_update=True)
                    if not result.get("ok"):
                        raise RuntimeError(str(result.get("error") or "invio fallito")[:500])
                    for campo in result.get("lookup_missing") or []:
                        if f"senza_{campo}" in totals:
                            totals[f"senza_{campo}"] += 1
                    if result.get("action") == "create":
                        totals["created"] += 1
                        # Se nel frattempo e' stata chiesta l'eliminazione, le serve l'id appena nato.
                        Outbox.objects.filter(
                            pk=entry.pk, azione=Outbox.AZIONE_DELETE, sharepoint_item_id=""
                        ).update(sharepoint_item_id=str(result.get("sharepoint_item_id") or ""))
                    else:
                        totals["updated"] += 1
                # Solo se nessuno ha modificato il record durante l'invio.
                Outbox.objects.filter(pk=entry.pk, versione=entry.versione).delete()
            except Exception as exc:
                totals["failed"] += 1
                Outbox.objects.filter(pk=entry.pk).update(
                    tentativi=F("tentativi") + 1,
                    ultimo_errore=str(exc)[:2000],
                    updated_at=timezone.now(),
                )
                logger.warning("[assenze:sp_push] assenza %s: invio fallito: %s", entry.assenza_id, exc)
    finally:
        _set_automation_queue_skip(False)
        cache.delete(_SP_PUSH_LOCK_KEY)

    return {
        "ok": totals["failed"] == 0,
        "mode": "outbox_push",
        "totals": totals,
        "pending": Outbox.objects.count(),
    }


def _find_assenza_id_by_sp_id(sp_id: str) -> int | None:
    rows = _fetch_all_dict("SELECT id FROM assenze WHERE sharepoint_item_id = %s", [str(sp_id)])
    return _as_int(rows[0].get("id")) if rows else None


def _sync_name_key(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).upper()


def _find_duplicate_assenza_id(payload: dict) -> int | None:
    """Richiesta gia' presente sul portale con la stessa chiave dell'import Excel.

    Chiave: (nominativo, giorno di inizio, giorno di fine). Serve a scartare gli
    elementi SharePoint non ancora collegati che il portale ha gia' registrato
    (import da file, o creati dal portale con collegamento mai salvato).
    """
    dt_start = payload.get("data_inizio")
    dt_end = payload.get("data_fine")
    name_key = _sync_name_key(payload.get("copia_nome"))
    if not isinstance(dt_start, datetime) or not isinstance(dt_end, datetime) or not name_key:
        return None
    day_start = dt_start.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = _fetch_all_dict(
        "SELECT id, copia_nome, data_fine FROM assenze WHERE data_inizio >= %s AND data_inizio < %s",
        [day_start, day_start + timedelta(days=1)],
    )
    for row in sorted(rows, key=lambda r: _as_int(r.get("id")) or 0):
        row_end = row.get("data_fine")
        if isinstance(row_end, str):
            row_end = _parse_input_dt(row_end)
        if isinstance(row_end, datetime) and timezone.is_aware(row_end):
            row_end = timezone.localtime(row_end).replace(tzinfo=None)
        if (
            isinstance(row_end, datetime)
            and row_end.date() == dt_end.date()
            and _sync_name_key(row.get("copia_nome")) == name_key
        ):
            return _as_int(row.get("id"))
    return None


def _apply_sp_item_to_local(item: dict, row_id: int | None, *, assenze_cols, has_dip: bool, has_capi: bool) -> str:
    """Scrive un elemento SharePoint nella tabella locale. Ritorna 'inserted'/'updated'/'skipped'."""
    sp_id, payload = _sp_item_to_local(item)
    data = _prepare_row_data(payload)
    outcome = "updated"

    with connections["default"].cursor() as cursor:
        if row_id is None:
            cols = list(data.keys())
            row_id = _insert_row_and_return_id(cursor, "assenze", cols, [data[c] for c in cols])
            if row_id is None:
                row_id = _find_inserted_assenza_id(data)
            outcome = "inserted"
        else:
            updates = dict(data)
            updates.pop("sharepoint_item_id", None)
            if updates:
                sets = ", ".join(f"{_quote_identifier(k)} = %s" for k in updates.keys())
                cursor.execute(f"UPDATE assenze SET {sets} WHERE id = %s", [*list(updates.values()), row_id])

        if row_id is None:
            return "skipped"

        _record_sp_origin(row_id, sp_id, creata_su_sharepoint=not _sp_item_created_by_portal(item))

        if has_dip and "dipendente_id" in assenze_cols and "nome_lookup_id" in assenze_cols:
            nome_lookup = _as_int(payload.get("nome_lookup_id"))
            if nome_lookup is not None:
                cursor.execute("SELECT id FROM dipendenti WHERE sharepoint_item_id = %s ORDER BY id DESC", [str(nome_lookup)])
                drow = cursor.fetchone()
                if drow and drow[0] is not None:
                    cursor.execute("UPDATE assenze SET dipendente_id = %s WHERE id = %s", [int(drow[0]), row_id])

        if has_capi and "capo_reparto_id" in assenze_cols and "capo_reparto_lookup_id" in assenze_cols:
            capo_lookup = _as_int(payload.get("capo_reparto_lookup_id"))
            if capo_lookup is not None:
                cursor.execute("SELECT id FROM capi_reparto WHERE sharepoint_item_id = %s ORDER BY id DESC", [str(capo_lookup)])
                crow = cursor.fetchone()
                if crow and crow[0] is not None:
                    cursor.execute("UPDATE assenze SET capo_reparto_id = %s WHERE id = %s", [int(crow[0]), row_id])
    return outcome


def _sync_pull_from_sharepoint() -> dict:
    """Applica al DB locale le modifiche della lista SharePoint dall'ultimo giro."""
    from .models import AssenzaSharePointOutbox as Outbox

    if not _table_exists("assenze"):
        return {"ok": False, "error": "Tabella assenze non disponibile"}
    if not _graph_configured():
        return {"ok": False, "error": "SharePoint non configurato"}

    delta_link = cache.get(_SP_DELTA_LINK_KEY) or None
    items, new_link = _graph_delta_changes(delta_link)

    # Lo stesso elemento puo' comparire piu' volte nel feed: vale l'ultima occorrenza.
    latest: dict[str, dict] = {}
    for item in items:
        sp_id = str(item.get("id") or "").strip()
        if sp_id:
            latest[sp_id] = item

    pending_ids = set(Outbox.objects.values_list("assenza_id", flat=True))
    assenze_cols = legacy_table_columns("assenze")
    has_dip = _table_exists("dipendenti")
    has_capi = _table_exists("capi_reparto")
    totals = {"inserted": 0, "updated": 0, "deleted": 0, "skipped_pending": 0, "discarded": 0, "failed": 0}

    # Le scritture di questo giro non devono far partire le automazioni del portale.
    _set_automation_queue_skip(True)
    try:
        for sp_id, item in latest.items():
            try:
                row_id = _find_assenza_id_by_sp_id(sp_id)
                if row_id is not None and row_id in pending_ids:
                    totals["skipped_pending"] += 1
                    continue
                if item.get("deleted"):
                    if row_id is not None and _delete_assenza(row_id):
                        totals["deleted"] += 1
                        logger.info("[assenze:sp_pull] assenza %s eliminata: rimossa su SharePoint (item %s)", row_id, sp_id)
                    continue
                if not item.get("fields"):
                    item = _graph_get_item(sp_id)
                    if not item:
                        continue
                if row_id is None:
                    # Elemento SharePoint mai collegato: se il portale ha gia' la stessa
                    # richiesta lo si scarta, senza unirlo ne' duplicarlo.
                    _sp_id, payload = _sp_item_to_local(item)
                    duplicate_id = _find_duplicate_assenza_id(payload)
                    if duplicate_id is not None:
                        totals["discarded"] += 1
                        logger.info(
                            "[assenze:sp_pull] item SharePoint %s scartato: richiesta gia' presente (assenza %s)",
                            sp_id, duplicate_id,
                        )
                        continue
                with transaction.atomic():
                    outcome = _apply_sp_item_to_local(
                        item, row_id, assenze_cols=assenze_cols, has_dip=has_dip, has_capi=has_capi
                    )
                if outcome in totals:
                    totals[outcome] += 1
            except Exception:
                totals["failed"] += 1
                logger.exception("[assenze:sp_pull] item SharePoint %s non applicato", sp_id)
    finally:
        _set_automation_queue_skip(False)

    # Con errori il token non avanza: il giro dopo rilegge le stesse modifiche.
    if new_link and totals["failed"] == 0:
        cache.set(_SP_DELTA_LINK_KEY, new_link, timeout=None)

    return {
        "ok": totals["failed"] == 0,
        "mode": "sharepoint_to_db_delta",
        "full": not delta_link,
        "totals": totals,
    }


def _pull_interval_seconds() -> int:
    raw = getattr(settings, "ASSENZE_SP_PULL_INTERVAL_SECONDS", 300)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 300
    return max(60, value)


def _maybe_pull(force: bool = False) -> dict:
    if not _graph_configured():
        return {"ok": False, "skipped": True, "reason": "not_configured"}

    now_ts = int(time.time())
    last_ts = int(cache.get(_SYNC_PULL_LAST_TS_KEY) or 0)
    interval = _pull_interval_seconds()
    if not force and last_ts and (now_ts - last_ts) < interval:
        return {"ok": True, "skipped": True, "reason": "throttled", "next_in": interval - (now_ts - last_ts)}

    if not cache.add(_SYNC_PULL_LOCK_KEY, "1", timeout=_SYNC_PULL_LOCK_TTL):
        return {"ok": True, "skipped": True, "reason": "busy"}

    try:
        result = _sync_pull_from_sharepoint()
        if result.get("ok"):
            cache.set(_SYNC_PULL_LAST_TS_KEY, now_ts, timeout=None)
        return result
    except Exception as exc:
        logger.exception("_maybe_pull: errore durante sync pull da SharePoint")
        return {"ok": False, "error": str(exc), "mode": "sharepoint_to_db_delta"}
    finally:
        cache.delete(_SYNC_PULL_LOCK_KEY)


def _sp_refresh_motivazioni() -> None:
    """Aggiorna in cache le motivazioni della lista (lette dal job, non dalle pagine)."""
    values = _graph_get_motivazioni()
    if values:
        cache.set(_SP_MOTIVAZIONI_CACHE_KEY, values, timeout=_SP_MOTIVAZIONI_CACHE_TTL)


def _motivazioni_options() -> list[str]:
    cached = cache.get(_SP_MOTIVAZIONI_CACHE_KEY)
    if isinstance(cached, list) and cached:
        return cached
    return _load_motivazioni_local()


def _ensure_colors_table() -> None:
    try:
        with connections["default"].cursor() as cursor:
            if _db_vendor() == "sqlite":
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ui_assenze_colors (
                        color_key TEXT PRIMARY KEY,
                        color_value TEXT NOT NULL,
                        updated_at TEXT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ui_assenze_colors_user (
                        user_key TEXT NOT NULL,
                        color_key TEXT NOT NULL,
                        color_value TEXT NOT NULL,
                        updated_at TEXT NULL,
                        PRIMARY KEY (user_key, color_key)
                    )
                    """
                )
            else:
                cursor.execute(
                    """
                    IF OBJECT_ID('ui_assenze_colors', 'U') IS NULL
                    CREATE TABLE ui_assenze_colors (
                        color_key NVARCHAR(64) NOT NULL PRIMARY KEY,
                        color_value NVARCHAR(7) NOT NULL,
                        updated_at DATETIME2 NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    IF OBJECT_ID('ui_assenze_colors_user', 'U') IS NULL
                    CREATE TABLE ui_assenze_colors_user (
                        user_key NVARCHAR(128) NOT NULL,
                        color_key NVARCHAR(64) NOT NULL,
                        color_value NVARCHAR(7) NOT NULL,
                        updated_at DATETIME2 NULL,
                        CONSTRAINT PK_ui_assenze_colors_user PRIMARY KEY (user_key, color_key)
                    )
                    """
                )
    except Exception:
        return


def _color_cache_ttl() -> int:
    ttl = int(getattr(settings, "ASSENZE_CALENDAR_COLORS_CACHE_TTL", 300) or 300)
    return max(60, ttl)


def _user_color_key(request) -> str:
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return "anon"
    user_id = getattr(request.user, "id", None)
    if user_id is not None:
        return f"id:{user_id}"
    username = str(request.user.get_username() or "").strip().lower()
    return f"user:{username}" if username else "anon"


def _load_global_color_overrides() -> dict[str, str]:
    cached = cache.get(_COLOR_CACHE_KEY_GLOBAL)
    if isinstance(cached, dict):
        return {k: v for k, v in cached.items() if k in _COLOR_KEYS and _COLOR_RE.match(str(v or ""))}

    _ensure_colors_table()
    overrides: dict[str, str] = {}
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT color_key, color_value FROM ui_assenze_colors")
            for key, value in cursor.fetchall():
                k = str(key or "").strip()
                v = str(value or "").strip()
                if k in _COLOR_KEYS and _COLOR_RE.match(v):
                    overrides[k] = v
    except Exception:
        pass

    cache.set(_COLOR_CACHE_KEY_GLOBAL, overrides, timeout=_color_cache_ttl())
    return overrides


def _load_user_color_overrides(user_key: str) -> dict[str, str]:
    cache_key = f"{_COLOR_CACHE_KEY_USER_PREFIX}{user_key}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return {k: v for k, v in cached.items() if k in _COLOR_KEYS and _COLOR_RE.match(str(v or ""))}

    _ensure_colors_table()
    overrides: dict[str, str] = {}
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute(
                "SELECT color_key, color_value FROM ui_assenze_colors_user WHERE user_key = %s",
                [user_key],
            )
            for key, value in cursor.fetchall():
                k = str(key or "").strip()
                v = str(value or "").strip()
                if k in _COLOR_KEYS and _COLOR_RE.match(v):
                    overrides[k] = v
    except Exception:
        pass

    cache.set(cache_key, overrides, timeout=_color_cache_ttl())
    return overrides


def _load_colors(user_key: str | None = None) -> dict[str, str]:
    colors = dict(_DEFAULT_COLORS)
    colors.update(_load_global_color_overrides())
    if user_key:
        colors.update(_load_user_color_overrides(user_key))
    return colors


def _save_colors(data: dict[str, str], user_key: str | None = None) -> dict[str, str]:
    _ensure_colors_table()
    clean: dict[str, str] = {}
    for key, value in data.items():
        k = str(key or "").strip()
        v = str(value or "").strip()
        if k in _COLOR_KEYS and _COLOR_RE.match(v):
            clean[k] = v

    with transaction.atomic():
        with connections["default"].cursor() as cursor:
            for key, value in clean.items():
                if _db_vendor() == "sqlite":
                    if user_key:
                        cursor.execute(
                            """
                            INSERT INTO ui_assenze_colors_user (user_key, color_key, color_value, updated_at)
                            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                            ON CONFLICT(user_key, color_key) DO UPDATE SET
                                color_value = excluded.color_value,
                                updated_at = CURRENT_TIMESTAMP
                            """,
                            [user_key, key, value],
                        )
                    else:
                        cursor.execute(
                            """
                            INSERT INTO ui_assenze_colors (color_key, color_value, updated_at)
                            VALUES (%s, %s, CURRENT_TIMESTAMP)
                            ON CONFLICT(color_key) DO UPDATE SET
                                color_value = excluded.color_value,
                                updated_at = CURRENT_TIMESTAMP
                            """,
                            [key, value],
                        )
                else:
                    if user_key:
                        cursor.execute(
                            """
                            MERGE ui_assenze_colors_user AS target
                            USING (SELECT %s AS user_key, %s AS color_key) AS src
                            ON target.user_key = src.user_key AND target.color_key = src.color_key
                            WHEN MATCHED THEN UPDATE SET
                                color_value = %s,
                                updated_at = SYSUTCDATETIME()
                            WHEN NOT MATCHED THEN
                                INSERT (user_key, color_key, color_value, updated_at)
                                VALUES (%s, %s, %s, SYSUTCDATETIME());
                            """,
                            [user_key, key, value, user_key, key, value],
                        )
                    else:
                        cursor.execute(
                            """
                            MERGE ui_assenze_colors AS target
                            USING (SELECT %s AS color_key) AS src
                            ON target.color_key = src.color_key
                            WHEN MATCHED THEN UPDATE SET
                                color_value = %s,
                                updated_at = SYSUTCDATETIME()
                            WHEN NOT MATCHED THEN
                                INSERT (color_key, color_value, updated_at)
                                VALUES (%s, %s, SYSUTCDATETIME());
                            """,
                            [key, value, key, value],
                        )

    if user_key:
        cache.delete(f"{_COLOR_CACHE_KEY_USER_PREFIX}{user_key}")
    else:
        cache.delete(_COLOR_CACHE_KEY_GLOBAL)
    return _load_colors(user_key=user_key)

def _event_color(tipo: str, consenso: str, colors: dict[str, str], moderation_status: int | None = None) -> str:
    if moderation_status is not None:
        stato = _MOD_TO_CONSENSO.get(str(moderation_status), _norm_consenso(consenso))
    else:
        stato = _norm_consenso(consenso)
    if stato == "Rifiutato":
        return colors.get("stato_rifiutato", _DEFAULT_COLORS["stato_rifiutato"])
    if stato in {"Bozza", "Programmato"}:
        return colors.get("stato_in_attesa", _DEFAULT_COLORS["stato_in_attesa"])
    tipo_key = {
        "Ferie": "tipo_ferie",
        "Permesso": "tipo_permesso",
        "Malattia": "tipo_malattia",
        "Flessibilità": "tipo_infortunio",
        "Certifica presenza": "tipo_certifica_presenza",
        "Altro": "tipo_altro",
    }.get(_norm_tipo(tipo), "stato_approvato")
    return colors.get(tipo_key, _DEFAULT_COLORS["stato_approvato"])


def _load_events(
    limit: int = 4000,
    start: datetime | None = None,
    end: datetime | None = None,
    colors: dict[str, str] | None = None,
    include_sensitive: bool = False,
) -> list[dict]:
    # SEC/GDPR: `motivazione` e `certificato_medico` (dato sanitario, categoria
    # speciale) sono inclusi negli eventi del calendario SOLO per chi gestisce a
    # livello aziendale (AMMINISTRAZIONE). Per i caporeparto/altri il calendario
    # resta visibile ma senza questi campi (default: esclusi).
    if not _table_exists("assenze"):
        return []

    # Il JOIN richiede sia la tabella di destinazione sia la colonna FK lato `assenze`:
    # in alcuni ambienti legacy (es. prod) `assenze.dipendente_id` puo' non esistere e
    # referenziarla manda in errore l'intera query (42S22). Vedi guard analogo nel pull.
    has_dip = _table_exists("dipendenti") and _has_assenze_column("dipendente_id")
    has_capi = _table_exists("capi_reparto") and _has_assenze_column("capo_reparto_id")
    joins = ""
    dip_expr = "a.copia_nome"
    capo_expr = "''"
    if has_dip:
        joins += " LEFT JOIN dipendenti d ON d.id = a.dipendente_id "
        dip_expr = "COALESCE(d.title, a.copia_nome)"
    if has_capi:
        joins += " LEFT JOIN capi_reparto cr ON cr.id = a.capo_reparto_id "
        capo_expr = "COALESCE(cr.title, '')"

    where_clauses = ["a.data_inizio IS NOT NULL", "a.data_fine IS NOT NULL"]
    params: list = []
    if start is not None:
        where_clauses.append("a.data_fine >= %s")
        params.append(start)
    if end is not None:
        where_clauses.append("a.data_inizio <= %s")
        params.append(end)

    _cert_col = ", a.certificato_medico" if _has_assenze_column("certificato_medico") else ""
    base_sql = f"""
        SELECT
            a.id,
            {dip_expr} AS dipendente,
            a.tipo_assenza,
            a.data_inizio,
            a.data_fine,
            a.consenso,
            a.moderation_status,
            a.motivazione_richiesta{_cert_col},
            {capo_expr} AS capo
        FROM assenze a
        {joins}
        WHERE {' AND '.join(where_clauses)}
    """
    sql = _select_limited(base_sql, "ORDER BY a.data_inizio DESC, a.id DESC", limit)
    rows = _fetch_all_dict(sql, params)
    resolved_colors = colors or _load_colors()

    events: list[dict] = []
    for row in rows:
        tipo = _tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta"))
        moderation_status = _as_int(row.get("moderation_status"))
        moderation_label = _moderation_label(moderation_status)
        consenso = moderation_label if moderation_label != "N/D" else _norm_consenso(row.get("consenso"))
        props = {
            "tipo": tipo,
            "consenso": consenso,
            "moderation_status": moderation_status,
            "capo": str(row.get("capo") or ""),
        }
        if include_sensitive:
            props["motivazione"] = _strip_tipo_metadata_from_motivazione(row.get("motivazione_richiesta"))
            props["certificato_medico"] = str(row.get("certificato_medico") or "")
        events.append(
            {
                "id": row.get("id"),
                "title": str(row.get("dipendente") or "N/D"),
                "start": _to_isoz(row.get("data_inizio")),
                "end": _to_isoz(row.get("data_fine")),
                "color": _event_color(tipo, consenso, resolved_colors, moderation_status=moderation_status),
                "extendedProps": props,
            }
        )
    managed = _sharepoint_managed_ids(e.get("id") for e in events)
    for event in events:
        event["extendedProps"]["gestita_sp"] = _as_int(event.get("id")) in managed
    return events


def _load_personal(name: str, email: str, limit: int = 20) -> list[dict]:
    if not _table_exists("assenze"):
        return []

    clauses = []
    params: list = []
    if name:
        clauses.append("UPPER(COALESCE(copia_nome,'')) = UPPER(%s)")
        params.append(name)
    if email:
        clauses.append("UPPER(COALESCE(email_esterna,'')) = UPPER(%s)")
        params.append(email)
    if not clauses:
        return []

    _note_col = ", note_gestione" if _has_assenze_column("note_gestione") else ""
    _cert_col = ", certificato_medico" if _has_assenze_column("certificato_medico") else ""
    _creata_col = ", created_datetime" if _has_assenze_column("created_datetime") else ""
    base_sql = f"""
        SELECT
            id,
            tipo_assenza,
            data_inizio,
            data_fine,
            consenso,
            motivazione_richiesta,
            moderation_status{_note_col}{_cert_col}{_creata_col}
        FROM assenze
        WHERE ({' OR '.join(clauses)})
    """
    sql = _select_limited(base_sql, "ORDER BY COALESCE(created_datetime, data_inizio) DESC, id DESC", limit)
    rows = _fetch_all_dict(sql, params)

    out = []
    for row in rows:
        moderation_status, moderation_label = _status_from_moderation(row.get("moderation_status"), default_pending=True)
        stato_value = moderation_label
        dt_inizio = row.get("data_inizio")
        dt_fine = row.get("data_fine")
        out.append(
            {
                "id": row.get("id"),
                "tipo": _tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta")),
                "tipo_raw": _tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta")),
                "consenso": stato_value,
                "stato": stato_value,
                "inizio_label": _dt_label(dt_inizio),
                "fine_label": _dt_label(dt_fine),
                "inizio": _dt_label(dt_inizio),
                "fine": _dt_label(dt_fine),
                "inizio_iso": _to_isoz(dt_inizio) or "",
                "fine_iso": _to_isoz(dt_fine) or "",
                "motivazione": _strip_tipo_metadata_from_motivazione(row.get("motivazione_richiesta")),
                "certificato_medico": str(row.get("certificato_medico") or ""),
                "note_gestione": str(row.get("note_gestione") or ""),
                "moderation_status": moderation_status,
                "moderation_label": moderation_label,
                "creata_label": _dt_label(row.get("created_datetime")),
            }
        )
    _mark_sharepoint_managed(out)
    return out


def _absence_status_bucket(value: str | None) -> str:
    stato = str(value or "").strip().lower()
    if "approv" in stato:
        return "approved"
    if "rifiut" in stato:
        return "rejected"
    return "waiting"


def _summarize_personal_requests(rows: list[dict]) -> dict:
    summary = {
        "total": len(rows),
        "approved": 0,
        "waiting": 0,
        "rejected": 0,
        "editable": 0,
        "medical": 0,
    }
    for row in rows:
        bucket = _absence_status_bucket(row.get("stato"))
        summary[bucket] += 1
        if bucket == "waiting":
            summary["editable"] += 1
        if row.get("certificato_medico"):
            summary["medical"] += 1
    return summary


def _summarize_pending_requests(rows: list[dict]) -> dict:
    summary = {
        "total": len(rows),
        "medical": 0,
        "ferie": 0,
        "permesso": 0,
        "other": 0,
    }
    for row in rows:
        tipo = _norm_tipo(row.get("tipo"))
        if row.get("certificato_medico"):
            summary["medical"] += 1
        if tipo == "Ferie":
            summary["ferie"] += 1
        elif tipo == "Permesso":
            summary["permesso"] += 1
        else:
            summary["other"] += 1
    return summary


def _attach_corsi_conflicts(rows: list[dict]) -> None:
    """Arricchisce in-place ogni riga assenza con `corsi_conflitto` e `n_corsi_conflitto`.

    Richiede `legacy_user_id`, `data_inizio_raw`, `data_fine_raw` sulle righe.
    Fa una sola query batch su `TrainingSession` per tutti i dipendenti coinvolti.
    Se manca legacy_user_id (es. tabella senza `utente_id`) lascia 0 conflitti.
    """
    if not rows:
        return
    try:
        from anagrafica.models_formazione import TrainingEnrollment, TrainingSession
    except Exception:
        for r in rows: r["corsi_conflitto"] = []; r["n_corsi_conflitto"] = 0
        return

    # Range globale e set legacy
    legacy_ids: set[int] = set()
    d_min = None
    d_max = None
    for r in rows:
        lid = r.get("legacy_user_id")
        if lid is None: continue
        try: lid = int(lid)
        except (TypeError, ValueError): continue
        legacy_ids.add(lid)
        ds = r.get("data_inizio_raw"); de = r.get("data_fine_raw")
        # normalizza datetime → date
        if hasattr(ds, "date"): ds = ds.date()
        if hasattr(de, "date"): de = de.date()
        if ds is None: continue
        d_min = ds if d_min is None or ds < d_min else d_min
        d_max = (de or ds) if d_max is None or (de or ds) > d_max else d_max

    if not legacy_ids or d_min is None:
        for r in rows: r.setdefault("corsi_conflitto", []); r.setdefault("n_corsi_conflitto", 0)
        return

    # Sessioni iscritte per ogni legacy_id
    enroll_pairs = list(
        TrainingEnrollment.objects
        .filter(legacy_anagrafica_id__in=legacy_ids)
        .values_list("legacy_anagrafica_id", "sessione_id")
    )
    sess_by_dip: dict[int, set] = {}
    all_sess_ids: set = set()
    for lid, sid in enroll_pairs:
        sess_by_dip.setdefault(int(lid), set()).add(int(sid))
        all_sess_ids.add(int(sid))

    # Carica le sessioni nel range globale, una sola query
    sess_data: dict = {}
    if all_sess_ids:
        for s in (TrainingSession.objects
                  .filter(pk__in=all_sess_ids, data_inizio__lte=d_max, data_fine__gte=d_min)
                  .exclude(stato="ANNULLATA")
                  .select_related("corso")):
            sess_data[s.pk] = s

    # Per ogni riga, calcola intersezione
    for r in rows:
        r.setdefault("corsi_conflitto", [])
        r.setdefault("n_corsi_conflitto", 0)
        lid = r.get("legacy_user_id")
        if lid is None: continue
        try: lid = int(lid)
        except (TypeError, ValueError): continue
        ds = r.get("data_inizio_raw"); de = r.get("data_fine_raw")
        if hasattr(ds, "date"): ds = ds.date()
        if hasattr(de, "date"): de = de.date()
        if ds is None: continue
        if de is None: de = ds
        conflitti = []
        for sid in sess_by_dip.get(lid, ()):
            s = sess_data.get(sid)
            if not s: continue
            if s.data_inizio <= de and s.data_fine >= ds:
                conflitti.append({
                    "id": s.pk,
                    "code": s.corso.codice,
                    "title": s.corso.titolo,
                    "data_inizio": s.data_inizio,
                    "data_fine":   s.data_fine,
                    "stato_display": s.get_stato_display(),
                    "url": f"/anagrafica/formazione/sessioni/{s.pk}/",
                })
        # Ordina per data inizio
        conflitti.sort(key=lambda c: c["data_inizio"])
        r["corsi_conflitto"] = conflitti
        r["n_corsi_conflitto"] = len(conflitti)


def _load_pending_for_manager(
    legacy_user_id: int | None,
    limit: int = 25,
    *,
    manager_name: str = "",
    manager_email: str = "",
) -> list[dict]:
    if not _table_exists("assenze"):
        return []
    manager_where_sql, manager_where_params, use_legacy_join = _combined_manager_assignment_where_clause(
        legacy_user_id=legacy_user_id,
        manager_name=manager_name,
        manager_email=manager_email,
        assenze_alias="a",
        capi_alias="cr",
    )
    if not manager_where_sql:
        return []
    join_sql = " LEFT JOIN capi_reparto cr ON cr.id = a.capo_reparto_id " if use_legacy_join else ""

    _cert_col = ", a.certificato_medico" if _has_assenze_column("certificato_medico") else ""
    _utente_col = ", a.utente_id" if _has_assenze_column("utente_id") else ""
    _creata_col = ", a.created_datetime" if _has_assenze_column("created_datetime") else ""
    base_sql = f"""
        SELECT
            a.id,
            a.copia_nome AS dipendente,
            a.tipo_assenza,
            a.data_inizio,
            a.data_fine,
            a.consenso,
            a.moderation_status,
            a.motivazione_richiesta{_cert_col}{_utente_col}{_creata_col}
        FROM assenze a
        {join_sql}
        WHERE {manager_where_sql}
          AND COALESCE(a.moderation_status, 2) = 2
    """
    sql = _select_limited(base_sql, "ORDER BY a.data_inizio DESC, a.id DESC", limit)
    rows = _fetch_all_dict(sql, manager_where_params)
    out = []
    for row in rows:
        moderation_status, moderation_label = _status_from_moderation(row.get("moderation_status"), default_pending=True)
        stato_value = moderation_label
        out.append(
            {
                "id": row.get("id"),
                "dipendente": str(row.get("dipendente") or "N/D"),
                "tipo": _tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta")),
                "consenso": stato_value,
                "inizio_label": _dt_label(row.get("data_inizio")),
                "fine_label": _dt_label(row.get("data_fine")),
                "motivo": _strip_tipo_metadata_from_motivazione(row.get("motivazione_richiesta")),
                "certificato_medico": str(row.get("certificato_medico") or ""),
                "moderation_status": moderation_status,
                "legacy_user_id": row.get("utente_id"),
                "data_inizio_raw": row.get("data_inizio"),
                "data_fine_raw":   row.get("data_fine"),
                "creata_label": _dt_label(row.get("created_datetime")),
            }
        )
    _attach_corsi_conflicts(out)
    _mark_sharepoint_managed(out)
    return out


def _load_gestite_for_manager(
    legacy_user_id: int | None,
    limit: int = 30,
    *,
    manager_name: str = "",
    manager_email: str = "",
) -> list[dict]:
    """Assenze già gestite (Approvato/Rifiutato) dal CAR indicato."""
    if not _table_exists("assenze"):
        return []
    manager_where_sql, manager_where_params, use_legacy_join = _combined_manager_assignment_where_clause(
        legacy_user_id=legacy_user_id,
        manager_name=manager_name,
        manager_email=manager_email,
        assenze_alias="a",
        capi_alias="cr",
    )
    if not manager_where_sql:
        return []
    join_sql = " LEFT JOIN capi_reparto cr ON cr.id = a.capo_reparto_id " if use_legacy_join else ""

    _note_col = ", a.note_gestione" if _has_assenze_column("note_gestione") else ""
    _cert_col = ", a.certificato_medico" if _has_assenze_column("certificato_medico") else ""
    _utente_col = ", a.utente_id" if _has_assenze_column("utente_id") else ""
    base_sql = f"""
        SELECT
            a.id,
            a.copia_nome AS dipendente,
            a.tipo_assenza,
            a.data_inizio,
            a.data_fine,
            a.consenso,
            a.moderation_status,
            a.motivazione_richiesta{_note_col}{_cert_col}{_utente_col}
        FROM assenze a
        {join_sql}
        WHERE {manager_where_sql}
          AND COALESCE(a.moderation_status, 2) IN (0, 1)
    """
    sql = _select_limited(base_sql, "ORDER BY a.data_inizio DESC, a.id DESC", limit)
    rows = _fetch_all_dict(sql, manager_where_params)
    out = []
    for row in rows:
        moderation_status, moderation_label = _status_from_moderation(row.get("moderation_status"), default_pending=True)
        out.append(
            {
                "id": row.get("id"),
                "dipendente": str(row.get("dipendente") or "N/D"),
                "tipo": _tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta")),
                "consenso": moderation_label,
                "inizio_label": _dt_label(row.get("data_inizio")),
                "fine_label": _dt_label(row.get("data_fine")),
                "motivo": _strip_tipo_metadata_from_motivazione(row.get("motivazione_richiesta")),
                "certificato_medico": str(row.get("certificato_medico") or ""),
                "moderation_status": moderation_status,
                "note_gestione": str(row.get("note_gestione") or ""),
                "legacy_user_id":   row.get("utente_id"),
                "data_inizio_raw":  row.get("data_inizio"),
                "data_fine_raw":    row.get("data_fine"),
            }
        )
    _attach_corsi_conflicts(out)
    _mark_sharepoint_managed(out)
    return out


def _load_assenze_car_periodo(
    legacy_user_id: int | None,
    date_start: datetime,
    date_end: datetime,
    limit: int = 200,
    *,
    manager_name: str = "",
    manager_email: str = "",
) -> list[dict]:
    """Assenze del personale del CAR in un dato intervallo (per riepilogo oggi/settimana)."""
    if not _table_exists("assenze"):
        return []
    manager_where_sql, manager_where_params, use_legacy_join = _combined_manager_assignment_where_clause(
        legacy_user_id=legacy_user_id,
        manager_name=manager_name,
        manager_email=manager_email,
        assenze_alias="a",
        capi_alias="cr",
    )
    if not manager_where_sql:
        return []
    join_sql = " LEFT JOIN capi_reparto cr ON cr.id = a.capo_reparto_id " if use_legacy_join else ""

    base_sql = f"""
        SELECT
            a.id,
            a.copia_nome AS dipendente,
            a.tipo_assenza,
            a.motivazione_richiesta,
            a.data_inizio,
            a.data_fine,
            a.consenso,
            a.moderation_status
        FROM assenze a
        {join_sql}
        WHERE {manager_where_sql}
          AND a.data_inizio IS NOT NULL
          AND a.data_fine IS NOT NULL
          AND a.data_fine >= %s
          AND a.data_inizio <= %s
          AND COALESCE(a.moderation_status, 2) != 1
    """
    sql = _select_limited(base_sql, "ORDER BY a.data_inizio, a.id", limit)
    rows = _fetch_all_dict(sql, [*manager_where_params, date_start, date_end])
    out = []
    for row in rows:
        _, moderation_label = _status_from_moderation(row.get("moderation_status"), default_pending=True)
        out.append(
            {
                "id": row.get("id"),
                "dipendente": str(row.get("dipendente") or "N/D"),
                "tipo": _tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta")),
                "consenso": moderation_label,
                "inizio_label": _dt_label(row.get("data_inizio")),
                "fine_label": _dt_label(row.get("data_fine")),
            }
        )
    return out


def _load_all_pending(limit: int = 100) -> list[dict]:
    """Tutte le assenze in attesa (nessun filtro su capo): per AMMINISTRAZIONE."""
    if not _table_exists("assenze"):
        return []
    _cert_col = ", a.certificato_medico" if _has_assenze_column("certificato_medico") else ""
    _utente_col = ", a.utente_id" if _has_assenze_column("utente_id") else ""
    _creata_col = ", a.created_datetime" if _has_assenze_column("created_datetime") else ""
    base_sql = f"""
        SELECT
            a.id,
            a.copia_nome AS dipendente,
            a.tipo_assenza,
            a.data_inizio,
            a.data_fine,
            a.consenso,
            a.moderation_status,
            a.motivazione_richiesta{_cert_col}{_utente_col}{_creata_col}
        FROM assenze a
        WHERE COALESCE(a.moderation_status, 2) = 2
    """
    sql = _select_limited(base_sql, "ORDER BY a.data_inizio DESC, a.id DESC", limit)
    rows = _fetch_all_dict(sql)
    out = []
    for row in rows:
        _, moderation_label = _status_from_moderation(row.get("moderation_status"), default_pending=True)
        out.append(
            {
                "id": row.get("id"),
                "dipendente": str(row.get("dipendente") or "N/D"),
                "tipo": _tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta")),
                "consenso": moderation_label,
                "inizio_label": _dt_label(row.get("data_inizio")),
                "fine_label": _dt_label(row.get("data_fine")),
                "motivo": _strip_tipo_metadata_from_motivazione(row.get("motivazione_richiesta")),
                "certificato_medico": str(row.get("certificato_medico") or ""),
                "moderation_status": row.get("moderation_status"),
                "legacy_user_id":  row.get("utente_id"),
                "data_inizio_raw": row.get("data_inizio"),
                "data_fine_raw":   row.get("data_fine"),
                "creata_label": _dt_label(row.get("created_datetime")),
            }
        )
    _attach_corsi_conflicts(out)
    _mark_sharepoint_managed(out)
    return out


def _load_all_gestite(limit: int = 50) -> list[dict]:
    """Ultime assenze già gestite (Approvato/Rifiutato), nessun filtro: per AMMINISTRAZIONE."""
    if not _table_exists("assenze"):
        return []
    _note_col = ", a.note_gestione" if _has_assenze_column("note_gestione") else ""
    _cert_col = ", a.certificato_medico" if _has_assenze_column("certificato_medico") else ""
    base_sql = f"""
        SELECT
            a.id,
            a.copia_nome AS dipendente,
            a.tipo_assenza,
            a.data_inizio,
            a.data_fine,
            a.consenso,
            a.moderation_status,
            a.motivazione_richiesta{_note_col}{_cert_col}
        FROM assenze a
        WHERE COALESCE(a.moderation_status, 2) IN (0, 1)
    """
    sql = _select_limited(base_sql, "ORDER BY a.data_inizio DESC, a.id DESC", limit)
    rows = _fetch_all_dict(sql)
    out = []
    for row in rows:
        _, moderation_label = _status_from_moderation(row.get("moderation_status"), default_pending=True)
        out.append(
            {
                "id": row.get("id"),
                "dipendente": str(row.get("dipendente") or "N/D"),
                "tipo": _tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta")),
                "consenso": moderation_label,
                "inizio_label": _dt_label(row.get("data_inizio")),
                "fine_label": _dt_label(row.get("data_fine")),
                "motivo": _strip_tipo_metadata_from_motivazione(row.get("motivazione_richiesta")),
                "certificato_medico": str(row.get("certificato_medico") or ""),
                "moderation_status": row.get("moderation_status"),
                "note_gestione": str(row.get("note_gestione") or ""),
            }
        )
    _mark_sharepoint_managed(out)
    return out


def _load_all_assenze_periodo(date_start: datetime, date_end: datetime, limit: int = 300) -> list[dict]:
    """Tutte le assenze in un periodo (non rifiutate): per AMMINISTRAZIONE."""
    if not _table_exists("assenze"):
        return []
    base_sql = """
        SELECT
            a.id,
            a.copia_nome AS dipendente,
            a.tipo_assenza,
            a.motivazione_richiesta,
            a.data_inizio,
            a.data_fine,
            a.consenso,
            a.moderation_status
        FROM assenze a
        WHERE a.data_inizio IS NOT NULL
          AND a.data_fine IS NOT NULL
          AND a.data_fine >= %s
          AND a.data_inizio <= %s
          AND COALESCE(a.moderation_status, 2) != 1
    """
    sql = _select_limited(base_sql, "ORDER BY a.data_inizio, a.id", limit)
    rows = _fetch_all_dict(sql, [date_start, date_end])
    out = []
    for row in rows:
        _, moderation_label = _status_from_moderation(row.get("moderation_status"), default_pending=True)
        out.append(
            {
                "id": row.get("id"),
                "dipendente": str(row.get("dipendente") or "N/D"),
                "tipo": _tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta")),
                "consenso": moderation_label,
                "inizio_label": _dt_label(row.get("data_inizio")),
                "fine_label": _dt_label(row.get("data_fine")),
            }
        )
    return out


def _legacy_capi_table_exists() -> bool:
    # Il valore guida il JOIN `cr.id = a.capo_reparto_id`: serve sia la tabella
    # `capi_reparto` sia la colonna FK `assenze.capo_reparto_id`, che in alcuni
    # ambienti legacy puo' mancare e farebbe fallire la query con 42S22.
    return _table_exists("capi_reparto") and _has_assenze_column("capo_reparto_id")


def _resolve_effective_reparto_for_legacy_user(legacy_user_id: int | None) -> str:
    if not legacy_user_id:
        return ""
    try:
        from core.models import UserExtraInfo

        extra = UserExtraInfo.objects.filter(legacy_user_id=int(legacy_user_id)).only("reparto").first()
        if extra and str(extra.reparto or "").strip():
            return str(extra.reparto or "").strip()
    except Exception:
        pass

    if not _table_exists("anagrafica_dipendenti"):
        return ""
    cols = legacy_table_columns("anagrafica_dipendenti")
    if "utente_id" not in cols or "reparto" not in cols:
        return ""

    rows = _fetch_all_dict(
        "SELECT reparto FROM anagrafica_dipendenti WHERE utente_id = %s ORDER BY id DESC",
        [int(legacy_user_id)],
    )
    for row in rows:
        reparto = str(row.get("reparto") or "").strip()
        if reparto:
            return reparto
    return ""


def _resolve_local_capo_legacy_user(raw_value: str | None, *, legacy_user_id: int | None = None):
    try:
        return resolve_caporeparto_legacy_user(raw_value, legacy_user_id=legacy_user_id)
    except Exception:
        return None


def _resolve_legacy_capo_lookup_by_raw_value(raw_value: str | None) -> int | None:
    raw = str(raw_value or "").strip()
    if not raw or not _legacy_capi_table_exists():
        return None
    cols = legacy_table_columns("capi_reparto")
    with connections["default"].cursor() as cursor:
        if "indirizzo_email" in cols:
            if _db_vendor() == "sqlite":
                cursor.execute(
                    "SELECT sharepoint_item_id FROM capi_reparto WHERE UPPER(COALESCE(indirizzo_email,'')) = UPPER(?) ORDER BY id DESC LIMIT 1",
                    [raw],
                )
            else:
                cursor.execute(
                    "SELECT TOP 1 sharepoint_item_id FROM capi_reparto WHERE UPPER(COALESCE(indirizzo_email,'')) = UPPER(%s) ORDER BY id DESC",
                    [raw],
                )
            row = cursor.fetchone()
            if row and row[0] is not None:
                return _as_int(row[0])
        if "title" in cols:
            if _db_vendor() == "sqlite":
                cursor.execute(
                    "SELECT sharepoint_item_id FROM capi_reparto WHERE UPPER(COALESCE(title,'')) = UPPER(?) ORDER BY id DESC LIMIT 1",
                    [raw],
                )
            else:
                cursor.execute(
                    "SELECT TOP 1 sharepoint_item_id FROM capi_reparto WHERE UPPER(COALESCE(title,'')) = UPPER(%s) ORDER BY id DESC",
                    [raw],
                )
            row = cursor.fetchone()
            if row and row[0] is not None:
                return _as_int(row[0])
    return None


def _anagrafica_hr_capo_ids() -> set[int]:
    """Id anagrafica di chi puo' comparire nel menu «Capo reparto».

    Non bastano i caporeparto dei reparti: l'approvatore di un dipendente e' il
    **responsabile della sua area aziendale** quando ce n'e' uno proprio
    (vedi ``_resolve_anagrafica_hr_effective_capo_ids``). Se il menu elencasse
    solo i caporeparto, quel responsabile non avrebbe una voce su cui essere
    selezionato e la richiesta ricadrebbe in silenzio sul caporeparto del
    reparto — cioe' su una persona diversa da quella mostrata in Anagrafica.
    """
    try:
        from anagrafica.models import AreaAziendale, Reparto
    except Exception:
        return set()

    ids: set[int] = set()
    try:
        for value in Reparto.objects.filter(is_active=True, caporeparto_legacy_id__isnull=False).values_list(
            "caporeparto_legacy_id", flat=True
        ):
            capo_id = _as_int(value)
            if capo_id is not None and capo_id > 0:
                ids.add(capo_id)
        for value in AreaAziendale.objects.filter(
            is_active=True, responsabile_legacy_id__isnull=False
        ).values_list("responsabile_legacy_id", flat=True):
            capo_id = _as_int(value)
            if capo_id is not None and capo_id > 0:
                ids.add(capo_id)
    except Exception:
        return set()
    return ids


def _anagrafica_row_label(row: dict) -> str:
    nome = str(row.get("nome") or "").strip()
    cognome = str(row.get("cognome") or "").strip()
    alias = str(row.get("aliasusername") or "").strip()
    email = str(row.get("email_notifica") or row.get("email") or "").strip()
    return " ".join(part for part in [cognome, nome] if part) or alias or email or f"#{row.get('id')}"


def _fetch_anagrafica_rows_by_ids(ids: set[int]) -> dict[int, dict]:
    clean_ids = sorted({int(v) for v in ids if _as_int(v) is not None and int(v) > 0})
    if not clean_ids or not _table_exists("anagrafica_dipendenti"):
        return {}
    cols = legacy_table_columns("anagrafica_dipendenti")
    select_cols = [c for c in ["id", "nome", "cognome", "aliasusername", "email", "email_notifica", "utente_id"] if c in cols]
    if "id" not in select_cols:
        return {}
    placeholders = ", ".join(["%s"] * len(clean_ids))
    rows = _fetch_all_dict(
        f"SELECT {_quoted_columns(select_cols)} FROM anagrafica_dipendenti WHERE id IN ({placeholders})",
        clean_ids,
    )
    return {int(row["id"]): row for row in rows if _as_int(row.get("id")) is not None}


def _legacy_user_for_anagrafica_row(row: dict):
    legacy_user_id = _as_int(row.get("utente_id"))
    if legacy_user_id is not None:
        user = _resolve_local_capo_legacy_user("", legacy_user_id=legacy_user_id)
        if user is not None:
            return user
    for raw in [row.get("email"), row.get("email_notifica"), row.get("aliasusername")]:
        user = _resolve_local_capo_legacy_user(str(raw or "").strip())
        if user is not None:
            return user
    return None


def _build_anagrafica_hr_capo_option(row: dict) -> dict:
    anagrafica_id = _as_int(row.get("id"))
    legacy_user = _legacy_user_for_anagrafica_row(row)
    legacy_user_id = _as_int(getattr(legacy_user, "id", None)) if legacy_user is not None else _as_int(row.get("utente_id"))
    email = str(getattr(legacy_user, "email", "") or "").strip()
    label = str(getattr(legacy_user, "nome", "") or "").strip() or _anagrafica_row_label(row)
    lookup_value = f"legacy_user:{legacy_user_id}" if legacy_user_id is not None else f"anagrafica:{anagrafica_id or ''}"
    option_value = email or lookup_value
    return {
        "Value": label,
        "Email": email,
        "LookupId": lookup_value,
        "LegacyLookupId": str(_resolve_legacy_capo_lookup_by_raw_value(option_value) or "").strip(),
        "LegacyUserId": str(legacy_user_id or "").strip(),
        "AnagraficaLegacyId": str(anagrafica_id or "").strip(),
    }


def _load_anagrafica_hr_capi_options() -> list[dict]:
    rows_by_id = _fetch_anagrafica_rows_by_ids(_anagrafica_hr_capo_ids())
    if not rows_by_id:
        return []

    out: list[dict] = []
    seen: set[str] = set()
    for row in sorted(rows_by_id.values(), key=lambda item: _anagrafica_row_label(item).casefold()):
        option = _build_anagrafica_hr_capo_option(row)
        key = str(option.get("LegacyUserId") or option.get("AnagraficaLegacyId") or option.get("Email") or "").casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(option)
    return out


def _build_local_capo_option(raw_value: str, *, legacy_user_id: int | None = None) -> dict:
    raw = str(raw_value or "").strip()
    legacy_user = _resolve_local_capo_legacy_user(raw, legacy_user_id=legacy_user_id)
    raw_is_email = "@" in raw
    email = raw if raw_is_email else ""
    reparto = ""
    legacy_user_id_value = str(legacy_user_id or "").strip()
    if legacy_user is not None:
        legacy_user_id_value = str(getattr(legacy_user, "id", "") or "").strip()
        reparto = _resolve_effective_reparto_for_legacy_user(_as_int(getattr(legacy_user, "id", None)))
        if not email:
            email = str(getattr(legacy_user, "email", "") or "").strip()
    display_value = reparto or raw or email
    option_value = email or raw
    return {
        "Value": display_value,
        "Email": email,
        "LookupId": option_value,
        "LegacyLookupId": str(_resolve_legacy_capo_lookup_by_raw_value(option_value or raw) or "").strip(),
        "LegacyUserId": legacy_user_id_value,
    }


def _load_local_capi_options() -> list[dict]:
    try:
        from core.models import OptioneConfig
    except Exception:
        return []

    out: list[dict] = []
    seen: set[str] = set()
    for option in OptioneConfig.objects.filter(tipo__iexact="caporeparto", is_active=True).order_by("ordine", "valore", "id"):
        raw = str(option.valore or "").strip()
        if not raw:
            continue
        option_legacy_user_id = _as_int(getattr(option, "legacy_user_id", None))
        key = str(option_legacy_user_id or raw).strip().casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(_build_local_capo_option(raw, legacy_user_id=option_legacy_user_id))
    return out


def _load_legacy_capi_options() -> list[dict]:
    if not _table_exists("capi_reparto"):
        return []
    cols = legacy_table_columns("capi_reparto")
    if "title" not in cols:
        return []
    email_col = "indirizzo_email" if "indirizzo_email" in cols else None
    sp_col = "sharepoint_item_id" if "sharepoint_item_id" in cols else None

    select_cols = ["title"]
    if email_col:
        select_cols.append(email_col)
    if sp_col:
        select_cols.append(sp_col)
    sql = f"SELECT {_quoted_columns(select_cols)} FROM capi_reparto ORDER BY title"
    rows = _fetch_all_dict(sql)

    out: list[dict] = []
    for row in rows:
        value = str(row.get("title") or "").strip()
        email = str(row.get(email_col) or "").strip() if email_col else ""
        if not value:
            continue
        out.append(
            {
                "Value": value,
                "Email": email,
                "LookupId": str(row.get(sp_col) or "").strip() if sp_col else "",
                "LegacyLookupId": str(row.get(sp_col) or "").strip() if sp_col else "",
                "LegacyUserId": "",
            }
        )
    return out


def _load_capi_options() -> list[dict]:
    anagrafica_options = _load_anagrafica_hr_capi_options()
    if anagrafica_options:
        return anagrafica_options
    local_options = _load_local_capi_options()
    if local_options:
        return local_options
    return _load_legacy_capi_options()


def _count_pending_for_car(
    legacy_user_id: int | None,
    *,
    manager_name: str = "",
    manager_email: str = "",
) -> int:
    """Conta le assenze in attesa del personale di un CAR (per il badge topbar)."""
    if not _table_exists("assenze"):
        return 0
    manager_where_sql, manager_where_params, use_legacy_join = _combined_manager_assignment_where_clause(
        legacy_user_id=legacy_user_id,
        manager_name=manager_name,
        manager_email=manager_email,
        assenze_alias="a",
        capi_alias="cr",
    )
    if not manager_where_sql:
        return 0
    try:
        join_sql = " LEFT JOIN capi_reparto cr ON cr.id = a.capo_reparto_id " if use_legacy_join else ""
        with connections["default"].cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM assenze a
                {join_sql}
                WHERE {manager_where_sql}
                  AND COALESCE(a.moderation_status, 2) = 2
                """,
                manager_where_params,
            )
            row = cursor.fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


def _norm_text_key(value: str | None) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _capo_option_value(capo: dict) -> str:
    email = str(capo.get("Email") or "").strip()
    if email:
        return email
    return str(capo.get("LookupId") or "").strip()


def _find_reparto_for_user(name: str, email: str, username: str) -> str:
    if not _table_exists("anagrafica_dipendenti"):
        return ""
    cols = legacy_table_columns("anagrafica_dipendenti")

    select_cols = []
    for col in ["nome", "cognome", "email", "aliasusername", "reparto"]:
        if col in cols:
            select_cols.append(col)
    if "reparto" not in select_cols:
        return ""

    if ("email" in cols and email) or ("aliasusername" in cols and username):
        clauses = []
        params: list[str] = []
        if "email" in cols and email:
            clauses.append("UPPER(COALESCE(email,'')) = UPPER(%s)")
            params.append(email)
        if "aliasusername" in cols and username:
            clauses.append("UPPER(COALESCE(aliasusername,'')) = UPPER(%s)")
            params.append(username)
        if clauses:
            sql = f"""
                SELECT {_quoted_columns(select_cols)}
                FROM anagrafica_dipendenti
                WHERE ({' OR '.join(clauses)})
                ORDER BY id DESC
            """
            for row in _fetch_all_dict(sql, params):
                reparto = str(row.get("reparto") or "").strip()
                if reparto:
                    return reparto

    target_name = _norm_text_key(name)
    if not target_name:
        return ""
    base_sql = f"""
        SELECT {_quoted_columns(select_cols)}
        FROM anagrafica_dipendenti
        WHERE {_blank_expr('reparto')} IS NOT NULL
    """
    sql = _select_limited(base_sql, "ORDER BY id DESC", 3000)
    for row in _fetch_all_dict(sql):
        reparto = str(row.get("reparto") or "").strip()
        if not reparto:
            continue
        nome = str(row.get("nome") or "").strip()
        cognome = str(row.get("cognome") or "").strip()
        candidates = {
            _norm_text_key(f"{cognome} {nome}"),
            _norm_text_key(f"{nome} {cognome}"),
        }
        candidates.discard("")
        if target_name in candidates:
            return reparto
    return ""


def _resolve_anagrafica_employee_id_for_user(
    *,
    legacy_user_id: int | None,
    email: str,
    username: str,
    name: str,
) -> int | None:
    if not _table_exists("anagrafica_dipendenti"):
        return None
    cols = legacy_table_columns("anagrafica_dipendenti")
    if "id" not in cols:
        return None

    clauses: list[str] = []
    params: list[str | int] = []
    if legacy_user_id is not None and "utente_id" in cols:
        clauses.append("utente_id = %s")
        params.append(int(legacy_user_id))

    email = str(email or "").strip()
    if email:
        if "email" in cols:
            clauses.append("UPPER(COALESCE(email,'')) = UPPER(%s)")
            params.append(email)
        if "email_notifica" in cols:
            clauses.append("UPPER(COALESCE(email_notifica,'')) = UPPER(%s)")
            params.append(email)

    username = str(username or "").strip()
    alias_candidates = {username}
    if "@" in username:
        alias_candidates.add(username.split("@", 1)[0].strip())
    if email and "@" in email:
        alias_candidates.add(email.split("@", 1)[0].strip())
    alias_candidates.discard("")
    if "aliasusername" in cols:
        for alias in sorted(alias_candidates):
            clauses.append("UPPER(COALESCE(aliasusername,'')) = UPPER(%s)")
            params.append(alias)

    if clauses:
        sql = _select_limited(
            f"SELECT id FROM anagrafica_dipendenti WHERE {' OR '.join(clauses)}",
            "ORDER BY id DESC",
            1,
        )
        rows = _fetch_all_dict(sql, params)
        if rows:
            return _as_int(rows[0].get("id"))

    target_name = _norm_text_key(name)
    if not target_name or not {"nome", "cognome"}.issubset(cols):
        return None
    sql = _select_limited(
        "SELECT id, nome, cognome FROM anagrafica_dipendenti",
        "ORDER BY id DESC",
        3000,
    )
    for row in _fetch_all_dict(sql):
        nome = str(row.get("nome") or "").strip()
        cognome = str(row.get("cognome") or "").strip()
        candidates = {
            _norm_text_key(f"{cognome} {nome}"),
            _norm_text_key(f"{nome} {cognome}"),
        }
        candidates.discard("")
        if target_name in candidates:
            return _as_int(row.get("id"))
    return None


def _legacy_user_id_from_anagrafica_employee_id(anagrafica_id: int | None) -> int | None:
    if anagrafica_id is None:
        return None
    row = _fetch_anagrafica_rows_by_ids({int(anagrafica_id)}).get(int(anagrafica_id))
    if not row:
        return None
    user = _legacy_user_for_anagrafica_row(row)
    return _as_int(getattr(user, "id", None)) if user is not None else _as_int(row.get("utente_id"))


def _resolve_anagrafica_hr_effective_capo_ids(
    *,
    legacy_user_id: int | None,
    email: str,
    username: str,
    name: str,
) -> tuple[int | None, int | None]:
    employee_id = _resolve_anagrafica_employee_id_for_user(
        legacy_user_id=legacy_user_id,
        email=email,
        username=username,
        name=name,
    )
    capo_anagrafica_id: int | None = None
    reparto = ""
    try:
        from anagrafica.models import DipendenteAnagraficaAziendale, Reparto
        from anagrafica.services.reparto_canonico import resolve_responsabile_effettivo

        if employee_id is not None:
            aziendale = (
                DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=employee_id)
                .select_related("area_aziendale", "area_aziendale__reparto")
                .only("caporeparto_legacy_id", "area", "area_aziendale")
                .first()
            )
            if aziendale is not None:
                # L'approvatore e' il responsabile dell'AREA AZIENDALE del
                # dipendente; il caporeparto del REPARTO e' solo il fallback
                # (stessa regola di `resolve_responsabile_effettivo`, cosi'
                # assenze e Anagrafica mostrano lo stesso nome). Il campo
                # denormalizzato `caporeparto_legacy_id` viene usato solo se
                # la catena canonica non risolve: e' una copia, aggiornata solo
                # al salvataggio del dipendente, e puo' essere stantia.
                area = getattr(aziendale, "area_aziendale", None)
                rep_canonico = getattr(area, "reparto", None) if area is not None else None
                capo_anagrafica_id = _as_int(
                    resolve_responsabile_effettivo(area=area, reparto=rep_canonico)
                )
                if capo_anagrafica_id is None:
                    capo_anagrafica_id = _as_int(getattr(aziendale, "caporeparto_legacy_id", None))
                reparto = str(getattr(aziendale, "area", "") or "").strip()

        if capo_anagrafica_id is None:
            reparto = reparto or _find_reparto_for_user(name=name, email=email, username=username)
            if reparto:
                rep = Reparto.objects.filter(nome__iexact=reparto, is_active=True).only("caporeparto_legacy_id").first()
                if rep is not None:
                    capo_anagrafica_id = _as_int(getattr(rep, "caporeparto_legacy_id", None))
    except Exception:
        capo_anagrafica_id = None

    return _legacy_user_id_from_anagrafica_employee_id(capo_anagrafica_id), capo_anagrafica_id


def _resolve_anagrafica_hr_default_capo_option(
    *,
    name: str,
    email: str,
    username: str,
    capi: list[dict],
    legacy_user_id: int | None = None,
) -> str:
    if not capi:
        return ""
    capo_legacy_user_id, capo_anagrafica_id = _resolve_anagrafica_hr_effective_capo_ids(
        legacy_user_id=legacy_user_id,
        email=email,
        username=username,
        name=name,
    )
    if capo_legacy_user_id is not None:
        option = _resolve_capo_option_value_from_ids(local_id=capo_legacy_user_id, lookup_id=None, capi=capi)
        if option:
            return option
    if capo_anagrafica_id is not None:
        for capo in capi:
            if _as_int(capo.get("AnagraficaLegacyId")) == capo_anagrafica_id:
                option = _capo_option_value(capo)
                if option:
                    return option
    return ""


def _resolve_default_capo_for_user(
    *,
    name: str,
    email: str,
    username: str,
    capi: list[dict],
    legacy_user_id: int | None = None,
) -> str:
    if not capi:
        return ""

    by_email: dict[str, str] = {}
    by_lookup: dict[str, str] = {}
    by_title: dict[str, str] = {}
    by_value: dict[str, str] = {}
    for capo in capi:
        option = _capo_option_value(capo)
        if not option:
            continue
        mail = _norm_text_key(capo.get("Email"))
        if mail:
            by_email[mail] = option
        lookup = _norm_text_key(capo.get("LookupId"))
        if lookup:
            by_lookup[lookup] = option
            by_value[lookup] = option
        legacy_lookup = _norm_text_key(capo.get("LegacyLookupId"))
        if legacy_lookup:
            by_lookup[legacy_lookup] = option
        title = _norm_text_key(capo.get("Value"))
        if title:
            by_title[title] = option

    # Step 1: caporeparto effettivo da Anagrafica HR.
    anagrafica_option = _resolve_anagrafica_hr_default_capo_option(
        name=name,
        email=email,
        username=username,
        capi=capi,
        legacy_user_id=legacy_user_id,
    )
    if anagrafica_option:
        return anagrafica_option

    # Step 2: UserExtraInfo.caporeparto (compatibilita RepartoCapoMapping)
    if legacy_user_id:
        try:
            from core.models import UserExtraInfo
            uei = UserExtraInfo.objects.filter(legacy_user_id=legacy_user_id).first()
            if uei and uei.caporeparto:
                option = (
                    by_email.get(_norm_text_key(uei.caporeparto))
                    or by_value.get(_norm_text_key(uei.caporeparto))
                    or by_title.get(_norm_text_key(uei.caporeparto))
                )
                if option:
                    return option
        except Exception:
            pass

    # Step 3: storico assenze precedenti (locale o legacy)
    clauses = []
    params: list[str] = []
    if name:
        clauses.append("UPPER(COALESCE(copia_nome,'')) = UPPER(%s)")
        params.append(name)
    if email:
        clauses.append("UPPER(COALESCE(email_esterna,'')) = UPPER(%s)")
        params.append(email)
    if clauses and _table_exists("assenze"):
        base_sql = f"""
            SELECT capo_reparto_id, capo_reparto_lookup_id
            FROM assenze
            WHERE ({' OR '.join(clauses)})
              AND (capo_reparto_id IS NOT NULL OR capo_reparto_lookup_id IS NOT NULL)
        """
        sql = _select_limited(base_sql, "ORDER BY COALESCE(modified_datetime, created_datetime, data_inizio) DESC, id DESC", 1)
        rows = _fetch_all_dict(sql, params)
        if rows:
            option = _resolve_capo_option_value_from_ids(
                local_id=_as_int(rows[0].get("capo_reparto_id")),
                lookup_id=_as_int(rows[0].get("capo_reparto_lookup_id")),
                capi=capi,
            )
            if option:
                return option

    # Step 4: mapping reparto -> caporeparto locale
    reparto = _find_reparto_for_user(name=name, email=email, username=username)
    if reparto:
        option = ""
        try:
            from core.models import RepartoCapoMapping

            mapping = RepartoCapoMapping.objects.filter(reparto__iexact=reparto, is_active=True).order_by("id").first()
            if mapping:
                option = (
                    by_email.get(_norm_text_key(mapping.caporeparto))
                    or by_value.get(_norm_text_key(mapping.caporeparto))
                    or by_title.get(_norm_text_key(mapping.caporeparto))
                )
        except Exception:
            option = ""
        if not option:
            option = by_title.get(_norm_text_key(reparto))
        if option:
            return option

    return ""


def _find_capo_dict_for_option(option: str, capi: list[dict]) -> dict | None:
    """Ritrova il dict del caporeparto (in ``capi``) data la sua option (email/lookup)."""
    key = _norm_text_key(option)
    if not key:
        return None
    for capo in capi:
        candidates = {
            _norm_text_key(_capo_option_value(capo)),
            _norm_text_key(capo.get("Email")),
            _norm_text_key(capo.get("LookupId")),
        }
        candidates.discard("")
        if key in candidates:
            return capo
    return None


def _capo_absent_on(capo: dict, day) -> bool:
    """True se il caporeparto ha un'assenza APPROVATA che copre ``day``.

    «Approvata» = ``moderation_status = 0`` (0=Approvato, 1=Rifiutato, 2=In attesa).
    Il match avviene per nome/email (come il resto del modulo assenze).
    Fail-safe: qualunque incertezza o errore → ``False`` (nessuna escalation).
    """
    if not _table_exists("assenze"):
        return False
    name = str(capo.get("Value") or "").strip()
    email = str(capo.get("Email") or "").strip()
    clauses: list[str] = []
    params: list = []
    if name:
        clauses.append("UPPER(COALESCE(copia_nome,'')) = UPPER(%s)")
        params.append(name)
    if email:
        clauses.append("UPPER(COALESCE(email_esterna,'')) = UPPER(%s)")
        params.append(email)
    if not clauses:
        return False
    day_start = datetime.combine(day, datetime.min.time())
    day_end = datetime.combine(day, datetime.max.time())
    base_sql = (
        "SELECT 1 FROM assenze WHERE (" + " OR ".join(clauses) + ") "
        "AND COALESCE(moderation_status, 2) = 0 "
        "AND data_inizio <= %s AND data_fine >= %s"
    )
    params.extend([day_end, day_start])
    try:
        rows = _fetch_all_dict(_select_limited(base_sql, "", 1), params)
        return bool(rows)
    except Exception:
        return False


def _superior_capo_option(capo_anagrafica_id: int | None, capi: list[dict]) -> str:
    """Option del superiore del caporeparto = il suo stesso ``caporeparto_legacy_id``.

    È il «capo del capo» dedotto dall'assegnazione gerarchica (coerente con la
    gestione ruoli/gerarchia). Mappato su una capo-option via ``AnagraficaLegacyId``.
    """
    if not capo_anagrafica_id:
        return ""
    try:
        from anagrafica.models import DipendenteAnagraficaAziendale
        from anagrafica.services.reparto_canonico import resolve_responsabile_effettivo

        az = (
            DipendenteAnagraficaAziendale.objects
            .filter(legacy_anagrafica_id=int(capo_anagrafica_id))
            .select_related("area_aziendale", "area_aziendale__reparto")
            .only("caporeparto_legacy_id", "area_aziendale")
            .first()
        )
        # Stessa regola dell'approvatore: area aziendale prima, reparto dopo,
        # campo denormalizzato solo come ultima spiaggia.
        area = getattr(az, "area_aziendale", None) if az else None
        rep_canonico = getattr(area, "reparto", None) if area is not None else None
        sup_id = _as_int(resolve_responsabile_effettivo(area=area, reparto=rep_canonico))
        if sup_id is None:
            sup_id = _as_int(getattr(az, "caporeparto_legacy_id", None)) if az else None
        if not sup_id:
            return ""
        for capo in capi:
            if _as_int(capo.get("AnagraficaLegacyId")) == sup_id:
                return _capo_option_value(capo)
    except Exception:
        return ""
    return ""


def _effective_capo_option(
    *, name: str, email: str, username: str, legacy_user_id: int | None,
    capi: list[dict], request_day,
) -> tuple[str, bool]:
    """Caporeparto autoritativo per la richiesta: ``(option, escalated)``.

    Risolve il caporeparto ASSEGNATO al dipendente e, **se e solo se** quel
    caporeparto risulta assente (assenza approvata) nel giorno della richiesta,
    lo sostituisce col superiore. Fail-safe: in caso di dubbio ritorna il
    caporeparto assegnato senza escalation.
    """
    base = _resolve_default_capo_for_user(
        name=name, email=email, username=username, capi=capi, legacy_user_id=legacy_user_id,
    )
    if not base:
        return "", False
    capo = _find_capo_dict_for_option(base, capi)
    if capo is None or not _capo_absent_on(capo, request_day):
        return base, False
    sup = _superior_capo_option(_as_int(capo.get("AnagraficaLegacyId")), capi)
    return (sup, True) if sup else (base, False)


def _resolve_capo_email_from_lookup(lookup_id: int | None, capi: list[dict]) -> str:
    if lookup_id is None:
        return ""
    return _resolve_capo_option_value_from_ids(local_id=None, lookup_id=lookup_id, capi=capi)


def _load_motivazioni_local(limit: int = 30) -> list[str]:
    if not _table_exists("assenze"):
        return []
    base_sql = f"""
        SELECT DISTINCT motivazione_richiesta
        FROM assenze
        WHERE {_blank_expr('motivazione_richiesta')} IS NOT NULL
    """
    sql = _select_limited(base_sql, "ORDER BY motivazione_richiesta ASC", limit)
    rows = _fetch_all_dict(sql)
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        txt = _strip_tipo_metadata_from_motivazione(row.get("motivazione_richiesta"))
        if txt and txt not in seen:
            seen.add(txt)
            out.append(txt)
    return out


def _prefill_from_copy(copy_from: str, capi: list[dict]) -> dict | None:
    source = str(copy_from or "").strip()
    if not source:
        return None

    local_id = _as_int(source)
    if local_id is not None:
        row = _get_assenza(local_id)
        if row:
            capo_local_id = _as_int(row.get("capo_reparto_id"))
            capo_lookup = _as_int(row.get("capo_reparto_lookup_id"))
            return {
                "tipo": _tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta")),
                "motivazione": _strip_tipo_metadata_from_motivazione(row.get("motivazione_richiesta")),
                "capo_email": _resolve_capo_option_value_from_ids(local_id=capo_local_id, lookup_id=capo_lookup, capi=capi),
                "salta_approvazione": bool(_as_bool(row.get("salta_approvazione"))),
            }

    sp_item = _graph_get_item(source)
    if not sp_item:
        return None
    fields = sp_item.get("fields") or {}
    capo_lookup = _as_int(fields.get("C_x002e_RepartoLookupId"))
    return {
        "tipo": _tipo_for_display(fields.get("Tipoassenza"), fields.get("Motivazionerichiesta")),
        "motivazione": _strip_tipo_metadata_from_motivazione(fields.get("Motivazionerichiesta")),
        "capo_email": _resolve_capo_email_from_lookup(capo_lookup, capi),
        "salta_approvazione": bool(_as_bool(fields.get("Salta_x0020_approvazione"))),
    }


def _request_json(request) -> dict:
    if request.content_type and "application/json" in request.content_type:
        try:
            payload = json.loads((request.body or b"{}").decode("utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            return {}
    return {}


def _build_submit_token(request, action: str) -> str:
    session_key = request.session.session_key
    if not session_key:
        request.session.save()
        session_key = request.session.session_key or ""
    return signing.dumps(
        {
            "uid": int(getattr(request.user, "id", 0) or 0),
            "sid": str(session_key or ""),
            "action": str(action or "").strip(),
        },
        salt=_FORM_TOKEN_SALT,
    )


def _has_valid_submit_token(request, token: str, action: str) -> bool:
    token = str(token or "").strip()
    if not token:
        return False
    try:
        payload = signing.loads(token, salt=_FORM_TOKEN_SALT, max_age=86400)
    except signing.BadSignature:
        return False
    except signing.SignatureExpired:
        return False

    return (
        int(payload.get("uid", -1)) == int(getattr(request.user, "id", 0) or 0)
        and str(payload.get("sid", "")) == str(request.session.session_key or "")
        and str(payload.get("action", "")) == str(action or "").strip()
    )


def _resolve_employee_identity_from_anagrafica(anagrafica_id: int) -> tuple[str, str, int | None] | None:
    if not _table_exists("anagrafica_dipendenti"):
        return None
    cols = legacy_table_columns("anagrafica_dipendenti")
    if not {"id", "nome", "cognome"}.issubset(cols):
        return None
    select_cols = [c for c in ["id", "nome", "cognome", "email", "email_notifica", "utente_id"] if c in cols]
    rows = _fetch_all_dict(
        f"SELECT {_quoted_columns(select_cols)} FROM anagrafica_dipendenti WHERE id = %s",
        [int(anagrafica_id)],
    )
    if not rows:
        return None
    row = rows[0]
    cognome = str(row.get("cognome") or "").strip()
    nome = str(row.get("nome") or "").strip()
    full_name = f"{cognome} {nome}".strip()
    if not full_name:
        return None
    email = str(row.get("email_notifica") or row.get("email") or "").strip().lower()
    legacy_user_id = _as_int(row.get("utente_id"))
    return full_name, email, legacy_user_id


@login_required
@require_http_methods(["GET"])
def api_dipendente_default_capo(request):
    perms = _assenze_permissions(request)
    if not perms.get("can_insert_for_others"):
        return _json_error("Permessi insufficienti.", status=403)
    dipendente_id = _as_int(request.GET.get("dipendente_id"))
    if not dipendente_id:
        return JsonResponse({"ok": True, "capo_value": ""})
    if not _can_insert_for_dipendente(request, dipendente_id):
        return _json_error("Dipendente fuori dal tuo reparto.", status=403)
    identity = _resolve_employee_identity_from_anagrafica(dipendente_id)
    if not identity:
        return JsonResponse({"ok": False, "capo_value": "", "error": "Dipendente non trovato"})
    emp_name, emp_email, emp_legacy_user_id = identity
    capi = _load_capi_options()
    capo_value = _resolve_default_capo_for_user(
        name=emp_name,
        email=emp_email,
        username="",
        capi=capi,
        legacy_user_id=emp_legacy_user_id,
    )
    return JsonResponse({"ok": True, "capo_value": capo_value})


def _render_richiesta(request, success: str = "", error: str = "", form_data: dict | None = None):
    perms = _assenze_permissions(request)
    name, email, _legacy_id = _legacy_identity(request)
    display_name = _resolve_request_display_name(
        legacy_user_id=_legacy_id,
        email=email,
        username=request.user.get_username(),
        fallback_name=name,
    )
    today = timezone.localdate()
    capi = _load_capi_options()
    motivazioni = _motivazioni_options()
    copy_from = str(request.GET.get("copy_from") or "").strip()
    prefill = _prefill_from_copy(copy_from, capi)

    can_insert_for_others = perms.get("can_insert_for_others", False)
    dipendenti = _insertable_dipendenti_for_request(request) if can_insert_for_others else []

    # Flessibilita: orari da Impostazioni e elenco degli abilitati. Il form li usa
    # per proporre le sole combinazioni ammesse; la verifica resta lato server.
    fless_conf = _flessibilita_config()
    fless_abilitati = _flessibilita_abilitati_ids()
    mio_anagrafica_id = _resolve_anagrafica_employee_id_for_user(
        legacy_user_id=_legacy_id,
        email=email,
        username=request.user.get_username(),
        name=display_name,
    )

    merged_form = {
        "tipoassenza": "",
        "motivazione": "",
        "certificato_medico": "",
        "dipendente_id": "",
        "caporeparto": _resolve_default_capo_for_user(
            name=display_name,
            email=email,
            username=request.user.get_username(),
            capi=capi,
            legacy_user_id=_legacy_id,
        ),
        "date_start": today.strftime("%Y-%m-%d"),
        "date_end": today.strftime("%Y-%m-%d"),
        "time_start": "06:00",
        "time_end": "14:00",
        "salta_approvazione": "0",
    }
    if prefill:
        if prefill.get("tipo"):
            merged_form["tipoassenza"] = str(prefill["tipo"])
        if prefill.get("motivazione"):
            merged_form["motivazione"] = str(prefill["motivazione"])
        if prefill.get("capo_email"):
            merged_form["caporeparto"] = str(prefill["capo_email"])
        if prefill.get("salta_approvazione"):
            merged_form["salta_approvazione"] = "1"
    if form_data:
        merged_form.update({k: str(v) for k, v in form_data.items() if v is not None})
    if not perms.get("can_skip_approval"):
        merged_form["salta_approvazione"] = "0"

    return render(
        request,
        "assenze/pages/richiesta_assenze.html",
        {
            "tipi": list(TIPI_ASSENZA_UI),
            "nome": display_name,
            "capi": capi,
            "dipendenti": dipendenti,
            "motivazioni": motivazioni,
            "copy_from": copy_from,
            "prefill": prefill,
            "form_success": success,
            "form_error": error,
            "form_data": merged_form,
            "submit_token": _build_submit_token(request, "assenze_invio"),
            "form_salta_approvazione": bool(_as_bool(merged_form.get("salta_approvazione"))),
            "flessibilita_entrate": fless_conf.entrate,
            "flessibilita_uscite": fless_conf.uscite,
            "flessibilita_abilitati_ids": sorted(fless_abilitati),
            "flessibilita_abilitato_io": mio_anagrafica_id in fless_abilitati,
            "ore_mattina_list": [f"{h:02d}" for h in range(6, 23)],
            "ore_pom_list":     [f"{h:02d}" for h in range(12, 24)],
            "minuti_list":      [f"{m:02d}" for m in range(0, 60, 5)],
            **_template_perm_context(request),
        },
    )


@login_required
def menu(request):
    name, email, legacy_id = _legacy_identity(request)
    recenti = _load_personal(name, email, limit=8)
    perms = _assenze_permissions(request)
    pending_count = 0
    if perms.get("can_update_any"):
        pending_count = len(_load_all_pending(limit=200))
    elif perms.get("can_update_owned"):
        pending_count = len(
            _load_pending_for_manager(
                legacy_id,
                limit=200,
                manager_name=name,
                manager_email=email,
            )
        )
    return render(
        request,
        "assenze/pages/menu.html",
        {
            "recenti": recenti,
            "car_pending_count": pending_count,
            **_template_perm_context(request),
        },
    )


@login_required
def richiesta_assenze(request):
    if not _assenze_permissions(request).get("can_insert"):
        return HttpResponseForbidden("Permessi insufficienti: inserimento richieste non consentito.")
    return _render_richiesta(request)


@login_required
@ensure_csrf_cookie
def gestione_assenze(request):
    """Pagina personale «Le mie richieste» (tutti gli utenti).

    Mostra lo storico delle proprie richieste (con modifica/eliminazione finché in
    attesa) e, per i soli capi reparto/CAR, la coda «Richieste da approvare» del
    proprio reparto. Il pannello amministrativo vive nella pagina Impostazioni
    (`impostazioni_admin`), riservata all'HR-admin.
    """
    name, email, legacy_id = _legacy_identity(request)
    perms = _assenze_permissions(request)
    e_capo = bool(perms.get("can_update_owned") or perms.get("can_update_any"))

    richieste_da_approvare = _load_pending_for_manager(
        legacy_id,
        limit=40,
        manager_name=name,
        manager_email=email,
    )
    richieste_personali = _load_personal(name, email, limit=40)

    # Le richieste dei propri dipendenti gia' decise: senza queste la pagina
    # mostrava solo la coda da approvare, e appena approvata una richiesta
    # spariva da qui senza lasciare traccia.
    richieste_dipendenti_gestite = (
        _load_gestite_for_manager(
            legacy_id,
            limit=40,
            manager_name=name,
            manager_email=email,
        )
        if e_capo
        else []
    )

    return render(
        request,
        "assenze/pages/gestione_assenze.html",
        {
            "richieste_personali": richieste_personali,
            "richieste_da_approvare": richieste_da_approvare,
            "richieste_dipendenti_gestite": richieste_dipendenti_gestite,
            "mostra_sezione_dipendenti": e_capo,
            "summary_personali": _summarize_personal_requests(richieste_personali),
            "summary_da_approvare": _summarize_pending_requests(richieste_da_approvare),
            "summary_dipendenti_gestite": _summarize_pending_requests(richieste_dipendenti_gestite),
            "ruolo_corrente": "",
            **get_module_branding_context("assenze", fallback_label="Assenze"),
            **_template_perm_context(request),
        },
    )


@login_required
@ensure_csrf_cookie
def impostazioni_admin(request):
    """Pagina «Impostazioni» del modulo assenze — riservata all'HR-admin.

    Contiene il pannello amministrativo (statistiche globali, gestione di TUTTE le
    assenze con Approva/Rifiuta/Elimina, log attività) e il branding di modulo.
    Gate: capability ACL `admin_assenze`. I profili non-admin vengono rimandati alla
    pagina personale «Le mie richieste».
    """
    if not user_can_modulo_action(request, "assenze", "admin_assenze"):
        from django.shortcuts import redirect
        return redirect("assenze_gestione")

    if request.method == "POST":
        if str(request.POST.get("form") or "").strip() == "flessibilita":
            return _salva_impostazioni_flessibilita(request)

        branding_response = handle_module_branding_post(
            request,
            module_key="assenze",
            redirect_to="assenze_impostazioni",
            audit_module="assenze",
            fallback_label="Assenze",
        )
        if branding_response is not None:
            return branding_response

    perms = _assenze_permissions(request)
    admin_q = (request.GET.get("q_admin") or "").strip()
    admin_overview = _admin_assenze_overview(
        admin_q,
        stato=request.GET.get("stato") or "",
        tipo=request.GET.get("tipo") or "",
        da=request.GET.get("da") or "",
        a=request.GET.get("a") or "",
        page=request.GET.get("page") or 1,
        per_page=request.GET.get("per_page") or ADMIN_PER_PAGE_DEFAULT,
    )
    admin_audit_entries = list(
        AuditLog.objects.filter(modulo="assenze").order_by("-created_at")[:100]
    )

    return render(
        request,
        "assenze/pages/impostazioni.html",
        {
            "is_assenze_admin": True,
            "can_manage_module_branding": True,
            "admin_q": admin_q,
            "admin_tabella_ok": admin_overview.get("tabella_ok", False),
            "admin_stats": admin_overview.get("stats"),
            "admin_by_tipo": admin_overview.get("by_tipo"),
            "admin_sync_info": admin_overview.get("sync_info"),
            "admin_assenze": admin_overview.get("assenze"),
            "admin_filtri": admin_overview.get("filtri"),
            "admin_paginazione": admin_overview.get("paginazione"),
            "admin_tipi_disponibili": admin_overview.get("tipi_disponibili"),
            "admin_stati_disponibili": admin_overview.get("stati_disponibili"),
            "admin_per_page_scelte": admin_overview.get("per_page_scelte"),
            "admin_audit_entries": admin_audit_entries,
            "admin_can_moderate": perms.get("can_update_any", False),
            "admin_can_delete": perms.get("can_delete_any", False),
            **_flessibilita_admin_context(),
            **get_module_branding_context("assenze", fallback_label="Assenze"),
            **_template_perm_context(request),
        },
    )


def _flessibilita_admin_context() -> dict:
    """Dati della sezione «Flessibilità» di Impostazioni."""
    from .models import FlessibilitaAbilitato

    conf = _flessibilita_config()
    abilitati_ids = _flessibilita_abilitati_ids()
    dipendenti = _load_dipendenti_attivi_list()
    elenco = [
        {
            "id": _as_int(d.get("id")),
            "full_name": d.get("full_name") or "",
            "abilitato": _as_int(d.get("id")) in abilitati_ids,
        }
        for d in dipendenti
        if _as_int(d.get("id")) is not None
    ]
    # Chi e' abilitato ma non compare fra gli attivi (es. cessato) resterebbe
    # invisibile: lo mostriamo comunque, altrimenti non si potrebbe togliere.
    noti = {row["id"] for row in elenco}
    for orfano in FlessibilitaAbilitato.objects.exclude(legacy_anagrafica_id__in=noti):
        elenco.append(
            {
                "id": orfano.legacy_anagrafica_id,
                "full_name": orfano.nominativo or f"#{orfano.legacy_anagrafica_id}",
                "abilitato": True,
                "fuori_elenco": True,
            }
        )
    elenco.sort(key=lambda row: str(row.get("full_name") or "").casefold())
    return {
        "flessibilita_orari_entrata": ", ".join(conf.entrate),
        "flessibilita_orari_uscita": ", ".join(conf.uscite),
        "flessibilita_dipendenti": elenco,
        "flessibilita_abilitati_count": len(abilitati_ids),
    }


def _salva_impostazioni_flessibilita(request):
    """Salva orari ammessi ed elenco degli abilitati alla flessibilità."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from .models import FlessibilitaAbilitato, FlessibilitaImpostazioni

    conf = FlessibilitaImpostazioni.get_solo()
    entrate = FlessibilitaImpostazioni._parse(request.POST.get("orari_entrata"))
    uscite = FlessibilitaImpostazioni._parse(request.POST.get("orari_uscita"))
    if not entrate or not uscite:
        messages.error(
            request,
            "Orari flessibilità non salvati: servono almeno un orario di entrata e uno di uscita, in formato HH:MM.",
        )
        return redirect("assenze_impostazioni")

    conf.orari_entrata = ",".join(entrate)
    conf.orari_uscita = ",".join(uscite)
    conf.updated_by = (request.user.get_username() or "")[:200]
    conf.save()

    selezionati: set[int] = set()
    for raw in request.POST.getlist("abilitati"):
        value = _as_int(raw)
        if value is not None and value > 0:
            selezionati.add(value)

    nomi = {
        _as_int(d.get("id")): str(d.get("full_name") or "")
        for d in _load_dipendenti_attivi_list()
    }
    precedenti = _flessibilita_abilitati_ids()
    with transaction.atomic():
        FlessibilitaAbilitato.objects.exclude(legacy_anagrafica_id__in=selezionati).delete()
        for ana_id in sorted(selezionati - precedenti):
            FlessibilitaAbilitato.objects.update_or_create(
                legacy_anagrafica_id=ana_id,
                defaults={
                    "nominativo": (nomi.get(ana_id) or "")[:200],
                    "created_by": (request.user.get_username() or "")[:200],
                },
            )

    log_action(
        request,
        "impostazioni_flessibilita_salvate",
        "assenze",
        {
            "orari_entrata": conf.orari_entrata,
            "orari_uscita": conf.orari_uscita,
            "abilitati": len(selezionati),
            "aggiunti": sorted(selezionati - precedenti),
            "rimossi": sorted(precedenti - selezionati),
        },
    )
    messages.success(
        request,
        f"Flessibilità aggiornata: {len(selezionati)} dipendenti abilitati, "
        f"entrata {', '.join(entrate)} · uscita {', '.join(uscite)}.",
    )
    return redirect("assenze_impostazioni")


def _riconciliazione_csv(items, da, a):
    import csv

    from django.http import HttpResponse

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="riconciliazione_presenze_{da:%Y%m%d}_{a:%Y%m%d}.csv"'
    )
    response.write("﻿")  # BOM per Excel
    writer = safe_csv_writer(response, delimiter=";")
    writer.writerow([
        "Dipendente", "Data presenza", "Ore presenza",
        "Tipo assenza approvata", "ID assenza", "ID presenza",
    ])
    for c in items:
        writer.writerow([
            c.nome,
            c.data.strftime("%d/%m/%Y"),
            c.ore_presenza if c.ore_presenza is not None else "",
            c.tipo_label,
            c.assenza_id if c.assenza_id is not None else "",
            c.presenza_id if c.presenza_id is not None else "",
        ])
    return response


@login_required
def riconciliazione(request):
    """RA1 — incongruenze presenza certificata vs assenza approvata (sola lettura).

    Riservata all'Amministrazione assenze (dato globale, le presenze certificate
    non hanno reparto). Export CSV con ?export=csv. Periodo filtrabile (default:
    dal 1° gennaio dell'anno corrente a oggi).
    """
    perms = _assenze_permissions(request)
    if not (perms.get("can_update_any") or getattr(request.user, "is_superuser", False)):
        return HttpResponseForbidden(
            "Accesso riservato all'Amministrazione assenze."
        )

    from .riconciliazione import conflitti as _conflitti, parse_periodo

    today = timezone.localdate()
    da, a = parse_periodo(
        request.GET.get("da"),
        request.GET.get("a"),
        default_da=today.replace(month=1, day=1),
        default_a=today,
    )
    items = _conflitti(da, a)

    if request.GET.get("export") == "csv":
        return _riconciliazione_csv(items, da, a)

    return render(
        request,
        "assenze/pages/riconciliazione.html",
        {
            "items": items,
            "totale": len(items),
            "da": da,
            "a": a,
            **get_module_branding_context("assenze", fallback_label="Assenze"),
            **_template_perm_context(request),
        },
    )


@login_required
@ensure_csrf_cookie
def car_dashboard(request):
    """Dashboard segnalazioni: per CAR (filtrato per reparto) e per AMMINISTRAZIONE (globale)."""
    perms = _assenze_permissions(request)
    is_admin = perms.get("can_update_any", False)
    is_car = perms.get("can_update_owned", False)
    if not is_admin and not is_car:
        return HttpResponseForbidden("Accesso non consentito: questa pagina è riservata ai Capi Reparto (CAR) e all'Amministrazione.")
    legacy_user_id = perms["legacy_user_id"]
    manager_name, manager_email, _ = _legacy_identity(request)

    pending_scope_raw = str(request.GET.get("scope") or "").strip().lower()
    pending_scope = "mine"
    if is_admin and pending_scope_raw in {"all", "tutte", "global"}:
        pending_scope = "all"
    show_diag = str(request.GET.get("diag") or "").strip().lower() in {"1", "true", "yes", "on"}
    capo_diag = None
    if show_diag:
        capo_diag = _capo_assignment_diagnostics(
            legacy_user_id=legacy_user_id,
            manager_name=manager_name,
            manager_email=manager_email,
        )
        capo_diag["manager_name"] = manager_name
        capo_diag["manager_email"] = manager_email
        capo_diag["legacy_user_id"] = legacy_user_id

    now = timezone.localtime()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    monday = today_start - timedelta(days=today_start.weekday())
    next_monday = monday + timedelta(days=7)

    if is_admin:
        if pending_scope == "all":
            da_gestire = _load_all_pending(limit=100)
        else:
            da_gestire = _load_pending_for_manager(
                legacy_user_id,
                limit=100,
                manager_name=manager_name,
                manager_email=manager_email,
            )
        gestite = _load_all_gestite(limit=50)
        riepilogo_oggi = _load_all_assenze_periodo(today_start, today_end, limit=200)
        riepilogo_settimana = _load_all_assenze_periodo(monday, next_monday, limit=500)
    else:
        da_gestire = _load_pending_for_manager(
            legacy_user_id,
            limit=60,
            manager_name=manager_name,
            manager_email=manager_email,
        )
        gestite = _load_gestite_for_manager(
            legacy_user_id,
            limit=30,
            manager_name=manager_name,
            manager_email=manager_email,
        )
        riepilogo_oggi = _load_assenze_car_periodo(
            legacy_user_id,
            today_start,
            today_end,
            limit=100,
            manager_name=manager_name,
            manager_email=manager_email,
        )
        riepilogo_settimana = _load_assenze_car_periodo(
            legacy_user_id,
            monday,
            next_monday,
            limit=300,
            manager_name=manager_name,
            manager_email=manager_email,
        )

    sync_diag = None
    if show_diag:
        diag_item_ids = [r.get("id") for r in gestite[:8]]
        diag_item_ids.extend(r.get("id") for r in da_gestire[:4])
        sync_diag = _build_sharepoint_sync_diagnostics(diag_item_ids, limit=12)

    return render(
        request,
        "assenze/pages/car_dashboard.html",
        {
            "da_gestire": da_gestire,
            # Solo i tipi effettivamente presenti in coda: una pillola che non
            # filtra niente e' rumore.
            "tipi_in_coda": sorted({str(r.get("tipo") or "").strip() for r in da_gestire if r.get("tipo")}),
            "gestite": gestite,
            "riepilogo_oggi": riepilogo_oggi,
            "riepilogo_settimana": riepilogo_settimana,
            "data_oggi": today_start.strftime("%d-%m-%Y"),
            "data_lunedi": monday.strftime("%d-%m-%Y"),
            "data_domenica": (next_monday - timedelta(days=1)).strftime("%d-%m-%Y"),
            "is_admin_view": is_admin,
            "pending_scope": pending_scope,
            "show_diag": show_diag,
            "capo_diag": capo_diag,
            "sync_diag": sync_diag,
            **_template_perm_context(request),
        },
    )


@login_required
@require_http_methods(["POST"])
def api_car_aggiorna_consenso(request, item_id: int):
    """API per CAR: approva o rifiuta una singola assenza del proprio reparto."""
    perms = _assenze_permissions(request)
    if not perms.get("can_update_owned") and not perms.get("can_update_any"):
        return _json_error("Permessi insufficienti: solo i CAR possono aggiornare il consenso.", status=403)

    current = _get_assenza(item_id)
    if not current:
        return _json_error("Record non trovato.", status=404)
    if not _can_manage_record(request, current, require_delete=False):
        return _json_error("Permessi insufficienti: puoi gestire solo record assegnati al tuo reparto.", status=403)

    managed_error = _sharepoint_managed_error(item_id)
    if managed_error:
        return managed_error

    payload = _request_json(request)
    consenso_raw = (payload.get("consenso") if payload else None) or request.POST.get("consenso") or ""
    consenso = _norm_consenso(consenso_raw)
    if consenso not in {"Approvato", "Rifiutato"}:
        return _json_error("Valore consenso non valido. Usa 'Approvato' o 'Rifiutato'.", status=400)

    note_raw = (payload.get("note_gestione") if payload else None)
    if note_raw is None:
        note_raw = request.POST.get("note_gestione", "")
    note_gestione = str(note_raw or "").strip()

    moderation_status = _CONSENSO_TO_MOD.get(consenso, 2)
    updates = {
        "consenso": consenso,
        "moderation_status": moderation_status,
        "note_gestione": note_gestione,
        "modified_datetime": timezone.now(),
    }
    updates.update(_approval_timestamp_update(consenso, current))
    ok = _update_assenza(
        item_id,
        updates,
    )
    if not ok:
        return _json_error("Aggiornamento non eseguito.", status=500)

    # --- Audit log ---
    try:
        from core.audit import log_action
        log_action(request, "assenza_moderata", "assenze", {
            "item_id": item_id,
            "consenso": consenso,
            "note_gestione": note_gestione,
        })
    except Exception:
        pass

    # --- Notifica all'utente richiedente ---
    try:
        from core.models import Notifica
        from core.legacy_models import UtenteLegacy
        richiedente_id = None
        email_rich = (current.get("email_esterna") or "").strip()
        if email_rich:
            u = UtenteLegacy.objects.filter(email__iexact=email_rich).first()
            if u:
                richiedente_id = u.id
        if richiedente_id:
            stato_label = "approvata" if consenso == "Approvato" else "rifiutata"
            tipo = f"assenza_{stato_label}"
            msg = f"La tua richiesta di assenza è stata {stato_label}."
            if note_gestione and consenso == "Rifiutato":
                msg += f" Nota: {note_gestione}"
            Notifica.objects.create(
                legacy_user_id=richiedente_id,
                tipo=tipo,
                messaggio=msg,
                url_azione="/assenze/richiesta_assenze",
            )
    except Exception:
        logger.exception("Assenze: notifica al richiedente non creata")

    sync_result = _sp_enqueue_upsert(item_id)

    return JsonResponse({"ok": True, "item_id": item_id, "consenso": consenso, "note_gestione": note_gestione, "sync": sync_result})


@login_required
@require_http_methods(["POST"])
def api_admin_assenza_delete(request, item_id: int):
    """API admin: elimina una qualsiasi assenza registrando una nota obbligatoria nel log."""
    perms = _assenze_permissions(request)
    if not perms.get("can_delete_any"):
        return _json_error("Permessi insufficienti: solo l'amministrazione può eliminare le assenze.", status=403)

    current = _get_assenza(item_id)
    if not current:
        return _json_error("Record non trovato.", status=404)

    payload = _request_json(request)
    note_raw = (payload.get("note_gestione") if payload else None)
    if note_raw is None:
        note_raw = request.POST.get("note_gestione", "")
    note_gestione = str(note_raw or "").strip()
    if not note_gestione:
        return _json_error("La nota è obbligatoria per eliminare un'assenza.", status=400)
    managed_error = _sharepoint_managed_error(item_id)
    if managed_error:
        return managed_error

    # Stessa transazione: la coda di eliminazione esiste solo se il record e' davvero cancellato.
    with transaction.atomic():
        _sp_enqueue_delete(item_id, current.get("sharepoint_item_id"))
        if not _delete_assenza(item_id):
            transaction.set_rollback(True)
            return _json_error("Eliminazione non riuscita.", status=500)

    # --- Audit log ---
    try:
        log_action(request, "assenza_eliminata", "assenze", {
            "item_id": item_id,
            "dipendente": str(current.get("copia_nome") or ""),
            "tipo": _tipo_for_display(current.get("tipo_assenza"), current.get("motivazione_richiesta")),
            "note_gestione": note_gestione,
        })
    except Exception:
        pass

    # Notifica eliminazione (best-effort), coerente con api_evento_delete.
    if _as_int(current.get("moderation_status")) == 0:
        try:
            _notify_assenza_deleted(request, current)
        except Exception:
            logger.warning("api_admin_assenza_delete: notifica fallita per id=%s", item_id, exc_info=True)

    return JsonResponse({"ok": True, "item_id": item_id})


@login_required
@ensure_csrf_cookie
def calendario(request):
    perms = _assenze_permissions(request)
    if not perms.get("can_view_calendar"):
        return HttpResponseForbidden("Permessi insufficienti: il tuo gruppo non può visualizzare il calendario assenze.")
    user_key = _user_color_key(request)
    user_colors = _load_colors(user_key=user_key)
    eventi_preview = []
    for event in _load_events(limit=50, colors=user_colors):
        eventi_preview.append(
            {
                "dipendente": event.get("title"),
                "tipo": event.get("extendedProps", {}).get("tipo"),
                "consenso": event.get("extendedProps", {}).get("consenso"),
                "inizio_label": _dt_label(event.get("start")),
                "fine_label": _dt_label(event.get("end")),
            }
        )
    from .htmx_views import _month_nav_ctx, _parse_mese
    from datetime import date
    mese_date = _parse_mese(request.GET.get("mese", timezone.localdate().strftime("%Y-%m")))
    return render(request, "assenze/pages/calendario.html", {
        "eventi_preview": eventi_preview,
        **_month_nav_ctx(mese_date),
        **_template_perm_context(request),
    })


@login_required
@require_http_methods(["GET"])
def api_eventi(request):
    perms = _assenze_permissions(request)
    if not perms.get("can_view_calendar"):
        return _json_error("Permessi insufficienti: calendario non disponibile per il tuo gruppo.", status=403)
    try:
        user_key = _user_color_key(request)
        user_colors = _load_colors(user_key=user_key)
        start = _parse_input_dt(request.GET.get("start"))
        end = _parse_input_dt(request.GET.get("end"))
        raw_limit = request.GET.get("limit", getattr(settings, "ASSENZE_CALENDAR_MAX_EVENTS", 1500))
        try:
            limit = int(raw_limit or 1500)
        except (TypeError, ValueError):
            limit = 1500
        limit = max(100, min(limit, 8000))
        return JsonResponse(
            _load_events(
                limit=limit, start=start, end=end, colors=user_colors,
                include_sensitive=bool(perms.get("can_update_any")),
            ),
            safe=False,
        )
    except Exception as exc:
        return _json_error(str(exc), status=500)


@login_required
@require_http_methods(["GET", "POST"])
def api_eventi_colors(request):
    if not _assenze_permissions(request).get("can_view_calendar"):
        return _json_error("Permessi insufficienti: colori calendario non disponibili per il tuo gruppo.", status=403)
    user_key = _user_color_key(request)
    if request.method == "GET":
        colors = _load_colors(user_key=user_key)
        return JsonResponse({"ok": True, "scope": "user", "colors": colors, "defaults": dict(_DEFAULT_COLORS)})

    payload = _request_json(request)
    color_map = payload.get("colors") if isinstance(payload, dict) else None
    if not isinstance(color_map, dict):
        return _json_error("Body JSON non valido: campo 'colors' mancante", status=400)

    for key, value in color_map.items():
        key_txt = str(key or "").strip()
        value_txt = str(value or "").strip()
        if key_txt in _COLOR_KEYS and not _COLOR_RE.match(value_txt):
            return _json_error(f"Formato colore non valido per '{key_txt}'", status=400)

    colors = _save_colors(color_map, user_key=user_key)
    return JsonResponse({"ok": True, "scope": "user", "colors": colors, "defaults": dict(_DEFAULT_COLORS)})

@login_required
@require_http_methods(["POST"])
def api_evento_update(request, item_id: int | None = None):
    perms = _assenze_permissions(request)
    if not perms.get("can_edit_events"):
        return _json_error("Permessi insufficienti: modifica record non consentita.", status=403)

    payload = _request_json(request)
    target_id = item_id or _as_int(payload.get("item_id")) or _as_int(request.POST.get("item_id"))
    if target_id is None:
        return _json_error("item_id mancante", status=400)

    current = _get_assenza(target_id)
    if not current:
        return _json_error("Record non trovato", status=404)
    if not _can_manage_record(request, current, require_delete=False):
        return _json_error("Permessi insufficienti: puoi modificare solo record assegnati a te come capo reparto.", status=403)
    managed_error = _sharepoint_managed_error(target_id)
    if managed_error:
        return managed_error

    requested_tipo = (
        (payload.get("tipo") if payload else None)
        or request.POST.get("tipo")
        or _tipo_for_display(current.get("tipo_assenza"), current.get("motivazione_richiesta"))
    )
    tipo = _tipo_for_storage(requested_tipo)
    if perms.get("can_update_any"):
        consenso = _norm_consenso((payload.get("consenso") if payload else None) or request.POST.get("consenso") or current.get("consenso"))
        moderation_status = _CONSENSO_TO_MOD.get(consenso, 2)
    else:
        consenso = _norm_consenso(current.get("consenso"))
        moderation_status = _as_int(current.get("moderation_status"))
        if moderation_status is None:
            moderation_status = _CONSENSO_TO_MOD.get(consenso, 2)
    inizio_raw = (payload.get("inizio") if payload else None) or request.POST.get("inizio")
    fine_raw = (payload.get("fine") if payload else None) or request.POST.get("fine")
    motivazione = (payload.get("motivazione") if payload else None)
    if motivazione is None:
        motivazione = request.POST.get("motivazione", current.get("motivazione_richiesta") or "")
    motivazione = _motivazione_for_storage(requested_tipo, motivazione)
    certificato_medico = payload.get("certificato_medico") if payload and "certificato_medico" in payload else None
    if certificato_medico is None:
        certificato_medico = request.POST.get("certificato_medico", current.get("certificato_medico") or "")
    certificato_medico = _certificato_medico_for_tipo(tipo, certificato_medico)

    dt_start = _parse_input_dt(inizio_raw) if inizio_raw else current.get("data_inizio")
    dt_end = _parse_input_dt(fine_raw) if fine_raw else current.get("data_fine")
    dt_end, auto_fine_msg = _autocorreggi_fine(dt_start, dt_end)
    err_msg, warn_msg = _validate_business_rules(
        tipo=tipo,
        dt_start=dt_start,
        dt_end=dt_end,
        person_name=str(current.get("copia_nome") or ""),
        person_email=str(current.get("email_esterna") or ""),
        person_anagrafica_id=_anagrafica_id_for_assenza_row(current),
        exclude_item_id=target_id,
    )
    if err_msg:
        return _json_error(err_msg, status=400)

    updates = {
        "tipo_assenza": tipo,
        "consenso": consenso,
        "moderation_status": moderation_status,
        "data_inizio": dt_start,
        "data_fine": dt_end,
        "motivazione_richiesta": motivazione,
        "certificato_medico": certificato_medico,
        "modified_datetime": timezone.now(),
    }
    if perms.get("can_update_any"):
        updates.update(_approval_timestamp_update(consenso, current))
    ok = _update_assenza(target_id, updates)
    if not ok:
        return _json_error("Aggiornamento non eseguito", status=500)

    sync_result = _sp_enqueue_upsert(target_id)

    return JsonResponse({
        "ok": True,
        "item_id": target_id,
        "sync": sync_result,
        "warning": " ".join(x for x in [auto_fine_msg, warn_msg] if x),
    })


@login_required
@require_http_methods(["POST"])
def api_evento_delete(request, item_id: int | None = None):
    perms = _assenze_permissions(request)
    can_delete_any = perms.get("can_delete_any", False)

    payload = _request_json(request)
    target_id = item_id or _as_int(payload.get("item_id")) or _as_int(request.POST.get("item_id"))
    if target_id is None:
        return _json_error("item_id mancante", status=400)

    current = _get_assenza(target_id)
    if not current:
        return _json_error("Record non trovato", status=404)

    if not can_delete_any:
        # Utenti non-admin possono eliminare solo le proprie richieste.
        if not perms.get("can_insert"):
            return _json_error("Permessi insufficienti: eliminazione record non consentita.", status=403)
        name, email, legacy_user_id = _legacy_identity(request)
        username = str(request.user.get_username() or "").strip()
        rec_utente_id = _as_int(current.get("utente_id"))
        rec_username = str(current.get("aliasusername") or "").strip()
        rec_email = str(current.get("email_esterna") or "").strip()
        rec_nome = str(current.get("copia_nome") or "").strip()
        # Proprieta' del record: si privilegiano gli identificatori UNIVOCI
        # (utente_id legacy, poi username, poi email). Il confronto sul nome
        # visualizzato e' solo fallback per i record legacy privi di id/username:
        # da solo non e' affidabile (omonimie) e non deve abilitare la delete
        # quando esiste un identificatore univoco che invece non combacia.
        if legacy_user_id is not None and rec_utente_id is not None:
            is_own = rec_utente_id == legacy_user_id
        elif username and rec_username:
            is_own = rec_username.casefold() == username.casefold()
        elif email and rec_email:
            is_own = rec_email.casefold() == email.casefold()
        else:
            is_own = bool(name) and rec_nome.casefold() == str(name).strip().casefold()
        if not is_own:
            return _json_error("Permessi insufficienti: puoi eliminare solo le tue richieste.", status=403)
    managed_error = _sharepoint_managed_error(target_id)
    if managed_error:
        return managed_error

    # Stessa transazione: la coda di eliminazione esiste solo se il record e' davvero cancellato.
    with transaction.atomic():
        _sp_enqueue_delete(target_id, current.get("sharepoint_item_id"))
        if not _delete_assenza(target_id):
            transaction.set_rollback(True)
            return _json_error("Eliminazione non riuscita", status=500)

    # Notifica mail SOLO per richieste gia' approvate (moderation_status == 0;
    # default 2 = in attesa). Best-effort: un errore mail non deve ribaltare
    # l'eliminazione gia' avvenuta.
    if _as_int(current.get("moderation_status")) == 0:
        try:
            _notify_assenza_deleted(request, current)
        except Exception:
            logger.warning(
                "api_evento_delete: notifica eliminazione fallita per id=%s",
                target_id,
                exc_info=True,
            )

    return JsonResponse({"ok": True, "item_id": target_id})


def _notify_assenza_deleted(request, record: dict) -> None:
    """Costruisce destinatari/contesto e invia l'avviso di eliminazione.

    Risolve l'email del capo reparto dai lookup del record e l'identita' di chi
    esegue l'eliminazione; delega l'invio a mail_delete_service (fail-open).
    """
    from .mail_delete_service import send_assenza_deleted_notification

    capi = _load_capi_options()
    capo_email = _resolve_capo_option_value_from_ids(
        local_id=_as_int(record.get("capo_reparto_id")),
        lookup_id=_as_int(record.get("capo_reparto_lookup_id")),
        capi=capi,
    )
    deleted_by_name, deleted_by_email, _ = _legacy_identity(request)
    tipo_display = _tipo_for_display(
        record.get("tipo_assenza"), record.get("motivazione_richiesta")
    )
    send_assenza_deleted_notification(
        record,
        tipo_display=tipo_display,
        capo_email=capo_email,
        deleted_by_name=deleted_by_name,
        deleted_by_email=deleted_by_email,
    )


@login_required
@require_http_methods(["POST"])
def api_mia_assenza_update(request, item_id: int):
    """Consente a un utente di modificare la propria richiesta ancora 'In attesa'."""
    perms = _assenze_permissions(request)
    if not perms.get("can_insert"):
        return _json_error("Permessi insufficienti.", status=403)

    current = _get_assenza(item_id)
    if not current:
        return _json_error("Record non trovato.", status=404)

    # Verifica appartenenza: solo la propria richiesta
    name, email, _ = _legacy_identity(request)
    rec_nome = str(current.get("copia_nome") or "").strip().upper()
    rec_email = str(current.get("email_esterna") or "").strip().upper()
    user_nome = str(name or "").strip().upper()
    user_email = str(email or "").strip().upper()
    is_own = (user_nome and rec_nome == user_nome) or (user_email and rec_email == user_email)
    if not is_own:
        return _json_error("Puoi modificare solo le tue richieste.", status=403)

    # Deve essere ancora In attesa
    mod_status = _as_int(current.get("moderation_status"))
    if mod_status is None:
        mod_status = _CONSENSO_TO_MOD.get(_norm_consenso(current.get("consenso")), 2)
    if mod_status != 2:
        return _json_error("La richiesta non è più modificabile (non è in stato 'In attesa').", status=400)
    managed_error = _sharepoint_managed_error(item_id)
    if managed_error:
        return managed_error

    payload = _request_json(request)
    requested_tipo = (
        (payload.get("tipo") if payload else None)
        or request.POST.get("tipo")
        or _tipo_for_display(current.get("tipo_assenza"), current.get("motivazione_richiesta"))
    )
    tipo = _tipo_for_storage(requested_tipo)
    inizio_raw = (payload.get("inizio") if payload else None) or request.POST.get("inizio")
    fine_raw = (payload.get("fine") if payload else None) or request.POST.get("fine")
    motivazione = (payload.get("motivazione") if payload else None)
    if motivazione is None:
        motivazione = request.POST.get("motivazione", current.get("motivazione_richiesta") or "")
    motivazione = _motivazione_for_storage(requested_tipo, motivazione)
    certificato_medico = payload.get("certificato_medico") if payload and "certificato_medico" in payload else None
    if certificato_medico is None:
        certificato_medico = request.POST.get("certificato_medico", current.get("certificato_medico") or "")
    certificato_medico = _certificato_medico_for_tipo(tipo, certificato_medico)

    dt_start = _parse_input_dt(inizio_raw) if inizio_raw else current.get("data_inizio")
    dt_end = _parse_input_dt(fine_raw) if fine_raw else current.get("data_fine")
    dt_end, auto_fine_msg = _autocorreggi_fine(dt_start, dt_end)

    err_msg, warn_msg = _validate_business_rules(
        tipo=tipo,
        dt_start=dt_start,
        dt_end=dt_end,
        person_name=str(current.get("copia_nome") or ""),
        person_email=str(current.get("email_esterna") or ""),
        person_anagrafica_id=_anagrafica_id_for_assenza_row(current),
        exclude_item_id=item_id,
    )
    if err_msg:
        return _json_error(err_msg, status=400)

    ok = _update_assenza(
        item_id,
        {
            "tipo_assenza": tipo,
            "data_inizio": dt_start,
            "data_fine": dt_end,
            "motivazione_richiesta": motivazione,
            "certificato_medico": certificato_medico,
            "modified_datetime": timezone.now(),
        },
    )
    if not ok:
        return _json_error("Aggiornamento non eseguito.", status=500)

    sync_result = _sp_enqueue_upsert(item_id)

    return JsonResponse({
        "ok": True,
        "item_id": item_id,
        "warning": " ".join(x for x in [auto_fine_msg, warn_msg] if x),
        "sync": sync_result,
    })


@login_required
@require_http_methods(["POST"])
def invio_placeholder(request):
    if not _has_valid_submit_token(request, request.POST.get("submit_token"), "assenze_invio"):
        return HttpResponseForbidden("Token invio non valido.")

    perms = _assenze_permissions(request)
    if not perms.get("can_insert"):
        return HttpResponseForbidden("Permessi insufficienti: inserimento richieste non consentito.")
    if not _table_exists("assenze"):
        return _render_richiesta(request, error="Tabella locale 'assenze' non disponibile.")

    requested_tipo = request.POST.get("tipoassenza")
    tipo = _tipo_for_storage(requested_tipo)
    motivazione = _motivazione_for_storage(requested_tipo, request.POST.get("motivazione"))
    certificato_medico = _certificato_medico_for_tipo(tipo, request.POST.get("certificato_medico"))
    date_start = str(request.POST.get("date_start") or "").strip()
    date_end = str(request.POST.get("date_end") or "").strip()
    time_start = str(request.POST.get("time_start") or "00:00").strip() or "00:00"
    time_end = str(request.POST.get("time_end") or "23:59").strip() or "23:59"
    capo_raw = str(request.POST.get("caporeparto") or "").strip()
    shortcut = str(request.POST.get("shortcut") or "").strip()
    salta_approvazione = bool(_as_bool(request.POST.get("salta_approvazione"))) if perms.get("can_skip_approval") else False
    tipo_ui = _norm_tipo(tipo)

    if tipo_ui == "Ferie":
        time_start = "00:00"
        time_end = "23:59"

    if not date_start or not date_end:
        return _render_richiesta(request, error="Compila data inizio e data fine.", form_data=request.POST.dict())

    try:
        start_local = datetime.strptime(f"{date_start} {time_start}", "%Y-%m-%d %H:%M")
        end_local = datetime.strptime(f"{date_end} {time_end}", "%Y-%m-%d %H:%M")
    except ValueError:
        return _render_richiesta(request, error="Formato data/ora non valido.", form_data=request.POST.dict())

    dt_start = start_local
    dt_end, auto_fine_msg = _autocorreggi_fine(start_local, end_local)

    if tipo_ui == "Permesso" and dt_start.date() != dt_end.date():
        return _render_richiesta(
            request,
            error="Il permesso deve iniziare e finire nello stesso giorno.",
            form_data=request.POST.dict(),
        )

    inserter_name, inserter_email, inserter_legacy_id = _legacy_identity(request)
    inserting_for_other = False
    dipendente_id_raw = str(request.POST.get("dipendente_id") or "").strip()

    if perms.get("can_insert_for_others") and dipendente_id_raw:
        ana_id = _as_int(dipendente_id_raw)
        if not ana_id:
            return _render_richiesta(request, error="ID dipendente non valido.", form_data=request.POST.dict())
        if not _can_insert_for_dipendente(request, ana_id):
            return _render_richiesta(
                request,
                error="Non sei autorizzato a inserire richieste per un altro dipendente.",
                form_data=request.POST.dict(),
            )
        identity = _resolve_employee_identity_from_anagrafica(ana_id)
        if not identity:
            return _render_richiesta(request, error="Dipendente selezionato non trovato in anagrafica.", form_data=request.POST.dict())
        display_name, email, legacy_id = identity
        person_anagrafica_id = ana_id
        inserting_for_other = True
    else:
        display_name = _resolve_request_display_name(
            legacy_user_id=inserter_legacy_id,
            email=inserter_email,
            username=request.user.get_username(),
            fallback_name=inserter_name,
        )
        email = inserter_email
        legacy_id = inserter_legacy_id
        person_anagrafica_id = _resolve_anagrafica_employee_id_for_user(
            legacy_user_id=legacy_id,
            email=email,
            username=request.user.get_username(),
            name=display_name,
        )

    err_msg, warn_msg = _validate_business_rules(
        tipo=tipo,
        dt_start=dt_start,
        dt_end=dt_end,
        person_name=display_name,
        person_email=email,
        person_anagrafica_id=person_anagrafica_id,
        shortcut=shortcut,
    )
    warn_msg = " ".join(x for x in [auto_fine_msg, warn_msg] if x)
    if err_msg:
        return _render_richiesta(request, error=err_msg, form_data=request.POST.dict())

    # Caporeparto AUTORITATIVO lato server: quello assegnato al dipendente (il
    # campo del form è bloccato). Se quel caporeparto è assente nel giorno di
    # inizio, l'approvazione passa al suo superiore. Fallback al valore del form
    # solo se il server non riesce a risolvere (compatibilità).
    capi_options = _load_capi_options()
    capo_username = "" if inserting_for_other else request.user.get_username()
    capo_effective, capo_escalated = _effective_capo_option(
        name=display_name,
        email=email,
        username=capo_username,
        legacy_user_id=legacy_id,
        capi=capi_options,
        request_day=dt_start.date(),
    )
    capo_final = capo_effective or capo_raw

    payload = {
        "sharepoint_item_id": None,
        "nome_lookup_id": _resolve_nome_lookup_id(legacy_id, display_name),
        "copia_nome": display_name,
        "email_esterna": email,
        "tipo_assenza": tipo,
        "capo_reparto_id": _resolve_capo_local_id(capo_final),
        "capo_reparto_lookup_id": _resolve_capo_lookup_id(capo_final),
        "data_inizio": dt_start,
        "data_fine": dt_end,
        "motivazione_richiesta": motivazione,
        "certificato_medico": certificato_medico,
        "salta_approvazione": salta_approvazione,
        "consenso": "In attesa",
        "moderation_status": 2,
        "created_datetime": timezone.now(),
        "modified_datetime": timezone.now(),
    }

    try:
        with transaction.atomic():
            local_id = _insert_assenza(payload)
    except Exception as exc:
        return _render_richiesta(request, error=f"Errore salvataggio locale: {exc}", form_data=request.POST.dict())

    if local_id is None:
        return _render_richiesta(request, error="Richiesta non salvata: impossibile ottenere ID locale.", form_data=request.POST.dict())

    if inserting_for_other:
        log_action(
            request,
            "assenza_inserita_per_conto",
            "assenze",
            {"local_id": local_id, "for_dipendente": display_name, "by": inserter_name},
        )

    if capo_escalated:
        log_action(
            request,
            "assenza_escalation_caporeparto",
            "assenze",
            {"local_id": local_id, "motivo": "caporeparto assente nel giorno", "capo_effettivo": capo_final},
        )

    sync_msg = "Sincronizzazione SharePoint non configurata."
    if _sp_enqueue_upsert(local_id).get("queued"):
        sync_msg = "Arriverà su SharePoint entro pochi minuti."

    warn_suffix = f" {warn_msg}" if warn_msg else ""
    proxy_note = f" (inserito per conto di {display_name})" if inserting_for_other else ""
    return _render_richiesta(request, success=f"Richiesta registrata su DB locale{proxy_note}. {sync_msg}{warn_suffix}")


@login_required
@require_http_methods(["POST"])
def aggiorna_consenso_placeholder(request, item_id: int):
    if not _assenze_permissions(request).get("can_update_any"):
        return _json_error("Permessi insufficienti: aggiornamento consenso non consentito.", status=403)
    managed_error = _sharepoint_managed_error(item_id)
    if managed_error:
        return managed_error
    consenso = _norm_consenso(request.POST.get("consenso"))
    updates = {
        "consenso": consenso,
        "moderation_status": _CONSENSO_TO_MOD.get(consenso, 2),
        "modified_datetime": timezone.now(),
    }
    updates.update(_approval_timestamp_update(consenso))
    ok = _update_assenza(
        item_id,
        updates,
    )
    if ok:
        _sp_enqueue_upsert(item_id)
    return JsonResponse({"ok": bool(ok), "item_id": item_id, "consenso": consenso})


@login_required
@require_http_methods(["GET", "POST"])
def api_sync_push(request):
    if not _assenze_permissions(request).get("can_update_any"):
        return _json_error("Permessi insufficienti: sync push consentito solo ad AMMINISTRAZIONE.", status=403)
    payload = _request_json(request)
    limit_raw = payload.get("limit_rows") if payload else request.GET.get("limit_rows", request.POST.get("limit_rows", 30))
    include_updates_raw = payload.get("include_updates") if payload else request.GET.get("include_updates", request.POST.get("include_updates", "0"))
    try:
        limit_rows = int(limit_raw or 30)
    except (TypeError, ValueError):
        limit_rows = 30
    include_updates = _as_bool(include_updates_raw)

    result = _sync_push(limit_rows=limit_rows, include_updates=include_updates)
    return JsonResponse(result, status=200 if result.get("ok") else 500)


@login_required
@require_http_methods(["GET", "POST"])
def api_sync_pull(request):
    if not _assenze_permissions(request).get("can_view_calendar"):
        return _json_error("Permessi insufficienti: sync pull non consentito per il tuo gruppo.", status=403)
    payload = _request_json(request)
    force_raw = payload.get("force") if payload else request.GET.get("force", request.POST.get("force", "0"))
    result = _maybe_pull(force=_as_bool(force_raw))
    return JsonResponse(result, status=200 if result.get("ok", True) else 500)


# ─────────────────────────────────────────────────────────────────────────────
# Export CSV
# ─────────────────────────────────────────────────────────────────────────────

import csv
from django.http import StreamingHttpResponse


class _Echo:
    """Pseudo-buffer per StreamingHttpResponse con csv.writer."""
    def write(self, value):
        return value


def _csv_streaming_response(rows_iter, headers: list[str], filename: str) -> StreamingHttpResponse:
    writer = safe_csv_writer(_Echo())

    def stream():
        yield writer.writerow(headers)
        for row in rows_iter:
            yield writer.writerow(row)

    resp = StreamingHttpResponse(bom_first(stream()), content_type=CSV_CONTENT_TYPE)
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@login_required
def export_assenze_car_csv(request):
    """Esporta in CSV le assenze del reparto del CAR loggato (o tutte per AMMIN)."""
    perms = _assenze_permissions(request)
    if not perms.get("can_update_owned") and not perms.get("can_update_any"):
        return HttpResponseForbidden("Permessi insufficienti.")

    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    legacy_user_id = int(legacy_user.id) if legacy_user else None
    manager_name = (
        str(getattr(legacy_user, "nome", "") or "").strip()
        if legacy_user
        else (request.user.get_full_name() or request.user.get_username() or "").strip()
    )
    manager_email = (
        str(getattr(legacy_user, "email", "") or "").strip()
        if legacy_user
        else (request.user.email or "").strip()
    )

    if perms.get("can_update_any"):
        rows_data = _load_all_pending(limit=5000) + _load_all_gestite(limit=5000)
    else:
        rows_data = _load_pending_for_manager(
            legacy_user_id,
            limit=5000,
            manager_name=manager_name,
            manager_email=manager_email,
        ) + _load_gestite_for_manager(
            legacy_user_id,
            limit=5000,
            manager_name=manager_name,
            manager_email=manager_email,
        )
    log_action(
        request,
        "export_csv",
        "assenze",
        {
            "rows": len(rows_data),
            "filters": {
                "scope": "all" if perms.get("can_update_any") else "owned_manager",
                "legacy_user_id": legacy_user_id,
                "manager_name": manager_name,
                "manager_email": manager_email,
                "limit": 5000,
            },
        },
    )

    headers = ["Dipendente", "Tipo", "Inizio", "Fine", "Stato", "Certificato medico", "Note"]

    def row_iter():
        for r in rows_data:
            yield [
                r.get("dipendente", ""),
                r.get("tipo", ""),
                r.get("inizio_label", ""),
                r.get("fine_label", ""),
                r.get("consenso", ""),
                r.get("certificato_medico", ""),
                r.get("note_gestione", ""),
            ]

    return _csv_streaming_response(row_iter(), headers, "assenze_reparto.csv")


@login_required
def export_gestione_assenze_csv(request):
    """Esporta in CSV le proprie assenze (vista gestione personale)."""
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    nome = getattr(legacy_user, "nome", "") or ""
    email = getattr(legacy_user, "email", "") or ""
    rows_data = _load_personal(nome, email, limit=5000)
    log_action(
        request,
        "export_csv",
        "assenze",
        {
            "rows": len(rows_data),
            "filters": {
                "scope": "personal",
                "nome": nome,
                "email": email,
                "limit": 5000,
            },
        },
    )

    headers = ["Tipo", "Inizio", "Fine", "Stato", "Motivazione", "Certificato medico", "Note"]

    def row_iter():
        for r in rows_data:
            yield [
                r.get("tipo", ""),
                r.get("inizio", ""),
                r.get("fine", ""),
                r.get("stato", ""),
                r.get("motivazione", ""),
                r.get("certificato_medico", ""),
                r.get("note_gestione", ""),
            ]

    return _csv_streaming_response(row_iter(), headers, "mie_assenze.csv")


ADMIN_STATI = {
    "in_attesa": ("In attesa", 2),
    "approvate": ("Approvate", 0),
    "rifiutate": ("Rifiutate", 1),
}
ADMIN_PER_PAGE_SCELTE = (25, 50, 100, 200)
ADMIN_PER_PAGE_DEFAULT = 25


def _admin_assenze_overview(
    q: str = "",
    *,
    stato: str = "",
    tipo: str = "",
    da: str = "",
    a: str = "",
    page: int = 1,
    per_page: int = ADMIN_PER_PAGE_DEFAULT,
) -> dict:
    """Panoramica admin del modulo assenze.

    Statistiche globali, distribuzione per tipo e **una pagina** di record
    filtrati. Prima venivano caricate in pagina fino a 5000 righe perche' la
    ricerca era client-side: su uno storico reale significa un documento enorme
    da scaricare e da rendere a ogni apertura delle Impostazioni, per poi
    guardarne venti. Filtri, ordinamento e paginazione sono ora lato server, e
    la ricerca copre comunque l'intero storico perche' e' una WHERE, non un
    filtro sul DOM.
    """
    tabella_ok = _table_exists("assenze")
    stats = {"total": 0, "in_attesa": 0, "approvate": 0, "rifiutate": 0}
    by_tipo: list[dict] = []
    from .models import AssenzaSharePointOutbox

    last_pull_ts = _as_int(cache.get(_SYNC_PULL_LAST_TS_KEY))
    sync_info = {
        "last_pull": (
            timezone.localtime(datetime.fromtimestamp(last_pull_ts, tz=dt_timezone.utc)).strftime("%d/%m/%Y %H:%M")
            if last_pull_ts else None
        ),
        "pending": AssenzaSharePointOutbox.objects.count(),
        "failing": AssenzaSharePointOutbox.objects.filter(tentativi__gt=0).count(),
    }

    stato = str(stato or "").strip().lower()
    if stato not in ADMIN_STATI:
        stato = ""
    tipo = str(tipo or "").strip()
    q = str(q or "").strip()
    da_dt = _parse_input_dt(f"{da}T00:00") if str(da or "").strip() else None
    a_dt = _parse_input_dt(f"{a}T23:59") if str(a or "").strip() else None
    try:
        per_page = int(per_page)
    except (TypeError, ValueError):
        per_page = ADMIN_PER_PAGE_DEFAULT
    if per_page not in ADMIN_PER_PAGE_SCELTE:
        per_page = ADMIN_PER_PAGE_DEFAULT
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1

    risultato = {
        "tabella_ok": tabella_ok,
        "stats": stats,
        "by_tipo": by_tipo,
        "sync_info": sync_info,
        "assenze": [],
        "filtri": {
            "q": q,
            "stato": stato,
            "tipo": tipo,
            "da": str(da or "").strip(),
            "a": str(a or "").strip(),
            "per_page": per_page,
            "attivi": bool(q or stato or tipo or da or a),
        },
        "tipi_disponibili": [],
        "stati_disponibili": [{"key": k, "label": v[0]} for k, v in ADMIN_STATI.items()],
        "per_page_scelte": list(ADMIN_PER_PAGE_SCELTE),
        "paginazione": {
            "page": 1, "pages": 1, "per_page": per_page, "total": 0,
            "da_riga": 0, "a_riga": 0, "ha_prec": False, "ha_succ": False,
            "prec": 1, "succ": 1,
        },
    }
    if not tabella_ok:
        return risultato

    def _count_sql(where="", count_params=None):
        sql = "SELECT COUNT(*) FROM assenze" + (f" WHERE {where}" if where else "")
        with connections["default"].cursor() as cur:
            cur.execute(sql, count_params or [])
            return cur.fetchone()[0]

    stats["total"] = _count_sql()
    stats["in_attesa"] = _count_sql("COALESCE(moderation_status, 2) = 2")
    stats["approvate"] = _count_sql("COALESCE(moderation_status, 2) = 0")
    stats["rifiutate"] = _count_sql("COALESCE(moderation_status, 2) = 1")

    tipo_sql = _select_limited(
        "SELECT tipo_assenza, motivazione_richiesta, COUNT(*) AS n FROM assenze GROUP BY tipo_assenza, motivazione_richiesta",
        "ORDER BY n DESC",
        30,
    )
    by_tipo_counts: dict[str, int] = {}
    for row in _fetch_all_dict(tipo_sql):
        tipo_label = _tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta"))
        by_tipo_counts[tipo_label] = by_tipo_counts.get(tipo_label, 0) + int(row.get("n") or 0)
    by_tipo = [
        {"tipo_assenza": t, "n": c}
        for t, c in sorted(by_tipo_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    risultato["by_tipo"] = by_tipo
    risultato["tipi_disponibili"] = [r["tipo_assenza"] for r in by_tipo]

    where_parts: list[str] = []
    params: list = []
    if q:
        where_parts.append(
            "(UPPER(COALESCE(copia_nome,'')) LIKE UPPER(%s)"
            " OR UPPER(COALESCE(tipo_assenza,'')) LIKE UPPER(%s)"
            " OR UPPER(COALESCE(motivazione_richiesta,'')) LIKE UPPER(%s))"
        )
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if stato:
        where_parts.append("COALESCE(moderation_status, 2) = %s")
        params.append(ADMIN_STATI[stato][1])
    if tipo:
        # Il tipo mostrato puo' derivare dalla motivazione ("Certifica presenza"
        # e' persistita come "Altro"): si filtra su entrambe le colonne.
        where_parts.append(
            "(UPPER(COALESCE(tipo_assenza,'')) = UPPER(%s)"
            " OR UPPER(COALESCE(motivazione_richiesta,'')) LIKE UPPER(%s))"
        )
        params.extend([tipo, f"%{tipo}%"])
    if da_dt is not None:
        # Periodi che si intersecano: una richiesta iniziata prima della finestra
        # ma ancora in corso dentro la finestra va mostrata.
        where_parts.append("data_fine >= %s")
        params.append(da_dt)
    if a_dt is not None:
        where_parts.append("data_inizio <= %s")
        params.append(a_dt)
    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    total = _count_sql(" AND ".join(where_parts) if where_parts else "", params)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    offset = (page - 1) * per_page

    base_sql = f"""
        SELECT
            id, copia_nome AS dipendente, tipo_assenza,
            data_inizio, data_fine, consenso,
            moderation_status, motivazione_richiesta
        FROM assenze
        {where_clause}
    """
    sql = _select_paginated(base_sql, "ORDER BY data_inizio DESC, id DESC", offset=offset, limit=per_page)

    assenze: list[dict] = []
    for row in _fetch_all_dict(sql, params):
        _, mod_label = _status_from_moderation(row.get("moderation_status"), default_pending=True)
        assenze.append({
            "id": row.get("id"),
            "dipendente": str(row.get("dipendente") or "N/D"),
            "tipo": _tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta")),
            "stato_label": mod_label,
            "moderation_status": row.get("moderation_status"),
            "inizio_label": _dt_label(row.get("data_inizio")),
            "fine_label": _dt_label(row.get("data_fine")),
            "motivo": _strip_tipo_metadata_from_motivazione(row.get("motivazione_richiesta")),
        })
    _mark_sharepoint_managed(assenze)

    risultato["assenze"] = assenze
    risultato["paginazione"] = {
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "total": total,
        "da_riga": offset + 1 if total else 0,
        "a_riga": min(offset + per_page, total),
        "ha_prec": page > 1,
        "ha_succ": page < pages,
        "prec": max(1, page - 1),
        "succ": min(pages, page + 1),
    }
    return risultato


@legacy_admin_or_acl_required("assenze", "gestione_admin")
def gestione_admin(request):
    """Deprecato: il pannello admin è ora unificato nelle Impostazioni assenze.

    Mantenuto come redirect per retrocompatibilità di eventuali bookmark/URL.
    """
    from django.shortcuts import redirect
    return redirect("assenze_impostazioni")


# ---------------------------------------------------------------------------
# Certificazione Presenza
# ---------------------------------------------------------------------------

@login_required
def certificazione_presenza(request):
    from .models import CertificazionePresenza

    is_admin = user_can_modulo_action(request, "assenze", "admin_assenze")
    # SEC: la certificazione presenze è una funzione amministrativa. Senza questo
    # enforcement la pagina elencava TUTTE le CertificazionePresenza e permetteva
    # create/update/delete (con auto-inserimento di un'assenza già "Approvato",
    # salta_approvazione=True, per un dipendente arbitrario) a qualsiasi utente
    # autenticato, scavalcando l'approvazione CAR. Il permesso era già calcolato
    # ma mai applicato.
    if not is_admin:
        return render(request, "core/pages/forbidden.html", status=403)
    perm_ctx = _template_perm_context(request)

    # Filtri lista
    q_nome   = (request.GET.get("q_nome")   or "").strip()
    q_data_da = request.GET.get("q_data_da") or ""
    q_data_a  = request.GET.get("q_data_a")  or ""

    qs = CertificazionePresenza.objects.all()
    if q_nome:
        qs = qs.filter(nome_dipendente__icontains=q_nome)
    if q_data_da:
        try:
            from datetime import date
            qs = qs.filter(data__gte=date.fromisoformat(q_data_da))
        except ValueError:
            pass
    if q_data_a:
        try:
            from datetime import date
            qs = qs.filter(data__lte=date.fromisoformat(q_data_a))
        except ValueError:
            pass

    records = list(qs[:200])

    # Lista dipendenti per il select: solo attivi e senza duplicati sul nome visualizzato.
    dipendenti_nomi = _certificazione_presenza_dipendenti_attivi()

    form_errors: dict = {}
    form_success = False
    edit_obj = None

    # Gestione edit (GET con ?edit=id)
    edit_id = request.GET.get("edit") or ""
    if edit_id and edit_id.isdigit():
        try:
            edit_obj = CertificazionePresenza.objects.get(pk=int(edit_id))
        except CertificazionePresenza.DoesNotExist:
            edit_obj = None

    if request.method == "POST":
        action = request.POST.get("action", "create")
        pk_raw = request.POST.get("pk", "")

        # --- DELETE ---
        if action == "delete" and pk_raw.isdigit():
            try:
                obj = CertificazionePresenza.objects.get(pk=int(pk_raw))
                obj.delete()
                log_action(request, "certifica_presenza_delete", {"pk": pk_raw})
            except CertificazionePresenza.DoesNotExist:
                pass
            from django.shortcuts import redirect
            return redirect(request.path)

        # --- CREATE / UPDATE ---
        nome  = (request.POST.get("nome_dipendente") or "").strip()
        data  = (request.POST.get("data") or "").strip()
        em    = (request.POST.get("entrata_mattina") or "").strip()
        um    = (request.POST.get("uscita_mattina")  or "").strip()
        tp    = bool(request.POST.get("turno_pomeriggio"))
        ep    = (request.POST.get("entrata_pomeriggio") or "").strip()
        up    = (request.POST.get("uscita_pomeriggio")  or "").strip()
        note  = (request.POST.get("note") or "").strip()

        if not nome:
            form_errors["nome_dipendente"] = "Campo obbligatorio."
        if not data:
            form_errors["data"] = "Campo obbligatorio."
        if not em:
            form_errors["entrata_mattina"] = "Campo obbligatorio."
        if not um:
            form_errors["uscita_mattina"] = "Campo obbligatorio."
        if tp:
            if not ep:
                form_errors["entrata_pomeriggio"] = "Obbligatorio se turno pomeriggio attivo."
            if not up:
                form_errors["uscita_pomeriggio"] = "Obbligatorio se turno pomeriggio attivo."

        if not form_errors:
            from datetime import date as date_type, time as time_type
            try:
                data_v = date_type.fromisoformat(data)
            except ValueError:
                form_errors["data"] = "Data non valida."

            def _parse_time(s):
                try:
                    parts = s.split(":")
                    return time_type(int(parts[0]), int(parts[1]))
                except Exception:
                    return None

            if not form_errors:
                em_v = _parse_time(em)
                um_v = _parse_time(um)
                ep_v = _parse_time(ep) if tp and ep else None
                up_v = _parse_time(up) if tp and up else None
                inserito_da = getattr(request.user, "get_full_name", lambda: "")() or str(request.user)

                if action == "update" and pk_raw.isdigit():
                    try:
                        obj = CertificazionePresenza.objects.get(pk=int(pk_raw))
                        obj.nome_dipendente    = nome
                        obj.data               = data_v
                        obj.entrata_mattina    = em_v
                        obj.uscita_mattina     = um_v
                        obj.turno_pomeriggio   = tp
                        obj.entrata_pomeriggio = ep_v
                        obj.uscita_pomeriggio  = up_v
                        obj.note               = note
                        obj.save()
                        log_action(request, "certifica_presenza_update", {"pk": obj.pk})
                        form_success = True
                        edit_obj = None
                    except CertificazionePresenza.DoesNotExist:
                        form_errors["global_error"] = "Record non trovato."
                else:
                    obj = CertificazionePresenza.objects.create(
                        nome_dipendente    = nome,
                        data               = data_v,
                        entrata_mattina    = em_v,
                        uscita_mattina     = um_v,
                        turno_pomeriggio   = tp,
                        entrata_pomeriggio = ep_v,
                        uscita_pomeriggio  = up_v,
                        note               = note,
                        inserito_da        = inserito_da,
                    )
                    log_action(request, "certifica_presenza_create", {"pk": obj.pk})

                    # --- Auto-approva: inserisce in tabella assenze con consenso=Approvato
                    #     e tenta push a SharePoint (flusso Power Automate) ---
                    if _table_exists("assenze"):
                        try:
                            now = timezone.now()
                            dt_start = datetime.combine(data_v, em_v)
                            dt_end   = datetime.combine(data_v, um_v)
                            assenza_payload = {
                                "sharepoint_item_id": None,
                                "nome_lookup_id":     None,
                                "copia_nome":         nome,
                                "email_esterna":      inserito_da,
                                "tipo_assenza":       _tipo_for_storage("Certifica presenza"),
                                "capo_reparto_lookup_id": None,
                                "data_inizio":        dt_start,
                                "data_fine":          dt_end,
                                "motivazione_richiesta": _motivazione_for_storage(
                                    "Certifica presenza",
                                    note or "Certifica presenza — inserimento diretto",
                                ),
                                "salta_approvazione": True,
                                "consenso":           "Approvato",
                                "moderation_status":  0,
                                "approvazione_datetime": now,
                                "created_datetime":   now,
                                "modified_datetime":  now,
                            }
                            with transaction.atomic():
                                local_id = _insert_assenza(assenza_payload)
                            if local_id:
                                obj.sharepoint_item_id = str(local_id)
                                obj.save(update_fields=["sharepoint_item_id"])
                                # Invio a SharePoint in coda, gestito dal job in background.
                                _sp_enqueue_upsert(local_id)
                        except Exception as exc:
                            logger.warning("certifica_presenza: errore auto-push assenze: %s", exc)

                    form_success = True

                # Aggiorna lista dopo salvataggio
                qs2 = CertificazionePresenza.objects.all()
                if q_nome:   qs2 = qs2.filter(nome_dipendente__icontains=q_nome)
                records = list(qs2[:200])

    ore_mattina_list   = [f"{h:02d}" for h in range(6, 23)]
    ore_pom_list       = [f"{h:02d}" for h in range(12, 24)]
    minuti_list        = [f"{m:02d}" for m in range(0, 60, 5)]

    return render(request, "assenze/pages/certificazione_presenza.html", {
        "records": records,
        "dipendenti_nomi": dipendenti_nomi,
        "form_errors": form_errors,
        "form_success": form_success,
        "edit_obj": edit_obj,
        "q_nome": q_nome,
        "q_data_da": q_data_da,
        "q_data_a": q_data_a,
        "ore_mattina_list": ore_mattina_list,
        "ore_pom_list": ore_pom_list,
        "minuti_list": minuti_list,
        **perm_ctx,
    })


# ─────────────────────────────────────────────────────────────────────────────
# CHECK FORMAZIONE: avviso non bloccante se richiesta assenza copre date di corsi
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def api_check_corsi(request):
    """Ritorna corsi/sessioni del dipendente che intersecano il range
    [date_start, date_end]. Non blocca: serve solo a popolare un avviso UI.

    Query params: date_start (obbl.), date_end (opz., default=date_start),
    legacy_id (opz., default=utente corrente; serve permesso caporeparto/admin se altro).

    Response JSON: { ok, n_conflicts, conflicts: [{date, session_id, code, title, ...}] }
    """
    from datetime import datetime as _dt

    def _parse(s):
        if not s: return None
        try: return _dt.strptime(s.strip(), "%Y-%m-%d").date()
        except (TypeError, ValueError): return None

    d_start = _parse(request.GET.get("date_start"))
    d_end   = _parse(request.GET.get("date_end")) or d_start
    if d_start is None:
        return JsonResponse({"ok": False, "error": "date_start mancante o non valida"}, status=400)
    if d_end < d_start:
        d_start, d_end = d_end, d_start

    _name, _email, my_legacy = _legacy_identity(request)
    raw_legacy = (request.GET.get("legacy_id") or "").strip()
    if raw_legacy:
        try:
            legacy_id = int(raw_legacy)
        except ValueError:
            return JsonResponse({"ok": False, "error": "legacy_id non valido"}, status=400)
        if my_legacy is None or int(my_legacy) != legacy_id:
            # SEC: per controllare un ALTRO dipendente serve lo scope effettivo
            # (AMMINISTRAZIONE = tutti, caporeparto = solo il proprio reparto), come
            # per l'inserimento per altri. Prima bastava essere un caporeparto
            # qualsiasi → enumerazione dei corsi di qualunque dipendente.
            if not _can_insert_for_dipendente(request, legacy_id):
                return JsonResponse({"ok": False, "error": "Non hai i permessi per controllare questo dipendente"}, status=403)
    else:
        if my_legacy is None:
            return JsonResponse({"ok": True, "n_conflicts": 0, "conflicts": []})
        legacy_id = int(my_legacy)

    try:
        from anagrafica.models_formazione import TrainingEnrollment, TrainingSession
    except Exception:
        return JsonResponse({"ok": True, "n_conflicts": 0, "conflicts": []})

    sess_ids = list(
        TrainingEnrollment.objects
        .filter(legacy_anagrafica_id=legacy_id)
        .values_list("sessione_id", flat=True)
    )
    if not sess_ids:
        return JsonResponse({"ok": True, "n_conflicts": 0, "conflicts": []})

    qs = (
        TrainingSession.objects
        .select_related("corso")
        .filter(pk__in=sess_ids, data_inizio__lte=d_end, data_fine__gte=d_start)
        .exclude(stato="ANNULLATA")
        .order_by("data_inizio")
    )

    conflicts = []
    for s in qs:
        first_overlap = max(s.data_inizio, d_start)
        conflicts.append({
            "date":          first_overlap.strftime("%Y-%m-%d"),
            "date_label":    first_overlap.strftime("%d-%m-%Y"),
            "session_id":    s.pk,
            "code":          s.codice_sessione,
            "title":         s.corso.titolo,
            "course_code":   s.corso.codice,
            "data_inizio":   s.data_inizio.strftime("%Y-%m-%d"),
            "data_fine":     s.data_fine.strftime("%Y-%m-%d"),
            "stato":         s.stato,
            "stato_display": s.get_stato_display(),
            "url":           f"/anagrafica/formazione/sessioni/{s.pk}/",
        })

    return JsonResponse({"ok": True, "n_conflicts": len(conflicts), "conflicts": conflicts})
