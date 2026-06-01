CREATE TRIGGER [dbo].[trg_anomalie_automation]
ON [dbo].[anomalie]
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    -- Guard: salta silenziosamente se la tabella automation_event_queue non esiste ancora
    IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NULL
        RETURN;

    -- Gestione INSERT (Nuova Anomalia)
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
            N'anomalie',
            N'anomalie',
            CAST(i.id AS NVARCHAR(100)),
            N'insert',
            N'anomalie_insert',
            NULL,
            (SELECT * FROM inserted i2 WHERE i2.id = i.id FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            NULL,
            N'pending',
            SYSUTCDATETIME()
        FROM inserted i;
    END

    -- Gestione UPDATE (Cambio avanzamento / chiusura)
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
            N'anomalie',
            N'anomalie',
            CAST(i.id AS NVARCHAR(100)),
            N'update',
            N'anomalie_update',
            NULL,
            (
                -- i.* include la colonna applicativa modified_by_user_id (se presente nello
                -- schema), popolata dalla view di salvataggio anomalia. AU-GAP1: il ruolo CC/CAR
                -- e il nome di registry modified_by_id vengono risolti a runtime da
                -- _enrich_anomalie_payload (che legge sia modified_by_id sia modified_by_user_id).
                -- Non si referenzia esplicitamente modified_by_user_id qui per non invalidare il
                -- trigger sugli schemi legacy in cui la colonna non esiste ancora.
                SELECT
                    i.*,
                    d.avanzamento AS old_avanzamento,
                    d.chiudere AS old_chiudere
                FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
            ),
            (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            N'pending',
            SYSUTCDATETIME()
        FROM inserted i
        JOIN deleted d ON i.id = d.id
        WHERE ISNULL(i.avanzamento, N'') <> ISNULL(d.avanzamento, N'')
           OR ISNULL(i.chiudere, 0) <> ISNULL(d.chiudere, 0);
    END
END
