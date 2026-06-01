-- =====================================================================
-- AU-GAP1 - Colonna "chi ha modificato" sulla tabella legacy anomalie
-- =====================================================================
-- Aggiunge dbo.anomalie.modified_by_user_id (INT NULL), necessaria per il
-- flusso AU42b (notifica anomalie filtrata per ruolo CAPOCOMMESSA/CAR).
--
-- Contesto:
--   - `anomalie` e' una tabella legacy SQL Server (NON un model Django):
--     questa colonna va aggiunta col presente script, non con makemigrations.
--   - Il codice applicativo e' difensivo: la view di salvataggio anomalia
--     popola modified_by_user_id SOLO se la colonna esiste; il trigger
--     trg_anomalie_automation la proietta nel payload tramite i.*.
--     Finche' la colonna non esiste, AU42b resta inattivo e nulla si rompe
--     (vale la versione "per campo" AU42).
--
-- Idempotente: l'ALTER viene eseguito solo se la colonna non esiste gia'.
-- Non distruttivo: INT NULL, i record storici restano senza valore.
--
-- Procedura consigliata:
--   1. Eseguire questo script su SQL Server TEST.
--   2. python django_app\manage.py apply_sql_triggers   (riapplica i trigger)
--   3. Verificare salvataggio anomalia + popolamento automation_event_queue.
--   4. Ripetere su PROD.
-- =====================================================================

IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'dbo.anomalie')
      AND name = N'modified_by_user_id'
)
BEGIN
    ALTER TABLE dbo.anomalie ADD modified_by_user_id INT NULL;
END
GO
