from django.apps import AppConfig


class RilevazioneIncidentiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "rilevazione_incidenti"
    verbose_name = "Rilevazione Incidenti"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_rilevazione_incidenti_acl_endpoints

            bootstrap_rilevazione_incidenti_acl_endpoints()
        except Exception:
            return
