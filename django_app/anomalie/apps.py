from django.apps import AppConfig


class AnomalieConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "anomalie"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_anomalie_acl_endpoints

            bootstrap_anomalie_acl_endpoints()
        except Exception:
            return

