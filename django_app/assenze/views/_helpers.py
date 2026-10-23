"""Viste del modulo Assenze — Funzioni e costanti condivise dai pilastri del modulo (un solo punto di lookup per i test).

Spacchettamento di ``assenze/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone as dt_timezone
import requests
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import connections, transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from config.env_config import get_first_env_value
from core.csv_export import CSV_CONTENT_TYPE, bom_first, safe_csv_writer
from core.acl import user_can_modulo_action
from core.caporeparto_utils import resolve_caporeparto_legacy_user

from core.audit import log_action
from core.graph_utils import acquire_graph_token, is_placeholder_value
from core.legacy_utils import get_legacy_user, legacy_table_columns, legacy_table_has_column
from core.permessi import decisione, sistema_ruoli_attivo

from ..constants import (
    AUTO_FINE_MINUTI,
    TIPI_ASSENZA_STORAGE,
    TIPI_ASSENZA_UI,
    SHORTCUT_PRESETS,
    SHORTCUT_CUSTOM,
    PERMESSO_MIN_MINUTES,
    PERMESSO_MAX_HOURS,
)
from core import naming
from django.http import StreamingHttpResponse

logger = logging.getLogger(__name__)

MODULO = "assenze"
_SYNC_PULL_LAST_TS_KEY = "assenze:sync_pull:last_ts"
_SP_PUSH_LOCK_KEY = "assenze:sp_push:lock"
_SP_PUSH_LOCK_TTL = 300
_SP_PUSH_BATCH = 50
_SP_MOTIVAZIONI_CACHE_KEY = "assenze:sp_motivazioni"
_SP_MOTIVAZIONI_CACHE_TTL = 2 * 60 * 60
_SELECT_RE = re.compile(r"^\s*SELECT\s", re.IGNORECASE)
_SELECT_DISTINCT_RE = re.compile(r"^\s*SELECT\s+DISTINCT\s", re.IGNORECASE)

_TIPI_UI = set(TIPI_ASSENZA_UI)
_TIPI_STORAGE = set(TIPI_ASSENZA_STORAGE)
_CERTIFICA_PRESENZA_MARKER = "[CERTIFICA_PRESENZA]"
_CONSENSI = {"In attesa", "Approvato", "Rifiutato", "Bozza", "Programmato"}
_MOD_TO_CONSENSO = {"0": "Approvato", "1": "Rifiutato", "2": "In attesa", "3": "Bozza", "4": "Programmato"}
_CONSENSO_TO_MOD = {"Approvato": 0, "Rifiutato": 1, "In attesa": 2, "Bozza": 3, "Programmato": 4}
_APPROVAZIONE_DATETIME_COL = "approvazione_datetime"


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


def _capo_regola_unica(anagrafica_id) -> int | None:
    """Capo dalla regola unica capo/team di Anagrafica, se accesa; altrimenti None
    e il chiamante resta sulla regola area → reparto di prima."""
    try:
        from anagrafica.services import capo_team

        if not capo_team.regola_unica_attiva():
            return None
        return _as_int(capo_team.capo_effettivo(anagrafica_id))
    except Exception:
        return None


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
        full_name = naming.nome_completo(nome, cognome)
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


def _capo_scelto_legacy_user_id(assenza_id) -> int | None:
    """Capo scelto a mano per la richiesta (utenti.id), se ce n'e' uno."""
    item_id = _as_int(assenza_id)
    if item_id is None:
        return None
    try:
        from ..models import AssenzaCapoScelto

        return _as_int(
            AssenzaCapoScelto.objects.filter(assenza_id=item_id).values_list("capo_legacy_user_id", flat=True).first()
        )
    except Exception:
        return None


def _con_capo_scelto(
    where: str, params: list, *, legacy_user_id: int | None, alias: str, per_approvazione: bool
) -> tuple[str, list]:
    """Aggiunge al perimetro le richieste con capo scelto a mano.

    Le richieste che hanno scelto questo capo entrano sempre. Per la coda e
    l'approvazione (``per_approvazione``) escono invece quelle che hanno scelto
    un altro capo: le approva solo il capo scelto. La consultazione (calendario,
    elenchi del reparto) le lascia al capo dell'organigramma.
    """
    if legacy_user_id is None:
        return where, params
    try:
        from ..models import AssenzaCapoScelto

        tabella = AssenzaCapoScelto._meta.db_table
        if not _table_exists(tabella):
            return where, params
    except Exception:
        return where, params
    prefix = f"{alias}." if alias else ""
    scelta = f"SELECT 1 FROM {tabella} cs WHERE cs.assenza_id = {prefix}id AND cs.capo_legacy_user_id"
    mia = f"EXISTS ({scelta} = %s)"
    if not where:
        return mia, [int(legacy_user_id)]
    if per_approvazione:
        return (
            f"((({where}) AND NOT EXISTS ({scelta} <> %s)) OR {mia})",
            [*params, int(legacy_user_id), int(legacy_user_id)],
        )
    return f"(({where}) OR {mia})", [*params, int(legacy_user_id)]


def _combined_manager_assignment_where_clause(
    *,
    legacy_user_id: int | None,
    manager_name: str = "",
    manager_email: str = "",
    assenze_alias: str = "a",
    capi_alias: str = "cr",
    per_approvazione: bool = False,
) -> tuple[str, list, bool]:
    where, params, use_legacy_join = _manager_assignment_where_clause_base(
        legacy_user_id=legacy_user_id,
        manager_name=manager_name,
        manager_email=manager_email,
        assenze_alias=assenze_alias,
        capi_alias=capi_alias,
    )
    if not _has_assenze_column("id"):
        return where, params, use_legacy_join
    where, params = _con_capo_scelto(
        where, params, legacy_user_id=legacy_user_id, alias=assenze_alias, per_approvazione=per_approvazione
    )
    return where, params, use_legacy_join


def _manager_assignment_where_clause_base(
    *,
    legacy_user_id: int | None,
    manager_name: str = "",
    manager_email: str = "",
    assenze_alias: str = "a",
    capi_alias: str = "cr",
) -> tuple[str, list, bool]:
    if sistema_ruoli_attivo():
        # Ruoli del portale: il perimetro del capo e' il suo team d'organigramma
        # (core.permessi.team), lo stesso per coda, conteggi, storico e calendario.
        from core.permessi.team import team_di

        team = sorted(team_di(legacy_user_id)) if legacy_user_id else []
        if not team or not _has_assenze_column("utente_id"):
            return "", [], False
        placeholders = ", ".join(["%s"] * len(team))
        return f"{assenze_alias}.utente_id IN ({placeholders})", list(team), False

    clauses: list[str] = []
    params: list = []

    use_legacy_join = _legacy_capi_table_exists()
    local_where, local_params = _local_manager_assignment_where_clause(
        legacy_user_id=legacy_user_id,
        alias=assenze_alias,
    )
    # Con una FK reale, capi_reparto.id NON e' utenti.id.
    if local_where and not use_legacy_join:
        clauses.append(local_where)
        params.extend(local_params)

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

    from ..team_scope import canonical_team_predicates

    known, mine, canonical_params = canonical_team_predicates(legacy_user_id, assenze_alias)
    legacy_where = f"({' OR '.join(clauses)})" if clauses else ""
    if known:
        # Una nuova assegnazione in HR prevale sul capo storico della richiesta.
        where = f"({mine} OR (NOT {known} AND {legacy_where}))" if legacy_where else mine
        return where, [*canonical_params, *params], use_legacy_join
    return legacy_where, params, use_legacy_join


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
    can_update_any = group == "AMMINISTRAZIONE"
    can_update_owned = group == "CAR"

    # --- Ampiezza di visibilita' sulle assenze altrui ------------------------
    # Tre livelli: "all" (tutta l'azienda: AMMINISTRAZIONE, DIREZIONE, HR),
    # "reparto" (solo i dipendenti di cui si e' capo assegnato: i CAR) e "own"
    # (solo le proprie richieste: tutti gli altri).
    #
    # La fonte canonica sono due capability ACL, assegnabili da /admin-portale/
    # accessi/ sia a un ruolo sia al singolo utente (override): il livello non
    # dipende piu' da come e' scritto il nome del ruolo. Il fallback sui gruppi
    # legacy resta finche' le capability non sono state distribuite, altrimenti
    # al primo deploy tutti i CAR perderebbero il calendario.
    view_scope = "own"
    view_scope_source = "legacy_group"
    try:
        if user_can_modulo_action(request, "assenze", "view_all_assenze"):
            view_scope, view_scope_source = "all", "acl"
        elif user_can_modulo_action(request, "assenze", "view_reparto_assenze"):
            view_scope, view_scope_source = "reparto", "acl"
    except Exception:
        logger.debug("_assenze_permissions: valutazione ACL scope fallita", exc_info=True)
    if view_scope_source != "acl":
        if can_update_any:
            view_scope = "all"
        elif can_update_owned:
            view_scope = "reparto"
        else:
            view_scope = "own"

    # Il calendario mostra assenze altrui: resta riservato a chi ha almeno il
    # perimetro di reparto. Un dipendente senza ruoli continua a non vederlo.
    can_view_calendar = view_scope in {"all", "reparto"}
    can_delete_any = group == "AMMINISTRAZIONE"
    can_skip_approval = group in {"CAR", "AMMINISTRAZIONE"}
    # Scelta del capo a cui inviare la richiesta: tutti possono cambiarlo. Il
    # capo proposto resta quello dell'organigramma; se ne sceglie un altro, solo
    # quello vede e approva la richiesta (``AssenzaCapoScelto``).
    can_choose_capo = True
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

    team_utenti_ids: frozenset[int] = frozenset()
    if sistema_ruoli_attivo():
        # Ruoli del portale: i flag storici si ricavano dalla matrice. Il team e'
        # quello dell'organigramma (core.permessi.team), non piu' i capi_reparto.
        vedere = decisione(request, MODULO, "vedere")
        creare = decisione(request, MODULO, "creare")
        approvare = decisione(request, MODULO, "approvare")
        cancellare = decisione(request, MODULO, "cancellare")
        view_scope = {"tutti": "all", "team": "reparto"}.get(vedere.ambito, "own") if vedere.consentito else "none"
        view_scope_source = "ruoli"
        can_insert = creare.consentito
        can_insert_for_others = creare.consentito and creare.ambito in {"team", "tutti"}
        insert_for_others_scope = "all" if can_insert_for_others else "none"
        # «Gestire» apre le impostazioni (permessi di pagina), non le approvazioni:
        # approva solo chi ha «approvare», sul perimetro del suo ambito.
        can_update_any = approvare.consentito and approvare.ambito == "tutti"
        can_update_owned = not can_update_any and approvare.consentito and approvare.ambito == "team"
        can_delete_any = cancellare.consentito and cancellare.ambito == "tutti"
        can_skip_approval = can_update_any or can_update_owned
        can_view_calendar = view_scope in {"all", "reparto"}
        group = "AMMINISTRAZIONE" if can_update_any else ("CAR" if can_update_owned else "UTENTI")
        if can_update_owned or view_scope == "reparto":
            from core.permessi.team import team_di

            team_utenti_ids = team_di(legacy_user_id)

    perms = {
        "group": group,
        "view_scope": view_scope,
        "view_scope_source": view_scope_source,
        "view_all": view_scope == "all",
        "legacy_user_id": legacy_user_id,
        "manager_name": manager_name,
        "manager_email": manager_email,
        "can_insert": can_insert,
        "can_insert_for_others": can_insert_for_others,
        "insert_for_others_scope": insert_for_others_scope,
        "can_view_calendar": can_view_calendar,
        "can_update_any": can_update_any,
        "can_update_owned": can_update_owned,
        "can_delete_any": can_delete_any,
        "can_skip_approval": can_skip_approval,
        "can_choose_capo": can_choose_capo,
        "can_edit_events": can_update_any or can_update_owned,
        "owned_capo_local_ids": owned_local_ids,
        "owned_capo_lookup_ids": owned_lookup_ids,
        "team_utenti_ids": team_utenti_ids,
        "role_labels": sorted(role_labels),
    }
    setattr(request, "_assenze_perm_cache", perms)
    return perms


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
        "assenze_can_choose_capo": perms.get("can_choose_capo", False),
        "assenze_can_edit_events": perms["can_edit_events"],
        "assenze_can_view_team": perms.get("view_scope") in {"all", "reparto"},
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

    # Capo scelto a mano nella richiesta: approva solo lui, non il capo
    # dell'organigramma.
    capo_scelto_id = _capo_scelto_legacy_user_id(row.get("id"))
    if capo_scelto_id is not None:
        return capo_scelto_id == _as_int(perms.get("legacy_user_id"))

    if perms.get("view_scope_source") == "ruoli":
        # Ruoli del portale: si approva chi sta nel proprio team d'organigramma.
        utente_id = _as_int(row.get("utente_id") or row.get("legacy_user_id"))
        return utente_id is not None and utente_id in set(perms.get("team_utenti_ids") or ())

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
    from ..models import FlessibilitaImpostazioni

    try:
        return FlessibilitaImpostazioni.get_solo()
    except Exception:
        logger.warning("[assenze] impostazioni flessibilita' non leggibili, uso i default", exc_info=True)
        return FlessibilitaImpostazioni(
            orari_entrata=FlessibilitaImpostazioni.ENTRATE_DEFAULT,
            orari_uscita=FlessibilitaImpostazioni.USCITE_DEFAULT,
        )


def _flessibilita_abilitati_ids() -> set[int]:
    from ..models import FlessibilitaAbilitato

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


def _update_assenza(item_id: int, updates: dict) -> bool:
    row = _prepare_row_data(updates)
    if not row:
        return False
    sets = ", ".join(f"{_quote_identifier(k)} = %s" for k in row.keys())
    with connections["default"].cursor() as cursor:
        cursor.execute(f"UPDATE assenze SET {sets} WHERE id = %s", [*list(row.values()), int(item_id)])
        return bool(cursor.rowcount)


def _delete_assenza(item_id: int) -> bool:
    from ..models import AssenzaOrigineSharePoint

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
    from ..models import AssenzaOrigineSharePoint as Origine

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
    from ..models import AssenzaOrigineSharePoint as Origine

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

    from ..models import AssenzaSharePointOutbox as Outbox

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

    from ..models import AssenzaSharePointOutbox as Outbox

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

    from ..models import AssenzaSharePointOutbox as Outbox

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


def _sp_refresh_motivazioni() -> None:
    """Aggiorna in cache le motivazioni della lista (lette dal job, non dalle pagine)."""
    values = _graph_get_motivazioni()
    if values:
        cache.set(_SP_MOTIVAZIONI_CACHE_KEY, values, timeout=_SP_MOTIVAZIONI_CACHE_TTL)


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
        per_approvazione=True,
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
    _capo_cols = "".join(f", a.{col}" for col in ("capo_reparto_id", "capo_reparto_lookup_id") if _has_assenze_column(col))
    base_sql = f"""
        SELECT
            a.id,
            a.copia_nome AS dipendente,
            a.tipo_assenza,
            a.data_inizio,
            a.data_fine,
            a.consenso,
            a.moderation_status,
            a.motivazione_richiesta{_cert_col}{_utente_col}{_creata_col}{_capo_cols}
        FROM assenze a
        {join_sql}
        WHERE {manager_where_sql}
          AND COALESCE(a.moderation_status, 2) = 2
    """
    sql = _select_limited(base_sql, "ORDER BY a.data_inizio DESC, a.id DESC", limit)
    rows = _applica_nominativo(_fetch_all_dict(sql, manager_where_params))
    out = []
    for row in rows:
        moderation_status, moderation_label = _status_from_moderation(row.get("moderation_status"), default_pending=True)
        stato_value = moderation_label
        out.append(
            {
                "id": row.get("id"),
                "capo_reparto_id": row.get("capo_reparto_id"),
                "capo_reparto_lookup_id": row.get("capo_reparto_lookup_id"),
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


def count_pending_for_manager(
    legacy_user_id: int | None,
    *,
    manager_name: str = "",
    manager_email: str = "",
) -> int:
    """Conteggio delle segnalazioni in attesa per un capo, con lo STESSO perimetro
    di `_load_pending_for_manager`.

    Serve al badge della subnav (`core.context_processors`), che prima usava una
    propria clausola di match piu' povera (niente `capi_reparto.utente_id`, niente
    fallback su dominio email o ordine nome/cognome) e mostrava quindi un numero
    diverso da quello che si vede aprendo la dashboard segnalazioni.
    """
    if not _table_exists("assenze"):
        return 0
    manager_where_sql, manager_where_params, use_legacy_join = _combined_manager_assignment_where_clause(
        per_approvazione=True,
        legacy_user_id=legacy_user_id,
        manager_name=manager_name,
        manager_email=manager_email,
        assenze_alias="a",
        capi_alias="cr",
    )
    if not manager_where_sql:
        return 0
    join_sql = " LEFT JOIN capi_reparto cr ON cr.id = a.capo_reparto_id " if use_legacy_join else ""
    sql = (
        "SELECT COUNT(*) FROM assenze a "
        + join_sql
        + f"WHERE {manager_where_sql} AND COALESCE(a.moderation_status, 2) = 2"
    )
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute(sql, manager_where_params)
            row = cursor.fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


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
    # Con la regola unica capo/team accesa il capo proposto puo' venire anche
    # dalla gerarchia dei ruoli o da un'eccezione sulla persona: il menu deve
    # contenerlo, altrimenti la proposta ricade in silenzio su un altro nome.
    try:
        from anagrafica.services import capo_team

        if capo_team.regola_unica_attiva():
            for value in capo_team.mappa_capi_in_cache().values():
                capo_id = _as_int(value)
                if capo_id is not None and capo_id > 0:
                    ids.add(capo_id)
    except Exception:
        pass
    return ids


def _anagrafica_row_label(row: dict) -> str:
    nome = str(row.get("nome") or "").strip()
    cognome = str(row.get("cognome") or "").strip()
    alias = str(row.get("aliasusername") or "").strip()
    email = str(row.get("email_notifica") or row.get("email") or "").strip()
    return naming.nome_completo(nome, cognome) or alias or email or f"#{row.get('id')}"


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
    label = naming.normalizza_parte(getattr(legacy_user, "nome", "")) or _anagrafica_row_label(row)
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
        per_approvazione=True,
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
    return naming.chiave_testo(value)


def _col_utente_id(alias: str = "a") -> str:
    """``, a.utente_id`` da aggiungere a una SELECT su assenze, se la colonna esiste."""
    if not _has_assenze_column("utente_id"):
        return ""
    return f", {alias}.utente_id" if alias else ", utente_id"


def _nominativi_per_utente(utente_ids) -> dict[int, str]:
    """``utente_id`` → nominativo nel formato unico (``COGNOME NOME``).

    Prima il dipendente collegato (nome e cognome separati: ordine certo), poi il
    nome dell'utente del portale."""
    ids = sorted({i for i in (_as_int(u) for u in utente_ids) if i})
    if not ids:
        return {}
    out: dict[int, str] = {}
    placeholders = ", ".join(["%s"] * len(ids))
    try:
        if _table_exists("anagrafica_dipendenti") and {"utente_id", "nome", "cognome"}.issubset(
            legacy_table_columns("anagrafica_dipendenti")
        ):
            for row in _fetch_all_dict(
                f"SELECT utente_id, nome, cognome FROM anagrafica_dipendenti WHERE utente_id IN ({placeholders})",
                ids,
            ):
                uid = _as_int(row.get("utente_id"))
                nominativo = naming.nome_completo(row.get("nome"), row.get("cognome"))
                if uid and nominativo:
                    out.setdefault(uid, nominativo)
        mancanti = [i for i in ids if i not in out]
        if mancanti and _table_exists("utenti"):
            for row in _fetch_all_dict(
                f"SELECT id, nome FROM utenti WHERE id IN ({', '.join(['%s'] * len(mancanti))})",
                mancanti,
            ):
                uid = _as_int(row.get("id"))
                nominativo = naming.normalizza_parte(row.get("nome"))
                if uid and nominativo:
                    out[uid] = nominativo
    except Exception:
        logger.warning("assenze: nominativi per utente non risolti", exc_info=True)
    return out


def _applica_nominativo(rows: list[dict], campo: str = "dipendente") -> list[dict]:
    """Sostituisce nel campo mostrato il nome salvato sulla richiesta con il
    nominativo nel formato unico.

    ``copia_nome`` resta invariato a DB: è sincronizzato con SharePoint. Qui si
    cambia solo ciò che si vede; se la richiesta non è collegata a un utente si
    mostra il testo salvato, in MAIUSCOLO."""
    mappa = _nominativi_per_utente(r.get("utente_id") for r in rows)
    for row in rows:
        row[campo] = mappa.get(_as_int(row.get("utente_id"))) or naming.normalizza_parte(row.get(campo))
    return rows


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
        candidates = naming.chiavi_confronto(nome, cognome)
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
        candidates = naming.chiavi_confronto(nome, cognome)
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
                capo_anagrafica_id = _capo_regola_unica(employee_id)
                if capo_anagrafica_id is None:
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
        sup_id = _capo_regola_unica(capo_anagrafica_id)
        if sup_id is None:
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


def _request_json(request) -> dict:
    if request.content_type and "application/json" in request.content_type:
        try:
            payload = json.loads((request.body or b"{}").decode("utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            return {}
    return {}


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
@require_http_methods(["POST"])
def _applica_moderazione(request, item_id: int, current: dict, consenso: str, note_gestione: str):
    """Approva o rifiuta un record: scrittura, audit, notifica, coda SharePoint.

    Estratta da ``api_car_aggiorna_consenso`` perche' la moderazione in blocco
    deve fare **esattamente** le stesse cose: una seconda implementazione
    avrebbe finito per dimenticarsi l'audit o la notifica al richiedente.
    Ritorna l'esito dell'accodamento SharePoint, oppure ``None`` se la scrittura
    non e' andata a buon fine.
    """
    updates = {
        "consenso": consenso,
        "moderation_status": _CONSENSO_TO_MOD.get(consenso, 2),
        "note_gestione": note_gestione,
        "modified_datetime": timezone.now(),
    }
    updates.update(_approval_timestamp_update(consenso, current))
    if not _update_assenza(item_id, updates):
        return None

    from .. import hr as _hr

    _hr.registra(
        item_id,
        "approvata" if consenso == "Approvato" else "rifiutata",
        utente=request.user.get_username(),
        prima=current,
        dopo=updates,
        motivo=note_gestione,
    )

    try:
        from core.audit import log_action as _log

        _log(request, "assenza_moderata", "assenze", {
            "item_id": item_id,
            "consenso": consenso,
            "note_gestione": note_gestione,
        })
    except Exception:
        pass

    try:
        from core.legacy_models import UtenteLegacy
        from core.models import Notifica

        richiedente_id = None
        email_rich = (current.get("email_esterna") or "").strip()
        if email_rich:
            u = UtenteLegacy.objects.filter(email__iexact=email_rich).first()
            if u:
                richiedente_id = u.id
        if richiedente_id:
            stato_label = "approvata" if consenso == "Approvato" else "rifiutata"
            msg = f"La tua richiesta di assenza è stata {stato_label}."
            if note_gestione and consenso == "Rifiutato":
                msg += f" Nota: {note_gestione}"
            Notifica.objects.create(
                legacy_user_id=richiedente_id,
                tipo=f"assenza_{stato_label}",
                messaggio=msg,
                url_azione="/assenze/richiesta_assenze",
            )
    except Exception:
        logger.exception("Assenze: notifica al richiedente non creata")

    return _sp_enqueue_upsert(item_id)


def _e_propria_assenza(request, current: dict) -> bool:
    """La richiesta e' di chi sta moderando? Stesso riconoscimento di «modifica la tua richiesta».

    Con il sistema dei ruoli acceso nessuno approva o rifiuta la propria assenza
    (separazione dei compiti, come nei DPI): decide un altro responsabile.
    """
    from core.permessi import sistema_ruoli_attivo

    if not sistema_ruoli_attivo():
        return False
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if legacy_user is not None and _as_int(current.get("utente_id")) == int(legacy_user.id):
        return True
    name, email, _ = _legacy_identity(request)
    rec_nome = str(current.get("copia_nome") or "").strip().upper()
    rec_email = str(current.get("email_esterna") or "").strip().upper()
    user_nome = str(name or "").strip().upper()
    user_email = str(email or "").strip().upper()
    return bool((user_email and rec_email == user_email) or (user_nome and rec_nome == user_nome))


def _e_mia_richiesta(request, current: dict) -> bool:
    """La richiesta è intestata a chi la guarda? Stessa regola dell'eliminazione delle proprie.

    Prima gli identificatori univoci (utente legacy, username, email), il nome
    solo per le righe che non ne hanno.
    """
    name, email, legacy_user_id = _legacy_identity(request)
    username = str(request.user.get_username() or "").strip()
    rec_utente_id = _as_int(current.get("utente_id"))
    rec_username = str(current.get("aliasusername") or "").strip()
    rec_email = str(current.get("email_esterna") or "").strip()
    if legacy_user_id is not None and rec_utente_id is not None:
        return rec_utente_id == legacy_user_id
    if username and rec_username:
        return rec_username.casefold() == username.casefold()
    if email and rec_email:
        return rec_email.casefold() == email.casefold()
    return bool(name) and str(current.get("copia_nome") or "").strip().casefold() == str(name).strip().casefold()


def _notify_assenza_deleted(request, record: dict) -> None:
    """Costruisce destinatari/contesto e invia l'avviso di eliminazione.

    Risolve l'email del capo reparto dai lookup del record e l'identita' di chi
    esegue l'eliminazione; delega l'invio a mail_delete_service (fail-open).
    """
    from ..mail_delete_service import send_assenza_deleted_notification

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


# ─────────────────────────────────────────────────────────────────────────────
# Export CSV
# ─────────────────────────────────────────────────────────────────────────────


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

# Colonne ordinabili: chiave usata nell'URL -> espressione SQL. Whitelist, non
# interpolazione: l'ordinamento arriva dalla query string.
ADMIN_ORDINAMENTI = {
    "id": "id",
    "dipendente": "copia_nome",
    "tipo": "tipo_assenza",
    "inizio": "data_inizio",
    "fine": "data_fine",
    "stato": "COALESCE(moderation_status, 2)",
    "creata": "created_datetime",
}
ADMIN_ORDINAMENTO_DEFAULT = "inizio"


def _admin_order_by(ordina: str, verso: str) -> str:
    """ORDER BY del pannello admin, da una whitelist (mai interpolazione libera).

    `id` fa da secondo criterio: senza, due righe con lo stesso valore possono
    scambiarsi di posto fra una pagina e l'altra e una sparirebbe dall'elenco.
    Non lo si ripete quando si ordina gia' per id: SQL Server rifiuta la stessa
    colonna due volte nell'ORDER BY (errore 169).
    """
    if ordina not in ADMIN_ORDINAMENTI:
        ordina = ADMIN_ORDINAMENTO_DEFAULT
    direzione = "ASC" if str(verso or "").lower() == "asc" else "DESC"
    order_by = f"ORDER BY {ADMIN_ORDINAMENTI[ordina]} {direzione}"
    if ordina != "id":
        order_by += ", id DESC"
    return order_by


# Nomi importati che i pilastri chiamano come ``_helpers.X`` (un solo bersaglio per mock.patch).
_VIA_HELPERS = (connections, get_legacy_user, legacy_table_columns, log_action, render, user_can_modulo_action)
