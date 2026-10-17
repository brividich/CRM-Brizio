# Migrazione a SQL Server 2025 Express (istanza affiancata)

Blocco **S1** del piano di backup e ripristino. Obiettivo: portare i database dell'HUB su una nuova istanza SQL Server 2025 Express (limite 50 GB per database invece di 10 GB) **sullo stesso PC di produzione**. L'istanza attuale e i database `DLM` e `CNGAUGE` non si toccano. Il rollback deve essere immediato.

Prerequisito: `audit_archive --run` già eseguito ([AUDIT_POLICY.md](AUDIT_POLICY.md)), così il database da spostare è piccolo.

## 1. Requisiti verificati

Fonte: Microsoft Learn, [SQL Server 2025: Hardware and Software Requirements](https://learn.microsoft.com/en-us/sql/sql-server/install/hardware-and-software-requirements-for-installing-sql-server-2025) (aggiornata il 20/07/2026) e [Editions and components of SQL Server 2025](https://learn.microsoft.com/en-us/sql/sql-server/editions-and-components-of-sql-server-2025).

| Requisito | Valore ufficiale | PC di produzione |
|---|---|---|
| Sistema operativo | Windows 10 o successivo, Windows Server 2019 o successivo. Express è supportato su Windows 11 Home, Pro, Enterprise e IoT Enterprise | Windows 11 Pro: **supportato** |
| .NET Framework | 4.7.2 | da verificare (lo controlla lo script) |
| Memoria | Express: minimo 512 MB, consigliato 1 GB | ok |
| Disco | almeno 6 GB liberi sul disco di sistema; motore circa 1,5 GB | lo controlla lo script |
| CPU | x64, 1,4 GHz (consigliato 2 GHz) | ok |
| Limiti di Express 2025 | **50 GB** per database; il minore fra 1 socket e 4 core; buffer pool 1.410 MB | come oggi, eccetto la dimensione |
| Driver | il setup installa ODBC Driver 17 e 18 | il portale usa ODBC 18 |

Compatibilità del portale:

- `mssql-django` supporta SQL Server 2025 dalla versione 1.7 ([release](https://github.com/microsoft/mssql-django/releases)); nel repo è fissata la **1.7.4**, insieme a `pyodbc` 5.3.0.
- **La macchina di sviluppo gira già su SQL Server 2025 Express (17.0.1000.7)** con il database di sviluppo in compatibility level 130. Nessun problema rilevato.
- Verifica del 17/10/2026 su una copia del DB di sviluppo ripristinata con `move-db-to-instance.ps1`:
  - `manage.py check` pulito;
  - 0 migrazioni mancanti;
  - `hub_backup_doctor`, `audit_archive --plan/--run/--restore` e `hub_db_tuning` funzionanti.
- Le note di rilascio di `mssql-django` non citano il compatibility level 170: per questo lo si alza solo dopo due settimane senza problemi (punto 4).

## 2. Installazione dell'istanza (`install-sql2025-instance.ps1`)

Supporti di installazione:

1. Scarica il bootstrapper ufficiale di SQL Server 2025 Express (`SQL2025-SSEI-Expr.exe`).
2. Scegli «Scarica supporti» → «Express Core»: si ottiene `SQLEXPR_x64_ENU.exe`.

```powershell
# simulazione: controlla i prerequisiti, legge la collation dell'istanza attuale, mostra il ConfigurationFile
.\deployment\scripts\install-sql2025-instance.ps1 -InstallerPath D:\SQL2025\SQLEXPR_x64_ENU.exe -WhatIf
# installazione (PowerShell come amministratore)
.\deployment\scripts\install-sql2025-instance.ps1 -InstallerPath D:\SQL2025\SQLEXPR_x64_ENU.exe -InstanceName HUB2025 -TcpPort 14330
```

Cosa fa lo script:

- controlla sistema operativo, .NET, RAM e spazio libero;
- legge dall'istanza attuale (`-SourceInstance`, default `.\SQLEXPRESS`) la collation e il modo di autenticazione;
- genera `C:\PortaleNovicrom\shared\sql2025\ConfigurationFile-HUB2025.ini`, che non contiene password. Imposta solo il motore, la stessa collation, gli amministratori (l'utente corrente e `BUILTIN\Administrators`), TCP attivo e named pipes spente, SQL Browser automatico, aggiornamenti dal setup disattivati;
- installa in modalità silenziosa;
- imposta la porta TCP fissa;
- se l'origine è in modalità mista, la imposta anche sulla nuova istanza tramite registro. `sa` resta disabilitato e nessuna password passa sulla riga di comando;
- verifica che l'istanza risponda in versione 17.x con la stessa collation.

È idempotente: se l'istanza esiste già, la verifica e la allinea. Il firewall non viene toccato, perché il portale gira sulla stessa macchina; `-OpenFirewall` serve solo per l'accesso da rete. Exit code: 0 = pronta, 3010 = serve un riavvio, 1 = errore. Il log va in `C:\PortaleNovicrom\shared\sql2025\install-*.log`.

Valori possibili per `DB_HOST` dopo l'installazione:

- `PCLOGSYS\HUB2025`, che richiede SQL Browser attivo;
- `PCLOGSYS,14330`, porta fissa senza Browser.

## 3. Spostamento di un database (`move-db-to-instance.ps1`)

Le fasi, ognuna cronometrata nel report JSON (`C:\PortaleNovicrom\shared\sql2025\move-<db>-<ts>.json`, accanto al log):

1. **Preflight.**
   - Rifiuta i DB di sistema, e `DLM`/`CNGAUGE` se manca `-AllowExternalDatabase`.
   - Rifiuta una versione di destinazione più vecchia e un DB già presente sulla destinazione: niente `REPLACE`, mai.
   - Controlla lo spazio libero nello staging e sui dati.
   - Cerca **riferimenti ad altri database** (nomi a tre parti, sinonimi): se ci sono si ferma, perché sulla nuova istanza si romperebbero. Nel codice del portale non ce ne sono.
2. **Manutenzione** (con `-Environment`). Disattiva il watchdog del qcluster (altrimenti lo riavvierebbe), ferma il pool IIS `PortaleNovicrom-<ENV>` e il task `QCluster_<ENV>`, chiude eventuali processi qcluster residui del venv.
3. **Backup** `COPY_ONLY, CHECKSUM` e `RESTORE VERIFYONLY`, con impronta SHA-256 del `.bak` nel report. La catena dei backup dell'origine non si interrompe.
4. **Restore** sulla destinazione `WITH MOVE, CHECKSUM, RECOVERY`. Compatibility level e recovery model restano quelli dell'origine.
5. **Login e utenti orfani.** `CREATE LOGIN … FROM WINDOWS` per gli account indicati in `-Logins` (l'identità del pool IIS). Gli utenti Windows orfani si riagganciano da soli, perché il login ha lo stesso SID; quelli non risolti finiscono nel report. Viene impostato lo stesso owner del DB di origine.
6. **`DBCC CHECKDB`.**
7. **`.env`** (`-UpdateEnv -NewDbHost`). Copia di sicurezza `config\.env.bak-<ts>`, poi aggiorna `DB_HOST` nel `.env` persistente (`C:\PortaleNovicrom\<env>\config\.env`) e lo copia nella release attiva.
8. **Riavvio** del pool e del qcluster, riattivazione del watchdog, `smoke-test.ps1`.
9. **Origine OFFLINE** (`-SetSourceOffline`): il DB viene messo offline, non cancellato.

Se qualcosa fallisce durante la manutenzione, lo script rimette il `.env` precedente e riavvia il portale sulla vecchia istanza. L'origine è ancora ONLINE, perché va offline solo all'ultimo passo. Rilanciato dopo uno spostamento riuscito, lo script se ne accorge e non fa nulla.

### Tempi misurati (macchina di sviluppo, SQL Server 2025 Express, disco SSD)

| DB | Allocati | Backup + verifica | Restore | CHECKDB | Totale |
|---|---|---|---|---|---|
| copia del DB di sviluppo | 464 MB (backup 280 MB) | 8 s | 9 s | 6 s | **28 s** |

Per la produzione, dopo `audit_archive --run`, si stimano pochi minuti di DB fermo. La finestra di manutenzione va comunque prevista di 30 minuti, per smoke test e controlli.

## 4. Procedura

### Prova su TEST (prima di tutto)

```powershell
# PowerShell come amministratore sul PC di produzione
.\deployment\scripts\move-db-to-instance.ps1 -Database PortaleNovicrom_TEST -SourceInstance .\SQLEXPRESS -TargetInstance .\HUB2025 -WhatIf
.\deployment\scripts\move-db-to-instance.ps1 -Database PortaleNovicrom_TEST -SourceInstance .\SQLEXPRESS -TargetInstance .\HUB2025 `
    -Environment test -Logins "<identità del pool PortaleNovicrom-TEST>" -NewDbHost "PCLOGSYS\HUB2025" -UpdateEnv -SetSourceOffline
```

Poi, sull'ambiente TEST:

1. `manage.py check` e `manage.py migrate --plan`: deve risultare senza operazioni.
2. Navigazione delle pagine principali: anagrafica, assets, ticket, automazioni, Centrale di comando.
3. Annotare in questa pagina i tempi riportati nel report JSON.

Se emergono incompatibilità di `mssql-django`, `pyodbc` o ODBC 18 con SQL 2025, ci si ferma e si riporta.

### Migrazione di PROD (la esegue Brizio, in finestra di manutenzione)

1. `audit_archive --run` completato (vedi [AUDIT_POLICY.md](AUDIT_POLICY.md)).
2. Lanciare:

   ```powershell
   .\deployment\scripts\move-db-to-instance.ps1 -Database PortaleNovicrom_PROD -SourceInstance .\SQLEXPRESS -TargetInstance .\HUB2025 -WhatIf
   .\deployment\scripts\move-db-to-instance.ps1 -Database PortaleNovicrom_PROD -SourceInstance .\SQLEXPRESS -TargetInstance .\HUB2025 `
       -Environment prod -Logins "<identità del pool PortaleNovicrom-PROD>" -NewDbHost "PCLOGSYS\HUB2025" -UpdateEnv -SetSourceOffline
   ```

3. Lo script esegue manutenzione, backup verificato, restore, login, CHECKDB, `.env`, riavvio, smoke test e origine OFFLINE.
4. Controllare `readyz` e la Centrale di comando. Il deploy successivo potrebbe chiedere `-AllowEnvDrift` (`.env` attivo diverso dal persistente).

L'identità del pool IIS **non cambia** in questo ciclo.

### Dopo la migrazione (ordine fisso)

1. Recovery model `FULL` e backup FULL immediato: `manage.py hub_backup_set_recovery --full --confirm` (blocco R1).
2. Task del backup del log ogni ora, 07–21 (`register-backup-tasks.ps1`, blocco R1).
3. `manage.py hub_db_tuning --query-store-max-mb 100 --apply`. Se il Query Store risulta spento, decidere se accenderlo con `--enable`.
4. **Dopo 2 settimane senza problemi**: `manage.py hub_db_tuning --compatibility-level 170` (dry-run), poi `--apply`, con una nota nel CHANGELOG. Per tornare indietro: `--compatibility-level <valore precedente> --apply`.

## 5. Rollback

Entro 30 giorni il DB di origine resta sulla vecchia istanza, OFFLINE:

1. Fermare il pool IIS e il qcluster.
2. Ripristinare il `.env`: copiare `config\.env.bak-<ts>` su `config\.env` (il nome esatto è nel report JSON).
3. Sulla vecchia istanza: `ALTER DATABASE [PortaleNovicrom_PROD] SET ONLINE`.
4. Riavviare pool e qcluster, poi `smoke-test.ps1 -Environment prod`.

I dati scritti dopo lo spostamento restano solo sulla nuova istanza: valutare prima di tornare indietro.

Dopo 30 giorni senza problemi, il vecchio DB OFFLINE si può eliminare, con un backup finale conservato.

## 6. DLM e CNGAUGE

Restano fuori dallo spostamento, che farà Brizio. Lo stesso script li accetta solo con `-AllowExternalDatabase`. Quando saranno sulla nuova istanza, `BACKUP_EXTRA_DATABASES` (blocco R1) li includerà nel motore di backup senza cambiarne il recovery model.

## 7. Test

`deployment\tests\test-sql-scripts.ps1` controlla il parsing degli script, le guardie (DB di sistema, `DLM`/`CNGAUGE`, nomi riservati) e i calcoli di spazio. Con `-SqlInstance .\SQLEXPRESS` fa anche il giro completo su un DB sintetico: spostamento, origine OFFLINE, idempotenza, poi pulizia. È verde sia su Windows PowerShell 5.1 sia su PowerShell 7.
