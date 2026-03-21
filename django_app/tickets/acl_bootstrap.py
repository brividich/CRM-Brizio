from __future__ import annotations

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "tickets_acl_bootstrap_v3"

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
    )
