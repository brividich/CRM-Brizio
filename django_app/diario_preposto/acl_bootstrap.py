from __future__ import annotations

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "diario_preposto_acl_bootstrap_v3"

_PULSANTI_DEFINITIONS = [
    {"modulo": "diario_preposto", "codice": "diario_preposto_lista", "label": "Diario Preposto - Lista", "url": "/diario-preposto/", "hide": False},
    {"modulo": "diario_preposto", "codice": "diario_preposto_nuovo", "label": "Diario Preposto - Nuovo inserimento", "url": "/diario-preposto/nuovo/", "hide": True},
    {"modulo": "diario_preposto", "codice": "diario_preposto_ispezioni", "label": "Diario Preposto - Ispezioni periodiche", "url": "/diario-preposto/ispezioni/", "hide": True},
    {"modulo": "diario_preposto", "codice": "diario_preposto_ispezione_nuova", "label": "Diario Preposto - Nuova ispezione periodica", "url": "/diario-preposto/ispezioni/nuova/", "hide": True},
    {"modulo": "diario_preposto", "codice": "diario_preposto_dettaglio", "label": "Diario Preposto - Dettaglio (API)", "url": "/diario-preposto/dettaglio", "hide": True},
    {"modulo": "diario_preposto", "codice": "diario_preposto_modifica", "label": "Diario Preposto - Modifica (API)", "url": "/diario-preposto/modifica", "hide": True},
    {"modulo": "diario_preposto", "codice": "diario_preposto_elimina", "label": "Diario Preposto - Elimina (API)", "url": "/diario-preposto/elimina", "hide": True},
    {"modulo": "diario_preposto", "codice": "diario_preposto_allegato_upload", "label": "Diario Preposto - Upload allegato (API)", "url": "/diario-preposto/api/allegato/upload/", "hide": True},
    {"modulo": "diario_preposto", "codice": "diario_preposto_allegato_delete", "label": "Diario Preposto - Elimina allegato (API)", "url": "/diario-preposto/api/allegato/delete/", "hide": True},
]


def bootstrap_diario_preposto_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "diario_preposto",
        icona="shield",
        section="diario_preposto_api",
        force=force,
    )
