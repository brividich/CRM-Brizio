CREATE TRIGGER [dbo].[trg_tasks_automation]
ON [dbo].[tasks_task]
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    -- Guard: salta silenziosamente se la tabella automation_event_queue non esiste ancora
    IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NULL
        RETURN;

    -- Gestione INSERT (Nuovo Task creato)
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
            N'tasks',
            N'tasks_task',
            CAST(i.id AS NVARCHAR(100)),
            N'insert',
            N'tasks_insert',
            NULL,
            (SELECT * FROM inserted i2 WHERE i2.id = i.id FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            NULL,
            N'pending',
            SYSUTCDATETIME()
        FROM inserted i;
    END

    -- Gestione UPDATE (Cambio stato, assegnatario o scadenza)
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
            N'tasks',
            N'tasks_task',
            CAST(i.id AS NVARCHAR(100)),
            N'update',
            N'tasks_update',
            NULL,
            (
                SELECT
                    i.*,
                    d.status AS old_status,
                    d.assigned_to_id AS old_assigned_to_id,
                    d.due_date AS old_due_date
                FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
            ),
            (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            N'pending',
            SYSUTCDATETIME()
        FROM inserted i
        JOIN deleted d ON i.id = d.id
        -- Triggeriamo l'evento solo se cambiano campi critici per evitare rumore
        WHERE ISNULL(i.status, N'') <> ISNULL(d.status, N'')
           OR ISNULL(i.assigned_to_id, -1) <> ISNULL(d.assigned_to_id, -1)
           OR ISNULL(CONVERT(NVARCHAR(30), i.due_date, 126), N'') <> ISNULL(CONVERT(NVARCHAR(30), d.due_date, 126), N'');
    END
END
