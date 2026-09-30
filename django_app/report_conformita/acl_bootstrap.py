"""Bootstrap ACL v2 canonico per Report conformita'.

Registra i permessi canonici (accesso al modulo + uno per area di report), i
binding route -> permesso (necessari con ACL_STRICT_CANONICAL in prod), la voce
di menu e i grant di default CREATE-ONLY: non sovrascrive le modifiche fatte in
/admin-portale/acl-canonico/. Pattern replicato da ``schede_sicurezza``.

Il binding della route del singolo report copre solo l'accesso al modulo: il
permesso dell'area (qualita/persone/sicurezza/it) e' verificato nella view,
fail-closed, perche' una route serve report di aree diverse.
"""
from __future__ import annotations

import logging

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

from .registry import AREA_IT, AREA_PERSONE, AREA_QUALITA, AREA_SICUREZZA

logger = logging.getLogger(__name__)

MODULE = "report_conformita"
_BOOTSTRAP_CACHE_KEY = "report_conformita_acl_bootstrap_v1"

PERM_VIEW = "report_conformita.modulo.view"
PERM_AREA = {
    AREA_QUALITA: "report_conformita.qualita.view",
    AREA_PERSONE: "report_conformita.persone.view",
    AREA_SICUREZZA: "report_conformita.sicurezza.view",
    AREA_IT: "report_conformita.it.view",
}

_CANONICAL = {
    PERM_VIEW: {
        "label": "Report conformità - Accesso",
        "description": "Accesso alla sezione Report conformità (ISO 9001, EN 9100, ISO 45001, ISO 27001). "
                       "I report visibili dipendono dai permessi di area.",
    },
    PERM_AREA[AREA_QUALITA]: {
        "label": "Report conformità - Qualità e processi",
        "description": "NC/OFI, albo fornitori, verifiche periodiche, presa visione procedure, manutenzione.",
    },
    PERM_AREA[AREA_PERSONE]: {
        "label": "Report conformità - Competenze e qualifiche",
        "description": "Formazione obbligatoria, qualifiche, processi speciali, efficacia formazione (dati nominativi).",
    },
    PERM_AREA[AREA_SICUREZZA]: {
        "label": "Report conformità - Salute e sicurezza",
        "description": "Eventi di sicurezza, DPI, scadenziario degli obblighi di legge.",
    },
    PERM_AREA[AREA_IT]: {
        "label": "Report conformità - Sicurezza delle informazioni",
        "description": "Inventario IT, licenze, revisione accessi, backup e vulnerabilità.",
    },
}

_ROUTE_BINDINGS = {
    "report_conformita:index": PERM_VIEW,
    "report_conformita:report": PERM_VIEW,
    "report_conformita:riesame": PERM_VIEW,
}

# Ruoli legacy reali: admin, amministrazione, caporeparto, HR, qualita, utente.
# L'area IT resta al solo admin: nessun ruolo legacy IT dedicato, si assegna a mano.
_ROLE_GRANTS = {
    "admin": {PERM_VIEW, *PERM_AREA.values()},
    "qualita": {PERM_VIEW, PERM_AREA[AREA_QUALITA], PERM_AREA[AREA_PERSONE], PERM_AREA[AREA_SICUREZZA]},
    "amministrazione": {PERM_VIEW, PERM_AREA[AREA_QUALITA]},
    "hr": {PERM_VIEW, PERM_AREA[AREA_PERSONE]},
}

_LEGACY_ACTIONS = {"rc_view": PERM_VIEW}

_PULSANTI_DEFINITIONS = [
    {"modulo": MODULE, "codice": "rc_view", "label": "Report conformità",
     "url": "/report-conformita/", "visible_topbar": True, "ui_order": 64},
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
                          "note": "[RC_BOOTSTRAP] binding Report conformità",
                          "priority": 80, "is_active": True},
            )
            changed = changed or created
            if not created and (binding.permission_id != code or not binding.is_active):
                binding.permission_id = code
                binding.is_active = True
                binding.save(update_fields=["permission", "is_active", "updated_at"])
                changed = True

        nav, created = ensure_navigation_item(
            "report-conformita",
            {"label": "Report conformità",
             "route_name": "report_conformita:index",
             "url_path": "", "section": "topbar",
             "required_permission_code": PERM_VIEW, "order": 64,
             "is_visible": True, "is_enabled": True, "icon": "file-check",
             "description": "Report per audit ISO 9001, EN 9100, ISO 45001, ISO 27001: web, PDF, Excel."},
        )
        changed = changed or created

        roles = {int(r.id): _norm(r.nome) for r in Ruolo.objects.all()}

        existing_nav = {int(x.legacy_role_id): x for x in NavigationRoleAccess.objects.filter(item=nav)}
        for rid, rname in roles.items():
            if PERM_VIEW not in _ROLE_GRANTS.get(rname, set()):
                continue
            row = existing_nav.get(rid)
            if row is None:
                NavigationRoleAccess.objects.create(item=nav, legacy_role_id=rid, can_view=True)
                changed = True

        for rid, rname in roles.items():
            grants = _ROLE_GRANTS.get(rname, set())
            for code in _CANONICAL:
                _, created = RolePermissionGrant.objects.get_or_create(
                    legacy_role_id=rid, permission_id=code,
                    defaults={"enabled": code in grants, "note": "[RC_BOOTSTRAP] default"},
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
                        can_edit=0, can_delete=0, can_approve=0,
                    )
                    changed = True

    if changed:
        try:
            bump_navigation_registry_version()
        except Exception:
            pass
    return changed


def bootstrap_report_conformita_acl(*, force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        MODULE,
        icona="file-check",
        section=MODULE,
        force=force,
        init_permessi=False,
        bootstrap_nav_fn=_bootstrap_canonical,
    )
