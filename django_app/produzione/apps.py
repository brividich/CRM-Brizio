from django.apps import AppConfig


class ProduzioneConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "produzione"
    verbose_name = "Ordini di produzione"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_produzione_acl

            bootstrap_produzione_acl()
        except Exception:
            return
