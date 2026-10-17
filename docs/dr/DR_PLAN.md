# Piano di disaster recovery — NOVICROM HUB

Versione 1 · 17/10/2026. Procedure operative: [RUNBOOK_RIPRISTINO.md](RUNBOOK_RIPRISTINO.md).

## Obiettivi

| Obiettivo | Valore | Come si ottiene |
|---|---|---|
| RPO (dati persi al massimo) | **1 ora** dalle 07 alle 21; 24 ore fuori orario o prima del recovery FULL | backup FULL ogni notte, backup del log ogni ora nella finestra (recovery model FULL dopo la migrazione a SQL Server 2025) |
| RTO (tempo per tornare operativi) | **mezza giornata** (tollerati 1–2 giorni) | `restore-host.ps1` / SetupWizard «Ripristina da backup», misurato a ogni prova trimestrale |
| Verifica dei backup | continua | `RESTORE VERIFYONLY` a ogni backup, impronte SHA-256, prova di ripristino automatica settimanale |

## Inventario dei componenti

| Componente | Dove vive | Come si protegge | Come si ripristina |
|---|---|---|---|
| Database `PortaleNovicrom_PROD` (e `_TEST`) | SQL Server Express sul PC (istanza attuale; poi `HUB2025` su SQL 2025) | `hub_backup --type full` + `--type log`, verificati | fase 2 di `restore-host.ps1` (FULL + LOG con STOPAT) |
| Database `DLM`, `CNGAUGE` | stessa istanza (non dell'HUB) | inclusi con `BACKUP_EXTRA_DATABASES` quando saranno sulla nuova istanza; recovery model mai cambiato | stessa fase, solo se presenti nel piano |
| Media e documenti privati (cifrati) | `C:\PortaleNovicrom\<env>\media`, `media_private` | `hub_backup --type files` (incrementale, store con impronte) | fase 4 (hash verificato, campioni decifrati) |
| Codice | release a cartelle + junction `current` | zip esatto della release copiato nel target (`_releases`) | fase 5 (`deploy-release.ps1`) |
| Segreti (`.env`, `DOCUMENT_ENCRYPTION_KEY`, certificato HTTPS) | `config\.env`, archivio certificati | Recovery Kit cifrato in 3 collocazioni + passphrase in busta | fase 3 (impronte verificate col backup) |
| Configurazione della macchina (IIS, task, SPN, versioni) | Windows | `hub_backup --type host` (fotografia + export XML) | fasi 1, 6, 7, 9; differenze nel report |
| Backup stessi | NAS Synology | Hyper Backup verso Synology C2 (cifrato) e secondo NAS in altra sede | Hyper Backup |
| Macchina intera (futura VM) | ESXi | Synology Active Backup for Business (agentless, application-aware) | ABB; il tool di ripristino resta il piano B e la via per cambiare macchina |

## Dipendenze esterne

| Dipendenza | Uso | Se manca |
|---|---|---|
| Active Directory / LDAP | login, Windows SSO, gMSA, account dei task | login locali (utenti legacy) ancora possibili; SSO no |
| Microsoft Graph / SharePoint / Outlook | mailbox, calendari, sync documenti | il portale funziona, le integrazioni si fermano |
| SMTP | notifiche | nessuna mail; il resto funziona |
| Microsoft Entra Application Proxy (connector) | link di approvazione da fuori (`/approval-actions/*`) | approvazioni da mail esterne non raggiungibili; dall'interno funzionano |
| Ollama (box GPU) | assistente AI | l'assistente degrada a ricerca testuale |
| Share SGI e documentali | AI e procedure | funzioni relative non disponibili |
| NAS dei backup | backup e ripristino | nessun backup finché non torna (runbook, scenario D) |
| DNS interno | nomi `hub.costruzioninovicrom.it` e `hub.cnovicrom.local` | il portale risponde solo per indirizzo; dopo un ripristino i record vanno aggiornati a mano |
| Internet (macchina di ripristino) | download dei prerequisiti verificati | usare la cache `\\nas\hub-backup\_prereqs` |

## Decisioni prese (16/10/2026)

| Tema | Decisione |
|---|---|
| Audit di business | 5 anni online, poi archivio; archivi conservati 10 anni |
| Pulizia dello storico dell'audit | `audit_archive --plan` → revisione → `--run`, eseguito solo da Brizio |
| Recovery model | FULL dopo la pulizia; log ogni ora 07–21 |
| SQL Server | 2025 Express, istanza affiancata sul PC attuale; `DLM` e `CNGAUGE` spostati in seguito da Brizio |
| Query Store | limite 100 MB |
| Ripristino dall'applicazione | disattivato (`HUB_TOOLS_DB_RESTORE_ENABLED=False`) |
| Identità del pool | invariata sul PC; gMSA sulla futura VM |
| Nomi del portale | `hub.costruzioninovicrom.it` (canonico, pubblico e interno) e `hub.cnovicrom.local` (alternativo) |
| Copia fuori sede | Synology C2 cifrato lato client + secondo NAS in altra sede |
| Recovery Kit | passphrase a Brizio + busta in Direzione; kit su share segreti, Vaultwarden, C2 |

## Decisioni aperte

- Data della migrazione di produzione a SQL Server 2025 e dell'attivazione del recovery model FULL.
- Data della prima prova di ripristino completo su VM isolata (si propone entro il trimestre).
- Monitoraggio dei job Hyper Backup: file di stato esportato dal NAS oppure controllo manuale periodico.
- Registrazione automatica del connector Entra (modulo MSAL.PS e client id) oppure procedura interattiva.
- Tempi della migrazione a VM su ESXi e configurazione di Active Backup for Business.
