from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import DatabaseError, transaction

from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Pulsante

logger = logging.getLogger(__name__)

_BOOTSTRAP_CACHE_KEY = "tasks_acl_bootstrap_v1"
_BOOTSTRAP_TTL_SECONDS = 300

_PULSANTI_DEFINITIONS = [
    {
        "modulo": "tasks",
        "codice": "tasks_view",
        "label": "Task - Lista",
        "url": "/tasks/",
        "visible_topbar": True,
        "ui_order": 45,
    },
    {
        "modulo": "tasks",
        "codice": "tasks_create",
        "label": "Task - Crea",
        "url": "/tasks/new/",
        "visible_topbar": False,
        "ui_order": None,
    },
    {
        "modulo": "tasks",
        "codice": "tasks_edit",
        "label": "Task - Modifica",
        "url": "/tasks/edit/",
        "visible_topbar": False,
        "ui_order": None,
    },
    {
        "modulo": "tasks",
        "codice": "tasks_comment",
        "label": "Task - Commenta",
        "url": "/tasks/comment/",
        "visible_topbar": False,
        "ui_order": None,
    },
    {
        "modulo": "tasks",
        "codice": "tasks_admin",
        "label": "Task - Scope globale",
        "url": "/tasks/admin/",
        "visible_topbar": False,
        "ui_order": None,
    },
]


def _upsert_pulsante(modulo: str, codice: str, label: str, url: str) -> tuple[int | None, bool]:
    changed = False
    pulsante = None
    try:
        pulsante = Pulsante.objects.filter(url__iexact=url).order_by("-id").first()
        if pulsante is None:
            pulsante = Pulsante.objects.filter(modulo__iexact=modulo, codice__iexact=codice).order_by("-id").first()
    except DatabaseError:
        return None, False

    if pulsante is None:
        try:
            pulsante = Pulsante.objects.create(
                modulo=modulo,
                codice=codice,
                nome_visibile=label,
                url=url,
                icona="check-square",
            )
            changed = True
        except DatabaseError:
            return None, False
    else:
        updates = []
        if (pulsante.modulo or "").strip() != modulo:
            pulsante.modulo = modulo
            updates.append("modulo")
        if (pulsante.codice or "").strip() != codice:
            pulsante.codice = codice
            updates.append("codice")
        if (pulsante.nome_visibile or "").strip() != label:
            pulsante.nome_visibile = label
            updates.append("nome_visibile")
        if (pulsante.url or "").strip() != url:
            pulsante.url = url
            updates.append("url")
        if updates:
            try:
                pulsante.save(update_fields=updates)
                changed = True
            except DatabaseError:
                return None, False

    return int(pulsante.id), changed


def _ensure_ui_meta_table() -> None:
    from django.db import connections

    try:
        with connections["default"].cursor() as cursor:
            vendor = connections["default"].vendor
            if vendor == "sqlite":
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ui_pulsanti_meta (
                        pulsante_id INTEGER PRIMARY KEY,
                        ui_slot TEXT NULL, ui_section TEXT NULL, ui_order INTEGER NULL,
                        visible_topbar INTEGER NOT NULL DEFAULT 1,
                        enabled INTEGER NOT NULL DEFAULT 1, updated_at TEXT NULL
                    )
                    """
                )
            else:
                cursor.execute(
                    """
                    IF OBJECT_ID('ui_pulsanti_meta', 'U') IS NULL
                    CREATE TABLE ui_pulsanti_meta (
                        pulsante_id INT NOT NULL PRIMARY KEY,
                        ui_slot NVARCHAR(50) NULL, ui_section NVARCHAR(100) NULL, ui_order INT NULL,
                        visible_topbar BIT NOT NULL DEFAULT 1,
                        enabled BIT NOT NULL DEFAULT 1, updated_at DATETIME2 NULL
                    )
                    """
                )
    except Exception:
        pass


def _set_topbar_visibility(pulsante_id: int, *, visible_topbar: bool, ui_order: int | None) -> None:
    _ensure_ui_meta_table()
    from django.db import connections

    slot = "topbar" if visible_topbar else "hidden"
    section = "tasks"
    visible_value = 1 if visible_topbar else 0

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
                        ui_order=excluded.ui_order,
                        visible_topbar=excluded.visible_topbar,
                        enabled=excluded.enabled,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    [pulsante_id, slot, section, ui_order, visible_value, 1],
                )
            else:
                cursor.execute(
                    """
                    MERGE ui_pulsanti_meta AS target
                    USING (SELECT %s AS pulsante_id) AS src ON target.pulsante_id = src.pulsante_id
                    WHEN MATCHED THEN UPDATE SET
                        ui_slot=%s,
                        ui_section=%s,
                        ui_order=%s,
                        visible_topbar=%s,
                        enabled=%s,
                        updated_at=SYSUTCDATETIME()
                    WHEN NOT MATCHED THEN INSERT
                        (pulsante_id, ui_slot, ui_section, ui_order, visible_topbar, enabled, updated_at)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, SYSUTCDATETIME());
                    """,
                    [
                        pulsante_id,
                        slot,
                        section,
                        ui_order,
                        visible_value,
                        1,
                        pulsante_id,
                        slot,
                        section,
                        ui_order,
                        visible_value,
                        1,
                    ],
                )
    except Exception:
        pass


def bootstrap_tasks_acl_endpoints(force: bool = False) -> None:
    if not force and cache.get(_BOOTSTRAP_CACHE_KEY):
        return

    changed = False
    try:
        with transaction.atomic():
            for definition in _PULSANTI_DEFINITIONS:
                pulsante_id, item_changed = _upsert_pulsante(
                    modulo=definition["modulo"],
                    codice=definition["codice"],
                    label=definition["label"],
                    url=definition["url"],
                )
                if pulsante_id:
                    _set_topbar_visibility(
                        pulsante_id,
                        visible_topbar=bool(definition.get("visible_topbar")),
                        ui_order=definition.get("ui_order"),
                    )
                changed = changed or item_changed
    except Exception as exc:
        logger.debug("ACL bootstrap tasks skipped: %s", exc)
        return

    if changed:
        try:
            bump_legacy_cache_version()
        except Exception:
            pass

    cache.set(_BOOTSTRAP_CACHE_KEY, True, timeout=_BOOTSTRAP_TTL_SECONDS)
