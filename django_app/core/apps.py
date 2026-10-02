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
        _install_user_full_name()


def _user_get_full_name(self) -> str:
    """Nominativo dell'utente nel formato unico del portale: ``COGNOME NOME``.

    Gli utenti nascono da ``utenti.nome`` (displayName AD, già «Cognome Nome")
    spezzato da ``core.legacy_utils._split_name``: ``first_name`` contiene quindi
    il cognome. Si tiene l'ordine salvato e si uniforma il maiuscolo."""
    from .naming import normalizza_parte

    return normalizza_parte(f"{self.first_name} {self.last_name}")


def _install_user_full_name():
    """Tutti i nominativi utente del portale (tendine, assegnatari, email...) passano
    da ``User.get_full_name()``: qui lo si allinea a ``core.naming`` invece di
    ritoccare ogni template. Lo username resta il fallback dove il nome manca."""
    from django.contrib.auth import get_user_model

    get_user_model().get_full_name = _user_get_full_name
