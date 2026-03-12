"""
Management command: aggiungi_certificato_medico
Aggiunge la colonna `certificato_medico` alla tabella legacy `assenze` se non esiste gia.

Utilizzo:
    python manage.py aggiungi_certificato_medico
"""
from django.core.management.base import BaseCommand
from django.db import connections


def _db_vendor() -> str:
    return connections["default"].vendor


class Command(BaseCommand):
    help = "Aggiunge la colonna certificato_medico alla tabella assenze (se assente)"

    def handle(self, *args, **options):
        vendor = _db_vendor()
        with connections["default"].cursor() as cursor:
            if vendor == "sqlite":
                cursor.execute("PRAGMA table_info(assenze)")
                cols = [row[1] for row in cursor.fetchall()]
                if "certificato_medico" in cols:
                    self.stdout.write(self.style.WARNING("Colonna certificato_medico gia presente. Nessuna azione."))
                    return
                cursor.execute("ALTER TABLE assenze ADD COLUMN certificato_medico TEXT")
            else:
                cursor.execute(
                    """
                    IF NOT EXISTS (
                        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_NAME = 'assenze' AND COLUMN_NAME = 'certificato_medico'
                    )
                    BEGIN
                        ALTER TABLE assenze ADD certificato_medico NVARCHAR(255) NULL
                    END
                    """
                )

        self.stdout.write(self.style.SUCCESS("Colonna certificato_medico aggiunta con successo."))
