"""Router del database del Registro accessi.

Le tabelle dell'app ``registro_log`` vanno nel database ``registro_log`` quando è
configurato (``REGISTRO_LOG_DB_NAME``: stesso server SQL del portale, database a
parte), altrimenti restano nel database del portale. Così il volume degli eventi non
pesa sul database principale né sui suoi backup, e si può svuotare senza toccarlo.
Nessuna relazione verso le tabelle del portale: le persone si collegano per id.
"""
from django.conf import settings

APP = "registro_log"
ALIAS = "registro_log"


def alias() -> str:
    return ALIAS if ALIAS in settings.DATABASES else "default"


class RegistroLogRouter:
    def db_for_read(self, model, **hints):
        if model._meta.app_label == APP:
            return alias()
        return None

    db_for_write = db_for_read

    def allow_relation(self, obj1, obj2, **hints):
        dentro = {obj1._meta.app_label == APP, obj2._meta.app_label == APP}
        if len(dentro) == 2:
            return False  # niente FK tra il registro e il portale: possono stare in database diversi
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == APP:
            return db == alias()
        if db == ALIAS:
            return False
        return None
