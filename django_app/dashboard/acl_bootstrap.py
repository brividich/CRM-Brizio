from __future__ import annotations

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "dashboard_acl_bootstrap_v3"

_PULSANTI_DEFINITIONS = [
    {"modulo": "dashboard", "codice": "dashboard_home", "label": "Dashboard - Home", "url": "/dashboard", "hide": False},
    {"modulo": "dashboard", "codice": "dashboard_richieste", "label": "Dashboard - Richieste", "url": "/richieste", "hide": True},
    {"modulo": "dashboard", "codice": "dashboard_anomalie_menu", "label": "Dashboard - Menu anomalie", "url": "/anomalie-menu", "hide": True},
    {"modulo": "dashboard", "codice": "dashboard_scheda_dipendente", "label": "Dashboard - Scheda dipendente", "url": "/scheda-dipendente", "hide": False},
    {"modulo": "dashboard", "codice": "dashboard_api_toggle", "label": "Dashboard - API toggle widget", "url": "/api/my-dashboard-toggle", "hide": True},
    {"modulo": "dashboard", "codice": "dashboard_api_layout", "label": "Dashboard - API layout widget", "url": "/api/my-dashboard-layout", "hide": True},
    {"modulo": "dashboard", "codice": "dashboard_api_employee_data", "label": "Dashboard - API employee board data", "url": "/api/employee-board/data", "hide": True},
    {"modulo": "dashboard", "codice": "dashboard_scheda_pdf", "label": "Dashboard - Scheda dipendente PDF", "url": "/scheda-dipendente/pdf", "hide": True},
    {"modulo": "dashboard", "codice": "dashboard_api_employee_layout", "label": "Dashboard - API employee board layout", "url": "/api/employee-board/layout", "hide": True},
    {"modulo": "dashboard", "codice": "dashboard_api_employee_widget_config", "label": "Dashboard - API employee board widget config", "url": "/api/employee-board/widget-config", "hide": True},
]


def bootstrap_dashboard_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "dashboard",
        icona="home",
        section="dashboard_api",
        force=force,
    )
