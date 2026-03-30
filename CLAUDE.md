# CLAUDE.md — Portale Novicrom

Documento di contesto per AI coding assistant. Aggiornato continuamente con il progetto.
Versione app corrente: **0.8.5** (2026-03-28)

---

## Stack tecnico

- **Backend:** Django 5.2, Python 3.11+
- **Database prod:** SQL Server (mssql-django 1.6, pyodbc 5.2)
- **Database dev:** SQLite (solo per sviluppo Django-only, senza tabelle legacy)
- **Auth:** 3 backend in cascata — `SQLServerLegacyBackend` → `LDAPBackend` (AD `cnovicrom.local`) → `ModelBackend`
- **Frontend:** SSR puro con Django templates, nessun framework JS, CSS custom
- **Integrazioni:** Microsoft Graph/SharePoint (MSAL), LDAP/AD, SMTP

---

## App Django (custom)

| App | Scopo |
| --- | ----- |
| `core` | Middleware ACL, navigation registry, legacy models, auth backends, context processors |
| `dashboard` | Home page utente, widget configurabili |
| `assenze` | Gestione assenze dipendenti + sync SharePoint |
| `anomalie` | Segnalazione e gestione anomalie produzione |
| `assets` | Gestione asset aziendali (macchinari, attrezzature) |
| `tasks` | Task management interno |
| `automazioni` | Designer visuale automazioni + SQL trigger → event queue |
| `admin_portale` | Pannello admin custom (non Django admin) |
| `anagrafica` | Anagrafica dipendenti (integrata con AD/legacy DB) |
| `notizie` | Bacheca notizie/comunicazioni |
| `timbri` | Report timbrature (lettura da DB legacy) |
| `planimetria` | Wrapper per assets (modelli vuoti, solo reindirizzamento) |
| `tickets` | Sistema ticket interni |
| `rentri` | Tracciabilità rifiuti (normativa RENTRI) |
| `diario_preposto` | Diario del preposto sicurezza |
| `rilevazione_incidenti` | Rilevazione incidenti / unsafe condition (CRUD via Graph API, SharePoint come fonte di verità) |
| `hub_tools` | Hub strumenti interni: Module Manager + Database Manager |
| `setup_wizard` | Wizard guidato prima configurazione (12 step) |
| `dpi` | Gestione DPI (Dispositivi Protezione Individuale): richieste con card-picker immagini, approvazione, consegna, storico, KPI |
| `procedure_refresh` | Presa visione procedure MT/MTSI: anagrafica documenti, revisioni con sorgente SharePoint/file server, campagne, assegnazioni, tracking aperture/conferme, report, export CSV |

---

## Sistema ACL / Permessi

**CRITICO: ci sono due sistemi ACL che coesistono e NON si sincronizzano.**

### 1. ACL Engine legacy (sicurezza reale)

- File: `core/acl.py`, `core/middleware.py`
- Pipeline: `path → _match_pulsante() → modulo+azione → perm_map per ruolo_id → 403/pass`
- Tabelle SQL Server legacy: `utenti`, `ruoli`, `pulsanti`, `permessi`, `anagrafica_dipendenti`
- Modelli in `core/legacy_models.py` — `Ruolo`, `UtenteLegacy`, `Pulsante`, `Permesso`, `AnagraficaDipendente` — ora `managed=True` (app_label="core"), migration `0029_legacy_managed` applicata con `--fake` (tabelle preesistenti su SQL Server)
- Bypass totale per `is_legacy_admin()`: cerca `ruolo.nome == "admin"` (case-insensitive)
- Bypass totale per `request.user.is_superuser`
- Cache ACL gestita da `core/legacy_cache.py` con chiavi versionare e `bump_legacy_cache_version()` (usa Django cache framework, non `lru_cache`)

### 2. Navigation Registry (visibilità menu, non sicurezza)

- File: `core/navigation_registry.py`
- Tabelle Django: `NavigationItem`, `NavigationRoleAccess`, `UserDashboardConfig`, `UserModuleVisibility`
- Deny-by-default: nessun record in `NavigationRoleAccess` = voce NON mostrata (riga 115-117 in `navigation_registry.py`)

#### Sezioni `NavigationItem.section`

| Valore | Dove viene renderizzata | ACL |
| --- | --- | --- |
| `topbar` | Barra di navigazione principale (in cima) | `NavigationRoleAccess` (deny-by-default) |
| `subnav` | Barra secondaria per modulo (filtrata per `parent_code`) | `NavigationRoleAccess` (deny-by-default) |
| `sidebar` | Menu laterale (modalità sidebar) | `NavigationRoleAccess` (deny-by-default) |
| `page` | Dentro una pagina specifica | `NavigationRoleAccess` (deny-by-default) |
| `admin_subnav` | Barra interna dell'admin portale (`/admin-portale/`) | **Nessuna ACL** — area già gated da `@legacy_admin_required` |

**`admin_subnav` — regola critica:** NON hardcodare mai voci in `admin_subnav.html`. Gestire sempre tramite `NavigationItem` con `section="admin_subnav"` via Navigation Builder o migration. Migration seed: `core/migrations/0031_admin_subnav_seed.py` (27 voci con gruppi, descrizioni e active_patterns). Il context processor inietta `admin_subnav_items` solo per utenti `is_legacy_admin()`.

### Path esenti da ACL (MIDDLEWARE_EXEMPT_PREFIXES)

Questi path bypassano completamente l'`ACLMiddleware`:

```text
/health  /version  /login  /logout  /cambia-password
/static/  /media/  /admin/  /favicon  /setup/  /admin-portale/hub/
```

Ogni nuova app che deve essere accessibile senza autenticazione va aggiunta a `MIDDLEWARE_EXEMPT_PREFIXES` in `config/settings/base.py`.

### ACL Bootstrap (pattern per nuovi endpoint API)

Alcune app registrano automaticamente i propri endpoint nell'ACL legacy all'avvio tramite `acl_bootstrap.py`. App con bootstrap: `assenze`, `notizie`, `tasks`, `diario_preposto`.

Pattern: `AppConfig.ready()` → chiama `bootstrap_*_acl_endpoints()` → upsert su tabella `pulsanti` → `bump_legacy_cache_version()`. Gli endpoint API vengono nascosti dalla UI via tabella `ui_pulsanti_meta`.

### Impersonation

- File: `core/impersonation.py`, `core/middleware.py` (`ImpersonationMiddleware`)
- Permette a un admin di impersonare un altro utente via session key `_impersonation_state`
- Durante l'impersonation `request.user` viene sostituito con l'utente target
- Stop path: `/impersonation/stop` e `/impersonation/stop/`
- Solo `is_legacy_admin()` può avviare l'impersonation

### Elementi hardcoded da NON replicare

- Nomi moduli: `"admin"`, `"dashboard"`, `"assenze"` in `core/acl.py`
- API gate: `"/api/anomalie/"` → `"/gestione-anomalie"` in `core/middleware.py`
- Nav gate: `"tasks"` → `"/tasks/"` in `core/context_processors.py`

### Architettura target (riferimento per nuove feature)

- Unica tabella `Permission` (code slug es. `"assenze.view"`)
- `RolePermission`: `role_id + permission_code + granted` (default False, opt-in)
- `UserPermissionOverride`: `user_id + permission_code + granted`
- `NavigationItem.permission_required` → FK a `Permission` (nullable = pubblico)
- Funzione unica `has_permission(user, code)` usata da middleware, template tag, decoratori

---

## Configurazione globale — SiteConfig

`SiteConfig` (in `core/models.py`) è una tabella key-value Django per personalizzare il portale senza toccare il codice (titolo sito, moduli abilitati, temi login, ecc.).

- Accesso: `SiteConfig.get_many(defaults)` — restituisce dict con fallback
- Usato da: `setup_wizard`, `hub_tools` (Module Manager), `context_processors`
- Non usare `settings.py` per configurazioni modificabili a runtime — usare `SiteConfig`

---

## Aggiornamenti obbligatori dopo ogni modifica

**REGOLA: dopo ogni modifica al codice (nuova funzionalità, bugfix, refactor significativo) aggiornare SEMPRE e AUTOMATICAMENTE questi file, senza aspettare istruzioni esplicite:**

1. **`CLAUDE.md`** — aggiornare la sezione pertinente (nuova app, nuovo modello, nuovo pattern, nuova regola)
2. **`CHANGELOG.md`** — aggiungere o aggiornare la voce nella sezione della versione corrente
3. **`README.md`** — aggiornare se la modifica cambia funzionalità visibili, URL, setup o dipendenze
4. **Versione** — se la modifica è rilevante per l'utente finale, applicare la checklist "Bump di versione" qui sotto

Questo aggiornamento è parte integrante di ogni task, non un'attività opzionale.

---

## Bump di versione — checklist obbligatoria

Ad ogni bump di versione (es. 0.7.3 → 0.7.4) aggiornare **tutti** questi punti, senza eccezioni:

1. `CLAUDE.md` riga 4 — `Versione app corrente: **X.Y.Z**`
2. `config/settings/base.py` — `APP_VERSION = env("APP_VERSION", "X.Y.Z")`
3. `setup_wizard/views.py` — default fallback in `APP_VERSION={s('app_version', 'X.Y.Z')}`
4. `hub_tools/views.py` — default fallback in `APP_VERSION={s('app_version', current_env.get('APP_VERSION', 'X.Y.Z'))}`
5. `.env` (file locale, non versionato) — `APP_VERSION=X.Y.Z`
6. `CHANGELOG.md` — aggiungere sezione `## X.Y.Z - YYYY-MM-DD`

Il file `.env` ha **la precedenza** su tutti i default nel codice: se non viene aggiornato, la UI mostrerà sempre il valore vecchio indipendentemente dagli altri file.

---

## Setup Wizard — regola obbligatoria

**Dopo ogni modifica a `deployment/setup_wizard.py` rigenerare SEMPRE il file `SetupWizard.exe`.**

Comando da eseguire (dalla root del repo, in bash):

```bash
cd "c:/Dev/Portale Novicrom/deployment" && python -m PyInstaller SetupWizard.spec --noconfirm
```

Output atteso finale: `Build complete! The results are available in: .../deployment/dist`

Il file `.exe` è l'unico artefatto distribuito agli utenti finali — se non viene rigenerato, le modifiche al wizard non raggiungono chi non ha Python installato.

- Spec file: `deployment/SetupWizard.spec`
- Output: `deployment/dist/SetupWizard.exe` (escluso da git via `.gitignore`)
- Dimensione attesa: ≈56 MB (include sorgente Django bundled per installazione DEV self-contained)

### Discovery SQL Server (DatabasePage)

- **3 strategie in background thread** (non blocca UI):
  1. `pyodbc.sqlservers()` — UDP broadcast SQL Browser (porta 1434)
  2. TCP scan porta 1433 su hostname comuni (localhost, macchina, varianti SQLEXPRESS, AD)
  3. UDP SSRP broadcast manuale per istanze su subnet diverse
- Pulsante "📋 Lista DB": si connette al server e popola Combobox con database utente (prova ODBC 18→17→generico)
- `self._discover_btn` e `self._list_db_btn` si disabilitano durante la ricerca

### Meccanismo auto-close (FinishPage / ReleaseDonePage / UninstallDonePage)

- Countdown gestito internamente da ogni pagina "Done" via `_start_countdown(n)` (aggiornato ogni secondo)
- Costruttore accetta `on_close=None` callback — passare sempre `self._close` dalla App parent
- `_close()` in WizardApp/ReleaseApp/UninstallApp chiama `root.destroy()` direttamente (non via `after`)

### Server Dashboard

Accessibile da: launcher (card "Gestisci server"), FinishPage (pulsante), CLI `--mode=dashboard`.

- Mostra stato IIS Site + App Pool per `TEST` e `PROD` con tab switcher
- Auto-refresh ogni 5 secondi via PowerShell `Get-Website` / `Get-WebAppPool`
- Pulsanti: Avvia, Ferma, Riavvia, Ricicla Pool, Apri Browser
- Log viewer: ultimi 40 righe di `ENV\logs\waitress_stdout.log`
- **Cleaner**: elimina release vecchie mantenendo ultime 3 + quella attiva (`current`)
- `ServerDashboard(parent=None)` → standalone (`tk.Tk`); `parent=widget` → `tk.Toplevel`

### HttpPlatformHandlerPage (step 8)

- Verifica presenza `httpPlatformHandler` via `Get-WebGlobalModule` PowerShell
- Badge verde se installato, giallo se mancante
- Pulsante "Scarica" apre `iis.net/downloads/microsoft/httpplatformhandler`
- `validate()` non bloccante — avvisa con dialog ma permette di continuare
- Saltata in DEV (aggiunta a `_skip_for_dev` con `_HPH_PAGE_IDX = 8`)

### Settings module mapping

Solo `config/settings/dev.py` e `config/settings/prod.py` esistono. Il wizard usa `_django_settings(environment)` per mappare:
- `dev` → `config.settings.dev` (SQLite)
- `test` → `config.settings.prod` (SQL Server)
- `prod` → `config.settings.prod` (SQL Server)

La funzione `_django_settings()` è definita a livello modulo in `setup_wizard.py`.

### Variabili .env generate dal wizard

I nomi delle variabili nel `.env` devono corrispondere ESATTAMENTE a quelli letti da `base.py`/`prod.py`:

| Variabile .env | Letta da | Note |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | `base.py` | NON `SECRET_KEY` |
| `DJANGO_DEBUG` | `base.py`/`prod.py` | NON `DEBUG` |
| `DJANGO_ALLOWED_HOSTS` | `prod.py` | NON `ALLOWED_HOSTS` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `prod.py` | NON `CSRF_TRUSTED_ORIGINS` |
| `DJANGO_LOG_DIR` | `base.py` | NON `LOG_DIR` |
| `DB_ENGINE`, `DB_NAME`, `DB_HOST`, `DB_USER`, `DB_PASSWORD` | `base.py` | OK — nomi corretti |
| `STATIC_ROOT`, `MEDIA_ROOT` | `base.py` | Ora leggono da env con fallback |

### Junction NTFS (\_create\_junction)

- Funzione module-level `_create_junction(link_path, target_path)` usata da `InstallPage` e `ReleaseRunPage`
- Strategia rimozione: `rmdir /Q` → `shutil.rmtree` → `rd /s /q`
- Errore chiaro se il path è ancora in uso

### HttpPlatformHandler check

- `_check_httpplatformhandler()` verifica la presenza del modulo IIS via `Get-WebGlobalModule`
- Se mancante: tenta installazione via WebPI CLI, altrimenti mostra istruzioni manuali
- Senza questo modulo, IIS restituisce errore 500.19 (0x8007000d)

### Crash-safety _run()

- `InstallPage`, `ReleaseRunPage`, `UninstallRunPage` hanno wrapper `_run()` → `_run_impl()` in try/except
- Se eccezione non gestita: logga traceback + chiama `_on_done` per mostrare comunque la pagina Done

**Trigger obbligatori — rigenerare l'exe dopo qualsiasi modifica a:**

| File / cartella | Motivo |
| --- | --- |
| `deployment/setup_wizard.py` | Il wizard stesso è compilato nell'exe |
| `django_app/` (qualsiasi file) | Il sorgente Django è bundled nell'exe per DEV self-contained |
| `deployment/scripts/*.ps1` | Script PowerShell inclusi in `datas` dello spec |
| `deployment/config/*.template` | Template inclusi in `datas` dello spec |
| `deployment/SetupWizard.spec` | Cambia la struttura del bundle |
| Bump di versione | Il numero versione nel wizard deve corrispondere |

---

## Pattern di sviluppo

### Import in tickets/views.py — REGOLA CRITICA

I modelli di altre app (`Asset`, `UserExtraInfo`, `AnagraficaDipendente`, `Fornitore`, ecc.) **NON** sono importati a livello di modulo in `tickets/views.py`. Vanno sempre importati **localmente dentro la funzione** che li usa:

```python
# CORRETTO
def mia_view(request):
    from assets.models import Asset as AssetModel
    ...

# SBAGLIATO — causa NameError a runtime
Asset.objects.filter(...)
```

Motivo: import lazy per evitare circular imports tra app.

### FBV (Function-Based Views)

Il progetto usa quasi esclusivamente FBV. Non introdurre CBV senza necessità.

### Settings

- `config/settings/base.py` + `dev.py` + `prod.py`
- Variabili ambiente da `.env` (via `environ`) + `config.ini` (via `configparser`)
- Per sviluppo: `--settings=config.settings.dev`

### Template Django — REGOLA: variabili NON possono iniziare con underscore

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

## Hub Tools — Strumenti interni admin

Percorso: `/admin-portale/hub/` — richiede `is_legacy_admin()`.

| Sottopath | View | Descrizione |
| --- | --- | --- |
| `moduli/` | `moduli` | Module Manager: abilita/disabilita moduli visibili. Toggle via AJAX. Redirect post-login configurabile. |
| `database/` | `database` | DB Manager: statistiche tabelle, backup, pulizia log/sessioni, ottimizzazione, ripristino. Engine rilevato automaticamente (SQLite in dev, SQL Server in prod). |
| `database/schema/` | `db_schema` | **Schema DB infografica**: mappa visuale di tutti i modelli Django (campi, tipi, relazioni FK/1:1/M:M). Template: `hub_tools/templates/hub_tools/db_schema.html`. Versione standalone anche in `db_schema.html` nella root del repo. |
| `homepage-builder/` | `homepage_builder` | Editor visuale layout home page per ruolo. |
| `setup-wizard/` | `setup_wizard_hub` | Riesecuzione wizard configurazione (12 step), legge `.env` corrente. |
| `guide/` | `guide_list` | Elenco guide/manuali (file statici da `tools/`). |
| `guide/<slug>/` | `guide_view` | Visualizzazione singola guida. |

### Schema DB — riepilogo modelli per app

| App | Modelli | Note |
| --- | --- | --- |
| `core` | 22 | Profile, NavigationItem, NavigationRoleAccess, AuditLog, SiteConfig, Notifica, UserExtraInfo, Checklist*, AnagraficaVoce/Risposta, Dashboard configs, RepartoCapoMapping, OptioneConfig, LoginBanner, LegacyRedirect, NavigationSnapshot |
| `core` (legacy, ex-unmanaged) | +5 | Ruolo, UtenteLegacy, AnagraficaDipendente, Pulsante, Permesso — ora `managed=True` sotto `core`, migration 0029 faked |
| `assets` | 25 | Asset, AssetCategory, AssetITDetails, WorkMachine, WorkOrder, WorkOrderAttachment/Log, PeriodicVerification, AssetEndpoint, PlantLayout/Area/Marker, AssetDocument, AssetLabelTemplate + modelli config UI |
| `tasks` | 7 | Project, Task, SubTask, TaskComment, ProjectComment, TaskEvent, TaskAttachment |
| `automazioni` | 6 | AutomationRule, AutomationCondition, AutomationAction, AutomationRunLog, AutomationActionLog, DashboardMetricValue |
| `tickets` | 4 | Ticket, TicketCommento, TicketAllegato, TicketImpostazioni |
| `notizie` | 4 | Notizia, NotiziaAudience, NotiziaAllegato, NotiziaLettura |
| `anagrafica` | 9 | Fornitore, FornitoreDocumento/Ordine/Valutazione/Asset, RuoloOperativo, DipendenteRuoloOperativo, DipendenteStatLayout, AnagraficaStatPermission |
| `timbri` | 4 | OperatoreTimbri, RegistroTimbro, RegistroTimbroImmagine, TimbriImportIssue |
| `diario_preposto` | 3 | SegnalazionePreposto, SegnalazioneAllegato, DiarioPrepostoImpostazioni |
| `rilevazione_incidenti` | 2 | RilevazioneIncidente (cache locale da SharePoint), SicurezzaImpostazioni |
| `rentri` | 1 | RegistroRifiuti |
| `assenze` | 1 | CertificazionePresenza |
| `dpi` | 5 | CategoriaDPI (con immagine, vita utile), DPIImpostazioni (singleton), RichiestaDPI (numero DPI-YYYY-NNNN, stati), ConsegnaDPI (1:1 con RichiestaDPI), RichiestaDPICommento |
| `procedure_refresh` | 6 | ProcedureDocument (code univoco, tipo MT/MTSI/ALTRO), ProcedureRevision (sorgente sharepoint/fileserver, unicità is_current per documento, validazione URL/path), ProcedureCampaign (stati draft/published/closed/archived), ProcedureCampaignDocument (FK campagna+revisione, unique_together), ProcedureAssignment (FK utente Django, stati assigned→opened→read_confirmed/overdue/cancelled, tracking aperture: open_count, first_opened_at, last_opened_at, IP, user_agent), ProcedureReadEvent (log eventi opened/confirmed/reminder_sent/reassigned/exported) |

**Relazioni inter-app principali:**

- `tickets.Ticket` → `assets.Asset` (FK), `anagrafica.Fornitore` (FK)
- `assets.WorkOrder` → `anagrafica.Fornitore` (FK), `assets.PeriodicVerification` (FK)
- `assets.PeriodicVerification` → `anagrafica.Fornitore` (FK), `assets.Asset` (M:M)
- `assets.FornitoreAsset` → `assets.Asset` (FK), `anagrafica.Fornitore` (FK)

---

## Infrastruttura server (NON riproducibile in dev)

Questi componenti esistono solo sul server di produzione:

- Tabelle legacy SQL Server: `utenti`, `ruoli`, `pulsanti`, `permessi`, `anagrafica_dipendenti` — DDL non nel repo, migration Django `0029_legacy_managed` presente ma applicata con `--fake` (tabelle preesistenti)
- Trigger SQL Server per assenze (`sql/`): `trg_assenze_automation_after_insert`, `trg_assenze_automation_after_update`
- Tabella `automation_event_queue` (`sql/automation_event_queue.sql`)
- SharePoint/Graph data (credenziali `GRAPH_*` nel `.env`)
- `media/fotocard`, `media/timbri`, `media/firme`
- `config.ini` runtime (solo `.example` nel repo)

---

## Automazioni

- Designer visuale → regole salvate su DB → trigger SQL Server → inserimento in `automation_event_queue`
- Management command: `python manage.py process_automation_queue`
- File principali: `automazioni/models.py`, `automazioni/views.py`, `sql/`

---

## Audit Trail

- Funzione: `core/audit.py` → `log_action(request, azione, modulo, dettaglio)`
- Scrive su `core.models.AuditLog` (tabella Django, con migration)
- Fire-and-forget: gli errori DB sono loggati ma non propagati alla view
- Traccia automaticamente se l'azione è eseguita in impersonation (aggiunge `_impersonation` nel payload)
- App che già usano audit log: `admin_portale`, `anomalie`, `assenze`, `assets`, `core`
- **Da usare** per ogni operazione CRUD rilevante (creazione/modifica/cancellazione di entità)

---

## URL routing

Tutte le app sono incluse in `config/urls.py`. Prefissi notevoli:

| Prefisso | App |
| --- | --- |
| `/setup/` | `setup_wizard` |
| `/admin-portale/` | `admin_portale` |
| `/admin-portale/hub/` | `hub_tools` |
| `/automazioni/` | `automazioni` |
| `/anagrafica/` | `anagrafica` |
| `/tickets/` | `tickets` |
| `/diario-preposto/` | `diario_preposto` |
| `/rilevazione-incidenti/` | `rilevazione_incidenti` |
| `/notizie/` | `notizie` |
| `/dpi/` | `dpi` |
| `/procedure-refresh/` | `procedure_refresh` |
| `/admin/` | Django admin nativo |

Le app `dashboard`, `assenze`, `anomalie`, `timbri`, `rentri`, `core`, `planimetria` usano prefisso vuoto `""` (i path sono definiti internamente al loro `urls.py`).

---

## Logging

- File log in `django_app/logs/`: `app.log`, `app-{hostname}.log`, `sql.log`
- Handler custom `SafeTimedRotatingFileHandler` in `core/logging_handlers.py` (rotazione giornaliera, safe per multi-process)
- SQL logging configurabile via env `SQL_LOG_ENABLED` e `SQL_LOG_LEVEL`
- In produzione non usare `print()` — usare sempre `logging.getLogger(__name__)`

---

## Compatibility layer Flask

- `core/legacy_flask_views.py`: 62 route Flask coperte (27 native, 35 redirect/410)
- Non modificare senza capire prima quale route Flask copre

---

## Debito tecnico noto (non toccare senza discussione)

1. SQL raw inline in `core/context_processors.py` e alcune views
2. Cache Graph primitiva (`Lock + dict`) — non sicura su multi-process (wsgi multi-worker)
3. `planimetria/models.py` è vuoto (solo commento) — non aggiungere logica
4. `module_registry.py`: solo `assets` registrato, gli altri moduli non sono brandizzabili

---

## Cache in produzione (IIS multi-worker)

Con 2+ worker IIS usare `DatabaseCache` (SQL Server) — condivisa tra processi:

- Configurata automaticamente da `config/settings/prod.py`
- **Setup una-tantum dopo ogni deploy su server vergine:** `python manage.py createcachetable`
- Tabella: `django_cache` (override con env `DJANGO_CACHE_TABLE`)
- `bump_legacy_cache_version()` usa `cache.incr()` atomico → invalidazione ACL immediata su tutti i worker
- Dev usa `LocMemCache` (default Django) — nessuna configurazione aggiuntiva

---

## Setup ambiente sviluppo

```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
pip install -r django_app/requirements.txt
# configurare django_app/.env e config.ini da .example
python django_app/manage.py migrate --settings=config.settings.dev
# applicare manualmente sql/ scripts su SQL Server
python django_app/manage.py runserver --settings=config.settings.dev
# oppure: avvia_server.bat
```

**Requisiti sistema:** Python 3.11+, SQL Server con schema legacy popolato, ODBC Driver 17 o 18 for SQL Server.

---

## File sensibili nel repo (da non esporre)

- `django_app/.env` — credenziali AD, IP di rete, SECRET_KEY
- `DIPENDENTI.csv` — dati reali dipendenti
- `db.sqlite3` — DB locale con dati di test
- `build/` e `dist/` — contengono `asta.exe` e `utenti.db`
