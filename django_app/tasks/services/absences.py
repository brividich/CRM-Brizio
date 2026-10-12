"""Assenze dei dipendenti viste dal KICK-OFF (conflitti con le date delle attivita').

La fonte e' il servizio dell'app ``assenze`` (``disponibilita_per_anagrafica``),
interrogato per ``anagrafica_dipendenti.id``: l'utente si collega alla sua
anagrafica dal ponte ``anagrafica_dipendenti.utente_id = Profile.legacy_user_id``,
e il servizio cerca le richieste per tutte le varianti del nominativo
(«Cognome Nome» / «Nome Cognome», accenti) e per email. Il vecchio confronto
esatto fra ``copia_nome`` e il nome completo Django resta solo come riserva per
gli utenti senza anagrafica collegata.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from django.db import DatabaseError, connections

from assenze.availability import disponibilita_per_anagrafica
from core.legacy_utils import legacy_table_columns

from ..models import (
    Task,
)

logger = logging.getLogger(__name__)

_STATO_LABEL = {"confermata": "Approvato", "pendente": "In attesa"}


def _legacy_anagrafica_id_for_user(user) -> int | None:
    """``anagrafica_dipendenti.id`` dell'utente, dal ponte ``utente_id``.

    ``Profile.legacy_user_id`` e' l'id di ``utenti``, non dell'anagrafica: i due
    interi non vanno mai confrontati direttamente.
    """
    profile = getattr(user, "profile", None)
    legacy_user_id = getattr(profile, "legacy_user_id", None) if profile else None
    if not legacy_user_id:
        return None
    columns = legacy_table_columns("anagrafica_dipendenti") or []
    if "id" not in columns or "utente_id" not in columns:
        return None
    try:
        rows = _legacy_fetch_all_dict(
            "SELECT id FROM anagrafica_dipendenti WHERE utente_id = %s ORDER BY id DESC",
            [int(legacy_user_id)],
        )
    except Exception:
        logger.warning("Anagrafica non risolta per legacy_user_id=%s", legacy_user_id, exc_info=True)
        return None
    for row in rows:
        if row.get("id") is not None:
            return int(row["id"])
    return None


def _absences_from_anagrafica(anagrafica_id: int, *, date_start: date, date_end: date) -> list[dict]:
    rows = disponibilita_per_anagrafica([anagrafica_id], date_start, date_end, includi_pendenti=True)
    normalized = [
        {
            "id": None,
            "start_date": row["data_inizio"],
            "end_date": row["data_fine"],
            "tipo": row.get("tipo") or "Assenza",
            "status": _STATO_LABEL.get(row.get("stato"), "In attesa"),
        }
        for row in rows.get(anagrafica_id, [])
    ]
    normalized.sort(key=lambda row: (row["start_date"], row["end_date"]))
    return normalized


def _legacy_fetch_all_dict(sql: str, params: list | tuple | None = None) -> list[dict]:
    with connections["default"].cursor() as cursor:
        cursor.execute(sql, params or [])
        columns = [str(col[0]) for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _coerce_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except Exception:
        pass
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def _absence_status_label(row: dict) -> str:
    raw_status = row.get("moderation_status")
    try:
        parsed = int(raw_status)
    except (TypeError, ValueError):
        parsed = None
    status_map = {
        0: "Approvato",
        1: "Rifiutato",
        2: "In attesa",
        3: "Bozza",
        4: "Programmato",
    }
    if parsed is not None:
        return status_map.get(parsed, "In attesa")
    consenso = str(row.get("consenso") or "").strip()
    if consenso:
        return consenso
    return "In attesa"


def _load_user_absences(user, *, date_start: date, date_end: date) -> list[dict]:
    if not user or date_end < date_start:
        return []

    anagrafica_id = _legacy_anagrafica_id_for_user(user)
    if anagrafica_id is not None:
        return _absences_from_anagrafica(anagrafica_id, date_start=date_start, date_end=date_end)
    return _load_user_absences_by_name(user, date_start=date_start, date_end=date_end)


def _load_user_absences_by_name(user, *, date_start: date, date_end: date) -> list[dict]:
    """Riserva per utenti senza anagrafica: confronto esatto su nome completo/email."""
    columns = legacy_table_columns("assenze")
    if not columns:
        legacy_table_columns.cache_clear()
        columns = legacy_table_columns("assenze")
    if not columns or "data_inizio" not in columns or "data_fine" not in columns:
        return []

    full_name = str(user.get_full_name() or user.get_username() or "").strip()
    email = str(getattr(user, "email", "") or "").strip()

    identity_clauses: list[str] = []
    identity_params: list = []
    if "copia_nome" in columns and full_name:
        identity_clauses.append("UPPER(COALESCE(copia_nome,'')) = UPPER(%s)")
        identity_params.append(full_name)
    if "email_esterna" in columns and email:
        identity_clauses.append("UPPER(COALESCE(email_esterna,'')) = UPPER(%s)")
        identity_params.append(email)
    if not identity_clauses:
        return []

    range_start = datetime.combine(date_start, datetime.min.time())
    range_end = datetime.combine(date_end, datetime.max.time())

    status_clause = ""
    status_params: list = []
    if "moderation_status" in columns:
        status_clause = "AND COALESCE(moderation_status, 2) != %s"
        status_params.append(1)
    elif "consenso" in columns:
        status_clause = "AND UPPER(COALESCE(consenso,'')) NOT LIKE UPPER(%s)"
        status_params.append("%rifiut%")

    tipo_select = "tipo_assenza" if "tipo_assenza" in columns else "'' AS tipo_assenza"
    consenso_select = "consenso" if "consenso" in columns else "'' AS consenso"
    moderation_select = "moderation_status" if "moderation_status" in columns else "NULL AS moderation_status"

    sql = f"""
        SELECT
            id,
            data_inizio,
            data_fine,
            {tipo_select},
            {consenso_select},
            {moderation_select}
        FROM assenze
        WHERE ({' OR '.join(identity_clauses)})
          AND data_inizio IS NOT NULL
          AND data_fine IS NOT NULL
          AND data_fine >= %s
          AND data_inizio <= %s
          {status_clause}
        ORDER BY data_inizio ASC, id ASC
    """

    try:
        rows = _legacy_fetch_all_dict(sql, [*identity_params, range_start, range_end, *status_params])
    except DatabaseError:
        return []
    except Exception:
        return []

    normalized: list[dict] = []
    for row in rows:
        start_date = _coerce_date(row.get("data_inizio"))
        end_date = _coerce_date(row.get("data_fine"))
        if not start_date or not end_date:
            continue
        if end_date < start_date:
            start_date, end_date = end_date, start_date
        normalized.append(
            {
                "id": row.get("id"),
                "start_date": start_date,
                "end_date": end_date,
                "tipo": str(row.get("tipo_assenza") or "Assenza").strip() or "Assenza",
                "status": _absence_status_label(row),
            }
        )
    return normalized


def _task_date_absence_conflicts(task: Task) -> dict[str, list[dict]]:
    if not task.assigned_to_id:
        return {}

    target_dates: dict[str, date] = {}
    if task.due_date:
        target_dates["due_date"] = task.due_date
    if task.next_step_due:
        target_dates["next_step_due"] = task.next_step_due
    if not target_dates:
        return {}

    date_start = min(target_dates.values())
    date_end = max(target_dates.values())
    absences = _load_user_absences(task.assigned_to, date_start=date_start, date_end=date_end)
    if not absences:
        return {}

    conflicts: dict[str, list[dict]] = {}
    for field_name, target_date in target_dates.items():
        field_conflicts = [row for row in absences if row["start_date"] <= target_date <= row["end_date"]]
        if field_conflicts:
            conflicts[field_name] = field_conflicts
    return conflicts


def _build_task_absence_day_map(tasks: list[Task], *, timeline_start: date, timeline_end: date) -> dict[int, dict[date, list[dict]]]:
    if timeline_end < timeline_start:
        return {}

    user_absence_cache: dict[int, list[dict]] = {}
    for task in tasks:
        if not task.assigned_to_id or task.assigned_to_id in user_absence_cache:
            continue
        user_absence_cache[task.assigned_to_id] = _load_user_absences(
            task.assigned_to,
            date_start=timeline_start,
            date_end=timeline_end,
        )

    per_task_day_map: dict[int, dict[date, list[dict]]] = {}
    for task in tasks:
        task_day_map: dict[date, list[dict]] = {}
        for absence in user_absence_cache.get(task.assigned_to_id, []):
            start_date = max(absence["start_date"], timeline_start)
            end_date = min(absence["end_date"], timeline_end)
            if end_date < start_date:
                continue
            current = start_date
            while current <= end_date:
                task_day_map.setdefault(current, []).append(absence)
                current += timedelta(days=1)
        per_task_day_map[task.id] = task_day_map
    return per_task_day_map
