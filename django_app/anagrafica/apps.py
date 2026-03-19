from django.apps import AppConfig


class AnagraficaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "anagrafica"
    verbose_name = "Anagrafica"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_anagrafica_acl_endpoints

            bootstrap_anagrafica_acl_endpoints()
        except Exception:
            return
