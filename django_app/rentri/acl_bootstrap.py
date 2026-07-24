from __future__ import annotations

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

# Bump alla v3: permesso canonico di gestione del registro RENTRI. Prima il gate
# `_can_manage_rentri` guardava solo `is_superuser or is_legacy_admin()` — vero
# unicamente per il ruolo "admin" — quindi nessun altro ruolo (es. RSPP, ufficio
# ambiente) poteva scrivere sul registro dal modulo permessi.
_BOOTSTRAP_CACHE_KEY = "rentri_acl_bootstrap_v3"

MODULE = "rentri"
PERM_RENTRI_MANAGE = "rentri.registro.manage"

# Permesso "solo definizione", senza RoutePermissionBinding: con
# ACL_STRICT_CANONICAL=True un binding di route negherebbe l'intera pagina a
# tutti i ruoli senza grant esplicito. Il cancello resta in-view e additivo.
_CANONICAL = {
    PERM_RENTRI_MANAGE: {
        "label": "RENTRI - Gestione registro rifiuti",
        "description": (
            "Scrittura sul registro RENTRI: carico, scarico, rettifiche, import, "
            "sincronizzazione. Senza il grant l'accesso al modulo resta in sola lettura."
        ),
    },
}

# Grant di default create-only: solo "admin", che passa comunque dal bypass.
_ROLE_GRANTS = {"admin": {PERM_RENTRI_MANAGE}}


def _bootstrap_canonical() -> bool:
    """Registra il permesso canonico di gestione registro + grant di default."""
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
                    defaults={"enabled": code in grants, "note": "[RENTRI_BOOTSTRAP] default"},
                )
                changed = changed or created
    return changed

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
        bootstrap_nav_fn=_bootstrap_canonical,
    )
