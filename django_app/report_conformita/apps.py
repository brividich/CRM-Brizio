from django.apps import AppConfig


class ReportConformitaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "report_conformita"
    verbose_name = "Report conformità"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_report_conformita_acl

            bootstrap_report_conformita_acl()
        except Exception:
            return
