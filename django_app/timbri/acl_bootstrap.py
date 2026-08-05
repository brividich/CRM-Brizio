from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import DatabaseError, transaction

from core.acl_bootstrap_base import set_ui_meta, should_skip_runtime_bootstrap, upsert_pulsante
from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Permesso, Ruolo

logger = logging.getLogger(__name__)

_BOOTSTRAP_CACHE_KEY = "timbri_runtime_bootstrap_v2"
_BOOTSTRAP_TTL_SECONDS = 300

_PULSANTI_DEFINITIONS = [
    {"modulo": "timbri", "codice": "timbri_home", "label": "Timbri - Elenco", "url": "/timbri/", "hide": False},
    {"modulo": "timbri", "codice": "timbri_view", "label": "Timbri - Scheda operatore", "url": "/timbri/operatori", "hide": True},
    {"modulo": "timbri", "codice": "timbri_edit", "label": "Timbri - Modifica", "url": "/timbri/record", "hide": True},
    {"modulo": "timbri", "codice": "timbri_config", "label": "Timbri - Impostazioni", "url": "/timbri/impostazioni/", "hide": True},
    {"modulo": "timbri", "codice": "timbri_export", "label": "Timbri - Export CSV", "url": "/timbri/export-csv", "hide": True},
    {"modulo": "timbri", "codice": "timbri_copy", "label": "Timbri - Copia immagine", "url": "/timbri/", "hide": True},
    {"modulo": "timbri", "codice": "timbri_download", "label": "Timbri - Scarica immagine", "url": "/timbri/immagine/", "hide": True},
]

_VISIBLE_ROLE_NAMES = {"admin", "amministrazione", "caporeparto", "hr"}
_EDIT_ROLE_NAMES = {"admin", "amministrazione"}
_COPY_ROLE_NAMES = {"admin", "amministrazione", "hr"}
_DOWNLOAD_ROLE_NAMES = {"admin", "amministrazione", "hr"}


def _upsert_permesso(
    *,
    ruolo_id: int,
    modulo: str,
    azione: str,
    can_view: bool,
    can_edit: bool,
    can_delete: bool,
    can_approve: bool,
) -> bool:
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
            # Senza il bump, i permessi sono cambiati ma il menu resta quello di
            # prima finche' la cache non scade da sola: sintomo classico di
            # "ho dato il permesso e non lo vede".
            logger.exception("Timbri: bump della versione del navigation registry fallito")
    return changed


def bootstrap_timbri_runtime(force: bool = False) -> None:
    if should_skip_runtime_bootstrap(force=force):
        logger.debug("ACL bootstrap timbri skipped for management command")
        return

    if not force and cache.get(_BOOTSTRAP_CACHE_KEY):
        return

    changed = False
    created_ids: list[tuple[int, bool]] = []

    try:
        with transaction.atomic():
            for item in _PULSANTI_DEFINITIONS:
                pid, item_changed = upsert_pulsante(
                    item["modulo"],
                    item["codice"],
                    item["label"],
                    item["url"],
                    icona="tag",
                )
                if pid:
                    created_ids.append((pid, bool(item["hide"])))
                changed = changed or item_changed

            role_map = {
                str(role.nome or "").strip().lower(): int(role.id)
                for role in Ruolo.objects.filter(nome__in=["admin", "amministrazione", "caporeparto", "HR"])
            }
            for role_name, role_id in role_map.items():
                can_edit = role_name in _EDIT_ROLE_NAMES
                can_copy = role_name in _COPY_ROLE_NAMES
                can_download = role_name in _DOWNLOAD_ROLE_NAMES
                for action in ["timbri_home", "timbri_view"]:
                    changed = _upsert_permesso(
                        ruolo_id=role_id, modulo="timbri", azione=action,
                        can_view=True, can_edit=can_edit, can_delete=False, can_approve=False,
                    ) or changed
                for action in ["timbri_edit", "timbri_config", "timbri_export"]:
                    changed = _upsert_permesso(
                        ruolo_id=role_id, modulo="timbri", azione=action,
                        can_view=can_edit, can_edit=can_edit, can_delete=False, can_approve=False,
                    ) or changed
                changed = _upsert_permesso(
                    ruolo_id=role_id, modulo="timbri", azione="timbri_copy",
                    can_view=can_copy, can_edit=can_copy, can_delete=False, can_approve=False,
                ) or changed
                changed = _upsert_permesso(
                    ruolo_id=role_id, modulo="timbri", azione="timbri_download",
                    can_view=can_download, can_edit=can_download, can_delete=False, can_approve=False,
                ) or changed

            changed = _bootstrap_navigation() or changed

    except Exception as exc:
        logger.debug("ACL bootstrap timbri skipped: %s", exc)
        return

    for pid, hide in created_ids:
        if hide:
            set_ui_meta(pid, section="timbri_hidden", visible_topbar=False)

    if changed:
        try:
            bump_legacy_cache_version()
        except Exception:
            pass

    cache.set(_BOOTSTRAP_CACHE_KEY, True, timeout=_BOOTSTRAP_TTL_SECONDS)
