CREATE TRIGGER [dbo].[trg_tasks_project_automation]
ON [dbo].[tasks_project]
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NULL
        RETURN;

    -- INSERT (nuovo KICK-OFF creato)
    IF EXISTS (SELECT * FROM inserted) AND NOT EXISTS (SELECT * FROM deleted)
    BEGIN
        INSERT INTO [dbo].[automation_event_queue] (
            [source_code], [source_table], [source_pk], [operation_type],
            [event_code], [watched_field], [payload_json], [old_payload_json],
            [status], [created_at]
        )
        SELECT
            N'tasks_project',
            N'tasks_project',
            CAST(i.id AS NVARCHAR(100)),
            N'insert',
            N'tasks_project_insert',
            NULL,
            (SELECT * FROM inserted i2 WHERE i2.id = i.id FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            NULL,
            N'pending',
            SYSUTCDATETIME()
        FROM inserted i;
    END

    -- UPDATE — solo se cambiano fase, impatto sicurezza o stato VRF
    IF EXISTS (SELECT * FROM inserted) AND EXISTS (SELECT * FROM deleted)
    BEGIN
        INSERT INTO [dbo].[automation_event_queue] (
            [source_code], [source_table], [source_pk], [operation_type],
            [event_code], [watched_field], [payload_json], [old_payload_json],
            [status], [created_at]
        )
        SELECT
            N'tasks_project',
            N'tasks_project',
            CAST(i.id AS NVARCHAR(100)),
            N'update',
            N'tasks_project_update',
            NULL,
            (
                SELECT
                    i.*,
                    d.phase AS old_phase,
                    d.safety_impact AS old_safety_impact,
                    d.vrf_status AS old_vrf_status
                FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
            ),
            (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            N'pending',
            SYSUTCDATETIME()
        FROM inserted i
        JOIN deleted d ON i.id = d.id
        WHERE ISNULL(i.phase, N'') <> ISNULL(d.phase, N'')
           OR ISNULL(i.safety_impact, 0) <> ISNULL(d.safety_impact, 0)
           OR ISNULL(i.vrf_status, N'') <> ISNULL(d.vrf_status, N'');
    END
END
