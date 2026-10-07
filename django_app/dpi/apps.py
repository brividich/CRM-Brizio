from django.apps import AppConfig


class DpiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dpi"
    verbose_name = "DPI"

    def ready(self):
        # Consegne in uso riallineate quando cambia la vita utile.
        from .segnali_scadenze import collega

        collega()
        try:
            from .acl_bootstrap import bootstrap_dpi_acl_endpoints

            bootstrap_dpi_acl_endpoints()
        except Exception:
            return
