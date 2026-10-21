# Security Boundaries

Security, privacy, ACL, and sensitive-data boundaries moved out of root CLAUDE.md.

Important: Do not read all docs automatically. Open only the files relevant to the current task.

## Security Center AI Prime Rules

- Treat safety/compliance modules (diario_preposto, 
ilevazione_incidenti, procedure_refresh, dpi, 
entri) as high-integrity workflows: preserve auditability, permissions, source-of-truth boundaries, and user-visible traceability.
- Do not include secrets, real customer data, mailbox dumps, production logs, credentials, certificates, private reports, or raw personal-data exports in prompts, docs, commits, generated examples, screenshots, or test fixtures.
- Use synthetic examples for incidents, procedures, DPI, approvals, mailbox messages, Graph payloads, and SharePoint data.
- Keep Microsoft Graph, LDAP, SMTP, SQL Server, and Entra configuration as environment/runtime data only; document variable names, not values.
- Token-based approval endpoints are intentionally narrow public surfaces. Do not broaden publication beyond the documented prefixes.

Hardening sicurezza 0.8.7:
- login rate limiting con `django-axes` (5 tentativi, lockout 1 ora, template custom `core/pages/lockout.html`)
- upload hardening extension+MIME reale tramite `core/upload_mime.py` (fail-closed se libmagic non disponibile)
- rimozione relay password AD in sessione (`_sso_relay_pwd` non usato)
- `legacy_table_columns()` protetto da whitelist `ALLOWED_LEGACY_TABLES` (niente `PRAGMA` su nomi tabella non ammessi)
- `_SPNEGO_CONTEXTS` bounded con `TTLCache(maxsize=500, ttl=60)` per evitare crescita memoria in handshake SSO interrotti
- export CSV `assenze`/`anomalie` tracciati in AuditLog con `log_action(..., "export_csv", ...)`

## Sistema ACL / Permessi

La rimozione di una visita medica errata usa il permesso canonico
`anagrafica.visite.delete` e il binding della sola rotta
`anagrafica:visita_medica_elimina`. La vista richiede anche l'accesso alle visite,
una motivazione e registra l'audit nella stessa transazione della cancellazione.
I referti collegati sono conservati nel fascicolo del dipendente e i riferimenti
alla visita eliminata vengono rimossi nella stessa transazione, con gli ID dei
documenti registrati nell'audit. I grant per ruoli non admin sono disabilitati
per default.

### 0. Ruoli del portale (core.permessi) — sopra l'ACL v2

Sistema unico per ruoli, matrice ruolo × modulo × azione e visibilità dei dati
(propri / team d'organigramma / tutti): `django_app/core/permessi/`, pagina
`/admin-portale/ruoli-portale/`. I ruoli sono `AccessGroup` (ordine = `priority`); la
matrice genera i `GroupPermissionGrant` delle pagine. Con l'interruttore acceso il ruolo
legacy, la tabella `permessi` e il fallback legacy non concedono più nulla. Ogni modulo
nuovo si dichiara in `<app>/registro_permessi.py` e usa `puo_fare` / `utenti_visibili`:
procedura in [PERMESSI_RUOLI.md](PERMESSI_RUOLI.md).

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
- Modelli in `core/legacy_models.py` Ã¢â‚¬â€ `Ruolo`, `UtenteLegacy`, `Pulsante`, `Permesso`, `AnagraficaDipendente` Ã¢â‚¬â€ `managed=True` (app_label="core"), migration `0029_legacy_managed` fake su SQL Server esistente.
- Cache ACL legacy: `core/legacy_cache.py` + `bump_legacy_cache_version()`.

### 3. Navigation Registry (visibilita menu, non sicurezza)

- File: `core/navigation_registry.py`
- Tabelle Django: `NavigationItem`, `NavigationRoleAccess`, `UserNavigationOverride`, `UserDashboardConfig`, `UserModuleVisibility`
- `NavigationItem` espone ora anche `required_permission_code`: se compilato, o se ricavabile da `route_name` / `url_path`, la visibilita della voce viene derivata dai grant canonici del ruolo/utente.
- Runtime attuale: `RolePermissionGrant` / `UserPermissionGrant` sono la fonte primaria di visibilita menu; `NavigationRoleAccess` sopravvive solo come fallback compat per voci ancora prive di permission code canonico.
- Quando il Navigation Registry e' vuoto/disattivato e la shell cade sul fallback legacy `pulsanti`, `core.context_processors.legacy_nav()` deve deduplicare la navigazione principale per modulo prima di renderizzare topbar/sidebar. Le tabelle legacy possono contenere piu azioni dello stesso modulo (`lista`, `crea`, `gestione`) ma il menu principale deve mostrare una sola voce modulo, specialmente dopo restore/import topbar.
- **Override per-utente navigazione** (`UserNavigationOverride`): in runtime e hide-only. `enabled=False` nasconde una voce gia consentita; i vecchi override positivi (`enabled=True`) non forzano piu la mostra di voci negate dal canonico. Non usa la cache; gli admin non sono soggetti agli override. Funziona su `topbar` e `subnav`. Gestito da "Step 5 Ã¢â‚¬â€œ Nav Override" in `/admin-portale/acl-canonico/` e da "Override Navigazione Utente" in `/admin-portale/navigation-builder/`.

#### Sezioni `NavigationItem.section`

| Valore | Dove viene renderizzata | ACL |
| --- | --- | --- |
| `topbar` | Barra di navigazione principale (in cima) | permission code canonico -> fallback `NavigationRoleAccess` solo se unmapped |
| `subnav` | Barra secondaria per modulo (filtrata per `parent_code`) | permission code canonico -> fallback `NavigationRoleAccess` solo se unmapped |
| `sidebar` | Menu laterale (modalita sidebar) | permission code canonico -> fallback `NavigationRoleAccess` solo se unmapped |
| `page` | Dentro una pagina specifica | permission code canonico -> fallback `NavigationRoleAccess` solo se unmapped |
| `admin_subnav` | Barra interna dell'admin portale (`/admin-portale/`) | **Nessuna ACL** Ã¢â‚¬â€ area gia gated da `@legacy_admin_required` |

**`admin_subnav` Ã¢â‚¬â€ regola critica:** NON hardcodare mai voci in `admin_subnav.html`. Gestire sempre tramite `NavigationItem` con `section="admin_subnav"` via Navigation Builder o migration. Migration seed: `core/migrations/0031_admin_subnav_seed.py` + `0032_admin_subnav_acl_nav_map.py` (voce aggiuntiva mappa permessi/navigazione). Il context processor inietta `admin_subnav_items` solo per utenti `is_legacy_admin()`.

Navigation Builder (`/admin-portale/navigation-builder/`): oltre alla tabella inline include una **vista visuale drag&drop orizzontale** (scroll laterale) a colonne per sezione (`topbar`, `subnav`, `admin_subnav`, `sidebar`, `page`) con card trascinabili, spostamento cross-sezione e sincronizzazione immediata su `NavigationItem.section` + `NavigationItem.order` tramite `api_navigation_reorder`. Ogni card supporta azioni rapide `Apri`, `Clona`, `Rimuovi`; il listener globale dei click nel template deve restare `async` perchÃƒÂ© invoca fetch asincrone. Nota semantica: `topbar` rappresenta la navigazione principale e in `nav_mode=side` viene renderizzata nella sidebar. Nel builder `sidebar` e trattata come opzione avanzata (`Sidebar Dedicated`) e viene nascosta in modalita standard.

Rendering icone navigazione: `render_icon` supporta alias SVG semantici (`layout-dashboard`, `newspaper`, `scan`, `id-card`, `package`, `shield-check`, `file-check`, `key-round`, ecc.), immagini (`media:`/`static:`/URL) e fallback automatico da label per sostituire iniziali placeholder nella topbar/sidebar.

Sidebar nav side: i gruppi aperti devono restare visivamente distinti dal primo livello tramite pannello annidato, rientro e stato aperto evidente, senza rompere la leggibilita in modalita `sb-collapsed` o mobile.

### Strumenti diagnostica/gestione ACL (admin)

- `/admin-portale/accessi/`: entrypoint semplice predefinito per i permessi ruolo. Da Fase 3 e **canonico-first**: il toggle modulo scrive solo i `RolePermissionGrant`; legacy ACL e fallback navigation restano visibili come contesto/copertura ma non sono piu la fonte primaria del salvataggio.
- Nella pagina Accessi, modulo -> natura (configurazione/operativo) -> sottomodulo e' una gerarchia di sola presentazione derivata dai permission code. I comandi del sottomodulo selezionano solo i suoi permessi; il salvataggio continua a scrivere grant canonici individuali. Il resolver ACL non legge questa gerarchia.
- `/admin-portale/gestione-accessi/`: dettaglio storico legacy ruolo -> modulo -> azione.
- `/admin-portale/acl-canonico/`: gestione operativa del layer v2 (permission code, route/path binding, grant ruolo, override utente, override navigazione utente). Tab: 1. PermissionDefinition, 2. Route Binding, 3. Role Grant, 4. User Override, **5. Nav Override** (nuovo).
- `/admin-portale/acl-route-coverage/`: report route dedicato con stati `CANONICAL_BOUND`, `LEGACY_FALLBACK`, `UNBOUND`, `COMING_SOON_EXCLUDED`, `REDIRECT_ONLY` e export CSV.
- Il report `acl-route-coverage` usa il binding canonico effettivo (winner route/path) per permission e warning; le route decorate con `@legacy_admin_required` sono marcate `admin_bypass` e non vengono conteggiate come `missing_grant`.
- `/admin-portale/acl-diagnostica/` (alias compat legacy: `/admin-portale/acl/`): diagnostica combinata legacy + canonical con **una sola decisione finale** del resolver v2, trace esplicito e blocco legacy relegato a dettaglio secondario.
- `/admin-portale/mappa-permessi-navigazione/`: mappa unica route/menu con sorgente (`REGISTRY`/`LEGACY`), ruoli abilitati, override utente, admin bypass e redirect legacy. Ogni riga ha drill-down workflow visuale cliccabile; con filtro ruolo attivo supporta toggle live sia dei grant canonici v2 (`RolePermissionGrant.enabled`) sia dei permessi legacy (`can_view`) via API.

### Path esenti da ACL (MIDDLEWARE_EXEMPT_PREFIXES)

Questi path bypassano completamente l'`ACLMiddleware`:

```text
/health  /healthz  /readyz  /version  /check  /login  /logout  /cambia-password
/static/  /media/  /admin/  /favicon  /setup/  /2fa/
/admin-portale/hub/          (Hub Tools: ogni view ha legacy_admin_or_acl_required)
/monitoring/report-problem/  (segnalazione problema dal client, POST JSON)
/assets/qr/pub/              (landing QR asset con token opaco, sola lettura)
/schede-sicurezza/s/         (scheda SDS mobile via QR fisico, sola lettura)
/gestione-anomalie/mail-action/  (azioni dalla mail anomalie, token monouso)
/suggestion-corner/nuova/    (form pubblico anonimo, rate-limit per IP + honeypot)
/automazioni/approvazione/   (token-based, no login required)
/admin-portale/automazioni/approvazione/
/approval-actions/           (token-based, Entra Application Proxy frontend)
/api/assets/contatori/ingest/  (token per collector + allowlist IP, SOLO rete interna)
/api/v1/                       (API dati sola lettura: token per applicazione + ambiti + allowlist IP, SOLO rete interna)
```

Allineato a `config/settings/base.py` il 18/10/2026. Il middleware non applica né login né ACL su questi prefissi: la protezione dipende solo dalla view (decoratore ACL, token, allowlist). Il test `core/test_security_audit_fase3.py` elenca in `PUBLIC_VIEWS` quelle che rispondono 200 a un anonimo: una nuova esenzione va aggiunta sia a `MIDDLEWARE_EXEMPT_PREFIXES` sia lì, con motivazione.

**`/api/assets/contatori/ingest/` — letture contatori dai collector** (es. OPC UA delle CNC): nessuna sessione, `Authorization: Bearer <token>` di un `MeterIngestClient` attivo (a DB solo hash SHA-256, confronto `hmac.compare_digest`), client IP in `ASSETS_METER_INGEST_ALLOWED_IPS` (IP o CIDR, default solo loopback; fuori = 403 JSON), ogni collector scrive solo sugli asset consentiti, 500 letture per chiamata. **Non pubblicare su Entra Application Proxy**: è un endpoint macchina-macchina di rete interna. Token creato da admin Django o `manage.py meter_ingest_client` (mostrato una volta sola). Contratto: `docs/moduli/assets_contatori_ingest.md`.

**`/api/v1/` — API dati in sola lettura per applicazioni** (Power BI, Power Automate, gestionali): nessuna sessione, `Authorization: Bearer <token>` di un `dati_bi.ApiClient` attivo (a DB solo hash SHA-256, confronto `hmac.compare_digest`), client IP in `DATI_API_ALLOWED_IPS` (default solo loopback; fuori = 403 JSON), ogni applicazione legge solo i suoi **ambiti** (403 JSON altrimenti), solo GET, al massimo 500 righe per pagina. **Mai dati personali nominativi** né testi liberi; il personale esce solo come conteggi per reparto (ambito `personale_aggregato`). **Non pubblicare su Entra Application Proxy.** Token da `manage.py dati_api_client` (mostrato una volta sola). Le viste SQL `bi_*` seguono le stesse regole sui dati e si leggono con un utente SQL in sola lettura (`manage.py bi_viste --grant`). Contratto: `docs/moduli/dati_bi.md`.

**`/approval-actions/` — Entra Application Proxy**: endpoint pensati per essere pubblicati selettivamente su Entra Application Proxy. Pubblicare **solo** `/approval-actions/*`, non l'intero `/automazioni/`. URL file: `automazioni/approval_proxy_urls.py`.

- `GET|POST /approval-actions/r/<segreto>/<approva|rifiuta>/` — **link personale** inviato a un solo destinatario (`AutomationApprovalLink`, a DB solo hash SHA-256, monouso). Decide a nome di `recipient_email` senza login. È il link delle email.
- `GET|POST /approval-actions/approve|reject/<uuid>/` e `/automazioni/approvazione/<uuid>/<approva|rifiuta>/` — link della richiesta: **login obbligatorio** e utente fra gli approvatori (`validate_approval_actor`). La pagina di stato `/automazioni/approvazione/<uuid>/` è visibile solo ad approvatori e admin.
- GET mostra sempre una conferma senza effetti; solo POST decide. Ogni decisione è in AuditLog (`approval_link_decision`, `approval_proxy_decision`, `*_denied`).
- **Mai** ricavare l'identità da header HTTP (`X-MS-CLIENT-PRINCIPAL-NAME`, `X-Forwarded-Email`): IIS li inoltra anche quando li scrive il client. Mai accettare decisioni anonime "da Teams".
- L'IP del client si legge solo con `core.net.client_ip` (`X-Forwarded-For` solo da `TRUSTED_PROXY_IPS`).
- Allegati di modulo: mai su storage pubblico `/media/`; usare `core.private_attachments.PrivateAttachmentStorage` (o lo storage privato del modulo) + view protetta, e aggiungere il `<location path="media/...">` di deny per i file storici.
- Cartelle storiche con dati personali bloccate in IIS (GDPR 21/10/2026): `media/anagrafica`, `media/fotocard`, `media/firme`, `media/timbri`, `media/tasks_vrf`, `media/tasks_attachments`, `media/attrezzature_import_preview`. Il `web.config` di un server gia' installato non si ridistribuisce: i blocchi si aggiungono a mano. `media_privatizza --apply` sposta i file storici nello storage privato cifrato.
Path auth-only condivisi gestiti direttamente da `ACLMiddleware` (senza grant ACL dedicati):
- `/onboarding/` per tutti gli utenti autenticati non superuser interessati al primo accesso
- `/notifiche/` e `/api/notifiche/...` per tutti gli utenti autenticati, cosi il centro notifiche e il popup ack restano sempre disponibili indipendentemente dal ruolo

### ACL Bootstrap (pattern per nuovi endpoint API)

Alcune app registrano automaticamente i propri endpoint nell'ACL legacy all'avvio tramite `acl_bootstrap.py`. App con bootstrap: `assenze`, `notizie`, `tasks`, `diario_preposto`.

Pattern: `AppConfig.ready()` ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ chiama `bootstrap_*_acl_endpoints()` ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ upsert su tabella `pulsanti` ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ `bump_legacy_cache_version()`. Gli endpoint API vengono nascosti dalla UI via tabella `ui_pulsanti_meta`.

### Bootstrap ACL v2 (nuovo)

- Management command: `python django_app/manage.py bootstrap_acl_v2 [--dry-run] [--apps app1,app2] [--apply] [--import-legacy] [--activate-generated-bindings]`
- Funzioni principali:
  - scansione route Django nominate
  - classificazione copertura route: `CANONICAL_BOUND`, `LEGACY_FALLBACK`, `UNBOUND`, `COMING_SOON_EXCLUDED`, `REDIRECT_ONLY`
  - proposta permission code iniziali (convenzione `modulo.risorsa.azione`)
  - scope per app (`--apps`) per migrazione incrementale modulo-per-modulo
  - import opzionale da `pulsanti`/`permessi` legacy solo con `--apply`; `--dry-run --import-legacy` non scrive
  - in apply: crea `PermissionDefinition`, `RoutePermissionBinding` e grant ruolo mancanti dal fallback legacy; grant e binding esistenti non vengono riscritti o riattivati
  - report finale con grouping per app di route `LEGACY_FALLBACK/UNBOUND` e conteggi before/after
  - nell'installazione iniziale il Setup Wizard esegue dry-run pre -> apply (`--import-legacy`) -> dry-run post; in TEST il seed `seed_acl_uat --reset` e opzionale
  - in Promuovi Release (TEST/PROD) il workflow esegue dry-run pre -> apply senza import legacy -> dry-run post; non esegue il seed UAT

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
- Solo `is_legacy_admin()` puÃƒÆ’Ã‚Â² avviare l'impersonation

### Elementi hardcoded da NON replicare

- Nomi moduli: `"admin"`, `"dashboard"`, `"assenze"` in `core/acl.py`
- API gate: `"/api/anomalie/"` ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ `"/gestione-anomalie"` in `core/middleware.py`
- Nav gate: `"tasks"` ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ `"/tasks/"` in `core/context_processors.py`

### Architettura target (stato attuale)

- Layer canonico v2 implementato con modelli Django gestiti + resolver dedicato.
- ACL legacy mantenuto come fallback compatibile (nessun big-bang).
- Migrazione incrementale modulo-per-modulo: nuove route possono usare subito binding canonico senza rompere le route storiche.

---

## SQL grezzo (censimento 19/10/2026)

Il portale interroga tabelle legacy SQL Server con `cursor.execute` (~660 chiamate; le più numerose in `anagrafica`, `core`, `admin_portale`, `assenze`, `automazioni`, `anomalie`). Regole:

- I **valori** (filtri, id, testo cercato, date) passano sempre come parametri (`%s`), mai nella stringa.
- Gli **identificatori** (tabella, colonna, alias) entrano nella stringa solo se vengono da un registro o da una costante: `Model._meta.db_table`, `legacy_table_columns(...)`, `source_registry` (automazioni), liste `_LEGACY_COLS`, oppure `connection.ops.quote_name(...)` dopo validazione (`core/db_diagnostics.py`).
- Le clausole composte (`" OR ".join(clauses)`, `",".join(["%s"] * n)`) contengono solo frammenti costanti e segnaposto.

`ruff --select S608` segnala 214 siti costruiti con f-string/format (53 file): il censimento li ha riesaminati tutti e nessuno interpola dati utente. `core/test_sql_census.py` tiene quel conteggio per file in `core/sql_grezzo_baseline.json`: una query nuova costruita con stringhe fa fallire il test finché non usa un parametro o finché il sito non viene riesaminato e aggiunto alla linea di base nello stesso commit.

## Content-Security-Policy e nonce

La CSP globale è `CSP_POLICY` (middleware `ContentSecurityPolicyMiddleware`, nessun host esterno, `'unsafe-inline'` su script e stile perché i template SSR hanno ancora ~265 `<script>` inline e ~230 handler `on*=`). Il nonce è pronto ma spento: `CSP_NONCE_ENABLED=1` passa a `CSP_POLICY_NONCE` (`script-src 'self' 'nonce-{nonce}'`, stile invariato) con `{nonce}` sostituito a ogni richiesta; il valore è in `request.csp_nonce` e nei template come `{{ csp_nonce }}` (context processor `core.context_processors.csp`, sempre presente). Prerequisito per accenderlo: ogni `<script>` inline con `nonce="{{ csp_nonce }}"` e nessun handler `on*=` (con un nonce i browser ignorano `'unsafe-inline'`). Rollout: prima `CSP_REPORT_ONLY=1`. Test: `core/test_csp_nonce.py`.

## Politica di audit (`core/audit_policy.py`)

L'audit automatico di insert/update/delete (`core/audit_signals.py`) segue una politica dichiarativa e versionata. Dettaglio e motivazioni: [docs/dr/AUDIT_POLICY.md](../dr/AUDIT_POLICY.md).

- **Classe A (default)**: audit completo. Ogni modello non elencato resta qui: si riduce solo ciò che è elencato esplicitamente.
- **Classe B**: modelli tecnici che sono già log (`AutomationRunLog`, `AutomationExecution`, `SecurityCveImpact`, `RilevazioneSNMP`…): nessuna riga e nessun listener.
- **Classe C**: contenuti voluminosi o personali (`SecuritySourceFile`, `SecurityMailboxMessage`, `SecurityReport`, `SgiTestoEstratto`): solo metadati e nomi dei campi, mai i valori (minimizzazione GDPR).
- **Classe D**: campi tecnici di stato che da soli non generano righe (es. `AutomationRule.last_run_at`, `Notifica.letta`).
- Invarianti: `log_action` e `login_fallito` non passano dalla politica; insert e delete di classe A/D si registrano sempre; nessuna riga per update senza modifiche reali; valori oltre 500 caratteri troncati con lunghezza e impronta SHA-256.
- Un modello di business non va mai in classe B o C. Ogni modifica della politica passa da PR + CHANGELOG e incrementa `AUDIT_POLICY_VERSION` (ISO/IEC 27001); `manage.py check` segnala chiavi errate (`core.W002`/`core.W003`).
- Lo storico si riduce solo con `manage.py audit_archive` (dry-run di default; archivio verificato prima di toccare il DB; `--run` in produzione lo esegue solo Brizio).

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

## Centrale SNMP (`contatori`)

### Reportistica Asset collegata

- Nuovi prefissi canonici: `/assets/impostazioni/reportistica` → `legacy.assets.admin_assets`;
  `/assets/reports/archivio` → `legacy.assets.assets_reports`. Migration Assets 0120 riusa i
  permessi senza assegnare grant. Nessuna modifica alle esenzioni pubbliche.
- Snapshot/PDF/XLSX nel DB, non MEDIA pubblici; download protetti, auditati e `private, no-store`.
  Creazione/modifica/estrazione/retry richiedono gestione e POST/CSRF; archivio in sola lettura.
- Il permesso Reports abilita la consultazione dell'intero perimetro dei report: non è un filtro
  per asset assegnati all'utente. Non esportare credenziali/community; valori Excel come testo,
  contenuti PDF escapati. Nessuna interrogazione apparati dall'esportazione.

### Polling e collegamenti

- Le comunicazioni verso MFC e dispositivi usano esclusivamente SNMP GET/WALK; non esiste alcun percorso SET.
- Le sonde accettano solo OID numerici puntati validati. La discovery limita ogni scansione a 512 host.
- La community globale risiede in `ImpostazioniSNMP`; gli override per dispositivo/MFC sono gia supportati dalla migration 0011. Il discovery accetta fino a 8 community transitorie, mai nei risultati, URL o messaggi: mostra solo l’indice della candidata riuscita e non ripropone i segreti nel form. La modalita background aggiunge un catalogo cifrato e risultati persistenti per richiedente: job con soli ID/revisione, audit senza segreti, form password senza redisplay, risposte no-store. La stessa route e le ACL esistenti proteggono catalogo e scansioni; nessun grant o bypass nuovo. Dettagli in docs/SNMP_DISCOVERY.md.
- Il ponte Asset è in sola lettura sul registro `assets`: l'automatch scrive soltanto la FK nel modulo `contatori`, e solo per un match univoco di seriale o endpoint IP. Ambiguità e assenze non vengono risolte automaticamente.

## Infrastruttura server (NON riproducibile in dev)

Questi componenti esistono solo sul server di produzione:

- Tabelle legacy SQL Server: `utenti`, `ruoli`, `pulsanti`, `permessi`, `anagrafica_dipendenti` ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â DDL non nel repo, migration Django `0029_legacy_managed` presente ma applicata con `--fake` (tabelle preesistenti)
- Trigger SQL Server per assenze (`sql/`): `trg_assenze_automation_after_insert`, `trg_assenze_automation_after_update`
- Tabella `automation_event_queue` (`sql/automation_event_queue.sql`) con riallineamento idempotente delle colonne nuove (es. `execute_after`) senza ricreazione della tabella
- SharePoint/Graph data (credenziali `GRAPH_*` nel `.env`)
- `media/fotocard`, `media/timbri`, `media/firme`
- `django_app/.env` runtime (solo `.example` nel repo)

---


## File sensibili nel repo (da non esporre)

- `django_app/.env` ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â credenziali AD, IP di rete, SECRET_KEY
- `DIPENDENTI.csv` ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â dati reali dipendenti
- `db.sqlite3` ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â DB locale con dati di test
- `build/` e `dist/` ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â contengono `asta.exe` e `utenti.db`

- **Cookie `nh_dev` (riconoscimento del dispositivo, 20/10/2026)**: firmato con `SECRET_KEY` (salt `core.dispositivi`), HttpOnly, SameSite Lax, Secure in https, 2 anni; contiene solo un numero casuale, nel DB l'impronta SHA-256 (`core.DispositivoAccesso`). Serve solo a dire «browser già visto»: non autentica e non sostituisce login o 2FA.
