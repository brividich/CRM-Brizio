from __future__ import annotations

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "notizie_acl_bootstrap_v4"

_PULSANTI_DEFINITIONS = [
    {"modulo": "notizie", "codice": "notizie_lista", "label": "Notizie - Lista", "url": "/notizie/", "hide": False},
    {"modulo": "notizie", "codice": "notizie_obbligatorie", "label": "Notizie - Obbligatorie", "url": "/notizie/obbligatorie/", "hide": False},
    {"modulo": "notizie", "codice": "notizie_report", "label": "Notizie - Report HR", "url": "/notizie/report/", "hide": False},
    {"modulo": "notizie", "codice": "notizie_dashboard", "label": "Notizie - Dashboard gestione", "url": "/notizie/dashboard/", "hide": True},
    {"modulo": "notizie", "codice": "notizie_conferma", "label": "Notizie - Conferma lettura (API)", "url": "/notizie/conferma", "hide": True},
    {"modulo": "notizie", "codice": "notizie_report_csv", "label": "Notizie - Export CSV (API)", "url": "/notizie/report/export-csv/", "hide": True},
    {"modulo": "notizie", "codice": "notizie_gestione", "label": "Notizie - Gestione admin", "url": "/notizie/gestione/", "hide": True},
    {"modulo": "notizie", "codice": "notizie_dashboard_nuova", "label": "Notizie - Nuova notizia", "url": "/notizie/dashboard/nuova/", "hide": True},
]


def bootstrap_notizie_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "notizie",
        icona="bell",
        section="notizie_api",
        force=force,
    )
