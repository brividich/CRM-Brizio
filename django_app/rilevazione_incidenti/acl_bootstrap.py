from __future__ import annotations

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

# Bump alla v5: permesso canonico delle impostazioni di modulo. Prima il gate
# `_can_manage_settings` guardava solo `is_superuser or is_legacy_admin()` — vero
# unicamente per il ruolo "admin" — quindi nessun altro ruolo (es. RSPP) poteva
# essere abilitato dal modulo permessi.
_BOOTSTRAP_CACHE_KEY = "rilevazione_incidenti_acl_bootstrap_v5"

MODULE = "rilevazione_incidenti"
PERM_IMPOSTAZIONI_MANAGE = "rilevazione_incidenti.impostazioni.manage"

# Permesso "solo definizione", senza RoutePermissionBinding: con
# ACL_STRICT_CANONICAL=True un binding di route negherebbe l'intera pagina a
# tutti i ruoli senza grant esplicito. Il cancello resta in-view e additivo.
_CANONICAL = {
    PERM_IMPOSTAZIONI_MANAGE: {
        "label": "Rilevazione Incidenti - Impostazioni modulo",
        "description": (
            "Configurazione del modulo rilevazione incidenti (SharePoint, ACL di "
            "notifica, parametri): area riservata alla gestione."
        ),
    },
}

# Grant di default create-only: solo "admin", che passa comunque dal bypass.
_ROLE_GRANTS = {"admin": {PERM_IMPOSTAZIONI_MANAGE}}


def _bootstrap_canonical() -> bool:
    """Registra il permesso canonico delle impostazioni + grant di default."""
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
                    defaults={"enabled": code in grants, "note": "[RILEV_BOOTSTRAP] default"},
                )
                changed = changed or created
    return changed

_PULSANTI_DEFINITIONS = [
    {"modulo": "rilevazione_incidenti", "codice": "rilev_inc_lista", "label": "Rilevazione Incidenti - Lista rilevazioni", "url": "/rilevazione-incidenti/", "hide": False},
    {"modulo": "rilevazione_incidenti", "codice": "rilev_inc_nuovo", "label": "Rilevazione Incidenti - Nuova rilevazione", "url": "/rilevazione-incidenti/nuovo/", "hide": False},
    {"modulo": "rilevazione_incidenti", "codice": "rilev_inc_dettaglio", "label": "Rilevazione Incidenti - Dettaglio rilevazione", "url": "/rilevazione-incidenti/dettaglio", "hide": True},
    {"modulo": "rilevazione_incidenti", "codice": "rilev_inc_modifica", "label": "Rilevazione Incidenti - Modifica rilevazione", "url": "/rilevazione-incidenti/modifica", "hide": True},
    {"modulo": "rilevazione_incidenti", "codice": "rilev_inc_statistiche", "label": "Rilevazione Incidenti - Statistiche", "url": "/rilevazione-incidenti/statistiche/", "hide": False},
    {"modulo": "rilevazione_incidenti", "codice": "rilev_inc_heatmap", "label": "Rilevazione Incidenti - Heatmap planimetria", "url": "/rilevazione-incidenti/heatmap/", "hide": False},
    {"modulo": "rilevazione_incidenti", "codice": "rilev_inc_impostazioni", "label": "Rilevazione Incidenti - Impostazioni (admin)", "url": "/rilevazione-incidenti/impostazioni/", "hide": True},
    {"modulo": "rilevazione_incidenti", "codice": "rilev_inc_export_csv", "label": "Rilevazione Incidenti - Export CSV", "url": "/rilevazione-incidenti/export-csv/", "hide": True},
]


def bootstrap_rilevazione_incidenti_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "rilevazione_incidenti",
        icona="shield",
        section="rilevazione_incidenti_api",
        force=force,
        bootstrap_nav_fn=_bootstrap_canonical,
    )
