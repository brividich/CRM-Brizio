from django.apps import AppConfig


class AssetsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "assets"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_assets_acl_endpoints

            bootstrap_assets_acl_endpoints()
        except Exception:
            return

