-- Creazione conservativa della tabella legacy [assenze].
-- Idempotente: se la tabella esiste gia' non viene ricreata ne' alterata.
-- Eseguire su SQL Server (ambiente test o prod) dove lo schema legacy e' assente.
--
-- Colonne derivate dalle query in assenze/views.py (tutti i campi letti/scritti).

IF OBJECT_ID(N'dbo.assenze', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[assenze] (
        [id]                        int             NOT NULL IDENTITY(1,1) PRIMARY KEY,

        -- Identita dipendente
        [nome_lookup_id]            int             NULL,
        [copia_nome]                nvarchar(255)   NULL DEFAULT '',
        [email_esterna]             nvarchar(255)   NULL DEFAULT '',
        [title]                     nvarchar(255)   NULL DEFAULT '',

        -- Tipo e periodo
        [tipo_assenza]              nvarchar(100)   NULL DEFAULT '',
        [data_inizio]               datetime2       NULL,
        [data_fine]                 datetime2       NULL,
        [motivazione_richiesta]     nvarchar(max)   NULL DEFAULT '',

        -- Approvazione
        [consenso]                  nvarchar(50)    NULL DEFAULT 'In attesa',
        [moderation_status]         int             NULL,
        [approvazione_datetime]     datetime2       NULL,
        [salta_approvazione]        bit             NOT NULL DEFAULT 0,

        -- Capo reparto (FK locale + lookup SharePoint)
        [capo_reparto_id]           int             NULL,
        [capo_reparto_lookup_id]    int             NULL,

        -- SharePoint sync
        [sharepoint_item_id]        nvarchar(64)    NULL DEFAULT '',

        -- Timestamp
        [created_datetime]          datetime2       NULL,
        [modified_datetime]         datetime2       NULL,

        -- Colonne opzionali (aggiunte successivamente — gestite via management command)
        [certificato_medico]        nvarchar(255)   NULL,
        [note_gestione]             nvarchar(max)   NULL
    );
    PRINT 'Tabella [assenze] creata.';
END
ELSE
BEGIN
    PRINT 'Tabella [assenze] gia'' presente — nessuna modifica.';

    -- Aggiunta conservativa delle colonne opzionali per ambienti con schema parziale.
    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.assenze') AND name = 'certificato_medico'
    )
        ALTER TABLE [dbo].[assenze] ADD [certificato_medico] nvarchar(255) NULL;

    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.assenze') AND name = 'note_gestione'
    )
        ALTER TABLE [dbo].[assenze] ADD [note_gestione] nvarchar(max) NULL;

    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.assenze') AND name = 'capo_reparto_id'
    )
        ALTER TABLE [dbo].[assenze] ADD [capo_reparto_id] int NULL;

    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.assenze') AND name = 'capo_reparto_lookup_id'
    )
        ALTER TABLE [dbo].[assenze] ADD [capo_reparto_lookup_id] int NULL;

    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.assenze') AND name = 'moderation_status'
    )
        ALTER TABLE [dbo].[assenze] ADD [moderation_status] int NULL;

    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.assenze') AND name = 'approvazione_datetime'
    )
        ALTER TABLE [dbo].[assenze] ADD [approvazione_datetime] datetime2 NULL;

    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.assenze') AND name = 'sharepoint_item_id'
    )
        ALTER TABLE [dbo].[assenze] ADD [sharepoint_item_id] nvarchar(64) NULL DEFAULT '';

    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.assenze') AND name = 'email_esterna'
    )
        ALTER TABLE [dbo].[assenze] ADD [email_esterna] nvarchar(255) NULL DEFAULT '';

    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.assenze') AND name = 'created_datetime'
    )
        ALTER TABLE [dbo].[assenze] ADD [created_datetime] datetime2 NULL;

    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.assenze') AND name = 'modified_datetime'
    )
        ALTER TABLE [dbo].[assenze] ADD [modified_datetime] datetime2 NULL;
END
