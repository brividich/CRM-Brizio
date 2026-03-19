from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import DatabaseError, transaction

from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Pulsante

logger = logging.getLogger(__name__)

_BOOTSTRAP_CACHE_KEY = "assets_acl_bootstrap_v1"
_BOOTSTRAP_TTL_SECONDS = 300

_PULSANTI_DEFINITIONS = [
    {"modulo": "assets", "codice": "assets_list", "label": "Assets - Lista asset", "url": "/assets/", "hide": False},
    {"modulo": "assets", "codice": "assets_new", "label": "Assets - Nuovo asset", "url": "/assets/new/", "hide": True},
    {"modulo": "assets", "codice": "assets_view", "label": "Assets - Dettaglio asset", "url": "/assets/view/", "hide": True},
    {"modulo": "assets", "codice": "assets_edit", "label": "Assets - Modifica asset", "url": "/assets/edit/", "hide": True},
    {"modulo": "assets", "codice": "assets_components", "label": "Assets - Componenti", "url": "/assets/componenti/", "hide": True},
    {
        "modulo": "assets",
        "codice": "assets_components_new",
        "label": "Assets - Nuovo componente",
        "url": "/assets/componenti/new/",
        "hide": True,
    },
    {
        "modulo": "assets",
        "codice": "assets_components_edit",
        "label": "Assets - Modifica componente",
        "url": "/assets/componenti/edit/",
        "hide": True,
    },
    {
        "modulo": "assets",
        "codice": "assets_deadlines",
        "label": "Assets - Scadenze amministrative",
        "url": "/assets/scadenze/",
        "hide": True,
    },
    {
        "modulo": "assets",
        "codice": "assets_deadlines_new",
        "label": "Assets - Nuova scadenza amministrativa",
        "url": "/assets/scadenze/new/",
        "hide": True,
    },
    {
        "modulo": "assets",
        "codice": "assets_deadlines_edit",
        "label": "Assets - Modifica scadenza amministrativa",
        "url": "/assets/scadenze/edit/",
        "hide": True,
    },
    {
        "modulo": "assets",
        "codice": "assets_maintenance_templates",
        "label": "Assets - Template manutenzione",
        "url": "/assets/manutenzione/templates/",
        "hide": True,
    },
    {
        "modulo": "assets",
        "codice": "assets_maintenance_templates_new",
        "label": "Assets - Nuovo template manutenzione",
        "url": "/assets/manutenzione/templates/new/",
        "hide": True,
    },
    {
        "modulo": "assets",
        "codice": "assets_maintenance_templates_edit",
        "label": "Assets - Modifica template manutenzione",
        "url": "/assets/manutenzione/templates/edit/",
        "hide": True,
    },
    {
        "modulo": "assets",
        "codice": "assets_maintenance_rules",
        "label": "Assets - Regole manutenzione",
        "url": "/assets/manutenzione/regole/",
        "hide": True,
    },
    {
        "modulo": "assets",
        "codice": "assets_maintenance_rules_new",
        "label": "Assets - Nuova regola manutenzione",
        "url": "/assets/manutenzione/regole/new/",
        "hide": True,
    },
    {
        "modulo": "assets",
        "codice": "assets_maintenance_rules_edit",
        "label": "Assets - Modifica regola manutenzione",
        "url": "/assets/manutenzione/regole/edit/",
        "hide": True,
    },
    {
        "modulo": "assets",
        "codice": "assets_maintenance_schedule",
        "label": "Assets - Prossime manutenzioni",
        "url": "/assets/manutenzione/prossime/",
        "hide": True,
    },
    {
        "modulo": "assets",
        "codice": "assets_assistance_contracts",
        "label": "Assets - Contratti assistenza",
        "url": "/assets/manutenzione/contratti/",
        "hide": True,
    },
    {
        "modulo": "assets",
        "codice": "assets_asset_maintenance_rules",
        "label": "Assets - Regole manutenzione asset",
        "url": "/assets/manutenzione/asset-rules/",
        "hide": True,
    },
    {
        "modulo": "assets",
        "codice": "assets_asset_maintenance_overrides_new",
        "label": "Assets - Nuovo override regola asset",
        "url": "/assets/manutenzione/asset-rule-overrides/new/",
        "hide": True,
    },
    {
        "modulo": "assets",
        "codice": "assets_asset_maintenance_overrides_edit",
        "label": "Assets - Modifica override regola asset",
        "url": "/assets/manutenzione/asset-rule-overrides/edit/",
        "hide": True,
    },
    {
        "modulo": "assets",
        "codice": "assets_asset_maintenance_overrides_reset",
        "label": "Assets - Ripristino override regola asset",
        "url": "/assets/manutenzione/asset-rule-overrides/reset/",
        "hide": True,
    },
    {"modulo": "assets", "codice": "assets_work_machines", "label": "Assets - Lista macchinari", "url": "/assets/work-machines/", "hide": False},
    {"modulo": "assets", "codice": "assets_wm_dashboard", "label": "Assets - Dashboard macchinari", "url": "/assets/work-machines/dashboard/", "hide": True},
    {"modulo": "assets", "codice": "assets_wm_map", "label": "Assets - Mappa planimetrica", "url": "/assets/work-machines/map/", "hide": True},
    {"modulo": "assets", "codice": "assets_workorders", "label": "Assets - Work orders", "url": "/assets/workorders/", "hide": False},
    {"modulo": "assets", "codice": "assets_wo_new", "label": "Assets - Nuovo work order", "url": "/assets/workorders/new/", "hide": True},
    {"modulo": "assets", "codice": "assets_verifiche", "label": "Assets - Verifiche periodiche", "url": "/assets/verifiche-periodiche/", "hide": False},
    {"modulo": "assets", "codice": "assets_reports", "label": "Assets - Reports", "url": "/assets/reports/", "hide": True},
    {"modulo": "assets", "codice": "assets_gestione", "label": "Assets - Gestione admin", "url": "/assets/gestione/", "hide": True},
    {"modulo": "assets", "codice": "assets_labels", "label": "Assets - Label designer", "url": "/assets/labels/", "hide": True},
    {"modulo": "assets", "codice": "assets_bulk_update", "label": "Assets - Bulk update", "url": "/assets/bulk-update/", "hide": True},
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
                codice=codice, nome_visibile=label, modulo=modulo, url=url, icona="tool"
            )
            changed = True
        except DatabaseError:
            return None, False
    else:
        updates = []
        if (pulsante.modulo or "").strip() != modulo:
            pulsante.modulo = modulo
            updates.append("modulo")
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


def _hide_pulsante(pulsante_id: int, section: str) -> None:
    _ensure_ui_meta_table()
    from django.db import connections

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
                        ui_slot=excluded.ui_slot, ui_section=excluded.ui_section,
                        visible_topbar=excluded.visible_topbar, updated_at=CURRENT_TIMESTAMP
                    """,
                    [pulsante_id, "hidden", section, None, 0, 1],
                )
            else:
                cursor.execute(
                    """
                    MERGE ui_pulsanti_meta AS target
                    USING (SELECT %s AS pulsante_id) AS src ON target.pulsante_id = src.pulsante_id
                    WHEN MATCHED THEN UPDATE SET
                        ui_slot=%s, ui_section=%s, visible_topbar=%s, enabled=%s,
                        updated_at=SYSUTCDATETIME()
                    WHEN NOT MATCHED THEN INSERT
                        (pulsante_id, ui_slot, ui_section, ui_order, visible_topbar, enabled, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, SYSUTCDATETIME());
                    """,
                    [pulsante_id, "hidden", section, 0, 1,
                     pulsante_id, "hidden", section, None, 0, 1],
                )
    except Exception:
        pass


def bootstrap_assets_acl_endpoints(force: bool = False) -> None:
    if not force and cache.get(_BOOTSTRAP_CACHE_KEY):
        return

    changed = False
    try:
        with transaction.atomic():
            for defn in _PULSANTI_DEFINITIONS:
                pid, item_changed = _upsert_pulsante(
                    modulo=defn["modulo"],
                    codice=defn["codice"],
                    label=defn["label"],
                    url=defn["url"],
                )
                if pid and defn.get("hide"):
                    _hide_pulsante(pid, "assets_api")
                changed = changed or item_changed
    except Exception as exc:
        logger.debug("ACL bootstrap assets skipped: %s", exc)
        return

    if changed:
        try:
            bump_legacy_cache_version()
        except Exception:
            pass

    cache.set(_BOOTSTRAP_CACHE_KEY, True, timeout=_BOOTSTRAP_TTL_SECONDS)
