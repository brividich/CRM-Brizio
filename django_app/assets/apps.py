from django.apps import AppConfig


class AssetsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "assets"

    def ready(self):
        # Avviso a Qualita' quando un'attrezzatura PART 145 / di processo qualificato cambia stato.
        from .services.part145 import collega_segnali

        collega_segnali()
        try:
            from .acl_bootstrap import bootstrap_assets_acl_endpoints

            bootstrap_assets_acl_endpoints()
        except Exception:
            return

