from __future__ import annotations

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "assets_acl_bootstrap_v3"

_PULSANTI_DEFINITIONS = [
    {"modulo": "assets", "codice": "assets_list", "label": "Assets - Lista asset", "url": "/assets/", "hide": False},
    {"modulo": "assets", "codice": "assets_new", "label": "Assets - Nuovo asset", "url": "/assets/new/", "hide": True},
    {"modulo": "assets", "codice": "assets_view", "label": "Assets - Dettaglio asset", "url": "/assets/view/", "hide": True},
    {"modulo": "assets", "codice": "assets_edit", "label": "Assets - Modifica asset", "url": "/assets/edit/", "hide": True},
    {"modulo": "assets", "codice": "assets_components", "label": "Assets - Componenti", "url": "/assets/componenti/", "hide": True},
    {"modulo": "assets", "codice": "assets_components_new", "label": "Assets - Nuovo componente", "url": "/assets/componenti/new/", "hide": True},
    {"modulo": "assets", "codice": "assets_components_edit", "label": "Assets - Modifica componente", "url": "/assets/componenti/edit/", "hide": True},
    {"modulo": "assets", "codice": "assets_deadlines", "label": "Assets - Scadenze amministrative", "url": "/assets/scadenze/", "hide": True},
    {"modulo": "assets", "codice": "assets_deadlines_new", "label": "Assets - Nuova scadenza amministrativa", "url": "/assets/scadenze/new/", "hide": True},
    {"modulo": "assets", "codice": "assets_deadlines_edit", "label": "Assets - Modifica scadenza amministrativa", "url": "/assets/scadenze/edit/", "hide": True},
    {"modulo": "assets", "codice": "assets_maintenance_templates", "label": "Assets - Template manutenzione", "url": "/assets/manutenzione/templates/", "hide": True},
    {"modulo": "assets", "codice": "assets_maintenance_templates_new", "label": "Assets - Nuovo template manutenzione", "url": "/assets/manutenzione/templates/new/", "hide": True},
    {"modulo": "assets", "codice": "assets_maintenance_templates_edit", "label": "Assets - Modifica template manutenzione", "url": "/assets/manutenzione/templates/edit/", "hide": True},
    {"modulo": "assets", "codice": "assets_maintenance_rules", "label": "Assets - Regole manutenzione", "url": "/assets/manutenzione/regole/", "hide": True},
    {"modulo": "assets", "codice": "assets_maintenance_rules_new", "label": "Assets - Nuova regola manutenzione", "url": "/assets/manutenzione/regole/new/", "hide": True},
    {"modulo": "assets", "codice": "assets_maintenance_rules_edit", "label": "Assets - Modifica regola manutenzione", "url": "/assets/manutenzione/regole/edit/", "hide": True},
    {"modulo": "assets", "codice": "assets_maintenance_schedule", "label": "Assets - Prossime manutenzioni", "url": "/assets/manutenzione/prossime/", "hide": True},
    {"modulo": "assets", "codice": "assets_assistance_contracts", "label": "Assets - Contratti assistenza", "url": "/assets/manutenzione/contratti/", "hide": True},
    {"modulo": "assets", "codice": "assets_asset_maintenance_rules", "label": "Assets - Regole manutenzione asset", "url": "/assets/manutenzione/asset-rules/", "hide": True},
    {"modulo": "assets", "codice": "assets_asset_maintenance_overrides_new", "label": "Assets - Nuovo override regola asset", "url": "/assets/manutenzione/asset-rule-overrides/new/", "hide": True},
    {"modulo": "assets", "codice": "assets_asset_maintenance_overrides_edit", "label": "Assets - Modifica override regola asset", "url": "/assets/manutenzione/asset-rule-overrides/edit/", "hide": True},
    {"modulo": "assets", "codice": "assets_asset_maintenance_overrides_reset", "label": "Assets - Ripristino override regola asset", "url": "/assets/manutenzione/asset-rule-overrides/reset/", "hide": True},
    {"modulo": "assets", "codice": "assets_work_machines", "label": "Assets - Lista macchinari", "url": "/assets/work-machines/", "hide": False},
    {"modulo": "assets", "codice": "assets_wm_dashboard", "label": "Assets - Dashboard macchinari", "url": "/assets/work-machines/dashboard/", "hide": True},
    {"modulo": "assets", "codice": "assets_wm_map", "label": "Assets - Mappa planimetrica", "url": "/assets/work-machines/map/", "hide": True},
    {"modulo": "assets", "codice": "assets_workorders", "label": "Assets - Work orders", "url": "/assets/workorders/", "hide": False},
    {"modulo": "assets", "codice": "assets_wo_new", "label": "Assets - Nuovo work order", "url": "/assets/workorders/new/", "hide": True},
    {"modulo": "assets", "codice": "assets_verifiche", "label": "Assets - Verifiche periodiche", "url": "/assets/verifiche-periodiche/", "hide": False},
    {"modulo": "assets", "codice": "assets_reports", "label": "Assets - Reports", "url": "/assets/reports/", "hide": True},
    {"modulo": "assets", "codice": "assets_gestione", "label": "Assets - Gestione admin", "url": "/assets/gestione/", "hide": True},
    {"modulo": "assets", "codice": "assets_labels", "label": "Assets - Label designer", "url": "/assets/labels/", "hide": True},
    {"modulo": "assets", "codice": "assets_bulk_update", "label": "Assets - Bulk update", "url": "/assets/bulk-update/", "hide": True},
    {"modulo": "assets", "codice": "assets_wm_map_editor", "label": "Assets - Editor planimetria", "url": "/assets/work-machines/map/editor/", "hide": True},
    {"modulo": "assets", "codice": "assets_wm_create", "label": "Assets - Nuovo macchinario", "url": "/assets/work-machines/new/", "hide": True},
    {"modulo": "assets", "codice": "assets_view_layout", "label": "Assets - Configurazione layout dettaglio", "url": "/assets/view-layout/", "hide": True},
    {"modulo": "assets", "codice": "assets_assign", "label": "Assets - Assegna asset", "url": "/assets/assign/", "hide": True},
    {"modulo": "assets", "codice": "assets_wo_view", "label": "Assets - Dettaglio work order", "url": "/assets/workorders/view/", "hide": True},
    {"modulo": "assets", "codice": "assets_wo_close", "label": "Assets - Chiudi work order", "url": "/assets/workorders/close/", "hide": True},
    {"modulo": "assets", "codice": "assets_reports_manage", "label": "Assets - Gestione template report", "url": "/assets/reports/manage/", "hide": True},
    {"modulo": "assets", "codice": "assets_maintenance_month_pdf", "label": "Assets - Report manutenzione mensile PDF", "url": "/assets/reports/work-machines/maintenance-month.pdf", "hide": True},
]


def bootstrap_assets_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "assets",
        icona="tool",
        section="assets_api",
        force=force,
    )
