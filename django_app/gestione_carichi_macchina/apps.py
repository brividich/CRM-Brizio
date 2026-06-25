from django.apps import AppConfig


class GestioneCarichiMacchinaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gestione_carichi_macchina"
    verbose_name = "Gestione Carichi Macchina"

    def ready(self):
        """Bootstrap ACL v2 canonico + voce di menu (idempotente, fail-safe)."""
        try:
            from .acl_bootstrap import bootstrap_carichi_acl_endpoints

            bootstrap_carichi_acl_endpoints()
        except Exception:
            return
