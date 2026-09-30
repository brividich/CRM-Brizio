-- Eventi del designer; nessun allegato, nota clinica o payload indiscriminato.
CREATE TRIGGER [dbo].[trg_diario_preposto_automation]
ON [dbo].[diario_preposto_segnalazionepreposto]
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NULL RETURN;
    INSERT INTO [dbo].[automation_event_queue]
        (source_code, source_table, source_pk, operation_type, event_code,
         watched_field, payload_json, old_payload_json, status, created_at)
    SELECT N'diario_preposto', N'diario_preposto_segnalazionepreposto', CAST(i.id AS NVARCHAR(100)),
        CASE WHEN d.id IS NULL THEN N'insert' ELSE N'update' END,
        CASE WHEN d.id IS NULL THEN N'diario_preposto_insert' ELSE N'diario_preposto_update' END,
        NULL,
        (SELECT i.[id], i.[codice_identificativo], i.[titolo], i.[preposto], i.[chi_segnala], i.[data_segnalazione], i.[creato_da_id] FOR JSON PATH, INCLUDE_NULL_VALUES, WITHOUT_ARRAY_WRAPPER),
        CASE WHEN d.id IS NULL THEN NULL ELSE
            (SELECT d.[id], d.[codice_identificativo], d.[titolo], d.[preposto], d.[chi_segnala], d.[data_segnalazione], d.[creato_da_id] FOR JSON PATH, INCLUDE_NULL_VALUES, WITHOUT_ARRAY_WRAPPER) END,
        N'pending', SYSUTCDATETIME()
    FROM inserted i LEFT JOIN deleted d ON d.id = i.id;
END
