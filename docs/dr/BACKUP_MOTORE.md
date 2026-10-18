# Motore di backup verificabile

Blocco **R1** del piano di backup e ripristino. Ogni backup è un *set* con queste caratteristiche:

- un manifest versionato;
- artefatti con impronta SHA-256 e verifica (`RESTORE VERIFYONLY`);
- copia verificata sul target e, se c'è, sulla destinazione secondaria;
- stato leggibile anche a database spento;
- retention GFS.

Il codice sta in `django_app/core/backup_engine/`, i comandi in `core/management/commands/hub_backup*.py`.

## Formato sul target

```
<BACKUP_TARGET>\<env>\
  20261017_020000_full\    manifest.json + db\<DB>_FULL_<ts>.bak           (uno per DB: HUB + BACKUP_EXTRA_DATABASES)
  20261017_100500_log\     manifest.json + db\<DB>_LOG_<ts>.trn            (catena: FULL di riferimento, FirstLSN/LastLSN)
  20261017_023000_files\   manifest.json + files\index.json                (radice → percorso → sha256, size, mtime)
  20261017_030000_host\    manifest.json + host\host-manifest.json, host\iis\*.xml, host\tasks\*.xml
  _objects\<aa>\<sha256>   store dei file condiviso fra i set: un file invariato non si ricopia
  _releases\portale-novicrom-vX.Y.Z-<ts>.zip   zip esatto della release attiva (riconosciuto dal commit)
  status.json              ultimo esito per tipo (copia anche in <LOG_DIR>\backup-status.json)
```

Il manifest viene scritto **per ultimo**: una cartella senza `manifest.json` è un set incompleto e la retention la elimina dopo due giorni.

Il manifest **non contiene segreti**:

- delle variabili del `.env` solo i nomi;
- di `DOCUMENT_ENCRYPTION_KEY` e `SECRET_KEY` solo l'impronta SHA-256, che serve a verificare che il Recovery Kit apra i documenti;
- dei certificati solo il thumbprint.

I file privati restano cifrati come sono: il backup non li decifra mai.

## Impostazioni (`.env`)

| Variabile | Default | Note |
|---|---|---|
| `BACKUP_TARGET` | `C:\PortaleNovicrom\shared\backups\hub` | in produzione **una share UNC** sul NAS (es. `\\nas\hub-backup`); se resta locale, il doctor lo segnala |
| `BACKUP_TARGET_SECONDARY` | vuoto | seconda destinazione facoltativa (la copia fuori sede la fa Hyper Backup) |
| `BACKUP_STAGING_DIR` | `C:\PortaleNovicrom\shared\backup-staging` | locale: qui SQL Server scrive il `.bak`, che poi viene copiato e verificato |
| `BACKUP_SQL_TIMEOUT_S` | 3600 | timeout di `sqlcmd` (prima era 120 s) |
| `BACKUP_LOG_WINDOW` | `07-21` | ore in cui gira il backup del log |
| `BACKUP_KEEP_DAILY` / `_WEEKLY` / `_MONTHLY` | 14 / 8 / 12 | retention GFS |
| `BACKUP_KEEP_LOG_DAYS` | 14 | finestra del ripristino puntuale |
| `BACKUP_EXTRA_DATABASES` | vuoto | es. `DLM,CNGAUGE`, quando saranno sulla nuova istanza: stesso trattamento, recovery model mai cambiato |
| `BACKUP_ENV_DIR` | vuoto | cartella **separata** (altra share/ACL) per la copia del `.env` completo (audit M10) |
| `BACKUP_ENV_NAME` | dedotto | `prod` / `test` nei percorsi |
| `BACKUP_DRILL_TABLES` | utenti, anagrafica, asset, ticket, visite | tabelle di cui si contano le righe nel manifest |
| `HUB_PUBLIC_HOSTNAME` / `HUB_ALT_HOSTNAMES` | vuoti | `hub.costruzioninovicrom.it` / `hub.cnovicrom.local`: il doctor verifica `ALLOWED_HOSTS`, CSRF, DNS e SPN |
| `BACKUP_LEGACY_MODE` | False | solo per emergenza: `backup_portale` torna al vecchio percorso, senza verifica |

## Comandi

| Comando | Effetto | Exit code |
|---|---|---|
| `hub_backup --type full` | `BACKUP DATABASE … WITH CHECKSUM` in staging → `RESTORE VERIFYONLY` → header LSN → copia verificata → manifest | 0 OK · 1 avvisi · 2 fallito |
| `hub_backup --type log` | `BACKUP LOG … WITH CHECKSUM`, solo con recovery FULL e nella finestra (`--force` per farlo fuori). Controlla la continuità con il log precedente | idem |
| `hub_backup --type files` | media e radici private, incrementale | idem |
| `hub_backup --type host` | fotografia della macchina: IIS, task, certificati, versioni, SPN, nomi, zip della release; copia del `.env` in `BACKUP_ENV_DIR` | idem |
| `hub_backup --type retention [--apply]` | GFS; senza `--apply` mostra solo cosa eliminerebbe | idem |
| `hub_backup --type all` | full + files + host | idem |
| `hub_backup_verify --latest` · `--set <id>` · `--chain` | ricalcola gli hash, riporta il `.bak` in staging per `VERIFYONLY`, controlla la catena LSN | idem |
| `hub_backup_doctor [--offline] [--json]` | capacità, audit, cache (R0) + target, staging, `BACKUP_ENV_DIR`, recovery model, freschezza dei set, prova di ripristino, task, nomi del portale | 0 / 1 / 2 |
| `hub_backup_set_recovery --full [--confirm]` | recovery FULL + backup FULL immediato, che avvia la catena (`--simple` per tornare indietro) | |
| `backup_portale` | wrapper compatibile: `hub_backup --type all` + retention. Il vecchio task del wizard continua a funzionare | |

Se il database non è raggiungibile durante un run, l'esito resta in `status.json` (`pending_db`) e viene scritto in `BackupRun` al run successivo.

## Retention

- **FULL, FILES, HOST**: tutti i set riusciti degli ultimi 14 giorni, poi il più recente di ogni settimana (8) e di ogni mese (12).
- **LOG**: restano finché esiste il FULL su cui poggiano, e comunque non oltre 14 giorni.
- **Mai cancellati**: l'ultimo FULL verificato e il set usato dall'ultima prova di ripristino riuscita, con i log che lo seguono.
- Gli oggetti di `_objects` non più referenziati da nessun indice conservato vengono eliminati.

Il test reale ha mostrato perché «uno al giorno» non basta: un FULL manuale fatto in giornata faceva eliminare il FULL delle 02:00 e i suoi log, aprendo un buco nel ripristino puntuale.

## Task pianificati (`deployment\scripts\register-backup-tasks.ps1`)

```powershell
# PowerShell come amministratore sul server; account con accesso di rete alla share dei backup
.\deployment\scripts\register-backup-tasks.ps1 -Environment prod -Credential (Get-Credential 'CNOVICROM\<account>') -WhatIf
.\deployment\scripts\register-backup-tasks.ps1 -Environment prod -Credential $cred -AuditArchiveDir \\nas\hub-archivi
```

| Task (`\PortaleNovicrom\`) | Quando | Comando |
|---|---|---|
| `PortaleNovicrom-Backup-PROD-FULL` | ogni giorno 02:00 | `hub_backup --type full` |
| `…-LOG` | ogni ora al minuto 05, 07–21 | `hub_backup --type log` |
| `…-FILES` | 02:30 | `hub_backup --type files` |
| `…-HOST` | 03:00 | `hub_backup --type host` |
| `…-RETENTION` | 05:00 | `hub_backup --type retention --apply` |
| `…-DRILL` (`-IncludeDrill`, blocco R2) | domenica 04:00 | `hub_restore_drill` |
| `…-AUDIT` (`-AuditArchiveDir`) | domenica 05:30 | `audit_archive --run` (classi B/C) |
| `…-AUDIT-BUSINESS` (`-IncludeBusinessArchive`, solo dopo S1) | ogni 4 settimane, domenica 06:00 | `audit_archive --category business --older-than-months 60` |

Cosa fa lo script:

- è idempotente: se un task esiste, lo aggiorna;
- concede all'account del servizio SQL il permesso Modify sullo staging;
- **disabilita**, senza cancellarlo, il vecchio task `PortaleNovicrom-Backup-PROD` del wizard, così alle 02:00 non partono due FULL;
- rifiuta i logon S4U, che non hanno credenziali di rete: servono `-Credential` oppure, sulla futura VM, `-GmsaAccount`.

## `backup-environment.ps1`

- **Non copia più il `.env` nel backup dati**: scrive solo i nomi delle variabili in `config\env_keys.txt`. Se il `.env` dichiara `BACKUP_ENV_DIR`, la copia completa va lì.
- Per default delega a `hub_backup --type all` (`-UseHubBackup`). Con `-UseHubBackup:$false` usa il percorso storico.
- I parametri esistenti restano invariati.

## Ordine di attivazione in produzione (lo esegue Brizio)

1. Deploy della release che contiene R0 e R1.
2. In `config\.env`: `BACKUP_TARGET=\\<nas>\hub-backup`, `BACKUP_ENV_DIR=\\<share segreti>\hub-env`, `HUB_PUBLIC_HOSTNAME`, `HUB_ALT_HOSTNAMES`.
3. `manage.py hub_backup_doctor` e correzione di quanto segnalato.
4. `manage.py hub_backup --type all`, poi `hub_backup_verify --latest`.
5. `register-backup-tasks.ps1 -Environment prod …`.
6. Dopo `audit_archive --run` e la migrazione a SQL 2025: `hub_backup_set_recovery --full --confirm` → il task LOG comincia a produrre la catena (RPO 1 ora).

## Verifiche fatte (17/10/2026, macchina di sviluppo, SQL Server 2025 Express)

Tutte su una copia del database di sviluppo, poi eliminata:

- `hub_backup --type all`: FULL di 280 MB con verifica, file, host.
- Log in SIMPLE: avviso chiaro, nessun set.
- `hub_backup_set_recovery --full --confirm`: FULL automatico.
- Due log continui e `hub_backup_verify --latest` con catena continua.
- Un byte alterato nel `.trn`: verifica FAILED, exit 2.
- Retention e wrapper `backup_portale`.
- Righe `BackupRun` registrate per ogni esito.

## Monitoraggio e prova di ripristino (blocco R2)

### Controlli di salute

I controlli di salute stanno in `monitoring/health.py`. Entrano in `/readyz`, ma **non sono mai critical**: un backup in ritardo non toglie il sito dal bilanciamento e non blocca il post-deploy. Nel payload pubblico compaiono solo nome e stato.

| Check | OK | WARN | FAIL |
|---|---|---|---|
| `backup_full` | ultimo FULL riuscito ≤ 26 h | ≤ 50 h | oltre 50 h, oppure nessun FULL |
| `backup_log` | nella finestra 07–21, ultimo log OK < 2 h | log in ritardo | catena interrotta |
| `restore_drill` | ultima prova riuscita < 8 giorni | < 35 giorni, mai eseguita, o ultima prova fallita | oltre 35 giorni |
| `recovery_kit` | kit allineato a `.env` e chiavi | kit assente o non allineato | — |
| `db_capacity` | < 70% del limite dell'edizione | ≥ 70% | ≥ 85% |

Fuori dalla finestra oraria il log non viene controllato. Con recovery SIMPLE il check del log risulta SKIPPED.

Lo schedule django-q `backup_health_alert` (ogni 30 minuti) apre o chiude una segnalazione nella centrale per ogni WARN/FAIL. Manda la mail agli amministratori **solo per i FAIL**, con dedup e quiet hours. L'alert dell'assistente AI non include più questi check.

Il digest giornaliero mostra «Servizi degradato» finché i backup non sono attivi: è voluto.

### Pagina «Backup e ripristino»

Si apre da Monitoring → Centrale di comando → «💾 Backup e ripristino» (`/admin-portale/monitoring/backup/`). È solo per gli amministratori di portale.

- **Riquadri**:
  - RPO attuale (minuti dall'ultimo punto ripristinabile, calcolato dal piano di ripristino);
  - ultimo FULL;
  - catena dei log;
  - ultima prova di ripristino con l'RTO misurato;
  - capacità del DB;
  - Recovery Kit.
- **Azioni**:
  - «Verifica ora»: accoda `core.backup_engine.tasks.verify_task`; l'esito compare come `BackupRun` di tipo verifica;
  - download di `restore-plan.json` per un punto nel tempo.
- **Tabelle**:
  - esecuzioni, con filtri per tipo, esito e periodo;
  - dettaglio di ogni set, con manifest leggibile;
  - ultime prove di ripristino.

Da questa pagina **non si può ripristinare nulla**.

### `manage.py hub_restore_drill`

1. Prende l'ultimo FULL verificato e i LOG fino al più recente (oppure `--stopat "AAAA-MM-GG HH:MM"`).
2. Se il DB × 1,1 non entra nello staging, non parte e registra un WARNING.
3. Esegue `RESTORE DATABASE <db>_drill … WITH MOVE, NORECOVERY, CHECKSUM`, poi i log in sequenza, poi `RECOVERY` (con `STOPAT`).
4. Sulla copia controlla:
   - `DBCC CHECKDB` (`PHYSICAL_ONLY` per default, `BACKUP_DRILL_CHECKDB_MODE=full` per il controllo completo);
   - migrazioni identiche al manifest;
   - righe delle tabelle chiave entro `BACKUP_DRILL_ROW_TOLERANCE_PCT` (5%).
5. Decifra in memoria `BACKUP_DRILL_DECRYPT_SAMPLES` (5) file per radice privata con la chiave corrente.
6. Esegue sempre `DROP DATABASE <db>_drill` nel `finally` e ripulisce lo staging.
7. Registra un `RestoreDrill` con l'RTO della sola parte DB e l'esito di ogni controllo.

Guardie: il nome della copia finisce sempre con `_drill` e non si usa mai `WITH REPLACE`. Anche i DB di `BACKUP_EXTRA_DATABASES` vengono ripristinati su una copia `_drill`, controllati e poi eliminati.

Il task DRILL (domenica 04:00) si registra con `register-backup-tasks.ps1 -IncludeDrill`.

### `manage.py hub_restore_plan`

`--target-time "AAAA-MM-GG HH:MM" [--out restore-plan.json]` calcola il piano di ripristino. Il calcolo sta in `core/backup_engine/restore_plan.py`, che non dipende da Django: il tool di ripristino lo usa anche su una macchina nuova.

Il piano contiene:

- il FULL di partenza;
- i LOG in ordine, con `STOPAT` sull'ultimo;
- lo snapshot dei file e la fotografia della macchina non oltre il punto richiesto;
- lo zip della release;
- le migrazioni;
- le impronte attese delle chiavi.

Se la catena ha un buco, il comando esce con exit 2.

### Ripristino dall'applicazione disattivato

`HUB_TOOLS_DB_RESTORE_ENABLED=False` è il default (decisione del 16/10/2026):

- `hub_tools.api_db_restore` risponde 403 JSON con `reason=restore_disabled` e rimanda a `restore-host.ps1`;
- in Hub → «Database» il pulsante «Ripristina» è sostituito da un rimando alla pagina dei backup;
- il **backup** al volo resta disponibile.

### Verifiche fatte (17/10/2026, SQL Server 2025 Express, copia del DB di sviluppo poi eliminata)

- `hub_restore_drill` reale: FULL + log ripristinati su `PN_R2_TEST_drill` con CHECKDB pulito e migrazioni identiche. Conteggi identici (utenti 140, anagrafica 145, asset 774, ticket 691), decifratura ok, RTO DB 10 s, copia eliminata.
- La prova ha trovato un bug, già corretto: `sqlcmd -h 1` ripeteva l'intestazione a ogni riga e `FILELISTONLY` veniva letto male. Corretti anche i messaggi d'errore localizzati («Messaggio N»).
- Pagina verificata a video in tema chiaro, scuro e su telefono a 390 px, senza scroll orizzontale.
