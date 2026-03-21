"""
core/acl_bootstrap_base.py
==========================
Libreria condivisa per il bootstrap ACL delle app del portale.

Ogni app espone un `acl_bootstrap.py` con sola la lista `_PULSANTI_DEFINITIONS`
e una chiamata a `run_bootstrap()`. Tutta la logica di upsert, ui_meta e
inizializzazione permessi è centralizzata qui.

Pattern definizioni pulsante
-----------------------------
Campi obbligatori: modulo, codice, label, url
Campi visibilità (uno dei due):
  - "hide": True/False       → True = nascosto (visible_topbar=False)
  - "visible_topbar": bool   → controlla topbar, abbinato a "ui_order": int|None
Se nessuno dei due è presente il pulsante resta visibile per default (nessuna
scrittura su ui_pulsanti_meta).
Campo opzionale: "icona" (override per-pulsante sull'icona default dell'app)
"""
from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import DatabaseError, connections, transaction

from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Pulsante

logger = logging.getLogger(__name__)

_BOOTSTRAP_TTL_SECONDS = 300


# ---------------------------------------------------------------------------
# Primitive di base (esportate — usate anche da bootstrap complessi)
# ---------------------------------------------------------------------------

def upsert_pulsante(
    modulo: str,
    codice: str,
    label: str,
    url: str,
    *,
    icona: str = "tool",
) -> tuple[int | None, bool]:
    """Crea o aggiorna un pulsante nella tabella legacy `pulsanti`.

    Restituisce (pulsante_id, changed).
    Aggiorna modulo, codice, nome_visibile, url se differenti dall'esistente.
    """
    changed = False
    pulsante = None
    try:
        pulsante = Pulsante.objects.filter(url__iexact=url).order_by("-id").first()
        if pulsante is None:
            pulsante = (
                Pulsante.objects.filter(modulo__iexact=modulo, codice__iexact=codice)
                .order_by("-id")
                .first()
            )
    except DatabaseError:
        return None, False

    if pulsante is None:
        try:
            pulsante = Pulsante.objects.create(
                codice=codice,
                nome_visibile=label,
                modulo=modulo,
                url=url,
                icona=icona,
            )
            changed = True
        except DatabaseError:
            return None, False
    else:
        updates: list[str] = []
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


def ensure_ui_meta_table() -> None:
    """Crea la tabella ui_pulsanti_meta se non esiste (SQLite e SQL Server)."""
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
        pass


def set_ui_meta(
    pulsante_id: int,
    *,
    section: str,
    visible_topbar: bool = True,
    ui_order: int | None = None,
) -> None:
    """Scrive (o aggiorna) il record ui_pulsanti_meta per un pulsante."""
    ensure_ui_meta_table()
    slot = "topbar" if visible_topbar else "hidden"
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
                        ui_slot=%s, ui_section=%s, ui_order=%s,
                        visible_topbar=%s, enabled=%s, updated_at=SYSUTCDATETIME()
                    WHEN NOT MATCHED THEN INSERT
                        (pulsante_id, ui_slot, ui_section, ui_order, visible_topbar, enabled, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, SYSUTCDATETIME());
                    """,
                    [
                        pulsante_id, slot, section, ui_order, visible_value, 1,
                        pulsante_id, slot, section, ui_order, visible_value, 1,
                    ],
                )
    except Exception:
        pass


def init_missing_permessi(modulo: str, azione: str) -> int:
    """Per ogni ruolo che non ha ancora un record Permesso per (modulo, azione),
    crea un record con tutti i flag a 0 (deny-by-default).

    Non modifica mai i record già esistenti.
    Restituisce il numero di record creati.
    """
    try:
        from core.legacy_models import Permesso, Ruolo

        existing_role_ids: set[int] = set(
            Permesso.objects.filter(
                modulo__iexact=modulo, azione__iexact=azione
            ).values_list("ruolo_id", flat=True)
        )
        all_role_ids: set[int] = {int(r.id) for r in Ruolo.objects.all()}
        missing = all_role_ids - existing_role_ids

        created = 0
        for role_id in missing:
            Permesso.objects.create(
                ruolo_id=role_id,
                modulo=modulo,
                azione=azione,
                consentito=0,
                can_view=0,
                can_edit=0,
                can_delete=0,
                can_approve=0,
            )
            created += 1
        return created
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Orchestratore principale
# ---------------------------------------------------------------------------

def run_bootstrap(
    definitions: list[dict],
    cache_key: str,
    app_name: str,
    *,
    icona: str = "tool",
    section: str | None = None,
    force: bool = False,
    init_permessi: bool = True,
    bootstrap_nav_fn=None,
) -> None:
    """Esegue il bootstrap ACL per una app.

    Per ogni definizione in `definitions`:
    - crea/aggiorna il pulsante nella tabella legacy
    - scrive ui_pulsanti_meta se necessario (campo hide o visible_topbar)
    - se init_permessi=True, crea i record Permesso mancanti (can_view=0)

    Parametri
    ---------
    definitions     Lista di dict con i campi: modulo, codice, label, url,
                    [hide | (visible_topbar + ui_order)], [icona]
    cache_key       Chiave cache Django per evitare ri-esecuzione frequente
    app_name        Nome app (usato per il log di debug)
    icona           Icona di default per nuovi pulsanti
    section         Sezione ui_pulsanti_meta (default: "{app_name}_api")
    force           Se True ignora la cache e riesegue sempre
    init_permessi   Se True crea record Permesso(can_view=0) per ruoli mancanti
    bootstrap_nav_fn Callable opzionale per inizializzare il NavigationRegistry
    """
    if not force and cache.get(cache_key):
        return

    _section = section or f"{app_name}_api"
    changed = False

    try:
        with transaction.atomic():
            for defn in definitions:
                modulo = defn["modulo"]
                codice = defn["codice"]
                label = defn["label"]
                url = defn["url"]
                per_icona = defn.get("icona", icona)

                pid, item_changed = upsert_pulsante(
                    modulo, codice, label, url, icona=per_icona
                )
                changed = changed or item_changed

                if pid is None:
                    continue

                # Determina se e come scrivere ui_pulsanti_meta
                if "visible_topbar" in defn:
                    set_ui_meta(
                        pid,
                        section=_section,
                        visible_topbar=bool(defn["visible_topbar"]),
                        ui_order=defn.get("ui_order"),
                    )
                elif defn.get("hide"):
                    set_ui_meta(pid, section=_section, visible_topbar=False)

                # Crea record Permesso mancanti per tutti i ruoli
                if init_permessi:
                    try:
                        init_missing_permessi(modulo, codice)
                    except Exception:
                        pass

    except Exception as exc:
        logger.debug("ACL bootstrap %s skipped: %s", app_name, exc)
        return

    if bootstrap_nav_fn is not None:
        try:
            nav_changed = bootstrap_nav_fn()
            changed = changed or bool(nav_changed)
        except Exception as exc:
            logger.debug("Navigation bootstrap %s skipped: %s", app_name, exc)

    if changed:
        try:
            bump_legacy_cache_version()
        except Exception:
            pass

    cache.set(cache_key, True, timeout=_BOOTSTRAP_TTL_SECONDS)
