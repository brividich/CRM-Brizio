from __future__ import annotations

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

# Bump alla v4: permesso canonico dell'area impostazioni tickets. Prima i gate
# delle impostazioni (`ticket_impostazioni`, `api_impostazioni`, `api_cerca_utenti`,
# `api_test_sp`, `api_import_csv`) guardavano solo `is_legacy_admin()` — vero
# unicamente per il ruolo "admin", per giunta senza bypass superuser — quindi
# nessun altro ruolo poteva essere abilitato dal modulo permessi.
_BOOTSTRAP_CACHE_KEY = "tickets_acl_bootstrap_v4"

MODULE = "tickets"
PERM_IMPOSTAZIONI_MANAGE = "tickets.impostazioni.manage"

# Permesso "solo definizione", senza RoutePermissionBinding: con
# ACL_STRICT_CANONICAL=True un binding di route negherebbe l'intera pagina a
# tutti i ruoli senza grant esplicito. Il cancello resta in-view e additivo.
_CANONICAL = {
    PERM_IMPOSTAZIONI_MANAGE: {
        "label": "Tickets - Impostazioni modulo",
        "description": (
            "Configurazione del modulo tickets (tipi, ACL, SharePoint, import CSV, "
            "ricerca utenti): area riservata alla gestione."
        ),
    },
}

# Grant di default create-only: solo "admin", che passa comunque dal bypass.
_ROLE_GRANTS = {"admin": {PERM_IMPOSTAZIONI_MANAGE}}


def _bootstrap_canonical() -> bool:
    """Registra il permesso canonico delle impostazioni + grant di default."""
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
                    defaults={"enabled": code in grants, "note": "[TICKETS_BOOTSTRAP] default"},
                )
                changed = changed or created
    return changed

_PULSANTI_DEFINITIONS = [
    {"modulo": "tickets", "codice": "tickets_dashboard", "label": "Tickets - Dashboard", "url": "/tickets/", "hide": False},
    {"modulo": "tickets", "codice": "tickets_nuovo", "label": "Tickets - Nuovo ticket", "url": "/tickets/nuovo/", "hide": True},
    {"modulo": "tickets", "codice": "tickets_gestione", "label": "Tickets - Lista gestione", "url": "/tickets/gestione/", "hide": True},
    {"modulo": "tickets", "codice": "tickets_impostazioni", "label": "Tickets - Impostazioni", "url": "/tickets/impostazioni/", "hide": True},
    {"modulo": "tickets", "codice": "tickets_api_commento", "label": "Tickets - API commento", "url": "/tickets/api/commento/", "hide": True},
    {"modulo": "tickets", "codice": "tickets_api_allegato", "label": "Tickets - API allegato", "url": "/tickets/api/allegato/", "hide": True},
    {"modulo": "tickets", "codice": "tickets_api_stato", "label": "Tickets - API stato", "url": "/tickets/api/stato/", "hide": True},
    {"modulo": "tickets", "codice": "tickets_api_assegna", "label": "Tickets - API assegna", "url": "/tickets/api/assegna/", "hide": True},
    {"modulo": "tickets", "codice": "tickets_api_bulk", "label": "Tickets - API bulk", "url": "/tickets/api/bulk/", "hide": True},
    {"modulo": "tickets", "codice": "tickets_api_import_csv", "label": "Tickets - API import CSV", "url": "/tickets/api/import-csv/", "hide": True},
    {"modulo": "tickets", "codice": "tickets_api_test_sp", "label": "Tickets - API test SharePoint", "url": "/tickets/api/test-sp/", "hide": True},
    {"modulo": "tickets", "codice": "tickets_api_asset", "label": "Tickets - API asset", "url": "/tickets/api/asset/", "hide": True},
    {"modulo": "tickets", "codice": "tickets_api_cerca_utenti", "label": "Tickets - API cerca utenti", "url": "/tickets/api/cerca-utenti/", "hide": True},
    {"modulo": "tickets", "codice": "tickets_api_assets_autocomplete", "label": "Tickets - API assets autocomplete", "url": "/tickets/api/assets-autocomplete/", "hide": True},
]


def bootstrap_tickets_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "tickets",
        icona="ticket",
        section="tickets_api",
        force=force,
        bootstrap_nav_fn=_bootstrap_canonical,
    )
