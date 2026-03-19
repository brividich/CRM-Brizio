from django.apps import AppConfig


class AutomazioniConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "automazioni"
    verbose_name = "Automazioni"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_automazioni_acl_endpoints

            bootstrap_automazioni_acl_endpoints()
        except Exception:
            return
