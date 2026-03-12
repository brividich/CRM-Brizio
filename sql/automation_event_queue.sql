-- Fase 2: creazione conservativa della queue tecnica.
-- Se la tabella esiste gia', questo script non applica alter distruttivi.
IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.automation_event_queue (
        id BIGINT NOT NULL IDENTITY(1,1),
        source_code NVARCHAR(100) NOT NULL,
        source_table NVARCHAR(100) NOT NULL,
        source_pk NVARCHAR(100) NULL,
        operation_type NVARCHAR(20) NOT NULL,
        event_code NVARCHAR(100) NULL,
        watched_field NVARCHAR(100) NULL,
        payload_json NVARCHAR(MAX) NOT NULL,
        old_payload_json NVARCHAR(MAX) NULL,
        status NVARCHAR(20) NOT NULL
            CONSTRAINT DF_automation_event_queue_status DEFAULT (N'pending'),
        retry_count INT NOT NULL
            CONSTRAINT DF_automation_event_queue_retry_count DEFAULT ((0)),
        error_message NVARCHAR(2000) NULL,
        created_at DATETIME2 NOT NULL
            CONSTRAINT DF_automation_event_queue_created_at DEFAULT (SYSUTCDATETIME()),
        picked_at DATETIME2 NULL,
        processed_at DATETIME2 NULL,
        CONSTRAINT PK_automation_event_queue PRIMARY KEY CLUSTERED (id)
    );
END;
GO

IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NOT NULL
    AND NOT EXISTS (
        SELECT 1
        FROM sys.check_constraints
        WHERE name = N'CK_automation_event_queue_status'
          AND parent_object_id = OBJECT_ID(N'dbo.automation_event_queue', N'U')
    )
BEGIN
    ALTER TABLE dbo.automation_event_queue
    ADD CONSTRAINT CK_automation_event_queue_status
        CHECK (status IN (N'pending', N'processing', N'done', N'error'));
END;
GO

IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NOT NULL
    AND NOT EXISTS (
        SELECT 1
        FROM sys.indexes
        WHERE object_id = OBJECT_ID(N'dbo.automation_event_queue', N'U')
          AND name = N'IX_automation_event_queue_status_created_at'
    )
BEGIN
    CREATE NONCLUSTERED INDEX IX_automation_event_queue_status_created_at
        ON dbo.automation_event_queue (status, created_at);
END;
GO

IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NOT NULL
    AND NOT EXISTS (
        SELECT 1
        FROM sys.indexes
        WHERE object_id = OBJECT_ID(N'dbo.automation_event_queue', N'U')
          AND name = N'IX_automation_event_queue_source_operation'
    )
BEGIN
    CREATE NONCLUSTERED INDEX IX_automation_event_queue_source_operation
        ON dbo.automation_event_queue (source_code, operation_type);
END;
GO
