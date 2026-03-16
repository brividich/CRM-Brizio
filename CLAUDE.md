# CLAUDE.md — Portale Novicrom

Documento di contesto per AI coding assistant. Aggiornato continuamente con il progetto.
Versione app corrente: **0.7.2**

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
| `hub_tools` | Hub strumenti interni: Module Manager + Database Manager |
| `setup_wizard` | Wizard guidato prima configurazione (12 step) |

---

## Sistema ACL / Permessi

**CRITICO: ci sono due sistemi ACL che coesistono e NON si sincronizzano.**

### 1. ACL Engine legacy (sicurezza reale)

- File: `core/acl.py`, `core/middleware.py`
- Pipeline: `path → _match_pulsante() → modulo+azione → perm_map per ruolo_id → 403/pass`
- Tabelle SQL Server legacy (non managed Django): `utenti`, `ruoli`, `pulsanti`, `permessi`
- Modelli unmanaged: `core/legacy_models.py` — `Ruolo`, `UtenteLegacy`, `Pulsante`, `Permesso`, `AnagraficaDipendente`
- Bypass totale per `is_legacy_admin()`: cerca `ruolo.nome == "admin"` (case-insensitive)
- Bypass totale per `request.user.is_superuser`
- **BUG:** `lru_cache` su `get_admin_role_ids()` non viene mai invalidata in-process

### 2. Navigation Registry (visibilità menu, non sicurezza)

- File: `core/navigation_registry.py`
- Tabelle Django: `NavigationItem`, `NavigationRoleAccess`, `UserDashboardConfig`, `UserModuleVisibility`
- **BUG:** nessun record in `NavigationRoleAccess` = visibile a tutti (fallback permissivo opt-out)

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

### Graph / SharePoint

- Utility centralizzata: `core/graph_utils.py` — `acquire_graph_token(tenant_id, client_id, client_secret)`
- Cache thread-safe con `Lock + dict`, rinnovo 60s prima della scadenza
- **Non duplicare** la logica token nelle singole app — usare sempre `core/graph_utils.py`

---

## Infrastruttura server (NON riproducibile in dev)

Questi componenti esistono solo sul server di produzione:

- Tabelle legacy SQL Server: `utenti`, `ruoli`, `pulsanti`, `permessi`, `anagrafica_dipendenti` — DDL non nel repo, nessuna migration Django
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

## Compatibility layer Flask

- `core/legacy_flask_views.py`: 62 route Flask coperte (27 native, 35 redirect/410)
- Non modificare senza capire prima quale route Flask copre

---

## Debito tecnico noto (non toccare senza discussione)

1. `anomalie/views.py`: ~10 `except Exception: pass` silenziano eccezioni senza logging
2. SQL raw inline in `core/context_processors.py` e alcune views
3. Cache Graph primitiva (`Lock + dict`) — non sicura su multi-process (wsgi multi-worker)
4. `asgi.py` punta a settings dev, `wsgi.py` a prod — non invertire per errore
5. `planimetria/models.py` è vuoto (solo commento) — non aggiungere logica
6. `module_registry.py`: solo `assets` registrato, gli altri moduli non sono brandizzabili

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
