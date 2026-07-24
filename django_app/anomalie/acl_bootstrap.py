from __future__ import annotations

from django.db import transaction

from core.acl_bootstrap_base import run_bootstrap

# Bump alla v3: permesso canonico della configurazione anomalie. Prima il gate
# `_can_manage_anomalie_config` guardava solo `is_superuser or is_legacy_admin()`
# — vero unicamente per il ruolo "admin" — quindi nessun altro ruolo (es.
# qualità) poteva essere abilitato dal modulo permessi.
_BOOTSTRAP_CACHE_KEY = "anomalie_acl_bootstrap_v3"

MODULE = "anomalie"
PERM_ANOMALIE_CONFIG = "anomalie.configurazione.manage"

# Permesso "solo definizione", senza RoutePermissionBinding: con
# ACL_STRICT_CANONICAL=True un binding di route negherebbe l'intera pagina a
# tutti i ruoli senza grant esplicito. Il cancello resta in-view e additivo.
_CANONICAL = {
    PERM_ANOMALIE_CONFIG: {
        "label": "Anomalie - Configurazione",
        "description": (
            "Configurazione del modulo anomalie: campi, notifiche agli operatori, "
            "sync e parametri. Area di gestione, non la semplice segnalazione."
        ),
    },
}

# Grant di default create-only: solo "admin", che passa comunque dal bypass.
_ROLE_GRANTS = {"admin": {PERM_ANOMALIE_CONFIG}}


def _bootstrap_canonical() -> bool:
    """Registra il permesso canonico della configurazione + grant di default."""
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
                    defaults={"enabled": code in grants, "note": "[ANOMALIE_BOOTSTRAP] default"},
                )
                changed = changed or created
    return changed

_PULSANTI_DEFINITIONS = [
    {"modulo": "anomalie", "codice": "anomalie_gestione", "label": "Anomalie - Gestione", "url": "/gestione-anomalie", "hide": False},
    {"modulo": "anomalie", "codice": "anomalie_nuova", "label": "Anomalie - Nuova segnalazione", "url": "/gestione-anomalie/nuova-segnalazione", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_configurazione", "label": "Anomalie - Configurazione", "url": "/gestione-anomalie/configurazione", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_statistiche", "label": "Anomalie - Statistiche", "url": "/gestione-anomalie/statistiche", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_ordini", "label": "Anomalie - API ordini", "url": "/api/anomalie/ordini", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_anomalie", "label": "Anomalie - API anomalie", "url": "/api/anomalie/anomalie", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_salva", "label": "Anomalie - API salva", "url": "/api/anomalie/salva", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_notifica_op", "label": "Anomalie - API notifica OP", "url": "/api/anomalie/notifica-op", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_seriali_op", "label": "Anomalie - API seriali OP", "url": "/api/anomalie/seriali-op", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_sync", "label": "Anomalie - API sync", "url": "/api/anomalie/sync", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_campi", "label": "Anomalie - API campi", "url": "/api/anomalie/campi", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_allegati", "label": "Anomalie - API allegati", "url": "/api/anomalie/allegati", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_statistiche", "label": "Anomalie - API statistiche", "url": "/api/anomalie/statistiche", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_api_report", "label": "Anomalie - API report", "url": "/api/anomalie/report", "hide": True},
    {"modulo": "anomalie", "codice": "anomalie_export_csv", "label": "Anomalie - Export CSV", "url": "/export-csv", "hide": True},
]


def bootstrap_anomalie_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "anomalie",
        icona="alert-triangle",
        section="anomalie_api",
        force=force,
        bootstrap_nav_fn=_bootstrap_canonical,
    )
