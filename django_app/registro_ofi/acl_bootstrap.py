"""Bootstrap ACL v2 canonico del modulo Registro OFI / NC.

Il registro ha permessi suoi: chi consulta il registro e la dashboard
(``PERM_OFI_VIEW``) e chi vede solo le voci di cui è responsabile
(``PERM_OFI_MIE``, concesso a tutti: la vista filtra per utente). L'inserimento
resta ``gestione_specifiche.registroofi.add`` (il modello vive in
``gestione_specifiche``).

Al primo avvio ``PERM_OFI_VIEW`` copia i grant di ruolo, utente e gruppo di
``gestione_specifiche.specifica.view``, che fino ad allora apriva il registro:
nessuno perde l'accesso. Solo creazione: le modifiche fatte in Admin › ACL restano.
"""
from __future__ import annotations

import logging

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap
from gestione_specifiche.acl_bootstrap import PERM_OFI_ADD, PERM_VIEW as PERM_GS_VIEW

logger = logging.getLogger(__name__)

MODULE = "registro_ofi"
# v1: modulo dedicato (dashboard, le mie voci, permessi propri).
_BOOTSTRAP_CACHE_KEY = "registro_ofi_acl_bootstrap_v1"

PERM_OFI_VIEW = "registro_ofi.registro.view"
PERM_OFI_MIE = "registro_ofi.mie.view"

_CANONICAL = {
    PERM_OFI_VIEW: {"label": "Registro OFI - Consulta registro e dashboard",
                    "description": "Dashboard, registro completo (MOD.174), cruscotto ed export delle voci OFI/NC."},
    PERM_OFI_MIE: {"label": "Registro OFI - Le mie voci",
                   "description": "Voci di cui si è responsabili: scheda, avanzamento PDCA ed evidenze."},
}

# Le viste ripetono il controllo fine: dettaglio, avanzamento ed evidenze sono di chi
# consulta il registro oppure del responsabile della voce.
_ROUTE_BINDINGS = {
    "registro_ofi:home": PERM_OFI_MIE,
    "registro_ofi:mie": PERM_OFI_MIE,
    "registro_ofi:guida": PERM_OFI_MIE,
    "registro_ofi:dettaglio": PERM_OFI_MIE,
    "registro_ofi:avanza": PERM_OFI_MIE,
    "registro_ofi:riapri": PERM_OFI_MIE,
    "registro_ofi:allegato_carica": PERM_OFI_MIE,
    "registro_ofi:allegato_scarica": PERM_OFI_MIE,
    "registro_ofi:lista": PERM_OFI_VIEW,
    "registro_ofi:cruscotto": PERM_OFI_VIEW,
    "registro_ofi:nuovo": PERM_OFI_ADD,
    "registro_ofi:modifica": PERM_OFI_ADD,
}

_NAV_CODE = "ofi_registro"


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _copia_grant_view(PermissionDefinition, RolePermissionGrant, UserPermissionGrant, GroupPermissionGrant) -> bool:
    """Chi apriva il registro con ``specifica.view`` lo apre anche con il permesso nuovo."""
    changed = False
    if not PermissionDefinition.objects.filter(code=PERM_GS_VIEW).exists():
        return False
    nota = "[OFI_BOOTSTRAP] da gestione_specifiche.specifica.view"
    for g in RolePermissionGrant.objects.filter(permission_id=PERM_GS_VIEW, enabled=True):
        _, created = RolePermissionGrant.objects.get_or_create(
            legacy_role_id=g.legacy_role_id, permission_id=PERM_OFI_VIEW, defaults={"enabled": True, "note": nota})
        changed = changed or created
    for g in UserPermissionGrant.objects.filter(permission_id=PERM_GS_VIEW, enabled=True):
        _, created = UserPermissionGrant.objects.get_or_create(
            legacy_user_id=g.legacy_user_id, permission_id=PERM_OFI_VIEW, defaults={"enabled": True, "note": nota})
        changed = changed or created
    for g in GroupPermissionGrant.objects.filter(permission_id=PERM_GS_VIEW, enabled=True):
        _, created = GroupPermissionGrant.objects.get_or_create(
            group_id=g.group_id, permission_id=PERM_OFI_VIEW, defaults={"enabled": True, "note": nota})
        changed = changed or created
    return changed


def _bootstrap_canonical() -> bool:
    from core.legacy_models import Ruolo
    from core.models import (
        GroupPermissionGrant, PermissionDefinition, RolePermissionGrant, RoutePermissionBinding,
        UserPermissionGrant,
    )
    from core.navigation_registry import bump_navigation_registry_version, ensure_navigation_item

    changed = False
    with transaction.atomic():
        nuovi = set()
        for code, payload in _CANONICAL.items():
            _, created = PermissionDefinition.objects.get_or_create(
                code=code,
                defaults={"module": MODULE, "label": payload["label"],
                          "description": payload["description"], "is_active": True},
            )
            if created:
                nuovi.add(code)
            changed = changed or created

        for route_name, code in _ROUTE_BINDINGS.items():
            binding, created = RoutePermissionBinding.objects.get_or_create(
                route_name=route_name, path_pattern="",
                defaults={"match_strategy": RoutePermissionBinding.MATCH_EXACT,
                          "permission_id": code, "source_app": MODULE,
                          "note": "[OFI_BOOTSTRAP] binding Registro OFI",
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

        # La voce di menu esiste già (core 0069/0070): ora apre la dashboard del modulo.
        _, nav_changed = ensure_navigation_item(
            _NAV_CODE,
            {"label": "Registro OFI", "route_name": "registro_ofi:home", "url_path": "",
             "section": "topbar", "required_permission_code": PERM_OFI_VIEW, "order": 63,
             "is_visible": True, "is_enabled": True, "icon": "clipboard",
             "description": "Registro OFI / NC (MOD.174): dashboard, registro, le mie voci."},
        )
        changed = changed or nav_changed

        if PERM_OFI_VIEW in nuovi:
            changed = _copia_grant_view(PermissionDefinition, RolePermissionGrant, UserPermissionGrant,
                                        GroupPermissionGrant) or changed

        roles = {int(r.id): _norm(r.nome) for r in Ruolo.objects.all()}
        for rid in roles:
            _, created = RolePermissionGrant.objects.get_or_create(
                legacy_role_id=rid, permission_id=PERM_OFI_MIE,
                defaults={"enabled": True, "note": "[OFI_BOOTSTRAP] default: filtrato per utente"},
            )
            changed = changed or created
            _, created = RolePermissionGrant.objects.get_or_create(
                legacy_role_id=rid, permission_id=PERM_OFI_VIEW,
                defaults={"enabled": roles[rid] == "admin", "note": "[OFI_BOOTSTRAP] default"},
            )
            changed = changed or created

    if changed:
        try:
            bump_navigation_registry_version()
        except Exception:
            pass
    return changed


def bootstrap_registro_ofi_acl(*, force: bool = False) -> None:
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
