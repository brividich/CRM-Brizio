-- Eventi del designer; nessun allegato, nota clinica o payload indiscriminato.
CREATE TRIGGER [dbo].[trg_anagrafica_visite_mediche_automation]
ON [dbo].[anagrafica_visitamedica]
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NULL RETURN;
    INSERT INTO [dbo].[automation_event_queue]
        (source_code, source_table, source_pk, operation_type, event_code,
         watched_field, payload_json, old_payload_json, status, created_at)
    SELECT N'anagrafica_visite_mediche', N'anagrafica_visitamedica', CAST(i.id AS NVARCHAR(100)),
        CASE WHEN d.id IS NULL THEN N'insert' ELSE N'update' END,
        CASE WHEN d.id IS NULL THEN N'anagrafica_visite_mediche_insert' ELSE N'anagrafica_visite_mediche_update' END,
        NULL,
        (SELECT i.[id], i.[legacy_anagrafica_id], i.[tipo_id], i.[data_svolgimento], i.[data_scadenza], i.[esito], N'Consultare la scheda riservata nel portale.' AS [prescrizioni] FOR JSON PATH, INCLUDE_NULL_VALUES, WITHOUT_ARRAY_WRAPPER),
        CASE WHEN d.id IS NULL THEN NULL ELSE
            (SELECT d.[id], d.[legacy_anagrafica_id], d.[tipo_id], d.[data_svolgimento], d.[data_scadenza], d.[esito], N'Consultare la scheda riservata nel portale.' AS [prescrizioni] FOR JSON PATH, INCLUDE_NULL_VALUES, WITHOUT_ARRAY_WRAPPER) END,
        N'pending', SYSUTCDATETIME()
    FROM inserted i LEFT JOIN deleted d ON d.id = i.id;
END
