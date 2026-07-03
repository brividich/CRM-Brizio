"""Bootstrap ACL v2 canonico per Gestione Carichi Macchina.

Registra: permessi canonici (view/edit), binding route->permesso (necessari con
ACL_STRICT_CANONICAL in prod), voce di menu, e grant di default CREATE-ONLY per
admin/amministrazione/caporeparto (non sovrascrive le modifiche fatte dall'admin
in /admin-portale/acl-canonico/). Chiamato da apps.ready() via run_bootstrap.
"""
from __future__ import annotations

import logging

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

logger = logging.getLogger(__name__)

MODULE = "gestione_carichi_macchina"
# v2: aggiunti i binding dei nuovi endpoint (impostazioni/config/duplica/sovrapposizione/
# suggerimento/dettaglio/registro). Bump = re-registrazione immediata dopo il deploy.
_BOOTSTRAP_CACHE_KEY = "gestione_carichi_macchina_acl_bootstrap_v2"

PERM_VIEW = "gestione_carichi_macchina.piano.view"
PERM_EDIT = "gestione_carichi_macchina.piano.edit"

_CANONICAL = {
    PERM_VIEW: {
        "label": "Carichi Macchina - Visualizza piano",
        "description": "Accesso alle viste Excel/Gantt, API piano e suggerimenti.",
    },
    PERM_EDIT: {
        "label": "Carichi Macchina - Modifica piano",
        "description": "Modifica celle e spostamenti (drag, cascata, undo).",
    },
}

_ROUTE_BINDINGS = {
    # Lettura del piano (view)
    "gestione_carichi_macchina:excel": PERM_VIEW,
    "gestione_carichi_macchina:gantt": PERM_VIEW,
    "gestione_carichi_macchina:registro": PERM_VIEW,
    "gestione_carichi_macchina:api_pianificazioni": PERM_VIEW,
    "gestione_carichi_macchina:api_pianificazione_dettaglio": PERM_VIEW,
    "gestione_carichi_macchina:api_suggerimento_macchina": PERM_VIEW,
    "gestione_carichi_macchina:api_spiega_macchina": PERM_VIEW,
    "gestione_carichi_macchina:api_sovrapposizione": PERM_VIEW,
    "gestione_carichi_macchina:cella_suggerimento": PERM_VIEW,
    # Modifica del piano (edit)
    "gestione_carichi_macchina:cella_edit": PERM_EDIT,
    "gestione_carichi_macchina:reschedule": PERM_EDIT,
    "gestione_carichi_macchina:reschedule_undo": PERM_EDIT,
    "gestione_carichi_macchina:pianificazione_duplica": PERM_EDIT,
    "gestione_carichi_macchina:impostazioni": PERM_EDIT,
    "gestione_carichi_macchina:macchina_config": PERM_EDIT,
}

_ROLE_GRANTS = {
    "admin": {PERM_VIEW, PERM_EDIT},
    "amministrazione": {PERM_VIEW, PERM_EDIT},
    "caporeparto": {PERM_VIEW, PERM_EDIT},
}

_LEGACY_ACTIONS = {"gcm_view": PERM_VIEW, "gcm_edit": PERM_EDIT}

_PULSANTI_DEFINITIONS = [
    {"modulo": MODULE, "codice": "gcm_view", "label": "Carichi Macchina",
     "url": "/carichi-macchina/", "visible_topbar": True, "ui_order": 46},
    {"modulo": MODULE, "codice": "gcm_edit", "label": "Carichi Macchina - Modifica",
     "url": "/carichi-macchina/cella/", "hide": True},
]


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _bootstrap_canonical() -> bool:
    from core.legacy_models import Permesso, Ruolo
    from core.models import (
        NavigationItem, NavigationRoleAccess, PermissionDefinition,
        RolePermissionGrant, RoutePermissionBinding,
    )
    from core.navigation_registry import bump_navigation_registry_version

    changed = False
    with transaction.atomic():
        # 1) permessi canonici
        for code, payload in _CANONICAL.items():
            _, created = PermissionDefinition.objects.get_or_create(
                code=code,
                defaults={"module": MODULE, "label": payload["label"],
                          "description": payload["description"], "is_active": True},
            )
            changed = changed or created

        # 2) binding route -> permesso
        for route_name, code in _ROUTE_BINDINGS.items():
            binding, created = RoutePermissionBinding.objects.get_or_create(
                route_name=route_name, path_pattern="",
                defaults={"match_strategy": RoutePermissionBinding.MATCH_EXACT,
                          "permission_id": code, "source_app": MODULE,
                          "note": "[GCM_BOOTSTRAP] binding Carichi Macchina",
                          "priority": 80, "is_active": True},
            )
            changed = changed or created
            if not created and (binding.permission_id != code or not binding.is_active):
                binding.permission_id = code
                binding.is_active = True
                binding.save(update_fields=["permission", "is_active", "updated_at"])
                changed = True

        # 3) voce di menu
        nav, created = NavigationItem.objects.update_or_create(
            code="carichi-macchina",
            defaults={"label": "Carichi Macchina",
                      "route_name": "gestione_carichi_macchina:excel",
                      "url_path": "", "section": "topbar",
                      "required_permission_code": PERM_VIEW, "order": 46,
                      "is_visible": True, "is_enabled": True, "icon": "calendar",
                      "description": "Pianificazione carichi macchina (Excel/Gantt)."},
        )
        changed = changed or created

        roles = {int(r.id): _norm(r.nome) for r in Ruolo.objects.all()}

        # 4) accesso menu per i ruoli con permesso view
        existing_nav = {int(x.legacy_role_id): x for x in NavigationRoleAccess.objects.filter(item=nav)}
        for rid, rname in roles.items():
            if PERM_VIEW not in _ROLE_GRANTS.get(rname, set()):
                continue
            row = existing_nav.get(rid)
            if row is None:
                NavigationRoleAccess.objects.create(item=nav, legacy_role_id=rid, can_view=True)
                changed = True
            elif not row.can_view:
                row.can_view = True
                row.save(update_fields=["can_view"])
                changed = True

        # 5) grant canonici + legacy, CREATE-ONLY (non clobbera modifiche admin)
        for rid, rname in roles.items():
            grants = _ROLE_GRANTS.get(rname, set())
            for code in (PERM_VIEW, PERM_EDIT):
                _, created = RolePermissionGrant.objects.get_or_create(
                    legacy_role_id=rid, permission_id=code,
                    defaults={"enabled": code in grants, "note": "[GCM_BOOTSTRAP] default"},
                )
                changed = changed or created
            for azione, code in _LEGACY_ACTIONS.items():
                enabled = code in grants
                if not Permesso.objects.filter(
                    ruolo_id=rid, modulo__iexact=MODULE, azione__iexact=azione
                ).exists():
                    Permesso.objects.create(
                        ruolo_id=rid, modulo=MODULE, azione=azione,
                        consentito=1 if enabled else 0, can_view=1 if enabled else 0,
                        can_edit=1 if enabled else 0, can_delete=0, can_approve=0,
                    )
                    changed = True

    if changed:
        try:
            bump_navigation_registry_version()
        except Exception:
            pass
    return changed


def bootstrap_carichi_acl_endpoints(*, force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        MODULE,
        icona="calendar",
        section=MODULE,
        force=force,
        init_permessi=False,
        bootstrap_nav_fn=_bootstrap_canonical,
    )
