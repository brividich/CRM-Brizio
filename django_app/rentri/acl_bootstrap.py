from __future__ import annotations

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "rentri_acl_bootstrap_v2"

_PULSANTI_DEFINITIONS = [
    {"modulo": "rentri", "codice": "rentri_menu", "label": "RENTRI - Registro rifiuti", "url": "/rentri/", "hide": False},
    {"modulo": "rentri", "codice": "rentri_carico", "label": "RENTRI - Carico", "url": "/rentri/carico/", "hide": True},
    {"modulo": "rentri", "codice": "rentri_scarico_orig", "label": "RENTRI - Scarico originale", "url": "/rentri/scarico-originale/", "hide": True},
    {"modulo": "rentri", "codice": "rentri_scarico_eff", "label": "RENTRI - Scarico effettivo", "url": "/rentri/scarico-effettivo/", "hide": True},
    {"modulo": "rentri", "codice": "rentri_rettifica", "label": "RENTRI - Rettifica scarico", "url": "/rentri/rettifica-scarico/", "hide": True},
    {"modulo": "rentri", "codice": "rentri_elenco", "label": "RENTRI - Elenco registri", "url": "/rentri/elenco/", "hide": True},
    {"modulo": "rentri", "codice": "rentri_import_preview", "label": "RENTRI - Import preview", "url": "/rentri/import/preview/", "hide": True},
    {"modulo": "rentri", "codice": "rentri_import_confirm", "label": "RENTRI - Import confirm", "url": "/rentri/import/confirm/", "hide": True},
    {"modulo": "rentri", "codice": "rentri_export_pdf", "label": "RENTRI - Export PDF", "url": "/rentri/export/pdf/", "hide": True},
    {"modulo": "rentri", "codice": "rentri_sync_pull", "label": "RENTRI - Sync pull API", "url": "/rentri/api/sync/pull", "hide": True},
]


def bootstrap_rentri_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "rentri",
        icona="trash-2",
        section="rentri_api",
        force=force,
    )
