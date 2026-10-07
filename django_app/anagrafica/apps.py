from django.apps import AppConfig


class AnagraficaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "anagrafica"
    verbose_name = "Anagrafica"

    def ready(self):
        # Scadenze HR ricalcolate a ogni modifica dei dati da cui dipendono.
        from .segnali_scadenze import collega

        collega()
        try:
            from .acl_bootstrap import bootstrap_anagrafica_acl_endpoints

            bootstrap_anagrafica_acl_endpoints()
        except Exception:
            return
