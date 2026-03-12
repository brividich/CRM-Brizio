from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import DatabaseError, connections, transaction

from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Permesso, Pulsante, Ruolo

logger = logging.getLogger(__name__)

_BOOTSTRAP_CACHE_KEY = "timbri_runtime_bootstrap_v1"
_BOOTSTRAP_TTL_SECONDS = 300

_PULSANTI_DEFINITIONS = [
    {"modulo": "timbri", "codice": "timbri_home", "label": "Timbri - Elenco", "url": "/timbri/", "hide": False},
    {"modulo": "timbri", "codice": "timbri_view", "label": "Timbri - Scheda operatore", "url": "/timbri/operatori", "hide": True},
    {"modulo": "timbri", "codice": "timbri_edit", "label": "Timbri - Modifica", "url": "/timbri/record", "hide": True},
    {"modulo": "timbri", "codice": "timbri_config", "label": "Timbri - Configurazione", "url": "/timbri/configurazione", "hide": True},
    {"modulo": "timbri", "codice": "timbri_import", "label": "Timbri - Import SharePoint", "url": "/timbri/configurazione/import", "hide": True},
    {"modulo": "timbri", "codice": "timbri_export", "label": "Timbri - Export CSV", "url": "/timbri/export-csv", "hide": True},
]

_VISIBLE_ROLE_NAMES = {"admin", "amministrazione", "caporeparto", "hr"}
_EDIT_ROLE_NAMES = {"admin", "amministrazione"}
_TOPBAR_ALLOWED_ROLE_NAMES = {"admin", "amministrazione", "caporeparto", "hr"}


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


def _hide_pulsante(pulsante_id: int, section: str) -> None:
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
                    [pulsante_id, "hidden", section, None, 0, 1],
                )
            else:
                cursor.execute(
                    """
                    MERGE ui_pulsanti_meta AS target
                    USING (SELECT %s AS pulsante_id) AS src
                    ON target.pulsante_id = src.pulsante_id
                    WHEN MATCHED THEN UPDATE SET
                        ui_slot=%s, ui_section=%s, visible_topbar=%s, enabled=%s,
                        updated_at=SYSUTCDATETIME()
                    WHEN NOT MATCHED THEN INSERT
                        (pulsante_id, ui_slot, ui_section, ui_order, visible_topbar, enabled, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, SYSUTCDATETIME());
                    """,
                    [pulsante_id, "hidden", section, 0, 1, pulsante_id, "hidden", section, None, 0, 1],
                )
    except Exception:
        return


def _upsert_pulsante(modulo: str, codice: str, label: str, url: str) -> tuple[int | None, bool]:
    changed = False
    row = None
    try:
        row = Pulsante.objects.filter(url__iexact=url).order_by("-id").first()
        if row is None:
            row = Pulsante.objects.filter(modulo__iexact=modulo, codice__iexact=codice).order_by("-id").first()
    except DatabaseError:
        return None, False

    if row is None:
        try:
            row = Pulsante.objects.create(
                modulo=modulo,
                codice=codice,
                nome_visibile=label,
                url=url,
                icona="tag",
            )
            return int(row.id), True
        except DatabaseError:
            return None, False

    updates = []
    if (row.modulo or "").strip() != modulo:
        row.modulo = modulo
        updates.append("modulo")
    if (row.codice or "").strip() != codice:
        row.codice = codice
        updates.append("codice")
    if (row.nome_visibile or "").strip() != label:
        row.nome_visibile = label
        updates.append("nome_visibile")
    if (row.url or "").strip() != url:
        row.url = url
        updates.append("url")
    if not row.icona:
        row.icona = "tag"
        updates.append("icona")
    if updates:
        try:
            row.save(update_fields=updates)
            changed = True
        except DatabaseError:
            return None, False
    return int(row.id), changed


def _upsert_permesso(*, ruolo_id: int, modulo: str, azione: str, can_view: bool, can_edit: bool, can_delete: bool, can_approve: bool) -> bool:
    row = (
        Permesso.objects.filter(ruolo_id=ruolo_id, modulo__iexact=modulo, azione__iexact=azione)
        .order_by("-id")
        .first()
    )
    fields = {
        "consentito": 1 if can_view else 0,
        "can_view": 1 if can_view else 0,
        "can_edit": 1 if can_edit else 0,
        "can_delete": 1 if can_delete else 0,
        "can_approve": 1 if can_approve else 0,
    }
    if row is None:
        Permesso.objects.create(ruolo_id=ruolo_id, modulo=modulo, azione=azione, **fields)
        return True
    updates = []
    for field, value in fields.items():
        if getattr(row, field, None) != value:
            setattr(row, field, value)
            updates.append(field)
    if updates:
        row.save(update_fields=updates)
        return True
    return False


def _bootstrap_navigation() -> bool:
    try:
        from core.models import NavigationItem, NavigationRoleAccess
        from core.navigation_registry import bump_navigation_registry_version
    except Exception:
        return False

    changed = False
    item, created = NavigationItem.objects.get_or_create(
        code="timbri",
        defaults={
            "label": "Timbri",
            "section": "topbar",
            "route_name": "timbri:index",
            "order": 58,
            "is_visible": True,
            "is_enabled": True,
            "description": "Registro timbri e firme",
        },
    )
    if created:
        changed = True
    else:
        updates = []
        if item.label != "Timbri":
            item.label = "Timbri"
            updates.append("label")
        if item.section != "topbar":
            item.section = "topbar"
            updates.append("section")
        if item.route_name != "timbri:index":
            item.route_name = "timbri:index"
            updates.append("route_name")
        if int(item.order or 0) != 58:
            item.order = 58
            updates.append("order")
        if not item.is_visible:
            item.is_visible = True
            updates.append("is_visible")
        if not item.is_enabled:
            item.is_enabled = True
            updates.append("is_enabled")
        if updates:
            item.save(update_fields=updates)
            changed = True

    allowed_roles = {
        int(role.id)
        for role in Ruolo.objects.filter(nome__in=["admin", "amministrazione", "caporeparto", "HR"])
    }
    existing = {int(x.legacy_role_id): x for x in NavigationRoleAccess.objects.filter(item=item)}
    for role_id in allowed_roles:
        row = existing.get(role_id)
        if row is None:
            NavigationRoleAccess.objects.create(item=item, legacy_role_id=role_id, can_view=True)
            changed = True
        elif not row.can_view:
            row.can_view = True
            row.save(update_fields=["can_view"])
            changed = True
    for role_id, row in existing.items():
        if role_id not in allowed_roles:
            row.delete()
            changed = True

    if changed:
        try:
            bump_navigation_registry_version()
        except Exception:
            pass
    return changed


def bootstrap_timbri_runtime(force: bool = False) -> None:
    if not force and cache.get(_BOOTSTRAP_CACHE_KEY):
        return

    changed = False
    try:
        with transaction.atomic():
            created_ids: list[tuple[int, bool]] = []
            for item in _PULSANTI_DEFINITIONS:
                pulsante_id, item_changed = _upsert_pulsante(
                    modulo=item["modulo"],
                    codice=item["codice"],
                    label=item["label"],
                    url=item["url"],
                )
                if pulsante_id:
                    created_ids.append((pulsante_id, bool(item["hide"])))
                changed = changed or item_changed

            role_map = {
                str(role.nome or "").strip().lower(): int(role.id)
                for role in Ruolo.objects.filter(nome__in=["admin", "amministrazione", "caporeparto", "HR"])
            }
            for role_name, role_id in role_map.items():
                can_edit = role_name in _EDIT_ROLE_NAMES
                for action in ["timbri_home", "timbri_view"]:
                    changed = _upsert_permesso(
                        ruolo_id=role_id,
                        modulo="timbri",
                        azione=action,
                        can_view=True,
                        can_edit=can_edit,
                        can_delete=False,
                        can_approve=False,
                    ) or changed
                for action in ["timbri_edit", "timbri_config", "timbri_import", "timbri_export"]:
                    changed = _upsert_permesso(
                        ruolo_id=role_id,
                        modulo="timbri",
                        azione=action,
                        can_view=can_edit,
                        can_edit=can_edit,
                        can_delete=False,
                        can_approve=False,
                    ) or changed

            changed = _bootstrap_navigation() or changed
    except Exception as exc:
        logger.debug("ACL bootstrap timbri skipped: %s", exc)
        return

    for pulsante_id, hide in created_ids:
        if hide:
            _hide_pulsante(pulsante_id, "timbri_hidden")

    if changed:
        try:
            bump_legacy_cache_version()
        except Exception:
            pass
    cache.set(_BOOTSTRAP_CACHE_KEY, True, timeout=_BOOTSTRAP_TTL_SECONDS)
