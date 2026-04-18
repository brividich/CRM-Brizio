"""
Management command: allinea_tipo_assenza_flessibilita
Allinea la tabella legacy `assenze` ai tipi canonici runtime.

Utilizzo:
    python manage.py allinea_tipo_assenza_flessibilita
    python manage.py allinea_tipo_assenza_flessibilita --dry-run
"""

from django.core.management.base import BaseCommand
from django.db import connections


CHECK_NAME = "CK_assenze_tipo"
OLD_VALUE = "Infortunio"
NEW_VALUE = "Flessibilit\u00e0"
ALTRO_VALUE = "Altro"
CERTIFICA_PRESENZA_VALUE = "Certifica presenza"
CERTIFICA_PRESENZA_MARKER = "[CERTIFICA_PRESENZA]"
ALLOWED_VALUES = (
    ALTRO_VALUE,
    NEW_VALUE,
    "Malattia",
    "Permesso",
    "Ferie",
    CERTIFICA_PRESENZA_VALUE,
)


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
        "Aggiorna il vincolo CK_assenze_tipo su SQL Server, converte i record "
        "'Infortunio' in 'Flessibilit\u00e0' e normalizza i vecchi record di "
        "'Certifica presenza' salvati come 'Altro'."
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
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {table_name}
                WHERE [tipo_assenza] = N'{ALTRO_VALUE}'
                  AND COALESCE([motivazione_richiesta], N'') LIKE N'[[]CERTIFICA_PRESENZA[]]%'
                """
            )
            cert_legacy_count = int((cursor.fetchone() or [0])[0] or 0)

            self.stdout.write(
                f"Schema: {schema} | record '{OLD_VALUE}': {old_count} | "
                f"record '{NEW_VALUE}': {new_count} | "
                f"record legacy 'Certifica presenza': {cert_legacy_count}"
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
            cursor.execute(
                f"""
                UPDATE {table_name}
                SET [tipo_assenza] = N'{CERTIFICA_PRESENZA_VALUE}',
                    [motivazione_richiesta] = LTRIM(
                        SUBSTRING(
                            COALESCE([motivazione_richiesta], N''),
                            LEN(N'{CERTIFICA_PRESENZA_MARKER}') + 1,
                            LEN(COALESCE([motivazione_richiesta], N''))
                        )
                    )
                WHERE [tipo_assenza] = N'{ALTRO_VALUE}'
                  AND COALESCE([motivazione_richiesta], N'') LIKE N'[[]CERTIFICA_PRESENZA[]]%'
                """
            )
            cursor.execute(_build_check_sql(table_name))
            cursor.execute(
                f"ALTER TABLE {table_name} CHECK CONSTRAINT {_quote_ident(CHECK_NAME)}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Vincolo CK_assenze_tipo riallineato e valori legacy convertiti a "
                "'Flessibilit\u00e0' / 'Certifica presenza'."
            )
        )
