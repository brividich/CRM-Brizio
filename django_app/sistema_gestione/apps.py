from django.apps import AppConfig


class SistemaGestioneConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sistema_gestione"
    verbose_name = "Sistema di gestione"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_sistema_gestione_acl

            bootstrap_sistema_gestione_acl()
        except Exception:
            return
