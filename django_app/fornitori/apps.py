from django.apps import AppConfig


class FornitoriConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "fornitori"
    verbose_name = "Anagrafica Fornitori"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_fornitori_acl_endpoints

            bootstrap_fornitori_acl_endpoints()
        except Exception:
            return
