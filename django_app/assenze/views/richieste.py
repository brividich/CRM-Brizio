"""Viste del modulo Assenze — Richieste: nuova richiesta, le mie richieste, invio e consenso, CAR, certificazione presenza.

Spacchettamento di ``assenze/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core import signing
from django.db import transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from core.module_branding import get_module_branding_context
from core.permessi import decisione, sistema_ruoli_attivo

from ..constants import (
    TIPI_ASSENZA_UI,
)
from core import naming

from .. import hr as calcoli_hr
from .. import serie
from . import _helpers  # noqa: E402

# Permesso ripetuto: oltre questa ampiezza (giorni di calendario) si chiede di
# spezzare la richiesta, per non creare per errore decine di permessi.
RIPETI_MAX_GIORNI = 31

logger = logging.getLogger(__name__)

_FORM_TOKEN_SALT = "assenze.form_submit"


def _certificazione_presenza_dipendenti_attivi() -> list[str]:
    if not _helpers._table_exists("anagrafica_dipendenti"):
        return []

    cols = _helpers.legacy_table_columns("anagrafica_dipendenti")
    select_cols = [c for c in ["cognome", "nome", "attivo"] if c in cols]
    if "nome" not in select_cols or "cognome" not in select_cols:
        return []

    where_parts = [
        "COALESCE(nome, '') <> ''",
        "COALESCE(cognome, '') <> ''",
    ]
    if "attivo" in select_cols:
        where_parts.append("attivo = 1")

    rows = _helpers._fetch_all_dict(
        f"""
        SELECT {_helpers._quoted_columns(select_cols)}
        FROM anagrafica_dipendenti
        WHERE {' AND '.join(where_parts)}
        ORDER BY cognome, nome
        """
    )

    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        full_name = naming.nome_completo(row.get('nome'), row.get('cognome'))
        if not full_name:
            continue
        key = re.sub(r"\s+", " ", full_name).casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(full_name)
    return names


def _resolve_request_display_name(
    *,
    legacy_user_id: int | None,
    email: str,
    username: str,
    fallback_name: str,
) -> str:
    fallback = str(fallback_name or "").strip()
    if not _helpers._table_exists("anagrafica_dipendenti"):
        return fallback

    cols = _helpers.legacy_table_columns("anagrafica_dipendenti")
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
    rows = _helpers._fetch_all_dict(
        f"""
        SELECT {_helpers._quoted_columns(select_cols)}
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


def _registra_capo_scelto(assenza_id, capo: dict | None, *, scelto_da: str = "") -> None:
    """Salva (o toglie) il capo scelto a mano per la richiesta."""
    item_id = _helpers._as_int(assenza_id)
    if item_id is None:
        return
    from ..models import AssenzaCapoScelto

    capo_id = _helpers._as_int((capo or {}).get("LegacyUserId"))
    if capo_id is None:
        AssenzaCapoScelto.objects.filter(assenza_id=item_id).delete()
        return
    AssenzaCapoScelto.objects.update_or_create(
        assenza_id=item_id,
        defaults={
            "capo_legacy_user_id": capo_id,
            "capo_nominativo": str((capo or {}).get("Value") or "")[:200],
            "scelto_da": str(scelto_da or "")[:200],
        },
    )


def _registra_inserita_da(assenza_id, *, gruppo: str | None, inserito_da: str = "") -> None:
    """Salva chi ha inserito la richiesta e con quale profilo Assenze.

    Non blocca mai l'inserimento: senza riga le automazioni trattano l'autore
    come sconosciuto e avvisano anche il caporeparto (comportamento storico).
    """
    item_id = _helpers._as_int(assenza_id)
    if item_id is None:
        return
    from ..models import AssenzaInseritaDa

    try:
        with transaction.atomic():
            AssenzaInseritaDa.objects.update_or_create(
                assenza_id=item_id,
                defaults={"gruppo": str(gruppo or "")[:20], "inserito_da": str(inserito_da or "")[:200]},
            )
    except Exception:
        logger.warning("Autore richiesta assenza %s non registrato", item_id, exc_info=True)


def _capo_assignment_diagnostics(
    *,
    legacy_user_id: int | None,
    manager_name: str = "",
    manager_email: str = "",
) -> dict:
    """Ritorna diagnostica sul match tra utente corrente e capi_reparto."""
    if not _helpers._table_exists("capi_reparto"):
        return {"table_exists": False, "where_sql": "", "params": [], "matched": [], "match_count": 0}

    cols = _helpers.legacy_table_columns("capi_reparto")
    where_sql, params = _helpers._capo_assignment_where_clause(
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

    rows = _helpers._fetch_all_dict(
        f"SELECT {_helpers._quoted_columns(select_cols, alias='cr')} FROM capi_reparto cr WHERE {where_sql} ORDER BY cr.title, cr.id",
        params,
    )
    return {
        "table_exists": True,
        "where_sql": where_sql,
        "params": params,
        "matched": rows,
        "match_count": len(rows),
    }


def _insertable_dipendenti_for_request(request) -> list[dict]:
    """Elenco dipendenti per cui l'utente corrente può inserire una richiesta."""
    perms = _helpers._assenze_permissions(request)
    if perms.get("insert_for_others_scope") == "all":
        return _helpers._load_dipendenti_attivi_list()
    return []


def _prepare_team_rows(request, rows):
    """La consultazione del reparto non concede dettagli riservati o scritture."""
    for row in rows:
        row["can_moderate"] = _helpers._can_manage_record(request, row)
        if not row["can_moderate"]:
            for field in ("motivo", "certificato_medico", "note_gestione"):
                row[field] = ""
    return rows


def _resolve_nome_lookup_id(legacy_user_id: int | None, display_name: str) -> int | None:
    if not _helpers._table_exists("dipendenti"):
        return None
    cols = _helpers.legacy_table_columns("dipendenti")
    with _helpers.connections["default"].cursor() as cursor:
        if legacy_user_id is not None and "utente_id" in cols:
            cursor.execute("SELECT id, sharepoint_item_id FROM dipendenti WHERE utente_id = %s ORDER BY id DESC", [legacy_user_id])
            row = cursor.fetchone()
            if row and row[1] is not None:
                return _helpers._as_int(row[1])
        if "title" in cols:
            if _helpers._db_vendor() == "sqlite":
                cursor.execute("SELECT sharepoint_item_id FROM dipendenti WHERE UPPER(COALESCE(title,'')) = UPPER(?) ORDER BY id DESC LIMIT 1", [display_name])
            else:
                cursor.execute("SELECT TOP 1 sharepoint_item_id FROM dipendenti WHERE UPPER(COALESCE(title,'')) = UPPER(%s) ORDER BY id DESC", [display_name])
            row = cursor.fetchone()
            if row and row[0] is not None:
                return _helpers._as_int(row[0])
    return None


def _resolve_capo_lookup_id(capo_value: str | None) -> int | None:
    raw = str(capo_value or "").strip()
    if not raw:
        return None
    numeric = _helpers._as_int(raw)
    if numeric is not None:
        return numeric
    return _helpers._resolve_legacy_capo_lookup_by_raw_value(raw)


def _find_local_capo_id_by_column(column_name: str, value) -> int | None:
    if value is None:
        return None
    sql = _helpers._select_limited(
        f"SELECT id FROM capi_reparto WHERE {column_name} = %s",
        "ORDER BY id DESC",
        1,
    )
    rows = _helpers._fetch_all_dict(sql, [value])
    if not rows:
        return None
    return _helpers._as_int(rows[0].get("id"))


def _resolve_capo_local_id_from_option_config(raw: str) -> int | None:
    try:
        from core.models import OptioneConfig
    except Exception:
        return None
    raw_lower = raw.strip().casefold()
    for option in OptioneConfig.objects.filter(tipo__iexact="caporeparto", is_active=True):
        if str(option.valore or "").strip().casefold() == raw_lower:
            legacy_user_id = _helpers._as_int(getattr(option, "legacy_user_id", None))
            if legacy_user_id is not None:
                return legacy_user_id
    return None


def _resolve_capo_local_id_from_anagrafica_hr(raw: str) -> int | None:
    raw_key = _helpers._norm_text_key(raw)
    if not raw_key:
        return None
    for option in _helpers._load_anagrafica_hr_capi_options():
        candidates = {
            _helpers._norm_text_key(_helpers._capo_option_value(option)),
            _helpers._norm_text_key(option.get("Email")),
            _helpers._norm_text_key(option.get("LookupId")),
            _helpers._norm_text_key(option.get("Value")),
            _helpers._norm_text_key(option.get("AnagraficaLegacyId")),
        }
        candidates.discard("")
        if raw_key in candidates:
            legacy_user_id = _helpers._as_int(option.get("LegacyUserId"))
            if legacy_user_id is not None:
                return legacy_user_id
    return None


def _resolve_capo_local_id(capo_value: str | None) -> int | None:
    raw = str(capo_value or "").strip()
    if not raw:
        return None
    anagrafica_hr_user_id = _resolve_capo_local_id_from_anagrafica_hr(raw)
    if not _helpers._legacy_capi_table_exists():
        return anagrafica_hr_user_id or _resolve_capo_local_id_from_option_config(raw)

    cols = _helpers.legacy_table_columns("capi_reparto")
    if "id" not in cols:
        return anagrafica_hr_user_id

    legacy_user = _helpers._resolve_local_capo_legacy_user(raw)
    legacy_user_id = _helpers._as_int(getattr(legacy_user, "id", None)) if legacy_user is not None else None
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

    numeric = _helpers._as_int(raw)
    if numeric is not None and "sharepoint_item_id" in cols:
        capo_id = _find_local_capo_id_by_column("sharepoint_item_id", int(numeric))
        if capo_id is not None:
            return capo_id

    if numeric is not None:
        capo_id = _find_local_capo_id_by_column("id", int(numeric))
        if capo_id is not None:
            return capo_id
    return anagrafica_hr_user_id


def _insert_assenza(data: dict) -> int | None:
    row = _helpers._prepare_row_data(data)
    if not row:
        return None
    cols = list(row.keys())
    values = [row[c] for c in cols]
    with _helpers.connections["default"].cursor() as cursor:
        row_id = _helpers._insert_row_and_return_id(cursor, "assenze", cols, values)
    if row_id is not None:
        return row_id
    return _helpers._find_inserted_assenza_id(row)


def _build_sharepoint_sync_diagnostics(item_ids: list[int], limit: int = 12) -> dict:
    result = {
        "enabled": _helpers._graph_configured(),
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
        parsed = _helpers._as_int(raw_id)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        unique_ids.append(parsed)
        if len(unique_ids) >= max(1, int(limit)):
            break

    for item_id in unique_ids:
        row = _helpers._diagnose_sharepoint_sync_item(item_id)
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


def _motivazioni_options() -> list[str]:
    cached = cache.get(_helpers._SP_MOTIVAZIONI_CACHE_KEY)
    if isinstance(cached, list) and cached:
        return cached
    return _helpers._load_motivazioni_local()


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
        tipo = _helpers._norm_tipo(row.get("tipo"))
        if row.get("certificato_medico"):
            summary["medical"] += 1
        if tipo == "Ferie":
            summary["ferie"] += 1
        elif tipo == "Permesso":
            summary["permesso"] += 1
        else:
            summary["other"] += 1
    return summary


def _team_history_period(periodo):
    today = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    if periodo == "passate":
        return " AND a.data_fine < %s", [today]
    if periodo == "future":
        return " AND a.data_fine >= %s", [today]
    return "", []


def _load_gestite_for_manager(
    legacy_user_id: int | None,
    limit: int = 30,
    *,
    manager_name: str = "",
    manager_email: str = "",
    offset: int = 0,
    periodo: str = "tutte",
) -> list[dict]:
    """Assenze già gestite (Approvato/Rifiutato) dal CAR indicato."""
    if not _helpers._table_exists("assenze"):
        return []
    manager_where_sql, manager_where_params, use_legacy_join = _helpers._combined_manager_assignment_where_clause(
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

    _note_col = ", a.note_gestione" if _helpers._has_assenze_column("note_gestione") else ""
    _cert_col = ", a.certificato_medico" if _helpers._has_assenze_column("certificato_medico") else ""
    _utente_col = ", a.utente_id" if _helpers._has_assenze_column("utente_id") else ""
    _capo_cols = "".join(f", a.{col}" for col in ("capo_reparto_id", "capo_reparto_lookup_id") if _helpers._has_assenze_column(col))
    base_sql = f"""
        SELECT
            a.id,
            a.copia_nome AS dipendente,
            a.tipo_assenza,
            a.data_inizio,
            a.data_fine,
            a.consenso,
            a.moderation_status,
            a.motivazione_richiesta{_note_col}{_cert_col}{_utente_col}{_capo_cols}
        FROM assenze a
        {join_sql}
        WHERE {manager_where_sql}
          AND COALESCE(a.moderation_status, 2) IN (0, 1)
    """
    period_sql, period_params = _team_history_period(periodo)
    base_sql += period_sql
    manager_where_params = [*manager_where_params, *period_params]
    sql = _helpers._select_paginated(base_sql, "ORDER BY a.data_inizio DESC, a.id DESC", offset=offset, limit=limit)
    rows = _helpers._applica_nominativo(_helpers._fetch_all_dict(sql, manager_where_params))
    out = []
    for row in rows:
        moderation_status, moderation_label = _helpers._status_from_moderation(row.get("moderation_status"), default_pending=True)
        out.append(
            {
                "id": row.get("id"),
                "capo_reparto_id": row.get("capo_reparto_id"),
                "capo_reparto_lookup_id": row.get("capo_reparto_lookup_id"),
                "dipendente": str(row.get("dipendente") or "N/D"),
                "tipo": _helpers._tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta")),
                "consenso": moderation_label,
                "inizio_label": _helpers._dt_label(row.get("data_inizio")),
                "fine_label": _helpers._dt_label(row.get("data_fine")),
                "motivo": _helpers._strip_tipo_metadata_from_motivazione(row.get("motivazione_richiesta")),
                "certificato_medico": str(row.get("certificato_medico") or ""),
                "moderation_status": moderation_status,
                "note_gestione": str(row.get("note_gestione") or ""),
                "legacy_user_id":   row.get("utente_id"),
                "data_inizio_raw":  row.get("data_inizio"),
                "data_fine_raw":    row.get("data_fine"),
            }
        )
    _helpers._attach_corsi_conflicts(out)
    _helpers._mark_sharepoint_managed(out)
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
    if not _helpers._table_exists("assenze"):
        return []
    manager_where_sql, manager_where_params, use_legacy_join = _helpers._combined_manager_assignment_where_clause(
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
            a.moderation_status{_helpers._col_utente_id()}
        FROM assenze a
        {join_sql}
        WHERE {manager_where_sql}
          AND a.data_inizio IS NOT NULL
          AND a.data_fine IS NOT NULL
          AND a.data_fine >= %s
          AND a.data_inizio <= %s
          AND COALESCE(a.moderation_status, 2) != 1
    """
    sql = _helpers._select_limited(base_sql, "ORDER BY a.data_inizio, a.id", limit)
    rows = _helpers._applica_nominativo(_helpers._fetch_all_dict(sql, [*manager_where_params, date_start, date_end]))
    out = []
    for row in rows:
        _, moderation_label = _helpers._status_from_moderation(row.get("moderation_status"), default_pending=True)
        out.append(
            {
                "id": row.get("id"),
                "dipendente": str(row.get("dipendente") or "N/D"),
                "tipo": _helpers._tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta")),
                "consenso": moderation_label,
                "inizio_label": _helpers._dt_label(row.get("data_inizio")),
                "fine_label": _helpers._dt_label(row.get("data_fine")),
            }
        )
    return out


def _load_all_pending(limit: int = 100) -> list[dict]:
    """Tutte le assenze in attesa (nessun filtro su capo): per AMMINISTRAZIONE."""
    if not _helpers._table_exists("assenze"):
        return []
    _cert_col = ", a.certificato_medico" if _helpers._has_assenze_column("certificato_medico") else ""
    _utente_col = ", a.utente_id" if _helpers._has_assenze_column("utente_id") else ""
    _creata_col = ", a.created_datetime" if _helpers._has_assenze_column("created_datetime") else ""
    _capo_cols = "".join(f", a.{col}" for col in ("capo_reparto_id", "capo_reparto_lookup_id") if _helpers._has_assenze_column(col))
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
        WHERE COALESCE(a.moderation_status, 2) = 2
    """
    sql = _helpers._select_limited(base_sql, "ORDER BY a.data_inizio DESC, a.id DESC", limit)
    rows = _helpers._applica_nominativo(_helpers._fetch_all_dict(sql))
    out = []
    for row in rows:
        _, moderation_label = _helpers._status_from_moderation(row.get("moderation_status"), default_pending=True)
        out.append(
            {
                "id": row.get("id"),
                "capo_reparto_id": row.get("capo_reparto_id"),
                "capo_reparto_lookup_id": row.get("capo_reparto_lookup_id"),
                "dipendente": str(row.get("dipendente") or "N/D"),
                "tipo": _helpers._tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta")),
                "consenso": moderation_label,
                "inizio_label": _helpers._dt_label(row.get("data_inizio")),
                "fine_label": _helpers._dt_label(row.get("data_fine")),
                "motivo": _helpers._strip_tipo_metadata_from_motivazione(row.get("motivazione_richiesta")),
                "certificato_medico": str(row.get("certificato_medico") or ""),
                "moderation_status": row.get("moderation_status"),
                "legacy_user_id":  row.get("utente_id"),
                "data_inizio_raw": row.get("data_inizio"),
                "data_fine_raw":   row.get("data_fine"),
                "creata_label": _helpers._dt_label(row.get("created_datetime")),
            }
        )
    _helpers._attach_corsi_conflicts(out)
    _helpers._mark_sharepoint_managed(out)
    return out


def _load_all_gestite(limit: int = 50, *, offset: int = 0, periodo: str = "tutte") -> list[dict]:
    """Ultime assenze già gestite (Approvato/Rifiutato), nessun filtro: per AMMINISTRAZIONE."""
    if not _helpers._table_exists("assenze"):
        return []
    _note_col = ", a.note_gestione" if _helpers._has_assenze_column("note_gestione") else ""
    _cert_col = ", a.certificato_medico" if _helpers._has_assenze_column("certificato_medico") else ""
    base_sql = f"""
        SELECT
            a.id,
            a.copia_nome AS dipendente,
            a.tipo_assenza,
            a.data_inizio,
            a.data_fine,
            a.consenso,
            a.moderation_status,
            a.motivazione_richiesta{_note_col}{_cert_col}{_helpers._col_utente_id()}
        FROM assenze a
        WHERE COALESCE(a.moderation_status, 2) IN (0, 1)
    """
    manager_where_params = []
    period_sql, period_params = _team_history_period(periodo)
    base_sql += period_sql
    manager_where_params = [*manager_where_params, *period_params]
    sql = _helpers._select_paginated(base_sql, "ORDER BY a.data_inizio DESC, a.id DESC", offset=offset, limit=limit)
    rows = _helpers._applica_nominativo(_helpers._fetch_all_dict(sql, manager_where_params))
    out = []
    for row in rows:
        _, moderation_label = _helpers._status_from_moderation(row.get("moderation_status"), default_pending=True)
        out.append(
            {
                "id": row.get("id"),
                "dipendente": str(row.get("dipendente") or "N/D"),
                "tipo": _helpers._tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta")),
                "consenso": moderation_label,
                "inizio_label": _helpers._dt_label(row.get("data_inizio")),
                "fine_label": _helpers._dt_label(row.get("data_fine")),
                "motivo": _helpers._strip_tipo_metadata_from_motivazione(row.get("motivazione_richiesta")),
                "certificato_medico": str(row.get("certificato_medico") or ""),
                "moderation_status": row.get("moderation_status"),
                "note_gestione": str(row.get("note_gestione") or ""),
            }
        )
    _helpers._mark_sharepoint_managed(out)
    return out


def _load_all_assenze_periodo(date_start: datetime, date_end: datetime, limit: int = 300) -> list[dict]:
    """Tutte le assenze in un periodo (non rifiutate): per AMMINISTRAZIONE."""
    if not _helpers._table_exists("assenze"):
        return []
    base_sql = f"""
        SELECT
            a.id,
            a.copia_nome AS dipendente,
            a.tipo_assenza,
            a.motivazione_richiesta,
            a.data_inizio,
            a.data_fine,
            a.consenso,
            a.moderation_status{_helpers._col_utente_id()}
        FROM assenze a
        WHERE a.data_inizio IS NOT NULL
          AND a.data_fine IS NOT NULL
          AND a.data_fine >= %s
          AND a.data_inizio <= %s
          AND COALESCE(a.moderation_status, 2) != 1
    """
    sql = _helpers._select_limited(base_sql, "ORDER BY a.data_inizio, a.id", limit)
    rows = _helpers._applica_nominativo(_helpers._fetch_all_dict(sql, [date_start, date_end]))
    out = []
    for row in rows:
        _, moderation_label = _helpers._status_from_moderation(row.get("moderation_status"), default_pending=True)
        out.append(
            {
                "id": row.get("id"),
                "dipendente": str(row.get("dipendente") or "N/D"),
                "tipo": _helpers._tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta")),
                "consenso": moderation_label,
                "inizio_label": _helpers._dt_label(row.get("data_inizio")),
                "fine_label": _helpers._dt_label(row.get("data_fine")),
            }
        )
    return out


def _resolve_capo_email_from_lookup(lookup_id: int | None, capi: list[dict]) -> str:
    if lookup_id is None:
        return ""
    return _helpers._resolve_capo_option_value_from_ids(local_id=None, lookup_id=lookup_id, capi=capi)


def _prefill_from_copy(copy_from: str, capi: list[dict]) -> dict | None:
    source = str(copy_from or "").strip()
    if not source:
        return None

    local_id = _helpers._as_int(source)
    if local_id is not None:
        row = _helpers._get_assenza(local_id)
        if row:
            capo_local_id = _helpers._as_int(row.get("capo_reparto_id"))
            capo_lookup = _helpers._as_int(row.get("capo_reparto_lookup_id"))
            return {
                "tipo": _helpers._tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta")),
                "motivazione": _helpers._strip_tipo_metadata_from_motivazione(row.get("motivazione_richiesta")),
                "capo_email": _helpers._resolve_capo_option_value_from_ids(local_id=capo_local_id, lookup_id=capo_lookup, capi=capi),
                "salta_approvazione": bool(_helpers._as_bool(row.get("salta_approvazione"))),
            }

    sp_item = _helpers._graph_get_item(source)
    if not sp_item:
        return None
    fields = sp_item.get("fields") or {}
    capo_lookup = _helpers._as_int(fields.get("C_x002e_RepartoLookupId"))
    return {
        "tipo": _helpers._tipo_for_display(fields.get("Tipoassenza"), fields.get("Motivazionerichiesta")),
        "motivazione": _helpers._strip_tipo_metadata_from_motivazione(fields.get("Motivazionerichiesta")),
        "capo_email": _resolve_capo_email_from_lookup(capo_lookup, capi),
        "salta_approvazione": bool(_helpers._as_bool(fields.get("Salta_x0020_approvazione"))),
    }


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


def _contesto_calendario(email: str, form: dict) -> dict:
    """Spunta «Metti nel mio calendario Outlook»: Graph acceso «su richiesta» e casella aziendale."""
    from .. import outlook_sync

    email = str(email or "").strip().lower()
    offerta = bool(email and "@" in email and outlook_sync.su_richiesta())
    return {
        "calendario_opzione": offerta,
        "calendario_email": email if offerta else "",
        "form_calendario": offerta and bool(_helpers._as_bool(form.get("calendario"))),
    }


def _richiedi_calendario(request, local_ids: list[int]) -> None:
    """Dopo l'inserimento: le richieste nel calendario Outlook di chi le ha inserite."""
    if request.POST.get("calendario") != "1" or not local_ids:
        return
    from .. import outlook_sync

    _name, email, _legacy = _helpers._legacy_identity(request)
    try:
        if outlook_sync.su_richiesta():
            outlook_sync.richiedi(local_ids, email, da=request.user.get_username())
    except Exception:
        logger.warning("Calendario Outlook non richiesto per %s", local_ids, exc_info=True)


def _richiedi_calendario_capo(request, item_id: int) -> None:
    """Approvata dal portale con la spunta: nel calendario Outlook di chi approva."""
    from .. import outlook_sync

    _name, email, _legacy = _helpers._legacy_identity(request)
    try:
        if outlook_sync.su_richiesta():
            outlook_sync.richiedi(item_id, email, da=request.user.get_username())
    except Exception:
        logger.warning("Calendario Outlook non richiesto per %s", item_id, exc_info=True)


def _render_richiesta(request, success: str = "", error: str = "", form_data: dict | None = None):
    perms = _helpers._assenze_permissions(request)
    name, email, _legacy_id = _helpers._legacy_identity(request)
    display_name = _resolve_request_display_name(
        legacy_user_id=_legacy_id,
        email=email,
        username=request.user.get_username(),
        fallback_name=name,
    )
    capi = _helpers._load_capi_options()
    motivazioni = _motivazioni_options()
    copy_from = str(request.GET.get("copy_from") or "").strip()
    prefill = _prefill_from_copy(copy_from, capi)

    can_insert_for_others = perms.get("can_insert_for_others", False)
    dipendenti = _insertable_dipendenti_for_request(request) if can_insert_for_others else []

    # Flessibilita: orari da Impostazioni e elenco degli abilitati. Il form li usa
    # per proporre le sole combinazioni ammesse; la verifica resta lato server.
    fless_conf = _helpers._flessibilita_config()
    fless_abilitati = _helpers._flessibilita_abilitati_ids()
    mio_anagrafica_id = _helpers._resolve_anagrafica_employee_id_for_user(
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
        "caporeparto": _helpers._resolve_default_capo_for_user(
            name=display_name,
            email=email,
            username=request.user.get_username(),
            capi=capi,
            legacy_user_id=_legacy_id,
        ),
        # Date vuote: chi compila deve sceglierle, non partire da oggi per sbaglio.
        "date_start": "",
        "date_end": "",
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

    return _helpers.render(
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
            "form_salta_approvazione": bool(_helpers._as_bool(merged_form.get("salta_approvazione"))),
            **_contesto_calendario(email, merged_form),
            "flessibilita_entrate": fless_conf.entrate,
            "flessibilita_uscite": fless_conf.uscite,
            "flessibilita_abilitati_ids": sorted(fless_abilitati),
            "flessibilita_abilitato_io": mio_anagrafica_id in fless_abilitati,
            "ore_mattina_list": [f"{h:02d}" for h in range(6, 23)],
            "ore_pom_list":     [f"{h:02d}" for h in range(12, 24)],
            "minuti_list":      [f"{m:02d}" for m in range(0, 60, 5)],
            **_helpers._template_perm_context(request),
        },
    )


@login_required
def richiesta_assenze(request):
    if not _helpers._assenze_permissions(request).get("can_insert"):
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
    name, email, legacy_id = _helpers._legacy_identity(request)
    perms = _helpers._assenze_permissions(request)
    e_capo = perms.get("view_scope") in {"all", "reparto"}

    richieste_da_approvare = _helpers._load_pending_for_manager(
        legacy_id,
        limit=40,
        manager_name=name,
        manager_email=email,
    )
    if not e_capo:
        richieste_da_approvare = []
    richieste_personali = _helpers._load_personal(name, email, limit=40)

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
    calcoli_hr.annota_coda(richieste_da_approvare)
    _prepare_team_rows(request, richieste_da_approvare)
    _prepare_team_rows(request, richieste_dipendenti_gestite)

    return _helpers.render(
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
            **_helpers._template_perm_context(request),
        },
    )


@login_required
@ensure_csrf_cookie
def car_dashboard(request):
    """Dashboard segnalazioni.

    Chi vede quante righe dipende dal perimetro di visibilita' (`view_scope`), non
    dal permesso di approvare: DIREZIONE/HR possono avere la vista aziendale senza
    poter decidere sulle richieste, mentre i pulsanti Approva/Rifiuta restano
    legati a `can_update_any` / `can_update_owned`.
    """
    perms = _helpers._assenze_permissions(request)
    is_admin = perms.get("can_update_any", False)
    is_car = perms.get("can_update_owned", False)
    view_all = perms.get("view_scope") == "all"
    if perms.get("view_scope") == "own":
        return HttpResponseForbidden("Accesso non consentito: questa pagina richiede la visibilità sulle assenze del reparto o dell'azienda.")
    legacy_user_id = perms["legacy_user_id"]
    manager_name, manager_email, _ = _helpers._legacy_identity(request)

    pending_scope_raw = str(request.GET.get("scope") or "").strip().lower()
    pending_scope = "mine"
    if view_all and pending_scope_raw in {"all", "tutte", "global"}:
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

    history_page = max(1, min(_helpers._as_int(request.GET.get("pagina_storico")) or 1, 100000))
    history_period = request.GET.get("periodo_storico", "tutte")
    if history_period not in {"tutte", "passate", "future"}:
        history_period = "tutte"
    history_offset = (history_page - 1) * 30
    now = timezone.localtime()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    monday = today_start - timedelta(days=today_start.weekday())
    next_monday = monday + timedelta(days=7)

    if view_all:
        if pending_scope == "all":
            da_gestire = _load_all_pending(limit=100)
        else:
            da_gestire = _helpers._load_pending_for_manager(
                legacy_user_id,
                limit=100,
                manager_name=manager_name,
                manager_email=manager_email,
            )
        gestite = _load_all_gestite(limit=31, offset=history_offset, periodo=history_period)
        riepilogo_oggi = _load_all_assenze_periodo(today_start, today_end, limit=200)
        riepilogo_settimana = _load_all_assenze_periodo(monday, next_monday, limit=500)
    else:
        da_gestire = _helpers._load_pending_for_manager(
            legacy_user_id,
            limit=60,
            manager_name=manager_name,
            manager_email=manager_email,
        )
        gestite = _load_gestite_for_manager(
            legacy_user_id,
            limit=31,
            offset=history_offset,
            periodo=history_period,
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

    history_has_next = len(gestite) > 30
    gestite = gestite[:30]
    calcoli_hr.annota_coda(da_gestire)
    _prepare_team_rows(request, da_gestire)
    _prepare_team_rows(request, gestite)
    sync_diag = None
    if show_diag:
        diag_item_ids = [r.get("id") for r in gestite[:8]]
        diag_item_ids.extend(r.get("id") for r in da_gestire[:4])
        sync_diag = _build_sharepoint_sync_diagnostics(diag_item_ids, limit=12)

    return _helpers.render(
        request,
        "assenze/pages/car_dashboard.html",
        {
            "da_gestire": da_gestire,
            **_contesto_calendario(_helpers._legacy_identity(request)[1], {}),
            # Solo i tipi effettivamente presenti in coda: una pillola che non
            # filtra niente e' rumore.
            "tipi_in_coda": sorted({str(r.get("tipo") or "").strip() for r in da_gestire if r.get("tipo")}),
            "gestite": gestite,
            "history_page": history_page,
            "history_previous": history_page - 1,
            "history_next": history_page + 1,
            "history_has_next": history_has_next,
            "history_period": history_period,
            "riepilogo_oggi": riepilogo_oggi,
            "riepilogo_settimana": riepilogo_settimana,
            "data_oggi": today_start.strftime("%d-%m-%Y"),
            "data_lunedi": monday.strftime("%d-%m-%Y"),
            "data_domenica": (next_monday - timedelta(days=1)).strftime("%d-%m-%Y"),
            "is_admin_view": is_admin,
            "can_view_all": view_all,
            "pending_scope": pending_scope,
            "show_diag": show_diag,
            "capo_diag": capo_diag,
            "sync_diag": sync_diag,
            **_helpers._template_perm_context(request),
        },
    )


def api_car_aggiorna_consenso(request, item_id: int):
    """API per CAR: approva o rifiuta una singola assenza del proprio reparto."""
    perms = _helpers._assenze_permissions(request)
    if not perms.get("can_update_owned") and not perms.get("can_update_any"):
        return _helpers._json_error("Permessi insufficienti: solo i CAR possono aggiornare il consenso.", status=403)

    current = _helpers._get_assenza(item_id)
    if not current:
        return _helpers._json_error("Record non trovato.", status=404)
    if not _helpers._can_manage_record(request, current, require_delete=False):
        return _helpers._json_error("Permessi insufficienti: puoi gestire solo record assegnati al tuo reparto.", status=403)
    if _helpers._e_propria_assenza(request, current):
        return _helpers._json_error("Non puoi approvare o rifiutare una tua richiesta: decide un altro responsabile.", status=403)

    managed_error = _helpers._sharepoint_managed_error(item_id)
    if managed_error:
        return managed_error

    payload = _helpers._request_json(request)
    consenso_raw = (payload.get("consenso") if payload else None) or request.POST.get("consenso") or ""
    consenso = _helpers._norm_consenso(consenso_raw)
    if consenso not in {"Approvato", "Rifiutato"}:
        return _helpers._json_error("Valore consenso non valido. Usa 'Approvato' o 'Rifiutato'.", status=400)

    note_raw = (payload.get("note_gestione") if payload else None)
    if note_raw is None:
        note_raw = request.POST.get("note_gestione", "")
    note_gestione = str(note_raw or "").strip()

    sync_result = _helpers._applica_moderazione(request, item_id, current, consenso, note_gestione)
    if sync_result is None:
        return _helpers._json_error("Aggiornamento non eseguito.", status=500)
    if consenso == "Approvato" and payload and payload.get("calendario") is True:
        _richiedi_calendario_capo(request, item_id)

    return JsonResponse({"ok": True, "item_id": item_id, "consenso": consenso, "note_gestione": note_gestione, "sync": sync_result})


@login_required
@require_http_methods(["POST"])
def api_mia_assenza_update(request, item_id: int):
    """Consente a un utente di modificare la propria richiesta ancora 'In attesa'."""
    perms = _helpers._assenze_permissions(request)
    if not perms.get("can_insert"):
        return _helpers._json_error("Permessi insufficienti.", status=403)

    current = _helpers._get_assenza(item_id)
    if not current:
        return _helpers._json_error("Record non trovato.", status=404)

    # Verifica appartenenza: solo la propria richiesta
    name, email, _ = _helpers._legacy_identity(request)
    rec_nome = str(current.get("copia_nome") or "").strip().upper()
    rec_email = str(current.get("email_esterna") or "").strip().upper()
    user_nome = str(name or "").strip().upper()
    user_email = str(email or "").strip().upper()
    is_own = (user_nome and rec_nome == user_nome) or (user_email and rec_email == user_email)
    if not is_own:
        return _helpers._json_error("Puoi modificare solo le tue richieste.", status=403)

    # Deve essere ancora In attesa
    mod_status = _helpers._as_int(current.get("moderation_status"))
    if mod_status is None:
        mod_status = _helpers._CONSENSO_TO_MOD.get(_helpers._norm_consenso(current.get("consenso")), 2)
    if mod_status != 2:
        return _helpers._json_error("La richiesta non è più modificabile (non è in stato 'In attesa').", status=400)
    managed_error = _helpers._sharepoint_managed_error(item_id)
    if managed_error:
        return managed_error

    payload = _helpers._request_json(request)
    requested_tipo = (
        (payload.get("tipo") if payload else None)
        or request.POST.get("tipo")
        or _helpers._tipo_for_display(current.get("tipo_assenza"), current.get("motivazione_richiesta"))
    )
    tipo = _helpers._tipo_for_storage(requested_tipo)
    inizio_raw = (payload.get("inizio") if payload else None) or request.POST.get("inizio")
    fine_raw = (payload.get("fine") if payload else None) or request.POST.get("fine")
    motivazione = (payload.get("motivazione") if payload else None)
    if motivazione is None:
        motivazione = request.POST.get("motivazione", current.get("motivazione_richiesta") or "")
    motivazione = _helpers._motivazione_for_storage(requested_tipo, motivazione)
    certificato_medico = payload.get("certificato_medico") if payload and "certificato_medico" in payload else None
    if certificato_medico is None:
        certificato_medico = request.POST.get("certificato_medico", current.get("certificato_medico") or "")
    certificato_medico = _helpers._certificato_medico_for_tipo(tipo, certificato_medico, current.get("certificato_medico"))

    dt_start = _helpers._parse_input_dt(inizio_raw) if inizio_raw else current.get("data_inizio")
    dt_end = _helpers._parse_input_dt(fine_raw) if fine_raw else current.get("data_fine")
    dt_end, auto_fine_msg = _helpers._autocorreggi_fine(dt_start, dt_end)

    err_msg, warn_msg = _helpers._validate_business_rules(
        tipo=tipo,
        dt_start=dt_start,
        dt_end=dt_end,
        person_name=str(current.get("copia_nome") or ""),
        person_email=str(current.get("email_esterna") or ""),
        person_anagrafica_id=_helpers._anagrafica_id_for_assenza_row(current),
        exclude_item_id=item_id,
    )
    if err_msg:
        return _helpers._json_error(err_msg, status=400)

    updates = {
        "tipo_assenza": tipo,
        "data_inizio": dt_start,
        "data_fine": dt_end,
        "motivazione_richiesta": motivazione,
        "certificato_medico": certificato_medico,
        "modified_datetime": timezone.now(),
    }
    ok = _helpers._update_assenza(item_id, updates)
    if not ok:
        return _helpers._json_error("Aggiornamento non eseguito.", status=500)
    calcoli_hr.registra(item_id, "modificata", utente=request.user.get_username(), prima=current, dopo=updates)
    _helpers._notify_assenza_modificata(request, current, calcoli_hr.differenze(current, updates))

    sync_result = _helpers._sp_enqueue_upsert(item_id)

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

    perms = _helpers._assenze_permissions(request)
    if not perms.get("can_insert"):
        return HttpResponseForbidden("Permessi insufficienti: inserimento richieste non consentito.")
    if not _helpers._table_exists("assenze"):
        return _render_richiesta(request, error="Tabella locale 'assenze' non disponibile.")

    requested_tipo = request.POST.get("tipoassenza")
    tipo = _helpers._tipo_for_storage(requested_tipo)
    motivazione = _helpers._motivazione_for_storage(requested_tipo, request.POST.get("motivazione"))
    certificato_medico = _helpers._certificato_medico_for_tipo(tipo, request.POST.get("certificato_medico"))
    date_start = str(request.POST.get("date_start") or "").strip()
    date_end = str(request.POST.get("date_end") or "").strip()
    time_start = str(request.POST.get("time_start") or "00:00").strip() or "00:00"
    time_end = str(request.POST.get("time_end") or "23:59").strip() or "23:59"
    capo_raw = str(request.POST.get("caporeparto") or "").strip()
    shortcut = str(request.POST.get("shortcut") or "").strip()
    salta_approvazione = bool(_helpers._as_bool(request.POST.get("salta_approvazione"))) if perms.get("can_skip_approval") else False
    tipo_ui = _helpers._norm_tipo(tipo)

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
    dt_end, auto_fine_msg = _helpers._autocorreggi_fine(start_local, end_local)

    if tipo_ui == "Permesso" and dt_start.date() != dt_end.date():
        return _render_richiesta(
            request,
            error="Il permesso deve iniziare e finire nello stesso giorno.",
            form_data=request.POST.dict(),
        )

    inserter_name, inserter_email, inserter_legacy_id = _helpers._legacy_identity(request)
    inserting_for_other = False
    dipendente_id_raw = str(request.POST.get("dipendente_id") or "").strip()

    if perms.get("can_insert_for_others") and dipendente_id_raw:
        ana_id = _helpers._as_int(dipendente_id_raw)
        if not ana_id:
            return _render_richiesta(request, error="ID dipendente non valido.", form_data=request.POST.dict())
        if not _helpers._can_insert_for_dipendente(request, ana_id):
            return _render_richiesta(
                request,
                error="Non sei autorizzato a inserire richieste per un altro dipendente.",
                form_data=request.POST.dict(),
            )
        identity = _helpers._resolve_employee_identity_from_anagrafica(ana_id)
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
        person_anagrafica_id = _helpers._resolve_anagrafica_employee_id_for_user(
            legacy_user_id=legacy_id,
            email=email,
            username=request.user.get_username(),
            name=display_name,
        )

    # Permesso ripetuto: stesso orario del primo giorno, una richiesta per ogni
    # giorno lavorativo fino a «ripeti_fino_al» (il primo giorno conta sempre).
    giorni = [dt_start.date()]
    ripeti_raw = str(request.POST.get("ripeti_fino_al") or "").strip() if tipo_ui == "Permesso" else ""
    if ripeti_raw:
        try:
            ripeti_fino = datetime.strptime(ripeti_raw, "%Y-%m-%d").date()
        except ValueError:
            return _render_richiesta(request, error="Data «Ripeti fino al» non valida.", form_data=request.POST.dict())
        if ripeti_fino < dt_start.date():
            return _render_richiesta(
                request,
                error="La data «Ripeti fino al» deve essere uguale o successiva alla data inizio.",
                form_data=request.POST.dict(),
            )
        if (ripeti_fino - dt_start.date()).days > RIPETI_MAX_GIORNI:
            return _render_richiesta(
                request,
                error=f"Un permesso si può ripetere al massimo per {RIPETI_MAX_GIORNI} giorni di calendario.",
                form_data=request.POST.dict(),
            )
        cal = calcoli_hr.calendario(dt_start.date(), ripeti_fino)
        giorni += cal.giorni_lavorativi(dt_start.date() + timedelta(days=1), ripeti_fino)
    occorrenze = [(dt_start, dt_end)] + [
        (datetime.combine(g, dt_start.time()), datetime.combine(g, dt_end.time())) for g in giorni[1:]
    ]
    ripetuto = len(occorrenze) > 1

    avvisi: list[str] = [auto_fine_msg] if auto_fine_msg else []
    for occ_start, occ_end in occorrenze:
        err_msg, warn_msg = _helpers._validate_business_rules(
            tipo=tipo,
            dt_start=occ_start,
            dt_end=occ_end,
            person_name=display_name,
            person_email=email,
            person_anagrafica_id=person_anagrafica_id,
            shortcut=shortcut,
        )
        if err_msg:
            prefisso = f"{occ_start:%d/%m/%Y}: " if ripetuto else ""
            return _render_richiesta(request, error=f"{prefisso}{err_msg}", form_data=request.POST.dict())
        # Controlli HR (saldo, contatori, chiusure): avvisano, non bloccano.
        avvisi_hr = calcoli_hr.avvisi_richiesta(
            anagrafica_id=person_anagrafica_id, tipo=tipo_ui, motivazione=motivazione, inizio=occ_start, fine=occ_end,
        )
        for testo in [warn_msg, *avvisi_hr]:
            if testo and testo not in avvisi:
                avvisi.append(testo)
    warn_msg = " ".join(avvisi)

    # Caporeparto AUTORITATIVO lato server: quello assegnato al dipendente (il
    # campo del form è bloccato). Se quel caporeparto è assente nel giorno della
    # richiesta, l'approvazione passa al suo superiore. Fallback al valore del
    # form solo se il server non riesce a risolvere (compatibilità).
    capi_options = _helpers._load_capi_options()
    capo_username = "" if inserting_for_other else request.user.get_username()

    def _capo_del_giorno(giorno):
        capo_effective, capo_escalated = _helpers._effective_capo_option(
            name=display_name,
            email=email,
            username=capo_username,
            legacy_user_id=legacy_id,
            capi=capi_options,
            request_day=giorno,
        )
        capo_final = capo_effective or capo_raw

        # Chi puo' scegliere il caporeparto (tutti tranne il ruolo UTENTE) invia al
        # capo selezionato, purche' sia fra quelli configurati. Se lascia quello
        # assegnato, resta valida l'escalation al superiore per assenza del capo.
        capo_scelto = False
        if perms.get("can_choose_capo") and capo_raw:
            chosen = _helpers._find_capo_dict_for_option(capo_raw, capi_options)
            if chosen is None:
                return None
            capo_assegnato = _helpers._resolve_default_capo_for_user(
                name=display_name, email=email, username=capo_username,
                capi=capi_options, legacy_user_id=legacy_id,
            )
            assegnato = _helpers._find_capo_dict_for_option(capo_assegnato, capi_options) if capo_assegnato else None
            effettivo = _helpers._find_capo_dict_for_option(capo_final, capi_options) if capo_final else None
            if chosen is not assegnato and chosen is not effettivo:
                capo_final = _helpers._capo_option_value(chosen) or capo_raw
                capo_escalated = False
                capo_scelto = True
        return capo_final, capo_escalated, capo_scelto

    capi_giorno = []
    for occ_start, _occ_end in occorrenze:
        capo = _capo_del_giorno(occ_start.date())
        if capo is None:
            return _render_richiesta(request, error="Caporeparto selezionato non valido.", form_data=request.POST.dict())
        capi_giorno.append(capo)

    def _payload(occ_start, occ_end, capo_final):
        return {
            "sharepoint_item_id": None,
            "nome_lookup_id": _resolve_nome_lookup_id(legacy_id, display_name),
            "copia_nome": display_name,
            "email_esterna": email,
            "tipo_assenza": tipo,
            "capo_reparto_id": _resolve_capo_local_id(capo_final),
            "capo_reparto_lookup_id": _resolve_capo_lookup_id(capo_final),
            "data_inizio": occ_start,
            "data_fine": occ_end,
            "motivazione_richiesta": motivazione,
            "certificato_medico": certificato_medico,
            "salta_approvazione": salta_approvazione,
            "consenso": "In attesa",
            "moderation_status": 2,
            "created_datetime": timezone.now(),
            "modified_datetime": timezone.now(),
        }

    local_ids: list[int] = []
    try:
        with transaction.atomic():
            for n, ((occ_start, occ_end), (capo_final, _esc, _scelto)) in enumerate(
                zip(occorrenze, capi_giorno, strict=True)
            ):
                # Permesso ripetuto: solo il primo giorno fa partire le automazioni
                # (una mail al capo, una conferma); gli altri seguono la sua decisione.
                if n:
                    _helpers._set_automation_queue_skip(True)
                try:
                    local_id = _insert_assenza(_payload(occ_start, occ_end, capo_final))
                finally:
                    if n:
                        _helpers._set_automation_queue_skip(False)
                if local_id is None:
                    raise RuntimeError("impossibile ottenere ID locale")
                # Stessa transazione dell'insert: l'evento in coda del trigger SQL
                # diventa visibile solo insieme all'autore (``inserito_da_gruppo``).
                _registra_inserita_da(local_id, gruppo=perms.get("group"), inserito_da=request.user.get_username())
                local_ids.append(local_id)
            if ripetuto:
                serie.registra(local_ids)
    except RuntimeError:
        return _render_richiesta(request, error="Richiesta non salvata: impossibile ottenere ID locale.", form_data=request.POST.dict())
    except Exception as exc:
        return _render_richiesta(request, error=f"Errore salvataggio locale: {exc}", form_data=request.POST.dict())

    _richiedi_calendario(request, local_ids)
    motivo_storico = f"Inserita per conto di {display_name}" if inserting_for_other else ""
    if ripetuto:
        nota = f"Permesso ripetuto: {len(local_ids)} giorni dal {giorni[0]:%d/%m/%Y} al {giorni[-1]:%d/%m/%Y}"
        motivo_storico = f"{motivo_storico}. {nota}" if motivo_storico else nota
    accodate = 0
    for local_id, (capo_final, capo_escalated, capo_scelto) in zip(local_ids, capi_giorno, strict=True):
        calcoli_hr.registra(local_id, "creata", utente=request.user.get_username(), motivo=motivo_storico)

        if inserting_for_other:
            _helpers.log_action(
                request,
                "assenza_inserita_per_conto",
                "assenze",
                {"local_id": local_id, "for_dipendente": display_name, "by": inserter_name},
            )

        if capo_scelto:
            try:
                _registra_capo_scelto(
                    local_id,
                    _helpers._find_capo_dict_for_option(capo_final, capi_options),
                    scelto_da=request.user.get_username(),
                )
            except Exception:
                pass
            _helpers.log_action(
                request,
                "assenza_caporeparto_scelto",
                "assenze",
                {"local_id": local_id, "capo_scelto": capo_final, "for_dipendente": display_name},
            )

        if capo_escalated:
            _helpers.log_action(
                request,
                "assenza_escalation_caporeparto",
                "assenze",
                {"local_id": local_id, "motivo": "caporeparto assente nel giorno", "capo_effettivo": capo_final},
            )

        if _helpers._sp_enqueue_upsert(local_id).get("queued"):
            accodate += 1

    if ripetuto:
        _helpers.log_action(
            request,
            "assenza_permesso_ripetuto",
            "assenze",
            {"local_ids": local_ids, "giorni": len(local_ids), "for_dipendente": display_name},
        )

    sync_msg = "Arriverà su SharePoint entro pochi minuti." if accodate else "Sincronizzazione SharePoint non configurata."
    warn_suffix = f" {warn_msg}" if warn_msg else ""
    proxy_note = f" (inserito per conto di {display_name})" if inserting_for_other else ""
    if ripetuto:
        elenco = ", ".join(f"{g:%d/%m}" for g in giorni)
        return _render_richiesta(
            request,
            success=(
                f"{len(local_ids)} permessi registrati su DB locale{proxy_note}, "
                f"dalle {dt_start:%H:%M} alle {dt_end:%H:%M} nei giorni {elenco}. "
                f"Il capo riceve una sola mail per tutti i giorni. {sync_msg}{warn_suffix}"
            ),
        )
    return _render_richiesta(request, success=f"Richiesta registrata su DB locale{proxy_note}. {sync_msg}{warn_suffix}")


@login_required
@require_http_methods(["POST"])
def aggiorna_consenso_placeholder(request, item_id: int):
    if not _helpers._assenze_permissions(request).get("can_update_any"):
        return _helpers._json_error("Permessi insufficienti: aggiornamento consenso non consentito.", status=403)
    managed_error = _helpers._sharepoint_managed_error(item_id)
    if managed_error:
        return managed_error
    consenso = _helpers._norm_consenso(request.POST.get("consenso"))
    updates = {
        "consenso": consenso,
        "moderation_status": _helpers._CONSENSO_TO_MOD.get(consenso, 2),
        "modified_datetime": timezone.now(),
    }
    updates.update(_helpers._approval_timestamp_update(consenso))
    ok = _helpers._update_assenza(
        item_id,
        updates,
    )
    if ok:
        _helpers._sp_enqueue_upsert(item_id)
    return JsonResponse({"ok": bool(ok), "item_id": item_id, "consenso": consenso})


@login_required
def export_assenze_car_csv(request):
    """Esporta in CSV le assenze visibili: il proprio reparto, o tutte per chi ha
    la visibilita' aziendale."""
    perms = _helpers._assenze_permissions(request)
    if perms.get("view_scope") in {"own", "none"}:
        return HttpResponseForbidden("Permessi insufficienti.")
    if sistema_ruoli_attivo():
        esportare = decisione(request, _helpers.MODULO, "esportare")
        if not esportare.consentito or esportare.ambito == "propri":
            from core.permessi.negato import risposta_negata

            return risposta_negata(request, pagina="Assenze")

    legacy_user = getattr(request, "legacy_user", None) or _helpers.get_legacy_user(request.user)
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

    if perms.get("view_scope") == "all":
        rows_data = _load_all_pending(limit=5000) + _load_all_gestite(limit=5000)
    else:
        rows_data = _helpers._load_pending_for_manager(
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
    _prepare_team_rows(request, rows_data)
    _helpers.log_action(
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

    headers = ["Dipendente", "Tipo", "Inizio", "Fine", "Stato", "Certificato arrivato", "Note"]

    def row_iter():
        for r in rows_data:
            yield [
                r.get("dipendente", ""),
                r.get("tipo", ""),
                r.get("inizio_label", ""),
                r.get("fine_label", ""),
                r.get("consenso", ""),
                "Sì" if r.get("certificato_medico") else "",
                r.get("note_gestione", ""),
            ]

    return _helpers._csv_streaming_response(row_iter(), headers, "assenze_reparto.csv")


# ---------------------------------------------------------------------------
# Certificazione Presenza
# ---------------------------------------------------------------------------

@login_required
def certificazione_presenza(request):
    from ..models import CertificazionePresenza

    is_admin = _helpers.user_can_modulo_action(request, "assenze", "admin_assenze")
    # SEC: la certificazione presenze è una funzione amministrativa. Senza questo
    # enforcement la pagina elencava TUTTE le CertificazionePresenza e permetteva
    # create/update/delete (con auto-inserimento di un'assenza già "Approvato",
    # salta_approvazione=True, per un dipendente arbitrario) a qualsiasi utente
    # autenticato, scavalcando l'approvazione CAR. Il permesso era già calcolato
    # ma mai applicato.
    if not is_admin:
        return _helpers.render(request, "core/pages/forbidden.html", status=403)
    perm_ctx = _helpers._template_perm_context(request)

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
                _helpers.log_action(request, "certifica_presenza_delete", {"pk": pk_raw})
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
                        _helpers.log_action(request, "certifica_presenza_update", {"pk": obj.pk})
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
                    _helpers.log_action(request, "certifica_presenza_create", {"pk": obj.pk})

                    # --- Auto-approva: inserisce in tabella assenze con consenso=Approvato
                    #     e tenta push a SharePoint (flusso Power Automate) ---
                    if _helpers._table_exists("assenze"):
                        try:
                            now = timezone.now()
                            dt_start = datetime.combine(data_v, em_v)
                            dt_end   = datetime.combine(data_v, um_v)
                            assenza_payload = {
                                "sharepoint_item_id": None,
                                "nome_lookup_id":     None,
                                "copia_nome":         nome,
                                "email_esterna":      inserito_da,
                                "tipo_assenza":       _helpers._tipo_for_storage("Certifica presenza"),
                                "capo_reparto_lookup_id": None,
                                "data_inizio":        dt_start,
                                "data_fine":          dt_end,
                                "motivazione_richiesta": _helpers._motivazione_for_storage(
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
                                _helpers._sp_enqueue_upsert(local_id)
                        except Exception as exc:
                            _helpers.logger.warning("certifica_presenza: errore auto-push assenze: %s", exc)

                    form_success = True

                # Aggiorna lista dopo salvataggio
                qs2 = CertificazionePresenza.objects.all()
                if q_nome:   qs2 = qs2.filter(nome_dipendente__icontains=q_nome)
                records = list(qs2[:200])

    ore_mattina_list   = [f"{h:02d}" for h in range(6, 23)]
    ore_pom_list       = [f"{h:02d}" for h in range(12, 24)]
    minuti_list        = [f"{m:02d}" for m in range(0, 60, 5)]

    return _helpers.render(request, "assenze/pages/certificazione_presenza.html", {
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
