from django.apps import AppConfig


class RegistroOfiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "registro_ofi"
    verbose_name = "Registro OFI / NC"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_registro_ofi_acl

            bootstrap_registro_ofi_acl()
        except Exception:
            return
