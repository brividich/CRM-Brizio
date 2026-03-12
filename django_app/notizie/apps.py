from django.apps import AppConfig


class NotizieConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notizie"
    verbose_name = "Notizie"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_notizie_acl_endpoints

            bootstrap_notizie_acl_endpoints()
        except Exception:
            return
