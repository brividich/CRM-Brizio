from django.apps import AppConfig


class ProcedureRefreshConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "procedure_refresh"
    verbose_name = "Presa Visione Procedure"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_procedure_refresh_acl_endpoints

            bootstrap_procedure_refresh_acl_endpoints()
        except Exception:
            return
