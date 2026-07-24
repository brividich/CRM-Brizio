from __future__ import annotations

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

# Bump alla v4: permesso canonico delle impostazioni di modulo. Prima il gate
# guardava solo `is_legacy_admin()` — vero unicamente per il ruolo "admin" —
# quindi nessun altro ruolo poteva essere abilitato dal modulo permessi.
_BOOTSTRAP_CACHE_KEY = "diario_preposto_acl_bootstrap_v4"

MODULE = "diario_preposto"
PERM_IMPOSTAZIONI_MANAGE = "diario_preposto.impostazioni.manage"

# Permesso "solo definizione", senza RoutePermissionBinding: con
# ACL_STRICT_CANONICAL=True un binding di route negherebbe la pagina a tutti i
# ruoli senza grant esplicito. Il cancello resta in-view e additivo.
_CANONICAL = {
    PERM_IMPOSTAZIONI_MANAGE: {
        "label": "Diario Preposto - Impostazioni modulo",
        "description": (
            "Configurazione del modulo (ACL di scrittura, branding) e ricerca "
            "dipendenti per il widget autorizzazioni."
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
                    defaults={"enabled": code in grants, "note": "[DP_BOOTSTRAP] default"},
                )
                changed = changed or created
    return changed

_PULSANTI_DEFINITIONS = [
    {"modulo": "diario_preposto", "codice": "diario_preposto_lista", "label": "Diario Preposto - Lista", "url": "/diario-preposto/", "hide": False},
    {"modulo": "diario_preposto", "codice": "diario_preposto_nuovo", "label": "Diario Preposto - Nuovo inserimento", "url": "/diario-preposto/nuovo/", "hide": True},
    {"modulo": "diario_preposto", "codice": "diario_preposto_ispezioni", "label": "Diario Preposto - Ispezioni periodiche", "url": "/diario-preposto/ispezioni/", "hide": True},
    {"modulo": "diario_preposto", "codice": "diario_preposto_ispezione_nuova", "label": "Diario Preposto - Nuova ispezione periodica", "url": "/diario-preposto/ispezioni/nuova/", "hide": True},
    {"modulo": "diario_preposto", "codice": "diario_preposto_dettaglio", "label": "Diario Preposto - Dettaglio (API)", "url": "/diario-preposto/dettaglio", "hide": True},
    {"modulo": "diario_preposto", "codice": "diario_preposto_modifica", "label": "Diario Preposto - Modifica (API)", "url": "/diario-preposto/modifica", "hide": True},
    {"modulo": "diario_preposto", "codice": "diario_preposto_elimina", "label": "Diario Preposto - Elimina (API)", "url": "/diario-preposto/elimina", "hide": True},
    {"modulo": "diario_preposto", "codice": "diario_preposto_allegato_upload", "label": "Diario Preposto - Upload allegato (API)", "url": "/diario-preposto/api/allegato/upload/", "hide": True},
    {"modulo": "diario_preposto", "codice": "diario_preposto_allegato_delete", "label": "Diario Preposto - Elimina allegato (API)", "url": "/diario-preposto/api/allegato/delete/", "hide": True},
]


def bootstrap_diario_preposto_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "diario_preposto",
        icona="shield",
        section="diario_preposto_api",
        force=force,
        bootstrap_nav_fn=_bootstrap_canonical,
    )
