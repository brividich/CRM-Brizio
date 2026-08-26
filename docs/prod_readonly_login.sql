/* --------------------------------------------------------------------------
   Login SQL Server di SOLA LETTURA per la diagnosi da sviluppo.

   Da eseguire UNA VOLTA sul server di produzione, con un'utenza sysadmin,
   contro il database del portale.

   Questa e' la barriera autorevole: il profilo `config.settings.prod_readonly`
   aggiunge un controllo lato client, ma e' questo grant a decidere davvero cosa
   l'utenza puo' fare.

   Sostituire <PASSWORD_FORTE> con una password generata a caso e conservata nel
   gestore di credenziali: non scriverla in chat, in un ticket o in un commit.
   -------------------------------------------------------------------------- */

USE [master];
GO

IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'hub_readonly')
BEGIN
    CREATE LOGIN [hub_readonly]
        WITH PASSWORD = N'<PASSWORD_FORTE>',
             CHECK_POLICY = ON,
             DEFAULT_DATABASE = [PORTALE NOVICROM];
END
GO

USE [PORTALE NOVICROM];
GO

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'hub_readonly')
BEGIN
    CREATE USER [hub_readonly] FOR LOGIN [hub_readonly];
END
GO

/* Sola lettura su tutto il database. */
ALTER ROLE [db_datareader] ADD MEMBER [hub_readonly];
GO

/* Nega esplicitamente la scrittura: se in futuro qualcuno aggiungesse
   l'utenza a un ruolo piu' ampio, il DENY continua a vincere. */
DENY INSERT, UPDATE, DELETE, ALTER, EXECUTE TO [hub_readonly];
GO

/* Verifica: deve elencare db_datareader e nient'altro di scrittura. */
SELECT r.name AS ruolo
FROM sys.database_role_members m
JOIN sys.database_principals r ON r.principal_id = m.role_principal_id
JOIN sys.database_principals u ON u.principal_id = m.member_principal_id
WHERE u.name = N'hub_readonly';
GO
