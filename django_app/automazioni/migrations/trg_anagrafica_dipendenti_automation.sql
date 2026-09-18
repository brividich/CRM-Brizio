CREATE TRIGGER [dbo].[trg_anagrafica_dipendenti_automation]
ON [dbo].[anagrafica_dipendenti]
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    -- Guard: salta silenziosamente se la tabella automation_event_queue non esiste ancora
    IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NULL
        RETURN;

    -- Gestione UPDATE (Cambio mansione)
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
        N'anagrafica_dipendenti',
        N'anagrafica_dipendenti',
        CAST(i.id AS NVARCHAR(100)),
        N'update',
        N'anagrafica_dipendenti_update',
        N'mansione',
        (
            SELECT
                i.*,
                d.mansione AS old_mansione
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
        ),
        (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
        N'pending',
        SYSUTCDATETIME()
    FROM inserted i
    JOIN deleted d ON i.id = d.id
    WHERE ISNULL(i.mansione, N'') <> ISNULL(d.mansione, N'');
END
