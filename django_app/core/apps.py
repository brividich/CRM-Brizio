import logging

from django.apps import AppConfig
from django.db.models.signals import post_migrate

logger = logging.getLogger(__name__)


def _ensure_legacy_anagrafica_columns(sender, **kwargs):
    """Allinea le colonne extra della tabella legacy `anagrafica_dipendenti`.

    Le colonne `ruolo`/`matricola`/`attivo`... non esistono nella tabella creata
    dalla migrazione: le aggiunge `ensure_anagrafica_schema()` con un ALTER TABLE.
    Farlo qui (a migrazioni applicate, fuori da qualunque transazione di test)
    invece che pigramente alla prima richiesta evita che, sotto test, l'ALTER
    venga annullato dal rollback lasciando la cache di schema disallineata dal DB.
    Idempotente: se le colonne ci sono gia', non fa nulla.
    """
    try:
        from .legacy_anagrafica import ensure_anagrafica_schema

        ensure_anagrafica_schema()
    except Exception:  # tabella legacy assente (deploy nuovo, DB parziale): non bloccare
        logger.debug("ensure_anagrafica_schema in post_migrate non eseguito", exc_info=True)


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from . import signals  # noqa: F401
        from . import audit_signals  # noqa: F401
        from . import checks  # noqa: F401  (registra i system check di igiene runtime)

        post_migrate.connect(_ensure_legacy_anagrafica_columns, sender=self)
