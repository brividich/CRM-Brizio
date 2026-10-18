"""Viste del Pannello di amministrazione — Funzioni e costanti condivise dai pilastri del modulo (un solo punto di lookup per i test).

Spacchettamento di ``admin_portale/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from django.apps import apps as django_apps
from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives, get_connection  # noqa: F401 — EmailMultiAlternatives e' bersaglio di mock.patch nei test
from django.core.files.storage import default_storage
from django.db import DatabaseError, connections, transaction
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from config.env_config import load_env_file_values, primary_runtime_env_path, update_env_file_values
from core.acl_v2 import (
    normalize_permission_code,
    validate_permission_code,
)
from core.legacy_cache import (
    bump_legacy_cache_version,
)
from core.legacy_models import Permesso, Pulsante, Ruolo, UtenteLegacy
from core.navigation_registry import (
    bump_navigation_registry_version,
    resolve_navigation_item_permission_code,
)
from core.legacy_utils import legacy_table_has_column
from core.models import (
    NavigationItem,
    PermissionDefinition,
    RolePermissionGrant,
    RoutePermissionBinding,
    UserPermissionOverride,
)

from ..decorators import legacy_admin_required
from ..forms import PulsanteForm


logger = logging.getLogger(__name__)

PERM_OPTIONAL_FIELDS = ("can_edit", "can_delete", "can_approve")

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
            # Ampiezza di visibilita' sulle assenze altrui. Non sono bottoni: non
            # aprono nulla, decidono QUANTE righe si vedono nel calendario, nella
            # dashboard segnalazioni e negli export. Senza nessuno dei due si
            # vedono soltanto le proprie richieste.
            {
                "codice": "view_all_assenze",
                "nome_visibile": "Vede le assenze di tutti",
                "url": "",
                "icona": "users",
                "ui_slot": "none",
                "ui_section": "gestione_assenze",
                "visible_topbar": False,
                "enabled": True,
            },
            {
                "codice": "view_reparto_assenze",
                "nome_visibile": "Vede le assenze del proprio reparto",
                "url": "",
                "icona": "user-check",
                "ui_slot": "none",
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
        "label": "Anagrafica HR",
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
        ],
    },
    "fornitori": {
        "label": "Anagrafica Fornitori",
        "icon": "briefcase",
        "buttons": [
            {
                "codice": "fornitori_index",
                "nome_visibile": "Fornitori",
                "url": "route:fornitori:index",
                "icona": "briefcase",
                "ui_slot": "topbar",
                "ui_section": "fornitori",
                "ui_order": 360,
                "visible_topbar": True,
                "enabled": True,
            },
            {
                "codice": "fornitori_list",
                "nome_visibile": "Fornitori - Lista",
                "url": "route:fornitori:fornitori_list",
                "icona": "briefcase",
                "ui_slot": "hidden",
                "ui_section": "fornitori",
                "visible_topbar": False,
                "enabled": True,
            },
            {
                "codice": "fornitori_create",
                "nome_visibile": "Fornitori - Nuovo fornitore",
                "url": "route:fornitori:fornitore_create",
                "icona": "plus",
                "ui_slot": "hidden",
                "ui_section": "fornitori",
                "visible_topbar": False,
                "enabled": True,
            },
            {
                "codice": "fornitore_detail",
                "nome_visibile": "Fornitori - Scheda fornitore",
                "url": "route:fornitori:fornitore_detail",
                "icona": "file-text",
                "ui_slot": "hidden",
                "ui_section": "fornitori",
                "visible_topbar": False,
                "enabled": True,
            },
            {
                "codice": "fornitore_edit",
                "nome_visibile": "Fornitori - Modifica fornitore",
                "url": "route:fornitori:fornitore_edit",
                "icona": "edit",
                "ui_slot": "hidden",
                "ui_section": "fornitori",
                "visible_topbar": False,
                "enabled": True,
            },
            {
                "codice": "fornitore_toggle_active",
                "nome_visibile": "Fornitori - Attiva/disattiva",
                "url": "route:fornitori:fornitore_toggle_active",
                "icona": "toggle-left",
                "ui_slot": "hidden",
                "ui_section": "fornitori",
                "visible_topbar": False,
                "enabled": True,
            },
            {
                "codice": "fornitore_documento_add",
                "nome_visibile": "Fornitori - Aggiungi documento",
                "url": "route:fornitori:fornitore_documento_add",
                "icona": "upload",
                "ui_slot": "hidden",
                "ui_section": "fornitori",
                "visible_topbar": False,
                "enabled": True,
            },
            {
                "codice": "fornitore_documento_delete",
                "nome_visibile": "Fornitori - Elimina documento",
                "url": "route:fornitori:fornitore_documento_delete",
                "icona": "trash",
                "ui_slot": "hidden",
                "ui_section": "fornitori",
                "visible_topbar": False,
                "enabled": True,
            },
            {
                "codice": "fornitore_ordine_add",
                "nome_visibile": "Fornitori - Aggiungi ordine",
                "url": "route:fornitori:fornitore_ordine_add",
                "icona": "shopping-cart",
                "ui_slot": "hidden",
                "ui_section": "fornitori",
                "visible_topbar": False,
                "enabled": True,
            },
            {
                "codice": "fornitore_ordine_stato",
                "nome_visibile": "Fornitori - Cambia stato ordine",
                "url": "route:fornitori:fornitore_ordine_stato",
                "icona": "refresh-cw",
                "ui_slot": "hidden",
                "ui_section": "fornitori",
                "visible_topbar": False,
                "enabled": True,
            },
            {
                "codice": "fornitore_valutazione_add",
                "nome_visibile": "Fornitori - Aggiungi valutazione",
                "url": "route:fornitori:fornitore_valutazione_add",
                "icona": "star",
                "ui_slot": "hidden",
                "ui_section": "fornitori",
                "visible_topbar": False,
                "enabled": True,
            },
            {
                "codice": "fornitore_valutazione_delete",
                "nome_visibile": "Fornitori - Elimina valutazione",
                "url": "route:fornitori:fornitore_valutazione_delete",
                "icona": "trash",
                "ui_slot": "hidden",
                "ui_section": "fornitori",
                "visible_topbar": False,
                "enabled": True,
            },
            {
                "codice": "fornitore_asset_add",
                "nome_visibile": "Fornitori - Collega asset",
                "url": "route:fornitori:fornitore_asset_add",
                "icona": "link",
                "ui_slot": "hidden",
                "ui_section": "fornitori",
                "visible_topbar": False,
                "enabled": True,
            },
            {
                "codice": "fornitore_asset_remove",
                "nome_visibile": "Fornitori - Scollega asset",
                "url": "route:fornitori:fornitore_asset_remove",
                "icona": "unlink",
                "ui_slot": "hidden",
                "ui_section": "fornitori",
                "visible_topbar": False,
                "enabled": True,
            },
        ],
    },
    "timbri": {
        "label": "Timbri",
        "icon": "scan",
        "buttons": [
            {
                "codice": "view_timbri",
                "nome_visibile": "Timbri",
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
    existing = _pulsanti_ui_meta_map().get(int(pulsante_id), {})
    ui_slot = (
        str(payload.get("ui_slot") or "").strip() or None
        if "ui_slot" in payload
        else (existing.get("ui_slot") or None)
    )
    ui_section = (
        str(payload.get("ui_section") or "").strip() or None
        if "ui_section" in payload
        else (existing.get("ui_section") or None)
    )
    ui_order = _int_or_none(payload.get("ui_order")) if "ui_order" in payload else existing.get("ui_order")
    has_card_image = "card_image" in payload
    card_image = _clean_card_image_value(payload.get("card_image")) if has_card_image else _clean_card_image_value(
        _card_image_raw_value(pulsante_id)
    )
    visible_topbar = (
        _bool_from_any(payload.get("visible_topbar"))
        if "visible_topbar" in payload
        else _boolish_db(existing.get("visible_topbar"), True)
    )
    enabled = (
        _bool_from_any(payload.get("enabled"))
        if "enabled" in payload
        else _boolish_db(existing.get("enabled"), True)
    )
    is_padre = (
        _bool_from_any(payload.get("is_padre"))
        if "is_padre" in payload
        else _boolish_db(existing.get("is_padre"), False)
    )
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


def _dotenv_path() -> Path:
    return primary_runtime_env_path(Path(settings.BASE_DIR))


def _dotenv_target_label(path: Path | None = None) -> str:
    target = path or _dotenv_path()
    if target != Path(settings.BASE_DIR) / ".env":
        return "config/.env persistente dell'ambiente"
    return ".env runtime"


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


def _ollama_diag_defaults() -> dict[str, str | bool | int]:
    rag_source_paths = getattr(settings, "OLLAMA_RAG_SOURCE_PATHS", ["README.md", "docs/ai"]) or []
    if isinstance(rag_source_paths, str):
        rag_source_paths_default = rag_source_paths
    else:
        rag_source_paths_default = ",".join(str(item).strip() for item in rag_source_paths if str(item).strip())
    return {
        "enabled": _effective_env_bool("OLLAMA_CHAT_ENABLED", bool(getattr(settings, "OLLAMA_CHAT_ENABLED", True))),
        "provider": _effective_env_value(
            "OLLAMA_API_PROVIDER",
            str(getattr(settings, "OLLAMA_API_PROVIDER", "ollama") or "ollama"),
        ).lower(),
        "base_url": _effective_env_value("OLLAMA_BASE_URL", str(getattr(settings, "OLLAMA_BASE_URL", "") or "")),
        "model": _effective_env_value("OLLAMA_CHAT_MODEL", str(getattr(settings, "OLLAMA_CHAT_MODEL", "") or "")),
        "openwebui_api_key_configured": bool(
            _effective_env_value("OPENWEBUI_API_KEY", str(getattr(settings, "OPENWEBUI_API_KEY", "") or ""))
        ),
        "timeout": _effective_env_int(
            "OLLAMA_REQUEST_TIMEOUT_SECONDS",
            int(getattr(settings, "OLLAMA_REQUEST_TIMEOUT_SECONDS", 60) or 60),
        ),
        "temperature": _effective_env_value(
            "OLLAMA_CHAT_TEMPERATURE",
            str(getattr(settings, "OLLAMA_CHAT_TEMPERATURE", "0.2") or "0.2"),
        ),
        "max_prompt_chars": _effective_env_int(
            "OLLAMA_CHAT_MAX_PROMPT_CHARS",
            int(getattr(settings, "OLLAMA_CHAT_MAX_PROMPT_CHARS", 4000) or 4000),
        ),
        "max_history_messages": _effective_env_int(
            "OLLAMA_CHAT_MAX_HISTORY_MESSAGES",
            int(getattr(settings, "OLLAMA_CHAT_MAX_HISTORY_MESSAGES", 10) or 10),
        ),
        "rag_enabled": _effective_env_bool("OLLAMA_RAG_ENABLED", bool(getattr(settings, "OLLAMA_RAG_ENABLED", True))),
        "rag_source_paths": _effective_env_value("OLLAMA_RAG_SOURCE_PATHS", rag_source_paths_default),
        "rag_max_chunks": _effective_env_int(
            "OLLAMA_RAG_MAX_CHUNKS",
            int(getattr(settings, "OLLAMA_RAG_MAX_CHUNKS", 4) or 4),
        ),
        "rag_max_context_chars": _effective_env_int(
            "OLLAMA_RAG_MAX_CONTEXT_CHARS",
            int(getattr(settings, "OLLAMA_RAG_MAX_CONTEXT_CHARS", 5000) or 5000),
        ),
        "rag_cache_seconds": _effective_env_int(
            "OLLAMA_RAG_CACHE_SECONDS",
            int(getattr(settings, "OLLAMA_RAG_CACHE_SECONDS", 300) or 300),
        ),
        "rag_max_db_entries": _effective_env_int(
            "OLLAMA_RAG_MAX_DB_ENTRIES",
            int(getattr(settings, "OLLAMA_RAG_MAX_DB_ENTRIES", 200) or 200),
        ),
    }


def _ollama_posted_config(post_data, defaults: dict[str, object]) -> dict[str, object]:
    def posted_or_default(field_name: str, default: object) -> str:
        raw_value = post_data.get(field_name)
        if raw_value in (None, ""):
            return str(default or "").strip()
        return str(raw_value).strip()

    return {
        "enabled": _bool_from_any(post_data.get("ollama_enabled")),
        "provider": posted_or_default("ollama_provider", defaults.get("provider") or "ollama").lower(),
        "base_url": (post_data.get("ollama_base_url") or str(defaults.get("base_url") or "")).strip(),
        "model": (post_data.get("ollama_model") or str(defaults.get("model") or "")).strip(),
        "openwebui_api_key": str(post_data.get("openwebui_api_key") or "").strip(),
        "openwebui_api_key_configured": bool(defaults.get("openwebui_api_key_configured")),
        "timeout": posted_or_default("ollama_timeout", defaults.get("timeout") or 60),
        "temperature": posted_or_default("ollama_temperature", defaults.get("temperature") or "0.2"),
        "max_prompt_chars": posted_or_default("ollama_max_prompt_chars", defaults.get("max_prompt_chars") or 4000),
        "max_history_messages": posted_or_default(
            "ollama_max_history_messages",
            defaults.get("max_history_messages") or 10,
        ),
        "rag_enabled": _bool_from_any(post_data.get("ollama_rag_enabled")),
        "rag_source_paths": posted_or_default(
            "ollama_rag_source_paths",
            defaults.get("rag_source_paths") or "README.md,docs/ai",
        ),
        "rag_max_chunks": posted_or_default("ollama_rag_max_chunks", defaults.get("rag_max_chunks") or 4),
        "rag_max_context_chars": posted_or_default(
            "ollama_rag_max_context_chars",
            defaults.get("rag_max_context_chars") or 5000,
        ),
        "rag_cache_seconds": posted_or_default(
            "ollama_rag_cache_seconds",
            defaults.get("rag_cache_seconds") or 300,
        ),
        "rag_max_db_entries": posted_or_default(
            "ollama_rag_max_db_entries",
            defaults.get("rag_max_db_entries") or 200,
        ),
    }


def _ollama_validate_config(config: dict[str, object]) -> tuple[bool, dict[str, object], str]:
    enabled = bool(config.get("enabled"))
    provider = str(config.get("provider") or "ollama").strip().lower()
    base_url = str(config.get("base_url") or "").strip().rstrip("/")
    model = str(config.get("model") or "").strip()
    if provider not in {"ollama", "openwebui"}:
        return False, config, "Provider AI non valido: scegli Ollama diretto oppure Open WebUI."

    if enabled:
        if not base_url:
            return False, config, "URL Ollama obbligatorio quando l'assistente AI e' abilitato."
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False, config, "URL Ollama non valido: usa http://host:porta oppure https://host:porta."
        if not model:
            return False, config, "Modello Ollama obbligatorio quando l'assistente AI e' abilitato."
        if provider == "openwebui" and not (
            str(config.get("openwebui_api_key") or "").strip() or bool(config.get("openwebui_api_key_configured"))
        ):
            return False, config, "API key Open WebUI obbligatoria: creala da Open WebUI > Settings > Account."
    elif base_url:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False, config, "URL Ollama non valido: usa http://host:porta oppure https://host:porta."

    try:
        timeout = int(str(config.get("timeout") or "").strip())
    except (TypeError, ValueError):
        return False, config, "Timeout Ollama non valido: usa un valore tra 1 e 300 secondi."
    if timeout < 1 or timeout > 300:
        return False, config, "Timeout Ollama non valido: usa un valore tra 1 e 300 secondi."

    try:
        temperature = float(str(config.get("temperature") or "0.2").replace(",", "."))
    except (TypeError, ValueError):
        return False, config, "Temperatura Ollama non valida: usa un numero tra 0 e 2."
    if temperature < 0 or temperature > 2:
        return False, config, "Temperatura Ollama non valida: usa un numero tra 0 e 2."

    try:
        max_prompt_chars = int(str(config.get("max_prompt_chars") or "").strip())
    except (TypeError, ValueError):
        return False, config, "Max prompt non valido: usa un valore tra 500 e 20000 caratteri."
    if max_prompt_chars < 500 or max_prompt_chars > 20000:
        return False, config, "Max prompt non valido: usa un valore tra 500 e 20000 caratteri."

    try:
        max_history_messages = int(str(config.get("max_history_messages") or "").strip())
    except (TypeError, ValueError):
        return False, config, "Max storico non valido: usa un valore tra 0 e 30 messaggi."
    if max_history_messages < 0 or max_history_messages > 30:
        return False, config, "Max storico non valido: usa un valore tra 0 e 30 messaggi."

    rag_enabled = bool(config.get("rag_enabled"))
    rag_source_paths = str(config.get("rag_source_paths") or "").strip()
    if rag_enabled and not rag_source_paths:
        return False, config, "Percorsi knowledge base obbligatori quando il RAG e' abilitato."
    if len(rag_source_paths) > 1000:
        return False, config, "Percorsi knowledge base troppo lunghi: usa massimo 1000 caratteri."
    forbidden_path_tokens = {".env", "media_private", "logs", "sqlite", ".db", "secrets"}
    lowered_paths = rag_source_paths.lower()
    if any(token in lowered_paths for token in forbidden_path_tokens):
        return False, config, "Percorsi knowledge base non validi: non indicizzare env, log, database o aree private."

    try:
        rag_max_chunks = int(str(config.get("rag_max_chunks") or "").strip())
    except (TypeError, ValueError):
        return False, config, "Max chunk RAG non valido: usa un valore tra 1 e 10."
    if rag_max_chunks < 1 or rag_max_chunks > 10:
        return False, config, "Max chunk RAG non valido: usa un valore tra 1 e 10."

    try:
        rag_max_context_chars = int(str(config.get("rag_max_context_chars") or "").strip())
    except (TypeError, ValueError):
        return False, config, "Max contesto RAG non valido: usa un valore tra 1000 e 20000 caratteri."
    if rag_max_context_chars < 1000 or rag_max_context_chars > 20000:
        return False, config, "Max contesto RAG non valido: usa un valore tra 1000 e 20000 caratteri."

    try:
        rag_cache_seconds = int(str(config.get("rag_cache_seconds") or "").strip())
    except (TypeError, ValueError):
        return False, config, "Cache RAG non valida: usa un valore tra 0 e 3600 secondi."
    if rag_cache_seconds < 0 or rag_cache_seconds > 3600:
        return False, config, "Cache RAG non valida: usa un valore tra 0 e 3600 secondi."

    try:
        rag_max_db_entries = int(str(config.get("rag_max_db_entries") or "").strip())
    except (TypeError, ValueError):
        return False, config, "Max FAQ AI non valido: usa un valore tra 0 e 1000."
    if rag_max_db_entries < 0 or rag_max_db_entries > 1000:
        return False, config, "Max FAQ AI non valido: usa un valore tra 0 e 1000."

    normalized = {
        "enabled": enabled,
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "openwebui_api_key": str(config.get("openwebui_api_key") or "").strip(),
        "openwebui_api_key_configured": bool(config.get("openwebui_api_key_configured")),
        "timeout": timeout,
        "temperature": str(temperature).rstrip("0").rstrip(".") if "." in str(temperature) else str(temperature),
        "max_prompt_chars": max_prompt_chars,
        "max_history_messages": max_history_messages,
        "rag_enabled": rag_enabled,
        "rag_source_paths": rag_source_paths,
        "rag_max_chunks": rag_max_chunks,
        "rag_max_context_chars": rag_max_context_chars,
        "rag_cache_seconds": rag_cache_seconds,
        "rag_max_db_entries": rag_max_db_entries,
    }
    return True, normalized, ""


def _ollama_endpoint_hint(base_url: str, *, http_status: int | None = None) -> str:
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
        host = parsed.hostname or "host"
    except ValueError:
        port = None
        host = "host"
    if port in {3000, 8080, 8081} or http_status in {404, 405}:
        return (
            "L'URL configurato sembra non essere l'API nativa di Ollama. "
            "Non usare l'indirizzo di Open WebUI: configura l'endpoint Ollama, "
            f"per esempio http://{host}:11434."
        )
    return "Verifica che l'URL punti all'API nativa di Ollama, non a Open WebUI."


def _ollama_json_get(url: str, timeout: int, *, headers: dict[str, str] | None = None) -> dict:
    request_headers = {"Accept": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, headers=request_headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    raw = raw.strip()
    return json.loads(raw or "{}")


def _ollama_catalog_warning(exc: Exception) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return "Catalogo modelli non verificato: /api/tags non ha restituito JSON valido."
    if isinstance(exc, urllib.error.HTTPError):
        return f"Catalogo modelli non verificato: /api/tags ha risposto HTTP {exc.code}."
    if isinstance(exc, TimeoutError):
        return "Catalogo modelli non verificato: timeout su /api/tags."
    if isinstance(exc, urllib.error.URLError):
        return f"Catalogo modelli non verificato: /api/tags non raggiungibile ({getattr(exc, 'reason', exc)})."
    return "Catalogo modelli non verificato: risposta /api/tags non leggibile."


def _ollama_test_connect(config: dict[str, object]) -> tuple[bool, str, dict[str, object]]:
    ok, normalized, error = _ollama_validate_config(config)
    if not ok:
        return False, error, {}
    if not normalized["enabled"]:
        return False, "Assistente AI disabilitato: abilitalo per eseguire il test Ollama.", {}

    base_url = str(normalized["base_url"])
    provider = str(normalized["provider"])
    model = str(normalized["model"])
    timeout = int(normalized["timeout"])
    if provider == "openwebui":
        api_key = str(normalized.get("openwebui_api_key") or "").strip() or _effective_env_value(
            "OPENWEBUI_API_KEY",
            str(getattr(settings, "OPENWEBUI_API_KEY", "") or ""),
        )
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        try:
            models_payload = _ollama_json_get(f"{base_url}/api/models", timeout, headers=headers)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                return False, (
                    f"Open WebUI ha risposto HTTP {exc.code}: API key mancante, non valida o scaduta. "
                    "Rigenera la key in Open WebUI > Settings > Account, incollala nel campo API key Open WebUI "
                    "e premi Test connessione o Salva configurazione."
                ), {}
            return False, f"Open WebUI non ha accettato il test modelli (HTTP {exc.code}). Verifica URL e API key.", {}
        except urllib.error.URLError as exc:
            return False, f"Open WebUI non raggiungibile: {getattr(exc, 'reason', exc)}", {}
        except TimeoutError:
            return False, "Timeout durante il test connessione Open WebUI.", {}
        except (OSError, json.JSONDecodeError) as exc:
            return False, f"Test Open WebUI fallito: {exc}", {}
        models = models_payload.get("data") if isinstance(models_payload, dict) else []
        names = {
            str(item.get("id") or item.get("name") or "").strip()
            for item in models
            if isinstance(item, dict) and str(item.get("id") or item.get("name") or "").strip()
        }
        model_available = model in names or model in {name.removesuffix(":latest") for name in names}
        metadata = {"version": "openwebui", "model_available": model_available}
        if model_available is False:
            return False, f"Open WebUI raggiunto, ma modello '{model}' non trovato in /api/models.", metadata
        return True, f"Open WebUI raggiunto. Modello '{model}' disponibile.", metadata
    try:
        version_payload = _ollama_json_get(f"{base_url}/api/version", timeout)
    except urllib.error.HTTPError as exc:
        return False, f"Endpoint Ollama non compatibile (HTTP {exc.code}). {_ollama_endpoint_hint(base_url, http_status=exc.code)}", {}
    except urllib.error.URLError as exc:
        return False, f"Ollama non raggiungibile: {getattr(exc, 'reason', exc)}", {}
    except TimeoutError:
        return False, "Timeout durante il test connessione Ollama.", {}
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"Test Ollama fallito: {exc}", {}

    tags_note = "Catalogo modelli non verificato."
    model_available = None
    try:
        tags_payload = _ollama_json_get(f"{base_url}/api/tags", timeout)
        models = tags_payload.get("models") if isinstance(tags_payload, dict) else []
        names = {
            str(item.get("name") or "").strip()
            for item in models
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
        names_without_latest = {name.removesuffix(":latest") for name in names}
        model_available = model in names or model in names_without_latest
        tags_note = f"Modello '{model}' disponibile." if model_available else f"Modello '{model}' non trovato in /api/tags."
    except Exception as exc:
        tags_note = _ollama_catalog_warning(exc)

    metadata = {
        "version": str(version_payload.get("version") or "") if isinstance(version_payload, dict) else "",
        "model_available": model_available,
    }
    if model_available is False:
        return False, f"Connessione Ollama riuscita, ma {tags_note}", metadata
    version_label = metadata["version"] or "versione non dichiarata"
    return True, f"Connessione Ollama riuscita ({version_label}). {tags_note}", metadata


def _ollama_save_settings(config: dict[str, object]) -> tuple[bool, str, dict[str, object]]:
    ok, normalized, error = _ollama_validate_config(config)
    if not ok:
        return False, error, config
    saved, message = _update_dotenv_assignments(
        {
            "OLLAMA_CHAT_ENABLED": "1" if normalized["enabled"] else "0",
            "OLLAMA_API_PROVIDER": str(normalized["provider"]),
            "OLLAMA_BASE_URL": str(normalized["base_url"]),
            "OLLAMA_CHAT_MODEL": str(normalized["model"]),
            "OLLAMA_REQUEST_TIMEOUT_SECONDS": str(normalized["timeout"]),
            "OLLAMA_CHAT_TEMPERATURE": str(normalized["temperature"]),
            "OLLAMA_CHAT_MAX_PROMPT_CHARS": str(normalized["max_prompt_chars"]),
            "OLLAMA_CHAT_MAX_HISTORY_MESSAGES": str(normalized["max_history_messages"]),
            "OLLAMA_RAG_ENABLED": "1" if normalized["rag_enabled"] else "0",
            "OLLAMA_RAG_SOURCE_PATHS": str(normalized["rag_source_paths"]),
            "OLLAMA_RAG_MAX_CHUNKS": str(normalized["rag_max_chunks"]),
            "OLLAMA_RAG_MAX_CONTEXT_CHARS": str(normalized["rag_max_context_chars"]),
            "OLLAMA_RAG_CACHE_SECONDS": str(normalized["rag_cache_seconds"]),
            "OLLAMA_RAG_MAX_DB_ENTRIES": str(normalized["rag_max_db_entries"]),
            **(
                {"OPENWEBUI_API_KEY": str(normalized["openwebui_api_key"])}
                if str(normalized.get("openwebui_api_key") or "").strip()
                else {}
            ),
        }
    )
    if not saved:
        return False, message, normalized
    return True, "Configurazione Assistente AI salvata. Riavvia il server per applicare.", normalized


def _update_dotenv_assignments(values: dict[str, str], *, delete_keys: list[str] | None = None) -> tuple[bool, str]:
    dotenv_path = _dotenv_path()
    try:
        update_env_file_values(values, dotenv_path=dotenv_path, delete_keys=delete_keys or [])
    except Exception as exc:
        return False, f"Errore scrittura .env: {exc}"
    return True, (
        f"Configurazione salvata in {_dotenv_target_label(dotenv_path)}. "
        "La sync da questa pagina usa subito i valori salvati; il runtime li applica dopo reload/deploy."
    )


def _role_choices():
    try:
        return list(Ruolo.objects.all().order_by("nome", "id"))
    except DatabaseError:
        return []


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
    # True se il modulo ha almeno un RoutePermissionBinding canonico attivo: in tal
    # caso i permessi legacy mostrati qui sono IGNORATI a runtime (decide l'ACL v2).
    canonical_managed: bool = False


def _canonical_managed_modules() -> set[str]:
    """Moduli (lowercase) con almeno un RoutePermissionBinding canonico attivo.

    Per questi moduli la decisione ACL passa per i grant canonici (ACL v2) e i
    permessi della tabella legacy sono ignorati a runtime — vedi core.acl_v2.
    """
    try:
        return {
            (b.source_app or "").strip().lower()
            for b in RoutePermissionBinding.objects.filter(is_active=True)
            if (b.source_app or "").strip()
        }
    except DatabaseError:
        return set()


def _canonical_module_write_block(modulo: str):
    """Restituisce una JsonResponse 409 se il modulo è governato dall'ACL canonico.

    Difesa server-side per gli endpoint di scrittura permessi LEGACY: su un modulo
    con binding canonico attivo la scrittura legacy è inefficace a runtime (vedi
    core.acl_v2) e va impedita per non illudere l'admin. Ritorna None se consentito.
    """
    mod = (modulo or "").strip().lower()
    if mod and mod in _canonical_managed_modules():
        return _json_error(
            f"Il modulo '{modulo}' è governato dall'ACL canonico (v2): i permessi "
            "legacy qui non hanno effetto. Gestisci gli accessi in "
            "/admin-portale/acl-canonico/.",
            status=409,
        )
    return None


def _aggregate_to_module_rows(rows: list[PermRow]) -> list[ModuloPermRow]:
    """Aggrega una lista di PermRow in ModuloPermRow (uno per modulo)."""
    module_map: dict[str, list[PermRow]] = {}
    for row in rows:
        key = (row.modulo or "").strip() or "N/D"
        module_map.setdefault(key, []).append(row)
    canonical_modules = _canonical_managed_modules()
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
            canonical_managed=modulo.strip().lower() in canonical_modules,
        ))
    return result


def _module_perm_rows_for_user(legacy_user_id: int) -> list[ModuloPermRow]:
    return _aggregate_to_module_rows(_full_perm_rows_for_user(legacy_user_id))


def _apply_accessi_semplice_changes(
    role_id: int,
    module_rows: list[dict],
    allowed_modules: set[str],
) -> tuple[int, list[str]]:
    """Applica i cambiamenti richiesti dalla UI semplificata sul solo layer canonico."""
    canonical_changed = 0
    skipped_modules: list[str] = []

    for row in module_rows:
        modulo = str(row.get("modulo") or "").strip()
        if not modulo:
            continue
        should_allow = modulo in allowed_modules
        permission_codes: list[str] = []
        seen_permission_codes: set[str] = set()
        for permission_code in row.get("canonical_permission_codes", []):
            permission_norm = normalize_permission_code(str(permission_code or ""))
            if not permission_norm or permission_norm in seen_permission_codes:
                continue
            seen_permission_codes.add(permission_norm)
            permission_codes.append(permission_norm)
        if not permission_codes:
            skipped_modules.append(modulo)
            continue
        for permission_norm in permission_codes:
            existing = (
                RolePermissionGrant.objects.filter(
                    legacy_role_id=int(role_id),
                    permission_id=permission_norm,
                )
                .order_by("-id")
                .first()
            )
            if should_allow:
                if existing is not None and bool(existing.enabled):
                    continue
                grant, created = RolePermissionGrant.objects.update_or_create(
                    legacy_role_id=int(role_id),
                    permission_id=permission_norm,
                    defaults={"enabled": True},
                )
                if created or not bool(getattr(existing, "enabled", False)):
                    canonical_changed += 1
                if not bool(grant.enabled):
                    grant.enabled = True
                    grant.save(update_fields=["enabled"])
                continue
            if existing is None:
                continue
            if not bool(existing.enabled):
                continue
            existing.enabled = False
            existing.save(update_fields=["enabled"])
            canonical_changed += 1

    return canonical_changed, skipped_modules


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


def _navigation_item_permission_code(item: NavigationItem) -> str:
    return normalize_permission_code(resolve_navigation_item_permission_code(item))


def _canonical_grants_map_for_role(role_id: int | None) -> dict[str, bool]:
    if role_id is None:
        return {}
    try:
        rows = list(
            RolePermissionGrant.objects.filter(legacy_role_id=int(role_id)).values(
                "permission_id",
                "enabled",
            )
        )
    except Exception:
        return {}
    grants_map: dict[str, bool] = {}
    for row in rows:
        permission_code = normalize_permission_code(str(row.get("permission_id") or ""))
        if permission_code:
            grants_map[permission_code] = bool(row.get("enabled"))
    return grants_map


def _acting_is_superuser(request) -> bool:
    """True se chi ha fatto login (non l'eventuale utente impersonato) e' superuser."""
    real_user = getattr(request, "impersonator_user", None) or request.user
    return bool(getattr(real_user, "is_superuser", False))


_TIPI_OPZIONE_LABELS = {
    "reparto":     "Reparti",
    "caporeparto": "Capireparto",
    "macchina":    "Macchine",
}


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


def _json_error(message: str, status: int = 400):
    return JsonResponse({"ok": False, "error": message}, status=status)


def _schedule_legacy_acl_cache_invalidation() -> None:
    transaction.on_commit(bump_legacy_cache_version)
    transaction.on_commit(bump_navigation_registry_version)


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
    blocked = _canonical_module_write_block(parsed[1])
    if blocked is not None:
        return blocked
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
def api_permessi_bulk(request):
    payload = _json_payload(request)
    ruolo_id = _int_or_none(payload.get("ruolo_id"))
    if ruolo_id is None:
        return _json_error("Payload bulk non valido.")

    allowed_fields = [name for name in _perm_flag_names() if name != "consentito"]
    mode = str(payload.get("mode") or "").strip().lower()
    updates = payload.get("updates")
    if updates is None:
        # The role wizard originally posts the rows under this key.
        updates = payload.get("rows") or []

    try:
        with transaction.atomic():
            if mode == "set_all":
                target_field = str(payload.get("field") or "").strip()
                target_value = _bool_from_any(payload.get("value"))
                if target_field and target_field not in allowed_fields:
                    return _json_error("Campo bulk non consentito.")
                # I moduli governati dall'ACL canonico non sono scrivibili lato legacy:
                # il bulk salta quei moduli per non illudere l'admin (vedi core.acl_v2).
                canonical_modules = _canonical_managed_modules()
                affected = 0
                skipped_canonical = 0
                for modulo, azione in _pulsanti_acl_keys():
                    if (modulo or "").strip().lower() in canonical_modules:
                        skipped_canonical += 1
                        continue
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
                    "skipped_canonical": skipped_canonical,
                })
                return JsonResponse({
                    "ok": True,
                    "affected": affected,
                    "skipped_canonical": skipped_canonical,
                })

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


def _clean_login_asset_url(value: str, *, label: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    parsed = urlsplit(cleaned)
    if parsed.scheme in {"http", "https"} or cleaned.startswith("/"):
        return cleaned
    raise ValueError(f"{label}: usa un percorso /media/... o un URL http/https.")


def _clean_login_landing_url(value: str) -> str:
    return _clean_login_asset_url(value, label="Immagine landing")


def _release_process_restart_fallback_enabled() -> bool:
    raw = os.environ.get("PORTAL_RELEASE_PROCESS_RESTART_FALLBACK", "1").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if os.environ.get("DJANGO_SETTINGS_MODULE", "").endswith(".test"):
        return False
    if os.environ.get("HTTP_PLATFORM_PORT") or os.environ.get("PORTAL_ENV_ROOT"):
        return True
    return not getattr(settings, "DEBUG", False)


def _release_schedule_process_restart(delay_seconds: float = 2.0) -> bool:
    if not _release_process_restart_fallback_enabled():
        return False

    def _exit_process() -> None:
        logger.warning("Riavvio processo Django schedulato dalla pagina Crea Release")
        os._exit(0)

    timer = threading.Timer(delay_seconds, _exit_process)
    timer.daemon = True
    timer.start()
    return True
