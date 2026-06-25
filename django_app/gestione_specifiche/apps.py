from django.apps import AppConfig


class GestioneSpecificheConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gestione_specifiche"
    verbose_name = "Gestione Specifiche"

    def ready(self):
        """Bootstrap ACL v2 canonico + voce di menu (idempotente, fail-safe).

        Collega anche il signal `post_transition` (audit FSM) importando il
        modulo `state_machine`.
        """
        try:
            from . import state_machine  # noqa: F401  (registra il signal audit)
        except Exception:
            pass
        try:
            from .acl_bootstrap import bootstrap_gestione_specifiche_acl

            bootstrap_gestione_specifiche_acl()
        except Exception:
            return
