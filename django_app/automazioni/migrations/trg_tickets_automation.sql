CREATE TRIGGER [dbo].[trg_tickets_automation]
ON [dbo].[tickets_ticket]
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    -- Guard: salta silenziosamente se la tabella automation_event_queue non esiste ancora
    IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NULL
        RETURN;

    -- Gestione INSERT (Nuovo Ticket)
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
            'tickets',
            'insert',
            CAST(id AS NVARCHAR(100)),
            (SELECT * FROM inserted i2 WHERE i2.id = i.id FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            'pending',
            GETDATE()
        FROM inserted i;
    END

    -- Gestione UPDATE (Cambio Stato o Assegnatario)
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
            'tickets',
            'update',
            CAST(i.id AS NVARCHAR(100)),
            (SELECT i.*, d.stato as old_stato, d.assegnato_a as old_assegnato_a FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            'pending',
            GETDATE()
        FROM inserted i
        JOIN deleted d ON i.id = d.id
        WHERE i.stato <> d.stato OR i.assegnato_a <> d.assegnato_a;
    END
END