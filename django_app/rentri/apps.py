from django.apps import AppConfig


class RentriConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "rentri"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_rentri_acl_endpoints

            bootstrap_rentri_acl_endpoints()
        except Exception:
            return
