CREATE TRIGGER [dbo].[trg_tasks_kickoff_automation]
ON [dbo].[tasks_kickoffmeeting]
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NULL
        RETURN;

    -- INSERT (nuovo incontro creato)
    IF EXISTS (SELECT * FROM inserted) AND NOT EXISTS (SELECT * FROM deleted)
    BEGIN
        INSERT INTO [dbo].[automation_event_queue] (
            [source_code], [source_table], [source_pk], [operation_type],
            [event_code], [watched_field], [payload_json], [old_payload_json],
            [status], [created_at]
        )
        SELECT
            N'tasks_kickoff',
            N'tasks_kickoffmeeting',
            CAST(i.id AS NVARCHAR(100)),
            N'insert',
            N'tasks_kickoff_insert',
            NULL,
            (SELECT * FROM inserted i2 WHERE i2.id = i.id FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            NULL,
            N'pending',
            SYSUTCDATETIME()
        FROM inserted i;
    END

    -- UPDATE (verbale compilato/aggiornato) — solo se cambia `note`
    IF EXISTS (SELECT * FROM inserted) AND EXISTS (SELECT * FROM deleted)
    BEGIN
        INSERT INTO [dbo].[automation_event_queue] (
            [source_code], [source_table], [source_pk], [operation_type],
            [event_code], [watched_field], [payload_json], [old_payload_json],
            [status], [created_at]
        )
        SELECT
            N'tasks_kickoff',
            N'tasks_kickoffmeeting',
            CAST(i.id AS NVARCHAR(100)),
            N'update',
            N'tasks_kickoff_update',
            N'note',
            (
                SELECT i.*, d.note AS old_note
                FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
            ),
            (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            N'pending',
            SYSUTCDATETIME()
        FROM inserted i
        JOIN deleted d ON i.id = d.id
        WHERE ISNULL(i.note, N'') <> ISNULL(d.note, N'');
    END
END
