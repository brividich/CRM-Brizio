from django.apps import AppConfig


class GlossarioTecnicoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "glossario_tecnico"
    verbose_name = "Glossario tecnico"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_glossario_tecnico_acl

            bootstrap_glossario_tecnico_acl()
        except Exception:
            return
