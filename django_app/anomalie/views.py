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
from django.db.models import Max
from django.http import FileResponse, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.text import slugify
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

from .models import (
    AnomalieAccessLevel,
    AnomalieLegacyRoleAccessRule,
    AnomalieListScope,
    AnomalieRoleAccessRule,
    AnomalieRoleAssignment,
    AnomalieRoleDefinition,
    AnomalieRoleType,
    AnomalieUserAccessRule,
)


logger = logging.getLogger(__name__)
User = get_user_model()


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
    for code, name, description, order_index, default_access in SYSTEM_ANOMALIE_ROLE_DEFINITIONS:
        role, created = AnomalieRoleDefinition.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "description": description,
                "is_system": True,
                "is_active": True,
                "order_index": order_index,
            },
        )
        update_fields = []
        if not role.is_system:
            role.is_system = True
            update_fields.append("is_system")
        if not role.is_active:
            role.is_active = True
            update_fields.append("is_active")
        if update_fields:
            update_fields.append("updated_at")
            role.save(update_fields=update_fields)
        AnomalieRoleAccessRule.objects.get_or_create(
            role_type=code,
            defaults={"access_level": default_access},
        )


def _anomalie_role_definitions(*, include_inactive: bool = False) -> list[AnomalieRoleDefinition]:
    _ensure_system_anomalie_roles()
    qs = AnomalieRoleDefinition.objects.all()
    if not include_inactive:
        qs = qs.filter(is_active=True)
    return list(qs.order_by("order_index", "name", "id"))


def _anomalie_role_label_map() -> dict[str, str]:
    return {role.code: role.name for role in _anomalie_role_definitions(include_inactive=True)}


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

    # 3. Ruoli custom assegnati
    custom_role_codes = {
        role.code
        for role in _anomalie_role_definitions(include_inactive=False)
        if not role.is_system
    }
    if custom_role_codes:
        assigned_codes = list(
            AnomalieRoleAssignment.objects.filter(
                user=user, role_type__in=custom_role_codes
            ).values_list("role_type", flat=True)
        )
        if assigned_codes:
            scopes.extend(
                AnomalieRoleAccessRule.objects.filter(
                    role_type__in=assigned_codes
                ).values_list("list_scope", flat=True)
            )

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


def _list_attachments_for_local(local_id: int) -> list[dict]:
    folder = _attachment_dir_for_local(local_id, create=False)
    if not folder.exists():
        return []

    paths: list[Path] = []
    for path in folder.iterdir():
        if not path.is_file():
            continue
        file_id = path.name
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


def _capireparto_from_anagrafica() -> list[str]:
    """Nomi distinti dei capireparto dai reparti attivi in anagrafica."""
    try:
        from anagrafica.models import Reparto
        ids = set(
            Reparto.objects.filter(is_active=True, caporeparto_legacy_id__isnull=False)
            .exclude(caporeparto_legacy_id=0)
            .values_list("caporeparto_legacy_id", flat=True)
        )
        if not ids:
            return []
        names = []
        for u in UtenteLegacy.objects.filter(id__in=ids).values("id", "nome"):
            label = str(u.get("nome") or "").strip()
            if label:
                names.append(label)
        return sorted(set(names))
    except Exception:
        logger.debug("[anomalie] impossibile caricare capireparto da anagrafica", exc_info=True)
        return []


def _load_anomalie_lists() -> dict[str, list[str]]:
    data = _default_anomalie_lists()
    path = _anomalie_lists_path()
    if not path.exists():
        data["capi_reparto"] = _capireparto_from_anagrafica()
        return data
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("[anomalie] impossibile leggere file liste: %s", path)
        data["capi_reparto"] = _capireparto_from_anagrafica()
        return data
    if not isinstance(payload, dict):
        data["capi_reparto"] = _capireparto_from_anagrafica()
        return data
    for key in ANOMALIE_LIST_KEYS:
        if key == "capi_reparto":
            continue  # sempre da anagrafica
        if key in payload:
            values = _normalize_choice_list(payload.get(key))
            if values or key not in ANOMALIE_NON_EMPTY_DEFAULT_KEYS:
                data[key] = values
            else:
                data[key] = list(ANOMALIE_LIST_DEFAULTS[key])
    data["capi_reparto"] = _capireparto_from_anagrafica()
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
    sp = str(row.get("sharepoint_item_id") or "").strip()
    if sp:
        return sp
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
    if not getattr(user, "is_authenticated", False):
        return AnomalieAccessLevel.NONE
    custom_role_codes = {
        role.code
        for role in _anomalie_role_definitions(include_inactive=False)
        if not role.is_system
    }
    if not custom_role_codes:
        return AnomalieAccessLevel.NONE
    assigned_codes = list(
        AnomalieRoleAssignment.objects.filter(
            user=user,
            role_type__in=custom_role_codes,
        ).values_list("role_type", flat=True)
    )
    if not assigned_codes:
        return AnomalieAccessLevel.NONE
    levels = list(
        AnomalieRoleAccessRule.objects.filter(role_type__in=assigned_codes).values_list("access_level", flat=True)
    )
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
        for role_type, access_level in AnomalieRoleAccessRule.objects.values_list("role_type", "access_level")
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
        AnomalieRoleAccessRule.objects.filter(role_type__in=matched_roles).values_list("access_level", flat=True)
    )
    return _max_anomalie_access_level(levels)


def _op_role_access_level_for_current_user(request, op_id: str) -> str:
    return _anomalie_role_access_level_for_codes(_op_role_codes_for_current_user(request, op_id))


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


def _anomalie_settings_redirect(tab: str, **params):
    query = {"tab": tab}
    query.update({k: v for k, v in params.items() if v})
    qs = "&".join(f"{quote(str(k))}={quote(str(v))}" for k, v in query.items())
    return redirect(f"{reverse('anomalie_configurazione_page')}?{qs}")


def _make_unique_anomalie_role_code(name: str) -> str:
    base = slugify(name).replace("-", "_").upper().strip("_") or "RUOLO"
    base = f"CUSTOM_{base}"
    base = base[:32].strip("_") or "CUSTOM_ROLE"
    candidate = base
    index = 2
    while AnomalieRoleDefinition.objects.filter(code=candidate).exists():
        suffix = f"_{index}"
        candidate = f"{base[: max(1, 32 - len(suffix))]}{suffix}"
        index += 1
    return candidate


def _handle_anomalie_roles_post(request):
    role_definitions = _anomalie_role_definitions(include_inactive=True)
    role_codes = {role.code for role in role_definitions}
    q_user = request.POST.get("q_user", "").strip()
    action = str(request.POST.get("action") or "").strip()

    if action == "create_role":
        role_name = (request.POST.get("role_name") or "").strip()
        if not role_name:
            messages.error(request, "Indica un nome per il ruolo.")
            return _anomalie_settings_redirect("permessi", sub="ruoli", q_user=q_user)
        if AnomalieRoleDefinition.objects.filter(name__iexact=role_name).exists():
            messages.error(request, f"Il ruolo '{role_name}' esiste gia.")
            return _anomalie_settings_redirect("permessi", sub="ruoli", q_user=q_user)
        max_order = AnomalieRoleDefinition.objects.aggregate(m=Max("order_index")).get("m") or 0
        role = AnomalieRoleDefinition.objects.create(
            code=_make_unique_anomalie_role_code(role_name),
            name=role_name[:80],
            description=(request.POST.get("role_description") or "").strip()[:255],
            is_system=False,
            is_active=True,
            order_index=max_order + 10,
        )
        messages.success(request, f"Ruolo '{role.name}' creato.")
        return _anomalie_settings_redirect("permessi", sub="ruoli", q_user=q_user)

    if action == "delete_role":
        role_code = (request.POST.get("role_code") or "").strip()
        role = AnomalieRoleDefinition.objects.filter(code=role_code).first()
        if not role:
            messages.error(request, "Ruolo non trovato.")
            return _anomalie_settings_redirect("permessi", sub="ruoli", q_user=q_user)
        if role.is_system:
            messages.error(request, "I ruoli di sistema non possono essere eliminati.")
            return _anomalie_settings_redirect("permessi", sub="ruoli", q_user=q_user)
        label = role.name
        role.delete()
        AnomalieRoleAssignment.objects.filter(role_type=role_code).delete()
        AnomalieRoleAccessRule.objects.filter(role_type=role_code).delete()
        messages.success(request, f"Ruolo '{label}' eliminato.")
        return _anomalie_settings_redirect("permessi", sub="ruoli", q_user=q_user)

    visible_ids = [int(v) for v in request.POST.getlist("visible_user_id") if str(v).isdigit()]
    if visible_ids:
        AnomalieRoleAssignment.objects.filter(user_id__in=visible_ids, role_type__in=role_codes).delete()
        to_create: list[AnomalieRoleAssignment] = []
        for user_id in visible_ids:
            for role_code in role_codes:
                if request.POST.get(f"role__{role_code}__{user_id}"):
                    to_create.append(AnomalieRoleAssignment(user_id=user_id, role_type=role_code))
        if to_create:
            AnomalieRoleAssignment.objects.bulk_create(to_create, ignore_conflicts=True)
    messages.success(request, "Ruoli operativi anomalie aggiornati.")
    return _anomalie_settings_redirect("permessi", sub="ruoli", q_user=q_user)


def _handle_anomalie_access_post(request):
    role_codes = {role.code for role in _anomalie_role_definitions(include_inactive=True)}
    legacy_role_rows = _anomalie_legacy_role_rows()
    legacy_role_labels = {int(row["id"]): str(row["label"]) for row in legacy_role_rows}
    valid_levels = {choice for choice, _label in AnomalieAccessLevel.choices}
    valid_scopes = {choice for choice, _label in AnomalieListScope.choices}

    for role_code in role_codes:
        level = (request.POST.get(f"access_role__{role_code}") or AnomalieAccessLevel.NONE).strip()
        if level not in valid_levels:
            level = AnomalieAccessLevel.NONE
        scope = (request.POST.get(f"list_scope_role__{role_code}") or AnomalieListScope.ALL).strip()
        if scope not in valid_scopes:
            scope = AnomalieListScope.ALL
        AnomalieRoleAccessRule.objects.update_or_create(
            role_type=role_code,
            defaults={"access_level": level, "list_scope": scope},
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
        return JsonResponse([])
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
                    "WHERE a.op_lookup_id = TRY_CAST(op.sharepoint_item_id AS INT) "
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
            {scope_where}
            GROUP BY
                op.sharepoint_item_id, op.title, op.part_number,
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

                quoted_insert_cols = _quoted_columns(insert_cols)
                cursor.execute(
                    f"""
                    INSERT INTO ordini_produzione ({quoted_insert_cols})
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
    # AU-GAP1: traccia CHI modifica l'anomalia, cosi' il trigger SQL puo' proiettare
    # modified_by_user_id nel payload automazioni e le regole possono filtrare per ruolo
    # (il ruolo CC/CAR viene poi risolto a runtime da _enrich_anomalie_payload).
    if "modified_by_user_id" in cols and legacy_user:
        insert_writable["modified_by_user_id"] = legacy_user.id
        update_writable["modified_by_user_id"] = legacy_user.id

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
                quoted_insert_cols = _quoted_columns(insert_cols)
                cursor.execute(
                    f"""
                    INSERT INTO anomalie ({quoted_insert_cols})
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
            }
        )
    except DatabaseError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=500)


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
        role_definitions = _anomalie_role_definitions(include_inactive=True)
        ruoli_filter_q = request.GET.get("q_user", "").strip()
        all_users = list(_anomalie_settings_users_queryset())
        filtered_users = _filter_anomalie_user_rows(all_users, ruoli_filter_q)
        assignments_raw = list(AnomalieRoleAssignment.objects.values_list("user_id", "role_type"))
        by_user: dict[int, set[str]] = {}
        for user_id, role_type in assignments_raw:
            by_user.setdefault(user_id, set()).add(role_type)
        roster = []
        for user in filtered_users:
            assigned_roles = by_user.get(user.id, set())
            roster.append(
                {
                    "id": user.id,
                    "label": user.get_full_name() or user.username,
                    "email": user.email or "",
                    "role_cells": [
                        {"code": role.code, "checked": role.code in assigned_roles}
                        for role in role_definitions
                    ],
                }
            )
        ruoli_context = {
            "ruoli_filter_q": ruoli_filter_q,
            "ruoli_roster": roster,
            "ruoli_role_definitions": role_definitions,
            "ruoli_colspan": 2 + len(role_definitions),
            "ruoli_stats": {
                "roles": len(role_definitions),
                "assignments": sum(len(values) for values in by_user.values()),
                "total_users": len(all_users),
                "filtered_users": len(roster),
            },
        }

    access_context = {}
    if tab == "permessi" and permessi_sub == "accessi":
        role_definitions = _anomalie_role_definitions(include_inactive=True)
        access_filter_q = request.GET.get("q_access_user", "").strip()
        all_users = list(_anomalie_settings_users_queryset())
        filtered_users = _filter_anomalie_user_rows(all_users, access_filter_q)
        legacy_role_rows = _anomalie_legacy_role_rows()
        role_rule_map = {
            role_type: {"access_level": access_level, "list_scope": list_scope}
            for role_type, access_level, list_scope in AnomalieRoleAccessRule.objects.values_list(
                "role_type", "access_level", "list_scope"
            )
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
                    "code": role.code,
                    "label": role.name,
                    "help": role.description
                    or (
                        "Ruolo custom: la regola vale globalmente per gli utenti assegnati."
                        if not role.is_system
                        else "Ruolo di sistema collegato all'OP."
                    ),
                    "is_system": role.is_system,
                    "access_level": role_rule_map.get(role.code, {}).get("access_level", AnomalieAccessLevel.NONE),
                    "list_scope": role_rule_map.get(role.code, {}).get("list_scope", AnomalieListScope.ALL),
                }
                for role in role_definitions
            ],
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
                "role_rules": len(role_rule_map),
                "legacy_role_rules": len(legacy_role_rule_map),
                "user_overrides": len(user_rule_map),
                "edit_all_roles": sum(
                    1 for v in role_rule_map.values() if v.get("access_level") == AnomalieAccessLevel.EDIT_ALL
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

    context = {
        "page_title": "Gestione Anomalie",
        "username": display_name,
        "config_lists_json": json.dumps(_load_anomalie_lists(), ensure_ascii=False),
        "attachments_dir": _anomalie_attachments_dir_value(),
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
        if key == "capi_reparto":
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

    try:
        log_action(
            request,
            "anomalie_config_liste_update",
            "anomalie",
            {"keys": list(updated.keys()), "attachments_dir": saved_attachments_dir},
        )
    except Exception:
        pass

    updated["capi_reparto"] = _capireparto_from_anagrafica()
    return JsonResponse({"success": True, "lists": updated, "attachments_dir": saved_attachments_dir})


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
    if not _has_table("anomalie"):
        from django.http import HttpResponse
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


@login_required
def api_anomalie_statistiche(request):
    """Statistiche aggregate anomalie con filtri opzionali."""
    if not _has_table("anomalie"):
        return _json_error("Tabella anomalie non disponibile.", 503)

    cols = set(legacy_table_columns("anomalie"))
    da = request.GET.get("da", "").strip()
    a_val = request.GET.get("a", "").strip()
    avanzamento = request.GET.get("avanzamento", "").strip()
    capocommessa = request.GET.get("capocommessa", "").strip()

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

    def _where(extra: str = "") -> str:
        parts = list(where_parts) + ([extra] if extra else [])
        return ("WHERE " + " AND ".join(parts)) if parts else ""

    totale = int((_fetch_all_dict(f"SELECT COUNT(*) AS n FROM anomalie {_where()}", params) or [{"n": 0}])[0]["n"])
    chiuse = int((_fetch_all_dict(f"SELECT COUNT(*) AS n FROM anomalie {_where('chiudere = 1')}", params) or [{"n": 0}])[0]["n"])

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
        "per_avanzamento": [dict(r) for r in per_avanzamento],
        "per_mese": [dict(r) for r in per_mese],
        "avanzamenti_disponibili": avanzamenti_list,
        "capocommessa_disponibili": capocommessa_list,
    })


@login_required
def export_anomalie_csv_filtrato(request):
    """Export CSV anomalie con filtri (da, a, avanzamento, capocommessa)."""
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

    da = request.GET.get("da", "").strip()
    a_val = request.GET.get("a", "").strip()
    avanzamento = request.GET.get("avanzamento", "").strip()
    capocommessa = request.GET.get("capocommessa", "").strip()

    where_parts: list[str] = []
    params: list = []
    if da:
        where_parts.append("created_datetime >= %s")
        params.append(da)
    if a_val:
        where_parts.append("created_datetime < %s")
        params.append(a_val + "T23:59:59")
    if avanzamento:
        where_parts.append("avanzamento = %s")
        params.append(avanzamento)
    if capocommessa:
        where_parts.append("ex_op_nominativo = %s")
        params.append(capocommessa)

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
            "filters": {
                "da": da,
                "a": a_val,
                "avanzamento": avanzamento,
                "capocommessa": capocommessa,
                "limit": 5000,
            },
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

    sql = """
        SELECT TOP 1
            sharepoint_item_id,
            title,
            part_number,
            incaricato,
            capocomessa,
            stato,
            in1text,
            created_datetime,
            modified_datetime
        FROM ordini_produzione
        WHERE {where_clause}
        ORDER BY id DESC
    """
    if op_item_id is not None:
        rows = _fetch_all_dict(sql.format(where_clause="TRY_CAST(sharepoint_item_id AS INT) = %s"), [int(op_item_id)])
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
        "item_id": str((op_row or {}).get("sharepoint_item_id") or (op_item_id if op_item_id is not None else "") or ""),
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
            "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "focus_local_id": anomalia_id or "",
        },
        "anomalie": anomalie,
        "anomalia": focus_anomalia or {"id": "", "seriale": "", "descrizione": ""},
        "allegati": focus_attachments,
    }

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
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
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
