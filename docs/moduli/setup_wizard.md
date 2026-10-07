# `setup_wizard` — wizard primo setup

Area **Core** · URL `/setup/` · codice [`django_app/setup_wizard/`](../../django_app/setup_wizard/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Wizard primo setup (anche via `SetupWizard.exe`)

## Dettaglio

Wizard Django 12 step raggiungibile su `/setup/`, usato quando `SETUP_COMPLETED=0`. Esiste anche come **installer standalone `SetupWizard.exe`** (14 step) per deploy Windows Server.

- Configurazione `SiteConfig`, `.env`, credenziali admin
- Wizard exe: discovery SQL Server (UDP broadcast + TCP scan + SSRP)
- Selezione moduli **tier-based** (system/standard/optional)
- Migrate selettivo per modulo scelto, con copertura di tutte le app dotate di migration (`anomalie`, `monitoring`, `planimetria` incluse)
- Runtime Python 3.11+ rilevato e validato prima della creazione del virtualenv
- `collectstatic` isolato dai bootstrap ACL runtime, così non apre cache/DB prima di copiare gli asset
- Preflight SQL Server: il database configurato viene creato/verificato prima delle migration; con `DB_TRUST_CERT=True` anche `sqlcmd` usa `-C` e, se serve, fallback ODBC con `TrustServerCertificate=yes`. In sviluppo locale, `DB_ENCRYPT=0` consente di disattivare `Encrypt` per istanze SQLEXPRESS legacy/non compatibili TLS, lasciandolo vuoto nei deploy normali.
- Il wizard web interno preserva `DB_TRUST_CERT` quando si modifica solo LDAP/SMTP, evitando che ODBC Driver 18 perda `TrustServerCertificate=yes` su ambienti con certificato SQL non trusted
- Trigger automazioni SQL idempotenti: `apply_sql_triggers` crea la queue e salta i trigger la cui tabella sorgente legacy/opzionale non esiste nel DB corrente; gli script assenze sono self-guarded anche se lanciati direttamente
- Fail-fast: se venv/pip/migrate/collectstatic falliscono, release **non** attivata
- FinishPage mostra banner rosso "Installazione Incompleta" con countdown 60s
- Server Dashboard integrato con start/stop/restart IIS, reset password live e terminale TEST/PROD con ~33 preset comandi curati dal Runbook (Test, ACL, AI/RAG, SGI, MPQ, Skill Matrix, Reminder, Import dati con «📎 Sfoglia file…» contestuale, Manutenzione, Sync), etichetta rischio 🟢/🟡/🔴 e descrizione breve per preset
- Menu di scelta (`SetupWizard.exe` senza argomenti): chiudere Installa/Gestisci server/Gestione Release/Disinstalla (X, Annulla o fine flusso) **ripresenta il menu** invece di uscire dal programma — si esce chiudendo il menu stesso
- Server Dashboard — pannello **Servizi Windows**: elenca i servizi rilevanti per l'hosting (IIS `W3SVC`/`WAS`/`AppHostSvc`, SQL Server `MSSQL*`/`SQLAgent*`/`SQLBrowser`/`SQLWriter`) con stato (in servizio / arrestato / avvio / arresto / in pausa) e tipo di avvio (automatico / manuale / disattivato); gestione inline Avvia/Ferma/Riavvia e cambio tipo di avvio, attiva solo se il setup gira come Amministratore
- Server Dashboard — **pagina scrollabile** (mouse + scrollbar) con in cima un **«Pannello di controllo»** a blocchi cliccabili (Stato servizi IIS · Servizi Windows · Controlli IIS · Automazioni django-q · Assistente AI · Log waitress · Terminale): ogni card porta direttamente alla sezione corrispondente, così le funzioni «sotto la piega» restano sempre raggiungibili
- Server Dashboard — **Command center**: in cima alla pagina lo stato interno del portale dell'ambiente selezionato, letto con `manage.py command_center status` (JSON) usando venv e release dell'ambiente. Sei indicatori (versione/commit del pacchetto, migrazioni pendenti, qcluster attivo o fermo, task falliti nelle 24 h, schedule KO / in ritardo / non registrati, servizi readyz) e quattro schede: **Schedule** (cadenza, prossima e ultima esecuzione, esito, stato; doppio clic = esecuzione immediata), **Errori recenti** di django-q con testo completo, **Servizi** readyz, **Dettagli** (issue aperte, automazioni fallite, job in ritardo). Azioni: Aggiorna stato, **Esegui ora** (lancia la funzione dello schedule nel terminale anche a qcluster fermo, `command_center run <nome>`), Registra schedule, **Verifica post-deploy**. Aggiornamento automatico ogni 2 minuti
- Server Dashboard — **Terminale grande**: la console in una finestra dedicata (font più grande, Pulisci, stessi preset) che condivide comando e output con il terminale in pagina
- Setup Wizard — **verifica post-deploy automatica**: a fine promozione release e a fine installazione TEST/PROD esegue `command_center post-deploy` (registra gli schedule django-q con `setup_q_schedules`, `check`, migrazioni pendenti, readyz); non blocca la release, i problemi finiscono nel riepilogo
- **Release Manager** (`--mode release`) con quattro operazioni: **Crea Release** (`.zip` completo da DEV), **Promuovi Release** (deploy `.zip` su TEST/PROD) e il flusso **Hotfix** a due fasi — **Crea Hotfix** (`--mode hotfix-create`, rileva i file modificati via git e li impacchetta in un `hotfix-*.zip` leggero) e **Applica Hotfix** (`--mode hotfix-apply`, estrae il pacchetto hotfix sul release attivo `current\`, esegue eventuali management command e ricicla IIS, senza nuova release)
- **Permessi durante gli upgrade**: Promuovi Release conserva grant e binding ACL gia configurati. Il bootstrap aggiunge solo route/permessi mancanti; il seed UAT con reset resta disponibile soltanto nell'installazione iniziale TEST. Un riallineamento dei grant ai valori legacy richiede il comando esplicito `acl_sync_legacy_grants` dopo averne esaminato il dry-run.
