from __future__ import annotations

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "procedure_refresh_acl_bootstrap_v1"

_PULSANTI_DEFINITIONS = [
    {
        "modulo": "procedure_refresh",
        "codice": "pr_view",
        "label": "Presa Visione - Le mie letture",
        "url": "/procedure-refresh/",
        "visible_topbar": True,
        "ui_order": 70,
    },
    {
        "modulo": "procedure_refresh",
        "codice": "pr_assignment_detail",
        "label": "Presa Visione - Dettaglio assegnazione",
        "url": "/procedure-refresh/",
        "visible_topbar": False,
        "ui_order": None,
    },
    {
        "modulo": "procedure_refresh",
        "codice": "pr_admin",
        "label": "Presa Visione - Impostazioni",
        "url": "/procedure-refresh/impostazioni/",
        "visible_topbar": False,
        "ui_order": None,
    },
    {
        "modulo": "procedure_refresh",
        "codice": "pr_documents",
        "label": "Presa Visione - Documenti",
        "url": "/procedure-refresh/admin/documenti/",
        "visible_topbar": False,
        "ui_order": None,
    },
    {
        "modulo": "procedure_refresh",
        "codice": "pr_campaigns",
        "label": "Presa Visione - Campagne",
        "url": "/procedure-refresh/admin/campagne/",
        "visible_topbar": False,
        "ui_order": None,
    },
    {
        "modulo": "procedure_refresh",
        "codice": "pr_report_user",
        "label": "Presa Visione - Report utente",
        "url": "/procedure-refresh/admin/report/utente/",
        "visible_topbar": False,
        "ui_order": None,
    },
    {
        "modulo": "procedure_refresh",
        "codice": "pr_report_document",
        "label": "Presa Visione - Report documento",
        "url": "/procedure-refresh/admin/report/documento/",
        "visible_topbar": False,
        "ui_order": None,
    },
    {
        "modulo": "procedure_refresh",
        "codice": "pr_report_campaign",
        "label": "Presa Visione - Report campagna",
        "url": "/procedure-refresh/admin/report/campagna/",
        "visible_topbar": False,
        "ui_order": None,
    },
    {
        "modulo": "procedure_refresh",
        "codice": "pr_export_csv",
        "label": "Presa Visione - Export CSV",
        "url": "/procedure-refresh/admin/export-csv/",
        "visible_topbar": False,
        "ui_order": None,
    },
]


def _bootstrap_navigation() -> bool:
    try:
        from core.models import NavigationItem, NavigationRoleAccess
        from core.legacy_models import Ruolo
        from core.navigation_registry import bump_navigation_registry_version
    except Exception:
        return False

    changed = False
    item, created = NavigationItem.objects.get_or_create(
        code="procedure_refresh",
        defaults={
            "label": "Presa Visione",
            "section": "topbar",
            "route_name": "procedure_refresh:my_assignments",
            "order": 70,
            "is_visible": True,
            "is_enabled": True,
            "description": "Presa visione procedure MT/MTSI",
            "icon": "file-text",
        },
    )
    if created:
        changed = True
    else:
        updates = []
        if item.label != "Presa Visione":
            item.label = "Presa Visione"
            updates.append("label")
        if item.section != "topbar":
            item.section = "topbar"
            updates.append("section")
        if item.route_name != "procedure_refresh:my_assignments":
            item.route_name = "procedure_refresh:my_assignments"
            updates.append("route_name")
        if int(item.order or 0) != 70:
            item.order = 70
            updates.append("order")
        if not item.is_visible:
            item.is_visible = True
            updates.append("is_visible")
        if not item.is_enabled:
            item.is_enabled = True
            updates.append("is_enabled")
        if updates:
            item.save(update_fields=updates)
            changed = True

    all_role_ids = {int(r.id) for r in Ruolo.objects.all()}
    existing = {
        int(x.legacy_role_id): x
        for x in NavigationRoleAccess.objects.filter(item=item)
    }
    for role_id in all_role_ids:
        row = existing.get(role_id)
        if row is None:
            NavigationRoleAccess.objects.create(item=item, legacy_role_id=role_id, can_view=True)
            changed = True
        elif not row.can_view:
            row.can_view = True
            row.save(update_fields=["can_view"])
            changed = True
    for role_id, row in existing.items():
        if role_id not in all_role_ids:
            row.delete()
            changed = True

    if changed:
        try:
            bump_navigation_registry_version()
        except Exception:
            pass
    return changed


def bootstrap_procedure_refresh_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "procedure_refresh",
        icona="file-text",
        section="procedure_refresh",
        force=force,
        bootstrap_nav_fn=_bootstrap_navigation,
    )
