from django.apps import AppConfig


class SchedeSicurezzaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "schede_sicurezza"
    verbose_name = "Schede di Sicurezza"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_schede_sicurezza_acl

            bootstrap_schede_sicurezza_acl()
        except Exception:
            return
