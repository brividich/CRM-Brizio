# Deployment Guide - NOVICROM HUB su Windows Server + IIS

> Versione guida: **2.1**
> Versione repo: **1.0.1**
> Aggiornata: **2026-04-22**

Questa guida descrive il flusso di deploy reale supportato oggi dal repository. La priorita e evitare drift tra documentazione, settings, wizard e packaging.

## Regole da tenere fisse

- Metodo raccomandato: `deployment/dist/SetupWizard.exe`
- Source of truth della versione: `VERSION`
- Settings disponibili nel repo: `config.settings.dev`, `config.settings.test`, `config.settings.prod`
- `config.settings.test` serve alla suite locale/CI e forza SQLite
- Nei flussi wizard/deploy l'ambiente `test` usa comunque `config.settings.prod`
- Il runtime carica i file `.env` tramite `iter_runtime_env_paths(...)` in `django_app/config/settings/base.py` (evoluzione del vecchio `_load_dotenv(...)`): in deploy legge prima `ENV/config/.env`, poi il `.env` copiato nella release attiva come fallback.
- Prima di creare una release zip, eseguire sempre `tools/release_guard.ps1`

## Verita del repo

### Settings

Il repository non usa `django-environ` e contiene `config/settings/test.py` solo per la suite locale/CI.

```python
# django_app/config/settings/base.py
PROJECT_DIR = Path(__file__).resolve().parents[2]
for _dotenv_path in iter_runtime_env_paths(PROJECT_DIR):
    load_dotenv_into_environ(_dotenv_path)
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
- finding HIGH in `secret_hygiene_check`
- errori di `python django_app\manage.py check --settings=config.settings.test`
- regressione ACL sopra la baseline `acl_coverage_report --max-missing 216`
- FAIL in `validate_deployment --format json --settings=config.settings.test`

Il guard produce anche questi artifact JSON in `django_app\`:

- `acl_report_latest.json`
- `deployment_validation_latest.json`

I warning di `validate_deployment` sono ammessi nella fase iniziale per non
bloccare il progetto su debito storico o integrazioni non configurate in locale.
Per ambienti piu severi usare:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\release_guard.ps1 -FailOnDeploymentWarn
```

La baseline ACL e volutamente esplicita: `-AclMaxMissing 216` e il default del
guard. Non usare `--fail-on-missing` finche esistono route storiche non migrate.
La baseline va aumentata solo con decisione consapevole e motivata; in condizioni
normali ogni nuovo binding dovrebbe ridurla. Se il guard fallisce per ACL, aprire
`django_app\acl_report_latest.json`, verificare le route `status=missing` e
decidere se creare binding/grant canonici o documentare temporaneamente il debito.

Comandi manuali equivalenti:

```powershell
python django_app\manage.py secret_hygiene_check
python django_app\manage.py acl_coverage_report --max-missing 216
python django_app\manage.py acl_coverage_report --format json
python django_app\manage.py validate_deployment --format json --settings=config.settings.test
python django_app\manage.py check --settings=config.settings.test
```

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

`deploy-release.ps1` usa `config.settings.prod` sia per `test` sia per `prod`, in linea con il repository. Dopo `migrate` i flussi supportati eseguono automaticamente `ensure_legacy_schema`, `apply_sql_triggers` (queue DDL + trigger in `django_app/automazioni/migrations/` e `sql/`) e `allinea_tipo_assenza_flessibilita` prima dell'attivazione della release. Durante il deploy controlla anche `DB_DRIVER` nel `.env` copiato nella release: se il valore manca o non e installato sul server applicativo, lo riallinea automaticamente al miglior driver SQL Server disponibile.

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
- `apply_sql_triggers`
- `allinea_tipo_assenza_flessibilita`
- `createcachetable`
- bootstrap ACL v2 pre/post migrate
- seed UAT opzionale in ambiente `test`
- configurazione IIS
- Server Dashboard con reset password live degli account locali, disponibile solo in esecuzione elevata come Administrator
- Pagina web `/admin-portale/crea-release/` con sezione `Operazioni server`: crea package, seleziona TEST/PROD, avvia automaticamente il task schedulato elevato `\PortaleNovicrom\IISRestart_TEST/PROD` per riavviare IIS e lancia comandi terminale nel virtualenv dell'ambiente scelto senza aprire una sessione desktop sul server. `configure-iis-site.ps1` e `deploy-release.ps1` registrano/aggiornano il task in modo idempotente; se il task non e' disponibile resta il fallback diretto IIS/processo Django.

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
- `django_app\acl_report_latest.json`
- `django_app\deployment_validation_latest.json`
- esito dello smoke HTTP
- eventuale checklist UAT ACL compilata

## Rollback

Rollback rapido:

```powershell
.\rollback-release.ps1 -Environment test
.\rollback-release.ps1 -Environment prod
```

Il modello a release directory + junction `current` permette di tornare indietro senza ricreare il pacchetto.

## Background jobs con django-q2

Il portale usa **django-q2** per eseguire i job periodici delle automazioni senza dipendere da finestre `cmd.exe` visibili. Il processo worker si chiama `qcluster`.

### Job periodici registrati

| Schedule | Funzione | Frequenza |
| --- | --- | --- |
| `automation_queue` | `automazioni.tasks.run_automation_queue` | ogni 60 s |
| `approval_mailbox` | `automazioni.tasks.run_approval_mailbox` | ogni 120 s |

### Prima configurazione dopo il deploy

```powershell
# 1. Migra le tabelle django-q (ORM broker + schedule)
ENV\venv\Scripts\python.exe manage.py migrate django_q --settings=config.settings.prod

# 2. Registra gli schedule in modo idempotente
ENV\venv\Scripts\python.exe manage.py setup_q_schedules --settings=config.settings.prod
```

Entrambi i comandi sono **idempotenti**: ri-eseguirli non crea duplicati.

### Avviare qcluster manualmente (test)

```powershell
ENV\venv\Scripts\python.exe manage.py qcluster --settings=config.settings.prod
```

Il processo rimane in foreground e scrive su stdout. Per uso in produzione registrarlo come Task Scheduler (vedi sotto).

### Registrare qcluster come Task Scheduler (produzione)

Registrare `deployment/start_qcluster.ps1` come task schedulato persistente:

```powershell
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"C:\PortaleNovicrom\shared\scripts\start_qcluster.ps1`" -Environment prod"

$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName "\PortaleNovicrom\QCluster_PROD" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Description "django-q2 qcluster — background job NOVICROM HUB PROD"
```

Impostazioni obbligatorie nel Task Scheduler GUI:

- **Trigger**: "All'avvio del computer" (At startup)
- **Esegui indipendentemente dall'accesso utente**: abilitato
- **Limite di tempo di esecuzione**: nessuno (task persistente)
- **Account**: account di servizio con accesso al filesystem e al DB

Lo script `start_qcluster.ps1` gestisce il restart automatico on crash con `Start-Sleep 5` tra un tentativo e il successivo; il log viene scritto su `C:\PortaleNovicrom\<env>\logs\qcluster.log`.

### Task Scheduler legacy (DEPRECATED)

> I task Windows che lanciavano direttamente `process_automation_queue` e `process_approval_mailbox` ogni minuto sono **deprecati** con l'adozione di django-q2. Mantenerli temporaneamente come fallback è accettabile durante la transizione, ma vanno disabilitati non appena qcluster è stabile in produzione.

Task deprecati:

- `Portale Hub Polling Mail` — sostituito da `approval_mailbox` schedule django-q
- task manuale `process_automation_queue` — sostituito da `automation_queue` schedule django-q

## Errori da evitare

- confondere `config.settings.test` con l'ambiente IIS `test`
- documentare `django-environ` come loader attivo
- creare una release senza eseguire il release guard
- considerare `django_app/VERSION` come sorgente primaria
- modificare `deployment/setup_wizard.py`, `deployment/SetupWizard.spec`, `deployment/setup_wizard_bundle_rules.json`, `deployment/scripts/*`, `deployment/config/*` o file runtime in `django_app/` senza rigenerare `SetupWizard.exe` o senza passare da `package-release.ps1`, che ora lo aggiorna automaticamente
