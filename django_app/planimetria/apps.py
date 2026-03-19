from django.apps import AppConfig


class PlanimetriaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "planimetria"
    verbose_name = "Planimetria Aziendale"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_planimetria_acl_endpoints

            bootstrap_planimetria_acl_endpoints()
        except Exception:
            return
