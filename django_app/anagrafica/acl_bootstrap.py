from __future__ import annotations

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "anagrafica_acl_bootstrap_v2"

_PULSANTI_DEFINITIONS = [
    {"modulo": "anagrafica", "codice": "anagrafica_index", "label": "Anagrafica - Dashboard", "url": "/anagrafica/", "hide": False},
    {"modulo": "anagrafica", "codice": "anagrafica_dipendenti", "label": "Anagrafica - Lista dipendenti", "url": "/anagrafica/dipendenti/", "hide": False},
    {"modulo": "anagrafica", "codice": "anagrafica_fornitori", "label": "Anagrafica - Lista fornitori", "url": "/anagrafica/fornitori/", "hide": False},
    {"modulo": "anagrafica", "codice": "anagrafica_fornitore_create", "label": "Anagrafica - Nuovo fornitore", "url": "/anagrafica/fornitori/nuovo/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_ruoli_operativi", "label": "Anagrafica - Ruoli operativi", "url": "/anagrafica/ruoli-operativi/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_mansioni", "label": "Anagrafica - Mansioni catalogo", "url": "/anagrafica/mansioni/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_qualifiche", "label": "Anagrafica - Qualifiche catalogo", "url": "/anagrafica/qualifiche/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_widget_layout", "label": "Anagrafica - API widget layout", "url": "/anagrafica/api/widget-layout/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_impostazioni_widget", "label": "Anagrafica - Impostazioni permessi widget", "url": "/anagrafica/impostazioni-widget/", "hide": True},
]


def bootstrap_anagrafica_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "anagrafica",
        icona="users",
        section="anagrafica_api",
        force=force,
    )
