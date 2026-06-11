from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
import json
import logging
import re
import traceback
from types import SimpleNamespace
from typing import Any

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.db import connection, transaction
from django.db.utils import ProgrammingError as DjangoProgrammingError
from django.utils import timezone

from .models import (
    AutomationAction,
    AutomationActionLog,
    AutomationActionLogStatus,
    AutomationActionType,
    ApprovalDeliveryMode,
    AUTOMATION_DELIVERY_ENDPOINT_UNAVAILABLE_MESSAGE,
    AutomationCondition,
    AutomationConditionOperator,
    AutomationConditionValueType,
    AutomationRule,
    AutomationRunLog,
    AutomationRunLogStatus,
    DashboardMetricValue,
    get_teams_flow_endpoint_by_id,
)
from .source_registry import get_action_mapping_fields, get_source_definition, get_source_fields


_UNCASTABLE = object()
_PLACEHOLDER_PATTERN = re.compile(r"\{([^{}]+)\}")
_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TRUTHY_VALUES = {"1", "true", "yes", "on"}
_FALSY_VALUES = {"0", "false", "no", "off"}
_QUEUE_ERROR_MESSAGE_LIMIT = 1900
MAX_QUEUE_EVENT_RETRY_COUNT = 5
_SENSITIVE_KEY_PARTS = ("password", "passwd", "secret", "token", "api_key", "apikey", "webhook", "url")


class AutomationSafetyError(ValueError):
    """Errore bloccante generato dai guardrail runtime delle automazioni."""


class QueueEventStatus:
    """Costanti per il campo status della tabella automation_event_queue."""
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"

logger = logging.getLogger(__name__)


# App moduli principali â€” usate per il picker "aggiungi tabella"
_MODULE_APPS = {
    "anagrafica", "assets", "assenze", "anomalie", "tasks", "tickets",
    "notizie", "timbri", "rentri", "dpi", "procedure_refresh",
    "diario_preposto", "rilevazione_incidenti", "automazioni", "core",
}


_FALLBACK_ACTION_TABLE_WHITELIST: dict[str, dict[str, dict[str, set[str]]]] = {
    AutomationActionType.INSERT_RECORD: {
        "core_notifica": {
            "fields": {"legacy_user_id", "tipo", "messaggio", "url_azione", "letta"},
            "where_fields": set(),
        },
    },
    AutomationActionType.UPDATE_RECORD: {
        "core_notifica": {
            "fields": {"tipo", "messaggio", "url_azione", "letta"},
            "where_fields": {"id", "legacy_user_id", "tipo"},
        },
        "tasks_task": {
            "fields": {"status", "priority", "next_step_text", "next_step_due", "due_date", "assigned_to_id"},
            "where_fields": {"id", "project_id", "assigned_to_id"},
        },
    },
}


def _normalize_identifier_list(raw_values: Any) -> set[str]:
    if not isinstance(raw_values, (list, tuple, set)):
        return set()
    return {str(value).strip() for value in raw_values if str(value).strip()}


def _clone_table_whitelist(source: dict[str, dict[str, dict[str, set[str]]]]) -> dict[str, dict[str, dict[str, set[str]]]]:
    return {
        str(action_type): {
            str(table_name): {
                "fields": set(table_config.get("fields", set())),
                "where_fields": set(table_config.get("where_fields", set())),
            }
            for table_name, table_config in tables.items()
        }
        for action_type, tables in source.items()
    }


def discover_module_tables() -> dict[str, dict[str, list[str]]]:
    """
    Restituisce tutte le tabelle dei modelli Django appartenenti ai moduli principali.
    Formato: { "app_label.ModelName (db_table)": {"table": str, "fields": [...], "all_fields": [...]} }
    Usato dal picker UI per selezionare tabelle da aggiungere alla whitelist.
    """
    from django.apps import apps
    from django.db.models import AutoField, BigAutoField, SmallAutoField

    result: dict[str, dict] = {}
    for model in apps.get_models():
        if not model._meta.managed:
            continue
        if model._meta.app_label not in _MODULE_APPS:
            continue
        table = model._meta.db_table
        editable: list[str] = []
        all_cols: list[str] = []
        for f in model._meta.get_fields():
            if not hasattr(f, "column") or not f.column:
                continue
            all_cols.append(f.column)
            if not isinstance(f, (AutoField, BigAutoField, SmallAutoField)):
                editable.append(f.column)
        label = f"{model._meta.app_label}.{model.__name__} ({table})"
        result[table] = {
            "label": label,
            "table": table,
            "fields": sorted(editable),
            "all_fields": sorted(all_cols),
        }
    return dict(sorted(result.items()))


def get_action_table_whitelist() -> dict[str, dict[str, dict[str, set[str]]]]:
    """
    Whitelist tabelle per INSERT_RECORD e UPDATE_RECORD.
    Legge da AutomationTableConfig (DB). Fallback hardcoded se la tabella Ã¨ vuota.
    """
    from .models import AutomationTableConfig

    try:
        db_entries = list(AutomationTableConfig.objects.all())
    except Exception:
        db_entries = []

    insert_tables: dict[str, dict[str, set[str]]] = {}
    update_tables: dict[str, dict[str, set[str]]] = {}

    for entry in db_entries:
        row: dict[str, set[str]] = {
            "fields": _normalize_identifier_list(entry.allowed_fields),
            "where_fields": _normalize_identifier_list(entry.where_fields),
        }
        if entry.action_type == AutomationActionType.INSERT_RECORD:
            insert_tables[str(entry.table_name or "").strip()] = row
        elif entry.action_type == AutomationActionType.UPDATE_RECORD:
            update_tables[str(entry.table_name or "").strip()] = row

    # Fallback hardcoded se il DB e' ancora vuoto
    if not insert_tables and not update_tables:
        fallback = _clone_table_whitelist(_FALLBACK_ACTION_TABLE_WHITELIST)
        insert_tables = fallback[AutomationActionType.INSERT_RECORD]
        update_tables = fallback[AutomationActionType.UPDATE_RECORD]

    return {
        AutomationActionType.INSERT_RECORD: insert_tables,
        AutomationActionType.UPDATE_RECORD: update_tables,
    }


def _normalize_queue_error_message(message: Any) -> str:
    text = str(message or "").strip()
    if not text:
        return "Errore non specificato."
    if len(text) <= _QUEUE_ERROR_MESSAGE_LIMIT:
        return text
    return f"{text[:_QUEUE_ERROR_MESSAGE_LIMIT - 3]}..."


def _coerce_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _normalize_runtime_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return bool(value)

    normalized = str(value).strip().lower()
    if normalized in _TRUTHY_VALUES:
        return True
    if normalized in _FALSY_VALUES:
        return False
    return None


def _resolve_legacy_user_email(legacy_user_id: Any) -> str:
    resolved_id = _coerce_int(legacy_user_id)
    if resolved_id is None:
        return ""

    try:
        from core.legacy_models import UtenteLegacy

        legacy_user = UtenteLegacy.objects.filter(id=resolved_id).only("email").order_by("id").first()
    except Exception:
        logger.warning(
            "_resolve_legacy_user_email: impossibile risolvere email per legacy_user_id=%s",
            resolved_id,
            exc_info=True,
        )
        legacy_user = None

    return str(getattr(legacy_user, "email", "") or "").strip().lower()


def _resolve_caporeparto_email_from_local_id(local_id: Any) -> str:
    resolved_id = _coerce_int(local_id)
    if resolved_id is None:
        return ""

    try:
        from core.legacy_utils import legacy_table_columns

        cols = set(legacy_table_columns("capi_reparto"))
    except Exception:
        logger.warning(
            "_resolve_caporeparto_email_from_local_id: impossibile leggere metadata per capi_reparto id=%s",
            resolved_id,
            exc_info=True,
        )
        cols = set()

    select_cols: list[str] = []
    if "indirizzo_email" in cols:
        select_cols.append("indirizzo_email")
    if "utente_id" in cols:
        select_cols.append("utente_id")
    if not select_cols:
        return ""

    try:
        with connection.cursor() as cursor:
            if connection.vendor == "sqlite":
                cursor.execute(
                    f"SELECT {', '.join(select_cols)} FROM capi_reparto WHERE id = %s ORDER BY id DESC LIMIT 1",
                    [resolved_id],
                )
            else:
                cursor.execute(
                    f"SELECT TOP 1 {', '.join(select_cols)} FROM capi_reparto WHERE id = %s ORDER BY id DESC",
                    [resolved_id],
                )
            row = cursor.fetchone()
    except Exception:
        logger.warning(
            "_resolve_caporeparto_email_from_local_id: impossibile risolvere email per capi_reparto.id=%s",
            resolved_id,
            exc_info=True,
        )
        row = None

    if not row:
        return ""

    offset = 0
    if "indirizzo_email" in cols:
        email = str(row[offset] or "").strip().lower()
        if email:
            return email
        offset += 1

    if "utente_id" in cols:
        return _resolve_legacy_user_email(row[offset])
    return ""


def _resolve_capo_email_from_reparto_mapping(dipendente_id: Any) -> str:
    resolved_id = _coerce_int(dipendente_id)
    if resolved_id is None:
        return ""
    try:
        from core.models import RepartoCapoMapping, UserExtraInfo

        extra = UserExtraInfo.objects.filter(legacy_user_id=resolved_id).only("reparto").first()
        reparto = str(getattr(extra, "reparto", "") or "").strip()
        if not reparto:
            return ""
        mapping = RepartoCapoMapping.objects.filter(reparto__iexact=reparto, is_active=True).first()
        if not mapping:
            return ""
        caporeparto = str(mapping.caporeparto or "").strip()
        if "@" in caporeparto:
            return caporeparto.lower()
        from core.legacy_models import UtenteLegacy

        user = UtenteLegacy.objects.filter(nome__iexact=caporeparto).only("email").first()
        return str(getattr(user, "email", "") or "").strip().lower()
    except Exception:
        logger.warning("_resolve_capo_email_from_reparto_mapping: errore per dipendente_id=%s", resolved_id, exc_info=True)
        return ""


def _resolve_caporeparto_email_from_lookup(lookup_id: Any) -> str:
    resolved_id = _coerce_int(lookup_id)
    if resolved_id is None:
        return ""

    try:
        with connection.cursor() as cursor:
            if connection.vendor == "sqlite":
                cursor.execute(
                    """
SELECT indirizzo_email
FROM capi_reparto
WHERE sharepoint_item_id = %s
ORDER BY id DESC
LIMIT 1
""",
                    [resolved_id],
                )
            else:
                cursor.execute(
                    """
SELECT TOP 1 indirizzo_email
FROM capi_reparto
WHERE sharepoint_item_id = %s
ORDER BY id DESC
""",
                    [resolved_id],
                )
            row = cursor.fetchone()
    except Exception:
        logger.warning(
            "_resolve_caporeparto_email_from_lookup: impossibile risolvere email per sharepoint_item_id=%s",
            resolved_id,
            exc_info=True,
        )
        row = None

    if not row or row[0] is None:
        return ""
    return str(row[0] or "").strip().lower()


def _fetch_assenza_runtime_details(assenza_id: Any) -> dict[str, Any]:
    resolved_id = _coerce_int(assenza_id)
    if resolved_id is None:
        return {}

    try:
        from core.legacy_utils import legacy_table_columns

        cols = set(legacy_table_columns("assenze"))
    except Exception:
        logger.warning(
            "_fetch_assenza_runtime_details: impossibile leggere metadata per assenza_id=%s",
            resolved_id,
            exc_info=True,
        )
        cols = set()

    select_cols: list[str] = []
    for col in (
        "email_esterna",
        "salta_approvazione",
        "capo_reparto_id",
        "capo_reparto_lookup_id",
        "nome_lookup_id",
        "copia_nome",
    ):
        if col in cols:
            select_cols.append(col)
    if not select_cols:
        return {}

    try:
        with connection.cursor() as cursor:
            quoted_cols = ", ".join(select_cols)
            if connection.vendor == "sqlite":
                cursor.execute(
                    f"SELECT {quoted_cols} FROM assenze WHERE id = %s ORDER BY id DESC LIMIT 1",
                    [resolved_id],
                )
            else:
                cursor.execute(
                    f"SELECT TOP 1 {quoted_cols} FROM assenze WHERE id = %s ORDER BY id DESC",
                    [resolved_id],
                )
            row = cursor.fetchone()
    except Exception:
        logger.warning(
            "_fetch_assenza_runtime_details: impossibile recuperare dettagli per assenza_id=%s",
            resolved_id,
            exc_info=True,
        )
        row = None

    if not row:
        return {}

    result: dict[str, Any] = {}
    values_by_col = dict(zip(select_cols, row))

    dipendente_email = str(values_by_col.get("email_esterna") or "").strip().lower()
    if dipendente_email:
        result["dipendente_email"] = dipendente_email

    if "salta_approvazione" in values_by_col:
        result["salta_approvazione"] = _normalize_runtime_bool(values_by_col.get("salta_approvazione"))

    capo_reparto_id = _coerce_int(values_by_col.get("capo_reparto_id"))
    if capo_reparto_id is not None:
        result["capo_reparto_id"] = capo_reparto_id

    capo_reparto_lookup_id = _coerce_int(values_by_col.get("capo_reparto_lookup_id"))
    if capo_reparto_lookup_id is not None:
        result["capo_reparto_lookup_id"] = capo_reparto_lookup_id

    dipendente_id = _coerce_int(values_by_col.get("nome_lookup_id"))
    if dipendente_id is not None:
        result["dipendente_id"] = dipendente_id

    dipendente_nome = str(values_by_col.get("copia_nome") or "").strip()
    if dipendente_nome:
        result["dipendente_nome"] = dipendente_nome

    return result


def _enrich_assenze_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload

    enriched = dict(payload)
    runtime_details = _fetch_assenza_runtime_details(enriched.get("id"))

    if enriched.get("capo_reparto_id") in {None, ""} and runtime_details.get("capo_reparto_id") is not None:
        enriched["capo_reparto_id"] = runtime_details.get("capo_reparto_id")
    if enriched.get("capo_reparto_lookup_id") in {None, ""} and runtime_details.get("capo_reparto_lookup_id") is not None:
        enriched["capo_reparto_lookup_id"] = runtime_details.get("capo_reparto_lookup_id")
    if enriched.get("dipendente_id") in {None, ""} and runtime_details.get("dipendente_id") is not None:
        enriched["dipendente_id"] = runtime_details.get("dipendente_id")

    capo_email = str(enriched.get("capo_email") or "").strip().lower()
    if not capo_email:
        capo_email = _resolve_caporeparto_email_from_local_id(enriched.get("capo_reparto_id"))
    if not capo_email:
        capo_email = _resolve_legacy_user_email(enriched.get("capo_reparto_id"))
    if not capo_email:
        capo_email = _resolve_caporeparto_email_from_lookup(enriched.get("capo_reparto_lookup_id"))
    if not capo_email:
        capo_email = _resolve_capo_email_from_reparto_mapping(enriched.get("dipendente_id"))
    if capo_email:
        enriched["capo_email"] = capo_email

    dipendente_email = str(
        enriched.get("dipendente_email")
        or enriched.get("email_esterna")
        or runtime_details.get("dipendente_email")
        or ""
    ).strip().lower()
    if not dipendente_email:
        dipendente_email = _resolve_legacy_user_email(enriched.get("dipendente_id"))
    if dipendente_email:
        enriched["dipendente_email"] = dipendente_email

    dipendente_nome = str(enriched.get("dipendente_nome") or runtime_details.get("dipendente_nome") or "").strip()
    if dipendente_nome:
        enriched["dipendente_nome"] = dipendente_nome

    salta_approvazione = enriched.get("salta_approvazione")
    if salta_approvazione in {None, ""}:
        salta_approvazione = runtime_details.get("salta_approvazione")
    normalized_salta_approvazione = _normalize_runtime_bool(salta_approvazione)
    if normalized_salta_approvazione is not None:
        enriched["salta_approvazione"] = normalized_salta_approvazione
    return enriched


def _enrich_tickets_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    asset_id = payload.get("asset_id")
    if not asset_id:
        return payload
    enriched = dict(payload)
    try:
        from assets.models import Asset
        asset = Asset.objects.only("name", "asset_tag").get(pk=asset_id)
        enriched.setdefault("asset_nome", asset.name)
        enriched.setdefault("asset_tag", asset.asset_tag)
    except Exception:
        pass
    return enriched


def _resolve_anomalie_role_for_legacy_id(legacy_user_id: Any) -> str:
    """
    AU-GAP1: risolve il ruolo operativo anomalie (CAPOCOMMESSA/CAR) di chi ha modificato,
    partendo dal legacy_user_id presente nel payload (proiettato dal trigger SQL via la
    colonna applicativa modified_by_user_id). Il ruolo NON e' un dato del DB legacy: vive
    nelle assegnazioni applicative `AnomalieRoleAssignment` (CC/CAR), quindi va derivato qui.
    Ritorna il code del ruolo ("CC"/"CAR") oppure stringa vuota se non determinabile.
    """
    if legacy_user_id in (None, ""):
        return ""
    try:
        legacy_id = int(legacy_user_id)
    except (TypeError, ValueError):
        return ""
    try:
        from core.models import Profile
        from anomalie.models import AnomalieRoleAssignment, AnomalieRoleType

        profile = Profile.objects.filter(legacy_user_id=legacy_id).only("user_id").first()
        if not profile:
            return ""
        # Se l'utente ha entrambi i ruoli, CC ha priorita' (capocommessa > CAR).
        role_codes = set(
            AnomalieRoleAssignment.objects.filter(user_id=profile.user_id)
            .values_list("role_type", flat=True)
        )
        if AnomalieRoleType.CAPO_COMMESSA in role_codes:
            return str(AnomalieRoleType.CAPO_COMMESSA)
        if AnomalieRoleType.CAR in role_codes:
            return str(AnomalieRoleType.CAR)
    except Exception:
        return ""
    return ""


def _enrich_anomalie_payload(payload: Any) -> Any:
    """
    AU-GAP1: arricchisce il payload anomalie con `modified_by_role` derivandolo da
    `modified_by_id`/`modified_by_user_id`. Abilita le condizioni "notifica solo se a
    modificare e' CAPOCOMMESSA/CAR" (AU42 versione 'per ruolo').
    """
    if not isinstance(payload, dict):
        return payload
    enriched = dict(payload)
    # Il trigger SQL puo' proiettare la colonna come modified_by_user_id; normalizziamo
    # verso il nome di registry modified_by_id (alias gia' previsti nel source_registry).
    modified_by_id = (
        enriched.get("modified_by_id")
        if enriched.get("modified_by_id") not in (None, "")
        else enriched.get("modified_by_user_id")
    )
    if modified_by_id not in (None, "") and enriched.get("modified_by_id") in (None, ""):
        enriched["modified_by_id"] = modified_by_id

    if enriched.get("modified_by_role") in (None, ""):
        role = _resolve_anomalie_role_for_legacy_id(modified_by_id)
        if role:
            enriched["modified_by_role"] = role
    return enriched


# Mappa sorgente -> template di path (relativo a SITE_URL) per il link al record nel
# portale. SOLO sorgenti con una URL di dettaglio per-record affidabile basata sulla PK
# (`id`) presente nel payload. Le altre sorgenti (es. rilevazione_incidenti usa sp_id non
# la PK; anomalie non ha una detail per-record; assenze/anagrafica/rentri/notizie/procedure
# non hanno una vista di dettaglio stabile) restano fuori: per loro {object_url} sara' vuoto
# e nei template il link semplicemente non comparira'. Meglio nessun link che un link rotto.
_OBJECT_URL_PATH_BY_SOURCE = {
    "tickets": "/tickets/{id}/",
    "dpi": "/dpi/gestione/{id}/",
    "assets": "/assets/view/{id}/",
}


def _build_object_url(source_code: str | None, payload: Any) -> str:
    """Costruisce l'URL assoluto al record sorgente, o stringa vuota se non disponibile."""
    if not isinstance(payload, dict):
        return ""
    normalized_source = str(source_code or "").strip().lower()
    path_template = _OBJECT_URL_PATH_BY_SOURCE.get(normalized_source)
    if not path_template:
        return ""
    record_id = payload.get("id")
    if record_id in (None, ""):
        return ""
    site_url = str(getattr(settings, "SITE_URL", "") or "").rstrip("/")
    if not site_url:
        return ""
    return f"{site_url}{path_template.format(id=record_id)}"


def _enrich_payload_for_source(source_code: str | None, payload: Any) -> Any:
    normalized_source = str(source_code or "").strip().lower()
    if normalized_source == "assenze":
        enriched = _enrich_assenze_payload(payload)
    elif normalized_source == "tickets":
        enriched = _enrich_tickets_payload(payload)
    elif normalized_source == "anomalie":
        enriched = _enrich_anomalie_payload(payload)
    else:
        enriched = payload

    # {object_url}: link al record nel portale, disponibile a tutti i template della regola.
    # Non sovrascrive un valore gia' presente nel payload.
    if isinstance(enriched, dict) and enriched.get("object_url") in (None, ""):
        object_url = _build_object_url(normalized_source, enriched)
        if object_url:
            if enriched is payload:
                enriched = dict(payload)
            enriched["object_url"] = object_url
    return enriched


def enrich_payload_for_source(source_code: str | None, payload: Any) -> Any:
    return _enrich_payload_for_source(source_code, payload)


def _cursor_fetch_dicts(cursor) -> list[dict[str, Any]]:
    columns = [column[0] for column in cursor.description or []]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


_QUEUE_DATETIME_FIELDS = {"created_at", "picked_at", "processed_at", "execute_after"}


def _normalize_queue_event_datetimes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark naive datetime fields from automation_event_queue as UTC-aware.

    SQL Server stores these via SYSUTCDATETIME(); pyodbc returns naive datetimes.
    Without tzinfo Django's date filter skips localtime conversion and shows UTC.
    """
    for row in rows:
        for field in _QUEUE_DATETIME_FIELDS:
            val = row.get(field)
            if isinstance(val, datetime) and val.tzinfo is None:
                row[field] = val.replace(tzinfo=dt_timezone.utc)
    return rows


def _queue_table_has_column(column_name: str) -> bool:
    normalized = str(column_name or "").strip()
    if not normalized:
        return False

    vendor = str(getattr(connection, "vendor", "") or "").lower()

    try:
        with connection.cursor() as cursor:
            if vendor == "sqlite":
                cursor.execute("PRAGMA table_info(automation_event_queue)")
                rows = cursor.fetchall() or []
                return any(str(row[1]) == normalized for row in rows if len(row) > 1)

            cursor.execute(
                """
SELECT 1
FROM sys.columns
WHERE object_id = OBJECT_ID(N'dbo.automation_event_queue', N'U')
  AND name = %s
""",
                [normalized],
            )
            return bool(cursor.fetchone())
    except DjangoProgrammingError:
        return False


def _build_queue_source_filter(source_code: str | None) -> tuple[str, list[Any]]:
    normalized = str(source_code or "").strip()
    if not normalized:
        return "", []
    return " AND source_code = %s", [normalized]


def _build_queue_filter_clauses(
    *,
    status: str | None = None,
    source_code: str | None = None,
    operation_type: str | None = None,
    queue_id: int | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    normalized_status = str(status or "").strip()
    if normalized_status:
        clauses.append("status = %s")
        params.append(normalized_status)

    normalized_source_code = str(source_code or "").strip()
    if normalized_source_code:
        clauses.append("source_code = %s")
        params.append(normalized_source_code)

    normalized_operation_type = str(operation_type or "").strip().lower()
    if normalized_operation_type:
        clauses.append("LOWER(operation_type) = %s")
        params.append(normalized_operation_type)

    if queue_id is not None:
        clauses.append("id = %s")
        params.append(int(queue_id))

    if not clauses:
        return "", params
    return f"WHERE {' AND '.join(clauses)}", params


def _deserialize_queue_json(raw_value: Any, *, field_name: str, allow_null: bool = False) -> dict[str, Any] | None:
    if raw_value in {None, ""}:
        if allow_null:
            return None
        raise ValueError(f"{field_name} mancante o vuoto.")

    if isinstance(raw_value, dict):
        return raw_value

    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field_name} non contiene JSON valido.") from exc

    if parsed is None and allow_null:
        return None
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} deve contenere un oggetto JSON.")
    return parsed


def _did_payload_field_change(payload: Any, old_payload: Any, field_name: str | None) -> bool:
    if not field_name or not isinstance(payload, dict) or not isinstance(old_payload, dict):
        return False
    return safe_get_payload_value(payload, field_name) != safe_get_payload_value(old_payload, field_name)


def _did_payload_change(payload: Any, old_payload: Any) -> bool:
    if not isinstance(payload, dict) or not isinstance(old_payload, dict):
        return False
    return payload != old_payload


def fetch_pending_queue_events(limit: int = 50, source_code: str | None = None) -> list[dict[str, Any]]:
    batch_limit = max(int(limit or 0), 1)
    source_filter_sql, source_filter_params = _build_queue_source_filter(source_code)
    execute_after_filter_sql = ""
    if _queue_table_has_column("execute_after"):
        execute_after_filter_sql = "\n    AND (execute_after IS NULL OR execute_after <= GETUTCDATE())"
    sql = f"""
WITH picked AS (
    SELECT TOP ({batch_limit}) id
    FROM dbo.automation_event_queue WITH (READPAST, UPDLOCK, ROWLOCK)
    WHERE status = %s
    {execute_after_filter_sql}
    {source_filter_sql}
    ORDER BY id ASC
)
UPDATE queue_rows
SET
    status = %s,
    picked_at = SYSUTCDATETIME(),
    error_message = NULL
OUTPUT
    inserted.id,
    inserted.source_code,
    inserted.source_table,
    inserted.source_pk,
    inserted.operation_type,
    inserted.event_code,
    inserted.watched_field,
    inserted.payload_json,
    inserted.old_payload_json,
    inserted.status,
    inserted.retry_count,
    inserted.error_message,
    inserted.created_at,
    inserted.picked_at,
    inserted.processed_at
FROM dbo.automation_event_queue AS queue_rows
INNER JOIN picked
    ON picked.id = queue_rows.id;
"""
    params = [QueueEventStatus.PENDING, *source_filter_params, QueueEventStatus.PROCESSING]
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return _cursor_fetch_dicts(cursor)


def fetch_pending_queue_event_snapshots(limit: int = 50, source_code: str | None = None) -> list[dict[str, Any]]:
    batch_limit = max(int(limit or 0), 1)
    source_filter_sql, source_filter_params = _build_queue_source_filter(source_code)
    execute_after_filter_sql = ""
    if _queue_table_has_column("execute_after"):
        execute_after_filter_sql = "\nAND (execute_after IS NULL OR execute_after <= GETUTCDATE())"
    sql = f"""
SELECT TOP ({batch_limit})
    id,
    source_code,
    source_table,
    source_pk,
    operation_type,
    event_code,
    watched_field,
    payload_json,
    old_payload_json,
    status,
    retry_count,
    error_message,
    created_at,
    picked_at,
    processed_at
FROM dbo.automation_event_queue
WHERE status = %s
{execute_after_filter_sql}
{source_filter_sql}
ORDER BY id ASC;
"""
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, [QueueEventStatus.PENDING, *source_filter_params])
            return _normalize_queue_event_datetimes(_cursor_fetch_dicts(cursor))
    except DjangoProgrammingError:
        return []


def list_queue_events(
    *,
    status: str | None = None,
    source_code: str | None = None,
    operation_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    row_limit = max(int(limit or 0), 1)
    where_sql, params = _build_queue_filter_clauses(
        status=status,
        source_code=source_code,
        operation_type=operation_type,
    )
    sql = f"""
SELECT TOP ({row_limit})
    id,
    source_code,
    source_table,
    source_pk,
    operation_type,
    event_code,
    watched_field,
    status,
    retry_count,
    error_message,
    created_at,
    picked_at,
    processed_at
FROM dbo.automation_event_queue
{where_sql}
ORDER BY id DESC;
"""
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return _normalize_queue_event_datetimes(_cursor_fetch_dicts(cursor))
    except DjangoProgrammingError:
        return []


def get_queue_event_detail(queue_id: int) -> dict[str, Any] | None:
    where_sql, params = _build_queue_filter_clauses(queue_id=queue_id)
    sql = f"""
SELECT
    id,
    source_code,
    source_table,
    source_pk,
    operation_type,
    event_code,
    watched_field,
    payload_json,
    old_payload_json,
    status,
    retry_count,
    error_message,
    created_at,
    picked_at,
    processed_at
FROM dbo.automation_event_queue
{where_sql};
"""
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = _normalize_queue_event_datetimes(_cursor_fetch_dicts(cursor))
    return rows[0] if rows else None


def count_queue_by_status(
    *,
    source_code: str | None = None,
    operation_type: str | None = None,
) -> dict[str, int]:
    where_sql, params = _build_queue_filter_clauses(source_code=source_code, operation_type=operation_type)
    sql = f"""
SELECT status, COUNT(*) AS total
FROM dbo.automation_event_queue
{where_sql}
GROUP BY status;
"""
    counts = {QueueEventStatus.PENDING: 0, QueueEventStatus.PROCESSING: 0, QueueEventStatus.DONE: 0, QueueEventStatus.ERROR: 0}
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            for row in _cursor_fetch_dicts(cursor):
                counts[str(row["status"])] = int(row["total"])
    except DjangoProgrammingError:
        pass
    return counts


def reset_queue_event_to_pending(queue_id: int) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
UPDATE dbo.automation_event_queue
SET
    status = %s,
    error_message = NULL,
    picked_at = NULL,
    processed_at = NULL
WHERE id = %s
  AND status = %s
  AND retry_count < %s
""",
            [QueueEventStatus.PENDING, int(queue_id), QueueEventStatus.ERROR, MAX_QUEUE_EVENT_RETRY_COUNT],
        )
        return bool(cursor.rowcount)


def stop_queue_event(queue_id: int, *, reason: str | None = None) -> bool:
    stop_reason = reason or "Evento stoppato manualmente dall'operatore."
    with connection.cursor() as cursor:
        cursor.execute(
            """
UPDATE dbo.automation_event_queue
SET
    status = %s,
    error_message = %s,
    processed_at = SYSUTCDATETIME()
WHERE id = %s
  AND status = %s
""",
            [QueueEventStatus.ERROR, _normalize_queue_error_message(stop_reason), int(queue_id), QueueEventStatus.PENDING],
        )
        return bool(cursor.rowcount)


def delete_queue_event(queue_id: int) -> bool:
    if AutomationRunLog.objects.filter(queue_event_id=int(queue_id)).exists():
        return False

    with connection.cursor() as cursor:
        cursor.execute(
            """
DELETE FROM dbo.automation_event_queue
WHERE id = %s
  AND status IN (%s, %s)
""",
            [int(queue_id), QueueEventStatus.PENDING, QueueEventStatus.ERROR],
        )
        return bool(cursor.rowcount)


def claim_queue_event_by_id(
    queue_id: int,
    *,
    allowed_statuses: tuple[str, ...] = (QueueEventStatus.PENDING, QueueEventStatus.ERROR),
    max_retry_count: int | None = None,
) -> dict[str, Any] | None:
    normalized_statuses = tuple(str(status).strip() for status in allowed_statuses if str(status).strip())
    if not normalized_statuses:
        return None

    placeholders = ", ".join(["%s"] * len(normalized_statuses))
    retry_filter_sql = ""
    retry_filter_params: list[Any] = []
    if max_retry_count is not None:
        retry_filter_sql = "  AND retry_count < %s"
        retry_filter_params = [int(max_retry_count)]
    sql = f"""
UPDATE dbo.automation_event_queue
SET
    status = %s,
    picked_at = SYSUTCDATETIME(),
    error_message = NULL
OUTPUT
    inserted.id,
    inserted.source_code,
    inserted.source_table,
    inserted.source_pk,
    inserted.operation_type,
    inserted.event_code,
    inserted.watched_field,
    inserted.payload_json,
    inserted.old_payload_json,
    inserted.status,
    inserted.retry_count,
    inserted.error_message,
    inserted.created_at,
    inserted.picked_at,
    inserted.processed_at
WHERE id = %s
  AND status IN ({placeholders})
{retry_filter_sql}
"""
    params = [QueueEventStatus.PROCESSING, int(queue_id), *normalized_statuses, *retry_filter_params]
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = _cursor_fetch_dicts(cursor)
    return rows[0] if rows else None


def mark_queue_done(queue_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
UPDATE dbo.automation_event_queue
SET
    status = %s,
    processed_at = SYSUTCDATETIME(),
    error_message = NULL
WHERE id = %s
""",
            [QueueEventStatus.DONE, int(queue_id)],
        )


def mark_queue_error(queue_id: int, error_message: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
UPDATE dbo.automation_event_queue
SET
    status = %s,
    retry_count = retry_count + 1,
    error_message = %s,
    processed_at = SYSUTCDATETIME()
WHERE id = %s
""",
            [QueueEventStatus.ERROR, _normalize_queue_error_message(error_message), int(queue_id)],
        )


def safe_get_payload_value(payload: Any, field_name: str | None) -> Any:
    if not isinstance(payload, dict) or not field_name:
        return None

    current = payload
    for chunk in str(field_name).split("."):
        if not isinstance(current, dict):
            return None
        if chunk not in current:
            return None
        current = current.get(chunk)
    return current


def _fetch_anomalie_by_op(op_title: Any) -> list[dict]:
    """Carica dal DB le anomalie non chiuse dell'OP identificata da ex_op_nominativo.

    Ritorna lista di dict con i campi utili per la mail (id, descrizione, seriale,
    avanzamento, note_capocommessa). Lista vuota in caso di errore o nessun risultato.
    """
    op_str = str(op_title or "").strip()
    if not op_str:
        return []
    try:
        if connection.vendor == "sqlite":
            sql = (
                "SELECT id, descrizione, seriale, avanzamento, note_capocommessa "
                "FROM anomalie WHERE LOWER(ex_op_nominativo) = LOWER(%s) "
                "AND (chiudere IS NULL OR chiudere = 0) ORDER BY id"
            )
        else:
            sql = (
                "SELECT id, descrizione, seriale, avanzamento, note_capocommessa "
                "FROM anomalie WHERE LOWER(CAST(ex_op_nominativo AS NVARCHAR(MAX))) = LOWER(%s) "
                "AND (chiudere IS NULL OR chiudere = 0) ORDER BY id"
            )
        with connection.cursor() as cur:
            cur.execute(sql, [op_str])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return rows
    except Exception:
        logger.warning("_fetch_anomalie_by_op: errore lettura anomalie per op=%s", op_str, exc_info=True)
        return []


def _resolve_op_recipients(op_title: Any) -> list[dict[str, str]]:
    """Risolve CC e CAR di un'OP tramite il titolo (ex_op_nominativo).

    Esegue due query sul DB legacy:
    1. ordini_produzione → capocomessa (cognome), incaricato (nome cognome), cercando per LOWER(title)
    2. anagrafica_dipendenti → email via match su cognome / nome+cognome

    Ritorna una lista di dict {email, display, role} (CC prima, CAR dopo).
    Lista vuota se l'OP non esiste o non ha capocomessa/incaricato.
    """
    op_title_str = str(op_title or "").strip()
    if not op_title_str:
        return []

    try:
        if connection.vendor == "sqlite":
            op_sql = "SELECT capocomessa, incaricato FROM ordini_produzione WHERE LOWER(title) = LOWER(%s) LIMIT 1"
        else:
            op_sql = "SELECT TOP 1 capocomessa, incaricato FROM ordini_produzione WHERE LOWER(title) = LOWER(%s)"
        with connection.cursor() as cur:
            cur.execute(op_sql, [op_title_str])
            row = cur.fetchone()
    except Exception:
        logger.warning("_resolve_op_recipients: impossibile leggere ordini_produzione title=%s", op_title_str, exc_info=True)
        return []

    if not row:
        logger.warning("_resolve_op_recipients: title=%r non trovato in ordini_produzione", op_title_str)
        return []

    capocomessa_raw = str(row[0] or "").strip()
    incaricato_raw = str(row[1] or "").strip()
    recipients = []

    def _email_by_cognome(cognome: str) -> tuple[str, str]:
        if not cognome:
            return "", ""
        try:
            if connection.vendor == "sqlite":
                sql = "SELECT email, nome, cognome FROM anagrafica_dipendenti WHERE LOWER(cognome) = LOWER(%s) AND attivo = 1 LIMIT 1"
            else:
                sql = "SELECT TOP 1 email, nome, cognome FROM anagrafica_dipendenti WHERE LOWER(cognome) = LOWER(%s) AND attivo = 1"
            with connection.cursor() as cur:
                cur.execute(sql, [cognome])
                r = cur.fetchone()
            if r:
                email = str(r[0] or "").strip()
                display = f"{str(r[1] or '').strip()} {str(r[2] or '').strip()}".strip().title()
                return email, display
        except Exception:
            logger.warning("_resolve_op_recipients: impossibile risolvere cognome=%s", cognome, exc_info=True)
        return "", cognome

    def _email_by_fullname(fullname: str) -> tuple[str, str]:
        if not fullname:
            return "", ""
        parts = fullname.strip().split()
        if len(parts) < 2:
            return _email_by_cognome(fullname)
        try:
            if connection.vendor == "sqlite":
                sql = (
                    "SELECT email, nome, cognome FROM anagrafica_dipendenti "
                    "WHERE (LOWER(nome || ' ' || cognome) = LOWER(%s) OR LOWER(cognome || ' ' || nome) = LOWER(%s)) "
                    "AND attivo = 1 LIMIT 1"
                )
            else:
                sql = (
                    "SELECT TOP 1 email, nome, cognome FROM anagrafica_dipendenti "
                    "WHERE (LOWER(CONCAT(nome, ' ', cognome)) = LOWER(%s) OR LOWER(CONCAT(cognome, ' ', nome)) = LOWER(%s)) "
                    "AND attivo = 1"
                )
            with connection.cursor() as cur:
                cur.execute(sql, [fullname, fullname])
                r = cur.fetchone()
            if r:
                email = str(r[0] or "").strip()
                display = f"{str(r[1] or '').strip()} {str(r[2] or '').strip()}".strip().title()
                return email, display
        except Exception:
            logger.warning("_resolve_op_recipients: impossibile risolvere incaricato=%s", fullname, exc_info=True)
        return "", fullname

    if capocomessa_raw:
        # Il campo `capocomessa` storicamente conteneva solo il COGNOME, ma in pratica
        # può contenere "Nome Cognome" completo (es. "LORENZO CAPONE"). In quel caso il
        # match per solo-cognome fallisce. Proviamo quindi prima il fullname (se ci sono
        # ≥2 token) e poi il fallback su cognome, come già fa l'incaricato.
        if len(capocomessa_raw.split()) >= 2:
            email, display = _email_by_fullname(capocomessa_raw)
            if not email:
                email, display = _email_by_cognome(capocomessa_raw)
        else:
            email, display = _email_by_cognome(capocomessa_raw)
        if email:
            recipients.append({"email": email, "display": display or capocomessa_raw, "role": "CC"})
        else:
            logger.info("_resolve_op_recipients: nessuna email per capocomessa=%s op=%s", capocomessa_raw, op_title_str)

    if incaricato_raw:
        email, display = _email_by_fullname(incaricato_raw)
        if email:
            # evita duplicato se CC e CAR sono la stessa persona
            if not any(r["email"].lower() == email.lower() for r in recipients):
                recipients.append({"email": email, "display": display or incaricato_raw, "role": "CAR"})
        else:
            logger.info("_resolve_op_recipients: nessuna email per incaricato=%s op=%s", incaricato_raw, op_title_str)

    return recipients


def render_template_string(template_str: str | None, context: Any) -> str:
    if template_str is None:
        return ""

    context_dict = context if isinstance(context, dict) else {}
    template = str(template_str)

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        value = safe_get_payload_value(context_dict, key)
        if value is None:
            return match.group(0)
        return str(value)

    return _PLACEHOLDER_PATTERN.sub(_replace, template)


def _normalize_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return bool(value)

    normalized = str(value).strip().lower()
    if normalized in _TRUTHY_VALUES:
        return True
    if normalized in _FALSY_VALUES:
        return False
    return None


def _parse_datetime(value: Any) -> datetime | object | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if not isinstance(value, str):
        return _UNCASTABLE

    normalized = value.strip()
    if not normalized:
        return None

    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return _UNCASTABLE


def _parse_date(value: Any) -> date | object | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return _UNCASTABLE

    normalized = value.strip()
    if not normalized:
        return None

    try:
        return date.fromisoformat(normalized)
    except ValueError:
        parsed = _parse_datetime(normalized)
        if parsed in {_UNCASTABLE, None}:
            return parsed
        return parsed.date()


def _coerce_value(value: Any, value_type: str | None) -> Any:
    if value is None:
        return None

    normalized_type = str(value_type or AutomationConditionValueType.STRING).strip().lower()

    if normalized_type == AutomationConditionValueType.STRING:
        return str(value)

    if normalized_type == AutomationConditionValueType.INT:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return _UNCASTABLE

    if normalized_type == AutomationConditionValueType.FLOAT:
        try:
            return Decimal(str(value).strip())
        except (InvalidOperation, TypeError, ValueError):
            return _UNCASTABLE

    if normalized_type == AutomationConditionValueType.BOOL:
        normalized_bool = _normalize_bool(value)
        return normalized_bool if normalized_bool is not None else _UNCASTABLE

    if normalized_type == AutomationConditionValueType.DATE:
        return _parse_date(value)

    if normalized_type == AutomationConditionValueType.DATETIME:
        return _parse_datetime(value)

    return str(value)


def _split_csv_values(raw_value: str, value_type: str | None) -> list[Any] | None:
    values: list[Any] = []
    for chunk in str(raw_value or "").split(","):
        candidate = _coerce_value(chunk.strip(), value_type)
        if candidate is _UNCASTABLE:
            return None
        values.append(candidate)
    return values


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _build_trigger_event_label(rule: AutomationRule) -> str:
    if rule.watched_field:
        return f"{rule.source_code}.{rule.operation_type}.{rule.watched_field}"
    return f"{rule.source_code}.{rule.operation_type}.{rule.trigger_scope}"


def evaluate_condition(condition: AutomationCondition, payload: Any, old_payload: Any = None) -> bool:
    try:
        operator = condition.operator
        value_type = condition.value_type
        compare_with_old = bool(condition.compare_with_old)

        current_raw = safe_get_payload_value(payload, condition.field_name)
        old_raw = safe_get_payload_value(old_payload, condition.field_name)
        selected_raw = old_raw if compare_with_old else current_raw

        if operator == AutomationConditionOperator.IS_EMPTY:
            return _is_empty_value(selected_raw)

        if operator == AutomationConditionOperator.IS_NOT_EMPTY:
            return not _is_empty_value(selected_raw)

        if operator in {
            AutomationConditionOperator.CHANGED,
            AutomationConditionOperator.CHANGED_TO,
            AutomationConditionOperator.CHANGED_FROM_TO,
        } and not isinstance(old_payload, dict):
            return False

        current_value = _coerce_value(current_raw, value_type)
        old_value = _coerce_value(old_raw, value_type)
        selected_value = old_value if compare_with_old else current_value
        expected_value = _coerce_value(condition.expected_value, value_type)

        if operator == AutomationConditionOperator.EQUALS:
            return selected_value not in {_UNCASTABLE} and expected_value not in {_UNCASTABLE} and selected_value == expected_value

        if operator == AutomationConditionOperator.NOT_EQUALS:
            return selected_value not in {_UNCASTABLE} and expected_value not in {_UNCASTABLE} and selected_value != expected_value

        if operator == AutomationConditionOperator.CONTAINS:
            if selected_value in {_UNCASTABLE, None} or expected_value in {_UNCASTABLE, None}:
                return False
            return str(expected_value) in str(selected_value)

        if operator == AutomationConditionOperator.STARTSWITH:
            if selected_value in {_UNCASTABLE, None} or expected_value in {_UNCASTABLE, None}:
                return False
            return str(selected_value).startswith(str(expected_value))

        if operator == AutomationConditionOperator.ENDSWITH:
            if selected_value in {_UNCASTABLE, None} or expected_value in {_UNCASTABLE, None}:
                return False
            return str(selected_value).endswith(str(expected_value))

        if operator == AutomationConditionOperator.GT:
            return selected_value not in {_UNCASTABLE, None} and expected_value not in {_UNCASTABLE, None} and selected_value > expected_value

        if operator == AutomationConditionOperator.GTE:
            return selected_value not in {_UNCASTABLE, None} and expected_value not in {_UNCASTABLE, None} and selected_value >= expected_value

        if operator == AutomationConditionOperator.LT:
            return selected_value not in {_UNCASTABLE, None} and expected_value not in {_UNCASTABLE, None} and selected_value < expected_value

        if operator == AutomationConditionOperator.LTE:
            return selected_value not in {_UNCASTABLE, None} and expected_value not in {_UNCASTABLE, None} and selected_value <= expected_value

        if operator == AutomationConditionOperator.IS_TRUE:
            return selected_value is True

        if operator == AutomationConditionOperator.IS_FALSE:
            return selected_value is False

        if operator == AutomationConditionOperator.IN_CSV:
            if selected_value in {_UNCASTABLE, None}:
                return False
            expected_values = _split_csv_values(condition.expected_value, value_type)
            return expected_values is not None and selected_value in expected_values

        if operator == AutomationConditionOperator.NOT_IN_CSV:
            if selected_value in {_UNCASTABLE, None}:
                return False
            expected_values = _split_csv_values(condition.expected_value, value_type)
            return expected_values is not None and selected_value not in expected_values

        if operator == AutomationConditionOperator.CHANGED:
            return current_value not in {_UNCASTABLE} and old_value not in {_UNCASTABLE} and current_value != old_value

        if operator == AutomationConditionOperator.CHANGED_TO:
            return (
                current_value not in {_UNCASTABLE}
                and old_value not in {_UNCASTABLE}
                and expected_value not in {_UNCASTABLE}
                and old_value != current_value
                and current_value == expected_value
            )

        if operator == AutomationConditionOperator.CHANGED_FROM_TO:
            if "|" not in str(condition.expected_value or ""):
                return False
            raw_old_expected, raw_new_expected = str(condition.expected_value).split("|", 1)
            old_expected = _coerce_value(raw_old_expected.strip(), value_type)
            new_expected = _coerce_value(raw_new_expected.strip(), value_type)
            return (
                current_value not in {_UNCASTABLE}
                and old_value not in {_UNCASTABLE}
                and old_expected not in {_UNCASTABLE}
                and new_expected not in {_UNCASTABLE}
                and old_value == old_expected
                and current_value == new_expected
                and old_value != current_value
            )

        if operator in {
            AutomationConditionOperator.DAYS_FROM_NOW_LTE,
            AutomationConditionOperator.DAYS_FROM_NOW_GTE,
        }:
            field_date = _parse_date(current_raw)
            if field_date in {_UNCASTABLE, None}:
                return False
            try:
                threshold = int(str(condition.expected_value).strip())
            except (TypeError, ValueError):
                return False
            delta_days = (field_date - date.today()).days
            if operator == AutomationConditionOperator.DAYS_FROM_NOW_LTE:
                return delta_days <= threshold
            return delta_days >= threshold

        if operator in {
            AutomationConditionOperator.DAYS_SPAN_GT,
            AutomationConditionOperator.DAYS_SPAN_GTE,
        }:
            # expected_value nel formato "altro_campo:N"
            raw_expected = str(condition.expected_value or "")
            if ":" not in raw_expected:
                return False
            other_field, raw_threshold = raw_expected.rsplit(":", 1)
            try:
                threshold = int(raw_threshold.strip())
            except (TypeError, ValueError):
                return False
            end_date = _parse_date(current_raw)
            start_date = _parse_date(safe_get_payload_value(payload, other_field.strip()))
            if end_date in {_UNCASTABLE, None} or start_date in {_UNCASTABLE, None}:
                return False
            span_days = (end_date - start_date).days
            if operator == AutomationConditionOperator.DAYS_SPAN_GT:
                return span_days > threshold
            return span_days >= threshold

        if operator == AutomationConditionOperator.COOLDOWN_GROUP:
            # LETTURA PURA: nessuna scrittura, sicura in dry-run/test.
            # field_name = campo che fornisce il VALORE del gruppo (es. ex_op_nominativo).
            # expected_value = "namespace:minuti" (es. "mail_anomalie_op:5"); il namespace è una
            # chiave logica condivisibile tra più regole. Se manca il namespace si usa field_name.
            # Ritorna True (eseguibile) se NON c'è un invio entro la finestra di cooldown.
            spec = _parse_cooldown_spec(condition)
            if spec is None:
                return True  # fail-open: expected_value malformato
            namespace, cooldown_minutes = spec
            group_value = str(safe_get_payload_value(payload, condition.field_name) or "").strip()
            if not group_value:
                return True  # campo gruppo assente: niente debounce
            try:
                from automazioni.models import AutomationCooldownGroup

                moment = timezone.now() - timedelta(minutes=cooldown_minutes)
                in_cooldown = AutomationCooldownGroup.objects.filter(
                    group_key=namespace,
                    group_value=group_value,
                    last_fired_at__gt=moment,
                ).exists()
            except Exception:
                logger.warning(
                    "[automazioni] cooldown_group: lettura fallita per namespace=%s â€” fail-open",
                    namespace,
                    exc_info=True,
                )
                return True  # fail-open
            return not in_cooldown

        return False
    except Exception:
        logger.warning(
            "evaluate_condition: eccezione durante la valutazione di field=%s operator=%s â€” condizione considerata False",
            getattr(condition, "field_name", "?"),
            getattr(condition, "operator", "?"),
            exc_info=True,
        )
        return False


def _parse_cooldown_spec(condition: Any) -> tuple[str, int] | None:
    """Estrae (namespace, minuti) dall'expected_value di una condizione cooldown_group.

    Formato atteso "namespace:minuti" (es. "mail_anomalie_op:5"); se manca il namespace si usa
    il field_name della condizione. Ritorna None se i minuti non sono interpretabili (fail-open).
    """
    try:
        raw = str(condition.expected_value or "").strip()
        namespace, sep, raw_minutes = raw.rpartition(":")
        namespace = namespace.strip() or str(getattr(condition, "field_name", "") or "").strip()
        cooldown_minutes = max(1, int(str(raw_minutes if sep else raw).strip()))
    except (TypeError, ValueError):
        logger.warning(
            "[automazioni] cooldown_group: expected_value malformato: %r â€” fail-open",
            getattr(condition, "expected_value", None),
        )
        return None
    if not namespace:
        return None
    return namespace, cooldown_minutes


def _commit_cooldown_groups(rule: AutomationRule, payload: Any) -> None:
    """Aggiorna last_fired_at per le condizioni cooldown_group della regola, dopo un'esecuzione
    riuscita. È la "scrittura" del debounce: tenuta fuori da evaluate_condition (predicato puro)
    e fatta solo a valle del successo, così un invio fallito non consuma la finestra di cooldown.
    """
    try:
        cooldown_conditions = [
            c
            for c in rule.conditions.filter(is_enabled=True)
            if c.operator == AutomationConditionOperator.COOLDOWN_GROUP
        ]
        if not cooldown_conditions:
            return
        from automazioni.models import AutomationCooldownGroup

        now = timezone.now()
        for condition in cooldown_conditions:
            spec = _parse_cooldown_spec(condition)
            if spec is None:
                continue
            namespace, _minutes = spec
            group_value = str(safe_get_payload_value(payload, condition.field_name) or "").strip()
            if not group_value:
                continue
            AutomationCooldownGroup.objects.update_or_create(
                group_key=namespace,
                group_value=group_value,
                defaults={"last_fired_at": now},
            )
    except Exception:
        logger.warning(
            "[automazioni] cooldown_group: commit last_fired_at fallito per rule=%s",
            getattr(rule, "code", "?"),
            exc_info=True,
        )


def _create_action_log(
    *,
    run_log: AutomationRunLog | None,
    action: Any,
    status: str,
    result_message: str,
    error_trace: str = "",
) -> AutomationActionLog | None:
    if run_log is None:
        return None

    return AutomationActionLog.objects.create(
        run_log=run_log,
        action=action if isinstance(action, AutomationAction) else None,
        status=status,
        result_message=result_message,
        error_trace=error_trace or None,
    )


def _action_identity(action: Any, run_log: AutomationRunLog | None = None) -> dict[str, Any]:
    rule = getattr(action, "rule", None) or getattr(run_log, "rule", None)
    return {
        "rule_id": getattr(rule, "pk", None) or getattr(run_log, "rule_id", None),
        "rule_code": getattr(rule, "code", "") or "",
        "action_id": getattr(action, "pk", None),
        "action_type": getattr(action, "action_type", "") or "",
    }


def _format_action_identity(action: Any, run_log: AutomationRunLog | None = None) -> str:
    identity = _action_identity(action, run_log)
    parts = []
    if identity["rule_id"] is not None:
        parts.append(f"rule_id={identity['rule_id']}")
    if identity["rule_code"]:
        parts.append(f"rule={identity['rule_code']}")
    if identity["action_id"] is not None:
        parts.append(f"action_id={identity['action_id']}")
    if identity["action_type"]:
        parts.append(f"type={identity['action_type']}")
    return " ".join(parts) or "action=sconosciuta"


def _redact_preview_value(field_name: str, value: Any) -> str:
    normalized_field = str(field_name or "").lower()
    if any(part in normalized_field for part in _SENSITIVE_KEY_PARTS):
        return "<redacted>"
    if value is None:
        return "NULL"
    text = str(value)
    if len(text) > 80:
        return f"{text[:77]}..."
    return text


def _format_dry_run_values(values: dict[str, Any]) -> str:
    if not values:
        return "-"
    return ", ".join(
        f"{field}={_redact_preview_value(field, value)}"
        for field, value in values.items()
    )


def _render_action_value(raw_value: Any, payload: Any) -> Any:
    if raw_value is None:
        return None
    if isinstance(raw_value, dict):
        return {str(key): _render_action_value(item, payload) for key, item in raw_value.items()}
    if isinstance(raw_value, (list, tuple, set)):
        return [_render_action_value(item, payload) for item in raw_value]
    if isinstance(raw_value, (bool, int, float, Decimal)):
        return raw_value
    return render_template_string(str(raw_value), payload if isinstance(payload, dict) else {})


def _source_field_map(source_code: str | None, *, include_virtual: bool = False) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for field in get_source_fields(source_code):
        field_name = str(field.get("name") or "").strip()
        if not field_name:
            continue
        if not include_virtual and (field.get("is_virtual") or not field.get("db_column")):
            continue
        result[field_name] = field
    return result


def _resolve_action_run_if(config: dict[str, Any], payload: Any, old_payload: Any = None) -> tuple[bool, str]:
    run_if = config.get("run_if")
    if not isinstance(run_if, dict) or not run_if:
        return True, ""

    # Il valore atteso e' accettato sia come `expected_value` (schema storico run_if di azione)
    # sia come `value` (schema usato dalle condition dei pacchetti e dal run_if di branch),
    # per uniformare i due schemi ed evitare confronti silenziosamente vuoti.
    raw_expected = run_if.get("expected_value")
    if raw_expected in (None, ""):
        raw_expected = run_if.get("value")
    condition = SimpleNamespace(
        field_name=str(run_if.get("field_name") or "").strip(),
        operator=str(run_if.get("operator") or "").strip(),
        expected_value=str(raw_expected or ""),
        value_type=str(run_if.get("value_type") or ""),
        compare_with_old=bool(run_if.get("compare_with_old")),
    )
    matched = evaluate_condition(condition, payload, old_payload=old_payload)
    negate = bool(run_if.get("negate"))
    if negate:
        matched = not matched

    description = f"{condition.field_name} {condition.operator}".strip()
    expected_value = str(condition.expected_value or "").strip()
    if expected_value:
        description = f"{description} {expected_value}"
    if negate:
        description = f"NOT ({description})"
    return matched, description or "run_if"


def _resolve_source_pk_for_action(
    *,
    source_definition: dict[str, Any] | None,
    payload: Any,
    queue_event: dict[str, Any] | None = None,
) -> Any:
    if queue_event and queue_event.get("source_pk") not in {None, ""}:
        return queue_event.get("source_pk")
    if not isinstance(payload, dict):
        return None
    pk_field = str((source_definition or {}).get("pk_field") or "id").strip() or "id"
    return safe_get_payload_value(payload, pk_field)


def _validate_source_update_fields(source_code: str | None, update_fields: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    source_definition = get_source_definition(source_code)
    if source_definition is None:
        raise ValueError("Sorgente non valida per update_trigger_record.")
    if not isinstance(update_fields, dict) or not update_fields:
        raise ValueError("update_trigger_record richiede update_fields non vuoto.")

    field_map = {
        str(field["name"]): field
        for field in get_action_mapping_fields(source_code)
        if field.get("db_column") and not field.get("is_virtual")
    }
    pk_field = str(source_definition.get("pk_field") or "id")
    invalid_fields = sorted(
        field_name
        for field_name in update_fields.keys()
        if str(field_name).strip() not in field_map or str(field_name).strip() == pk_field
    )
    if invalid_fields:
        raise ValueError(
            "Campi non aggiornabili sul record triggerante: " + ", ".join(invalid_fields) + "."
        )
    return source_definition, field_map


def _execute_update_trigger_record(
    *,
    source_code: str | None,
    payload_context: Any,
    queue_event: dict[str, Any] | None,
    update_fields: dict[str, Any],
) -> dict[str, Any]:
    source_definition, field_map = _validate_source_update_fields(source_code, update_fields)
    source_pk = _resolve_source_pk_for_action(
        source_definition=source_definition,
        payload=payload_context,
        queue_event=queue_event,
    )
    if source_pk in {None, ""}:
        raise ValueError("Impossibile determinare la PK del record triggerante.")

    rendered_update_fields = {
        str(field_name).strip(): _render_action_value(raw_value, payload_context)
        for field_name, raw_value in update_fields.items()
    }
    # Coercizione di tipo: SQL Server rifiuta stringhe su colonne tinyint/int.
    # Applichiamo una conversione best-effort in base al data_type del campo.
    coerced_update_fields: dict[str, Any] = {}
    for field_name, value in rendered_update_fields.items():
        data_type = str(field_map.get(field_name, {}).get("data_type") or "").strip().lower()
        coerced_update_fields[field_name] = _coerce_db_value(value, data_type)
    assignments = ", ".join(
        f"{connection.ops.quote_name(str(field_map[field_name]['db_column']))} = %s"
        for field_name in coerced_update_fields.keys()
    )
    quoted_table = connection.ops.quote_name(str(source_definition.get("table_name") or ""))
    pk_field_name = str(source_definition.get("pk_field") or "id")
    pk_meta = _source_field_map(source_code, include_virtual=False).get(pk_field_name, {"db_column": pk_field_name})
    quoted_pk = connection.ops.quote_name(str(pk_meta.get("db_column") or pk_field_name))
    params = [coerced_update_fields[field_name] for field_name in coerced_update_fields.keys()] + [source_pk]
    sql = f"UPDATE {quoted_table} SET {assignments} WHERE {quoted_pk} = %s"

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return {
                "rowcount": cursor.rowcount if cursor.rowcount is not None else 0,
                "source_pk": source_pk,
                "sql": sql,
                "params": params,
                "columns": list(coerced_update_fields.keys()),
            }


def _coerce_db_value(value: Any, data_type: str) -> Any:
    """Converte un valore renderizzato nel tipo Python corretto per il DB.

    SQL Server rifiuta nvarchar su colonne tinyint/int: i campi bool vanno
    mappati a 0/1, i campi int vanno forzati a int.  Restituisce il valore
    originale se la conversione non e' applicabile o fallisce.
    """
    if value is None:
        return None
    if data_type == "bool":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        str_val = str(value).strip().lower()
        if str_val in {"1", "true", "yes", "si", "sì", "t", "vero"}:
            return 1
        return 0
    if data_type == "int":
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except (TypeError, ValueError):
            return value  # lascia che SQL Server generi un errore descrittivo
    if data_type == "float":
        if isinstance(value, (int, float)):
            return value
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    return value


def _coerce_timeout_seconds(raw_value: Any, *, default: int = 20) -> int:
    try:
        timeout = int(raw_value)
    except (TypeError, ValueError):
        timeout = default
    return max(timeout, 1)


def _render_delay_until(raw_value: Any, payload_context: Any) -> datetime:
    rendered = str(_render_action_value(raw_value, payload_context) or "").strip()
    if not rendered:
        raise ValueError("delay_schedule richiede until_template valorizzato.")

    parsed_datetime = _parse_datetime(rendered)
    if parsed_datetime is _UNCASTABLE:
        parsed_date = _parse_date(rendered)
        if parsed_date in {_UNCASTABLE, None}:
            raise ValueError("until_template non produce una data/ora ISO valida.")
        parsed_datetime = datetime.combine(parsed_date, datetime.min.time())
    elif parsed_datetime is None:
        raise ValueError("until_template non produce una data/ora valida.")

    if timezone.is_naive(parsed_datetime):
        parsed_datetime = timezone.make_aware(parsed_datetime, timezone.get_current_timezone())
    return parsed_datetime


def _http_request_payload(config: dict[str, Any], payload_context: Any) -> tuple[str, str, dict[str, str], Any, int, list[int]]:
    method = str(config.get("method") or "").strip().upper()
    url = str(_render_action_value(config.get("url_template"), payload_context) or "").strip()
    headers_raw = _render_action_value(config.get("headers"), payload_context)
    headers = {
        str(key).strip(): str(value).strip()
        for key, value in (headers_raw.items() if isinstance(headers_raw, dict) else [])
        if str(key).strip()
    }
    body = _render_action_value(config.get("body_template"), payload_context)
    timeout_seconds = _coerce_timeout_seconds(config.get("timeout_seconds"), default=20)
    expected_statuses = [
        int(status)
        for status in (config.get("expected_statuses") or [])
        if str(status).strip()
    ]
    return method, url, headers, body, timeout_seconds, expected_statuses


def _perform_http_request(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    body: Any,
    timeout_seconds: int,
) -> requests.Response:
    request_kwargs: dict[str, Any] = {
        "method": method,
        "url": url,
        "headers": headers or None,
        "timeout": timeout_seconds,
    }

    if body is not None and body != "":
        content_type = str((headers or {}).get("Content-Type") or (headers or {}).get("content-type") or "").lower()
        if isinstance(body, (dict, list)):
            request_kwargs["json"] = body
        elif "application/json" in content_type:
            try:
                request_kwargs["json"] = json.loads(str(body))
            except (TypeError, ValueError, json.JSONDecodeError):
                request_kwargs["data"] = str(body)
        else:
            request_kwargs["data"] = str(body)

    return requests.request(**request_kwargs)


def _normalize_teams_theme_color(raw_value: Any) -> str:
    normalized = str(raw_value or "").strip().lstrip("#")
    return normalized or "2563EB"


def _parse_email_recipients(raw_value: Any, payload: Any, field_name: str) -> list[str]:
    rendered_value = _render_action_value(raw_value, payload)

    if rendered_value is None or rendered_value == "":
        return []

    if isinstance(rendered_value, str):
        candidates = rendered_value.split(",")
    elif isinstance(rendered_value, (list, tuple, set)):
        candidates = list(rendered_value)
    else:
        raise ValueError(f"{field_name} deve essere una stringa CSV o una lista.")

    emails: list[str] = []
    for candidate in candidates:
        email = str(candidate).strip()
        if not email:
            continue
        if "{" in email and "}" in email:
            raise ValueError(f"Placeholder non risolto in {field_name}: {email}.")
        try:
            validate_email(email)
        except ValidationError as exc:
            raise ValueError(f"Indirizzo email non valido in {field_name}: {email}.") from exc
        emails.append(email)
    return emails


def _filter_recipients_by_notifica_pref(
    to: list[str],
    cc: list[str],
    bcc: list[str],
    notifica_tipo: str,
) -> tuple[list[str], list[str], list[str]]:
    """Rimuove da to/cc/bcc gli indirizzi di utenti che hanno disabilitato notifica_tipo.

    La lookup avviene tramite User.email. Se un indirizzo non corrisponde ad alcun
    utente Django, viene mantenuto (fail-open: meglio inviare che perdere una notifica).
    """
    from django.contrib.auth import get_user_model
    from core.models import UserOnboarding

    all_emails = set(to + cc + bcc)
    if not all_emails:
        return to, cc, bcc

    User = get_user_model()
    try:
        # Mappa email -> user per tutti i destinatari in un'unica query
        users_by_email = {
            u.email.lower(): u
            for u in User.objects.filter(email__in=list(all_emails)).only("id", "email")
            if u.email
        }
        # Onboarding completato per gli utenti trovati, in un'unica query
        user_ids = [u.id for u in users_by_email.values()]
        onb_map = {
            o.user_id: o
            for o in UserOnboarding.objects.filter(user_id__in=user_ids, completed=True)
        }
    except Exception:
        return to, cc, bcc  # fail-open in caso di errore DB

    def keep(email: str) -> bool:
        user = users_by_email.get(email.lower())
        if user is None:
            return True  # indirizzo sconosciuto: non filtrare
        onb = onb_map.get(user.id)
        if onb is None:
            return True  # utente senza onboarding: fail-open
        return onb.get_notifica(notifica_tipo, default=True)

    return (
        [e for e in to if keep(e)],
        [e for e in cc if keep(e)],
        [e for e in bcc if keep(e)],
    )


def _validate_sender_email(raw_value: Any, payload: Any) -> str:
    rendered = _render_action_value(raw_value, payload)
    from_email = str(rendered or settings.DEFAULT_FROM_EMAIL or "").strip()
    if not from_email:
        raise ValueError("from_email mancante e DEFAULT_FROM_EMAIL non configurato.")
    try:
        validate_email(from_email)
    except ValidationError as exc:
        raise ValueError(f"Indirizzo from_email non valido: {from_email}.") from exc
    return from_email


def _dedupe_emails(emails: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_emails: list[str] = []
    for email in emails:
        normalized = str(email or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_emails.append(normalized)
    return unique_emails


def _resolve_approval_delivery_mode(config: dict[str, Any]) -> str:
    explicit_mode = str(config.get("delivery_mode") or "").strip()
    if explicit_mode:
        return explicit_mode

    has_flow = any(
        [
            str(config.get("teams_flow_endpoint_id") or "").strip(),
            str(config.get("teams_flow_url") or "").strip(),
            str(config.get("teams_recipient_email_template") or "").strip(),
        ]
    )
    has_legacy = any(
        [
            str(config.get("teams_preset_id") or "").strip(),
            str(config.get("teams_webhook_url") or "").strip(),
        ]
    )
    has_email = bool(str(config.get("to_template") or "").strip())

    if has_flow and has_email:
        return ApprovalDeliveryMode.EMAIL_AND_TEAMS_CHAT_FLOW
    if has_flow:
        return ApprovalDeliveryMode.TEAMS_CHAT_FLOW
    if has_legacy:
        return ApprovalDeliveryMode.TEAMS_WEBHOOK_LEGACY
    return ApprovalDeliveryMode.EMAIL


def _create_approval_record(
    *,
    action: AutomationAction,
    run_log: AutomationRunLog | None,
    approver_emails: list[str],
    subject: str,
    message_body: str,
    expiry_days: int,
    payload_context: dict[str, Any],
    old_payload: Any,
    approved_actions: list[dict[str, Any]],
    rejected_actions: list[dict[str, Any]],
):
    from .models import AutomationApproval

    return AutomationApproval.objects.create(
        run_log=run_log,
        action=action if getattr(action, "pk", None) else None,
        approver_emails=approver_emails,
        subject=subject,
        message=message_body,
        expires_at=timezone.now() + timedelta(days=expiry_days),
        resume_payload=payload_context,
        resume_old_payload=old_payload if isinstance(old_payload, dict) else None,
        approved_actions=approved_actions,
        rejected_actions=rejected_actions,
    )


def _build_approval_links(approval: Any) -> tuple[str, str]:
    site_url = str(getattr(settings, "SITE_URL", "") or "").rstrip("/")
    approve_url = f"{site_url}/automazioni/approvazione/{approval.token}/approva/"
    reject_url = f"{site_url}/automazioni/approvazione/{approval.token}/rifiuta/"
    return approve_url, reject_url


def _send_approval_email(
    *,
    approver_emails: list[str],
    subject: str,
    message_body: str,
    approve_url: str,
    reject_url: str,
    approve_label: str,
    reject_label: str,
    expires_at: datetime | None,
    html_body_override: str | None = None,
    text_body_override: str | None = None,
) -> str:
    """
    Invia l'email di approvazione.
    Se html_body_override / text_body_override sono valorizzati (rendering da ApprovalEmailTemplate),
    vengono usati direttamente. Altrimenti viene generato il corpo inline (comportamento legacy).
    """
    from_email = _validate_sender_email("", {})
    expires_label = timezone.localtime(expires_at).strftime("%d-%m-%Y %H:%M") if expires_at else "N/D"

    if html_body_override is not None and text_body_override is not None:
        html_body = html_body_override
        text_body = text_body_override
    else:
        from django.template.loader import render_to_string
        from django.utils.safestring import mark_safe
        import html as _html

        expires_warning = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;">'
            f'<tr><td style="padding:14px 16px;border-left:4px solid #d69e2e;background:#fffaf0;border-radius:10px;'
            f'color:#6b4f0f;font-size:13px;line-height:1.55;">'
            f'La richiesta scade il <strong>{expires_label}</strong>.'
            f'</td></tr></table>'
        ) if expires_at else ""

        cta_buttons = (
            f'<table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
            f'<tr>'
            f'<td style="padding:0 12px 0 0;">'
            f'<a href="{approve_url}" class="ecta" style="display:inline-block;padding:12px 22px;background:#38a169;'
            f'color:#ffffff;text-decoration:none;border-radius:9px;font-size:14px;font-weight:800;">{_html.escape(approve_label)}</a>'
            f'</td>'
            f'<td style="padding:0;">'
            f'<a href="{reject_url}" class="ecta" style="display:inline-block;padding:12px 22px;background:#e53e3e;'
            f'color:#ffffff;text-decoration:none;border-radius:9px;font-size:14px;font-weight:800;">{_html.escape(reject_label)}</a>'
            f'</td>'
            f'</tr>'
            f'</table>'
        )

        # Preserva gli a-capo del message_template: prima si escapa l'HTML (sicurezza),
        # poi i newline diventano <br> cosi' il corpo non collassa su una riga unica.
        message_body_html = _html.escape(message_body).replace("\n", "<br>")
        html_body = render_to_string("core/email/base_email.html", {
            "email_type": "Approvazione",
            "badge": "Richiede azione",
            "section_label": "Richiesta approvazione",
            "body_content": mark_safe(f'<p style="color:#475569;font-size:15px;line-height:1.7;">{message_body_html}</p>'),
            "expires_html": mark_safe(expires_warning),
            "cta_buttons": mark_safe(cta_buttons),
        })
        text_body = (
            f"{message_body}\n\n"
            f"{approve_label}: {approve_url}\n"
            f"{reject_label}: {reject_url}\n"
        )

    for approver_email in approver_emails:
        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=from_email,
            to=[approver_email],
        )
        message.attach_alternative(html_body, "text/html")
        message.send(fail_silently=False)

    return f"Email approvazione inviata a {', '.join(approver_emails)}."


def _resolve_approval_email_template(config: dict[str, Any]) -> Any | None:
    """
    Risolve l'ApprovalEmailTemplate referenziato nel config di send_approval.
    Ritorna il template o None se non specificato / non trovato / tabella mancante.
    Degrada silenziosamente: mai sollevare eccezioni qui.
    """
    template_id = config.get("approval_email_template_id")
    template_code = config.get("approval_email_template_code")
    if not template_id and not template_code:
        return None
    try:
        from .models import get_approval_email_template
        template, table_missing = get_approval_email_template(
            template_id=template_id,
            template_code=template_code,
            enabled_only=True,
        )
        if table_missing:
            logger.warning(
                "_resolve_approval_email_template: tabella ApprovalEmailTemplate non trovata. "
                "Eseguire `migrate automazioni`."
            )
        return template
    except Exception:
        logger.warning("_resolve_approval_email_template: errore nel caricamento template.", exc_info=True)
        return None


def _parse_approval_facts(config: dict[str, Any], payload_context: dict[str, Any]) -> list[dict[str, str]]:
    facts: list[dict[str, str]] = []
    facts_inline = str(config.get("teams_facts_inline") or "").strip()
    if facts_inline:
        for raw_line in facts_inline.splitlines():
            line = str(raw_line or "").strip()
            if not line or "|" not in line:
                continue
            fact_name, fact_value_template = line.split("|", 1)
            fact_name = fact_name.strip()
            if not fact_name:
                continue
            facts.append(
                {
                    "name": fact_name,
                    "value": render_template_string(fact_value_template.strip(), payload_context),
                }
            )
        return facts

    for fact_cfg in list(config.get("teams_facts") or []):
        if not isinstance(fact_cfg, dict):
            continue
        fact_name = str(fact_cfg.get("name") or "").strip()
        if not fact_name:
            continue
        facts.append(
            {
                "name": fact_name,
                "value": render_template_string(str(fact_cfg.get("value_template") or ""), payload_context),
            }
        )
    return facts


def _resolve_approval_teams_webhook_legacy_url(config: dict[str, Any], payload_context: dict[str, Any]) -> str:
    teams_webhook_url_raw = str(config.get("teams_webhook_url") or "").strip()
    teams_preset_id = config.get("teams_preset_id")

    if teams_preset_id:
        from .models import TeamsWebhookPreset

        preset = TeamsWebhookPreset.objects.get(pk=teams_preset_id, is_active=True)
        teams_webhook_url_raw = str(preset.webhook_url or "").strip()

    teams_webhook_url = render_template_string(teams_webhook_url_raw, payload_context).strip()
    if not teams_webhook_url:
        raise ValueError("Webhook Teams legacy mancante.")
    return teams_webhook_url


def _send_approval_teams_webhook_legacy(
    *,
    config: dict[str, Any],
    payload_context: dict[str, Any],
    subject: str,
    message_body: str,
    approve_url: str,
    reject_url: str,
    approve_label: str,
    reject_label: str,
) -> str:
    teams_webhook_url = _resolve_approval_teams_webhook_legacy_url(config, payload_context)
    teams_title = render_template_string(config.get("teams_title_template") or subject, payload_context).strip() or subject
    teams_theme_color = str(config.get("teams_theme_color") or "1a56db").strip()
    facts = _parse_approval_facts(config, payload_context)
    card_payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": teams_theme_color,
        "summary": teams_title,
        "title": teams_title,
        "sections": [
            {
                "activitySubtitle": message_body,
                "facts": facts,
                "markdown": True,
            }
        ],
        "potentialAction": [
            {
                "@type": "HttpPOST",
                "name": approve_label,
                "target": approve_url,
                "body": '{"action":"approve"}',
                "bodyContentType": "application/json",
            },
            {
                "@type": "HttpPOST",
                "name": reject_label,
                "target": reject_url,
                "body": '{"action":"reject"}',
                "bodyContentType": "application/json",
            },
        ],
    }
    response = _perform_http_request(
        method="POST",
        url=teams_webhook_url,
        headers={"Content-Type": "application/json"},
        body=card_payload,
        timeout_seconds=10,
    )
    if not response.ok:
        raise ValueError(f"Teams webhook legacy ha risposto con HTTP {response.status_code}.")
    return f"Teams webhook legacy inviato (HTTP {response.status_code})."


def _render_required_email(raw_template: Any, payload_context: dict[str, Any], *, field_label: str) -> str:
    email_value = render_template_string(str(raw_template or ""), payload_context).strip().lower()
    if not email_value:
        raise ValueError(f"{field_label} vuota.")
    try:
        validate_email(email_value)
    except ValidationError as exc:
        raise ValueError(f"{field_label} non valida: {email_value}.") from exc
    return email_value


def _resolve_approval_teams_flow_endpoint_url(config: dict[str, Any]) -> str:
    endpoint_id = str(config.get("teams_flow_endpoint_id") or "").strip()
    raw_url = str(config.get("teams_flow_url") or "").strip()
    if endpoint_id:
        endpoint, unavailable = get_teams_flow_endpoint_by_id(endpoint_id, active_only=True)
        if unavailable:
            raise ValueError(AUTOMATION_DELIVERY_ENDPOINT_UNAVAILABLE_MESSAGE)
        if endpoint is not None:
            raw_url = str(endpoint.endpoint_url or "").strip()
    if not raw_url:
        raise ValueError("Endpoint Teams Flow mancante o non attivo.")
    return raw_url


def _format_approval_expires_at(expires_at: datetime | None) -> str:
    if not expires_at:
        return ""
    normalized = expires_at
    if timezone.is_naive(normalized):
        normalized = timezone.make_aware(normalized, dt_timezone.utc)
    return normalized.astimezone(dt_timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _send_approval_teams_chat_flow(
    *,
    config: dict[str, Any],
    approval: Any,
    payload_context: dict[str, Any],
    subject: str,
    message_body: str,
    approve_url: str,
    reject_url: str,
) -> dict[str, Any]:
    recipient_email = _render_required_email(
        config.get("teams_recipient_email_template"),
        payload_context,
        field_label="recipient_email",
    )
    endpoint_url = _resolve_approval_teams_flow_endpoint_url(config)
    teams_subject = render_template_string(config.get("teams_title_template") or subject, payload_context).strip() or subject
    payload = {
        "approval_id": approval.pk,
        "token": str(approval.token),
        "recipient_email": recipient_email,
        "subject": teams_subject,
        "message": message_body,
        "approve_url": approve_url,
        "reject_url": reject_url,
        "expires_at": _format_approval_expires_at(approval.expires_at),
        "facts": _parse_approval_facts(config, payload_context),
    }
    response = requests.post(endpoint_url, json=payload, timeout=10)
    if not response.ok:
        raise ValueError(f"Teams chat flow ha risposto con HTTP {response.status_code}.")
    return {
        "recipient_email": recipient_email,
        "payload": payload,
        "result_message": f"Teams chat flow inviato a {recipient_email} (HTTP {response.status_code}).",
    }


def validate_target_table_and_fields(
    action_type: str,
    target_table: str,
    data_fields: list[str] | set[str],
    where_field: str | None = None,
) -> dict[str, set[str]]:
    table_name = str(target_table or "").strip()
    if not table_name:
        raise AutomationSafetyError(f"Tabella target mancante per {action_type}.")

    whitelist = get_action_table_whitelist().get(action_type, {})
    table_rules = whitelist.get(table_name)
    if table_rules is None:
        raise AutomationSafetyError(f"Tabella target non whitelistata per {action_type}: {table_name}.")
    if not _SAFE_IDENTIFIER_PATTERN.match(table_name):
        raise AutomationSafetyError(f"Tabella target non ammessa per {action_type}: {table_name}.")

    requested_fields = {str(field).strip() for field in data_fields if str(field).strip()}
    if not requested_fields:
        raise AutomationSafetyError(f"{action_type} richiede almeno una colonna valida.")
    invalid_identifier_fields = sorted(field for field in requested_fields if not _SAFE_IDENTIFIER_PATTERN.match(field))
    if invalid_identifier_fields:
        invalid_list = ", ".join(invalid_identifier_fields)
        raise AutomationSafetyError(f"Colonne con nome non ammesso per {table_name}: {invalid_list}.")

    invalid_fields = requested_fields - set(table_rules.get("fields", set()))
    if invalid_fields:
        invalid_list = ", ".join(sorted(invalid_fields))
        raise AutomationSafetyError(f"Colonne non whitelistate per {table_name}: {invalid_list}.")

    if where_field is not None:
        normalized_where_field = str(where_field).strip()
        if not normalized_where_field:
            raise AutomationSafetyError("where_field e' obbligatorio.")
        if not _SAFE_IDENTIFIER_PATTERN.match(normalized_where_field):
            raise AutomationSafetyError(f"Campo where con nome non ammesso per {table_name}: {normalized_where_field}.")
        allowed_where_fields = set(table_rules.get("where_fields", set()))
        if normalized_where_field not in allowed_where_fields:
            raise AutomationSafetyError(f"Campo where non whitelistato per {table_name}: {normalized_where_field}.")

    return {
        "fields": set(table_rules.get("fields", set())),
        "where_fields": set(table_rules.get("where_fields", set())),
    }


def execute_safe_insert(target_table: str, field_values: dict[str, Any]) -> dict[str, Any]:
    if not field_values:
        raise ValueError("field_mappings non puo' essere vuoto.")

    normalized_values = {str(field).strip(): value for field, value in field_values.items() if str(field).strip()}
    validate_target_table_and_fields(AutomationActionType.INSERT_RECORD, target_table, list(normalized_values.keys()))

    columns = list(normalized_values.keys())
    quoted_table = connection.ops.quote_name(target_table)
    quoted_columns = ", ".join(connection.ops.quote_name(column) for column in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    params = [normalized_values[column] for column in columns]
    sql = f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})"

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return {
                "rowcount": cursor.rowcount if cursor.rowcount is not None else 1,
                "inserted_pk": getattr(cursor, "lastrowid", None),
                "sql": sql,
                "params": params,
            }


def execute_safe_update(
    target_table: str,
    update_fields: dict[str, Any],
    where_field: str,
    where_value: Any,
) -> dict[str, Any]:
    if not update_fields:
        raise ValueError("update_fields non puo' essere vuoto.")
    if where_value is None or where_value == "":
        raise ValueError("where_value_template non produce un valore valido.")

    normalized_update_fields = {
        str(field).strip(): value
        for field, value in update_fields.items()
        if str(field).strip()
    }
    normalized_where_field = str(where_field or "").strip()
    validate_target_table_and_fields(
        AutomationActionType.UPDATE_RECORD,
        target_table,
        list(normalized_update_fields.keys()),
        where_field=normalized_where_field,
    )

    columns = list(normalized_update_fields.keys())
    quoted_table = connection.ops.quote_name(target_table)
    assignments = ", ".join(f"{connection.ops.quote_name(column)} = %s" for column in columns)
    quoted_where_field = connection.ops.quote_name(normalized_where_field)
    params = [normalized_update_fields[column] for column in columns] + [where_value]
    sql = f"UPDATE {quoted_table} SET {assignments} WHERE {quoted_where_field} = %s"

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return {
                "rowcount": cursor.rowcount if cursor.rowcount is not None else 0,
                "sql": sql,
                "params": params,
            }


_ASSENZE_SPLIT_DEFAULT_COPY_COLUMNS = (
    "dipendente_id",
    "nome_lookup_id",
    "copia_nome",
    "email_esterna",
    "capo_reparto_id",
    "capo_reparto_lookup_id",
    "motivazione_richiesta",
    "motivazione",
    "certificato_medico",
    "note_gestione",
)
_ASSENZE_SPLIT_DEFAULT_DAY_COUNT_FIELDS = (
    "giorni_permesso",
    "giornipermesso",
    "Giornipermesso",
    "giorni",
)
_ASSENZE_SPLIT_DEFAULT_DEDUPE_FIELDS = (
    "dipendente_id",
    "copia_nome",
    "email_esterna",
    "tipo_assenza",
    "data_inizio",
    "data_fine",
    "motivazione_richiesta",
)


def _local_naive_now() -> datetime:
    now = timezone.now()
    if timezone.is_aware(now):
        return timezone.localtime(now).replace(tzinfo=None)
    return now


def _as_local_naive_datetime(value: Any, *, field_label: str) -> datetime:
    parsed = _parse_datetime(value)
    if parsed is None or parsed is _UNCASTABLE:
        raise ValueError(f"split_assenza_giornaliera: `{field_label}` non contiene una data/ora valida.")
    if timezone.is_aware(parsed):
        parsed = timezone.localtime(parsed).replace(tzinfo=None)
    return parsed.replace(tzinfo=None)


def _render_split_value(raw_value: Any, payload_context: dict[str, Any]) -> Any:
    rendered = _render_action_value(raw_value, payload_context)
    if isinstance(rendered, str):
        return rendered.strip()
    return rendered


def _split_config_int(config: dict[str, Any], key: str, default: int, *, minimum: int, maximum: int) -> int:
    raw_value = config.get(key, default)
    try:
        value = int(Decimal(str(raw_value).replace(",", ".").strip()))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"split_assenza_giornaliera: `{key}` deve essere un intero.") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"split_assenza_giornaliera: `{key}` deve essere tra {minimum} e {maximum}.")
    return value


def _split_config_bool(
    config: dict[str, Any],
    payload_context: dict[str, Any],
    keys: tuple[str, ...],
    default: bool,
) -> bool:
    raw_value = default
    for key in keys:
        if key in config:
            raw_value = config.get(key)
            break
    normalized = _normalize_runtime_bool(_render_split_value(raw_value, payload_context))
    return default if normalized is None else normalized


def _split_config_list(config: dict[str, Any], key: str, default: tuple[str, ...]) -> list[str]:
    raw_value = config.get(key)
    if raw_value is None and key == "days_count_fields":
        raw_value = config.get("days_count_field")
    if raw_value is None:
        return list(default)
    if isinstance(raw_value, str):
        return [chunk.strip() for chunk in raw_value.split(",") if chunk.strip()]
    if isinstance(raw_value, (list, tuple, set)):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    return list(default)


def _payload_first_value(payload_context: dict[str, Any], *field_names: str) -> Any:
    for field_name in field_names:
        value = safe_get_payload_value(payload_context, field_name)
        if value is not None:
            return value
    return None


def _resolve_split_day_count(config: dict[str, Any], payload_context: dict[str, Any]) -> int | None:
    for field_name in _split_config_list(
        config,
        "days_count_fields",
        _ASSENZE_SPLIT_DEFAULT_DAY_COUNT_FIELDS,
    ):
        value = safe_get_payload_value(payload_context, field_name)
        if value is None or value == "":
            continue
        try:
            parsed = Decimal(str(value).replace(",", ".").strip())
        except (InvalidOperation, TypeError, ValueError):
            continue
        if parsed > 1:
            return int(parsed)
    return None


def _split_assenza_offsets(
    config: dict[str, Any],
    payload_context: dict[str, Any],
) -> tuple[datetime, datetime, list[int], str]:
    start_field = str(config.get("start_field") or "data_inizio").strip() or "data_inizio"
    end_field = str(config.get("end_field") or "data_fine").strip() or "data_fine"
    start_dt = _as_local_naive_datetime(
        safe_get_payload_value(payload_context, start_field),
        field_label=start_field,
    )
    end_dt = _as_local_naive_datetime(
        safe_get_payload_value(payload_context, end_field),
        field_label=end_field,
    )
    if end_dt < start_dt:
        raise ValueError("split_assenza_giornaliera: `data_fine` precede `data_inizio`.")

    include_first_day = _split_config_bool(config, payload_context, ("include_first_day",), False)
    first_offset = 0 if include_first_day else 1
    days_from_payload = _resolve_split_day_count(config, payload_context)
    source_label = "date"

    if days_from_payload is not None:
        last_offset = max(days_from_payload - 1, 0)
        source_label = "days_count"
    else:
        last_offset = (end_dt.date() - start_dt.date()).days

    if last_offset < first_offset:
        return start_dt, end_dt, [], source_label

    offsets = list(range(first_offset, last_offset + 1))
    max_days = _split_config_int(config, "max_days", 60, minimum=1, maximum=366)
    if len(offsets) > max_days:
        raise ValueError(
            "split_assenza_giornaliera: lo split genererebbe "
            f"{len(offsets)} record, oltre il limite max_days={max_days}."
        )
    return start_dt, end_dt, offsets, source_label


def _table_column_map(table_name: str) -> dict[str, str]:
    if not table_name or not _SAFE_IDENTIFIER_PATTERN.match(table_name):
        raise AutomationSafetyError(f"Tabella Assenze non ammessa per split_assenza_giornaliera: {table_name}.")

    quoted_table = connection.ops.quote_name(table_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT * FROM {quoted_table} WHERE 1 = 0")
            return {
                str(column[0]).strip().lower(): str(column[0]).strip()
                for column in (cursor.description or [])
                if str(column[0]).strip()
            }
    except Exception as exc:
        raise ValueError(f"split_assenza_giornaliera: impossibile leggere la tabella `{table_name}`.") from exc


def _resolve_table_column(column_map: dict[str, str], column_name: str) -> str | None:
    return column_map.get(str(column_name or "").strip().lower())


def _set_split_row_value(
    row: dict[str, Any],
    column_map: dict[str, str],
    column_name: str,
    value: Any,
    *,
    allow_empty: bool = False,
) -> None:
    actual_column = _resolve_table_column(column_map, column_name)
    if not actual_column:
        return
    if not allow_empty and (value is None or value == ""):
        return
    row[actual_column] = value


def _build_assenza_split_base_row(
    config: dict[str, Any],
    payload_context: dict[str, Any],
    column_map: dict[str, str],
) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for column_name in _split_config_list(config, "copy_columns", _ASSENZE_SPLIT_DEFAULT_COPY_COLUMNS):
        value = safe_get_payload_value(payload_context, column_name)
        if value is None and column_name == "copia_nome":
            value = _payload_first_value(payload_context, "dipendente_nome", "richiedente_nome")
        elif value is None and column_name == "email_esterna":
            value = _payload_first_value(payload_context, "dipendente_email", "richiedente_email")
        _set_split_row_value(row, column_map, column_name, value)

    tipo_template = config.get("tipo_assenza_template", config.get("created_type_template", "{tipo_assenza}"))
    tipo_assenza = _render_split_value(tipo_template, payload_context)
    _set_split_row_value(row, column_map, "tipo_assenza", tipo_assenza)

    salta_approvazione = _split_config_bool(
        config,
        payload_context,
        ("salta_approvazione", "set_salta_approvazione"),
        True,
    )
    _set_split_row_value(row, column_map, "salta_approvazione", salta_approvazione, allow_empty=True)

    moderation_raw = config.get("moderation_status", config.get("set_moderation_status", 0))
    moderation_value = _render_split_value(moderation_raw, payload_context)
    if moderation_value is not None and moderation_value != "":
        try:
            moderation_value = int(str(moderation_value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("split_assenza_giornaliera: `moderation_status` deve essere intero.") from exc
        _set_split_row_value(row, column_map, "moderation_status", moderation_value, allow_empty=True)

    consenso_template = config.get("consenso_template", config.get("set_consenso", "Approvato"))
    consenso_value = _render_split_value(consenso_template, payload_context)
    _set_split_row_value(row, column_map, "consenso", consenso_value)

    now_value = _local_naive_now()
    _set_split_row_value(row, column_map, "created_datetime", now_value, allow_empty=True)
    _set_split_row_value(row, column_map, "modified_datetime", now_value, allow_empty=True)
    if _split_config_bool(config, payload_context, ("set_approval_datetime",), True):
        _set_split_row_value(row, column_map, "approvazione_datetime", now_value, allow_empty=True)
    _set_split_row_value(row, column_map, "giornipermesso", 1, allow_empty=True)
    _set_split_row_value(row, column_map, "giorni_permesso", 1, allow_empty=True)
    _set_split_row_value(row, column_map, "fattomultipli", False, allow_empty=True)
    return row


def _build_assenza_split_rows(
    config: dict[str, Any],
    payload_context: dict[str, Any],
    column_map: dict[str, str],
) -> tuple[list[dict[str, Any]], str]:
    start_dt, end_dt, offsets, source_label = _split_assenza_offsets(config, payload_context)
    data_inizio_col = _resolve_table_column(column_map, "data_inizio")
    data_fine_col = _resolve_table_column(column_map, "data_fine")
    if not data_inizio_col or not data_fine_col:
        raise ValueError("split_assenza_giornaliera: la tabella Assenze richiede `data_inizio` e `data_fine`.")

    base_row = _build_assenza_split_base_row(config, payload_context, column_map)
    rows: list[dict[str, Any]] = []
    start_time = start_dt.time().replace(tzinfo=None)
    end_time = end_dt.time().replace(tzinfo=None)

    for offset in offsets:
        current_day = start_dt.date() + timedelta(days=offset)
        row = dict(base_row)
        row[data_inizio_col] = datetime.combine(current_day, start_time)
        row[data_fine_col] = datetime.combine(current_day, end_time)
        rows.append(row)
    return rows, source_label


def _assenza_split_row_exists(
    table_name: str,
    row: dict[str, Any],
    config: dict[str, Any],
    column_map: dict[str, str],
) -> bool:
    if not _split_config_bool(config, row, ("dedupe",), True):
        return False

    dedupe_columns = _split_config_list(config, "dedupe_fields", _ASSENZE_SPLIT_DEFAULT_DEDUPE_FIELDS)
    where_parts: list[str] = []
    params: list[Any] = []
    for column_name in dedupe_columns:
        actual_column = _resolve_table_column(column_map, column_name)
        if not actual_column or actual_column not in row or row[actual_column] is None or row[actual_column] == "":
            continue
        where_parts.append(f"{connection.ops.quote_name(actual_column)} = %s")
        params.append(row[actual_column])

    if not where_parts:
        return False

    quoted_table = connection.ops.quote_name(table_name)
    where_sql = " AND ".join(where_parts)
    if connection.vendor == "sqlite":
        sql = f"SELECT 1 FROM {quoted_table} WHERE {where_sql} LIMIT 1"
    else:
        sql = f"SELECT TOP 1 1 FROM {quoted_table} WHERE {where_sql}"
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone() is not None


def execute_split_assenza_giornaliera(
    *,
    config: dict[str, Any],
    payload_context: dict[str, Any],
    source_code: str,
) -> dict[str, Any]:
    configured_source = str(config.get("source_code") or "").strip()
    effective_source = source_code or configured_source
    if effective_source != "assenze":
        raise AutomationSafetyError(
            "split_assenza_giornaliera puo' essere eseguita solo sulla sorgente `assenze`."
        )

    source_definition = get_source_definition("assenze") or {}
    table_name = str(source_definition.get("table_name") or "assenze").strip()
    column_map = _table_column_map(table_name)
    rows, day_source = _build_assenza_split_rows(config, payload_context, column_map)
    if not rows:
        return {"planned": 0, "inserted": 0, "skipped": 0, "day_source": day_source}

    inserted = 0
    skipped = 0
    with transaction.atomic():
        for row in rows:
            if _assenza_split_row_exists(table_name, row, config, column_map):
                skipped += 1
                continue
            columns = list(row.keys())
            quoted_table = connection.ops.quote_name(table_name)
            quoted_columns = ", ".join(connection.ops.quote_name(column) for column in columns)
            placeholders = ", ".join(["%s"] * len(columns))
            params = [row[column] for column in columns]
            sql = f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})"
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
            inserted += 1

    return {"planned": len(rows), "inserted": inserted, "skipped": skipped, "day_source": day_source}


def preview_split_assenza_giornaliera(
    *,
    config: dict[str, Any],
    payload_context: dict[str, Any],
) -> dict[str, Any]:
    start_dt, end_dt, offsets, day_source = _split_assenza_offsets(config, payload_context)
    dates = [
        (start_dt.date() + timedelta(days=offset)).isoformat()
        for offset in offsets
    ]
    return {
        "start": start_dt,
        "end": end_dt,
        "planned": len(offsets),
        "dates": dates,
        "day_source": day_source,
    }


def find_matching_rules(queue_event: dict[str, Any]) -> list[AutomationRule]:
    source_code = str(queue_event.get("source_code") or "").strip()
    operation_type = str(queue_event.get("operation_type") or "").strip().lower()
    payload = queue_event.get("payload")
    old_payload = queue_event.get("old_payload")

    if not source_code or operation_type not in {"insert", "update"}:
        return []

    base_queryset = AutomationRule.objects.filter(
        source_code=source_code,
        operation_type=operation_type,
        is_active=True,
        is_draft=False,
    ).order_by("id")

    if operation_type == "insert":
        return list(base_queryset.filter(trigger_scope="all_inserts"))

    matched_rules: list[AutomationRule] = []
    for rule in base_queryset.filter(trigger_scope__in=["all_updates", "any_change", "specific_field"]):
        if rule.trigger_scope == "all_updates":
            matched_rules.append(rule)
            continue
        if rule.trigger_scope == "any_change" and _did_payload_change(payload, old_payload):
            matched_rules.append(rule)
            continue
        if rule.trigger_scope == "specific_field" and _did_payload_field_change(payload, old_payload, rule.watched_field):
            matched_rules.append(rule)
    return matched_rules


def _log_skipped_by_group(
    rule: AutomationRule,
    queue_id: int,
    winner: AutomationRule,
    payload: Any,
    old_payload: Any,
) -> None:
    """Registra un run-log SKIPPED per una regola esclusa da un'altra del gruppo.

    Preserva la tracciabilita': in UI resta visibile perche' la regola non ha
    agito, senza eseguirne le azioni.
    """
    try:
        now = timezone.now()
        AutomationRunLog.objects.create(
            rule=rule,
            queue_event_id=queue_id,
            source_code=rule.source_code,
            operation_type=rule.operation_type,
            trigger_event_label=_build_trigger_event_label(rule),
            status=AutomationRunLogStatus.SKIPPED,
            payload_json=payload if isinstance(payload, dict) else {},
            old_payload_json=old_payload,
            started_at=now,
            finished_at=now,
            execution_ms=0,
            is_test=False,
            result_message=(
                f"Saltata: gruppo '{rule.exclusion_group}' gia' gestito dalla "
                f"regola {winner.code} (priorita' {int(getattr(winner, 'priority', 0) or 0)})."
            ),
        )
    except Exception:
        logger.exception(
            "Impossibile registrare il run-log SKIPPED di gruppo per la regola %s (queue %s)",
            getattr(rule, "code", "?"),
            queue_id,
        )


def process_queue_event(queue_event: dict[str, Any]) -> dict[str, Any]:
    queue_id = int(queue_event["id"])
    source_code = str(queue_event.get("source_code") or "").strip()

    try:
        payload = _deserialize_queue_json(queue_event.get("payload_json"), field_name="payload_json")
        old_payload = _deserialize_queue_json(
            queue_event.get("old_payload_json"),
            field_name="old_payload_json",
            allow_null=True,
        )
        payload = _enrich_payload_for_source(source_code, payload)
        old_payload = _enrich_payload_for_source(source_code, old_payload)
    except ValueError as exc:
        mark_queue_error(queue_id, exc)
        return {"queue_id": queue_id, "status": QueueEventStatus.ERROR, "rule_runs": 0, "message": str(exc)}

    event_context = {
        **queue_event,
        "operation_type": str(queue_event.get("operation_type") or "").strip().lower(),
        "payload": payload,
        "old_payload": old_payload,
    }

    try:
        matching_rules = find_matching_rules(event_context)
    except Exception as exc:
        logger.exception("Errore matching regole per queue event %s", queue_id)
        mark_queue_error(queue_id, f"Errore matching regole: {exc}")
        return {"queue_id": queue_id, "status": QueueEventStatus.ERROR, "rule_runs": 0, "message": str(exc)}

    # Le regole senza exclusion_group vengono eseguite tutte (comportamento storico).
    # Le regole con lo stesso exclusion_group si escludono a vicenda sul medesimo
    # record: ne parte una sola, quella a priorita' piu' alta. Se la vincente va in
    # errore si prova la successiva del gruppo (fallback a cascata), cosi' il flusso
    # non viene perso; gli errori "assorbiti" dal fallback non mettono in errore
    # l'evento di coda. Un gruppo va in errore solo se TUTTE le sue regole falliscono.
    ungrouped_rules: list[AutomationRule] = []
    grouped_rules: dict[str, list[AutomationRule]] = {}
    for rule in matching_rules:
        group = str(getattr(rule, "exclusion_group", "") or "").strip()
        if group:
            grouped_rules.setdefault(group, []).append(rule)
        else:
            ungrouped_rules.append(rule)

    worker_errors: list[str] = []

    def _run_rule_status(rule: AutomationRule) -> tuple[str | None, str | None]:
        """Esegue una regola; ritorna (status_run_log, errore_o_None)."""
        try:
            run_log = run_rule(
                rule,
                payload,
                old_payload=old_payload,
                queue_event_id=queue_id,
                initiated_by=None,
                is_test=False,
                queue_event=queue_event,
            )
            return getattr(run_log, "status", None), None
        except Exception as exc:
            logger.exception("Errore run_rule per queue event %s e regola %s", queue_id, rule.code)
            return AutomationRunLogStatus.ERROR, f"{rule.code}: {exc}"

    for rule in ungrouped_rules:
        _status, error = _run_rule_status(rule)
        if error:
            worker_errors.append(error)

    for group, rules in grouped_rules.items():
        ordered = sorted(rules, key=lambda r: (-int(getattr(r, "priority", 0) or 0), r.id))
        group_errors: list[str] = []
        winner: AutomationRule | None = None
        for rule in ordered:
            if winner is not None:
                _log_skipped_by_group(rule, queue_id, winner, payload, old_payload)
                continue
            status, error = _run_rule_status(rule)
            if status in {
                AutomationRunLogStatus.SUCCESS,
                AutomationRunLogStatus.WAITING_APPROVAL,
            }:
                # Vincente: blocca il gruppo, le restanti vengono saltate (loggate).
                winner = rule
                continue
            if status == AutomationRunLogStatus.SKIPPED:
                # Condizioni non soddisfatte: non e' la regola giusta per questo
                # record, si prova la successiva senza considerarla errore.
                continue
            # status ERROR (con o senza eccezione): la regola e' fallita ->
            # fallback alla successiva del gruppo. Si registra comunque un errore
            # cosi' che, se nessuna del gruppo vince, l'evento resti ritentabile.
            group_errors.append(error or f"{rule.code}: esecuzione terminata in errore.")
        # Il gruppo propaga errore solo se nessuna regola ha vinto: in tal caso
        # tutti i tentativi sono falliti e l'evento deve restare ritentabile.
        if winner is None and group_errors:
            worker_errors.extend(group_errors)

    matched_rule_codes = [rule.code for rule in matching_rules]

    if worker_errors:
        mark_queue_error(queue_id, "; ".join(worker_errors))
        return {
            "queue_id": queue_id,
            "status": QueueEventStatus.ERROR,
            "rule_runs": len(matching_rules),
            "message": "; ".join(worker_errors),
            "candidate_rule_codes": matched_rule_codes,
        }

    mark_queue_done(queue_id)
    return {
        "queue_id": queue_id,
        "status": QueueEventStatus.DONE,
        "rule_runs": len(matching_rules),
        "message": "" if matching_rules else "Nessuna regola candidata.",
        "candidate_rule_codes": matched_rule_codes,
    }


def _preview_action_for_dry_run(
    action: AutomationAction,
    payload: Any,
    old_payload: Any = None,
    queue_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = action.config_json if isinstance(action.config_json, dict) else {}
    payload_context = payload if isinstance(payload, dict) else {}
    source_code = (
        str((queue_event or {}).get("source_code") or "").strip()
        or str(getattr(getattr(action, "rule", None), "source_code", "") or "").strip()
    )

    try:
        should_run, run_if_description = _resolve_action_run_if(config, payload_context, old_payload=old_payload)
        if not should_run:
            message = (
                f"DRY-RUN: action saltata ({run_if_description})."
                if run_if_description
                else "DRY-RUN: action saltata."
            )
            return {
                "status": AutomationActionLogStatus.SKIPPED,
                "action_id": action.pk,
                "action_type": action.action_type,
                "message": message,
            }

        if action.action_type == AutomationActionType.INSERT_RECORD:
            target_table = str(config.get("target_table") or "").strip()
            field_mappings = config.get("field_mappings")
            if not isinstance(field_mappings, dict) or not field_mappings:
                raise ValueError("insert_record richiede field_mappings non vuoto.")
            rendered_fields = {
                str(field_name).strip(): _render_action_value(raw_value, payload_context)
                for field_name, raw_value in field_mappings.items()
                if str(field_name).strip()
            }
            validate_target_table_and_fields(AutomationActionType.INSERT_RECORD, target_table, rendered_fields.keys())
            return {
                "status": AutomationActionLogStatus.SUCCESS,
                "action_id": action.pk,
                "action_type": action.action_type,
                "message": (
                    f"DRY-RUN insert_record: scriverebbe su {target_table} "
                    f"[{_format_dry_run_values(rendered_fields)}]."
                ),
            }

        if action.action_type == AutomationActionType.UPDATE_RECORD:
            target_table = str(config.get("target_table") or "").strip()
            where_field = str(config.get("where_field") or "").strip()
            where_value = _render_action_value(config.get("where_value_template"), payload_context)
            if isinstance(where_value, str) and _PLACEHOLDER_PATTERN.search(where_value):
                raise ValueError("where_value_template non produce un valore valido.")
            update_fields = config.get("update_fields")
            if not isinstance(update_fields, dict) or not update_fields:
                raise ValueError("update_record richiede update_fields non vuoto.")
            rendered_update_fields = {
                str(field_name).strip(): _render_action_value(raw_value, payload_context)
                for field_name, raw_value in update_fields.items()
                if str(field_name).strip()
            }
            validate_target_table_and_fields(
                AutomationActionType.UPDATE_RECORD,
                target_table,
                rendered_update_fields.keys(),
                where_field=where_field,
            )
            return {
                "status": AutomationActionLogStatus.SUCCESS,
                "action_id": action.pk,
                "action_type": action.action_type,
                "message": (
                    f"DRY-RUN update_record: aggiornerebbe {target_table} "
                    f"where {where_field}={_redact_preview_value(where_field, where_value)} "
                    f"set [{_format_dry_run_values(rendered_update_fields)}]."
                ),
            }

        if action.action_type == AutomationActionType.UPDATE_TRIGGER_RECORD:
            update_fields = config.get("update_fields")
            update_fields = update_fields if isinstance(update_fields, dict) else {}
            source_definition, field_map = _validate_source_update_fields(source_code, update_fields)
            source_pk = _resolve_source_pk_for_action(
                source_definition=source_definition,
                payload=payload_context,
                queue_event=queue_event,
            )
            if source_pk in {None, ""}:
                raise ValueError("Impossibile determinare la PK del record triggerante.")
            rendered_update_fields = {
                str(field_name).strip(): _render_action_value(raw_value, payload_context)
                for field_name, raw_value in update_fields.items()
                if str(field_name).strip()
            }
            columns = {
                str(field_map[field_name]["db_column"]): value
                for field_name, value in rendered_update_fields.items()
            }
            return {
                "status": AutomationActionLogStatus.SUCCESS,
                "action_id": action.pk,
                "action_type": action.action_type,
                "message": (
                    f"DRY-RUN update_trigger_record: aggiornerebbe {source_code}#{source_pk} "
                    f"set [{_format_dry_run_values(columns)}]."
                ),
            }

        if action.action_type == AutomationActionType.SPLIT_ASSENZA_GIORNALIERA:
            preview_source = source_code or str(config.get("source_code") or "").strip()
            if preview_source != "assenze":
                raise AutomationSafetyError(
                    "split_assenza_giornaliera puo' essere validata solo sulla sorgente `assenze`."
                )
            preview = preview_split_assenza_giornaliera(config=config, payload_context=payload_context)
            return {
                "status": AutomationActionLogStatus.SUCCESS,
                "action_id": action.pk,
                "action_type": action.action_type,
                "message": (
                    "DRY-RUN split_assenza_giornaliera: "
                    f"creerebbe {preview['planned']} record giornalieri "
                    f"({', '.join(preview['dates']) or 'nessun giorno da creare'}; "
                    f"sorgente giorni={preview['day_source']})."
                ),
            }

        if action.action_type == AutomationActionType.UPDATE_DASHBOARD_METRIC:
            metric_code = str(config.get("metric_code") or "").strip()
            operation = str(config.get("operation") or "").strip().lower()
            rendered_value = render_template_string(config.get("value_template"), payload_context).strip()
            if not metric_code:
                raise ValueError("update_dashboard_metric richiede metric_code.")
            if operation not in {"set", "increment", "decrement"}:
                raise ValueError("update_dashboard_metric richiede operation valida: set, increment o decrement.")
            if not rendered_value:
                raise ValueError("update_dashboard_metric richiede value_template valorizzato.")
            Decimal(rendered_value)
            return {
                "status": AutomationActionLogStatus.SUCCESS,
                "action_id": action.pk,
                "action_type": action.action_type,
                "message": (
                    f"DRY-RUN update_dashboard_metric: aggiornerebbe metric={metric_code} "
                    f"operation={operation} value={rendered_value}."
                ),
            }

        if action.action_type == AutomationActionType.DELAY_SCHEDULE:
            return {
                "status": AutomationActionLogStatus.SUCCESS,
                "action_id": action.pk,
                "action_type": action.action_type,
                "message": "DRY-RUN delay_schedule: schedulerebbe un nuovo evento queue.",
            }

        return {
            "status": AutomationActionLogStatus.SUCCESS,
            "action_id": action.pk,
            "action_type": action.action_type,
            "message": f"DRY-RUN {action.action_type}: validazione queue eseguita, azione runtime non invocata.",
        }
    except Exception as exc:
        if isinstance(exc, AutomationSafetyError):
            logger.warning(
                "automation safety guardrail blocked dry-run %s: %s",
                _format_action_identity(action),
                exc,
            )
            message = f"DRY-RUN safety blocked {action.action_type}: {exc}"
        else:
            message = f"DRY-RUN errore {action.action_type}: {exc}"
        return {
            "status": AutomationActionLogStatus.ERROR,
            "action_id": getattr(action, "pk", None),
            "action_type": getattr(action, "action_type", ""),
            "message": message,
        }


def _preview_rule_for_dry_run(
    rule: AutomationRule,
    payload: Any,
    old_payload: Any = None,
    queue_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    condition_messages: list[str] = []
    for condition in rule.conditions.filter(is_enabled=True).order_by("order", "id"):
        if not evaluate_condition(condition, payload, old_payload=old_payload):
            return {
                "rule_id": rule.pk,
                "rule_code": rule.code,
                "status": AutomationRunLogStatus.SKIPPED,
                "message": f"DRY-RUN regola saltata: condizione non soddisfatta ({condition.field_name}).",
                "actions": [],
            }
        condition_messages.append(f"{condition.field_name}:{condition.operator}")

    action_previews = [
        _preview_action_for_dry_run(action, payload, old_payload=old_payload, queue_event=queue_event)
        for action in rule.actions.filter(is_enabled=True).order_by("order", "id")
    ]
    action_errors = sum(1 for preview in action_previews if preview.get("status") == AutomationActionLogStatus.ERROR)
    return {
        "rule_id": rule.pk,
        "rule_code": rule.code,
        "status": AutomationRunLogStatus.ERROR if action_errors else AutomationRunLogStatus.SUCCESS,
        "message": (
            f"DRY-RUN regola {rule.code}: azioni valutate={len(action_previews)}, "
            f"errori={action_errors}."
        ),
        "conditions": condition_messages,
        "actions": action_previews,
    }


def process_single_queue_event_by_id(queue_id: int) -> dict[str, Any]:
    queue_event = claim_queue_event_by_id(
        queue_id,
        allowed_statuses=(QueueEventStatus.PENDING, QueueEventStatus.ERROR),
        max_retry_count=MAX_QUEUE_EVENT_RETRY_COUNT,
    )
    if queue_event is None:
        detail = get_queue_event_detail(queue_id)
        if detail is None:
            return {
                "queue_id": int(queue_id),
                "status": QueueEventStatus.ERROR,
                "rule_runs": 0,
                "message": "Evento queue non trovato.",
            }
        retry_count = int(detail.get("retry_count") or 0)
        if retry_count >= MAX_QUEUE_EVENT_RETRY_COUNT:
            return {
                "queue_id": int(queue_id),
                "status": QueueEventStatus.ERROR,
                "rule_runs": 0,
                "message": (
                    f"Evento queue ha raggiunto il numero massimo di retry "
                    f"({MAX_QUEUE_EVENT_RETRY_COUNT}). Stato attuale: {detail.get('status')}."
                ),
            }
        return {
            "queue_id": int(queue_id),
            "status": QueueEventStatus.ERROR,
            "rule_runs": 0,
            "message": f"Evento queue non processabile nello stato corrente: {detail.get('status')}.",
        }
    return process_queue_event(queue_event)


def process_pending_queue_events(
    limit: int = 50,
    source_code: str | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    summary = {
        "limit": max(int(limit or 0), 1),
        "source_code": str(source_code or "").strip() or None,
        "dry_run": bool(dry_run),
        "fetched": 0,
        "done": 0,
        "error": 0,
        "rule_runs": 0,
        "events": [],
    }

    if dry_run:
        queue_events = fetch_pending_queue_event_snapshots(summary["limit"], source_code=summary["source_code"])
        summary["fetched"] = len(queue_events)
        for queue_event in queue_events:
            try:
                payload = _deserialize_queue_json(queue_event.get("payload_json"), field_name="payload_json")
                old_payload = _deserialize_queue_json(
                    queue_event.get("old_payload_json"),
                    field_name="old_payload_json",
                    allow_null=True,
                )
                event_source_code = str(queue_event.get("source_code") or "").strip()
                payload = _enrich_payload_for_source(event_source_code, payload)
                old_payload = _enrich_payload_for_source(event_source_code, old_payload)
                event_context = {
                    **queue_event,
                    "operation_type": str(queue_event.get("operation_type") or "").strip().lower(),
                    "payload": payload,
                    "old_payload": old_payload,
                }
                rules = find_matching_rules(event_context)
                rule_previews = [
                    _preview_rule_for_dry_run(
                        rule,
                        payload,
                        old_payload=old_payload,
                        queue_event=event_context,
                    )
                    for rule in rules
                ]
                preview_errors = sum(
                    1
                    for rule_preview in rule_previews
                    for action_preview in rule_preview.get("actions", [])
                    if action_preview.get("status") == AutomationActionLogStatus.ERROR
                )
                summary["rule_runs"] += len(rules)
                summary["error"] += preview_errors
                summary["events"].append(
                    {
                        "queue_id": int(queue_event["id"]),
                        "status": "dry-run",
                        "candidate_rule_codes": [rule.code for rule in rules],
                        "rule_previews": rule_previews,
                        "message": (
                            f"Dry-run: regole candidate={len(rules)}, safety/errori azione={preview_errors}."
                        ),
                    }
                )
            except Exception as exc:
                summary["error"] += 1
                summary["events"].append(
                    {
                        "queue_id": int(queue_event["id"]),
                        "status": QueueEventStatus.ERROR,
                        "message": _normalize_queue_error_message(exc),
                    }
                )
        return summary

    queue_events = fetch_pending_queue_events(summary["limit"], source_code=summary["source_code"])
    summary["fetched"] = len(queue_events)
    for queue_event in queue_events:
        try:
            event_result = process_queue_event(queue_event)
        except Exception as exc:
            queue_id = int(queue_event["id"])
            logger.exception("Errore batch processing queue event %s", queue_id)
            try:
                mark_queue_error(queue_id, exc)
            except Exception:
                logger.exception("Errore durante mark_queue_error per queue event %s", queue_id)
            event_result = {
                "queue_id": queue_id,
                "status": QueueEventStatus.ERROR,
                "rule_runs": 0,
                "message": _normalize_queue_error_message(exc),
            }

        summary["events"].append(event_result)
        summary["rule_runs"] += int(event_result.get("rule_runs") or 0)
        if event_result.get("status") == QueueEventStatus.DONE:
            summary["done"] += 1
        elif event_result.get("status") == QueueEventStatus.ERROR:
            summary["error"] += 1

    return summary


def _schedule_queue_event(
    source_code: str,
    source_table: str,
    source_pk: str | None,
    operation_type: str,
    event_code: str | None,
    payload_json: str,
    execute_after,
) -> None:
    """Inserisce un nuovo evento in coda con una data di esecuzione futura."""
    from django.db import connections
    vendor = str(connections["default"].vendor or "").lower()
    if not _queue_table_has_column("execute_after"):
        raise RuntimeError(
            "La tabella dbo.automation_event_queue non espone la colonna 'execute_after'. "
            "Riallinea lo schema rieseguendo sql/automation_event_queue.sql."
        )
    execute_after_str = execute_after.strftime("%Y-%m-%d %H:%M:%S")
    if "microsoft" in vendor or "mssql" in vendor:
        sql = """
            INSERT INTO dbo.automation_event_queue
                (source_code, source_table, source_pk, operation_type, event_code,
                 payload_json, old_payload_json, status, retry_count, created_at, execute_after)
            VALUES (?, ?, ?, ?, ?, ?, NULL, 'pending', 0, SYSUTCDATETIME(), ?)
        """
    else:
        sql = """
            INSERT INTO automation_event_queue
                (source_code, source_table, source_pk, operation_type, event_code,
                 payload_json, old_payload_json, status, retry_count, created_at, execute_after)
            VALUES (?, ?, ?, ?, ?, ?, NULL, 'pending', 0, datetime('now'), ?)
        """
    with connections["default"].cursor() as cursor:
        cursor.execute(sql, [source_code, source_table, source_pk, operation_type,
                             event_code, payload_json, execute_after_str])


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Helpers per azioni di controllo flusso (branch, do_until, for_each, approval)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _check_simple_condition(
    field_name: str,
    operator: str,
    expected_value: str,
    value_type: str,
    payload: dict[str, Any],
    old_payload: dict[str, Any] | None = None,
) -> bool:
    """Valuta una condizione semplice senza richiedere un modello AutomationCondition."""
    from .models import AutomationConditionOperator, AutomationConditionValueType
    condition = SimpleNamespace(
        field_name=field_name,
        operator=operator or AutomationConditionOperator.EQUALS,
        expected_value=expected_value or "",
        value_type=value_type or AutomationConditionValueType.STRING,
        compare_with_old=False,
        is_enabled=True,
    )
    try:
        return evaluate_condition(condition, payload, old_payload=old_payload)
    except Exception:
        return False


def _execute_inline_action(
    child_config: dict[str, Any],
    payload: Any,
    old_payload: Any = None,
    run_log: Any = None,
    parent_action: Any = None,
) -> dict[str, Any]:
    """
    Esegue un'azione inline definita come dizionario (embedded in config_json).
    Crea un oggetto SimpleNamespace compatibile con execute_action.
    """
    if not isinstance(child_config, dict):
        return {"status": AutomationActionLogStatus.SKIPPED, "result_message": "child_config non valido."}
    action_type = str(child_config.get("action_type") or child_config.get("type") or "").strip()
    if not action_type:
        return {"status": AutomationActionLogStatus.SKIPPED, "result_message": "action_type mancante nell'azione inline."}

    # Le azioni embedded nei pacchetti/rami inline possono dichiarare i parametri in due modi:
    # (a) annidati sotto `config_json` (schema runtime), oppure (b) come chiavi top-level
    # sul dict dell'azione (schema usato dai pacchetti import, es. {"action_type":"send_email",
    # "to":..., "subject_template":...}). execute_action legge tutto da config_json, quindi
    # se config_json e' assente/vuoto promuovo le chiavi top-level (escludendo i meta) a config,
    # altrimenti l'azione inline girerebbe con configurazione vuota.
    explicit_config = child_config.get("config_json")
    if isinstance(explicit_config, dict) and explicit_config:
        inline_config = dict(explicit_config)
    else:
        _meta_keys = {"action_type", "type", "description", "name", "is_enabled", "enabled", "order", "config_json", "config"}
        inline_config = {key: value for key, value in child_config.items() if key not in _meta_keys}

    inline_action = SimpleNamespace(
        id=None,
        pk=None,
        action_type=action_type,
        config_json=inline_config,
        description=str(child_config.get("description") or ""),
        is_enabled=True,
        order=0,
        rule=getattr(parent_action, "rule", None),
    )
    return execute_action(inline_action, payload, old_payload=old_payload, run_log=run_log)


def _query_source_for_each(
    source_code: str,
    filter_field: str | None,
    filter_value: Any,
    max_items: int = 50,
) -> list[dict[str, Any]]:
    """
    Interroga una sorgente registrata per restituire i record da iterare in for_each.
    Valida table_name e filter_field contro il source registry.
    """
    from .source_registry import get_source_definition, get_source_fields

    source = get_source_definition(source_code)
    if not source:
        raise ValueError(f"Sorgente '{source_code}' non trovata nel source registry.")
    table_name = str(source.get("table_name") or "").strip()
    if not table_name:
        raise ValueError(f"Sorgente '{source_code}' non ha una tabella DB definita (non supportata per for_each).")

    valid_fields = {f["name"] for f in get_source_fields(source_code)}

    if filter_field and filter_field not in valid_fields:
        raise ValueError(f"Il campo filtro '{filter_field}' non Ã¨ esposto dalla sorgente '{source_code}'.")

    max_items = max(1, min(int(max_items or 50), 500))

    from django.db import connections
    vendor = str(connections["default"].vendor or "").lower()
    is_mssql = "microsoft" in vendor or "mssql" in vendor

    try:
        with connections["default"].cursor() as cursor:
            if filter_field and filter_value is not None:
                if is_mssql:
                    sql = f"SELECT TOP {max_items} * FROM {table_name} WHERE {filter_field} = ?"
                    cursor.execute(sql, [filter_value])
                else:
                    sql = f"SELECT * FROM {table_name} WHERE {filter_field} = ? LIMIT {max_items}"
                    cursor.execute(sql, [filter_value])
            else:
                if is_mssql:
                    sql = f"SELECT TOP {max_items} * FROM {table_name}"
                    cursor.execute(sql)
                else:
                    sql = f"SELECT * FROM {table_name} LIMIT {max_items}"
                    cursor.execute(sql)
            return _cursor_fetch_dicts(cursor)
    except Exception as exc:
        raise ValueError(f"Errore durante la query for_each su '{table_name}': {exc}") from exc


def _count_source(
    source_code: str,
    filter_field: str | None,
    filter_value: Any,
    *,
    window_field: str | None = None,
    window_days: int | None = None,
) -> int:
    """
    Conta i record di una sorgente registrata filtrando per un campo e, opzionalmente,
    su una finestra temporale (window_field >= oggi - window_days).
    Valida table_name, filter_field e window_field contro il source registry.
    Usato dall'azione count_branch per esprimere soglie tipo "N eventi in M giorni".
    """
    from .source_registry import get_source_definition, get_source_fields

    source = get_source_definition(source_code)
    if not source:
        raise ValueError(f"Sorgente '{source_code}' non trovata nel source registry.")
    table_name = str(source.get("table_name") or "").strip()
    if not table_name:
        raise ValueError(f"Sorgente '{source_code}' non ha una tabella DB definita (count non supportato).")

    valid_fields = {f["name"] for f in get_source_fields(source_code)}
    if filter_field and filter_field not in valid_fields:
        raise ValueError(f"Il campo filtro '{filter_field}' non e' esposto dalla sorgente '{source_code}'.")
    if window_field and window_field not in valid_fields:
        raise ValueError(f"Il campo finestra '{window_field}' non e' esposto dalla sorgente '{source_code}'.")

    where_parts: list[str] = []
    params: list[Any] = []
    if filter_field and filter_value is not None:
        where_parts.append(f"{filter_field} = ?")
        params.append(filter_value)
    if window_field and window_days:
        threshold = (date.today() - timedelta(days=int(window_days))).isoformat()
        where_parts.append(f"{window_field} >= ?")
        params.append(threshold)

    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
    sql = f"SELECT COUNT(*) FROM {table_name}{where_sql}"

    from django.db import connections
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    except Exception as exc:
        raise ValueError(f"Errore durante il conteggio su '{table_name}': {exc}") from exc


def _insert_loop_reschedule_event(
    rule: Any,
    payload: dict[str, Any],
    delay_value: int,
    delay_unit: str,
) -> None:
    """
    Inserisce un nuovo evento in coda per rischedulare un'iterazione do_until.
    Il payload include il contatore _loop_iteration aggiornato.
    """
    _unit_map = {"minutes": timedelta(minutes=1), "hours": timedelta(hours=1), "days": timedelta(days=1)}
    unit_delta = _unit_map.get(delay_unit, timedelta(hours=1))
    execute_after = timezone.now() + unit_delta * int(delay_value or 1)

    source_code = str(getattr(rule, "source_code", "") or "")
    operation_type = str(getattr(rule, "operation_type", "update") or "update")
    source = get_source_definition(source_code) if source_code else None
    source_table = str((source or {}).get("table_name") or source_code)
    pk_field = str((source or {}).get("pk_field") or "id")
    source_pk = str(payload.get(pk_field) or "0")
    event_code = f"do_until_loop_rule_{getattr(rule, 'pk', 0)}"

    _schedule_queue_event(
        source_code=source_code,
        source_table=source_table,
        source_pk=source_pk,
        operation_type=operation_type,
        event_code=event_code,
        payload_json=json.dumps(payload, ensure_ascii=False, default=str),
        execute_after=execute_after,
    )


def execute_action(
    action: AutomationAction,
    payload: Any,
    old_payload: Any = None,
    run_log: AutomationRunLog | None = None,
    queue_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = action.config_json if isinstance(action.config_json, dict) else {}
    payload_context = payload if isinstance(payload, dict) else {}
    source_code = (
        str((queue_event or {}).get("source_code") or "").strip()
        or str(getattr(run_log, "source_code", "") or "").strip()
        or str(getattr(getattr(action, "rule", None), "source_code", "") or "").strip()
    )
    source_definition = get_source_definition(source_code)

    try:
        should_run, run_if_description = _resolve_action_run_if(config, payload_context, old_payload=old_payload)
        if not should_run:
            result_message = (
                f"Action saltata: branch non soddisfatto ({run_if_description})."
                if run_if_description else
                "Action saltata: branch non soddisfatto."
            )
            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SKIPPED,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SKIPPED, "result_message": result_message, "action_log": action_log}

        if action.action_type == AutomationActionType.SEND_EMAIL:
            to = _parse_email_recipients(config.get("to"), payload_context, "to")
            cc = _parse_email_recipients(config.get("cc"), payload_context, "cc")
            bcc = _parse_email_recipients(config.get("bcc"), payload_context, "bcc")
            reply_to = _parse_email_recipients(config.get("reply_to"), payload_context, "reply_to")

            # Filtra destinatari che hanno disabilitato questo tipo di notifica.
            # notifica_tipo Ã¨ opzionale: se assente, nessun filtro viene applicato.
            notifica_tipo = (config.get("notifica_tipo") or "").strip()
            if notifica_tipo:
                to, cc, bcc = _filter_recipients_by_notifica_pref(to, cc, bcc, notifica_tipo)

            if not any([to, cc, bcc]):
                # Tutti i destinatari hanno disabilitato la notifica: skip silenzioso.
                skipped_msg = (
                    f"Email skippata: tutti i destinatari hanno disabilitato "
                    f"le notifiche di tipo '{notifica_tipo}'."
                    if notifica_tipo else
                    "send_email richiede almeno un destinatario in to, cc o bcc."
                )
                if notifica_tipo:
                    action_log = _create_action_log(
                        run_log=run_log, action=action,
                        status=AutomationActionLogStatus.SUCCESS,
                        result_message=skipped_msg,
                    )
                    return {"status": AutomationActionLogStatus.SUCCESS, "result_message": skipped_msg, "action_log": action_log}
                raise ValueError(skipped_msg)

            from_email = _validate_sender_email(config.get("from_email"), payload_context)
            subject = render_template_string(config.get("subject_template"), payload_context).strip()
            body_text = render_template_string(config.get("body_text_template"), payload_context)
            body_html = render_template_string(config.get("body_html_template"), payload_context)
            fail_silently = bool(config.get("fail_silently"))

            # Wrappa nel layout grafico standard.
            # - Se body_html è già un documento completo (<!DOCTYPE / <html): usato direttamente.
            # - Se body_html è un frammento: wrappato nel base template.
            # - Se body_html è vuoto ma body_text esiste: il testo viene convertito in HTML e wrappato.
            from django.template.loader import render_to_string
            from django.utils.safestring import mark_safe
            _base_ctx = {
                "email_type": (config.get("email_type") or "Automazioni"),
                "badge": (config.get("badge") or ""),
                "section_label": (config.get("section_label") or ""),
                "title": render_template_string(config.get("title_template"), payload_context),
            }
            if body_html and not body_html.lstrip().lower().startswith(("<!doctype", "<html")):
                body_html = render_to_string("core/email/base_email.html", {
                    **_base_ctx,
                    "body_content": mark_safe(body_html),
                })
            elif not body_html and body_text:
                # Nessun HTML configurato: genera da testo plain (escape + newline → <br>)
                import html as _html
                text_as_html = _html.escape(body_text).replace("\n", "<br>")
                body_html = render_to_string("core/email/base_email.html", {
                    **_base_ctx,
                    "body_content": mark_safe(f'<p style="color:#475569;font-size:15px;line-height:1.7;">{text_as_html}</p>'),
                })

            message = EmailMultiAlternatives(
                subject=subject,
                body=body_text,
                from_email=from_email,
                to=to,
                cc=cc,
                bcc=bcc,
                reply_to=reply_to,
            )
            if body_html:
                message.attach_alternative(body_html, "text/html")

            try:
                sent_count = message.send(fail_silently=fail_silently)
            except Exception as smtp_exc:
                import smtplib
                exc_type = type(smtp_exc).__name__
                if isinstance(smtp_exc, smtplib.SMTPServerDisconnected):
                    from django.conf import settings as _s
                    raise ValueError(
                        f"SMTP: il server ha chiuso la connessione prima del completamento "
                        f"({exc_type}: {smtp_exc}). "
                        f"Verificare che SMTP AUTH sia abilitato per la casella '{getattr(_s, 'EMAIL_HOST_USER', '?')}' "
                        f"su {getattr(_s, 'EMAIL_HOST', '?')}:{getattr(_s, 'EMAIL_PORT', '?')}, "
                        f"che la porta sia raggiungibile dal server e che le credenziali siano corrette."
                    ) from smtp_exc
                elif isinstance(smtp_exc, smtplib.SMTPAuthenticationError):
                    raise ValueError(
                        f"SMTP: autenticazione fallita ({exc_type}: {smtp_exc}). "
                        f"Verificare utente e password SMTP."
                    ) from smtp_exc
                raise
            if sent_count < 1:
                raise ValueError("Il backend email non ha confermato l'invio del messaggio.")

            recipients = ", ".join(to + cc + bcc)
            result_message = f"Email inviata a [{recipients}] con subject='{subject[:120]}'."
            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_message, "action_log": action_log}

        if action.action_type == AutomationActionType.SEND_APPROVAL:
            delivery_mode = _resolve_approval_delivery_mode(config)
            subject = render_template_string(
                config.get("subject_template") or "Richiesta di approvazione", payload_context
            ).strip() or "Richiesta di approvazione"
            message_body = render_template_string(config.get("message_template") or "", payload_context)
            expiry_days = max(1, int(config.get("expiry_days") or 7))
            approved_actions = list(config.get("approved_actions") or [])
            rejected_actions = list(config.get("rejected_actions") or [])
            approve_label = str(config.get("approve_label") or "Approva")
            reject_label = str(config.get("reject_label") or "Rifiuta")

            email_delivery_modes = {
                ApprovalDeliveryMode.EMAIL,
                ApprovalDeliveryMode.TEAMS_WEBHOOK_LEGACY,
                ApprovalDeliveryMode.EMAIL_AND_TEAMS_CHAT_FLOW,
            }
            flow_delivery_modes = {
                ApprovalDeliveryMode.TEAMS_CHAT_FLOW,
                ApprovalDeliveryMode.EMAIL_AND_TEAMS_CHAT_FLOW,
            }

            email_approver_emails: list[str] = []
            if delivery_mode in email_delivery_modes:
                email_approver_emails = _parse_email_recipients(config.get("to_template"), payload_context, "to_template")
                if not email_approver_emails:
                    raise ValueError("send_approval: nessun approvatore email specificato.")

            flow_recipient_email = ""
            if delivery_mode in flow_delivery_modes:
                flow_recipient_email = _render_required_email(
                    config.get("teams_recipient_email_template"),
                    payload_context,
                    field_label="recipient_email",
                )

            approver_emails = _dedupe_emails(email_approver_emails + ([flow_recipient_email] if flow_recipient_email else []))
            if not approver_emails:
                raise ValueError("send_approval: nessun approvatore risolto per il recapito richiesto.")

            # ── Risolvi template email (opzionale, non bloccante) ─────────────
            email_template = _resolve_approval_email_template(config)

            approval = _create_approval_record(
                action=action,
                run_log=run_log,
                approver_emails=approver_emails,
                subject=subject,
                message_body=message_body,
                expiry_days=expiry_days,
                payload_context=payload_context,
                old_payload=old_payload,
                approved_actions=approved_actions,
                rejected_actions=rejected_actions,
            )
            approve_url, reject_url = _build_approval_links(approval)

            # ── Se presente un template, rende il corpo HTML/text e opzionalmente
            #    sovrascrive subject se non è stato valorizzato esplicitamente
            html_body_override: str | None = None
            text_body_override: str | None = None
            if email_template is not None:
                try:
                    from .approval_email_templates import build_template_context, render_approval_email
                    tpl_context = build_template_context(
                        payload_context,
                        approval=approval,
                        approve_url=approve_url,
                        reject_url=reject_url,
                    )
                    # Aggiunge expires_at nel context per il rendering del template
                    if approval.expires_at:
                        tpl_context["expires_at"] = timezone.localtime(approval.expires_at).strftime("%d-%m-%Y %H:%M")
                    rendered = render_approval_email(
                        email_template,
                        tpl_context,
                        approve_url=approve_url,
                        reject_url=reject_url,
                    )
                    # Usa il subject del template solo se non è stato esplicitamente
                    # configurato nella regola (config ha subject_template vuoto/default)
                    raw_rule_subject = str(config.get("subject_template") or "").strip()
                    if not raw_rule_subject or raw_rule_subject == "Richiesta di approvazione":
                        subject = rendered["subject"] or subject
                    html_body_override = rendered["html_body"]
                    text_body_override = rendered["text_body"]
                except Exception:
                    logger.warning(
                        "send_approval: errore rendering ApprovalEmailTemplate id=%s. "
                        "Fallback al comportamento standard.",
                        getattr(email_template, "pk", "?"),
                        exc_info=True,
                    )
                    html_body_override = None
                    text_body_override = None

            result_message_parts = [
                f"Richiesta approvazione creata per {', '.join(approver_emails)}.",
                f"Token: {approval.token}.",
                f"Scadenza: {expiry_days} giorni.",
            ]
            if email_template is not None:
                result_message_parts.append(f"Template email: {email_template.name}.")
            delivery_success = False
            strict_teams_flow = bool(config.get("strict_teams_flow"))

            try:
                if delivery_mode in email_delivery_modes:
                    result_message_parts.append(
                        _send_approval_email(
                            approver_emails=email_approver_emails,
                            subject=subject,
                            message_body=message_body,
                            approve_url=approve_url,
                            reject_url=reject_url,
                            approve_label=approve_label,
                            reject_label=reject_label,
                            expires_at=approval.expires_at,
                            html_body_override=html_body_override,
                            text_body_override=text_body_override,
                        )
                    )
                    delivery_success = True

                if delivery_mode == ApprovalDeliveryMode.TEAMS_WEBHOOK_LEGACY:
                    try:
                        result_message_parts.append(
                            _send_approval_teams_webhook_legacy(
                                config=config,
                                payload_context=payload_context,
                                subject=subject,
                                message_body=message_body,
                                approve_url=approve_url,
                                reject_url=reject_url,
                                approve_label=approve_label,
                                reject_label=reject_label,
                            )
                        )
                    except Exception as teams_legacy_exc:
                        logger.warning("send_approval: Teams webhook legacy error: %s", teams_legacy_exc)
                        result_message_parts.append(f"Teams webhook legacy non inviato ({teams_legacy_exc}).")

                if delivery_mode in flow_delivery_modes:
                    try:
                        flow_result = _send_approval_teams_chat_flow(
                            config=config,
                            approval=approval,
                            payload_context=payload_context,
                            subject=subject,
                            message_body=message_body,
                            approve_url=approve_url,
                            reject_url=reject_url,
                        )
                        result_message_parts.append(flow_result["result_message"])
                        delivery_success = True
                    except Exception as teams_flow_exc:
                        logger.warning("send_approval: Teams chat flow error: %s", teams_flow_exc)
                        if delivery_mode == ApprovalDeliveryMode.TEAMS_CHAT_FLOW or strict_teams_flow:
                            raise
                        result_message_parts.append(f"Teams chat flow non inviato ({teams_flow_exc}).")
            except Exception:
                if not delivery_success:
                    approval.delete()
                raise

            if not delivery_success:
                approval.delete()
                raise ValueError("Nessun recapito approvazione riuscito.")

            result_message = " ".join(part for part in result_message_parts if part)
            if run_log is not None:
                run_log.status = AutomationRunLogStatus.WAITING_APPROVAL
                run_log.result_message = result_message
                run_log.save(update_fields=["status", "result_message"])

            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_message, "action_log": action_log}

        if action.action_type == AutomationActionType.WRITE_LOG:
            message = render_template_string(config.get("message_template"), payload_context)
            result_message = message or "write_log eseguita senza message_template valorizzato."
            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_message, "action_log": action_log}

        if action.action_type == AutomationActionType.UPDATE_DASHBOARD_METRIC:
            metric_code = str(config.get("metric_code") or "").strip()
            operation = str(config.get("operation") or "").strip().lower()
            rendered_value = render_template_string(
                config.get("value_template"),
                payload_context,
            ).strip()

            if not metric_code:
                raise ValueError("update_dashboard_metric richiede metric_code.")
            if operation not in {"set", "increment", "decrement"}:
                raise ValueError("update_dashboard_metric richiede operation valida: set, increment o decrement.")
            if not rendered_value:
                raise ValueError("update_dashboard_metric richiede value_template valorizzato.")

            try:
                delta = Decimal(rendered_value)
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValueError("value_template non produce un numero decimale valido.") from exc

            metric, created = DashboardMetricValue.objects.get_or_create(
                metric_code=metric_code,
                defaults={
                    "label": metric_code.replace("_", " ").strip().title() or metric_code,
                    "current_value": Decimal("0"),
                },
            )

            if operation == "set":
                metric.current_value = delta
            elif operation == "increment":
                metric.current_value = Decimal(metric.current_value) + delta
            else:
                metric.current_value = Decimal(metric.current_value) - delta
            metric.save()

            prefix = "creata" if created else "aggiornata"
            result_message = (
                f"Dashboard metric {metric.metric_code} {prefix} con operation={operation} e value={delta}."
            )
            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_message, "action_log": action_log}

        if action.action_type == AutomationActionType.INSERT_RECORD:
            target_table = str(config.get("target_table") or "").strip()
            field_mappings = config.get("field_mappings")
            if not isinstance(field_mappings, dict) or not field_mappings:
                raise ValueError("insert_record richiede field_mappings non vuoto.")

            rendered_fields = {
                str(field_name).strip(): _render_action_value(raw_value, payload_context)
                for field_name, raw_value in field_mappings.items()
            }
            result = execute_safe_insert(target_table, rendered_fields)
            columns = ", ".join(rendered_fields.keys())
            result_message = (
                f"Insert eseguito su {target_table} con colonne [{columns}]"
                f" e righe inserite={result['rowcount']}."
            )
            if result.get("inserted_pk") is not None:
                result_message = f"{result_message} PK={result['inserted_pk']}."
            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_message, "action_log": action_log}

        if action.action_type == AutomationActionType.UPDATE_RECORD:
            target_table = str(config.get("target_table") or "").strip()
            where_field = str(config.get("where_field") or "").strip()
            where_value = _render_action_value(config.get("where_value_template"), payload_context)
            if isinstance(where_value, str) and _PLACEHOLDER_PATTERN.search(where_value):
                raise ValueError("where_value_template non produce un valore valido.")
            update_fields = config.get("update_fields")
            if not isinstance(update_fields, dict) or not update_fields:
                raise ValueError("update_record richiede update_fields non vuoto.")

            rendered_update_fields = {
                str(field_name).strip(): _render_action_value(raw_value, payload_context)
                for field_name, raw_value in update_fields.items()
            }
            result = execute_safe_update(target_table, rendered_update_fields, where_field, where_value)
            columns = ", ".join(rendered_update_fields.keys())
            result_message = (
                f"Update eseguito su {target_table} usando {where_field}"
                f" e colonne [{columns}]. Record aggiornati={result['rowcount']}."
            )
            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_message, "action_log": action_log}

        if action.action_type == AutomationActionType.UPDATE_TRIGGER_RECORD:
            update_fields = config.get("update_fields")
            result = _execute_update_trigger_record(
                source_code=source_code,
                payload_context=payload_context,
                queue_event=queue_event,
                update_fields=update_fields if isinstance(update_fields, dict) else {},
            )
            columns = ", ".join(result.get("columns") or [])
            result_message = (
                f"Record triggerante {source_code}#{result['source_pk']} aggiornato"
                f" con colonne [{columns}]. Record aggiornati={result['rowcount']}."
            )
            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_message, "action_log": action_log}

        if action.action_type == AutomationActionType.SPLIT_ASSENZA_GIORNALIERA:
            result = execute_split_assenza_giornaliera(
                config=config,
                payload_context=payload_context,
                source_code=source_code,
            )
            result_message = (
                "Split assenza giornaliera completato: "
                f"pianificati={result['planned']}, inseriti={result['inserted']}, "
                f"saltati={result['skipped']} (sorgente giorni={result['day_source']})."
            )
            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_message, "action_log": action_log}

        if action.action_type == AutomationActionType.DELAY_SCHEDULE:
            mode = str(config.get("mode") or "").strip().lower() or "relative"
            now = timezone.now()
            if mode == "until":
                execute_after = _render_delay_until(config.get("until_template"), payload_context)
                if execute_after <= now:
                    raise ValueError("delay_schedule richiede una data/ora futura.")
            else:
                unit = str(config.get("unit") or "").strip().lower() or "days"
                raw_value = config.get("value_template", config.get("giorni", 1))
                rendered_value = str(_render_action_value(raw_value, payload_context) or "").strip()
                if not rendered_value:
                    raise ValueError("delay_schedule richiede value_template valorizzato.")
                try:
                    amount = Decimal(rendered_value)
                except (InvalidOperation, TypeError, ValueError) as exc:
                    raise ValueError("delay_schedule richiede un valore numerico valido.") from exc
                if amount <= 0:
                    raise ValueError("delay_schedule richiede un valore positivo.")
                if unit == "minutes":
                    execute_after = now + timedelta(minutes=float(amount))
                elif unit == "hours":
                    execute_after = now + timedelta(hours=float(amount))
                else:
                    execute_after = now + timedelta(days=float(amount))

            event = queue_event or {}
            import json as _json
            payload_json_str = event.get("payload_json") or _json.dumps(payload if isinstance(payload, dict) else {})
            if not isinstance(payload_json_str, str):
                payload_json_str = _json.dumps(payload_json_str, ensure_ascii=False, default=str)
            source_pk = _resolve_source_pk_for_action(
                source_definition=source_definition,
                payload=payload_context,
                queue_event=queue_event,
            )
            event_code = event.get("event_code")
            if not event_code and getattr(action, "rule_id", None):
                event_code = _build_trigger_event_label(action.rule)
            _schedule_queue_event(
                source_code=source_code,
                source_table=event.get("source_table", "") or str((source_definition or {}).get("table_name") or ""),
                source_pk=source_pk,
                operation_type=event.get("operation_type", "") or str(getattr(run_log, "operation_type", "") or "") or str(getattr(getattr(action, "rule", None), "operation_type", "") or ""),
                event_code=event_code,
                payload_json=payload_json_str,
                execute_after=execute_after,
            )
            result_msg = f"Evento schedulato per {execute_after.isoformat()}."
            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_msg,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_msg, "action_log": action_log}

        if action.action_type == AutomationActionType.HTTP_REQUEST:
            method, url, headers, body, timeout_seconds, expected_statuses = _http_request_payload(config, payload_context)
            if not method:
                raise ValueError("http_request richiede method.")
            if not url:
                raise ValueError("http_request richiede url_template.")
            if _PLACEHOLDER_PATTERN.search(url):
                unresolved = _PLACEHOLDER_PATTERN.findall(url)
                raise ValueError(f"url_template non produce un URL valido. Placeholder non risolti: {unresolved}. URL parziale: {url!r}")

            response = _perform_http_request(
                method=method,
                url=url,
                headers=headers,
                body=body,
                timeout_seconds=timeout_seconds,
            )
            if expected_statuses:
                ok = response.status_code in expected_statuses
            else:
                ok = bool(response.ok)
            if not ok:
                raise ValueError(f"HTTP {response.status_code} ricevuto da {url}.")

            body_preview = str(getattr(response, "text", "") or "").replace("\r", " ").replace("\n", " ").strip()
            if len(body_preview) > 140:
                body_preview = body_preview[:137].rstrip() + "..."
            result_message = f"HTTP {method} {url} -> {response.status_code}."
            if body_preview:
                result_message = f"{result_message} Body: {body_preview}"
            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_message, "action_log": action_log}

        if action.action_type == AutomationActionType.SEND_ANOMALIE_MAIL_ACTION:
            from anomalie.mail_action_service import send_anomalie_action_email

            to_raw = str(_render_action_value(config.get("to"), payload_context) or "").strip()
            if not to_raw:
                raise ValueError("send_anomalie_mail_action richiede 'to' (email destinatario).")
            recipient_email = to_raw

            recipient_display = str(_render_action_value(config.get("recipient_display"), payload_context) or "").strip()
            if not recipient_display:
                recipient_display = recipient_email

            pk_field = str((source_definition or {}).get("pk_field") or "id")
            anomalia_id = payload_context.get(pk_field)
            if anomalia_id is None:
                raise ValueError("send_anomalie_mail_action: ID anomalia non trovato nel payload.")

            op_id = str(payload_context.get("ex_op_nominativo") or "").strip()
            op_nominativo = op_id

            mail_action = str(_render_action_value(config.get("action"), payload_context) or "visualizza").strip()
            expires_hours = max(1, int(config.get("expires_hours") or 48))
            source_automation_label = str(config.get("source_automation") or "").strip()

            legacy_user_id_raw = payload_context.get("created_by")
            recipient_legacy_user_id = int(legacy_user_id_raw) if legacy_user_id_raw is not None else None

            anomalie_rows = [dict(payload_context, id=anomalia_id)]

            token_obj = send_anomalie_action_email(
                recipient_email=recipient_email,
                recipient_display=recipient_display,
                recipient_legacy_user_id=recipient_legacy_user_id,
                op_id=op_id,
                op_nominativo=op_nominativo,
                anomalie_rows=anomalie_rows,
                action=mail_action,
                expires_hours=expires_hours,
                source_automation=source_automation_label,
            )

            result_message = (
                f"Mail-action anomalie inviata a {recipient_email} "
                f"(token={str(token_obj.token)[:8]}…, op={op_id}, action={mail_action})."
            )
            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_message, "action_log": action_log}

        if action.action_type == AutomationActionType.SEND_ANOMALIE_MAIL_ACTION_BY_OP:
            from anomalie.mail_action_service import send_anomalie_action_email

            pk_field = str((source_definition or {}).get("pk_field") or "id")
            anomalia_id = payload_context.get(pk_field)
            if anomalia_id is None:
                raise ValueError("send_anomalie_mail_action_by_op: ID anomalia non trovato nel payload.")

            op_title = str(payload_context.get("ex_op_nominativo") or "").strip()
            if not op_title:
                raise ValueError("send_anomalie_mail_action_by_op: ex_op_nominativo non presente nel payload.")

            recipients = _resolve_op_recipients(op_title)
            if not recipients:
                raise ValueError(
                    f"send_anomalie_mail_action_by_op: impossibile risolvere CC/CAR per OP='{op_title}'."
                )

            # Routing: benestare_field indica un campo bool del payload
            # true → to=CAR, cc=CC; false/assente → to=CC, cc=CAR
            benestare_field = str(config.get("benestare_field") or "").strip()
            benestare = False
            if benestare_field:
                raw_val = payload_context.get(benestare_field)
                benestare = bool(raw_val) if raw_val is not None else False

            cc_rec = next((r for r in recipients if r["role"] == "CC"), None)
            car_rec = next((r for r in recipients if r["role"] == "CAR"), None)

            if benestare:
                primary = car_rec or cc_rec
                secondary = cc_rec if primary is car_rec else None
            else:
                primary = cc_rec or car_rec
                secondary = car_rec if primary is cc_rec else None

            if not primary:
                raise ValueError("send_anomalie_mail_action_by_op: nessun destinatario principale risolto.")

            mail_action = str(_render_action_value(config.get("action"), payload_context) or "prendi_in_carico").strip()
            expires_hours = max(1, int(config.get("expires_hours") or 48))
            source_automation_label = str(config.get("source_automation") or "").strip()
            op_id = str(payload_context.get("ex_op_nominativo") or "").strip()

            # Carica tutte le anomalie aperte dell'OP dal DB per popolare la mail
            anomalie_rows = _fetch_anomalie_by_op(op_id) or [dict(payload_context, id=anomalia_id)]

            cc_emails = [secondary["email"]] if secondary else []

            token_obj = send_anomalie_action_email(
                recipient_email=primary["email"],
                recipient_display=primary["display"],
                op_id=op_id,
                op_nominativo=op_id,
                anomalie_rows=anomalie_rows,
                action=mail_action,
                expires_hours=expires_hours,
                source_automation=source_automation_label,
            )

            # Invia copia CC se presente
            if cc_emails:
                from django.core.mail import EmailMultiAlternatives
                from anomalie.mail_action_service import build_anomalie_action_email
                from django.utils import timezone
                from datetime import timedelta
                expires_at = timezone.now() + timedelta(hours=expires_hours)
                subj, body_text, body_html = build_anomalie_action_email(
                    recipient_email=primary["email"],
                    recipient_display=primary["display"],
                    op_id=op_id,
                    op_nominativo=op_id,
                    anomalie_rows=anomalie_rows,
                    action=mail_action,
                    token_str=token_obj.token,
                    expires_at=token_obj.expires_at,
                )
                msg = EmailMultiAlternatives(
                    subject=subj,
                    body=body_text,
                    from_email=None,
                    to=[primary["email"]],
                    cc=cc_emails,
                )
                msg.attach_alternative(body_html, "text/html")
                msg.send(fail_silently=True)

            role_label = "CAR" if benestare else "CC"
            cc_label = secondary["email"] if secondary else "nessuno"
            result_message = (
                f"Mail-action OP inviata a {primary['email']} ({role_label}), "
                f"cc={cc_label}, op={op_id}, action={mail_action}, "
                f"token={str(token_obj.token)[:8]}…"
            )
            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_message, "action_log": action_log}

        if action.action_type == AutomationActionType.TEAMS_WEBHOOK:
            webhook_url = str(_render_action_value(config.get("webhook_url"), payload_context) or "").strip()
            if not webhook_url:
                raise ValueError("teams_webhook richiede webhook_url.")
            if _PLACEHOLDER_PATTERN.search(webhook_url):
                raise ValueError("webhook_url non produce un URL valido.")

            title = str(_render_action_value(config.get("title_template"), payload_context) or "").strip()
            summary = str(_render_action_value(config.get("summary_template"), payload_context) or "").strip()
            text = str(_render_action_value(config.get("text_template"), payload_context) or "").strip()
            facts_raw = _render_action_value(config.get("facts"), payload_context)
            facts = [
                {"name": str(key).strip(), "value": str(value).strip()}
                for key, value in (facts_raw.items() if isinstance(facts_raw, dict) else [])
                if str(key).strip()
            ]
            card_payload: dict[str, Any] = {
                "@type": "MessageCard",
                "@context": "http://schema.org/extensions",
                "summary": summary or title or "Automazione Portale",
                "themeColor": _normalize_teams_theme_color(_render_action_value(config.get("theme_color"), payload_context)),
            }
            if title:
                card_payload["title"] = title
            if text:
                card_payload["text"] = text
            if facts:
                card_payload["sections"] = [{"facts": facts}]

            response = _perform_http_request(
                method="POST",
                url=webhook_url,
                headers={"Content-Type": "application/json"},
                body=card_payload,
                timeout_seconds=20,
            )
            if not response.ok:
                raise ValueError(f"Teams webhook ha risposto con HTTP {response.status_code}.")

            result_message = f"Teams webhook inviato -> {response.status_code} ({title or summary or 'card'})."
            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_message, "action_log": action_log}

        # â”€â”€ DO_UNTIL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if action.action_type == AutomationActionType.DO_UNTIL:
            check_field = str(config.get("check_field") or "").strip()
            check_operator = str(config.get("check_operator") or "equals").strip()
            check_value = str(config.get("check_value") or "").strip()
            check_value_type = str(config.get("check_value_type") or "string").strip()
            max_iterations = max(1, int(config.get("max_iterations") or 10))
            current_iteration = int(payload_context.get("_loop_iteration") or 0)
            retry_delay_value = max(1, int(config.get("retry_delay_value") or 24))
            retry_delay_unit = str(config.get("retry_delay_unit") or "hours").strip()
            loop_actions = list(config.get("loop_actions") or [])
            on_success_actions = list(config.get("on_success_actions") or [])
            on_timeout_actions = list(config.get("on_timeout_actions") or [])

            condition_met = (
                _check_simple_condition(check_field, check_operator, check_value, check_value_type, payload_context)
                if check_field else False
            )

            if condition_met:
                # Condizione soddisfatta â†’ esegui azioni di successo
                for child_cfg in on_success_actions:
                    _execute_inline_action(child_cfg, payload_context, old_payload=old_payload, run_log=run_log, parent_action=action)
                result_message = f"Do Until: condizione soddisfatta all'iterazione {current_iteration}. Azioni success eseguite: {len(on_success_actions)}."
            elif current_iteration >= max_iterations:
                # Timeout â†’ esegui azioni di timeout
                for child_cfg in on_timeout_actions:
                    _execute_inline_action(child_cfg, payload_context, old_payload=old_payload, run_log=run_log, parent_action=action)
                result_message = (
                    f"Do Until: max iterazioni ({max_iterations}) raggiunto senza soddisfare la condizione. "
                    f"Azioni timeout eseguite: {len(on_timeout_actions)}."
                )
            else:
                # Esegui loop body e rischiedulamla
                for child_cfg in loop_actions:
                    _execute_inline_action(child_cfg, payload_context, old_payload=old_payload, run_log=run_log, parent_action=action)
                new_payload = {**payload_context, "_loop_iteration": current_iteration + 1}
                try:
                    rule_ref = getattr(action, "rule", None)
                    if rule_ref is not None:
                        _insert_loop_reschedule_event(rule_ref, new_payload, retry_delay_value, retry_delay_unit)
                        reschedule_note = f"Rischedulato tra {retry_delay_value} {retry_delay_unit}."
                    else:
                        reschedule_note = "Impossibile rischedulare: rule non disponibile."
                except Exception as _re:
                    reschedule_note = f"Rischedulazione fallita: {_re}."
                result_message = (
                    f"Do Until iter {current_iteration + 1}/{max_iterations}: condizione non soddisfatta. "
                    f"Azioni loop eseguite: {len(loop_actions)}. {reschedule_note}"
                )

            action_log = _create_action_log(
                run_log=run_log, action=action,
                status=AutomationActionLogStatus.SUCCESS,
                result_message=result_message,
            )
            return {"status": AutomationActionLogStatus.SUCCESS, "result_message": result_message, "action_log": action_log}

        # â”€â”€ FOR_EACH â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if action.action_type == AutomationActionType.FOR_EACH:
            foreach_source = str(config.get("source_code") or source_code or "").strip()
            filter_field = str(config.get("filter_field") or "").strip() or None
            filter_value_raw = config.get("filter_value_template")
            filter_value = render_template_string(str(filter_value_raw or ""), payload_context) if filter_value_raw else None
            # `max_iterations` e' l'alias usato dai pacchetti/validazione; `max_items` resta supportato.
            max_items = max(1, int(config.get("max_items") or config.get("max_iterations") or 50))
            # Le azioni del corpo loop sono accettate sia come `each_actions` (schema runtime
            # storico) sia come `loop_actions`/`actions` (schema usato dalla validazione import e
            # dai pacchetti). Allineo i due schemi per evitare loop vuoti silenziosi.
            each_actions = list(
                config.get("each_actions")
                or config.get("loop_actions")
                or config.get("actions")
                or []
            )

            if not foreach_source:
                raise ValueError("for_each: source_code non specificato.")

            records = _query_source_for_each(foreach_source, filter_field, filter_value, max_items)
            processed = 0
            errors = 0
            for record in records:
                record_payload = {**payload_context, **record}
                for child_cfg in each_actions:
                    res = _execute_inline_action(
                        child_cfg, record_payload, old_payload=old_payload, run_log=run_log, parent_action=action
                    )
                    if res.get("status") == AutomationActionLogStatus.ERROR:
                        errors += 1
                processed += 1

            result_message = (
                f"For Each: {processed} record da '{foreach_source}'. "
                f"Azioni per record: {len(each_actions)}. Errori totali: {errors}."
            )
            final_status = AutomationActionLogStatus.ERROR if errors else AutomationActionLogStatus.SUCCESS
            action_log = _create_action_log(
                run_log=run_log, action=action,
                status=final_status,
                result_message=result_message,
            )
            return {"status": final_status, "result_message": result_message, "action_log": action_log}

        # â”€â”€ BRANCH (If/Else) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if action.action_type == AutomationActionType.BRANCH:
            # Schema alternativo (usato dai pacchetti/validazione): la condizione e' un dict
            # `run_if` con field_name/operator/value/value_type, e i rami sono
            # then_actions/else_actions. Lo schema runtime storico usa invece
            # condition_field/condition_operator/... e if_true_actions/if_false_actions.
            # Supporto entrambi, dando priorita' ai valori espliciti dello schema storico.
            run_if = config.get("run_if") if isinstance(config.get("run_if"), dict) else {}
            condition_field = str(
                config.get("condition_field") or run_if.get("field_name") or ""
            ).strip()
            condition_operator = str(
                config.get("condition_operator") or run_if.get("operator") or "equals"
            ).strip()
            condition_value = str(
                config.get("condition_value")
                if config.get("condition_value") is not None
                else (run_if.get("value") if run_if.get("value") is not None else "")
            ).strip()
            condition_value_type = str(
                config.get("condition_value_type") or run_if.get("value_type") or "string"
            ).strip()
            compare_with_old = bool(config.get("compare_with_old") or run_if.get("compare_with_old"))
            if_true_actions = list(config.get("if_true_actions") or config.get("then_actions") or [])
            if_false_actions = list(config.get("if_false_actions") or config.get("else_actions") or [])

            condition_met = (
                _check_simple_condition(
                    condition_field, condition_operator, condition_value,
                    condition_value_type, payload_context,
                    old_payload=old_payload if compare_with_old else None,
                )
                if condition_field else False
            )

            branch_actions = if_true_actions if condition_met else if_false_actions
            branch_label = "if_true" if condition_met else "if_false"
            errors = 0
            for child_cfg in branch_actions:
                res = _execute_inline_action(
                    child_cfg, payload_context, old_payload=old_payload, run_log=run_log, parent_action=action
                )
                if res.get("status") == AutomationActionLogStatus.ERROR:
                    errors += 1

            result_message = (
                f"Branch: eseguito ramo '{branch_label}' "
                f"({len(branch_actions)} azioni, {errors} errori)."
            )
            final_status = AutomationActionLogStatus.ERROR if errors else AutomationActionLogStatus.SUCCESS
            action_log = _create_action_log(
                run_log=run_log, action=action,
                status=final_status,
                result_message=result_message,
            )
            return {"status": final_status, "result_message": result_message, "action_log": action_log}

        # â”€â”€ COUNT_BRANCH (conta record + soglia) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if action.action_type == AutomationActionType.COUNT_BRANCH:
            count_source = str(config.get("source_code") or source_code or "").strip()
            filter_field = str(config.get("filter_field") or "").strip() or None
            filter_value_raw = config.get("filter_value_template")
            filter_value = (
                render_template_string(str(filter_value_raw or ""), payload_context)
                if filter_value_raw else None
            )
            window_field = str(config.get("window_field") or "").strip() or None
            window_days = config.get("window_days")
            try:
                window_days = int(window_days) if window_days not in (None, "") else None
            except (TypeError, ValueError):
                raise ValueError("count_branch: window_days deve essere un intero.")
            try:
                threshold = int(config.get("threshold"))
            except (TypeError, ValueError):
                raise ValueError("count_branch: threshold (soglia) intera obbligatoria.")
            operator = str(config.get("operator") or "gte").strip().lower()

            if not count_source:
                raise ValueError("count_branch: source_code non specificato.")

            total = _count_source(
                count_source, filter_field, filter_value,
                window_field=window_field, window_days=window_days,
            )
            _ops = {
                "gte": total >= threshold, "gt": total > threshold,
                "lte": total <= threshold, "lt": total < threshold,
                "eq": total == threshold,
            }
            condition_met = _ops.get(operator, total >= threshold)

            then_actions = list(config.get("then_actions") or [])
            else_actions = list(config.get("else_actions") or [])
            branch_actions = then_actions if condition_met else else_actions
            branch_label = "then" if condition_met else "else"
            errors = 0
            for child_cfg in branch_actions:
                res = _execute_inline_action(
                    child_cfg, payload_context, old_payload=old_payload, run_log=run_log, parent_action=action
                )
                if res.get("status") == AutomationActionLogStatus.ERROR:
                    errors += 1

            result_message = (
                f"Count Branch: '{count_source}' count={total} {operator} {threshold} "
                f"=> {condition_met}; ramo '{branch_label}' ({len(branch_actions)} azioni, {errors} errori)."
            )
            final_status = AutomationActionLogStatus.ERROR if errors else AutomationActionLogStatus.SUCCESS
            action_log = _create_action_log(
                run_log=run_log, action=action,
                status=final_status,
                result_message=result_message,
            )
            return {"status": final_status, "result_message": result_message, "action_log": action_log}

        raise NotImplementedError(f"Action type '{action.action_type}' non ancora implementato in fase 4B.")
    except AutomationSafetyError as exc:
        action_identity = _format_action_identity(action, run_log)
        logger.warning("automation safety guardrail blocked %s: %s", action_identity, exc)
        error_trace = traceback.format_exc()
        result_message = f"Safety guardrail: {exc}"
        action_log = _create_action_log(
            run_log=run_log,
            action=action,
            status=AutomationActionLogStatus.ERROR,
            result_message=result_message,
            error_trace=error_trace,
        )
        return {"status": AutomationActionLogStatus.ERROR, "result_message": result_message, "action_log": action_log}
    except Exception as exc:
        logger.warning(
            "execute_action: errore nel tipo=%s run_log=%s rule_id=%s action_id=%s: %s",
            getattr(action, "action_type", "?"),
            getattr(run_log, "pk", None),
            getattr(getattr(action, "rule", None), "pk", None) or getattr(run_log, "rule_id", None),
            getattr(action, "pk", None),
            exc,
            exc_info=True,
        )
        error_trace = traceback.format_exc()
        result_message = str(exc) or "Errore durante esecuzione action."
        action_log = _create_action_log(
            run_log=run_log,
            action=action,
            status=AutomationActionLogStatus.ERROR,
            result_message=result_message,
            error_trace=error_trace,
        )
        return {"status": AutomationActionLogStatus.ERROR, "result_message": result_message, "action_log": action_log}


def run_rule(
    rule: AutomationRule,
    payload: Any,
    old_payload: Any = None,
    queue_event_id: int | None = None,
    initiated_by: Any = None,
    is_test: bool = False,
    queue_event: dict[str, Any] | None = None,
) -> AutomationRunLog:
    started_at = timezone.now()
    payload = _enrich_payload_for_source(rule.source_code, payload)
    old_payload = _enrich_payload_for_source(rule.source_code, old_payload)
    run_log = AutomationRunLog.objects.create(
        rule=rule,
        queue_event_id=queue_event_id,
        source_code=rule.source_code,
        operation_type=rule.operation_type,
        trigger_event_label=_build_trigger_event_label(rule),
        status=AutomationRunLogStatus.TEST if is_test else AutomationRunLogStatus.SUCCESS,
        payload_json=payload if payload is not None else {},
        old_payload_json=old_payload,
        started_at=started_at,
        initiated_by=initiated_by,
        is_test=is_test,
        result_message="Esecuzione avviata.",
    )

    try:
        enabled_conditions = rule.conditions.filter(is_enabled=True).order_by("order", "id")
        for condition in enabled_conditions:
            if not evaluate_condition(condition, payload, old_payload=old_payload):
                run_log.status = AutomationRunLogStatus.SKIPPED
                run_log.result_message = (
                    f"Condizione non soddisfatta: {condition.field_name} {condition.operator} (order={condition.order})."
                )
                break
        else:
            action_errors = 0
            action_count = 0
            enabled_actions = rule.actions.filter(is_enabled=True).order_by("order", "id")
            for action in enabled_actions:
                action_count += 1
                result = execute_action(action, payload, old_payload=old_payload, run_log=run_log, queue_event=queue_event)
                if result["status"] == AutomationActionLogStatus.ERROR:
                    action_errors += 1
                    if rule.stop_on_first_failure:
                        run_log.result_message = (
                            f"Esecuzione interrotta alla action {action.order} ({action.action_type}) per stop_on_first_failure."
                        )
                        break

            if action_errors:
                run_log.status = AutomationRunLogStatus.ERROR
                if not run_log.result_message or run_log.result_message == "Esecuzione avviata.":
                    run_log.result_message = f"Esecuzione completata con {action_errors} action in errore."
            elif run_log.status == AutomationRunLogStatus.WAITING_APPROVAL:
                if not run_log.result_message or run_log.result_message == "Esecuzione avviata.":
                    run_log.result_message = f"In attesa di approvazione. Azioni elaborate: {action_count}."
            else:
                run_log.status = AutomationRunLogStatus.TEST if is_test else AutomationRunLogStatus.SUCCESS
                run_log.result_message = f"Regola eseguita con successo. Azioni elaborate: {action_count}."
                # Debounce: registra l'invio per le condizioni cooldown_group SOLO ora che le
                # azioni sono andate a buon fine (e non nei test, per non consumare la finestra).
                if not is_test:
                    _commit_cooldown_groups(rule, payload)
    except Exception:
        logger.exception(
            "run_rule: errore inatteso durante l'esecuzione della regola=%s queue_event_id=%s",
            getattr(rule, "code", "?"),
            queue_event_id,
        )
        run_log.status = AutomationRunLogStatus.ERROR
        run_log.result_message = "Errore inatteso durante l'esecuzione della regola."
        run_log.error_trace = traceback.format_exc()
    finally:
        finished_at = timezone.now()
        run_log.finished_at = finished_at
        run_log.execution_ms = max(int((finished_at - started_at).total_seconds() * 1000), 0)
        if is_test:
            rule.last_test_at = finished_at
            rule.save(update_fields=["last_test_at", "updated_at"])
        else:
            rule.last_run_at = finished_at
            rule.save(update_fields=["last_run_at", "updated_at"])
        run_log.save()

    return run_log


def process_approval_decision(token: str, decision: str, decided_by_email: str = "") -> dict[str, Any]:
    """
    Processa una decisione di approvazione (approved/rejected).
    Esegue le azioni del ramo corrispondente e aggiorna il run_log originale.

    Args:
        token: UUID del token di approvazione.
        decision: "approved" o "rejected".
        decided_by_email: email di chi ha preso la decisione.

    Returns:
        dict con: ok, approval_id, decision, actions_run, message
    """
    from .models import AutomationApproval, AutomationRunLogStatus

    if decision not in ("approved", "rejected"):
        return {"ok": False, "message": f"Decisione '{decision}' non valida. Usare 'approved' o 'rejected'."}

    with transaction.atomic():
        try:
            approval = (
                AutomationApproval.objects.select_for_update()
                .select_related("run_log", "action__rule")
                .get(token=token)
            )
        except AutomationApproval.DoesNotExist:
            return {"ok": False, "message": "Richiesta di approvazione non trovata."}

        if approval.status != AutomationApproval.Status.PENDING:
            return {
                "ok": False,
                "message": f"La richiesta Ã¨ giÃ  in stato '{approval.status}'. Non Ã¨ possibile decidere nuovamente.",
                "current_status": approval.status,
            }

        if approval.is_expired():
            approval.status = AutomationApproval.Status.EXPIRED
            approval.save(update_fields=["status"])
            return {"ok": False, "message": "La richiesta di approvazione Ã¨ scaduta."}

        # Aggiorna approval in transazione: il token diventa monouso prima delle azioni ramo.
        approval.status = decision
        approval.decided_by_email = decided_by_email or ""
        approval.decided_at = timezone.now()
        approval.save(update_fields=["status", "decided_by_email", "decided_at"])

        # Recupera il run_log originale e aggiorna il suo status
        run_log = approval.run_log
        run_log.status = AutomationRunLogStatus.SUCCESS if decision == "approved" else AutomationRunLogStatus.SKIPPED
        run_log.result_message = (
            f"Approvazione ricevuta: {decision} da '{decided_by_email or 'N/D'}' il {timezone.localtime(approval.decided_at).strftime('%d-%m-%Y %H:%M')}."
        )
        run_log.save(update_fields=["status", "result_message"])

    # Esegui le azioni del ramo corrispondente
    branch_actions = approval.approved_actions if decision == "approved" else approval.rejected_actions
    payload = approval.resume_payload if isinstance(approval.resume_payload, dict) else {}
    old_payload = approval.resume_old_payload if isinstance(approval.resume_old_payload, dict) else None

    actions_run = 0
    actions_errors = 0
    for child_cfg in (branch_actions or []):
        parent_action = approval.action
        res = _execute_inline_action(child_cfg, payload, old_payload=old_payload, run_log=run_log, parent_action=parent_action)
        actions_run += 1
        if res.get("status") == AutomationActionLogStatus.ERROR:
            actions_errors += 1

    return {
        "ok": True,
        "approval_id": approval.pk,
        "decision": decision,
        "actions_run": actions_run,
        "actions_errors": actions_errors,
        "message": (
            f"Decisione '{decision}' elaborata. "
            f"Azioni eseguite: {actions_run} (errori: {actions_errors})."
        ),
    }
