"""
Management command: allinea_tipo_assenza_flessibilita
Allinea la tabella legacy `assenze` al tipo canonico `Flessibilità`.

Utilizzo:
    python manage.py allinea_tipo_assenza_flessibilita
    python manage.py allinea_tipo_assenza_flessibilita --dry-run
"""

from django.core.management.base import BaseCommand
from django.db import connections


CHECK_NAME = "CK_assenze_tipo"
OLD_VALUE = "Infortunio"
NEW_VALUE = "Flessibilità"
ALLOWED_VALUES = ("Altro", NEW_VALUE, "Malattia", "Permesso", "Ferie")


def _quote_ident(name: str) -> str:
    return f"[{str(name).replace(']', ']]')}]"


def _build_check_sql(table_name: str) -> str:
    allowed = " OR ".join(f"([tipo_assenza]=N'{value}')" for value in ALLOWED_VALUES)
    return (
        f"ALTER TABLE {table_name} WITH CHECK "
        f"ADD CONSTRAINT {_quote_ident(CHECK_NAME)} CHECK ({allowed})"
    )


class Command(BaseCommand):
    help = (
        "Aggiorna il vincolo CK_assenze_tipo su SQL Server e converte i record "
        "'Infortunio' in 'Flessibilità'."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra lo stato attuale senza modificare il database.",
        )

    def handle(self, *args, **options):
        connection = connections["default"]
        vendor = str(connection.vendor or "").lower()
        if vendor == "sqlite":
            self.stdout.write(
                self.style.WARNING(
                    "Database SQLite rilevato: nessun vincolo SQL Server da aggiornare."
                )
            )
            return

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT TOP 1 TABLE_SCHEMA
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_NAME = 'assenze'
                ORDER BY CASE WHEN TABLE_SCHEMA = 'dbo' THEN 0 ELSE 1 END, TABLE_SCHEMA
                """
            )
            row = cursor.fetchone()
            if not row or not row[0]:
                self.stdout.write(
                    self.style.WARNING(
                        "Tabella legacy 'assenze' non trovata sul database corrente: "
                        "nessun riallineamento necessario."
                    )
                )
                return
            schema = str(row[0]).strip()
            table_name = f"{_quote_ident(schema)}.{_quote_ident('assenze')}"

            cursor.execute(
                f"SELECT COUNT(*) FROM {table_name} WHERE [tipo_assenza] = N'{OLD_VALUE}'"
            )
            old_count = int((cursor.fetchone() or [0])[0] or 0)
            cursor.execute(
                f"SELECT COUNT(*) FROM {table_name} WHERE [tipo_assenza] = N'{NEW_VALUE}'"
            )
            new_count = int((cursor.fetchone() or [0])[0] or 0)

            self.stdout.write(
                f"Schema: {schema} | record '{OLD_VALUE}': {old_count} | "
                f"record '{NEW_VALUE}': {new_count}"
            )

            if options["dry_run"]:
                self.stdout.write(
                    self.style.WARNING("Dry-run: nessuna modifica applicata al database.")
                )
                return

            cursor.execute(
                f"""
                IF EXISTS (
                    SELECT 1
                    FROM sys.check_constraints
                    WHERE name = N'{CHECK_NAME}'
                      AND parent_object_id = OBJECT_ID(N'{schema}.assenze')
                )
                BEGIN
                    ALTER TABLE {table_name} DROP CONSTRAINT {_quote_ident(CHECK_NAME)}
                END
                """
            )
            cursor.execute(
                f"""
                UPDATE {table_name}
                SET [tipo_assenza] = N'{NEW_VALUE}'
                WHERE [tipo_assenza] = N'{OLD_VALUE}'
                """
            )
            cursor.execute(_build_check_sql(table_name))
            cursor.execute(
                f"ALTER TABLE {table_name} CHECK CONSTRAINT {_quote_ident(CHECK_NAME)}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Vincolo CK_assenze_tipo riallineato e valori legacy convertiti a 'Flessibilità'."
            )
        )
