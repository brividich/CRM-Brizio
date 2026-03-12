"""
Management command: aggiungi_note_gestione
Aggiunge la colonna `note_gestione` alla tabella legacy `assenze` se non esiste già.

Utilizzo:
    python manage.py aggiungi_note_gestione
"""
from django.core.management.base import BaseCommand
from django.db import connections


def _db_vendor() -> str:
    return connections["default"].vendor


class Command(BaseCommand):
    help = "Aggiunge la colonna note_gestione alla tabella assenze (se assente)"

    def handle(self, *args, **options):
        vendor = _db_vendor()
        with connections["default"].cursor() as cursor:
            if vendor == "sqlite":
                cursor.execute("PRAGMA table_info(assenze)")
                cols = [row[1] for row in cursor.fetchall()]
                if "note_gestione" in cols:
                    self.stdout.write(self.style.WARNING("Colonna note_gestione già presente. Nessuna azione."))
                    return
                cursor.execute("ALTER TABLE assenze ADD COLUMN note_gestione TEXT")
            else:
                # SQL Server
                cursor.execute(
                    """
                    IF NOT EXISTS (
                        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_NAME = 'assenze' AND COLUMN_NAME = 'note_gestione'
                    )
                    BEGIN
                        ALTER TABLE assenze ADD note_gestione NVARCHAR(MAX) NULL
                    END
                    """
                )

        self.stdout.write(self.style.SUCCESS("Colonna note_gestione aggiunta con successo."))
