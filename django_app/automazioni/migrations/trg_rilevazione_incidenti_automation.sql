-- Eventi del designer; nessun allegato, nota clinica o payload indiscriminato.
CREATE TRIGGER [dbo].[trg_rilevazione_incidenti_automation]
ON [dbo].[rilevazione_incidenti_rilevazioneincidente]
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NULL RETURN;
    INSERT INTO [dbo].[automation_event_queue]
        (source_code, source_table, source_pk, operation_type, event_code,
         watched_field, payload_json, old_payload_json, status, created_at)
    SELECT N'rilevazione_incidenti', N'rilevazione_incidenti_rilevazioneincidente', CAST(i.id AS NVARCHAR(100)),
        CASE WHEN d.id IS NULL THEN N'insert' ELSE N'update' END,
        CASE WHEN d.id IS NULL THEN N'rilevazione_incidenti_insert' ELSE N'rilevazione_incidenti_update' END,
        NULL,
        (SELECT i.[id], i.[tipologia_scheda], i.[reparto], i.[data_segnalazione], i.[approvazione_rls], i.[chiusura_rspp], i.[data_chiusura_rspp] FOR JSON PATH, INCLUDE_NULL_VALUES, WITHOUT_ARRAY_WRAPPER),
        CASE WHEN d.id IS NULL THEN NULL ELSE
            (SELECT d.[id], d.[tipologia_scheda], d.[reparto], d.[data_segnalazione], d.[approvazione_rls], d.[chiusura_rspp], d.[data_chiusura_rspp] FOR JSON PATH, INCLUDE_NULL_VALUES, WITHOUT_ARRAY_WRAPPER) END,
        N'pending', SYSUTCDATETIME()
    FROM inserted i LEFT JOIN deleted d ON d.id = i.id;
END
