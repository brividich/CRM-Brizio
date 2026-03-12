from django.apps import AppConfig


class AssenzeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "assenze"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_assenze_acl_endpoints

            bootstrap_assenze_acl_endpoints()
        except Exception:
            # Bootstrap ACL is best effort: avoid blocking startup for local/test DBs.
            return
