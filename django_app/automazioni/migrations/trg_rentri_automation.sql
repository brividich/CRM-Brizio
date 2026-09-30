-- Eventi del designer; nessun allegato, nota clinica o payload indiscriminato.
CREATE TRIGGER [dbo].[trg_rentri_automation]
ON [dbo].[rentri_registrorifiuti]
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NULL RETURN;
    INSERT INTO [dbo].[automation_event_queue]
        (source_code, source_table, source_pk, operation_type, event_code,
         watched_field, payload_json, old_payload_json, status, created_at)
    SELECT N'rentri', N'rentri_registrorifiuti', CAST(i.id AS NVARCHAR(100)),
        CASE WHEN d.id IS NULL THEN N'insert' ELSE N'update' END,
        CASE WHEN d.id IS NULL THEN N'rentri_insert' ELSE N'rentri_update' END,
        NULL,
        (SELECT i.[id], i.[tipo], i.[data], i.[id_registrazione], i.[rentri_si_no], i.[salva], i.[arrivo_fir], i.[codice], i.[quantita], i.[carico_scarico], i.[inserito_da] FOR JSON PATH, INCLUDE_NULL_VALUES, WITHOUT_ARRAY_WRAPPER),
        CASE WHEN d.id IS NULL THEN NULL ELSE
            (SELECT d.[id], d.[tipo], d.[data], d.[id_registrazione], d.[rentri_si_no], d.[salva], d.[arrivo_fir], d.[codice], d.[quantita], d.[carico_scarico], d.[inserito_da] FOR JSON PATH, INCLUDE_NULL_VALUES, WITHOUT_ARRAY_WRAPPER) END,
        N'pending', SYSUTCDATETIME()
    FROM inserted i LEFT JOIN deleted d ON d.id = i.id;
END
