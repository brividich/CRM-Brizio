# Changelog — Portale Novicrom / BoluHUB

Tutte le modifiche rilevanti al progetto sono documentate qui.
Formato: [Keep a Changelog](https://keepachangelog.com/it/1.0.0/)

---

## 0.8.5 - 2026-03-28

### Added
- **Admin Subnav dinamica** — La barra di navigazione interna dell'admin portale (`/admin-portale/`) è ora gestita dal database tramite `NavigationItem` con `section="admin_subnav"`. Aggiungere, rimuovere, rinominare e riordinare le voci senza toccare codice: tutto da `/admin-portale/navigation-builder/`.
  - `core/navigation_registry.py`: nuova funzione `get_admin_subnav_nodes()`, aggiunto campo `description` a `NavigationNode`
  - `core/context_processors.py`: inietta `admin_subnav_items` nel contesto template per tutti gli admin
  - `admin_portale/templates/.../admin_subnav.html`: reso completamente dinamico
  - Navigation Builder: aggiunta sezione `admin_subnav` nei filtri e nei select di creazione/edit
  - `core/migrations/0031_admin_subnav_seed.py`: seed delle 27 voci preesistenti con gruppi, ordini, active_patterns e descrizioni contestuali
- **Setup Wizard: SQL Server discovery multi-strategia** — La pagina Database ora usa un sistema di discovery robusto in background thread con 3 strategie:
  1. `pyodbc.sqlservers()` — UDP broadcast via SQL Browser service (porta 1434)
  2. TCP scan su porta 1433 per hostname comuni (localhost, SQLEXPRESS, hostname macchina, varianti AD)
  3. UDP SSRP broadcast manuale per scoprire istanze anche su subnet diverse
  - Il pulsante "🔍 Scopri server" non blocca l'UI durante la ricerca (thread daemon)
  - Nuovo pulsante "📋 Lista DB" che si connette al server selezionato e popola un Combobox con i database utente disponibili (filtra master/tempdb/model/msdb), prova driver ODBC 18 → 17 → generico
  - Auto-selezione del database più probabile (cerca "portale" o "novicrom" nel nome)
  - Il campo Nome Database è ora un Combobox invece di un semplice Entry
  - Auto-discovery al caricamento della pagina Database (non serve premere il pulsante)
  - Mostra driver ODBC disponibili come nota informativa
- **Setup Wizard: auto-install waitress** — Durante installazione TEST/PROD, `waitress` viene installato automaticamente se non presente nel requirements.txt (necessario per IIS HttpPlatformHandler)

### Added
- **Setup Wizard: step "Prerequisiti IIS"** — Nuova pagina (step 8) tra IIS/Web e Utente Admin. Verifica la presenza di `HttpPlatformHandler` via PowerShell, mostra badge verde/giallo, offre link diretto al download. `validate()` non bloccante: avvisa ma permette di continuare. Saltata in DEV.
- **Server Dashboard** — Pannello di controllo offline accessibile da: schermata launcher, FinishPage del wizard, riga di comando (`--mode=dashboard`). Mostra stato sito IIS e App Pool per TEST/PROD con auto-refresh ogni 5 secondi. Pulsanti: Avvia, Ferma, Riavvia, Ricicla Pool, Apri Browser. Log viewer (ultimi 40 righe di `waitress_stdout.log`). Può aprirsi come finestra standalone (`tk.Tk`) o sovrapposto al wizard (`tk.Toplevel`).
- **Server Dashboard: Cleaner** — Pulsante "Pulisci release vecchie" nel footer del dashboard. Mantiene le ultime 3 release + quella attiva, elimina le più vecchie con conferma.
- **Wizard: chiusura garantita** — `_close()` ora chiama `root.quit()` + `root.destroy()` + `os._exit(0)` come ultima risorsa — garantisce chiusura su Python 3.14.

### Fixed
- **Setup Wizard: finestre terminale infinite dal Server Dashboard** — Tutti i `subprocess.run` e `subprocess.Popen` del wizard mancavano di `creationflags=subprocess.CREATE_NO_WINDOW`. Il Server Dashboard fa auto-refresh ogni 5 secondi lanciando PowerShell: senza questo flag ogni chiamata apriva una finestra terminale visibile, causando un loop di finestre senza fine. Aggiunto `CREATE_NO_WINDOW` a tutti i subprocess del file (dashboard, junction, sqlcmd, IIS config, uninstall, Python version check, HttpPlatformHandler check).

### Fixed
- **Setup Wizard: `config.settings.test` non esiste** — Il wizard generava `DJANGO_SETTINGS_MODULE=config.settings.test` per l'ambiente TEST, ma solo `dev.py` e `prod.py` esistono. Aggiunta funzione `_django_settings()` che mappa `test→prod` e `dev→dev`. Questo causava il fallimento a cascata di collectstatic, migrate, createcachetable, createsuperuser e creazione admin legacy.
- **Setup Wizard: nomi variabili .env errati** — Il file `.env` generato usava nomi che non corrispondevano a quelli letti da `base.py`/`prod.py`: `SECRET_KEY` → `DJANGO_SECRET_KEY`, `DEBUG` → `DJANGO_DEBUG`, `ALLOWED_HOSTS` → `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` → `DJANGO_CSRF_TRUSTED_ORIGINS`, `LOG_DIR` → `DJANGO_LOG_DIR`. Aggiunti anche `SECURE_SSL_REDIRECT=False` (per TEST senza HTTPS) e `DB_TRUST_CERT=True`.
- **Setup Wizard: junction (mklink /J) fallisce** — Riscritto meccanismo creazione junction in funzione module-level `_create_junction()`: prova `rmdir /Q`, poi `shutil.rmtree`, poi `rd /s /q` come fallback. Messaggio errore chiaro se il path è ancora in uso.
- **Setup Wizard: createcachetable falso positivo** — Il return code di `createcachetable` non veniva controllato — segnava sempre "✓ completato". Ora controlla il risultato e mostra errore se fallito.
- **Setup Wizard: HttpPlatformHandler IIS mancante** — Aggiunto check `_check_httpplatformhandler()` prima della scrittura web.config. Verifica la presenza del modulo via `Get-WebGlobalModule`, tenta installazione via WebPI, e mostra istruzioni manuali se non riesce. Senza questo modulo IIS restituisce errore 500.19.
- **base.py: STATIC_ROOT e MEDIA_ROOT non configurabili** — `STATIC_ROOT` e `MEDIA_ROOT` erano hardcoded in `base.py`. Ora leggono rispettivamente da env `STATIC_ROOT` e `MEDIA_ROOT` con fallback ai percorsi originali.
- **Setup Wizard: Python 3.14 pyodbc build error** — Aggiunto metodo `_pip_install_with_retry()` con fallback per errori di compilazione e pre-processing dinamico del requirements.txt.
  - `deployment/setup_wizard.py`: nuovo metodo `_pip_install_with_retry()` con pre-processing dinamico e logica retry
  - `django_app/requirements.txt`: aggiornato `pyodbc==5.2.0` → `pyodbc>=5.2.0`
- **Setup Wizard: finestra non si chiudeava dopo completamento** — Riscritto il meccanismo di auto-close con countdown animato reale (aggiornato al secondo):
  - `FinishPage`, `ReleaseDonePage`, `UninstallDonePage`: ora gestiscono internamente il countdown via `_start_countdown(n)` che aggiorna il label ogni secondo e chiama `on_close` callback allo scadere
  - `WizardApp._close()`, `ReleaseApp._close()`, `UninstallApp._close()`: semplificati — chiamano `root.destroy()` direttamente invece di `root.after(0, root.destroy)`
  - Eliminato il problema di `root.after(15000/30000, ...)` che non si triggerava se il timer veniva registrato prima che la pagina fosse mostrata
- **Setup Wizard: crash durante installazione lasciava la finestra bloccata** — Aggiunto wrapper `_run()` / `_run_impl()` con try/except su `InstallPage`, `ReleaseRunPage`, `UninstallRunPage`. Se un'eccezione non gestita si verifica durante l'installazione, viene loggata e la pagina Done viene comunque mostrata invece di bloccare il wizard.
- **Setup Wizard (exe): script PowerShell non trovati** — Corretto il percorso degli script `.ps1` nell'eseguibile frozen: usa `sys._MEIPASS / "scripts"` invece di `Path(__file__).parent / "scripts"` che non funzionava nell'exe compilato con PyInstaller.
- **base.py: DB_ENGINE=mssql non riconosciuto** — `build_database_from_env()` controllava solo `engine == "sqlserver"` ma il wizard scrive `DB_ENGINE=mssql`. Risultato: fallback silenzioso a SQLite in produzione. Fix: `engine in ("sqlserver", "mssql")`.
- **Setup Wizard: IIS 502.3 (0x8007053d) — permessi app pool** — `_configure_iis()` imposta l'identità del pool su `LocalSystem` (identityType=0) per garantire accesso al venv e ai file Django senza errori di permesso.
- **Setup Wizard: creazione automatica database SQL Server** — Nuovo metodo `_create_sql_database()` chiamato allo step 8 prima di `migrate`: usa `sqlcmd` per eseguire `CREATE DATABASE [nome]` con IF NOT EXISTS. Supporta sia Windows Auth che credenziali esplicite. Metodi condivisi `_find_sqlcmd()` e `_sqlcmd_auth_args()` per evitare duplicazioni.
- **Setup Wizard: login NT AUTHORITY\\SYSTEM su SQL Server** — Quando l'installazione usa Windows Integrated Auth (`DB_TRUSTED_CONNECTION=yes`) e il pool IIS gira come LocalSystem, viene ora eseguito automaticamente `sqlcmd` per creare il login `[NT AUTHORITY\SYSTEM]` su SQL Server e assegnargli ruolo `db_owner` sul database target. Se `sqlcmd` non è nel PATH mostra le istruzioni manuali per SSMS. Nuovo metodo `_configure_sql_login()` chiamato nello step 11 prima della configurazione IIS.
- **Setup Wizard: IIS 500.19 (0x80070021) — sezione handlers bloccata** — `_configure_iis()` ora esegue `appcmd.exe unlock config -section:system.webServer/handlers` prima di creare il sito, sbloccando l'override da web.config a livello di sito.
- **Setup Wizard: tasto X non chiudeva la finestra** — Aggiunto `root.protocol("WM_DELETE_WINDOW", self._close)` a `WizardApp`, `ReleaseApp` e `UninstallApp`. Ora il clic sulla X chiama `_close()` con `quit() + destroy() + os._exit(0)`, terminando il processo anche in presenza di thread daemon attivi.
- **Setup Wizard: pulsante Indietro non si disabilitava correttamente** — `SecondaryButton` riscritto con flag `_enabled` e metodo `set_enabled(bool)`. `_show()` in tutti e tre gli App aggiornato per usare `set_enabled()` invece di `._lbl.configure(state=...)` (che non bloccava gli eventi click su `tk.Label`).
- **Setup Wizard: STATIC_ROOT ignorato da collectstatic** — `env_vars` passato ai sottocomandi Django ora include esplicitamente `STATIC_ROOT` e `MEDIA_ROOT` valorizzati con i path dell'environment (`ep/static`, `ep/media`). Senza questo fix, `_load_dotenv` usava `setdefault` e non sovrascriveva le variabili già presenti nell'ambiente di sistema, causando `collectstatic` a copiare in `staticfiles/` nella release invece che nella cartella `static/` condivisa.
- **Setup Wizard: password admin in formato werkzeug** — Il wizard usava `make_password()` di Django per creare la password dell'utente admin legacy, ma il backend di autenticazione `SQLServerLegacyBackend` usa `check_password_hash()` di **werkzeug** (formato `pbkdf2:sha256:...`). I due formati sono incompatibili. Fix: sostituito `make_password` con `generate_password_hash` di werkzeug in entrambe le occorrenze dello script di creazione admin (wizard PROD e wizard DEV).
- **Setup Wizard: DB_ENGINE=mssql scritto nel .env invece di sqlserver** — `Config.to_env()` scriveva `DB_ENGINE=mssql` ma `build_database_from_env()` (già fixato) accetta `sqlserver`. Uniformato a `DB_ENGINE=sqlserver`.
- **Setup Wizard: creazione login NT AUTHORITY\\SYSTEM spostata prima di migrate** — `_configure_sql_login()` era chiamata nello step 11 (dopo IIS), ma `migrate` è nello step 8. Il migrate falliva silenziosamente perché l'utente non aveva ancora permessi sul DB. Ora entrambe le operazioni SQL (`_create_sql_database` + `_configure_sql_login`) vengono eseguite all'inizio dello step 8, prima di `migrate`.
- **Setup Wizard: versione sidebar obsoleta** — Corretto "v0.8.4" → "v0.8.5" nella sidebar.
- **Setup Wizard (exe): pyodbc mancante** — `pyodbc` non era installato nell'ambiente di build. Ora installato e bundled nell'exe. Aggiunto anche `socket`, `winreg`, `traceback`, `json` ai `hiddenimports` nel `.spec`.
- **Setup Wizard: import mancanti** — `socket`, `winreg`, `traceback` ora importati a livello di modulo invece che localmente nei metodi. Previene crash in caso di mancata risoluzione.
- **Setup Wizard: discovery SQL Server potenziata** — Aggiunte 2 nuove strategie: lettura istanze dal Windows Registry (`HKLM\...\Instance Names\SQL`) e scansione servizi Windows (`Get-Service MSSQL*`). Trovano server locali come "TESTPORTALE" anche senza SQL Browser attivo.

---

## Versioni precedenti

La storia delle versioni precedenti alla 0.8.5 non è stata ancora documentata in questo file.
Consultare `git log` per la cronologia completa dei commit.
