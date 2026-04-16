# Struttura Attuale - NOVICROM HUB

Data snapshot: 2026-04-16 | Versione: 0.9.18

---

## 1) Entrypoint e configurazione

- Entrypoint operativo Django: `django_app/manage.py`.
- URL root Django: `django_app/config/urls.py`.
- Settings sviluppo: `django_app/config/settings/dev.py` (SQLite, DEBUG=True).
- Settings produzione: `django_app/config/settings/prod.py` (SQL Server, SECRET_KEY obbligatoria, DatabaseCache).
- Base settings condivisi: `django_app/config/settings/base.py`.
- Variabili ambiente: `django_app/.env` caricato dal loader custom `_load_dotenv(...)` in `config/settings/base.py` + `config.ini` opzionale (via `configparser`).
- Profili supportati: `config.settings.dev` e `config.settings.prod`. Nei flussi wizard/deploy l'ambiente `test` usa `config.settings.prod`.

---

## 2) App Django attive (20 app custom)

### Core / Infrastruttura

| App | Scopo | Path |
| --- | --- | --- |
| `core` | Auth, middleware ACL/sessione, topbar dinamica, navigation registry, modelli legacy, context processors, audit, notifiche, impersonation | `django_app/core/` |
| `dashboard` | Home page utente con widget configurabili per ruolo | `django_app/dashboard/` |
| `admin_portale` | Pannello admin custom: utenti, ruoli, permessi, navigazione, topbar live, navigation builder, diagnostica LDAP, monitoring | `django_app/admin_portale/` |
| `hub_tools` | Hub strumenti interni admin: module manager, database manager, schema DB, homepage builder, guide, categorie navigazione, gestione notifiche | `django_app/hub_tools/` |
| `setup_wizard` | Wizard guidato prima configurazione (12 step): DB, AD/LDAP, SharePoint, SMTP, moduli, utente admin, info azienda | `django_app/setup_wizard/` |
| `automazioni` | Designer visuale automazioni + SQL trigger → event queue, monitor job | `django_app/automazioni/` |
| `monitoring` | Osservabilita interna: issue tracking con deduplication, problem report utente, monitor automazioni, alert email | `django_app/monitoring/` |

### HR e Workflow

| App | Scopo | Path |
| --- | --- | --- |
| `assenze` | Richieste assenza, calendario, gestione, sync SharePoint, certificazioni presenza | `django_app/assenze/` |
| `anomalie` | Segnalazione e gestione anomalie produzione | `django_app/anomalie/` |
| `tickets` | Sistema ticket interni con allegati, commenti, link ad asset e fornitori | `django_app/tickets/` |
| `notizie` | Bacheca notizie/comunicazioni con audience e letture tracciate | `django_app/notizie/` |
| `timbri` | Report timbrature (lettura da DB legacy SQL Server) | `django_app/timbri/` |
| `tasks` | `KICK-OFF`: portfolio kickoff, attivita kickoff, subtask, commenti, allegati, import Excel e flusso P/N/revisione/versione; `VRF` resta il documento Excel MOD.073 | `django_app/tasks/` |

### Operations e Asset

| App | Scopo | Path |
| --- | --- | --- |
| `assets` | Gestione asset aziendali: inventario, work order, macchine, verifiche periodiche, planimetrie, etichette | `django_app/assets/` |
| `planimetria` | Wrapper per assets (reindirizzamento, modelli vuoti) | `django_app/planimetria/` |
| `anagrafica` | Anagrafica dipendenti (integrata con AD/legacy), fornitori, ruoli operativi | `django_app/anagrafica/` |

### Sicurezza e Compliance

| App | Scopo | Path |
| --- | --- | --- |
| `dpi` | Gestione DPI: categorie con immagine, richieste con card picker, approvazione, consegna, storico, KPI | `django_app/dpi/` |
| `procedure_refresh` | Presa visione procedure MT/MTSI: documenti, revisioni, campagne, assegnazioni, tracking, report, export CSV | `django_app/procedure_refresh/` |
| `diario_preposto` | Diario del preposto sicurezza con segnalazioni e allegati | `django_app/diario_preposto/` |
| `rilevazione_incidenti` | Rilevazione incidenti/unsafe condition (CRUD via Graph API, SharePoint come fonte di verita) | `django_app/rilevazione_incidenti/` |
| `rentri` | Tracciabilita rifiuti (normativa RENTRI) con registro | `django_app/rentri/` |

---

## 3) Routing funzionale (config/urls.py)

| Prefisso URL | App | Note |
| --- | --- | --- |
| `""` | `dashboard.urls` | Home, widget, preferenze UI |
| `""` | `assenze.urls` | Richieste, calendario, gestione |
| `""` | `anomalie.urls` | Segnalazioni produzione |
| `""` | `core.urls` | Auth, legacy routes, notifiche, impersonation |
| `""` | `timbri.urls` | Report timbrature |
| `""` | `rentri.urls` | Registro rifiuti |
| `""` | `planimetria.urls` | Reindirizzamento a assets |
| `"assets/"` | `assets.urls` | Inventario, work order, macchine |
| `"tickets/"` | `tickets.urls` | Ticket interni |
| `"notizie/"` | `notizie.urls` | Bacheca notizie |
| `"tasks/"` | `tasks.urls` | `KICK-OFF` |
| `"automazioni/"` | `automazioni.urls` | Designer automazioni |
| `"anagrafica/"` | `anagrafica.urls` | Dipendenti, fornitori |
| `"diario-preposto/"` | `diario_preposto.urls` | Diario preposto |
| `"rilevazione-incidenti/"` | `rilevazione_incidenti.urls` | Incidenti/unsafe |
| `"dpi/"` | `dpi.urls` | Dispositivi protezione |
| `"procedure-refresh/"` | `procedure_refresh.urls` | Presa visione procedure |
| `"setup/"` | `setup_wizard.urls` | Wizard prima configurazione |
| `"admin-portale/"` | `admin_portale.urls` | Pannello admin custom |
| `"admin-portale/hub/"` | `hub_tools.urls` | Hub strumenti interni |
| `"admin/"` | Django admin nativo | |

Le app senza prefisso condividono il path vuoto; l'ordine degli `include()` e significativo.

---

## 4) Navigazione UI

- Template topbar globale: `django_app/core/templates/core/components/topnav.html`.
- Menu dinamico calcolato da `core.context_processors` (espone `topbar_groups`, `topbar_color`, `subnav_items`).
- Sorgente primaria: `core/navigation_registry.py` (modello `NavigationItem`/`NavigationRoleAccess`).
- **Categorie colorate**: `ModuleCategory` assegna colori e raggruppamenti alla topbar (gestite in `/admin-portale/hub/categorie/`).
- Fallback: dati legacy `pulsanti` e metadati `ui_pulsanti_meta`.
- Configurazione no-code: `/admin-portale/navigation-builder/` (snap shot/rollback) e `/admin-portale/topbar-live/` (editor rapido).

---

## 5) Layer dati

### Tabelle legacy SQL Server (unmanaged → ora managed con fake migration)

Modelli in `core/legacy_models.py`, migration `0029_legacy_managed` applicata con `--fake`:

- `utenti`, `ruoli`, `permessi`, `pulsanti`, `anagrafica_dipendenti`

### Tabelle Django managed (principali)

- **core**: `Profile`, `NavigationItem`, `NavigationRoleAccess`, `AuditLog`, `SiteConfig`, `Notifica`, `UserExtraInfo`, `ModuleCategory`, `LoginBanner`, `LegacyRedirect`, `NavigationSnapshot`
- **assets**: `Asset`, `AssetCategory`, `WorkOrder`, `WorkMachine`, `PeriodicVerification`, `PlantLayout`, `AssetDocument`
- **dpi**: `CategoriaDPI`, `DPIImpostazioni`, `RichiestaDPI`, `ConsegnaDPI`, `RichiestaDPICommento`
- **procedure_refresh**: `ProcedureDocument`, `ProcedureRevision`, `ProcedureCampaign`, `ProcedureCampaignDocument`, `ProcedureAssignment`, `ProcedureReadEvent`
- **monitoring**: `Issue`, `IssueOccurrence`, `UserProblemReport`, `AutomationJob`, `AutomationExecution`
- (altre tabelle per tutti i moduli sopra elencati)

---

## 6) Sicurezza e permessi

### Middleware stack (in ordine)

1. `SessionIdleTimeoutMiddleware` — timeout inattivita sessione
2. `ImpersonationMiddleware` — sostituisce `request.user` durante impersonation admin
3. `ACLMiddleware` — login obbligatorio + ACL legacy su tutti i path non esenti
4. `IssueCaptureMiddleware` — cattura eccezioni non gestite e risposte lente per il monitoring

### File chiave

- `django_app/core/session_middleware.py` — timeout sessione
- `django_app/core/middleware.py` — ACL e impersonation
- `django_app/core/acl.py` — logica permessi legacy
- `django_app/core/impersonation.py` — impersonation admin
- `django_app/monitoring/middleware.py` — cattura issue

### Path esenti da ACL (MIDDLEWARE_EXEMPT_PREFIXES)

`/health`, `/version`, `/login`, `/logout`, `/cambia-password`, `/static/`, `/media/`, `/admin/`, `/favicon`, `/setup/`, `/admin-portale/hub/`

### Bypass totali

- `is_legacy_admin()` (ruolo "admin" case-insensitive): bypass completo ACL
- `request.user.is_superuser`: bypass completo ACL

---

## 7) Integrazioni esterne

| Integrazione | Configurazione | Utilizzo |
| --- | --- | --- |
| **Microsoft Graph / SharePoint** | `GRAPH_*` nel `.env` | Assenze, rilevazione incidenti, procedure refresh (sorgente documenti) |
| **LDAP / Active Directory** | `AUTH_LDAP_*` nel `.env` + `config.ini` | Auth backend in cascata, sync utenti, diagnostica |
| **SMTP** | `EMAIL_*` nel `.env` | Notifiche sistema, alert monitoring, comunicazioni |
| **SQL Server legacy** | `DB_*` nel `.env`, ODBC Driver 17/18 | Tabelle legacy, trigger automazioni |

---

## 8) Automazioni

- Designer visuale → regole su DB → trigger SQL Server → `automation_event_queue`
- Processor: `python manage.py process_automation_queue`
- Decorator `@monitored_automation` per wrappare qualsiasi job con tracking automatico
- File principali: `automazioni/models.py`, `automazioni/views.py`, `sql/`

---

## 9) Monitoring e osservabilita

- Dashboard admin: `/admin-portale/monitoring/` (richiede `is_legacy_admin()`)
- Deduplicazione issue per fingerprint SHA-256
- Alert email con rate-limit per fingerprint (1h default)
- Pulsante "Segnala problema" globale nel topnav per tutti gli utenti autenticati
- Management commands: `monitoring_healthcheck`, `monitoring_digest`

---

## 10) Cache in produzione (IIS multi-worker)

- Backend: `DatabaseCache` su SQL Server (configurato automaticamente da `prod.py`)
- Setup una-tantum: `python manage.py createcachetable`
- Tabella: `django_cache` (override con `DJANGO_CACHE_TABLE`)
- `bump_legacy_cache_version()` usa `cache.incr()` atomico per invalidazione ACL condivisa tra worker

---

## 11) Compatibilita legacy

- Route legacy ancora esposte in `django_app/core/urls.py`
- Handler compatibili in `django_app/core/legacy_flask_views.py` (62 route: 27 native, 35 redirect/410)
- `LegacyRedirect` (modello Django): intercetta vecchi URL e reindirizza verso nuove route
- Alcune GET legacy reindirizzate alle pagine Django attuali; endpoint dismessi restituiscono `410 Gone`

---

## 12) Regola pratica per orientarsi

| Necessita | Dove guardare |
| --- | --- |
| Navigazione UI | `topnav.html`, `core/context_processors.py`, `core/navigation_registry.py` |
| Autorizzazioni | `core/middleware.py`, `core/acl.py` |
| Configurazione menu no-code | `/admin-portale/navigation-builder/` |
| Categorie colori topbar | `/admin-portale/hub/categorie/` |
| Moduli abilitati/disabilitati | `/admin-portale/hub/moduli/` |
| Compatibilita legacy | `core/legacy_flask_views.py` |
| Monitoring e issue | `/admin-portale/monitoring/` |
| Audit trail operazioni | `core/audit.py`, tabella `core_auditlog` |

