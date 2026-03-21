from django.apps import AppConfig


class DpiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dpi"
    verbose_name = "DPI"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_dpi_acl_endpoints

            bootstrap_dpi_acl_endpoints()
        except Exception:
            return
