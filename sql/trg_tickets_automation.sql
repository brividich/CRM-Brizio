CREATE TRIGGER [dbo].[trg_tickets_automation]
ON [dbo].[tickets_ticket]
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    -- Gestione INSERT (Nuovo Ticket)
    IF EXISTS (SELECT * FROM inserted) AND NOT EXISTS (SELECT * FROM deleted)
    BEGIN
        INSERT INTO [dbo].[automation_event_queue] (
            [source_code],
            [source_table],
            [source_pk],
            [operation_type],
            [payload_json],
            [status],
            [created_at]
        )
        SELECT
            'tickets',
            'tickets_ticket',
            CAST(i.id AS NVARCHAR(100)),
            'insert',
            (SELECT * FROM inserted i2 WHERE i2.id = i.id FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            'pending',
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
            [payload_json],
            [status],
            [created_at]
        )
        SELECT
            'tickets',
            'tickets_ticket',
            CAST(i.id AS NVARCHAR(100)),
            'update',
            (SELECT i.*, d.stato as old_stato, d.assegnato_a as old_assegnato_a FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            'pending',
            SYSUTCDATETIME()
        FROM inserted i
        JOIN deleted d ON i.id = d.id
        WHERE i.stato <> d.stato OR ISNULL(i.assegnato_a, '') <> ISNULL(d.assegnato_a, '');
    END
END