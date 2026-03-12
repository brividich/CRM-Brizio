<<<<<<< HEAD
# Portale Applicativo Django

<p align="center">
  Repository pubblico di una piattaforma Django modulare per dashboard, workflow operativi, gestione dati e strumenti amministrativi.
</p>

<p align="center">
  <strong>Python</strong> 3.12+ ·
  <strong>Django</strong> 5.2 ·
  <strong>Database</strong> SQLite / SQL Server ·
  <strong>Auth</strong> Django / LDAP opzionale
</p>

---

## Panoramica

Il codice applicativo vive in `django_app/` ed e' organizzato in moduli funzionali separati.

Questo repository e' stato preparato per essere mantenuto pubblico:

- configurazioni sensibili sostituite con placeholder sicuri
- documentazione interna ridotta al minimo necessario
- bootstrap e struttura runtime lasciati invariati

## Stato Del Repository

| Voce | Dettaglio |
| --- | --- |
| Codice Django | `django_app/` |
| Entrypoint corretto | `django_app/manage.py` |
| `manage.py` in root | placeholder, non usare |
| Template config | `django_app/.env.example`, `.env.example`, `config.ini.example` |
| Documentazione tecnica | `doc/README.md` |

## Stack Tecnico

| Area | Tecnologia |
| --- | --- |
| Runtime | Python 3.12 consigliato |
| Web framework | Django 5.2 |
| Database | SQLite per setup rapido, SQL Server per ambienti completi |
| Driver SQL Server | `mssql-django`, `pyodbc` |
| Autenticazione | Django auth, LDAP opzionale |
| Integrazioni | Microsoft Graph / SharePoint opzionali |

Le dipendenze principali sono in `django_app/requirements.txt`.

## Moduli Principali

| Area | Moduli |
| --- | --- |
| Base applicativa | `core`, `dashboard` |
| Workflow | `assenze`, `anomalie`, `tickets` |
| Operations | `assets`, `planimetria`, `tasks` |
| Dati e contenuti | `anagrafica`, `timbri`, `notizie` |
| Amministrazione | `admin_portale`, `automazioni` |

## Struttura Essenziale

```text
repo-root/
|-- django_app/
|   |-- manage.py
|   |-- config/
|   |-- core/
|   `-- ...
|-- doc/
|-- .env.example
|-- config.ini.example
`-- .gitignore
```

## Quick Start

### 1. Crea l'ambiente virtuale

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r django_app\requirements.txt
```

### 2. Prepara la configurazione

Crea `django_app/.env` partendo da `django_app/.env.example`.

Configurazione minima per sviluppo locale rapido:

```env
DJANGO_SECRET_KEY=CHANGE_ME
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
DB_ENGINE=sqlite
```

Se serve SQL Server:

- installa `ODBC Driver 18 for SQL Server`
- imposta `DB_ENGINE=sqlserver`
- valorizza `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
- usa `DB_TRUST_CERT=1` solo in sviluppo con certificati self-signed

`config.ini.example` contiene chiavi legacy e integrazioni accessorie. Se necessario, copialo in `config.ini` e sostituisci i placeholder con i valori del tuo ambiente.

### 3. Avvia il progetto

```powershell
python django_app\manage.py migrate
python django_app\manage.py runserver
```

`django_app/manage.py` usa di default `config.settings.dev`.

Endpoint locali tipici:

- `http://127.0.0.1:8000`
- `http://localhost:8000`

## Produzione

Per usare i settings di produzione:

```powershell
$env:DJANGO_SETTINGS_MODULE="config.settings.prod"
python django_app\manage.py check
```

Le impostazioni `prod` usano SQL Server come database di default e abilitano opzioni HTTP/HTTPS piu' restrittive. `ALLOWED_HOSTS` e trusted origins vanno forniti via variabili ambiente.

## File Utili

- `django_app/config/settings/base.py`: configurazione comune
- `django_app/config/settings/dev.py`: impostazioni sviluppo
- `django_app/config/settings/prod.py`: impostazioni produzione
- `django_app/.env.example`: esempio completo delle variabili runtime
- `.env.example`: template alternativo a livello repository
- `config.ini.example`: esempio configurazione legacy / integrazioni

## Documentazione

Per l'indice dei documenti tecnici mantenuti nel repository, vedi `doc/README.md`.
=======
# CRM-Brizio
>>>>>>> 1e8d9ff84ffa1a10b5771f6c8e6831fbe862b9f5
