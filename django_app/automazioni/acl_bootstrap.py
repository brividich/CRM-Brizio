from __future__ import annotations

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "automazioni_acl_bootstrap_v3"

_PULSANTI_DEFINITIONS = [
    {"modulo": "automazioni", "codice": "automazioni_regole", "label": "Automazioni - Lista regole", "url": "/automazioni/regole/", "hide": False},
    {"modulo": "automazioni", "codice": "automazioni_sorgenti", "label": "Automazioni - Sorgenti", "url": "/automazioni/sorgenti/", "hide": True},
    {"modulo": "automazioni", "codice": "automazioni_contenuti", "label": "Automazioni - Contenuti", "url": "/automazioni/contenuti/", "hide": True},
    {"modulo": "automazioni", "codice": "automazioni_queue", "label": "Automazioni - Coda esecuzione", "url": "/automazioni/queue/", "hide": True},
    {"modulo": "automazioni", "codice": "automazioni_run_log", "label": "Automazioni - Log esecuzione", "url": "/automazioni/run-log/", "hide": True},
    {"modulo": "automazioni", "codice": "automazioni_rule_create", "label": "Automazioni - Nuova regola", "url": "/automazioni/regole/nuova/", "hide": True},
    {"modulo": "automazioni", "codice": "automazioni_rule_import", "label": "Automazioni - Importa package", "url": "/automazioni/regole/importa-package/", "hide": True},
    {"modulo": "automazioni", "codice": "automazioni_rule_import_result", "label": "Automazioni - Risultato importazione", "url": "/automazioni/regole/importa-package/risultato/", "hide": True},
]


def bootstrap_automazioni_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "automazioni",
        icona="zap",
        section="automazioni_api",
        force=force,
    )
