from django.apps import AppConfig


class RegistroLogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "registro_log"
    verbose_name = "Registro accessi (log dei server)"
