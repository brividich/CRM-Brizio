# Deployment Guide - NOVICROM HUB su Windows Server + IIS

> Versione guida: **2.1**  
> Versione repo: **0.9.18**  
> Aggiornata: **2026-04-13**

Questa guida descrive il flusso di deploy reale supportato oggi dal repository. La priorita e evitare drift tra documentazione, settings, wizard e packaging.

## Regole da tenere fisse

- Metodo raccomandato: `deployment/dist/SetupWizard.exe`
- Source of truth della versione: `VERSION`
- Settings disponibili nel repo: `config.settings.dev`, `config.settings.test`, `config.settings.prod`
- `config.settings.test` serve alla suite locale/CI e forza SQLite
- Nei flussi wizard/deploy l'ambiente `test` usa comunque `config.settings.prod`
- Il file `.env` viene caricato dal loader custom `_load_dotenv(...)` in `django_app/config/settings/base.py`
- Prima di creare una release zip, eseguire sempre `tools/release_guard.ps1`

## Verita del repo

### Settings

Il repository non usa `django-environ` e contiene `config/settings/test.py` solo per la suite locale/CI.

```python
# django_app/config/settings/base.py
PROJECT_DIR = Path(__file__).resolve().parents[2]
_load_dotenv(PROJECT_DIR / ".env")
```

```python
# django_app/config/settings/prod.py
from .base import *  # noqa: F403,F401
from .base import SECRET_KEY, build_database_from_env, env, env_bool, env_list

DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", [])
DATABASES = {"default": build_database_from_env("sqlserver")}
```

### Ambienti

- `dev`: sviluppo locale, tipicamente SQLite
- `config.settings.test`: profilo locale/CI per test automatici, sempre SQLite
- `test` come ambiente deploy: IIS/SQL Server con settings `config.settings.prod`
- `prod`: deploy IIS/SQL Server con settings `config.settings.prod`

## Flusso raccomandato

### 1. Verifica locale prima del package

Dalla root del repository:

```powershell
python manage.py test
python manage.py bootstrap_acl_v2 --dry-run --settings=config.settings.dev
powershell -ExecutionPolicy Bypass -File .\tools\release_guard.ps1
```

`python manage.py test` usa `config.settings.test`; l'ambiente IIS chiamato `test` continua invece a usare `config.settings.prod`.

Il guard blocca il rilascio se trova:

- versioni fuori sync nei documenti canonici
- riferimenti docs non compatibili con il repo reale
- fallback di versione non allineati
- `deployment/dist/SetupWizard.exe` mancante o palesemente obsoleto
- fallimento di `bootstrap_acl_v2 --dry-run`

### 2. Crea il pacchetto release

```powershell
cd "C:\Dev\Portale Novicrom\deployment\scripts"
.\package-release.ps1
```

Output atteso:

- zip `portale-novicrom-vX.Y.Z-YYYYMMDD_HHmmss.zip`
- salvataggio in `C:\PortaleNovicrom\shared\packages\` se la cartella esiste
- altrimenti salvataggio in `.\releases\`

`package-release.ps1` verifica automaticamente `deployment/dist/SetupWizard.exe` prima di comprimere i file: se manca o e obsoleto rispetto ai trigger runtime del bundle, lo rigenera con PyInstaller e poi esegue `tools/release_guard.ps1`.

### Repo locale senza `C:\PortaleNovicrom`

Se stai eseguendo il portale direttamente dalla working copy del repository su Windows, senza la struttura deploy `C:\PortaleNovicrom\test|prod`, puoi registrare il poller queue locale con:

```powershell
.\deployment\scripts\register-local-polling-mail.ps1 -StartNow
```

Lo script crea o aggiorna il task schedulato `Portale Hub Polling Mail`, usa il `.venv` del repo, lancia `process_automation_queue --settings=config.settings.prod` ogni minuto e scrive il log in `django_app\logs\automation_queue.log`. Il task usa un wrapper PowerShell hidden, quindi il polling resta silent e non apre finestre `cmd` o `powershell` a ogni esecuzione.

### 3. Deploy su server

Flusso minimo su server:

```powershell
.\deploy-release.ps1 -Environment test -PackagePath "C:\PortaleNovicrom\shared\packages\portale-novicrom-vX.Y.Z-YYYYMMDD_HHmmss.zip"
.\activate-release.ps1 -Environment test
```

`deploy-release.ps1` usa `config.settings.prod` sia per `test` sia per `prod`, in linea con il repository, e dopo `migrate` esegue automaticamente `allinea_tipo_assenza_flessibilita` per riallineare `CK_assenze_tipo` prima dell'attivazione della release. Durante il deploy controlla anche `DB_DRIVER` nel `.env` copiato nella release: se il valore manca o non e installato sul server applicativo, lo riallinea automaticamente al miglior driver SQL Server disponibile.

Per PROD:

```powershell
.\backup-environment.ps1 -Environment prod
.\deploy-release.ps1 -Environment prod -PackagePath "C:\PortaleNovicrom\shared\packages\portale-novicrom-vX.Y.Z-YYYYMMDD_HHmmss.zip"
.\activate-release.ps1 -Environment prod
```

## SetupWizard.exe

`SetupWizard.exe` resta il metodo consigliato per installazione iniziale, upgrade e promozione di release.

Automatizza almeno:

- creazione cartelle ambiente
- creazione venv
- scrittura `.env`
- `pip install -r requirements.txt`
- `collectstatic`
- `migrate`
- `allinea_tipo_assenza_flessibilita`
- `createcachetable`
- bootstrap ACL v2 pre/post migrate
- seed UAT opzionale in ambiente `test`
- configurazione IIS
- Server Dashboard con reset password live degli account locali, disponibile solo in esecuzione elevata come Administrator

Il wizard e `deployment/scripts/setup-environment.ps1` auto-rilevano un Python 3.11+ valido tramite `py`, percorsi standard, registry e `PATH`; se `venv`, `pip install`, `collectstatic` o `migrate` falliscono, la release non viene piu attivata o riciclata sotto IIS. Dopo `collectstatic` i flussi supportati verificano anche gli asset sentinella `static\core\css\theme.css` e `static\monitoring\css\monitoring.css`.

## Prerequisiti server

- Windows Server con IIS installato
- HttpPlatformHandler disponibile
- SQL Server raggiungibile
- Un driver ODBC SQL Server installato (18/17/13 o equivalente legacy compatibile)
- Python 3.11+ disponibile (non necessariamente in `C:\Python311\python.exe`)
- `sqlcmd` disponibile se usi i flussi che creano o configurano il database

## Struttura operativa consigliata

```text
C:\PortaleNovicrom\
|-- shared\
|   |-- packages\
|   |-- backups\
|   `-- scripts\
|-- test\
|   |-- current\
|   |-- releases\
|   |-- config\
|   |-- static\
|   |-- media\
|   |-- logs\
|   `-- venv\
`-- prod\
    |-- current\
    |-- releases\
    |-- config\
    |-- static\
    |-- media\
    |-- logs\
    `-- venv\
```

## Post-deploy e smoke

### Smoke HTTP

```powershell
.\deployment\scripts\smoke-test.ps1 -Environment test
.\deployment\scripts\smoke-test.ps1 -Environment prod
```

Lo smoke verifica almeno:

- `/health`
- `/version`
- `/login/`
- redirect della root
- handler 404

### Smoke governance ACL

Su ambiente locale o su una macchina con il progetto montato:

```powershell
python manage.py bootstrap_acl_v2 --dry-run --settings=config.settings.dev
```

### Evidenze consigliate prima della promozione

- output di `tools/release_guard.ps1`
- output di `bootstrap_acl_v2 --dry-run`
- esito dello smoke HTTP
- eventuale checklist UAT ACL compilata

## Rollback

Rollback rapido:

```powershell
.\rollback-release.ps1 -Environment test
.\rollback-release.ps1 -Environment prod
```

Il modello a release directory + junction `current` permette di tornare indietro senza ricreare il pacchetto.

## Errori da evitare

- confondere `config.settings.test` con l'ambiente IIS `test`
- documentare `django-environ` come loader attivo
- creare una release senza eseguire il release guard
- considerare `django_app/VERSION` come sorgente primaria
- modificare `deployment/setup_wizard.py`, `deployment/SetupWizard.spec`, `deployment/setup_wizard_bundle_rules.json`, `deployment/scripts/*`, `deployment/config/*` o file runtime in `django_app/` senza rigenerare `SetupWizard.exe` o senza passare da `package-release.ps1`, che ora lo aggiorna automaticamente

