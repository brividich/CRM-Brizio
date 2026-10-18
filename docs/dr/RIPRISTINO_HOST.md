# Reinstallazione da backup: `restore-host.ps1`

Il tool ricostruisce NOVICROM HUB su una macchina nuova a partire dai backup verificati (BUILD_SPEC R3). Caratteristiche:

- **headless**;
- **riprendibile**: con `-Resume` riparte dalla prima fase non completata;
- ogni fase controlla prima lo stato e agisce solo se serve, ed è cronometrata.

Alla fine produce un report con l'**RTO** misurato, da archiviare come evidenza della prova di disaster recovery. Il runbook completo, con scenari, contatti e calendario delle prove, arriva con il blocco R4.

## Prima di cominciare

Servono:

- l'accesso alla share dei backup (`BACKUP_TARGET`);
- il file del Recovery Kit e la passphrase (busta in Direzione);
- un account con accesso di rete alla share per i task, oppure il gMSA sulla futura VM;
- per il connector Entra, un amministratore del tenant che possa fare l'accesso interattivo con MFA.

La macchina di ripristino ha internet. Gli installer si possono comunque preparare prima nella cache del NAS (`<BACKUP_TARGET>\_prereqs`), così il ripristino non dipende dai siti esterni:

```powershell
.\deployment\scripts\restore-host.ps1 -BackupTarget \\nas\hub-backup -CachePrereqsOnly
```

## Uso

```powershell
# 1) simulazione: mostra cosa farebbe ogni fase, non cambia nulla
.\deployment\scripts\restore-host.ps1 -BackupTarget \\nas\hub-backup -RecoveryKit D:\kit\prod.hubkit `
    -PublicHostname hub.costruzioninovicrom.it -AltHostnames hub.cnovicrom.local -WhatIf
# 2) ripristino (PowerShell come amministratore)
.\deployment\scripts\restore-host.ps1 -BackupTarget \\nas\hub-backup -RecoveryKit D:\kit\prod.hubkit `
    -PublicHostname hub.costruzioninovicrom.it -AltHostnames hub.cnovicrom.local `
    -AppPoolIdentity 'CNOVICROM\gmsa-hub$' -TaskGmsa 'CNOVICROM\gmsa-hub$'
# 3) dopo un errore o un riavvio
.\deployment\scripts\restore-host.ps1 ... -Resume
# a un punto nel tempo (es. cancellazione accidentale alle 14:35)
.\deployment\scripts\restore-host.ps1 ... -TargetTime "2026-10-16 14:30"
```

Parametri principali:

| Parametro | Uso |
|---|---|
| `-Environment` | `prod` (default) o `test` |
| `-PlanFile` / `-TargetTime` | un piano già calcolato, oppure il punto nel tempo; senza nessuno dei due si usa il più recente |
| `-AppPoolIdentity` | `ApplicationPoolIdentity` (default, come oggi), `DOMINIO\utente` (con `-AppPoolCredential`) oppure `DOMINIO\gmsa$` |
| `-SqlInstance`, `-SqlMajorVersion` | istanza da usare o da installare. La versione non può mai essere più vecchia di quella del backup |
| `-SkipPhase` | salta fasi per nome o numero, es. `entra,9` |
| `-ApplySpn` | crea gli SPN mancanti, se i diritti lo consentono. Senza, stampa i comandi `setspn` da eseguire |
| `-EntraTenantId`, `-EntraConnectorClientId` | registrazione automatica del connector, con il modulo MSAL.PS installato |

Lo stato sta in `C:\PortaleNovicrom\shared\recovery\state.json`; lì si trovano anche transcript, `restore-plan.json` e report.

## Fasi

| # | Fase | Cosa fa |
|---|---|---|
| 0 | Preflight | Controlla privilegi, edizione di Windows, dominio, spazio libero (almeno 3 × DB + file, letto dai manifest), raggiungibilità del target, internet, porte 80/443. Legge la fotografia della macchina d'origine e chiede conferma |
| 1 | Prerequisiti | Installa IIS (`Install-WindowsFeature` su Server, `Enable-WindowsOptionalFeature` su client), poi gli installer del **lock** `deployment\recovery\prereqs.lock.json` nella stessa minor di Python del backup. Prepara il venv con i requirements e calcola il piano di ripristino |
| 2 | SQL Server | Installa l'istanza se manca (`install-sql2025-instance.ps1` con la collation del backup). Rifiuta il downgrade di versione. Esegue il restore di FULL e LOG (`NORECOVERY`, `STOPAT`, `RECOVERY`) dei soli DB del piano e mai sopra un DB esistente. Poi login dell'identità del pool e utenti orfani |
| 3 | Segreti | Importa il Recovery Kit (passphrase digitata a mano) e confronta le impronte delle chiavi col piano: **se non coincidono si ferma**, perché quella chiave non aprirebbe i documenti. Estrae il certificato HTTPS |
| 4 | File | Ricostruisce media e radici private dallo store `_objects`, con SHA-256 verificato su ogni file. Decifra in memoria 5 campioni per radice privata e imposta le ACL NTFS per l'identità del pool |
| 5 | Release | Usa lo **zip esatto** del backup (`_releases/…`) con `deploy-release.ps1 -AutoActivate`. Se il deploy applica migrazioni, lo segnala: DB e codice non erano allineati |
| 6 | IIS | Esegue `configure-iis-site.ps1`, imposta l'identità del pool, importa il certificato in `LocalMachine\My` e crea i binding HTTPS per i nomi pubblico e alternativo. Confronta i binding con la macchina d'origine. Infine `secure-env-acl.ps1` |
| 7 | Task | `register-backup-tasks.ps1 -IncludeDrill`, worker `QCluster_<ENV>` (mai interattivo) + watchdog, coda automazioni, helper IIS. Segnala i task della macchina d'origine che mancano (es. polling mail) |
| 8 | Connector Entra | Installazione silent dal lock; registrazione con token interattivo (MSAL.PS), altrimenti azione manuale. Il token non va mai su disco. Ricorda connector group e URL interno |
| 9 | Identità e rete | `setspn -Q` per entrambi i nomi (comandi `setspn -S` suggeriti, applicati solo con `-ApplySpn`), DNS (**mai modificato**: solo istruzioni), share usate dal portale, regole firewall |
| 10 | Verifica | `smoke-test.ps1`, `hub_recovery_selfcheck` (DB, migrazioni, chiavi = backup, documenti cifrati aperti, pagine protette servite), `hub_backup_doctor`, primo `hub_backup --type full` |
| 11 | Report | `recovery-report-<data>.html` e `.json`: durata di ogni fase, **RTO totale**, differenze rispetto alla macchina d'origine, azioni manuali rimaste |

## Prerequisiti: il lock

`deployment\recovery\prereqs.lock.json` contiene, per ogni installer, l'URL ufficiale, l'URL risolto, l'**SHA-256**, il firmatario, la versione, gli argomenti silent e il controllo di presenza. I valori li scrive `deployment\recovery\update-prereqs-lock.ps1`:

1. scarica ogni installer;
2. verifica la **firma Authenticode**: deve essere valida e del firmatario atteso (Microsoft Corporation o Python Software Foundation);
3. solo allora registra hash e URL.

Una voce senza hash non viene mai scaricata. Se un file cambia alla fonte (link «evergreen»), l'hash non coincide e il tool si ferma: si rilancia `update-prereqs-lock.ps1` e si committa il lock aggiornato.

Stato al 17/10/2026, tutte le voci verificate:

| Voce | Versione |
|---|---|
| Python | 3.11.9, 3.12.10, 3.13.16 |
| VC++ 2015-2022 | 14.44 |
| ODBC Driver 18 | 18.4.1.1 |
| HttpPlatformHandler | 1.2 |
| URL Rewrite | 2.1 |
| SQL Server 2025 Express (bootstrapper) | 17.0.1000.7 |
| Microsoft Entra private network connector | 1.5.4892 |

Tesseract e Poppler restano installazioni manuali, se la macchina d'origine li usava: le versioni sono nell'host-manifest.

## Strumenti eseguibili senza Django

Sulla macchina nuova si usano prima che il portale sia configurato:

- `core/backup_engine/restore_plan.py <BACKUP_TARGET>\<env> [--target-time] --out restore-plan.json`
- `core/backup_engine/recovery_kit.py verify|import …`
- `core/backup_engine/restore_files.py <BACKUP_TARGET>\<env> --index <set>\files\index.json [--env-file] [--map VECCHIO=NUOVO] [--dry-run]`

## Test

- `deployment\tests\test-restore-host.ps1 -Python <python>` verifica: ripresa da `state.json`, rifiuto del downgrade SQL, rifiuto dei DB fuori piano, prerequisiti senza hash o con hash diverso, report HTML/JSON con RTO, e `-WhatIf` di tutte le fasi su un target sintetico senza modifiche e senza segreti a video. Gira su PowerShell 5.1 e 7.
- Python, `core.test_recovery_kit`:
  - kit: round-trip, passphrase errata, manomissione di intestazione o contenuto, passphrase debole, import che si ferma con impronte diverse;
  - ricostruzione dei file: hash verificato, campioni decifrati, chiave sbagliata rilevata;
  - lock dei prerequisiti.
