from __future__ import annotations

import json
import logging
import os
import re
import socket
import tempfile
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from django.apps import apps as django_apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.validators import validate_email
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.core.paginator import Paginator
from django.db import DatabaseError, connections, transaction
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import URLPattern, URLResolver, Resolver404, get_resolver, resolve, reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST
from werkzeug.security import generate_password_hash

from config.env_config import get_first_env_value, load_env_file_values, update_env_file_values
from automazioni.approval_mailbox_runtime import (
    get_approval_imap_form_defaults,
    get_approval_imap_status,
    run_approval_imap_poll_now,
    save_approval_imap_settings,
)
from core.acl import diagnose_permesso_for_context
from core.acl_v2 import diagnose_acl_access, normalize_binding_path_pattern, normalize_permission_code, validate_permission_code
from core.audit import log_action
from core.caporeparto_utils import (
    format_caporeparto_label,
    normalize_caporeparto_option,
    resolve_caporeparto_legacy_user,
)
from core.impersonation import start_impersonation
from core.legacy_anagrafica import ensure_anagrafica_schema, sync_anagrafica_from_legacy_user
from core.legacy_cache import (
    bump_legacy_cache_version,
    get_cached_pulsanti_catalog,
    normalize_legacy_path,
)
from core.legacy_models import AnagraficaDipendente, Permesso, Pulsante, Ruolo, UtenteLegacy
from core.navigation_registry import (
    bump_navigation_registry_version,
    export_navigation_state,
    publish_navigation_snapshot,
    restore_navigation_snapshot,
)
from core.legacy_utils import get_legacy_user, legacy_table_columns, legacy_table_has_column
from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime
from core.models import (
    AnagraficaRisposta,
    AnagraficaVoce,
    ChecklistEsecuzione,
    ChecklistRisposta,
    ChecklistVoce,
    EmployeeBoardConfig,
    LegacyRedirect,
    LoginBanner,
    NavigationItem,
    NavigationRoleAccess,
    NavigationSnapshot,
    Notifica,
    OptioneConfig,
    PermissionDefinition,
    Profile,
    RolePermissionGrant,
    RoutePermissionBinding,
    SiteConfig,
    UserDashboardConfig,
    UserDashboardLayout,
    UserExtraInfo,
    UserUiPreference,
    UserModuleVisibility,
    UserPermissionGrant,
    UserPermissionOverride,
)

from .decorators import legacy_admin_required
from .forms import BulkRoleForm, PulsanteForm, UtenteCreateForm, UtenteUpdateForm


PERM_OPTIONAL_FIELDS = ("can_edit", "can_delete", "can_approve")
logger = logging.getLogger(__name__)
NAV_ICON_STORAGE_DIR = "navigation/icons"
NAV_ICON_ALLOWED_EXTENSIONS = {".ico", ".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif"}

# ---------------------------------------------------------------------------
# CATALOGO MODULI â€” pulsanti standard per ogni modulo noto del portale.
# Aggiungere qui nuovi moduli: la pagina pulsanti proporrÃ  automaticamente
# i pulsanti mancanti con un click per crearli tutti + inizializzare i permessi.
# ---------------------------------------------------------------------------
MODULE_CATALOG: dict[str, dict] = {
    "dashboard": {
        "label": "Dashboard",
        "icon": "layout-dashboard",
        "buttons": [
            {
                "codice": "view_dashboard",
                "nome_visibile": "Dashboard",
                "url": "route:dashboard_home",
                "icona": "layout-dashboard",
                "ui_slot": "topbar",
                "ui_section": "toolbar",
                "visible_topbar": True,
                "enabled": True,
            },
        ],
    },
    "assenze": {
        "label": "Assenze",
        "icon": "calendar",
        "buttons": [
            {
                "codice": "view_assenze",
                "nome_visibile": "Le mie assenze",
                "url": "route:assenze_dipendente",
                "icona": "calendar",
                "ui_slot": "topbar",
                "ui_section": "gestione_assenze",
                "visible_topbar": True,
                "enabled": True,
            },
            {
                "codice": "gestione_assenze",
                "nome_visibile": "Impostazioni Assenze",
                "url": "route:gestione_assenze",
                "icona": "calendar",
                "ui_slot": "topbar",
                "ui_section": "gestione_assenze",
                "visible_topbar": True,
                "enabled": True,
            },
            {
                "codice": "calendario_assenze",
                "nome_visibile": "Calendario Assenze",
                "url": "route:calendario_assenze",
                "icona": "calendar",
                "ui_slot": "topbar",
                "ui_section": "calendario_assenze",
                "visible_topbar": True,
                "enabled": True,
            },
            {
                "codice": "admin_assenze",
                "nome_visibile": "Gestione interna Assenze",
                "url": "/assenze/gestione-admin/",
                "icona": "settings",
                "ui_slot": "topbar",
                "ui_section": "gestione_assenze",
                "visible_topbar": False,
                "enabled": True,
            },
        ],
    },
    "anomalie": {
        "label": "Gestione Anomalie",
        "icon": "octagon-alert",
        "buttons": [
            {
                "codice": "gestione_anomalie",
                "nome_visibile": "Anomalie",
                "url": "route:gestione_anomalie_page",
                "icona": "octagon-alert",
                "ui_slot": "topbar",
                "ui_section": "gestione_anomalie",
                "visible_topbar": True,
                "enabled": True,
            },
            {
                "codice": "admin_anomalie",
                "nome_visibile": "Gestione interna Anomalie",
                "url": "/gestione-anomalie/configurazione",
                "icona": "settings",
                "ui_slot": "topbar",
                "ui_section": "gestione_anomalie",
                "visible_topbar": False,
                "enabled": True,
            },
        ],
    },
    "notizie": {
        "label": "Notizie",
        "icon": "newspaper",
        "buttons": [
            {
                "codice": "view_notizie",
                "nome_visibile": "Notizie",
                "url": "route:notizie_lista",
                "icona": "newspaper",
                "ui_slot": "topbar",
                "ui_section": "notizie",
                "visible_topbar": True,
                "enabled": True,
            },
            {
                "codice": "admin_notizie",
                "nome_visibile": "Impostazioni Notizie",
                "url": "/notizie/impostazioni/",
                "icona": "settings",
                "ui_slot": "topbar",
                "ui_section": "notizie",
                "visible_topbar": False,
                "enabled": True,
            },
        ],
    },
    "assets": {
        "label": "Assets",
        "icon": "package",
        "buttons": [
            {
                "codice": "view_assets",
                "nome_visibile": "Inventario Asset",
                "url": "/assets/",
                "icona": "package",
                "ui_slot": "topbar",
                "ui_section": "assets",
                "visible_topbar": True,
                "enabled": True,
            },
            {
                "codice": "admin_assets",
                "nome_visibile": "Impostazioni Assets",
                "url": "/assets/impostazioni/",
                "icona": "settings",
                "ui_slot": "topbar",
                "ui_section": "assets",
                "visible_topbar": False,
                "enabled": True,
            },
        ],
    },
    "tasks": {
        "label": "Tasks",
        "icon": "list-todo",
        "buttons": [
            {
                "codice": "view_tasks",
                "nome_visibile": "Task",
                "url": "/tasks/",
                "icona": "list-todo",
                "ui_slot": "topbar",
                "ui_section": "tasks",
                "visible_topbar": True,
                "enabled": True,
            },
            {
                "codice": "admin_tasks",
                "nome_visibile": "Gestione interna Tasks",
                "url": "/tasks/gestione/",
                "icona": "settings",
                "ui_slot": "topbar",
                "ui_section": "tasks",
                "visible_topbar": False,
                "enabled": True,
            },
        ],
    },
    "automazioni": {
        "label": "Automazioni",
        "icon": "flow",
        "buttons": [
            {
                "codice": "automazioni_view",
                "nome_visibile": "Automazioni - Sorgenti",
                "url": "route:admin_portale:automazioni_sorgenti",
                "icona": "flow",
                "ui_slot": "topbar",
                "ui_section": "admin_automazioni",
                "visible_topbar": False,
                "enabled": True,
            },
            {
                "codice": "automazioni_manage",
                "nome_visibile": "Automazioni - Contenuti",
                "url": "route:admin_portale:automazioni_contenuti",
                "icona": "settings",
                "ui_slot": "topbar",
                "ui_section": "admin_automazioni",
                "visible_topbar": False,
                "enabled": True,
            },
        ],
    },
    "portale_esterno": {
        "label": "Portale Esterno",
        "icon": "N",
        "buttons": [
            {
                "codice": "portale_esterno",
                "nome_visibile": "Portale Esterno",
                "url": "https://PORTALE-URL-DA-CONFIGURARE",
                "icona": "N",
                "ui_slot": "topbar",
                "ui_section": "portale_esterno",
                "visible_topbar": True,
                "enabled": True,
            },
        ],
    },
    "anagrafica": {
        "label": "Anagrafica",
        "icon": "id-card",
        "buttons": [
            {
                "codice": "view_anagrafica_dipendenti",
                "nome_visibile": "Dipendenti",
                "url": "route:anagrafica:dipendenti_list",
                "icona": "id-card",
                "ui_slot": "topbar",
                "ui_section": "anagrafica",
                "visible_topbar": True,
                "enabled": True,
            },
            {
                "codice": "view_anagrafica_fornitori",
                "nome_visibile": "Fornitori",
                "url": "route:anagrafica:fornitori_list",
                "icona": "briefcase",
                "ui_slot": "topbar",
                "ui_section": "anagrafica",
                "visible_topbar": True,
                "enabled": True,
            },
        ],
    },
    "timbri": {
        "label": "Timbrature",
        "icon": "scan",
        "buttons": [
            {
                "codice": "view_timbri",
                "nome_visibile": "Timbrature",
                "url": "route:timbri:index",
                "icona": "scan",
                "ui_slot": "topbar",
                "ui_section": "timbri",
                "visible_topbar": True,
                "enabled": True,
            },
        ],
    },
    "tickets": {
        "label": "Tickets",
        "icon": "ticket",
        "buttons": [
            {
                "codice": "view_tickets",
                "nome_visibile": "I miei ticket",
                "url": "route:tickets:dashboard",
                "icona": "ticket",
                "ui_slot": "topbar",
                "ui_section": "tickets",
                "visible_topbar": True,
                "enabled": True,
            },
            {
                "codice": "gestione_tickets",
                "nome_visibile": "Gestione Ticket",
                "url": "route:tickets:gestione_list",
                "icona": "settings",
                "ui_slot": "topbar",
                "ui_section": "tickets",
                "visible_topbar": False,
                "enabled": True,
            },
        ],
    },
    "rentri": {
        "label": "RENTRI",
        "icon": "recycle",
        "buttons": [
            {
                "codice": "view_rentri",
                "nome_visibile": "RENTRI",
                "url": "route:rentri_menu",
                "icona": "recycle",
                "ui_slot": "topbar",
                "ui_section": "rentri",
                "visible_topbar": True,
                "enabled": True,
            },
        ],
    },
    "diario_preposto": {
        "label": "Diario Preposto",
        "icon": "clipboard-list",
        "buttons": [
            {
                "codice": "view_diario_preposto",
                "nome_visibile": "Diario Preposto",
                "url": "route:diario_preposto:lista",
                "icona": "clipboard-list",
                "ui_slot": "topbar",
                "ui_section": "diario_preposto",
                "visible_topbar": True,
                "enabled": True,
            },
        ],
    },
    "rilevazione_incidenti": {
        "label": "Rilevazione Incidenti",
        "icon": "alert-triangle",
        "buttons": [
            {
                "codice": "view_rilevazione_incidenti",
                "nome_visibile": "Rilevazione Incidenti",
                "url": "route:rilevazione_incidenti:lista",
                "icona": "alert-triangle",
                "ui_slot": "topbar",
                "ui_section": "rilevazione_incidenti",
                "visible_topbar": True,
                "enabled": True,
            },
        ],
    },
    "dpi": {
        "label": "DPI",
        "icon": "shield-check",
        "buttons": [
            {
                "codice": "view_dpi",
                "nome_visibile": "DPI",
                "url": "route:dpi:dashboard",
                "icona": "shield-check",
                "ui_slot": "topbar",
                "ui_section": "dpi",
                "visible_topbar": True,
                "enabled": True,
            },
            {
                "codice": "gestione_dpi",
                "nome_visibile": "Gestione DPI",
                "url": "route:dpi:gestione_list",
                "icona": "settings",
                "ui_slot": "topbar",
                "ui_section": "dpi",
                "visible_topbar": False,
                "enabled": True,
            },
        ],
    },
    "procedure_refresh": {
        "label": "Procedure",
        "icon": "file-check",
        "buttons": [
            {
                "codice": "view_procedure_refresh",
                "nome_visibile": "Le mie procedure",
                "url": "route:procedure_refresh:my_assignments",
                "icona": "file-check",
                "ui_slot": "topbar",
                "ui_section": "procedure_refresh",
                "visible_topbar": True,
                "enabled": True,
            },
            {
                "codice": "admin_procedure_refresh",
                "nome_visibile": "Impostazioni Procedure",
                "url": "route:procedure_refresh:admin_dashboard",
                "icona": "settings",
                "ui_slot": "topbar",
                "ui_section": "procedure_refresh",
                "visible_topbar": False,
                "enabled": True,
            },
        ],
    },
}


def _proposed_from_catalog(existing_codici: set[str]) -> list[dict]:
    """Confronta MODULE_CATALOG con i pulsanti nel DB; restituisce moduli con pulsanti mancanti.
    Usa existing_codici (set di codici globali) perchÃ© la UNIQUE KEY DB Ã¨ su codice, non su (modulo, codice).
    """
    proposed = []
    for module_key, module_def in MODULE_CATALOG.items():
        missing = [
            btn for btn in module_def["buttons"]
            if btn["codice"].lower() not in existing_codici
        ]
        if missing:
            proposed.append({
                "key": module_key,
                "label": module_def["label"],
                "icon": module_def.get("icon", ""),
                "missing_buttons": missing,
                "total": len(module_def["buttons"]),
            })
    return proposed


def _app_modules_without_pulsanti(existing_moduli: set[str]) -> list[dict]:
    """App Django del progetto che non hanno pulsanti e non sono nel catalogo."""
    SKIP = {"admin_portale", "core", "admin", "auth", "contenttypes", "sessions", "messages", "staticfiles"}
    results = []
    try:
        for app_config in django_apps.get_app_configs():
            if "django." in app_config.name:
                continue
            if app_config.label in SKIP:
                continue
            if app_config.label in MODULE_CATALOG:
                continue
            if app_config.label.lower() in existing_moduli:
                continue
            results.append({"label": app_config.label, "verbose_name": str(app_config.verbose_name)})
    except Exception:
        pass
    return results


def _ensure_permessi_for_button(modulo: str, codice: str) -> int:
    """Garantisce record 'permessi' per ogni ruolo (can_view=0 se non esiste).
    Riusa _get_or_create_permesso che crea con tutti i flag a 0."""
    created = 0
    try:
        for ruolo in Ruolo.objects.all():
            _get_or_create_permesso(int(ruolo.id), modulo, codice)
            created += 1
    except DatabaseError:
        pass
    return created


def _audit_safe(request, azione: str, modulo: str, dettaglio: dict | None = None) -> None:
    """Audit fire-and-forget senza interrompere il flusso utente."""
    try:
        from core.audit import log_action

        log_action(request, azione, modulo, dettaglio or {})
    except Exception:
        pass


def _safe_redirect_url(request, candidate: str | None, fallback: str) -> str:
    """Restituisce candidate solo se Ã¨ un URL locale sicuro, altrimenti fallback.

    Protegge da open redirect: rifiuta URL assoluti verso domini esterni, URL
    con schema javascript:/data: e qualsiasi valore che non passi il controllo
    Django url_has_allowed_host_and_scheme.
    """
    if candidate:
        candidate = str(candidate).strip()
        if url_has_allowed_host_and_scheme(
            url=candidate,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return candidate
    return fallback


def _normalize_category(value: str | None, default: str = "Generale") -> str:
    raw = str(value or "").strip()
    if not raw:
        return default
    return raw[:100]


def _iter_urlpatterns(patterns, namespace_prefix: str = ""):
    for entry in patterns:
        if isinstance(entry, URLPattern):
            name = entry.name
            if not name:
                continue
            route_name = f"{namespace_prefix}{name}"
            try:
                path_value = reverse(route_name)
            except Exception:
                path_value = ""
            yield {
                "route_name": route_name,
                "path": path_value,
            }
            continue
        if isinstance(entry, URLResolver):
            nested_ns = namespace_prefix
            if entry.namespace:
                nested_ns = f"{namespace_prefix}{entry.namespace}:"
            yield from _iter_urlpatterns(entry.url_patterns, nested_ns)


def _route_catalog() -> list[dict[str, str]]:
    try:
        resolver = get_resolver()
        rows = list(_iter_urlpatterns(resolver.url_patterns))
    except Exception:
        return []

    # Riduci rumore tecnico e ordina in modo utile per l'admin.
    hidden_prefixes = ("admin:",)
    filtered = []
    seen = set()
    for row in rows:
        route_name = row["route_name"]
        path = row.get("path") or ""
        if route_name.startswith(hidden_prefixes):
            continue
        if route_name in seen:
            continue
        seen.add(route_name)
        filtered.append(
            {
                "route_name": route_name,
                "path": path,
                "portal_value": f"route:{route_name}",
            }
        )
    filtered.sort(key=lambda r: (r["route_name"]))
    return filtered


def _boolish_db(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    try:
        return bool(int(value))
    except Exception:
        return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def _clean_card_image_value(value) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return raw[:500]


def _card_image_public_url(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    if lower.startswith(("http://", "https://", "data:")):
        return raw
    if raw.startswith("/"):
        return raw
    media_url = str(getattr(settings, "MEDIA_URL", "/media/") or "/media/")
    if not media_url.endswith("/"):
        media_url += "/"
    return media_url + raw.lstrip("/")


def _is_allowed_nav_icon_extension(ext: str) -> bool:
    return str(ext or "").strip().lower() in NAV_ICON_ALLOWED_EXTENSIONS


def _navigation_icon_library_items() -> list[dict[str, str]]:
    try:
        _, files = default_storage.listdir(NAV_ICON_STORAGE_DIR)
    except Exception:
        return []

    items: list[dict[str, str]] = []
    for filename in sorted(files, key=str.lower):
        ext = Path(str(filename or "")).suffix.lower()
        if not _is_allowed_nav_icon_extension(ext):
            continue
        stored_value = f"{NAV_ICON_STORAGE_DIR}/{str(filename).strip().lstrip('/')}".replace("\\", "/")
        items.append(
            {
                "name": Path(filename).name,
                "label": Path(filename).stem,
                "value": stored_value,
                "url": _card_image_public_url(stored_value),
            }
        )
    return items


def _save_navigation_icon_upload(upload) -> tuple[str, str]:
    filename = str(getattr(upload, "name", "") or "icon").strip() or "icon"
    base_name, ext = os.path.splitext(filename)
    ext = ext.lower()
    if not _is_allowed_nav_icon_extension(ext):
        raise ValidationError("Formato file non valido: usa .ico, .png, .svg o un formato immagine supportato.")

    safe_name = slugify(base_name) or "nav-icon"
    unique_suffix = timezone.now().strftime("%Y%m%d%H%M%S%f")
    target_path = f"{NAV_ICON_STORAGE_DIR}/{safe_name}-{unique_suffix}{ext}"
    saved_path = default_storage.save(target_path, upload).replace("\\", "/")
    return saved_path, _card_image_public_url(saved_path)


def _normalize_media_storage_path(value: str | None) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    media_url = str(getattr(settings, "MEDIA_URL", "/media/") or "/media/")
    if media_url and raw.startswith(media_url):
        raw = raw[len(media_url):]
    return raw.lstrip("/")


def _delete_card_image_file(value: str | None) -> None:
    storage_path = _normalize_media_storage_path(value)
    if not storage_path:
        return
    if storage_path.lower().startswith(("http://", "https://", "data:")):
        return
    # Limita la cancellazione ai file caricati dal pannello.
    if not storage_path.startswith("dashboard/modules/"):
        return
    try:
        if default_storage.exists(storage_path):
            default_storage.delete(storage_path)
    except Exception:
        pass


def _ensure_ui_meta_column(cursor, vendor: str, column_name: str, sqlite_column_ddl: str, sqlserver_column_ddl: str) -> None:
    try:
        if vendor == "sqlite":
            cursor.execute("PRAGMA table_info(ui_pulsanti_meta)")
            cols = {str(row[1]).strip().lower() for row in cursor.fetchall() if len(row) > 1}
            if column_name.lower() in cols:
                return
            cursor.execute(f"ALTER TABLE ui_pulsanti_meta ADD COLUMN {sqlite_column_ddl}")
            return

        cursor.execute(f"SELECT COL_LENGTH('ui_pulsanti_meta', '{column_name}')")
        row = cursor.fetchone()
        if row and row[0] is not None:
            return
        cursor.execute(f"ALTER TABLE ui_pulsanti_meta ADD {sqlserver_column_ddl}")
    except Exception:
        pass


def _ensure_pulsanti_ui_meta_table() -> None:
    try:
        with connections["default"].cursor() as cursor:
            vendor = connections["default"].vendor
            if vendor == "sqlite":
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ui_pulsanti_meta (
                        pulsante_id INTEGER PRIMARY KEY,
                        ui_slot TEXT NULL,
                        ui_section TEXT NULL,
                        ui_order INTEGER NULL,
                        card_image TEXT NULL,
                        visible_topbar INTEGER NOT NULL DEFAULT 1,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        is_padre INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NULL
                    )
                    """
                )
            else:
                cursor.execute(
                    """
                    IF OBJECT_ID('ui_pulsanti_meta', 'U') IS NULL
                    CREATE TABLE ui_pulsanti_meta (
                        pulsante_id INT NOT NULL PRIMARY KEY,
                        ui_slot NVARCHAR(50) NULL,
                        ui_section NVARCHAR(100) NULL,
                        ui_order INT NULL,
                        card_image NVARCHAR(500) NULL,
                        visible_topbar BIT NOT NULL DEFAULT 1,
                        enabled BIT NOT NULL DEFAULT 1,
                        is_padre BIT NOT NULL DEFAULT 0,
                        updated_at DATETIME2 NULL
                    )
                    """
                )
            _ensure_ui_meta_column(cursor, vendor, "card_image", "card_image TEXT NULL", "card_image NVARCHAR(500) NULL")
            _ensure_ui_meta_column(cursor, vendor, "is_padre", "is_padre INTEGER NOT NULL DEFAULT 0", "is_padre BIT NOT NULL DEFAULT 0")
    except Exception:
        pass


def _pulsanti_ui_meta_map() -> dict[int, dict]:
    _ensure_pulsanti_ui_meta_table()
    try:
        with connections["default"].cursor() as cursor:
            try:
                cursor.execute(
                    """
                    SELECT pulsante_id, ui_slot, ui_section, ui_order, card_image, visible_topbar, enabled, is_padre
                    FROM ui_pulsanti_meta
                    """
                )
                rows = cursor.fetchall()
            except Exception:
                cursor.execute(
                    """
                    SELECT pulsante_id, ui_slot, ui_section, ui_order, visible_topbar, enabled
                    FROM ui_pulsanti_meta
                    """
                )
                rows = [(*r[:4], "", *r[4:], 0) for r in cursor.fetchall()]
    except Exception:
        return {}
    result: dict[int, dict] = {}
    for row in rows:
        try:
            pid = int(row[0])
        except Exception:
            continue
        result[pid] = {
            "ui_slot": (row[1] or "").strip() if row[1] is not None else "",
            "ui_section": (row[2] or "").strip() if row[2] is not None else "",
            "ui_order": int(row[3]) if row[3] is not None else None,
            "card_image": (row[4] or "").strip() if row[4] is not None else "",
            "visible_topbar": _boolish_db(row[5], True),
            "enabled": _boolish_db(row[6], True),
            "is_padre": _boolish_db(row[7] if len(row) > 7 else 0, False),
        }
    return result


def _card_image_raw_value(pulsante_id: int) -> str:
    _ensure_pulsanti_ui_meta_table()
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT card_image FROM ui_pulsanti_meta WHERE pulsante_id = %s", [pulsante_id])
            row = cursor.fetchone()
            return (str(row[0]).strip() if row and row[0] is not None else "")
    except Exception:
        return ""


def _save_pulsante_ui_meta(pulsante_id: int, payload: dict) -> None:
    _ensure_pulsanti_ui_meta_table()
    ui_slot = str(payload.get("ui_slot") or "").strip() or None
    ui_section = str(payload.get("ui_section") or "").strip() or None
    ui_order = _int_or_none(payload.get("ui_order"))
    has_card_image = "card_image" in payload
    card_image = _clean_card_image_value(payload.get("card_image")) if has_card_image else _clean_card_image_value(
        _card_image_raw_value(pulsante_id)
    )
    visible_topbar = _bool_from_any(payload.get("visible_topbar")) if "visible_topbar" in payload else True
    enabled = _bool_from_any(payload.get("enabled")) if "enabled" in payload else True
    is_padre = _bool_from_any(payload.get("is_padre")) if "is_padre" in payload else False
    with connections["default"].cursor() as cursor:
        vendor = connections["default"].vendor
        if vendor == "sqlite":
            cursor.execute(
                """
                INSERT INTO ui_pulsanti_meta
                    (pulsante_id, ui_slot, ui_section, ui_order, card_image, visible_topbar, enabled, is_padre, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT(pulsante_id) DO UPDATE SET
                    ui_slot=excluded.ui_slot,
                    ui_section=excluded.ui_section,
                    ui_order=excluded.ui_order,
                    card_image=excluded.card_image,
                    visible_topbar=excluded.visible_topbar,
                    enabled=excluded.enabled,
                    is_padre=excluded.is_padre,
                    updated_at=CURRENT_TIMESTAMP
                """,
                [
                    pulsante_id,
                    ui_slot,
                    ui_section,
                    ui_order,
                    card_image,
                    1 if visible_topbar else 0,
                    1 if enabled else 0,
                    1 if is_padre else 0,
                ],
            )
        else:
            cursor.execute(
                """
                MERGE ui_pulsanti_meta AS target
                USING (SELECT %s AS pulsante_id) AS src
                ON target.pulsante_id = src.pulsante_id
                WHEN MATCHED THEN UPDATE SET
                    ui_slot = %s,
                    ui_section = %s,
                    ui_order = %s,
                    card_image = %s,
                    visible_topbar = %s,
                    enabled = %s,
                    is_padre = %s,
                    updated_at = SYSUTCDATETIME()
                WHEN NOT MATCHED THEN
                    INSERT (pulsante_id, ui_slot, ui_section, ui_order, card_image, visible_topbar, enabled, is_padre, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, SYSUTCDATETIME());
                """,
                [
                    pulsante_id,
                    ui_slot,
                    ui_section,
                    ui_order,
                    card_image,
                    1 if visible_topbar else 0,
                    1 if enabled else 0,
                    1 if is_padre else 0,
                    pulsante_id,
                    ui_slot,
                    ui_section,
                    ui_order,
                    card_image,
                    1 if visible_topbar else 0,
                    1 if enabled else 0,
                    1 if is_padre else 0,
                ],
            )


def _infer_pulsante_area(p: Pulsante) -> tuple[str, str]:
    codice = str(getattr(p, "codice", "") or "").strip().lower()
    modulo = str(getattr(p, "modulo", "") or "").strip().lower()
    url = str(getattr(p, "url", "") or "").strip().lower()
    route_name = ""
    if url.startswith("route:") or url.startswith("django:"):
        route_name = url.split(":", 1)[1].strip().lower()

    text = " ".join([codice, modulo, url, route_name])
    if any(k in text for k in ("gestione_anomalie", "/api/anomalie", "anomalie", "anomalia")):
        return "anomalie", "Gestione Anomalie"
    if any(k in text for k in ("assenze", "richiesta_assenze", "calendario")):
        if "calendario" in text:
            return "assenze_calendario", "Calendario Assenze"
        return "assenze", "Gestione Assenze"
    if any(k in text for k in ("permessi", "ruoli", "pulsanti")):
        return "admin_permessi", "Gestione Permessi / Ruoli"
    if any(k in text for k in ("utenti", "utente_")):
        return "admin_utenti", "Gestione Utenti"
    if any(k in text for k in ("admin_portale", "pannello_admin", "/admin")):
        return "admin", "Pannello Admin"
    if any(k in text for k in ("richieste",)):
        return "richieste", "Le mie richieste"
    if any(k in text for k in ("dashboard",)):
        return "toolbar", "Toolbar / Dashboard"
    return "altro", "Altro"


def _area_from_ui_meta_or_infer(p: Pulsante, meta: dict | None) -> tuple[str, str]:
    if meta:
        ui_slot = (meta.get("ui_slot") or "").strip()
        ui_section = (meta.get("ui_section") or "").strip()
        if ui_slot and ui_section:
            return f"{ui_slot}:{ui_section}", f"{ui_slot} / {ui_section}"
        if ui_section:
            return ui_section, ui_section
        if ui_slot:
            return ui_slot, ui_slot
    return _infer_pulsante_area(p)


def _bool_from_any(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "on", "yes", "y"}


def _int_or_none(value):
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_payload(request: HttpRequest) -> dict:
    try:
        raw = request.body.decode("utf-8") if request.body else "{}"
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _post_or_json_payload(request: HttpRequest) -> dict:
    if "application/json" in (request.headers.get("Content-Type") or ""):
        return _json_payload(request)
    return dict(request.POST.items())


def _asset_model():
    try:
        return django_apps.get_model("assets", "Asset")
    except Exception:
        return None


LDAP_DIAG_FIELDS: tuple[dict[str, object], ...] = (
    {
        "key": "enabled",
        "label": "LDAP abilitato",
        "setting_name": "LDAP_ENABLED",
        "env_key": "LDAP_ENABLED",
        "ini_key": "enabled",
        "default": False,
        "kind": "bool",
    },
    {
        "key": "server",
        "label": "Server LDAP",
        "setting_name": "LDAP_SERVER",
        "env_key": "LDAP_SERVER",
        "ini_key": "server",
        "default": "",
        "kind": "str",
    },
    {
        "key": "domain",
        "label": "Dominio (NetBIOS)",
        "setting_name": "LDAP_DOMAIN",
        "env_key": "LDAP_DOMAIN",
        "ini_key": "domain",
        "default": "",
        "kind": "str",
    },
    {
        "key": "upn_suffix",
        "label": "UPN suffix",
        "setting_name": "LDAP_UPN_SUFFIX",
        "env_key": "LDAP_UPN_SUFFIX",
        "ini_key": "upn_suffix",
        "default": "",
        "kind": "str",
    },
    {
        "key": "timeout",
        "label": "Timeout (s)",
        "setting_name": "LDAP_TIMEOUT",
        "env_key": "LDAP_TIMEOUT",
        "ini_key": "timeout",
        "default": 5,
        "kind": "int",
    },
    {
        "key": "service_user",
        "label": "Service user",
        "setting_name": "LDAP_SERVICE_USER",
        "env_key": "LDAP_SERVICE_USER",
        "ini_key": "service_user",
        "default": "",
        "kind": "str",
    },
    {
        "key": "base_dn",
        "label": "Base DN",
        "setting_name": "LDAP_BASE_DN",
        "env_key": "LDAP_BASE_DN",
        "ini_key": "base_dn",
        "default": "",
        "kind": "str",
    },
    {
        "key": "user_filter",
        "label": "User filter",
        "setting_name": "LDAP_USER_FILTER",
        "env_key": "LDAP_USER_FILTER",
        "ini_key": "user_filter",
        "default": "(&(objectCategory=person)(objectClass=user))",
        "kind": "str",
    },
    {
        "key": "group_allowlist",
        "label": "Group allowlist",
        "setting_name": "LDAP_GROUP_ALLOWLIST",
        "env_key": "LDAP_GROUP_ALLOWLIST",
        "ini_key": "group_allowlist",
        "default": [],
        "kind": "csv",
    },
    {
        "key": "sync_page_size",
        "label": "Sync page size",
        "setting_name": "LDAP_SYNC_PAGE_SIZE",
        "env_key": "LDAP_SYNC_PAGE_SIZE",
        "ini_key": "sync_page_size",
        "default": 500,
        "kind": "int",
    },
)


def _dotenv_path() -> Path:
    return Path(settings.BASE_DIR) / ".env"


def _config_ini_path() -> Path:
    return Path(settings.BASE_DIR).parent / "config.ini"


def _load_dotenv_values(dotenv_path: Path | None = None) -> dict[str, str]:
    return load_env_file_values(dotenv_path or _dotenv_path())


def _effective_env_value(env_key: str, default: str = "") -> str:
    dotenv_values = _load_dotenv_values()
    dotenv_value = dotenv_values.get(env_key)
    process_env_value = os.environ.get(env_key)
    if process_env_value is not None and (dotenv_value is None or process_env_value != dotenv_value):
        return str(process_env_value or "").strip()
    if dotenv_value is not None:
        return str(dotenv_value or "").strip()
    return str(default or "").strip()


def _effective_env_bool(env_key: str, default: bool = False) -> bool:
    value = _effective_env_value(env_key, "")
    if value == "":
        return bool(default)
    return _bool_from_any(value)


def _effective_env_int(env_key: str, default: int) -> int:
    value = _int_or_none(_effective_env_value(env_key, ""))
    if value is None:
        return int(default)
    return int(value)


def _ldap_csv_items(value) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        items = value
    elif value in (None, ""):
        items = []
    else:
        items = str(value).split(",")
    return [str(item).strip() for item in items if str(item).strip()]


def _ldap_normalize_field_value(field: dict[str, object], value):
    kind = str(field.get("kind") or "str")
    default = field.get("default")
    if kind == "bool":
        return _bool_from_any(default if value is None else value)
    if kind == "int":
        coerced = _int_or_none(value)
        if coerced is None:
            coerced = _int_or_none(default)
        return coerced or 0
    if kind == "csv":
        return tuple(item.casefold() for item in _ldap_csv_items(value))
    return str(value or "").strip()


def _ldap_display_field_value(field: dict[str, object], value) -> str:
    kind = str(field.get("kind") or "str")
    if kind == "bool":
        return "Si" if _ldap_normalize_field_value(field, value) else "No"
    if kind == "int":
        return str(_ldap_normalize_field_value(field, value))
    if kind == "csv":
        items = _ldap_csv_items(value)
        return ", ".join(items) if items else "(vuota)"
    text = str(value or "").strip()
    return text or "(non configurato)"


def _ldap_form_field_value(field: dict[str, object], value):
    kind = str(field.get("kind") or "str")
    if kind == "bool":
        return _ldap_normalize_field_value(field, value)
    if kind == "int":
        return _ldap_normalize_field_value(field, value)
    if kind == "csv":
        return ", ".join(_ldap_csv_items(value))
    return str(value or "").strip()


def _load_config_ini_ad_values() -> dict[str, str]:
    """Legge la sezione [ACTIVE_DIRECTORY] da config.ini e restituisce un dict chiave->valore."""
    import configparser as _cp
    parser = _cp.ConfigParser()
    config_path = _config_ini_path()
    if config_path.exists():
        try:
            parser.read(str(config_path), encoding="utf-8")
        except Exception:
            pass
    if parser.has_section("ACTIVE_DIRECTORY"):
        return dict(parser.items("ACTIVE_DIRECTORY"))
    return {}


def _ldap_source_label(source_key: str) -> str:
    mapping = {
        "dotenv": ".env",
        "process_env": "ambiente processo",
        "config_ini": "config.ini",
        "default": "default codice",
        "stale_runtime": "runtime gia caricato",
    }
    return mapping.get(source_key, source_key)


def _ldap_runtime_source(
    field: dict[str, object],
    runtime_value,
    dotenv_values: dict[str, str],
    ini_values: dict[str, str] | None = None,
) -> str:
    runtime_norm = _ldap_normalize_field_value(field, runtime_value)
    env_key = str(field.get("env_key") or "")
    ini_key = str(field.get("ini_key") or "")
    dotenv_value = dotenv_values.get(env_key)
    process_env_value = os.environ.get(env_key)

    if process_env_value is not None and (dotenv_value is None or process_env_value != dotenv_value):
        if runtime_norm == _ldap_normalize_field_value(field, process_env_value):
            return "process_env"
    if dotenv_value is not None and runtime_norm == _ldap_normalize_field_value(field, dotenv_value):
        return "dotenv"
    if ini_values is not None and ini_key and ini_key in ini_values:
        if runtime_norm == _ldap_normalize_field_value(field, ini_values[ini_key]):
            return "config_ini"
    if runtime_norm == _ldap_normalize_field_value(field, field.get("default")):
        return "default"
    return "stale_runtime"


def _ldap_next_boot_value(
    field: dict[str, object],
    dotenv_values: dict[str, str],
    ini_values: dict[str, str] | None = None,
):
    env_key = str(field.get("env_key") or "")
    ini_key = str(field.get("ini_key") or "")
    dotenv_value = dotenv_values.get(env_key)
    process_env_value = os.environ.get(env_key)
    if process_env_value is not None and (dotenv_value is None or process_env_value != dotenv_value):
        return process_env_value, "process_env"
    if dotenv_value is not None:
        return dotenv_value, "dotenv"
    if ini_values is not None and ini_key and ini_key in ini_values:
        return ini_values[ini_key], "config_ini"
    return field.get("default"), "default"


def _ldap_diag_runtime_rows(runtime_cfg: dict[str, object]) -> tuple[list[dict[str, object]], bool, bool]:
    dotenv_values = _load_dotenv_values()
    ini_values = _load_config_ini_ad_values()
    rows: list[dict[str, object]] = []
    has_pending_restart = False
    has_env_override = False

    for field in LDAP_DIAG_FIELDS:
        key = str(field["key"])
        runtime_value = runtime_cfg.get(key)
        runtime_source = _ldap_runtime_source(field, runtime_value, dotenv_values, ini_values)
        next_value, next_source = _ldap_next_boot_value(field, dotenv_values, ini_values)

        runtime_norm = _ldap_normalize_field_value(field, runtime_value)
        next_norm = _ldap_normalize_field_value(field, next_value)
        runtime_matches_next = runtime_norm == next_norm
        dotenv_value = dotenv_values.get(str(field.get("env_key") or ""))
        override_active = (
            next_source == "process_env"
            and dotenv_value is not None
            and _ldap_normalize_field_value(field, dotenv_value) != next_norm
        )

        if not runtime_matches_next:
            status_label = "Riavvio necessario"
            status_tone = "warning"
            note = "Il processo Django attuale non usa ancora il valore che verra letto al prossimo avvio."
            has_pending_restart = True
        elif override_active:
            status_label = "Override attivo"
            status_tone = "warning"
            note = f"{_ldap_source_label(next_source)} ha priorita su .env per questo campo."
            has_env_override = True
        elif next_source in {"dotenv", "process_env", "config_ini"}:
            status_label = "Allineato"
            status_tone = "success"
            note = f"Il runtime legge questo campo da {_ldap_source_label(next_source)}."
        else:
            status_label = "Default"
            status_tone = "muted"
            note = "Nessun valore persistito trovato: resta attivo il default applicativo."

        rows.append(
            {
                "key": key,
                "label": field["label"],
                "runtime_value_display": _ldap_display_field_value(field, runtime_value),
                "runtime_source_label": _ldap_source_label(runtime_source),
                "next_value_display": _ldap_display_field_value(field, next_value),
                "next_source_label": _ldap_source_label(next_source),
                "status_label": status_label,
                "status_tone": status_tone,
                "note": note,
            }
        )

    return rows, has_pending_restart, has_env_override


def _ldap_effective_form_state() -> tuple[dict[str, object], dict[str, str]]:
    dotenv_values = _load_dotenv_values()
    ini_values = _load_config_ini_ad_values()
    values: dict[str, object] = {}
    source_labels: dict[str, str] = {}

    for field in LDAP_DIAG_FIELDS:
        key = str(field["key"])
        next_value, next_source = _ldap_next_boot_value(field, dotenv_values, ini_values)
        values[key] = _ldap_form_field_value(field, next_value)
        source_labels[key] = _ldap_source_label(next_source)

    return values, source_labels


def _ldap_file_defaults(runtime_cfg: dict[str, object]) -> dict[str, object]:
    values, _source_labels = _ldap_effective_form_state()
    return values


def _ldap_effective_source_labels() -> dict[str, str]:
    _values, source_labels = _ldap_effective_form_state()
    return source_labels


def _ldap_missing_required_labels(cfg: dict[str, object], required_keys: tuple[str, ...]) -> list[str]:
    labels_by_key = {
        str(field["key"]): str(field["label"])
        for field in LDAP_DIAG_FIELDS
    }
    missing: list[str] = []

    for key in required_keys:
        if key == "enabled":
            if not _bool_from_any(cfg.get(key)):
                missing.append(labels_by_key.get(key, key))
            continue
        if not str(cfg.get(key) or "").strip():
            missing.append(labels_by_key.get(key, key))

    return missing


def _ldap_diag_defaults() -> dict[str, object]:
    allowlist = getattr(settings, "LDAP_GROUP_ALLOWLIST", []) or []
    return {
        "enabled": bool(getattr(settings, "LDAP_ENABLED", False)),
        "server": str(getattr(settings, "LDAP_SERVER", "") or ""),
        "domain": str(getattr(settings, "LDAP_DOMAIN", "") or ""),
        "upn_suffix": str(getattr(settings, "LDAP_UPN_SUFFIX", "") or ""),
        "timeout": int(getattr(settings, "LDAP_TIMEOUT", 5) or 5),
        "service_user": str(getattr(settings, "LDAP_SERVICE_USER", "") or ""),
        "base_dn": str(getattr(settings, "LDAP_BASE_DN", "") or ""),
        "user_filter": str(getattr(settings, "LDAP_USER_FILTER", "") or ""),
        "group_allowlist": ", ".join([str(v).strip() for v in allowlist if str(v).strip()]),
        "sync_page_size": int(getattr(settings, "LDAP_SYNC_PAGE_SIZE", 500) or 500),
        "sync_limit": 0,
        "sync_dry_run": True,
        "sync_replace_allowlist": False,
    }


def _smtp_diag_defaults() -> dict[str, str | bool | int]:
    return {
        "host": _effective_env_value("EMAIL_HOST", str(getattr(settings, "EMAIL_HOST", "") or "")),
        "port": _effective_env_int("EMAIL_PORT", int(getattr(settings, "EMAIL_PORT", 587) or 587)),
        "user": _effective_env_value("EMAIL_HOST_USER", str(getattr(settings, "EMAIL_HOST_USER", "") or "")),
        "password_configured": bool(
            _effective_env_value("EMAIL_HOST_PASSWORD", str(getattr(settings, "EMAIL_HOST_PASSWORD", "") or ""))
        ),
        "use_tls": _effective_env_bool("EMAIL_USE_TLS", bool(getattr(settings, "EMAIL_USE_TLS", True))),
        "use_ssl": _effective_env_bool("EMAIL_USE_SSL", bool(getattr(settings, "EMAIL_USE_SSL", False))),
        "timeout": _effective_env_int("EMAIL_TIMEOUT", int(getattr(settings, "EMAIL_TIMEOUT", 10) or 10)),
        "default_from_email": _effective_env_value(
            "DEFAULT_FROM_EMAIL",
            str(getattr(settings, "DEFAULT_FROM_EMAIL", "") or ""),
        ),
        "test_to": "",
    }

def _update_dotenv_assignments(values: dict[str, str], *, delete_keys: list[str] | None = None) -> tuple[bool, str]:
    try:
        update_env_file_values(values, dotenv_path=_dotenv_path(), delete_keys=delete_keys or [])
    except Exception as exc:
        return False, f"Errore scrittura .env: {exc}"
    return True, "Configurazione salvata in .env. Riavvia il server per applicare."


def _ldap_test_connect(server_url: str, timeout: int) -> tuple[bool, str]:
    try:
        from ldap3 import NONE, Server
    except Exception as exc:
        return False, f"ldap3 non disponibile: {exc}"
    try:
        server = Server(server_url, connect_timeout=timeout, get_info=NONE)
        # open() prova la connessione TCP senza bind credenziali
        from ldap3 import Connection
        conn = Connection(server)
        conn.open()
        # ldap3 puo' restituire None su open() anche con socket aperto.
        if not conn.closed:
            conn.unbind()
            return True, "Connessione LDAP riuscita."
        err = conn.last_error or conn.result or "nessun dettaglio disponibile"
        return False, f"Connessione LDAP fallita: {err}"
    except Exception as exc:
        return False, f"Connessione LDAP fallita: {exc}"


def _ldap_test_bind(server_url: str, timeout: int, username: str, password: str, domain: str, upn_suffix: str) -> tuple[bool, str]:
    try:
        from ldap3 import AUTO_BIND_NO_TLS, NONE, NTLM, SIMPLE, Connection, Server
    except Exception as exc:
        return False, f"ldap3 non disponibile: {exc}"

    ident = (username or "").strip()
    pwd = (password or "").strip()
    if not ident or not pwd:
        return False, "Username e password sono obbligatori per il test bind."

    if "@" in ident:
        upn = ident
        bind_dn = ident
    else:
        suffix = (upn_suffix or "").lstrip("@")
        upn = f"{ident}@{suffix}" if suffix else ident
        bind_dn = upn

    server = Server(server_url, connect_timeout=timeout, get_info=NONE)
    try:
        conn = Connection(
            server,
            user=bind_dn,
            password=pwd,
            authentication=SIMPLE,
            auto_bind=AUTO_BIND_NO_TLS,
            raise_exceptions=False,
        )
        if conn.bind():
            conn.unbind()
            return True, f"Bind LDAP riuscito con UPN ({bind_dn})."
        conn.unbind()
    except Exception as exc:
        logger.info("LDAP UPN bind test failed: %s", exc)

    if domain and "@" not in ident:
        try:
            ntlm_user = f"{domain}\\{ident}"
            conn2 = Connection(
                server,
                user=ntlm_user,
                password=pwd,
                authentication=NTLM,
                auto_bind=AUTO_BIND_NO_TLS,
                raise_exceptions=False,
            )
            if conn2.bind():
                conn2.unbind()
                return True, f"Bind LDAP riuscito con NTLM ({ntlm_user})."
            err = str(conn2.result)
            conn2.unbind()
            return False, f"Bind fallito (UPN e NTLM). Ultimo errore: {err}"
        except Exception as exc:
            return False, f"Bind fallito (UPN e NTLM): {exc}"

    return False, "Bind fallito con UPN."


def _ldap_save_service_account(service_user: str, service_password: str) -> tuple[bool, str]:
    ok, message = _update_dotenv_assignments(
        {
            "LDAP_SERVICE_USER": service_user,
            "LDAP_SERVICE_PASSWORD": service_password,
        }
    )
    if not ok:
        return ok, message
    return True, f"Service account salvato: {service_user}. Riavvia il server per applicare."


def _ldap_save_settings(
    *,
    enabled: bool,
    server: str,
    domain: str,
    upn_suffix: str,
    timeout: int,
    base_dn: str,
    user_filter: str,
    group_allowlist: str,
    sync_page_size: int,
) -> tuple[bool, str]:
    normalized_timeout = max(1, int(timeout or 5))
    normalized_page_size = max(100, min(int(sync_page_size or 500), 2000))

    ok, message = _update_dotenv_assignments(
        {
            "LDAP_ENABLED": "1" if enabled else "0",
            "LDAP_SERVER": server,
            "LDAP_DOMAIN": domain,
            "LDAP_UPN_SUFFIX": upn_suffix,
            "LDAP_TIMEOUT": str(normalized_timeout),
            "LDAP_BASE_DN": base_dn,
            "LDAP_USER_FILTER": user_filter,
            "LDAP_GROUP_ALLOWLIST": group_allowlist,
            "LDAP_SYNC_PAGE_SIZE": str(normalized_page_size),
        }
    )
    if not ok:
        return ok, message
    return True, "Configurazione LDAP salvata. Riavvia il server per applicare."


def _smtp_test_connect(
    host: str,
    port: int,
    username: str,
    password: str,
    *,
    use_tls: bool,
    use_ssl: bool,
    timeout: int,
) -> tuple[bool, str]:
    if not host:
        return False, "Server SMTP non configurato."
    if use_tls and use_ssl:
        return False, "SMTP non valido: use_tls e use_ssl non possono essere entrambi attivi."

    try:
        connection = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=host,
            port=int(port or 0),
            username=username or "",
            password=password or "",
            use_tls=bool(use_tls),
            use_ssl=bool(use_ssl),
            timeout=int(timeout or 10),
            fail_silently=False,
        )
        connection.open()
        connection.close()
        return True, "Connessione SMTP riuscita."
    except Exception as exc:
        return False, f"Connessione SMTP fallita: {exc}"


def _smtp_normalize_recipients(value) -> tuple[bool, list[str], str]:
    if value is None:
        return True, [], ""
    if isinstance(value, (list, tuple)):
        raw_items = value
    else:
        raw_items = str(value).replace(";", ",").split(",")
    recipients = [str(item).strip() for item in raw_items if str(item).strip()]
    for email in recipients:
        try:
            validate_email(email)
        except ValidationError:
            return False, [], f"Indirizzo email non valido: {email}"
    return True, recipients, ""


def _smtp_send_test_email(
    host: str,
    port: int,
    username: str,
    password: str,
    *,
    use_tls: bool,
    use_ssl: bool,
    timeout: int,
    from_email: str,
    to_email: str,
) -> tuple[bool, str]:
    sender = (from_email or "").strip()
    recipient_value = (to_email or "").strip()
    if not sender:
        return False, "Default from email obbligatoria per l'invio di test."
    try:
        validate_email(sender)
    except ValidationError:
        return False, f"Default from email non valida: {sender}"

    ok, recipients, error_message = _smtp_normalize_recipients(recipient_value)
    if not ok:
        return False, error_message
    if not recipients:
        return False, "Destinatario test obbligatorio."
    if use_tls and use_ssl:
        return False, "Configurazione SMTP non valida: TLS e SSL non possono essere entrambi attivi."

    connection = None
    try:
        connection = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=host,
            port=int(port or 0),
            username=username or "",
            password=password or "",
            use_tls=bool(use_tls),
            use_ssl=bool(use_ssl),
            timeout=int(timeout or 10),
            fail_silently=False,
        )
        message = EmailMultiAlternatives(
            subject="Test SMTP Portale Applicativo",
            body=(
                "Questa e' una mail di test inviata dal pannello Config SRV del Portale Applicativo.\n\n"
                f"Server: {host}:{port}\n"
                f"Utente SMTP: {username or '(vuoto)'}"
            ),
            from_email=sender,
            to=recipients,
            connection=connection,
        )
        sent_count = message.send(fail_silently=False)
        if sent_count < 1:
            return False, "Invio mail di test non riuscito: nessun messaggio inviato."
        return True, f"Mail di test inviata con successo a {', '.join(recipients)}."
    except Exception as exc:
        return False, f"Invio mail di test fallito: {exc}"
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def _smtp_save_settings(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    use_tls: bool,
    use_ssl: bool,
    timeout: int,
    default_from_email: str,
) -> tuple[bool, str]:
    current_password = _effective_env_value(
        "EMAIL_HOST_PASSWORD",
        str(getattr(settings, "EMAIL_HOST_PASSWORD", "") or ""),
    )
    effective_password = str(password or "").strip() or current_password
    return _update_dotenv_assignments(
        {
            "EMAIL_HOST": host,
            "EMAIL_PORT": str(port),
            "EMAIL_HOST_USER": user,
            "EMAIL_HOST_PASSWORD": effective_password,
            "EMAIL_USE_TLS": "1" if use_tls else "0",
            "EMAIL_USE_SSL": "1" if use_ssl else "0",
            "EMAIL_TIMEOUT": str(timeout),
            "DEFAULT_FROM_EMAIL": default_from_email,
        }
    )


def _role_choices():
    try:
        return list(Ruolo.objects.all().order_by("nome", "id"))
    except DatabaseError:
        return []


def _role_name_map() -> dict[int, str]:
    return {int(r.id): (r.nome or "") for r in _role_choices()}


def _perm_flag_names() -> list[str]:
    names = ["can_view"]
    for field in PERM_OPTIONAL_FIELDS:
        if legacy_table_has_column("permessi", field):
            names.append(field)
    if legacy_table_has_column("permessi", "consentito"):
        names.append("consentito")
    return names


def _get_or_create_permesso(ruolo_id: int, modulo: str, azione: str) -> Permesso:
    perm = (
        Permesso.objects.filter(
            ruolo_id=ruolo_id,
            modulo__iexact=(modulo or "").strip(),
            azione__iexact=(azione or "").strip(),
        )
        .order_by("-id")
        .first()
    )
    if perm:
        return perm
    defaults = {
        "ruolo_id": ruolo_id,
        "modulo": (modulo or "").strip(),
        "azione": (azione or "").strip(),
        "consentito": 0,
        "can_view": 0,
        "can_edit": 0,
        "can_delete": 0,
        "can_approve": 0,
    }
    return Permesso.objects.create(**defaults)


def _set_perm_field(perm: Permesso, field: str, value: bool) -> None:
    if not hasattr(perm, field):
        raise ValueError(f"Campo permesso non valido: {field}")
    setattr(perm, field, 1 if value else 0)
    update_fields = [field]
    if field == "can_view" and hasattr(perm, "consentito"):
        perm.consentito = 1 if value else 0
        update_fields.append("consentito")
    perm.save(update_fields=update_fields)


def _has_pulsanti_ordine() -> bool:
    return legacy_table_has_column("pulsanti", "ordine")


def _pulsanti_order_map() -> dict[int, int]:
    if not _has_pulsanti_ordine():
        return {}
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT id, ordine FROM pulsanti")
            rows = cursor.fetchall()
        result = {}
        for row in rows:
            try:
                result[int(row[0])] = int(row[1]) if row[1] is not None else 999999
            except (TypeError, ValueError):
                continue
        return result
    except Exception:
        return {}


def _set_pulsante_ordine(pulsante_id: int, ordine: int | None) -> None:
    if not _has_pulsanti_ordine():
        return
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("UPDATE pulsanti SET ordine = %s WHERE id = %s", [ordine, pulsante_id])
    except Exception:
        # Optional field: ignore if backend/column has issues.
        return


@dataclass
class PermRow:
    modulo: str
    azione: str
    label: str
    url: str
    values: dict[str, int]


@dataclass
class ModuloPermRow:
    """Aggregazione dei permessi a livello di modulo (non singolo pulsante)."""
    modulo: str
    pulsanti_count: int
    can_view: bool   # True se TUTTI i pulsanti del modulo hanno can_view=1
    partial: bool    # True se SOLO ALCUNI hanno can_view=1 (stato misto)


def _aggregate_to_module_rows(rows: list[PermRow]) -> list[ModuloPermRow]:
    """Aggrega una lista di PermRow in ModuloPermRow (uno per modulo)."""
    module_map: dict[str, list[PermRow]] = {}
    for row in rows:
        key = (row.modulo or "").strip() or "N/D"
        module_map.setdefault(key, []).append(row)
    result = []
    for modulo, module_rows in sorted(module_map.items(), key=lambda x: x[0].lower()):
        can_views = [bool(row.values.get("can_view", 0)) for row in module_rows]
        all_on = all(can_views)
        any_on = any(can_views)
        result.append(ModuloPermRow(
            modulo=modulo,
            pulsanti_count=len(module_rows),
            can_view=all_on,
            partial=any_on and not all_on,
        ))
    return result


def _module_perm_rows_for_role(ruolo_id: int) -> list[ModuloPermRow]:
    return _aggregate_to_module_rows(_permission_rows_for_role(ruolo_id))


def _module_perm_rows_for_user(legacy_user_id: int) -> list[ModuloPermRow]:
    return _aggregate_to_module_rows(_full_perm_rows_for_user(legacy_user_id))


def _build_gestione_accessi_data(ruolo_id: int) -> list[dict]:
    """Dati per la pagina Gestione Accessi unificata.

    Restituisce una lista ordinata per modulo, ciascuna con:
      modulo, total_count, active_count, all_on, partial, pulsanti_rows
    dove ogni riga pulsante ha: pulsante, can_view, can_edit, can_delete, can_approve.

    Carica pulsanti e permessi con 2 query (no N+1).
    """
    try:
        all_pulsanti = list(Pulsante.objects.all().order_by("modulo", "nome_visibile", "id"))
    except DatabaseError:
        return []

    # Raggruppa per modulo
    grouped: dict[str, list[Pulsante]] = {}
    for p in all_pulsanti:
        mod = (p.modulo or "").strip()
        if not mod:
            continue
        grouped.setdefault(mod, []).append(p)

    # Carica tutti i permessi per il ruolo in una query sola
    try:
        raw_perms = list(Permesso.objects.filter(ruolo_id=ruolo_id))
    except DatabaseError:
        raw_perms = []

    # Indice (modulo_lower, azione_lower) â†’ permesso piÃ¹ recente
    perm_index: dict[tuple[str, str], Permesso] = {}
    for p in raw_perms:
        key = ((p.modulo or "").strip().lower(), (p.azione or "").strip().lower())
        # In caso di duplicati usa l'id piÃ¹ alto (piÃ¹ recente)
        if key not in perm_index or int(p.id) > int(perm_index[key].id):
            perm_index[key] = p

    optional_fields = [f for f in PERM_OPTIONAL_FIELDS if legacy_table_has_column("permessi", f)]

    result: list[dict] = []
    for modulo in sorted(grouped.keys(), key=str.lower):
        pulsanti_list = grouped[modulo]
        pulsanti_rows: list[dict] = []
        active_count = 0

        for pulsante in pulsanti_list:
            azione = (pulsante.codice or "").strip()
            if not azione:
                continue
            perm = perm_index.get((modulo.lower(), azione.lower()))
            can_view = bool(getattr(perm, "can_view", 0)) or bool(getattr(perm, "consentito", 0)) if perm else False
            can_edit = bool(getattr(perm, "can_edit", 0)) if perm and "can_edit" in optional_fields else False
            can_delete = bool(getattr(perm, "can_delete", 0)) if perm and "can_delete" in optional_fields else False
            can_approve = bool(getattr(perm, "can_approve", 0)) if perm and "can_approve" in optional_fields else False
            if can_view:
                active_count += 1
            pulsanti_rows.append({
                "pulsante": pulsante,
                "azione": azione,
                "can_view": can_view,
                "can_edit": can_edit,
                "can_delete": can_delete,
                "can_approve": can_approve,
            })

        total = len(pulsanti_rows)
        result.append({
            "modulo": modulo,
            "pulsanti_rows": pulsanti_rows,
            "total_count": total,
            "active_count": active_count,
            "all_on": total > 0 and active_count == total,
            "partial": 0 < active_count < total,
            "optional_fields": optional_fields,
        })

    return result


_ACCESSI_SEMPLICE_ROUTE_ALIASES = {
    "anomalie_menu": "anomalie",
    "coming_assenze": "assenze",
    "employee_board": "dashboard",
    "dashboard_home": "dashboard",
    "scheda_dipendente": "dashboard",
    "richieste": "assenze",
}
_ACCESSI_SEMPLICE_PATH_ALIASES = {
    "/": "dashboard",
    "/dashboard": "dashboard",
    "/scheda-dipendente": "dashboard",
    "/richieste": "assenze",
    "/anomalie-menu": "anomalie",
}


def _normalize_accessi_semplice_module_key(raw_value: str) -> str:
    value = str(raw_value or "").strip().lower().replace("-", "_").replace(" ", "_")
    while "__" in value:
        value = value.replace("__", "_")
    return value.strip("._:/")


def _accessi_semplice_module_display_label(module_key: str) -> str:
    key = _normalize_accessi_semplice_module_key(module_key)
    catalog = MODULE_CATALOG.get(key) or {}
    label = str(catalog.get("label") or "").strip()
    if label:
        return label
    return key.replace("_", " ").strip().title() or "N/D"


def _infer_accessi_semplice_module_from_route(route_name: str, known_modules: set[str]) -> str:
    route = str(route_name or "").strip()
    if not route:
        return ""

    route_norm = _normalize_accessi_semplice_module_key(route)
    alias = _ACCESSI_SEMPLICE_ROUTE_ALIASES.get(route_norm)
    if alias:
        return alias

    namespace = ""
    local_name = route
    if ":" in route:
        namespace, local_name = route.split(":", 1)
        namespace_norm = _normalize_accessi_semplice_module_key(namespace)
        if namespace_norm in known_modules:
            return namespace_norm

    local_norm = _normalize_accessi_semplice_module_key(local_name)
    if local_norm in known_modules:
        return local_norm
    if local_norm.startswith("coming_"):
        coming_target = _normalize_accessi_semplice_module_key(local_norm[len("coming_"):])
        if coming_target in known_modules:
            return coming_target

    tokens = [token for token in re.split(r"[_\-]+", local_name.lower()) if token]
    if tokens:
        first_token = _normalize_accessi_semplice_module_key(tokens[0])
        if first_token in known_modules:
            return first_token
        two_tokens = _normalize_accessi_semplice_module_key("_".join(tokens[:2]))
        if two_tokens in known_modules:
            return two_tokens

    return ""


def _infer_accessi_semplice_module_from_path(path_value: str, known_modules: set[str]) -> str:
    path_norm = normalize_legacy_path(path_value or "/")
    alias = _ACCESSI_SEMPLICE_PATH_ALIASES.get(path_norm)
    if alias:
        return alias

    pieces = [piece for piece in path_norm.strip("/").split("/") if piece]
    if not pieces:
        return ""
    first_piece = pieces[0]
    full_candidate = _normalize_accessi_semplice_module_key(first_piece)
    if full_candidate in known_modules:
        return full_candidate

    split_candidate = _normalize_accessi_semplice_module_key(first_piece.split("-", 1)[0])
    if split_candidate in known_modules:
        return split_candidate
    return ""


def _infer_navigation_item_module_key(item: NavigationItem, known_modules: set[str]) -> str:
    category = getattr(item, "category", None)
    category_key = _normalize_accessi_semplice_module_key(getattr(category, "key", ""))
    if category_key and category_key in known_modules:
        return category_key

    parent_code = _normalize_accessi_semplice_module_key(getattr(item, "parent_code", ""))
    if parent_code and parent_code in known_modules:
        return parent_code

    route_candidate = _infer_accessi_semplice_module_from_route(str(item.route_name or ""), known_modules)
    if route_candidate:
        return route_candidate

    target = _navigation_item_target_payload(item)
    path_candidate = _infer_accessi_semplice_module_from_path(
        str(target.get("normalized_path") or item.url_path or ""),
        known_modules,
    )
    if path_candidate:
        return path_candidate

    return ""


def _build_accessi_semplice_rows(selected_role_id: int | None) -> list[dict]:
    """Righe sintetiche modulo->legacy/canonical/menu per la UI semplificata."""
    try:
        pulsanti = list(Pulsante.objects.all().order_by("modulo", "nome_visibile", "id"))
    except DatabaseError:
        return []

    try:
        permission_defs = list(
            PermissionDefinition.objects.filter(is_active=True).order_by("module", "code")
        )
    except Exception:
        permission_defs = []

    try:
        nav_items = list(
            NavigationItem.objects.filter(
                is_visible=True,
                is_enabled=True,
            )
            .exclude(section="admin_subnav")
            .select_related("category")
            .order_by("section", "order", "label", "id")
        )
    except Exception:
        nav_items = []

    known_modules = {
        _normalize_accessi_semplice_module_key(key)
        for key in MODULE_CATALOG.keys()
        if _normalize_accessi_semplice_module_key(key)
    }
    for pulsante in pulsanti:
        modulo_key = _normalize_accessi_semplice_module_key(pulsante.modulo or "")
        if modulo_key:
            known_modules.add(modulo_key)
    for perm in permission_defs:
        modulo_key = _normalize_accessi_semplice_module_key(perm.module or "")
        if modulo_key:
            known_modules.add(modulo_key)
    for item in nav_items:
        parent_code = _normalize_accessi_semplice_module_key(item.parent_code or "")
        if parent_code:
            known_modules.add(parent_code)

    grouped: dict[str, list[Pulsante]] = {}
    for pulsante in pulsanti:
        modulo_key = _normalize_accessi_semplice_module_key(pulsante.modulo or "")
        if not modulo_key:
            continue
        grouped.setdefault(modulo_key, []).append(pulsante)

    canonical_by_module: dict[str, list[PermissionDefinition]] = {}
    for perm in permission_defs:
        modulo_key = _normalize_accessi_semplice_module_key(perm.module or "")
        if not modulo_key:
            continue
        canonical_by_module.setdefault(modulo_key, []).append(perm)

    navigation_by_module: dict[str, list[NavigationItem]] = {}
    for item in nav_items:
        modulo_key = _infer_navigation_item_module_key(item, known_modules)
        if not modulo_key:
            continue
        navigation_by_module.setdefault(modulo_key, []).append(item)

    module_perm_map: dict[str, ModuloPermRow] = {}
    if selected_role_id is not None:
        try:
            for row in _module_perm_rows_for_role(selected_role_id):
                modulo_key = _normalize_accessi_semplice_module_key(row.modulo or "")
                if modulo_key:
                    module_perm_map[modulo_key] = row
        except DatabaseError:
            pass

    canonical_grants_map: dict[str, bool] = {}
    nav_access_map: dict[int, bool] = {}
    if selected_role_id is not None:
        try:
            canonical_rows = list(
                RolePermissionGrant.objects.filter(legacy_role_id=int(selected_role_id)).values(
                    "permission_id",
                    "enabled",
                )
            )
        except Exception:
            canonical_rows = []
        for row in canonical_rows:
            permission_code = normalize_permission_code(str(row.get("permission_id") or ""))
            if permission_code:
                canonical_grants_map[permission_code] = bool(row.get("enabled"))

        try:
            nav_rows = list(
                NavigationRoleAccess.objects.filter(legacy_role_id=int(selected_role_id)).values(
                    "item_id",
                    "can_view",
                )
            )
        except Exception:
            nav_rows = []
        for row in nav_rows:
            item_id = _int_or_none(row.get("item_id"))
            if item_id is None:
                continue
            nav_access_map[int(item_id)] = bool(row.get("can_view"))

    ui_meta_map = _pulsanti_ui_meta_map()
    rows: list[dict] = []
    all_modules = sorted(
        set(grouped.keys()) | set(canonical_by_module.keys()) | set(navigation_by_module.keys()),
        key=str.lower,
    )
    for modulo_key in all_modules:
        module_pulsanti = grouped.get(modulo_key, [])
        perm_row = module_perm_map.get(modulo_key)
        canonical_permissions = canonical_by_module.get(modulo_key, [])
        nav_module_items = navigation_by_module.get(modulo_key, [])

        enabled_values: list[bool] = []
        pulsanti_rows: list[dict] = []
        for pulsante in module_pulsanti:
            pid = int(pulsante.id)
            meta = ui_meta_map.get(pid, {})
            enabled = bool(meta.get("enabled", True))
            enabled_values.append(enabled)
            pulsanti_rows.append(
                {
                    "id": pid,
                    "label": pulsante.label,
                    "enabled": enabled,
                }
            )

        enabled_count = sum(1 for item in enabled_values if item)
        buttons_total = len(enabled_values)

        canonical_codes = [str(perm.code or "").strip() for perm in canonical_permissions if str(perm.code or "").strip()]
        canonical_enabled_count = sum(
            1 for code in canonical_codes if canonical_grants_map.get(normalize_permission_code(code), False)
        )
        canonical_total = len(canonical_codes)
        canonical_enabled = canonical_total > 0 and canonical_enabled_count == canonical_total
        canonical_partial = canonical_enabled_count > 0 and canonical_enabled_count < canonical_total

        nav_item_ids = [int(item.id) for item in nav_module_items]
        nav_enabled_count = sum(1 for item_id in nav_item_ids if nav_access_map.get(int(item_id), False))
        nav_total = len(nav_item_ids)
        nav_enabled = nav_total > 0 and nav_enabled_count == nav_total
        nav_partial = nav_enabled_count > 0 and nav_enabled_count < nav_total

        component_states: list[bool] = []
        component_partial = False
        if perm_row is not None:
            component_states.append(bool(perm_row.can_view))
            component_partial = component_partial or bool(perm_row.partial)
        if canonical_total:
            component_states.append(bool(canonical_enabled))
            component_partial = component_partial or bool(canonical_partial)
        if nav_total:
            component_states.append(bool(nav_enabled))
            component_partial = component_partial or bool(nav_partial)

        simple_enabled = bool(component_states) and all(component_states)
        simple_partial = component_partial or (bool(component_states) and any(component_states) and not all(component_states))
        display_label = _accessi_semplice_module_display_label(modulo_key)

        rows.append(
            {
                "modulo": modulo_key,
                "display_label": display_label,
                "pulsanti": pulsanti_rows,
                "pulsanti_count": len(pulsanti_rows),
                "sample_labels": [p["label"] for p in pulsanti_rows[:3]],
                "legacy_role_enabled": bool(perm_row.can_view) if perm_row else False,
                "legacy_role_partial": bool(perm_row.partial) if perm_row else False,
                "canonical_permissions_count": canonical_total,
                "canonical_permission_codes": canonical_codes,
                "canonical_enabled": canonical_enabled,
                "canonical_partial": canonical_partial,
                "navigation_items_count": nav_total,
                "navigation_item_ids": nav_item_ids,
                "navigation_enabled": nav_enabled,
                "navigation_partial": nav_partial,
                "buttons_enabled_count": enabled_count,
                "buttons_total_count": buttons_total,
                "simple_enabled": simple_enabled,
                "simple_partial": simple_partial,
            }
        )
    return rows


def _apply_accessi_semplice_changes(
    role_id: int,
    module_rows: list[dict],
    allowed_modules: set[str],
) -> tuple[int, int, int]:
    """Applica i cambiamenti richiesti dalla UI semplificata.

    Returns:
      (permessi_legacy_modificati, grant_canonici_modificati, menu_ruolo_modificati)
    """
    acl_keys = _pulsanti_acl_keys()
    module_acl_map: dict[str, list[tuple[str, str]]] = {}
    for modulo, azione in acl_keys:
        modulo_key = _normalize_accessi_semplice_module_key(modulo or "")
        if not modulo_key:
            continue
        module_acl_map.setdefault(modulo_key, []).append((modulo, azione))

    permessi_changed = 0
    canonical_changed = 0
    navigation_changed = 0

    for row in module_rows:
        modulo = str(row.get("modulo") or "").strip()
        if not modulo:
            continue
        modulo_norm = _normalize_accessi_semplice_module_key(modulo)

        should_allow = modulo in allowed_modules
        for mod, azione in module_acl_map.get(modulo_norm, []):
            perm = _get_or_create_permesso(role_id, mod, azione)
            current = bool(getattr(perm, "can_view", 0)) or bool(getattr(perm, "consentito", 0))
            if current == should_allow:
                continue
            _set_perm_field(perm, "can_view", should_allow)
            permessi_changed += 1

        for permission_code in row.get("canonical_permission_codes", []):
            permission_norm = normalize_permission_code(str(permission_code or ""))
            if not permission_norm:
                continue
            grant, _created = RolePermissionGrant.objects.update_or_create(
                legacy_role_id=int(role_id),
                permission_id=permission_norm,
                defaults={"enabled": bool(should_allow)},
            )
            if bool(grant.enabled) != bool(should_allow):
                grant.enabled = bool(should_allow)
                grant.save(update_fields=["enabled"])
            # update_or_create may still leave us unable to count changes if defaults
            # match current state; compare against row-level snapshot instead.
        current_canonical_state = bool(row.get("canonical_enabled"))
        current_canonical_partial = bool(row.get("canonical_partial"))
        if row.get("canonical_permissions_count") and (current_canonical_partial or current_canonical_state != should_allow):
            canonical_changed += int(row.get("canonical_permissions_count") or 0)

        for item_id in row.get("navigation_item_ids", []):
            nav_item_id = _int_or_none(item_id)
            if nav_item_id is None:
                continue
            NavigationRoleAccess.objects.update_or_create(
                item_id=int(nav_item_id),
                legacy_role_id=int(role_id),
                defaults={"can_view": bool(should_allow)},
            )
        current_nav_state = bool(row.get("navigation_enabled"))
        current_nav_partial = bool(row.get("navigation_partial"))
        if row.get("navigation_items_count") and (current_nav_partial or current_nav_state != should_allow):
            navigation_changed += int(row.get("navigation_items_count") or 0)

    return permessi_changed, canonical_changed, navigation_changed


def _full_perm_rows_for_user(legacy_user_id: int) -> list[PermRow]:
    """PermRow per-pulsante per un utente con override UserPermissionOverride giÃ  applicati."""
    utente = UtenteLegacy.objects.filter(id=legacy_user_id).first()
    if not utente:
        return []
    rows = _permission_rows_for_role(int(utente.ruolo_id)) if utente.ruolo_id else []
    overrides = {
        ((ov.modulo or "").strip().lower(), (ov.azione or "").strip().lower()): ov
        for ov in UserPermissionOverride.objects.filter(legacy_user_id=legacy_user_id)
    }
    for row in rows:
        key = ((row.modulo or "").strip().lower(), (row.azione or "").strip().lower())
        if key in overrides:
            ov = overrides[key]
            if ov.can_view is not None:
                row.values["can_view"] = 1 if ov.can_view else 0
    return rows


def _build_perm_detail(rows: list[PermRow]) -> dict[str, list[dict]]:
    """Raggruppa i PermRow per modulo in un dict {modulo: [{azione, label, can_view}]}."""
    result: dict[str, list[dict]] = {}
    for row in rows:
        key = (row.modulo or "").strip() or "N/D"
        result.setdefault(key, []).append({
            "azione": row.azione,
            "label": row.label or row.azione,
            "can_view": bool(row.values.get("can_view", 0)),
        })
    return result


def _group_perm_rows_by_modulo(rows: list[PermRow]) -> list[tuple[str, list[PermRow]]]:
    grouped: dict[str, list[PermRow]] = {}
    for row in rows:
        key = (row.modulo or "").strip() or "N/D"
        grouped.setdefault(key, []).append(row)
    result = []
    for modulo in sorted(grouped.keys(), key=str.lower):
        items = sorted(grouped[modulo], key=lambda r: ((r.label or "").lower(), (r.azione or "").lower()))
        result.append((modulo, items))
    return result


def _permission_rows_for_role(ruolo_id: int | None) -> list[PermRow]:
    rows: dict[tuple[str, str], PermRow] = {}

    for pulsante in Pulsante.objects.all():
        modulo = (pulsante.modulo or "").strip()
        azione = (pulsante.codice or "").strip()
        if not modulo or not azione:
            continue
        key = (modulo.lower(), azione.lower())
        rows[key] = PermRow(
            modulo=modulo,
            azione=azione,
            label=pulsante.label,
            url=(pulsante.url or "").strip(),
            values={k: 0 for k in _perm_flag_names()},
        )

    if ruolo_id is None:
        return sorted(rows.values(), key=lambda r: (r.modulo.lower(), r.label.lower(), r.azione.lower()))

    perms = Permesso.objects.filter(ruolo_id=ruolo_id).order_by("modulo", "azione", "-id")
    for perm in perms:
        modulo = (perm.modulo or "").strip()
        azione = (perm.azione or "").strip()
        if not modulo or not azione:
            continue
        key = (modulo.lower(), azione.lower())
        if key not in rows:
            rows[key] = PermRow(
                modulo=modulo,
                azione=azione,
                label=f"{modulo}:{azione}",
                url="",
                values={k: 0 for k in _perm_flag_names()},
            )
        for field in _perm_flag_names():
            rows[key].values[field] = 1 if _bool_from_any(getattr(perm, field, 0)) else 0

    return sorted(rows.values(), key=lambda r: (r.modulo.lower(), r.label.lower(), r.azione.lower()))


def _pulsanti_acl_keys() -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for pulsante in Pulsante.objects.all():
        modulo = (pulsante.modulo or "").strip()
        azione = (pulsante.codice or "").strip()
        if not modulo or not azione:
            continue
        key = (modulo, azione)
        norm = (modulo.lower(), azione.lower())
        if norm in seen:
            continue
        seen.add(norm)
        result.append(key)
    return result


@legacy_admin_required
@require_GET
def index(request):
    stats = {"utenti_attivi": 0, "ruoli": 0, "pulsanti": 0, "permessi": 0}
    try:
        stats["utenti_attivi"] = UtenteLegacy.objects.filter(attivo=True).count()
        stats["ruoli"] = Ruolo.objects.count()
        stats["pulsanti"] = Pulsante.objects.count()
        stats["permessi"] = Permesso.objects.count()
    except DatabaseError as exc:
        messages.error(request, f"Errore lettura tabelle legacy: {exc}")

    return render(request, "admin_portale/pages/index.html", {"stats": stats})


def _count_ui_pulsanti_meta_rows() -> int | None:
    _ensure_pulsanti_ui_meta_table()
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM ui_pulsanti_meta")
            row = cursor.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return None


@legacy_admin_required
@require_GET
def schema_dati(request):
    tables = []
    try:
        auth_user_count = get_user_model().objects.count()
    except Exception:
        auth_user_count = None
    try:
        profile_count = Profile.objects.count()
    except Exception:
        profile_count = None
    try:
        legacy_utenti_count = UtenteLegacy.objects.count()
    except DatabaseError:
        legacy_utenti_count = None
    try:
        legacy_ruoli_count = Ruolo.objects.count()
    except DatabaseError:
        legacy_ruoli_count = None
    try:
        legacy_permessi_count = Permesso.objects.count()
    except DatabaseError:
        legacy_permessi_count = None
    try:
        legacy_pulsanti_count = Pulsante.objects.count()
    except DatabaseError:
        legacy_pulsanti_count = None
    ui_meta_count = _count_ui_pulsanti_meta_rows()

    tables.extend(
        [
            {
                "name": "utenti",
                "layer": "SQL Server (legacy)",
                "used_for": "Anagrafica utenti del portale legacy + utenti auto-creati da login LDAP.",
                "managed_from": "Admin Portale -> Utenti",
                "notes": "Campi chiave: nome, email, ruolo, ruolo_id, attivo, password (*AD_MANAGED* per utenti LDAP).",
                "count": legacy_utenti_count,
            },
            {
                "name": "ruoli",
                "layer": "SQL Server (legacy)",
                "used_for": "Ruoli applicativi (es. admin, utente) usati da ACL e gestione utenti.",
                "managed_from": "DB legacy / (parziale) Admin Portale",
                "notes": "Il ruolo assegnato all'utente determina i permessi effettivi.",
                "count": legacy_ruoli_count,
            },
            {
                "name": "permessi",
                "layer": "SQL Server (legacy)",
                "used_for": "Matrice ACL per ruolo + modulo + azione (can_view/can_edit/...).",
                "managed_from": "Admin Portale -> Permessi",
                "notes": "Serve per autorizzare pagine/menu; se mancante o can_view=0 genera 403.",
                "count": legacy_permessi_count,
            },
            {
                "name": "pulsanti",
                "layer": "SQL Server (legacy)",
                "used_for": "Definizione menu/pulsanti (codice, label, modulo, url, icona).",
                "managed_from": "Admin Portale -> Pulsanti",
                "notes": "Usata sia per topbar dinamica sia per mappare ACL (modulo+azione). Supporta url `route:...`.",
                "count": legacy_pulsanti_count,
            },
            {
                "name": "ui_pulsanti_meta",
                "layer": "SQL Server (nuova tabella supporto Django)",
                "used_for": "Metadati UI dei pulsanti: slot, sezione, ordine UI, topbar, attivo.",
                "managed_from": "Admin Portale -> Pulsanti",
                "notes": "Tabella creata dal portale per gestire posizione/contesto senza hardcode.",
                "count": ui_meta_count,
            },
            {
                "name": "core_profile",
                "layer": "DB Django",
                "used_for": "Collegamento tra utente Django e utente legacy (legacy_user_id, ruolo snapshot).",
                "managed_from": "Automatico (login/sync)",
                "notes": "Ãˆ il ponte tra autenticazione Django e tabelle legacy.",
                "count": profile_count,
            },
            {
                "name": "auth_user",
                "layer": "DB Django",
                "used_for": "Utenti Django per sessione/login e integrazione con middleware Django.",
                "managed_from": "Automatico (sync da legacy / LDAP)",
                "notes": "Non sostituisce `utenti`: viene sincronizzata per usare auth/sessioni Django.",
                "count": auth_user_count,
            },
        ]
    )

    return render(
        request,
        "admin_portale/pages/schema_dati.html",
        {
            "tables": tables,
        },
    )


@legacy_admin_required
def ldap_diagnostica(request):
    runtime_cfg = _ldap_diag_defaults()
    defaults = _ldap_file_defaults(runtime_cfg)
    ldap_cfg_source_labels = _ldap_effective_source_labels()
    ldap_sync_cfg = {
        "sync_limit": 0,
        "sync_dry_run": True,
        "sync_replace_allowlist": False,
        "group_allowlist": str(runtime_cfg["group_allowlist"] or ""),
    }
    ldap_diag_rows, ldap_runtime_has_pending_restart, ldap_runtime_has_env_override = _ldap_diag_runtime_rows(runtime_cfg)
    smtp_defaults = _smtp_diag_defaults()
    approval_imap_status = get_approval_imap_status()
    approval_imap_form = get_approval_imap_form_defaults()
    result_connect = None
    result_bind = None
    result_service = None
    result_smtp = None
    result_approval_imap = None
    sync_result = None
    bind_username = ""

    if request.method == "POST":
        def _posted_str(key: str, fallback: str) -> str:
            if key in request.POST:
                return (request.POST.get(key) or "").strip()
            return str(fallback or "").strip()

        action = (request.POST.get("action") or "").strip().lower()
        server = _posted_str("server", defaults["server"])
        domain = _posted_str("domain", defaults["domain"])
        upn_suffix = _posted_str("upn_suffix", defaults["upn_suffix"])
        timeout = _int_or_none(request.POST.get("timeout")) if "timeout" in request.POST else None
        timeout = timeout or int(defaults["timeout"])
        base_dn = _posted_str("base_dn", defaults["base_dn"])
        user_filter = _posted_str("user_filter", defaults["user_filter"])
        group_allowlist = _posted_str("group_allowlist", defaults["group_allowlist"])
        sync_page_size = _int_or_none(request.POST.get("sync_page_size")) if "sync_page_size" in request.POST else None
        sync_page_size = sync_page_size or int(defaults["sync_page_size"])
        bind_username = (request.POST.get("bind_username") or "").strip()
        bind_password = (request.POST.get("bind_password") or "").strip()
        defaults.update(
            {
                "server": server,
                "domain": domain,
                "upn_suffix": upn_suffix,
                "timeout": timeout,
                "base_dn": base_dn,
                "user_filter": user_filter,
                "group_allowlist": group_allowlist,
                "sync_page_size": sync_page_size,
            }
        )
        if action in ("save_service_account", "test_service_bind"):
            svc_user = (request.POST.get("service_user") or "").strip()
            svc_password = (request.POST.get("service_password") or "").strip()
            defaults["service_user"] = svc_user
            if action == "save_service_account":
                ok, msg = _ldap_save_service_account(svc_user, svc_password)
                result_service = {"ok": ok, "message": msg}
                (messages.success if ok else messages.error)(request, msg)
                if ok:
                    defaults = _ldap_file_defaults(runtime_cfg)
                    ldap_cfg_source_labels = _ldap_effective_source_labels()
                    ldap_diag_rows, ldap_runtime_has_pending_restart, ldap_runtime_has_env_override = _ldap_diag_runtime_rows(runtime_cfg)
            else:
                if not server:
                    result_service = {
                        "ok": False,
                        "message": "Server LDAP non configurato nei valori effettivi. Controlla ambiente processo o .env.",
                    }
                else:
                    try:
                        ok, msg = _ldap_test_bind(server, int(timeout), svc_user, svc_password, domain, upn_suffix)
                    except Exception as exc:
                        ok, msg = False, f"Errore connessione LDAP: {exc}"
                    result_service = {"ok": ok, "message": f"[Service Account] {msg}"}
                    (messages.success if ok else messages.error)(request, result_service["message"])
        elif action in ("test_smtp_connect", "test_smtp_send", "save_smtp_config"):
            smtp_host = (request.POST.get("smtp_host") or smtp_defaults["host"]).strip()
            smtp_port = _int_or_none(request.POST.get("smtp_port")) or int(smtp_defaults["port"])
            smtp_user = (request.POST.get("smtp_user") or smtp_defaults["user"]).strip()
            smtp_password = (request.POST.get("smtp_password") or "").strip()
            smtp_use_tls = _bool_from_any(request.POST.get("smtp_use_tls"))
            smtp_use_ssl = _bool_from_any(request.POST.get("smtp_use_ssl"))
            smtp_timeout = _int_or_none(request.POST.get("smtp_timeout")) or int(smtp_defaults["timeout"])
            smtp_from_email = (request.POST.get("smtp_default_from_email") or smtp_defaults["default_from_email"]).strip()
            smtp_test_to = (request.POST.get("smtp_test_to") or smtp_defaults.get("test_to") or "").strip()

            smtp_defaults.update(
                {
                    "host": smtp_host,
                    "port": smtp_port,
                    "user": smtp_user,
                    "password_configured": bool(smtp_password or smtp_defaults.get("password_configured")),
                    "use_tls": smtp_use_tls,
                    "use_ssl": smtp_use_ssl,
                    "timeout": smtp_timeout,
                    "default_from_email": smtp_from_email,
                    "test_to": smtp_test_to,
                }
            )

            if action == "test_smtp_connect":
                effective_password = smtp_password or _effective_env_value(
                    "EMAIL_HOST_PASSWORD",
                    str(getattr(settings, "EMAIL_HOST_PASSWORD", "") or ""),
                )
                ok, msg = _smtp_test_connect(
                    smtp_host,
                    smtp_port,
                    smtp_user,
                    effective_password,
                    use_tls=smtp_use_tls,
                    use_ssl=smtp_use_ssl,
                    timeout=smtp_timeout,
                )
                result_smtp = {"ok": ok, "message": msg}
                (messages.success if ok else messages.error)(request, msg)
            elif action == "test_smtp_send":
                effective_password = smtp_password or _effective_env_value(
                    "EMAIL_HOST_PASSWORD",
                    str(getattr(settings, "EMAIL_HOST_PASSWORD", "") or ""),
                )
                ok, msg = _smtp_send_test_email(
                    smtp_host,
                    smtp_port,
                    smtp_user,
                    effective_password,
                    use_tls=smtp_use_tls,
                    use_ssl=smtp_use_ssl,
                    timeout=smtp_timeout,
                    from_email=smtp_from_email,
                    to_email=smtp_test_to,
                )
                result_smtp = {"ok": ok, "message": msg}
                (messages.success if ok else messages.error)(request, msg)
            else:
                ok, msg = _smtp_save_settings(
                    host=smtp_host,
                    port=smtp_port,
                    user=smtp_user,
                    password=smtp_password,
                    use_tls=smtp_use_tls,
                    use_ssl=smtp_use_ssl,
                    timeout=smtp_timeout,
                    default_from_email=smtp_from_email,
                )
                result_smtp = {"ok": ok, "message": msg}
                (messages.success if ok else messages.error)(request, msg)
        elif action == "save_approval_imap_config":
            posted_port = (request.POST.get("approval_imap_port") or "").strip()
            try:
                parsed_port = max(int(posted_port or approval_imap_form["port"]), 1)
            except (TypeError, ValueError):
                parsed_port = int(approval_imap_form["port"])

            approval_imap_form = {
                "host": (request.POST.get("approval_imap_host") or "").strip(),
                "port": parsed_port,
                "user": (request.POST.get("approval_imap_user") or "").strip(),
                "password": "",
                "folder": (request.POST.get("approval_imap_folder") or "").strip() or "INBOX",
                "use_ssl": _bool_from_any(request.POST.get("approval_imap_use_ssl")),
                "password_configured": bool((request.POST.get("approval_imap_password") or "").strip())
                or bool(approval_imap_form.get("password_configured")),
            }
            ok, msg = save_approval_imap_settings(
                host=str(approval_imap_form["host"]),
                port=int(approval_imap_form["port"]),
                user=str(approval_imap_form["user"]),
                password=(request.POST.get("approval_imap_password") or "").strip(),
                use_ssl=bool(approval_imap_form["use_ssl"]),
                folder=str(approval_imap_form["folder"]),
                dotenv_path=_dotenv_path(),
            )
            result_approval_imap = {"ok": ok, "message": msg, "output": "", "stats": {}}
            approval_imap_status = get_approval_imap_status()
            if ok:
                approval_imap_form = get_approval_imap_form_defaults()
            (messages.success if ok else messages.error)(request, msg)
        elif action == "run_approval_imap_poll":
            result_approval_imap = run_approval_imap_poll_now()
            approval_imap_status = get_approval_imap_status()
            (messages.success if result_approval_imap.get("ok") else messages.error)(
                request,
                str(result_approval_imap.get("message") or "Polling mailbox fallito."),
            )
        elif action == "save_ldap_config":
            enabled = _bool_from_any(request.POST.get("enabled"))
            defaults["enabled"] = enabled
            ok, msg = _ldap_save_settings(
                enabled=enabled,
                server=server,
                domain=domain,
                upn_suffix=upn_suffix,
                timeout=timeout,
                base_dn=base_dn,
                user_filter=user_filter,
                group_allowlist=group_allowlist,
                sync_page_size=sync_page_size,
            )
            result_connect = {"ok": ok, "message": msg}
            (messages.success if ok else messages.error)(request, msg)
            if ok:
                defaults = _ldap_file_defaults(runtime_cfg)
                ldap_cfg_source_labels = _ldap_effective_source_labels()
                ldap_diag_rows, ldap_runtime_has_pending_restart, ldap_runtime_has_env_override = _ldap_diag_runtime_rows(runtime_cfg)
        elif action == "test_connect":
            if not server:
                result_connect = {
                    "ok": False,
                    "message": "Server LDAP non configurato nei valori effettivi. Compila il campo oppure verifica ambiente processo e .env.",
                }
            else:
                ok, msg = _ldap_test_connect(server, int(timeout))
                result_connect = {"ok": ok, "message": msg}
                (messages.success if ok else messages.error)(request, msg)
        elif action == "test_bind":
            if not server:
                result_bind = {
                    "ok": False,
                    "message": "Server LDAP non configurato nei valori effettivi. Compila il campo oppure verifica ambiente processo e .env.",
                }
            else:
                ok, msg = _ldap_test_bind(server, int(timeout), bind_username, bind_password, domain, upn_suffix)
                result_bind = {"ok": ok, "message": msg}
                (messages.success if ok else messages.error)(request, msg)
        elif action == "sync_users":
            sync_limit = _int_or_none(request.POST.get("sync_limit")) or 0
            sync_dry_run = _bool_from_any(request.POST.get("sync_dry_run"))
            sync_replace_allowlist = _bool_from_any(request.POST.get("sync_replace_allowlist"))
            sync_group_allowlist = (request.POST.get("sync_group_allowlist") or "").strip()
            ldap_sync_cfg.update(
                {
                    "sync_limit": sync_limit,
                    "sync_dry_run": sync_dry_run,
                    "sync_replace_allowlist": sync_replace_allowlist,
                    "group_allowlist": sync_group_allowlist or str(runtime_cfg.get("group_allowlist") or ""),
                }
            )

            cmd_out = StringIO()
            cmd_err = StringIO()
            cmd_kwargs = {"stdout": cmd_out, "stderr": cmd_err}
            if sync_dry_run:
                cmd_kwargs["dry_run"] = True
            if sync_limit > 0:
                cmd_kwargs["limit"] = int(sync_limit)
            if sync_replace_allowlist:
                cmd_kwargs["replace_allowlist_memberships"] = True
            if sync_group_allowlist:
                cmd_kwargs["group_allowlist"] = sync_group_allowlist

            try:
                call_command("sync_ldap_users", **cmd_kwargs)
                out_text = (cmd_out.getvalue() or "").strip()
                err_text = (cmd_err.getvalue() or "").strip()
                full_output = "\n".join([part for part in [out_text, err_text] if part]).strip()
                sync_result = {"ok": True, "output": full_output}
                messages.success(request, "Sync utenti LDAP completata.")
            except Exception as exc:
                out_text = (cmd_out.getvalue() or "").strip()
                err_text = (cmd_err.getvalue() or "").strip()
                full_output = "\n".join([part for part in [out_text, err_text] if part]).strip()
                sync_result = {"ok": False, "output": full_output, "error": str(exc)}
                messages.error(request, f"Sync utenti LDAP fallita: {exc}")
        else:
            messages.warning(request, "Azione non riconosciuta.")

    ldap_effective_auth_missing = _ldap_missing_required_labels(defaults, ("enabled", "server"))
    ldap_effective_sync_missing = _ldap_missing_required_labels(
        defaults,
        ("enabled", "server", "service_user", "base_dn", "user_filter"),
    )

    return render(
        request,
        "admin_portale/pages/ldap_diagnostica.html",
        {
            "ldap_cfg": defaults,
            "ldap_cfg_source_labels": ldap_cfg_source_labels,
            "ldap_runtime_cfg": runtime_cfg,
            "ldap_runtime_rows": ldap_diag_rows,
            "ldap_runtime_has_pending_restart": ldap_runtime_has_pending_restart,
            "ldap_runtime_has_env_override": ldap_runtime_has_env_override,
            "ldap_effective_auth_ready": len(ldap_effective_auth_missing) == 0,
            "ldap_effective_auth_missing": ldap_effective_auth_missing,
            "ldap_effective_sync_ready": len(ldap_effective_sync_missing) == 0,
            "ldap_effective_sync_missing": ldap_effective_sync_missing,
            "ldap_sync_cfg": ldap_sync_cfg,
            "smtp_cfg": smtp_defaults,
            "approval_imap_status": approval_imap_status,
            "approval_imap_form": approval_imap_form,
            "result_connect": result_connect,
            "result_bind": result_bind,
            "result_service": result_service,
            "result_smtp": result_smtp,
            "result_approval_imap": result_approval_imap,
            "bind_username": bind_username,
            "sync_result": sync_result,
        },
    )


@legacy_admin_required
def ldap_import_utenti(request):
    """Pagina importazione selettiva utenti da LDAP/AD."""
    server_url = str(getattr(settings, "LDAP_SERVER", "") or "").strip()
    service_user = str(getattr(settings, "LDAP_SERVICE_USER", "") or "").strip()
    service_password = str(getattr(settings, "LDAP_SERVICE_PASSWORD", "") or "").strip()
    base_dn = str(getattr(settings, "LDAP_BASE_DN", "") or "").strip()
    user_filter_tmpl = str(getattr(settings, "LDAP_USER_FILTER", "") or "").strip()
    domain = str(getattr(settings, "LDAP_DOMAIN", "") or "").strip()
    upn_suffix = str(getattr(settings, "LDAP_UPN_SUFFIX", "") or "").strip()
    timeout = int(getattr(settings, "LDAP_TIMEOUT", 5) or 5)
    ldap_enabled = bool(getattr(settings, "LDAP_ENABLED", False))
    ldap_configured = bool(server_url and service_user and base_dn and user_filter_tmpl)

    if request.method == "GET":
        return render(
            request,
            "admin_portale/pages/ldap_import.html",
            {
                "ldap_enabled": ldap_enabled,
                "ldap_configured": ldap_configured,
                "ldap_server": server_url,
                "roles": _role_choices(),
            },
        )

    # POST — azioni AJAX
    action = (request.POST.get("action") or "").strip()

    if not ldap_configured:
        return JsonResponse({"ok": False, "error": "LDAP non configurato (server, service account o base DN mancanti)."}, status=400)

    try:
        from ldap3 import AUTO_BIND_NO_TLS, NONE, NTLM, SIMPLE, SUBTREE, Connection
        from ldap3 import Server as LdapServer
        from ldap3.core.exceptions import LDAPException, LDAPSocketOpenError
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"ldap3 non disponibile: {exc}"}, status=500)

    def _ldap_connect():
        srv = LdapServer(server_url, connect_timeout=timeout, get_info=NONE)
        conn = Connection(srv, user=service_user, password=service_password, authentication=SIMPLE, auto_bind=AUTO_BIND_NO_TLS, raise_exceptions=False)
        if conn.bind():
            return conn, None
        if domain and "@" not in service_user and "\\" not in service_user:
            conn2 = Connection(srv, user=f"{domain}\\{service_user}", password=service_password, authentication=NTLM, auto_bind=AUTO_BIND_NO_TLS, raise_exceptions=False)
            if conn2.bind():
                return conn2, None
        return None, f"Bind LDAP fallito: {conn.result}"

    def _first(data, key):
        raw = data.get(key)
        if isinstance(raw, list):
            return str(raw[0]).strip() if raw else ""
        return str(raw or "").strip()

    def _entry_to_user(data):
        upn = _first(data, "userPrincipalName").lower()
        mail = _first(data, "mail").lower()
        sam = _first(data, "sAMAccountName")
        given = _first(data, "givenName")
        sn = _first(data, "sn")
        display = _first(data, "displayName") or f"{given} {sn}".strip() or sam
        if not upn and sam and upn_suffix:
            upn = f"{sam.lower()}@{upn_suffix.lstrip('@')}"
        ident = upn or mail
        member_dns = data.get("memberOf") or []
        if isinstance(member_dns, str):
            member_dns = [member_dns]
        groups = []
        for dn in member_dns:
            for part in str(dn).split(","):
                chunk = part.strip()
                if chunk.upper().startswith("CN="):
                    groups.append(chunk[3:])
                    break
        return ident, sam, display, groups[:8]

    if action == "search":
        name_q = (request.POST.get("q") or "").strip()
        if name_q:
            ldap_filter = f"(&{user_filter_tmpl}(|(displayName=*{name_q}*)(sAMAccountName=*{name_q}*)(mail=*{name_q}*)))"
        else:
            ldap_filter = user_filter_tmpl

        try:
            conn, err = _ldap_connect()
            if not conn:
                return JsonResponse({"ok": False, "error": err}, status=400)
        except (LDAPSocketOpenError, LDAPException, OSError) as exc:
            return JsonResponse({"ok": False, "error": f"Connessione LDAP fallita: {exc}"}, status=400)

        attrs = ["displayName", "givenName", "sn", "mail", "userPrincipalName", "sAMAccountName", "memberOf"]
        ok = conn.search(search_base=base_dn, search_filter=ldap_filter, search_scope=SUBTREE, attributes=attrs, paged_size=500)
        if not ok:
            conn.unbind()
            return JsonResponse({"ok": False, "error": f"Ricerca LDAP fallita: {conn.result}"}, status=400)

        existing_emails = {(e or "").strip().lower() for e in UtenteLegacy.objects.values_list("email", flat=True) if e}

        users = []
        for entry in conn.entries:
            data = entry.entry_attributes_as_dict if hasattr(entry, "entry_attributes_as_dict") else {}
            ident, sam, display, groups = _entry_to_user(data)
            if not ident:
                continue
            users.append({
                "display_name": display,
                "email": ident,
                "sam": sam,
                "groups": groups,
                "already_imported": ident.lower() in existing_emails,
            })

        conn.unbind()
        users.sort(key=lambda u: (u["already_imported"], (u["display_name"] or "").lower()))
        return JsonResponse({"ok": True, "users": users, "total": len(users)})

    elif action == "import":
        selected_emails_raw = request.POST.getlist("emails[]")
        ruolo_id = _int_or_none(request.POST.get("ruolo_id"))

        if not selected_emails_raw:
            return JsonResponse({"ok": False, "error": "Nessun utente selezionato."}, status=400)

        target_set = {e.strip().lower() for e in selected_emails_raw if e.strip()}

        ruolo_name = ""
        if ruolo_id:
            try:
                ruolo_obj = Ruolo.objects.filter(id=ruolo_id).first()
                if ruolo_obj:
                    ruolo_name = (ruolo_obj.nome or "").strip()
            except DatabaseError:
                pass
        if not ruolo_name:
            try:
                default_role = Ruolo.objects.filter(nome__iexact="utente").first()
                if default_role:
                    ruolo_name = default_role.nome
                    ruolo_id = int(default_role.id)
            except DatabaseError:
                pass

        from core.legacy_utils import legacy_table_columns, sync_django_user_from_legacy
        user_cols = legacy_table_columns("utenti")
        has_json_ruoli = "ruoli" in user_cols

        # Costruisce filtro LDAP mirato se pochi utenti, altrimenti cerca tutti e filtra
        if len(target_set) <= 30:
            upn_clauses = "".join(f"(userPrincipalName={e})" for e in target_set)
            mail_clauses = "".join(f"(mail={e})" for e in target_set)
            ldap_filter = f"(&{user_filter_tmpl}(|{upn_clauses}{mail_clauses}))"
        else:
            ldap_filter = user_filter_tmpl

        try:
            conn, err = _ldap_connect()
            if not conn:
                return JsonResponse({"ok": False, "error": err}, status=400)
        except (LDAPSocketOpenError, LDAPException, OSError) as exc:
            return JsonResponse({"ok": False, "error": f"Connessione LDAP fallita: {exc}"}, status=400)

        attrs = ["displayName", "givenName", "sn", "mail", "userPrincipalName", "sAMAccountName"]
        conn.search(search_base=base_dn, search_filter=ldap_filter, search_scope=SUBTREE, attributes=attrs, paged_size=500)

        results = {"created": [], "updated": [], "errors": []}

        try:
            with transaction.atomic():
                for entry in conn.entries:
                    data = entry.entry_attributes_as_dict if hasattr(entry, "entry_attributes_as_dict") else {}
                    ident, sam, display, _groups = _entry_to_user(data)
                    if not ident:
                        continue
                    if len(target_set) > 30 and ident.lower() not in target_set:
                        continue

                    try:
                        legacy_user = UtenteLegacy.objects.filter(email__iexact=ident).first()
                        if legacy_user is None:
                            create_kwargs = {
                                "nome": display,
                                "email": ident,
                                "password": "*AD_MANAGED*",
                                "ruolo": ruolo_name,
                                "attivo": True,
                                "deve_cambiare_password": False,
                            }
                            if ruolo_id:
                                create_kwargs["ruolo_id"] = ruolo_id
                            if has_json_ruoli:
                                create_kwargs["ruoli"] = f'["{ruolo_name}"]' if ruolo_name else "[]"
                            legacy_user = UtenteLegacy.objects.create(**create_kwargs)
                            sync_django_user_from_legacy(legacy_user)
                            results["created"].append({"nome": display, "email": ident})
                            _audit_safe(request, "ldap_import_user_create", "admin_portale", {
                                "email": ident, "nome": display, "ruolo_id": ruolo_id, "ruolo": ruolo_name,
                            })
                        else:
                            changed = []
                            if (legacy_user.password or "") != "*AD_MANAGED*":
                                legacy_user.password = "*AD_MANAGED*"
                                changed.append("password")
                            if not bool(legacy_user.attivo):
                                legacy_user.attivo = True
                                changed.append("attivo")
                            if changed:
                                legacy_user.save(update_fields=changed)
                            sync_django_user_from_legacy(legacy_user)
                            results["updated"].append({"nome": display, "email": ident})
                            _audit_safe(request, "ldap_import_user_update", "admin_portale", {
                                "email": ident, "nome": display, "changed": changed,
                            })
                    except DatabaseError as exc:
                        results["errors"].append({"email": ident, "error": str(exc)})
        except Exception as exc:
            conn.unbind()
            return JsonResponse({"ok": False, "error": f"Errore durante l'importazione: {exc}"}, status=500)

        conn.unbind()
        return JsonResponse({"ok": True, "results": results})

    return JsonResponse({"ok": False, "error": "Azione non valida."}, status=400)


def _normalize_acl_diag_path(raw_path: str) -> str:
    raw = str(raw_path or "").strip()
    if not raw:
        return "/"
    if not raw.startswith("/"):
        raw = "/" + raw
    return raw


def _safe_reverse_route(route_name: str) -> tuple[str, str]:
    route = str(route_name or "").strip()
    if not route:
        return "", ""
    try:
        return reverse(route), ""
    except Exception as exc:
        return "", str(exc)


def _resolve_view_name_for_path(path_value: str) -> str:
    try:
        match = resolve(path_value)
        return str(getattr(match, "view_name", "") or "").strip()
    except Resolver404:
        return ""
    except Exception:
        return ""


def _navigation_item_target_payload(item: NavigationItem) -> dict:
    route_name = str(item.route_name or "").strip()
    url_path = str(item.url_path or "").strip()
    href = ""
    reverse_error = ""
    coming = False
    if route_name:
        href, reverse_error = _safe_reverse_route(route_name)
        if reverse_error:
            coming = True
            href = reverse("coming_admin")
    elif url_path:
        href = url_path
    else:
        coming = True
        href = reverse("coming_admin")
    if route_name == "coming_admin":
        coming = True
    is_external = str(href).lower().startswith(("http://", "https://"))
    normalized_path = normalize_legacy_path(href) if href and not is_external else ""
    return {
        "href": href,
        "normalized_path": normalized_path,
        "route_name": route_name,
        "reverse_error": reverse_error,
        "coming": coming,
        "is_external": is_external,
    }


def _role_ids_to_labels(role_ids: list[int], role_name_map: dict[int, str]) -> list[str]:
    labels: list[str] = []
    for role_id in role_ids:
        rid = int(role_id)
        role_name = role_name_map.get(rid, "?") or "?"
        labels.append(f"{rid} - {role_name}")
    return labels


def _collect_registry_matches_for_path(
    *,
    path_norm: str,
    route_name: str,
    role_name_map: dict[int, str],
) -> list[dict]:
    try:
        items = list(NavigationItem.objects.all().order_by("section", "order", "label", "id"))
    except DatabaseError:
        return []
    if not items:
        return []

    item_ids = [int(item.id) for item in items]
    access_rows = list(
        NavigationRoleAccess.objects.filter(item_id__in=item_ids, can_view=True)
        .order_by("item_id", "legacy_role_id")
    )
    access_map: dict[int, list[int]] = {}
    for row in access_rows:
        access_map.setdefault(int(row.item_id), []).append(int(row.legacy_role_id))

    matched_rows: list[dict] = []
    for item in items:
        target = _navigation_item_target_payload(item)
        item_route_name = str(item.route_name or "").strip()
        item_url_path = str(item.url_path or "").strip()
        item_url_norm = normalize_legacy_path(item_url_path) if item_url_path and item_url_path.startswith("/") else ""

        is_match = False
        if route_name and route_name == item_route_name:
            is_match = True
        if path_norm and target["normalized_path"] == path_norm:
            is_match = True
        if path_norm and item_url_norm and item_url_norm == path_norm:
            is_match = True
        if not is_match:
            continue

        role_ids = sorted(set(access_map.get(int(item.id), [])))
        matched_rows.append(
            {
                "id": int(item.id),
                "code": item.code,
                "label": item.label,
                "section": item.section,
                "group": item.group or "",
                "route_name": item.route_name or "",
                "url_path": item.url_path or "",
                "target_href": target["href"],
                "target_path": target["normalized_path"],
                "coming": bool(target["coming"]),
                "reverse_error": target["reverse_error"],
                "role_ids": role_ids,
                "role_labels": _role_ids_to_labels(role_ids, role_name_map),
                "is_visible": bool(item.is_visible),
                "is_enabled": bool(item.is_enabled),
            }
        )
    return matched_rows


def _collect_legacy_redirect_matches(*, path_norm: str, route_name: str) -> dict:
    try:
        rows = list(LegacyRedirect.objects.filter(is_enabled=True).order_by("legacy_path", "id"))
    except Exception:
        return {"inbound": [], "outbound": []}

    inbound: list[dict] = []
    outbound: list[dict] = []
    for row in rows:
        legacy_norm = normalize_legacy_path(str(row.legacy_path or "/"))
        target_route_name = str(row.target_route_name or "").strip()
        target_url_path = str(row.target_url_path or "").strip()
        target_route_path = ""
        reverse_error = ""
        target_route_norm = ""
        if target_route_name:
            target_route_path, reverse_error = _safe_reverse_route(target_route_name)
            if target_route_path:
                target_route_norm = normalize_legacy_path(target_route_path)
        target_url_norm = normalize_legacy_path(target_url_path) if target_url_path.startswith("/") else ""
        target_norm = target_route_norm or target_url_norm
        payload = {
            "id": int(row.id),
            "legacy_path": legacy_norm,
            "target_route_name": target_route_name,
            "target_route_path": target_route_path,
            "target_url_path": target_url_path,
            "target_path_normalized": target_norm,
            "reverse_error": reverse_error,
            "note": row.note or "",
        }
        if legacy_norm == path_norm:
            inbound.append(payload)
        if (route_name and target_route_name == route_name) or (target_norm and target_norm == path_norm):
            outbound.append(payload)

    return {"inbound": inbound, "outbound": outbound}


def _acl_diag_badges(*, diag: dict, registry_matches: list[dict], redirect_matches: dict) -> list[str]:
    badges: list[str] = []
    canonical_result = diag.get("canonical_result") or {}
    canonical_payload = canonical_result.get("canonical") or {}
    final_source = str(diag.get("final_decision_source") or canonical_result.get("decision_source") or "").strip()
    if canonical_payload.get("binding_found"):
        badges.append("CANONICAL_BINDING")
    if final_source == "canonical":
        badges.append("CANONICAL_DECISION")
    if final_source == "legacy_fallback":
        badges.append("LEGACY_FALLBACK")
    if final_source == "legacy_admin_bypass":
        badges.append("LEGACY_ADMIN_BYPASS")
    if final_source == "superuser_bypass":
        badges.append("SUPERUSER_BYPASS")
    if registry_matches:
        badges.append("REGISTRY")
    if diag.get("pulsante"):
        badges.append("LEGACY")
    override = diag.get("override") or {}
    if override.get("can_view") is not None:
        badges.append("OVERRIDE")
    if diag.get("admin_bypass"):
        badges.append("ADMIN BYPASS")
    inbound = (redirect_matches.get("inbound") or [])
    outbound = (redirect_matches.get("outbound") or [])
    if inbound or outbound:
        badges.append("REDIRECT")
    if any(bool(row.get("coming")) for row in registry_matches):
        badges.append("COMING")
    registry_enabled = bool(getattr(settings, "NAVIGATION_REGISTRY_ENABLED", True))
    fallback_enabled = bool(getattr(settings, "NAVIGATION_LEGACY_FALLBACK_ENABLED", False))
    if registry_enabled and fallback_enabled and not registry_matches and diag.get("pulsante"):
        badges.append("FALLBACK REGISTRY->LEGACY")
    return badges


def _acl_human_summary(diag: dict) -> dict:
    canonical_result = diag.get("canonical_result") or {}
    canonical_payload = canonical_result.get("canonical") or {}
    final_allowed = bool(diag.get("final_allowed", canonical_result.get("allowed", False)))
    final_source = str(diag.get("final_decision_source") or canonical_result.get("decision_source") or "").strip()
    permission_code = str((canonical_payload.get("binding") or {}).get("permission_code") or "")
    effective_level = str(canonical_payload.get("effective_level") or "")
    role_name = str((diag.get("role") or {}).get("nome") or "ruolo")

    if final_source == "superuser_bypass":
        return {
            "title": "Accesso consentito: bypass superuser Django.",
            "detail": "La route non e stata valutata da binding/grant perche l'utente e superuser.",
            "tone": "allow",
        }
    if final_source == "legacy_admin_bypass":
        return {
            "title": "Accesso consentito: bypass admin legacy.",
            "detail": "Il resolver ha riconosciuto l'utente come admin legacy.",
            "tone": "allow",
        }
    if final_source == "canonical":
        if final_allowed:
            if effective_level == "user_override":
                return {
                    "title": f"Accesso consentito: override utente canonico su '{permission_code}'.",
                    "detail": "La route e bindata al permission code e l'override utente ha precedenza sul grant ruolo.",
                    "tone": "allow",
                }
            return {
                "title": f"Accesso consentito: il ruolo '{role_name}' ha grant su '{permission_code}'.",
                "detail": "Decisione canonica route -> permission_code -> grant ruolo.",
                "tone": "allow",
            }
        if effective_level == "user_override":
            return {
                "title": f"Accesso negato: override utente canonico nega '{permission_code}'.",
                "detail": "L'override utente ha precedenza sul grant ruolo.",
                "tone": "deny",
            }
        role_grant = canonical_payload.get("role_grant") or {}
        if role_grant.get("exists") is False:
            return {
                "title": f"Accesso negato: route bindata a '{permission_code}' ma grant ruolo assente.",
                "detail": "Il fallback legacy non viene usato perche il binding canonico esiste.",
                "tone": "deny",
            }
        return {
            "title": f"Accesso negato: route bindata a '{permission_code}' e grant ruolo non abilitato.",
            "detail": "Decisione canonica prioritaria rispetto al legacy.",
            "tone": "deny",
        }
    if final_source == "legacy_fallback":
        if final_allowed:
            return {
                "title": "Accesso consentito dal fallback legacy.",
                "detail": "Manca un binding canonico per questa route/path; la decisione arriva dalla catena legacy.",
                "tone": "allow",
            }
        return {
            "title": "Accesso negato dal fallback legacy.",
            "detail": "Manca un binding canonico e il controllo legacy ha negato l'accesso.",
            "tone": "deny",
        }
    if final_allowed:
        return {
            "title": "Accesso consentito.",
            "detail": str(diag.get("final_reason") or canonical_result.get("reason") or ""),
            "tone": "allow",
        }
    return {
        "title": "Accesso negato.",
        "detail": str(diag.get("final_reason") or canonical_result.get("reason") or ""),
        "tone": "deny",
    }


def _permission_row_is_allowed(can_view, consentito) -> bool:
    return bool(can_view) or bool(consentito)


def _build_allowed_roles_by_permission_key() -> dict[tuple[str, str], set[int]]:
    result: dict[tuple[str, str], set[int]] = {}
    try:
        rows = list(
            Permesso.objects.all().values(
                "ruolo_id",
                "modulo",
                "azione",
                "can_view",
                "consentito",
            )
        )
    except Exception:
        return result
    for row in rows:
        if not _permission_row_is_allowed(row.get("can_view"), row.get("consentito")):
            continue
        modulo = str(row.get("modulo") or "").strip().lower()
        azione = str(row.get("azione") or "").strip().lower()
        ruolo_id = _int_or_none(row.get("ruolo_id"))
        if not modulo or not azione or ruolo_id is None:
            continue
        result.setdefault((modulo, azione), set()).add(int(ruolo_id))
    return result


def _build_override_counts_by_permission_key() -> dict[tuple[str, str], dict[str, int]]:
    result: dict[tuple[str, str], dict[str, int]] = {}
    try:
        rows = list(
            UserPermissionOverride.objects.exclude(can_view__isnull=True).values(
                "modulo",
                "azione",
                "can_view",
            )
        )
    except Exception:
        return result
    for row in rows:
        modulo = str(row.get("modulo") or "").strip().lower()
        azione = str(row.get("azione") or "").strip().lower()
        if not modulo or not azione:
            continue
        key = (modulo, azione)
        bucket = result.setdefault(key, {"allow": 0, "deny": 0})
        if bool(row.get("can_view")):
            bucket["allow"] += 1
        else:
            bucket["deny"] += 1
    return result


def _canonical_binding_matches_path(binding: RoutePermissionBinding, path_norm: str) -> bool:
    strategy = (binding.match_strategy or RoutePermissionBinding.MATCH_EXACT).lower()
    if strategy == RoutePermissionBinding.MATCH_REGEX:
        try:
            return re.search(binding.path_pattern or "", path_norm) is not None
        except re.error:
            return False
    pattern = normalize_binding_path_pattern(binding.path_pattern, for_regex=False)
    if not pattern:
        return False
    if strategy == RoutePermissionBinding.MATCH_PREFIX:
        return path_norm == pattern or path_norm.startswith(pattern + "/")
    return path_norm == pattern


def _build_permission_navigation_map_rows(
    *,
    q_filter: str,
    source_filter: str,
    selected_role_id: int | None,
    role_name_map: dict[int, str],
) -> list[dict]:
    rows_by_key: dict[str, dict] = {}
    q_norm = str(q_filter or "").strip().lower()
    allowed_roles_map = _build_allowed_roles_by_permission_key()
    override_map = _build_override_counts_by_permission_key()
    canonical_route_map: dict[str, list[RoutePermissionBinding]] = {}
    canonical_path_bindings: list[RoutePermissionBinding] = []
    canonical_grants_by_code: dict[str, dict] = {}
    registry_enabled = bool(getattr(settings, "NAVIGATION_REGISTRY_ENABLED", True))
    fallback_enabled = bool(getattr(settings, "NAVIGATION_LEGACY_FALLBACK_ENABLED", False))

    try:
        canonical_bindings = list(
            RoutePermissionBinding.objects.filter(is_active=True)
            .select_related("permission")
            .order_by("priority", "id")
        )
    except Exception:
        canonical_bindings = []
    for binding in canonical_bindings:
        route_name_norm = str(binding.route_name or "").strip().lower()
        if route_name_norm:
            canonical_route_map.setdefault(route_name_norm, []).append(binding)
        if str(binding.path_pattern or "").strip():
            canonical_path_bindings.append(binding)

    if selected_role_id is not None:
        try:
            grants = list(
                RolePermissionGrant.objects.filter(legacy_role_id=int(selected_role_id)).values(
                    "id", "permission_id", "enabled"
                )
            )
        except Exception:
            grants = []
        for grant_row in grants:
            permission_code = str(grant_row.get("permission_id") or "").strip()
            if not permission_code:
                continue
            canonical_grants_by_code[permission_code] = {
                "id": int(grant_row.get("id") or 0),
                "enabled": bool(grant_row.get("enabled")),
            }

    def ensure_row(path_norm: str) -> dict:
        key = f"path:{path_norm}"
        row = rows_by_key.get(key)
        if row is None:
            row = {
                "path": path_norm,
                "route_names": set(),
                "menu_labels": set(),
                "registry_sections": set(),
                "registry_role_ids": set(),
                "legacy_role_ids": set(),
                "source_flags": set(),
                "redirect_paths": set(),
                "override_allow": 0,
                "override_deny": 0,
                "coming": False,
                "admin_bypass": False,
                "legacy_buttons": [],
                "registry_items": [],
                "applied_override_keys": set(),
                "canonical_permissions": {},
            }
            rows_by_key[key] = row
        return row

    for route in _route_catalog():
        path = str(route.get("path") or "").strip()
        if not path:
            continue
        path_norm = normalize_legacy_path(path)
        row = ensure_row(path_norm)
        route_name = str(route.get("route_name") or "").strip()
        if route_name:
            row["route_names"].add(route_name)

    try:
        registry_items = list(NavigationItem.objects.all().order_by("section", "order", "label", "id"))
    except Exception:
        registry_items = []
    access_map: dict[int, set[int]] = {}
    if registry_items:
        access_rows = list(
            NavigationRoleAccess.objects.filter(
                item_id__in=[int(item.id) for item in registry_items],
                can_view=True,
            ).order_by("item_id", "legacy_role_id")
        )
        for row in access_rows:
            access_map.setdefault(int(row.item_id), set()).add(int(row.legacy_role_id))

    for item in registry_items:
        target = _navigation_item_target_payload(item)
        path_norm = str(target.get("normalized_path") or "").strip()
        if not path_norm:
            continue
        row = ensure_row(path_norm)
        row["source_flags"].add("REGISTRY")
        row["menu_labels"].add(str(item.label or item.code or path_norm))
        row["registry_sections"].add(str(item.section or ""))
        if target.get("coming"):
            row["coming"] = True
        if item.route_name:
            row["route_names"].add(str(item.route_name).strip())
        role_ids = access_map.get(int(item.id), set())
        row["registry_role_ids"].update(role_ids)
        row["registry_items"].append(
            {
                "id": int(item.id),
                "code": item.code,
                "label": item.label,
                "section": item.section,
                "route_name": item.route_name or "",
                "url_path": item.url_path or "",
                "role_ids": sorted(role_ids),
            }
        )

    for pulsante in get_cached_pulsanti_catalog():
        path_norm = str(pulsante.get("url_normalized") or "").strip()
        if not path_norm:
            continue
        row = ensure_row(path_norm)
        row["source_flags"].add("LEGACY")
        row["menu_labels"].add(str(pulsante.get("label") or pulsante.get("codice") or path_norm))
        row["admin_bypass"] = True
        modulo_norm = str(pulsante.get("modulo_norm") or "").strip().lower()
        codice_norm = str(pulsante.get("codice_norm") or "").strip().lower()
        perm_key = (modulo_norm, codice_norm)
        row["legacy_role_ids"].update(allowed_roles_map.get(perm_key, set()))
        if perm_key in override_map and perm_key not in row["applied_override_keys"]:
            row["applied_override_keys"].add(perm_key)
            row["override_allow"] += int(override_map[perm_key]["allow"])
            row["override_deny"] += int(override_map[perm_key]["deny"])
        row["legacy_buttons"].append(
            {
                "id": int(pulsante["id"]),
                "modulo": pulsante.get("modulo") or "",
                "azione": pulsante.get("codice") or "",
                "label": pulsante.get("label") or "",
            }
        )

    try:
        redirects = list(LegacyRedirect.objects.filter(is_enabled=True).order_by("legacy_path", "id"))
    except Exception:
        redirects = []
    for redirect_row in redirects:
        target_route_name = str(redirect_row.target_route_name or "").strip()
        target_url_path = str(redirect_row.target_url_path or "").strip()
        target_path = ""
        if target_route_name:
            target_path, _err = _safe_reverse_route(target_route_name)
        if not target_path and target_url_path.startswith("/"):
            target_path = target_url_path
        if not target_path:
            continue
        target_norm = normalize_legacy_path(target_path)
        row = ensure_row(target_norm)
        row["source_flags"].add("REDIRECT")
        row["redirect_paths"].add(normalize_legacy_path(str(redirect_row.legacy_path or "/")))
        if target_route_name:
            row["route_names"].add(target_route_name)

    rows: list[dict] = []
    for row in rows_by_key.values():
        source_flags = set(row["source_flags"])
        role_ids = sorted(set(row["registry_role_ids"]) | set(row["legacy_role_ids"]))
        selected_role_visible = selected_role_id is None or selected_role_id in role_ids

        has_override = bool(row["override_allow"] or row["override_deny"])
        is_fallback = bool(registry_enabled and fallback_enabled and "LEGACY" in source_flags and "REGISTRY" not in source_flags)
        badges: list[str] = []
        if "REGISTRY" in source_flags:
            badges.append("REGISTRY")
        if "LEGACY" in source_flags:
            badges.append("LEGACY")
        if has_override:
            badges.append("OVERRIDE")
        if row["admin_bypass"]:
            badges.append("ADMIN BYPASS")
        if row["redirect_paths"]:
            badges.append("REDIRECT")
        if row["coming"]:
            badges.append("COMING")
        if is_fallback:
            badges.append("FALLBACK")

        if source_filter == "registry" and "REGISTRY" not in source_flags:
            continue
        if source_filter == "legacy" and "LEGACY" not in source_flags:
            continue
        if source_filter == "redirect" and not row["redirect_paths"]:
            continue
        if source_filter == "override" and not has_override:
            continue
        if source_filter == "fallback" and not is_fallback:
            continue

        legacy_buttons = sorted(
            row["legacy_buttons"],
            key=lambda item: (
                str(item.get("modulo") or "").lower(),
                str(item.get("azione") or "").lower(),
                int(item.get("id") or 0),
            ),
        )
        for button in legacy_buttons:
            modulo_norm = str(button.get("modulo") or "").strip().lower()
            azione_norm = str(button.get("azione") or "").strip().lower()
            allowed_roles = sorted(allowed_roles_map.get((modulo_norm, azione_norm), set()))
            button["allowed_role_ids"] = allowed_roles
            button["selected_role_allowed"] = (
                bool(selected_role_id in allowed_roles) if selected_role_id is not None else None
            )

        if selected_role_id is not None and not selected_role_visible:
            if not legacy_buttons:
                continue

        route_names = sorted([v for v in row["route_names"] if v])
        matched_bindings: dict[int, dict] = {}
        for route_name in route_names:
            for binding in canonical_route_map.get(route_name.lower(), []):
                slot = matched_bindings.setdefault(
                    int(binding.id),
                    {"binding": binding, "matched_by": set()},
                )
                slot["matched_by"].add("route_name")
        for binding in canonical_path_bindings:
            if not _canonical_binding_matches_path(binding, row["path"]):
                continue
            slot = matched_bindings.setdefault(
                int(binding.id),
                {"binding": binding, "matched_by": set()},
            )
            slot["matched_by"].add("path_pattern")

        canonical_permissions_map: dict[str, dict] = {}
        for payload in matched_bindings.values():
            binding = payload["binding"]
            permission_code = str(binding.permission_id or "").strip()
            if not permission_code:
                continue
            permission_label = ""
            permission_module = ""
            permission_active = True
            try:
                permission_label = str(binding.permission.label or "").strip()
                permission_module = str(binding.permission.module or "").strip()
                permission_active = bool(binding.permission.is_active)
            except Exception:
                permission_label = ""
                permission_module = ""
                permission_active = True

            row_entry = canonical_permissions_map.setdefault(
                permission_code,
                {
                    "permission_code": permission_code,
                    "permission_label": permission_label,
                    "permission_module": permission_module,
                    "permission_active": permission_active,
                    "bindings": [],
                },
            )
            matched_by = sorted([value for value in payload["matched_by"] if value])
            row_entry["bindings"].append(
                {
                    "id": int(binding.id),
                    "route_name": str(binding.route_name or "").strip(),
                    "path_pattern": str(binding.path_pattern or "").strip(),
                    "match_strategy": str(binding.match_strategy or "").strip(),
                    "source_app": str(binding.source_app or "").strip(),
                    "priority": int(binding.priority or 0),
                    "matched_by": matched_by,
                }
            )

        canonical_permissions = sorted(
            canonical_permissions_map.values(),
            key=lambda item: str(item.get("permission_code") or "").lower(),
        )
        canonical_missing_grants = 0
        canonical_denied_grants = 0
        canonical_enabled_grants = 0
        for canonical_row in canonical_permissions:
            permission_code = str(canonical_row.get("permission_code") or "").strip()
            grant_info = canonical_grants_by_code.get(permission_code)
            grant_exists = grant_info is not None
            grant_enabled = bool(grant_info.get("enabled")) if grant_info else False
            canonical_row["selected_role_grant_exists"] = bool(grant_exists) if selected_role_id is not None else None
            canonical_row["selected_role_grant_enabled"] = bool(grant_enabled) if selected_role_id is not None else None
            canonical_row["selected_role_grant_id"] = int(grant_info.get("id") or 0) if grant_info else None
            canonical_row["bindings"] = sorted(
                canonical_row["bindings"],
                key=lambda item: (
                    int(item.get("priority") or 0),
                    str(item.get("route_name") or "").lower(),
                    str(item.get("path_pattern") or "").lower(),
                    int(item.get("id") or 0),
                ),
            )
            if selected_role_id is None:
                continue
            if grant_info is None:
                canonical_missing_grants += 1
            elif grant_enabled:
                canonical_enabled_grants += 1
            else:
                canonical_denied_grants += 1

        menu_labels = sorted([v for v in row["menu_labels"] if v])
        role_labels = _role_ids_to_labels(role_ids, role_name_map)
        search_blob = " ".join(
            [
                row["path"],
                " ".join(route_names),
                " ".join(menu_labels),
                " ".join(role_labels),
                " ".join(sorted(source_flags)),
                " ".join(sorted(row["registry_sections"])),
                " ".join(
                    [str(item.get("permission_code") or "") for item in canonical_permissions]
                ),
                " ".join(
                    [str(item.get("permission_label") or "") for item in canonical_permissions]
                ),
            ]
        ).lower()
        if q_norm and q_norm not in search_blob:
            continue

        rows.append(
            {
                "path": row["path"],
                "route_names": route_names,
                "menu_labels": menu_labels,
                "source_flags": sorted(source_flags),
                "source_label": " + ".join(sorted(source_flags)) if source_flags else "-",
                "registry_sections": sorted([s for s in row["registry_sections"] if s]),
                "role_ids": role_ids,
                "role_labels": role_labels,
                "selected_role_visible": bool(selected_role_visible),
                "override_allow": int(row["override_allow"]),
                "override_deny": int(row["override_deny"]),
                "redirect_paths": sorted(row["redirect_paths"]),
                "badges": badges,
                "is_fallback": is_fallback,
                "legacy_buttons_count": len(row["legacy_buttons"]),
                "registry_items_count": len(row["registry_items"]),
                "canonical_permissions_count": len(canonical_permissions),
                "canonical_permissions": canonical_permissions,
                "canonical_selected_role_missing_grants": int(canonical_missing_grants),
                "canonical_selected_role_denied_grants": int(canonical_denied_grants),
                "canonical_selected_role_enabled_grants": int(canonical_enabled_grants),
                "legacy_buttons": legacy_buttons,
                "registry_items": sorted(
                    row["registry_items"],
                    key=lambda item: (
                        str(item.get("section") or "").lower(),
                        str(item.get("label") or "").lower(),
                        int(item.get("id") or 0),
                    ),
                ),
            }
        )

    rows.sort(key=lambda r: (r["path"], ", ".join(r["route_names"])))
    return rows


@legacy_admin_required
def acl_diagnostica(request):
    source = request.POST if request.method == "POST" else request.GET
    requested_user_id = _int_or_none(source.get("legacy_user_id"))
    requested_role_id = _int_or_none(source.get("legacy_role_id"))
    path_input = str(source.get("path") or "").strip()
    route_name_input = str(source.get("route_name") or "").strip()

    selected_route_path = ""
    route_reverse_error = ""
    if route_name_input:
        selected_route_path, route_reverse_error = _safe_reverse_route(route_name_input)
        if not path_input and selected_route_path:
            path_input = selected_route_path
    if route_name_input and route_reverse_error:
        messages.warning(request, f"Route '{route_name_input}' non risolvibile: {route_reverse_error}")

    if not path_input:
        path_input = "/assenze/"
    path_value = _normalize_acl_diag_path(path_input)
    resolved_route_name = _resolve_view_name_for_path(path_value)
    effective_route_name = route_name_input or resolved_route_name
    path_normalized = normalize_legacy_path(path_value)

    current_legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    target_legacy_user = current_legacy_user
    if requested_user_id is not None:
        try:
            target_legacy_user = UtenteLegacy.objects.filter(id=requested_user_id).first()
            if target_legacy_user is None:
                messages.warning(request, f"Utente legacy ID {requested_user_id} non trovato.")
        except DatabaseError as exc:
            messages.error(request, f"Errore lettura utente legacy: {exc}")
            target_legacy_user = None

    role_choices = _role_choices()
    role_name_map = {int(role.id): str(role.nome or "") for role in role_choices}
    valid_role_ids = set(role_name_map.keys())
    if requested_role_id is not None and requested_role_id not in valid_role_ids:
        messages.warning(request, f"Ruolo legacy ID {requested_role_id} non trovato: ignorato.")
        requested_role_id = None

    legacy_diag = diagnose_permesso_for_context(
        legacy_user=target_legacy_user,
        path=path_value,
        forced_role_id=requested_role_id,
    )

    canonical_legacy_user = target_legacy_user
    if requested_role_id is not None:
        role_name = role_name_map.get(int(requested_role_id), "")
        if target_legacy_user is not None:
            canonical_legacy_user = UtenteLegacy(
                id=target_legacy_user.id,
                nome=target_legacy_user.nome,
                email=target_legacy_user.email,
                password=target_legacy_user.password,
                ruolo=role_name or target_legacy_user.ruolo,
                attivo=target_legacy_user.attivo,
                deve_cambiare_password=target_legacy_user.deve_cambiare_password,
                ruolo_id=requested_role_id,
            )
        else:
            canonical_legacy_user = UtenteLegacy(
                id=-1,
                nome=f"Simulazione ruolo #{requested_role_id}",
                email="",
                password="",
                ruolo=role_name or "",
                attivo=True,
                deve_cambiare_password=False,
                ruolo_id=requested_role_id,
            )

    canonical_diag = diagnose_acl_access(
        path=path_value,
        legacy_user=canonical_legacy_user,
        # In diagnostica admin mostriamo la decisione ACL "reale" del target legacy
        # senza bypass automatico del superuser che sta consultando la pagina.
        django_user=None,
    )
    diag = dict(legacy_diag)
    diag["legacy_result"] = legacy_diag
    diag["canonical_result"] = canonical_diag
    diag["final_allowed"] = bool(canonical_diag.get("allowed", False))
    diag["final_reason"] = str(canonical_diag.get("reason") or legacy_diag.get("reason") or "")
    diag["final_decision_source"] = str(canonical_diag.get("decision_source") or legacy_diag.get("decision_source") or "")
    diag["route_name_canonical"] = str(canonical_diag.get("route_name") or "")
    diag["path_normalized"] = str(canonical_diag.get("path_normalized") or legacy_diag.get("path_normalized") or "")
    diag["trace"] = list(canonical_diag.get("trace") or [])

    if requested_user_id is not None and not target_legacy_user:
        diag["reason"] = diag.get("reason") or "Utente legacy richiesto non disponibile."

    registry_matches = _collect_registry_matches_for_path(
        path_norm=path_normalized,
        route_name=effective_route_name,
        role_name_map=role_name_map,
    )
    redirect_matches = _collect_legacy_redirect_matches(
        path_norm=path_normalized,
        route_name=effective_route_name,
    )
    diag["route_resolution"] = {
        "selected_route_name": route_name_input,
        "selected_route_path": selected_route_path,
        "resolved_route_name": resolved_route_name,
        "path_normalized": path_normalized,
    }
    diag["registry_matches"] = registry_matches
    diag["redirect_matches"] = redirect_matches
    diag["badges"] = _acl_diag_badges(
        diag=diag,
        registry_matches=registry_matches,
        redirect_matches=redirect_matches,
    )
    diag["human_summary"] = _acl_human_summary(diag)
    diag["navigation_summary"] = {
        "registry_match_count": len(registry_matches),
        "redirect_inbound_count": len(redirect_matches.get("inbound") or []),
        "redirect_outbound_count": len(redirect_matches.get("outbound") or []),
        "legacy_acl_match": bool(legacy_diag.get("pulsante")),
    }

    return render(
        request,
        "admin_portale/pages/acl_diagnostica.html",
        {
            "diag": diag,
            "path_value": path_value,
            "route_name_value": route_name_input,
            "requested_user_id": requested_user_id if requested_user_id is not None else "",
            "requested_role_id": requested_role_id if requested_role_id is not None else "",
            "current_legacy_user": current_legacy_user,
            "target_legacy_user": target_legacy_user,
            "route_catalog": _route_catalog(),
            "role_choices": role_choices,
        },
    )


@legacy_admin_required
@require_GET
def mappa_permessi_navigazione(request):
    q_filter = str(request.GET.get("q") or "").strip()
    source_filter = str(request.GET.get("source") or "all").strip().lower()
    if source_filter not in {"all", "registry", "legacy", "redirect", "override", "fallback"}:
        source_filter = "all"

    selected_role_id = _int_or_none(request.GET.get("legacy_role_id"))
    role_choices = _role_choices()
    role_name_map = {int(role.id): str(role.nome or "") for role in role_choices}
    if selected_role_id is not None and selected_role_id not in set(role_name_map.keys()):
        messages.warning(request, f"Ruolo legacy ID {selected_role_id} non trovato: filtro ignorato.")
        selected_role_id = None

    rows = _build_permission_navigation_map_rows(
        q_filter=q_filter,
        source_filter=source_filter,
        selected_role_id=selected_role_id,
        role_name_map=role_name_map,
    )
    summary = {
        "rows_total": len(rows),
        "rows_canonical": sum(1 for row in rows if row["canonical_permissions_count"] > 0),
        "rows_registry": sum(1 for row in rows if "REGISTRY" in row["source_flags"]),
        "rows_legacy": sum(1 for row in rows if "LEGACY" in row["source_flags"]),
        "rows_override": sum(1 for row in rows if "OVERRIDE" in row["badges"]),
        "rows_redirect": sum(1 for row in rows if "REDIRECT" in row["badges"]),
    }
    selected_role_label = ""
    if selected_role_id is not None:
        selected_role_label = role_name_map.get(int(selected_role_id), "")

    return render(
        request,
        "admin_portale/pages/mappa_permessi_navigazione.html",
        {
            "rows": rows,
            "summary": summary,
            "filters": {
                "q": q_filter,
                "source": source_filter,
                "legacy_role_id": selected_role_id if selected_role_id is not None else "",
            },
            "role_choices": role_choices,
            "selected_role_id": selected_role_id,
            "selected_role_label": selected_role_label,
            "api_permessi_toggle_url": reverse("admin_portale:api_permessi_toggle"),
            "api_acl_v2_role_grant_toggle_url": reverse("admin_portale:api_acl_v2_role_grant_toggle"),
        },
    )


@legacy_admin_required
@require_GET
def utenti_list(request):
    q = (request.GET.get("q") or "").strip()
    attivo_filter = (request.GET.get("attivo") or "").strip()
    ruolo_filter = (request.GET.get("ruolo_id") or "").strip()
    pwd_filter = (request.GET.get("pwd_change") or "").strip()
    current_legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)

    utenti_qs = UtenteLegacy.objects.all().order_by("id")
    if q:
        utenti_qs = utenti_qs.filter(Q(nome__icontains=q) | Q(email__icontains=q))
    if attivo_filter in {"0", "1"}:
        utenti_qs = utenti_qs.filter(attivo=bool(int(attivo_filter)))
    if ruolo_filter.isdigit():
        utenti_qs = utenti_qs.filter(ruolo_id=int(ruolo_filter))
    if pwd_filter in {"0", "1"}:
        utenti_qs = utenti_qs.filter(deve_cambiare_password=bool(int(pwd_filter)))

    paginator = Paginator(utenti_qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    utenti_page = list(page_obj.object_list)
    _attach_anagrafica_to_users(utenti_page)
    page_obj.object_list = utenti_page
    roles = _role_choices()
    role_map = {int(r.id): r for r in roles}

    return render(
        request,
        "admin_portale/pages/utenti_list.html",
        {
            "page_obj": page_obj,
            "roles": roles,
            "role_map": role_map,
            "filters": {"q": q, "attivo": attivo_filter, "ruolo_id": ruolo_filter, "pwd_change": pwd_filter},
            "create_form": UtenteCreateForm(initial={"attivo": True, "deve_cambiare_password": True}),
            "current_legacy_user_id": int(current_legacy_user.id) if current_legacy_user else None,
        },
    )


def _attach_anagrafica_to_users(users: list[UtenteLegacy]) -> None:
    """Arricchisce gli utenti con campi da anagrafica_dipendenti.

    Strategia: JOIN diretto via utente_id (FK) se disponibile,
    con fallback a match per email/alias per record non ancora collegati.
    """
    if not users:
        return
    cols = legacy_table_columns("anagrafica_dipendenti")
    if not cols:
        return

    selectable = ["id", "utente_id", "email", "email_notifica", "reparto", "mansione", "aliasusername", "attivo"]
    select_cols = [c for c in selectable if c in cols]
    has_utente_id = "utente_id" in select_cols

    user_ids = [int(u.id) for u in users if u.id]
    if not user_ids:
        return

    by_utente_id: dict[int, dict] = {}
    orphans: list[dict] = []

    try:
        if has_utente_id:
            placeholders = ", ".join(["%s"] * len(user_ids))
            sql = (
                f"SELECT {', '.join(select_cols)} FROM anagrafica_dipendenti "
                f"WHERE utente_id IN ({placeholders})"
            )
            with connections["default"].cursor() as cur:
                cur.execute(sql, user_ids)
                db_cols = [str(c[0]).lower() for c in cur.description]
                for row in cur.fetchall():
                    record = dict(zip(db_cols, row))
                    uid = record.get("utente_id")
                    if uid is not None:
                        by_utente_id[int(uid)] = record

        # Fallback per utenti non ancora collegati tramite FK
        unlinked = [u for u in users if int(u.id) not in by_utente_id]
        if unlinked and "email" in cols:
            emails = sorted({str(u.email or "").strip().lower() for u in unlinked if str(u.email or "").strip()})
            aliases = sorted(
                {
                    str(u.email or "").strip().lower().split("@", 1)[0]
                    for u in unlinked
                    if "@" in str(u.email or "").strip().lower()
                }
            )
            if emails or aliases:
                where_parts: list[str] = []
                params: list[str] = []
                if emails:
                    where_parts.append("LOWER(COALESCE(email,'')) IN (" + ", ".join(["%s"] * len(emails)) + ")")
                    params.extend(emails)
                if aliases and "aliasusername" in select_cols:
                    where_parts.append(
                        "LOWER(COALESCE(aliasusername,'')) IN (" + ", ".join(["%s"] * len(aliases)) + ")"
                    )
                    params.extend(aliases)
                if where_parts:
                    sql = (
                        f"SELECT {', '.join(select_cols)} FROM anagrafica_dipendenti "
                        "WHERE " + " OR ".join(where_parts)
                    )
                    with connections["default"].cursor() as cur:
                        cur.execute(sql, params)
                        db_cols = [str(c[0]).lower() for c in cur.description]
                        orphans = [dict(zip(db_cols, row)) for row in cur.fetchall()]
    except Exception:
        return

    for u in users:
        uid = int(u.id)
        row: dict = by_utente_id.get(uid, {})

        if not row and orphans:
            user_email = str(u.email or "").strip().lower()
            user_alias = user_email.split("@", 1)[0] if "@" in user_email else ""
            best_score = -1
            for cand in orphans:
                row_email = str(cand.get("email") or "").strip().lower()
                row_alias = str(cand.get("aliasusername") or "").strip().lower()
                score = 0
                if row_email and row_email == user_email:
                    score += 8
                elif user_alias and row_alias and row_alias == user_alias:
                    score += 5
                else:
                    continue
                if str(cand.get("reparto") or "").strip():
                    score += 2
                if str(cand.get("mansione") or "").strip():
                    score += 1
                if score > best_score:
                    best_score = score
                    row = cand

        u.anagrafica_reparto = str(row.get("reparto") or "").strip()
        u.anagrafica_mansione = str(row.get("mansione") or "").strip()
        u.anagrafica_aliasusername = str(row.get("aliasusername") or "").strip()
        u.anagrafica_email_notifica = str(row.get("email_notifica") or "").strip()
        raw_attivo = row.get("attivo")
        if raw_attivo is None:
            u.anagrafica_attivo = None
        else:
            u.anagrafica_attivo = bool(raw_attivo)


def _sync_legacy_user_to_anagrafica(utente: UtenteLegacy, *, force_active: bool | None = None) -> dict:
    ensure_anagrafica_schema()
    return sync_anagrafica_from_legacy_user(utente, force_active=force_active)


def _load_caporeparto_options() -> list[dict[str, str]]:
    """Carica le opzioni caporeparto configurate localmente nel portale."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for option in OptioneConfig.objects.filter(tipo__iexact="caporeparto", is_active=True).order_by("ordine", "valore", "id"):
        txt = str(option.valore or "").strip()
        legacy_user_id = _int_or_none(getattr(option, "legacy_user_id", None))
        key = str(legacy_user_id or txt).strip().casefold()
        if not txt or key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "value": txt,
                "label": format_caporeparto_label(txt, legacy_user_id=legacy_user_id),
                "title": txt,
                "legacy_user_id": str(legacy_user_id or ""),
            }
        )

    return out


@legacy_admin_required
@require_GET
def utente_edit(request, user_id: int):
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    current_legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    roles = _role_choices()
    flag_names = _perm_flag_names()

    # Permessi del ruolo
    perm_rows: list[PermRow] = []
    grouped_perm_rows: list[tuple[str, list[PermRow]]] = []
    if utente.ruolo_id:
        try:
            perm_rows = _permission_rows_for_role(int(utente.ruolo_id))
            grouped_perm_rows = _group_perm_rows_by_modulo(perm_rows)
        except DatabaseError:
            pass

    # Override per-utente (mappa {(modulo, azione): dict_flags})
    overrides_map: dict[str, dict] = {}
    try:
        for ov in UserPermissionOverride.objects.filter(legacy_user_id=utente.id):
            key = f"{ov.modulo}|{ov.azione}"
            overrides_map[key] = {
                "can_view": ov.can_view,
                "can_edit": ov.can_edit,
                "can_delete": ov.can_delete,
                "can_approve": ov.can_approve,
            }
    except Exception:
        pass

    # Dashboard: tutti i pulsanti del ruolo + visibilitÃ  per-utente (pulsante + modulo)
    dash_by_module: list[dict] = []
    module_vis_map: dict[str, bool] = {}
    try:
        dash_hidden: set[int] = {
            row.pulsante_id
            for row in UserDashboardConfig.objects.filter(legacy_user_id=utente.id, visible=False)
        }
        module_vis_map = {
            mv.modulo.lower(): mv.visible
            for mv in UserModuleVisibility.objects.filter(legacy_user_id=utente.id)
        }
        # Costruisce lista flat, poi raggruppa per modulo
        flat: list[dict] = []
        for pr in perm_rows:
            try:
                puls = Pulsante.objects.filter(
                    modulo__iexact=pr.modulo, codice__iexact=pr.azione
                ).first()
                if not puls:
                    continue
                pid = int(puls.id)
                modulo_display = (puls.modulo or pr.modulo or "Generale").strip() or "Generale"
                flat.append({
                    "pulsante_id": pid,
                    "name": puls.label,
                    "modulo": modulo_display,
                    "url": (puls.url or "").strip(),
                    "puls_visible": pid not in dash_hidden,
                })
            except Exception:
                continue

        # Raggruppa per modulo mantenendo l'ordine di prima comparsa
        seen_mod: dict[str, dict] = {}
        for item in flat:
            mod = item["modulo"]
            if mod not in seen_mod:
                seen_mod[mod] = {
                    "modulo": mod,
                    "module_visible": module_vis_map.get(mod.lower(), True),
                    "pulsanti": [],
                }
            seen_mod[mod]["pulsanti"].append(item)
        dash_by_module = list(seen_mod.values())
    except Exception:
        pass

    # Anagrafica: lookup via utente_id (FK) con fallback su email
    anagrafica_row: dict | None = None
    try:
        all_cols = legacy_table_columns("anagrafica_dipendenti")
        selectable = ["nome", "cognome", "reparto", "mansione", "email", "email_notifica", "aliasusername", "attivo", "utente_id"]
        select_cols = [c for c in selectable if c in all_cols]
        if select_cols:
            with connections["default"].cursor() as cur:
                if "utente_id" in all_cols:
                    cur.execute(
                        f"SELECT {', '.join(select_cols)} FROM anagrafica_dipendenti WHERE utente_id = %s",
                        [utente.id],
                    )
                    row = cur.fetchone()
                    if not row and utente.email:
                        cur.execute(
                            f"SELECT {', '.join(select_cols)} FROM anagrafica_dipendenti WHERE LOWER(email) = LOWER(%s)",
                            [utente.email.strip()],
                        )
                        row = cur.fetchone()
                elif utente.email:
                    cur.execute(
                        f"SELECT {', '.join(select_cols)} FROM anagrafica_dipendenti WHERE LOWER(email) = LOWER(%s)",
                        [utente.email.strip()],
                    )
                    row = cur.fetchone()
                else:
                    row = None
                if row:
                    anagrafica_row = dict(zip([c[0] for c in cur.description], row))
    except Exception:
        pass

    # Extra info (upsert on save)
    extra_info = UserExtraInfo.objects.filter(legacy_user_id=utente.id).first()

    # Asset assegnabili/assegnati al dipendente
    assets_for_assignment = []
    asset_assigned_ids: list[int] = []
    asset_model = _asset_model()
    if asset_model is not None:
        try:
            assets_for_assignment = list(
                asset_model.objects.all()
                .order_by("asset_tag", "name", "id")
                .only("id", "asset_tag", "name", "status", "assignment_to", "assigned_legacy_user_id")
            )
            asset_assigned_ids = [
                int(a.id)
                for a in assets_for_assignment
                if int(getattr(a, "assigned_legacy_user_id", 0) or 0) == int(utente.id)
            ]
        except Exception:
            assets_for_assignment = []
            asset_assigned_ids = []

    # Opzioni dropdown configurabili (reparto, caporeparto, macchina, ...)
    opzioni_by_tipo: dict[str, list[str]] = {}
    for o in OptioneConfig.objects.filter(is_active=True):
        opzioni_by_tipo.setdefault(o.tipo, []).append(o.valore)
    caporeparto_options = _load_caporeparto_options()

    # Campi extra anagrafica configurabili
    anagrafica_voci = list(AnagraficaVoce.objects.filter(is_active=True).order_by("categoria", "ordine", "id"))
    for v in anagrafica_voci:
        v.scelte_json = json.dumps(v.scelte)

    # Risposte salvate per questo utente
    anagrafica_risposte_map: dict[int, str] = {
        r.voce_id: r.valore
        for r in AnagraficaRisposta.objects.filter(legacy_user_id=utente.id)
    }

    # Onboarding wizard primo accesso
    onboarding_data = None
    django_user_id = None
    ui_prefs_data = None
    try:
        from core.models import Profile, UserOnboarding
        _profile = Profile.objects.filter(legacy_user_id=utente.id).select_related("user").first()
        if _profile:
            django_user_id = _profile.user_id
            onboarding_data = UserOnboarding.objects.filter(user_id=django_user_id).first()
            ui_prefs_data = UserUiPreference.objects.filter(user_id=django_user_id).first()
    except Exception:
        pass

    return render(
        request,
        "admin_portale/pages/utente_edit.html",
        {
            "utente_obj": utente,
            "roles": roles,
            "flag_names": flag_names,
            "grouped_perm_rows": grouped_perm_rows,
            "overrides_map_json": json.dumps(overrides_map),
            "dash_by_module": dash_by_module,
            "module_vis_json": json.dumps(module_vis_map),
            "anagrafica_row": anagrafica_row,
            "extra_info": extra_info,
            "assets_for_assignment": assets_for_assignment,
            "asset_assigned_ids": asset_assigned_ids,
            "opzioni_by_tipo": opzioni_by_tipo,
            "caporeparto_options": caporeparto_options,
            "anagrafica_voci": anagrafica_voci,
            "anagrafica_risposte_map": anagrafica_risposte_map,
            "anagrafica_risposte_json": json.dumps(anagrafica_risposte_map),
            "checklist_checkin":  ChecklistEsecuzione.objects.filter(legacy_user_id=utente.id, tipo_checklist="checkin").first(),
            "checklist_checkout": ChecklistEsecuzione.objects.filter(legacy_user_id=utente.id, tipo_checklist="checkout").first(),
            "current_legacy_user_id": int(current_legacy_user.id) if current_legacy_user else None,
            "onboarding_data": onboarding_data,
            "django_user_id": django_user_id,
            "ui_prefs_data": ui_prefs_data,
        },
    )


@legacy_admin_required
@csrf_protect
@require_POST
def utente_create(request):
    form = UtenteCreateForm(request.POST)
    if not form.is_valid():
        messages.error(request, f"Dati nuovo utente non validi: {form.errors.as_text()}")
        return redirect("admin_portale:utenti_list")

    data = form.cleaned_data
    ruolo_id = _int_or_none(data.get("ruolo_id"))
    ruolo_name = ""
    if ruolo_id:
        try:
            ruolo = Ruolo.objects.filter(id=ruolo_id).first()
            if ruolo:
                ruolo_name = (ruolo.nome or "").strip()
        except DatabaseError:
            ruolo_name = ""

    if bool(data.get("ad_managed")):
        password_value = "*AD_MANAGED*"
    else:
        password_value = generate_password_hash((data.get("password_iniziale") or "").strip())

    try:
        with transaction.atomic():
            utente = UtenteLegacy.objects.create(
                nome=(data.get("nome") or "").strip(),
                email=(data.get("email") or "").strip(),
                password=password_value,
                ruolo=ruolo_name,
                ruolo_id=ruolo_id,
                attivo=bool(data.get("attivo")),
                deve_cambiare_password=bool(data.get("deve_cambiare_password")),
            )
            _sync_legacy_user_to_anagrafica(utente)
        _audit_safe(request, "utente_create", "admin_portale", {
            "target_legacy_user_id": int(utente.id),
            "nome": utente.nome,
            "email": utente.email,
            "ruolo_id": utente.ruolo_id,
            "ruolo": utente.ruolo,
            "attivo": bool(utente.attivo),
            "ad_managed": bool(data.get("ad_managed")),
        })
        messages.success(request, f"Utente creato (ID {utente.id}).")
    except DatabaseError as exc:
        messages.error(request, f"Errore creazione utente: {exc}")
    except Exception as exc:
        messages.error(request, f"Errore creazione utente/anagrafica: {exc}")

    return redirect("admin_portale:utenti_list")


def _delete_legacy_user_with_dependencies(utente: UtenteLegacy) -> dict[str, int]:
    profile = Profile.objects.select_related("user").filter(legacy_user_id=utente.id).first()
    django_user_id = int(profile.user_id) if profile and profile.user_id else 0
    asset_model = _asset_model()
    released_assets = 0

    with transaction.atomic():
        if asset_model is not None:
            released_assets = int(
                asset_model.objects.filter(assigned_legacy_user_id=utente.id).update(
                    assigned_legacy_user_id=None,
                    assignment_to="",
                    assignment_reparto="",
                )
            )

        UserPermissionOverride.objects.filter(legacy_user_id=utente.id).delete()
        UserDashboardConfig.objects.filter(legacy_user_id=utente.id).delete()
        UserModuleVisibility.objects.filter(legacy_user_id=utente.id).delete()
        UserDashboardLayout.objects.filter(legacy_user_id=utente.id).delete()
        UserExtraInfo.objects.filter(legacy_user_id=utente.id).delete()
        EmployeeBoardConfig.objects.filter(legacy_user_id=utente.id).delete()
        AnagraficaRisposta.objects.filter(legacy_user_id=utente.id).delete()
        ChecklistEsecuzione.objects.filter(legacy_user_id=utente.id).delete()
        Notifica.objects.filter(legacy_user_id=utente.id).delete()
        anagrafica_unlinked = int(AnagraficaDipendente.objects.filter(utente_id=utente.id).update(utente=None))

        if profile and profile.user_id:
            profile.user.delete()
        else:
            Profile.objects.filter(legacy_user_id=utente.id).delete()

        utente.delete()

    return {
        "django_user_id": django_user_id,
        "released_assets": released_assets,
        "anagrafica_unlinked": anagrafica_unlinked,
    }


@legacy_admin_required
@csrf_protect
@require_POST
def utente_update(request, user_id: int):
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    form = UtenteUpdateForm(request.POST)
    if not form.is_valid():
        messages.error(request, f"Dati non validi: {form.errors.as_text()}")
        return redirect("admin_portale:utente_edit", user_id=user_id)

    data = form.cleaned_data
    utente.nome = (data.get("nome") or "").strip()
    utente.email = (data.get("email") or "").strip()
    utente.attivo = bool(data.get("attivo"))
    utente.ruolo_id = _int_or_none(data.get("ruolo_id"))
    utente.deve_cambiare_password = bool(data.get("deve_cambiare_password")) or bool(data.get("force_password_reset"))

    if utente.ruolo_id:
        try:
            ruolo = Ruolo.objects.filter(id=utente.ruolo_id).first()
            if ruolo:
                utente.ruolo = (ruolo.nome or "").strip()
        except DatabaseError:
            pass

    try:
        with transaction.atomic():
            utente.save()
            _sync_legacy_user_to_anagrafica(utente)
        _audit_safe(request, "utente_update", "admin_portale", {
            "target_legacy_user_id": int(utente.id),
            "nome": utente.nome,
            "email": utente.email,
            "ruolo_id": utente.ruolo_id,
            "ruolo": utente.ruolo,
            "attivo": bool(utente.attivo),
            "deve_cambiare_password": bool(utente.deve_cambiare_password),
        })
        messages.success(request, f"Utente #{utente.id} aggiornato.")
    except DatabaseError as exc:
        messages.error(request, f"Errore salvataggio utente: {exc}")
    except Exception as exc:
        messages.error(request, f"Errore sincronizzazione utente/anagrafica: {exc}")

    return redirect("admin_portale:utente_edit", user_id=user_id)


@legacy_admin_required
@csrf_protect
@require_POST
def utenti_bulk_role(request):
    form = BulkRoleForm(request.POST)
    if not form.is_valid():
        messages.error(request, f"Dati non validi: {form.errors.as_text()}")
        return redirect("admin_portale:utenti_list")

    ids_from_checkboxes = [_int_or_none(v) for v in request.POST.getlist("user_ids")]
    ids = [v for v in ids_from_checkboxes if v is not None]
    ids = ids or form.cleaned_user_ids()
    ruolo_id = form.cleaned_data["ruolo_id"]
    role_name = _role_name_map().get(int(ruolo_id), "")

    if not ids:
        messages.warning(request, "Nessun utente selezionato.")
        return redirect("admin_portale:utenti_list")

    try:
        with transaction.atomic():
            UtenteLegacy.objects.filter(id__in=ids).update(ruolo_id=ruolo_id, ruolo=role_name)
        _audit_safe(request, "utenti_bulk_role", "admin_portale", {
            "target_user_ids": ids,
            "ruolo_id": ruolo_id,
            "ruolo": role_name,
            "count": len(ids),
        })
        messages.success(request, f"Ruolo aggiornato per {len(ids)} utenti.")
    except DatabaseError as exc:
        messages.error(request, f"Errore aggiornamento massivo: {exc}")

    return redirect("admin_portale:utenti_list")


@legacy_admin_required
@csrf_protect
@require_POST
def utenti_bulk_action(request):
    ids_from_checkboxes = [_int_or_none(v) for v in request.POST.getlist("user_ids")]
    ids = [v for v in ids_from_checkboxes if v is not None]
    mode = (request.POST.get("bulk_mode") or "").strip().lower()
    if not ids:
        messages.warning(request, "Nessun utente selezionato.")
        return redirect("admin_portale:utenti_list")

    try:
        with transaction.atomic():
            if mode == "activate":
                updated_users = list(UtenteLegacy.objects.filter(id__in=ids))
                UtenteLegacy.objects.filter(id__in=ids).update(attivo=True)
                for utente in updated_users:
                    utente.attivo = True
                    _sync_legacy_user_to_anagrafica(utente, force_active=True)
                _audit_safe(request, "utenti_bulk_activate", "admin_portale", {"target_user_ids": ids, "count": len(ids)})
                messages.success(request, f"Attivati {len(ids)} utenti.")
            elif mode == "deactivate":
                updated_users = list(UtenteLegacy.objects.filter(id__in=ids))
                UtenteLegacy.objects.filter(id__in=ids).update(attivo=False)
                for utente in updated_users:
                    utente.attivo = False
                    _sync_legacy_user_to_anagrafica(utente, force_active=False)
                _audit_safe(request, "utenti_bulk_deactivate", "admin_portale", {"target_user_ids": ids, "count": len(ids)})
                messages.success(request, f"Disattivati {len(ids)} utenti.")
            elif mode == "force_pwd":
                UtenteLegacy.objects.filter(id__in=ids).update(deve_cambiare_password=True)
                _audit_safe(request, "utenti_bulk_force_pwd", "admin_portale", {"target_user_ids": ids, "count": len(ids)})
                messages.success(request, f"Forzato cambio password per {len(ids)} utenti.")
            else:
                messages.error(request, "Azione bulk non valida.")
    except DatabaseError as exc:
        messages.error(request, f"Errore azione bulk utenti: {exc}")
    except Exception as exc:
        messages.error(request, f"Errore sincronizzazione massiva utenti/anagrafica: {exc}")

    return redirect("admin_portale:utenti_list")


@legacy_admin_required
@csrf_protect
@require_POST
def utente_force_change_password(request, user_id: int):
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    try:
        utente.deve_cambiare_password = True
        utente.save(update_fields=["deve_cambiare_password"])
        messages.success(request, f"Forzato cambio password per utente #{utente.id}.")
    except DatabaseError as exc:
        messages.error(request, f"Errore aggiornamento utente: {exc}")
    _fallback = reverse("admin_portale:utenti_list")
    next_url = _safe_redirect_url(request, request.POST.get("next") or request.META.get("HTTP_REFERER"), _fallback)
    return redirect(next_url)


@legacy_admin_required
@csrf_protect
@require_POST
def utente_impersonate(request, user_id: int):
    target_user = get_object_or_404(UtenteLegacy, id=user_id)
    admin_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    next_url = _safe_redirect_url(request, (request.POST.get("next") or "").strip(), reverse("dashboard_home"))

    if getattr(request, "impersonation_active", False):
        messages.error(request, "Esci prima dall'impersonazione corrente.")
        return redirect(next_url)

    if not bool(target_user.attivo):
        messages.error(request, f"L'utente #{target_user.id} non e' attivo.")
        return redirect(next_url)

    if admin_user and int(target_user.id) == int(admin_user.id):
        messages.info(request, "Sei gia' autenticato come questo utente.")
        return redirect(next_url)

    context = start_impersonation(request, target_user)
    if not context:
        messages.error(request, "Impossibile avviare l'impersonazione per questo utente.")
        return redirect(next_url)

    log_action(
        request,
        "impersonation_start",
        "admin_portale",
        {
            "target_legacy_user_id": int(target_user.id),
            "target_display": (target_user.nome or target_user.email or "").strip(),
        },
    )
    messages.warning(
        request,
        f"Impersonazione attiva per {target_user.nome or target_user.email or f'utente #{target_user.id}'}.",
    )
    return redirect(next_url)


@legacy_admin_required
@csrf_protect
@require_POST
def utente_toggle_active(request, user_id: int):
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    try:
        with transaction.atomic():
            utente.attivo = not bool(utente.attivo)
            utente.save(update_fields=["attivo"])
            _sync_legacy_user_to_anagrafica(utente, force_active=bool(utente.attivo))
        _audit_safe(request, "utente_toggle_active", "admin_portale", {
            "target_legacy_user_id": int(utente.id),
            "attivo": bool(utente.attivo),
        })
        messages.success(
            request,
            f"Utente #{utente.id} {'attivato' if utente.attivo else 'disattivato'}.",
        )
    except DatabaseError as exc:
        messages.error(request, f"Errore aggiornamento utente: {exc}")
    except Exception as exc:
        messages.error(request, f"Errore sincronizzazione utente/anagrafica: {exc}")
    _fallback = reverse("admin_portale:utenti_list")
    next_url = _safe_redirect_url(request, request.POST.get("next") or request.META.get("HTTP_REFERER"), _fallback)
    return redirect(next_url)


@legacy_admin_required
@csrf_protect
@require_POST
def utente_delete(request, user_id: int):
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    current_legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    _fallback = reverse("admin_portale:utenti_list")
    next_url = _safe_redirect_url(request, request.POST.get("next") or request.META.get("HTTP_REFERER"), _fallback)

    if current_legacy_user and int(current_legacy_user.id) == int(utente.id):
        messages.error(request, "Non puoi eliminare l'utente con cui sei autenticato.")
        return redirect(next_url)

    user_label = (utente.nome or utente.email or f"Utente #{utente.id}").strip()

    try:
        cleanup = _delete_legacy_user_with_dependencies(utente)
        log_action(
            request,
            "utente_delete",
            "admin_portale",
            {
                "target_legacy_user_id": int(user_id),
                "target_display": user_label,
                "deleted_django_user_id": cleanup["django_user_id"] or None,
                "released_assets": cleanup["released_assets"],
                "anagrafica_unlinked": cleanup["anagrafica_unlinked"],
            },
        )
        messages.success(request, f"Utente #{user_id} eliminato definitivamente.")
    except Exception as exc:
        logger.exception("utente_delete: errore eliminazione utente_id=%s", user_id)
        messages.error(request, f"Errore eliminazione utente: {exc}")

    return redirect(next_url)


@legacy_admin_required
@csrf_protect
@require_POST
def utente_quick_role(request, user_id: int):
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    role_key = f"quick_ruolo_id_{user_id}"
    ruolo_id = _int_or_none(request.POST.get(role_key))
    ruolo_name = ""
    if ruolo_id:
        try:
            ruolo = Ruolo.objects.filter(id=ruolo_id).first()
            if ruolo:
                ruolo_name = (ruolo.nome or "").strip()
        except DatabaseError:
            ruolo_name = ""
    try:
        utente.ruolo_id = ruolo_id
        utente.ruolo = ruolo_name
        utente.save(update_fields=["ruolo_id", "ruolo"])
        _audit_safe(request, "utente_quick_role", "admin_portale", {
            "target_legacy_user_id": int(utente.id),
            "ruolo_id": ruolo_id,
            "ruolo": ruolo_name,
        })
        messages.success(request, f"Ruolo aggiornato per utente #{utente.id}.")
    except DatabaseError as exc:
        messages.error(request, f"Errore aggiornamento ruolo utente: {exc}")
    _fallback = reverse("admin_portale:utenti_list")
    next_url = _safe_redirect_url(request, request.POST.get("next") or request.META.get("HTTP_REFERER"), _fallback)
    return redirect(next_url)


@legacy_admin_required
@require_GET
def utente_permessi_effettivi(request, user_id: int):
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    rows: list[PermRow] = []
    grouped_rows: list[tuple[str, list[PermRow]]] = []
    if utente.ruolo_id:
        try:
            rows = _permission_rows_for_role(int(utente.ruolo_id))
            grouped_rows = _group_perm_rows_by_modulo(rows)
        except DatabaseError as exc:
            messages.error(request, f"Errore lettura permessi effettivi: {exc}")
    return render(
        request,
        "admin_portale/pages/utente_permessi_effettivi.html",
        {
            "utente_obj": utente,
            "perm_rows": rows,
            "grouped_perm_rows": grouped_rows,
            "flag_names": _perm_flag_names(),
        },
    )


@legacy_admin_required
@csrf_protect
@require_POST
def api_user_perm_override(request, user_id: int):
    """Imposta/rimuove un override permesso per-utente.
    Payload: {modulo, azione, field, value}  (value: true/false/null)
    """
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _json_payload(request)
    modulo = (payload.get("modulo") or "").strip()
    azione = (payload.get("azione") or "").strip()
    field = (payload.get("field") or "").strip()
    value = payload.get("value")  # true / false / null

    allowed_fields = {"can_view", "can_edit", "can_delete", "can_approve"}
    if not modulo or not azione or field not in allowed_fields:
        return JsonResponse({"ok": False, "error": "Parametri non validi."}, status=400)

    # value None = rimuovi override per quel campo
    bool_value = None if value is None else bool(value)

    try:
        ov, _ = UserPermissionOverride.objects.get_or_create(
            legacy_user_id=utente.id,
            modulo=modulo,
            azione=azione,
        )
        setattr(ov, field, bool_value)
        ov.save(update_fields=[field])

        # Se tutti i campi sono None â†’ elimina il record
        ov.refresh_from_db()
        if ov.all_null():
            ov.delete()

        try:
            from core.audit import log_action
            log_action(request, "override_permesso", "admin", {
                "target_user_id": utente.id,
                "modulo": modulo,
                "azione": azione,
                "field": field,
                "value": bool_value,
            })
        except Exception:
            pass

        return JsonResponse({"ok": True})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@legacy_admin_required
@require_POST
def api_user_dashboard_toggle(request, user_id: int):
    """Imposta visibilitÃ  pulsante dashboard per-utente.
    Payload: {pulsante_id, visible}  (visible: bool)
    """
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _json_payload(request)
    pulsante_id = _int_or_none(payload.get("pulsante_id"))
    visible = payload.get("visible")

    if pulsante_id is None or visible is None:
        return JsonResponse({"ok": False, "error": "Parametri non validi."}, status=400)

    bool_visible = bool(visible)
    try:
        if bool_visible:
            # visible=True â†’ rimuovi il record (default Ã¨ visibile)
            UserDashboardConfig.objects.filter(
                legacy_user_id=utente.id, pulsante_id=pulsante_id
            ).delete()
        else:
            UserDashboardConfig.objects.update_or_create(
                legacy_user_id=utente.id,
                pulsante_id=pulsante_id,
                defaults={"visible": False},
            )
        return JsonResponse({"ok": True})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@legacy_admin_required
@require_POST
def api_user_module_toggle(request, user_id: int):
    """Imposta visibilitÃ  di un intero modulo dashboard per-utente.
    Payload: {modulo, visible}  (visible: bool)
    """
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _json_payload(request)
    modulo = (payload.get("modulo") or "").strip()
    visible = payload.get("visible")

    if not modulo or visible is None:
        return JsonResponse({"ok": False, "error": "Parametri non validi."}, status=400)

    bool_visible = bool(visible)
    try:
        if bool_visible:
            # visible=True â†’ rimuovi il record (default Ã¨ visibile)
            UserModuleVisibility.objects.filter(
                legacy_user_id=utente.id, modulo=modulo
            ).delete()
        else:
            UserModuleVisibility.objects.update_or_create(
                legacy_user_id=utente.id,
                modulo=modulo,
                defaults={"visible": False},
            )
        return JsonResponse({"ok": True})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# CHECKLIST â€” Onboarding / Offboarding
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def _checklist_last_per_user(tipo: str, user_ids: list[int]) -> dict[int, "ChecklistEsecuzione"]:
    """Ritorna l'ultima esecuzione del tipo dato, una per user_id. 2 query totali per entrambi i tipi."""
    # Django non supporta GROUP BY + ORDER BY direttamente; usiamo ordinamento + seen set.
    seen: set[int] = set()
    result: dict[int, ChecklistEsecuzione] = {}
    for esec in ChecklistEsecuzione.objects.filter(
        tipo_checklist=tipo, legacy_user_id__in=user_ids
    ).order_by("legacy_user_id", "-data_esecuzione"):
        if esec.legacy_user_id not in seen:
            seen.add(esec.legacy_user_id)
            result[esec.legacy_user_id] = esec
    return result


@legacy_admin_required
@require_GET
def checklist_index(request):
    """Vista globale: configurazione voci + panoramica utenti."""
    voci_checkin  = list(ChecklistVoce.objects.filter(tipo_checklist="checkin").order_by("categoria", "ordine", "id"))
    voci_checkout = list(ChecklistVoce.objects.filter(tipo_checklist="checkout").order_by("categoria", "ordine", "id"))
    # Pre-serialize scelte as JSON so the template can output safe data-* attributes
    for v in voci_checkin + voci_checkout:
        v.scelte_json = json.dumps(v.scelte)
    utenti = list(UtenteLegacy.objects.filter(attivo=True).order_by("nome"))

    # Stato check-in/out: 2 query bulk invece di 2N
    user_ids = [u.id for u in utenti]
    checkin_map  = _checklist_last_per_user("checkin",  user_ids)
    checkout_map = _checklist_last_per_user("checkout", user_ids)

    utenti_con_stato = [
        {"utente": u, "checkin": checkin_map.get(u.id), "checkout": checkout_map.get(u.id)}
        for u in utenti
    ]

    return render(request, "admin_portale/pages/checklist_index.html", {
        "page_title": "Onboarding / Offboarding",
        "voci_checkin":  voci_checkin,
        "voci_checkout": voci_checkout,
        "utenti_con_stato": utenti_con_stato,
    })


@legacy_admin_required
@require_GET
def checklist_utente(request, user_id: int):
    """Vista per-utente: form esecuzione + storico."""
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    voci_checkin  = list(ChecklistVoce.objects.filter(tipo_checklist="checkin",  is_active=True).order_by("categoria", "ordine", "id"))
    voci_checkout = list(ChecklistVoce.objects.filter(tipo_checklist="checkout", is_active=True).order_by("categoria", "ordine", "id"))
    esecuzioni = list(
        ChecklistEsecuzione.objects.filter(legacy_user_id=user_id)
        .prefetch_related("risposte")
        .order_by("-data_esecuzione")[:50]
    )
    return render(request, "admin_portale/pages/checklist_utente.html", {
        "page_title": f"Checklist â€” {utente.nome}",
        "utente_obj": utente,
        "voci_checkin":  voci_checkin,
        "voci_checkout": voci_checkout,
        "esecuzioni": esecuzioni,
    })


@legacy_admin_required
@require_POST
def api_checklist_voce_create(request):
    """Crea una nuova voce checklist. Payload: {tipo_checklist, label, tipo_campo, scelte[], obbligatorio, ordine}"""
    payload = _json_payload(request)
    tipo = (payload.get("tipo_checklist") or "").strip()
    label = (payload.get("label") or "").strip()
    if tipo not in ("checkin", "checkout") or not label:
        return JsonResponse({"ok": False, "error": "tipo_checklist e label obbligatori."}, status=400)
    try:
        voce = ChecklistVoce.objects.create(
            tipo_checklist=tipo,
            categoria=_normalize_category(payload.get("categoria"), default="Generale"),
            label=label[:300],
            tipo_campo=(payload.get("tipo_campo") or "check").strip(),
            scelte=payload.get("scelte") or [],
            obbligatorio=bool(payload.get("obbligatorio", False)),
            ordine=int(payload.get("ordine") or 100),
            is_active=True,
        )
        _audit_safe(
            request,
            "checklist_voce_create",
            "admin_checklist",
            {
                "voce_id": voce.id,
                "tipo_checklist": voce.tipo_checklist,
                "categoria": voce.categoria,
                "label": voce.label,
                "tipo_campo": voce.tipo_campo,
                "scelte": voce.scelte,
                "obbligatorio": voce.obbligatorio,
                "ordine": voce.ordine,
                "is_active": voce.is_active,
            },
        )
        return JsonResponse({"ok": True, "id": voce.id})
    except Exception:
        logger.exception("api_checklist_voce_create: errore creazione voce")
        return JsonResponse({"ok": False, "error": "Errore interno del server."}, status=500)


@legacy_admin_required
@require_POST
def api_checklist_voce_update(request):
    """Aggiorna una voce checklist. Payload: {id, label, tipo_campo, scelte[], obbligatorio, ordine}"""
    payload = _json_payload(request)
    voce_id = _int_or_none(payload.get("id"))
    if not voce_id:
        return JsonResponse({"ok": False, "error": "id mancante."}, status=400)
    voce = get_object_or_404(ChecklistVoce, id=voce_id)
    try:
        before = {
            "tipo_checklist": voce.tipo_checklist,
            "categoria": voce.categoria,
            "label": voce.label,
            "tipo_campo": voce.tipo_campo,
            "scelte": voce.scelte,
            "obbligatorio": voce.obbligatorio,
            "ordine": voce.ordine,
            "is_active": voce.is_active,
        }
        if payload.get("categoria") is not None:
            voce.categoria = _normalize_category(payload.get("categoria"), default=voce.categoria or "Generale")
        voce.label       = (payload.get("label") or voce.label).strip()[:300]
        voce.tipo_campo  = (payload.get("tipo_campo") or voce.tipo_campo).strip()
        voce.scelte      = payload.get("scelte") if payload.get("scelte") is not None else voce.scelte
        voce.obbligatorio = bool(payload.get("obbligatorio", voce.obbligatorio))
        voce.ordine      = int(payload.get("ordine") or voce.ordine)
        voce.save()
        _audit_safe(
            request,
            "checklist_voce_update",
            "admin_checklist",
            {
                "voce_id": voce.id,
                "before": before,
                "after": {
                    "tipo_checklist": voce.tipo_checklist,
                    "categoria": voce.categoria,
                    "label": voce.label,
                    "tipo_campo": voce.tipo_campo,
                    "scelte": voce.scelte,
                    "obbligatorio": voce.obbligatorio,
                    "ordine": voce.ordine,
                    "is_active": voce.is_active,
                },
            },
        )
        return JsonResponse({"ok": True})
    except Exception:
        logger.exception("api_checklist_voce_update: errore aggiornamento voce")
        return JsonResponse({"ok": False, "error": "Errore interno del server."}, status=500)


@legacy_admin_required
@require_POST
def api_checklist_voce_toggle(request):
    """Attiva/disattiva una voce. Payload: {id, is_active}"""
    payload = _json_payload(request)
    voce_id = _int_or_none(payload.get("id"))
    if not voce_id:
        return JsonResponse({"ok": False, "error": "id mancante."}, status=400)
    voce = get_object_or_404(ChecklistVoce, id=voce_id)
    try:
        before = bool(voce.is_active)
        voce.is_active = bool(payload.get("is_active", not voce.is_active))
        voce.save(update_fields=["is_active"])
        _audit_safe(
            request,
            "checklist_voce_toggle",
            "admin_checklist",
            {
                "voce_id": voce.id,
                "before_is_active": before,
                "after_is_active": bool(voce.is_active),
            },
        )
        return JsonResponse({"ok": True, "is_active": voce.is_active})
    except Exception:
        logger.exception("api_checklist_voce_toggle: errore toggle voce")
        return JsonResponse({"ok": False, "error": "Errore interno del server."}, status=500)


@legacy_admin_required
@require_POST
def api_checklist_voce_delete(request):
    """Elimina una voce (solo se non ha risposte registrate). Payload: {id}"""
    payload = _json_payload(request)
    voce_id = _int_or_none(payload.get("id"))
    if not voce_id:
        return JsonResponse({"ok": False, "error": "id mancante."}, status=400)
    voce = get_object_or_404(ChecklistVoce, id=voce_id)
    before = {
        "voce_id": voce.id,
        "tipo_checklist": voce.tipo_checklist,
        "categoria": voce.categoria,
        "label": voce.label,
        "tipo_campo": voce.tipo_campo,
        "scelte": voce.scelte,
        "obbligatorio": voce.obbligatorio,
        "ordine": voce.ordine,
        "is_active": voce.is_active,
    }
    if ChecklistRisposta.objects.filter(voce_id=voce_id).exists():
        return JsonResponse({"ok": False, "error": "Impossibile eliminare: la voce ha risposte registrate. Usa disattiva."}, status=400)
    try:
        voce.delete()
        _audit_safe(request, "checklist_voce_delete", "admin_checklist", before)
        return JsonResponse({"ok": True})
    except Exception:
        logger.exception("api_checklist_voce_delete: errore eliminazione voce")
        return JsonResponse({"ok": False, "error": "Errore interno del server."}, status=500)


@legacy_admin_required
@require_POST
def api_checklist_esegui(request, user_id: int):
    """Salva un'esecuzione checklist per un utente.
    Payload: {tipo: "checkin"|"checkout", note: "", risposte: [{voce_id, valore}]}
    """
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _json_payload(request)
    tipo = (payload.get("tipo") or "").strip()
    if tipo not in ("checkin", "checkout"):
        return JsonResponse({"ok": False, "error": "tipo non valido."}, status=400)

    legacy_user = get_legacy_user(request.user)
    admin_id   = legacy_user.id if legacy_user else None
    admin_nome = (legacy_user.nome if legacy_user else request.user.get_full_name()) or request.user.username

    risposte_raw: list = payload.get("risposte") or []
    # Carica snapshot voci
    voce_ids = [r.get("voce_id") for r in risposte_raw if r.get("voce_id")]
    voci_map = {v.id: v for v in ChecklistVoce.objects.filter(id__in=voce_ids)}

    try:
        with transaction.atomic():
            esec = ChecklistEsecuzione.objects.create(
                legacy_user_id=utente.id,
                utente_nome=utente.nome or "",
                tipo_checklist=tipo,
                eseguita_da_id=admin_id,
                eseguita_da_nome=admin_nome,
                note=(payload.get("note") or "").strip(),
                completata=True,
            )
            bulk = []
            for r in risposte_raw:
                vid = _int_or_none(r.get("voce_id"))
                if not vid:
                    continue
                voce = voci_map.get(vid)
                bulk.append(ChecklistRisposta(
                    esecuzione=esec,
                    voce_id=vid,
                    voce_label=voce.label if voce else f"Voce #{vid}",
                    voce_tipo=voce.tipo_campo if voce else "testo",
                    valore=(r.get("valore") or ""),
                ))
            ChecklistRisposta.objects.bulk_create(bulk)
        _audit_safe(
            request,
            "checklist_esecuzione_create",
            "admin_checklist",
            {
                "esecuzione_id": esec.id,
                "target_user_id": utente.id,
                "target_user_nome": utente.nome or "",
                "tipo_checklist": tipo,
                "note": (payload.get("note") or "").strip(),
                "risposte_count": len(bulk),
                "risposte": [
                    {
                        "voce_id": r.voce_id,
                        "voce_label": r.voce_label,
                        "voce_tipo": r.voce_tipo,
                        "voce_categoria": (voci_map.get(r.voce_id).categoria if voci_map.get(r.voce_id) else ""),
                        "valore": r.valore,
                    }
                    for r in bulk
                ],
            },
        )
        return JsonResponse({"ok": True, "esecuzione_id": esec.id})
    except Exception:
        logger.exception("api_checklist_esegui: errore salvataggio esecuzione")
        return JsonResponse({"ok": False, "error": "Errore interno del server."}, status=500)


@legacy_admin_required
@require_POST
def api_user_extra_info(request, user_id: int):
    """Salva le informazioni anagrafiche extra per un utente.
    Payload: { caporeparto, macchina, telefono, cellulare, note }
    """
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _json_payload(request)

    before_obj = UserExtraInfo.objects.filter(legacy_user_id=utente.id).first()
    before = {
        "reparto": (before_obj.reparto if before_obj else ""),
        "caporeparto": (before_obj.caporeparto if before_obj else ""),
        "macchina": (before_obj.macchina if before_obj else ""),
        "telefono": (before_obj.telefono if before_obj else ""),
        "cellulare": (before_obj.cellulare if before_obj else ""),
        "note": (before_obj.note if before_obj else ""),
    }

    new_reparto    = (payload.get("reparto") or "").strip()[:200]
    new_caporeparto = (payload.get("caporeparto") or "").strip()[:200]

    # Auto-assegna caporeparto da mapping se il reparto cambia e il caporeparto
    # non Ã¨ stato impostato esplicitamente nel payload.
    if new_reparto and not new_caporeparto:
        from core.models import RepartoCapoMapping
        mapping = RepartoCapoMapping.objects.filter(
            reparto__iexact=new_reparto, is_active=True
        ).first()
        if mapping:
            new_caporeparto = mapping.caporeparto

    if new_caporeparto:
        normalized = normalize_caporeparto_option(new_caporeparto, promote_role=True)
        if not normalized.get("ok"):
            return JsonResponse({"ok": False, "error": normalized.get("error") or "Caporeparto non valido."}, status=400)
        new_caporeparto = str(normalized["value"] or "").strip()[:200]

    defaults = {
        "reparto":     new_reparto,
        "caporeparto": new_caporeparto,
        "macchina":    (payload.get("macchina") or "").strip()[:200],
        "telefono":    (payload.get("telefono") or "").strip()[:50],
        "cellulare":   (payload.get("cellulare") or "").strip()[:50],
        "note":        (payload.get("note") or "").strip(),
    }
    try:
        UserExtraInfo.objects.update_or_create(
            legacy_user_id=utente.id,
            defaults=defaults,
        )
        _audit_safe(
            request,
            "utente_extra_info_update",
            "admin_anagrafica",
            {
                "target_user_id": utente.id,
                "before": before,
                "after": defaults,
            },
        )
        return JsonResponse({"ok": True})
    except Exception:
        logger.exception("api_user_extra_info: errore salvataggio info extra")
        return JsonResponse({"ok": False, "error": "Errore interno del server."}, status=500)


# â”€â”€ Anagrafica config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@legacy_admin_required
@require_POST
def api_user_asset_assignments(request, user_id: int):
    """Assegna uno o piu asset a un dipendente (replace completo delle assegnazioni utente)."""
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _json_payload(request)
    raw_ids = payload.get("asset_ids")
    if raw_ids is None:
        raw_ids = []
    if not isinstance(raw_ids, list):
        return JsonResponse({"ok": False, "error": "asset_ids deve essere una lista."}, status=400)

    requested_ids: list[int] = []
    for value in raw_ids:
        iv = _int_or_none(value)
        if iv and iv > 0:
            requested_ids.append(int(iv))
    requested_ids = sorted(set(requested_ids))

    asset_model = _asset_model()
    if asset_model is None:
        return JsonResponse({"ok": False, "error": "Modulo asset non disponibile."}, status=503)

    try:
        valid_ids = set(asset_model.objects.filter(id__in=requested_ids).values_list("id", flat=True))
        display_name = (utente.nome or utente.email or f"Utente #{utente.id}").strip()[:200]

        reparto = ""
        extra = UserExtraInfo.objects.filter(legacy_user_id=utente.id).first()
        if extra:
            reparto = (extra.reparto or "").strip()[:120]
        if not reparto:
            ana = AnagraficaDipendente.objects.filter(utente_id=utente.id).first()
            if ana:
                reparto = (ana.reparto or "").strip()[:120]

        with transaction.atomic():
            released = asset_model.objects.filter(assigned_legacy_user_id=utente.id).exclude(id__in=valid_ids).update(
                assigned_legacy_user_id=None,
                assignment_to="",
                assignment_reparto="",
            )
            assign_defaults = {
                "assigned_legacy_user_id": int(utente.id),
                "assignment_to": display_name,
            }
            if reparto:
                assign_defaults["assignment_reparto"] = reparto
            assigned = asset_model.objects.filter(id__in=valid_ids).update(**assign_defaults)

        _audit_safe(
            request,
            "utente_asset_assignments_update",
            "admin_anagrafica",
            {
                "target_user_id": int(utente.id),
                "target_user_nome": display_name,
                "assigned_count": int(assigned),
                "released_count": int(released),
                "asset_ids": sorted(int(v) for v in valid_ids),
            },
        )
        return JsonResponse(
            {
                "ok": True,
                "assigned_count": int(assigned),
                "released_count": int(released),
                "asset_ids": sorted(int(v) for v in valid_ids),
            }
        )
    except Exception:
        logger.exception("api_user_asset_assignments: errore salvataggio assegnazioni")
        return JsonResponse({"ok": False, "error": "Errore interno del server."}, status=500)


_TIPI_OPZIONE_LABELS = {
    "reparto":     "Reparti",
    "caporeparto": "Capireparto",
    "macchina":    "Macchine",
}


@legacy_admin_required
@require_GET
def anagrafica_config(request):
    """Pagina di configurazione per dropdown e campi extra dell'anagrafica utente."""
    from core.models import RepartoCapoMapping

    tipi = list(_TIPI_OPZIONE_LABELS.keys())
    opzioni_by_tipo: dict[str, list] = {t: [] for t in tipi}
    for o in OptioneConfig.objects.all():
        if o.tipo in opzioni_by_tipo:
            opzioni_by_tipo[o.tipo].append(o)
        else:
            opzioni_by_tipo.setdefault(o.tipo, []).append(o)

    for option in opzioni_by_tipo.get("caporeparto", []):
        legacy_user_id = _int_or_none(getattr(option, "legacy_user_id", None))
        if legacy_user_id is None:
            resolved_user = resolve_caporeparto_legacy_user(option.valore)
            legacy_user_id = int(resolved_user.id) if resolved_user else None
        option.display_label = format_caporeparto_label(
            option.valore,
            legacy_user_id=legacy_user_id,
            include_role=True,
        )
        option.resolved_legacy_user_id = legacy_user_id

    anagrafica_voci = list(AnagraficaVoce.objects.all().order_by("categoria", "ordine", "id"))
    for v in anagrafica_voci:
        v.scelte_json = json.dumps(v.scelte)

    # Mappings reparto â†’ caporeparto
    reparto_capo_mappings = list(
        RepartoCapoMapping.objects.filter(is_active=True).order_by("reparto", "id")
    )
    # Per ogni reparto configurato, marca se ha giÃ  un mapping
    for mapping in reparto_capo_mappings:
        mapping.caporeparto_label = format_caporeparto_label(mapping.caporeparto)
    reparti_con_mapping = {m.reparto for m in reparto_capo_mappings}

    context = {
        "tipi_opzione": tipi,
        "tipi_opzione_labels": _TIPI_OPZIONE_LABELS,
        "opzioni_by_tipo": opzioni_by_tipo,
        "anagrafica_voci": anagrafica_voci,
        "email_domain_default": (getattr(settings, "LDAP_UPN_SUFFIX", "") or "").lstrip("@") or "example.local",
        "reparto_capo_mappings": reparto_capo_mappings,
        "reparti_con_mapping": reparti_con_mapping,
    }
    try:
        return render(request, "admin_portale/pages/anagrafica_config.html", context)
    except OSError:
        logger.exception("Template anagrafica_config non leggibile: uso fallback")
        messages.warning(
            request,
            "Template principale non disponibile sul filesystem. "
            "Mostro una versione semplificata della pagina.",
        )
        return render(request, "admin_portale/pages/anagrafica_config_fallback.html", context)


@legacy_admin_required
@require_POST
def anagrafica_import_csv(request):
    upload = request.FILES.get("dipendenti_csv")
    if not upload:
        messages.error(request, "Seleziona un file CSV prima di avviare l'import.")
        return redirect("admin_portale:anagrafica_config")

    email_domain = (request.POST.get("email_domain") or "").strip().lstrip("@").lower()
    dry_run = bool(request.POST.get("dry_run"))
    sync_legacy_users = bool(request.POST.get("sync_legacy_users"))
    default_password = (request.POST.get("default_password") or "").strip()
    if sync_legacy_users and not default_password:
        messages.error(request, "Per creare utenti offline devi inserire una password iniziale.")
        return redirect("admin_portale:anagrafica_config")
    temp_path = ""
    cmd_out = StringIO()
    cmd_err = StringIO()

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            for chunk in upload.chunks():
                tmp.write(chunk)
            temp_path = tmp.name

        call_command(
            "import_dipendenti_csv",
            temp_path,
            email_domain=email_domain,
            dry_run=dry_run,
            sync_legacy_users=sync_legacy_users,
            default_password=default_password,
            skip_checks=True,
            stdout=cmd_out,
            stderr=cmd_err,
        )
        output = (cmd_out.getvalue() or "").strip()
        if dry_run:
            messages.warning(request, f"Import CSV (dry-run) completato. {output}")
        else:
            messages.success(request, f"Import CSV completato. {output}")
    except Exception as exc:
        detail = (cmd_err.getvalue() or cmd_out.getvalue() or str(exc)).strip()
        if len(detail) > 900:
            detail = detail[:900] + "..."
        messages.error(request, f"Import CSV fallito: {detail}")
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass

    return redirect("admin_portale:anagrafica_config")


@legacy_admin_required
@require_POST
def api_opzione_create(request):
    payload = _json_payload(request)
    tipo = (payload.get("tipo") or "").strip()[:50]
    valore = (payload.get("valore") or "").strip()[:200]
    if not tipo or not valore:
        return JsonResponse({"ok": False, "error": "tipo e valore obbligatori."}, status=400)
    legacy_user_id = None
    if tipo.lower() == "caporeparto":
        normalized = normalize_caporeparto_option(
            valore,
            legacy_user_id=_int_or_none(payload.get("legacy_user_id")),
            promote_role=True,
        )
        if not normalized.get("ok"):
            return JsonResponse({"ok": False, "error": normalized.get("error") or "Caporeparto non valido."}, status=400)
        legacy_user_id = int(normalized["legacy_user_id"])
        valore = str(normalized["value"] or "").strip()[:200]
        duplicate = OptioneConfig.objects.filter(tipo__iexact="caporeparto", legacy_user_id=legacy_user_id).first()
        if duplicate:
            return JsonResponse({"ok": False, "error": "Questo utente Ã¨ giÃ  configurato come caporeparto."}, status=400)
    o = OptioneConfig.objects.create(
        tipo=tipo,
        valore=valore,
        legacy_user_id=legacy_user_id,
        ordine=int(payload.get("ordine") or 100),
    )
    return JsonResponse({"ok": True, "id": o.id})


@legacy_admin_required
@require_POST
def api_opzione_update(request):
    payload = _json_payload(request)
    o = get_object_or_404(OptioneConfig, id=_int_or_none(payload.get("id")))
    valore = (payload.get("valore") or "").strip()[:200]
    if not valore:
        return JsonResponse({"ok": False, "error": "valore obbligatorio."}, status=400)
    if str(o.tipo or "").strip().lower() == "caporeparto":
        normalized = normalize_caporeparto_option(
            valore,
            legacy_user_id=_int_or_none(payload.get("legacy_user_id")) or _int_or_none(getattr(o, "legacy_user_id", None)),
            promote_role=True,
        )
        if not normalized.get("ok"):
            return JsonResponse({"ok": False, "error": normalized.get("error") or "Caporeparto non valido."}, status=400)
        legacy_user_id = int(normalized["legacy_user_id"])
        duplicate = OptioneConfig.objects.filter(tipo__iexact="caporeparto", legacy_user_id=legacy_user_id).exclude(id=o.id).first()
        if duplicate:
            return JsonResponse({"ok": False, "error": "Questo utente Ã¨ giÃ  configurato come caporeparto."}, status=400)
        o.legacy_user_id = legacy_user_id
        o.valore = str(normalized["value"] or "").strip()[:200]
    else:
        o.valore = valore
        if hasattr(o, "legacy_user_id"):
            o.legacy_user_id = None
    if payload.get("ordine") is not None:
        o.ordine = int(payload.get("ordine") or 100)
    o.save()
    return JsonResponse({"ok": True})


@legacy_admin_required
@require_POST
def api_opzione_toggle(request):
    payload = _json_payload(request)
    o = get_object_or_404(OptioneConfig, id=_int_or_none(payload.get("id")))
    o.is_active = bool(payload.get("is_active", True))
    o.save()
    return JsonResponse({"ok": True, "is_active": o.is_active})


@legacy_admin_required
@require_POST
def api_opzione_delete(request):
    payload = _json_payload(request)
    o = get_object_or_404(OptioneConfig, id=_int_or_none(payload.get("id")))
    o.delete()
    return JsonResponse({"ok": True})


@legacy_admin_required
@require_POST
def api_reparto_capo_set(request):
    """Upsert mapping reparto â†’ caporeparto.

    Payload JSON: { reparto: str, caporeparto: str }
    Se caporeparto Ã¨ vuoto, elimina il mapping esistente per quel reparto.
    """
    from core.models import RepartoCapoMapping
    payload = _json_payload(request)
    reparto     = (payload.get("reparto") or "").strip()[:200]
    caporeparto = (payload.get("caporeparto") or "").strip()[:200]
    if not reparto:
        return JsonResponse({"ok": False, "error": "reparto obbligatorio."}, status=400)
    if not caporeparto:
        # Rimuovi eventuale mapping
        deleted, _ = RepartoCapoMapping.objects.filter(reparto__iexact=reparto).delete()
        return JsonResponse({"ok": True, "action": "deleted", "deleted": deleted})
    normalized = normalize_caporeparto_option(caporeparto, promote_role=True)
    if not normalized.get("ok"):
        return JsonResponse({"ok": False, "error": normalized.get("error") or "Caporeparto non valido."}, status=400)
    caporeparto = str(normalized["value"] or "").strip()[:200]
    obj, created = RepartoCapoMapping.objects.update_or_create(
        reparto=reparto,
        defaults={"caporeparto": caporeparto, "is_active": True},
    )
    _audit_safe(request, "reparto_capo_mapping_set", "admin_anagrafica",
                {"reparto": reparto, "caporeparto": caporeparto, "created": created})
    return JsonResponse({"ok": True, "id": obj.id, "action": "created" if created else "updated"})


@legacy_admin_required
@require_POST
def api_reparto_capo_delete(request):
    """Elimina un mapping reparto â†’ caporeparto per ID."""
    from core.models import RepartoCapoMapping
    payload = _json_payload(request)
    pk = _int_or_none(payload.get("id"))
    if not pk:
        return JsonResponse({"ok": False, "error": "id obbligatorio."}, status=400)
    obj = get_object_or_404(RepartoCapoMapping, id=pk)
    obj.delete()
    return JsonResponse({"ok": True})


@legacy_admin_required
@require_POST
def api_reparto_capo_sync(request):
    """Propaga il mapping reparto â†’ caporeparto a tutti gli utenti di quel reparto.

    Payload JSON: { reparto: str }
    Aggiorna UserExtraInfo.caporeparto per tutti gli utenti con quel reparto,
    solo se il mapping esiste e is_active=True.
    """
    from core.models import RepartoCapoMapping, UserExtraInfo
    payload = _json_payload(request)
    reparto = (payload.get("reparto") or "").strip()
    if not reparto:
        return JsonResponse({"ok": False, "error": "reparto obbligatorio."}, status=400)
    mapping = RepartoCapoMapping.objects.filter(reparto__iexact=reparto, is_active=True).first()
    if not mapping:
        return JsonResponse({"ok": False, "error": "Nessun mapping attivo per questo reparto."}, status=404)
    updated = UserExtraInfo.objects.filter(reparto__iexact=reparto).update(caporeparto=mapping.caporeparto)
    _audit_safe(request, "reparto_capo_sync", "admin_anagrafica",
                {"reparto": reparto, "caporeparto": mapping.caporeparto, "users_updated": updated})
    return JsonResponse({"ok": True, "reparto": reparto, "caporeparto": mapping.caporeparto, "users_updated": updated})


@legacy_admin_required
@require_POST
def api_anagrafica_voce_create(request):
    payload = _json_payload(request)
    label = (payload.get("label") or "").strip()[:300]
    if not label:
        return JsonResponse({"ok": False, "error": "label obbligatoria."}, status=400)
    v = AnagraficaVoce.objects.create(
        categoria=_normalize_category(payload.get("categoria"), default="Campi extra"),
        label=label,
        tipo_campo=payload.get("tipo_campo") or "testo",
        scelte=payload.get("scelte") or [],
        obbligatorio=bool(payload.get("obbligatorio", False)),
        ordine=int(payload.get("ordine") or 100),
    )
    _audit_safe(
        request,
        "anagrafica_voce_create",
        "admin_anagrafica",
        {
            "voce_id": v.id,
            "categoria": v.categoria,
            "label": v.label,
            "tipo_campo": v.tipo_campo,
            "scelte": v.scelte,
            "obbligatorio": v.obbligatorio,
            "ordine": v.ordine,
            "is_active": v.is_active,
        },
    )
    return JsonResponse({"ok": True, "id": v.id})


@legacy_admin_required
@require_POST
def api_anagrafica_voce_update(request):
    payload = _json_payload(request)
    v = get_object_or_404(AnagraficaVoce, id=_int_or_none(payload.get("id")))
    before = {
        "categoria": v.categoria,
        "label": v.label,
        "tipo_campo": v.tipo_campo,
        "scelte": v.scelte,
        "obbligatorio": v.obbligatorio,
        "ordine": v.ordine,
        "is_active": v.is_active,
    }
    if payload.get("categoria") is not None:
        v.categoria = _normalize_category(payload.get("categoria"), default=v.categoria or "Campi extra")
    if payload.get("label") is not None:
        v.label = (payload["label"] or "").strip()[:300]
    if payload.get("tipo_campo") is not None:
        v.tipo_campo = payload["tipo_campo"]
    if payload.get("scelte") is not None:
        v.scelte = payload["scelte"] or []
    if payload.get("obbligatorio") is not None:
        v.obbligatorio = bool(payload["obbligatorio"])
    if payload.get("ordine") is not None:
        v.ordine = int(payload["ordine"] or 100)
    v.save()
    _audit_safe(
        request,
        "anagrafica_voce_update",
        "admin_anagrafica",
        {
            "voce_id": v.id,
            "before": before,
                "after": {
                    "categoria": v.categoria,
                    "label": v.label,
                    "tipo_campo": v.tipo_campo,
                    "scelte": v.scelte,
                    "obbligatorio": v.obbligatorio,
                    "ordine": v.ordine,
                "is_active": v.is_active,
            },
        },
    )
    return JsonResponse({"ok": True})


@legacy_admin_required
@require_POST
def api_anagrafica_voce_toggle(request):
    payload = _json_payload(request)
    v = get_object_or_404(AnagraficaVoce, id=_int_or_none(payload.get("id")))
    before = bool(v.is_active)
    v.is_active = bool(payload.get("is_active", True))
    v.save()
    _audit_safe(
        request,
        "anagrafica_voce_toggle",
        "admin_anagrafica",
        {
            "voce_id": v.id,
            "before_is_active": before,
            "after_is_active": bool(v.is_active),
        },
    )
    return JsonResponse({"ok": True, "is_active": v.is_active})


@legacy_admin_required
@require_POST
def api_anagrafica_voce_delete(request):
    payload = _json_payload(request)
    v = get_object_or_404(AnagraficaVoce, id=_int_or_none(payload.get("id")))
    before = {
        "voce_id": v.id,
        "categoria": v.categoria,
        "label": v.label,
        "tipo_campo": v.tipo_campo,
        "scelte": v.scelte,
        "obbligatorio": v.obbligatorio,
        "ordine": v.ordine,
        "is_active": v.is_active,
    }
    if AnagraficaRisposta.objects.filter(voce=v).exists():
        return JsonResponse({"ok": False, "error": "Impossibile eliminare: esistono risposte registrate."}, status=400)
    v.delete()
    _audit_safe(request, "anagrafica_voce_delete", "admin_anagrafica", before)
    return JsonResponse({"ok": True})


@legacy_admin_required
@require_POST
def api_anagrafica_risposte_save(request, user_id: int):
    """Salva le risposte ai campi extra anagrafica per un utente.
    Payload: { "risposte": [{"voce_id": int, "valore": str}, ...] }
    """
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _json_payload(request)
    risposte = payload.get("risposte") or []
    try:
        voce_ids = [_int_or_none(item.get("voce_id")) for item in risposte]
        voce_ids = [vid for vid in voce_ids if vid is not None]
        before_map = {
            r.voce_id: (r.valore or "")
            for r in AnagraficaRisposta.objects.filter(legacy_user_id=utente.id, voce_id__in=voce_ids)
        }
        changes: list[dict] = []
        for item in risposte:
            voce_id = _int_or_none(item.get("voce_id"))
            valore = (item.get("valore") or "").strip()
            if voce_id is None:
                continue
            old_value = before_map.get(voce_id, "")
            AnagraficaRisposta.objects.update_or_create(
                legacy_user_id=utente.id,
                voce_id=voce_id,
                defaults={"valore": valore},
            )
            if old_value != valore:
                changes.append({"voce_id": voce_id, "before": old_value, "after": valore})
        if changes:
            _audit_safe(
                request,
                "anagrafica_risposte_save",
                "admin_anagrafica",
                {
                    "target_user_id": utente.id,
                    "changes": changes,
                    "changed_count": len(changes),
                },
            )
        return JsonResponse({"ok": True})
    except Exception:
        logger.exception("api_anagrafica_risposte_save: errore")
        return JsonResponse({"ok": False, "error": "Errore interno del server."}, status=500)


@legacy_admin_required
@require_GET
def permessi(request):
    roles = _role_choices()
    users = list(UtenteLegacy.objects.order_by("nome", "id"))
    target_type = request.GET.get("target_type", "role")  # "role" | "user"
    selected_role_id = _int_or_none(request.GET.get("ruolo_id"))
    selected_user_id = _int_or_none(request.GET.get("user_id"))

    module_rows: list[ModuloPermRow] = []
    perm_detail: dict[str, list[dict]] = {}
    selected_user = None
    if target_type == "user":
        if selected_user_id is not None:
            selected_user = UtenteLegacy.objects.filter(id=selected_user_id).first()
            try:
                raw_rows = _full_perm_rows_for_user(selected_user_id)
                module_rows = _aggregate_to_module_rows(raw_rows)
                perm_detail = _build_perm_detail(raw_rows)
            except DatabaseError as exc:
                messages.error(request, f"Errore lettura permessi: {exc}")
    else:
        target_type = "role"
        if selected_role_id is None and roles:
            selected_role_id = int(roles[0].id)
        try:
            if selected_role_id is not None:
                raw_rows = _permission_rows_for_role(selected_role_id)
                module_rows = _aggregate_to_module_rows(raw_rows)
                perm_detail = _build_perm_detail(raw_rows)
        except DatabaseError as exc:
            messages.error(request, f"Errore lettura permessi: {exc}")

    return render(
        request,
        "admin_portale/pages/permessi.html",
        {
            "roles": roles,
            "users": users,
            "target_type": target_type,
            "selected_role_id": selected_role_id,
            "selected_user_id": selected_user_id,
            "selected_user": selected_user,
            "module_rows": module_rows,
            "perm_detail": perm_detail,
        },
    )


@legacy_admin_required
@require_GET
def pulsanti(request):
    q_filter = (request.GET.get("q") or "").strip()
    modulo_filter = (request.GET.get("modulo") or "").strip()
    area_filter = (request.GET.get("area") or "").strip()
    try:
        pulsanti_list = list(Pulsante.objects.all())
    except DatabaseError as exc:
        pulsanti_list = []
        messages.error(request, f"Errore lettura pulsanti: {exc}")

    modules = sorted({(p.modulo or "").strip() for p in pulsanti_list if (p.modulo or "").strip()}, key=str.lower)
    ui_meta_map = _pulsanti_ui_meta_map()
    for p in pulsanti_list:
        meta = ui_meta_map.get(int(getattr(p, "id", 0) or 0), {})
        setattr(p, "ui_slot", meta.get("ui_slot", ""))
        setattr(p, "ui_section", meta.get("ui_section", ""))
        setattr(p, "ui_order_meta", meta.get("ui_order"))
        setattr(p, "card_image", meta.get("card_image", ""))
        setattr(p, "card_image_url", _card_image_public_url(meta.get("card_image")))
        setattr(p, "visible_topbar", meta.get("visible_topbar", True))
        setattr(p, "ui_enabled", meta.get("enabled", True))
        setattr(p, "is_padre", meta.get("is_padre", False))
        area_key, area_label = _area_from_ui_meta_or_infer(p, meta)
        setattr(p, "area_key", area_key)
        setattr(p, "area_label", area_label)
    area_options_map = {}
    for p in pulsanti_list:
        area_options_map[getattr(p, "area_key", "altro")] = getattr(p, "area_label", "Altro")
    area_options = [{"key": k, "label": area_options_map[k]} for k in sorted(area_options_map.keys())]

    # Statistiche pre-filtro (per le card stat nella pagina)
    pulsanti_all_unfiltered = pulsanti_list
    pulsanti_total = len(pulsanti_list)
    pulsanti_attivi_count = sum(1 for p in pulsanti_list if getattr(p, "ui_enabled", True))
    moduli_total = len(modules)

    if modulo_filter:
        pulsanti_list = [p for p in pulsanti_list if (p.modulo or "").strip().lower() == modulo_filter.lower()]
    if area_filter:
        pulsanti_list = [p for p in pulsanti_list if getattr(p, "area_key", "") == area_filter]
    if q_filter:
        q_lower = q_filter.lower()
        pulsanti_list = [
            p
            for p in pulsanti_list
            if q_lower in (p.codice or "").lower()
            or q_lower in (p.nome_visibile or "").lower()
            or q_lower in (p.modulo or "").lower()
            or q_lower in (p.url or "").lower()
            or q_lower in (getattr(p, "ui_slot", "") or "").lower()
            or q_lower in (getattr(p, "ui_section", "") or "").lower()
        ]

    order_map = _pulsanti_order_map()
    for p in pulsanti_list:
        setattr(p, "ordine_value", order_map.get(int(p.id)) if hasattr(p, "id") else None)
    if _has_pulsanti_ordine():
        pulsanti_list.sort(
            key=lambda p: (
                getattr(p, "ordine_value", 999999) if getattr(p, "ordine_value", None) is not None else 999999,
                (p.modulo or "").lower(),
                (p.label or "").lower(),
                int(p.id),
            )
        )
    else:
        pulsanti_list.sort(key=lambda p: ((p.modulo or "").lower(), (p.label or "").lower(), int(p.id)))

    # Suggerimenti UI per rendere piu' semplice la compilazione dei campi.
    default_slot_options = [
        "topbar",
        "toolbar",
        "sidebar",
        "page",
        "widget",
        "modal",
        "hidden",
    ]
    default_section_options = [
        "toolbar",
        "dashboard",
        "gestione_assenze",
        "calendario_assenze",
        "richiesta_assenza",
        "richieste",
        "gestione_anomalie",
        "admin",
        "admin_utenti",
        "admin_permessi",
        "admin_pulsanti",
        "admin_acl",
        "admin_ldap",
    ]
    default_icon_options = [
        "home",
        "dashboard",
        "layout-dashboard",
        "calendar",
        "calendar-x",
        "user",
        "users",
        "id-card",
        "shield",
        "shield-check",
        "lock",
        "settings",
        "list",
        "list-todo",
        "alert",
        "triangle-alert",
        "octagon-alert",
        "newspaper",
        "scan",
        "package",
        "ticket",
        "clipboard-list",
        "file-check",
        "file-text",
        "briefcase",
        "clock",
        "recycle",
        "workflow",
        "wrench",
        "siren",
        "key-round",
        "ACL",
        "LDAP",
        "N",
    ]
    ui_slot_options = sorted(
        {
            *default_slot_options,
            *{
                (getattr(p, "ui_slot", "") or "").strip()
                for p in pulsanti_list
                if (getattr(p, "ui_slot", "") or "").strip()
            },
        },
        key=str.lower,
    )
    ui_section_options = sorted(
        {
            *default_section_options,
            *{
                (getattr(p, "ui_section", "") or "").strip()
                for p in pulsanti_list
                if (getattr(p, "ui_section", "") or "").strip()
            },
        },
        key=str.lower,
    )
    icon_options = sorted(
        {
            *default_icon_options,
            *{(p.icona or "").strip() for p in pulsanti_list if (p.icona or "").strip()},
        },
        key=str.lower,
    )
    ui_presets = [
        {
            "key": "topbar_dashboard",
            "label": "Topbar / Dashboard",
            "description": "Voce topbar generale (dashboard/richieste).",
            "values": {
                "ui_slot": "topbar",
                "ui_section": "toolbar",
                "visible_topbar": True,
                "enabled": True,
            },
        },
        {
            "key": "topbar_assenze",
            "label": "Topbar / Assenze",
            "description": "Voce topbar per gestione o richieste assenze.",
            "values": {
                "ui_slot": "topbar",
                "ui_section": "gestione_assenze",
                "visible_topbar": True,
                "enabled": True,
            },
        },
        {
            "key": "topbar_anomalie",
            "label": "Topbar / Anomalie",
            "description": "Voce topbar per gestione anomalie.",
            "values": {
                "ui_slot": "topbar",
                "ui_section": "gestione_anomalie",
                "visible_topbar": True,
                "enabled": True,
            },
        },
        {
            "key": "topbar_admin",
            "label": "Topbar / Admin",
            "description": "Voce topbar amministrativa.",
            "values": {
                "ui_slot": "topbar",
                "ui_section": "admin",
                "visible_topbar": True,
                "enabled": True,
            },
        },
        {
            "key": "page_admin_tool",
            "label": "Strumento pagina Admin",
            "description": "Pulsante interno di pagina (non topbar).",
            "values": {
                "ui_slot": "page",
                "ui_section": "admin",
                "visible_topbar": False,
                "enabled": True,
            },
        },
        {
            "key": "hidden_disabled",
            "label": "Nascosto / Disabilitato",
            "description": "Pulsante non visibile e non attivo (parcheggiato).",
            "values": {
                "ui_slot": "hidden",
                "ui_section": "altro",
                "visible_topbar": False,
                "enabled": False,
            },
        },
    ]

    # Calcola moduli del catalogo con pulsanti mancanti e app senza pulsanti
    all_pulsanti = pulsanti_all_unfiltered
    existing_codici_lower = {(p.codice or "").strip().lower() for p in all_pulsanti}
    existing_moduli_lower = {(p.modulo or "").strip().lower() for p in all_pulsanti}
    proposed_modules = _proposed_from_catalog(existing_codici_lower)
    auto_detected_apps = _app_modules_without_pulsanti(existing_moduli_lower)

    return render(
        request,
        "admin_portale/pages/pulsanti.html",
        {
            "pulsanti_list": pulsanti_list,
            "has_ordine": _has_pulsanti_ordine(),
            "moduli": modules,
            "area_options": area_options,
            "filters": {"q": q_filter, "modulo": modulo_filter, "area": area_filter},
            "route_catalog": _route_catalog(),
            "ui_slot_options": ui_slot_options,
            "ui_section_options": ui_section_options,
            "icon_options": icon_options,
            "ui_presets": ui_presets,
            "proposed_modules": proposed_modules,
            "auto_detected_apps": auto_detected_apps,
            "pulsanti_total": pulsanti_total,
            "pulsanti_attivi_count": pulsanti_attivi_count,
            "moduli_total": moduli_total,
        },
    )


@legacy_admin_required
@require_GET
def topbar_live(request):
    q_filter = (request.GET.get("q") or "").strip()
    section_filter = (request.GET.get("section") or "").strip()
    view_mode = (request.GET.get("view") or "topbar").strip().lower()
    if view_mode not in {"topbar", "all"}:
        view_mode = "topbar"

    try:
        pulsanti_list = list(Pulsante.objects.all())
    except DatabaseError as exc:
        pulsanti_list = []
        messages.error(request, f"Errore lettura pulsanti: {exc}")

    ui_meta_map = _pulsanti_ui_meta_map()
    order_map = _pulsanti_order_map()

    section_options = {
        "toolbar",
        "dashboard",
        "gestione_assenze",
        "calendario_assenze",
        "richiesta_assenza",
        "richieste",
        "gestione_anomalie",
        "admin",
    }
    slot_options = {"topbar", "toolbar", "sidebar", "page", "widget", "hidden"}

    for p in pulsanti_list:
        pid = int(getattr(p, "id", 0) or 0)
        meta = ui_meta_map.get(pid, {})
        ui_slot = (meta.get("ui_slot", "") or "").strip()
        ui_section = (meta.get("ui_section", "") or "").strip()
        visible_topbar = bool(meta.get("visible_topbar", True))
        enabled = bool(meta.get("enabled", True))

        setattr(p, "ui_slot", ui_slot)
        setattr(p, "ui_section", ui_section)
        setattr(p, "ui_order_meta", meta.get("ui_order"))
        setattr(p, "visible_topbar", visible_topbar)
        setattr(p, "ui_enabled", enabled)
        setattr(p, "is_padre", bool(meta.get("is_padre", False)))
        setattr(p, "ordine_value", order_map.get(pid))
        setattr(
            p,
            "display_label",
            (p.nome_visibile or getattr(p, "label", "") or p.codice or f"Pulsante #{pid}"),
        )

        ui_slot_norm = ui_slot.lower()
        is_topbar_slot = ui_slot_norm in {"", "topbar", "toolbar"}
        setattr(p, "is_topbar_candidate", bool(visible_topbar and is_topbar_slot))
        setattr(p, "is_topbar_active", bool(visible_topbar and enabled and is_topbar_slot))

        if ui_section:
            section_options.add(ui_section)
        if ui_slot:
            slot_options.add(ui_slot)

    if view_mode == "topbar":
        pulsanti_list = [p for p in pulsanti_list if getattr(p, "is_topbar_candidate", False)]

    if section_filter:
        section_filter_l = section_filter.lower()
        pulsanti_list = [
            p for p in pulsanti_list if (getattr(p, "ui_section", "") or "").lower() == section_filter_l
        ]

    if q_filter:
        q_lower = q_filter.lower()
        pulsanti_list = [
            p
            for p in pulsanti_list
            if q_lower in (p.codice or "").lower()
            or q_lower in (p.nome_visibile or "").lower()
            or q_lower in (p.modulo or "").lower()
            or q_lower in (p.url or "").lower()
            or q_lower in (getattr(p, "ui_section", "") or "").lower()
            or q_lower in (getattr(p, "ui_slot", "") or "").lower()
        ]

    pulsanti_list.sort(
        key=lambda p: (
            getattr(p, "ui_order_meta", 999999) if getattr(p, "ui_order_meta", None) is not None else 999999,
            getattr(p, "ordine_value", 999999) if getattr(p, "ordine_value", None) is not None else 999999,
            (p.display_label or "").lower(),
            int(p.id),
        )
    )

    return render(
        request,
        "admin_portale/pages/topbar_live.html",
        {
            "pulsanti_list": pulsanti_list,
            "section_options": sorted(section_options, key=str.lower),
            "slot_options": sorted(slot_options, key=str.lower),
            "filters": {"q": q_filter, "section": section_filter, "view": view_mode},
            "route_catalog": _route_catalog(),
        },
    )


def _parse_role_ids(value) -> list[int]:
    if isinstance(value, list):
        raw_tokens = value
    else:
        raw_tokens = str(value or "").replace(";", ",").split(",")
    result: list[int] = []
    seen = set()
    for token in raw_tokens:
        try:
            role_id = int(str(token).strip())
        except Exception:
            continue
        if role_id <= 0 or role_id in seen:
            continue
        seen.add(role_id)
        result.append(role_id)
    return result


def _normalize_nav_url_path(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    if lower.startswith(("http://", "https://", "/")):
        return raw
    return "/" + raw


def _normalize_legacy_path_input(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not raw.startswith("/"):
        raw = "/" + raw
    if raw != "/":
        raw = raw.rstrip("/")
    return raw.lower()


def _apply_navigation_role_access(item: NavigationItem, role_ids: list[int]) -> None:
    NavigationRoleAccess.objects.filter(item=item).delete()
    if not role_ids:
        return
    rows = [
        NavigationRoleAccess(item=item, legacy_role_id=int(role_id), can_view=True)
        for role_id in role_ids
    ]
    NavigationRoleAccess.objects.bulk_create(rows)


def _navigation_item_payload(item: NavigationItem, role_ids_map: dict[int, list[int]]) -> dict:
    role_ids = role_ids_map.get(int(item.id), [])
    return {
        "id": int(item.id),
        "code": item.code,
        "label": item.label,
        "section": item.section,
        "parent_code": item.parent_code or "",
        "route_name": item.route_name,
        "url_path": item.url_path,
        "order": int(item.order),
        "is_visible": bool(item.is_visible),
        "is_enabled": bool(item.is_enabled),
        "open_in_new_tab": bool(item.open_in_new_tab),
        "icon": item.icon or "",
        "group": item.group or "",
        "active_patterns": item.active_patterns or "",
        "description": item.description or "",
        "role_ids": role_ids,
        "role_ids_csv": ",".join(str(v) for v in role_ids),
    }


def _normalize_navigation_icon(value) -> str:
    return str(value or "").strip()[:500]


def _unique_nav_code(base_code: str, used: set[str]) -> str:
    base = slugify(base_code or "")[:72] or "item"
    candidate = base
    idx = 2
    while candidate in used:
        suffix = f"-{idx}"
        candidate = (base[: max(1, 80 - len(suffix))] + suffix)[:80]
        idx += 1
    used.add(candidate)
    return candidate


@legacy_admin_required
@require_GET
def navigation_builder(request):
    q_filter = (request.GET.get("q") or "").strip()
    section_filter = (request.GET.get("section") or "all").strip().lower()
    advanced_mode = _bool_from_any(request.GET.get("advanced"))
    if section_filter not in {"topbar", "subnav", "sidebar", "page", "admin_subnav", "all"}:
        section_filter = "all"

    items_all = list(NavigationItem.objects.all().order_by("section", "order", "label", "id"))
    if q_filter:
        q_lower = q_filter.lower()
        items_all = [
            item
            for item in items_all
            if q_lower in (item.code or "").lower()
            or q_lower in (item.label or "").lower()
            or q_lower in (item.route_name or "").lower()
            or q_lower in (item.url_path or "").lower()
            or q_lower in (item.section or "").lower()
        ]
    if section_filter == "all":
        items = list(items_all)
    else:
        items = [item for item in items_all if str(item.section or "").strip().lower() == section_filter]

    access_rows = NavigationRoleAccess.objects.filter(item_id__in=[int(i.id) for i in items_all]).order_by("legacy_role_id")
    role_ids_map: dict[int, list[int]] = {}
    for row in access_rows:
        role_ids_map.setdefault(int(row.item_id), []).append(int(row.legacy_role_id))

    item_rows_all = [_navigation_item_payload(item, role_ids_map) for item in items_all]
    item_rows = [_navigation_item_payload(item, role_ids_map) for item in items]

    try:
        ruoli = list(Ruolo.objects.all().order_by("nome").values("id", "nome"))
    except DatabaseError:
        ruoli = []

    snapshots = list(NavigationSnapshot.objects.all().order_by("-version", "-id")[:20])
    redirects = list(LegacyRedirect.objects.all().order_by("legacy_path", "id")[:200])

    # Override navigazione utente
    from core.models import UserNavigationOverride
    nav_override_user_id = _int_or_none(request.GET.get("nav_override_user_id"))
    nav_override_user = None
    nav_override_user_label = ""
    nav_override_rows: list[dict] = []
    nav_items_for_override: list[dict] = []
    if nav_override_user_id:
        try:
            nav_override_user = UtenteLegacy.objects.get(id=nav_override_user_id)
        except UtenteLegacy.DoesNotExist:
            nav_override_user_id = None
        if nav_override_user:
            try:
                ana = AnagraficaDipendente.objects.filter(utente_id=nav_override_user_id).first()
                cognome = str(getattr(ana, "cognome", "") or "").strip()
                nome = str(getattr(nav_override_user, "nome", "") or "").strip()
                nav_override_user_label = f"{cognome} {nome}".strip() or nome or nav_override_user.email or str(nav_override_user_id)
            except Exception:
                nav_override_user_label = str(getattr(nav_override_user, "nome", "") or nav_override_user_id)
            user_grants = {
                int(ov.item_id): bool(ov.enabled)
                for ov in UserNavigationOverride.objects.filter(legacy_user_id=nav_override_user_id)
            }
            role_id_for_nav = None
            if getattr(nav_override_user, "ruolo_id", None):
                try:
                    role_id_for_nav = int(nav_override_user.ruolo_id)
                except Exception:
                    pass
            role_access_items: set[int] = set()
            if role_id_for_nav is not None:
                for row in NavigationRoleAccess.objects.filter(legacy_role_id=role_id_for_nav, can_view=True):
                    role_access_items.add(int(row.item_id))
            nav_visible_items = list(NavigationItem.objects.filter(
                is_visible=True, is_enabled=True,
                section__in=["topbar", "subnav", "sidebar", "page"],
            ).order_by("section", "order", "label"))
            for ni in nav_visible_items:
                iid = int(ni.id)
                role_allowed = iid in role_access_items
                override = user_grants.get(iid)  # None / True / False
                if override is True:
                    state = "ov-show"
                elif override is False:
                    state = "ov-hide"
                elif role_allowed:
                    state = "role-show"
                else:
                    state = "role-hide"
                nav_override_rows.append({
                    "item_id": iid,
                    "item_code": ni.code,
                    "item_label": ni.label,
                    "item_section": ni.section,
                    "item_icon": ni.icon or "",
                    "role_allowed": role_allowed,
                    "override": override,
                    "state": state,
                })
            # Raggruppamento per section
            nav_sections_order = ["topbar", "subnav", "sidebar", "page"]
            nav_override_by_section: dict[str, list] = {s: [] for s in nav_sections_order}
            for row in nav_override_rows:
                s = row["item_section"]
                if s in nav_override_by_section:
                    nav_override_by_section[s].append(row)
    visual_lane_defs = [
        ("topbar", "Main Nav (Topbar/Sidebar)", "Navigazione principale: in UI side viene resa nella sidebar."),
        ("subnav", "Subnav", "Secondo livello contestuale per modulo"),
        ("admin_subnav", "Admin Subnav", "Menu interno admin portale"),
        ("sidebar", "Sidebar Dedicated", "Slot dedicato menu laterale (se usato esplicitamente)."),
        ("page", "Page", "Azioni locali dentro una pagina"),
    ]
    visual_rows_by_section: dict[str, list[dict]] = {key: [] for key, _label, _hint in visual_lane_defs}
    for row in item_rows_all:
        section_key = str(row.get("section") or "").strip().lower()
        if section_key not in visual_rows_by_section:
            continue
        visual_rows_by_section[section_key].append(row)
    visual_sections = [
        {
            "key": key,
            "label": label,
            "hint": hint,
            "items": visual_rows_by_section.get(key, []),
        }
        for key, label, hint in visual_lane_defs
    ]

    return render(
        request,
        "admin_portale/pages/navigation_builder.html",
        {
            "item_rows": item_rows,
            "route_catalog": _route_catalog(),
            "ruoli": ruoli,
            "snapshots": snapshots,
            "redirects": redirects,
            "icon_library": _navigation_icon_library_items(),
            "filters": {"q": q_filter, "section": section_filter, "advanced": "1" if advanced_mode else "0"},
            "state_preview_json": json.dumps(export_navigation_state(), ensure_ascii=False, indent=2),
            "visual_sections": visual_sections,
            "advanced_mode": bool(advanced_mode),
            # Override navigazione per-utente
            "nav_override_user_id": nav_override_user_id,
            "nav_override_user": nav_override_user,
            "nav_override_user_label": nav_override_user_label,
            "nav_override_rows": nav_override_rows,
            "nav_override_by_section": nav_override_by_section if nav_override_user_id else {},
        },
    )


@legacy_admin_required
@csrf_protect
@require_POST
def api_navigation_item_create(request):
    payload = _post_or_json_payload(request)
    label = str(payload.get("label") or "").strip()
    if not label:
        return _json_error("Label obbligatoria.")

    code_raw = str(payload.get("code") or "").strip() or label
    code = slugify(code_raw)[:80]
    if not code:
        return _json_error("Codice non valido.")
    if NavigationItem.objects.filter(code=code).exists():
        return _json_error("Codice gia' presente. Scegli un codice diverso.")

    route_name = str(payload.get("route_name") or "").strip()
    url_path = _normalize_nav_url_path(payload.get("url_path") or "")
    if not route_name and not url_path:
        return _json_error("Serve almeno route_name o url_path.")

    section = str(payload.get("section") or "topbar").strip().lower() or "topbar"
    parent_code = str(payload.get("parent_code") or "").strip().lower()
    icon = _normalize_navigation_icon(payload.get("icon"))
    order_value = _int_or_none(payload.get("order"))
    role_ids = _parse_role_ids(payload.get("role_ids") or payload.get("role_ids_csv"))

    try:
        with transaction.atomic():
            item = NavigationItem.objects.create(
                code=code,
                label=label,
                section=section,
                parent_code=parent_code,
                route_name=route_name,
                url_path=url_path,
                order=(order_value if order_value is not None else 100),
                is_visible=_bool_from_any(payload.get("is_visible")) if "is_visible" in payload else True,
                is_enabled=_bool_from_any(payload.get("is_enabled")) if "is_enabled" in payload else True,
                open_in_new_tab=_bool_from_any(payload.get("open_in_new_tab")) if "open_in_new_tab" in payload else False,
                icon=icon,
                description=str(payload.get("description") or "").strip(),
                created_by=request.user,
                updated_by=request.user,
            )
            _apply_navigation_role_access(item, role_ids)
            transaction.on_commit(bump_navigation_registry_version)
    except Exception as exc:
        return _json_error(f"Errore salvataggio: {exc}", status=500)

    return JsonResponse({"ok": True, "id": int(item.id), "code": item.code})


@legacy_admin_required
@csrf_protect
@require_POST
def api_navigation_item_update(request):
    payload = _post_or_json_payload(request)
    item_id = _int_or_none(payload.get("id"))
    if not item_id:
        return _json_error("ID voce mancante.")
    item = get_object_or_404(NavigationItem, id=item_id)

    label = str(payload.get("label") or "").strip()
    if not label:
        return _json_error("Label obbligatoria.")

    code_raw = str(payload.get("code") or "").strip() or item.code
    code = slugify(code_raw)[:80]
    if not code:
        return _json_error("Codice non valido.")
    if NavigationItem.objects.filter(code=code).exclude(id=item.id).exists():
        return _json_error("Codice gia' presente su un'altra voce.")

    route_name = str(payload.get("route_name") or "").strip()
    url_path = _normalize_nav_url_path(payload.get("url_path") or "")
    if not route_name and not url_path:
        return _json_error("Serve almeno route_name o url_path.")

    section = str(payload.get("section") or "topbar").strip().lower() or "topbar"
    parent_code = str(payload.get("parent_code") or "").strip().lower()
    icon = _normalize_navigation_icon(payload.get("icon"))
    order_value = _int_or_none(payload.get("order"))
    role_ids = _parse_role_ids(payload.get("role_ids") or payload.get("role_ids_csv"))

    try:
        with transaction.atomic():
            item.code = code
            item.label = label
            item.section = section
            item.parent_code = parent_code
            item.route_name = route_name
            item.url_path = url_path
            item.order = order_value if order_value is not None else 100
            item.is_visible = _bool_from_any(payload.get("is_visible")) if "is_visible" in payload else item.is_visible
            item.is_enabled = _bool_from_any(payload.get("is_enabled")) if "is_enabled" in payload else item.is_enabled
            item.open_in_new_tab = (
                _bool_from_any(payload.get("open_in_new_tab")) if "open_in_new_tab" in payload else item.open_in_new_tab
            )
            item.icon = icon
            item.description = str(payload.get("description") or "").strip()
            item.updated_by = request.user
            item.save()
            _apply_navigation_role_access(item, role_ids)
            transaction.on_commit(bump_navigation_registry_version)
    except Exception as exc:
        return _json_error(f"Errore aggiornamento: {exc}", status=500)

    return JsonResponse({"ok": True})


@legacy_admin_required
@csrf_protect
@require_POST
def api_navigation_item_delete(request):
    payload = _post_or_json_payload(request)
    item_id = _int_or_none(payload.get("id"))
    if not item_id:
        return _json_error("ID voce mancante.")
    deleted, _ = NavigationItem.objects.filter(id=item_id).delete()
    if not deleted:
        return _json_error("Voce non trovata.", status=404)
    transaction.on_commit(bump_navigation_registry_version)
    return JsonResponse({"ok": True})


@legacy_admin_required
@csrf_protect
@require_POST
def api_navigation_reorder(request):
    """Aggiorna ordine (e opzionalmente sezione) delle voci di navigazione."""
    payload = _post_or_json_payload(request)
    section_orders = payload.get("section_orders")
    if isinstance(section_orders, dict):
        allowed_sections = {"topbar", "subnav", "admin_subnav", "sidebar", "page"}
        cleaned: dict[str, list[int]] = {}
        seen_item_ids: set[int] = set()
        for section_key, raw_ids in section_orders.items():
            section = str(section_key or "").strip().lower()
            if section not in allowed_sections:
                return _json_error(f"Sezione non valida: {section_key}")
            if not isinstance(raw_ids, list):
                return _json_error(f"section_orders[{section}] deve essere una lista di ID interi.")
            try:
                item_ids = [int(value) for value in raw_ids]
            except (TypeError, ValueError):
                return _json_error(f"section_orders[{section}] contiene valori non interi.")
            for item_id in item_ids:
                if item_id in seen_item_ids:
                    return _json_error(f"ID duplicato nel drag&drop visuale: {item_id}")
                seen_item_ids.add(item_id)
            cleaned[section] = item_ids
        with transaction.atomic():
            for section, item_ids in cleaned.items():
                for idx, item_id in enumerate(item_ids):
                    NavigationItem.objects.filter(id=item_id).update(
                        section=section,
                        order=(idx + 1) * 10,
                    )
        transaction.on_commit(bump_navigation_registry_version)
        return JsonResponse({"ok": True, "mode": "section_orders", "updated": len(seen_item_ids)})

    ordered_ids = payload.get("ordered_ids")
    if not isinstance(ordered_ids, list):
        return _json_error("ordered_ids deve essere una lista di ID interi.")
    try:
        ordered_ids = [int(x) for x in ordered_ids]
    except (TypeError, ValueError):
        return _json_error("ordered_ids contiene valori non interi.")
    with transaction.atomic():
        for idx, item_id in enumerate(ordered_ids):
            NavigationItem.objects.filter(id=item_id).update(order=(idx + 1) * 10)
    transaction.on_commit(bump_navigation_registry_version)
    return JsonResponse({"ok": True})


@legacy_admin_required
@csrf_protect
@require_POST
def api_navigation_bootstrap_from_legacy(request):
    payload = _post_or_json_payload(request)
    force = _bool_from_any(payload.get("force")) if "force" in payload else False
    if NavigationItem.objects.exists() and not force:
        return _json_error("NavigationItem gia' popolata. Usa force=1 per sovrascrivere.", status=409)

    ui_meta_map = _pulsanti_ui_meta_map()
    order_map = _pulsanti_order_map()
    pulsanti = list(Pulsante.objects.all().order_by("id"))
    used_codes = {str(v).strip().lower() for v in NavigationItem.objects.values_list("code", flat=True)}

    created = 0
    updated = 0
    with transaction.atomic():
        if force:
            NavigationRoleAccess.objects.all().delete()
            NavigationItem.objects.all().delete()
            used_codes = set()

        for puls in pulsanti:
            pid = int(getattr(puls, "id", 0) or 0)
            meta = ui_meta_map.get(pid, {})
            if meta and not bool(meta.get("enabled", True)):
                continue
            if meta and not bool(meta.get("visible_topbar", True)):
                continue
            ui_slot = str(meta.get("ui_slot") or "").strip().lower() if isinstance(meta, dict) else ""
            if ui_slot and ui_slot not in {"topbar", "toolbar"}:
                continue

            raw_url = str(puls.url or "").strip()
            route_name = ""
            url_path = ""
            lower = raw_url.lower()
            if lower.startswith("route:") or lower.startswith("django:"):
                route_name = raw_url.split(":", 1)[1].strip()
            else:
                url_path = _normalize_nav_url_path(raw_url)

            order_hint = meta.get("ui_order") if isinstance(meta, dict) else None
            if order_hint is None:
                order_hint = order_map.get(pid)
            if order_hint is None:
                order_hint = 1000 + pid

            base_code = str(puls.codice or puls.nome_visibile or f"legacy-{pid}")
            code = _unique_nav_code(base_code, used_codes)
            label = str(puls.nome_visibile or puls.label or puls.codice or f"Voce {pid}")

            item = NavigationItem.objects.filter(code=code).first()
            is_created = item is None
            if is_created:
                item = NavigationItem(
                    code=code,
                    created_by=request.user,
                )
            item.label = label
            item.section = "topbar"
            item.route_name = route_name
            item.url_path = url_path
            item.order = int(order_hint)
            item.is_visible = True
            item.is_enabled = True
            item.icon = _normalize_navigation_icon(getattr(puls, "icona", ""))
            item.description = f"Importata da pulsanti.id={pid}"
            item.updated_by = request.user
            item.save()
            if is_created:
                created += 1
            else:
                updated += 1

        transaction.on_commit(bump_navigation_registry_version)

    return JsonResponse({"ok": True, "created": created, "updated": updated})


@legacy_admin_required
@csrf_protect
@require_POST
def api_navigation_publish(request):
    payload = _post_or_json_payload(request)
    note = str(payload.get("note") or "").strip()
    snap = publish_navigation_snapshot(created_by=request.user, note=note)
    return JsonResponse({"ok": True, "snapshot_id": int(snap.id), "version": int(snap.version)})


@legacy_admin_required
@csrf_protect
@require_POST
def api_navigation_restore(request):
    payload = _post_or_json_payload(request)
    snapshot_id = _int_or_none(payload.get("snapshot_id") or payload.get("id"))
    if not snapshot_id:
        return _json_error("snapshot_id mancante.")
    snapshot = get_object_or_404(NavigationSnapshot, id=snapshot_id)
    try:
        restore_navigation_snapshot(snapshot)
    except Exception as exc:
        return _json_error(f"Errore restore snapshot: {exc}", status=500)
    return JsonResponse({"ok": True, "restored_version": int(snapshot.version)})


@legacy_admin_required
@csrf_protect
@require_POST
def api_navigation_icon_upload(request):
    upload = request.FILES.get("icon") or request.FILES.get("image")
    if upload is None:
        return _json_error("File icona mancante.")

    content_type = str(getattr(upload, "content_type", "") or "").strip().lower()
    ext = Path(str(getattr(upload, "name", "") or "")).suffix.lower()
    if content_type and not content_type.startswith("image/") and not _is_allowed_nav_icon_extension(ext):
        return _json_error("Formato file non valido: serve una immagine.")

    try:
        saved_path, public_url = _save_navigation_icon_upload(upload)
    except ValidationError as exc:
        return _json_error("; ".join(exc.messages) or "Formato file non valido.")
    except Exception as exc:
        return _json_error(f"Errore salvataggio icona: {exc}")

    return JsonResponse(
        {
            "ok": True,
            "icon": {
                "name": Path(saved_path).name,
                "label": Path(saved_path).stem,
                "value": saved_path,
                "url": public_url,
            },
        }
    )


@legacy_admin_required
@csrf_protect
@require_POST
def api_legacy_redirect_upsert(request):
    payload = _post_or_json_payload(request)
    row_id = _int_or_none(payload.get("id"))
    legacy_path = _normalize_legacy_path_input(payload.get("legacy_path"))
    if not legacy_path:
        return _json_error("legacy_path obbligatorio.")

    target_route = str(payload.get("target_route_name") or "").strip()
    target_path = _normalize_nav_url_path(payload.get("target_url_path") or "")
    if not target_route and not target_path:
        return _json_error("Serve target_route_name o target_url_path.")

    defaults = {
        "target_route_name": target_route,
        "target_url_path": target_path,
        "is_enabled": _bool_from_any(payload.get("is_enabled")) if "is_enabled" in payload else True,
        "note": str(payload.get("note") or "").strip(),
    }
    try:
        if row_id:
            row = get_object_or_404(LegacyRedirect, id=row_id)
            for key, value in defaults.items():
                setattr(row, key, value)
            row.legacy_path = legacy_path
            row.save()
        else:
            row, created = LegacyRedirect.objects.update_or_create(
                legacy_path=legacy_path,
                defaults=defaults,
            )
            _ = created
    except Exception as exc:
        return _json_error(f"Errore redirect: {exc}", status=500)

    return JsonResponse({"ok": True, "id": int(row.id)})


@legacy_admin_required
@csrf_protect
@require_POST
def api_legacy_redirect_delete(request):
    payload = _post_or_json_payload(request)
    row_id = _int_or_none(payload.get("id"))
    if not row_id:
        return _json_error("ID redirect mancante.")
    deleted, _ = LegacyRedirect.objects.filter(id=row_id).delete()
    if not deleted:
        return _json_error("Redirect non trovato.", status=404)
    return JsonResponse({"ok": True})


@legacy_admin_required
@csrf_protect
@require_POST
def api_nav_user_override_toggle(request, legacy_user_id: int):
    """Imposta o rimuove un UserNavigationOverride per un utente e una voce di navigazione.

    Body JSON: { "item_id": <int>, "state": "show" | "hide" | "inherit" }
    """
    from core.models import UserNavigationOverride
    payload = _post_or_json_payload(request)
    item_id = _int_or_none(payload.get("item_id"))
    state = str(payload.get("state") or "").strip().lower()
    if not item_id or state not in {"show", "hide", "inherit"}:
        return _json_error("Payload incompleto o stato non valido.")
    item = get_object_or_404(NavigationItem, pk=item_id)
    if state == "inherit":
        UserNavigationOverride.objects.filter(legacy_user_id=legacy_user_id, item=item).delete()
        bump_navigation_registry_version()
        return JsonResponse({"ok": True, "state": "inherit"})
    enabled = state == "show"
    UserNavigationOverride.objects.update_or_create(
        legacy_user_id=legacy_user_id,
        item=item,
        defaults={"enabled": enabled},
    )
    bump_navigation_registry_version()
    return JsonResponse({"ok": True, "state": state})


@legacy_admin_required
@csrf_protect
@require_POST
def api_nav_user_override_clear(request, legacy_user_id: int):
    """Azzera tutti gli override navigazione per un utente."""
    from core.models import UserNavigationOverride
    deleted, _ = UserNavigationOverride.objects.filter(legacy_user_id=legacy_user_id).delete()
    bump_navigation_registry_version()
    return JsonResponse({"ok": True, "deleted": deleted})


def _json_error(message: str, status: int = 400):
    return JsonResponse({"ok": False, "error": message}, status=status)


def _schedule_legacy_acl_cache_invalidation() -> None:
    transaction.on_commit(bump_legacy_cache_version)


def _validate_perm_payload(payload: dict) -> tuple[int, str, str] | None:
    ruolo_id = _int_or_none(payload.get("ruolo_id"))
    modulo = str(payload.get("modulo") or "").strip()
    azione = str(payload.get("azione") or "").strip()
    if ruolo_id is None or not modulo or not azione:
        return None
    return ruolo_id, modulo, azione


@legacy_admin_required
@csrf_protect
@require_POST
def api_permessi_toggle(request):
    payload = _json_payload(request)
    parsed = _validate_perm_payload(payload)
    field = str(payload.get("field") or "").strip()
    if parsed is None:
        return _json_error("Payload incompleto.")
    allowed_fields = set(_perm_flag_names())
    if field not in allowed_fields:
        return _json_error("Campo non consentito.")
    value = _bool_from_any(payload.get("value"))

    try:
        with transaction.atomic():
            perm = _get_or_create_permesso(*parsed)
            _set_perm_field(perm, field, value)
            _schedule_legacy_acl_cache_invalidation()
    except DatabaseError as exc:
        return _json_error(f"Errore DB: {exc}")
    except ValueError as exc:
        return _json_error(str(exc))

    return JsonResponse({"ok": True})


@legacy_admin_required
@csrf_protect
@require_POST
def api_acl_v2_role_grant_toggle(request):
    payload = _json_payload(request)
    role_id = _int_or_none(payload.get("ruolo_id") or payload.get("role_id"))
    permission_code = normalize_permission_code(str(payload.get("permission_code") or ""))
    is_valid_code, validation_error = validate_permission_code(permission_code)
    if role_id is None or not is_valid_code:
        return _json_error(validation_error or "Payload incompleto.")
    value = _bool_from_any(payload.get("value"))

    permission = PermissionDefinition.objects.filter(code=permission_code).first()
    if permission is None:
        return _json_error(f"Permission code non trovato: {permission_code}.", status=404)

    try:
        with transaction.atomic():
            grant, created = RolePermissionGrant.objects.update_or_create(
                legacy_role_id=int(role_id),
                permission_id=permission.code,
                defaults={"enabled": bool(value)},
            )
    except DatabaseError as exc:
        return _json_error(f"Errore DB: {exc}")

    return JsonResponse(
        {
            "ok": True,
            "created": bool(created),
            "role_id": int(grant.legacy_role_id),
            "permission_code": grant.permission_id,
            "enabled": bool(grant.enabled),
            "grant_id": int(grant.id),
        }
    )


@legacy_admin_required
@csrf_protect
@require_POST
def api_acl_v2_role_module_set(request):
    """POST {role_id, module, value}  — abilita/disabilita tutti i permessi di un modulo per un ruolo."""
    payload = _json_payload(request)
    role_id = _int_or_none(payload.get("role_id") or payload.get("ruolo_id"))
    module = str(payload.get("module") or "").strip().lower()
    value = _bool_from_any(payload.get("value"))
    if role_id is None or not module:
        return _json_error("Parametri non validi.")
    permissions = list(PermissionDefinition.objects.filter(is_active=True, module__iexact=module))
    if not permissions:
        return _json_error(f"Nessun permesso trovato per modulo '{module}'.", status=404)
    try:
        with transaction.atomic():
            for perm in permissions:
                RolePermissionGrant.objects.update_or_create(
                    legacy_role_id=int(role_id),
                    permission_id=perm.code,
                    defaults={"enabled": value},
                )
    except DatabaseError as exc:
        return _json_error(f"Errore DB: {exc}", status=500)
    return JsonResponse({"ok": True, "affected": len(permissions), "module": module, "value": value})


@legacy_admin_required
@csrf_protect
@require_POST
def api_acl_v2_user_grant_toggle(request, user_id: int):
    """POST {permission_code, state}  state: 'allow'|'deny'|'inherit'"""
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _json_payload(request)
    permission_code = normalize_permission_code(str(payload.get("permission_code") or ""))
    state = str(payload.get("state") or "inherit").strip().lower()
    is_valid, err = validate_permission_code(permission_code)
    if not is_valid:
        return _json_error(err or "Permission code non valido.")
    if state not in {"allow", "deny", "inherit"}:
        return _json_error("State non valido. Valori: allow, deny, inherit.")
    if not PermissionDefinition.objects.filter(code=permission_code).exists():
        return _json_error(f"Permission code non trovato: {permission_code}.", status=404)
    try:
        with transaction.atomic():
            if state == "inherit":
                UserPermissionGrant.objects.filter(legacy_user_id=user_id, permission_id=permission_code).delete()
            else:
                UserPermissionGrant.objects.update_or_create(
                    legacy_user_id=user_id,
                    permission_id=permission_code,
                    defaults={"enabled": state == "allow"},
                )
    except DatabaseError as exc:
        return _json_error(f"Errore DB: {exc}", status=500)
    return JsonResponse({"ok": True, "state": state, "permission_code": permission_code, "user_id": user_id})


@legacy_admin_required
@csrf_protect
@require_POST
def api_acl_v2_user_module_set(request, user_id: int):
    """POST {module, state}  state: 'allow'|'deny'|'inherit'"""
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _json_payload(request)
    module = str(payload.get("module") or "").strip().lower()
    state = str(payload.get("state") or "inherit").strip().lower()
    if not module:
        return _json_error("Modulo non valido.")
    if state not in {"allow", "deny", "inherit"}:
        return _json_error("State non valido. Valori: allow, deny, inherit.")
    permissions = list(PermissionDefinition.objects.filter(is_active=True, module__iexact=module))
    if not permissions:
        return _json_error(f"Nessun permesso trovato per modulo '{module}'.", status=404)
    try:
        with transaction.atomic():
            for perm in permissions:
                if state == "inherit":
                    UserPermissionGrant.objects.filter(legacy_user_id=user_id, permission_id=perm.code).delete()
                else:
                    UserPermissionGrant.objects.update_or_create(
                        legacy_user_id=user_id,
                        permission_id=perm.code,
                        defaults={"enabled": state == "allow"},
                    )
    except DatabaseError as exc:
        return _json_error(f"Errore DB: {exc}", status=500)
    return JsonResponse({"ok": True, "state": state, "module": module, "user_id": user_id})


@legacy_admin_required
@csrf_protect
@require_POST
def api_permessi_bulk(request):
    payload = _json_payload(request)
    ruolo_id = _int_or_none(payload.get("ruolo_id"))
    if ruolo_id is None:
        return _json_error("Payload bulk non valido.")

    allowed_fields = [name for name in _perm_flag_names() if name != "consentito"]
    mode = str(payload.get("mode") or "").strip().lower()
    updates = payload.get("updates") or []

    try:
        with transaction.atomic():
            if mode == "set_all":
                target_field = str(payload.get("field") or "").strip()
                target_value = _bool_from_any(payload.get("value"))
                if target_field and target_field not in allowed_fields:
                    return _json_error("Campo bulk non consentito.")
                affected = 0
                for modulo, azione in _pulsanti_acl_keys():
                    perm = _get_or_create_permesso(ruolo_id, modulo, azione)
                    changed_fields: list[str] = []
                    fields_to_apply = [target_field] if target_field else allowed_fields
                    for field in fields_to_apply:
                        setattr(perm, field, 1 if target_value else 0)
                        changed_fields.append(field)
                    if "can_view" in changed_fields and hasattr(perm, "consentito"):
                        perm.consentito = perm.can_view
                        changed_fields.append("consentito")
                    elif not target_field and hasattr(perm, "consentito") and "consentito" not in changed_fields:
                        perm.consentito = perm.can_view
                        changed_fields.append("consentito")
                    perm.save(update_fields=changed_fields)
                    affected += 1
                _schedule_legacy_acl_cache_invalidation()
                _audit_safe(request, "permessi_bulk_set_all", "admin_portale", {
                    "ruolo_id": ruolo_id,
                    "field": target_field or "(all)",
                    "value": target_value,
                    "affected": affected,
                })
                return JsonResponse({"ok": True, "affected": affected})

            if mode == "reset_role":
                deleted, _ = Permesso.objects.filter(ruolo_id=ruolo_id).delete()
                _schedule_legacy_acl_cache_invalidation()
                _audit_safe(request, "permessi_bulk_reset_role", "admin_portale", {
                    "ruolo_id": ruolo_id,
                    "deleted": deleted,
                })
                return JsonResponse({"ok": True, "deleted": deleted})

            if mode == "copy_from_role":
                source_role_id = _int_or_none(payload.get("source_role_id"))
                if source_role_id is None:
                    return _json_error("source_role_id mancante.")
                source_perms = list(Permesso.objects.filter(ruolo_id=source_role_id).order_by("modulo", "azione", "-id"))
                latest_map: dict[tuple[str, str], Permesso] = {}
                for perm in source_perms:
                    key = ((perm.modulo or "").strip().lower(), (perm.azione or "").strip().lower())
                    if key not in latest_map:
                        latest_map[key] = perm
                copied = 0
                for src in latest_map.values():
                    modulo = (src.modulo or "").strip()
                    azione = (src.azione or "").strip()
                    if not modulo or not azione:
                        continue
                    dest = _get_or_create_permesso(ruolo_id, modulo, azione)
                    update_fields: list[str] = []
                    for field in allowed_fields:
                        if hasattr(dest, field):
                            setattr(dest, field, 1 if _bool_from_any(getattr(src, field, 0)) else 0)
                            update_fields.append(field)
                    if hasattr(dest, "consentito"):
                        if hasattr(src, "consentito") and getattr(src, "consentito", None) is not None:
                            dest.consentito = 1 if _bool_from_any(getattr(src, "consentito", 0)) else 0
                        else:
                            dest.consentito = 1 if _bool_from_any(getattr(src, "can_view", 0)) else 0
                        update_fields.append("consentito")
                    dest.save(update_fields=list(dict.fromkeys(update_fields)))
                    copied += 1
                _schedule_legacy_acl_cache_invalidation()
                _audit_safe(request, "permessi_bulk_copy_from_role", "admin_portale", {
                    "ruolo_id": ruolo_id,
                    "source_role_id": source_role_id,
                    "copied": copied,
                })
                return JsonResponse({"ok": True, "copied": copied})

            if not isinstance(updates, list):
                return _json_error("Payload bulk non valido.")
            for row in updates:
                if not isinstance(row, dict):
                    continue
                modulo = str(row.get("modulo") or "").strip()
                azione = str(row.get("azione") or "").strip()
                if not modulo or not azione:
                    continue
                perm = _get_or_create_permesso(ruolo_id, modulo, azione)
                changed_fields: list[str] = []
                for field in allowed_fields:
                    if field not in row:
                        continue
                    setattr(perm, field, 1 if _bool_from_any(row.get(field)) else 0)
                    changed_fields.append(field)
                if "can_view" in changed_fields and hasattr(perm, "consentito"):
                    perm.consentito = perm.can_view
                    changed_fields.append("consentito")
                if changed_fields:
                    perm.save(update_fields=changed_fields)
            _schedule_legacy_acl_cache_invalidation()
    except DatabaseError as exc:
        return _json_error(f"Errore DB: {exc}")

    return JsonResponse({"ok": True, "mode": mode or "updates"})


def _pulsante_payload_to_form(request):
    payload = _post_or_json_payload(request)
    if "id" in payload and isinstance(payload["id"], list):
        payload["id"] = payload["id"][0]
    return PulsanteForm(payload)


@legacy_admin_required
@csrf_protect
@require_POST
def api_pulsanti_create(request):
    form = _pulsante_payload_to_form(request)
    if not form.is_valid():
        return _json_error(form.errors.get_json_data())
    data = form.cleaned_data
    try:
        with transaction.atomic():
            raw_payload = _post_or_json_payload(request)
            pulsante = Pulsante.objects.create(
                codice=data["codice"],
                nome_visibile=(data.get("nome_visibile") or "").strip() or None,
                modulo=data["modulo"],
                url=data["url"],
                icona=(data.get("icona") or "").strip() or None,
                descrizione=(data.get("descrizione") or "").strip() or None,
            )
            _set_pulsante_ordine(int(pulsante.id), data.get("ordine"))
            _save_pulsante_ui_meta(int(pulsante.id), raw_payload)
            _ensure_permessi_for_button(data["modulo"], data["codice"])
            _schedule_legacy_acl_cache_invalidation()
    except DatabaseError as exc:
        return _json_error(f"Errore DB: {exc}")
    return JsonResponse({"ok": True, "id": int(pulsante.id)})


@legacy_admin_required
@csrf_protect
@require_POST
def api_pulsanti_update(request):
    form = _pulsante_payload_to_form(request)
    if not form.is_valid():
        return _json_error(form.errors.get_json_data())
    data = form.cleaned_data
    pulsante_id = data.get("id")
    if not pulsante_id:
        return _json_error("ID pulsante mancante.")

    pulsante = get_object_or_404(Pulsante, id=pulsante_id)
    pulsante.codice = data["codice"]
    pulsante.nome_visibile = (data.get("nome_visibile") or "").strip() or None
    pulsante.modulo = data["modulo"]
    pulsante.url = data["url"]
    pulsante.icona = (data.get("icona") or "").strip() or None
    pulsante.descrizione = (data.get("descrizione") or "").strip() or None

    try:
        with transaction.atomic():
            raw_payload = _post_or_json_payload(request)
            pulsante.save()
            _set_pulsante_ordine(int(pulsante.id), data.get("ordine"))
            _save_pulsante_ui_meta(int(pulsante.id), raw_payload)
            _schedule_legacy_acl_cache_invalidation()
    except DatabaseError as exc:
        return _json_error(f"Errore DB: {exc}")

    return JsonResponse({"ok": True})


@legacy_admin_required
@csrf_protect
@require_POST
def api_pulsanti_card_image(request):
    """Imposta immagine card modulo globale (URL o upload file)."""
    if request.FILES:
        pid = _int_or_none(request.POST.get("pulsante_id") or request.POST.get("id"))
        upload = request.FILES.get("image")
        if not pid:
            return _json_error("ID pulsante mancante.")
        if not Pulsante.objects.filter(id=pid).exists():
            return _json_error("Pulsante non trovato.", status=404)
        if upload is None:
            return _json_error("File immagine mancante.")
        if not str(getattr(upload, "content_type", "") or "").lower().startswith("image/"):
            return _json_error("Formato file non valido: serve una immagine.")

        base_name, ext = os.path.splitext(str(getattr(upload, "name", "") or "module"))
        if not ext:
            ext = ".png"
        safe_name = slugify(base_name) or f"module-{pid}"
        target_path = f"dashboard/modules/{safe_name}-{pid}{ext.lower()}"
        old_value = _card_image_raw_value(pid)

        try:
            with transaction.atomic():
                saved_path = default_storage.save(target_path, upload).replace("\\", "/")
                _save_pulsante_ui_meta(pid, {"card_image": saved_path})
                if old_value and _normalize_media_storage_path(old_value) != _normalize_media_storage_path(saved_path):
                    _delete_card_image_file(old_value)
        except Exception as exc:
            return _json_error(f"Errore salvataggio immagine: {exc}")

        return JsonResponse({
            "ok": True,
            "pulsante_id": pid,
            "card_image": saved_path,
            "card_image_url": _card_image_public_url(saved_path),
        })

    payload = _post_or_json_payload(request)
    pid = _int_or_none(payload.get("pulsante_id") or payload.get("id"))
    if not pid:
        return _json_error("ID pulsante mancante.")
    if not Pulsante.objects.filter(id=pid).exists():
        return _json_error("Pulsante non trovato.", status=404)

    remove = _bool_from_any(payload.get("remove"))
    old_value = _card_image_raw_value(pid)
    new_value = None if remove else _clean_card_image_value(payload.get("card_image"))
    try:
        with transaction.atomic():
            _save_pulsante_ui_meta(pid, {"card_image": new_value})
            if remove and old_value:
                _delete_card_image_file(old_value)
    except Exception as exc:
        return _json_error(f"Errore aggiornamento immagine: {exc}")

    return JsonResponse({
        "ok": True,
        "pulsante_id": pid,
        "card_image": new_value or "",
        "card_image_url": _card_image_public_url(new_value),
    })


@legacy_admin_required
@csrf_protect
@require_POST
def api_pulsanti_delete(request):
    payload = _post_or_json_payload(request)
    pulsante_id = _int_or_none(payload.get("id"))
    if not pulsante_id:
        return _json_error("ID pulsante mancante.")

    old_image = _card_image_raw_value(pulsante_id)
    try:
        with transaction.atomic():
            deleted, _ = Pulsante.objects.filter(id=pulsante_id).delete()
            if deleted:
                _ensure_pulsanti_ui_meta_table()
                with connections["default"].cursor() as cursor:
                    cursor.execute("DELETE FROM ui_pulsanti_meta WHERE pulsante_id = %s", [pulsante_id])
                _delete_card_image_file(old_image)
                _schedule_legacy_acl_cache_invalidation()
    except DatabaseError as exc:
        return _json_error(f"Errore DB: {exc}")
    if not deleted:
        return _json_error("Pulsante non trovato.", status=404)
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# CATALOGO MODULI â€” crea tutti i pulsanti di un modulo + auto-permessi
# ---------------------------------------------------------------------------


@legacy_admin_required
@csrf_protect
@require_POST
def api_modulo_crea_da_catalog(request):
    """Crea i pulsanti mancanti per un modulo del catalogo + inizializza permessi per tutti i ruoli.
    Payload: {"modulo_key": "portale_esterno"}
    Risposta: {"ok": true, "modulo": ..., "created_buttons": N, "created_permessi": N}
    """
    payload = _json_payload(request)
    modulo_key = str(payload.get("modulo_key") or "").strip()
    if not modulo_key or modulo_key not in MODULE_CATALOG:
        return _json_error(f"Modulo '{modulo_key}' non trovato nel catalogo.")

    module_def = MODULE_CATALOG[modulo_key]
    try:
        # Controlla per codice globalmente: la UNIQUE KEY DB Ã¨ su 'codice' (non su modulo+codice)
        existing_codici = {
            (p.codice or "").strip().lower()
            for p in Pulsante.objects.all()
        }
    except DatabaseError as exc:
        return _json_error(f"Errore lettura pulsanti: {exc}")

    created_buttons = 0
    created_permessi = 0
    try:
        with transaction.atomic():
            for btn_def in module_def["buttons"]:
                if btn_def["codice"].lower() in existing_codici:
                    continue
                pulsante = Pulsante.objects.create(
                    codice=btn_def["codice"],
                    nome_visibile=btn_def.get("nome_visibile"),
                    modulo=modulo_key,
                    url=btn_def["url"],
                    icona=btn_def.get("icona"),
                )
                _save_pulsante_ui_meta(int(pulsante.id), btn_def)
                created_permessi += _ensure_permessi_for_button(modulo_key, btn_def["codice"])
                created_buttons += 1
            _schedule_legacy_acl_cache_invalidation()
    except DatabaseError as exc:
        return _json_error(f"Errore DB: {exc}")

    return JsonResponse({
        "ok": True,
        "modulo": modulo_key,
        "created_buttons": created_buttons,
        "created_permessi": created_permessi,
    })


# ---------------------------------------------------------------------------
# WIZARD PULSANTE â€” creazione guidata pulsante + UI meta + permessi in un passo
# ---------------------------------------------------------------------------

def _wizard_context() -> dict:
    """Dati di contesto condivisi per la pagina wizard."""
    try:
        ruoli = list(Ruolo.objects.all().order_by("nome").values("id", "nome"))
    except DatabaseError:
        ruoli = []

    try:
        moduli_esistenti = sorted(
            {m for m in Pulsante.objects.values_list("modulo", flat=True) if m},
            key=str.lower,
        )
    except DatabaseError:
        moduli_esistenti = []

    default_slot_options = ["topbar", "toolbar", "sidebar", "page", "widget", "modal", "hidden"]
    default_section_options = [
        "toolbar", "dashboard", "gestione_assenze", "calendario_assenze",
        "richiesta_assenza", "richieste", "gestione_anomalie",
        "admin", "admin_utenti", "admin_permessi", "admin_pulsanti", "admin_automazioni",
    ]
    default_icon_options = [
        "home", "dashboard", "layout-dashboard", "calendar", "calendar-x", "user", "users",
        "id-card", "shield", "shield-check", "lock", "settings", "list", "list-todo",
        "alert", "triangle-alert", "octagon-alert", "newspaper", "scan", "package",
        "ticket", "clipboard-list", "file-check", "file-text", "briefcase", "clock",
        "recycle", "workflow", "wrench", "siren", "key-round",
    ]

    return {
        "ruoli": ruoli,
        "moduli_esistenti": moduli_esistenti,
        "route_catalog": _route_catalog(),
        "ui_slot_options": default_slot_options,
        "ui_section_options": default_section_options,
        "icon_options": default_icon_options,
    }


@legacy_admin_required
@require_GET
def wizard_pulsante(request):
    """Pagina wizard step-by-step per creare un pulsante con permessi."""
    return render(request, "admin_portale/pages/wizard_pulsante.html", _wizard_context())


@legacy_admin_required
@csrf_protect
@require_POST
def api_wizard_pulsante_submit(request):
    """
    POST JSON:
    {
      "pulsante": {codice, nome_visibile, modulo, url, icona},
      "ui_meta": {ui_slot, ui_section, ui_order, visible_topbar, enabled},
      "permessi": [{ruolo_id, can_view, can_edit, can_delete, can_approve}, ...]
    }
    Risposta: {"ok": True, "pulsante_id": N, "created": bool, "permessi_salvati": K}
    """
    payload = _json_payload(request)

    # --- Validazione sezione pulsante ---
    p_data = payload.get("pulsante")
    if not isinstance(p_data, dict):
        return _json_error("Sezione 'pulsante' mancante o non valida.")

    codice = str(p_data.get("codice") or "").strip()
    modulo = str(p_data.get("modulo") or "").strip()
    url_val = str(p_data.get("url") or "").strip()
    nome_visibile = str(p_data.get("nome_visibile") or "").strip() or None
    icona = str(p_data.get("icona") or "").strip() or None

    if not codice:
        return _json_error("Il campo 'codice' Ã¨ obbligatorio.")
    if len(codice) > 100:
        return _json_error("'codice' non puÃ² superare 100 caratteri.")
    if not modulo:
        return _json_error("Il campo 'modulo' (sezione) Ã¨ obbligatorio.")
    if len(modulo) > 100:
        return _json_error("'modulo' non puÃ² superare 100 caratteri.")
    if not url_val:
        return _json_error("Il campo 'url' Ã¨ obbligatorio.")
    # Normalizza: se non Ã¨ route:, django:, http:, https: â†’ prefissa con /
    if not (url_val.startswith(("route:", "django:", "http://", "https://", "/"))):
        url_val = "/" + url_val

    # --- Validazione sezione ui_meta ---
    ui_meta = payload.get("ui_meta")
    if not isinstance(ui_meta, dict):
        ui_meta = {}

    # --- Validazione sezione permessi ---
    permessi_raw = payload.get("permessi")
    if not isinstance(permessi_raw, list):
        permessi_raw = []

    ruoli_validi = set()
    try:
        ruoli_validi = {int(r.id) for r in Ruolo.objects.all()}
    except DatabaseError:
        pass

    permessi_clean = []
    for item in permessi_raw:
        if not isinstance(item, dict):
            continue
        ruolo_id = _int_or_none(item.get("ruolo_id"))
        if ruolo_id is None or ruolo_id not in ruoli_validi:
            continue
        permessi_clean.append({
            "ruolo_id": ruolo_id,
            "can_view": 1 if _bool_from_any(item.get("can_view")) else 0,
            "can_edit": 1 if _bool_from_any(item.get("can_edit")) else 0,
            "can_delete": 1 if _bool_from_any(item.get("can_delete")) else 0,
            "can_approve": 1 if _bool_from_any(item.get("can_approve")) else 0,
        })

    # --- Salvataggio atomico ---
    try:
        with transaction.atomic():
            pulsante, created = Pulsante.objects.update_or_create(
                codice=codice,
                defaults={
                    "nome_visibile": nome_visibile,
                    "modulo": modulo,
                    "url": url_val,
                    "icona": icona,
                },
            )
            pid = int(pulsante.id)
            _save_pulsante_ui_meta(pid, ui_meta)

            permessi_salvati = 0
            for perm_data in permessi_clean:
                perm = _get_or_create_permesso(perm_data["ruolo_id"], modulo, codice)
                perm.can_view = perm_data["can_view"]
                perm.can_edit = perm_data["can_edit"]
                perm.can_delete = perm_data["can_delete"]
                perm.can_approve = perm_data["can_approve"]
                if hasattr(perm, "consentito"):
                    perm.consentito = perm_data["can_view"]
                perm.save()
                permessi_salvati += 1

            # Garantisci records (can_view=0) per i ruoli non specificati nel wizard
            ruoli_nel_wizard = {p["ruolo_id"] for p in permessi_clean}
            for ruolo in Ruolo.objects.all():
                if int(ruolo.id) not in ruoli_nel_wizard:
                    _get_or_create_permesso(int(ruolo.id), modulo, codice)

            _schedule_legacy_acl_cache_invalidation()

    except DatabaseError as exc:
        return _json_error(f"Errore DB: {exc}", status=500)

    return JsonResponse({
        "ok": True,
        "pulsante_id": pid,
        "created": created,
        "permessi_salvati": permessi_salvati,
    })


# ---------------------------------------------------------------------------
# PERMESSI â€” toggle modulo intero per ruolo o per utente
# ---------------------------------------------------------------------------

@legacy_admin_required
@csrf_protect
@require_POST
def api_permessi_modulo_set(request):
    """Imposta can_view per TUTTI i pulsanti di un modulo per un ruolo.
    Payload: {ruolo_id, modulo, can_view}
    """
    payload = _json_payload(request)
    ruolo_id = _int_or_none(payload.get("ruolo_id"))
    modulo = str(payload.get("modulo") or "").strip()
    can_view = _bool_from_any(payload.get("can_view"))
    if ruolo_id is None or not modulo:
        return _json_error("Parametri non validi.")
    acl_keys = [(m, a) for m, a in _pulsanti_acl_keys() if m.lower() == modulo.lower()]
    if not acl_keys:
        return _json_error("Nessun pulsante trovato per il modulo indicato.", status=404)
    try:
        with transaction.atomic():
            affected = 0
            for mod, azione in acl_keys:
                perm = _get_or_create_permesso(ruolo_id, mod, azione)
                perm.can_view = 1 if can_view else 0
                update_fields = ["can_view"]
                if hasattr(perm, "consentito"):
                    perm.consentito = perm.can_view
                    update_fields.append("consentito")
                perm.save(update_fields=update_fields)
                affected += 1
            _schedule_legacy_acl_cache_invalidation()
    except DatabaseError as exc:
        return _json_error(f"Errore DB: {exc}", status=500)
    return JsonResponse({"ok": True, "affected": affected})


@legacy_admin_required
@csrf_protect
@require_POST
def api_user_modulo_perm_set(request, user_id: int):
    """Imposta can_view override per TUTTI i pulsanti di un modulo per un utente.
    Payload: {modulo, can_view}  (can_view null = rimuovi override, torna al ruolo)
    """
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _json_payload(request)
    modulo = str(payload.get("modulo") or "").strip()
    can_view_raw = payload.get("can_view")  # true / false / null
    if not modulo:
        return _json_error("Parametri non validi.")
    can_view = None if can_view_raw is None else _bool_from_any(can_view_raw)
    acl_keys = [(m, a) for m, a in _pulsanti_acl_keys() if m.lower() == modulo.lower()]
    try:
        with transaction.atomic():
            affected = 0
            for mod, azione in acl_keys:
                if can_view is None:
                    UserPermissionOverride.objects.filter(
                        legacy_user_id=utente.id, modulo=mod, azione=azione
                    ).delete()
                else:
                    ov, _ = UserPermissionOverride.objects.get_or_create(
                        legacy_user_id=utente.id, modulo=mod, azione=azione,
                    )
                    ov.can_view = can_view
                    ov.save(update_fields=["can_view"])
                affected += 1
            _schedule_legacy_acl_cache_invalidation()
    except Exception as exc:
        return _json_error(f"Errore DB: {exc}", status=500)
    return JsonResponse({"ok": True, "affected": affected})


# ---------------------------------------------------------------------------
# DASHBOARD â€” toggle visibilitÃ  modulo (enabled in ui_pulsanti_meta)
# ---------------------------------------------------------------------------

def _set_pulsante_meta_enabled(pulsante_id: int, enabled: bool) -> None:
    """Aggiorna solo il flag enabled in ui_pulsanti_meta senza toccare gli altri campi."""
    _ensure_pulsanti_ui_meta_table()
    val = 1 if enabled else 0
    with connections["default"].cursor() as cursor:
        vendor = connections["default"].vendor
        if vendor == "sqlite":
            cursor.execute(
                """
                INSERT INTO ui_pulsanti_meta (pulsante_id, enabled, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT(pulsante_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    updated_at = CURRENT_TIMESTAMP
                """,
                [pulsante_id, val],
            )
        else:
            cursor.execute(
                """
                MERGE ui_pulsanti_meta AS t
                USING (SELECT %s AS pulsante_id) AS s ON t.pulsante_id = s.pulsante_id
                WHEN MATCHED THEN UPDATE SET enabled = %s, updated_at = SYSUTCDATETIME()
                WHEN NOT MATCHED THEN
                    INSERT (pulsante_id, enabled, updated_at) VALUES (%s, %s, SYSUTCDATETIME());
                """,
                [pulsante_id, val, pulsante_id, val],
            )


@legacy_admin_required
@csrf_protect
@require_POST
def api_pulsanti_set_enabled(request):
    """POST {pulsante_id, enabled} â€” imposta solo il flag enabled nel meta UI."""
    payload = _post_or_json_payload(request)
    pid = _int_or_none(payload.get("pulsante_id") or payload.get("id"))
    enabled = _bool_from_any(payload.get("enabled"))
    if not pid:
        return _json_error("pulsante_id mancante.")
    if not Pulsante.objects.filter(id=pid).exists():
        return _json_error("Pulsante non trovato.", status=404)
    try:
        with transaction.atomic():
            _set_pulsante_meta_enabled(pid, enabled)
            _schedule_legacy_acl_cache_invalidation()
    except DatabaseError as exc:
        return _json_error(f"Errore DB: {exc}", status=500)
    return JsonResponse({"ok": True, "pulsante_id": pid, "enabled": enabled})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Audit log
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@legacy_admin_required
def audit_log_view(request):
    from core.models import AuditLog
    from django.core.paginator import Paginator

    qs = AuditLog.objects.all()

    filtro_modulo = (request.GET.get("modulo") or "").strip()
    filtro_azione = (request.GET.get("azione") or "").strip()
    filtro_data = (request.GET.get("data") or "").strip()

    if filtro_modulo:
        qs = qs.filter(modulo=filtro_modulo)
    if filtro_azione:
        qs = qs.filter(azione__icontains=filtro_azione)
    if filtro_data:
        qs = qs.filter(created_at__date=filtro_data)

    moduli_disponibili = AuditLog.objects.values_list("modulo", flat=True).distinct().order_by("modulo")

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "admin_portale/pages/audit_log.html", {
        "page_title": "Audit Log",
        "page_obj": page_obj,
        "filtro_modulo": filtro_modulo,
        "filtro_azione": filtro_azione,
        "filtro_data": filtro_data,
        "moduli_disponibili": moduli_disponibili,
    })


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Health check admin
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@legacy_admin_required
def admin_health_check(request):
    from django.conf import settings as djsettings
    from django.db import connection, connections as all_connections
    from pathlib import Path

    checks = []

    # 1. DB Django (SQLite default)
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        checks.append({"nome": "DB Django (SQLite)", "ok": True, "dettaglio": "Connesso"})
    except Exception as exc:
        checks.append({"nome": "DB Django (SQLite)", "ok": False, "dettaglio": str(exc)})

    # 2. DB Legacy (SQL Server) â€” alias "default" in prod, stessa conn in dev
    try:
        with all_connections["default"].cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM utenti")
            row = cur.fetchone()
        checks.append({"nome": "DB Legacy (tabella utenti)", "ok": True, "dettaglio": f"{row[0]} utenti"})
    except Exception as exc:
        checks.append({"nome": "DB Legacy (tabella utenti)", "ok": False, "dettaglio": str(exc)})

    # 3. Azure MSAL config
    msal_vars = ["AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"]
    missing = [v for v in msal_vars if not getattr(djsettings, v, None)]
    msal_ok = not missing
    checks.append({
        "nome": "Azure MSAL Config",
        "ok": msal_ok,
        "dettaglio": "Configurato" if msal_ok else f"Variabili mancanti: {', '.join(missing)}",
    })

    # 4. File di log
    try:
        log_path = Path(djsettings.BASE_DIR) / "logs" / "app.log"
        if log_path.exists():
            size_kb = round(log_path.stat().st_size / 1024, 1)
            checks.append({"nome": "File di log", "ok": True, "dettaglio": f"{log_path} ({size_kb} KB)"})
        else:
            checks.append({"nome": "File di log", "ok": False, "dettaglio": f"Non trovato: {log_path}"})
    except Exception as exc:
        checks.append({"nome": "File di log", "ok": False, "dettaglio": str(exc)})

    # 5. Sessioni Django attive
    try:
        from django.contrib.sessions.models import Session
        from django.utils import timezone as tz
        n = Session.objects.filter(expire_date__gt=tz.now()).count()
        checks.append({"nome": "Sessioni attive", "ok": True, "dettaglio": f"{n} sessioni"})
    except Exception as exc:
        checks.append({"nome": "Sessioni attive", "ok": False, "dettaglio": str(exc)})

    # 6. Ultima notifica creata
    try:
        from core.models import Notifica
        ultima = Notifica.objects.order_by("-created_at").first()
        if ultima:
            checks.append({"nome": "Notifiche", "ok": True, "dettaglio": f"Ultima: {ultima.created_at:%d/%m/%Y %H:%M}"})
        else:
            checks.append({"nome": "Notifiche", "ok": True, "dettaglio": "Nessuna notifica presente"})
    except Exception as exc:
        checks.append({"nome": "Notifiche", "ok": False, "dettaglio": str(exc)})

    all_ok = all(c["ok"] for c in checks)
    return render(request, "admin_portale/pages/health_check.html", {
        "page_title": "Health Check",
        "checks": checks,
        "all_ok": all_ok,
    })


# ---------------------------------------------------------------------------
# Dashboard Gestione Accessi
# ---------------------------------------------------------------------------

@legacy_admin_required
@require_GET
def accessi_dashboard(request):
    """Dashboard unica: ruoli con conteggi, pulsanti, override utenti recenti."""
    ruoli_info = []
    pulsanti_count = 0
    override_count = 0
    override_recenti = []

    try:
        ruoli = list(Ruolo.objects.all().order_by("nome"))
        pulsanti_count = Pulsante.objects.count()
        for r in ruoli:
            cnt = Permesso.objects.filter(ruolo_id=r.id, can_view=1).count()
            tot = Permesso.objects.filter(ruolo_id=r.id).count()
            ruoli_info.append({"ruolo": r, "perm_attivi": cnt, "perm_totali": tot})
    except DatabaseError as exc:
        messages.error(request, f"Errore lettura tabelle legacy: {exc}")

    try:
        override_count = UserPermissionOverride.objects.count()
        override_recenti = list(
            UserPermissionOverride.objects.order_by("-id")[:15]
        )
        # Arricchisci con nome utente
        uid_set = {o.legacy_user_id for o in override_recenti}
        utenti_map = {}
        try:
            for u in UtenteLegacy.objects.filter(id__in=uid_set):
                utenti_map[int(u.id)] = u.nome or str(u.id)
        except DatabaseError:
            pass
        for o in override_recenti:
            o.nome_utente = utenti_map.get(int(o.legacy_user_id), f"ID {o.legacy_user_id}")
    except Exception as exc:
        messages.warning(request, f"Errore lettura override: {exc}")

    return render(request, "admin_portale/pages/accessi.html", {
        "page_title": "Accessi Avanzati",
        "ruoli_info": ruoli_info,
        "pulsanti_count": pulsanti_count,
        "override_count": override_count,
        "override_recenti": override_recenti,
    })


@legacy_admin_required
@csrf_protect
def accessi_semplice(request):
    """Pannello semplificato unico per ruoli/moduli.

    Permette in una sola schermata di:
    - attivare/disattivare accesso modulo per ruolo
    - sincronizzare nella stessa azione legacy ACL, grant canonici v2 e visibilita menu

    I casi speciali restano delegati agli strumenti avanzati.
    """
    roles = _role_choices()
    selected_role_id = _int_or_none(request.GET.get("ruolo_id") or request.POST.get("ruolo_id"))
    if selected_role_id is None and roles:
        selected_role_id = int(roles[0].id)

    if request.method == "POST":
        if selected_role_id is None:
            messages.error(request, "Seleziona un ruolo prima di salvare.")
            return redirect(reverse("admin_portale:accessi"))

        module_rows = _build_accessi_semplice_rows(selected_role_id)
        allowed_modules = {str(v).strip() for v in request.POST.getlist("simple_modules") if str(v).strip()}

        try:
            with transaction.atomic():
                perm_changed, canonical_changed, navigation_changed = _apply_accessi_semplice_changes(
                    selected_role_id,
                    module_rows,
                    allowed_modules,
                )
                if perm_changed:
                    _schedule_legacy_acl_cache_invalidation()
                if navigation_changed:
                    transaction.on_commit(bump_navigation_registry_version)
            messages.success(
                request,
                (
                    "Salvato. "
                    f"Legacy aggiornato: {perm_changed}. "
                    f"Grant canonici aggiornati: {canonical_changed}. "
                    f"Menu ruolo aggiornati: {navigation_changed}."
                ),
            )
        except DatabaseError as exc:
            messages.error(request, f"Errore durante il salvataggio: {exc}")
        except Exception as exc:
            messages.error(request, f"Errore durante il salvataggio: {exc}")

        return redirect(f"{reverse('admin_portale:accessi')}?ruolo_id={selected_role_id}")

    module_rows = _build_accessi_semplice_rows(selected_role_id)
    selected_role = None
    if selected_role_id is not None:
        selected_role = next((r for r in roles if int(r.id) == int(selected_role_id)), None)

    return render(
        request,
        "admin_portale/pages/accessi_semplice.html",
        {
            "page_title": "Accessi Semplificati",
            "roles": roles,
            "selected_role_id": selected_role_id,
            "selected_role": selected_role,
            "module_rows": module_rows,
        },
    )


# ---------------------------------------------------------------------------
# Gestione Accessi â€” pagina unificata (ruolo + moduli + pulsanti + flag)
# ---------------------------------------------------------------------------

@legacy_admin_required
@csrf_protect
def gestione_accessi(request):
    """Pagina unificata: selezione ruolo â†’ accordion per modulo â†’ tabella pulsanti.

    Sostituisce Accessi, Accessi Avanzati e Matrice Permessi in un'unica vista.
    POST salva in batch tutti i flag can_view/can_edit/can_delete per il ruolo.
    """
    roles = _role_choices()
    selected_role_id = _int_or_none(request.GET.get("ruolo_id") or request.POST.get("ruolo_id"))
    if selected_role_id is None and roles:
        selected_role_id = int(roles[0].id)

    if request.method == "POST":
        if selected_role_id is None:
            messages.error(request, "Seleziona un ruolo prima di salvare.")
            return redirect(reverse("admin_portale:gestione_accessi"))

        # all_keys Ã¨ una lista di "modulo::codice" per ogni pulsante renderizzato
        all_keys = request.POST.getlist("all_keys")
        if not all_keys:
            messages.warning(request, "Nessun dato ricevuto.")
            return redirect(f"{reverse('admin_portale:gestione_accessi')}?ruolo_id={selected_role_id}")

        optional_fields = [f for f in PERM_OPTIONAL_FIELDS if legacy_table_has_column("permessi", f)]
        try:
            with transaction.atomic():
                saved = 0
                for key in all_keys:
                    if "::" not in key:
                        continue
                    modulo, azione = key.split("::", 1)
                    modulo = modulo.strip()
                    azione = azione.strip()
                    if not modulo or not azione:
                        continue

                    can_view = f"cv_{azione}" in request.POST
                    can_edit = f"ce_{azione}" in request.POST if "can_edit" in optional_fields else False
                    can_delete = f"cd_{azione}" in request.POST if "can_delete" in optional_fields else False
                    can_approve = f"ca_{azione}" in request.POST if "can_approve" in optional_fields else False

                    perm = _get_or_create_permesso(selected_role_id, modulo, azione)
                    update_fields: list[str] = []

                    def _chk(field: str, new_val: bool) -> None:
                        nonlocal saved
                        if int(getattr(perm, field, 0) or 0) != int(new_val):
                            setattr(perm, field, 1 if new_val else 0)
                            update_fields.append(field)

                    _chk("can_view", can_view)
                    if legacy_table_has_column("permessi", "consentito"):
                        if int(getattr(perm, "consentito", 0) or 0) != int(can_view):
                            perm.consentito = 1 if can_view else 0
                            update_fields.append("consentito")
                    if "can_edit" in optional_fields:
                        _chk("can_edit", can_edit)
                    if "can_delete" in optional_fields:
                        _chk("can_delete", can_delete)
                    if "can_approve" in optional_fields:
                        _chk("can_approve", can_approve)

                    if update_fields:
                        perm.save(update_fields=list(dict.fromkeys(update_fields)))
                        saved += 1

                if saved:
                    _schedule_legacy_acl_cache_invalidation()

            messages.success(request, f"Salvato. {saved} permessi aggiornati.")
        except DatabaseError as exc:
            messages.error(request, f"Errore durante il salvataggio: {exc}")

        return redirect(f"{reverse('admin_portale:gestione_accessi')}?ruolo_id={selected_role_id}")

    # GET â€” costruisce i dati per il template
    module_data: list[dict] = []
    selected_role = None
    total_active = 0
    total_pulsanti = 0

    if selected_role_id is not None:
        selected_role = next((r for r in roles if int(r.id) == selected_role_id), None)
        try:
            module_data = _build_gestione_accessi_data(selected_role_id)
            for mod in module_data:
                total_active += mod["active_count"]
                total_pulsanti += mod["total_count"]
        except DatabaseError as exc:
            messages.error(request, f"Errore lettura permessi: {exc}")

    optional_fields = [f for f in PERM_OPTIONAL_FIELDS if legacy_table_has_column("permessi", f)]

    return render(
        request,
        "admin_portale/pages/gestione_accessi.html",
        {
            "roles": roles,
            "selected_role_id": selected_role_id,
            "selected_role": selected_role,
            "module_data": module_data,
            "total_active": total_active,
            "total_pulsanti": total_pulsanti,
            "optional_fields": optional_fields,
        },
    )


# ---------------------------------------------------------------------------
# Matrice Permessi â€” vista ruoli Ã— pulsanti per modulo
# ---------------------------------------------------------------------------

@legacy_admin_required
@csrf_protect
def matrice_permessi(request):
    """Matrice permessi: righe = pulsanti del modulo, colonne = tutti i ruoli.
    Permette di abilitare/disabilitare can_view per ogni cella con un solo POST.
    """
    roles = _role_choices()
    try:
        modules = sorted(
            {(p.modulo or "").strip() for p in Pulsante.objects.all() if (p.modulo or "").strip()},
            key=str.lower,
        )
    except DatabaseError as exc:
        messages.error(request, f"Errore lettura moduli: {exc}")
        modules = []

    selected_module = (request.GET.get("modulo") or request.POST.get("modulo") or "").strip()
    if not selected_module and modules:
        selected_module = modules[0]

    if request.method == "POST":
        if not selected_module:
            messages.error(request, "Seleziona un modulo prima di salvare.")
            return redirect(reverse("admin_portale:matrice_permessi"))

        try:
            pulsanti_modulo = list(
                Pulsante.objects.filter(modulo__iexact=selected_module).order_by("codice")
            )
            with transaction.atomic():
                saved = 0
                for pulsante in pulsanti_modulo:
                    azione = (pulsante.codice or "").strip()
                    modulo = (pulsante.modulo or "").strip()
                    if not azione or not modulo:
                        continue
                    for role in roles:
                        field_name = f"perm_{int(role.id)}_{azione}"
                        can_view = field_name in request.POST
                        perm = _get_or_create_permesso(int(role.id), modulo, azione)
                        new_val = 1 if can_view else 0
                        if int(perm.can_view or 0) != new_val or int(perm.consentito or 0) != new_val:
                            perm.can_view = new_val
                            perm.consentito = new_val
                            perm.save(update_fields=["can_view", "consentito"])
                            saved += 1
                if saved:
                    _schedule_legacy_acl_cache_invalidation()
            messages.success(request, f"Matrice salvata. {saved} permessi aggiornati.")
        except DatabaseError as exc:
            messages.error(request, f"Errore durante il salvataggio: {exc}")

        return redirect(f"{reverse('admin_portale:matrice_permessi')}?modulo={selected_module}")

    # Costruisce la matrice per il modulo selezionato.
    # pulsante_rows = [{"pulsante": Pulsante, "cells": [{"role": Ruolo, "can_view": bool}]}]
    pulsante_rows: list[dict] = []

    if selected_module:
        try:
            pulsanti_modulo = list(
                Pulsante.objects.filter(modulo__iexact=selected_module).order_by("codice")
            )
            # Carica tutti i permessi per il modulo in una query sola
            perms = Permesso.objects.filter(modulo__iexact=selected_module)
            perm_index: dict[tuple[str, int], bool] = {}
            for p in perms:
                key = ((p.azione or "").strip().lower(), int(p.ruolo_id or 0))
                can = bool(p.can_view) or bool(p.consentito)
                perm_index[key] = perm_index.get(key, False) or can

            for pulsante in pulsanti_modulo:
                azione = (pulsante.codice or "").strip()
                if not azione:
                    continue
                cells = [
                    {
                        "role": role,
                        "field_name": f"perm_{int(role.id)}_{azione}",
                        "can_view": perm_index.get((azione.lower(), int(role.id)), False),
                    }
                    for role in roles
                ]
                pulsante_rows.append({"pulsante": pulsante, "cells": cells})
        except DatabaseError as exc:
            messages.error(request, f"Errore lettura matrice: {exc}")

    return render(
        request,
        "admin_portale/pages/matrice_permessi.html",
        {
            "modules": modules,
            "selected_module": selected_module,
            "roles": roles,
            "pulsante_rows": pulsante_rows,
        },
    )


# ---------------------------------------------------------------------------
# Gestione Ruoli (CRUD)
# ---------------------------------------------------------------------------

@legacy_admin_required
def ruoli_list(request):
    """Lista ruoli con conteggio utenti. POST crea un nuovo ruolo."""
    if request.method == "POST":
        nome = (request.POST.get("nome") or "").strip()
        if not nome:
            messages.error(request, "Il nome del ruolo è obbligatorio.")
            return redirect(reverse("admin_portale:ruoli_list"))
        try:
            if Ruolo.objects.filter(nome__iexact=nome).exists():
                messages.error(request, f"Esiste già un ruolo con nome «{nome}».")
                return redirect(reverse("admin_portale:ruoli_list"))
            ruolo = Ruolo.objects.create(nome=nome)
            bump_legacy_cache_version()
            log_action(request, "crea_ruolo", "admin_portale", f"Ruolo creato: {nome} (id={ruolo.id})")
            messages.success(request, f"Ruolo «{nome}» creato con successo.")
        except DatabaseError as exc:
            messages.error(request, f"Errore database: {exc}")
        return redirect(reverse("admin_portale:ruoli_list"))

    ruoli = []
    user_counts: dict[int, int] = {}
    try:
        ruoli = list(Ruolo.objects.all().order_by("id"))
    except DatabaseError as exc:
        messages.error(request, f"Errore lettura ruoli: {exc}")
    try:
        from django.db.models import Count as _Count
        for row in UtenteLegacy.objects.values("ruolo_id").annotate(n=_Count("id")):
            if row["ruolo_id"] is not None:
                user_counts[int(row["ruolo_id"])] = row["n"]
    except DatabaseError:
        pass
    for r in ruoli:
        r.user_count = user_counts.get(int(r.id), 0)

    return render(request, "admin_portale/pages/ruoli_list.html", {
        "ruoli": ruoli,
        "page_title": "Gestione Ruoli",
    })


@legacy_admin_required
@require_POST
def ruolo_update(request, ruolo_id: int):
    """Aggiorna il nome di un ruolo e sincronizza la colonna stringa utenti.ruolo."""
    try:
        ruolo = Ruolo.objects.get(pk=ruolo_id)
    except Ruolo.DoesNotExist:
        messages.error(request, "Ruolo non trovato.")
        return redirect(reverse("admin_portale:ruoli_list"))
    nome = (request.POST.get("nome") or "").strip()
    if not nome:
        messages.error(request, "Il nome non può essere vuoto.")
        return redirect(reverse("admin_portale:ruoli_list"))
    try:
        if Ruolo.objects.filter(nome__iexact=nome).exclude(pk=ruolo_id).exists():
            messages.error(request, f"Esiste già un ruolo con nome «{nome}».")
            return redirect(reverse("admin_portale:ruoli_list"))
        old_nome = ruolo.nome
        ruolo.nome = nome
        ruolo.save(update_fields=["nome"])
        UtenteLegacy.objects.filter(ruolo_id=ruolo_id).update(ruolo=nome)
        bump_legacy_cache_version()
        log_action(request, "modifica_ruolo", "admin_portale", f"Ruolo {ruolo_id}: '{old_nome}' → '{nome}'")
        messages.success(request, f"Ruolo aggiornato: «{nome}».")
    except DatabaseError as exc:
        messages.error(request, f"Errore database: {exc}")
    return redirect(reverse("admin_portale:ruoli_list"))


@legacy_admin_required
@require_POST
def ruolo_delete(request, ruolo_id: int):
    """Elimina ruolo solo se non ha utenti assegnati. Rimuove anche i permessi collegati."""
    try:
        ruolo = Ruolo.objects.get(pk=ruolo_id)
    except Ruolo.DoesNotExist:
        messages.error(request, "Ruolo non trovato.")
        return redirect(reverse("admin_portale:ruoli_list"))
    try:
        user_count = UtenteLegacy.objects.filter(ruolo_id=ruolo_id).count()
        if user_count > 0:
            messages.error(
                request,
                f"Impossibile eliminare «{ruolo.nome}»: {user_count} utent{'e' if user_count == 1 else 'i'} "
                f"{'è assegnato' if user_count == 1 else 'sono assegnati'} a questo ruolo.",
            )
            return redirect(reverse("admin_portale:ruoli_list"))
        nome = ruolo.nome
        Permesso.objects.filter(ruolo_id=ruolo_id).delete()
        ruolo.delete()
        bump_legacy_cache_version()
        log_action(request, "elimina_ruolo", "admin_portale", f"Ruolo eliminato: {nome} (id={ruolo_id})")
        messages.success(request, f"Ruolo «{nome}» eliminato.")
    except DatabaseError as exc:
        messages.error(request, f"Errore database: {exc}")
    return redirect(reverse("admin_portale:ruoli_list"))


@legacy_admin_required
@require_POST
def api_ruolo_create(request):
    """API JSON — crea un nuovo ruolo (usato dal wizard inline)."""
    nome = (request.POST.get("nome") or "").strip()
    if not nome:
        return JsonResponse({"ok": False, "error": "Nome obbligatorio."}, status=400)
    try:
        if Ruolo.objects.filter(nome__iexact=nome).exists():
            return JsonResponse({"ok": False, "error": f"Esiste già un ruolo con nome «{nome}»."}, status=400)
        ruolo = Ruolo.objects.create(nome=nome)
        bump_legacy_cache_version()
        log_action(request, "crea_ruolo", "admin_portale", f"Ruolo creato via wizard: {nome} (id={ruolo.id})")
        return JsonResponse({"ok": True, "ruolo": {"id": ruolo.id, "nome": ruolo.nome}})
    except DatabaseError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


# ---------------------------------------------------------------------------
# Wizard Configura Ruolo
# ---------------------------------------------------------------------------

@legacy_admin_required
@require_GET
def wizard_ruolo(request):
    """Wizard step-by-step per configurare i permessi di un ruolo."""
    ruoli = []
    moduli_pulsanti: dict[str, list] = {}
    perm_map_json = "{}"
    ruolo_id_presel = request.GET.get("ruolo_id", "")

    try:
        ruoli = list(Ruolo.objects.all().order_by("nome"))
    except DatabaseError as exc:
        messages.error(request, f"Errore lettura ruoli: {exc}")

    try:
        for p in Pulsante.objects.order_by("modulo", "nome_visibile"):
            mod = (p.modulo or "").strip() or "altro"
            moduli_pulsanti.setdefault(mod, []).append(p)
    except DatabaseError as exc:
        messages.error(request, f"Errore lettura pulsanti: {exc}")

    # Carica permessi attuali per il ruolo pre-selezionato
    if ruolo_id_presel:
        try:
            rid = int(ruolo_id_presel)
            perm_map: dict[str, dict] = {}
            for p in Permesso.objects.filter(ruolo_id=rid):
                key = f"{p.modulo}__{p.azione}"
                perm_map[key] = {
                    "can_view": int(p.can_view or 0),
                    "can_edit": int(p.can_edit or 0),
                    "can_delete": int(p.can_delete or 0),
                    "can_approve": int(p.can_approve or 0),
                }
            perm_map_json = json.dumps(perm_map)
        except (DatabaseError, ValueError) as exc:
            messages.warning(request, f"Errore caricamento permessi ruolo: {exc}")

    return render(request, "admin_portale/pages/wizard_ruolo.html", {
        "page_title": "Wizard Configura Ruolo",
        "ruoli": ruoli,
        "moduli_pulsanti": moduli_pulsanti,
        "perm_map_json": perm_map_json,
        "ruolo_id_presel": ruolo_id_presel,
        "api_bulk_url": reverse("admin_portale:api_permessi_bulk"),
        "api_perm_ruolo_url": reverse("admin_portale:api_wizard_permessi_ruolo"),
        "accessi_url": reverse("admin_portale:gestione_accessi"),
    })


@legacy_admin_required
@require_GET
def api_wizard_permessi_ruolo(request):
    """Ritorna la perm_map JSON per un ruolo (usato dal wizard AJAX)."""
    ruolo_id = request.GET.get("ruolo_id", "")
    if not ruolo_id:
        return JsonResponse({"ok": False, "error": "ruolo_id required"}, status=400)
    try:
        rid = int(ruolo_id)
        perm_map: dict[str, dict] = {}
        for p in Permesso.objects.filter(ruolo_id=rid):
            key = f"{p.modulo}__{p.azione}"
            perm_map[key] = {
                "can_view": int(p.can_view or 0),
                "can_edit": int(p.can_edit or 0),
                "can_delete": int(p.can_delete or 0),
                "can_approve": int(p.can_approve or 0),
            }
        return JsonResponse({"ok": True, "perm_map": perm_map})
    except (DatabaseError, ValueError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


# ---------------------------------------------------------------------------
# GuestPortal SSO relay
# ---------------------------------------------------------------------------

def _read_guestportal_config() -> dict:
    return {
        "url": _effective_env_value("GUESTPORTAL_URL", ""),
        "field_username": _effective_env_value("GUESTPORTAL_FIELD_USERNAME", "username") or "username",
        "field_password": _effective_env_value("GUESTPORTAL_FIELD_PASSWORD", "password") or "password",
        "username_format": _effective_env_value("GUESTPORTAL_USERNAME_FORMAT", "upn") or "upn",
    }


def _build_guestportal_username(request, fmt: str) -> str:
    """
    Costruisce il valore username da passare al GuestPortal in base al formato:
    - 'upn'   â†’ alias@example.local  (usa request.legacy_user.email se disponibile)
    - 'alias' â†’ solo alias             (request.user.username)
    - 'ntlm'  â†’ DOMINIO\\alias
    """
    alias = request.user.username or ""
    legacy_user = getattr(request, "legacy_user", None)

    if fmt == "upn":
        if legacy_user and getattr(legacy_user, "email", None):
            return str(legacy_user.email)
        # Fallback: aggiungi il suffisso UPN dalle impostazioni
        upn_suffix = getattr(settings, "LDAP_UPN_SUFFIX", "@example.local")
        if "@" not in alias:
            return alias + upn_suffix
        return alias
    elif fmt == "ntlm":
        domain = getattr(settings, "LDAP_DOMAIN", "EXAMPLE")
        return f"{domain}\\{alias}"
    else:  # alias
        return alias


@legacy_admin_required
@require_GET
def guestportal_sso(request):
    """Pagina relay per accesso al GuestPortal con credenziali AD. Il browser
    POSTa direttamente all'URL esterno: la password non transita mai dal server Django."""
    cfg = _read_guestportal_config()
    if not cfg["url"]:
        messages.error(
            request,
            "URL GuestPortal non configurato. Imposta GUESTPORTAL_URL nel file .env."
        )
    username = _build_guestportal_username(request, cfg["username_format"])
    return render(request, "admin_portale/pages/guestportal_sso.html", {
        "page_title": "Accesso GuestPortal",
        "gp_url": cfg["url"],
        "gp_field_username": cfg["field_username"],
        "gp_field_password": cfg["field_password"],
        "gp_username": username,
    })


# ---------------------------------------------------------------------------
# Login Config
# ---------------------------------------------------------------------------

_LOGIN_CONFIG_KEYS = [
    ("login_titolo",       "Titolo pagina",          "Portale Applicativo"),
    ("login_sottotitolo",  "Sottotitolo / azienda",  "Example Organization"),
    ("login_sso_visibile", "Bottone SSO visibile",   "1"),
    ("login_sso_label",    "Etichetta bottone SSO",  "Accedi con credenziali Windows"),
]

_LOGO_UPLOAD_DIR = "site"
_ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".webp"}


@legacy_admin_required
@require_GET
def login_config(request):
    valori = {chiave: SiteConfig.get(chiave, default) for chiave, _, default in _LOGIN_CONFIG_KEYS}
    logo_url = SiteConfig.get("login_logo_url", "")
    banners = list(LoginBanner.objects.all())
    return render(request, "admin_portale/pages/login_config.html", {
        "config_keys": _LOGIN_CONFIG_KEYS,
        "valori": valori,
        "logo_url": logo_url,
        "banners": banners,
        "banner_tipi": LoginBanner.TIPO_CHOICES,
    })


@legacy_admin_required
@csrf_protect
@require_POST
def api_login_config_save(request):
    changed = {}
    for chiave, descrizione, _ in _LOGIN_CONFIG_KEYS:
        if chiave in request.POST:
            valore = request.POST[chiave].strip()
            SiteConfig.set(chiave, valore, descrizione)
            changed[chiave] = valore
    _audit_safe(request, "login_config_save", "admin_portale", {"changed_keys": list(changed.keys())})
    messages.success(request, "Configurazione login salvata.")
    return redirect("admin_portale:login_config")


@legacy_admin_required
@csrf_protect
@require_POST
def api_login_logo_upload(request):
    upload = request.FILES.get("logo")
    if not upload:
        messages.error(request, "Nessun file selezionato.")
        return redirect("admin_portale:login_config")
    ext = os.path.splitext(upload.name)[1].lower()
    if ext not in _ALLOWED_LOGO_EXTENSIONS:
        messages.error(request, f"Formato non consentito ({ext}). Usa PNG, JPG, SVG o WEBP.")
        return redirect("admin_portale:login_config")
    filename = f"login_logo{ext}"
    save_path = os.path.join(_LOGO_UPLOAD_DIR, filename)
    # Salva sovrascrivendo un eventuale logo precedente
    saved = default_storage.save(save_path, upload)
    # Normalizza path â†’ URL relativa (sempre forward slash)
    url = settings.MEDIA_URL + saved.replace("\\", "/")
    SiteConfig.set("login_logo_url", url, "URL logo pagina login (caricato da admin)")
    messages.success(request, "Logo aggiornato.")
    return redirect("admin_portale:login_config")


@legacy_admin_required
@csrf_protect
@require_POST
def api_login_logo_remove(request):
    current = SiteConfig.get("login_logo_url", "")
    if current:
        # Rimuovi file fisico se presente
        rel = current.replace(settings.MEDIA_URL, "", 1)
        try:
            if default_storage.exists(rel):
                default_storage.delete(rel)
        except Exception:
            pass
        SiteConfig.set("login_logo_url", "", "URL logo pagina login")
    messages.success(request, "Logo rimosso.")
    return redirect("admin_portale:login_config")


@legacy_admin_required
@csrf_protect
@require_POST
def api_login_banner_create(request):
    testo = (request.POST.get("testo") or "").strip()
    if not testo:
        messages.error(request, "Il testo del banner non puÃ² essere vuoto.")
        return redirect("admin_portale:login_config")
    tipo = request.POST.get("tipo") or "info"
    if tipo not in dict(LoginBanner.TIPO_CHOICES):
        tipo = "info"
    ordine = int(request.POST.get("ordine") or 100)
    banner = LoginBanner.objects.create(testo=testo, tipo=tipo, ordine=ordine, is_active=True)
    _audit_safe(request, "login_banner_create", "admin_portale", {"banner_id": int(banner.id), "tipo": tipo})
    messages.success(request, "Banner aggiunto.")
    return redirect("admin_portale:login_config")


@legacy_admin_required
@csrf_protect
@require_POST
def api_login_banner_toggle(request):
    payload = _json_payload(request)
    b = get_object_or_404(LoginBanner, id=_int_or_none(payload.get("id")))
    b.is_active = not b.is_active
    b.save(update_fields=["is_active"])
    _audit_safe(request, "login_banner_toggle", "admin_portale", {"banner_id": int(b.id), "is_active": b.is_active})
    return JsonResponse({"ok": True, "is_active": b.is_active})


@legacy_admin_required
@csrf_protect
@require_POST
def api_login_banner_delete(request):
    payload = _json_payload(request)
    b = get_object_or_404(LoginBanner, id=_int_or_none(payload.get("id")))
    banner_id = int(b.id)
    b.delete()
    _audit_safe(request, "login_banner_delete", "admin_portale", {"banner_id": banner_id})
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# BRANDING PORTALE — favicon globale
# ---------------------------------------------------------------------------

_FAVICON_UPLOAD_DIR = "site"
_FAVICON_ALLOWED_EXTS = {".ico", ".png", ".svg"}
_FAVICON_ALLOWED_MIMES = {
    "image/x-icon",
    "image/vnd.microsoft.icon",
    "image/png",
    "image/svg+xml",
}


@legacy_admin_required
@require_GET
def branding_config(request):
    favicon_url = SiteConfig.get("brand_favicon", "")
    return render(request, "admin_portale/pages/branding_config.html", {
        "favicon_url": favicon_url,
    })


@legacy_admin_required
@csrf_protect
@require_POST
def api_branding_favicon_upload(request):
    upload = request.FILES.get("favicon")
    if not upload:
        messages.error(request, "Nessun file selezionato.")
        return redirect("admin_portale:branding_config")
    if upload.size > 512 * 1024:
        messages.error(request, "File troppo grande (max 512 KB).")
        return redirect("admin_portale:branding_config")
    try:
        validate_extension_and_mime(
            upload,
            allowed_extensions=_FAVICON_ALLOWED_EXTS,
            allowed_mimes=_FAVICON_ALLOWED_MIMES,
            max_bytes=None,
            label="Favicon",
        )
    except UploadMimeValidationError as exc:
        messages.error(request, str(exc))
        return redirect("admin_portale:branding_config")
    raw_ext = os.path.splitext(upload.name)[1].lower()
    ext = raw_ext if raw_ext in _FAVICON_ALLOWED_EXTS else ".ico"
    save_path = os.path.join(_FAVICON_UPLOAD_DIR, f"branding_favicon{ext}")
    if default_storage.exists(save_path):
        default_storage.delete(save_path)
    saved = default_storage.save(save_path, upload)
    url = settings.MEDIA_URL + saved.replace("\\", "/")
    SiteConfig.set("brand_favicon", url, "URL favicon globale del portale")
    _audit_safe(request, "branding_favicon_upload", "admin_portale", {"path": saved})
    messages.success(request, "Favicon aggiornato.")
    return redirect("admin_portale:branding_config")


@legacy_admin_required
@csrf_protect
@require_POST
def api_branding_favicon_remove(request):
    current = SiteConfig.get("brand_favicon", "")
    if current:
        rel = current.replace(settings.MEDIA_URL, "", 1)
        try:
            if default_storage.exists(rel):
                default_storage.delete(rel)
        except Exception:
            pass
        SiteConfig.set("brand_favicon", "", "URL favicon globale del portale")
    _audit_safe(request, "branding_favicon_remove", "admin_portale", {})
    messages.success(request, "Favicon rimosso. Verrà usato il favicon predefinito.")
    return redirect("admin_portale:branding_config")


# ---------------------------------------------------------------------------
# CREA RELEASE PACKAGE
# ---------------------------------------------------------------------------

@legacy_admin_required
def crea_release(request):
    import subprocess
    from django.http import FileResponse, Http404

    repo_root = Path(settings.BASE_DIR).parent
    script_path = repo_root / "deployment" / "scripts" / "package-release.ps1"

    # Directory pacchetti: shared/packages se esiste, altrimenti releases/ nella repo
    shared_packages = Path("C:/PortaleNovicrom/shared/packages")
    releases_dir = repo_root / "releases"

    def _list_packages():
        pkgs = []
        for pkg_dir in [shared_packages, releases_dir]:
            if pkg_dir.exists():
                for f in sorted(pkg_dir.glob("portale-novicrom-*.zip"), reverse=True)[:10]:
                    pkgs.append({
                        "name": f.name,
                        "path": str(f),
                        "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
                    })
        return pkgs

    result = None
    if request.method == "POST":
        if not script_path.exists():
            result = {"ok": False, "error": f"Script non trovato: {script_path}"}
        else:
            try:
                proc = subprocess.run(
                    ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
                    capture_output=True,
                    text=True,
                    timeout=300,
                    cwd=str(script_path.parent),
                )
                stdout = proc.stdout.strip()
                stderr = proc.stderr.strip()
                ok = proc.returncode == 0
                zip_path = None
                for line in reversed(stdout.splitlines()):
                    line = line.strip()
                    if line.endswith(".zip") and Path(line).exists():
                        zip_path = line
                        break
                result = {
                    "ok": ok,
                    "stdout": stdout,
                    "stderr": stderr,
                    "zip_path": zip_path,
                    "zip_name": Path(zip_path).name if zip_path else None,
                    "zip_size_mb": round(Path(zip_path).stat().st_size / (1024 * 1024), 1) if zip_path else None,
                }
                if ok and zip_path:
                    _audit_safe(request, "crea_release", "admin_portale", {"zip": zip_path})
            except subprocess.TimeoutExpired:
                result = {"ok": False, "error": "Timeout: lo script ha impiegato troppo tempo (>5 min)"}
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}

    return render(request, "admin_portale/pages/crea_release.html", {
        "packages": _list_packages(),
        "result": result,
        "script_path": str(script_path),
        "script_exists": script_path.exists(),
        "app_version": getattr(settings, "APP_VERSION", ""),
    })


@legacy_admin_required
@require_GET
def download_release_package(request):
    from django.http import FileResponse, Http404

    pkg_path = request.GET.get("path", "").strip()
    if not pkg_path:
        raise Http404
    f = Path(pkg_path)
    # Sicurezza: accetta solo zip con il prefisso atteso
    if not f.exists() or not f.suffix == ".zip" or not f.name.startswith("portale-novicrom-"):
        raise Http404
    return FileResponse(open(f, "rb"), as_attachment=True, filename=f.name)

