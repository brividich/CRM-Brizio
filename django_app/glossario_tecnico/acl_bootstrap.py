"""Bootstrap ACL v2 canonico del Glossario tecnico.

Due permessi: consultazione (tutti i ruoli) e gestione (inserire, modificare,
validare, decidere le proposte AI) per admin e qualità. L'Ufficio tecnico non ha un
ruolo legacy dedicato: si abilita per utente o gruppo in Admin › ACL. Grant di
default CREATE-ONLY (pattern ``sistema_gestione``): le modifiche fatte in admin non
vengono sovrascritte ai riavvii.
"""
from __future__ import annotations

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

MODULE = "glossario_tecnico"
_BOOTSTRAP_CACHE_KEY = "glossario_tecnico_acl_bootstrap_v1"

PERM_VIEW = "glossario_tecnico.termini.view"
PERM_GESTIONE = "glossario_tecnico.gestione"

_CANONICAL = {
    PERM_VIEW: {
        "label": "Glossario tecnico - Consulta",
        "description": "Consultazione del glossario tecnico (termini, varianti, simboli).",
    },
    PERM_GESTIONE: {
        "label": "Glossario tecnico - Gestione",
        "description": "Inserisce e modifica termini e varianti, valida le bozze, decide le proposte AI.",
    },
}

_ROUTE_BINDINGS = {
    "glossario_tecnico:index": PERM_VIEW,
    "glossario_tecnico:termine": PERM_VIEW,
    "glossario_tecnico:api_cerca": PERM_VIEW,
    "glossario_tecnico:termine_nuovo": PERM_GESTIONE,
    "glossario_tecnico:termine_modifica": PERM_GESTIONE,
    "glossario_tecnico:variante_aggiungi": PERM_GESTIONE,
    "glossario_tecnico:variante_elimina": PERM_GESTIONE,
    "glossario_tecnico:revisione": PERM_GESTIONE,
    "glossario_tecnico:api_stato": PERM_GESTIONE,
    "glossario_tecnico:proposta_decidi": PERM_GESTIONE,
}

_ROLE_GRANTS_GESTIONE = {"admin", "qualita"}

_LEGACY_ACTIONS = {"gl_view": PERM_VIEW}

_PULSANTI_DEFINITIONS = [
    {"modulo": MODULE, "codice": "gl_view", "label": "Glossario tecnico",
     "url": "/glossario/", "visible_topbar": True, "ui_order": 66},
]


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _bootstrap_canonical() -> bool:
    from core.legacy_models import Permesso, Ruolo
    from core.models import NavigationRoleAccess, PermissionDefinition, RolePermissionGrant, RoutePermissionBinding
    from core.navigation_registry import bump_navigation_registry_version, ensure_navigation_item

    changed = False
    with transaction.atomic():
        for code, payload in _CANONICAL.items():
            _, created = PermissionDefinition.objects.get_or_create(
                code=code,
                defaults={"module": MODULE, "label": payload["label"],
                          "description": payload["description"], "is_active": True},
            )
            changed = changed or created

        for route_name, code in _ROUTE_BINDINGS.items():
            binding, created = RoutePermissionBinding.objects.get_or_create(
                route_name=route_name, path_pattern="",
                defaults={"match_strategy": RoutePermissionBinding.MATCH_EXACT,
                          "permission_id": code, "source_app": MODULE,
                          "note": "[GL_BOOTSTRAP] binding Glossario tecnico",
                          "priority": 80, "is_active": True},
            )
            changed = changed or created
            if not created and (binding.permission_id != code or not binding.is_active):
                binding.permission_id = code
                binding.is_active = True
                binding.save(update_fields=["permission", "is_active", "updated_at"])
                changed = True

        nav, created = ensure_navigation_item(
            "glossario-tecnico",
            {"label": "Glossario tecnico",
             "route_name": "glossario_tecnico:index",
             "url_path": "", "section": "topbar",
             "required_permission_code": PERM_VIEW, "order": 66,
             "is_visible": True, "is_enabled": True, "icon": "book-open",
             "description": "Termini di lavorazione, quotatura, tolleranze, trattamenti e sigle SGI con sinonimi e simboli."},
        )
        changed = changed or created

        roles = {int(r.id): _norm(r.nome) for r in Ruolo.objects.all()}
        existing_nav = {int(x.legacy_role_id): x for x in NavigationRoleAccess.objects.filter(item=nav)}
        for rid in roles:
            if rid not in existing_nav:
                NavigationRoleAccess.objects.create(item=nav, legacy_role_id=rid, can_view=True)
                changed = True

        for rid, rname in roles.items():
            grants = {PERM_VIEW} | ({PERM_GESTIONE} if rname in _ROLE_GRANTS_GESTIONE else set())
            for code in _CANONICAL:
                _, created = RolePermissionGrant.objects.get_or_create(
                    legacy_role_id=rid, permission_id=code,
                    defaults={"enabled": code in grants, "note": "[GL_BOOTSTRAP] default"},
                )
                changed = changed or created
            for azione, code in _LEGACY_ACTIONS.items():
                if not Permesso.objects.filter(ruolo_id=rid, modulo__iexact=MODULE, azione__iexact=azione).exists():
                    Permesso.objects.create(
                        ruolo_id=rid, modulo=MODULE, azione=azione,
                        consentito=1, can_view=1, can_edit=0, can_delete=0, can_approve=0,
                    )
                    changed = True

    if changed:
        try:
            bump_navigation_registry_version()
        except Exception:
            pass
    return changed


def bootstrap_glossario_tecnico_acl(*, force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        MODULE,
        icona="book-open",
        section=MODULE,
        force=force,
        init_permessi=False,
        bootstrap_nav_fn=_bootstrap_canonical,
    )
