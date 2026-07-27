"""Bootstrap ACL v2 canonico per Gestione Specifiche.

Registra: permessi canonici, binding route->permesso (necessari con
ACL_STRICT_CANONICAL in prod), voce di menu e grant di default CREATE-ONLY
per admin/amministrazione (non sovrascrive le modifiche fatte in
/admin-portale/acl-canonico/). Chiamato da apps.ready() via run_bootstrap.

NB ruoli di processo (DM, IN1, RDD, MSM, MSO, MSA, SGI): da mappare ai Ruolo
legacy reali — vedi BLOCKER B2. Qui NON si creano gruppi AD (guardrail §8).
"""
from __future__ import annotations

import logging

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

logger = logging.getLogger(__name__)

MODULE = "gestione_specifiche"
_BOOTSTRAP_CACHE_KEY = "gestione_specifiche_acl_bootstrap_v17"

# --- Permessi canonici --------------------------------------------------------
PERM_VIEW = "gestione_specifiche.specifica.view"
PERM_CLAIM = "gestione_specifiche.specifica.claim"
PERM_COMPILA = "gestione_specifiche.mod133.compila"
PERM_APPROVA = "gestione_specifiche.mod133.approva"
PERM_SOSPENDI = "gestione_specifiche.specifica.sospendi"
PERM_ANNULLA = "gestione_specifiche.specifica.annulla"
PERM_DEROGA = "gestione_specifiche.distribuzione.deroga"
PERM_DISTRIBUISCI = "gestione_specifiche.distribuzione.distribuisci"
PERM_ADMIN = "gestione_specifiche.admin"
# Registro OFI standalone (MOD.174): inserimento/modifica manuale di una voce.
PERM_OFI_ADD = "gestione_specifiche.registroofi.add"

_CANONICAL = {
    PERM_VIEW: {"label": "Specifiche - Visualizza", "description": "Accesso elenco/dettaglio/storico specifiche e API."},
    PERM_CLAIM: {"label": "Specifiche - Presa in carico", "description": "Claim del task (avvio flow-down, compilazione, approvazione)."},
    PERM_COMPILA: {"label": "Specifiche - Compila MOD.133", "description": "Compilazione righe MOD.133 e chiusura compilazione."},
    PERM_APPROVA: {"label": "Specifiche - Approva MOD.133", "description": "Approvazione/respingimento flow-down e creazione OFI su conferma."},
    PERM_SOSPENDI: {"label": "Specifiche - Sospendi/Ripristina", "description": "Sospensione, ripristino, annullamento, gestione errore tecnico."},
    PERM_ANNULLA: {"label": "Specifiche - Annulla", "description": "Annullamento e marcatura duplicato."},
    PERM_DEROGA: {"label": "Specifiche - Deroga copie", "description": "Deroga giustificata sulla regola copie cartacee."},
    PERM_DISTRIBUISCI: {"label": "Specifiche - Distribuisci", "description": "Creazione e tracciamento distribuzioni."},
    PERM_ADMIN: {"label": "Specifiche - Amministrazione", "description": "Sezione admin del modulo: mappatura cartelle, timbri, auto-approvazione, notifiche."},
    PERM_OFI_ADD: {"label": "Registro OFI - Inserisci/Modifica", "description": "Inserimento e modifica manuale delle voci del registro OFI/NC (MOD.174)."},
}

# Binding route -> permesso (esteso man mano che le rotte vengono aggiunte).
_ROUTE_BINDINGS = {
    "gestione_specifiche:lista": PERM_VIEW,
    "gestione_specifiche:kpi": PERM_VIEW,
    "gestione_specifiche:dettaglio": PERM_VIEW,
    "gestione_specifiche:allegato_download": PERM_VIEW,
    "gestione_specifiche:nuova": PERM_COMPILA,
    "gestione_specifiche:modifica": PERM_COMPILA,
    "gestione_specifiche:avvia_flow_down": PERM_APPROVA,
    "gestione_specifiche:claim": PERM_CLAIM,
    "gestione_specifiche:mod133_compila": PERM_COMPILA,
    "gestione_specifiche:mod133_riga_add": PERM_COMPILA,
    "gestione_specifiche:mod133_chiudi": PERM_COMPILA,
    "gestione_specifiche:mod133_approva": PERM_APPROVA,
    "gestione_specifiche:applica_timbri": PERM_COMPILA,
    "gestione_specifiche:riga_genera_ofi": PERM_APPROVA,
    "gestione_specifiche:azione_ofi_approva": PERM_APPROVA,
    "gestione_specifiche:riga_documento_add": PERM_COMPILA,
    "gestione_specifiche:riga_documento_delete": PERM_COMPILA,
    # Registro OFI standalone (namespace registro_ofi, montato a /ofi-registro/).
    "registro_ofi:lista": PERM_VIEW,
    "registro_ofi:dettaglio": PERM_VIEW,
    "registro_ofi:nuovo": PERM_OFI_ADD,
    "registro_ofi:modifica": PERM_OFI_ADD,
    "gestione_specifiche:distribuzione_nuova": PERM_DISTRIBUISCI,
    "gestione_specifiche:scheda_storico": PERM_VIEW,
    "gestione_specifiche:storico_export_csv": PERM_VIEW,
    "gestione_specifiche:storico_export_pdf": PERM_VIEW,
    "gestione_specifiche:sospendi": PERM_SOSPENDI,
    "gestione_specifiche:ripristina": PERM_SOSPENDI,
    "gestione_specifiche:annulla": PERM_ANNULLA,
    "gestione_specifiche:ricerca": PERM_VIEW,
    "gestione_specifiche:guida": PERM_VIEW,
    "gestione_specifiche:composito_preview": PERM_VIEW,
    "gestione_specifiche:composito_thumb": PERM_VIEW,
    "gestione_specifiche:cartella_suggerita": PERM_VIEW,
    "gestione_specifiche:ai_precompila_mod133": PERM_COMPILA,
    "gestione_specifiche:ai_proponi_tag": PERM_COMPILA,
    "gestione_specifiche:ai_diff_mod133": PERM_COMPILA,
    # #6 — sezione Amministrazione (ACL PERM_ADMIN)
    "gestione_specifiche:admin_home": PERM_ADMIN,
    "gestione_specifiche:admin_cartelle": PERM_ADMIN,
    "gestione_specifiche:admin_cartella_edit": PERM_ADMIN,
    "gestione_specifiche:admin_cartella_delete": PERM_ADMIN,
    "gestione_specifiche:admin_auto_approva": PERM_ADMIN,
    "gestione_specifiche:admin_notifiche": PERM_ADMIN,
    "gestione_specifiche:admin_log": PERM_ADMIN,
    "gestione_specifiche:admin_specifiche": PERM_ADMIN,
    "gestione_specifiche:admin_specifica_riassegna": PERM_ADMIN,
    "gestione_specifiche:admin_timbri": PERM_ADMIN,
    "gestione_specifiche:admin_timbro_delete": PERM_ADMIN,
}

# Grant di default (CREATE-ONLY, l'admin può rifinire in /admin-portale/acl-canonico/).
# Mappatura proposta verso i ruoli legacy reali (admin/amministrazione/caporeparto/
# HR/qualita/utente) in attesa della conferma ruoli di processo (BLOCKER B2):
#   IT Admin -> admin · SGI/RDD -> qualita · DM -> amministrazione · capi -> caporeparto.
_ALL_PERMS = set(_CANONICAL.keys())
_ROLE_GRANTS = {
    "admin": _ALL_PERMS,
    "amministrazione": _ALL_PERMS,
    "qualita": _ALL_PERMS,
    "caporeparto": {PERM_VIEW, PERM_CLAIM, PERM_COMPILA},
}

# Azioni legacy -> permesso canonico (per i record Permesso di fallback).
_LEGACY_ACTIONS = {
    "gs_view": PERM_VIEW,
    "gs_claim": PERM_CLAIM,
    "gs_compila": PERM_COMPILA,
    "gs_approva": PERM_APPROVA,
    "gs_sospendi": PERM_SOSPENDI,
    "gs_annulla": PERM_ANNULLA,
    "gs_deroga": PERM_DEROGA,
    "gs_distribuisci": PERM_DISTRIBUISCI,
    "gs_admin": PERM_ADMIN,
    "gs_ofi_add": PERM_OFI_ADD,
}

_PULSANTI_DEFINITIONS = [
    {"modulo": MODULE, "codice": "gs_view", "label": "Gestione Specifiche",
     "url": "/gestione-specifiche/", "visible_topbar": True, "ui_order": 47},
]

# Subnav interna del modulo (tab sotto la barra principale), fedele al design
# Claude (handoff "Gestione Specifiche", sidebar "MODULO QUALITÀ", 7 voci).
# Tutte gated da PERM_VIEW. parent_code = app_name così get_subnav_nodes le
# associa alla sezione corrente. **Target distinti obbligatori**: il registry
# accorpa voci con lo stesso route_name/url_path → le "code di lavoro"
# per-specifica del design diventano viste filtrate dell'elenco (url distinte).
_BASE = "/gestione-specifiche/"
_SUBNAV_ITEMS = [
    {"code": "gs-sub-cruscotto", "label": "Cruscotto specifiche",
     "route_name": "gestione_specifiche:lista", "order": 10, "icon": "grid",
     "description": "Elenco e cruscotto delle specifiche."},
    {"code": "gs-sub-scheda", "label": "Scheda + MOD.133",
     "url_path": f"{_BASE}?stato=flow_down", "order": 20, "icon": "file-text",
     "description": "Specifiche in flow-down: apri per compilare scheda e MOD.133."},
    {"code": "gs-sub-approvazione", "label": "Approvazione MOD.133",
     "url_path": f"{_BASE}?stato=flow_down&vista=approvazione", "order": 30, "icon": "shield",
     "description": "Coda dei MOD.133 da approvare (separazione compilatore/approvatore)."},
    {"code": "gs-sub-distribuzione", "label": "Distribuzione copie",
     "url_path": f"{_BASE}?stato=in_validita", "order": 40, "icon": "box",
     "description": "Specifiche in validità: distribuzione ai reparti e tracciamento copie."},
    {"code": "gs-sub-storico", "label": "Storico specifica",
     "url_path": f"{_BASE}?storico=1", "order": 50, "icon": "clock",
     "description": "Archivio: specifiche superate/terminali e cronologia."},
    {"code": "gs-sub-kpi", "label": "Dashboard KPI qualità",
     "route_name": "gestione_specifiche:kpi", "order": 60, "icon": "bar-chart",
     "description": "Indicatori direzionali del flusso specifiche."},
    {"code": "gs-sub-inventario", "label": "Inventario componenti",
     "order": 70, "icon": "package", "coming": True,
     "description": "In arrivo: inventario componenti collegati alle specifiche."},
]
_SUBNAV_CODES = {s["code"] for s in _SUBNAV_ITEMS}


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
                          "note": "[GS_BOOTSTRAP] binding Gestione Specifiche",
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
            code="gestione-specifiche",
            defaults={"label": "Gestione Specifiche",
                      "route_name": "gestione_specifiche:lista",
                      "url_path": "", "section": "topbar",
                      "required_permission_code": PERM_VIEW, "order": 47,
                      "is_visible": True, "is_enabled": True, "icon": "file-text",
                      "description": "Flusso specifiche + MOD.133 (qualità ISO 9001/EN 9100)."},
        )
        changed = changed or created

        # 3b) subnav interna del modulo (7 voci come da design). "Inventario
        # componenti" è senza target → il registry la rende "in arrivo".
        for sub in _SUBNAV_ITEMS:
            _, created = NavigationItem.objects.update_or_create(
                code=sub["code"],
                defaults={"label": sub["label"],
                          "route_name": sub.get("route_name", ""),
                          "url_path": sub.get("url_path", ""),
                          "section": "subnav", "parent_code": MODULE,
                          "required_permission_code": PERM_VIEW, "order": sub["order"],
                          "is_visible": True, "is_enabled": True,
                          "icon": sub.get("icon", ""),
                          "description": sub.get("description", "")},
            )
            changed = changed or created
        # 3c) pulizia voci subnav del modulo non più previste (es. vecchie code)
        stale = NavigationItem.objects.filter(
            section="subnav", parent_code=MODULE
        ).exclude(code__in=_SUBNAV_CODES)
        if stale.exists():
            stale.delete()
            changed = True

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
                    defaults={"enabled": code in grants, "note": "[GS_BOOTSTRAP] default"},
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


def bootstrap_gestione_specifiche_acl(*, force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        MODULE,
        icona="file-text",
        section=MODULE,
        force=force,
        init_permessi=False,
        bootstrap_nav_fn=_bootstrap_canonical,
    )
