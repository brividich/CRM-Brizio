from __future__ import annotations

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "anomalie_acl_bootstrap_v2"

_PULSANTI_DEFINITIONS = [
    {"modulo": "anomalie", "codice": "anomalie_gestione", "label": "Anomalie - Gestione", "url": "/gestione-anomalie", "hide": False},
    {"modulo": "anomalie", "codice": "anomalie_nuova", "label": "Anomalie - Nuova segnalazione", "url": "/gestione-anomalie/nuova-segnalazione", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_configurazione", "label": "Anomalie - Configurazione", "url": "/gestione-anomalie/configurazione", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_statistiche", "label": "Anomalie - Statistiche", "url": "/gestione-anomalie/statistiche", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_ordini", "label": "Anomalie - API ordini", "url": "/api/anomalie/ordini", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_anomalie", "label": "Anomalie - API anomalie", "url": "/api/anomalie/anomalie", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_salva", "label": "Anomalie - API salva", "url": "/api/anomalie/salva", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_notifica_op", "label": "Anomalie - API notifica OP", "url": "/api/anomalie/notifica-op", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_seriali_op", "label": "Anomalie - API seriali OP", "url": "/api/anomalie/seriali-op", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_sync", "label": "Anomalie - API sync", "url": "/api/anomalie/sync", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_campi", "label": "Anomalie - API campi", "url": "/api/anomalie/campi", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_allegati", "label": "Anomalie - API allegati", "url": "/api/anomalie/allegati", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_statistiche", "label": "Anomalie - API statistiche", "url": "/api/anomalie/statistiche", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_report", "label": "Anomalie - API report", "url": "/api/anomalie/report", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_export_csv", "label": "Anomalie - Export CSV", "url": "/export-csv", "hide": True},
]


def bootstrap_anomalie_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "anomalie",
        icona="alert-triangle",
        section="anomalie_api",
        force=force,
    )
