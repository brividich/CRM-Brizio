from __future__ import annotations

import logging

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

logger = logging.getLogger(__name__)

_BOOTSTRAP_CACHE_KEY = "tasks_acl_bootstrap_v9"

MODULE = "tasks"

LEGACY_PERMISSIONS = {
    "tasks_view": "KICK-OFF - Visualizza attività",
    "tasks_create": "KICK-OFF - Crea attività e progetti",
    "tasks_edit": "KICK-OFF - Modifica attività",
    "tasks_comment": "KICK-OFF - Commenta e gestisce sottotask",
    "tasks_admin": "KICK-OFF - Gestione amministrativa",
    "tasks_projects": "KICK-OFF - Accesso progetti e VRF",
}

CANONICAL_PERMISSION_MAP = {
    "tasks_view": "tasks.kickoff.view",
    "tasks_create": "tasks.kickoff.create",
    "tasks_edit": "tasks.kickoff.edit",
    "tasks_comment": "tasks.kickoff.comment",
    "tasks_admin": "tasks.kickoff.admin",
    "tasks_projects": "tasks.kickoff.projects",
}

_PULSANTI_DEFINITIONS = [
    {
        "modulo": MODULE,
        "codice": "tasks_view",
        "label": LEGACY_PERMISSIONS["tasks_view"],
        "url": "/tasks/",
        "visible_topbar": True,
        "ui_order": 45,
    },
    {
        "modulo": MODULE,
        "codice": "tasks_create",
        "label": LEGACY_PERMISSIONS["tasks_create"],
        "url": "/tasks/new/",
        "hide": True,
    },
    {
        "modulo": MODULE,
        "codice": "tasks_edit",
        "label": LEGACY_PERMISSIONS["tasks_edit"],
        "url": "/tasks/edit/",
        "hide": True,
    },
    {
        "modulo": MODULE,
        "codice": "tasks_comment",
        "label": LEGACY_PERMISSIONS["tasks_comment"],
        "url": "/tasks/comment/",
        "hide": True,
    },
    {
        "modulo": MODULE,
        "codice": "tasks_admin",
        "label": LEGACY_PERMISSIONS["tasks_admin"],
        "url": "/tasks/admin/",
        "hide": True,
    },
    {
        "modulo": MODULE,
        "codice": "tasks_projects",
        "label": LEGACY_PERMISSIONS["tasks_projects"],
        "url": "/tasks/projects/",
        "hide": True,
    },
]

_CANONICAL_PERMISSION_DEFINITIONS = {
    "tasks.kickoff.view": {
        "label": "KICK-OFF - Visualizza attività",
        "description": "Accesso in lettura a lista attività, dettaglio, VRF e template Excel.",
    },
    "tasks.kickoff.create": {
        "label": "KICK-OFF - Crea attività e progetti",
        "description": "Creazione attività, sottotask, incontri e nuovi progetti KICK-OFF.",
    },
    "tasks.kickoff.edit": {
        "label": "KICK-OFF - Modifica attività",
        "description": "Modifica attività esistenti, aggiornamento date, cambio stato e Gantt.",
    },
    "tasks.kickoff.comment": {
        "label": "KICK-OFF - Commenta e gestisce sottotask",
        "description": "Aggiunta commenti, allegati, sottotask e punti agenda incontri.",
    },
    "tasks.kickoff.admin": {
        "label": "KICK-OFF - Gestione amministrativa",
        "description": "Pagine gestione e impostazioni, import Excel, copia progetti, eliminazione incontri.",
    },
    "tasks.kickoff.projects": {
        "label": "KICK-OFF - Accesso progetti e VRF",
        "description": "Lista progetti, Gantt, incontri, caricamento e compilazione VRF.",
    },
}

_ROUTE_BINDINGS = {
    # Lista e dettaglio attività
    "tasks:list": "tasks.kickoff.view",
    "tasks:da_gestire": "tasks.kickoff.view",
    "tasks:incontri_calendario": "tasks.kickoff.view",
    "tasks:incontri_lista": "tasks.kickoff.view",
    # Proporre un punto e' consentito ai convocati: la view verifica che
    # l'utente sia fra i partecipanti, il permesso resta quello di lettura.
    "tasks:project_meeting_proposal_create": "tasks.kickoff.view",
    "tasks:detail": "tasks.kickoff.view",
    "tasks:download_excel_template": "tasks.kickoff.view",
    "tasks:category_fields_json": "tasks.kickoff.view",
    "tasks:asset_availability_json": "tasks.kickoff.view",
    "tasks:identity_suggest": "tasks.kickoff.view",
    "tasks:project_vrf_download": "tasks.kickoff.view",
    # Creazione
    "tasks:create": "tasks.kickoff.create",
    "tasks:project_create": "tasks.kickoff.create",
    "tasks:project_meeting_create": "tasks.kickoff.create",
    "tasks:project_meeting_task_from_step": "tasks.kickoff.create",
    # Modifica attività e Gantt
    "tasks:edit": "tasks.kickoff.edit",
    "tasks:change_status": "tasks.kickoff.edit",
    "tasks:project_set_phase": "tasks.kickoff.edit",
    "tasks:update_due_date": "tasks.kickoff.edit",
    "tasks:project_gantt_update_task": "tasks.kickoff.edit",
    "tasks:project_gantt_shift_task": "tasks.kickoff.edit",
    "tasks:project_meeting_edit": "tasks.kickoff.edit",
    "tasks:project_meeting_minutes": "tasks.kickoff.edit",
    "tasks:project_meeting_run": "tasks.kickoff.edit",
    "tasks:project_meeting_send_invite": "tasks.kickoff.edit",
    "tasks:project_meeting_send_minute": "tasks.kickoff.edit",
    "tasks:project_meeting_minute_close": "tasks.kickoff.edit",
    "tasks:project_meeting_minute_reopen": "tasks.kickoff.edit",
    # Commenti, sottotask, allegati e agenda incontri
    "tasks:add_comment": "tasks.kickoff.comment",
    "tasks:add_subtask": "tasks.kickoff.comment",
    "tasks:add_attachment": "tasks.kickoff.comment",
    "tasks:edit_subtask_status": "tasks.kickoff.comment",
    "tasks:subtask_toggle": "tasks.kickoff.comment",
    "tasks:add_project_comment": "tasks.kickoff.comment",
    "tasks:project_meeting_issue_status": "tasks.kickoff.comment",
    "tasks:project_meeting_action_status": "tasks.kickoff.comment",
    "tasks:project_meeting_proposal_decide": "tasks.kickoff.comment",
    "tasks:project_meeting_agenda_toggle": "tasks.kickoff.comment",
    "tasks:project_meeting_agenda_item_update": "tasks.kickoff.comment",
    "tasks:project_meeting_quick_capture": "tasks.kickoff.comment",
    # Gestione amministrativa
    "tasks:gestione_admin": "tasks.kickoff.admin",
    "tasks:impostazioni": "tasks.kickoff.admin",
    "tasks:import_excel": "tasks.kickoff.admin",
    "tasks:copy_project_with_vrf": "tasks.kickoff.admin",
    "tasks:copy_project_with_vrf_without_pn": "tasks.kickoff.admin",
    "tasks:project_meeting_delete": "tasks.kickoff.admin",
    # Progetti, Gantt e VRF
    "tasks:project_list": "tasks.kickoff.projects",
    "tasks:project_overview": "tasks.kickoff.projects",
    "tasks:project_actions": "tasks.kickoff.projects",
    "tasks:project_gantt": "tasks.kickoff.projects",
    "tasks:project_info_json": "tasks.kickoff.projects",
    "tasks:project_meetings": "tasks.kickoff.projects",
    "tasks:project_decisions": "tasks.kickoff.projects",
    "tasks:project_meeting_detail": "tasks.kickoff.projects",
    "tasks:project_meeting_minute_pdf": "tasks.kickoff.projects",
    "tasks:project_vrf_upload": "tasks.kickoff.projects",
    "tasks:project_vrf_compile": "tasks.kickoff.projects",
    # Bridge attrezzature — ACL effettivo gestito dal modulo attrezzature
    "tasks:attrezzature_action": "tasks.kickoff.view",
}

_ROLE_GRANTS = {
    "admin": set(CANONICAL_PERMISSION_MAP.values()),
    "amministrazione": set(CANONICAL_PERMISSION_MAP.values()),
    "caporeparto": {
        "tasks.kickoff.view",
        "tasks.kickoff.create",
        "tasks.kickoff.edit",
        "tasks.kickoff.comment",
        "tasks.kickoff.projects",
    },
    "operatore": {
        "tasks.kickoff.view",
        "tasks.kickoff.comment",
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
                    "note": "[TASKS_BOOTSTRAP] binding KICK-OFF",
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

        existing_nav_item = (
            NavigationItem.objects.filter(section="topbar", route_name="tasks:list")
            .order_by("id")
            .first()
        )
        nav_item, created = NavigationItem.objects.update_or_create(
            code=existing_nav_item.code if existing_nav_item else "tasks",
            defaults={
                "label": "KICK-OFF",
                "route_name": "tasks:list",
                "url_path": "",
                "section": "topbar",
                "required_permission_code": "tasks.kickoff.view",
                "order": 40,
                "is_visible": True,
                "is_enabled": True,
                "icon": "check-square",
                "description": "Gestione attività KICK-OFF, progetti, VRF e incontri.",
            },
        )
        changed = changed or created

        roles_by_id = {int(role.id): _normalize_role_name(role.nome) for role in Ruolo.objects.all()}
        enabled_view_role_ids = {
            role_id
            for role_id, role_name in roles_by_id.items()
            if "tasks.kickoff.view" in _ROLE_GRANTS.get(role_name, set())
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
                            "note": "[TASKS_BOOTSTRAP] default accessi KICK-OFF",
                        },
                    )
                    changed = changed or created
                    if not created and bool(grant.enabled) != bool(enabled):
                        grant.enabled = bool(enabled)
                        grant.note = "[TASKS_BOOTSTRAP] default accessi KICK-OFF"
                        grant.save(update_fields=["enabled", "note", "updated_at"])
                        changed = True

    if changed:
        try:
            bump_navigation_registry_version()
        except Exception:
            pass
    return changed


def bootstrap_tasks_acl_endpoints(*, force: bool = False, seed_role_grants: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        MODULE,
        icona="check-square",
        section="tasks",
        force=force,
        bootstrap_nav_fn=lambda: _bootstrap_canonical_acl(seed_role_grants=seed_role_grants),
    )
