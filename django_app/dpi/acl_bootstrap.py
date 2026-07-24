from __future__ import annotations

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

# Bump alla v4: permesso canonico dell'area gestione DPI. Prima il gate
# `_is_gestore` guardava solo `is_superuser or is_legacy_admin()` — vero
# unicamente per il ruolo "admin" — quindi nessun altro ruolo (es. RSPP,
# magazzino) poteva essere abilitato dal modulo permessi.
_BOOTSTRAP_CACHE_KEY = "dpi_acl_bootstrap_v4"

MODULE = "dpi"
PERM_DPI_MANAGE = "dpi.gestione.manage"

# Permesso "solo definizione", senza RoutePermissionBinding: con
# ACL_STRICT_CANONICAL=True un binding di route negherebbe l'intera pagina a
# tutti i ruoli senza grant esplicito. Il cancello resta in-view e additivo.
_CANONICAL = {
    PERM_DPI_MANAGE: {
        "label": "DPI - Gestione richieste e impostazioni",
        "description": (
            "Gestione delle richieste DPI, consegne, storico, catalogo categorie/"
            "modelli e impostazioni del modulo."
        ),
    },
}

# Grant di default create-only: solo "admin", che passa comunque dal bypass.
_ROLE_GRANTS = {"admin": {PERM_DPI_MANAGE}}


def _bootstrap_canonical() -> bool:
    """Registra il permesso canonico dell'area gestione + grant di default."""
    from core.legacy_models import Ruolo
    from core.models import PermissionDefinition, RolePermissionGrant

    changed = False
    with transaction.atomic():
        for code, payload in _CANONICAL.items():
            _, created = PermissionDefinition.objects.get_or_create(
                code=code,
                defaults={"module": MODULE, "label": payload["label"],
                          "description": payload["description"], "is_active": True},
            )
            changed = changed or created

        for rid, rname in {int(r.id): (r.nome or "").strip().lower()
                           for r in Ruolo.objects.all()}.items():
            grants = _ROLE_GRANTS.get(rname, set())
            for code in _CANONICAL:
                _, created = RolePermissionGrant.objects.get_or_create(
                    legacy_role_id=rid, permission_id=code,
                    defaults={"enabled": code in grants, "note": "[DPI_BOOTSTRAP] default"},
                )
                changed = changed or created
    return changed

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


def _bootstrap_nav_and_canonical() -> bool:
    """Combina il seed della navigazione con la registrazione del permesso canonico."""
    changed_nav = _bootstrap_navigation()
    changed_canonical = _bootstrap_canonical()
    return bool(changed_nav or changed_canonical)


def bootstrap_dpi_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "dpi",
        icona="shield",
        section="dpi",
        force=force,
        bootstrap_nav_fn=_bootstrap_nav_and_canonical,
    )
