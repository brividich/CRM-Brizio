from __future__ import annotations

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

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, connections, transaction
from django.http import FileResponse, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse
from django.conf import settings
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_POST
from config.env_config import get_first_env_value, update_env_file_values
from core.acl import user_can_modulo_action
from core.audit import log_action
from core.upload_mime import (
    UploadMimeValidationError,
    safe_filename,
    validate_extension_and_mime,
)
from core.legacy_models import AnagraficaDipendente, Ruolo, UtenteLegacy
from core.legacy_utils import get_legacy_user, is_legacy_admin, legacy_table_columns, sync_django_user_from_legacy
from core.models import AuditLog, Notifica, Profile
from core.operational_roles import (
    get_active_roles,
    get_role_ids_for_user,
    get_roster_by_role,
    get_users_for_role,
)

from .models import (
    AnomalieAccessLevel,
    AnomalieLegacyRoleAccessRule,
    AnomalieListScope,
    AnomalieRoleAccessRule,
    AnomalieRoleType,
    AnomalieUserAccessRule,
)


logger = logging.getLogger(__name__)
User = get_user_model()


# Nome fisico della colonna chiave dell'ordine di produzione in `ordini_produzione`.
# Storicamente "sharepoint_item_id" (id dell'item SharePoint durante il porting),
# oggi e' semplicemente l'id univoco dell'OP — SharePoint non c'entra piu'. Il
# nome fisico resta invariato in DB (la tabella e' ricreata da un processo
# esterno), ma nel codice ci si riferisce ad esso tramite questo alias neutro,
# cosi' il nome "storico" compare in un solo punto.
OP_ITEM_ID_COL = "sharepoint_item_id"


ANOMALIE_LIST_KEYS = (
    "capi_reparto",
    "capi_commessa",
    "causali_doc",
    "stati_superficie",
    "avanzamenti",
    "autorizzati_modifica",
    "conferma_aggiornamenti",
    "rdc_segnalazione",
    "escalation_supervisori",
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
    # Email destinatarie fisse della mail di conferma aggiornamenti anomalie.
    "conferma_aggiornamenti": [],
    # Email dedicata alle anomalie da aprire RDC / segnalare a cliente
    # (riceve la mail solo quando l'aggiornamento contiene quei flag).
    "rdc_segnalazione": [],
    # Email supervisori del resoconto escalation "OP da controllare"
    # (anomalie ferme in "In attesa" oltre soglia ore).
    "escalation_supervisori": [],
}
ANOMALIE_NON_EMPTY_DEFAULT_KEYS = frozenset({"causali_doc", "stati_superficie", "avanzamenti"})
# Liste derivate dall'anagrafica: sola lettura, mai persistite nel file JSON.
ANOMALIE_DERIVED_LIST_KEYS = frozenset({"capi_reparto", "capi_commessa"})
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
ANOMALIE_SETTINGS_TABS = ("riepilogo", "config", "permessi", "record", "log")
# Alias retrocompatibili: le vecchie URL ?tab=ruoli|accessi restano valide e
# vengono normalizzate nella view al nuovo tab "permessi" con sub corrispondente.
ANOMALIE_SETTINGS_TAB_ALIASES = {
    "ruoli": ("permessi", "ruoli"),
    "accessi": ("permessi", "accessi"),
}
ANOMALIE_PERMESSI_SUBTABS = ("ruoli", "accessi")
ANOMALIE_ACCESS_LEVEL_ORDER = {
    AnomalieAccessLevel.NONE: 0,
    AnomalieAccessLevel.READ_ALL: 1,
    AnomalieAccessLevel.EDIT_ASSIGNED: 2,
    AnomalieAccessLevel.EDIT_ALL: 3,
}
ANOMALIE_LIST_SCOPE_ORDER = {
    AnomalieListScope.OWN_ANOMALIE: 0,
    AnomalieListScope.ASSIGNED: 1,
    AnomalieListScope.ALL: 2,
}
SYSTEM_ANOMALIE_ROLE_DEFINITIONS = (
    (
        AnomalieRoleType.CAPO_COMMESSA,
        "Capocommessa",
        "Ruolo collegato al campo Capocommessa dell'OP.",
        10,
        AnomalieAccessLevel.EDIT_ASSIGNED,
    ),
    (
        AnomalieRoleType.CAR,
        "CAR / Incaricato",
        "Ruolo collegato al campo Incaricato/CAR dell'OP.",
        20,
        AnomalieAccessLevel.EDIT_ASSIGNED,
    ),
)


def _json_error(msg: str, status: int = 400):
    return JsonResponse({"error": msg}, status=status)


def _normalize_anomalie_settings_tab(raw_tab: str | None, *, default: str = "config") -> str:
    tab = str(raw_tab or "").strip().lower()
    if tab in ANOMALIE_SETTINGS_TAB_ALIASES:
        return ANOMALIE_SETTINGS_TAB_ALIASES[tab][0]
    return tab if tab in ANOMALIE_SETTINGS_TABS else default


def _normalize_anomalie_permessi_sub(raw_tab: str | None, raw_sub: str | None, *, default: str = "ruoli") -> str:
    raw_tab_norm = str(raw_tab or "").strip().lower()
    if raw_tab_norm in ANOMALIE_SETTINGS_TAB_ALIASES:
        return ANOMALIE_SETTINGS_TAB_ALIASES[raw_tab_norm][1]
    sub = str(raw_sub or "").strip().lower()
    return sub if sub in ANOMALIE_PERMESSI_SUBTABS else default


def _ensure_system_anomalie_roles() -> None:
    """Garantisce le regole di accesso per i ruoli di SISTEMA (CC/CAR).

    Il catalogo dei ruoli custom non e' piu' locale: la fonte unica e'
    ``anagrafica.RuoloOperativo`` (vedi ``core.operational_roles``).
    """
    for code, _name, _description, _order_index, default_access in SYSTEM_ANOMALIE_ROLE_DEFINITIONS:
        AnomalieRoleAccessRule.objects.get_or_create(
            role_type=code,
            ruolo_operativo=None,
            defaults={"access_level": default_access},
        )


def _anomalie_system_roles() -> list[dict]:
    """Ruoli di sistema (CC/CAR) come righe pronte per template/logica."""
    _ensure_system_anomalie_roles()
    return [
        {"code": code, "name": name, "description": description, "is_system": True}
        for code, name, description, _order_index, _default_access in SYSTEM_ANOMALIE_ROLE_DEFINITIONS
    ]


def _anomalie_custom_rules_for_user(user) -> list[AnomalieRoleAccessRule]:
    """Regole accesso custom applicabili a un utente Django.

    I ruoli custom provengono dal catalogo anagrafica: si recuperano gli id
    ``RuoloOperativo`` ricoperti dall'utente e si filtrano le regole su quegli id.
    """
    if not getattr(user, "is_authenticated", False):
        return []
    role_ids = get_role_ids_for_user(user)
    if not role_ids:
        return []
    return list(
        AnomalieRoleAccessRule.objects.filter(ruolo_operativo_id__in=role_ids)
    )


def _anomalie_settings_users_queryset():
    """Utenti disponibili nelle impostazioni anomalie, sincronizzati da `utenti`.

    Le regole salvano FK verso auth_user, ma la sorgente aziendale resta la
    tabella legacy `utenti`. Quando manca lo specchio Django, lo creiamo qui.
    """
    base_qs = User.objects.filter(is_active=True).select_related("profile")
    try:
        active_legacy_users = list(
            UtenteLegacy.objects.filter(attivo=True).only("id", "nome", "email", "ruolo", "ruolo_id")
        )
    except DatabaseError:
        return base_qs.order_by("first_name", "last_name", "username")

    if not active_legacy_users:
        return base_qs.order_by("first_name", "last_name", "username")

    active_legacy_ids = [int(user.id) for user in active_legacy_users]
    mapped_ids = set(
        Profile.objects.filter(legacy_user_id__in=active_legacy_ids).values_list("legacy_user_id", flat=True)
    )
    for legacy_user in active_legacy_users:
        if int(legacy_user.id) in mapped_ids:
            continue
        try:
            sync_django_user_from_legacy(legacy_user)
        except Exception:
            logger.exception(
                "Impossibile sincronizzare utente legacy anomalie legacy_user_id=%s",
                getattr(legacy_user, "id", None),
            )

    mapped_qs = base_qs.filter(profile__legacy_user_id__in=active_legacy_ids)
    if not mapped_qs.exists():
        return base_qs.order_by("first_name", "last_name", "username")
    return mapped_qs.order_by("first_name", "last_name", "username")


def _filter_anomalie_user_rows(users, query: str):
    users = list(users)
    query = str(query or "").strip().casefold()
    if not query:
        return users

    legacy_ids = []
    for user in users:
        profile = getattr(user, "profile", None)
        legacy_user_id = getattr(profile, "legacy_user_id", None) if profile is not None else None
        if legacy_user_id:
            legacy_ids.append(legacy_user_id)

    legacy_by_id = {}
    if legacy_ids:
        try:
            legacy_by_id = {
                row["id"]: row
                for row in UtenteLegacy.objects.filter(id__in=legacy_ids).values("id", "nome", "email", "ruolo")
            }
        except DatabaseError:
            legacy_by_id = {}

    def _haystack(user) -> str:
        parts = [
            user.get_full_name(),
            getattr(user, "first_name", ""),
            getattr(user, "last_name", ""),
            getattr(user, "username", ""),
            getattr(user, "email", ""),
        ]
        profile = getattr(user, "profile", None)
        if profile is not None:
            legacy_user_id = getattr(profile, "legacy_user_id", None)
            parts.append(str(legacy_user_id or ""))
            legacy_row = legacy_by_id.get(legacy_user_id)
            if legacy_row:
                parts.extend([legacy_row.get("nome"), legacy_row.get("email"), legacy_row.get("ruolo")])
        return " ".join(str(part or "") for part in parts).casefold()

    return [user for user in users if query in _haystack(user)]


def _anomalie_legacy_role_rows() -> list[dict]:
    """Ruoli aziendali disponibili dalla tabella legacy `ruoli`."""
    rows: list[dict] = []
    try:
        rows = [
            {
                "id": int(role.id),
                "label": str(role.nome or "").strip() or f"Ruolo #{role.id}",
            }
            for role in Ruolo.objects.all().order_by("nome", "id")
        ]
    except DatabaseError:
        rows = []

    if rows:
        return rows

    # Fallback prudente: se `ruoli` non e' raggiungibile ma `utenti` si',
    # mostriamo comunque i ruolo_id incontrati sugli utenti attivi.
    try:
        seen: dict[int, str] = {}
        for role_id, role_name in (
            UtenteLegacy.objects.filter(attivo=True, ruolo_id__isnull=False)
            .values_list("ruolo_id", "ruolo")
            .distinct()
        ):
            role_id_int = int(role_id)
            seen[role_id_int] = str(role_name or "").strip() or f"Ruolo #{role_id_int}"
        rows = [{"id": role_id, "label": label} for role_id, label in seen.items()]
    except (DatabaseError, TypeError, ValueError):
        rows = []
    return sorted(rows, key=lambda row: (str(row["label"]).casefold(), int(row["id"])))


def _access_level_at_least(level: str, minimum: str) -> bool:
    return ANOMALIE_ACCESS_LEVEL_ORDER.get(level, 0) >= ANOMALIE_ACCESS_LEVEL_ORDER.get(minimum, 0)


def _max_anomalie_access_level(levels: list[str]) -> str:
    if not levels:
        return AnomalieAccessLevel.NONE
    return max(levels, key=lambda level: ANOMALIE_ACCESS_LEVEL_ORDER.get(level, 0))


def _max_anomalie_list_scope(scopes: list[str]) -> str:
    if not scopes:
        return AnomalieListScope.ALL
    return max(scopes, key=lambda s: ANOMALIE_LIST_SCOPE_ORDER.get(s, 2))


def _request_anomalie_list_scope(request) -> str:
    """Calcola lo scope di visibilità lista OP dell'utente corrente.

    ALL            → vede tutti gli OP (default)
    ASSIGNED       → vede solo gli OP in cui compare come capocommessa/CAR
    OWN_ANOMALIE   → vede solo gli OP con almeno una propria anomalia creata

    Priorità (vince il più permissivo): superuser/admin > EDIT_ALL > user override
    > legacy role > custom role. I ruoli di sistema (CC, CAR) vengono applicati solo
    se l'utente risulta effettivamente capocommessa/CAR su almeno un OP.
    """
    user = getattr(request, "user", None)
    if bool(getattr(user, "is_superuser", False)):
        return AnomalieListScope.ALL
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(user)
    if legacy_user and is_legacy_admin(legacy_user):
        return AnomalieListScope.ALL

    global_level = _request_anomalie_global_access_level(request)
    if _access_level_at_least(global_level, AnomalieAccessLevel.EDIT_ALL):
        return AnomalieListScope.ALL

    if not getattr(user, "is_authenticated", False):
        return AnomalieListScope.ALL

    scopes: list[str] = []

    # 1. Override per singolo utente
    try:
        scopes.append(user.anomalie_access_rule.list_scope)
    except AnomalieUserAccessRule.DoesNotExist:
        pass

    # 2. Ruolo aziendale legacy
    role_id = _request_legacy_role_id(request)
    if role_id is not None:
        s = (
            AnomalieLegacyRoleAccessRule.objects.filter(legacy_role_id=role_id)
            .values_list("list_scope", flat=True)
            .first()
        )
        if s:
            scopes.append(s)

    # 3. Ruoli operativi custom (dall'anagrafica) ricoperti dall'utente
    custom_rules = _anomalie_custom_rules_for_user(user)
    if custom_rules:
        scopes.extend(rule.list_scope for rule in custom_rules)

    # 4. Ruoli di sistema (CC, CAR): applica solo se l'utente compare su almeno un OP
    system_rule_map = {
        r["role_type"]: r["list_scope"]
        for r in AnomalieRoleAccessRule.objects.filter(
            role_type__in=[AnomalieRoleType.CAPO_COMMESSA, AnomalieRoleType.CAR]
        ).values("role_type", "list_scope")
    }
    non_all_system = [s for s in system_rule_map.values() if s != AnomalieListScope.ALL]
    if non_all_system and _has_table("ordini_produzione"):
        identity = _current_user_identity(request)
        user_name = identity["name"]
        if user_name:
            try:
                match = _fetch_all_dict(
                    "SELECT TOP 1 1 AS m FROM ordini_produzione WHERE capocomessa LIKE %s OR incaricato LIKE %s",
                    [f"%{user_name}%", f"%{user_name}%"],
                )
                if match:
                    scopes.extend(system_rule_map.values())
            except Exception:
                pass

    return _max_anomalie_list_scope(scopes) if scopes else AnomalieListScope.ALL


def _has_table(table_name: str) -> bool:
    return bool(legacy_table_columns(table_name))


def _fetch_all_dict(sql: str, params: list | tuple | None = None) -> list[dict]:
    with connections["default"].cursor() as cursor:
        cursor.execute(sql, params or [])
        cols = [str(c[0]) for c in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _quote_identifier(name: str) -> str:
    return connections["default"].ops.quote_name(str(name))


def _quoted_columns(columns: list[str], *, alias: str | None = None) -> str:
    if alias:
        return ", ".join(f"{alias}.{_quote_identifier(col)}" for col in columns)
    return ", ".join(_quote_identifier(col) for col in columns)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


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
    rel_cfg = get_first_env_value("ANOMALIE_ATTACHMENTS_DIR", default=ANOMALIE_ATTACHMENTS_DIR_DEFAULT)
    _, path = _resolve_anomalie_attachments_path(rel_cfg)
    return path


def _anomalie_attachments_dir_value() -> str:
    return get_first_env_value("ANOMALIE_ATTACHMENTS_DIR", default=ANOMALIE_ATTACHMENTS_DIR_DEFAULT)


def _save_anomalie_attachments_dir(value: str) -> str:
    cleaned, _ = _resolve_anomalie_attachments_path(value)
    update_env_file_values({"ANOMALIE_ATTACHMENTS_DIR": cleaned})
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


def _list_attachments_for_local(local_id: int) -> list[dict]:
    folder = _attachment_dir_for_local(local_id, create=False)
    if not folder.exists():
        return []

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

    items: list[dict] = []
    for path in paths:
        file_id = path.name
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
            }
        )
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


def _label_from_anagrafica_row(row: dict) -> str:
    """Compone l'etichetta dipendente ("Nome Cognome") da una riga anagrafica.

    Usa la stessa fonte (``anagrafica_dipendenti``) e gli stessi id legacy
    impiegati da Anagrafica per popolare/risolvere ``caporeparto_legacy_id`` e
    ``ruolo_aziendale``, così le label coincidono con quelle mostrate nei
    moduli HR.
    """
    nome = str(row.get("nome") or "").strip()
    cognome = str(row.get("cognome") or "").strip()
    return " ".join(part for part in [nome, cognome] if part).strip()


def _capireparto_from_anagrafica() -> list[str]:
    """Nomi distinti dei capireparto dai reparti attivi in anagrafica.

    ``Reparto.caporeparto_legacy_id`` è l'id legacy del *dipendente*
    (tabella ``anagrafica_dipendenti``), non di ``UtenteLegacy``: vanno quindi
    risolti dalla stessa fonte usata da Anagrafica, altrimenti gli id collidono
    con account diversi e si ottengono nomi errati.
    """
    try:
        from anagrafica.models import Reparto
        from core.legacy_anagrafica import fetch_anagrafica_rows
        ids = sorted({
            int(v)
            for v in Reparto.objects.filter(
                is_active=True, caporeparto_legacy_id__isnull=False
            )
            .exclude(caporeparto_legacy_id=0)
            .values_list("caporeparto_legacy_id", flat=True)
            if int(v or 0) > 0
        })
        if not ids:
            return []
        names = [
            _label_from_anagrafica_row(row)
            for row in fetch_anagrafica_rows(ids=ids, deduplicate=True)
        ]
        return sorted({n for n in names if n})
    except Exception:
        logger.debug("[anomalie] impossibile caricare capireparto da anagrafica", exc_info=True)
        return []


def _capicommessa_from_anagrafica() -> list[str]:
    """Nomi distinti dei dipendenti che fanno parte del reparto capocommessa.

    I capicommessa NON sono identificati da un ruolo aziendale testuale: sono i
    dipendenti appartenenti a uno specifico reparto (default "IN1"), il cui
    nome è in ``DipendenteAnagraficaAziendale.area``. L'appartenenza al reparto
    conferisce automaticamente il ruolo di capocommessa. Il reparto sorgente è
    configurabile via ``settings.ANOMALIE_CAPOCOMMESSA_REPARTO``.
    """
    reparto = str(getattr(settings, "ANOMALIE_CAPOCOMMESSA_REPARTO", "IN1") or "").strip()
    if not reparto:
        return []
    try:
        from anagrafica.models import DipendenteAnagraficaAziendale
        from core.legacy_anagrafica import fetch_anagrafica_rows
        ids = sorted({
            int(v)
            for v in DipendenteAnagraficaAziendale.objects.filter(
                area__iexact=reparto
            ).values_list("legacy_anagrafica_id", flat=True)
            if int(v or 0) > 0
        })
        if not ids:
            return []
        names = [
            _label_from_anagrafica_row(row)
            for row in fetch_anagrafica_rows(ids=ids, deduplicate=True)
        ]
        return sorted({n for n in names if n})
    except Exception:
        logger.debug("[anomalie] impossibile caricare capicommessa da anagrafica", exc_info=True)
        return []


def _apply_derived_anomalie_lists(data: dict[str, list[str]]) -> None:
    """Sovrascrive le liste derivate dall'anagrafica (sola lettura)."""
    data["capi_reparto"] = _capireparto_from_anagrafica()
    data["capi_commessa"] = _capicommessa_from_anagrafica()


def _load_anomalie_lists() -> dict[str, list[str]]:
    data = _default_anomalie_lists()
    path = _anomalie_lists_path()
    if not path.exists():
        _apply_derived_anomalie_lists(data)
        return data
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("[anomalie] impossibile leggere file liste: %s", path)
        _apply_derived_anomalie_lists(data)
        return data
    if not isinstance(payload, dict):
        _apply_derived_anomalie_lists(data)
        return data
    for key in ANOMALIE_LIST_KEYS:
        if key in ANOMALIE_DERIVED_LIST_KEYS:
            continue  # sempre da anagrafica
        if key in payload:
            values = _normalize_choice_list(payload.get(key))
            if values or key not in ANOMALIE_NON_EMPTY_DEFAULT_KEYS:
                data[key] = values
            else:
                data[key] = list(ANOMALIE_LIST_DEFAULTS[key])
    _apply_derived_anomalie_lists(data)
    return data


def _save_anomalie_lists(lists_payload: dict[str, list[str]]) -> None:
    path = _anomalie_lists_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Legge il file esistente per preservare chiavi non-lista (es. menu_logo)
    try:
        existing: dict = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        existing = {}
    for key in ANOMALIE_LIST_KEYS:
        if key in ANOMALIE_DERIVED_LIST_KEYS:
            existing.pop(key, None)  # derivata da anagrafica: mai persistita
            continue
        existing[key] = _normalize_choice_list(lists_payload.get(key, []))
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_anomalie_menu_logo() -> str:
    """Restituisce l'URL del logo personalizzato del menu anomalie, o stringa vuota."""
    path = _anomalie_lists_path()
    if not path.exists():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return str(payload.get("menu_logo") or "").strip()
    except Exception:
        return ""


def _save_anomalie_menu_logo(url: str) -> None:
    path = _anomalie_lists_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing: dict = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        existing = {}
    existing["menu_logo"] = str(url or "").strip()
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")




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
    # La chiave d'identita' dell'anomalia e' sempre la PK locale `id`.
    # `sharepoint_item_id` non e' piu' usata come chiave (residuo del porting
    # da SharePoint, NULL su tutti i record nuovi): resta in tabella solo per
    # i record legacy importati, ma non indirizza piu' il salvataggio.
    local_id = row.get("id")
    return f"local:{int(local_id)}" if local_id is not None else ""


def _row_capocommessa(row: dict):
    return row.get("capocommessa") or row.get("capocomessa")


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
            f"""
            SELECT TOP 1 {OP_ITEM_ID_COL}
            FROM ordini_produzione
            WHERE title = %s
            ORDER BY id DESC
            """,
            [op_title_clean],
        )
        if not rows:
            return None
        sp_id = str(rows[0].get(OP_ITEM_ID_COL) or "").strip()
        return int(sp_id) if sp_id.isdigit() else None
    except Exception:
        return None


def _legacy_role_name(request) -> str:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    return str(getattr(legacy_user, "ruolo", "") or "").strip().lower()


def _request_legacy_role_id(request) -> int | None:
    cached = getattr(request, "_anomalie_legacy_role_id", None)
    if cached is not None:
        return cached

    raw_role_id = None
    user = getattr(request, "user", None)
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(user)
    if legacy_user is not None:
        raw_role_id = getattr(legacy_user, "ruolo_id", None)

    if raw_role_id is None and getattr(user, "is_authenticated", False):
        try:
            raw_role_id = user.profile.legacy_ruolo_id
        except Profile.DoesNotExist:
            raw_role_id = None

    try:
        cached = int(raw_role_id) if raw_role_id is not None else None
    except (TypeError, ValueError):
        cached = None
    request._anomalie_legacy_role_id = cached
    return cached


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


def _request_anomalie_custom_role_access_level(request) -> str:
    user = getattr(request, "user", None)
    custom_rules = _anomalie_custom_rules_for_user(user)
    if not custom_rules:
        return AnomalieAccessLevel.NONE
    levels = [rule.access_level for rule in custom_rules]
    return _max_anomalie_access_level(levels)


def _request_anomalie_user_override_level(request) -> str:
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return AnomalieAccessLevel.NONE
    try:
        return user.anomalie_access_rule.access_level
    except AnomalieUserAccessRule.DoesNotExist:
        return AnomalieAccessLevel.NONE


def _request_anomalie_legacy_role_access_level(request) -> str:
    role_id = _request_legacy_role_id(request)
    if role_id is None:
        return AnomalieAccessLevel.NONE
    return (
        AnomalieLegacyRoleAccessRule.objects.filter(legacy_role_id=role_id)
        .values_list("access_level", flat=True)
        .first()
        or AnomalieAccessLevel.NONE
    )


def _request_anomalie_global_access_level(request) -> str:
    if bool(getattr(getattr(request, "user", None), "is_superuser", False)):
        return AnomalieAccessLevel.EDIT_ALL
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if legacy_user and is_legacy_admin(legacy_user):
        return AnomalieAccessLevel.EDIT_ALL
    return _max_anomalie_access_level(
        [
            _request_anomalie_user_override_level(request),
            _request_anomalie_legacy_role_access_level(request),
            _request_anomalie_custom_role_access_level(request),
        ]
    )


def _anomalie_frontend_access_context(request) -> dict:
    _ensure_system_anomalie_roles()
    role_access = {
        role_type: access_level
        for role_type, access_level in AnomalieRoleAccessRule.objects.filter(
            ruolo_operativo__isnull=True
        )
        .exclude(role_type="")
        .values_list("role_type", "access_level")
    }
    global_level = _request_anomalie_global_access_level(request)
    return {
        "global_level": global_level,
        "can_edit_all": _access_level_at_least(global_level, AnomalieAccessLevel.EDIT_ALL),
        "role_access": role_access,
    }


def _op_role_codes_for_current_user(request, op_id: str) -> list[str]:
    _ensure_system_anomalie_roles()
    op_title = _safe_text(op_id, 100)
    if not op_title or not _has_table("ordini_produzione"):
        return []

    try:
        rows = _fetch_all_dict(
            "SELECT TOP 1 capocomessa, incaricato FROM ordini_produzione WHERE title = %s",
            [op_title],
        )
    except Exception:
        return []
    if not rows:
        return []

    current_name_norms = _current_user_name_norms(request)
    identity = _current_user_identity(request)
    if not current_name_norms and identity["name_norm"]:
        current_name_norms = {identity["name_norm"]}
    if not current_name_norms:
        return []

    matched_roles: list[str] = []
    role_to_people = {
        AnomalieRoleType.CAPO_COMMESSA: _row_capocommessa(rows[0]),
        AnomalieRoleType.CAR: rows[0].get("incaricato"),
    }
    for role_code, raw_people in role_to_people.items():
        tokens = _split_people_tokens(str(raw_people or ""))
        if not tokens:
            continue
        token_norms = {_normalize_identity_text(t) for t in tokens}
        if current_name_norms.intersection(token_norms):
            matched_roles.append(role_code)

    return matched_roles


def _anomalie_role_access_level_for_codes(role_codes: list[str]) -> str:
    matched_roles = [str(role_code or "").strip() for role_code in role_codes if str(role_code or "").strip()]
    if not matched_roles:
        return AnomalieAccessLevel.NONE
    levels = list(
        AnomalieRoleAccessRule.objects.filter(
            role_type__in=matched_roles, ruolo_operativo__isnull=True
        ).values_list("access_level", flat=True)
    )
    return _max_anomalie_access_level(levels)


def _op_role_access_level_for_current_user(request, op_id: str) -> str:
    return _anomalie_role_access_level_for_codes(_op_role_codes_for_current_user(request, op_id))


def _user_created_anomalia_on_op(request, op_id: str) -> bool:
    """True se l'utente corrente ha creato almeno un'anomalia sull'OP (scope OWN)."""
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not legacy_user:
        return False
    op_title = _safe_text(op_id, 100)
    if not op_title or not _has_table("anomalie"):
        return False
    if "created_by_user_id" not in (legacy_table_columns("anomalie") or set()):
        return False
    try:
        rows = _fetch_all_dict(
            "SELECT COUNT(*) AS n FROM anomalie "
            "WHERE created_by_user_id = %s AND ex_op_nominativo = %s",
            [legacy_user.id, op_title],
        )
        return bool(rows and int(rows[0].get("n") or 0) > 0)
    except Exception:
        return False


def _can_view_anomalie_for_op(request, op_id: str) -> bool:
    """Visibilità in lettura delle anomalie di un OP.

    Default storico: qualsiasi utente autenticato può consultare. Se però un
    amministratore ha ristretto lo scope dell'utente (ASSIGNED / OWN_ANOMALIE),
    la restrizione vale anche in lettura sul singolo OP, non solo sull'elenco:
    senza questo lo scope sarebbe puramente cosmetico (qualunque utente potrebbe
    leggere le anomalie di un OP qualsiasi passando op_id/op_item_id all'API).
    I permessi di modifica restano vincolati a _can_edit_anomalie_for_op.
    """
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return False

    scope = _request_anomalie_list_scope(request)
    if scope == AnomalieListScope.ALL:
        return True

    # Scope ristretto: consentito solo se l'utente ha titolo sull'OP.
    if _can_edit_anomalie_for_op(request, op_id):
        return True
    if _op_role_codes_for_current_user(request, op_id):
        return True
    if scope == AnomalieListScope.OWN_ANOMALIE and _user_created_anomalia_on_op(request, op_id):
        return True
    return False


def _can_export_anomalie(request) -> bool:
    """Export massivo riservato ad admin / utenti con EDIT_ALL.

    L'export scarica fino a migliaia di righe in un colpo solo: a differenza
    della consultazione (aperta), va ristretto a chi ha pieni diritti sul
    modulo (superuser, admin legacy o livello accesso EDIT_ALL).
    """
    return _access_level_at_least(
        _request_anomalie_global_access_level(request),
        AnomalieAccessLevel.EDIT_ALL,
    )


def _can_edit_anomalie_for_op(request, op_id: str) -> bool:
    if bool(getattr(request.user, "is_superuser", False)):
        return True
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if legacy_user and is_legacy_admin(legacy_user):
        return True

    global_level = _request_anomalie_global_access_level(request)
    if _access_level_at_least(global_level, AnomalieAccessLevel.EDIT_ALL):
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

    matched_op_roles = _op_role_codes_for_current_user(request, op_id)
    if matched_op_roles and _access_level_at_least(global_level, AnomalieAccessLevel.EDIT_ASSIGNED):
        return True

    op_role_level = _anomalie_role_access_level_for_codes(matched_op_roles)
    if _access_level_at_least(op_role_level, AnomalieAccessLevel.EDIT_ASSIGNED):
        return True

    return False


def _can_manage_anomalie_config(request) -> bool:
    if bool(getattr(request.user, "is_superuser", False)):
        return True
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not legacy_user:
        return False
    return bool(is_legacy_admin(legacy_user))


def _anomalie_ruoli_anagrafica_url() -> str:
    """URL del catalogo Ruoli Operativi in anagrafica (gestione assegnazioni)."""
    try:
        return reverse("ruoli_operativi_list")
    except NoReverseMatch:
        return ""


def _anomalie_settings_redirect(tab: str, **params):
    query = {"tab": tab}
    query.update({k: v for k, v in params.items() if v})
    qs = "&".join(f"{quote(str(k))}={quote(str(v))}" for k, v in query.items())
    return redirect(f"{reverse('anomalie_configurazione_page')}?{qs}")


def _handle_anomalie_roles_post(request):
    """Il catalogo ruoli e le assegnazioni sono ora gestiti in Anagrafica.

    Manteniamo l'endpoint solo per retro-compatibilita': qualsiasi POST sul
    sub-tab ruoli rimanda al pannello (sola lettura) con un avviso.
    """
    q_user = request.POST.get("q_user", "").strip()
    messages.info(
        request,
        "Catalogo e assegnazioni dei ruoli operativi si gestiscono da Anagrafica > Ruoli operativi.",
    )
    return _anomalie_settings_redirect("permessi", sub="ruoli", q_user=q_user)


def _handle_anomalie_access_post(request):
    system_codes = {row["code"] for row in _anomalie_system_roles()}
    custom_role_ids = set(get_active_roles().values_list("id", flat=True))
    legacy_role_rows = _anomalie_legacy_role_rows()
    legacy_role_labels = {int(row["id"]): str(row["label"]) for row in legacy_role_rows}
    valid_levels = {choice for choice, _label in AnomalieAccessLevel.choices}
    valid_scopes = {choice for choice, _label in AnomalieListScope.choices}

    # Regole sui ruoli di sistema (CC/CAR) -> chiave role_type
    for role_code in system_codes:
        level = (request.POST.get(f"access_role__{role_code}") or AnomalieAccessLevel.NONE).strip()
        if level not in valid_levels:
            level = AnomalieAccessLevel.NONE
        scope = (request.POST.get(f"list_scope_role__{role_code}") or AnomalieListScope.ALL).strip()
        if scope not in valid_scopes:
            scope = AnomalieListScope.ALL
        AnomalieRoleAccessRule.objects.update_or_create(
            role_type=role_code,
            ruolo_operativo=None,
            defaults={"access_level": level, "list_scope": scope},
        )

    # Regole sui ruoli operativi custom (anagrafica) -> chiave ruolo_operativo_id
    for ruolo_id in custom_role_ids:
        level = (request.POST.get(f"access_custom_role__{ruolo_id}") or "").strip()
        scope = (request.POST.get(f"list_scope_custom_role__{ruolo_id}") or AnomalieListScope.ALL).strip()
        if scope not in valid_scopes:
            scope = AnomalieListScope.ALL
        if not level or level == AnomalieAccessLevel.NONE or level not in valid_levels:
            AnomalieRoleAccessRule.objects.filter(ruolo_operativo_id=ruolo_id).delete()
            continue
        AnomalieRoleAccessRule.objects.update_or_create(
            ruolo_operativo_id=ruolo_id,
            defaults={"role_type": "", "access_level": level, "list_scope": scope},
        )

    visible_ids = [int(v) for v in request.POST.getlist("visible_access_user_id") if str(v).isdigit()]
    for user_id in visible_ids:
        level = (request.POST.get(f"access_user__{user_id}") or "").strip()
        scope = (request.POST.get(f"list_scope_user__{user_id}") or AnomalieListScope.ALL).strip()
        if scope not in valid_scopes:
            scope = AnomalieListScope.ALL
        if not level:
            AnomalieUserAccessRule.objects.filter(user_id=user_id).delete()
            continue
        if level not in valid_levels or level == AnomalieAccessLevel.NONE:
            AnomalieUserAccessRule.objects.filter(user_id=user_id).delete()
            continue
        AnomalieUserAccessRule.objects.update_or_create(
            user_id=user_id,
            defaults={"access_level": level, "list_scope": scope},
        )

    visible_legacy_role_ids = [
        int(v)
        for v in request.POST.getlist("visible_legacy_role_id")
        if str(v).strip().isdigit()
    ]
    for role_id in visible_legacy_role_ids:
        level = (request.POST.get(f"access_legacy_role__{role_id}") or "").strip()
        scope = (request.POST.get(f"list_scope_legacy_role__{role_id}") or AnomalieListScope.ALL).strip()
        if scope not in valid_scopes:
            scope = AnomalieListScope.ALL
        if not level or level == AnomalieAccessLevel.NONE:
            AnomalieLegacyRoleAccessRule.objects.filter(legacy_role_id=role_id).delete()
            continue
        if level not in valid_levels:
            AnomalieLegacyRoleAccessRule.objects.filter(legacy_role_id=role_id).delete()
            continue
        AnomalieLegacyRoleAccessRule.objects.update_or_create(
            legacy_role_id=role_id,
            defaults={
                "legacy_role_name": legacy_role_labels.get(role_id, f"Ruolo #{role_id}")[:100],
                "access_level": level,
                "list_scope": scope,
            },
        )

    messages.success(request, "Regole accesso anomalie aggiornate.")
    return _anomalie_settings_redirect(
        "permessi", sub="accessi", q_access_user=request.POST.get("q_access_user", "").strip()
    )


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
            capo_val = str(_row_capocommessa(op_rows[0]) or "").strip()
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
    context = {
        "page_title": "Gestione Anomalie",
        "legacy_user": legacy_user,
        "is_admin": is_admin,
        "db_has_ordini": _has_table("ordini_produzione"),
        "db_has_anomalie": _has_table("anomalie"),
        "config_lists_json": json.dumps(lists_cfg, ensure_ascii=False),
        "current_user_name": identity["name"],
        "current_user_email": identity["email"],
        "current_user_name_norms_json": json.dumps(
            sorted({identity["name_norm"], *_current_user_name_norms(request)} - {""}),
            ensure_ascii=False,
        ),
        "access_context_json": json.dumps(_anomalie_frontend_access_context(request), ensure_ascii=False),
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
        return JsonResponse([], safe=False)
    try:
        list_scope = _request_anomalie_list_scope(request)
        identity = _current_user_identity(request)
        legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)

        scope_where = ""
        scope_params: list = []

        if list_scope == AnomalieListScope.ASSIGNED:
            user_name = identity["name"]
            if user_name:
                scope_where = "WHERE (op.capocomessa LIKE %s OR op.incaricato LIKE %s)"
                scope_params = [f"%{user_name}%", f"%{user_name}%"]
            # se il nome non è disponibile, mostra nulla per sicurezza
            else:
                scope_where = "WHERE 1=0"

        elif list_scope == AnomalieListScope.OWN_ANOMALIE:
            has_created_by = "created_by_user_id" in (legacy_table_columns("anomalie") or set())
            if has_created_by and legacy_user:
                scope_where = (
                    "WHERE EXISTS ("
                    "SELECT 1 FROM anomalie a "
                    f"WHERE a.op_lookup_id = TRY_CAST(op.{OP_ITEM_ID_COL} AS INT) "
                    "AND a.created_by_user_id = %s)"
                )
                scope_params = [legacy_user.id]
            elif legacy_user:
                # fallback: filtra per nome come ASSIGNED se created_by_user_id assente
                user_name = identity["name"]
                if user_name:
                    scope_where = "WHERE (op.capocomessa LIKE %s OR op.incaricato LIKE %s)"
                    scope_params = [f"%{user_name}%", f"%{user_name}%"]
                else:
                    scope_where = "WHERE 1=0"
            else:
                scope_where = "WHERE 1=0"

        sql = f"""
            SELECT
                op.{OP_ITEM_ID_COL} AS item_id,
                op.title AS op_title,
                op.part_number,
                op.incaricato,
                op.capocomessa,
                op.stato,
                COUNT(a.id) AS anomalie_count,
                SUM(CASE WHEN COALESCE(a.chiudere, 0) = 0 THEN 1 ELSE 0 END) AS anomalie_aperte_count
            FROM ordini_produzione op
            LEFT JOIN anomalie a
                ON a.op_lookup_id = TRY_CAST(op.{OP_ITEM_ID_COL} AS INT)
            {scope_where}
            GROUP BY
                op.{OP_ITEM_ID_COL}, op.title, op.part_number,
                op.incaricato, op.capocomessa, op.stato
            ORDER BY op.title
        """
        rows = _fetch_all_dict(sql, scope_params or None)
        result = [
            {
                "item_id": r.get("item_id"),
                "id": r.get("op_title") or "—",
                "pn": r.get("part_number") or "—",
                "capo": _row_capocommessa(r) or "—",
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
    if OP_ITEM_ID_COL not in cols:
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
                    f"""
                    SELECT COALESCE(MIN(TRY_CAST({OP_ITEM_ID_COL} AS INT)), 0)
                    FROM ordini_produzione WITH (UPDLOCK, HOLDLOCK)
                    """
                )
                row_min = cursor.fetchone()
                min_numeric = int(row_min[0] or 0) if row_min else 0
                next_local_item_id = -1 if min_numeric >= 0 else (min_numeric - 1)
                insert_writable[OP_ITEM_ID_COL] = str(next_local_item_id)

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

                quoted_insert_cols = _quoted_columns(insert_cols)
                cursor.execute(
                    f"""
                    INSERT INTO ordini_produzione ({quoted_insert_cols})
                    OUTPUT
                        INSERTED.id,
                        INSERTED.{OP_ITEM_ID_COL},
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

    # Scope ristretto (ASSIGNED/OWN): lettura del singolo OP consentita solo se
    # l'utente ha titolo. Per lo scope ALL (caso comune) si salta la verifica.
    if _request_anomalie_list_scope(request) != AnomalieListScope.ALL:
        op_row = _report_op_row(sp_item_id_int, None)
        op_title = _safe_text((op_row or {}).get("title"), 100)
        if not _can_view_anomalie_for_op(request, op_title):
            return _json_error("Permesso negato", status=403)

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
    # Titolo OP (ex_op_nominativo): usato come fallback quando op_lookup_id e' NULL.
    # Molti OP non hanno sharepoint_item_id (sistema in migrazione da SharePoint),
    # quindi le anomalie salvate restano con op_lookup_id NULL e sparirebbero
    # dall'elenco filtrato per solo op_lookup_id. Il match per titolo le recupera.
    op_title = _safe_text(request.GET.get("op_id"), 100)
    if not sp_item_id:
        resolved = _resolve_op_lookup_id(None, request.GET.get("op_id"))
        if resolved is not None:
            sp_item_id = str(resolved)
    if not sp_item_id and not op_title:
        return JsonResponse([], safe=False)

    sp_item_id_int = None
    if sp_item_id:
        try:
            sp_item_id_int = int(sp_item_id)
        except (TypeError, ValueError):
            return _json_error("sp_item_id non valido", status=400)
    if not _has_table("anomalie"):
        return JsonResponse([], safe=False)

    cols = legacy_table_columns("anomalie")
    rdc_col = ", numero_rdc" if "numero_rdc" in cols else ""

    # Se non ho il titolo OP ma ho il lookup id, lo derivo per estendere il match
    # anche ai record con op_lookup_id NULL ma stesso ex_op_nominativo.
    if not op_title and sp_item_id_int is not None:
        try:
            op_rows = _fetch_all_dict(
                f"SELECT TOP 1 title FROM ordini_produzione WHERE {OP_ITEM_ID_COL} = %s",
                [sp_item_id_int],
            )
            if op_rows:
                op_title = _safe_text(op_rows[0].get("title"), 100)
        except Exception:
            op_title = ""

    if not _can_view_anomalie_for_op(request, op_title or str(sp_item_id_int or "")):
        return _json_error("Permesso negato", status=403)

    # Costruisce la WHERE: per lookup id (se presente) E/O per titolo OP.
    where_parts: list[str] = []
    params: list = []
    if sp_item_id_int is not None:
        where_parts.append("op_lookup_id = %s")
        params.append(sp_item_id_int)
    if op_title:
        if connections["default"].vendor == "sqlite":
            where_parts.append("LOWER(ex_op_nominativo) = LOWER(%s)")
        else:
            where_parts.append("LOWER(CAST(ex_op_nominativo AS NVARCHAR(MAX))) = LOWER(%s)")
        params.append(op_title)
    where_clause = " OR ".join(where_parts)

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
            WHERE {where_clause}
            ORDER BY seriale
            """,
            params,
        )
        # Dedup difensivo: con WHERE in OR un record puo' matchare entrambi i rami.
        seen_ids = set()
        unique_rows = []
        for r in rows:
            rid = r.get("id")
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            unique_rows.append(r)
        return JsonResponse(_serialize_anomalie_rows(unique_rows), safe=False)
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
        # Diagnostica upload (prod): traccia destinazione e scrivibilità reale.
        try:
            probe = folder / f".write_test_{uuid4().hex}.tmp"
            with probe.open("wb") as _fh:
                _fh.write(b"ok")
            probe.unlink()
            writable_ok = True
            writable_err = ""
        except OSError as _wexc:
            writable_ok = False
            writable_err = str(_wexc)
        logger.info(
            "[anomalie] allegati_upload start local_id=%s op=%s dir=%s scrivibile=%s%s file_count=%s",
            local_id, op_id, folder, writable_ok,
            f" err={writable_err}" if writable_err else "", len(files),
        )
        # Fail-fast esplicito: se la cartella destinazione non è scrivibile (es.
        # ANOMALIE_ATTACHMENTS_DIR errato o senza permessi IIS_IUSRS in prod), NON
        # restituire un falso successo. Errore chiaro + log, così il problema non
        # resta silenzioso ("messaggio verde" ma file mai salvato).
        if not writable_ok:
            logger.error(
                "[anomalie] allegati_upload cartella non scrivibile local_id=%s op=%s dir=%s err=%s",
                local_id, op_id, folder, writable_err,
            )
            return _json_error(
                f"Cartella allegati non scrivibile sul server ({folder}): {writable_err}",
                status=500,
            )
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
            try:
                with target.open("wb") as dest:
                    for chunk in f.chunks():
                        dest.write(chunk)
            except OSError as wexc:
                # Es. cartella non scrivibile da IIS_IUSRS in prod: non abbattere
                # l'intero upload, registra l'errore per-file e prosegui.
                logger.error(
                    "[anomalie] allegati_upload scrittura fallita local_id=%s file=%s target=%s: %s",
                    local_id, safe_name, target, wexc,
                )
                errors.append(f"{original}: scrittura fallita ({wexc})")
                continue
            saved += 1
            saved_file_ids.append(file_id)
            saved_names.append(safe_name)

        logger.info(
            "[anomalie] allegati_upload done local_id=%s op=%s saved=%s errors=%s",
            local_id, op_id, saved, len(errors),
        )

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
        "avanzamento": _safe_text(data.get("avanzamento"), 100) or "In attesa",
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
    # AU-GAP1: traccia CHI modifica l'anomalia, cosi' il trigger SQL puo' proiettare
    # modified_by_user_id nel payload automazioni e le regole possono filtrare per ruolo
    # (il ruolo CC/CAR viene poi risolto a runtime da _enrich_anomalie_payload).
    if "modified_by_user_id" in cols and legacy_user:
        insert_writable["modified_by_user_id"] = legacy_user.id
        update_writable["modified_by_user_id"] = legacy_user.id

    where_clause = None
    where_params: list = []
    local_pk_id = None

    # La chiave d'identita' e' sempre la PK locale `id`. `item_id` arriva come
    # "local:<id>"; per retro-compatibilita' si accetta anche un id numerico
    # nudo (vecchi link). `sharepoint_item_id` non e' piu' usata come chiave.
    if item_id and "id" in cols:
        raw = item_id.split(":", 1)[1] if item_id.lower().startswith("local:") else item_id
        try:
            local_pk_id = int(raw)
            where_clause = "id = %s"
            where_params = [local_pk_id]
        except ValueError:
            pass

    # Stato precedente (solo per UPDATE), per la timeline AnomaliaActionLog.
    previous_status = ""
    if where_clause == "id = %s" and local_pk_id is not None:
        try:
            with connections["default"].cursor() as pre_cur:
                pre_cur.execute(
                    "SELECT avanzamento, chiudere FROM anomalie WHERE id = %s",
                    [local_pk_id],
                )
                pre_row = pre_cur.fetchone()
            if pre_row is not None:
                prev_av = str(pre_row[0] or "").strip()
                prev_chiuso = bool(pre_row[1])
                previous_status = "Chiusa" if prev_chiuso else (prev_av or "In attesa")
        except DatabaseError:
            logger.warning("api_salva: lettura stato precedente fallita id=%s", local_pk_id, exc_info=True)

    try:
        with connections["default"].cursor() as cursor:
            updated = 0
            if where_clause:
                set_sql_parts = []
                set_params: list = []
                for col, val in update_writable.items():
                    quoted_col = _quote_identifier(col)
                    if isinstance(val, tuple) and val[0] == "__sql__":
                        set_sql_parts.append(f"{quoted_col} = {val[1]}")
                    else:
                        set_sql_parts.append(f"{quoted_col} = %s")
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
                # OUTPUT INSERTED non è compatibile con trigger su SQL Server (err 334);
                # si usa SCOPE_IDENTITY() + SELECT separato.
                quoted_insert_cols = _quoted_columns(insert_cols)
                cursor.execute(
                    f"INSERT INTO anomalie ({quoted_insert_cols}) VALUES ({', '.join(insert_placeholders)})",
                    insert_params,
                )
                cursor.execute("SELECT CAST(SCOPE_IDENTITY() AS INT)")
                id_row = cursor.fetchone()
                local_id = int(id_row[0]) if id_row and id_row[0] is not None else None
            else:
                if where_clause == "id = %s":
                    cursor.execute("SELECT id FROM anomalie WHERE id = %s", [where_params[0]])
                else:
                    cursor.execute("SELECT TOP 1 id FROM anomalie ORDER BY id DESC")
                row = cursor.fetchone()
                local_id = int(row[0]) if row and row[0] is not None else None

        returned_item_id = f"local:{local_id}" if local_id is not None else None

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

        # Timeline azioni (fire-and-forget): registra il cambio stato dal portale
        # cosi' AnomaliaActionLog copre sia il canale mail sia quello web.
        try:
            new_status = "Chiusa" if chiudere_val else (payload_map.get("avanzamento") or "In attesa")
            action_kind = "crea" if updated <= 0 else ("chiudi" if chiudere_val else "aggiorna")
            identity = _current_user_identity(request)
            from anomalie.mail_action_service import log_anomalia_portal_action
            log_anomalia_portal_action(
                anomalia_id=local_id,
                op_id=op_id,
                action=action_kind,
                user=request.user,
                legacy_user_id=int(legacy_user.id) if legacy_user else None,
                user_display=identity.get("name") or request.user.username,
                previous_status=previous_status,
                new_status=new_status,
                ip_address=(request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
                            or request.META.get("REMOTE_ADDR") or None),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )
        except Exception:
            logger.warning("api_salva: timeline log fallita op=%s", op_id, exc_info=True)

        # Notifiche in-app (fire-and-forget)
        sn_val = _safe_text(data.get("sn")) or ""
        if segnalare_val:
            _notify_anomalia_event(request, "segnalare", local_id, op_id, sn_val)
        if chiudere_val:
            _notify_anomalia_event(request, "chiudere", local_id, op_id, sn_val)

        # Mail di conferma post-salvataggio: parte SEMPRE, su qualsiasi salvataggio
        # (INSERT di nuova anomalia o UPDATE), da qualsiasi pulsante. Per evitare di
        # inondare CC/CAR quando si salva più volte di fila sullo stesso OP, l'invio è
        # gestito dalla coda di DEBOUNCE: `register_pending_update` accumula gli update e
        # il task periodico `anomalie_pending_notifications` invia UNA mail riepilogativa
        # quando l'OP è fermo da più della soglia (~5 min). Niente più ramo "immediato"
        # legato a un bottone dedicato: la notifica è implicita in ogni "Salva".
        if local_id is not None:
            try:
                identity = _current_user_identity(request)
                modified_by = identity.get("name") or request.user.username
                update_row = {
                    "id": local_id,
                    "seriale": sn_val,
                    "avanzamento": payload_map.get("avanzamento") or "",
                    "descrizione": _safe_text(data.get("desc")) or "",
                    "numero_rdc": _safe_text(data.get("numero_rdc"), 100) or "",
                    "pezzi_recuperato": bool(_as_bool_int(data.get("pezzi_prec"))),
                    "note": _safe_text(data.get("note")) or "",
                    "aprire_rdc": bool(payload_map.get("aprire_rdc")),
                    "segnalare": bool(segnalare_val),
                    "chiudere": bool(chiudere_val),
                }
                from anomalie.mail_action_service import register_pending_update
                register_pending_update(
                    op_id=op_id,
                    op_nominativo=op_id,
                    update_row=update_row,
                    modified_by=modified_by,
                )
            except Exception:
                logger.warning("api_salva: gestione conferma salvataggio fallita op=%s", op_id, exc_info=True)

        return JsonResponse(
            {
                "success": True,
                "item_id": returned_item_id,
                "local_id": local_id,
            }
        )
    except DatabaseError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=500)


# Etichette leggibili per le action loggate (mail + portale), per la timeline.
_TIMELINE_ACTION_LABELS = {
    "crea": "Anomalia creata",
    "aggiorna": "Anomalia aggiornata",
    "chiudi": "Anomalia chiusa",
    "prendi_in_carico": "Presa in carico",
    "approva": "Approvata",
    "respingi": "Respinta",
    "richiedi_modifica": "Richiesta modifica",
    "visualizza": "Visualizzata",
}

# Etichette canale (AnomaliaActionLog.Source) per la timeline.
_TIMELINE_SOURCE_LABELS = {
    "mail_action": "Link da mail",
    "portal": "Portale",
    "system": "Sistema",
}


@login_required
def api_anomalie_timeline(request):
    """Timeline aggregata delle azioni su un OP (lettura AnomaliaActionLog).

    Aggrega per OP: raccoglie gli id anomalia legacy dell'OP e restituisce i log
    sia per quegli id sia per op_id (così copre anche azioni storiche su righe
    poi rimosse). Sola lettura: accessibile a qualsiasi utente autenticato,
    coerente con _can_view_anomalie_for_op.
    """
    op_title = _safe_text(request.GET.get("op_id"), 100)
    op_item_id = request.GET.get("op_item_id") or request.GET.get("sp_item_id")
    if not op_title and not op_item_id:
        return JsonResponse({"items": []})
    if not _can_view_anomalie_for_op(request, op_title):
        return _json_error("Permesso negato", status=403)

    from django.db.models import Q

    from anomalie.mail_action_models import AnomaliaActionLog

    # Id anomalie dell'OP dalla tabella legacy (match per lookup id e/o titolo).
    anomalia_ids: list[int] = []
    if _has_table("anomalie"):
        where_parts: list[str] = []
        params: list = []
        resolved = _resolve_op_lookup_id(op_item_id, op_title)
        if resolved is not None:
            where_parts.append("op_lookup_id = %s")
            params.append(resolved)
        if op_title:
            if connections["default"].vendor == "sqlite":
                where_parts.append("LOWER(ex_op_nominativo) = LOWER(%s)")
            else:
                where_parts.append("LOWER(CAST(ex_op_nominativo AS NVARCHAR(MAX))) = LOWER(%s)")
            params.append(op_title)
        if where_parts:
            try:
                rows = _fetch_all_dict(
                    f"SELECT id FROM anomalie WHERE {' OR '.join(where_parts)}", params
                )
                anomalia_ids = [int(r["id"]) for r in rows if r.get("id") is not None]
            except DatabaseError:
                logger.warning("api_anomalie_timeline: lettura id anomalie fallita op=%s", op_title, exc_info=True)

    filt = Q()
    if anomalia_ids:
        filt |= Q(anomalia_id__in=anomalia_ids)
    if op_title:
        filt |= Q(op_id=op_title)
    if not filt:
        return JsonResponse({"items": []})

    try:
        logs = list(
            AnomaliaActionLog.objects.filter(filt).order_by("-created_at")[:200]
        )
    except Exception:
        logger.warning("api_anomalie_timeline: lettura log fallita op=%s", op_title, exc_info=True)
        return JsonResponse({"items": []})

    # NB: il `timezone` di modulo e' datetime.timezone (stdlib); per localtime
    # serve django.utils.timezone, importato localmente con alias.
    from django.utils import timezone as dj_tz

    items = []
    for log in logs:
        items.append({
            "id": log.id,
            "anomalia_id": log.anomalia_id,
            "action": log.action,
            "action_label": _TIMELINE_ACTION_LABELS.get(log.action, log.action or "Azione"),
            "user": log.user_display or "—",
            "previous_status": log.previous_status or "",
            "new_status": log.new_status or "",
            "note": log.note or "",
            "source": log.source,
            "source_label": _TIMELINE_SOURCE_LABELS.get(log.source, log.source or ""),
            "created_at": dj_tz.localtime(log.created_at).strftime("%d-%m-%Y %H:%M") if log.created_at else "",
        })
    return JsonResponse({"items": items})


@login_required
def api_seriali_op(request):
    """Ritorna i seriali con anomalie APERTE sull'OP, per il check duplicati live.

    Risposta: {"seriali": ["LCN0001", "LCN0005", ...]}. I seriali compositi
    (range "LCN0001-LCN0010" o liste "LCN0001, LCN0005") vengono espansi nei
    singoli token così il confronto lato client copre anche i pezzi dentro un range.
    """
    op_id = _safe_text(request.GET.get("op_id"), 100)
    if not op_id:
        return JsonResponse({"seriali": []})
    if not _has_table("anomalie"):
        return JsonResponse({"seriali": []})
    try:
        with connections["default"].cursor() as cur:
            if connections["default"].vendor == "sqlite":
                sql = (
                    "SELECT seriale FROM anomalie WHERE LOWER(ex_op_nominativo) = LOWER(%s) "
                    "AND (chiudere IS NULL OR chiudere = 0)"
                )
            else:
                sql = (
                    "SELECT seriale FROM anomalie WHERE LOWER(CAST(ex_op_nominativo AS NVARCHAR(MAX))) = LOWER(%s) "
                    "AND (chiudere IS NULL OR chiudere = 0)"
                )
            cur.execute(sql, [op_id])
            raw = [str(r[0] or "").strip() for r in cur.fetchall()]
    except DatabaseError:
        logger.warning("api_seriali_op: lettura fallita op=%s", op_id, exc_info=True)
        return JsonResponse({"seriali": []})

    # Espandi range numerici e liste in singoli token per il confronto duplicati.
    seriali: set[str] = set()
    for val in raw:
        if not val:
            continue
        # rimuovi eventuale suffisso "(N pezzi)"
        base = re.sub(r"\s*\(\d+\s*pezz[io]\)\s*$", "", val, flags=re.IGNORECASE).strip()
        # lista separata da virgola
        if "," in base:
            for tok in base.split(","):
                tok = tok.strip()
                if tok:
                    seriali.add(tok)
            continue
        # range con trattino: prefisso + numero
        m = re.match(r"^(.*?)(\d+)\s*-\s*(?:\1)?(\d+)$", base)
        if m:
            prefix, a, b = m.group(1), m.group(2), m.group(3)
            try:
                na, nb = int(a), int(b)
                pad = len(a)
                if na <= nb and nb - na <= 1000:
                    for i in range(na, nb + 1):
                        seriali.add(f"{prefix}{str(i).zfill(pad)}")
                    continue
            except ValueError:
                pass
        seriali.add(base)

    return JsonResponse({"seriali": sorted(seriali)})


def _op_is_benestare(op_title: str) -> bool:
    """True se l'OP è un collaudo di benestare (ordini_produzione.stato = 'Benestare')."""
    op_str = str(op_title or "").strip()
    if not op_str:
        return False
    try:
        with connections["default"].cursor() as cur:
            cur.execute(
                "SELECT TOP 1 stato FROM ordini_produzione WHERE LOWER(title) = LOWER(%s)"
                if connections["default"].vendor != "sqlite"
                else "SELECT stato FROM ordini_produzione WHERE LOWER(title) = LOWER(%s) LIMIT 1",
                [op_str],
            )
            row = cur.fetchone()
        if row:
            return "benestare" in str(row[0] or "").strip().lower()
    except DatabaseError:
        logger.warning("_op_is_benestare: lettura stato fallita op=%s", op_str, exc_info=True)
    return False


# Code della regola automazione che gestisce la notifica mail-action OP.
# La regola è gestibile da /automazioni/regole/ (destinatari via action config,
# scadenza link, attiva/disattiva). L'endpoint la invoca a richiesta sul "Salva ed esci".
ANOMALIE_NOTIFICA_OP_RULE_CODE = "au51-anomalia-creata-mail-action-op"


@login_required
@require_POST
def api_notifica_op(request):
    """Invia la mail-action aggregata a CC/CAR dell'OP eseguendo la regola automazione.

    Chiamato dal frontend al 'Salva ed esci'. Invece di mandare la mail in modo
    diretto, esegue la regola automazione `ANOMALIE_NOTIFICA_OP_RULE_CODE` via
    `run_rule(...)`: così la configurazione (action, destinatari, scadenza link,
    attivazione) vive nella regola gestibile da UI e ogni invio finisce nel run log.

    Il trigger resta il bottone (non l'insert): nessun cooldown, nessun doppione.
    Se la regola non esiste o è disattivata, non viene inviata alcuna mail.
    """
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return _json_error("Body JSON non valido", status=400)
    if not isinstance(data, dict):
        return _json_error("Body JSON non valido", status=400)

    op_id = _safe_text(data.get("op_id"), 100)
    if not op_id:
        return _json_error("op_id obbligatorio", status=400)
    if not _can_edit_anomalie_for_op(request, op_id):
        return _json_error("Permesso negato: non autorizzato su questo OP", status=403)

    from automazioni.models import AutomationRule
    from automazioni.services import run_rule, _fetch_anomalie_by_op

    # Niente mail se non ci sono anomalie aperte sull'OP.
    anomalie_rows = _fetch_anomalie_by_op(op_id)
    if not anomalie_rows:
        return JsonResponse({"success": True, "sent": False, "reason": "no_open_anomalie"})

    rule = (
        AutomationRule.objects.filter(code=ANOMALIE_NOTIFICA_OP_RULE_CODE, is_active=True)
        .order_by("id")
        .first()
    )
    if rule is None:
        # Regola assente o disattivata: gestione interamente da UI, nessun invio.
        return JsonResponse({"success": True, "sent": False, "reason": "rule_inactive"})

    # Il payload deve contenere ex_op_nominativo (per risolvere CC/CAR e anomalie)
    # e il pk dell'anomalia (richiesto dall'handler dell'action). Usa la prima aperta.
    first_anomalia_id = anomalie_rows[0].get("id")
    payload = {
        "id": first_anomalia_id,
        "ex_op_nominativo": op_id,
    }

    try:
        run_log = run_rule(rule, payload, initiated_by=request.user)
    except Exception as exc:
        logger.warning("api_notifica_op: run_rule fallita op=%s: %s", op_id, exc, exc_info=True)
        return JsonResponse({"success": False, "sent": False, "reason": "run_error", "error": str(exc)}, status=500)

    try:
        log_action(request, "anomalia_notifica_op", "anomalie", {
            "op_id": op_id,
            "rule_code": ANOMALIE_NOTIFICA_OP_RULE_CODE,
            "run_log_id": run_log.id,
            "run_status": run_log.status,
            "n_anomalie": len(anomalie_rows),
        })
    except Exception:
        pass

    sent = run_log.status == "success"
    return JsonResponse({
        "success": True,
        "sent": sent,
        "run_log_id": run_log.id,
        "run_status": run_log.status,
        "n_anomalie": len(anomalie_rows),
    })


@login_required
def api_sync(request):
    return _json_error("Sincronizzazione SharePoint non disponibile", status=410)


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
        if action in {"create_role", "delete_role", "save_roles"}:
            return _handle_anomalie_roles_post(request)
        if action == "save_access":
            return _handle_anomalie_access_post(request)

    raw_tab = request.GET.get("tab")
    tab = _normalize_anomalie_settings_tab(raw_tab, default="config")
    permessi_sub = (
        _normalize_anomalie_permessi_sub(raw_tab, request.GET.get("sub"))
        if tab == "permessi"
        else ""
    )

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

    audit_entries = AuditLog.objects.filter(modulo="anomalie").order_by("-created_at")[:100]

    ruoli_context = {}
    if tab == "permessi" and permessi_sub == "ruoli":
        # Catalogo e assegnazioni sono di sola lettura: fonte unica = anagrafica.
        roster = get_roster_by_role()
        ruoli_catalog_rows = [
            {
                "id": item["ruolo"].id,
                "name": item["ruolo"].nome,
                "description": item["ruolo"].descrizione or "",
                "icona": item["ruolo"].icona or "",
                "colore": item["ruolo"].colore or "",
                "users": [
                    {"id": u.id, "label": u.get_full_name() or u.username, "email": u.email or ""}
                    for u in item["users"]
                ],
            }
            for item in roster
        ]
        total_assignments = sum(len(r["users"]) for r in ruoli_catalog_rows)
        ruoli_context = {
            "ruoli_system_rows": _anomalie_system_roles(),
            "ruoli_catalog_rows": ruoli_catalog_rows,
            "ruoli_anagrafica_url": _anomalie_ruoli_anagrafica_url(),
            "ruoli_stats": {
                "roles": len(ruoli_catalog_rows),
                "assignments": total_assignments,
                "total_users": len({u["id"] for r in ruoli_catalog_rows for u in r["users"]}),
            },
        }

    access_context = {}
    if tab == "permessi" and permessi_sub == "accessi":
        system_rows = _anomalie_system_roles()
        custom_roles = list(get_active_roles())
        access_filter_q = request.GET.get("q_access_user", "").strip()
        all_users = list(_anomalie_settings_users_queryset())
        filtered_users = _filter_anomalie_user_rows(all_users, access_filter_q)
        legacy_role_rows = _anomalie_legacy_role_rows()
        # Regole di sistema: chiave role_type; regole custom: chiave ruolo_operativo_id.
        system_rule_map = {
            role_type: {"access_level": access_level, "list_scope": list_scope}
            for role_type, access_level, list_scope in AnomalieRoleAccessRule.objects.filter(
                ruolo_operativo__isnull=True
            )
            .exclude(role_type="")
            .values_list("role_type", "access_level", "list_scope")
        }
        custom_rule_map = {
            ruolo_id: {"access_level": access_level, "list_scope": list_scope}
            for ruolo_id, access_level, list_scope in AnomalieRoleAccessRule.objects.filter(
                ruolo_operativo__isnull=False
            ).values_list("ruolo_operativo_id", "access_level", "list_scope")
        }
        legacy_role_rule_map = {
            role_id: {"access_level": access_level, "list_scope": list_scope}
            for role_id, access_level, list_scope in AnomalieLegacyRoleAccessRule.objects.values_list(
                "legacy_role_id", "access_level", "list_scope"
            )
        }
        user_rule_map = {
            user_id: {"access_level": access_level, "list_scope": list_scope}
            for user_id, access_level, list_scope in AnomalieUserAccessRule.objects.values_list(
                "user_id", "access_level", "list_scope"
            )
        }
        list_scope_choices = list(AnomalieListScope.choices)
        access_context = {
            "access_filter_q": access_filter_q,
            "access_role_rows": [
                {
                    "code": row["code"],
                    "label": row["name"],
                    "help": row["description"] or "Ruolo di sistema collegato all'OP.",
                    "access_level": system_rule_map.get(row["code"], {}).get(
                        "access_level", AnomalieAccessLevel.NONE
                    ),
                    "list_scope": system_rule_map.get(row["code"], {}).get(
                        "list_scope", AnomalieListScope.ALL
                    ),
                }
                for row in system_rows
            ],
            "access_custom_role_rows": [
                {
                    "id": ruolo.id,
                    "label": ruolo.nome,
                    "help": ruolo.descrizione or "Ruolo operativo (anagrafica): vale per gli utenti assegnati.",
                    "access_level": custom_rule_map.get(ruolo.id, {}).get("access_level", ""),
                    "list_scope": custom_rule_map.get(ruolo.id, {}).get("list_scope", AnomalieListScope.ALL),
                }
                for ruolo in custom_roles
            ],
            "access_custom_role_choices": [
                ("", "Nessuna regola extra"),
                (AnomalieAccessLevel.READ_ALL, "Vede tutte le anomalie"),
                (AnomalieAccessLevel.EDIT_ASSIGNED, "Modifica solo OP/anomalie in carico"),
                (AnomalieAccessLevel.EDIT_ALL, "Vede e modifica tutto il modulo"),
            ],
            "access_ruoli_anagrafica_url": _anomalie_ruoli_anagrafica_url(),
            "access_legacy_role_rows": [
                {
                    "id": row["id"],
                    "label": row["label"],
                    "access_level": legacy_role_rule_map.get(row["id"], {}).get("access_level", ""),
                    "list_scope": legacy_role_rule_map.get(row["id"], {}).get("list_scope", AnomalieListScope.ALL),
                }
                for row in legacy_role_rows
            ],
            "access_user_rows": [
                {
                    "id": user.id,
                    "label": user.get_full_name() or user.username,
                    "email": user.email or "",
                    "access_level": user_rule_map.get(user.id, {}).get("access_level", ""),
                    "list_scope": user_rule_map.get(user.id, {}).get("list_scope", AnomalieListScope.ALL),
                }
                for user in filtered_users
            ],
            "access_role_choices": [
                (AnomalieAccessLevel.NONE, "Nessun accesso extra"),
                (AnomalieAccessLevel.READ_ALL, "Vede tutte le anomalie"),
                (AnomalieAccessLevel.EDIT_ASSIGNED, "Modifica solo OP/anomalie in carico"),
                (AnomalieAccessLevel.EDIT_ALL, "Vede e modifica tutto il modulo"),
            ],
            "access_legacy_role_choices": [
                ("", "Nessuna regola extra"),
                (AnomalieAccessLevel.READ_ALL, "Vede tutto il modulo"),
                (AnomalieAccessLevel.EDIT_ASSIGNED, "Vede tutto + modifica solo OP/anomalie in carico"),
                (AnomalieAccessLevel.EDIT_ALL, "Vede e modifica tutto il modulo"),
            ],
            "access_user_choices": [
                ("", "Eredita scope standard"),
                (AnomalieAccessLevel.READ_ALL, "Vede tutto il modulo"),
                (AnomalieAccessLevel.EDIT_ASSIGNED, "Vede tutto + modifica solo OP/anomalie in carico"),
                (AnomalieAccessLevel.EDIT_ALL, "Vede e modifica tutto il modulo"),
            ],
            "list_scope_choices": list_scope_choices,
            "access_stats": {
                "role_rules": len(system_rule_map) + len(custom_rule_map),
                "custom_role_rules": len(custom_rule_map),
                "legacy_role_rules": len(legacy_role_rule_map),
                "user_overrides": len(user_rule_map),
                "edit_all_roles": sum(
                    1
                    for v in list(system_rule_map.values()) + list(custom_rule_map.values())
                    if v.get("access_level") == AnomalieAccessLevel.EDIT_ALL
                ),
                "edit_all_legacy_roles": sum(
                    1 for v in legacy_role_rule_map.values() if v.get("access_level") == AnomalieAccessLevel.EDIT_ALL
                ),
                "edit_all_users": sum(
                    1 for v in user_rule_map.values() if v.get("access_level") == AnomalieAccessLevel.EDIT_ALL
                ),
                "total_users": len(all_users),
                "filtered_users": len(filtered_users),
                "legacy_roles": len(legacy_role_rows),
            },
        }

    from anomalie.escalation_config import get_escalation_config

    context = {
        "page_title": "Gestione Anomalie",
        "username": display_name,
        "config_lists_json": json.dumps(_load_anomalie_lists(), ensure_ascii=False),
        "attachments_dir": _anomalie_attachments_dir_value(),
        "escalation_cfg": get_escalation_config(),
        "tab": tab,
        "permessi_sub": permessi_sub,
        "tabella_ok": tabella_ok,
        "stats": stats,
        "by_avanzamento": by_avanzamento,
        "anomalie_record": anomalie_record,
        "q_anomalie": q_anomalie,
        "audit_entries": audit_entries,
    }
    context.update(ruoli_context)
    context.update(access_context)
    return render(request, "anomalie/pages/anomalie_configurazione.html", context)


@login_required
def api_anomalie_config_liste(request):
    if request.method == "GET":
        return JsonResponse(
            {
                "success": True,
                "lists": _load_anomalie_lists(),
                "attachments_dir": _anomalie_attachments_dir_value(),
                "menu_logo": _load_anomalie_menu_logo(),
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
        if key in ANOMALIE_DERIVED_LIST_KEYS:
            continue  # derivato da anagrafica, non salvato nel JSON
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

    # Impostazioni promemoria & escalation (SiteConfig), se presenti nel payload.
    escalation_saved = None
    esc_payload = payload.get("escalation")
    if isinstance(esc_payload, dict):
        try:
            from anomalie.escalation_config import get_escalation_config, save_escalation_config
            save_escalation_config(
                attivo=bool(esc_payload.get("attivo")),
                soglia_ore=esc_payload.get("soglia_ore"),
                ora_invio=esc_payload.get("ora_invio"),
            )
            escalation_saved = get_escalation_config()
        except Exception:
            logger.exception("[anomalie] salvataggio escalation fallito")

    try:
        log_action(
            request,
            "anomalie_config_liste_update",
            "anomalie",
            {
                "keys": list(updated.keys()),
                "attachments_dir": saved_attachments_dir,
                "escalation": escalation_saved,
            },
        )
    except Exception:
        pass

    _apply_derived_anomalie_lists(updated)
    return JsonResponse({
        "success": True,
        "lists": updated,
        "attachments_dir": saved_attachments_dir,
        "escalation": escalation_saved,
    })


@login_required
@csrf_protect
@require_POST
def api_anomalie_config_logo(request):
    """Upload del logo personalizzato per il menu anomalie."""
    if not _can_manage_anomalie_config(request):
        return JsonResponse({"success": False, "error": "Permesso negato"}, status=403)
    uploaded = request.FILES.get("logo")
    if not uploaded:
        return JsonResponse({"success": False, "error": "Nessun file ricevuto"}, status=400)
    safe_name = safe_filename(uploaded.name)
    ext = Path(safe_name).suffix.lower() if safe_name else ""
    # Per il logo, usiamo whitelist allargata che include SVG (testuale) e
    # validazione MIME via libmagic per i formati binari. Bloccato fail-closed.
    binary_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    if ext == ".svg":
        size = int(getattr(uploaded, "size", 0) or 0)
        if size <= 0:
            return JsonResponse({"success": False, "error": "Logo: file vuoto"}, status=400)
        if size > 2 * 1024 * 1024:
            return JsonResponse({"success": False, "error": "Logo: supera il limite di 2 MB"}, status=400)
    elif ext in binary_exts:
        try:
            validate_extension_and_mime(
                uploaded,
                allowed_extensions=binary_exts,
                allowed_mimes={
                    "image/png", "image/jpeg", "image/gif", "image/webp",
                },
                max_bytes=2 * 1024 * 1024,
                label=safe_name or "Logo",
                allow_empty=False,
            )
        except UploadMimeValidationError as exc:
            return JsonResponse({"success": False, "error": str(exc)}, status=400)
    else:
        return JsonResponse({"success": False, "error": f"Formato non supportato: {ext or 'sconosciuto'}"}, status=400)
    logo_dir = Path(settings.MEDIA_ROOT) / "anomalie_logo"
    logo_dir.mkdir(parents=True, exist_ok=True)
    logo_path = logo_dir / f"menu_logo{ext}"
    # Rimuove eventuali loghi precedenti con estensione diversa
    for old in logo_dir.glob("menu_logo.*"):
        if old != logo_path:
            old.unlink(missing_ok=True)
    with open(logo_path, "wb") as fh:
        for chunk in uploaded.chunks():
            fh.write(chunk)
    logo_url = f"{settings.MEDIA_URL.rstrip('/')}/anomalie_logo/menu_logo{ext}"
    _save_anomalie_menu_logo(logo_url)
    return JsonResponse({"success": True, "url": logo_url})


@login_required
@csrf_protect
@require_POST
def api_anomalie_config_logo_reset(request):
    """Rimuove il logo personalizzato e ripristina quello di default."""
    if not _can_manage_anomalie_config(request):
        return JsonResponse({"success": False, "error": "Permesso negato"}, status=403)
    logo_dir = Path(settings.MEDIA_ROOT) / "anomalie_logo"
    for f in logo_dir.glob("menu_logo.*"):
        f.unlink(missing_ok=True)
    _save_anomalie_menu_logo("")
    return JsonResponse({"success": True})


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
    if not _can_export_anomalie(request):
        return HttpResponse("Permesso negato.", status=403)
    if not _has_table("anomalie"):
        return HttpResponse("Tabella anomalie non disponibile.", status=503)

    cols = legacy_table_columns("anomalie")
    wanted = [c for c in ["id", "ex_op_nominativo", "seriale", "descrizione",
                           "note_capocommessa", "numero_rdc", "avanzamento",
                           "created_datetime", "modified_datetime", "sharepoint_item_id"] if c in cols]
    if not wanted:
        wanted = list(cols)[:10]
    quoted_wanted = _quoted_columns(wanted)
    with connections["default"].cursor() as cur:
        cur.execute(f"SELECT TOP 5000 {quoted_wanted} FROM anomalie ORDER BY id DESC")
        rows_data = cur.fetchall()

    log_action(
        request,
        "export_csv",
        "anomalie",
        {
            "rows": len(rows_data),
            "filters": {"mode": "all", "limit": 5000},
        },
    )

    def stream():
        writer = csv.writer(_Echo())
        yield writer.writerow(wanted)
        for row in rows_data:
            yield writer.writerow([str(v) if v is not None else "" for v in row])

    resp = StreamingHttpResponse(stream(), content_type="text/csv; charset=utf-8-sig")
    resp["Content-Disposition"] = 'attachment; filename="anomalie.csv"'
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# Statistiche anomalie
# ─────────────────────────────────────────────────────────────────────────────


@login_required
def anomalie_statistiche_page(request):
    """Pagina statistiche ed estrazioni anomalie."""
    context = {
        "page_title": "Statistiche Anomalie",
        "db_has_anomalie": _has_table("anomalie"),
        "can_manage_config": _can_manage_anomalie_config(request),
    }
    return render(request, "anomalie/pages/anomalie_statistiche.html", context)


def _statistiche_where(request, cols: set[str]) -> tuple[list[str], list]:
    """Costruisce i frammenti WHERE condivisi tra statistiche, ricerca ed export."""
    da = request.GET.get("da", "").strip()
    a_val = request.GET.get("a", "").strip()
    avanzamento = request.GET.get("avanzamento", "").strip()
    capocommessa = request.GET.get("capocommessa", "").strip()
    stato = request.GET.get("stato", "").strip().lower()          # "", "aperte", "chiuse"
    rdc = request.GET.get("rdc", "").strip().lower()              # "", "si", "no"
    segnalazione = request.GET.get("segnalazione", "").strip().lower()
    q = request.GET.get("q", "").strip()

    where_parts: list[str] = []
    params: list = []

    if da and "created_datetime" in cols:
        where_parts.append("created_datetime >= %s")
        params.append(da)
    if a_val and "created_datetime" in cols:
        where_parts.append("created_datetime < %s")
        params.append(a_val + "T23:59:59")
    if avanzamento and "avanzamento" in cols:
        where_parts.append("avanzamento = %s")
        params.append(avanzamento)
    if capocommessa and "ex_op_nominativo" in cols:
        where_parts.append("ex_op_nominativo = %s")
        params.append(capocommessa)
    if stato == "aperte":
        where_parts.append("COALESCE(chiudere, 0) = 0")
    elif stato == "chiuse":
        where_parts.append("COALESCE(chiudere, 0) = 1")
    if rdc == "si" and "aprire_rdc" in cols:
        where_parts.append("COALESCE(aprire_rdc, 0) = 1")
    elif rdc == "no" and "aprire_rdc" in cols:
        where_parts.append("COALESCE(aprire_rdc, 0) = 0")
    if segnalazione == "si" and "segnalare_cliente" in cols:
        where_parts.append("COALESCE(segnalare_cliente, 0) = 1")
    elif segnalazione == "no" and "segnalare_cliente" in cols:
        where_parts.append("COALESCE(segnalare_cliente, 0) = 0")
    if q:
        text_cols = [c for c in ("seriale", "descrizione", "ex_op_nominativo", "note_capocommessa", "numero_rdc") if c in cols]
        if text_cols:
            like = "%" + q + "%"
            ors = " OR ".join(f"{_quote_identifier(c)} LIKE %s" for c in text_cols)
            where_parts.append("(" + ors + ")")
            params.extend([like] * len(text_cols))
    return where_parts, params


@login_required
def api_anomalie_statistiche(request):
    """Statistiche aggregate anomalie con filtri opzionali."""
    if not _has_table("anomalie"):
        return _json_error("Tabella anomalie non disponibile.", 503)

    cols = set(legacy_table_columns("anomalie"))
    where_parts, params = _statistiche_where(request, cols)

    def _where(extra: str = "") -> str:
        parts = list(where_parts) + ([extra] if extra else [])
        return ("WHERE " + " AND ".join(parts)) if parts else ""

    def _count(extra: str = "") -> int:
        return int((_fetch_all_dict(f"SELECT COUNT(*) AS n FROM anomalie {_where(extra)}", params) or [{"n": 0}])[0]["n"])

    totale = _count()
    chiuse = _count("COALESCE(chiudere, 0) = 1")
    rdc_aperti = _count("COALESCE(aprire_rdc, 0) = 1") if "aprire_rdc" in cols else 0
    segnalazioni = _count("COALESCE(segnalare_cliente, 0) = 1") if "segnalare_cliente" in cols else 0
    recuperati = _count("COALESCE(pezzo_recuperato, 0) = 1") if "pezzo_recuperato" in cols else 0
    in_attesa = 0
    if "avanzamento" in cols:
        params_attesa = list(params) + ["In attesa"]
        in_attesa = int(
            (_fetch_all_dict(f"SELECT COUNT(*) AS n FROM anomalie {_where('avanzamento = %s')}", params_attesa) or [{"n": 0}])[0]["n"]
        )

    # Tempo medio di gestione (giorni) per le anomalie chiuse: modified - created.
    tempo_medio_giorni = None
    if {"created_datetime", "modified_datetime", "chiudere"} <= cols:
        try:
            row = _fetch_all_dict(
                f"SELECT AVG(CAST(DATEDIFF(hour, created_datetime, modified_datetime) AS float)) AS h "
                f"FROM anomalie {_where('COALESCE(chiudere,0) = 1 AND modified_datetime IS NOT NULL')}",
                params,
            )
            if row and row[0].get("h") is not None:
                tempo_medio_giorni = round(float(row[0]["h"]) / 24.0, 1)
        except Exception:
            tempo_medio_giorni = None

    per_avanzamento: list[dict] = []
    if "avanzamento" in cols:
        per_avanzamento = _fetch_all_dict(
            f"SELECT COALESCE(avanzamento, '(non specificato)') AS avanzamento, COUNT(*) AS n "
            f"FROM anomalie {_where()} GROUP BY avanzamento ORDER BY n DESC",
            params,
        )

    per_mese: list[dict] = []
    if "created_datetime" in cols:
        try:
            per_mese = _fetch_all_dict(
                f"SELECT FORMAT(created_datetime, 'yyyy-MM') AS mese, COUNT(*) AS n "
                f"FROM anomalie {_where()} "
                f"GROUP BY FORMAT(created_datetime, 'yyyy-MM') ORDER BY mese DESC",
                params,
            )
        except Exception:
            per_mese = []

    # Top OP (nominativo) con più anomalie nel filtro corrente.
    per_op: list[dict] = []
    if "ex_op_nominativo" in cols:
        try:
            per_op = _fetch_all_dict(
                f"SELECT TOP 15 COALESCE(ex_op_nominativo, '(non specificato)') AS op, "
                f"COUNT(*) AS n, "
                f"SUM(CASE WHEN COALESCE(chiudere,0)=1 THEN 1 ELSE 0 END) AS chiuse "
                f"FROM anomalie {_where()} GROUP BY ex_op_nominativo ORDER BY n DESC",
                params,
            )
        except Exception:
            per_op = _fetch_all_dict(
                f"SELECT COALESCE(ex_op_nominativo, '(non specificato)') AS op, COUNT(*) AS n, 0 AS chiuse "
                f"FROM anomalie {_where()} GROUP BY ex_op_nominativo ORDER BY n DESC",
                params,
            )[:15]

    avanzamenti_list: list[str] = []
    if "avanzamento" in cols:
        avanzamenti_list = [
            str(r["avanzamento"])
            for r in _fetch_all_dict(
                "SELECT DISTINCT avanzamento FROM anomalie "
                "WHERE avanzamento IS NOT NULL AND avanzamento != '' ORDER BY avanzamento"
            )
        ]

    capocommessa_list: list[str] = []
    if "ex_op_nominativo" in cols:
        capocommessa_list = [
            str(r["ex_op_nominativo"])
            for r in _fetch_all_dict(
                "SELECT DISTINCT ex_op_nominativo FROM anomalie "
                "WHERE ex_op_nominativo IS NOT NULL AND ex_op_nominativo != '' ORDER BY ex_op_nominativo"
            )
        ]

    return JsonResponse({
        "totale": totale,
        "aperte": totale - chiuse,
        "chiuse": chiuse,
        "rdc_aperti": rdc_aperti,
        "segnalazioni": segnalazioni,
        "recuperati": recuperati,
        "in_attesa": in_attesa,
        "tempo_medio_giorni": tempo_medio_giorni,
        "per_avanzamento": [dict(r) for r in per_avanzamento],
        "per_mese": [dict(r) for r in per_mese],
        "per_op": [dict(r) for r in per_op],
        "avanzamenti_disponibili": avanzamenti_list,
        "capocommessa_disponibili": capocommessa_list,
    })


@login_required
def api_anomalie_ricerca(request):
    """Tabella di ricerca dettaglio anomalie, paginata, con gli stessi filtri delle statistiche."""
    if not _has_table("anomalie"):
        return _json_error("Tabella anomalie non disponibile.", 503)

    cols = set(legacy_table_columns("anomalie"))
    where_parts, params = _statistiche_where(request, cols)
    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    try:
        page = max(1, int(request.GET.get("page", "1")))
    except ValueError:
        page = 1
    page_size = 25
    offset = (page - 1) * page_size

    totale = int((_fetch_all_dict(f"SELECT COUNT(*) AS n FROM anomalie {where_clause}", params) or [{"n": 0}])[0]["n"])

    wanted = [
        c for c in (
            "id", "ex_op_nominativo", "seriale", "descrizione",
            "avanzamento", "numero_rdc", "aprire_rdc", "segnalare_cliente",
            "chiudere", "created_datetime", "modified_datetime",
        )
        if c in cols
    ]
    quoted = _quoted_columns(wanted)
    order_col = "id" if "id" in cols else wanted[0]
    sql = (
        f"SELECT {quoted} FROM anomalie {where_clause} "
        f"ORDER BY {_quote_identifier(order_col)} DESC "
        f"OFFSET %s ROWS FETCH NEXT %s ROWS ONLY"
    )
    try:
        rows = _fetch_all_dict(sql, list(params) + [offset, page_size])
    except Exception:
        # Fallback per backend senza OFFSET/FETCH (es. SQLite in dev).
        sql_lim = f"SELECT {quoted} FROM anomalie {where_clause} ORDER BY {_quote_identifier(order_col)} DESC LIMIT %s OFFSET %s"
        rows = _fetch_all_dict(sql_lim, list(params) + [page_size, offset])

    def _clean(r: dict) -> dict:
        out = {}
        for k, v in r.items():
            out[k] = v.isoformat() if hasattr(v, "isoformat") else v
        return out

    return JsonResponse({
        "totale": totale,
        "page": page,
        "page_size": page_size,
        "pages": (totale + page_size - 1) // page_size if totale else 0,
        "righe": [_clean(r) for r in rows],
    })


@login_required
def export_anomalie_csv_filtrato(request):
    """Export CSV anomalie con filtri (da, a, avanzamento, capocommessa)."""
    if not _can_export_anomalie(request):
        return HttpResponse("Permesso negato.", status=403)
    if not _has_table("anomalie"):
        return HttpResponse("Tabella anomalie non disponibile.", status=503)

    cols_all = legacy_table_columns("anomalie")
    wanted = [
        c for c in [
            "id", "ex_op_nominativo", "seriale", "descrizione",
            "note_capocommessa", "numero_rdc", "avanzamento",
            "chiudere", "created_datetime", "modified_datetime",
        ]
        if c in cols_all
    ] or list(cols_all)[:10]

    where_parts, params = _statistiche_where(request, set(cols_all))
    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    quoted_wanted = _quoted_columns(wanted)
    sql = f"SELECT TOP 5000 {quoted_wanted} FROM anomalie {where_clause} ORDER BY id DESC"
    with connections["default"].cursor() as cur:
        cur.execute(sql, params)
        rows_data = cur.fetchall()

    log_action(
        request,
        "export_csv",
        "anomalie",
        {
            "rows": len(rows_data),
            "filters": {k: request.GET.get(k, "") for k in ("da", "a", "avanzamento", "capocommessa", "stato", "rdc", "segnalazione", "q")},
            "limit": 5000,
        },
    )

    def stream():
        writer = csv.writer(_Echo())
        yield writer.writerow(wanted)
        for row in rows_data:
            yield writer.writerow([str(v) if v is not None else "" for v in row])

    resp = StreamingHttpResponse(stream(), content_type="text/csv; charset=utf-8-sig")
    resp["Content-Disposition"] = 'attachment; filename="anomalie_export.csv"'
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# Report riepilogativo OP
# ─────────────────────────────────────────────────────────────────────────────

_REPORT_TEMPLATE_FILENAME = "anomalie_report_template.html"
_REPORT_TEMPLATE_MAX_SIZE = 512 * 1024  # 512 KB
_REPORT_REQUIRED_PLACEHOLDER_GROUPS = [
    ("{{ op.id }}", "{{ anomalia.seriale }}", "{{ anomalia.descrizione }}"),
    ("{{ anomalia.id }}", "{{ anomalia.seriale }}", "{{ anomalia.descrizione }}"),
]
_EXTERNAL_SCRIPT_RE = re.compile(r'<script[^>]+src\s*=\s*["\']https?://', re.IGNORECASE)


def _report_template_path() -> Path:
    return _repo_root() / "config" / _REPORT_TEMPLATE_FILENAME


def _default_report_template_path() -> Path:
    return _repo_root() / "django_app" / "anomalie" / "templates" / "anomalie" / "pages" / "report_segnalazione.html"


def _load_report_template() -> str | None:
    p = _report_template_path()
    return p.read_text(encoding="utf-8") if p.exists() else None


def _validate_report_template(content: bytes, filename: str) -> list[str]:
    """Valida un template HTML per il report riepilogativo OP."""
    errors: list[str] = []
    if not filename.lower().endswith(".html"):
        errors.append("Sono accettati solo file .html.")
    if len(content) > _REPORT_TEMPLATE_MAX_SIZE:
        errors.append("Il file supera il limite di 512 KB.")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        errors.append("Il file deve essere in formato UTF-8.")
        return errors
    has_required_group = any(all(placeholder in text for placeholder in group) for group in _REPORT_REQUIRED_PLACEHOLDER_GROUPS)
    if not has_required_group:
        errors.append(
            "Il template deve includere i placeholder del report OP "
            "({{ op.id }}, {{ anomalia.seriale }}, {{ anomalia.descrizione }}) "
            "oppure quelli legacy della singola anomalia."
        )
    if _EXTERNAL_SCRIPT_RE.search(text):
        errors.append("Il template non può caricare script da domini esterni (<script src=\"https://...\">).")
    return errors


def _report_default_template_response() -> HttpResponse:
    content = _default_report_template_path().read_text(encoding="utf-8")
    response = HttpResponse(content, content_type="text/html; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="report_default_op.html"'
    return response


def _report_focus_anomaly_row(local_id: int) -> dict | None:
    rows = _fetch_all_dict(
        """
        SELECT TOP 1 id, op_lookup_id, ex_op_nominativo
        FROM anomalie
        WHERE id = %s
        """,
        [int(local_id)],
    )
    return rows[0] if rows else None


def _report_op_row(op_item_id: int | None, op_title: str | None) -> dict | None:
    if not _has_table("ordini_produzione"):
        return None

    sql = f"""
        SELECT TOP 1
            {OP_ITEM_ID_COL},
            title,
            part_number,
            incaricato,
            capocomessa,
            stato,
            in1text,
            created_datetime,
            modified_datetime
        FROM ordini_produzione
        WHERE {{where_clause}}
        ORDER BY id DESC
    """
    if op_item_id is not None:
        rows = _fetch_all_dict(sql.format(where_clause=f"TRY_CAST({OP_ITEM_ID_COL} AS INT) = %s"), [int(op_item_id)])
        if rows:
            return rows[0]
    if op_title:
        rows = _fetch_all_dict(sql.format(where_clause="title = %s"), [str(op_title)])
        if rows:
            return rows[0]
    return None


def _report_anomalie_rows(op_item_id: int | None, op_title: str | None) -> list[dict]:
    cols = set(legacy_table_columns("anomalie"))
    select_cols = [
        "id",
        "sharepoint_item_id",
        "ex_op_nominativo",
        "seriale",
        "descrizione",
        "note_capocommessa",
        "pezzo_recuperato",
        "aprire_rdc",
        "segnalare_cliente",
        "chiudere",
        "avanzamento",
    ]
    for optional_col in ("numero_rdc", "created_datetime", "modified_datetime"):
        if optional_col in cols:
            select_cols.append(optional_col)
    quoted_select_cols = _quoted_columns(select_cols)

    where_parts: list[str] = []
    params: list[object] = []
    if op_item_id is not None:
        where_parts.append("op_lookup_id = %s")
        params.append(int(op_item_id))
    if op_title:
        where_parts.append("ex_op_nominativo = %s")
        params.append(str(op_title))
    if not where_parts:
        return []

    sql = f"""
        SELECT {quoted_select_cols}
        FROM anomalie
        WHERE {" OR ".join(where_parts)}
        ORDER BY seriale, id
    """
    return _fetch_all_dict(sql, params)


def _serialize_report_anomalia(row: dict) -> dict:
    local_id = int(row["id"]) if row.get("id") is not None else None
    attachments: list[dict] = []
    if local_id is not None:
        try:
            attachments = _list_attachments_for_local(local_id)
        except Exception:
            logger.exception("[anomalie] impossibile leggere allegati report local_id=%s", local_id)
            attachments = []

    data = {k: (str(v) if v is not None else "") for k, v in row.items()}
    data.update(
        {
            "local_id": local_id,
            "item_id": _display_item_id(row),
            "is_closed": bool(row.get("chiudere")),
            "aprire_rdc_bool": bool(row.get("aprire_rdc")),
            "segnalare_cliente_bool": bool(row.get("segnalare_cliente")),
            "pezzo_recuperato_bool": bool(row.get("pezzo_recuperato")),
            "attachments": attachments,
            "attachments_count": len(attachments),
        }
    )
    return data


def _render_op_report_pdf(request, context: dict) -> HttpResponse:
    """Genera il PDF del report OP dal contesto già costruito per la resa HTML."""
    try:
        from anomalie.services.report_pdf import build_op_report_pdf_bytes

        pdf_bytes = build_op_report_pdf_bytes(
            context.get("op") or {},
            context.get("report") or {},
            context.get("anomalie") or [],
            attachment_path_resolver=_attachment_file_path,
        )
    except Exception:
        logger.exception("[anomalie] generazione report PDF fallita")
        return HttpResponse("Generazione PDF non riuscita.", status=500)

    op_id = str((context.get("op") or {}).get("id") or "OP").strip() or "OP"
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", op_id).strip("_") or "OP"
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="report_{safe_name}.pdf"'
    return resp


@login_required
def report_segnalazione_html(request):
    """Genera un report HTML stampabile per un OP e le sue anomalie collegate."""
    if request.GET.get("_tpl_default"):
        return _report_default_template_response()

    if not _has_table("anomalie"):
        return HttpResponse("Tabella anomalie non disponibile.", status=503)

    anomalia_id_raw = str(request.GET.get("id") or "").strip()
    op_item_id_raw = str(request.GET.get("op_item_id") or "").strip()
    op_title = _safe_text(request.GET.get("op_id"), 100)

    anomalia_id: int | None = None
    if anomalia_id_raw:
        try:
            anomalia_id = int(anomalia_id_raw)
        except ValueError:
            return HttpResponse("ID anomalia non valido.", status=400)

    op_item_id: int | None = None
    if op_item_id_raw:
        try:
            op_item_id = int(op_item_id_raw)
        except ValueError:
            return HttpResponse("OP item_id non valido.", status=400)

    if anomalia_id is None and op_item_id is None and not op_title:
        return HttpResponse("Parametro mancante: usa 'op_item_id', 'op_id' oppure 'id'.", status=400)

    focus_row = None
    if anomalia_id is not None:
        focus_row = _report_focus_anomaly_row(anomalia_id)
        if not focus_row:
            return HttpResponse("Anomalia non trovata.", status=404)
        if op_item_id is None:
            try:
                op_item_id = int(focus_row.get("op_lookup_id"))
            except (TypeError, ValueError):
                op_item_id = None
        op_title = op_title or _safe_text(focus_row.get("ex_op_nominativo"), 100)

    if op_item_id is None and op_title:
        op_item_id = _resolve_op_lookup_id(None, op_title)

    op_row = _report_op_row(op_item_id, op_title)
    if not op_title and op_row:
        op_title = _safe_text(op_row.get("title"), 100)

    rows = _report_anomalie_rows(op_item_id, op_title)
    if not rows and not op_row:
        return HttpResponse("Documento OP non trovato.", status=404)

    if not op_title and rows:
        op_title = _safe_text(rows[0].get("ex_op_nominativo"), 100)

    if op_title and not _can_view_anomalie_for_op(request, op_title):
        return HttpResponse("Permesso negato.", status=403)

    anomalie = [_serialize_report_anomalia(row) for row in rows]
    focus_anomalia = next((row for row in anomalie if row.get("local_id") == anomalia_id), None)
    if focus_anomalia is None and anomalie:
        focus_anomalia = anomalie[0]

    op = {
        "item_id": str((op_row or {}).get(OP_ITEM_ID_COL) or (op_item_id if op_item_id is not None else "") or ""),
        "id": str((op_row or {}).get("title") or op_title or ""),
        "pn": str((op_row or {}).get("part_number") or ""),
        "capo": str(_row_capocommessa(op_row or {}) or ""),
        "car": str((op_row or {}).get("incaricato") or ""),
        "stato": str((op_row or {}).get("stato") or ""),
        "info": str((op_row or {}).get("in1text") or ""),
        "created_datetime": str((op_row or {}).get("created_datetime") or ""),
        "modified_datetime": str((op_row or {}).get("modified_datetime") or ""),
    }
    anomalie_aperte = sum(1 for row in anomalie if not row.get("is_closed"))
    total_attachments = sum(int(row.get("attachments_count") or 0) for row in anomalie)
    focus_attachments = [str(item.get("name") or "") for item in (focus_anomalia or {}).get("attachments", [])]
    context = {
        "op": op,
        "report": {
            "anomalie_totali": len(anomalie),
            "anomalie_aperte": anomalie_aperte,
            "anomalie_chiuse": max(len(anomalie) - anomalie_aperte, 0),
            "allegati_totali": total_attachments,
            "generated_at": datetime.now().strftime("%d-%m-%Y %H:%M"),
            "focus_local_id": anomalia_id or "",
        },
        "anomalie": anomalie,
        "anomalia": focus_anomalia or {"id": "", "seriale": "", "descrizione": ""},
        "allegati": focus_attachments,
    }

    # Variante PDF: stessa fonte dati della resa HTML, veste sobria archiviabile.
    # Ignora il template HTML personalizzato (il PDF usa il layout strutturato
    # condiviso del portale, non il markup libero).
    if str(request.GET.get("format") or "").strip().lower() == "pdf":
        return _render_op_report_pdf(request, context)

    custom_tpl = _load_report_template()
    if custom_tpl:
        from django.template import Context, Template
        try:
            html = Template(custom_tpl).render(Context(context))
            return HttpResponse(html)
        except Exception as exc:
            logger.warning("Errore rendering template report personalizzato: %s", exc)
            # Fallback al template di default

    return render(request, "anomalie/pages/report_segnalazione.html", context)


# ─────────────────────────────────────────────────────────────────────────────
# Configurazione template report
# ─────────────────────────────────────────────────────────────────────────────


@login_required
@csrf_protect
def api_anomalie_config_report_template(request):
    """GET: stato template report. POST action=upload: carica nuovo. POST action=reset: ripristina default."""
    if not _can_manage_anomalie_config(request):
        return JsonResponse({"error": "Permesso negato"}, status=403)

    if request.method == "GET":
        p = _report_template_path()
        if p.exists():
            stat = p.stat()
            return JsonResponse({
                "has_custom": True,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d-%m-%Y %H:%M"),
            })
        return JsonResponse({"has_custom": False})

    if request.method == "POST":
        action = request.POST.get("action", "upload")
        if action == "reset":
            p = _report_template_path()
            if p.exists():
                p.unlink()
            log_action(request, "anomalie_report_template_reset", "Template report ripristinato al default")
            return JsonResponse({"success": True, "message": "Template ripristinato al default."})

        file_obj = request.FILES.get("template")
        if not file_obj:
            return JsonResponse({"success": False, "errors": ["Nessun file caricato."]})

        content = file_obj.read()
        errors = _validate_report_template(content, file_obj.name)
        if errors:
            return JsonResponse({"success": False, "errors": errors})

        p = _report_template_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        log_action(request, "anomalie_report_template_upload", f"Template report aggiornato: {file_obj.name}")
        return JsonResponse({"success": True, "message": f"Template '{file_obj.name}' caricato correttamente."})

    return _json_error("Metodo non supportato.", 405)
