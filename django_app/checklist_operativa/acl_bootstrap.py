from __future__ import annotations

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "checklist_operativa_acl_bootstrap_v1"

MODULE = "checklist_operativa"
PERM_CONFIGURAZIONE_MANAGE = "checklist_operativa.configurazione.manage"

# Permesso "solo definizione": nessun RoutePermissionBinding qui, il gate resta
# in-view (come diario_preposto) per non negare la pagina a tutti in
# ACL_STRICT_CANONICAL senza grant esplicito.
_CANONICAL = {
    PERM_CONFIGURAZIONE_MANAGE: {
        "label": "Checklist Operativa - Configurazione",
        "description": (
            "Gestione mansioni/template, creazione eventi di chiusura, revisione "
            "proposte e accesso allo storico delle chiusure."
        ),
    },
}

# Grant di default create-only: solo "admin", che passa comunque dal bypass superuser.
_ROLE_GRANTS = {"admin": {PERM_CONFIGURAZIONE_MANAGE}}


def _bootstrap_canonical() -> bool:
    from core.legacy_models import Ruolo
    from core.models import PermissionDefinition, RolePermissionGrant

    changed = False
    with transaction.atomic():
        for code, payload in _CANONICAL.items():
            _, created = PermissionDefinition.objects.get_or_create(
                code=code,
                defaults={"module": MODULE, "label": payload["label"],
                          "description": payload["description"], "is_active": True},
            )
            changed = changed or created

        for rid, rname in {int(r.id): (r.nome or "").strip().lower()
                           for r in Ruolo.objects.all()}.items():
            grants = _ROLE_GRANTS.get(rname, set())
            for code in _CANONICAL:
                _, created = RolePermissionGrant.objects.get_or_create(
                    legacy_role_id=rid, permission_id=code,
                    defaults={"enabled": code in grants, "note": "[CO_BOOTSTRAP] default"},
                )
                changed = changed or created
    return changed


_PULSANTI_DEFINITIONS = [
    {"modulo": "checklist_operativa", "codice": "checklist_operativa_gestione", "label": "Checklist Operativa - Gestione", "url": "/checklist-operativa/", "hide": False},
    {"modulo": "checklist_operativa", "codice": "checklist_operativa_configurazione", "label": "Checklist Operativa - Configurazione", "url": "/checklist-operativa/configurazione/", "hide": True},
    {"modulo": "checklist_operativa", "codice": "checklist_operativa_riepilogo", "label": "Checklist Operativa - Riepilogo storico", "url": "/checklist-operativa/riepilogo/", "hide": True},
]


def bootstrap_checklist_operativa_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "checklist_operativa",
        icona="check-square",
        section="checklist_operativa_api",
        force=force,
        bootstrap_nav_fn=_bootstrap_canonical,
    )
