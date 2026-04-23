# CLAUDE.md - Portale Novicrom

Documento di contesto per AI coding assistant. Aggiornato continuamente con il progetto.
Versione app corrente: **1.0.1** (2026-04-22)

---

## Stack tecnico

- **Backend:** Django 5.2, Python 3.11+
- **WSGI IIS:** Waitress tramite HttpPlatformHandler (dipendenza runtime dichiarata in `django_app/requirements.txt`)
- **Database prod:** SQL Server (mssql-django 1.6, pyodbc 5.2)
- **Database dev:** SQLite (solo per sviluppo Django-only, senza tabelle legacy)
- **Auth:** 4 backend in cascata - `AxesStandaloneBackend` -> `SQLServerLegacyBackend` -> `LDAPBackend` (AD `cnovicrom.local`) -> `ModelBackend`
- **Frontend:** SSR puro con Django templates, nessun framework JS, CSS custom
- **Layout shared:** `core/base.html` + `core/static/core/css/theme.css` fungono da shell viewport-aware; i root wrapper di modulo/dashboard devono riempire l'altezza disponibile ed evitare sidebar/grid con `align-self: start` o `align-items: start` se questo crea vuoti verticali visibili
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
| `assenze` | Modulo unificato assenze: richieste, gestione, calendario, certificazioni + sync SharePoint; il submit locale risolve `capo_reparto_id` verso la FK reale `capi_reparto.id` (non `utenti.id`), cosi email e lookup SharePoint del form non generano piu conflitti FK su SQL Server |
| `anomalie` | Segnalazione e gestione anomalie produzione |
| `assets` | Gestione asset aziendali (macchinari, attrezzature) + scadenzari manutenzioni/scadenze con creazione eventi Outlook sul calendario dell'utente selezionato; la manutenzione periodica vive come categoria della manutenzione su `/assets/manutenzione/verifiche/` con redirect legacy da `/assets/verifiche-periodiche/`; dashboard KPI personalizzabile per utente su `/assets/dashboard/` con 12 widget (scadenze, OdL, verifiche, ripartizioni) e drag & drop; la lista inventario canonica vive su `/assets/lista/` e i vecchi link filtrati `/assets/?asset_type=...` vengono riallineati automaticamente; licenze software su `/assets/licenze/` assegnabili ad asset o dipendenti anagrafica; categorie asset e campi dinamici si gestiscono nella tab `Categorie asset` di `/assets/impostazioni/`, con rimando rapido anche dallo Studio amministratore inventario |
| `tasks` | `KICK-OFF`: portfolio kickoff, attivita kickoff, subtask, commenti, allegati, import Excel e upload documento MOD.073 VRF |
| `automazioni` | Designer visuale automazioni + workspace flow split-view + SQL trigger -> event queue; il modulo e trattato come **audience admin** nel module registry (entrypoint operativo in `/admin-portale/automazioni/`), mentre gli endpoint token-based `/automazioni/approvazione/*` e `/approval-actions/*` restano esenti da ACL. La queue admin in `/admin-portale/automazioni/queue/` espone le azioni manuali `Stoppa` (porta un evento `pending` in `error` senza eseguirlo) ed `Elimina` (solo per eventi `pending/error` senza run log collegati), oltre a una card salute del poller che mostra task Windows locale `Portale Hub Polling Mail`, ultimo job monitorato e log `django_app/logs/automation_queue.log`; i timestamp della card vengono normalizzati nella timezone corrente del progetto (default `Europe/Rome`) e la UI espone il fuso usato; il polling Graph delle reply approvative processa ora i messaggi in ordine cronologico crescente (`first valid decision wins`), valida sempre il mittente in fail-closed, deduplica in modo persistente su `internet_message_id` e marca come lette solo le reply terminali/non riprocessabili; nel designer condizioni `expected_value` espone anche `Valori disponibili` con picker generico da source registry/DB e il pannello destro resta scrollabile in autonomia |
| `admin_portale` | Pannello admin custom (non Django admin); la pagina `/admin-portale/crea-release/` crea il package zip e include `Operazioni server` per selezionare TEST/PROD, avviare automaticamente il task schedulato elevato `\PortaleNovicrom\IISRestart_TEST/PROD` per riavviare sito/App Pool IIS e lanciare comandi terminale nel virtualenv dell'ambiente scelto; se il task non e' disponibile resta il fallback diretto IIS/processo Django |
| `anagrafica` | Anagrafica dipendenti (integrata con AD/legacy DB, fallback automatico `email_notifica` -> `email` quando il dato legacy manca) |
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

Pattern condiviso pagine modulo `Impostazioni`:
- ogni modulo mantiene una propria pagina dedicata, non esiste una pagina impostazioni centralizzata unica
- i percorsi canonici sono `/diario-preposto/impostazioni/`, `/rilevazione-incidenti/impostazioni/`, `/timbri/impostazioni/`, `/rentri/impostazioni/`, `/assenze/impostazioni/`, `/notizie/impostazioni/`, `/procedure-refresh/impostazioni/`, `/tasks/impostazioni/`, `/assets/impostazioni/`
- gli URL legacy tipo `gestione`, `configurazione`, `admin` restano compatibili tramite redirect quando esistevano gia
- nel modulo `tasks` la pagina canonica `/tasks/impostazioni/` include le tab amministrative `Configurazione`, `Riepilogo`, `Ruoli operativi` (catalogo ruoli operativo estendibile + matrice utenti x ruolo; PM/CC/PRG restano ruoli di sistema e filtrano i dropdown kickoff), `Accessi` (regole per ruolo operativo + override per singolo utente), `Promemoria` (gestione `TaskReminder` con azioni Elimina/Rimanda/Invia ora), `Record` e `Log attivita`; il vecchio `/tasks/gestione/` reindirizza alla tab `Riepilogo`
- il branding modulo usa `module_branding.<module>.display_label` e `module_branding.<module>.logo_url` in `SiteConfig`; se presenti, nome e logo possono apparire nelle hero, nelle shell modulo e nei link amministrativi
- nel modulo `assets` la configurazione categorie/campi dinamici vive nella tab `Categorie asset` della pagina `Impostazioni`; lo Studio amministratore in `/assets/lista/` mantiene solo un rimando rapido per compatibilita e discoverability
- nel modulo `tasks` (branding utente `KICK-OFF`) il kickoff coincide con il progetto e per i nuovi record riceve nome automatico `KICK-OFF <n>` tramite `kickoff_number`; `VRF` indica solo il documento Excel MOD.073. La creazione di un nuovo kickoff vive sul percorso dedicato a 3 step `/tasks/projects/new/` (anagrafica) -> `/tasks/projects/<id>/vrf/compile/` (matrice rischi) -> `/tasks/projects/<id>/gantt/` (empty-state con CTA `Aggiungi prima attivita'`). Il form `Nuova attivita'`/`Modifica attivita'` in `/tasks/new/` richiede sempre un kickoff **esistente**: la UI non mostra piu' il ramo "Nuovo kickoff inline" ma rimanda al flusso dedicato con un banner CTA (il backend `TaskForm` mantiene il ramo `project_link_mode=new` solo per retrocompat dei test). Per i kickoff esistenti il form mostra option label `nome | P/N | Rev | Ver | Cliente` e riusa automaticamente un kickoff gia accessibile con stessa identita `part_number + revisione + versione`, evitando duplicati (stessa logica di matching replicata in `ProjectKickoffForm`). `Revisione` e `Versione` non sono valide senza `P/N`. La lista kickoff espone anche le azioni `Copia kickoff e VRF` e `Copia kickoff e VRF tranne P/N`. CTA primari del portfolio: `+ Nuovo kickoff` (flow guidato) e `+ Nuova attivita` (attivita' singola o agganciata a kickoff esistente)
- **Accessi task kickoff**: la visibilita operativa dei task parte sempre dallo scope diretto storico (creator, assegnatario, subscriber, progetto creato dall'utente) e puo essere estesa da `/tasks/impostazioni/?tab=accessi`. Le regole per i ruoli di sistema PM/CC/PRG valgono sui kickoff dove l'utente e' indicato come `project_manager`, `capo_commessa` o `programmer`; le regole per ruoli custom valgono sui task il cui `TaskCategory.role_type` e' associato a quel ruolo. Gli override utente valgono globalmente sul modulo. Livelli disponibili: `Nessun accesso extra`, `Vede tutto`, `Vede tutto + modifica solo task assegnati`, `Vede e modifica tutto`. Le azioni Gantt/drag/quick edit, copia kickoff e gestione VRF usano queste regole tramite `_can_manage_task()` / `_can_manage_project()`.
- **Accessi gestione anomalie**: la pagina `/gestione-anomalie/configurazione?tab=accessi` replica il modello ruoli/override del KICK-OFF per il modulo anomalie. Il permesso pagina/ACL resta la prima barriera; le regole anomalie decidono cosa si puo modificare dentro il modulo. I ruoli di sistema `Capocommessa` e `CAR / Incaricato` sono risolti dai campi dell'OP (`ordini_produzione.capocomessa`, `ordini_produzione.incaricato`) e di default possono modificare gli OP in carico (`EDIT_ASSIGNED`). I ruoli custom assegnati nella tab `Ruoli operativi`, i ruoli aziendali legacy (`ruoli.id` collegato a `utenti.ruolo_id`) e gli override utente valgono globalmente. La tab sincronizza gli utenti attivi da `utenti` verso `auth_user`/`Profile` quando manca lo specchio Django.
- **VRF upload workflow**: alla creazione di un nuovo kickoff, il sistema reindirizza a `/tasks/projects/<id>/vrf/` per caricare il documento MOD.073. La view `project_vrf_upload` analizza il file .xlsx con `openpyxl` (celle fisse: B3=P/N, I3=Descrizione, P3=Esp, O2=Preventivo n°, P2=Versione, B4=Cliente) e mostra un'anteprima prima del commit. Il blocco progressivo e gestito da `_vrf_status_detail()`: `PENDING` diventa warning dopo `vrf_reminder_days` giorni (default 7) e bloccante dopo `vrf_blocking_days` giorni (default 30); questi parametri si configurano in `TaskImpostazioni` dalla tab `Configurazione` di `/tasks/impostazioni/`. Il blocco impedisce creazione e modifica di VRF tramite guard in `task_create` e `task_edit`. `VRFDocStatus` ha tre stati: `PENDING` / `UPLOADED` / `NOT_REQUIRED`. Il portfolio espone una colonna "Documento" con badge colorato per stato. Tutte le azioni (carica, conferma, salta, non richiesto) sono tracciate in AuditLog
- **Calendario Outlook + promemoria portale per task kickoff**: il form `Nuova/Modifica attivita'` espone sezione **Promemoria** con checkbox `add_to_outlook` (opt-in) + `outlook_target_email` (override, default email assegnatario) e `reminder_portal_enabled_field` (opt-out, default attivo). Al save la funzione `_sync_task_integrations()` richiama `tasks/outlook_reminder.py::sync_task_outlook_event()` (che usa l'helper generico `core/outlook_calendar.py` via Microsoft Graph) per creare/aggiornare/eliminare l'evento sul calendario dell'utente target con reminder 15 min prima. Tracking dedup via `TaskCalendarEvent` (1:N col Task, `source_key=tasks.task:<id>:due`). Il promemoria portale viene schedulato come record `TaskReminder` con `fire_at = due_date - TaskImpostazioni.giorni_preavviso` e materializzato come `core.Notifica` dal comando `python manage.py send_task_reminders` (schedulare come task Windows quotidiano, es. 07:30). Errori Graph non bloccanti (warning, task resta salvato).
- **VRF compilazione online (MOD.073 Rev.10)**: in alternativa all'upload, la pagina `/tasks/projects/<id>/vrf/compile/` permette di compilare l'intera matrice rischi nel browser (9 rischi, 45 sub-parametri, 3 fasi Preventivazione/Industrializzazione/Produzione) con ricalcolo live di medie, `K x R` e TR per fase, highlight della soglia DIG >= 46. Il catalogo rischi e la mappatura celle sono centralizzati in `tasks/vrf_catalog.py`; il generatore `tasks/vrf_generator.py::build_vrf_xlsx()` apre il template distribuito in `tasks/vrf_template/MOD_073_VRF_Rev10.xlsx` e scrive i punteggi sulle celle canoniche preservando formule e formattazione del foglio originale. Il payload e cache dei totali vivono su `VRFRiskAssessment` (OneToOne con `Project`, `data` JSON). Azioni POST: `save_draft` (persiste bozza) e `confirm` (genera xlsx, salva su `Project.vrf_file`, marca `UPLOADED`). Endpoint `/vrf/download/` riscarica l'ultimo file o lo rigenera dal draft. AuditLog: `vrf_compiled_draft`, `vrf_compiled_inline`. Il CTA "Compila online" e primario nella pagina `/vrf/` accanto al classico upload file
- **Deploy promote / automazioni SQL**: `collectstatic` in prod usa `ManifestStaticFilesStorage`, quindi i file statici versionati non devono contenere riferimenti a sourcemap mancanti (es. `//# sourceMappingURL=...`). Il command `apply_sql_triggers` deve supportare sia `CREATE TRIGGER` sia `CREATE OR ALTER TRIGGER`, eseguire script multi-batch con `GO`, e i trigger queue devono scrivere sullo schema corrente `automation_event_queue` (`source_code`, `source_table`, `source_pk`, `operation_type`, `event_code`, `watched_field`, `payload_json`, `old_payload_json`, `status`, `created_at`) invece del legacy `item_id`. Prima di creare ogni trigger deve verificare la tabella target dichiarata in `ON dbo.<tabella>`: se la tabella legacy/opzionale non esiste (es. `dbo.assenze` in un DB TEST pulito), il trigger va marcato `[SKIP]` senza bloccare il deploy. Gli script SQL per sorgenti legacy opzionali devono essere self-guarded (`IF OBJECT_ID(...) IS NULL PRINT/SKIP ELSE EXEC sys.sp_executesql N'CREATE OR ALTER TRIGGER...'`) per evitare errore SQL Server 8197 anche quando lo script viene eseguito fuori dal command Django.

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
- `resolve_canonical_target()` privilegia ora il binding path piu specifico a parita di priorita e, se riceve solo `route_name`, prova anche `reverse(route_name)` per risolvere correttamente i binding path-only.
- Compat routing operativo: la landing `/anomalie-menu` resta una pagina contenitore/launcher; se il ruolo ha almeno un permesso operativo del modulo anomalie (`anomalie_aperte` o `inserimento_anomalie`), il resolver puo consentire l'accesso anche quando il grant canonico del contenitore `legacy.dashboard.dashboard_anomalie_menu` e assente o negato.

### 2. ACL Legacy (fallback compatibilita)

- File: `core/acl.py`
- Pipeline storica: `path -> _match_pulsante() -> modulo+azione -> perm_map per ruolo_id -> 403/pass`
- Stato attuale runtime: `core/acl.py` e sempre piu una **facade compat** sopra il canonico. Se una route/path o un `legacy.<modulo>.<azione>` hanno gia un permission code canonico registrato, la decisione passa prima da `PermissionDefinition` / `RolePermissionGrant` / `UserPermissionGrant`; il legacy resta come fallback solo per superfici ancora non migrate.
- Diagnostica legacy dettagliata: `diagnose_permesso_for_context()`
- Tabelle SQL Server legacy: `utenti`, `ruoli`, `pulsanti`, `permessi`, `anagrafica_dipendenti`
- Modelli in `core/legacy_models.py` â€” `Ruolo`, `UtenteLegacy`, `Pulsante`, `Permesso`, `AnagraficaDipendente` â€” `managed=True` (app_label="core"), migration `0029_legacy_managed` fake su SQL Server esistente.
- Cache ACL legacy: `core/legacy_cache.py` + `bump_legacy_cache_version()`.

### 3. Navigation Registry (visibilita menu, non sicurezza)

- File: `core/navigation_registry.py`
- Tabelle Django: `NavigationItem`, `NavigationRoleAccess`, `UserNavigationOverride`, `UserDashboardConfig`, `UserModuleVisibility`
- `NavigationItem` espone ora anche `required_permission_code`: se compilato, o se ricavabile da `route_name` / `url_path`, la visibilita della voce viene derivata dai grant canonici del ruolo/utente.
- Runtime attuale: `RolePermissionGrant` / `UserPermissionGrant` sono la fonte primaria di visibilita menu; `NavigationRoleAccess` sopravvive solo come fallback compat per voci ancora prive di permission code canonico.
- Quando il Navigation Registry e' vuoto/disattivato e la shell cade sul fallback legacy `pulsanti`, `core.context_processors.legacy_nav()` deve deduplicare la navigazione principale per modulo prima di renderizzare topbar/sidebar. Le tabelle legacy possono contenere piu azioni dello stesso modulo (`lista`, `crea`, `gestione`) ma il menu principale deve mostrare una sola voce modulo, specialmente dopo restore/import topbar.
- **Override per-utente navigazione** (`UserNavigationOverride`): in runtime e hide-only. `enabled=False` nasconde una voce gia consentita; i vecchi override positivi (`enabled=True`) non forzano piu la mostra di voci negate dal canonico. Non usa la cache; gli admin non sono soggetti agli override. Funziona su `topbar` e `subnav`. Gestito da "Step 5 â€“ Nav Override" in `/admin-portale/acl-canonico/` e da "Override Navigazione Utente" in `/admin-portale/navigation-builder/`.

#### Sezioni `NavigationItem.section`

| Valore | Dove viene renderizzata | ACL |
| --- | --- | --- |
| `topbar` | Barra di navigazione principale (in cima) | permission code canonico -> fallback `NavigationRoleAccess` solo se unmapped |
| `subnav` | Barra secondaria per modulo (filtrata per `parent_code`) | permission code canonico -> fallback `NavigationRoleAccess` solo se unmapped |
| `sidebar` | Menu laterale (modalita sidebar) | permission code canonico -> fallback `NavigationRoleAccess` solo se unmapped |
| `page` | Dentro una pagina specifica | permission code canonico -> fallback `NavigationRoleAccess` solo se unmapped |
| `admin_subnav` | Barra interna dell'admin portale (`/admin-portale/`) | **Nessuna ACL** â€” area gia gated da `@legacy_admin_required` |

**`admin_subnav` â€” regola critica:** NON hardcodare mai voci in `admin_subnav.html`. Gestire sempre tramite `NavigationItem` con `section="admin_subnav"` via Navigation Builder o migration. Migration seed: `core/migrations/0031_admin_subnav_seed.py` + `0032_admin_subnav_acl_nav_map.py` (voce aggiuntiva mappa permessi/navigazione). Il context processor inietta `admin_subnav_items` solo per utenti `is_legacy_admin()`.

Navigation Builder (`/admin-portale/navigation-builder/`): oltre alla tabella inline include una **vista visuale drag&drop orizzontale** (scroll laterale) a colonne per sezione (`topbar`, `subnav`, `admin_subnav`, `sidebar`, `page`) con card trascinabili, spostamento cross-sezione e sincronizzazione immediata su `NavigationItem.section` + `NavigationItem.order` tramite `api_navigation_reorder`. Ogni card supporta azioni rapide `Apri`, `Clona`, `Rimuovi`; il listener globale dei click nel template deve restare `async` perchÃ© invoca fetch asincrone. Nota semantica: `topbar` rappresenta la navigazione principale e in `nav_mode=side` viene renderizzata nella sidebar. Nel builder `sidebar` e trattata come opzione avanzata (`Sidebar Dedicated`) e viene nascosta in modalita standard.

Rendering icone navigazione: `render_icon` supporta alias SVG semantici (`layout-dashboard`, `newspaper`, `scan`, `id-card`, `package`, `shield-check`, `file-check`, `key-round`, ecc.), immagini (`media:`/`static:`/URL) e fallback automatico da label per sostituire iniziali placeholder nella topbar/sidebar.

Sidebar nav side: i gruppi aperti devono restare visivamente distinti dal primo livello tramite pannello annidato, rientro e stato aperto evidente, senza rompere la leggibilita in modalita `sb-collapsed` o mobile.

### Strumenti diagnostica/gestione ACL (admin)

- `/admin-portale/accessi/`: entrypoint semplice predefinito per i permessi ruolo. Da Fase 3 e **canonico-first**: il toggle modulo scrive solo i `RolePermissionGrant`; legacy ACL e fallback navigation restano visibili come contesto/copertura ma non sono piu la fonte primaria del salvataggio.
- `/admin-portale/gestione-accessi/`: dettaglio storico legacy ruolo -> modulo -> azione.
- `/admin-portale/acl-canonico/`: gestione operativa del layer v2 (permission code, route/path binding, grant ruolo, override utente, override navigazione utente). Tab: 1. PermissionDefinition, 2. Route Binding, 3. Role Grant, 4. User Override, **5. Nav Override** (nuovo).
- `/admin-portale/acl-route-coverage/`: report route dedicato con stati `CANONICAL_BOUND`, `LEGACY_FALLBACK`, `UNBOUND`, `COMING_SOON_EXCLUDED`, `REDIRECT_ONLY` e export CSV.
- Il report `acl-route-coverage` usa il binding canonico effettivo (winner route/path) per permission e warning; le route decorate con `@legacy_admin_required` sono marcate `admin_bypass` e non vengono conteggiate come `missing_grant`.
- `/admin-portale/acl-diagnostica/` (alias compat legacy: `/admin-portale/acl/`): diagnostica combinata legacy + canonical con **una sola decisione finale** del resolver v2, trace esplicito e blocco legacy relegato a dettaglio secondario.
- `/admin-portale/mappa-permessi-navigazione/`: mappa unica route/menu con sorgente (`REGISTRY`/`LEGACY`), ruoli abilitati, override utente, admin bypass e redirect legacy. Ogni riga ha drill-down workflow visuale cliccabile; con filtro ruolo attivo supporta toggle live sia dei grant canonici v2 (`RolePermissionGrant.enabled`) sia dei permessi legacy (`can_view`) via API.

### Path esenti da ACL (MIDDLEWARE_EXEMPT_PREFIXES)

Questi path bypassano completamente l'`ACLMiddleware`:

```text
/health  /version  /login  /logout  /cambia-password
/static/  /media/  /admin/  /favicon  /setup/  /admin-portale/hub/
/automazioni/approvazione/   (token-based, no login required)
/approval-actions/           (token-based, Entra Application Proxy frontend)
```

Ogni nuova app che deve essere accessibile senza autenticazione va aggiunta a `MIDDLEWARE_EXEMPT_PREFIXES` in `config/settings/base.py`.

**`/approval-actions/` — Entra Application Proxy**: endpoint GET one-click (`/approval-actions/approve/<token>/` e `/approval-actions/reject/<token>/`) pensati per essere pubblicati selettivamente su Entra Application Proxy. Riusano `process_approval_decision()`. L'identità viene estratta da sessione Django → `X-MS-CLIENT-PRINCIPAL-NAME` → `X-Forwarded-Email`. Ogni decisione è tracciata in AuditLog. Pubblicare **solo** `/approval-actions/*` nell'Application Proxy, non l'intero `/automazioni/`. URL file: `automazioni/approval_proxy_urls.py`.

Path auth-only condivisi gestiti direttamente da `ACLMiddleware` (senza grant ACL dedicati):
- `/onboarding/` per tutti gli utenti autenticati non superuser interessati al primo accesso
- `/notifiche/` e `/api/notifiche/...` per tutti gli utenti autenticati, cosi il centro notifiche e il popup ack restano sempre disponibili indipendentemente dal ruolo

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
- Branding globale portale: chiavi `portal_name`, `portal_subtitle`, `brand_logo_full`, `brand_logo_compact`, `brand_favicon`, `brand_primary_color`, `brand_accent_color`, `brand_background_color`; si gestiscono da `/admin-portale/hub/categorie/`, con upload validato MIME in `media/portal_branding/` o fallback via URL assoluto/relativo.
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

1. `CLAUDE.md` riga 4 — `Versione app corrente: **X.Y.Z** (YYYY-MM-DD)`
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
| `setup-wizard/` | `setup_wizard_hub` | Riesecuzione wizard configurazione (12 step), legge `.env` corrente normalizzando i booleani e preservando `DB_TRUST_CERT` durante modifiche LDAP/SMTP. |
| `guide/` | `guide_list` | Elenco guide/manuali/documentazione tecnica indicizzato automaticamente da `tools/`, `doc/`, `deployment/` e `django_app/assets/README.md` con deduplica per formato (`html` > `pdf` > `md`). |
| `guide/<slug>/` | `guide_view` | Visualizzazione singola guida. |
| `categorie/` | `categorie` | Categorie moduli/topbar e branding globale portale: nome, sottotitolo, upload o URL per logo sidebar espansa/compatta, favicon e colori shell/accento/sfondo. Gli upload finiscono in `media/portal_branding/`. |

### Guide Hub

- `/admin-portale/hub/guide/` non usa piu un catalogo hardcoded: scopre automaticamente i documenti supportati (`.html`, `.pdf`, `.md`) nelle directory sorgente del progetto dedicate alla documentazione.
- `guide_serve` risolve i documenti per `slug` (con fallback legacy sul filename), serve `html` e `pdf` nativamente e incapsula i `md` in un viewer HTML integrato per mantenerli consultabili anche dentro l'iframe dell'Hub.
- La vista singola guida usa CTA topbar compatti (`Nuova scheda`, `Lista guide`) per non sottrarre spazio verticale/orizzontale al documento.
- Se una guida porta un'icona con encoding corrotto (mojibake tipo `ðŸ...`), il catalogo la deve omettere del tutto invece di mostrare caratteri rotti davanti al titolo.

### Schema DB Ã¢â‚¬â€ riepilogo modelli per app

| App | Modelli | Note |
| --- | --- | --- |
| `core` | 23 | Profile, NavigationItem, NavigationRoleAccess, AuditLog, SiteConfig, Notifica, UserExtraInfo, Checklist*, AnagraficaVoce/Risposta, Dashboard configs, RepartoCapoMapping, OptioneConfig, LoginBanner, LegacyRedirect, NavigationSnapshot, UserOnboarding |
| `core` (legacy, ex-unmanaged) | +5 | Ruolo, UtenteLegacy, AnagraficaDipendente, Pulsante, Permesso Ã¢â‚¬â€ ora `managed=True` sotto `core`, migration 0029 faked |
| `assets` | 27 | Asset, AssetCategory, AssetITDetails, WorkMachine, WorkOrder, WorkOrderAttachment/Log, PeriodicVerification, SoftwareLicense, AssetEndpoint, PlantLayout/Area/Marker, AssetDocument, AssetLabelTemplate, AssetDashboardConfig (config widget dashboard per utente) + modelli config UI |
| `tasks` | 11 | Project (+ `kickoff_number`, `revisione`, `versione`, `vrf_status`, `vrf_file`, `vrf_original_name`, `vrf_uploaded_at`, `vrf_quote_number`, `vrf_description`, `vrf_esp`), Task, SubTask, TaskComment, ProjectComment, TaskEvent, TaskAttachment, VRFRiskAssessment (1:1 con Project, payload JSON matrice rischi MOD.073 Rev.10 + cache totali TR per fase), TaskRoleDefinition, TaskRoleAccessRule, TaskUserAccessRule; `TaskImpostazioni` singleton con `vrf_reminder_days` e `vrf_blocking_days` |
| `automazioni` | 9 | AutomationRule, AutomationCondition, AutomationAction, AutomationRunLog, AutomationActionLog, DashboardMetricValue, AutomationApproval, TeamsWebhookPreset, AutomationDeliveryEndpoint |
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
- Tabella `automation_event_queue` (`sql/automation_event_queue.sql`) con riallineamento idempotente delle colonne nuove (es. `execute_after`) senza ricreazione della tabella
- SharePoint/Graph data (credenziali `GRAPH_*` nel `.env`)
- `media/fotocard`, `media/timbri`, `media/firme`
- `django_app/.env` runtime (solo `.example` nel repo)

---

## Automazioni

- Designer visuale Ã¢â€ â€™ regole salvate su DB Ã¢â€ â€™ trigger SQL Server Ã¢â€ â€™ inserimento in `automation_event_queue`
- Management command: `python manage.py process_automation_queue`
- File principali: `automazioni/models.py`, `automazioni/views.py`, `sql/`
- I task Windows che schedulano `process_automation_queue` devono usare un runner silent/hidden, senza lanciare finestre `cmd.exe` visibili a ogni minuto, ma continuando a scrivere su `automation_queue.log`.
- Compatibilita schema queue: il fetch degli eventi `pending` deve degradare se `dbo.automation_event_queue` non ha ancora `execute_after`, cosi le regole `insert/update` continuano a funzionare; le azioni che schedulano eventi futuri devono invece restituire un errore funzionale chiaro finche il DDL non viene riallineato
- Sorgente `assenze`: l'enrichment runtime di `capo_email` deve risolvere prima `capo_reparto_id` come FK locale `capi_reparto.id` leggendo `indirizzo_email` (e in fallback `utente_id`), non come `utenti.id`; solo dopo sono ammessi i fallback legacy/sharepoint
- Builder classico e designer visuale devono passare cataloghi sorgente e preset al frontend come oggetti Python via `json_script`; non usare `json.dumps` sui valori gia destinati a `json_script`, altrimenti i dropdown trigger/condizioni restano fermi sulla sorgente iniziale.
- Designer visuale e pagina test espongono ora un browser campi smart con ricerca, filtri per ambito (`trigger`, `condition`, `template`, `action_mapping`) e inserimento contestuale nel target attivo (select, template o JSON raw).
- Il `source_registry` puo dichiarare per ogni campo metadata UI come `allowed_values`, `value_source_label` e `ui_control`; il designer condizioni deve riusarli per mostrare accanto a `expected_value` il riquadro `Valori disponibili` e, per i campi mappati a colonna fisica, completarlo via endpoint `/admin-portale/automazioni/api/sorgenti/<source>/campi/<field>/valori/` con valori distinti reali dal DB. Il comportamento deve restare generico per qualsiasi campo queryable, non hardcoded a `tipo_assenza`; per `assenze.tipo_assenza` i valori canonici vanno condivisi con il modulo assenze, non duplicati in JS/template.
- Il pannello laterale `Contenuti / Colonne disponibili` del designer deve restare sticky e con scroll autonomo rispetto alla pagina, anche nella workspace del diagramma, per evitare di perdere il contesto mentre si cercano campi o si compongono condizioni/template/mapping.
- La pagina test manuale usa un composer guidato per `payload_json` e `old_payload_json`, sincronizzato con i textarea raw e con diff sintetico dei campi cambiati.
- Le sorgenti che in update aggiungono campi runtime `old_*` direttamente nel payload (es. `tickets`, `tasks`) devono dichiararli nel `source_registry` come campi virtuali per renderli disponibili a catalogo, preset, test e template.
- Il converter Power Automate integrato vive su `admin_portale:automazioni_rule_power_automate_convert`: riusa i servizi della cartella spostata `django_app/powerautomate-to-django-automations/app` tramite `automazioni/power_automate_bridge.py`, non tramite una seconda webapp standalone.
- La pagina `Converti Power Automate` deve restare agganciata al workflow SSR di `Importa Package`: upload `.zip/.json`, analisi, remediation opzionale, diagramma del flow originale, download package e handoff diretto alla sessione di import esistente. Se una singola regola e' gia importabile, il converter puo' anche creare una bozza draft/disattiva e aprirla subito nel designer visuale. Non creare un importer parallelo.
- La tabella target nel converter integrato e' opzionale e va popolata dal catalogo tabelle del portale (`discover_module_tables()`), non dal vecchio wizard SQL Server standalone. Se manca il target, il package deve restare convertibile per il solo runtime portale.
- Per i flow con approval, il converter deve mostrare un selettore di `ApprovalEmailTemplate` attivi, con default sul primo `hybrid` e fallback sul primo `mail_reply`; il package deve salvare il riferimento portabile `approval_email_template_code` e una sezione top-level `approval_conversion`, non dipendere dal solo PK locale.
- La conversione automatica approval e' consentita solo per source noti/non `generic` e solo sul subset sicuro dei branch (`send_email`, `write_log`, `update_trigger_record`). I branch non mappabili restano in `issues`/`warnings`; per `assenze` il converter deve generare un vero `send_approval` e prependere `moderation_status=0/1` nei rami approvato/rifiutato.
- Il designer visuale espone un **test live inline** nel pannello laterale: modalita "Dati campione" e "Record reale" (AJAX picker ultimi 20 record), esecuzione via `POST /api/regole/<id>/test-ajax/` con risultati azione per azione. Endpoint aggiuntivi: `GET /api/sorgenti/<code>/record-recenti/` e `GET /api/sorgenti/<code>/record/<id>/payload/`.
- Nel designer visuale, `branch`, `do_until` e `for_each` non devono presentarsi come editor solo-JSON per il caso d'uso normale: servono pannelli guidati leggibili (`Se Vero/Se Falso`, `Corpo loop/Se completato/Se timeout`, `Azioni per ogni record`) con badge di stato, lista delle azioni inline e quick actions. Il JSON embedded in `config_json` resta il formato canonico, ma va relegato a `JSON avanzato` come fallback esperto senza rompere import/export o riapertura draft.
- Le card azione `send_email` hanno un pulsante "Anteprima" che mostra un pannello email renderizzato live (Da/A/Oggetto/Corpo) con highlight automatico dei `{placeholder}`, aggiornato su ogni keystroke senza submit.
- **Azioni di controllo flusso** (migration 0008): `send_approval`, `do_until`, `for_each`, `branch` — tutte con azioni figlie embedded in `config_json` come lista `[{action_type, config_json, description}]`.
  - `send_approval`: pausa il flusso, crea `AutomationApproval`, lascia il run log in `waiting_approval` e mantiene `process_approval_decision()` come source of truth per i rami `approved_actions` / `rejected_actions`. URL decision classici: `/automazioni/approvazione/<token>/approva|rifiuta/` (no login, token-based, `@csrf_exempt`). URL proxy Entra: `/approval-actions/approve|reject/<token>/` (GET one-click, vedi sezione `MIDDLEWARE_EXEMPT_PREFIXES`).
  - `send_approval` supporta `delivery_mode` configurabile in `config_json`: `email`, `teams_webhook_legacy`, `teams_chat_flow`, `email_and_teams_chat_flow`.
  - `teams_webhook_legacy`: mantiene il comportamento storico con `MessageCard` verso webhook di canale Teams; l'endpoint decision rileva POST JSON (chiamate Teams) e risponde con header `CARD-ACTION-STATUS` invece di HTML.
  - `teams_chat_flow`: renderizza `teams_recipient_email_template`, costruisce payload JSON (`approval_id`, `token`, `recipient_email`, `subject`, `message`, `approve_url`, `reject_url`, `expires_at`, `facts`) e invia una `POST` a un endpoint Power Automate / Teams Workflow. Teams recapita la card al singolo utente, ma la business logic resta nel portale: i pulsanti aprono sempre gli URL firmati del portale.
  - `email_and_teams_chat_flow`: recapita sia email sia flow Teams; per default email riuscita + Teams flow fallito produce warning nel `result_message` ma non fallisce l'azione, salvo `strict_teams_flow=true`.
  - `do_until`: esegue `loop_actions` ogni iterazione e si richiama tramite `_insert_loop_reschedule_event()`; esce quando la condizione (`check_field/operator/value`) è soddisfatta o si raggiunge `max_iterations`. Tiene il contatore in `payload._loop_iteration`.
  - `for_each`: interroga una sorgente registrata con filtro opzionale, esegue `each_actions` su ogni record (max `max_items`). Solo sorgenti con `table_name` definito nel registry; `filter_field` validato contro i campi esposti.
  - `branch`: valuta una condizione e esegue `if_true_actions` o `if_false_actions`. Simile a `run_if` ma con pieno ramo else.
- **Diagramma di flusso Power Automate-style**: bottone "🔀 Diagramma di flusso" nel designer visuale. Visualizzazione verticale con nodi colorati, connettori freccia, rami approvazione/branch, corpo loop do_until e iterazione for_each. Renderizzato lato client da `flow_nodes_json` iniettato nel contesto via `_build_flow_nodes()` in `views.py`. Pulsante "Modifica ↓" su ogni nodo scrolla al form corrispondente.
- Il modal del diagramma "Aggiungi azione al flusso" deve renderizzare le card azione gia' lato server e usare la stessa lista serializzata anche nel JS del diagramma; non affidare il picker a un popolamento solo client-side. Inoltre il CSS del modal deve rispettare esplicitamente `[hidden]`, altrimenti puo comparire da solo al load o non sparire davvero in chiusura.
- Nel diagramma, l'editing inline delle azioni deve riusare la card reale del formset invece di creare un secondo editor separato: in questo modo il salvataggio resta SSR, non si sdoppiano gli stati dei campi e il nodo puo' riallinearsi live con preview, titolo e stato della card.
- L'apertura del diagramma deve comportarsi come una workspace split-view stile Power Automate: overlay full-viewport, inspector fisso a sinistra, canvas a destra, `body` bloccato finche' la workspace e' aperta, chiusura con backdrop/Esc e scorciatoie che rimandano alle sezioni `trigger-section`, `conditions-section` e `actions-section` nel form SSR sottostante.
- `AutomationApproval` (migration 0008): token UUID univoco, approver_emails, approved/rejected_actions, status `pending/approved/rejected/expired`, expires_at, decided_by_email. Path `/automazioni/approvazione/` esente da ACL (`MIDDLEWARE_EXEMPT_PREFIXES`).
- `TeamsWebhookPreset` (migration 0009): webhook URL legacy riutilizzabile con nome, descrizione, is_active. Gestito su `/automazioni/canali-teams/`. Il campo `teams_preset_id` in `config_json` di `send_approval` fa lookup del URL da DB; fallback su `teams_webhook_url` raw (retrocompat). I fatti sono specificati come `Etichetta | {valore}` per riga in `teams_facts_inline` (alternativa alla lista JSON legacy `teams_facts`). Nel designer e in `action_card.html` il dropdown Teams legacy mostra solo preset attivi.
- `AutomationDeliveryEndpoint` (migration 0010): endpoint generico riutilizzabile per recapiti automazione, con `endpoint_type` (`teams_webhook_legacy`, `teams_flow_webhook`), URL, flag `is_active`, codice e descrizione. La pagina `/automazioni/canali-teams/` gestisce ora sia i preset legacy sia gli endpoint Teams Flow; `send_approval` usa `teams_flow_endpoint_id` per risolvere l'URL del Power Automate / Teams Workflow, con fallback compatibile su eventuale `teams_flow_url` raw in `config_json`.
- Schema drift difensivo: se il codice gira su un database dove la migration `automazioni.0010_automationdeliveryendpoint` non e' ancora applicata, pagina `Canali Teams`, builder classico, designer visuale e form `SEND_APPROVAL` non devono andare in 500. I lookup verso `AutomationDeliveryEndpoint` degradano a lista vuota con warning UI esplicito e il runtime `teams_chat_flow` restituisce un errore funzionale chiaro; il rimedio operativo resta `python django_app/manage.py migrate automazioni`.
- **Template Email Approvazioni** (migration 0011): `ApprovalEmailTemplate` — template riutilizzabili per le mail generate da `send_approval`. Gestiti su `/automazioni/template-approvazioni/` (voce "Template approvazioni" in subnav). Tre `delivery_mode`: `portal_links` (link HTTP, default), `mail_reply` (mailto: verso mailbox tecnica — per reti non esposte), `hybrid`. La mailbox tecnica si configura per-template (`mailto_mailbox`) o tramite `SiteConfig` chiave `automazioni_approval_mailbox`. Service layer in `automazioni/approval_email_templates.py`: rendering, context building, build mailto links, preview. Il `config_json` di `send_approval` puo' referenziare il template con `approval_email_template_id` (PK) o `approval_email_template_code`, ma per package/import/export e riapertura draft il riferimento canonico deve essere `approval_email_template_code`; l'id locale resta solo comodita' di lookup. Schema drift: lookup safe se migration non applicata. La preview su `/automazioni/template-approvazioni/<pk>/preview/` mostra HTML renderizzato con dati mock e rileva placeholder non risolti.
- Il `package_importer` deve normalizzare, validare e simulare esplicitamente `send_approval`, compresi `approved_actions`/`rejected_actions` embedded, warning su template approval non risolti localmente e preview sintetica di approvatori/template/count dei branch nel dry-run.
- **Polling mailbox approvazioni via Microsoft Graph** (migration 0012, backend default): management command `python manage.py process_approval_mailbox [--dry-run] [--folder <cartella>] [--limit N] [--since-hours N] [--only-unread] [--no-mark-read]`. Legge la mailbox via Graph API (autenticazione moderna, compatibile con Microsoft 365 / Exchange Online dove Basic Auth è bloccata). Riusa le credenziali `GRAPH_TENANT_ID/CLIENT_ID/CLIENT_SECRET` già presenti nel `.env`. Service layer in `automazioni/mailbox_graph.py`: `fetch_messages()`, `normalize_message()`, `parse_approval_command()`, `poll_graph_mailbox()`, `_validate_sender()`. Configurazione via `APPROVAL_MAILBOX_BACKEND=graph`, `APPROVAL_MAILBOX_ADDRESS`, `APPROVAL_MAILBOX_FOLDER`, `APPROVAL_GRAPH_ONLY_UNREAD`, `APPROVAL_GRAPH_PAGE_SIZE`, `APPROVAL_GRAPH_MARK_READ`. Tracking idempotente su `ApprovalMailboxMessage` (dedup su `internet_message_id` RFC 2822). Permessi app registration richiesti: `Mail.ReadWrite` Application permission + Admin Consent su tenant Entra ID.
- **Tracking messaggi mailbox** (`ApprovalMailboxMessage`, migration 0012): record per ogni messaggio letto. Campi: `internet_message_id` (dedup key univoco), `graph_message_id`, `mailbox`, `folder_name`, `from_email`, `received_at`, `command_detected`, `token_found`, `processing_status` (pending/processed/ignored/error), `processing_error`, `excerpt`, `linked_approval` FK, `processed_at`. Diagnostica: `/automazioni/mailbox-log/` (voce "Log mailbox" visibile dalle Impostazioni Automazioni).
- **Backend IMAP legacy** (`poll_approval_mailbox`): mantenuto per retrocompat con ambienti che usano IMAP Basic Auth classico (non M365). Configurazione in `.env`: `APPROVAL_IMAP_*`. Non funziona su Microsoft 365 con Basic Auth bloccata: usare `process_approval_mailbox` (Graph).
- **Dispatcher unificato**: `run_approval_poll_now()` in `automazioni/approval_mailbox_runtime.py` smista a Graph o IMAP in base a `APPROVAL_MAILBOX_BACKEND`. La pagina `/admin-portale/automazioni/impostazioni/` mostra il pannello Graph come primario e quello IMAP come sezione collassabile legacy. Il salvataggio da UI scrive `APPROVAL_MAILBOX_BACKEND=graph` nel `.env`.
- **Impostazioni Automazioni**: la pagina admin `/admin-portale/automazioni/impostazioni/` espone stato runtime del backend attivo (Graph/IMAP), editing parametri, pulsante `Esegui ora`, quick link a template/canali Teams/log mailbox e salvataggio della mailbox tecnica globale `automazioni_approval_mailbox` in `SiteConfig`. Lo stesso pannello IMAP e' visibile anche in `/admin-portale/ldap/` dentro `Configurazione SMTP`.

---

## Ricerca Globale (Ctrl+K)

- Endpoint: `GET /api/search/?q=<query>` → `core/views.py:api_global_search` → `core/urls.py`
- Attivazione: `Ctrl+K` (o `Cmd+K` su Mac) oppure click sull'icona 🔍 nella topbar
- Modelli interrogati (max 5 risultati per gruppo): `AnagraficaDipendente`, `Asset`, `Ticket`, `Project`, `Task`, `ProcedureDocument`
- I modelli di altre app vanno importati localmente dentro la funzione per evitare import circolari
- Risposta: `{"results": [{tipo, label, sub, url}, ...], "query": "..."}` con risultati raggruppati per tipo
- UI: overlay spotlight in `topnav.html` con navigazione da tastiera (frecce, Enter, Esc), debounce 220ms; in modalita sidebar il trigger rapido vive anche in `core/components/sidebar.html` come card scura integrata con hint `Ctrl+K` e resa icon-only quando `sb-collapsed` e attivo
- CSS: classi `.gs-*` in `theme.css`; ogni tipo di risultato ha la sua classe colore `.gs-tipo-<tipo>`
- Query minima: 2 caratteri; gestione errori per app non disponibili tramite `try/except` silenzioso

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

## Wizard di primo accesso (Onboarding)

- Modello: `core.UserOnboarding` (OneToOne su Django User) — migration `0043_useronboarding`
- URL: `/onboarding/` (view `onboarding_wizard`, name `onboarding_wizard`)
- Intercettazione: `ACLMiddleware` (dopo check autenticazione) → redirect a `/onboarding/` se `UserOnboarding.is_done()` è `False`
- Accesso pagina: `/onboarding/` resta sempre apribile a qualsiasi utente autenticato, senza grant ACL legacy/canonico dedicati
- Superusers bypass il check onboarding
- Reset API: `POST /api/onboarding/<django_user_id>/reset` (name `api_onboarding_reset`) — azioni: `reset` (riproponi wizard) o `skip` (esenta utente); solo admin legacy o superuser
- Admin UI: scheda utente in Admin Portale → tab Checklist → card "Wizard primo accesso"
- Step correnti wizard: `Benvenuto` → `Contatti` → `Interfaccia` → `Notifiche` → `Riepilogo`
- Preferenze UI raccolte: `nav_mode`, `font_scale`, `sidebar_collapsed`, `sidebar_footer_actions` (persistite in `core.UserUiPreference`)
- Notifiche email: il wizard deve mostrare solo i moduli effettivamente visibili al ruolo corrente; i tipi nascosti vanno persistiti come disabilitati per evitare preferenze fuorvianti
- Dati raccolti onboarding: `email_contatto`, `cellulare_contatto`, `notifiche_config` (JSON tipo → bool, es. `assenze`, `comunicazioni`, `scadenzari`, `ticket`)
- Azioni tracciate in AuditLog: `onboarding_completato`, `onboarding_reset`, `onboarding_esentato`

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

Nota dev tooling: `django_app/avvia_server.bat` evita intenzionalmente una scansione CIM/WMI globale dei processi Python. Su alcune postazioni Windows `Get-CimInstance Win32_Process` puo restare bloccato; per questo il batch pulisce solo il listener `LISTENING` sulla porta `8000` prima di lanciare `runserver`.

**Requisiti sistema:** Python 3.11+, SQL Server con schema legacy popolato, un driver ODBC SQL Server installato (`18`, `17`, `13`, `SQL Server Native Client 11.0` o `SQL Server`).

---

## File sensibili nel repo (da non esporre)

- `django_app/.env` Ã¢â‚¬â€ credenziali AD, IP di rete, SECRET_KEY
- `DIPENDENTI.csv` Ã¢â‚¬â€ dati reali dipendenti
- `db.sqlite3` Ã¢â‚¬â€ DB locale con dati di test
- `build/` e `dist/` Ã¢â‚¬â€ contengono `asta.exe` e `utenti.db`



