# CLAUDE.md - Portale Novicrom

Documento di contesto per AI coding assistant. Aggiornato continuamente con il progetto.
Versione app corrente: **0.9.4** (2026-04-08)

---

## Stack tecnico

- **Backend:** Django 5.2, Python 3.11+
- **WSGI IIS:** Waitress tramite HttpPlatformHandler (dipendenza runtime dichiarata in `django_app/requirements.txt`)
- **Database prod:** SQL Server (mssql-django 1.6, pyodbc 5.2)
- **Database dev:** SQLite (solo per sviluppo Django-only, senza tabelle legacy)
- **Auth:** 4 backend in cascata - `AxesStandaloneBackend` -> `SQLServerLegacyBackend` -> `LDAPBackend` (AD `cnovicrom.local`) -> `ModelBackend`
- **Frontend:** SSR puro con Django templates, nessun framework JS, CSS custom
- **Integrazioni:** Microsoft Graph/SharePoint/Outlook Calendar (MSAL), LDAP/AD, SMTP

Hardening sicurezza 0.8.7:
- login rate limiting con `django-axes` (5 tentativi, lockout 1 ora, template custom `core/pages/lockout.html`)
- upload hardening extension+MIME reale tramite `core/upload_mime.py` (fail-closed se libmagic non disponibile)
- rimozione relay password AD in sessione (`_sso_relay_pwd` non usato)
- `legacy_table_columns()` protetto da whitelist `ALLOWED_LEGACY_TABLES` (niente `PRAGMA` su nomi tabella non ammessi)
- `_SPNEGO_CONTEXTS` bounded con `TTLCache(maxsize=500, ttl=60)` per evitare crescita memoria in handshake SSO interrotti
- export CSV `assenze`/`anomalie` tracciati in AuditLog con `log_action(..., "export_csv", ...)`

---

## App Django (custom)

| App | Scopo |
| --- | ----- |
| `core` | Middleware ACL, navigation registry, legacy models, auth backends, context processors |
| `dashboard` | Home page utente e dashboard principale KPI/personalizzabile |
| `assenze` | Modulo unificato assenze: richieste, gestione, calendario, certificazioni + sync SharePoint |
| `anomalie` | Segnalazione e gestione anomalie produzione |
| `assets` | Gestione asset aziendali (macchinari, attrezzature) + scadenzario manutenzioni con creazione eventi Outlook sul calendario dell'utente selezionato |
| `tasks` | Task management interno |
| `automazioni` | Designer visuale automazioni + SQL trigger -> event queue |
| `admin_portale` | Pannello admin custom (non Django admin) |
| `anagrafica` | Anagrafica dipendenti (integrata con AD/legacy DB) |
| `notizie` | Bacheca notizie/comunicazioni |
| `timbri` | Report timbrature (lettura da DB legacy) |
| `planimetria` | Wrapper per assets (modelli vuoti, solo reindirizzamento) |
| `tickets` | Sistema ticket interni |
| `rentri` | Tracciabilita rifiuti (normativa RENTRI) |
| `diario_preposto` | Diario del preposto sicurezza |
| `rilevazione_incidenti` | Rilevazione incidenti / unsafe condition (CRUD via Graph API, SharePoint come fonte di verita) |
| `hub_tools` | Hub strumenti interni: Module Manager + Database Manager |
| `setup_wizard` | Wizard guidato prima configurazione (12 step) |
| `dpi` | Gestione DPI (Dispositivi Protezione Individuale): richieste con card-picker immagini, approvazione, consegna, storico, KPI |
| `procedure_refresh` | Presa visione procedure MT/MTSI: anagrafica documenti, revisioni con sorgente SharePoint/file server, campagne, assegnazioni, tracking aperture/conferme, report, export CSV |

---

## Sistema ACL / Permessi

### 1. ACL Canonico v2 (sorgente primaria sicurezza)

- File: `core/acl_v2.py`, `core/middleware.py`
- Modello dati gestito (Django managed):
  - `PermissionDefinition`
  - `RolePermissionGrant`
  - `UserPermissionGrant`
  - `RoutePermissionBinding`
- Ordine di risoluzione runtime:
  1. `request.user.is_superuser` bypass
  2. `is_legacy_admin()` bypass
  3. binding canonico (`route_name` o `path_pattern`) -> `permission_code`
  4. grant ruolo canonico (`RolePermissionGrant.enabled`)
  5. override utente canonico (`UserPermissionGrant.enabled`)
  6. **solo se binding canonico assente**: fallback ACL legacy
- Diagnostica strutturata: `resolve_acl_access()` / `diagnose_acl_access()` restituiscono sempre `decision_source`, `reason`, `trace`, blocco `canonical` e blocco `legacy_fallback`.
- Middleware: `ACLMiddleware` ora usa il resolver v2 e salva il dettaglio in `request.acl_decision`.

### 2. ACL Legacy (fallback compatibilita)

- File: `core/acl.py`
- Pipeline storica: `path -> _match_pulsante() -> modulo+azione -> perm_map per ruolo_id -> 403/pass`
- Diagnostica legacy dettagliata: `diagnose_permesso_for_context()`
- Tabelle SQL Server legacy: `utenti`, `ruoli`, `pulsanti`, `permessi`, `anagrafica_dipendenti`
- Modelli in `core/legacy_models.py` â€” `Ruolo`, `UtenteLegacy`, `Pulsante`, `Permesso`, `AnagraficaDipendente` â€” `managed=True` (app_label="core"), migration `0029_legacy_managed` fake su SQL Server esistente.
- Cache ACL legacy: `core/legacy_cache.py` + `bump_legacy_cache_version()`.

### 3. Navigation Registry (visibilita menu, non sicurezza)

- File: `core/navigation_registry.py`
- Tabelle Django: `NavigationItem`, `NavigationRoleAccess`, `UserNavigationOverride`, `UserDashboardConfig`, `UserModuleVisibility`
- Deny-by-default: nessun record in `NavigationRoleAccess` = voce NON mostrata (riga 115-117 in `navigation_registry.py`)
- **Override per-utente navigazione** (`UserNavigationOverride`): dopo il filtro di ruolo, `_apply_user_nav_overrides()` applica override positivi (forza mostra) e negativi (forza nascondi) per singolo utente legacy. Non usa la cache; gli admin non sono soggetti agli override. Funziona su `topbar` e `subnav`. Gestito da "Step 5 â€“ Nav Override" in `/admin-portale/acl-canonico/` e da "Override Navigazione Utente" in `/admin-portale/navigation-builder/`.

#### Sezioni `NavigationItem.section`

| Valore | Dove viene renderizzata | ACL |
| --- | --- | --- |
| `topbar` | Barra di navigazione principale (in cima) | `NavigationRoleAccess` (deny-by-default) |
| `subnav` | Barra secondaria per modulo (filtrata per `parent_code`) | `NavigationRoleAccess` (deny-by-default) |
| `sidebar` | Menu laterale (modalita sidebar) | `NavigationRoleAccess` (deny-by-default) |
| `page` | Dentro una pagina specifica | `NavigationRoleAccess` (deny-by-default) |
| `admin_subnav` | Barra interna dell'admin portale (`/admin-portale/`) | **Nessuna ACL** â€” area gia gated da `@legacy_admin_required` |

**`admin_subnav` â€” regola critica:** NON hardcodare mai voci in `admin_subnav.html`. Gestire sempre tramite `NavigationItem` con `section="admin_subnav"` via Navigation Builder o migration. Migration seed: `core/migrations/0031_admin_subnav_seed.py` + `0032_admin_subnav_acl_nav_map.py` (voce aggiuntiva mappa permessi/navigazione). Il context processor inietta `admin_subnav_items` solo per utenti `is_legacy_admin()`.

Navigation Builder (`/admin-portale/navigation-builder/`): oltre alla tabella inline include una **vista visuale drag&drop orizzontale** (scroll laterale) a colonne per sezione (`topbar`, `subnav`, `admin_subnav`, `sidebar`, `page`) con card trascinabili, spostamento cross-sezione e sincronizzazione immediata su `NavigationItem.section` + `NavigationItem.order` tramite `api_navigation_reorder`. Ogni card supporta azioni rapide `Apri`, `Clona`, `Rimuovi`; il listener globale dei click nel template deve restare `async` perchÃ© invoca fetch asincrone. Nota semantica: `topbar` rappresenta la navigazione principale e in `nav_mode=side` viene renderizzata nella sidebar. Nel builder `sidebar` e trattata come opzione avanzata (`Sidebar Dedicated`) e viene nascosta in modalita standard.

Rendering icone navigazione: `render_icon` supporta alias SVG semantici (`layout-dashboard`, `newspaper`, `scan`, `id-card`, `package`, `shield-check`, `file-check`, `key-round`, ecc.), immagini (`media:`/`static:`/URL) e fallback automatico da label per sostituire iniziali placeholder nella topbar/sidebar.

Sidebar nav side: i gruppi aperti devono restare visivamente distinti dal primo livello tramite pannello annidato, rientro e stato aperto evidente, senza rompere la leggibilita in modalita `sb-collapsed` o mobile.

### Strumenti diagnostica/gestione ACL (admin)

- `/admin-portale/acl-canonico/`: gestione operativa del layer v2 (permission code, route/path binding, grant ruolo, override utente, override navigazione utente). Tab: 1. PermissionDefinition, 2. Route Binding, 3. Role Grant, 4. User Override, **5. Nav Override** (nuovo).
- `/admin-portale/acl-route-coverage/`: report route dedicato con stati `CANONICAL_BOUND`, `LEGACY_FALLBACK`, `UNBOUND`, `COMING_SOON_EXCLUDED`, `REDIRECT_ONLY` e export CSV.
- `/admin-portale/acl-diagnostica/` (alias compat legacy: `/admin-portale/acl/`): diagnostica combinata legacy + canonical con decisione finale del resolver v2 e trace.
- `/admin-portale/mappa-permessi-navigazione/`: mappa unica route/menu con sorgente (`REGISTRY`/`LEGACY`), ruoli abilitati, override utente, admin bypass e redirect legacy. Ogni riga ha drill-down workflow visuale cliccabile; con filtro ruolo attivo supporta toggle live sia dei grant canonici v2 (`RolePermissionGrant.enabled`) sia dei permessi legacy (`can_view`) via API.

### Path esenti da ACL (MIDDLEWARE_EXEMPT_PREFIXES)

Questi path bypassano completamente l'`ACLMiddleware`:

```text
/health  /version  /login  /logout  /cambia-password
/static/  /media/  /admin/  /favicon  /setup/  /admin-portale/hub/
```

Ogni nuova app che deve essere accessibile senza autenticazione va aggiunta a `MIDDLEWARE_EXEMPT_PREFIXES` in `config/settings/base.py`.

### ACL Bootstrap (pattern per nuovi endpoint API)

Alcune app registrano automaticamente i propri endpoint nell'ACL legacy all'avvio tramite `acl_bootstrap.py`. App con bootstrap: `assenze`, `notizie`, `tasks`, `diario_preposto`.

Pattern: `AppConfig.ready()` Ã¢â€ â€™ chiama `bootstrap_*_acl_endpoints()` Ã¢â€ â€™ upsert su tabella `pulsanti` Ã¢â€ â€™ `bump_legacy_cache_version()`. Gli endpoint API vengono nascosti dalla UI via tabella `ui_pulsanti_meta`.

### Bootstrap ACL v2 (nuovo)

- Management command: `python django_app/manage.py bootstrap_acl_v2 [--dry-run] [--apps app1,app2] [--apply] [--import-legacy] [--activate-generated-bindings]`
- Funzioni principali:
  - scansione route Django nominate
  - classificazione copertura route: `CANONICAL_BOUND`, `LEGACY_FALLBACK`, `UNBOUND`, `COMING_SOON_EXCLUDED`, `REDIRECT_ONLY`
  - proposta permission code iniziali (convenzione `modulo.risorsa.azione`)
  - scope per app (`--apps`) per migrazione incrementale modulo-per-modulo
  - import opzionale da `pulsanti`/`permessi` legacy
  - in apply: upsert `PermissionDefinition` + `RoutePermissionBinding` e sync opzionale grant ruolo da fallback legacy (`RolePermissionGrant`)
  - report finale con grouping per app di route `LEGACY_FALLBACK/UNBOUND` e conteggi before/after
  - in `SetupWizard.exe` (test/prod e promote release) viene eseguito workflow automatico: dry-run pre -> apply (`--import-legacy`) -> dry-run post; in `test` il seed `seed_acl_uat --reset` Ã¨ opzionale tramite checkbox `Esegui seed UAT ACL`

### Seed ACL v2 UAT (nuovo)

- Management command: `python django_app/manage.py seed_acl_uat [--reset] [--password ...]`
- Prepara un pacchetto UAT ripetibile in ambiente locale/dev:
  - 3 ruoli legacy (`utente_base`, `responsabile_operativo`, `amministratore_portale`)
  - 6 utenti seed (`uat.base1`, `uat.base2`, `uat.resp1`, `uat.resp2`, `uat.admin1`, `uat.override1`)
  - permission definition + route binding + role grant + user override canonici
  - fallback legacy campione (`/uat/legacy-fallback-map`) + route intentionally unbound (`/uat/unbound-probe/`) + redirect legacy campione
  - report finale con route coverage campione e scenari runtime ALLOW/DENY

### Impersonation

- File: `core/impersonation.py`, `core/middleware.py` (`ImpersonationMiddleware`)
- Permette a un admin di impersonare un altro utente via session key `_impersonation_state`
- Durante l'impersonation `request.user` viene sostituito con l'utente target
- Stop path: `/impersonation/stop` e `/impersonation/stop/`
- Solo `is_legacy_admin()` puÃƒÂ² avviare l'impersonation

### Elementi hardcoded da NON replicare

- Nomi moduli: `"admin"`, `"dashboard"`, `"assenze"` in `core/acl.py`
- API gate: `"/api/anomalie/"` Ã¢â€ â€™ `"/gestione-anomalie"` in `core/middleware.py`
- Nav gate: `"tasks"` Ã¢â€ â€™ `"/tasks/"` in `core/context_processors.py`

### Architettura target (stato attuale)

- Layer canonico v2 implementato con modelli Django gestiti + resolver dedicato.
- ACL legacy mantenuto come fallback compatibile (nessun big-bang).
- Migrazione incrementale modulo-per-modulo: nuove route possono usare subito binding canonico senza rompere le route storiche.

---

## Configurazione globale - SiteConfig
`SiteConfig` (in `core/models.py`) ÃƒÂ¨ una tabella key-value Django per personalizzare il portale senza toccare il codice (titolo sito, moduli abilitati, temi login, ecc.).

- Accesso: `SiteConfig.get_many(defaults)` Ã¢â‚¬â€ restituisce dict con fallback
- Usato da: `setup_wizard`, `hub_tools` (Module Manager), `context_processors`
- Non usare `settings.py` per configurazioni modificabili a runtime Ã¢â‚¬â€ usare `SiteConfig`

---

## Aggiornamenti obbligatori dopo ogni modifica

**REGOLA: dopo ogni modifica al codice (nuova funzionalitÃƒÂ , bugfix, refactor significativo) aggiornare SEMPRE e AUTOMATICAMENTE questi file, senza aspettare istruzioni esplicite:**

1. **`CLAUDE.md`** Ã¢â‚¬â€ aggiornare la sezione pertinente (nuova app, nuovo modello, nuovo pattern, nuova regola)
2. **`CHANGELOG.md`** Ã¢â‚¬â€ aggiungere o aggiornare la voce nella sezione della versione corrente
3. **`README.md`** Ã¢â‚¬â€ aggiornare se la modifica cambia funzionalitÃƒÂ  visibili, URL, setup o dipendenze
4. **Versione** Ã¢â‚¬â€ se la modifica ÃƒÂ¨ rilevante per l'utente finale, applicare la checklist "Bump di versione" qui sotto

Questo aggiornamento ÃƒÂ¨ parte integrante di ogni task, non un'attivitÃƒÂ  opzionale.

### Governance docs/release

- Brand documentale canonico: `NOVICROM HUB`
- I nomi storici come `Portale Novicrom` possono restare solo come esempio di istanza, percorso o cartella di deploy
- Set canonico da mantenere coerente con `VERSION`: `README.md`, `CLAUDE.md`, `CHANGELOG.md`, `doc/README.md`, `doc/START_HERE.md`, `doc/TESTING.md`, `doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md`, `doc/STRUTTURA_ATTUALE_PORTALE.md`, `deployment/README_DEPLOY_IIS_WINDOWS.md`, `tools/MANUALE_ADMIN_NAVIGAZIONE_PERMESSI.md`
- Guard operativo: `tools/release_guard.ps1`
- `deployment/scripts/package-release.ps1` deve eseguire il guard prima di creare lo zip

---

## Bump di versione - checklist obbligatoria

Ad ogni bump di versione (es. `0.7.3 -> 0.7.4`) aggiornare tutti questi punti, senza eccezioni:

1. `VERSION` (root repo) - single source of truth (`X.Y.Z`)
2. `CLAUDE.md` riga 4 - `Versione app corrente: **X.Y.Z**`
3. `.env` locale runtime - `APP_VERSION=X.Y.Z` + tutte le `APP_VERSION_*` se presenti
4. `django_app/.env.example` - aggiornare `APP_VERSION` e tutte le `APP_VERSION_*`
5. `CHANGELOG.md` - aggiungere sezione `## X.Y.Z - YYYY-MM-DD`

I default codice leggono da `VERSION` tramite `config/app_version.py`; evitare hardcode diretti in altri file.

Se esiste `django_app/VERSION`, trattarlo solo come mirror di compatibilita: non e una source of truth indipendente e va mantenuto allineato al file root.

Il file `.env` ha precedenza sui default nel codice: se non viene aggiornato, UI e wizard continueranno a mostrare il valore precedente.

---

## Setup Wizard - regola obbligatoria

Dopo ogni modifica a `deployment/setup_wizard.py` rigenerare sempre `deployment/dist/SetupWizard.exe`.

Comando da eseguire dalla root del repo:

```bash
cd "c:/Dev/Portale Novicrom/deployment" && python -m PyInstaller SetupWizard.spec --noconfirm
```

Output atteso finale: `Build complete! The results are available in: .../deployment/dist`

L'exe e l'artefatto distribuito agli utenti finali: se non viene rigenerato, le modifiche al wizard non raggiungono chi non ha Python installato.

- Spec file: `deployment/SetupWizard.spec`
- Output: `deployment/dist/SetupWizard.exe` (escluso da git via `.gitignore`)
- Il bundle del wizard deve escludere sempre `.env`, `.venv`, `.tmp_tests`, database locali, cache, log, media, test suite Python e altri artefatti macchina-specifici da `django_app/`.
- Le esclusioni del bundle sono centralizzate in `deployment/setup_wizard_bundle_rules.json`; `SetupWizard.spec` e `tools/release_guard.ps1` devono leggerlo entrambi.
- `SetupWizard.spec` usa hook custom per `tkinter` e deve continuare a includere `_tcl_data` e `_tk_data`.
- Il runtime Python del wizard e di `deployment/scripts/setup-environment.ps1` deve essere auto-rilevato in modo robusto (`py`, percorsi standard, registry, `PATH`) e validato come Python 3.11+.
- Se falliscono `venv`, `pip install`, `collectstatic` o `migrate`, il wizard deve marcare l'errore esplicitamente e non attivare la release/IIS o schedulare task su un ambiente incompleto.

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
- `python manage.py test` usa automaticamente `config.settings.test` se non passi `--settings`
- Nei flussi wizard/deploy l'ambiente `test` usa comunque `config.settings.prod`
- La source of truth persistita e `django_app/.env`; il processo puo sovrascrivere singole chiavi via environment variables
- Per LDAP la precedenza runtime e: ambiente processo -> `django_app/.env` -> default codice
- `LDAP_GROUP_ALLOWLIST` e `LDAP_SYNC_PAGE_SIZE` devono restare coerenti con i valori persistiti in `.env`, senza fallback paralleli legacy
- Per sviluppo usare `--settings=config.settings.dev`

### Template Django - REGOLA: variabili NON possono iniziare con underscore

Django proibisce a livello di template engine l'accesso a chiavi dict o attributi che iniziano con `_`. Questo vale per template tag, dot notation e loop variables.

```python
# SBAGLIATO Ã¢â‚¬â€ causa TemplateSyntaxError a runtime
f["_stato"] = "APERTO"     # nel template: {{ f._stato }} Ã¢â€ â€™ ERRORE

# CORRETTO
f["stato"] = "APERTO"      # nel template: {{ f.stato }} Ã¢â€ â€™ OK
```

Questo si applica anche a dict arbitrari passati al template (es. campi SharePoint arricchiti con metadati computed). Non usare mai chiavi `_xxx` in oggetti/dict che vengono passati al contesto template.

### Graph / SharePoint

- Utility centralizzata: `core/graph_utils.py` Ã¢â‚¬â€ `acquire_graph_token(tenant_id, client_id, client_secret)`
- Cache thread-safe con `Lock + dict`, rinnovo 60s prima della scadenza
- **Non duplicare** la logica token nelle singole app Ã¢â‚¬â€ usare sempre `core/graph_utils.py`
- I nomi di campo SharePoint con spazi usano encoding URL: spazio Ã¢â€ â€™ `_x0020_`, slash Ã¢â€ â€™ `_x002F_`. Verificare sempre i nomi reali via risposta Graph API prima di hardcodarli.

---

## Hub Tools Ã¢â‚¬â€ Strumenti interni admin

Percorso: `/admin-portale/hub/` Ã¢â‚¬â€ richiede `is_legacy_admin()`.

| Sottopath | View | Descrizione |
| --- | --- | --- |
| `moduli/` | `moduli` | Module Manager: abilita/disabilita moduli visibili. Toggle via AJAX. Redirect post-login configurabile. |
| `database/` | `database` | DB Manager: statistiche tabelle, backup, pulizia log/sessioni, ottimizzazione, ripristino. Engine rilevato automaticamente (SQLite in dev, SQL Server in prod). |
| `database/schema/` | `db_schema` | **Schema DB infografica**: mappa visuale di tutti i modelli Django (campi, tipi, relazioni FK/1:1/M:M). Template: `hub_tools/templates/hub_tools/db_schema.html`. Versione standalone anche in `db_schema.html` nella root del repo. |
| `homepage-builder/` | `homepage_builder` | Editor visuale layout home page per ruolo. |
| `setup-wizard/` | `setup_wizard_hub` | Riesecuzione wizard configurazione (12 step), legge `.env` corrente. |
| `guide/` | `guide_list` | Elenco guide/manuali/documentazione tecnica indicizzato automaticamente da `tools/`, `doc/`, `deployment/` e `django_app/assets/README.md` con deduplica per formato (`html` > `pdf` > `md`). |
| `guide/<slug>/` | `guide_view` | Visualizzazione singola guida. |

### Guide Hub

- `/admin-portale/hub/guide/` non usa piu un catalogo hardcoded: scopre automaticamente i documenti supportati (`.html`, `.pdf`, `.md`) nelle directory sorgente del progetto dedicate alla documentazione.
- `guide_serve` risolve i documenti per `slug` (con fallback legacy sul filename), serve `html` e `pdf` nativamente e incapsula i `md` in un viewer HTML integrato per mantenerli consultabili anche dentro l'iframe dell'Hub.
- La vista singola guida usa CTA topbar compatti (`Nuova scheda`, `Lista guide`) per non sottrarre spazio verticale/orizzontale al documento.

### Schema DB Ã¢â‚¬â€ riepilogo modelli per app

| App | Modelli | Note |
| --- | --- | --- |
| `core` | 22 | Profile, NavigationItem, NavigationRoleAccess, AuditLog, SiteConfig, Notifica, UserExtraInfo, Checklist*, AnagraficaVoce/Risposta, Dashboard configs, RepartoCapoMapping, OptioneConfig, LoginBanner, LegacyRedirect, NavigationSnapshot |
| `core` (legacy, ex-unmanaged) | +5 | Ruolo, UtenteLegacy, AnagraficaDipendente, Pulsante, Permesso Ã¢â‚¬â€ ora `managed=True` sotto `core`, migration 0029 faked |
| `assets` | 25 | Asset, AssetCategory, AssetITDetails, WorkMachine, WorkOrder, WorkOrderAttachment/Log, PeriodicVerification, AssetEndpoint, PlantLayout/Area/Marker, AssetDocument, AssetLabelTemplate + modelli config UI |
| `tasks` | 7 | Project, Task, SubTask, TaskComment, ProjectComment, TaskEvent, TaskAttachment |
| `automazioni` | 6 | AutomationRule, AutomationCondition, AutomationAction, AutomationRunLog, AutomationActionLog, DashboardMetricValue |
| `tickets` | 7 | Ticket (+ campi analitici: componente, causa_radice, tipo_fermo, ore_fermo_macchina, data_presa_in_carico, data_primo_intervento, risolto_da_nome, ricorrente, ticket_origine FK), TicketCommento, TicketAllegato, TicketImpostazioni, CategoriaTicket, TicketStatoLog (log cambio stato), TicketIntervento (sessioni lavoro tecnico) |
| `notizie` | 4 | Notizia, NotiziaAudience, NotiziaAllegato, NotiziaLettura |
| `anagrafica` | 9 | Fornitore, FornitoreDocumento/Ordine/Valutazione/Asset, RuoloOperativo, DipendenteRuoloOperativo, DipendenteStatLayout, AnagraficaStatPermission |
| `timbri` | 4 | OperatoreTimbri, RegistroTimbro, RegistroTimbroImmagine, TimbriImportIssue |
| `diario_preposto` | 3 | SegnalazionePreposto, SegnalazioneAllegato, DiarioPrepostoImpostazioni |
| `rilevazione_incidenti` | 2 | RilevazioneIncidente (cache locale da SharePoint), SicurezzaImpostazioni |
| `rentri` | 1 | RegistroRifiuti |
| `assenze` | 1 | CertificazionePresenza |
| `dpi` | 5 | CategoriaDPI (con immagine, vita utile), DPIImpostazioni (singleton), RichiestaDPI (numero DPI-YYYY-NNNN, stati), ConsegnaDPI (1:1 con RichiestaDPI), RichiestaDPICommento |
| `procedure_refresh` | 6 | ProcedureDocument (code univoco, tipo MT/MTSI/ALTRO), ProcedureRevision (sorgente sharepoint/fileserver, unicitÃƒÂ  is_current per documento, validazione URL/path), ProcedureCampaign (stati draft/published/closed/archived), ProcedureCampaignDocument (FK campagna+revisione, unique_together), ProcedureAssignment (FK utente Django, stati assignedÃ¢â€ â€™openedÃ¢â€ â€™read_confirmed/overdue/cancelled, tracking aperture: open_count, first_opened_at, last_opened_at, IP, user_agent), ProcedureReadEvent (log eventi opened/confirmed/reminder_sent/reassigned/exported) |

**Relazioni inter-app principali:**

- `tickets.Ticket` Ã¢â€ â€™ `assets.Asset` (FK), `anagrafica.Fornitore` (FK)
- `assets.WorkOrder` Ã¢â€ â€™ `anagrafica.Fornitore` (FK), `assets.PeriodicVerification` (FK)
- `assets.PeriodicVerification` Ã¢â€ â€™ `anagrafica.Fornitore` (FK), `assets.Asset` (M:M)
- `assets.FornitoreAsset` Ã¢â€ â€™ `assets.Asset` (FK), `anagrafica.Fornitore` (FK)

---

## Infrastruttura server (NON riproducibile in dev)

Questi componenti esistono solo sul server di produzione:

- Tabelle legacy SQL Server: `utenti`, `ruoli`, `pulsanti`, `permessi`, `anagrafica_dipendenti` Ã¢â‚¬â€ DDL non nel repo, migration Django `0029_legacy_managed` presente ma applicata con `--fake` (tabelle preesistenti)
- Trigger SQL Server per assenze (`sql/`): `trg_assenze_automation_after_insert`, `trg_assenze_automation_after_update`
- Tabella `automation_event_queue` (`sql/automation_event_queue.sql`)
- SharePoint/Graph data (credenziali `GRAPH_*` nel `.env`)
- `media/fotocard`, `media/timbri`, `media/firme`
- `django_app/.env` runtime (solo `.example` nel repo)

---

## Automazioni

- Designer visuale Ã¢â€ â€™ regole salvate su DB Ã¢â€ â€™ trigger SQL Server Ã¢â€ â€™ inserimento in `automation_event_queue`
- Management command: `python manage.py process_automation_queue`
- File principali: `automazioni/models.py`, `automazioni/views.py`, `sql/`

---

## Audit Trail

- Funzione: `core/audit.py` Ã¢â€ â€™ `log_action(request, azione, modulo, dettaglio)`
- Scrive su `core.models.AuditLog` (tabella Django, con migration)
- Fire-and-forget: gli errori DB sono loggati ma non propagati alla view
- Traccia automaticamente se l'azione ÃƒÂ¨ eseguita in impersonation (aggiunge `_impersonation` nel payload)
- App che giÃƒÂ  usano audit log: `admin_portale`, `anomalie`, `assenze`, `assets`, `core`
- **Da usare** per ogni operazione CRUD rilevante (creazione/modifica/cancellazione di entitÃƒÂ )

---

## URL routing

### `legacy_admin_required` su endpoint API/AJAX

- File: `django_app/admin_portale/decorators.py`
- Per pagine HTML mantiene il comportamento storico: redirect a login se l'utente non e autenticato, pagina `403` se e autenticato ma non admin legacy.
- Per richieste API/AJAX (`/api/`, `Accept: application/json`, `Content-Type: application/json`, `X-Requested-With: XMLHttpRequest`) deve restituire JSON esplicito:
  - `401` con `{ok: false, reason: "unauthenticated", ...}`
  - `403` con `{ok: false, reason: "forbidden", ...}`
- Motivo: evitare errori frontend tipo `Unexpected token '<'` quando il browser prova a fare `response.json()` su una pagina HTML di login/forbidden.
- La stessa regola vale anche per `django_app/core/middleware.py` (`ACLMiddleware`): gli endpoint protetti non devono fare redirect/render HTML se la richiesta e API/AJAX.
- I template/admin page che consumano API JSON devono passare da `window.portalReadJsonResponse(...)` (definito in `django_app/core/templates/core/base.html`) invece di chiamare `response.json()` direttamente, cosi `401/403`, payload `{ok:false}` e HTML inatteso vengono trasformati in errori gestibili con messaggi utente leggibili.

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

### Confine dashboard / moduli

- `dashboard` deve restare una superficie KPI/launcher, non il contenitore dei workflow di dominio.
- La dashboard principale vive in `dashboard` come workspace personale: widget KPI multi-modulo, layout utente e template iniziale globale gestito dagli admin. `scheda-dipendente` resta solo come alias compatibile.
- Per `assenze`, il punto di ingresso canonico e il modulo `/assenze/`: menu, nuova richiesta, gestione personale, calendario e certificazione presenza.
- Eventuali route legacy o compatibilita (es. `/richieste`, alias `coming_assenze`) devono puntare al modulo `assenze`, non duplicarne le pagine dentro `dashboard`.

---

## Logging

- File log in `django_app/logs/`: `app.log`, `app-{hostname}.log`, `sql.log`
- Handler custom `SafeTimedRotatingFileHandler` in `core/logging_handlers.py` (rotazione giornaliera, safe per multi-process)
- SQL logging configurabile via env `SQL_LOG_ENABLED` e `SQL_LOG_LEVEL`
- In produzione non usare `print()` Ã¢â‚¬â€ usare sempre `logging.getLogger(__name__)`

---

## Compatibility layer Flask

- `core/legacy_flask_views.py`: 62 route Flask coperte (27 native, 35 redirect/410)
- Non modificare senza capire prima quale route Flask copre

---

## Debito tecnico noto (non toccare senza discussione)

1. SQL raw inline in `core/context_processors.py` e alcune views
2. Cache Graph primitiva (`Lock + dict`) Ã¢â‚¬â€ non sicura su multi-process (wsgi multi-worker)
3. `planimetria/models.py` ÃƒÂ¨ vuoto (solo commento) Ã¢â‚¬â€ non aggiungere logica
4. `module_registry.py`: solo `assets` registrato, gli altri moduli non sono brandizzabili

---

## Cache in produzione (IIS multi-worker)

Con 2+ worker IIS usare `DatabaseCache` (SQL Server) Ã¢â‚¬â€ condivisa tra processi:

- Configurata automaticamente da `config/settings/prod.py`
- **Setup una-tantum dopo ogni deploy su server vergine:** `python manage.py createcachetable`
- Tabella: `django_cache` (override con env `DJANGO_CACHE_TABLE`)
- `bump_legacy_cache_version()` usa `cache.incr()` atomico Ã¢â€ â€™ invalidazione ACL immediata su tutti i worker
- Dev usa `LocMemCache` (default Django) Ã¢â‚¬â€ nessuna configurazione aggiuntiva

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

**Requisiti sistema:** Python 3.11+, SQL Server con schema legacy popolato, un driver ODBC SQL Server installato (`18`, `17`, `13`, `SQL Server Native Client 11.0` o `SQL Server`).

---

## File sensibili nel repo (da non esporre)

- `django_app/.env` Ã¢â‚¬â€ credenziali AD, IP di rete, SECRET_KEY
- `DIPENDENTI.csv` Ã¢â‚¬â€ dati reali dipendenti
- `db.sqlite3` Ã¢â‚¬â€ DB locale con dati di test
- `build/` e `dist/` Ã¢â‚¬â€ contengono `asta.exe` e `utenti.db`



