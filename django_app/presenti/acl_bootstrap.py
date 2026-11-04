"""Bootstrap ACL v2 canonico del modulo Presenti in azienda.

Permessi:

- ``PERM_LISTA``: lista live dei presenti, PDF e guida. Concesso a **tutti i ruoli**
  (decisione del 04/11/2026: la lista è visibile a tutti gli utenti del portale).
- ``PERM_APPELLO``: avviare, contare e chiudere un appello di evacuazione. A tutti
  i ruoli: in emergenza chiunque deve poter aprire l'appello.
- ``PERM_USCITE``: uscite non timbrate della propria squadra (la vista filtra per
  capo). A tutti i ruoli.
- ``PERM_USCITE_TUTTE``: uscite non timbrate di tutta l'azienda. Solo admin.
- ``PERM_IMPOSTAZIONI``: impostazioni del modulo (pubblicazione PDF, avvisi). Solo admin.

Solo creazione: le modifiche fatte in Admin › ACL restano.
"""
from __future__ import annotations

import logging

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

logger = logging.getLogger(__name__)

MODULE = "presenti"
_BOOTSTRAP_CACHE_KEY = "presenti_acl_bootstrap_v1"

PERM_LISTA = "presenti.lista.view"
PERM_APPELLO = "presenti.appello.manage"
PERM_USCITE = "presenti.uscite.view"
PERM_USCITE_TUTTE = "presenti.uscite.tutte"
PERM_IMPOSTAZIONI = "presenti.impostazioni.manage"

_CANONICAL = {
    PERM_LISTA: {"label": "Presenti in azienda - Lista live",
                 "description": "Chi è in azienda adesso (timbrature Solari), pallino «In azienda», PDF."},
    PERM_APPELLO: {"label": "Presenti in azienda - Appello di evacuazione",
                   "description": "Avviare l'appello, spuntare le persone contate al punto di raccolta, chiuderlo."},
    PERM_USCITE: {"label": "Presenti in azienda - Uscite non timbrate (squadra)",
                  "description": "Giornate con entrata senza uscita delle persone di cui si è capo."},
    PERM_USCITE_TUTTE: {"label": "Presenti in azienda - Uscite non timbrate (tutti)",
                        "description": "Giornate con entrata senza uscita di tutta l'azienda."},
    PERM_IMPOSTAZIONI: {"label": "Presenti in azienda - Impostazioni",
                        "description": "Pubblicazione del PDF su SharePoint e avvisi delle uscite non timbrate."},
}

_ROUTE_BINDINGS = {
    "presenti:home": PERM_LISTA,
    "presenti:lista_parziale": PERM_LISTA,
    "presenti:pdf": PERM_LISTA,
    "presenti:guida": PERM_LISTA,
    "presenti:appello": PERM_APPELLO,
    "presenti:appello_avvia": PERM_APPELLO,
    "presenti:appello_parziale": PERM_APPELLO,
    "presenti:appello_spunta": PERM_APPELLO,
    "presenti:appello_chiudi": PERM_APPELLO,
    "presenti:appello_stampa": PERM_APPELLO,
    "presenti:uscite": PERM_USCITE,
    "presenti:impostazioni": PERM_IMPOSTAZIONI,
}

# A tutti i ruoli (True) o solo ad admin (False).
_DEFAULT_TUTTI = {
    PERM_LISTA: True,
    PERM_APPELLO: True,
    PERM_USCITE: True,
    PERM_USCITE_TUTTE: False,
    PERM_IMPOSTAZIONI: False,
}

_NAV_CODE = "presenti"


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
                          "note": "[PRESENTI_BOOTSTRAP] binding Presenti in azienda",
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
            "label": "Presenti in azienda", "route_name": "presenti:home", "url_path": "",
            "section": "topbar", "required_permission_code": PERM_LISTA, "order": 45,
            "is_visible": True, "is_enabled": True, "icon": "users",
            "description": "Chi è in azienda adesso, appello di evacuazione, uscite non timbrate.",
        }
        categoria = ModuleCategory.objects.filter(key="persone").first()
        if categoria is not None:
            defaults_nav["category"] = categoria
        _, nav_changed = ensure_navigation_item(_NAV_CODE, defaults_nav)
        changed = changed or nav_changed

        roles = {int(r.id): _norm(r.nome) for r in Ruolo.objects.all()}
        for rid, nome in roles.items():
            for code, tutti in _DEFAULT_TUTTI.items():
                _, created = RolePermissionGrant.objects.get_or_create(
                    legacy_role_id=rid, permission_id=code,
                    defaults={"enabled": tutti or nome == "admin", "note": "[PRESENTI_BOOTSTRAP] default"},
                )
                changed = changed or created

    if changed:
        try:
            bump_navigation_registry_version()
        except Exception:
            pass
    return changed


def bootstrap_presenti_acl(*, force: bool = False) -> None:
    run_bootstrap(
        [],
        _BOOTSTRAP_CACHE_KEY,
        MODULE,
        icona="users",
        section=MODULE,
        force=force,
        init_permessi=False,
        bootstrap_nav_fn=_bootstrap_canonical,
    )
