from __future__ import annotations

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "rilevazione_incidenti_acl_bootstrap_v3"

_PULSANTI_DEFINITIONS = [
    {"modulo": "rilevazione_incidenti", "codice": "rilev_inc_lista", "label": "Rilevazione Incidenti - Lista rilevazioni", "url": "/rilevazione-incidenti/", "hide": False},
    {"modulo": "rilevazione_incidenti", "codice": "rilev_inc_nuovo", "label": "Rilevazione Incidenti - Nuova rilevazione", "url": "/rilevazione-incidenti/nuovo/", "hide": False},
    {"modulo": "rilevazione_incidenti", "codice": "rilev_inc_dettaglio", "label": "Rilevazione Incidenti - Dettaglio rilevazione", "url": "/rilevazione-incidenti/dettaglio", "hide": True},
    {"modulo": "rilevazione_incidenti", "codice": "rilev_inc_modifica", "label": "Rilevazione Incidenti - Modifica rilevazione", "url": "/rilevazione-incidenti/modifica", "hide": True},
    {"modulo": "rilevazione_incidenti", "codice": "rilev_inc_statistiche", "label": "Rilevazione Incidenti - Statistiche", "url": "/rilevazione-incidenti/statistiche/", "hide": False},
    {"modulo": "rilevazione_incidenti", "codice": "rilev_inc_impostazioni", "label": "Rilevazione Incidenti - Impostazioni (admin)", "url": "/rilevazione-incidenti/impostazioni/", "hide": True},
    {"modulo": "rilevazione_incidenti", "codice": "rilev_inc_export_csv", "label": "Rilevazione Incidenti - Export CSV", "url": "/rilevazione-incidenti/export-csv/", "hide": True},
]


def bootstrap_rilevazione_incidenti_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "rilevazione_incidenti",
        icona="shield",
        section="rilevazione_incidenti_api",
        force=force,
    )
