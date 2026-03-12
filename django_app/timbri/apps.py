from django.apps import AppConfig


class TimbriConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "timbri"
    verbose_name = "Registro timbri"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_timbri_runtime

            bootstrap_timbri_runtime()
        except Exception:
            return

