from django.apps import AppConfig


class ContatoriConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'contatori'
    verbose_name = 'Contatori IT'

    def ready(self):
        from . import signals  # noqa: F401 - registra i ricevitori
