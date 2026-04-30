from __future__ import annotations

import logging

from django.db import DatabaseError, transaction

from core.acl_bootstrap_base import run_bootstrap

logger = logging.getLogger(__name__)

_BOOTSTRAP_CACHE_KEY = "attrezzature_acl_bootstrap_v2"

MODULE = "attrezzature"

LEGACY_PERMISSIONS = {
    "attrezzature_view": "Gestione Attrezzatura - Accesso modulo",
    "attrezzature_add": "Gestione Attrezzatura - Crea attrezzature",
    "attrezzature_change": "Gestione Attrezzatura - Modifica attrezzature",
    "attrezzature_delete": "Gestione Attrezzatura - Elimina attrezzature",
    "attrezzature_import": "Gestione Attrezzatura - Import Excel",
    "attrezzature_export": "Gestione Attrezzatura - Export",
    "attrezzature_task_view": "Gestione Attrezzatura - Vede task operativi",
    "attrezzature_task_manage": "Gestione Attrezzatura - Gestisce task operativi",
    "attrezzature_link_kickoff": "Gestione Attrezzatura - Collegamento KICK-OFF",
    "attrezzature_confirm_ready_production": "Gestione Attrezzatura - Conferma pronta produzione",
}

CANONICAL_PERMISSION_MAP = {
    "attrezzature_view": "attrezzature.attrezzature.view",
    "attrezzature_add": "attrezzature.attrezzature.create",
    "attrezzature_change": "attrezzature.attrezzature.edit",
    "attrezzature_delete": "attrezzature.attrezzature.delete",
    "attrezzature_import": "attrezzature.import.import",
    "attrezzature_export": "attrezzature.attrezzature.export",
    "attrezzature_task_view": "attrezzature.tasks.view",
    "attrezzature_task_manage": "attrezzature.tasks.manage",
    "attrezzature_link_kickoff": "attrezzature.kickoff.link",
    "attrezzature_confirm_ready_production": "attrezzature.attrezzature.confirm",
}

_PULSANTI_DEFINITIONS = [
    {
        "modulo": MODULE,
        "codice": "attrezzature_view",
        "label": LEGACY_PERMISSIONS["attrezzature_view"],
        "url": "/attrezzature/",
        "visible_topbar": True,
        "ui_order": 55,
    },
    {
        "modulo": MODULE,
        "codice": "attrezzature_add",
        "label": LEGACY_PERMISSIONS["attrezzature_add"],
        "url": "/attrezzature/nuova/",
        "hide": True,
    },
    {
        "modulo": MODULE,
        "codice": "attrezzature_change",
        "label": LEGACY_PERMISSIONS["attrezzature_change"],
        "url": "/attrezzature/modifica/",
        "hide": True,
    },
    {
        "modulo": MODULE,
        "codice": "attrezzature_delete",
        "label": LEGACY_PERMISSIONS["attrezzature_delete"],
        "url": "/attrezzature/elimina/",
        "hide": True,
    },
    {
        "modulo": MODULE,
        "codice": "attrezzature_import",
        "label": LEGACY_PERMISSIONS["attrezzature_import"],
        "url": "/attrezzature/import/",
        "hide": True,
    },
    {
        "modulo": MODULE,
        "codice": "attrezzature_export",
        "label": LEGACY_PERMISSIONS["attrezzature_export"],
        "url": "/attrezzature/export/",
        "hide": True,
    },
    {
        "modulo": MODULE,
        "codice": "attrezzature_task_view",
        "label": LEGACY_PERMISSIONS["attrezzature_task_view"],
        "url": "/attrezzature/tasks/",
        "hide": True,
    },
    {
        "modulo": MODULE,
        "codice": "attrezzature_task_manage",
        "label": LEGACY_PERMISSIONS["attrezzature_task_manage"],
        "url": "/attrezzature/tasks/nuova/",
        "hide": True,
    },
    {
        "modulo": MODULE,
        "codice": "attrezzature_link_kickoff",
        "label": LEGACY_PERMISSIONS["attrezzature_link_kickoff"],
        "url": "/tasks/attrezzature/action/",
        "hide": True,
    },
    {
        "modulo": MODULE,
        "codice": "attrezzature_confirm_ready_production",
        "label": LEGACY_PERMISSIONS["attrezzature_confirm_ready_production"],
        "url": "/attrezzature/conferma-pronta-produzione/",
        "hide": True,
    },
]

_CANONICAL_PERMISSION_DEFINITIONS = {
    "attrezzature.attrezzature.view": {
        "label": "Gestione Attrezzatura - Vede attrezzature",
        "description": "Accesso in lettura a lista, dettaglio e pannello embedded.",
    },
    "attrezzature.attrezzature.create": {
        "label": "Gestione Attrezzatura - Crea attrezzature",
        "description": "Creazione manuale o bozza attrezzatura.",
    },
    "attrezzature.attrezzature.edit": {
        "label": "Gestione Attrezzatura - Modifica attrezzature",
        "description": "Modifica schede, avanzamento e disponibilita.",
    },
    "attrezzature.attrezzature.delete": {
        "label": "Gestione Attrezzatura - Elimina attrezzature",
        "description": "Eliminazione singola o multipla riservata agli amministratori.",
    },
    "attrezzature.attrezzature.confirm": {
        "label": "Gestione Attrezzatura - Conferma pronta produzione",
        "description": "Conferma pronta produzione e aggiorna readiness.",
    },
    "attrezzature.attrezzature.export": {
        "label": "Gestione Attrezzatura - Export",
        "description": "Permesso predisposto per export futuri.",
    },
    "attrezzature.import.import": {
        "label": "Gestione Attrezzatura - Import Excel",
        "description": "Preview e conferma import legacy Excel.",
    },
    "attrezzature.tasks.view": {
        "label": "Gestione Attrezzatura - Vede task",
        "description": "Accesso in lettura ai task operativi attrezzatura.",
    },
    "attrezzature.tasks.manage": {
        "label": "Gestione Attrezzatura - Gestisce task",
        "description": "Creazione, completamento e blocco task operativi.",
    },
    "attrezzature.kickoff.link": {
        "label": "Gestione Attrezzatura - Collega KICK-OFF",
        "description": "Azioni embedded dal dettaglio Activity KICK-OFF.",
    },
}

_ROUTE_BINDINGS = {
    "attrezzature:list": "attrezzature.attrezzature.view",
    "attrezzature:detail": "attrezzature.attrezzature.view",
    "attrezzature:embedded_preview": "attrezzature.attrezzature.view",
    "attrezzature:create": "attrezzature.attrezzature.create",
    "attrezzature:edit": "attrezzature.attrezzature.edit",
    "attrezzature:delete": "attrezzature.attrezzature.delete",
    "attrezzature:bulk_delete": "attrezzature.attrezzature.delete",
    "attrezzature:update_progress": "attrezzature.attrezzature.edit",
    "attrezzature:confirm_ready": "attrezzature.attrezzature.confirm",
    "attrezzature:import": "attrezzature.import.import",
    "attrezzature:import_preview": "attrezzature.import.import",
    "attrezzature:import_confirm": "attrezzature.import.import",
    "attrezzature:task_list": "attrezzature.tasks.view",
    "attrezzature:task_detail": "attrezzature.tasks.view",
    "attrezzature:task_create": "attrezzature.tasks.manage",
    "attrezzature:task_complete": "attrezzature.tasks.manage",
    "attrezzature:task_block": "attrezzature.tasks.manage",
    "tasks:attrezzature_action": "attrezzature.kickoff.link",
}

_ROLE_GRANTS = {
    "admin": set(CANONICAL_PERMISSION_MAP.values()),
    "amministrazione": set(CANONICAL_PERMISSION_MAP.values()),
    "caporeparto": {
        "attrezzature.attrezzature.view",
        "attrezzature.attrezzature.create",
        "attrezzature.attrezzature.edit",
        "attrezzature.attrezzature.confirm",
        "attrezzature.tasks.view",
        "attrezzature.tasks.manage",
        "attrezzature.kickoff.link",
    },
    "qualita": {
        "attrezzature.attrezzature.view",
        "attrezzature.attrezzature.edit",
        "attrezzature.attrezzature.confirm",
        "attrezzature.tasks.view",
        "attrezzature.tasks.manage",
        "attrezzature.kickoff.link",
    },
}


def _normalize_role_name(value: str) -> str:
    return str(value or "").strip().lower()


def _upsert_legacy_permission(*, role_id: int, action: str, enabled: bool) -> bool:
    from core.legacy_models import Permesso

    defaults = {
        "consentito": 1 if enabled else 0,
        "can_view": 1 if enabled else 0,
        "can_edit": 1 if enabled else 0,
        "can_delete": 0,
        "can_approve": 0,
    }
    row = (
        Permesso.objects.filter(ruolo_id=role_id, modulo__iexact=MODULE, azione__iexact=action)
        .order_by("-id")
        .first()
    )
    if row is None:
        Permesso.objects.create(ruolo_id=role_id, modulo=MODULE, azione=action, **defaults)
        return True

    updates = []
    for field, value in defaults.items():
        if getattr(row, field, None) != value:
            setattr(row, field, value)
            updates.append(field)
    if updates:
        row.save(update_fields=updates)
        return True
    return False


def _bootstrap_canonical_acl(*, seed_role_grants: bool = False) -> bool:
    from core.legacy_models import Ruolo
    from core.models import (
        NavigationItem,
        NavigationRoleAccess,
        PermissionDefinition,
        RolePermissionGrant,
        RoutePermissionBinding,
    )
    from core.navigation_registry import bump_navigation_registry_version

    changed = False
    with transaction.atomic():
        for code, payload in _CANONICAL_PERMISSION_DEFINITIONS.items():
            permission, created = PermissionDefinition.objects.get_or_create(
                code=code,
                defaults={
                    "module": MODULE,
                    "label": payload["label"],
                    "description": payload["description"],
                    "is_active": True,
                },
            )
            changed = changed or created
            updates = []
            for field in ("module", "label", "description"):
                value = MODULE if field == "module" else payload[field]
                if getattr(permission, field) != value:
                    setattr(permission, field, value)
                    updates.append(field)
            if not permission.is_active:
                permission.is_active = True
                updates.append("is_active")
            if updates:
                permission.save(update_fields=[*updates, "updated_at"])
                changed = True

        for route_name, permission_code in _ROUTE_BINDINGS.items():
            binding, created = RoutePermissionBinding.objects.get_or_create(
                route_name=route_name,
                path_pattern="",
                defaults={
                    "match_strategy": RoutePermissionBinding.MATCH_EXACT,
                    "permission_id": permission_code,
                    "source_app": MODULE,
                    "note": "[ATTREZZATURE_BOOTSTRAP] binding Gestione Attrezzatura",
                    "priority": 80,
                    "is_active": True,
                },
            )
            changed = changed or created
            updates = []
            if binding.permission_id != permission_code:
                binding.permission_id = permission_code
                updates.append("permission")
            if binding.match_strategy != RoutePermissionBinding.MATCH_EXACT:
                binding.match_strategy = RoutePermissionBinding.MATCH_EXACT
                updates.append("match_strategy")
            if binding.source_app != MODULE:
                binding.source_app = MODULE
                updates.append("source_app")
            if int(binding.priority or 0) != 80:
                binding.priority = 80
                updates.append("priority")
            if not binding.is_active:
                binding.is_active = True
                updates.append("is_active")
            if updates:
                binding.save(update_fields=[*updates, "updated_at"])
                changed = True

        nav_item, created = NavigationItem.objects.update_or_create(
            code="gestione-attrezzatura",
            defaults={
                "label": "Gestione Attrezzatura",
                "route_name": "attrezzature:list",
                "url_path": "",
                "section": "topbar",
                "required_permission_code": "attrezzature.attrezzature.view",
                "order": 55,
                "is_visible": True,
                "is_enabled": True,
                "icon": "wrench",
                "description": "Modulo operativo per avanzamento attrezzature e import Excel legacy.",
            },
        )
        changed = changed or created

        roles_by_id = {int(role.id): _normalize_role_name(role.nome) for role in Ruolo.objects.all()}
        enabled_view_role_ids = {
            role_id
            for role_id, role_name in roles_by_id.items()
            if "attrezzature.attrezzature.view" in _ROLE_GRANTS.get(role_name, set())
        }
        existing_nav_access = {
            int(row.legacy_role_id): row
            for row in NavigationRoleAccess.objects.filter(item=nav_item)
        }
        for role_id in enabled_view_role_ids:
            row = existing_nav_access.get(role_id)
            if row is None:
                NavigationRoleAccess.objects.create(item=nav_item, legacy_role_id=role_id, can_view=True)
                changed = True
            elif not row.can_view:
                row.can_view = True
                row.save(update_fields=["can_view"])
                changed = True

        if seed_role_grants:
            for role_id, role_name in roles_by_id.items():
                grants = _ROLE_GRANTS.get(role_name, set())
                for legacy_action, permission_code in CANONICAL_PERMISSION_MAP.items():
                    enabled = permission_code in grants
                    changed = _upsert_legacy_permission(role_id=role_id, action=legacy_action, enabled=enabled) or changed
                    grant, created = RolePermissionGrant.objects.get_or_create(
                        legacy_role_id=role_id,
                        permission_id=permission_code,
                        defaults={
                            "enabled": enabled,
                            "note": "[ATTREZZATURE_BOOTSTRAP] default accessi Gestione Attrezzatura",
                        },
                    )
                    changed = changed or created
                    if not created and bool(grant.enabled) != bool(enabled):
                        grant.enabled = bool(enabled)
                        grant.note = "[ATTREZZATURE_BOOTSTRAP] default accessi Gestione Attrezzatura"
                        grant.save(update_fields=["enabled", "note", "updated_at"])
                        changed = True

    if changed:
        try:
            bump_navigation_registry_version()
        except Exception:
            pass
    return changed


def bootstrap_attrezzature_acl_endpoints(*, force: bool = False, seed_role_grants: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        MODULE,
        icona="wrench",
        section="attrezzature",
        force=force,
        bootstrap_nav_fn=lambda: _bootstrap_canonical_acl(seed_role_grants=seed_role_grants),
    )
