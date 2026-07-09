"""Bootstrap ACL v2 canonico per Suggestion Corner (sola lettura, sessione 3).

Registra: permesso canonico view, binding route->permesso (necessari con
ACL_STRICT_CANONICAL in prod), voce di menu e grant di default a TUTTI i ruoli
(il modulo è apribile da ogni utente autenticato; lo scope dei dati è deciso in
permissions.visible_segnalazioni via Group SMS_TEAM). Chiamato da apps.ready().
"""
from __future__ import annotations

import logging

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

logger = logging.getLogger(__name__)

MODULE = "suggestion_corner"
_BOOTSTRAP_CACHE_KEY = "suggestion_corner_acl_bootstrap_v3"

PERM_VIEW = "suggestion_corner.segnalazione.view"

_CANONICAL = {
    PERM_VIEW: {
        "label": "Suggestion Corner - Visualizza",
        "description": "Accesso a elenco e dettaglio segnalazioni (scope per-utente via Group SMS_TEAM).",
    },
}

# Tutte le route (lettura + azioni FSM) usano il gate PERM_VIEW; l'autorizzazione
# fine delle azioni (SMS_TEAM/incaricato/controllore) è enforced in-view.
_ROUTE_BINDINGS = {
    "suggestion_corner:home": PERM_VIEW,
    "suggestion_corner:dettaglio": PERM_VIEW,
    "suggestion_corner:classifica": PERM_VIEW,
    "suggestion_corner:definisci_plan": PERM_VIEW,
    "suggestion_corner:avvia_do": PERM_VIEW,
    "suggestion_corner:completa_do": PERM_VIEW,
    "suggestion_corner:avvia_check": PERM_VIEW,
    "suggestion_corner:do_da_rifare": PERM_VIEW,
    "suggestion_corner:check_positivo": PERM_VIEW,
    "suggestion_corner:check_negativo": PERM_VIEW,
    "suggestion_corner:check_rinviato": PERM_VIEW,
    "suggestion_corner:inserisci_act": PERM_VIEW,
    "suggestion_corner:chiudi": PERM_VIEW,
    # Copilota AI (sessione 9) — gate PERM_VIEW; l'accesso fine è SMS_TEAM in-view.
    "suggestion_corner:ai_classifica": PERM_VIEW,
    "suggestion_corner:ai_bozza_plan": PERM_VIEW,
    "suggestion_corner:ai_simili": PERM_VIEW,
}

_PULSANTI_DEFINITIONS = [
    {"modulo": MODULE, "codice": "sc_view", "label": "Suggestion Corner",
     "url": "/suggestion-corner/", "visible_topbar": True, "ui_order": 95},
]


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _bootstrap_canonical() -> bool:
    from core.legacy_models import Ruolo
    from core.models import (
        NavigationItem, NavigationRoleAccess, PermissionDefinition,
        RolePermissionGrant, RoutePermissionBinding,
    )
    from core.navigation_registry import bump_navigation_registry_version

    changed = False
    with transaction.atomic():
        # 1) permesso canonico
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
                          "note": "[SC_BOOTSTRAP] binding Suggestion Corner",
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
            code="suggestion-corner",
            defaults={"label": "Suggestion Corner",
                      "route_name": "suggestion_corner:home",
                      "url_path": "", "section": "topbar",
                      "required_permission_code": PERM_VIEW, "order": 95,
                      "is_visible": True, "is_enabled": True, "icon": "message-square",
                      "description": "Segnalazioni di miglioramento (SMS)."},
        )
        changed = changed or created

        # 4) grant PERM_VIEW a TUTTI i ruoli (modulo apribile da ogni utente;
        #    lo scope dati è filtrato in view). CREATE-ONLY, non clobbera l'admin.
        roles = {int(r.id): _norm(r.nome) for r in Ruolo.objects.all()}
        existing_nav = {int(x.legacy_role_id): x for x in NavigationRoleAccess.objects.filter(item=nav)}
        for rid in roles:
            _, created = RolePermissionGrant.objects.get_or_create(
                legacy_role_id=rid, permission_id=PERM_VIEW,
                defaults={"enabled": True, "note": "[SC_BOOTSTRAP] default view"},
            )
            changed = changed or created
            row = existing_nav.get(rid)
            if row is None:
                NavigationRoleAccess.objects.create(item=nav, legacy_role_id=rid, can_view=True)
                changed = True
            elif not row.can_view:
                row.can_view = True
                row.save(update_fields=["can_view"])
                changed = True

    if changed:
        try:
            bump_navigation_registry_version()
        except Exception:
            pass
    return changed


def bootstrap_suggestion_corner_acl(*, force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        MODULE,
        icona="message-square",
        section=MODULE,
        force=force,
        init_permessi=False,
        bootstrap_nav_fn=_bootstrap_canonical,
    )
