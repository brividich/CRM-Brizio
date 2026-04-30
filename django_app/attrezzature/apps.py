from django.apps import AppConfig


class AttrezzatureConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "attrezzature"
    verbose_name = "Gestione Attrezzatura"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_attrezzature_acl_endpoints

            bootstrap_attrezzature_acl_endpoints()
        except Exception:
            pass
