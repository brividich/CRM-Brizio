from django.apps import AppConfig


class PresentiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "presenti"
    verbose_name = "Presenti in azienda"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_presenti_acl

            bootstrap_presenti_acl()
        except Exception:
            return
