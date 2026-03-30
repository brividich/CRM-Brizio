
<h1 align="center">BoluHUB</h1>

![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Django 5.2](https://img.shields.io/badge/Django-5.2-0C4B33?logo=django&logoColor=white)
![Version 0.8.6](https://img.shields.io/badge/version-0.8.6-F97316)
![Database SQLite or SQL Server](https://img.shields.io/badge/DB-SQLite%20%7C%20SQL%20Server-1E3A5F)

Repository pubblico del software **BrizioHUB**. Il nome istanza Ã¨ configurabile per deployment
(es. "Portale Novicrom") tramite il wizard di configurazione al primo avvio.

![Preview dashboard BrizioHUB](.github/assets/dashboard-preview.svg)

## Panoramica

Il codice applicativo vive in `django_app/` ed espone un portale aziendale costruito su Django 5.2,
con moduli separati per operativita quotidiana, amministrazione, anagrafiche, asset, workflow e automazioni.

L'entrypoint corretto per lo sviluppo locale e `django_app/manage.py`.

## Personalizzazione interfaccia

Il portale include un sistema di preferenze UI per utente che permette di adattare
la leggibilita e i comandi rapidi senza modificare codice o template:

- `font_scale` globale con profili `small`, `normal`, `large`, `xl`
- tipografia coerente su dashboard, moduli operativi, form, tabelle, card e widget
- sidebar con toggle compatto in alto e logo separato
- footer sidebar personalizzabile con azioni rapide aggiungibili, rimovibili e riordinabili

Le preferenze vengono salvate lato server e riapplicate automaticamente al login successivo.

## Cosa include

| Area | Descrizione |
| --- | --- |
| Dashboard e UX | home modulare, viste per ruolo, scorciatoie operative, navigazione dinamica, font scaling globale e sidebar personalizzabile con categorie colorate |
| Workflow | assenze, anomalie, tickets, timbri, notizie e richieste interne |
| Operations | inventory asset, work order, macchine di lavoro, planimetrie e verifiche periodiche |
| Sicurezza e compliance | DPI (richieste/approvazione/consegna), diario preposto, rilevazione incidenti, presa visione procedure MT/MTSI, tracciabilita rifiuti RENTRI |
| Governance | gestione utenti, ACL canonico v2 + fallback legacy, pulsanti UI, audit, diagnostica LDAP, diagnostica ACL e mappa permessi/navigazione |
| Automazioni | designer visuale, sorgenti, queue processor, test regole e import package |
| Osservabilita | monitoring interno, issue tracking, alert email, segnalazioni utente, monitor automazioni |
| Compatibilita legacy | route storiche, tabelle unmanaged e fallback di navigazione/permessi |

## Preview

Anteprime visuali GitHub-friendly dei flussi principali del portale.

| Assets / Officina | Automazioni |
| --- | --- |
| ![Preview modulo assets e officina](.github/assets/assets-preview.svg) | ![Preview designer automazioni](.github/assets/automation-preview.svg) |

## ACL canonico v2 (permission-code based)

Il portale supporta un layer ACL canonico progressivo che convive con il legacy:

- `PermissionDefinition`: catalogo permessi leggibili (`code`, `label`, `module`, `description`)
- `RoutePermissionBinding`: mappa route/path -> `permission_code`
- `RolePermissionGrant`: grant ruolo legacy -> `permission_code`
- `UserPermissionGrant`: override per-utente sullo stesso `permission_code`
- resolver unificato in `core/acl_v2.py` integrato in middleware
- fallback legacy (`pulsanti` + `permessi`) usato solo se il binding canonico manca

Strumenti operativi:

- `/admin-portale/acl-canonico/` per gestire permission code, binding e grant
- `/admin-portale/acl-route-coverage/` per classificare tutte le route (`CANONICAL_BOUND`, `LEGACY_FALLBACK`, `UNBOUND`, `COMING_SOON_EXCLUDED`, `REDIRECT_ONLY`)
- `/admin-portale/acl-diagnostica/` per capire perché un accesso è consentito/negato
- comando `python django_app/manage.py bootstrap_acl_v2` per supportare migrazione incrementale
- comando `python django_app/manage.py seed_acl_uat --reset` per caricare un pacchetto UAT ripetibile (ruoli, utenti, binding, grant, override, fallback legacy, report scenari)

## Stack tecnico

| Area | Tecnologia |
| --- | --- |
| Runtime | Python 3.11+ |
| Framework | Django 5.2.11 |
| Database dev | SQLite |
| Database full environment | SQL Server via `mssql-django` e `pyodbc` |
| Auth | Django auth, ACL canonico v2 con fallback legacy, LDAP opzionale |
| Integrazioni opzionali | Microsoft Graph / SharePoint, SMTP, Active Directory |

Dipendenze principali: `django_app/requirements.txt`

## Moduli principali

| Gruppo | Moduli |
| --- | --- |
| Core platform | `core`, `dashboard` |
| HR e workflow | `assenze`, `anomalie`, `tickets`, `timbri`, `notizie` |
| Sicurezza e compliance | `diario_preposto`, `rilevazione_incidenti`, `dpi`, `procedure_refresh`, `rentri` |
| Operations | `assets`, `tasks`, `planimetria` |
| Backoffice | `admin_portale`, `anagrafica` |
| Automation | `automazioni` |
| Infrastruttura | `hub_tools`, `setup_wizard`, `monitoring` |

## Quick start

### 1. Crea l'ambiente

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r django_app\requirements.txt
```

### 2. Prepara la configurazione

```powershell
Copy-Item django_app\.env.example django_app\.env
```

Configurazione minima consigliata per sviluppo locale:

```env
DJANGO_SECRET_KEY=CHANGE_ME
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
DB_ENGINE=sqlite
```

`django_app/.env` e il file principale di runtime.
`config.ini.example` resta utile solo per integrazioni legacy o configurazioni opzionali.

### 3. Avvia il progetto

```powershell
python django_app\manage.py migrate
python django_app\manage.py runserver
```

Endpoint tipici in locale:

- `http://127.0.0.1:8000/` â€” dashboard
- `http://127.0.0.1:8000/assets/` â€” gestione asset
- `http://127.0.0.1:8000/admin-portale/` â€” pannello admin
- `http://127.0.0.1:8000/admin-portale/acl-canonico/` - gestione permission code / binding / grant
- `http://127.0.0.1:8000/admin-portale/acl-route-coverage/` - report copertura route ACL con filtri e export CSV
- `http://127.0.0.1:8000/admin-portale/acl-diagnostica/` - diagnostica ACL (utente/ruolo/path/route)
- `http://127.0.0.1:8000/admin-portale/mappa-permessi-navigazione/` - mappa route/menu/ruoli/override/redirect con drill-down workflow per riga e toggle live permessi legacy (con ruolo filtro attivo)
- `http://127.0.0.1:8000/tickets/` â€” ticket interni
- `http://127.0.0.1:8000/dpi/` â€” dispositivi protezione individuale
- `http://127.0.0.1:8000/procedure-refresh/` â€” presa visione procedure
- `http://127.0.0.1:8000/admin-portale/hub/` â€” hub strumenti interni

## Configurazione ambienti

- `config.settings.dev` usa SQLite di default ed e il profilo caricato da `django_app/manage.py`.
- `config.settings.prod` usa SQL Server di default, `ALLOWED_HOSTS` vuoto e impostazioni HTTP/HTTPS piu restrittive.
- Per SQL Server serve `ODBC Driver 18 for SQL Server`.
- LDAP, Graph e SMTP sono attivabili da variabili ambiente o da `config.ini` dove previsto.

Check rapido del profilo produzione:

```powershell
$env:DJANGO_SETTINGS_MODULE="config.settings.prod"
python django_app\manage.py check
```

### Setup cache multi-worker (IIS con 2+ worker)

Con piÃ¹ worker IIS la cache deve essere condivisa tra processi. Il profilo prod usa automaticamente `DatabaseCache` su SQL Server. Eseguire **una sola volta** dopo ogni deploy su server vergine:

```powershell
python django_app\manage.py createcachetable --settings=config.settings.prod
```

> Il `SetupWizard.exe` esegue `createcachetable` automaticamente durante l'installazione.

### Backup automatico

- Command: `python django_app\manage.py backup_portale`
- Opzioni: `--include-media`, `--retention N`
- Config via `.env`: `BACKUP_DIR` (path root), `BACKUP_RETENTION` (numero backup da mantenere)
- Cleanup retention: vengono rimosse solo cartelle backup con formato timestamp `YYYYMMDD_HHMMSS`

## Comandi utili

```powershell
python django_app\manage.py test
python django_app\manage.py process_automation_queue
python django_app\manage.py bootstrap_acl_v2
python django_app\manage.py seed_acl_uat --reset
python django_app\manage.py show_urls
```

## Struttura repository

```text
repo-root/
|-- django_app/
|   |-- manage.py
|   |-- config/
|   |-- core/
|   |-- assets/
|   |-- automazioni/
|   `-- ...
|-- doc/
|-- sql/
|-- .github/assets/
|-- .env.example
`-- config.ini.example
```

## Deployment su Windows Server + IIS

Il metodo raccomandato Ã¨ **`SetupWizard.exe`** (`deployment/dist/`), che automatizza:
creazione directory, venv, `.env`, database SQL Server, migrate, collectstatic, createcachetable,
utente admin e configurazione IIS completa.

Prerequisiti: IIS + HttpPlatformHandler, SQL Server, ODBC Driver 17/18, sqlcmd, Python 3.11+.

Per il flusso manuale e il troubleshooting: [deployment/README_DEPLOY_IIS_WINDOWS.md](deployment/README_DEPLOY_IIS_WINDOWS.md)

## Documentazione collegata

- [Guida deployment IIS (manuale + troubleshooting)](deployment/README_DEPLOY_IIS_WINDOWS.md)
- [Manuale amministratore â€” navigazione e permessi](tools/MANUALE_ADMIN_NAVIGAZIONE_PERMESSI.md)
- [Guida ACL v2 (permission-code based)](doc/ACL_V2_PERMISSION_GUIDE.md)
- [Guida rapida admin ACL v2](doc/ACL_V2_ADMIN_QUICK_GUIDE.md)
- [Convenzione permission code ACL v2](doc/ACL_V2_PERMISSION_CODE_CONVENTION.md)
- [Checklist UAT ACL v2](doc/ACL_V2_UAT_CHECKLIST.md)
- [Guida seed UAT ACL v2](doc/ACL_V2_UAT_SEED_GUIDE.md)
- [Matrice scenari UAT ACL v2](doc/ACL_V2_UAT_SCENARIOS.md)
- [Note del modulo assets](django_app/assets/README.md)

## Nota sul repository pubblico

Questo repository e stato ripulito per una pubblicazione sicura:

- credenziali reali e configurazioni sensibili non sono incluse
- i file `.example` rappresentano solo template o placeholder
- la documentazione mantenuta nel repository e limitata a cio che serve per orientarsi nel codice

