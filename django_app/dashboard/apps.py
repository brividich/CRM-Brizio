from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dashboard"

    def ready(self):
        # Bacheca della home in cache: ogni modifica a documenti/categorie la rinnova.
        try:
            from django.db.models.signals import post_delete, post_save

            from core.models import HubLink, HubLinkCategory

            from .views_home_portale import bacheca_cache_invalida

            for modello in (HubLink, HubLinkCategory):
                post_save.connect(bacheca_cache_invalida, sender=modello, dispatch_uid=f"bacheca_cache_{modello.__name__}_save")
                post_delete.connect(bacheca_cache_invalida, sender=modello, dispatch_uid=f"bacheca_cache_{modello.__name__}_delete")
        except Exception:
            pass
        try:
            from .acl_bootstrap import bootstrap_dashboard_acl_endpoints

            bootstrap_dashboard_acl_endpoints()
        except Exception:
            return

