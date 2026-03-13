-- Trigger interamente set-based e compatibile con insert multi-riga.
-- Event code tecnico stabile per evitare ambiguita' in questa fase.
CREATE OR ALTER TRIGGER dbo.trg_assenze_automation_after_insert
ON dbo.assenze
AFTER INSERT
AS
BEGIN
    SET NOCOUNT ON;

    IF NOT EXISTS (SELECT 1 FROM inserted)
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
        N'assenze',
        N'assenze',
        CAST(i.id AS NVARCHAR(100)),
        N'INSERT',
        N'assenze_insert',
        NULL,
        (
            SELECT
                i.id,
                i.dipendente_id,
                i.data_inizio,
                i.data_fine,
                i.tipo_assenza,
                i.motivazione_richiesta,
                i.moderation_status,
                i.capo_reparto_id,
                i.email_esterna AS dipendente_email,
                i.salta_approvazione,
                u.email AS capo_email
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
        ),
        NULL,
        N'pending'
    FROM inserted AS i
    LEFT JOIN dbo.utenti AS u
        ON u.id = i.capo_reparto_id;
END;
GO
