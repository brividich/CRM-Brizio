
from __future__ import annotations

import configparser
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core import signing
from django.db import connections, transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from core.acl import user_can_modulo_action
from core.caporeparto_utils import resolve_caporeparto_legacy_user

from admin_portale.decorators import legacy_admin_required
from core.audit import log_action
from core.graph_utils import acquire_graph_token, is_placeholder_value
from core.legacy_utils import get_legacy_user, legacy_table_columns, legacy_table_has_column
from core.models import AuditLog

logger = logging.getLogger(__name__)

_SYNC_PULL_LOCK_KEY = "assenze:sync_pull:lock"
_SYNC_PULL_LAST_TS_KEY = "assenze:sync_pull:last_ts"
_SYNC_PULL_LOCK_TTL = 120
_PENDING_RECONCILE_LOCK_KEY = "assenze:pending_reconcile:lock"
_PENDING_RECONCILE_LAST_TS_KEY = "assenze:pending_reconcile:last_ts"
_PENDING_RECONCILE_LOCK_TTL = 120
_PENDING_RECONCILE_INTERVAL_SECONDS = 60

_COLOR_CACHE_KEY_GLOBAL = "assenze:colors:global:v1"
_COLOR_CACHE_KEY_USER_PREFIX = "assenze:colors:user:v1:"
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_SELECT_RE = re.compile(r"^\s*SELECT\s", re.IGNORECASE)
_DEFAULT_COLORS = {
    "tipo_ferie": "#10b981",
    "tipo_permesso": "#3b82f6",
    "tipo_malattia": "#ef4444",
    "tipo_infortunio": "#f97316",
    "tipo_altro": "#8b5cf6",
    "stato_in_attesa": "#60a5fa",
    "stato_rifiutato": "#94a3b8",
    "stato_approvato": "#34d399",
}
_COLOR_KEYS = set(_DEFAULT_COLORS.keys())

_TIPI_UI = {"Ferie", "Permesso", "Malattia", "Flessibilità", "Certifica presenza", "Altro"}
_TIPI_STORAGE = {"Ferie", "Permesso", "Malattia", "Flessibilità", "Certifica presenza", "Altro"}
_CONSENSI = {"In attesa", "Approvato", "Rifiutato", "Bozza", "Programmato"}
_MOD_TO_CONSENSO = {"0": "Approvato", "1": "Rifiutato", "2": "In attesa", "3": "Bozza", "4": "Programmato"}
_CONSENSO_TO_MOD = {"Approvato": 0, "Rifiutato": 1, "In attesa": 2, "Bozza": 3, "Programmato": 4}
_FORM_TOKEN_SALT = "assenze.form_submit"


def _json_error(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": msg}, status=status)


def _db_vendor() -> str:
    return str(connections["default"].vendor or "").lower()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_ini() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(_repo_root() / "config.ini", encoding="utf-8")
    return parser


# Caricato una volta sola a import time, come in config/settings/base.py.
_INI = _load_ini()


def _env_or_ini(section: str, option: str, *env_keys: str) -> str:
    for key in env_keys:
        value = (os.getenv(key) or "").strip()
        if value:
            return value
    if _INI.has_section(section):
        return str(_INI.get(section, option, fallback="") or "").strip()
    return ""


def _graph_settings() -> dict[str, str]:
    return {
        "tenant_id": _env_or_ini("AZIENDA", "tenant_id", "GRAPH_TENANT_ID", "AZURE_TENANT_ID"),
        "client_id": _env_or_ini("AZIENDA", "client_id", "GRAPH_CLIENT_ID", "AZURE_CLIENT_ID"),
        "client_secret": _env_or_ini("AZIENDA", "client_secret", "GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET"),
        "site_id": _env_or_ini("AZIENDA", "site_id", "GRAPH_SITE_ID"),
        "list_id_assenze": _env_or_ini("AZIENDA", "list_id_assenze", "GRAPH_LIST_ID_ASSENZE"),
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


def _graph_get_all() -> list[dict]:
    url = f"{_graph_base_url()}?expand=fields&$top=500"
    rows: list[dict] = []
    while url:
        r = requests.get(url, headers=_graph_headers(), timeout=25)
        if r.status_code != 200:
            raise RuntimeError(f"Graph GET {r.status_code}: {r.text[:300]}")
        payload = r.json()
        rows.extend(payload.get("value", []) or [])
        url = payload.get("@odata.nextLink")
    return rows


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
    return timezone.localtime(dt).strftime("%d/%m/%Y %H:%M")


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


def _tipo_for_storage(value) -> str:
    tipo_ui = _norm_tipo(value)
    if tipo_ui == "Certifica presenza":
        return "Certifica presenza"
    return tipo_ui if tipo_ui in _TIPI_STORAGE else "Altro"


def _tipo_for_graph(value) -> str:
    tipo_ui = _norm_tipo(value)
    if tipo_ui == "Flessibilità":
        return "Flessibilità"
    if tipo_ui == "Certifica presenza":
        return "Certifica presenza"
    return tipo_ui if tipo_ui in {"Ferie", "Permesso", "Malattia", "Altro"} else "Altro"


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
    if _SELECT_RE.search(base_sql):
        sql_with_top = _SELECT_RE.sub(lambda m: f"{m.group(0)}TOP {limit} ", base_sql, count=1)
        return f"{sql_with_top} {order_by_sql}"
    return f"SELECT TOP {limit} * FROM ({base_sql}) _q {order_by_sql}"


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
        SELECT {', '.join(select_cols)}
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
        SELECT {', '.join(select_cols)}
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
        f"SELECT {', '.join(f'cr.{c}' for c in select_cols)} FROM capi_reparto cr WHERE {where_sql} ORDER BY cr.title, cr.id",
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
        f"SELECT {', '.join(select_cols)} FROM capi_reparto c WHERE {where_sql}",
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

    perms = {
        "group": group,
        "legacy_user_id": legacy_user_id,
        "can_insert": can_insert,
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


def _template_perm_context(request) -> dict:
    perms = _assenze_permissions(request)
    return {
        "assenze_group": perms["group"],
        "assenze_can_insert": perms["can_insert"],
        "assenze_can_view_calendar": perms["can_view_calendar"],
        "assenze_can_skip_approval": perms["can_skip_approval"],
        "assenze_can_edit_events": perms["can_edit_events"],
        "assenze_can_delete_events": perms["can_delete_any"],
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


def _validate_business_rules(
    *,
    tipo: str,
    dt_start: datetime | None,
    dt_end: datetime | None,
    person_name: str = "",
    person_email: str = "",
    exclude_item_id: int | None = None,
) -> tuple[str, str]:
    if dt_start is None or dt_end is None:
        return "Compila data e ora inizio/fine.", ""
    if dt_end <= dt_start:
        return "La data/ora di fine deve essere successiva all'inizio.", ""

    tipo_ui = _norm_tipo(tipo)
    warning = ""
    if tipo_ui == "Flessibilità":
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


def _resolve_capo_local_id(capo_value: str | None) -> int | None:
    raw = str(capo_value or "").strip()
    if not raw:
        return None
    legacy_user = _resolve_local_capo_legacy_user(raw)
    if legacy_user is not None:
        return _as_int(getattr(legacy_user, "id", None))
    return None


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
    base_sql = f"SELECT {', '.join(select_cols)} FROM capi_reparto WHERE sharepoint_item_id = %s"
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
    vendor = _db_vendor()
    if vendor == "sqlite":
        cursor.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})", values)
        return int(cursor.lastrowid) if cursor.lastrowid else None
    if vendor in {"microsoft", "mssql", "sql_server"}:
        cursor.execute(
            (
                "DECLARE @inserted_ids TABLE (id int); "
                f"INSERT INTO {table} ({', '.join(cols)}) "
                f"OUTPUT INSERTED.id INTO @inserted_ids VALUES ({placeholders}); "
                "SELECT TOP 1 id FROM @inserted_ids;"
            ),
            values,
        )
        row_inserted = _fetch_first_row_from_cursor(cursor)
        if row_inserted and row_inserted[0] is not None:
            return int(row_inserted[0])
        return None
    cursor.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})", values)
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
    ]
    clauses: list[str] = []
    params: list[object] = []
    for field in match_fields:
        if field not in row:
            continue
        value = row.get(field)
        if value is None:
            clauses.append(f"{field} IS NULL")
        else:
            clauses.append(f"{field} = %s")
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
    sets = ", ".join([f"{k} = %s" for k in row.keys()])
    with connections["default"].cursor() as cursor:
        cursor.execute(f"UPDATE assenze SET {sets} WHERE id = %s", [*list(row.values()), int(item_id)])
        return bool(cursor.rowcount)


def _delete_assenza(item_id: int) -> bool:
    with connections["default"].cursor() as cursor:
        cursor.execute("DELETE FROM assenze WHERE id = %s", [int(item_id)])
        return bool(cursor.rowcount)


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
        "tipo_assenza",
        "data_inizio",
        "data_fine",
        "motivazione_richiesta",
        "certificato_medico",
        "salta_approvazione",
        "consenso",
        "moderation_status",
        "note_gestione",
    ]
    selected = [col for col in wanted if col in cols]
    if "id" not in selected:
        return None
    rows = _fetch_all_dict(f"SELECT {', '.join(selected)} FROM assenze WHERE id = %s", [int(item_id)])
    return rows[0] if rows else None


def _sp_fields_from_row(row: dict) -> dict:
    tipo = _tipo_for_graph(row.get("tipo_assenza"))
    consenso = _norm_consenso(row.get("consenso"))
    fields = {
        "CopiaNome": str(row.get("copia_nome") or ""),
        "emailesterna": str(row.get("email_esterna") or ""),
        "Tipoassenza": tipo,
        "Motivazionerichiesta": str(row.get("motivazione_richiesta") or ""),
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
    fields = _sp_fields_from_row(row)

    if sp_id and force_update:
        ok, payload = _graph_update(sp_id, fields)
        if not ok:
            return {"ok": False, "error": str(payload)}
        _update_assenza(item_id, {"modified_datetime": timezone.now()})
        return {"ok": True, "action": "update", "sharepoint_item_id": sp_id}

    ok, payload = _graph_create(fields)
    if not ok:
        return {"ok": False, "error": str(payload)}
    created_sp_id = str((payload or {}).get("id") or "").strip()
    if not created_sp_id:
        return {"ok": False, "error": "Risposta SharePoint senza item_id"}
    _update_assenza(item_id, {"sharepoint_item_id": created_sp_id, "modified_datetime": timezone.now()})
    return {"ok": True, "action": "create", "sharepoint_item_id": created_sp_id}


def _sync_push(limit_rows: int = 30, include_updates: bool = False) -> dict:
    if not _table_exists("assenze"):
        return {"ok": False, "error": "Tabella assenze non disponibile"}
    if not _graph_configured():
        return {"ok": False, "error": "SharePoint non configurato"}

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

    data = {
        "sharepoint_item_id": sp_id,
        "nome_lookup_id": _as_int(fields.get("NomeLookupId")),
        "copia_nome": str(fields.get("CopiaNome") or "").strip(),
        "email_esterna": str(fields.get("emailesterna") or "").strip().lower(),
        "tipo_assenza": _tipo_for_storage(fields.get("Tipoassenza")),
        "capo_reparto_lookup_id": _as_int(fields.get("C_x002e_RepartoLookupId")),
        "data_inizio": _parse_sp_dt(fields.get("Data_x0020_inizio")),
        "data_fine": _parse_sp_dt(fields.get("Datafine")),
        "motivazione_richiesta": str(fields.get("Motivazionerichiesta") or "").strip(),
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


def _reconcile_pending_item_ids_with_sharepoint(item_ids: list[int], *, force: bool = False) -> dict:
    if not item_ids:
        return {"ok": True, "skipped": True, "reason": "empty", "checked": 0, "updated": 0}
    if not _graph_configured():
        return {"ok": False, "skipped": True, "reason": "not_configured", "checked": 0, "updated": 0}

    now_ts = int(time.time())
    last_ts = int(cache.get(_PENDING_RECONCILE_LAST_TS_KEY) or 0)
    if not force and last_ts and (now_ts - last_ts) < _PENDING_RECONCILE_INTERVAL_SECONDS:
        return {"ok": True, "skipped": True, "reason": "throttled", "checked": 0, "updated": 0}

    if not cache.add(_PENDING_RECONCILE_LOCK_KEY, "1", timeout=_PENDING_RECONCILE_LOCK_TTL):
        return {"ok": True, "skipped": True, "reason": "busy", "checked": 0, "updated": 0}

    checked = 0
    updated = 0
    try:
        seen: set[int] = set()
        for raw_id in item_ids:
            item_id = _as_int(raw_id)
            if item_id is None or item_id in seen:
                continue
            seen.add(item_id)

            current = _get_assenza(item_id)
            if not current:
                continue
            local_status, _local_label = _effective_status(
                current.get("consenso"),
                current.get("moderation_status"),
                default_pending=True,
            )
            if local_status != 2:
                continue

            sp_id = str(current.get("sharepoint_item_id") or "").strip()
            if not sp_id:
                continue

            try:
                sp_item = _graph_get_item(sp_id)
            except Exception:
                continue
            if not sp_item:
                continue

            checked += 1
            _sp_item_id, payload = _sp_item_to_local(sp_item)
            remote_status, _remote_label = _effective_status(
                payload.get("consenso"),
                payload.get("moderation_status"),
                default_pending=True,
            )
            if remote_status == 2:
                continue

            updates = dict(payload)
            updates.pop("sharepoint_item_id", None)
            if _update_assenza(item_id, updates):
                updated += 1

        cache.set(_PENDING_RECONCILE_LAST_TS_KEY, now_ts, timeout=None)
        return {"ok": True, "skipped": False, "checked": checked, "updated": updated}
    finally:
        cache.delete(_PENDING_RECONCILE_LOCK_KEY)


def _sync_pull_from_sharepoint(limit_rows: int | None = None) -> dict:
    if not _table_exists("assenze"):
        return {"ok": False, "error": "Tabella assenze non disponibile"}
    if not _graph_configured():
        return {"ok": False, "error": "SharePoint non configurato"}

    items = _graph_get_all()
    if limit_rows is not None:
        items = items[: max(1, int(limit_rows))]

    assenze_cols = legacy_table_columns("assenze")
    has_dip = _table_exists("dipendenti")
    has_capi = _table_exists("capi_reparto")

    inserted = 0
    updated = 0

    with transaction.atomic():
        with connections["default"].cursor() as cursor:
            for item in items:
                try:
                    sp_id, payload = _sp_item_to_local(item)
                except Exception:
                    continue

                cursor.execute("SELECT id FROM assenze WHERE sharepoint_item_id = %s", [sp_id])
                existing = cursor.fetchone()
                row_id = int(existing[0]) if existing and existing[0] is not None else None
                data = _prepare_row_data(payload)

                if row_id is None:
                    cols = list(data.keys())
                    vals = [data[c] for c in cols]
                    row_id = _insert_row_and_return_id(cursor, "assenze", cols, vals)
                    if row_id is None:
                        row_id = _find_inserted_assenza_id(data)
                    inserted += 1
                else:
                    updates = dict(data)
                    updates.pop("sharepoint_item_id", None)
                    if updates:
                        sets = ", ".join([f"{k} = %s" for k in updates.keys()])
                        cursor.execute(f"UPDATE assenze SET {sets} WHERE id = %s", [*list(updates.values()), row_id])
                    updated += 1

                if row_id is None:
                    continue

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

    return {"ok": True, "mode": "sharepoint_to_db_pull", "totals": {"inserted": inserted, "updated": updated}}


def _pull_interval_seconds() -> int:
    raw = getattr(settings, "ASSENZE_SP_PULL_INTERVAL_SECONDS", 300)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 300
    return max(60, value)


def _sync_on_page_load_enabled() -> bool:
    value = getattr(settings, "ASSENZE_SYNC_ON_PAGE_LOAD", False)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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
    finally:
        cache.delete(_SYNC_PULL_LOCK_KEY)


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
        "Altro": "tipo_altro",
    }.get(_norm_tipo(tipo), "stato_approvato")
    return colors.get(tipo_key, _DEFAULT_COLORS["stato_approvato"])


def _load_events(
    limit: int = 4000,
    start: datetime | None = None,
    end: datetime | None = None,
    colors: dict[str, str] | None = None,
) -> list[dict]:
    if not _table_exists("assenze"):
        return []

    has_dip = _table_exists("dipendenti")
    has_capi = _table_exists("capi_reparto")
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
        tipo = _norm_tipo(row.get("tipo_assenza"))
        moderation_status = _as_int(row.get("moderation_status"))
        moderation_label = _moderation_label(moderation_status)
        consenso = moderation_label if moderation_label != "N/D" else _norm_consenso(row.get("consenso"))
        events.append(
            {
                "id": row.get("id"),
                "title": str(row.get("dipendente") or "N/D"),
                "start": _to_isoz(row.get("data_inizio")),
                "end": _to_isoz(row.get("data_fine")),
                "color": _event_color(tipo, consenso, resolved_colors, moderation_status=moderation_status),
                "extendedProps": {
                    "tipo": tipo,
                    "consenso": consenso,
                    "moderation_status": moderation_status,
                    "motivazione": str(row.get("motivazione_richiesta") or ""),
                    "certificato_medico": str(row.get("certificato_medico") or ""),
                    "capo": str(row.get("capo") or ""),
                },
            }
        )
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
    base_sql = f"""
        SELECT
            id,
            tipo_assenza,
            data_inizio,
            data_fine,
            consenso,
            motivazione_richiesta,
            moderation_status{_note_col}{_cert_col}
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
                "tipo": _norm_tipo(row.get("tipo_assenza")),
                "tipo_raw": _tipo_for_storage(row.get("tipo_assenza")),
                "consenso": stato_value,
                "stato": stato_value,
                "inizio_label": _dt_label(dt_inizio),
                "fine_label": _dt_label(dt_fine),
                "inizio": _dt_label(dt_inizio),
                "fine": _dt_label(dt_fine),
                "inizio_iso": _to_isoz(dt_inizio) or "",
                "fine_iso": _to_isoz(dt_fine) or "",
                "motivazione": str(row.get("motivazione_richiesta") or ""),
                "certificato_medico": str(row.get("certificato_medico") or ""),
                "note_gestione": str(row.get("note_gestione") or ""),
                "moderation_status": moderation_status,
                "moderation_label": moderation_label,
            }
        )
    return out


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
    base_sql = f"""
        SELECT
            a.id,
            a.copia_nome AS dipendente,
            a.tipo_assenza,
            a.data_inizio,
            a.data_fine,
            a.consenso,
            a.moderation_status,
            a.motivazione_richiesta{_cert_col}
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
                "tipo": _norm_tipo(row.get("tipo_assenza")),
                "consenso": stato_value,
                "inizio_label": _dt_label(row.get("data_inizio")),
                "fine_label": _dt_label(row.get("data_fine")),
                "motivo": str(row.get("motivazione_richiesta") or ""),
                "certificato_medico": str(row.get("certificato_medico") or ""),
                "moderation_status": moderation_status,
            }
        )
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
                "tipo": _norm_tipo(row.get("tipo_assenza")),
                "consenso": moderation_label,
                "inizio_label": _dt_label(row.get("data_inizio")),
                "fine_label": _dt_label(row.get("data_fine")),
                "motivo": str(row.get("motivazione_richiesta") or ""),
                "certificato_medico": str(row.get("certificato_medico") or ""),
                "moderation_status": moderation_status,
                "note_gestione": str(row.get("note_gestione") or ""),
            }
        )
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
                "tipo": _norm_tipo(row.get("tipo_assenza")),
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
    base_sql = f"""
        SELECT
            a.id,
            a.copia_nome AS dipendente,
            a.tipo_assenza,
            a.data_inizio,
            a.data_fine,
            a.consenso,
            a.moderation_status,
            a.motivazione_richiesta{_cert_col}
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
                "tipo": _norm_tipo(row.get("tipo_assenza")),
                "consenso": moderation_label,
                "inizio_label": _dt_label(row.get("data_inizio")),
                "fine_label": _dt_label(row.get("data_fine")),
                "motivo": str(row.get("motivazione_richiesta") or ""),
                "certificato_medico": str(row.get("certificato_medico") or ""),
                "moderation_status": row.get("moderation_status"),
            }
        )
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
                "tipo": _norm_tipo(row.get("tipo_assenza")),
                "consenso": moderation_label,
                "inizio_label": _dt_label(row.get("data_inizio")),
                "fine_label": _dt_label(row.get("data_fine")),
                "motivo": str(row.get("motivazione_richiesta") or ""),
                "certificato_medico": str(row.get("certificato_medico") or ""),
                "moderation_status": row.get("moderation_status"),
                "note_gestione": str(row.get("note_gestione") or ""),
            }
        )
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
                "tipo": _norm_tipo(row.get("tipo_assenza")),
                "consenso": moderation_label,
                "inizio_label": _dt_label(row.get("data_inizio")),
                "fine_label": _dt_label(row.get("data_fine")),
            }
        )
    return out


def _legacy_capi_table_exists() -> bool:
    return _table_exists("capi_reparto")


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
    sql = f"SELECT {', '.join(select_cols)} FROM capi_reparto ORDER BY title"
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
                SELECT {', '.join(select_cols)}
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
        SELECT {', '.join(select_cols)}
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

    # Step 1: UserExtraInfo.caporeparto (da RepartoCapoMapping) — priorità massima
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

    # Step 2: storico assenze precedenti (locale o legacy)
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

    # Step 3: mapping reparto → caporeparto locale
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
    for row in rows:
        txt = str(row.get("motivazione_richiesta") or "").strip()
        if txt:
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
                "tipo": _norm_tipo(row.get("tipo_assenza")),
                "motivazione": str(row.get("motivazione_richiesta") or "").strip(),
                "capo_email": _resolve_capo_option_value_from_ids(local_id=capo_local_id, lookup_id=capo_lookup, capi=capi),
                "salta_approvazione": bool(_as_bool(row.get("salta_approvazione"))),
            }

    sp_item = _graph_get_item(source)
    if not sp_item:
        return None
    fields = sp_item.get("fields") or {}
    capo_lookup = _as_int(fields.get("C_x002e_RepartoLookupId"))
    return {
        "tipo": _norm_tipo(fields.get("Tipoassenza")),
        "motivazione": str(fields.get("Motivazionerichiesta") or "").strip(),
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


def _render_richiesta(request, success: str = "", error: str = "", form_data: dict | None = None):
    perms = _assenze_permissions(request)
    name, email, _legacy_id = _legacy_identity(request)
    display_name = _resolve_request_display_name(
        legacy_user_id=_legacy_id,
        email=email,
        username=request.user.get_username(),
        fallback_name=name,
    )
    today = datetime.now(dt_timezone.utc).date()
    tomorrow = today + timedelta(days=1)
    capi = _load_capi_options()
    motivazioni = _graph_get_motivazioni() or _load_motivazioni_local()
    copy_from = str(request.GET.get("copy_from") or "").strip()
    prefill = _prefill_from_copy(copy_from, capi)

    merged_form = {
        "tipoassenza": "",
        "motivazione": "",
        "certificato_medico": "",
        "caporeparto": _resolve_default_capo_for_user(
            name=display_name,
            email=email,
            username=request.user.get_username(),
            capi=capi,
            legacy_user_id=_legacy_id,
        ),
        "date_start": today.strftime("%Y-%m-%d"),
        "date_end": tomorrow.strftime("%Y-%m-%d"),
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
            "tipi": ["Ferie", "Permesso", "Malattia", "Flessibilità", "Certifica presenza", "Altro"],
            "nome": display_name,
            "capi": capi,
            "motivazioni": motivazioni,
            "copy_from": copy_from,
            "prefill": prefill,
            "form_success": success,
            "form_error": error,
            "form_data": merged_form,
            "submit_token": _build_submit_token(request, "assenze_invio"),
            "form_salta_approvazione": bool(_as_bool(merged_form.get("salta_approvazione"))),
            "ore_mattina_list": [f"{h:02d}" for h in range(6, 23)],
            "ore_pom_list":     [f"{h:02d}" for h in range(12, 24)],
            "minuti_list":      [f"{m:02d}" for m in range(0, 60, 5)],
            **_template_perm_context(request),
        },
    )


@login_required
def menu(request):
    name, email, _legacy_id = _legacy_identity(request)
    recenti = _load_personal(name, email, limit=8)
    return render(request, "assenze/pages/menu.html", {"recenti": recenti, **_template_perm_context(request)})


@login_required
def richiesta_assenze(request):
    if not _assenze_permissions(request).get("can_insert"):
        return HttpResponseForbidden("Permessi insufficienti: inserimento richieste non consentito.")
    return _render_richiesta(request)


@login_required
@ensure_csrf_cookie
def gestione_assenze(request):
    name, email, legacy_id = _legacy_identity(request)
    if _sync_on_page_load_enabled():
        _maybe_pull(force=False)
    richieste_da_approvare = _load_pending_for_manager(
        legacy_id,
        limit=40,
        manager_name=name,
        manager_email=email,
    )
    reconcile_pending = _reconcile_pending_item_ids_with_sharepoint(
        [r.get("id") for r in richieste_da_approvare],
        force=False,
    )
    if reconcile_pending.get("updated"):
        richieste_da_approvare = _load_pending_for_manager(
            legacy_id,
            limit=40,
            manager_name=name,
            manager_email=email,
        )
    return render(
        request,
        "assenze/pages/gestione_assenze.html",
        {
            "richieste_personali": _load_personal(name, email, limit=40),
            "richieste_da_approvare": richieste_da_approvare,
            "ruolo_corrente": "",
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
    if _sync_on_page_load_enabled():
        _maybe_pull(force=False)

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

    now = datetime.now()
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

    reconcile_pending = _reconcile_pending_item_ids_with_sharepoint(
        [r.get("id") for r in da_gestire],
        force=show_diag,
    )
    if reconcile_pending.get("updated"):
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
            "gestite": gestite,
            "riepilogo_oggi": riepilogo_oggi,
            "riepilogo_settimana": riepilogo_settimana,
            "data_oggi": today_start.strftime("%d/%m/%Y"),
            "data_lunedi": monday.strftime("%d/%m/%Y"),
            "data_domenica": (next_monday - timedelta(days=1)).strftime("%d/%m/%Y"),
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
    ok = _update_assenza(
        item_id,
        {
            "consenso": consenso,
            "moderation_status": moderation_status,
            "note_gestione": note_gestione,
            "modified_datetime": timezone.now(),
        },
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
                url_azione="/assenze/gestione/",
            )
    except Exception:
        pass

    sync_result: dict = {"ok": False, "reason": "not_configured"}
    if _graph_configured():
        sync_result = _sync_one_to_sharepoint(item_id, force_update=True)

    return JsonResponse({"ok": True, "item_id": item_id, "consenso": consenso, "note_gestione": note_gestione, "sync": sync_result})


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
    return render(request, "assenze/pages/calendario.html", {"eventi_preview": eventi_preview, **_template_perm_context(request)})


@login_required
@require_http_methods(["GET"])
def api_eventi(request):
    if not _assenze_permissions(request).get("can_view_calendar"):
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
        return JsonResponse(_load_events(limit=limit, start=start, end=end, colors=user_colors), safe=False)
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

    tipo = _tipo_for_storage((payload.get("tipo") if payload else None) or request.POST.get("tipo") or current.get("tipo_assenza"))
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
    motivazione = str(motivazione or "").strip()
    certificato_medico = payload.get("certificato_medico") if payload and "certificato_medico" in payload else None
    if certificato_medico is None:
        certificato_medico = request.POST.get("certificato_medico", current.get("certificato_medico") or "")
    certificato_medico = _certificato_medico_for_tipo(tipo, certificato_medico)

    dt_start = _parse_input_dt(inizio_raw) if inizio_raw else current.get("data_inizio")
    dt_end = _parse_input_dt(fine_raw) if fine_raw else current.get("data_fine")
    err_msg, warn_msg = _validate_business_rules(
        tipo=tipo,
        dt_start=dt_start,
        dt_end=dt_end,
        person_name=str(current.get("copia_nome") or ""),
        person_email=str(current.get("email_esterna") or ""),
        exclude_item_id=target_id,
    )
    if err_msg:
        return _json_error(err_msg, status=400)

    ok = _update_assenza(
        target_id,
        {
            "tipo_assenza": tipo,
            "consenso": consenso,
            "moderation_status": moderation_status,
            "data_inizio": dt_start,
            "data_fine": dt_end,
            "motivazione_richiesta": motivazione,
            "certificato_medico": certificato_medico,
            "modified_datetime": timezone.now(),
        },
    )
    if not ok:
        return _json_error("Aggiornamento non eseguito", status=500)

    sync_result = {"ok": False, "reason": "not_configured"}
    if _graph_configured():
        sync_result = _sync_one_to_sharepoint(target_id, force_update=True)

    return JsonResponse({"ok": True, "item_id": target_id, "sync": sync_result, "warning": warn_msg})


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
        name, email, _ = _legacy_identity(request)
        rec_nome = str(current.get("copia_nome") or "").strip().upper()
        rec_email = str(current.get("email_esterna") or "").strip().upper()
        user_nome = str(name or "").strip().upper()
        user_email = str(email or "").strip().upper()
        is_own = (user_nome and rec_nome == user_nome) or (user_email and rec_email == user_email)
        if not is_own:
            return _json_error("Permessi insufficienti: puoi eliminare solo le tue richieste.", status=403)

    sp_id = str(current.get("sharepoint_item_id") or "").strip()
    if sp_id and _graph_configured():
        ok, err = _graph_delete(sp_id)
        if not ok:
            return _json_error(f"Errore eliminazione SharePoint: {err}", status=502)

    if not _delete_assenza(target_id):
        return _json_error("Eliminazione non riuscita", status=500)
    return JsonResponse({"ok": True, "item_id": target_id})


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

    payload = _request_json(request)
    tipo = _tipo_for_storage((payload.get("tipo") if payload else None) or request.POST.get("tipo") or current.get("tipo_assenza"))
    inizio_raw = (payload.get("inizio") if payload else None) or request.POST.get("inizio")
    fine_raw = (payload.get("fine") if payload else None) or request.POST.get("fine")
    motivazione = (payload.get("motivazione") if payload else None)
    if motivazione is None:
        motivazione = request.POST.get("motivazione", current.get("motivazione_richiesta") or "")
    motivazione = str(motivazione or "").strip()
    certificato_medico = payload.get("certificato_medico") if payload and "certificato_medico" in payload else None
    if certificato_medico is None:
        certificato_medico = request.POST.get("certificato_medico", current.get("certificato_medico") or "")
    certificato_medico = _certificato_medico_for_tipo(tipo, certificato_medico)

    dt_start = _parse_input_dt(inizio_raw) if inizio_raw else current.get("data_inizio")
    dt_end = _parse_input_dt(fine_raw) if fine_raw else current.get("data_fine")

    err_msg, warn_msg = _validate_business_rules(
        tipo=tipo,
        dt_start=dt_start,
        dt_end=dt_end,
        person_name=str(current.get("copia_nome") or ""),
        person_email=str(current.get("email_esterna") or ""),
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

    sync_result = {"ok": False, "reason": "not_configured"}
    if _graph_configured():
        sync_result = _sync_one_to_sharepoint(item_id, force_update=True)

    return JsonResponse({"ok": True, "item_id": item_id, "warning": warn_msg, "sync": sync_result})


@csrf_exempt
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

    tipo = _tipo_for_storage(request.POST.get("tipoassenza"))
    motivazione = str(request.POST.get("motivazione") or "").strip()
    certificato_medico = _certificato_medico_for_tipo(tipo, request.POST.get("certificato_medico"))
    date_start = str(request.POST.get("date_start") or "").strip()
    date_end = str(request.POST.get("date_end") or "").strip()
    time_start = str(request.POST.get("time_start") or "00:00").strip() or "00:00"
    time_end = str(request.POST.get("time_end") or "23:59").strip() or "23:59"
    capo_raw = str(request.POST.get("caporeparto") or "").strip()
    salta_approvazione = bool(_as_bool(request.POST.get("salta_approvazione"))) if perms.get("can_skip_approval") else False

    if not date_start or not date_end:
        return _render_richiesta(request, error="Compila data inizio e data fine.", form_data=request.POST.dict())

    try:
        start_local = datetime.strptime(f"{date_start} {time_start}", "%Y-%m-%d %H:%M")
        end_local = datetime.strptime(f"{date_end} {time_end}", "%Y-%m-%d %H:%M")
    except ValueError:
        return _render_richiesta(request, error="Formato data/ora non valido.", form_data=request.POST.dict())

    dt_start = start_local
    dt_end = end_local

    name, email, legacy_id = _legacy_identity(request)
    display_name = _resolve_request_display_name(
        legacy_user_id=legacy_id,
        email=email,
        username=request.user.get_username(),
        fallback_name=name,
    )
    err_msg, warn_msg = _validate_business_rules(
        tipo=tipo,
        dt_start=dt_start,
        dt_end=dt_end,
        person_name=display_name,
        person_email=email,
    )
    if err_msg:
        return _render_richiesta(request, error=err_msg, form_data=request.POST.dict())

    payload = {
        "sharepoint_item_id": None,
        "nome_lookup_id": _resolve_nome_lookup_id(legacy_id, display_name),
        "copia_nome": display_name,
        "email_esterna": email,
        "tipo_assenza": tipo,
        "capo_reparto_id": _resolve_capo_local_id(capo_raw),
        "capo_reparto_lookup_id": _resolve_capo_lookup_id(capo_raw),
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

    sync_msg = "Sincronizzazione SharePoint non configurata."
    if _graph_configured():
        sync_res = _sync_one_to_sharepoint(local_id, force_update=False)
        if sync_res.get("ok"):
            sync_msg = f"Sync SharePoint avviato (item {sync_res.get('sharepoint_item_id')})."
        else:
            sync_msg = f"Salvato su DB locale, sync SharePoint fallita: {sync_res.get('error')}"

    warn_suffix = f" {warn_msg}" if warn_msg else ""
    return _render_richiesta(request, success=f"Richiesta registrata su DB locale. {sync_msg}{warn_suffix}")


@login_required
@require_http_methods(["POST"])
def aggiorna_consenso_placeholder(request, item_id: int):
    if not _assenze_permissions(request).get("can_update_any"):
        return _json_error("Permessi insufficienti: aggiornamento consenso non consentito.", status=403)
    consenso = _norm_consenso(request.POST.get("consenso"))
    ok = _update_assenza(
        item_id,
        {
            "consenso": consenso,
            "moderation_status": _CONSENSO_TO_MOD.get(consenso, 2),
            "modified_datetime": timezone.now(),
        },
    )
    if ok and _graph_configured():
        _sync_one_to_sharepoint(item_id, force_update=True)
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
    writer = csv.writer(_Echo())

    def stream():
        yield writer.writerow(headers)
        for row in rows_iter:
            yield writer.writerow(row)

    resp = StreamingHttpResponse(stream(), content_type="text/csv; charset=utf-8-sig")
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


@legacy_admin_required
def gestione_admin(request):
    """Pagina di gestione interna Assenze — accesso solo admin."""
    tab = request.GET.get("tab", "riepilogo")

    tabella_ok = _table_exists("assenze")

    # --- Statistiche ---
    stats = {"total": 0, "in_attesa": 0, "approvate": 0, "rifiutate": 0}
    by_tipo = []
    sync_info = {
        "last_pull": cache.get(_SYNC_PULL_LAST_TS_KEY),
    }

    if tabella_ok:
        def _count_sql(where=""):
            sql = "SELECT COUNT(*) FROM assenze" + (f" WHERE {where}" if where else "")
            with connections["default"].cursor() as cur:
                cur.execute(sql)
                return cur.fetchone()[0]

        stats["total"] = _count_sql()
        stats["in_attesa"] = _count_sql("COALESCE(moderation_status, 2) = 2")
        stats["approvate"] = _count_sql("COALESCE(moderation_status, 2) = 0")
        stats["rifiutate"] = _count_sql("COALESCE(moderation_status, 2) = 1")

        tipo_sql = _select_limited(
            "SELECT tipo_assenza, COUNT(*) AS n FROM assenze GROUP BY tipo_assenza",
            "ORDER BY n DESC",
            30,
        )
        by_tipo_counts: dict[str, int] = {}
        for row in _fetch_all_dict(tipo_sql):
            tipo_label = _norm_tipo(row.get("tipo_assenza"))
            by_tipo_counts[tipo_label] = by_tipo_counts.get(tipo_label, 0) + int(row.get("n") or 0)
        by_tipo = [
            {"tipo_assenza": tipo, "n": count}
            for tipo, count in sorted(by_tipo_counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    # --- Record: tutte le assenze ---
    q = request.GET.get("q", "").strip()
    assenze = []
    if tabella_ok:
        where_parts = []
        params = []
        if q:
            where_parts.append("(UPPER(COALESCE(copia_nome,'')) LIKE UPPER(%s) OR UPPER(COALESCE(tipo_assenza,'')) LIKE UPPER(%s))")
            params.extend([f"%{q}%", f"%{q}%"])
        where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        base_sql = f"""
            SELECT
                id, copia_nome AS dipendente, tipo_assenza,
                data_inizio, data_fine, consenso,
                moderation_status, motivazione_richiesta
            FROM assenze
            {where_clause}
        """
        sql = _select_limited(base_sql, "ORDER BY data_inizio DESC, id DESC", 100)
        rows = _fetch_all_dict(sql, params)
        for row in rows:
            _, mod_label = _status_from_moderation(row.get("moderation_status"), default_pending=True)
            assenze.append({
                "id": row.get("id"),
                "dipendente": str(row.get("dipendente") or "N/D"),
                "tipo": _norm_tipo(row.get("tipo_assenza")),
                "stato_label": mod_label,
                "moderation_status": row.get("moderation_status"),
                "inizio_label": _dt_label(row.get("data_inizio")),
                "fine_label": _dt_label(row.get("data_fine")),
                "motivo": str(row.get("motivazione_richiesta") or ""),
            })

    # --- Log ---
    audit_entries = AuditLog.objects.filter(modulo="assenze").order_by("-created_at")[:100]

    return render(
        request,
        "assenze/pages/gestione_admin.html",
        {
            "page_title": "Gestione Assenze",
            "tab": tab,
            "tabella_ok": tabella_ok,
            # stats
            "stats": stats,
            "by_tipo": by_tipo,
            "sync_info": sync_info,
            # records
            "assenze": assenze,
            "q": q,
            # log
            "audit_entries": audit_entries,
        },
    )


# ---------------------------------------------------------------------------
# Certificazione Presenza
# ---------------------------------------------------------------------------

@login_required
def certificazione_presenza(request):
    from .models import CertificazionePresenza

    is_admin = user_can_modulo_action(request, "assenze", "admin_assenze")
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
                            dt_start = datetime.combine(data_v, em_v)
                            dt_end   = datetime.combine(data_v, um_v)
                            assenza_payload = {
                                "sharepoint_item_id": None,
                                "nome_lookup_id":     None,
                                "copia_nome":         nome,
                                "email_esterna":      inserito_da,
                                "tipo_assenza":       "Certifica presenza",
                                "capo_reparto_lookup_id": None,
                                "data_inizio":        dt_start,
                                "data_fine":          dt_end,
                                "motivazione_richiesta": note or "Certifica presenza — inserimento diretto",
                                "salta_approvazione": True,
                                "consenso":           "Approvato",
                                "moderation_status":  0,
                                "created_datetime":   timezone.now(),
                                "modified_datetime":  timezone.now(),
                            }
                            with transaction.atomic():
                                local_id = _insert_assenza(assenza_payload)
                            if local_id:
                                obj.sharepoint_item_id = str(local_id)
                                obj.save(update_fields=["sharepoint_item_id"])
                                # Tenta push a SharePoint best-effort (sync push standard)
                                try:
                                    _sync_push(limit_rows=5, include_updates=False)
                                except Exception:
                                    pass
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
