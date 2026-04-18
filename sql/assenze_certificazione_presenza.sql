-- Creazione conservativa della tabella assenze_certificazionepresenza.
-- Idempotente: se la tabella esiste gia' non viene ricreata ne' alterata.
-- Corrisponde alle migration Django: assenze 0001 + 0002.
--
-- Da eseguire su ambienti dove le migration Django non possono girare
-- direttamente, oppure come fix manuale se la tabella risulta mancante.

IF OBJECT_ID(N'dbo.assenze_certificazionepresenza', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[assenze_certificazionepresenza] (
        [id]                  bigint          NOT NULL IDENTITY(1,1) PRIMARY KEY,
        [nome_dipendente]     nvarchar(200)   NOT NULL,
        [data]                date            NOT NULL,
        [entrata_mattina]     time            NOT NULL,
        [uscita_mattina]      time            NOT NULL,
        [turno_pomeriggio]    bit             NOT NULL,
        [entrata_pomeriggio]  time            NULL,
        [uscita_pomeriggio]   time            NULL,
        [note]                nvarchar(max)   NOT NULL DEFAULT '',
        [inserito_da]         nvarchar(200)   NOT NULL DEFAULT '',
        [created_at]          datetimeoffset  NOT NULL,
        [updated_at]          datetimeoffset  NOT NULL,
        -- Campi aggiunti da migration 0002
        [assenza_id]          int             NULL,
        [capo_reparto_email]  nvarchar(200)   NOT NULL DEFAULT '',
        [consenso]            nvarchar(20)    NOT NULL DEFAULT 'In attesa',
        [origine]             nvarchar(10)    NOT NULL DEFAULT 'admin',
        [salta_approvazione]  bit             NOT NULL DEFAULT 0,
        [sharepoint_item_id]  nvarchar(64)    NOT NULL DEFAULT ''
    );
    PRINT 'Tabella assenze_certificazionepresenza creata.';
END
ELSE
BEGIN
    PRINT 'Tabella assenze_certificazionepresenza gia'' presente — nessuna modifica.';

    -- Aggiunta conservativa delle colonne introdotte da migration 0002
    -- (per ambienti dove e' stata applicata solo la 0001).
    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.assenze_certificazionepresenza')
          AND name = 'assenza_id'
    )
        ALTER TABLE [dbo].[assenze_certificazionepresenza]
            ADD [assenza_id] int NULL;

    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.assenze_certificazionepresenza')
          AND name = 'capo_reparto_email'
    )
        ALTER TABLE [dbo].[assenze_certificazionepresenza]
            ADD [capo_reparto_email] nvarchar(200) NOT NULL DEFAULT '';

    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.assenze_certificazionepresenza')
          AND name = 'consenso'
    )
        ALTER TABLE [dbo].[assenze_certificazionepresenza]
            ADD [consenso] nvarchar(20) NOT NULL DEFAULT 'In attesa';

    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.assenze_certificazionepresenza')
          AND name = 'origine'
    )
        ALTER TABLE [dbo].[assenze_certificazionepresenza]
            ADD [origine] nvarchar(10) NOT NULL DEFAULT 'admin';

    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.assenze_certificazionepresenza')
          AND name = 'salta_approvazione'
    )
        ALTER TABLE [dbo].[assenze_certificazionepresenza]
            ADD [salta_approvazione] bit NOT NULL DEFAULT 0;

    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.assenze_certificazionepresenza')
          AND name = 'sharepoint_item_id'
    )
        ALTER TABLE [dbo].[assenze_certificazionepresenza]
            ADD [sharepoint_item_id] nvarchar(64) NOT NULL DEFAULT '';
END
