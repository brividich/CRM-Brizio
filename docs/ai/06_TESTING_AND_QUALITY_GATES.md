# Testing And Quality Gates

Workflow, release, Setup Wizard, and local quality rules moved out of root CLAUDE.md.

Important: Do not read all docs automatically. Open only the files relevant to the current task.

## Aggiornamenti obbligatori dopo ogni modifica

**REGOLA: dopo ogni modifica al codice (nuova funzionalitÃƒÆ’Ã‚Â , bugfix, refactor significativo) aggiornare SEMPRE e AUTOMATICAMENTE questi file, senza aspettare istruzioni esplicite:**

1. **`docs/ai/*.md` + `CLAUDE.md` leggero** ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â aggiornare il file AI mirato per dettagli lunghi; aggiornare `CLAUDE.md` solo per regole operative concise
2. **`CHANGELOG.md`** ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â aggiungere o aggiornare la voce nella sezione della versione corrente
3. **`README.md`** ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â aggiornare se la modifica cambia funzionalitÃƒÆ’Ã‚Â  visibili, URL, setup o dipendenze
4. **Versione** ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â se la modifica ÃƒÆ’Ã‚Â¨ rilevante per l'utente finale, applicare la checklist "Bump di versione" qui sotto

Questo aggiornamento ÃƒÆ’Ã‚Â¨ parte integrante di ogni task, non un'attivitÃƒÆ’Ã‚Â  opzionale.

### Governance docs/release

- Brand documentale canonico: `NOVICROM HUB`
- I nomi storici come `Portale Novicrom` possono restare solo come esempio di istanza, percorso o cartella di deploy
- Set canonico da mantenere coerente con `VERSION`: `README.md`, `CLAUDE.md`, `CHANGELOG.md`, `docs/ai/*.md`, `doc/README.md`, `doc/START_HERE.md`, `doc/TESTING.md`, `doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md`, `doc/STRUTTURA_ATTUALE_PORTALE.md`, `deployment/README_DEPLOY_IIS_WINDOWS.md`, `tools/MANUALE_ADMIN_NAVIGAZIONE_PERMESSI.md`
- Guard operativo: `tools/release_guard.ps1`
- Il release guard esegue anche `secret_hygiene_check` (bloccante), `acl_coverage_report --max-missing 216`, `validate_deployment --format json --settings=config.settings.test` (FAIL bloccanti, WARN ammessi) e `check --settings=config.settings.test`.
- Il gate test del release guard usa label esplicite (`core tasks attrezzature`) perche la discovery globale lanciata dalla root del repo non entra in `django_app/` (directory senza `__init__.py`) e puo terminare con `Found 0 test(s)` / `NO TESTS RAN`. Il profilo `config.settings.test` applica la stessa baseline tramite `NovicromDiscoverRunner` quando `manage.py test` viene invocato senza label. Il guard deve fallire se l'output del comando test contiene una di queste condizioni, anche con exit code 0.
- Artifact guard generati e non versionati: `django_app/acl_report_latest.json` e `django_app/deployment_validation_latest.json`.
- Non usare `acl_coverage_report --fail-on-missing` nel guard finche la baseline storica non e azzerata; ogni aumento di `-AclMaxMissing` deve essere una decisione esplicita.
- `deployment/scripts/package-release.ps1` deve eseguire il guard prima di creare lo zip

---

## Bump di versione - checklist obbligatoria

Ad ogni bump di versione (es. `0.7.3 -> 0.7.4`) aggiornare TUTTI questi file, senza eccezioni. Il release guard (`tools/release_guard.ps1`) verifica ognuno di essi e blocca il packaging se uno solo e fuori allineamento.

### File codice (hardcode da aggiornare)

1. `VERSION` (root repo) â€” single source of truth (`X.Y.Z`)
2. `django_app/VERSION` â€” mirror di compatibilita, deve combaciare con root `VERSION`
3. `django_app/config/app_version.py` â€” riga `DEFAULT_APP_VERSION = "X.Y.Z"`
4. `deployment/setup_wizard.py` â€” riga `_DEFAULT_APP_VERSION = "X.Y.Z"`

### File configurazione

1. `django_app/.env.example` â€” `APP_VERSION=X.Y.Z` + tutte le `APP_VERSION_*`
2. `config\test\.env` e `config\prod\.env` â€” `APP_VERSION=X.Y.Z` (source of truth runtime deploy)

### File documentazione (tutti devono mostrare la versione nel frontmatter/header)

1. `CLAUDE.md` header â€” `Versione app corrente: **X.Y.Z** (YYYY-MM-DD)`
2. `CHANGELOG.md` â€” aggiungere sezione `## X.Y.Z - YYYY-MM-DD`
3. `README.md` â€” badge `![Version X.Y.Z](https://img.shields.io/badge/version-X.Y.Z-F97316)`
4. `doc/README.md` â€” `> Versione documentazione: **X.Y.Z**`
5. `doc/START_HERE.md` â€” `> Versione documentazione: **X.Y.Z**`
6. `doc/TESTING.md` â€” `> Versione documentazione: **X.Y.Z**`
7. `doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md` â€” `> Versione documentazione: **X.Y.Z**`
8. `doc/STRUTTURA_ATTUALE_PORTALE.md` â€” `Data snapshot: YYYY-MM-DD | Versione: X.Y.Z`
9. `deployment/README_DEPLOY_IIS_WINDOWS.md` â€” `> Versione repo: **X.Y.Z**`
10. `tools/MANUALE_ADMIN_NAVIGAZIONE_PERMESSI.md` â€” `> NOVICROM HUB Â· Aggiornato: YYYY-MM-DD (vX.Y.Z)`

### Regole operative

- I default codice leggono da `VERSION` tramite `config/app_version.py`; evitare ulteriori hardcode.
- Il file `.env` runtime ha precedenza sui default nel codice: se non viene aggiornato, UI e wizard mostrano il valore precedente.
- Dopo ogni modifica a `setup_wizard.py` rigenerare `deployment/dist/SetupWizard.exe` (vedi sezione Setup Wizard).

---

## Setup Wizard - regola obbligatoria

Dopo ogni modifica a `deployment/setup_wizard.py` rigenerare sempre `deployment/dist/SetupWizard.exe`.

Comando da eseguire dalla root del repo:

```powershell
$env:PYTHONPATH = "C:\Dev\Portale Novicrom\deployment\pyinstaller_bootstrap"
Set-Location "C:\Dev\Portale Novicrom\deployment"
python -m PyInstaller SetupWizard.spec --noconfirm
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
```

Output atteso finale: `Build complete! The results are available in: .../deployment/dist`

L'exe e l'artefatto distribuito agli utenti finali: se non viene rigenerato, le modifiche al wizard non raggiungono chi non ha Python installato.

- Spec file: `deployment/SetupWizard.spec`
- Output: `deployment/dist/SetupWizard.exe` (escluso da git via `.gitignore`)
- Il bundle del wizard deve escludere sempre `.env`, `.venv`, `.tmp_tests`, database locali, cache, log, media, test suite Python e altri artefatti macchina-specifici da `django_app/`.
- Nei test Django che scrivono file o `MEDIA_ROOT` su Windows, preferire cartelle sotto `django_app/.tmp_tests` invece di `tempfile.TemporaryDirectory()` di sistema, per evitare `PermissionError` sporadici su creazione o cleanup di directory annidate.
- Le esclusioni del bundle sono centralizzate in `deployment/setup_wizard_bundle_rules.json`; `SetupWizard.spec`, `tools/release_guard.ps1` e `deployment/scripts/package-release.ps1` devono leggerlo tutti per restare coerenti.
- `deployment/scripts/package-release.ps1` deve auto-rigenerare `deployment/dist/SetupWizard.exe` se manca o e obsoleto rispetto ai trigger runtime del bundle, prima di eseguire il release guard.
- `SetupWizard.spec` usa hook custom per `tkinter` e deve continuare a includere `_tcl_data` e `_tk_data`.
- Il runtime Python del wizard e di `deployment/scripts/setup-environment.ps1` deve essere auto-rilevato in modo robusto (`py`, percorsi standard, registry, `PATH`) e validato come Python 3.11+.
- I flussi wizard DEV/TEST/PROD devono risolvere il runtime Python prima di creare il virtualenv; se non viene trovato Python 3.11+ devono registrare errore `venv` e saltare pip/migrate senza attivare release incomplete.
- I bootstrap ACL runtime lanciati dagli `AppConfig.ready()` devono usare `should_skip_runtime_bootstrap()` e non devono toccare cache/DB durante comandi Django non runtime (`collectstatic`, `createcachetable`, `migrate`, `check`, `test`), altrimenti il deploy puo bloccarsi prima dell'esecuzione reale del comando.
- Prima di `migrate` il wizard deve creare/verificare il database SQL Server configurato: la creazione deve avvenire in un batch dedicato su `master`, poi l'apertura del DB va verificata separatamente (`sqlcmd -d <DB>` o ODBC con `DATABASE=`). Non combinare `CREATE DATABASE` e `USE [DB]` nello stesso batch. Se `DB_TRUST_CERT=True`, anche `sqlcmd` deve ricevere `-C`; se resta bloccato su TLS/certificato, il wizard deve riprovare via ODBC con `TrustServerCertificate=yes`. Se fallisce con login/db accesso negato, deve saltare le migration e mostrare rimedio SSMS esplicito invece di lasciare traceback `18456/4060`.
- Dopo `migrate`, ogni flusso supportato di installazione/promote/deploy deve eseguire `ensure_legacy_schema` prima di trigger SQL, allineamenti assenze, ACL bootstrap e seed. Questo comando crea/allinea le tabelle runtime legacy richieste dal portale (`ordini_produzione`, `anomalie`, `dipendenti`, `capi_reparto`, `info_personali`, `sync_audit`, colori UI assenze) e deve essere bloccante su SQL Server se fallisce.
- Il wizard interno `/admin-portale/hub/setup-wizard/` deve normalizzare i booleani del `.env` (`True`/`False`, `yes`/`no`, `1`/`0`) prima del render e preservare `DB_TRUST_CERT` quando si salvano solo LDAP/SMTP; non deve mai spegnere `TrustServerCertificate` per differenze di formato tra wizard desktop e web.
- Se falliscono `venv`, `pip install`, `collectstatic`, `migrate` o `ensure_legacy_schema`, il wizard deve marcare l'errore esplicitamente e non attivare la release/IIS o schedulare task su un ambiente incompleto.

### Release Manager (`--mode release` / `create` / `promote` / `hotfix-create` / `hotfix-apply`)

- Quattro operazioni nel Gestore Release (`ReleaseApp`): `create` (zip completo da DEV), `promote` (deploy zip su TEST/PROD) e il flusso Hotfix a due fasi `hotfix-create` + `hotfix-apply`.
- `hotfix-create` (`ReleaseConfigHotfixCreate` + `ReleaseRunPage._run_hotfix_create`, lato DEV): rileva i file modificati/nuovi con git tramite l'helper `_git_changed_files` (`git diff --name-only HEAD` + `git ls-files --others --exclude-standard`) e li impacchetta in un `hotfix-vX.Y.Z-<timestamp>.zip` con verifica di integrità.
- `hotfix-apply` (`ReleaseConfigHotfixApply` + `ReleaseRunPage._run_hotfix_apply`, lato server): estrae il pacchetto hotfix sul release attivo `current\` con guard anti zip-slip, esegue eventuali management command Django con `--settings` coerente e ricicla l'App Pool IIS, senza creare una nuova release né aggiornare la junction.
- Flusso: su DEV `hotfix-create` → copia del pacchetto sul server → `hotfix-apply` su TEST/PROD. Per migration, dipendenze o nuovi statici resta obbligatorio `promote`. L'hotfix non aggiorna la junction e va sempre riportato nel `.zip` di release successivo.

### Selezione moduli (ModulesPage â€” step 11)

- `MODULE_REGISTRY` (costante di modulo in `setup_wizard.py`): lista di dict con campi `key`, `label`, `description`, `app_label`, `required`, `default`, `depends_on`, `has_migrations`, `tier`.
- Tre tier: `system` (obbligatori, checkbox disabilitato), `standard` (pre-selezionati), `optional` (disattivati per default â€” futuro licensing).
- Ogni app con migration Django deve essere presente in `MODULE_REGISTRY` con `has_migrations=True`, anche se e' un wrapper/servizio tecnico (`monitoring`, `planimetria`, `anomalie`), altrimenti `createsuperuser` e i comandi successivi avvisano di migration non applicate.
- `cfg.selected_modules`: lista di key salvata nel `Config` e passata al migrate selettivo.
- `_run_selective_migrate()` presente sia in `InstallPage` che in `ReleaseRunPage` (non ereditano): migra nell'ordine `_DJANGO_BUILTIN_MIGRATE_LABELS` â†’ moduli `required` â†’ moduli opzionali selezionati.
- La dipendenza automatica tra moduli (es. `tickets` â†’ `assets`, `anagrafica`) Ã¨ gestita in UI via `depends_on`: attivare un modulo auto-attiva le sue dipendenze; disattivarlo auto-disattiva i moduli che dipendono da esso.
- Totale step wizard installazione: **14** (aggiunto "Moduli" tra "Utente Admin" e "Riepilogo").

### Discovery SQL Server (DatabasePage)

- 3 strategie in background thread:
  1. `pyodbc.sqlservers()` - UDP broadcast SQL Browser (porta 1434)
  2. TCP scan porta 1433 su hostname comuni
  3. UDP SSRP broadcast manuale per istanze su subnet diverse
- Pulsante `Lista DB`: si connette al server e popola la combobox con i database utente.
- Il wizard espone e persiste anche `DB_DRIVER`: allinea automaticamente il `.env` al miglior driver SQL Server realmente installato sul server applicativo (`18 -> 17 -> 13 -> Native Client -> SQL Server`) e blocca il setup se non trova alcun driver compatibile.
- `self._discover_btn` e `self._list_db_btn` si disabilitano durante la ricerca.

### Meccanismo auto-close (FinishPage / ReleaseDonePage / UninstallDonePage)

- Countdown gestito internamente da ogni pagina `Done` via `_start_countdown(n)`.
- Il costruttore accetta `on_close=None`: passare sempre `self._close` dalla app parent.
- `_close()` in `WizardApp` / `ReleaseApp` / `UninstallApp` chiama `root.destroy()` direttamente.

### Server Dashboard

Accessibile da launcher, FinishPage e CLI `--mode=dashboard`.

- Mostra stato IIS Site + App Pool per `TEST` e `PROD`
- Auto-refresh ogni 5 secondi via PowerShell `Get-Website` / `Get-WebAppPool`
- Pulsanti: avvia, ferma, riavvia, ricicla pool, apri browser
- Reset password live account locali disponibile solo quando il wizard gira come Administrator
- Log viewer: ultime 40 righe di `ENV\logs\waitress_stdout.log`
- Terminale integrato per l'ambiente selezionato (`TEST`/`PROD`): i comandi `manage.py ...` e `python ...` vengono eseguiti con `ENV\venv\Scripts\python.exe`, `cwd=ENV\current\django_app`, `DJANGO_SETTINGS_MODULE` coerente e `PORTAL_SKIP_RUNTIME_BOOTSTRAP=1`; include preset (`check`, `showmigrations`, `migrate`, `collectstatic` dry-run, ACL) e richiede conferma per ogni comando su `PROD`
- Cleaner: elimina release vecchie mantenendo ultime 3 + quella attiva (`current`)
- `ServerDashboard(parent=None)` usa `tk.Tk`; con `parent=widget` usa `tk.Toplevel`

### HttpPlatformHandlerPage (step 8)

- Verifica presenza `httpPlatformHandler` via `Get-WebGlobalModule`
- Badge verde se installato, giallo se mancante
- Pulsante `Scarica` apre `iis.net/downloads/microsoft/httpplatformhandler`
- `validate()` non e bloccante: avvisa con dialog ma permette di continuare
- Saltata in DEV tramite `_skip_for_dev` con `_HPH_PAGE_IDX = 8`

### Settings

- `config/settings/base.py` + `dev.py` + `test.py` + `prod.py`
- Variabili ambiente da `django_app/.env` caricate dal loader custom `_load_dotenv(...)` in `base.py`
- `config.settings.test` forza SQLite e servizi lightweight anche se il file `.env` punta a SQL Server
- `config.settings.test` usa un database test SQLite con nome per processo sotto `django_app/.tmp_tests`, cosi un file rimasto da un run interrotto non puo bloccare il run successivo con prompt interattivi o schema parziali.
- `python manage.py test` usa automaticamente `config.settings.test` se non passi `--settings`
- Nei flussi wizard/deploy l'ambiente `test` usa comunque `config.settings.prod`
- La source of truth persistita e `django_app/.env` in sviluppo; nei deploy TEST/PROD e `ENV/config/.env`, caricato prima del `.env` copiato nella release attiva (`current/django_app/.env` o `releases/<id>/django_app/.env`) che resta solo fallback per chiavi mancanti.
- Per LDAP la precedenza runtime e: ambiente processo -> `ENV/config/.env` nei deploy o `django_app/.env` in dev -> default codice.
- La pagina `/admin-portale/ldap/` deve usare i valori LDAP effettivi per sync/import utenti anche prima del reload Django: la sync web passa override espliciti a `sync_ldap_users`, legge `LDAP_SERVICE_PASSWORD` da ambiente/`.env`, mostra stato password configurata e preserva il segreto esistente se il campo password resta vuoto al salvataggio. Nei deploy TEST/PROD i salvataggi admin devono scrivere il `config/.env` persistente dell'ambiente, non il `.env` copiato nella release attiva.
- `LDAP_GROUP_ALLOWLIST` e `LDAP_SYNC_PAGE_SIZE` devono restare coerenti con i valori persistiti in `.env`, senza fallback paralleli legacy
- Per sviluppo usare `--settings=config.settings.dev`

### Template Django - REGOLA: variabili NON possono iniziare con underscore

Django proibisce a livello di template engine l'accesso a chiavi dict o attributi che iniziano con `_`. Questo vale per template tag, dot notation e loop variables.

```python
# SBAGLIATO ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â causa TemplateSyntaxError a runtime
f["_stato"] = "APERTO"     # nel template: {{ f._stato }} ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ ERRORE

# CORRETTO
f["stato"] = "APERTO"      # nel template: {{ f.stato }} ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ OK
```

Questo si applica anche a dict arbitrari passati al template (es. campi SharePoint arricchiti con metadati computed). Non usare mai chiavi `_xxx` in oggetti/dict che vengono passati al contesto template.

### Graph / SharePoint

- Utility centralizzata: `core/graph_utils.py` ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â `acquire_graph_token(tenant_id, client_id, client_secret)`
- Cache thread-safe con `Lock + dict`, rinnovo 60s prima della scadenza
- **Non duplicare** la logica token nelle singole app ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â usare sempre `core/graph_utils.py`
- I nomi di campo SharePoint con spazi usano encoding URL: spazio ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ `_x0020_`, slash ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ `_x002F_`. Verificare sempre i nomi reali via risposta Graph API prima di hardcodarli.

---


## Setup ambiente sviluppo

```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
pip install -r django_app/requirements.txt
# configurare django_app/.env da .env.example
python django_app/manage.py migrate --settings=config.settings.dev
python django_app/manage.py test
# applicare manualmente sql/ scripts su SQL Server
python django_app/manage.py runserver --settings=config.settings.dev
# oppure: avvia_server.bat
```

Nota dev tooling: `django_app/avvia_server.bat` evita intenzionalmente una scansione CIM/WMI globale dei processi Python. Su alcune postazioni Windows `Get-CimInstance Win32_Process` puo restare bloccato; per questo il batch pulisce solo il listener `LISTENING` sulla porta `8000` prima di lanciare `runserver`.

**Requisiti sistema:** Python 3.11+, SQL Server con schema legacy popolato, un driver ODBC SQL Server installato (`18`, `17`, `13`, `SQL Server Native Client 11.0` o `SQL Server`).

---

