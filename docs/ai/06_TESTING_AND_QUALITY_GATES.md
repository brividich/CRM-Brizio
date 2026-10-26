# Testing And Quality Gates

Workflow, release, Setup Wizard, and local quality rules moved out of root CLAUDE.md.

Important: Do not read all docs automatically. Open only the files relevant to the current task.

## Aggiornamenti obbligatori dopo ogni modifica

**REGOLA: dopo ogni modifica al codice (nuova funzionalità, bugfix, refactor significativo) aggiornare SEMPRE e AUTOMATICAMENTE questi file, senza aspettare istruzioni esplicite:**

1. **`docs/ai/*.md` + `CLAUDE.md` leggero** — aggiornare il file AI mirato per dettagli lunghi; aggiornare `CLAUDE.md` solo per regole operative concise
2. **`CHANGELOG.md`** — aggiungere o aggiornare la voce nella sezione della versione corrente
3. **`README.md`** — aggiornare se la modifica cambia funzionalità visibili, URL, setup o dipendenze
4. **Versione** — se la modifica è rilevante per l'utente finale, applicare la checklist "Bump di versione" qui sotto

Questo aggiornamento è parte integrante di ogni task, non un'attività opzionale.

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

1. `VERSION` (root repo) — single source of truth (`X.Y.Z`)
2. `django_app/VERSION` — mirror di compatibilita, deve combaciare con root `VERSION`
3. `django_app/config/app_version.py` — riga `DEFAULT_APP_VERSION = "X.Y.Z"`
4. `deployment/setup_wizard.py` — riga `_DEFAULT_APP_VERSION = "X.Y.Z"`

### File configurazione

1. `django_app/.env.example` — `APP_VERSION=X.Y.Z` + tutte le `APP_VERSION_*`
2. `config\test\.env` e `config\prod\.env` — `APP_VERSION=X.Y.Z` (source of truth runtime deploy)

### File documentazione (tutti devono mostrare la versione nel frontmatter/header)

1. `CLAUDE.md` header — `Versione app corrente: **X.Y.Z** (YYYY-MM-DD)`
2. `CHANGELOG.md` — aggiungere sezione `## X.Y.Z - YYYY-MM-DD`
3. `README.md` — badge `![Version X.Y.Z](https://img.shields.io/badge/version-X.Y.Z-F97316)`
4. `doc/README.md` — `> Versione documentazione: **X.Y.Z**`
5. `doc/START_HERE.md` — `> Versione documentazione: **X.Y.Z**`
6. `doc/TESTING.md` — `> Versione documentazione: **X.Y.Z**`
7. `doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md` — `> Versione documentazione: **X.Y.Z**`
8. `doc/STRUTTURA_ATTUALE_PORTALE.md` — `Data snapshot: YYYY-MM-DD | Versione: X.Y.Z`
9. `deployment/README_DEPLOY_IIS_WINDOWS.md` — `> Versione repo: **X.Y.Z**`
10. `tools/MANUALE_ADMIN_NAVIGAZIONE_PERMESSI.md` — `> NOVICROM HUB · Aggiornato: YYYY-MM-DD (vX.Y.Z)`

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
- `hotfix-create` (`ReleaseConfigHotfixCreate` + `ReleaseRunPage._run_hotfix_create`, lato DEV): **nasce da commit, mai dal working tree**. Input: commit in produzione (base, da Centrale di comando/BUILD_INFO) e commit target (default `origin/release/prod`). `_git_hotfix_plan` rifiuta se il target non è in `release/prod` o se la base non ne è antenata; calcola `git diff --name-status base target` e filtra con la stessa allowlist di `package-release.ps1` (`django_app/`, `deployment/`, `sql/`, `tools/`, root md/VERSION; esclusi `docs`, `media*`, `dist`, `build`, `*.exe`, ecc.: altrimenti dopo l'hotfix `BUILD_INFO` dichiarerebbe un commit che `current\` non rispecchia). Migration o `requirements*.txt` **bloccano** il pacchetto. I file escono da `git show target:path`; lo zip `hotfix-vX.Y.Z-<target8>-<timestamp>.zip` contiene `HOTFIX_INFO.json` (base, target, file, eliminati, `needs_collectstatic`). Pacchetto incompleto = eliminato.
- `hotfix-apply` (`ReleaseConfigHotfixApply` + `ReleaseRunPage._run_hotfix_apply`, lato server): fail-closed. Rifiuta se manca `HOTFIX_INFO.json` o se `current\BUILD_INFO.json` non ha `commit` uguale alla base del pacchetto. Copia i file sostituiti in `<env>\hotfix_backups\<timestamp>-<target8>\`, applica scritture ed eliminazioni (guard zip-slip con `is_relative_to`), in caso di errore ripristina tutto. Poi aggiorna `BUILD_INFO.json` (`commit` = target, voce in `hotfixes[]`), esegue `collectstatic` se servono statici, i management command opzionali e ricicla l'App Pool IIS. Non crea release né tocca la junction.
- `promote` conserva i grant e i binding ACL gia presenti: dopo `migrate` esegue `bootstrap_acl_v2 --apply` senza `--import-legacy`, e non esegue `seed_acl_uat --reset` neppure su TEST. Il seed UAT resta opzionale nell'installazione iniziale TEST.
- Flusso: fix su feature → main → `release/prod` (come sempre) → su DEV `hotfix-create` → copia sul server → `hotfix-apply` su TEST poi PROD. `deployment/scripts/patch-release.ps1` resta solo per emergenze: copia dal working tree e non aggiorna BUILD_INFO.

#### Hotfix o release?

| Hotfix (Crea/Applica Hotfix) | Release (Crea Release + Promuovi) |
|---|---|
| Il server è su un commit noto (BUILD_INFO con `commit`) | Pacchetto in prod senza BUILD_INFO/commit, o costruito da working tree |
| Diff base→target senza migration né `requirements*.txt` | Qualunque migration o dipendenza nuova |
| Codice, template, SQL, statici (collectstatic automatico) | Modifiche a `.env`, `web.config`, schedule `setup_q_schedules`, comandi post-deploy (`normalizza_*`, `ricalcola_*`) |
| Correzione urgente, pochi file, rischio basso | Versione nuova (bump `VERSION`), più funzionalità accumulate, lavoro da collaudare su TEST |

Regola pratica: se anche un solo punto cade nella colonna destra, è una release. Il wizard la impone comunque bloccando migration/requirements e base sbagliata.

### Selezione moduli (ModulesPage — step 11)

- `MODULE_REGISTRY` (costante di modulo in `setup_wizard.py`): lista di dict con campi `key`, `label`, `description`, `app_label`, `required`, `default`, `depends_on`, `has_migrations`, `tier`.
- Tre tier: `system` (obbligatori, checkbox disabilitato), `standard` (pre-selezionati), `optional` (disattivati per default — futuro licensing).
- Ogni app con migration Django deve essere presente in `MODULE_REGISTRY` con `has_migrations=True`, anche se e' un wrapper/servizio tecnico (`monitoring`, `planimetria`, `anomalie`), altrimenti `createsuperuser` e i comandi successivi avvisano di migration non applicate.
- `cfg.selected_modules`: lista di key salvata nel `Config` e passata al migrate selettivo.
- `_run_selective_migrate()` presente sia in `InstallPage` che in `ReleaseRunPage` (non ereditano): migra nell'ordine `_DJANGO_BUILTIN_MIGRATE_LABELS` → moduli `required` → moduli opzionali selezionati.
- La dipendenza automatica tra moduli (es. `tickets` → `assets`, `anagrafica`) è gestita in UI via `depends_on`: attivare un modulo auto-attiva le sue dipendenze; disattivarlo auto-disattiva i moduli che dipendono da esso.
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
# SBAGLIATO — causa TemplateSyntaxError a runtime
f["_stato"] = "APERTO"     # nel template: {{ f._stato }} → ERRORE

# CORRETTO
f["stato"] = "APERTO"      # nel template: {{ f.stato }} → OK
```

Questo si applica anche a dict arbitrari passati al template (es. campi SharePoint arricchiti con metadati computed). Non usare mai chiavi `_xxx` in oggetti/dict che vengono passati al contesto template.

### Graph / SharePoint

- Utility centralizzata: `core/graph_utils.py` — `acquire_graph_token(tenant_id, client_id, client_secret)`
- Cache thread-safe con `Lock + dict`, rinnovo 60s prima della scadenza
- **Non duplicare** la logica token nelle singole app — usare sempre `core/graph_utils.py`
- I nomi di campo SharePoint con spazi usano encoding URL: spazio → `_x0020_`, slash → `_x002F_`. Verificare sempre i nomi reali via risposta Graph API prima di hardcodarli.

---

## Sessioni parallele e disciplina git

Le regole brevi sono in `CLAUDE.md`; qui le motivazioni.

- **Perché un worktree per sessione.** Branch e file non committati appartengono alla cartella, non alla sessione. Se più sessioni lavorano in `C:\Dev\Portale Novicrom`, il `git checkout` di una cambia il branch sotto le altre e il `git add` di una mette in stage il lavoro in corso di un'altra (e un checkout può scartare in silenzio modifiche non committate). Il checkout condiviso resta un riferimento in sola lettura; se proprio si deve toccare un file lì, si mettono in stage solo i propri hunk.
- **Perché ogni sessione chiude con un commit.** Il server di sviluppo serve la cartella di lavoro, quindi il codice «funziona» anche se non è committato; il packager invece esporta un commit di `release/prod`. Un file non committato funziona in locale e non esiste per la produzione: la divergenza si scopre al deploy. Un commit su branch feature è al sicuro e recuperabile, ma non è in produzione finché non arriva in `release/prod`.
- **Percorso dei merge.** Feature → `main` (integrazione e verifica) → `release/prod` (promozione). Mai merge diretti di una feature in release (regola di Brizio, 02/10/2026).
- **Pre-flight del pacchetto.** `deployment/scripts/package-release.ps1` fallisce se il tree è sporco o se il branch corrente ha commit assenti da `release/prod`. `-FromWorkingTree -Force` è solo per emergenze: il pacchetto si dichiara non tracciabile in `BUILD_INFO.json` e la Centrale di comando lo mostra in rosso.
- **Badge di sviluppo.** Con `DEBUG=True` il badge in basso a destra mostra i file non committati e i commit non ancora in `release/prod`.

---

## CI GitHub (audit sicurezza 09/10)

- **Security Gate** (push/PR su `main`): `pip-audit` per primo (eccezioni solo con `--ignore-vuln <ID>` commentato e con scadenza), `check`, drift migrazioni, `validate_deployment`, test sentinella e test di regressione dell'audit. Job `diff-scan`: gitleaks sui commit nuovi, bandit solo sui problemi introdotti nei file modificati, ruff `BLE001`/`S110` sui file Python nuovi (niente `except Exception: pass` nel codice nuovo).
- **Nightly full test suite**: tutta la suite (`manage.py test .` da `django_app/`, `--parallel auto`), inclusi i guardrail lenti di `core.test_security_audit_fase3` (route esenti dal login aperte agli anonimi, IDOR generico sulle route con id). Una nuova route pubblica va aggiunta a `PUBLIC_VIEWS` con il motivo.
- Senza etichette `manage.py test` esegue solo `DEFAULT_TEST_LABELS` (core, tasks, attrezzature).
- **PR check** (`.github/workflows/pr-check.yml`, PR verso `main` e `release/prod`, igiene repo 18/10): `check`, drift migrazioni, ruff `F821,F811,E722,F401` su tutto `django_app` (debito a zero dal 18/10), test delle sole app toccate dal diff (`tools/apps_dal_diff.ps1 -BaseRef <sha>`: cartelle dirette di `django_app/` con `apps.py`, `config/` esclusa).
- **Coverage notturna**: la suite notturna gira sotto `coverage run` (config `[tool.coverage.*]` in `pyproject.toml`, lanciata da `django_app/` con `--rcfile=../pyproject.toml`); tabella per app nel riepilogo del run e artifact `coverage-report` (json + html, 14 giorni). Nessuna soglia bloccante.

---

## Strumenti di qualità locali (igiene repo 18/10)

- `pyproject.toml` (radice): ruff `py311`, riga 120, regole `E,F,B,DJ`, `E501` ignorata, `F401` ignorata in `migrations/` e `__init__.py`; esclusi `.tmp_tests`, `staticfiles`, `powerautomate-to-django-automations`. Dal 18/10 `ruff check django_app --select F821,F811,E722,F401` è a zero: va tenuto così (i tipi usati solo nelle annotazioni si importano sotto `if TYPE_CHECKING:`).
- `.pre-commit-config.yaml`: al commit ruff con le sole regole a debito zero (`F821,F811,E722,F401`, come il PR check), `end-of-file-fixer`, `check-added-large-files` (5 MB). Regole complete e `ruff format --check` solo a richiesta (`pre-commit run --hook-stage manual --files <file>`): il codice non è mai stato formattato e ha ~900 segnalazioni preesistenti, bloccherebbero quasi ogni commit. Attivazione: `pip install -r django_app/requirements-dev.txt; pre-commit install`.
- `tools/pulizia_root.ps1 [-IncludeIgnored]`: elenca i non tracciati in radice, non cancella nulla.
- `config.test_runner.NovicromDiscoverRunner` rimuove in `teardown_test_environment` le cartelle orfane `django_app/.tmp_tests/tasks_test_media_*`.

## Dry-run migrazioni su SQL Server (`tools/migration_dryrun.ps1`)

I test girano su SQLite: certi errori del dialetto SQL Server escono solo al `migrate` del deploy, che fallisce e lascia la release **non attivata** (`release_promote_*.log`). Prima di un rilascio con migrazioni:

```powershell
.\tools\migration_dryrun.ps1                      # default --settings=config.settings.prod_readonly
.\tools\migration_dryrun.ps1 -App anagrafica,assets
.\tools\migration_dryrun.ps1 -RepoPath C:\Dev\pn-release   # migrazioni di un altro checkout (es. release/prod)
```

Lo script prende le righe `[ ]` di `showmigrations --plan`, salva l'SQL di `sqlmigrate` per ciascuna in `deployment/dryrun/<data>/` (ignorata da git) con `_report.txt`, ed esce con 1 se trova:

- **Indice filtrato con `NOT`/`OR`/`LIKE`**: SQL Server li rifiuta (errore 156). Tipico di `UniqueConstraint(condition=~Q(campo=""))` → usare `Q(campo__gt="")`; ammessi `=`, `>`, `IS NULL`, `IS NOT NULL`, `AND`.
- **INSERT a batch dentro savepoint** (`DECLARE @t TABLE` / `OUTPUT INSERTED` dopo `SAVE TRANSACTION`): al primo scarto lascia result set pendenti sul cursore pyodbc, `savepoint_rollback` fallisce e tutta la transazione si invalida (`TransactionManagementError` a cascata). In un loop riga-per-riga con `atomic()` annidato usare una `INSERT ... VALUES` semplice.

Le operazioni `RunPython` sono elencate come «da rivedere a mano» (sqlmigrate non ne mostra l'SQL) ma non bloccano. Il profilo `prod_readonly` ha un router che nega le migrazioni e svuoterebbe l'SQL: lo script esegue `sqlmigrate` con i router disattivati, mentre la barriera di sola lettura sulle query (execute_wrapper + grant `db_datareader`) resta attiva.

## Test su SQL Server (`config.settings.test_mssql`, 25/10/2026)

`config.settings.test` usa sempre SQLite: i rami con SQL scritto a mano (`connection.vendor == "microsoft"`, `TOP`, `ISNULL`, `READPAST`…) e le migrazioni non girano mai nei test. Il profilo `test_mssql` è identico ma usa un SQL Server vero, letto solo da variabili `TEST_MSSQL_*` (mai `DB_*` del `.env`, che in sviluppo punta al DB locale condiviso tra le sessioni):

| Variabile | Default | Note |
|---|---|---|
| `TEST_MSSQL_HOST` | — (obbligatoria) | es. `localhost\HUBTEST`; rifiuta `NOVISQL`/`PCLOGSYS` |
| `TEST_MSSQL_USER` / `TEST_MSSQL_PASSWORD` | vuote = autenticazione Windows | serve il ruolo `dbcreator` |
| `TEST_MSSQL_DRIVER` | `ODBC Driver 18 for SQL Server` | |
| `TEST_MSSQL_DB` | `test_hub_mssql` | deve iniziare con `test_`; Django crea e cancella solo questo |

```powershell
$env:TEST_MSSQL_HOST = "localhost\HUBTEST"
python django_app\manage.py test assenze --keepdb --settings=config.settings.test_mssql
```

- Il primo giro senza `--keepdb` applica **tutte** le migrazioni da zero su SQL Server: è anche la prova che una installazione nuova parte.
- **Istanza locale consigliata:** SQL Server 2025 Developer (gratuita, stessa versione 17 della produzione su NOVISQL\CNHUB), istanza con nome **`HUBTEST`**, autenticazione Windows, separata da `SQLEXPRESS` che contiene il DB di sviluppo. Dopo l'installazione basta impostare `TEST_MSSQL_HOST`.
- **CI:** `.github/workflows/nightly-mssql.yml` (notte e a richiesta) installa SQL Server Express sul runner Windows e lancia `migrate` da zero più i test delle app con più SQL a mano (`automazioni assenze anomalie admin_portale dashboard core`). È separato dalla suite notturna su SQLite: se è rosso non blocca le PR.
- Non sostituisce `tools/migration_dryrun.ps1`, che controlla le migrazioni *pendenti* contro lo schema reale di produzione.

## Repo annidato `django_app/powerautomate-to-django-automations`

È un **gitlink** (mode 160000) senza `.gitmodules`: git ne registra solo il commit, un clone o un worktree lo vede come cartella vuota. Nel checkout di sviluppo contiene un repo git proprio con una **`.venv`** dentro e un'app Flask (`app/webapp.py`) avviata con **`debug=True`** (debugger Werkzeug = esecuzione di codice remoto se esposto). Non fa parte del portale: è escluso dal packager (`$excludeDirs` in `deployment/scripts/package-release.ps1`, oltre all'allowlist), dal bundle di `SetupWizard.exe` (`exclude_dir_names` in `deployment/setup_wizard_bundle_rules.json`, test `core.test_wizard_bundle_rules`) e da ruff (`pyproject.toml`). Un exe costruito dal checkout prima del 18/10 può contenerlo (con la sua `.venv`): va ricostruito. Non avviarlo su interfacce raggiungibili da rete; non aggiungerlo a `INSTALLED_APPS`.

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

