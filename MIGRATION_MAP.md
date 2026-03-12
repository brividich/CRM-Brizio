# MIGRATION_MAP (Flask -> Django 5.2 LTS)

## Scope e metodo
- Audit statico del codice in `flask_app/` (con riferimenti runtime a `config.ini` e `requirements.txt` quando necessari).
- Nessuna modifica al codice Flask; documento preparatorio per migrazione a Django 5.2 LTS.
- Nota: non elenco `HEAD`/`OPTIONS` impliciti di Flask, solo metodi dichiarati/effettivi.

## Executive summary
- App Flask modulare a blueprint, ma con logica business fortemente accoppiata ai route handler e query SQL inline.
- Autenticazione attuale: sessione Flask (cookie) + login locale DB + opzionale Active Directory via LDAP (`ldap3`). Nessun JWT attivo (dipendenza `PyJWT` presente ma non usata).
- DB runtime: SQL Server via `pyodbc` con wrapper custom che emula API `sqlite3`; nessun ORM/SQLAlchemy.
- Fonte dati ibrida: alcune pagine leggono direttamente SharePoint (Microsoft Graph), altre leggono dal DB locale sincronizzato.
- Schema e migrazioni DB vengono eseguiti a runtime dentro l'app (`init_db()` + `run_migrations()`), con DDL sparso anche in moduli admin/sync.
- Migrazione consigliata: portare per primi core identity/session/ACL + accesso DB/repository; mantenere SharePoint come adapter separato e sincronizzazioni come job esterni al web request thread.

## 1) Route Flask (Migration Map)
| Path | Methods | Blueprint | File |
|---|---|---|---|
| `/` | `GET` | `app` | `flask_app/app.py` |
| `/` | `GET, POST` | `auth` | `flask_app/modules/auth/routes.py` |
| `/admin` | `GET, POST` | `admin` | `flask_app/modules/admin/routes.py` |
| `/admin/anagrafica` | `GET` | `anagrafica` | `flask_app/modules/admin/routes_anagrafica.py` |
| `/admin/anagrafica/<int:dip_id>/salva` | `POST` | `anagrafica` | `flask_app/modules/admin/routes_anagrafica.py` |
| `/admin/anagrafica/sync_ad` | `GET` | `anagrafica` | `flask_app/modules/admin/routes_anagrafica.py` |
| `/admin/api/permessi/bulk` | `POST` | `gestione_ruoli` | `flask_app/modules/admin/routes_gestione_ruoli.py` |
| `/admin/api/permessi/toggle` | `POST` | `gestione_ruoli` | `flask_app/modules/admin/routes_gestione_ruoli.py` |
| `/admin/api/pulsanti/create` | `POST` | `gestione_ruoli` | `flask_app/modules/admin/routes_gestione_ruoli.py` |
| `/admin/api/pulsanti/delete` | `POST` | `gestione_ruoli` | `flask_app/modules/admin/routes_gestione_ruoli.py` |
| `/admin/api/pulsanti/update` | `POST` | `gestione_ruoli` | `flask_app/modules/admin/routes_gestione_ruoli.py` |
| `/admin/delete_fotocard/<int:user_id>` | `POST` | `admin` | `flask_app/modules/admin/routes.py` |
| `/admin/export_utenti` | `GET` | `admin` | `flask_app/modules/admin/routes.py` |
| `/admin/force_migrations` | `GET` | `admin` | `flask_app/modules/admin/routes.py` |
| `/admin/gestione_completa` | `GET` | `gestione_ruoli` | `flask_app/modules/admin/routes_gestione_ruoli.py` |
| `/admin/gestione_pulsanti` | `GET, POST` | `gestione_ruoli` | `flask_app/modules/admin/routes_gestione_ruoli.py` |
| `/admin/gestione_ruoli` | `GET` | `gestione_ruoli` | `flask_app/modules/admin/routes_gestione_ruoli.py` |
| `/admin/gestione_ruoli` | `POST` | `gestione_ruoli` | `flask_app/modules/admin/routes_gestione_ruoli.py` |
| `/admin/gestione_utenti` | `GET` | `gestione_utenti` | `flask_app/modules/admin/routes_gestione_utenti.py` |
| `/admin/log-audit` | `GET` | `admin` | `flask_app/modules/admin/routes.py` |
| `/admin/modifica_info` | `POST` | `admin` | `flask_app/modules/admin/routes.py` |
| `/admin/modifica_ruoli_massivo` | `POST` | `admin` | `flask_app/modules/admin/routes.py` |
| `/admin/modifica_ruolo` | `POST` | `admin` | `flask_app/modules/admin/routes.py` |
| `/admin/modifica_ruolo_singolo` | `POST` | `admin` | `flask_app/modules/admin/routes.py` |
| `/admin/permessi` | `GET, POST` | `permessi` | `flask_app/modules/admin/routes_permessi.py` |
| `/admin/permessi/aggiungi` | `POST` | `permessi` | `flask_app/modules/admin/routes_permessi.py` |
| `/admin/reset_password_scheda` | `POST` | `admin` | `flask_app/modules/admin/routes.py` |
| `/admin/ricarica_capi` | `GET` | `admin` | `flask_app/modules/admin/routes.py` |
| `/admin/sync/<lista>` | `GET` | `sync` | `flask_app/modules/admin/routes_sync.py` |
| `/admin/sync/pending-anomalie` | `GET` | `sync` | `flask_app/modules/admin/routes_sync.py` |
| `/admin/sync_info_personali` | `GET` | `admin` | `flask_app/modules/admin/routes.py` |
| `/admin/sync_mansioni` | `GET` | `admin` | `flask_app/modules/admin/routes.py` |
| `/admin/test` | `GET` | `gestione_ruoli` | `flask_app/modules/admin/routes_gestione_ruoli.py` |
| `/admin/upload_fotocard` | `POST` | `admin` | `flask_app/modules/admin/routes.py` |
| `/admin/utente/<int:user_id>` | `GET` | `admin` | `flask_app/modules/admin/routes.py` |
| `/admin/utente/<int:user_id>/pdf` | `GET` | `admin` | `flask_app/modules/admin/routes.py` |
| `/anomalie-menu` | `GET` | `dashboard` | `flask_app/modules/dashboard/routes.py` |
| `/api/anomalie/anomalie` | `GET` | `anomalie_api` | `flask_app/modules/admin/routes_anomalie_api.py` |
| `/api/anomalie/campi` | `GET` | `anomalie_api` | `flask_app/modules/admin/routes_anomalie_api.py` |
| `/api/anomalie/db/anomalie` | `GET` | `anomalie_api` | `flask_app/modules/admin/routes_anomalie_api.py` |
| `/api/anomalie/db/ordini` | `GET` | `anomalie_api` | `flask_app/modules/admin/routes_anomalie_api.py` |
| `/api/anomalie/ordini` | `GET` | `anomalie_api` | `flask_app/modules/admin/routes_anomalie_api.py` |
| `/api/anomalie/salva` | `POST` | `anomalie_api` | `flask_app/modules/admin/routes_anomalie_api.py` |
| `/api/anomalie/sync` | `POST` | `anomalie_api` | `flask_app/modules/admin/routes_anomalie_api.py` |
| `/assenze/` | `GET` | `assenze` | `flask_app/modules/assenze/routes.py` |
| `/assenze/aggiorna_consenso/<int:item_id>` | `POST` | `assenze` | `flask_app/modules/assenze/routes.py` |
| `/assenze/api/eventi` | `GET` | `assenze` | `flask_app/modules/assenze/routes.py` |
| `/assenze/calendario` | `GET` | `assenze` | `flask_app/modules/assenze/routes.py` |
| `/assenze/gestione_assenze` | `GET` | `assenze` | `flask_app/modules/assenze/routes.py` |
| `/assenze/invio` | `POST` | `assenze` | `flask_app/modules/assenze/routes.py` |
| `/assenze/richiesta_assenze` | `GET` | `assenze` | `flask_app/modules/assenze/routes.py` |
| `/cambia-password` | `GET, POST` | `auth` | `flask_app/modules/auth/routes.py` |
| `/check` | `GET` | `app` | `flask_app/app.py` |
| `/dashboard` | `GET` | `dashboard` | `flask_app/modules/dashboard/routes.py` |
| `/gestione-anomalie` | `GET` | `admin` | `flask_app/modules/admin/routes.py` |
| `/gestione-anomalie/apertura` | `GET, POST` | `admin` | `flask_app/modules/admin/routes.py` |
| `/gestione-anomalie/apertura/anomalie` | `GET, POST` | `admin` | `flask_app/modules/admin/routes.py` |
| `/gestione_utenti/modifica/<int:user_id>` | `POST` | `gestione_utenti` | `flask_app/modules/admin/routes_gestione_utenti.py` |
| `/logout` | `GET` | `auth` | `flask_app/modules/auth/routes.py` |
| `/modifica_capo` | `POST` | `admin` | `flask_app/modules/admin/routes.py` |
| `/modifica_info_completa` | `POST` | `admin` | `flask_app/modules/admin/routes.py` |
| `/richieste` | `GET` | `dashboard` | `flask_app/modules/dashboard/routes.py` |

## 2) Auth attuale (identita utente, sessione, LDAP/AD, mapping DB)
### Meccanismo principale
- Sessione Flask cookie-based firmata con `SECRET_KEY` (`config.ini`), non JWT.
- In `flask_app/app.py`:
  - `PERMANENT_SESSION_LIFETIME = 8h`
  - `SESSION_COOKIE_HTTPONLY = True`
  - `SESSION_COOKIE_SAMESITE = 'Lax'`
  - `SESSION_COOKIE_SECURE` non impostato esplicitamente
- `_create_session()` in `flask_app/modules/auth/routes.py` salva in sessione:
  - `user_id`, `nome`, `email`, `ruolo`, `ruolo_id`
  - `ruoli` (lista serializzata come JSON string)

### Login locale (DB)
- Route: `POST /` (`auth.login`).
- Lookup su `utenti` per email oppure nome (`SELECT * FROM utenti WHERE lower(email|nome) = ?`).
- Password hash verificata con `werkzeug.security.check_password_hash`.
- Campo `attivo` blocca login.
- Campo `deve_cambiare_password` forza redirect a `/cambia-password`.

### Login Active Directory / LDAP (Domino non rilevato)
- Gestito da `flask_app/modules/auth/ad_auth.py` con `ldap3`.
- Bind LDAP semplice con UPN e fallback `DOMINIO\utente` (NetBIOS).
- Parametri da `config.ini` `[ACTIVE_DIRECTORY]`: `enabled`, `server`, `domain`, `upn_suffix`, `timeout`, piu service account per sync anagrafica.
- In caso di successo AD: `_find_or_create_ad_user()` crea utente locale automatico se assente.
- Auto-provisioning in `utenti`: `ruolo='utente'`, `ruoli='["utente"]'`, password hash placeholder `*AD_MANAGED*`.
- Mapping AD -> DB avviene per `email` (`UPN`) su `utenti.email`.

### Sync AD anagrafica (service account)
- Route `GET /admin/anagrafica/sync_ad` (`routes_anagrafica.py`).
- Usa `ldap3` con autenticazione `NTLM` e service account da `config.ini`.
- Aggiorna `anagrafica_dipendenti.ad_username` e `anagrafica_dipendenti.ad_guid` con matching per alias/email.

### Logout e password
- `GET /logout`: `session.clear()`.
- `GET/POST /cambia-password`: aggiorna `utenti.password` e `deve_cambiare_password = 0`.

## 3) Ruoli / permessi attuali (rappresentazione e enforcement)
### Rappresentazione dati
- `utenti.ruolo` (stringa legacy, singolo ruolo)
- `utenti.ruoli` (JSON string con lista ruoli, legacy/misto)
- `utenti.ruolo_id` (FK verso `ruoli.id`, direzione piu strutturata)
- `ruoli` seedati da `init_db`: `admin`, `caporeparto`, `HR`, `qualita`, `amministrazione`, `utente`
- `pulsanti` definisce menu/programmi/modulo/url (usato anche come base ACL)
- `permessi` contiene ACL per `(ruolo_id, modulo, azione)` con campi granulari:
  - `can_view`, `can_edit`, `can_delete`, `can_approve`
  - `consentito` legacy compatibile (allineato a `can_view`)

### Enforcement runtime
- Decorator principale: `require_roles()` in `flask_app/modules/utils.py`.
- Controlla sessione (`user_id`, `ruolo`) e poi:
  - bypass totale se `ruolo == 'admin'`
  - altrimenti chiama `check_permesso(user_id, request.path)`
- `check_permesso()` normalizza il path, lo mappa su `pulsanti.url/codice`, poi verifica `permessi` per `ruolo_id`.
- Cache permessi in memoria processo con TTL (`[CACHE].permessi_ttl`, fallback 300s).

### Inconsistenze attuali (importanti per la migrazione)
- `require_roles(*ruoli_permessi)` ignora di fatto i ruoli passati al decorator e usa solo ACL dinamica su path + admin bypass.
- Naming ruoli misto (`utente`, `user`, `dipendente`, `gestore`, `HR`) con rischio drift logico.
- Alcune route usano `@require_roles`, altre fanno check manuali `session['ruolo']`.

## 4) DB: accesso a SQL Server, query e modelli
### Accesso DB
- Modulo centrale: `flask_app/modules/utils.py`.
- Driver: `pyodbc` (SQL Server), stringa di connessione da `config.ini` `[SQLSERVER]`.
- Supporta Windows Authentication (`Trusted_Connection=yes`) se `username/password` sono vuoti.
- Wrapper custom (`ConnectionWrapper`, `CursorWrapper`, `Row`) per compatibilita `sqlite3`:
  - row access per nome (`row['colonna']`)
  - `lastrowid` via `SCOPE_IDENTITY()`
  - context manager commit/rollback
- Nessun ORM (no SQLAlchemy, no Flask-SQLAlchemy).

### Dove sono query e pseudo-modelli (SQL raw)
- `flask_app/modules/utils.py`: bootstrap schema, migrazioni, ACL, helper DB.
- `flask_app/modules/auth/routes.py`: login/cambio password su `utenti`.
- `flask_app/modules/dashboard/routes.py`: legge `pulsanti`; statistiche/richieste soprattutto via Graph.
- `flask_app/modules/assenze/routes.py`: API calendario dal DB (`assenze` + join), resto soprattutto via Graph.
- `flask_app/modules/admin/routes.py`: CRUD utenti/info, export, fotocard, staging anomalie, sync helper admin.
- `flask_app/modules/admin/routes_gestione_ruoli.py`: CRUD `pulsanti` e `permessi`.
- `flask_app/modules/admin/routes_gestione_utenti.py`: lista/modifica utenti + ruoli.
- `flask_app/modules/admin/routes_anagrafica.py`: `anagrafica_dipendenti` + associazioni a `utenti`.
- `flask_app/modules/admin/routes_sync.py`: sync SharePoint -> DB e push staging -> SharePoint.

## 5) Tabelle principali usate e relazioni deducibili
### Tabelle core applicative (create/migrate in `modules/utils.py`)
- `ruoli`
- `utenti`
- `pulsanti`
- `permessi`
- `info_personali`
- `mansione`

### Tabelle replica SharePoint (create in `modules/utils.py`, popolate da `routes_sync.py`)
- `dipendenti`
- `capi_reparto`
- `ordini_produzione`
- `anomalie`
- `assenze`

### Tabelle tecniche/staging/sync
- `_portale_init` (sentinella init DB)
- `op_aperture_locali` (staging apertura OP)
- `anomalie_locali_staging` (staging anomalie pending sync)
- `anomalie_allegati_staging` (metadati allegati; upload SP non implementato)
- `sync_audit` (audit sync)

### Tabelle esterne/attese ma non create dal bootstrap Flask
- `anagrafica_dipendenti` (usata in `routes_anagrafica.py` e `sync_mansioni`, si assume gia presente)

### Relazioni deducibili (DB)
- `utenti.ruolo_id -> ruoli.id`
- `permessi.ruolo_id -> ruoli.id`
- `info_personali.utente_id -> utenti.id`
- `utenti.mansione_id -> mansione.id`
- `dipendenti.utente_id -> utenti.id` (`ON DELETE SET NULL`)
- `capi_reparto.utente_id -> utenti.id` (`ON DELETE SET NULL`)
- `utenti.capo_reparto_id -> capi_reparto.id` (`ON DELETE SET NULL`)
- `assenze.dipendente_id -> dipendenti.id` (`ON DELETE SET NULL`)
- `assenze.capo_reparto_id -> capi_reparto.id` (`ON DELETE SET NULL`)
- `anomalie.ordine_id` esiste ma la FK esplicita viene rimossa come obsoleta.
- Relazione effettiva usata dal codice per anomalie/ordini:
  - `anomalie.op_lookup_id` (INT SharePoint lookup) <-> `ordini_produzione.sharepoint_item_id` (NVARCHAR, spesso PK naturale dopo migration)

### Relazioni logiche (non sempre vincolate da FK)
- ACL: `pulsanti.(modulo,codice,url)` <-> `permessi.(modulo,azione)` <-> `ruoli`
- Riconciliazioni sync: `dipendenti.title ~ utenti.nome`, `capi_reparto.indirizzo_email ~ utenti.email`
- `anagrafica_dipendenti.utente_id ~ utenti.id` (associazione manuale/admin)

## 6) Template/static esistenti e pagine principali
### Template usati da route (rilevati)
| Route/Page (function) | Template | File |
|---|---|---|
| `/admin` (admin_page) | `admin.html` | `flask_app/modules/admin/routes.py` |
| `/admin/anagrafica` (anagrafica_page) | `admin/anagrafica.html` | `flask_app/modules/admin/routes_anagrafica.py` |
| `/admin/gestione_ruoli` (gestione_ruoli) | `admin/gestione_completa.html` | `flask_app/modules/admin/routes_gestione_ruoli.py` |
| `/admin/gestione_utenti` (gestione_utenti) | `admin/gestione_utenti.html` | `flask_app/modules/admin/routes_gestione_utenti.py` |
| `/admin/log-audit` (admin_log_audit) | `admin_log_audit.html` | `flask_app/modules/admin/routes.py` |
| `/gestione-anomalie/apertura/anomalie` (gestione_anomalie_inserimento_page) | `anomalie_inserimento_collegate.html` | `flask_app/modules/admin/routes.py` |
| `/gestione-anomalie/apertura` (gestione_anomalie_apertura_page) | `anomalie_inserimento_op.html` | `flask_app/modules/admin/routes.py` |
| `/anomalie-menu` (anomalie_menu) | `anomalie_menu.html` | `flask_app/modules/dashboard/routes.py` |
| `/assenze/richiesta_assenze` (richiesta_assenze) | `assenze.html` | `flask_app/modules/assenze/routes.py` |
| `/assenze/` (pagina_assenze) | `assenze_menu.html` | `flask_app/modules/assenze/routes.py` |
| `/assenze/calendario` (calendario_assenze) | `calendario_assenze.html` | `flask_app/modules/assenze/routes.py` |
| `/cambia-password` (cambia_password) | `cambia_password.html` | `flask_app/modules/auth/routes.py` |
| `/dashboard` (dashboard) | `dashboard.html` | `flask_app/modules/dashboard/routes.py` |
| `/gestione-anomalie` (gestione_anomalie_page) | `gestione_anomalie.html` | `flask_app/modules/admin/routes.py` |
| `/` (login) | `login.html` | `flask_app/modules/auth/routes.py` |
| `/assenze/gestione_assenze` (gestione_assenze) | `richieste.html` | `flask_app/modules/assenze/routes.py` |
| `/richieste` (richieste) | `richieste.html` | `flask_app/modules/dashboard/routes.py` |
| `/admin/test` (test) | `test.html` | `flask_app/modules/admin/routes_gestione_ruoli.py` |
| `/admin/utente/<int:user_id>` (utente_dettaglio) | `utente_dettaglio.html` | `flask_app/modules/admin/routes.py` |

### Template presenti in `flask_app/templates/`
- `templates/admin.html`
- `templates/admin.html.bak`
- `templates/admin/anagrafica.html`
- `templates/admin/gestione_completa.html`
- `templates/admin/gestione_permessi.html`
- `templates/admin/gestione_pulsanti.html`
- `templates/admin/gestione_ruoli.html`
- `templates/admin/gestione_utenti.html`
- `templates/admin/tabella_permessi.html`
- `templates/admin/tabella_pulsanti.html`
- `templates/admin_log_audit.html`
- `templates/anomalie_inserimento_collegate.html`
- `templates/anomalie_inserimento_op.html`
- `templates/anomalie_menu.html`
- `templates/approvazioni.html`
- `templates/assenze.html`
- `templates/assenze.html.bak`
- `templates/assenze_menu.html`
- `templates/calendario_assenze.html`
- `templates/cambia_password.html`
- `templates/dashboard.html`
- `templates/dashboard.html.bak`
- `templates/gestione_anomalie.html`
- `templates/index.html`
- `templates/index.html.bak`
- `templates/layout.html`
- `templates/layout.html.bak`
- `templates/login.html`
- `templates/richieste.html`
- `templates/richieste.html.bak`
- `templates/successo.html`
- `templates/successo.html.bak`
- `templates/test.html`
- `templates/utente_dettaglio.html`

### Template referenziati dal codice (subset)
- `admin.html`
- `admin/anagrafica.html`
- `admin/gestione_completa.html`
- `admin/gestione_utenti.html`
- `admin_log_audit.html`
- `anomalie_inserimento_collegate.html`
- `anomalie_inserimento_op.html`
- `anomalie_menu.html`
- `assenze.html`
- `assenze_menu.html`
- `calendario_assenze.html`
- `cambia_password.html`
- `dashboard.html`
- `gestione_anomalie.html`
- `login.html`
- `richieste.html`
- `test.html`
- `utente_dettaglio.html`

### Static presenti in `flask_app/static/`
- `static/CN.png`
- `static/fotocard/137.jpg`
- `static/img/avatar_placeholder.png`
- `static/logo.jpg`
- `static/logo.png`

### Pagine principali (funzionali)
- Login / cambio password: `login.html`, `cambia_password.html`
- Dashboard e richieste utente: `dashboard.html`, `richieste.html`
- Assenze: `assenze_menu.html`, `assenze.html`, `calendario_assenze.html`, `richieste.html` (riuso per gestione/approvazioni)
- Anomalie: `anomalie_menu.html`, `gestione_anomalie.html`, `anomalie_inserimento_op.html`, `anomalie_inserimento_collegate.html`
- Admin: `admin.html`, `utente_dettaglio.html`, `admin_log_audit.html`
- Admin specializzato: `admin/gestione_utenti.html`, `admin/gestione_completa.html`, `admin/anagrafica.html`

## 7) Dipendenze e punti critici
### Dipendenze runtime (osservate)
- Web: `Flask`, `Flask-WTF`, `Flask-Limiter`, `Jinja2`, `Werkzeug`
- DB: `pyodbc` + driver ODBC SQL Server (18/17/...)
- Directory/LDAP: `ldap3`
- SharePoint / Microsoft Graph: `requests`, `msal`
- Data/export/media: `pandas`, `openpyxl`, `Pillow`, `reportlab`, `pytz`
- File locali runtime: `config.ini`, `temp/...`, `static/fotocard/`, `app.log`

### Gap / incongruenze dipendenze
- `pyodbc` e `ldap3` sono usati dal codice ma non risultano in `requirements.txt` (rischio bootstrap/CI).
- `PyJWT` e presente in `requirements.txt` ma non viene usato nel codice Flask.

### Punti critici tecnici (migrazione)
- Secrets in chiaro in `config.ini` (credenziali admin locale e Microsoft Graph, ecc.).
- Doppia route `/`: `auth.login` e `app.index` (possibile shadowing/ambiguita routing).
- Authz incoerente: mix tra `require_roles()` e controlli manuali su sessione.
- `require_roles()` ignora i ruoli passati al decorator e basa l'accesso sull'ACL dinamica del path.
- Naming ruoli non uniforme (`utente/user/dipendente/gestore/HR`).
- DDL/migrazioni eseguiti a runtime nella web app (assenza di framework migrazioni formale).
- Thread background dentro `create_app()` (preload cache + scheduler sync): rischio duplicazione in debug/multi-worker.
- Forte accoppiamento a Microsoft Graph nel request cycle (latenza/fallimenti impattano pagine).
- Doppia source of truth (Graph live vs DB replica) con possibili inconsistenze temporali.
- CSRF solo parzialmente applicato (`WTF_CSRF_CHECK_DEFAULT=False`, controlli manuali solo su alcune POST).
- Workflow allegati anomalie incompleto: staging locale presente, upload SharePoint non implementato.
- Incongruenza `routes_anagrafica.py`: importa `_validate_csrf_or_raise`/`ValidationError` da `modules.utils`, ma i simboli risultano definiti altrove (`admin/routes.py`).
- Presenza di codice legacy sqlite (import/commenti/DDL) che aumenta il debito tecnico nel porting.

## 8) Piano migrazione proposto (8 step)
### Cosa portare per primo
- Primo blocco: **identity + session + ACL + accesso DB core** (`utenti`, `ruoli`, `pulsanti`, `permessi`) in Django.
- Motivo: abilita login/autorizzazione e routing dei moduli migrati senza dover portare subito tutte le integrazioni SharePoint.

### Step-by-step
1. **Freeze e baseline funzionale**
   - Congelare schema SQL Server attuale (DDL) e catalogare i flow critici.
   - Aggiungere test smoke minimi sul Flask corrente (login, dashboard, assenze, admin, sync).

2. **Design modelli Django (mapping schema)**
   - Modellare tabelle core + replica SharePoint in Django (inizialmente anche `managed=False` se serve).
   - Definire strategia di compatibilita per `utenti.ruolo`, `utenti.ruoli`, `utenti.ruolo_id`.

3. **Port auth/session + backend AD/LDAP**
   - Implementare auth Django con backend locale DB e backend AD opzionale.
   - Portare logout, cambio password, `attivo`, `deve_cambiare_password`, auto-provisioning AD.

4. **Port ACL dinamica e menu (`pulsanti`/`permessi`)**
   - Portare `check_permesso` come service/middleware Django.
   - Portare dashboard base e context processor per menu dinamico.
   - Stabilire mapping URL Django <-> `pulsanti.url` (fondamentale per cutover graduale).

5. **Port viste read-mostly (basso rischio)**
   - Dashboard, richieste, menu assenze/anomalie, calendario + API eventi da DB locale.
   - Dove possibile, preferire DB replica al Graph live per stabilita/performance.

6. **Port moduli admin core**
   - Gestione utenti, ruoli/permessi, anagrafica, log audit, export utenti/PDF scheda.
   - Spostare SQL raw in repository/service layer e centralizzare validazione/CSRF.

7. **Port sync SharePoint e workflow anomalie staging come job separati**
   - Estrarre `routes_sync.py` in servizi + management commands / task queue (Celery/RQ/APScheduler esterno).
   - Portare workflow staging anomalie e completare upload allegati SharePoint.

8. **Cutover progressivo e decommission Flask**
   - Reverse proxy con routing progressivo per path.
   - Allineare `pulsanti.url`, eseguire smoke test, freeze scritture sui moduli migrati, spegnimento finale Flask.

## Appendice: note pratiche per Django 5.2 LTS
- Separare per dominio: `accounts`, `acl`, `assenze`, `anomalie`, `sync_sharepoint`, `admin_portale`.
- Portare integrazioni Graph/LDAP in adapter/service layer testabili (no chiamate dirette nelle view).
- Sostituire scheduler thread in-process con job scheduler esterno.
