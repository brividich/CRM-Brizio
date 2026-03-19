from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import DatabaseError, transaction

from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Pulsante

logger = logging.getLogger(__name__)

_BOOTSTRAP_CACHE_KEY = "anomalie_acl_bootstrap_v1"
_BOOTSTRAP_TTL_SECONDS = 300

_PULSANTI_DEFINITIONS = [
    {"modulo": "anomalie", "codice": "anomalie_gestione", "label": "Anomalie - Gestione", "url": "/gestione-anomalie", "hide": False},
    {"modulo": "anomalie", "codice": "anomalie_nuova", "label": "Anomalie - Nuova segnalazione", "url": "/gestione-anomalie/nuova-segnalazione", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_configurazione", "label": "Anomalie - Configurazione", "url": "/gestione-anomalie/configurazione", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_statistiche", "label": "Anomalie - Statistiche", "url": "/gestione-anomalie/statistiche", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_ordini", "label": "Anomalie - API ordini", "url": "/api/anomalie/ordini", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_anomalie", "label": "Anomalie - API anomalie", "url": "/api/anomalie/anomalie", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_salva", "label": "Anomalie - API salva", "url": "/api/anomalie/salva", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_sync", "label": "Anomalie - API sync", "url": "/api/anomalie/sync", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_campi", "label": "Anomalie - API campi", "url": "/api/anomalie/campi", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_allegati", "label": "Anomalie - API allegati", "url": "/api/anomalie/allegati", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_statistiche", "label": "Anomalie - API statistiche", "url": "/api/anomalie/statistiche", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_report", "label": "Anomalie - API report", "url": "/api/anomalie/report", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_export_csv", "label": "Anomalie - Export CSV", "url": "/export-csv", "hide": True},
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
                codice=codice, nome_visibile=label, modulo=modulo, url=url, icona="alert-triangle"
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


def bootstrap_anomalie_acl_endpoints(force: bool = False) -> None:
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
                    _hide_pulsante(pid, "anomalie_api")
                changed = changed or item_changed
    except Exception as exc:
        logger.debug("ACL bootstrap anomalie skipped: %s", exc)
        return

    if changed:
        try:
            bump_legacy_cache_version()
        except Exception:
            pass

    cache.set(_BOOTSTRAP_CACHE_KEY, True, timeout=_BOOTSTRAP_TTL_SECONDS)
