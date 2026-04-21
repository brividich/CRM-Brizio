-- Trigger interamente set-based e compatibile con update multi-riga.
-- Il confronto fine old/new restera' demandato a Django nelle fasi successive.
-- Self-guard: su ambienti TEST/PROD senza tabella legacy dbo.assenze non deve bloccare il deploy.
IF OBJECT_ID(N'dbo.assenze', N'U') IS NULL
BEGIN
    PRINT N'[SKIP] dbo.assenze non esiste: trigger trg_assenze_automation_after_update non creato.';
END
ELSE
BEGIN
EXEC sys.sp_executesql N'
CREATE OR ALTER TRIGGER dbo.trg_assenze_automation_after_update
ON dbo.assenze
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    IF NOT EXISTS (SELECT 1 FROM inserted)
    BEGIN
        RETURN;
    END;

    IF OBJECT_ID(N''dbo.automation_event_queue'', N''U'') IS NULL
    BEGIN
        RETURN;
    END;

    INSERT INTO dbo.automation_event_queue (
        source_code,
        source_table,
        source_pk,
        operation_type,
        event_code,
        watched_field,
        payload_json,
        old_payload_json,
        status
    )
    SELECT
        N''assenze'',
        N''assenze'',
        CAST(i.id AS NVARCHAR(100)),
        N''UPDATE'',
        N''assenze_update'',
        NULL,
        (
            SELECT
                i.id,
                i.nome_lookup_id AS dipendente_id,
                i.copia_nome AS dipendente_nome,
                i.data_inizio,
                i.data_fine,
                i.tipo_assenza,
                i.motivazione_richiesta,
                i.moderation_status,
                i.capo_reparto_id,
                i.email_esterna AS dipendente_email,
                i.salta_approvazione,
                ui.email AS capo_email
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
        ),
        (
            SELECT
                d.id,
                d.nome_lookup_id AS dipendente_id,
                d.copia_nome AS dipendente_nome,
                d.data_inizio,
                d.data_fine,
                d.tipo_assenza,
                d.motivazione_richiesta,
                d.moderation_status,
                d.capo_reparto_id,
                d.email_esterna AS dipendente_email,
                d.salta_approvazione,
                ud.email AS capo_email
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
        ),
        N''pending''
    FROM inserted AS i
    INNER JOIN deleted AS d
        ON d.id = i.id
    LEFT JOIN dbo.utenti AS ui
        ON ui.id = i.capo_reparto_id
    LEFT JOIN dbo.utenti AS ud
        ON ud.id = d.capo_reparto_id;
END;
';
END;
GO
