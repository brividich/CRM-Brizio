# Struttura Attuale Portale Applicativo

Data snapshot: 2026-03-12

## 1) Entrypoint e configurazione

- Entrypoint operativo Django: `django_app/manage.py`.
- URL root Django: `django_app/config/urls.py`.
- Settings runtime di sviluppo: `django_app/config/settings/dev.py`.
- Base settings condivisi: `django_app/config/settings/base.py`.

## 2) App Django attive

- `core`: autenticazione, middleware ACL/sessione, topbar dinamica, route legacy compatibili.
- `dashboard`: dashboard utente e accesso rapido ai moduli.
- `assenze`: richieste, gestione, calendario e certificazioni presenza.
- `anomalie`: segnalazioni e integrazioni dati collegate.
- `admin_portale`: gestione utenti, permessi, navigazione e diagnostica amministrativa.
- `anagrafica`: anagrafica dipendenti legacy e gestione fornitori.
- `assets`: inventario asset, macchine, planimetrie e verifiche periodiche.

## 3) Routing funzionale

Da `django_app/config/urls.py`:

- `"" -> dashboard.urls`
- `"" -> assenze.urls`
- `"" -> anomalie.urls`
- `"admin-portale/" -> admin_portale.urls`
- `"" -> core.urls`
- `"admin/" -> django admin`

Le app non-admin condividono il prefisso vuoto, quindi l'ordine degli `include()` resta significativo.

## 4) Navigazione UI

- Template topbar globale: `django_app/core/templates/core/components/topnav.html`.
- Menu dinamico calcolato da `core.context_processors.legacy_nav`.
- Sorgente primaria: `core/navigation_registry.py`.
- Fallback: dati legacy `pulsanti` e metadati `ui_pulsanti_meta`.

## 5) Layer dati

- Tabelle legacy unmanaged in `django_app/core/legacy_models.py`.
- Tabelle Django gestite in `django_app/core/models.py`.
- Tabella di supporto UI: `ui_pulsanti_meta`.

## 6) Sicurezza e permessi

- `SessionIdleTimeoutMiddleware`: timeout per inattivita' di sessione.
- `ACLMiddleware`: login obbligatorio e ACL legacy sui path applicativi.
- File chiave: `django_app/core/session_middleware.py`, `django_app/core/middleware.py`, `django_app/core/acl.py`.

## 7) Compatibilita' legacy

- Route legacy ancora esposte in `django_app/core/urls.py`.
- Handler compatibili in `django_app/core/legacy_flask_views.py`.
- Alcune GET legacy vengono redirette alle pagine Django attuali; endpoint dismessi possono restituire `410 Gone`.

## 8) Regola pratica per orientarsi

- Navigazione UI: `topnav.html` e `core/context_processors.py`.
- Autorizzazioni: `core/middleware.py` e `core/acl.py`.
- Compatibilita' legacy: `core/legacy_flask_views.py`.
- Configurazione amministrativa della navigazione: area `admin-portale`.
