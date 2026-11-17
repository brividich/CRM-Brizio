CREATE TRIGGER [dbo].[trg_tickets_automation]
ON [dbo].[tickets_ticket]
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    -- Guard: salta silenziosamente se la tabella automation_event_queue non esiste ancora
    IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NULL
        RETURN;

    -- Audit S3: un errore sulla coda automazioni non deve annullare la richiesta
    -- dell utente. Errori di istruzione intercettati qui; se la transazione e
    -- compromessa (XACT_STATE = -1) l errore viene rilanciato.
    -- Unico file del trigger: una copia in sql/ veniva applicata dopo questa e
    -- non scriveva old_payload_json, quindi le regole «specific_field» (es. mail
    -- al richiedente al cambio stato) non partivano mai.
    SET XACT_ABORT OFF;
    BEGIN TRY

    -- Gestione INSERT (Nuovo Ticket)
    IF EXISTS (SELECT * FROM inserted) AND NOT EXISTS (SELECT * FROM deleted)
    BEGIN
        INSERT INTO [dbo].[automation_event_queue] (
            [source_code],
            [source_table],
            [source_pk],
            [operation_type],
            [event_code],
            [watched_field],
            [payload_json],
            [old_payload_json],
            [status],
            [created_at]
        )
        SELECT
            N'tickets',
            N'tickets_ticket',
            CAST(i.id AS NVARCHAR(100)),
            N'insert',
            N'tickets_insert',
            NULL,
            (SELECT * FROM inserted i2 WHERE i2.id = i.id FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            NULL,
            N'pending',
            SYSUTCDATETIME()
        FROM inserted i;
    END

    -- Gestione UPDATE (Cambio Stato o Assegnatario)
    IF EXISTS (SELECT * FROM inserted) AND EXISTS (SELECT * FROM deleted)
    BEGIN
        INSERT INTO [dbo].[automation_event_queue] (
            [source_code],
            [source_table],
            [source_pk],
            [operation_type],
            [event_code],
            [watched_field],
            [payload_json],
            [old_payload_json],
            [status],
            [created_at]
        )
        SELECT
            N'tickets',
            N'tickets_ticket',
            CAST(i.id AS NVARCHAR(100)),
            N'update',
            N'tickets_update',
            NULL,
            (
                SELECT
                    i.*,
                    d.stato AS old_stato,
                    d.assegnato_a AS old_assegnato_a
                FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
            ),
            (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            N'pending',
            SYSUTCDATETIME()
        FROM inserted i
        JOIN deleted d ON i.id = d.id
        WHERE ISNULL(i.stato, N'') <> ISNULL(d.stato, N'')
           OR ISNULL(i.assegnato_a, N'') <> ISNULL(d.assegnato_a, N'');
    END

    END TRY
    BEGIN CATCH
        IF XACT_STATE() = -1
            THROW;
    END CATCH;
END
