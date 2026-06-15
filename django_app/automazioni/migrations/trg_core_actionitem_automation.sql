CREATE TRIGGER [dbo].[trg_core_actionitem_automation]
ON [dbo].[core_actionitem]
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    -- Guard: salta silenziosamente se la tabella automation_event_queue non esiste ancora
    IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NULL
        RETURN;

    -- Gestione INSERT (Nuova azione CAPA)
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
            N'core_actionitem',
            N'core_actionitem',
            CAST(i.id AS NVARCHAR(100)),
            N'insert',
            N'core_actionitem_insert',
            NULL,
            (SELECT * FROM inserted i2 WHERE i2.id = i.id FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            NULL,
            N'pending',
            SYSUTCDATETIME()
        FROM inserted i;
    END

    -- Gestione UPDATE (Cambio stato workflow CAPA)
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
            N'core_actionitem',
            N'core_actionitem',
            CAST(i.id AS NVARCHAR(100)),
            N'update',
            N'core_actionitem_update',
            N'stato',
            (
                SELECT
                    i.*,
                    d.stato AS old_stato
                FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
            ),
            (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            N'pending',
            SYSUTCDATETIME()
        FROM inserted i
        JOIN deleted d ON i.id = d.id
        WHERE ISNULL(i.stato, N'') <> ISNULL(d.stato, N'');
    END
END
