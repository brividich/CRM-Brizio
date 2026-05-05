# Report Completo NOVICROM HUB

**Data:** 2026-05-04
**Versione Portale:** 1.0.1
**Autore:** Analisi Multiagent

---

## 1. Executive Summary

NOVICROM HUB è il portale aziendale interno di Constructions Novicrom SRL, sviluppato con Django 5.2 e Python 3.11+. Il portale gestisce workflow operativi, sicurezza, compliance, automazioni e governance ACL granulare.

### Metriche Chiave

| Metrica | Valore |
|---------|--------|
| App Django Custom | 22 |
| Modelli Totali | 100+ |
| Versione | 1.0.1 (2026-04-28) |
| Stack | Django 5.2, Python 3.11+, SQL Server |
| Runtime | Waitress + IIS HttpPlatformHandler |
| ACL v2 Coverage | 200+ route con binding |
| ACL Legacy Fallback | 68 route senza binding |

### Punti di Forza Principali

1. **Architettura SSR Puro** - Server-side rendering con Django templates, HTMX per interazioni dinamiche
2. **Governance ACL Granulare** - Sistema ACL v2 con policy-as-data e fallback legacy per migrazione incrementale
3. **Integrazioni Native Microsoft 365** - Graph API per Outlook Calendar, SharePoint, Teams
4. **Storage Dual-Mode** - SQLite in sviluppo, SQL Server in produzione
5. **Deployment Windows-First** - Setup wizard 14 step con PyInstaller, IIS integration
6. **Audit Trail Completo** - Tracciamento automatico operazioni CRUD
7. **Automazioni Visuale** - Designer drag-and-drop con trigger SQL
8. **Dashboard Personalizzabile** - Widget KPI cross-modulo con drag-and-drop

---

## 2. Architettura del Portale

### 2.1 Stack Tecnologico Completo

#### Runtime & Framework
- **Python:** 3.11+
- **Django:** 5.2.11
- **WSGI Produzione:** Waitress via HttpPlatformHandler (IIS)

#### Database
- **Dev:** SQLite
- **Test/Prod:** SQL Server via `mssql-django` + `pyodbc 5.3.0`
- **Driver ODBC:** 18/17/13 (auto-rilevato)

#### Autenticazione
- **Cascata:** `AxesStandaloneBackend` → `SQLServerLegacyBackend` → `LDAPBackend` → `ModelBackend`
- **Rate-limiting:** django-axes (5 tentativi, 1 min cooldown)
- **Session:** Timeout inattività configurabile (default 3600s)

#### Frontend
- **Rendering:** SSR con Django templates
- **Interazioni:** HTMX 1.27.0
- **CSS:** Custom, nessun framework JS
- **Static:** `collectstatic` con `STATIC_ROOT` configurabile

#### Cache
- **Dev:** `LocMemCache`
- **Prod:** `DatabaseCache` su SQL Server

#### Background Processing
- **Queue:** `django-q2` 1.9.0
- **Processor:** Windows Scheduled Tasks
- **Mailbox Poller:** `process_approval_mailbox` via Graph API

#### Osservabilità
- **Logging:** `SafeTimedRotatingFileHandler` multi-process
- **SQL Logging:** Opzionale con `SQL_LOG_ENABLED`
- **Audit:** Database `AuditLog` table
- **Monitoring:** Issue tracking interno, alert email

### 2.2 Pattern Architetturali Chiave

#### SSR Puro con Django Templates
- Nessun framework JavaScript lato client
- Rendering server-side completo
- HTMX per interazioni dinamiche

#### Layer ACL Doppio (v2 + Fallback Legacy)
- **ACL Canonico v2:** policy-as-data con `PermissionDefinition`, `RoutePermissionBinding`, `RolePermissionGrant`, `UserPermissionGrant`
- **Fallback Legacy:** `pulsanti` + `permessi` per migrazione incrementale
- Resolver route-per-route: se esiste binding canonico usa v2, altrimenti scivola su legacy
- Logging throttled (5m/route) per audit del fallback

#### Storage Dual-Mode
- **Dev:** SQLite con `LocMemCache`
- **Test/Prod:** SQL Server con `DatabaseCache` (token Graph, ACL, sessioni)
- Driver ODBC 18/17/13 auto-rilevato

#### Deploy Windows-First
- Waitress + HttpPlatformHandler + IIS
- Installer PyInstaller `SetupWizard.exe` (14 step)
- Windows Scheduled Tasks per background processing

#### Cache Condivisa Multi-Worker
- `DatabaseCache` su SQL Server per sincronizzazione tra worker IIS
- Token Graph cached con lock in-process + backend condiviso

#### Audit Trail Fire-and-Forget
- `core.audit.log_action()` su tabella `AuditLog`
- Tracciamento completo operazioni CRUD rilevanti

### 2.3 Integrazioni Esterne

#### Microsoft Graph API
- **File chiave:** `core/graph_utils.py`
- **Uso:**
  - SharePoint sync (assenze, incidenti)
  - Outlook Calendar (scadenze assets)
  - Teams chat flow (approvazioni)
  - Mailbox polling (approvazioni email)
- **Cache:** Token MSAL cached con 60s buffer ante scadenza
- **Configurazione:** `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`, `GRAPH_SITE_ID`, `GRAPH_LIST_ID_*`

#### LDAP / Active Directory
- **File chiave:** `core/accounts/backends.py` (LDAPBackend)
- **Uso:**
  - Auth utenti con `LDAPBackend`
  - Sync anagrafica via `sync_ldap_users`
  - SSO SPNEGO opzionale
- **Configurazione:** `LDAP_ENABLED`, `LDAP_SERVER`, `LDAP_DOMAIN`, `LDAP_UPN_SUFFIX`, `LDAP_TIMEOUT`, `LDAP_SERVICE_USER`, `LDAP_SERVICE_PASSWORD`, `LDAP_BASE_DN`, `LDAP_USER_FILTER`, `LDAP_GROUP_ALLOWLIST`

#### SMTP
- **Uso:** Notifiche utente, approvazioni email, reminder procedure
- **Configurazione:** `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL`, `SITE_URL`

#### Entra Application Proxy
- **Uso:** Pubblicazione selettiva di `/approval-actions/*` per approvazioni one-click fuori rete
- **File chiave:** `automazioni/approval_proxy_urls.py`

#### Health Checks Runtime
- **File chiave:** `monitoring/health.py`
- **Endpoint:** `/healthz` (liveness), `/readyz` (readiness)
- **Check:** DB, cache, Graph token, LDAP, SMTP, automation queue
- **Cache:** Risultato memoizzato per `READYZ_TTL_SECONDS` (default 10s)
- **IP Allowlist:** `HEALTHZ_ALLOWED_IPS` (default loopback)

### 2.4 Diagramma Architettura

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLIENT (Browser)                          │
│                    (SSR + HTMX + No JS Framework)                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      IIS + HttpPlatformHandler                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Waitress (WSGI)                           │
│                    (Multi-worker IIS pool)                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Django 5.2 Application                        │
├─────────────────────────────────────────────────────────────────┤
│  Middleware Stack:                                                │
│  - SecurityMiddleware                                            │
│  - AdaptiveSecureCookieMiddleware                                │
│  - SessionMiddleware                                             │
│  - HtmxMiddleware                                                 │
│  - CommonMiddleware                                               │
│  - CsrfViewMiddleware                                             │
│  - EnsureCSRFCookieMiddleware                                    │
│  - AuthenticationMiddleware                                      │
│  - AxesMiddleware (rate-limiting)                                │
│  - ImpersonationMiddleware                                       │
│  - IssueCaptureMiddleware                                        │
│  - SessionIdleTimeoutMiddleware                                  │
│  - SetupRequiredMiddleware                                       │
│  - ACLMiddleware (v2 + legacy fallback)                          │
│  - NotizieMandatoryMiddleware                                    │
│  - MessagesMiddleware                                             │
│  - XFrameOptionsMiddleware                                        │
├─────────────────────────────────────────────────────────────────┤
│  URL Routing:                                                     │
│  - /healthz, /readyz (health checks)                              │
│  - /setup/ (setup wizard)                                        │
│  - /approval-actions/ (Entra Application Proxy)                  │
│  - /<module>/ (22 app Django)                                    │
├─────────────────────────────────────────────────────────────────┤
│  Views & Templates:                                               │
│  - SSR con Django templates                                      │
│  - HTMX per aggiornamenti parziali                               │
│  - No JS framework lato client                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Layer Servizi                                │
├─────────────────────────────────────────────────────────────────┤
│  ACL v2:                                                          │
│  - PermissionDefinition                                          │
│  - RoutePermissionBinding                                        │
│  - RolePermissionGrant                                           │
│  - UserPermissionGrant                                           │
│  - Fallback Legacy (pulsanti + permessi)                         │
├─────────────────────────────────────────────────────────────────┤
│  Integrazioni:                                                    │
│  - Microsoft Graph (Outlook, SharePoint, Teams)                  │
│  - LDAP/AD (autenticazione, sync utenti)                         │
│  - SMTP (notifiche email)                                         │
│  - Entra Application Proxy (approvazioni esterne)                │
├─────────────────────────────────────────────────────────────────┤
│  Background Processing:                                           │
│  - django-q2 queue processor                                      │
│  - Windows Scheduled Tasks                                       │
│  - Mailbox polling (Graph API)                                    │
├─────────────────────────────────────────────────────────────────┤
│  Audit Trail:                                                     │
│  - AuditLog table                                                 │
│  - Impersonation tracking                                        │
│  - Fire-and-forget logging                                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Data Layer                                   │
├─────────────────────────────────────────────────────────────────┤
│  Database:                                                        │
│  - Dev: SQLite                                                    │
│  - Test/Prod: SQL Server (mssql-django + pyodbc)                 │
│  - Driver ODBC: 18/17/13 (auto-rilevato)                         │
├─────────────────────────────────────────────────────────────────┤
│  Cache:                                                           │
│  - Dev: LocMemCache                                               │
│  - Prod: DatabaseCache (multi-worker sync)                      │
│  - Token Graph: cached con 60s buffer                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      External Services                             │
├─────────────────────────────────────────────────────────────────┤
│  - Microsoft Graph API                                            │
│  - LDAP/Active Directory                                          │
│  - SMTP Server                                                    │
│  - Entra Application Proxy                                        │
└─────────────────────────────────────────────────────────────────┘
```

### 2.5 Routing e Middleware Stack

#### Middleware Stack (ordine esecuzione)
```python
[
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.AdaptiveSecureCookieMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "core.csrf_cookie_middleware.EnsureCSRFCookieMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "axes.middleware.AxesMiddleware",
    "core.middleware.ImpersonationMiddleware",
    "monitoring.middleware.IssueCaptureMiddleware",
    "core.session_middleware.SessionIdleTimeoutMiddleware",
    "setup_wizard.middleware.SetupRequiredMiddleware",
    "core.middleware.ACLMiddleware",
    "notizie.mandatory_middleware.NotizieMandatoryMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
```

#### Prefissi URL Esenti da Autenticazione
```python
MIDDLEWARE_EXEMPT_PREFIXES = (
    "/health", "/healthz", "/readyz", "/version", "/check",
    "/login", "/logout", "/cambia-password",
    "/static/", "/media/", "/admin/", "/favicon",
    "/setup/", "/admin-portale/hub/",
    "/monitoring/report-problem/",
    "/admin-portale/automazioni/approvazione/",
    "/automazioni/approvazione/",  # token-based
    "/approval-actions/",          # token-based, Entra Application Proxy
)
```

---

## 3. Moduli Funzionali

### 3.1 Catalogo Completo delle App

Il portale è composto da **22 app Django custom** organizzate per area funzionale:

#### Core Platform (7 app)

| App | Scopo | Modelli Chiave |
|-----|-------|----------------|
| **core** | Infrastruttura e autenticazione | Profile, NavigationItem, AuditLog, SiteConfig, Notifica, UserExtraInfo |
| **dashboard** | Home KPI personalizzabile | DashboardConfig, Widget |
| **admin_portale** | Pannello admin custom | ACL canonico, diagnostica, mappa permessi |
| **hub_tools** | Hub strumenti interni | Module Manager, DB Manager, Schema infografica |
| **setup_wizard** | Wizard primo setup | 14 step con installer standalone |
| **monitoring** | Osservabilità interna | Issue tracking, alert email, health checks |
| **axes** | Rate-limiting login | django-axes |

#### Operations (4 app)

| App | Scopo | Modelli Chiave |
|-----|-------|----------------|
| **anagrafica** | Dipendenti + fornitori | Fornitore, RuoloOperativo, Mansione, Qualifica |
| **assets** | Inventario IT e produzione | Asset, WorkOrder, PeriodicVerification, SoftwareLicense, PlantLayout |
| **attrezzature** | Gestione Attrezzatura | Attrezzatura, AttrezzaturaTask, AttrezzaturaKickoffLink |
| **tasks** | Portfolio KICK-OFF progetti | Project, Task, KickoffMeeting, VRFRiskAssessment |
| **planimetria** | Wrapper compatibile | Reindirizzamenti verso assets |

#### HR & Workflow (5 app)

| App | Scopo | Modelli Chiave |
|-----|-------|----------------|
| **assenze** | Richieste ferie/permessi | CertificazionePresenza |
| **anomalie** | Segnalazione anomalie | Anomalia |
| **tickets** | Ticket interni | Ticket, TicketCommento, TicketIntervento |
| **timbri** | Report timbrature | OperatoreTimbri, RegistroTimbro |
| **notizie** | Bacheca comunicazioni | Notizia, NotiziaAudience, NotiziaLettura |

#### Sicurezza & Compliance (5 app)

| App | Scopo | Modelli Chiave |
|-----|-------|----------------|
| **dpi** | Dispositivi Protezione Individuale | CategoriaDPI, RichiestaDPI, ConsegnaDPI |
| **diario_preposto** | Diario preposto sicurezza | SegnalazionePreposto, SegnalazioneAllegato |
| **rilevazione_incidenti** | Incidenti sicurezza | RilevazioneIncidente (cache SharePoint) |
| **procedure_refresh** | Presa visione procedure | ProcedureDocument, ProcedureRevision, ProcedureCampaign |
| **rentri** | Tracciabilità rifiuti RENTRI | RegistroRifiuti |

#### Automazione (1 app)

| App | Scopo | Modelli Chiave |
|-----|-------|----------------|
| **automazioni** | Designer visuale | AutomationRule, AutomationCondition, AutomationAction, AutomationApproval |

### 3.2 Funzionalità Principali per Area

#### Core Platform
- **Dashboard personalizzabile** con widget drag&drop per utente
- **Sistema ACL v2** con policy-as-data e fallback legacy
- **Navigazione dinamica** con registry per ruolo
- **Audit trail** completo con tracciamento operazioni
- **Impersonation** controllata e tracciabile
- **Setup wizard** 14 step con installer PyInstaller
- **Health checks** runtime con IP whitelist

#### Operations
- **Inventario asset** completo con categorie e campi dinamici
- **Ordini di lavoro** e manutenzioni periodiche
- **Contratti assistenza** e licenze software
- **Planimetria officina** con posizionamento asset
- **Portfolio KICK-OFF** con numerazione automatica
- **Diagramma Gantt** per pianificazione progetti
- **Incontri di avanzamento** con integrazione Outlook
- **VRF MOD.073** (upload o compilazione online)
- **Gestione attrezzature** con lifecycle operativo

#### HR & Workflow
- **Richieste assenza** con approvazione capo reparto
- **Calendario presenze** con sync SharePoint
- **Ticket IT/manutenzione** con interventi e analitiche
- **Report timbrature** da DB legacy
- **Bacheca notizie** con audience targeting

#### Sicurezza & Compliance
- **Gestione DPI** con richieste, approvazione, consegna
- **Diario preposto** per segnalazioni sicurezza
- **Rilevazione incidenti** con integrazione SharePoint
- **Presa visione procedure** MT/MTSI con campagne
- **Tracciabilità rifiuti** RENTRI

#### Automazioni
- **Designer visuale** drag-and-drop
- **Trigger SQL** → event queue
- **Approvazioni** via email/Teams/Graph
- **Queue processor** con polling
- **Template email** riutilizzabili

### 3.3 Workflow e Automazioni Principali

#### Workflow Chiave

1. **Ticket:** Apertura → In carico → Risolto → Chiuso
2. **DPI:** Richiesta → Approvato → Consegnato → Scaduto
3. **Assets:** In magazzino → In uso → In riparazione → Dismesso
4. **Tasks:** TODO → In progress → Done
5. **Kick-off:** Creazione → VRF → Gantt → Esecuzione

#### Automazioni Principali

1. **SQL Trigger → Event Queue**
   - Trigger SQL Server inseriscono in `automation_event_queue`
   - Worker processa coda automazioni

2. **Approvazioni**
   - Workflow approvazione con email/Teams
   - Polling Graph per reply approvative

3. **Promemoria**
   - Management command per notifiche scadenze
   - Integrazione Outlook calendar

### 3.4 Pattern Views/Templates

#### Pattern comune:
1. **Lista** - `*_list()` con filtri GET, paginazione
2. **Dettaglio** - `*_detail()` con dati correlati
3. **Creazione** - `*_nuovo()` o `*_create()` con form
4. **Modifica** - `*_edit()` con form
5. **Eliminazione** - `*_delete()` con conferma
6. **Impostazioni** - `*_impostazioni()` per configurazione modulo
7. **API** - `api_*` per operazioni AJAX

#### Pattern template:
- `pages/lista.html` - Template lista standard
- `pages/dettaglio.html` - Template dettaglio
- `pages/nuovo.html` - Template creazione
- `pages/impostazioni.html` - Template impostazioni

---

## 4. Analisi Sicurezza

### 4.1 Sistema ACL v2 e Legacy Fallback

Il sistema di controllo accessi implementa un'architettura ibrida con layer canonico v2 e fallback legacy:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Richiesta HTTP                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  ACLMiddleware                                                   │
│  - Verifica autenticazione                                      │
│  - Verifica onboarding completato                               │
│  - Verifica impersonation attiva                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Bypass Superuser                                                │
│  - request.user.is_superuser → ALLOW                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Bypass Legacy Admin                                             │
│  - is_legacy_admin() → ALLOW                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  ACL Canonico v2                                                │
│  1. resolve_canonical_target()                                   │
│     - Cerca RoutePermissionBinding per route_name                │
│     - Cerca RoutePermissionBinding per path_pattern               │
│     - Strategie: EXACT, PREFIX, REGEX                           │
│  2. evaluate_permission_code_access()                            │
│     - Verifica PermissionDefinition                             │
│     - Verifica RolePermissionGrant                              │
│     - Verifica UserPermissionGrant                              │
│     - Compat bridge con legacy permessi                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Fallback Legacy (solo se binding canonico assente)             │
│  - check_permesso() → _match_pulsante()                          │
│  - Mapping modulo+azione → perm_map per ruolo_id                │
│  - Cache: legacy_cache.py (TTL 120s)                            │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Pipeline di Autenticazione

Il sistema implementa una pipeline di autenticazione a 4 livelli con fallback progressivo:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Richiesta di Autenticazione                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. AxesStandaloneBackend (django-axes)                          │
│     - Rate limiting: 5 tentativi, lockout 1 ora                   │
│     - Template custom: core/pages/lockout.html                   │
│     - AXES_RESET_ON_SUCCESS = True                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. SQLServerLegacyBackend                                       │
│     - Autenticazione tramite tabelle legacy SQL Server          │
│     - Supporto alias username (dominio\alias, alias@dominio)     │
│     - Password hash con werkzeug.security.check_password_hash   │
│     - Flag *AD_MANAGED* per password gestite da AD               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. LDAPBackend                                                  │
│     - Autenticazione LDAP/AD via ldap3                          │
│     - Supporto NTLM e SIMPLE authentication                      │
│     - Timeout configurabile (default 5s)                         │
│     - Fail-closed su errori LDAP bind                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. ModelBackend (Django standard)                               │
│     - Fallback finale per utenti Django locali                  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 Middleware di Sicurezza

#### AdaptiveSecureCookieMiddleware
- Downgrade CSRF/session cookies su HTTP non-HTTPS
- Protezione contro downgrade attacchi su HTTPS

#### SessionIdleTimeoutMiddleware
- Timeout sessione inattiva (default 3600s)
- Logout automatico dopo timeout
- Esenzioni per MIDDLEWARE_EXEMPT_PREFIXES

#### EnsureCSRFCookieMiddleware
- Pre-generazione cookie CSRF
- Evita errori "CSRF cookie not set"
- Attivo solo per richieste HTML

#### ACLMiddleware
- Verifica autenticazione
- Verifica onboarding completato
- Gestisce impersonation
- Risolve ACL v2 con fallback legacy
- Logging throttled per fallback legacy

#### ImpersonationMiddleware
- Solo is_legacy_admin() può avviare
- Session key: _impersonation_state
- Stop path: /impersonation/stop
- Tracciabilità completa

### 4.4 Protezione Endpoint API/AJAX

#### Rilevamento Richieste JSON
```python
def _is_json_request(request) -> bool:
    # Rileva richieste API/AJAX tramite:
    - Accept: application/json
    - Content-Type: application/json
    - X-Requested-With: XMLHttpRequest
    - Path: /api/
```

#### Risposte API Standardizzate
```python
# 401 Unauthenticated
{
    "ok": False,
    "error": "Autenticazione richiesta.",
    "reason": "unauthenticated",
    "login_url": "/login?next=..."
}

# 403 Forbidden
{
    "ok": False,
    "error": "Permessi insufficienti.",
    "reason": "forbidden"
}
```

### 4.5 Gestione Secrets e Credentials

#### Variabili d'Ambiente
```python
# Credenziali LDAP
LDAP_ENABLED, LDAP_SERVER, LDAP_DOMAIN, LDAP_UPN_SUFFIX,
LDAP_TIMEOUT, LDAP_SERVICE_USER, LDAP_SERVICE_PASSWORD, LDAP_BASE_DN

# Credenziali Database
DB_ENGINE, DB_DRIVER, DB_NAME, DB_HOST, DB_USER, DB_PASSWORD, DB_TRUST_CERT

# Credenziali Email
EMAIL_BACKEND, EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER,
EMAIL_HOST_PASSWORD, EMAIL_USE_TLS, EMAIL_USE_SSL

# Credenziali Microsoft Graph
GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET,
GRAPH_SHAREPOINT_SITE_ID

# Security
DJANGO_SECRET_KEY, SITE_URL, HEALTHZ_ALLOWED_IPS, TRUSTED_PROXY_IPS
```

#### File Sensibili (NON nel repo)
```
django_app/.env              # Credenziali runtime
DIPENDENTI.csv              # Dati reali dipendenti
db.sqlite3                  # DB locale con dati di test
build/ e dist/              # Contengono asta.exe e utenti.db
```

### 4.6 Health Checks Runtime

#### /healthz (Liveness)
- Verifica integrità base
- IP whitelist: HEALTHZ_ALLOWED_IPS
- Default: solo 127.0.0.1 e ::1
- Configurabile per proxy IIS/load balancer

#### /readyz (Readiness)
- Endpoint readiness con cache
- READYZ_TTL_SECONDS: default 10s
- Cache per evitare DoS su integrazioni
- Check configurabili: READYZ_CHECKS_ENABLED
- Check disponibili: db_default, db_legacy, cache, graph_token, ldap, smtp, automation_queue

### 4.7 Vulnerabilità Potenziali Identificate

#### Vulnerabilità di Media Criticità

**V1: Session Fixation (Rischio Medio)**
- Non c'è evidenza di session regeneration dopo login
- Le sessioni potrebbero essere riutilizzate
- **Raccomandazione:** Implementare `request.session.cycle_key()` dopo login

**V2: CSRF Token Leakage (Rischio Basso)**
- Potenziale esposizione su HTTP non-HTTPS
- **Raccomandazione:** Forzare HTTPS in produzione, configurare HSTS headers

**V3: LDAP Injection (Rischio Basso)**
- `_ldap_escape_filter()` implementa escaping base
- Non copre tutti i caratteri speciali LDAP
- **Raccomandazione:** Usare ldap3.escape_filter_chars() se disponibile

#### Vulnerabilità di Bassa Criticità

**V4: Information Disclosure (Rischio Basso)**
- Error messages dettagliati in alcuni casi
- **Raccomandazione:** Verificare DEBUG=False in produzione

**V5: Rate Limiting Incompleto (Rischio Basso)**
- Rate limiting solo su login
- **Raccomandazione:** Implementare rate limiting su API endpoints, password reset

**V6: Cache Poisoning (Rischio Basso)**
- Cache ACL legacy con TTL 120s
- **Raccomandazione:** Implementare cache invalidation immediata

#### Vulnerabilità di Configurazione

**V7: Trusted Proxy IPs (Rischio Medio)**
- Default vuoto: nessun proxy fidato
- Se configurato male, possibile IP spoofing
- **Raccomandazione:** Documentare configurazione proxy, validare IP proxy

**V8: Health Checks Exposure (Rischio Basso)**
- Default solo loopback
- Se configurato male, possibile information disclosure
- **Raccomandazione:** Verificare configurazione in produzione

### 4.8 Raccomandazioni di Sicurezza Prioritarie

#### Priorità Alta

**R1: Forzare HTTPS in Produzione**
```python
# In config/settings/prod.py
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000  # 1 anno
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

**R2: Implementare Session Regeneration**
```python
# In core/views.py login view
from django.contrib.auth import login
def login_view(request):
    # ... autenticazione ...
    login(request, user)
    request.session.cycle_key()  # ← Aggiungere
    # ... redirect ...
```

**R3: Configurare Proper Logging**
```python
# In config/settings/base.py
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'secure': {
            'format': '%(asctime)s %(levelname)s %(process)d %(request)s %(message)s'
        },
    },
    'handlers': {
        'file': {
            'level': 'WARNING',
            'class': 'logging.FileHandler',
            'filename': '/var/log/novicrom/security.log',
            'formatter': 'secure',
        },
    },
    'loggers': {
        'django.security': {
            'handlers': ['file'],
            'level': 'WARNING',
            'propagate': True,
        },
        'core.acl': {
            'handlers': ['file'],
            'level': 'WARNING',
            'propagate': True,
        },
    },
}
```

#### Priorità Media

**R4: Implementare Rate Limiting Esteso**
- Implementare rate limiting su API endpoints
- Implementare rate limiting su password reset
- Implementare rate limiting su operazioni sensibili

**R5: Validare Configurazione Proxy**
- Documentare configurazione proxy
- Validare IP proxy in whitelist
- Monitorare accessi da IP non fidati

**R6: Implementare Cache Invalidation**
- Invalida cache ACL immediata su cambiamenti permessi
- Considerare TTL più corto per ambienti critici

#### Priorità Bassa

**R7: Implementare Content Security Policy**
- Configurare CSP headers
- Limitare script sources

**R8: Implementare X-Content-Type-Options**
- Configurare security headers
- Protezione contro MIME sniffing

**R9: Implementare Referrer Policy**
- Configurare referrer policy
- Limitare information leakage

---

## 5. Informazioni Varie

### 5.1 Metriche e Statistiche

#### Dimensione e Complessità
- **22 app Django custom** raggruppate per area funzionale
- **25+ moduli** totali (inclusi moduli di sistema)
- **Versione corrente:** 1.0.1 (2026-04-28)
- **Stack tecnologico:** Django 5.2, Python 3.11+, SQL Server (test/prod), SQLite (dev)
- **Runtime:** Waitress + IIS HttpPlatformHandler

#### Modelli per App
| App | Modelli | Note |
|-----|---------|------|
| `core` | 23+5 legacy | Profile, NavigationItem, AuditLog, SiteConfig, Notifica, ecc. |
| `assets` | 27 | Asset, WorkOrder, PeriodicVerification, SoftwareLicense, ecc. |
| `attrezzature` | 8 | Attrezzatura, AttrezzaturaTask, AttrezzaturaKickoffLink, ecc. |
| `tasks` | 14+ | Project, Task, KickoffMeeting, MeetingIssue, VRFRiskAssessment, ecc. |
| `automazioni` | 9 | AutomationRule, AutomationCondition, AutomationAction, ecc. |
| `tickets` | 7 | Ticket, TicketCommento, TicketAllegato, TicketImpostazioni, ecc. |
| `dpi` | 5 | CategoriaDPI, RichiestaDPI, ConsegnaDPI, ecc. |
| `procedure_refresh` | 6 | ProcedureDocument, ProcedureRevision, ProcedureCampaign, ecc. |

#### Integrazioni
- **Microsoft Graph:** Outlook Calendar, SharePoint, Outlook Mail
- **LDAP/AD:** Autenticazione e sincronizzazione utenti
- **SMTP:** Notifiche email
- **Entra Application Proxy:** Approvazioni esterne

#### Governance ACL
- **ACL v2 canonico** con fallback legacy per migrazione incrementale
- **200+ route** con binding ACL v2 creati automaticamente
- **68 route** senza binding (sotto soglia 222 del release guard)
- **Layer ACL doppio:** policy-as-data + fallback legacy

### 5.2 Debito Tecnico Noto

#### 1. SQL Raw Inline
- **Posizione:** `core/context_processors.py` e alcune views
- **Problema:** Query SQL inline invece di ORM
- **Impatto:** Manutenibilità e sicurezza
- **Priorità:** Media

#### 2. Cache Graph Primitiva
- **Posizione:** Cache Graph (`Lock + dict`)
- **Problema:** Non sicura su multi-process (wsgi multi-worker)
- **Impatto:** Race condition in produzione
- **Priorità:** Alta

#### 3. Planimetria Vuota
- **Posizione:** `planimetria/models.py`
- **Problema:** Solo commento, nessuna logica
- **Impatto:** Modulo non funzionante
- **Priorità:** Bassa

#### 4. Module Registry Incompleto
- **Posizione:** `module_registry.py`
- **Problema:** Solo `assets` registrato
- **Impatto:** Altri moduli non brandizzabili
- **Priorità:** Media

#### 5. Flask Compatibility Layer
- **Posizione:** `core/legacy_flask_views.py`
- **Problema:** 62 route Flask coperte (27 native, 35 redirect/410)
- **Impatto:** Complessità manutenzione
- **Priorità:** Bassa

### 5.3 Direzione Corrente del Prodotto

#### Branding e Identità
- **NOVICROM HUB** come brand canonico
- Nomi storici (`Portale Novicrom`) solo per deployment/legacy
- Branding modulo via `module_branding.<module>` in SiteConfig

#### Architettura Target
- **SSR puro** con Django templates
- **Layer ACL doppio:** v2 + fallback legacy
- **Storage dual-mode:** SQLite dev / SQL Server prod
- **Deploy Windows-first:** Waitress + IIS
- **Cache condivisa multi-worker:** DatabaseCache

#### Governance ACL
- Migrazione incrementale route-per-route verso ACL v2
- Bootstrap automatico per copertura route
- Fallback legacy finché copertura non completa
- Diagnostica combinata legacy + canonical

#### Moduli e Workflow
- Ogni modulo mantiene pagina impostazioni dedicata
- Percorsi canonici: `/<modulo>/impostazioni/`
- URL legacy compatibili via redirect
- Branding modulo configurabile

#### Security Center AI
- Priorità a workflow sicurezza/compliance
- Audit trail e source-of-truth boundaries
- Privacy-preserving examples
- SharePoint/Graph come fonte di verità

#### Automazioni
- Designer visuale con trigger SQL
- Approvazioni fail-closed e deduplicate
- Portabilità email/Teams/Graph
- Queue processor con polling

### 5.4 Best Practices

#### Development
- Usare SQLite in sviluppo per velocità
- Usare SQL Server in test/produzione per realismo
- Configurare .env locale per credenziali
- Eseguire migrate con settings appropriati

#### Testing
- Eseguire test suite prima di commit
- Eseguire `python manage.py check` per validazione
- Eseguire `python manage.py secret_hygiene_check` per secrets
- Eseguire `python manage.py validate_deployment` per deployment

#### Deployment
- Usare Setup Wizard per primo setup
- Eseguire release guard prima di deploy
- Verificare health checks post-deploy
- Monitorare errori e performance

#### Security
- Forzare HTTPS in produzione
- Configurare HSTS headers
- Implementare rate limiting esteso
- Validare configurazione proxy
- Implementare cache invalidation

---

## 6. Conclusioni e Raccomandazioni

### 6.1 Sintesi Finale

NOVICROM HUB è un portale aziendale maturo e ben strutturato con 22 app Django custom e 25+ moduli funzionali. L'architettura SSR puro con Django templates, HTMX e integrazioni native Microsoft 365 rappresenta un punto di forza significativo, offrendo performance ottimali e una governance ACL granulare.

Il sistema di governance ACL v2 con fallback legacy per migrazione incrementale è ben progettato, con 200+ route già coperte e solo 68 senza binding (sotto soglia del release guard). Le integrazioni con Microsoft Graph, LDAP/AD e SMTP sono native e ben integrate.

Il debito tecnico noto è limitato e gestibile: 5 item principali con priorità variabile. La cache Graph primitiva è l'unico item ad alta priorità, mentre gli altri possono essere affrontati gradualmente.

La direzione corrente del prodotto è chiara: mantenere NOVICROM HUB come brand canonico, continuare la migrazione ACL v2, preservare il deployment Windows-first, e prioritizzare i workflow sicurezza/compliance per Security Center AI.

### 6.2 Raccomandazioni Prioritarie

#### Immediato (1-2 settimane)

1. **Risolvere Cache Graph Primitiva (ALTA)**
   - Sostituire `Lock + dict` con DatabaseCache
   - Garantire thread-safety in multi-worker
   - Testare in ambiente di produzione

2. **Forzare HTTPS in Produzione (ALTA)**
   - Configurare SECURE_SSL_REDIRECT
   - Configurare HSTS headers
   - Configurare cookie secure

3. **Implementare Session Regeneration (ALTA)**
   - Aggiungere `request.session.cycle_key()` dopo login
   - Testare session fixation protection

#### Breve Termine (1-2 mesi)

4. **Completare Module Registry (MEDIA)**
   - Registrare tutti i moduli in `module_registry.py`
   - Abilitare branding per tutti i moduli
   - Documentare pattern di registrazione

5. **Refactor SQL Raw Inline (MEDIA)**
   - Sostituire query SQL inline con ORM
   - Migliorare manutenibilità e sicurezza
   - Testare performance dopo refactor

6. **Implementare Rate Limiting Esteso (MEDIA)**
   - Implementare rate limiting su API endpoints
   - Implementare rate limiting su password reset
   - Implementare rate limiting su operazioni sensibili

#### Medio Termine (3-6 mesi)

7. **Completare Planimetria (BASSA)**
   - Implementare logica in `planimetria/models.py`
   - Definire requisiti funzionali
   - Valutare se mantenere o rimuovere

8. **Documentare Flask Compatibility Layer (BASSA)**
   - Mappare tutte le 62 route Flask
   - Documentare redirect e 410
   - Pianificare dismissione graduale

9. **Implementare Content Security Policy (BASSA)**
   - Configurare CSP headers
   - Limitare script sources
   - Testare compatibilità

#### Continuo

10. **Migrazione ACL v2 (CONTINUO)**
    - Continuare bootstrap automatico
    - Ridurre route senza binding
    - Documentare pattern di migrazione

11. **Testing e Quality Gates (CONTINUO)**
    - Mantenere release guard attivo
    - Eseguire contract test integrazioni
    - Validare deployment pre-release

### 6.3 Prossimi Passi

1. **Priorità 1:** Risolvere cache Graph primitiva
2. **Priorità 2:** Forzare HTTPS in produzione
3. **Priorità 3:** Implementare session regeneration
4. **Priorità 4:** Completare module registry
5. **Priorità 5:** Refactor SQL raw inline
6. **Priorità 6:** Implementare rate limiting esteso

### 6.4 Rischio Complessivo

**Rischio Complessivo:** MEDIO-BASSO

L'architettura di sicurezza è ben progettata con controlli appropriati. Le vulnerabilità identificate sono principalmente di configurazione e possono essere mitigate con le raccomandazioni fornite.

### 6.5 Valutazione Finale

NOVICROM HUB è una piattaforma solida, ben architettata e con una direzione chiara, con debito tecnico limitato e gestibile. Le raccomandazioni prioritarie sono focalizzate e realizzabili, e la direzione corrente del prodotto è coerente con gli obiettivi di sicurezza, compliance e operatività.

---

**Report generato da:** Analisi Multiagent
**Data:** 2026-05-04
**Versione:** 1.0.0
