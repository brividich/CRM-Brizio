from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dashboard"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_dashboard_acl_endpoints

            bootstrap_dashboard_acl_endpoints()
        except Exception:
            return

