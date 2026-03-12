from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import DatabaseError, connections, transaction

from core.legacy_cache import bump_legacy_cache_version, normalize_legacy_button_url
from core.legacy_models import Pulsante

logger = logging.getLogger(__name__)

_BOOTSTRAP_CACHE_KEY = "assenze_acl_bootstrap_v1"
_BOOTSTRAP_TTL_SECONDS = 300


def _ensure_ui_meta_table() -> None:
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
                        visible_topbar INTEGER NOT NULL DEFAULT 1,
                        enabled INTEGER NOT NULL DEFAULT 1,
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
                        visible_topbar BIT NOT NULL DEFAULT 1,
                        enabled BIT NOT NULL DEFAULT 1,
                        updated_at DATETIME2 NULL
                    )
                    """
                )
    except Exception:
        return


def _hide_api_pulsante(pulsante_id: int) -> None:
    _ensure_ui_meta_table()
    try:
        with connections["default"].cursor() as cursor:
            vendor = connections["default"].vendor
            if vendor == "sqlite":
                cursor.execute(
                    """
                    INSERT INTO ui_pulsanti_meta
                        (pulsante_id, ui_slot, ui_section, ui_order, visible_topbar, enabled, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT(pulsante_id) DO UPDATE SET
                        ui_slot=excluded.ui_slot,
                        ui_section=excluded.ui_section,
                        visible_topbar=excluded.visible_topbar,
                        enabled=excluded.enabled,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    [pulsante_id, "hidden", "assenze_api", None, 0, 1],
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
                        visible_topbar = %s,
                        enabled = %s,
                        updated_at = SYSUTCDATETIME()
                    WHEN NOT MATCHED THEN
                        INSERT (pulsante_id, ui_slot, ui_section, ui_order, visible_topbar, enabled, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, SYSUTCDATETIME());
                    """,
                    [pulsante_id, "hidden", "assenze_api", 0, 1, pulsante_id, "hidden", "assenze_api", None, 0, 1],
                )
    except Exception:
        return


def _calendar_acl_identity() -> tuple[str, str]:
    fallback = ("assenze", "assenze_calendario")
    try:
        for pulsante in Pulsante.objects.all():
            norm = normalize_legacy_button_url(pulsante.url or "")
            if norm == "/assenze/calendario":
                modulo = (pulsante.modulo or "").strip() or fallback[0]
                codice = (pulsante.codice or "").strip() or fallback[1]
                return modulo, codice
    except DatabaseError:
        return fallback
    return fallback


def _upsert_acl_pulsante(
    modulo: str,
    codice: str,
    label: str,
    url: str,
    allow_acl_match: bool = True,
) -> tuple[int | None, bool]:
    changed = False
    pulsante = None
    try:
        pulsante = Pulsante.objects.filter(url__iexact=url).order_by("-id").first()
        if pulsante is None and allow_acl_match:
            pulsante = Pulsante.objects.filter(modulo__iexact=modulo, codice__iexact=codice).order_by("-id").first()
    except DatabaseError:
        return None, False

    if pulsante is None:
        try:
            pulsante = Pulsante.objects.create(
                codice=codice,
                nome_visibile=label,
                modulo=modulo,
                url=url,
                icona="lock",
            )
            changed = True
        except DatabaseError:
            return None, False
    else:
        update_fields = []
        if (pulsante.modulo or "").strip() != modulo:
            pulsante.modulo = modulo
            update_fields.append("modulo")
        if allow_acl_match and (pulsante.codice or "").strip() != codice:
            pulsante.codice = codice
            update_fields.append("codice")
        if (pulsante.url or "").strip() != url:
            pulsante.url = url
            update_fields.append("url")
        expected_label = (label or "").strip()
        if expected_label and (pulsante.nome_visibile or "").strip() != expected_label:
            pulsante.nome_visibile = expected_label
            update_fields.append("nome_visibile")
        if update_fields:
            try:
                pulsante.save(update_fields=update_fields)
                changed = True
            except DatabaseError:
                return None, False

    return int(pulsante.id), changed


def bootstrap_assenze_acl_endpoints(force: bool = False) -> None:
    if not force and cache.get(_BOOTSTRAP_CACHE_KEY):
        return

    calendar_modulo, calendar_codice = _calendar_acl_identity()
    definitions = [
        {
            "modulo": calendar_modulo,
            "codice": calendar_codice,
            "label": "Assenze API Eventi (Calendario)",
            "url": "/assenze/api/eventi",
            "allow_acl_match": False,
        },
        {
            "modulo": "assenze",
            "codice": "assenze_eventi_colors",
            "label": "Assenze API Colori Calendario",
            "url": "/assenze/api/eventi/colors",
            "allow_acl_match": True,
        },
        {
            "modulo": "assenze",
            "codice": "assenze_evento_update",
            "label": "Assenze API Modifica Evento",
            "url": "/assenze/api/eventi/update",
            "allow_acl_match": True,
        },
        {
            "modulo": "assenze",
            "codice": "assenze_evento_delete",
            "label": "Assenze API Elimina Evento",
            "url": "/assenze/api/eventi/delete",
            "allow_acl_match": True,
        },
        {
            "modulo": "assenze",
            "codice": "assenze_sync_push",
            "label": "Assenze Sync Push SharePoint",
            "url": "/assenze/api/sync/push",
            "allow_acl_match": True,
        },
        {
            "modulo": "assenze",
            "codice": "assenze_sync_pull",
            "label": "Assenze Sync Pull SharePoint",
            "url": "/assenze/api/sync/pull",
            "allow_acl_match": True,
        },
    ]

    changed = False
    created_ids: list[int] = []
    try:
        with transaction.atomic():
            for item in definitions:
                pulsante_id, item_changed = _upsert_acl_pulsante(
                    modulo=item["modulo"],
                    codice=item["codice"],
                    label=item["label"],
                    url=item["url"],
                    allow_acl_match=bool(item["allow_acl_match"]),
                )
                if pulsante_id:
                    created_ids.append(pulsante_id)
                changed = changed or item_changed
    except Exception as exc:
        logger.debug("ACL bootstrap assenze skipped: %s", exc)
        return

    for pulsante_id in created_ids:
        _hide_api_pulsante(pulsante_id)

    if changed:
        try:
            bump_legacy_cache_version()
        except Exception:
            pass

    cache.set(_BOOTSTRAP_CACHE_KEY, True, timeout=_BOOTSTRAP_TTL_SECONDS)
