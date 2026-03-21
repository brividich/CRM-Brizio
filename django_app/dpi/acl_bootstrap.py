from __future__ import annotations

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "dpi_acl_bootstrap_v3"

_PULSANTI_DEFINITIONS = [
    {"modulo": "dpi", "codice": "dpi_view", "label": "DPI - Dashboard", "url": "/dpi/", "visible_topbar": True, "ui_order": 55},
    {"modulo": "dpi", "codice": "dpi_create", "label": "DPI - Nuova richiesta", "url": "/dpi/nuova/", "visible_topbar": False, "ui_order": None},
    {"modulo": "dpi", "codice": "dpi_manage", "label": "DPI - Gestione richieste", "url": "/dpi/gestione/", "visible_topbar": False, "ui_order": None},
    {"modulo": "dpi", "codice": "dpi_impostazioni", "label": "DPI - Impostazioni", "url": "/dpi/impostazioni/", "visible_topbar": False, "ui_order": None},
    {"modulo": "dpi", "codice": "dpi_storico", "label": "DPI - Storico consegne", "url": "/dpi/storico/", "visible_topbar": False, "ui_order": None},
    {"modulo": "dpi", "codice": "dpi_categoria_create", "label": "DPI - Nuova categoria", "url": "/dpi/impostazioni/categorie/nuova/", "visible_topbar": False, "ui_order": None},
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
        code="dpi",
        defaults={
            "label": "DPI",
            "section": "topbar",
            "route_name": "dpi:dashboard",
            "order": 62,
            "is_visible": True,
            "is_enabled": True,
            "description": "Dispositivi di Protezione Individuale",
            "icon": "shield",
        },
    )
    if created:
        changed = True
    else:
        updates = []
        if item.label != "DPI":
            item.label = "DPI"
            updates.append("label")
        if item.section != "topbar":
            item.section = "topbar"
            updates.append("section")
        if item.route_name != "dpi:dashboard":
            item.route_name = "dpi:dashboard"
            updates.append("route_name")
        if int(item.order or 0) != 62:
            item.order = 62
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
    existing = {int(x.legacy_role_id): x for x in NavigationRoleAccess.objects.filter(item=item)}
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


def bootstrap_dpi_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "dpi",
        icona="shield",
        section="dpi",
        force=force,
        bootstrap_nav_fn=_bootstrap_navigation,
    )
