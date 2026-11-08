"""Bootstrap ACL v2 canonico della sezione Ordini di produzione.

Permessi:

- ``PERM_VIEW``: elenco degli OP e scheda con documenti, FAI e anomalie. A tutti i ruoli:
  i FAI e le anomalie restano filtrati dai permessi dei loro moduli.
- ``PERM_DOCUMENTI``: aggiungere, cambiare ed eliminare i documenti di produzione. Solo admin
  di default, si assegna in Admin › ACL.
- ``PERM_IMPOSTAZIONI``: tipi di documento. Solo admin.

Solo creazione: le modifiche fatte in Admin › ACL restano.
"""
from __future__ import annotations

import logging

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

logger = logging.getLogger(__name__)

MODULE = "produzione"
_BOOTSTRAP_CACHE_KEY = "produzione_acl_bootstrap_v1"

PERM_VIEW = "produzione.op.view"
PERM_DOCUMENTI = "produzione.documenti.manage"
PERM_IMPOSTAZIONI = "produzione.impostazioni.manage"

_CANONICAL = {
    PERM_VIEW: {"label": "Ordini di produzione - Elenco e scheda OP",
                "description": "Elenco degli OP, scheda con documenti di produzione, FAI e anomalie."},
    PERM_DOCUMENTI: {"label": "Ordini di produzione - Documenti",
                     "description": "Aggiungere, cambiare ed eliminare i documenti di produzione di un OP."},
    PERM_IMPOSTAZIONI: {"label": "Ordini di produzione - Impostazioni",
                        "description": "Tipi di documento di produzione."},
}

_ROUTE_BINDINGS = {
    "produzione:elenco": PERM_VIEW,
    "produzione:scheda": PERM_VIEW,
    "produzione:guida": PERM_VIEW,
    "produzione:documento": PERM_DOCUMENTI,
    "produzione:documento_elimina": PERM_DOCUMENTI,
    "produzione:impostazioni": PERM_IMPOSTAZIONI,
}

# A tutti i ruoli (True) o solo ad admin (False).
_DEFAULT_TUTTI = {
    PERM_VIEW: True,
    PERM_DOCUMENTI: False,
    PERM_IMPOSTAZIONI: False,
}

_NAV_CODE = "produzione_op"


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _bootstrap_canonical() -> bool:
    from core.legacy_models import Ruolo
    from core.models import ModuleCategory, PermissionDefinition, RolePermissionGrant, RoutePermissionBinding
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
                          "note": "[PRODUZIONE_BOOTSTRAP] binding Ordini di produzione",
                          "priority": 80, "is_active": True},
            )
            changed = changed or created
            if not created and (binding.permission_id != code or not binding.is_active
                                or binding.source_app != MODULE):
                binding.permission_id = code
                binding.is_active = True
                binding.source_app = MODULE
                binding.save(update_fields=["permission", "is_active", "source_app", "updated_at"])
                changed = True

        defaults_nav = {
            "label": "Ordini di produzione", "route_name": "produzione:elenco", "url_path": "",
            "section": "topbar", "required_permission_code": PERM_VIEW, "order": 15,
            "is_visible": True, "is_enabled": True, "icon": "clipboard",
            "description": "Gli OP con i documenti di produzione, i FAI e le anomalie.",
        }
        categoria = ModuleCategory.objects.filter(key="manutenzione").first()
        if categoria is not None:
            defaults_nav["category"] = categoria
        _, nav_changed = ensure_navigation_item(_NAV_CODE, defaults_nav)
        changed = changed or nav_changed

        roles = {int(r.id): _norm(r.nome) for r in Ruolo.objects.all()}
        for rid, nome in roles.items():
            for code, tutti in _DEFAULT_TUTTI.items():
                _, created = RolePermissionGrant.objects.get_or_create(
                    legacy_role_id=rid, permission_id=code,
                    defaults={"enabled": tutti or nome == "admin", "note": "[PRODUZIONE_BOOTSTRAP] default"},
                )
                changed = changed or created

    if changed:
        try:
            bump_navigation_registry_version()
        except Exception:
            pass
    return changed


def bootstrap_produzione_acl(*, force: bool = False) -> None:
    run_bootstrap(
        [],
        _BOOTSTRAP_CACHE_KEY,
        MODULE,
        icona="clipboard",
        section=MODULE,
        force=force,
        init_permessi=False,
        bootstrap_nav_fn=_bootstrap_canonical,
    )
