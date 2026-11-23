from django.apps import AppConfig


class AssenzeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "assenze"

    def ready(self):
        # Calendario unico del portale: patrono, sabato e chiusure si leggono da qui;
        # dopo una modifica gli altri moduli li vedono subito (core.calendario_it).
        from django.db.models.signals import post_delete, post_save

        from core.calendario_it import svuota_cache

        from .models import AssenzeImpostazioniHR, ChiusuraAziendale

        def _svuota(**kwargs):
            svuota_cache()

        for modello in (AssenzeImpostazioniHR, ChiusuraAziendale):
            post_save.connect(_svuota, sender=modello, weak=False, dispatch_uid=f"calendario_{modello.__name__}_save")
            post_delete.connect(_svuota, sender=modello, weak=False, dispatch_uid=f"calendario_{modello.__name__}_delete")
        try:
            from .acl_bootstrap import bootstrap_assenze_acl_endpoints

            bootstrap_assenze_acl_endpoints()
        except Exception:
            # Bootstrap ACL is best effort: avoid blocking startup for local/test DBs.
            return
