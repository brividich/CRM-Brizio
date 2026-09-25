"""Bootstrap ACL v2 canonico per Sistema di gestione.

Permessi canonici, binding route -> permesso (necessari con ACL_STRICT_CANONICAL),
voce di menu e grant di default CREATE-ONLY. Pattern di ``schede_sicurezza`` e
``report_conformita``. Le decisioni fini (approvazione, modifica solo in bozza)
sono ripetute nelle view.
"""
from __future__ import annotations

import logging

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

logger = logging.getLogger(__name__)

MODULE = "sistema_gestione"
_BOOTSTRAP_CACHE_KEY = "sistema_gestione_acl_bootstrap_v2"

PERM_VIEW = "sistema_gestione.modulo.view"
PERM_SOA_VIEW = "sistema_gestione.soa.view"
PERM_SOA_EDIT = "sistema_gestione.soa.edit"
PERM_SOA_APPROVA = "sistema_gestione.soa.approva"
PERM_AUDIT_VIEW = "sistema_gestione.audit.view"
PERM_AUDIT_EDIT = "sistema_gestione.audit.edit"
PERM_AUDIT_ESEGUI = "sistema_gestione.audit.esegui"
PERM_AUDIT_APPROVA = "sistema_gestione.audit.approva"

_CANONICAL = {
    PERM_VIEW: {
        "label": "Sistema di gestione - Accesso",
        "description": "Accesso alla sezione Sistema di gestione (SoA ISO 27001, audit interni).",
    },
    PERM_SOA_VIEW: {
        "label": "Sistema di gestione - SoA: consulta",
        "description": "Consultazione della Dichiarazione di applicabilità (MOD.165) e del registro threat intelligence.",
    },
    PERM_SOA_EDIT: {
        "label": "Sistema di gestione - SoA: prepara",
        "description": "Compila le revisioni in bozza, le propone alla Direzione, registra la threat intelligence.",
    },
    PERM_SOA_APPROVA: {
        "label": "Sistema di gestione - SoA: approva",
        "description": "Approva la revisione proposta (Direzione): diventa la SoA in vigore.",
    },
    PERM_AUDIT_VIEW: {
        "label": "Sistema di gestione - Audit: consulta",
        "description": "Consulta programmi, piani, checklist, rapporti e PDF degli audit interni.",
    },
    PERM_AUDIT_EDIT: {
        "label": "Sistema di gestione - Audit: prepara",
        "description": "Gestisce auditor, programma annuale, piani e rapporti di audit.",
    },
    PERM_AUDIT_ESEGUI: {
        "label": "Sistema di gestione - Audit: esegui",
        "description": "Compila checklist, evidenze e rapporto degli audit assegnati.",
    },
    PERM_AUDIT_APPROVA: {
        "label": "Sistema di gestione - Audit: approva",
        "description": "Approva programma e piano, convalida e valuta il rapporto di audit.",
    },
}

_ROUTE_BINDINGS = {
    "sistema_gestione:index": PERM_VIEW,
    "sistema_gestione:soa": PERM_SOA_VIEW,
    "sistema_gestione:soa_revisione": PERM_SOA_VIEW,
    "sistema_gestione:soa_copia_firmata": PERM_SOA_VIEW,
    "sistema_gestione:soa_voce": PERM_SOA_EDIT,
    "sistema_gestione:soa_nuova_revisione": PERM_SOA_EDIT,
    "sistema_gestione:soa_proponi": PERM_SOA_EDIT,
    "sistema_gestione:soa_riporta_in_bozza": PERM_SOA_EDIT,
    "sistema_gestione:soa_carica_firmata": PERM_SOA_EDIT,
    "sistema_gestione:soa_approva": PERM_SOA_APPROVA,
    "sistema_gestione:threat_intelligence": PERM_SOA_VIEW,
    "sistema_gestione:threat_intelligence_nuova": PERM_SOA_EDIT,
    "sistema_gestione:audit_index": PERM_AUDIT_VIEW,
    "sistema_gestione:auditor_elenco": PERM_AUDIT_VIEW,
    "sistema_gestione:programma_dettaglio": PERM_AUDIT_VIEW,
    "sistema_gestione:programma_export_pdf": PERM_AUDIT_VIEW,
    "sistema_gestione:programma_copia_firmata": PERM_AUDIT_VIEW,
    "sistema_gestione:audit_dettaglio": PERM_AUDIT_VIEW,
    "sistema_gestione:audit_export": PERM_AUDIT_VIEW,
    "sistema_gestione:audit_copia_firmata": PERM_AUDIT_VIEW,
    "sistema_gestione:auditor_nuovo": PERM_AUDIT_EDIT,
    "sistema_gestione:auditor_modifica": PERM_AUDIT_EDIT,
    "sistema_gestione:programma_nuovo": PERM_AUDIT_EDIT,
    "sistema_gestione:programma_riga_nuova": PERM_AUDIT_EDIT,
    "sistema_gestione:programma_riga_modifica": PERM_AUDIT_EDIT,
    "sistema_gestione:programma_cella": PERM_AUDIT_EDIT,
    "sistema_gestione:programma_proponi": PERM_AUDIT_EDIT,
    "sistema_gestione:programma_nuova_revisione": PERM_AUDIT_EDIT,
    "sistema_gestione:programma_carica_firmata": PERM_AUDIT_EDIT,
    "sistema_gestione:audit_nuovo": PERM_AUDIT_EDIT,
    "sistema_gestione:audit_modifica": PERM_AUDIT_EDIT,
    "sistema_gestione:audit_persona_salva": PERM_AUDIT_EDIT,
    "sistema_gestione:audit_agenda_salva": PERM_AUDIT_EDIT,
    "sistema_gestione:audit_comunica": PERM_AUDIT_EDIT,
    "sistema_gestione:audit_carica_firmata": PERM_AUDIT_EDIT,
    "sistema_gestione:audit_approva_lead": PERM_AUDIT_ESEGUI,
    "sistema_gestione:audit_avvia": PERM_AUDIT_ESEGUI,
    "sistema_gestione:audit_esito_salva": PERM_AUDIT_ESEGUI,
    "sistema_gestione:audit_domanda_aggiuntiva": PERM_AUDIT_ESEGUI,
    "sistema_gestione:audit_car_sezione": PERM_AUDIT_ESEGUI,
    "sistema_gestione:audit_rapporto_salva": PERM_AUDIT_ESEGUI,
    "sistema_gestione:audit_firma_rapporto": PERM_AUDIT_ESEGUI,
    "sistema_gestione:audit_riapri_rapporto": PERM_AUDIT_ESEGUI,
    "sistema_gestione:auditor_approva_esterno": PERM_AUDIT_APPROVA,
    "sistema_gestione:programma_approva": PERM_AUDIT_APPROVA,
    "sistema_gestione:programma_convalida": PERM_AUDIT_APPROVA,
    "sistema_gestione:audit_approva_direzione": PERM_AUDIT_APPROVA,
    "sistema_gestione:audit_convalida_ente": PERM_AUDIT_APPROVA,
    "sistema_gestione:audit_valuta_rdd": PERM_AUDIT_APPROVA,
}

# Ruoli legacy reali: admin, amministrazione, caporeparto, HR, qualita, utente.
# Preparazione (CISO) e approvazione (Direzione) non hanno un ruolo legacy dedicato:
# si assegnano per utente o gruppo in Admin › ACL.
_ROLE_GRANTS = {
    "admin": set(_CANONICAL),
    "qualita": {PERM_VIEW, PERM_SOA_VIEW, PERM_AUDIT_VIEW},
}

_LEGACY_ACTIONS = {"sg_view": PERM_VIEW}

_PULSANTI_DEFINITIONS = [
    {"modulo": MODULE, "codice": "sg_view", "label": "Sistema di gestione",
     "url": "/sistema-gestione/", "visible_topbar": True, "ui_order": 65},
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
                          "note": "[SG_BOOTSTRAP] binding Sistema di gestione",
                          "priority": 80, "is_active": True},
            )
            changed = changed or created
            if not created and (binding.permission_id != code or not binding.is_active):
                binding.permission_id = code
                binding.is_active = True
                binding.save(update_fields=["permission", "is_active", "updated_at"])
                changed = True

        nav, created = ensure_navigation_item(
            "sistema-gestione",
            {"label": "Sistema di gestione",
             "route_name": "sistema_gestione:index",
             "url_path": "", "section": "topbar",
             "required_permission_code": PERM_VIEW, "order": 65,
             "is_visible": True, "is_enabled": True, "icon": "shield-check",
             "description": "Dichiarazione di applicabilità ISO 27001 (MOD.165), threat intelligence, audit interni."},
        )
        changed = changed or created

        roles = {int(r.id): _norm(r.nome) for r in Ruolo.objects.all()}
        existing_nav = {int(x.legacy_role_id): x for x in NavigationRoleAccess.objects.filter(item=nav)}
        for rid, rname in roles.items():
            if PERM_VIEW in _ROLE_GRANTS.get(rname, set()) and rid not in existing_nav:
                NavigationRoleAccess.objects.create(item=nav, legacy_role_id=rid, can_view=True)
                changed = True

        for rid, rname in roles.items():
            grants = _ROLE_GRANTS.get(rname, set())
            for code in _CANONICAL:
                _, created = RolePermissionGrant.objects.get_or_create(
                    legacy_role_id=rid, permission_id=code,
                    defaults={"enabled": code in grants, "note": "[SG_BOOTSTRAP] default"},
                )
                changed = changed or created
            for azione, code in _LEGACY_ACTIONS.items():
                enabled = code in grants
                if not Permesso.objects.filter(ruolo_id=rid, modulo__iexact=MODULE, azione__iexact=azione).exists():
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


def bootstrap_sistema_gestione_acl(*, force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        MODULE,
        icona="shield-check",
        section=MODULE,
        force=force,
        init_permessi=False,
        bootstrap_nav_fn=_bootstrap_canonical,
    )
