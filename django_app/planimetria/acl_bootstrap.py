from __future__ import annotations

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "planimetria_acl_bootstrap_v2"

_PULSANTI_DEFINITIONS = [
    {"modulo": "planimetria", "codice": "planimetria_mappa", "label": "Planimetria - Mappa", "url": "/planimetria/", "hide": False},
    {"modulo": "planimetria", "codice": "planimetria_editor", "label": "Planimetria - Editor", "url": "/planimetria/editor/", "hide": True},
]


def bootstrap_planimetria_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "planimetria",
        icona="map",
        section="planimetria_api",
        force=force,
    )
