-- Aggiunge il supporto a execute_after per scheduling differito degli eventi in coda.
-- Eseguire solo se la colonna non esiste già.
IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.automation_event_queue', N'U')
          AND name = N'execute_after'
    )
BEGIN
    ALTER TABLE dbo.automation_event_queue
        ADD execute_after DATETIME2 NULL;
END;
GO

-- Indice per filtrare efficacemente gli eventi schedulati
IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE object_id = OBJECT_ID(N'dbo.automation_event_queue', N'U')
          AND name = N'IX_automation_event_queue_execute_after'
    )
BEGIN
    CREATE NONCLUSTERED INDEX IX_automation_event_queue_execute_after
        ON dbo.automation_event_queue (execute_after)
        WHERE execute_after IS NOT NULL;
END;
GO
