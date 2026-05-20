from __future__ import annotations

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "fornitori_acl_bootstrap_v2"

_PULSANTI_DEFINITIONS = [
    {"modulo": "fornitori", "codice": "fornitori_index", "label": "Fornitori - Dashboard", "url": "/fornitori/", "hide": False},
    {"modulo": "fornitori", "codice": "fornitori_list", "label": "Fornitori - Lista", "url": "/fornitori/elenco/", "hide": False},
    {"modulo": "fornitori", "codice": "fornitori_create", "label": "Fornitori - Nuovo fornitore", "url": "/fornitori/nuovo/", "hide": True},
]


def bootstrap_fornitori_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "fornitori",
        icona="briefcase",
        section="fornitori_api",
        force=force,
    )
