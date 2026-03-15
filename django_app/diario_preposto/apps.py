from django.apps import AppConfig


class DiarioPrepostoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "diario_preposto"
    verbose_name = "Diario Preposto RSPP ASPP RLS"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_diario_preposto_acl_endpoints

            bootstrap_diario_preposto_acl_endpoints()
        except Exception:
            return
