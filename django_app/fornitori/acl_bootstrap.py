from __future__ import annotations

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "fornitori_acl_bootstrap_v2"

_PULSANTI_DEFINITIONS = [
    {
        "modulo": "fornitori",
        "codice": "fornitori_index",
        "label": "Fornitori - Dashboard",
        "url": "route:fornitori:index",
        "visible_topbar": True,
        "ui_order": 360,
    },
    {
        "modulo": "fornitori",
        "codice": "fornitori_list",
        "label": "Fornitori - Lista",
        "url": "route:fornitori:fornitori_list",
        "visible_topbar": False,
    },
    {
        "modulo": "fornitori",
        "codice": "fornitori_create",
        "label": "Fornitori - Nuovo fornitore",
        "url": "route:fornitori:fornitore_create",
        "visible_topbar": False,
    },
    {
        "modulo": "fornitori",
        "codice": "fornitore_detail",
        "label": "Fornitori - Scheda fornitore",
        "url": "route:fornitori:fornitore_detail",
        "visible_topbar": False,
    },
    {
        "modulo": "fornitori",
        "codice": "fornitore_edit",
        "label": "Fornitori - Modifica fornitore",
        "url": "route:fornitori:fornitore_edit",
        "visible_topbar": False,
    },
    {
        "modulo": "fornitori",
        "codice": "fornitore_toggle_active",
        "label": "Fornitori - Attiva/disattiva",
        "url": "route:fornitori:fornitore_toggle_active",
        "visible_topbar": False,
    },
    {
        "modulo": "fornitori",
        "codice": "fornitore_documento_add",
        "label": "Fornitori - Aggiungi documento",
        "url": "route:fornitori:fornitore_documento_add",
        "visible_topbar": False,
    },
    {
        "modulo": "fornitori",
        "codice": "fornitore_documento_delete",
        "label": "Fornitori - Elimina documento",
        "url": "route:fornitori:fornitore_documento_delete",
        "visible_topbar": False,
    },
    {
        "modulo": "fornitori",
        "codice": "fornitore_ordine_add",
        "label": "Fornitori - Aggiungi ordine",
        "url": "route:fornitori:fornitore_ordine_add",
        "visible_topbar": False,
    },
    {
        "modulo": "fornitori",
        "codice": "fornitore_ordine_stato",
        "label": "Fornitori - Cambia stato ordine",
        "url": "route:fornitori:fornitore_ordine_stato",
        "visible_topbar": False,
    },
    {
        "modulo": "fornitori",
        "codice": "fornitore_valutazione_add",
        "label": "Fornitori - Aggiungi valutazione",
        "url": "route:fornitori:fornitore_valutazione_add",
        "visible_topbar": False,
    },
    {
        "modulo": "fornitori",
        "codice": "fornitore_valutazione_delete",
        "label": "Fornitori - Elimina valutazione",
        "url": "route:fornitori:fornitore_valutazione_delete",
        "visible_topbar": False,
    },
    {
        "modulo": "fornitori",
        "codice": "fornitore_asset_add",
        "label": "Fornitori - Collega asset",
        "url": "route:fornitori:fornitore_asset_add",
        "visible_topbar": False,
    },
    {
        "modulo": "fornitori",
        "codice": "fornitore_asset_remove",
        "label": "Fornitori - Scollega asset",
        "url": "route:fornitori:fornitore_asset_remove",
        "visible_topbar": False,
    },
]


def bootstrap_fornitori_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "fornitori",
        icona="briefcase",
        section="fornitori",
        force=force,
    )
