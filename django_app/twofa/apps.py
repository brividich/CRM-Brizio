from django.apps import AppConfig


class TwoFaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "twofa"
    verbose_name = "Autenticazione a due fattori"
