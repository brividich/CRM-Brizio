from django.apps import AppConfig
from django.db.models.signals import post_migrate


def migra_database_registro(sender, using="default", verbosity=1, **kwargs):
    """Dopo il ``migrate`` del database del portale, migra anche il database del registro.

    Con ``REGISTRO_LOG_DB_NAME`` le tabelle stanno nell'alias ``registro_log`` (vedi
    ``router.py``), che un ``migrate`` normale non tocca. Così il deploy, il Setup Wizard e
    la console del qcluster restano un solo ``migrate`` e il database a parte non resta
    indietro. Il ``migrate`` annidato arriva qui con ``using="registro_log"`` e si ferma.
    """
    from django.conf import settings
    from django.core.management import call_command

    from registro_log.router import ALIAS

    if using == ALIAS or ALIAS not in settings.DATABASES:
        return
    call_command("migrate", "registro_log", database=ALIAS, interactive=False,
                 verbosity=max(0, int(verbosity) - 1))


class RegistroLogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "registro_log"
    verbose_name = "Registro accessi (log dei server)"

    def ready(self):
        post_migrate.connect(migra_database_registro, sender=self,
                             dispatch_uid="registro_log_migra_database_registro")
