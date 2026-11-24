from django.apps import AppConfig


class AssetsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "assets"

    def ready(self):
        # Avviso a Qualita' quando un'attrezzatura PART 145 / di processo qualificato cambia stato.
        from .services.part145 import collega_segnali

        collega_segnali()
        # Soglia di ritardo degli OdL tenuta 30 s in memoria: si rilegge appena la configurazione cambia.
        try:
            from django.db.models.signals import post_delete, post_save

            from core.models import SiteConfig

            from .maintenance import _SOGLIA_RITARDO_MEMO

            def _azzera_soglia(**_kwargs):
                _SOGLIA_RITARDO_MEMO["valore"] = None

            post_save.connect(_azzera_soglia, sender=SiteConfig, weak=False, dispatch_uid="assets_soglia_ritardo_save")
            post_delete.connect(_azzera_soglia, sender=SiteConfig, weak=False, dispatch_uid="assets_soglia_ritardo_delete")
        except Exception:
            pass
        try:
            from .acl_bootstrap import bootstrap_assets_acl_endpoints

            bootstrap_assets_acl_endpoints()
        except Exception:
            return

