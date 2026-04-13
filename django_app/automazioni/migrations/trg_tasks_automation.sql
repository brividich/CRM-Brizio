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
            [operation_type], 
            [item_id], 
            [payload_json], 
            [status], 
            [created_at]
        )
        SELECT 
            'tasks', 
            'insert', 
            CAST(id AS NVARCHAR(100)),
            (SELECT * FROM inserted i2 WHERE i2.id = i.id FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            'pending',
            GETDATE()
        FROM inserted i;
    END

    -- Gestione UPDATE (Cambio stato, assegnatario o scadenza)
    IF EXISTS (SELECT * FROM inserted) AND EXISTS (SELECT * FROM deleted)
    BEGIN
        INSERT INTO [dbo].[automation_event_queue] (
            [source_code], 
            [operation_type], 
            [item_id], 
            [payload_json], 
            [status], 
            [created_at]
        )
        SELECT 
            'tasks', 
            'update', 
            CAST(i.id AS NVARCHAR(100)),
            (SELECT i.*, d.status as old_status, d.assigned_to_id as old_assigned_to_id, d.due_date as old_due_date FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            'pending',
            GETDATE()
        FROM inserted i
        JOIN deleted d ON i.id = d.id
        -- Triggeriamo l'evento solo se cambiano campi critici per evitare rumore
        WHERE i.status <> d.status OR i.assigned_to_id <> d.assigned_to_id OR i.due_date <> d.due_date;
    END
END