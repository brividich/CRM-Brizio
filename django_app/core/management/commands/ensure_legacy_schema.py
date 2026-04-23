from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from core.legacy_utils import legacy_table_columns


@dataclass(frozen=True)
class SqlStep:
    name: str
    sql: str


def _normalize_sql(sql: str) -> str:
    return "\n".join(line.rstrip() for line in sql.strip().splitlines())


SQL_STEPS = [
    SqlStep(
        "info_personali",
        """
        IF OBJECT_ID(N'dbo.info_personali', N'U') IS NULL
        BEGIN
            CREATE TABLE dbo.info_personali (
                id INT NOT NULL IDENTITY(1,1),
                utente_id INT NULL,
                qualifica NVARCHAR(200) NULL,
                reparto NVARCHAR(200) NULL,
                matricola NVARCHAR(100) NULL,
                data_assunzione NVARCHAR(50) NULL,
                email NVARCHAR(200) NULL,
                data_assunzione_date DATE NULL,
                CONSTRAINT PK_info_personali PRIMARY KEY (id)
            );
        END
        """,
    ),
    SqlStep(
        "dipendenti",
        """
        IF OBJECT_ID(N'dbo.dipendenti', N'U') IS NULL
        BEGIN
            CREATE TABLE dbo.dipendenti (
                id INT NOT NULL IDENTITY(1,1),
                sharepoint_item_id NVARCHAR(50) NULL,
                title NVARCHAR(255) NULL,
                created_datetime DATETIME2 NULL,
                modified_datetime DATETIME2 NULL,
                created_by NVARCHAR(255) NULL,
                modified_by NVARCHAR(255) NULL,
                utente_id INT NULL,
                CONSTRAINT PK_dipendenti PRIMARY KEY (id)
            );
        END
        """,
    ),
    SqlStep(
        "capi_reparto",
        """
        IF OBJECT_ID(N'dbo.capi_reparto', N'U') IS NULL
        BEGIN
            CREATE TABLE dbo.capi_reparto (
                id INT NOT NULL IDENTITY(1,1),
                sharepoint_item_id NVARCHAR(50) NULL,
                title NVARCHAR(255) NULL,
                indirizzo_email NVARCHAR(254) NULL,
                created_datetime DATETIME2 NULL,
                modified_datetime DATETIME2 NULL,
                created_by NVARCHAR(255) NULL,
                modified_by NVARCHAR(255) NULL,
                utente_id INT NULL,
                Nome NVARCHAR(255) NULL,
                ruolo_id INT NULL,
                CONSTRAINT PK_capi_reparto PRIMARY KEY (id)
            );
        END
        """,
    ),
    SqlStep(
        "ordini_produzione",
        """
        IF OBJECT_ID(N'dbo.ordini_produzione', N'U') IS NULL
        BEGIN
            CREATE TABLE dbo.ordini_produzione (
                id INT NOT NULL IDENTITY(1,1),
                sharepoint_item_id NVARCHAR(50) NOT NULL,
                title NVARCHAR(100) NULL,
                part_number NVARCHAR(200) NULL,
                in1text NVARCHAR(255) NULL,
                capocomessa NVARCHAR(255) NULL,
                incaricato NVARCHAR(255) NULL,
                stato NVARCHAR(50) NULL,
                created_datetime DATETIME2 NULL,
                modified_datetime DATETIME2 NULL,
                created_by NVARCHAR(255) NULL,
                modified_by NVARCHAR(255) NULL,
                CONSTRAINT PK_ordini_produzione PRIMARY KEY (id)
            );
        END
        """,
    ),
    SqlStep(
        "anomalie",
        """
        IF OBJECT_ID(N'dbo.anomalie', N'U') IS NULL
        BEGIN
            CREATE TABLE dbo.anomalie (
                id INT NOT NULL IDENTITY(1,1),
                sharepoint_item_id NVARCHAR(50) NULL,
                ex_op_nominativo NVARCHAR(100) NULL,
                op_lookup_id INT NULL,
                seriale NVARCHAR(200) NULL,
                descrizione NVARCHAR(MAX) NULL,
                note_capocommessa NVARCHAR(MAX) NULL,
                pezzo_recuperato BIT NULL CONSTRAINT DF_anomalie_pezzo_recuperato DEFAULT 0,
                aprire_rdc BIT NULL CONSTRAINT DF_anomalie_aprire_rdc DEFAULT 0,
                numero_rdc NVARCHAR(100) NULL,
                segnalare_cliente BIT NULL CONSTRAINT DF_anomalie_segnalare_cliente DEFAULT 0,
                chiudere BIT NULL CONSTRAINT DF_anomalie_chiudere DEFAULT 0,
                avanzamento NVARCHAR(100) NULL CONSTRAINT DF_anomalie_avanzamento DEFAULT N'Accetto lo stato',
                created_datetime DATETIME2 NULL,
                modified_datetime DATETIME2 NULL,
                created_by NVARCHAR(255) NULL,
                modified_by NVARCHAR(255) NULL,
                created_by_user_id INT NULL,
                ordine_id INT NULL,
                CONSTRAINT PK_anomalie PRIMARY KEY (id)
            );
        END
        """,
    ),
    SqlStep(
        "sync_audit",
        """
        IF OBJECT_ID(N'dbo.sync_audit', N'U') IS NULL
        BEGIN
            CREATE TABLE dbo.sync_audit (
                id INT NOT NULL IDENTITY(1,1),
                sync_type NVARCHAR(80) NOT NULL,
                trigger_source NVARCHAR(80) NULL,
                initiated_by_user_id INT NULL,
                initiated_by_email NVARCHAR(200) NULL,
                status NVARCHAR(30) NOT NULL,
                started_at DATETIME2 NULL,
                ended_at DATETIME2 NULL,
                duration_ms INT NULL,
                batch_id NVARCHAR(64) NULL,
                details_json NVARCHAR(MAX) NULL,
                error_text NVARCHAR(MAX) NULL,
                created_at DATETIME2 NOT NULL CONSTRAINT DF_sync_audit_created_at DEFAULT SYSUTCDATETIME(),
                CONSTRAINT PK_sync_audit PRIMARY KEY (id)
            );
        END
        """,
    ),
    SqlStep(
        "ui_assenze_colors",
        """
        IF OBJECT_ID(N'dbo.ui_assenze_colors', N'U') IS NULL
        BEGIN
            CREATE TABLE dbo.ui_assenze_colors (
                color_key NVARCHAR(64) NOT NULL,
                color_value NVARCHAR(7) NOT NULL,
                updated_at DATETIME2 NULL,
                CONSTRAINT PK_ui_assenze_colors PRIMARY KEY (color_key)
            );
        END
        """,
    ),
    SqlStep(
        "ui_assenze_colors_user",
        """
        IF OBJECT_ID(N'dbo.ui_assenze_colors_user', N'U') IS NULL
        BEGIN
            CREATE TABLE dbo.ui_assenze_colors_user (
                user_key NVARCHAR(128) NOT NULL,
                color_key NVARCHAR(64) NOT NULL,
                color_value NVARCHAR(7) NOT NULL,
                updated_at DATETIME2 NULL,
                CONSTRAINT PK_ui_assenze_colors_user PRIMARY KEY (user_key, color_key)
            );
        END
        """,
    ),
]


ALIGNMENT_STEPS = [
    SqlStep(
        "ordini_produzione_id_sequence",
        """
        IF OBJECT_ID(N'dbo.ordini_produzione', N'U') IS NOT NULL
           AND NOT EXISTS (
               SELECT 1
               FROM sys.columns
               WHERE object_id = OBJECT_ID(N'dbo.ordini_produzione')
                 AND name = N'id'
           )
        BEGIN
            IF OBJECT_ID(N'dbo.seq_ordini_produzione_id', N'SO') IS NULL
                CREATE SEQUENCE dbo.seq_ordini_produzione_id AS INT START WITH 1 INCREMENT BY 1;

            EXEC sys.sp_executesql N'ALTER TABLE dbo.ordini_produzione ADD id INT NULL';

            EXEC sys.sp_executesql N'
                UPDATE dbo.ordini_produzione
                SET id = NEXT VALUE FOR dbo.seq_ordini_produzione_id
                WHERE id IS NULL
            ';

            EXEC sys.sp_executesql N'ALTER TABLE dbo.ordini_produzione ALTER COLUMN id INT NOT NULL';
            EXEC sys.sp_executesql N'
                ALTER TABLE dbo.ordini_produzione
                ADD CONSTRAINT DF_ordini_produzione_id DEFAULT NEXT VALUE FOR dbo.seq_ordini_produzione_id FOR id
            ';
        END
        """,
    ),
    SqlStep(
        "ordini_produzione_columns",
        """
        IF OBJECT_ID(N'dbo.ordini_produzione', N'U') IS NOT NULL
        BEGIN
            IF COL_LENGTH(N'dbo.ordini_produzione', N'sharepoint_item_id') IS NULL
                ALTER TABLE dbo.ordini_produzione ADD sharepoint_item_id NVARCHAR(50) NULL;
            IF COL_LENGTH(N'dbo.ordini_produzione', N'title') IS NULL
                ALTER TABLE dbo.ordini_produzione ADD title NVARCHAR(100) NULL;
            IF COL_LENGTH(N'dbo.ordini_produzione', N'part_number') IS NULL
                ALTER TABLE dbo.ordini_produzione ADD part_number NVARCHAR(200) NULL;
            IF COL_LENGTH(N'dbo.ordini_produzione', N'in1text') IS NULL
                ALTER TABLE dbo.ordini_produzione ADD in1text NVARCHAR(255) NULL;
            IF COL_LENGTH(N'dbo.ordini_produzione', N'capocomessa') IS NULL
                ALTER TABLE dbo.ordini_produzione ADD capocomessa NVARCHAR(255) NULL;
            IF COL_LENGTH(N'dbo.ordini_produzione', N'incaricato') IS NULL
                ALTER TABLE dbo.ordini_produzione ADD incaricato NVARCHAR(255) NULL;
            IF COL_LENGTH(N'dbo.ordini_produzione', N'stato') IS NULL
                ALTER TABLE dbo.ordini_produzione ADD stato NVARCHAR(50) NULL;
            IF COL_LENGTH(N'dbo.ordini_produzione', N'created_datetime') IS NULL
                ALTER TABLE dbo.ordini_produzione ADD created_datetime DATETIME2 NULL;
            IF COL_LENGTH(N'dbo.ordini_produzione', N'modified_datetime') IS NULL
                ALTER TABLE dbo.ordini_produzione ADD modified_datetime DATETIME2 NULL;
            IF COL_LENGTH(N'dbo.ordini_produzione', N'created_by') IS NULL
                ALTER TABLE dbo.ordini_produzione ADD created_by NVARCHAR(255) NULL;
            IF COL_LENGTH(N'dbo.ordini_produzione', N'modified_by') IS NULL
                ALTER TABLE dbo.ordini_produzione ADD modified_by NVARCHAR(255) NULL;
        END
        """,
    ),
    SqlStep(
        "anomalie_columns",
        """
        IF OBJECT_ID(N'dbo.anomalie', N'U') IS NOT NULL
        BEGIN
            IF COL_LENGTH(N'dbo.anomalie', N'sharepoint_item_id') IS NULL
                ALTER TABLE dbo.anomalie ADD sharepoint_item_id NVARCHAR(50) NULL;
            IF COL_LENGTH(N'dbo.anomalie', N'ex_op_nominativo') IS NULL
                ALTER TABLE dbo.anomalie ADD ex_op_nominativo NVARCHAR(100) NULL;
            IF COL_LENGTH(N'dbo.anomalie', N'op_lookup_id') IS NULL
                ALTER TABLE dbo.anomalie ADD op_lookup_id INT NULL;
            IF COL_LENGTH(N'dbo.anomalie', N'seriale') IS NULL
                ALTER TABLE dbo.anomalie ADD seriale NVARCHAR(200) NULL;
            IF COL_LENGTH(N'dbo.anomalie', N'descrizione') IS NULL
                ALTER TABLE dbo.anomalie ADD descrizione NVARCHAR(MAX) NULL;
            IF COL_LENGTH(N'dbo.anomalie', N'note_capocommessa') IS NULL
                ALTER TABLE dbo.anomalie ADD note_capocomessa NVARCHAR(MAX) NULL;
            IF COL_LENGTH(N'dbo.anomalie', N'pezzo_recuperato') IS NULL
                ALTER TABLE dbo.anomalie ADD pezzo_recuperato BIT NULL CONSTRAINT DF_anomalie_pezzo_recuperato_add DEFAULT 0;
            IF COL_LENGTH(N'dbo.anomalie', N'aprire_rdc') IS NULL
                ALTER TABLE dbo.anomalie ADD aprire_rdc BIT NULL CONSTRAINT DF_anomalie_aprire_rdc_add DEFAULT 0;
            IF COL_LENGTH(N'dbo.anomalie', N'numero_rdc') IS NULL
                ALTER TABLE dbo.anomalie ADD numero_rdc NVARCHAR(100) NULL;
            IF COL_LENGTH(N'dbo.anomalie', N'segnalare_cliente') IS NULL
                ALTER TABLE dbo.anomalie ADD segnalare_cliente BIT NULL CONSTRAINT DF_anomalie_segnalare_cliente_add DEFAULT 0;
            IF COL_LENGTH(N'dbo.anomalie', N'chiudere') IS NULL
                ALTER TABLE dbo.anomalie ADD chiudere BIT NULL CONSTRAINT DF_anomalie_chiudere_add DEFAULT 0;
            IF COL_LENGTH(N'dbo.anomalie', N'avanzamento') IS NULL
                ALTER TABLE dbo.anomalie ADD avanzamento NVARCHAR(100) NULL CONSTRAINT DF_anomalie_avanzamento_add DEFAULT N'Accetto lo stato';
            IF COL_LENGTH(N'dbo.anomalie', N'created_datetime') IS NULL
                ALTER TABLE dbo.anomalie ADD created_datetime DATETIME2 NULL;
            IF COL_LENGTH(N'dbo.anomalie', N'modified_datetime') IS NULL
                ALTER TABLE dbo.anomalie ADD modified_datetime DATETIME2 NULL;
            IF COL_LENGTH(N'dbo.anomalie', N'created_by') IS NULL
                ALTER TABLE dbo.anomalie ADD created_by NVARCHAR(255) NULL;
            IF COL_LENGTH(N'dbo.anomalie', N'modified_by') IS NULL
                ALTER TABLE dbo.anomalie ADD modified_by NVARCHAR(255) NULL;
            IF COL_LENGTH(N'dbo.anomalie', N'created_by_user_id') IS NULL
                ALTER TABLE dbo.anomalie ADD created_by_user_id INT NULL;
            IF COL_LENGTH(N'dbo.anomalie', N'ordine_id') IS NULL
                ALTER TABLE dbo.anomalie ADD ordine_id INT NULL;
        END
        """,
    ),
]


INDEX_STEPS = [
    SqlStep(
        "IX_dipendenti_sp_item",
        """
        IF OBJECT_ID(N'dbo.dipendenti', N'U') IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_dipendenti_sp_item' AND object_id = OBJECT_ID(N'dbo.dipendenti'))
           AND COL_LENGTH(N'dbo.dipendenti', N'sharepoint_item_id') IS NOT NULL
        BEGIN
            CREATE UNIQUE INDEX IX_dipendenti_sp_item ON dbo.dipendenti (sharepoint_item_id)
            WHERE sharepoint_item_id IS NOT NULL;
        END
        """,
    ),
    SqlStep(
        "IX_capi_reparto_sp_item",
        """
        IF OBJECT_ID(N'dbo.capi_reparto', N'U') IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_capi_reparto_sp_item' AND object_id = OBJECT_ID(N'dbo.capi_reparto'))
           AND COL_LENGTH(N'dbo.capi_reparto', N'sharepoint_item_id') IS NOT NULL
        BEGIN
            CREATE UNIQUE INDEX IX_capi_reparto_sp_item ON dbo.capi_reparto (sharepoint_item_id)
            WHERE sharepoint_item_id IS NOT NULL;
        END
        """,
    ),
    SqlStep(
        "IX_op_title",
        """
        IF OBJECT_ID(N'dbo.ordini_produzione', N'U') IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_op_title' AND object_id = OBJECT_ID(N'dbo.ordini_produzione'))
           AND COL_LENGTH(N'dbo.ordini_produzione', N'title') IS NOT NULL
        BEGIN
            CREATE INDEX IX_op_title ON dbo.ordini_produzione (title);
        END
        """,
    ),
    SqlStep(
        "IX_op_stato",
        """
        IF OBJECT_ID(N'dbo.ordini_produzione', N'U') IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_op_stato' AND object_id = OBJECT_ID(N'dbo.ordini_produzione'))
           AND COL_LENGTH(N'dbo.ordini_produzione', N'stato') IS NOT NULL
        BEGIN
            CREATE INDEX IX_op_stato ON dbo.ordini_produzione (stato);
        END
        """,
    ),
    SqlStep(
        "IX_anomalie_sp_item",
        """
        IF OBJECT_ID(N'dbo.anomalie', N'U') IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_anomalie_sp_item' AND object_id = OBJECT_ID(N'dbo.anomalie'))
           AND COL_LENGTH(N'dbo.anomalie', N'sharepoint_item_id') IS NOT NULL
        BEGIN
            CREATE UNIQUE INDEX IX_anomalie_sp_item ON dbo.anomalie (sharepoint_item_id)
            WHERE sharepoint_item_id IS NOT NULL;
        END
        """,
    ),
    SqlStep(
        "IX_anomalie_op_lookup_id",
        """
        IF OBJECT_ID(N'dbo.anomalie', N'U') IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_anomalie_op_lookup_id' AND object_id = OBJECT_ID(N'dbo.anomalie'))
           AND COL_LENGTH(N'dbo.anomalie', N'op_lookup_id') IS NOT NULL
        BEGIN
            CREATE INDEX IX_anomalie_op_lookup_id ON dbo.anomalie (op_lookup_id);
        END
        """,
    ),
    SqlStep(
        "IX_anomalie_seriale",
        """
        IF OBJECT_ID(N'dbo.anomalie', N'U') IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_anomalie_seriale' AND object_id = OBJECT_ID(N'dbo.anomalie'))
           AND COL_LENGTH(N'dbo.anomalie', N'seriale') IS NOT NULL
        BEGIN
            CREATE INDEX IX_anomalie_seriale ON dbo.anomalie (seriale);
        END
        """,
    ),
]


class Command(BaseCommand):
    help = "Crea o riallinea le tabelle legacy operative richieste dal portale su SQL Server."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Mostra gli step senza applicarli.")

    def handle(self, *args, **options):
        if connections["default"].vendor != "microsoft":
            raise CommandError("ensure_legacy_schema supporta solo SQL Server/mssql.")

        dry_run = bool(options.get("dry_run"))
        steps = [*SQL_STEPS, *ALIGNMENT_STEPS, *INDEX_STEPS]

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run: nessuna modifica applicata."))
            for step in steps:
                self.stdout.write(f"[DRY] {step.name}")
            return

        applied: list[str] = []
        with transaction.atomic():
            with connections["default"].cursor() as cursor:
                for step in steps:
                    cursor.execute(_normalize_sql(step.sql))
                    applied.append(step.name)

        try:
            legacy_table_columns.cache_clear()
        except AttributeError:
            pass

        self.stdout.write(self.style.SUCCESS(f"Schema legacy riallineato: {len(applied)} step eseguiti."))
        for name in applied:
            self.stdout.write(f" - {name}")
