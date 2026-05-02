from django.apps import AppConfig


class AttrezzatureConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "attrezzature"
    verbose_name = "Gestione Attrezzatura"

    def ready(self):
        from core.acl_bootstrap_base import should_skip_runtime_bootstrap

        if should_skip_runtime_bootstrap():
            return

        try:
            from .acl_bootstrap import bootstrap_attrezzature_acl_endpoints

            bootstrap_attrezzature_acl_endpoints()
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Bootstrap ACL attrezzature saltato o fallito: %s",
                exc,
            )
