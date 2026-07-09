"""Bootstrap ACL v2 canonico per Schede di Sicurezza.

Registra: permessi canonici (view/gestisci), binding route->permesso
(necessari con ACL_STRICT_CANONICAL in prod), voce di menu e grant di default
CREATE-ONLY (non sovrascrive modifiche fatte in /admin-portale/acl-canonico/).
Chiamato da apps.ready() via run_bootstrap. Pattern replicato da
`gestione_carichi_macchina`/`gestione_specifiche` (vedi RECON §5).
"""
from __future__ import annotations

import logging

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

logger = logging.getLogger(__name__)

MODULE = "schede_sicurezza"
_BOOTSTRAP_CACHE_KEY = "schede_sicurezza_acl_bootstrap_v2"

PERM_VIEW = "schede_sicurezza.prodotto.view"
PERM_GESTISCI = "schede_sicurezza.prodotto.gestisci"

_CANONICAL = {
    PERM_VIEW: {
        "label": "Schede Sicurezza - Visualizza",
        "description": "Accesso a elenco/dettaglio prodotti, vista mobile QR, download PDF e presa visione.",
    },
    PERM_GESTISCI: {
        "label": "Schede Sicurezza - Gestisci",
        "description": "Creazione/modifica prodotti chimici, caricamento nuove versioni SDS, elenco prese visione.",
    },
}

_ROUTE_BINDINGS = {
    "schede_sicurezza:prodotto_list": PERM_VIEW,
    "schede_sicurezza:prodotto_detail": PERM_VIEW,
    "schede_sicurezza:prodotto_qr": PERM_VIEW,
    "schede_sicurezza:scheda_mobile": PERM_VIEW,
    "schede_sicurezza:scheda_download": PERM_VIEW,
    "schede_sicurezza:presa_visione_conferma": PERM_VIEW,
    "schede_sicurezza:prodotto_nuovo": PERM_GESTISCI,
    "schede_sicurezza:prodotto_modifica": PERM_GESTISCI,
    "schede_sicurezza:presa_visione_list": PERM_GESTISCI,
    "schede_sicurezza:report_compliance": PERM_GESTISCI,
}

# Ruoli legacy reali (portale): admin, amministrazione, caporeparto, HR, qualita, utente.
# Presa visione via QR è operativa in reparto -> vista consentita a tutti; la
# gestione anagrafica prodotti/SDS resta ai ruoli con responsabilità di reparto/qualità.
_ROLE_GRANTS = {
    "admin": {PERM_VIEW, PERM_GESTISCI},
    "amministrazione": {PERM_VIEW, PERM_GESTISCI},
    "qualita": {PERM_VIEW, PERM_GESTISCI},
    "caporeparto": {PERM_VIEW, PERM_GESTISCI},
    "hr": {PERM_VIEW},
    "utente": {PERM_VIEW},
}

_LEGACY_ACTIONS = {"ss_view": PERM_VIEW, "ss_gestisci": PERM_GESTISCI}

_PULSANTI_DEFINITIONS = [
    {"modulo": MODULE, "codice": "ss_view", "label": "Schede di Sicurezza",
     "url": "/schede-sicurezza/", "visible_topbar": True, "ui_order": 71},
    {"modulo": MODULE, "codice": "ss_gestisci", "label": "Schede di Sicurezza - Gestione",
     "url": "/schede-sicurezza/nuovo/", "hide": True},
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
                          "note": "[SS_BOOTSTRAP] binding Schede Sicurezza",
                          "priority": 80, "is_active": True},
            )
            changed = changed or created
            if not created and (binding.permission_id != code or not binding.is_active):
                binding.permission_id = code
                binding.is_active = True
                binding.save(update_fields=["permission", "is_active", "updated_at"])
                changed = True

        # 3) voce di menu (area Sicurezza/Compliance, coerente con dpi/procedure_refresh)
        nav, created = NavigationItem.objects.update_or_create(
            code="schede-sicurezza",
            defaults={"label": "Schede di Sicurezza",
                      "route_name": "schede_sicurezza:prodotto_list",
                      "url_path": "", "section": "topbar",
                      "required_permission_code": PERM_VIEW, "order": 71,
                      "is_visible": True, "is_enabled": True, "icon": "alert-triangle",
                      "description": "Archivio schede dati di sicurezza prodotti chimici (SDS)."},
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
            for code in _CANONICAL:
                _, created = RolePermissionGrant.objects.get_or_create(
                    legacy_role_id=rid, permission_id=code,
                    defaults={"enabled": code in grants, "note": "[SS_BOOTSTRAP] default"},
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


def bootstrap_schede_sicurezza_acl(*, force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        MODULE,
        icona="alert-triangle",
        section=MODULE,
        force=force,
        init_permessi=False,
        bootstrap_nav_fn=_bootstrap_canonical,
    )
