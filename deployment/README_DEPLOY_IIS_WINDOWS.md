# Deployment Guide — Portale Novicrom su Windows Server + IIS

> Versione guida: 2.0 — Stack: Django 5.2, Python 3.11+, SQL Server, IIS + HttpPlatformHandler + Waitress
> **Metodo raccomandato:** usa `SetupWizard.exe` per automatizzare tutto il processo (sezione 0).

---

## Indice

1. [Architettura della soluzione](#1-architettura-della-soluzione)
2. [Prerequisiti server](#2-prerequisiti-server)
3. [Struttura directory sul server](#3-struttura-directory-sul-server)
4. [Primo setup (eseguire una volta)](#4-primo-setup-eseguire-una-volta)
5. [Configurazione IIS](#5-configurazione-iis)
6. [Flusso di deploy standard](#6-flusso-di-deploy-standard)
7. [Rollback](#7-rollback)
8. [Checklist operative](#8-checklist-operative)
9. [Troubleshooting](#9-troubleshooting)
10. [Soluzione consigliata vs alternativa](#10-soluzione-consigliata-vs-alternativa)
11. [Errori da evitare con IIS + Django](#11-errori-da-evitare-con-iis--django)

---

## 0. Installazione automatica con SetupWizard.exe (raccomandato)

Il metodo più semplice e affidabile è usare **`deployment/dist/SetupWizard.exe`**, che automatizza
l'intero processo senza richiedere competenze tecniche.

### Cosa fa il wizard automaticamente

| Step | Operazione |
|------|-----------|
| 1 | Crea la struttura directory (`C:\PortaleNovicrom\ENV\`) |
| 2 | Crea il virtualenv Python |
| 3 | Estrae il pacchetto release |
| 4 | Scrive il file `.env` con tutte le variabili corrette |
| 5 | `pip install -r requirements.txt` + waitress |
| 6 | `collectstatic` → copia in `ENV\static\` |
| 7 | Crea il database SQL Server (se non esiste) |
| 8 | Crea il login `NT AUTHORITY\SYSTEM` su SQL Server (solo Windows Auth) |
| 9 | `migrate` → crea tutte le tabelle Django |
| 10 | `createcachetable` → crea la tabella cache condivisa |
| 11 | Crea l'utente admin legacy (con password werkzeug) |
| 12 | Crea la junction `current` → release |
| 13 | Sblocca la sezione `<handlers>` IIS (fix 500.19) |
| 14 | Configura App Pool (LocalSystem, Always Running) |
| 15 | Crea il sito IIS con virtual directory `/static` e `/media` |

### Prerequisiti prima di eseguire il wizard

- Windows Server con IIS installato e attivo
- **HttpPlatformHandler v1.2** installato in IIS
- SQL Server raggiungibile sulla rete (il DB non deve esistere — il wizard lo crea)
- **ODBC Driver 17 o 18 for SQL Server** installato
- **sqlcmd** disponibile (incluso con SQL Server o SSMS)
- Python 3.11+ installato nel PATH

### Avvio

```
SetupWizard.exe
```

Seleziona **Nuova installazione**, scegli l'ambiente (TEST o PROD), compila i dati
(percorso, SQL Server, porta IIS, credenziali admin) e premi **Installa**.
Il wizard mostra il log in tempo reale e richiede solo un click finale.

### Note importanti

- Il wizard scrive `DB_ENGINE=sqlserver` nel `.env` (non `mssql`)
- `STATIC_ROOT` e `MEDIA_ROOT` vengono passati esplicitamente a `collectstatic`
- La password dell'utente admin viene hashata con **werkzeug** (`generate_password_hash`),
  formato compatibile con `SQLServerLegacyBackend`
- `SETUP_COMPLETED=1` viene scritto nel `.env` per evitare il redirect al wizard Django interno
- Il login `NT AUTHORITY\SYSTEM` viene creato con ruolo `db_owner` sul database target
  perché l'App Pool gira come LocalSystem

---

## 1. Architettura della soluzione

### Flusso richiesta

```
Client Browser
      │
      ▼
   IIS (porta 80/8080)
      │
      ├── /static/*  ──────────► File statici serviti direttamente da IIS
      │                           (C:\PortaleNovicrom\ENV\static\)
      │
      ├── /media/*   ──────────► File media serviti direttamente da IIS
      │                           (C:\PortaleNovicrom\ENV\media\)
      │
      └── /* (tutto il resto) ──► HttpPlatformHandler
                                       │
                                       ▼
                                  Waitress (WSGI server Python)
                                       │  porta dinamica assegnata da IIS
                                       ▼
                                  Django (config.wsgi:application)
                                       │
                                       ▼
                              SQL Server (mssql-django)
                              AD/LDAP, SharePoint/Graph
```

### Soluzione tecnica scelta

| Componente | Scelta | Motivo |
|-----------|--------|--------|
| Web server | IIS | Requisito obbligatorio |
| Integrazione Python | **HttpPlatformHandler + Waitress** | Moderno, supportato, gestione processo nativa IIS |
| Alternativa | wfastcgi | Più semplice, ma deprecato |
| Gestione release | Directory junction `current` | Rollback istantaneo, zero-copy |
| Config separata | `config\.env` fuori dal codice | Stessa config tra release |
| Venv | Condiviso per ambiente | Riuso tra release, deploy più veloci |

### Struttura release

```
C:\PortaleNovicrom\
├── shared\
│   ├── scripts\           ← Script PowerShell deployment
│   ├── packages\          ← Pacchetti release .zip (da DEV)
│   └── backups\           ← Backup automatici pre-deploy
│
├── test\
│   ├── current\           ← JUNCTION → releases\20260321_143000\
│   ├── releases\
│   │   ├── 20260320_100000\   ← release vecchio
│   │   └── 20260321_143000\   ← release attuale (puntato da current)
│   │       └── django_app\
│   │           ├── .env       ← copiato da config\.env al deploy
│   │           ├── config.ini ← copiato da config\config.ini
│   │           ├── manage.py
│   │           └── config\settings\test.py
│   ├── logs\
│   ├── config\            ← .env e config.ini MASTER (non versionati)
│   ├── static\            ← output collectstatic
│   ├── media\             ← upload utenti
│   ├── run\               ← marker release, pid
│   ├── venv\              ← virtualenv Python (condiviso tra release)
│   └── web.config         ← configurazione IIS
│
└── prod\                  ← stessa struttura di test\
```

---

## 2. Prerequisiti server

### Sistema operativo

- Windows Server 2019 o 2022 (raccomandato)
- Windows Server 2016 (supportato)

### Ruoli e feature Windows Server

Installa da **Server Manager → Gestione → Aggiungi ruoli e funzionalità**:

```
Web Server (IIS)
└── Web Server
    ├── Common HTTP Features
    │   ├── Default Document         ✓
    │   ├── Static Content           ✓
    │   └── HTTP Errors              ✓
    ├── Application Development
    │   ├── CGI                      ✓  (necessario per wfastcgi se usi alternativa)
    │   └── ISAPI Extensions         ✓
    ├── Security
    │   └── Request Filtering        ✓
    └── Performance
        └── Static Content Compress  ✓
```

Oppure via PowerShell (da eseguire come admin):

```powershell
Install-WindowsFeature -Name Web-Server, Web-Common-Http, Web-Static-Content,
    Web-Default-Doc, Web-Http-Errors, Web-CGI, Web-ISAPI-Ext,
    Web-Security, Web-Filtering, Web-Stat-Compression,
    Web-Http-Logging, Web-Mgmt-Console -IncludeManagementTools
```

### Moduli IIS aggiuntivi (download e installazione manuale)

1. **HttpPlatformHandler v1.2**
   - URL: https://www.iis.net/downloads/microsoft/httpplatformhandler
   - Installa come estensione IIS (MSI standard, segui wizard)
   - Verifica: IIS Manager → Handler Mappings → cerca "httpPlatformHandler"

2. **URL Rewrite Module 2.1** (opzionale ma utile)
   - URL: https://www.iis.net/downloads/microsoft/url-rewrite

3. **Application Request Routing (ARR)** (opzionale, solo se proxy inverso)

### Python

- **Versione richiesta:** Python 3.11.x (o superiore compatibile)
- **Installazione:** Scarica da python.org — usa installer per tutti gli utenti
- **Percorso raccomandato:** `C:\Python311\` (evita spazi nel percorso)
- **Opzioni installer:**
  - ✓ Add Python to PATH
  - ✓ Install for all users
  - ✓ pip
  - ✓ py launcher

Verifica installazione:
```cmd
C:\Python311\python.exe --version
# Output atteso: Python 3.11.x
```

### ODBC Driver per SQL Server

- **ODBC Driver 17 for SQL Server** (o 18, controlla compatibilità mssql-django)
- Download: Microsoft Download Center
- Necessario per la connessione Django → SQL Server via pyodbc

### Tools aggiuntivi (raccomandati)

- **sqlcmd**: per backup DB via script, incluso con SQL Server o scaricabile separatamente
- **7-Zip** o PowerShell 5+ (per decompressione zip — PS5+ è già sufficiente)

---

## 3. Struttura directory sul server

Crea la struttura base (fatto automaticamente da `setup-environment.ps1`):

```powershell
# Esegui setup per entrambi gli ambienti
.\scripts\setup-environment.ps1 -Environment test -PythonPath "C:\Python311\python.exe"
.\scripts\setup-environment.ps1 -Environment prod -PythonPath "C:\Python311\python.exe"
```

Struttura risultante:
```
C:\PortaleNovicrom\
├── shared\packages\        ← zip delle release
├── shared\backups\         ← backup config/DB
├── test\config\            ← .env e config.ini TEST (da creare manualmente)
├── test\venv\              ← virtualenv TEST
├── prod\config\            ← .env e config.ini PROD
└── prod\venv\              ← virtualenv PROD
```

---

## 4. Primo setup (eseguire una volta)

### 4.1 Copia gli script di deploy sul server

```powershell
# Opzione A: copia manuale
xcopy "\\DEV-PC\PortaleNovicrom\deployment\scripts\*" "C:\PortaleNovicrom\shared\scripts\" /E /Y

# Opzione B: copia da un pacchetto release che include deployment\
# (il package-release.ps1 include la cartella deployment\)
```

### 4.2 Setup ambiente TEST

```powershell
cd C:\PortaleNovicrom\shared\scripts

# 1. Crea struttura directory + venv
.\setup-environment.ps1 -Environment test

# 2. Copia e modifica il file di configurazione
Copy-Item "C:\PortaleNovicrom\shared\scripts\..\config\.env.test.example" `
          "C:\PortaleNovicrom\test\config\.env"
notepad "C:\PortaleNovicrom\test\config\.env"    # MODIFICA CON VALORI REALI

# 3. Crea config.ini (copia dall'esempio nel repo)
Copy-Item "\\DEV-PC\...\config.ini.example" "C:\PortaleNovicrom\test\config\config.ini"
notepad "C:\PortaleNovicrom\test\config\config.ini"

# 4. Configura sito IIS TEST (porta 8080)
.\configure-iis-site.ps1 -Environment test -Port 8080 -Hostname "portale-test.cnovicrom.local"
```

### 4.3 Setup ambiente PROD

```powershell
# Stessa procedura con -Environment prod
.\setup-environment.ps1 -Environment prod
# ... modifica .env.prod ...
.\configure-iis-site.ps1 -Environment prod -Port 80 -Hostname "portale.cnovicrom.local"
```

### 4.4 Configura settings Django per IIS

Verifica che `config/settings/prod.py` legga le variabili dal file `.env`:

```python
# config/settings/prod.py
import environ, os
from .base import *

env = environ.Env()
environ.Env.read_env(os.path.join(BASE_DIR, ".env"))   # BASE_DIR = django_app/

DEBUG = False
STATIC_ROOT  = env("STATIC_ROOT",  default=str(BASE_DIR / "static"))
MEDIA_ROOT   = env("MEDIA_ROOT",   default=str(BASE_DIR / "media"))
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")
```

Crea anche `config/settings/test.py` se non esiste (può importare da prod):
```python
# config/settings/test.py
from .prod import *
# Override specifici per TEST se necessario
```

### 4.5 Verifica STATIC_ROOT e MEDIA_ROOT nel settings

`STATIC_ROOT` deve puntare a `C:\PortaleNovicrom\AMBIENTE\static\` — verificalo nel `.env`.

---

## 5. Configurazione IIS

Lo script `configure-iis-site.ps1` fa tutto automaticamente. Questa sezione documenta cosa viene creato.

### Application Pool

| Impostazione | Valore |
|-------------|--------|
| Nome | `PortaleNovicrom-TEST` / `PortaleNovicrom-PROD` |
| .NET CLR | Nessun codice gestito |
| Pipeline | Integrata |
| Start mode | Always Running |
| Idle timeout | Disabilitato (0) |
| Periodic restart | Disabilitato |

### Sito IIS

| Impostazione | TEST | PROD |
|-------------|------|------|
| Nome | PortaleNovicrom-TEST | PortaleNovicrom-PROD |
| Physical path | `C:\PortaleNovicrom\test\` | `C:\PortaleNovicrom\prod\` |
| Porta | 8080 | 80 |
| App Pool | PortaleNovicrom-TEST | PortaleNovicrom-PROD |

### Virtual Directories

```
PortaleNovicrom-TEST
├── /static  →  C:\PortaleNovicrom\test\static\
└── /media   →  C:\PortaleNovicrom\test\media\
```

### web.config

Il file `web.config` viene copiato dal template e personalizzato per l'ambiente:
- Si trova in `C:\PortaleNovicrom\test\web.config` (root del sito IIS)
- **Non** è dentro `current\` — rimane stabile tra i cambi di release
- Punta all'eseguibile Python nel venv: `C:\PortaleNovicrom\test\venv\Scripts\python.exe`
- Il processo Python viene avviato da `current\django_app\` come working directory

### DNS / hosts

Per test locale, aggiungi a `C:\Windows\System32\drivers\etc\hosts`:
```
127.0.0.1   portale-test.cnovicrom.local
10.0.0.5    portale.cnovicrom.local
```

---

## 6. Flusso di deploy standard

```
DEV Machine                          Server (TEST/PROD)
─────────────────────────────────────────────────────────
A. Sviluppo locale
   git commit & push

B. Crea pacchetto release
   .\scripts\package-release.ps1
   → portale-novicrom-vX.Y.Z-20260321_143000.zip

C. Copia zip sul server ──────────► C:\PortaleNovicrom\shared\packages\

D. Deploy su TEST ───────────────►  .\deploy-release.ps1 -Environment test
                                        - Estrae zip
                                        - Copia .env da config\
                                        - pip install -r requirements.txt
                                        - collectstatic
                                        - migrate
                                        - createcachetable

E. Attiva su TEST ───────────────►  .\activate-release.ps1 -Environment test
                                        - Salva release precedente
                                        - Stop IIS app pool
                                        - Aggiorna junction current
                                        - Start IIS app pool
                                        - Smoke test automatico

F. Test manuale ─────────────────►  http://portale-test.cnovicrom.local:8080/

G. Promozione PROD ──────────────►  .\backup-environment.ps1 -Environment prod
                                    .\deploy-release.ps1 -Environment prod -PackagePath <same.zip>
                                    .\activate-release.ps1 -Environment prod
```

### Comandi dettagliati

#### B. Crea pacchetto (su macchina dev)

```powershell
cd "C:\Dev\Portale Novicrom\deployment\scripts"
.\package-release.ps1
# Output: C:\PortaleNovicrom\shared\packages\portale-novicrom-vX.Y.Z-20260321_143000.zip
```

#### C. Copia sul server

```powershell
# Via share di rete (se disponibile):
Copy-Item "portale-novicrom-vX.Y.Z-20260321_143000.zip" `
          "\\SERVER\PortaleNovicrom\shared\packages\"

# Oppure via USB / altri metodi
```

#### D-E. Deploy + Attivazione TEST (in un solo comando)

```powershell
cd C:\PortaleNovicrom\shared\scripts
$pkg = "C:\PortaleNovicrom\shared\packages\portale-novicrom-vX.Y.Z-20260321_143000.zip"
.\deploy-release.ps1 -Environment test -PackagePath $pkg -AutoActivate
```

#### F. Smoke test manuale

```powershell
.\smoke-test.ps1 -Environment test
```

#### G. Promozione PROD

```powershell
# 1. Backup sicurezza
.\backup-environment.ps1 -Environment prod -IncludeDatabase

# 2. Deploy (non attiva ancora)
$pkg = "C:\PortaleNovicrom\shared\packages\portale-novicrom-vX.Y.Z-20260321_143000.zip"
.\deploy-release.ps1 -Environment prod -PackagePath $pkg

# 3. Attiva (richiede conferma)
.\activate-release.ps1 -Environment prod -ReleaseTag 20260321_143000
```

---

## 7. Rollback

### Rollback rapido (al release precedente)

```powershell
cd C:\PortaleNovicrom\shared\scripts
.\rollback-release.ps1 -Environment prod
# Interattivo: mostra release disponibili e chiede conferma
```

### Rollback a release specifico

```powershell
# Lista release disponibili
Get-ChildItem C:\PortaleNovicrom\prod\releases\ | Sort-Object Name -Descending

# Rollback a un tag specifico
.\rollback-release.ps1 -Environment prod -ReleaseTag 20260320_120000
```

### Rollback manuale (emergenza)

```powershell
# Stop app pool
Import-Module WebAdministration
Stop-WebAppPool -Name "PortaleNovicrom-PROD"

# Rimuovi junction e ricrea verso release precedente
cmd /c 'rmdir "C:\PortaleNovicrom\prod\current"'
New-Item -ItemType Junction -Path "C:\PortaleNovicrom\prod\current" `
         -Target "C:\PortaleNovicrom\prod\releases\20260320_120000"

# Riavvia
Start-WebAppPool -Name "PortaleNovicrom-PROD"
```

### Tempi di rollback attesi

- Rollback codice: **< 30 secondi** (solo cambio junction + recycle)
- Rollback con migration DB: **non automatico** — le migration sono irreversibili per default

> **IMPORTANTE:** Gli script NON eseguono `migrate --fake` o reverse migration.
> Se una migration rompe lo schema, il rollback codice non basta.
> Pianifica migration distruttive con attenzione o usa migration reversibili.

---

## 8. Checklist operative

### Checklist: Deploy TEST

```
[ ] 1. package-release.ps1 eseguito sul PC dev — zip generato
[ ] 2. Zip copiato in shared\packages\ sul server
[ ] 3. .env TEST aggiornato se ci sono nuove variabili richieste
[ ] 4. deploy-release.ps1 -Environment test -PackagePath <zip>
        [ ] pip install completato senza errori
        [ ] collectstatic completato
        [ ] migrate completato senza errori
[ ] 5. activate-release.ps1 -Environment test -ReleaseTag <tag>
[ ] 6. smoke-test.ps1 -Environment test — tutti PASS
[ ] 7. Test manuale browser: login, funzionalità principali
[ ] 8. Verifica log: C:\PortaleNovicrom\test\logs\
```

### Checklist: Promozione PROD

```
[ ] 1. Deploy TEST completato e testato
[ ] 2. Finestra di manutenzione comunicata agli utenti (se necessario)
[ ] 3. backup-environment.ps1 -Environment prod -IncludeDatabase
[ ] 4. deploy-release.ps1 -Environment prod -PackagePath <STESSO zip di TEST>
        [ ] pip install OK
        [ ] collectstatic OK
        [ ] migrate OK (verifica migration critiche!)
[ ] 5. activate-release.ps1 -Environment prod -ReleaseTag <tag>
        [ ] Conferma digitando 'SI'
[ ] 6. smoke-test.ps1 -Environment prod — tutti PASS
[ ] 7. Test manuale rapido in produzione
[ ] 8. Notifica agli utenti (se necessario)
[ ] 9. Aggiornamento CHANGELOG.md
```

### Checklist: Verifica post-deploy

```
[ ] URL principale risponde (200 o redirect 302 atteso)
[ ] Login funziona
[ ] Static files caricati correttamente (CSS/JS)
[ ] Nessun errore 500 nei log
[ ] Log app.log senza eccezioni Django
[ ] Log waitress_stdout.log senza errori Python
[ ] Moduli principali accessibili: Dashboard, Assenze, Anomalie, Asset
[ ] Integrazioni attive (se modificate): AD/LDAP, SharePoint/Graph
```

### Checklist: Rollback

```
[ ] Identifica il problema (500? Login rotto? Migration fallita?)
[ ] Se migration critica → coinvolgi DBA prima del rollback
[ ] rollback-release.ps1 -Environment <env>
[ ] smoke-test.ps1 post-rollback — tutti PASS
[ ] Verifica log: problema risolto?
[ ] Documenta l'incidente
[ ] Pianifica fix e prossimo deploy
```

---

## 9. Troubleshooting

### 502 Bad Gateway

**Causa:** IIS non riesce a connettersi al processo Python/Waitress.

1. Controlla che il processo Python sia avviato:
   ```powershell
   Get-Process python -ErrorAction SilentlyContinue
   ```
2. Controlla i log stdout di IIS:
   ```
   C:\PortaleNovicrom\prod\logs\waitress_stdout.log
   ```
3. Controlla il log eventi IIS:
   ```powershell
   Get-EventLog -LogName Application -Source "IIS*" -Newest 20
   ```
4. Verifica che il venv Python esista:
   ```powershell
   Test-Path "C:\PortaleNovicrom\prod\venv\Scripts\python.exe"
   ```
5. Verifica il web.config — i percorsi sono corretti?
6. Verifica permessi NTFS sulla cartella dell'app pool.

### 500 Internal Server Error

**Causa:** Errore Django.

1. Abilita DEBUG=True nel `.env` temporaneamente (solo se sicuro):
   ```
   DEBUG=True
   ```
2. Controlla i log Django:
   ```
   C:\PortaleNovicrom\prod\logs\app.log
   ```
3. Cerca errori di importazione, migration non applicate, variabili .env mancanti.
4. Esegui check manuale:
   ```powershell
   cd C:\PortaleNovicром\prod\current\django_app
   C:\PortaleNovicrom\prod\venv\Scripts\python.exe manage.py check --settings=config.settings.prod
   ```

### Static files non caricati (404 su /static/)

1. Verifica che collectstatic sia stato eseguito:
   ```powershell
   (Get-ChildItem C:\PortaleNovicrom\prod\static\ -Recurse | Measure-Object).Count
   # Deve essere > 0
   ```
2. Verifica virtual directory IIS in IIS Manager.
3. Verifica permessi NTFS sulla cartella `static\`.
4. Controlla STATIC_ROOT nel `.env` — deve puntare a `C:\PortaleNovicrom\prod\static`.

### Errore 403 su static files

- IIS non serve directory listing per default. Va bene per `/static/` (directory listing = 403).
- Se un file specifico dà 403, verifica permessi NTFS.

### Migration fallita

```powershell
# Verifica stato migration
cd C:\PortaleNovicrom\prod\current\django_app
$env:DJANGO_SETTINGS_MODULE = "config.settings.prod"
C:\PortaleNovicrom\prod\venv\Scripts\python.exe manage.py showmigrations

# Applica migration specifica
C:\PortaleNovicrom\prod\venv\Scripts\python.exe manage.py migrate core --settings=config.settings.prod
```

### App pool in stato Stopped

```powershell
Import-Module WebAdministration
Get-WebAppPoolState -Name "PortaleNovicrom-PROD"
Start-WebAppPool -Name "PortaleNovicrom-PROD"
```

### Login failed for user 'NT AUTHORITY\SYSTEM' (18456)

L'App Pool gira come LocalSystem ma `NT AUTHORITY\SYSTEM` non ha un login su SQL Server.

```sql
USE [master];
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'NT AUTHORITY\SYSTEM')
    CREATE LOGIN [NT AUTHORITY\SYSTEM] FROM WINDOWS;

USE [PortaleNovicrom_TEST];  -- sostituisci con il tuo DB
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'NT AUTHORITY\SYSTEM')
    CREATE USER [NT AUTHORITY\SYSTEM] FOR LOGIN [NT AUTHORITY\SYSTEM];
ALTER ROLE db_owner ADD MEMBER [NT AUTHORITY\SYSTEM];
```

Il wizard esegue questo automaticamente se `sqlcmd` è disponibile.

### Django usa SQLite invece di SQL Server

Sintomo: nel log appare `Engine: sqlite` o il path del DB è `\django_app\db.sqlite3`.

Causa: `DB_ENGINE=mssql` nel `.env` non viene riconosciuto (il valore corretto è `sqlserver`).

Fix:
```powershell
(Get-Content .env) -replace 'DB_ENGINE=mssql','DB_ENGINE=sqlserver' | Set-Content .env
```

Il wizard aggiornato scrive già `DB_ENGINE=sqlserver`.

### "No migrations to apply" con DB vuoto

Causa: Django trova `django_migrations` con righe ma le tabelle non esistono (installazione precedente fallita a metà).

Fix: ricrea il database da zero e rilancia migrate:
```sql
USE [master]; DROP DATABASE [NomeDB]; CREATE DATABASE [NomeDB];
```
```powershell
python manage.py migrate --settings=config.settings.prod
```

### collectstatic copia in `staticfiles/` invece di `ENV\static\`

Causa: `STATIC_ROOT` già impostata nell'ambiente di sistema sovrascrive il `.env`
(che usa `setdefault` e non sovrascrive variabili già presenti).

Fix manuale:
```powershell
$env:STATIC_ROOT = "C:\PortaleNovicrom\test\static"
python manage.py collectstatic --noinput --settings=config.settings.prod
```

Il wizard aggiornato passa `STATIC_ROOT` esplicitamente come variabile d'ambiente.

### "Invalid hash method 'pbkdf2_sha256'" al login

Causa: la password dell'utente legacy è stata creata con Django `make_password` ma il backend
`SQLServerLegacyBackend` usa werkzeug `check_password_hash` (formato incompatibile).

Fix: ricrea la password con werkzeug:
```powershell
python -c "
import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.prod'
django.setup()
from core.legacy_models import UtenteLegacy
from werkzeug.security import generate_password_hash
u = UtenteLegacy.objects.get(nome='admin')
u.password = generate_password_hash('NUOVA_PASSWORD')
u.save()
print('OK')
"
```

### 500.19 — sezione handlers bloccata (0x80070021)

La sezione `<handlers>` in IIS è bloccata a livello server e non può essere sovrascritta dal `web.config` del sito.

```cmd
%windir%\system32\inetsrv\appcmd.exe unlock config -section:system.webServer/handlers
```

Il wizard esegue questo automaticamente durante la configurazione IIS.

### Invalid object name 'django_cache_test'

La tabella cache non è stata creata. In produzione con IIS multi-worker, Django usa `DatabaseCache`.

```powershell
python manage.py createcachetable --settings=config.settings.prod
```

Il wizard lo esegue automaticamente dopo migrate.

### Errore connessione SQL Server

1. Verifica che ODBC Driver sia installato: `odbcad32.exe`
2. Testa connessione:
   ```powershell
   & "C:\PortaleNovicrom\prod\venv\Scripts\python.exe" -c "import pyodbc; print(pyodbc.drivers())"
   ```
3. Verifica credenziali nel `.env`: `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
4. Verifica che il firewall di SQL Server consenta connessioni dalla porta 1433.

### LDAP / AD non funziona

1. Verifica connettività: `Test-NetConnection -ComputerName DC01.cnovicrom.local -Port 389`
2. Verifica credenziali `LDAP_BIND_DN` e `LDAP_BIND_PASSWORD`
3. Controlla che il service account AD non sia scaduto.

### Errore "Junction already exists"

```powershell
# Rimuovi il junction manualmente
cmd /c 'rmdir "C:\PortaleNovicrom\prod\current"'
# Poi riesegui activate-release.ps1
```

### Log da consultare sempre

| File | Contenuto |
|------|-----------|
| `logs\waitress_stdout.log` | Output processo Python (errori import, startup) |
| `logs\app.log` | Log applicazione Django |
| `logs\app-HOSTNAME.log` | Stesso, per hostname |
| `logs\sql.log` | Query SQL (se SQL_LOG_ENABLED=True) |
| `logs\pip-install-TIMESTAMP.log` | Output pip install dell'ultimo deploy |
| Event Viewer → Application | Errori IIS/Windows |

---

## 10. Soluzione consigliata vs alternativa

### Soluzione A (RACCOMANDATA): HttpPlatformHandler + Waitress

**Pro:**
- Processo Python gestito da IIS (restart automatico in caso di crash)
- Logging stdout integrato
- Nessun servizio Windows aggiuntivo da gestire
- Supporta WebSocket (per sviluppi futuri con ASGI/Channels)
- Microsoft lo mantiene attivamente

**Contro:**
- Richiede installazione del modulo HttpPlatformHandler (download separato)
- Il processo Python gira in-process rispetto all'app pool

**Requisiti extra:** HttpPlatformHandler v1.2 installato in IIS

**Template web.config:** `config/web.config.httpplatform.template`

---

### Soluzione B (ALTERNATIVA): wfastcgi

**Pro:**
- Configurazione leggermente più semplice
- Non richiede moduli IIS aggiuntivi (solo CGI attivato)
- Ampiamente documentato online

**Contro:**
- **Deprecato** (ultimo aggiornamento 2019 su PyPI)
- No gestione processo (crash = 502 finché non recicli manualmente l'app pool)
- Non supporta WebSocket
- Limitazioni performance su carichi elevati

**Quando usarla:** server legacy dove non puoi installare moduli IIS aggiuntivi.

**Configurazione wfastcgi:**
```powershell
# Installa nel venv
pip install wfastcgi

# Registra con IIS (da CMD admin — annota l'output!)
C:\PortaleNovicrom\prod\venv\Scripts\wfastcgi-enable.exe
# Stampa qualcosa come:
# "C:\PortaleNovicrom\prod\venv\Scripts\python.exe|C:\...\wfastcgi.py" can now be used as a FastCGI script processor

# Modifica web.config.wfastcgi.template sostituendo %%PYTHON_FASTCGI%%
# con il percorso stampato sopra
```

**Template web.config:** `config/web.config.wfastcgi.template`

---

## 11. Errori da evitare con IIS + Django

### DEBUG=True in produzione

Lasciare `DEBUG=True` espone stack trace completo agli utenti. Sempre `DEBUG=False` in prod.
Se hai bisogno di debug, usa i log Django (`app.log`), non DEBUG=True.

### SECRET_KEY identica tra ambienti

Genera una chiave unica per ogni ambiente:
```powershell
python -c "import secrets; print(secrets.token_hex(50))"
```

### STATIC_ROOT che punta dentro current\

Sbagliato: `STATIC_ROOT = current\django_app\static`
Giusto: `STATIC_ROOT = C:\PortaleNovicrom\prod\static` (fuori da current)

I file statici devono sopravvivere al cambio di release senza rieseguire collectstatic.

### venv dentro la cartella del release

Se il venv è dentro `releases\TIMESTAMP\`, ogni deploy reinstalla tutto e il rollback
diventa lento. Il venv va in `prod\venv\` (condiviso tra release).

### Permessi NTFS troppo permissivi

L'account `IIS AppPool\PortaleNovicrom-PROD` deve avere:
- **ReadAndExecute** sulla cartella del sito
- **Modify** SOLO su `logs\` e `media\`
- **Read** su `config\` (contiene .env con credenziali)

NON dare `Full Control` all'intero sito.

### Ricaricare IIS senza fermare il processo Python

Se esegui `iisreset` senza fermare prima l'app pool, potresti avere processi Python orfani
sulla stessa porta. Usa sempre `Stop-WebAppPool` prima di modificare la release attiva.

### Migration senza backup DB

Esegui sempre `backup-environment.ps1` prima di un deploy con migration.
Una migration distruttiva (drop column, drop table) non è reversibile automaticamente.

### .env con credenziali nel repository

Il file `.env` NON deve mai essere committato. Solo `.env.test.example` e `.env.prod.example`
(senza credenziali reali) vanno nel repo. Verifica `.gitignore`.

### app pool con identità sbagliata

Il wizard imposta **LocalSystem** come identità dell'App Pool. Questo garantisce:
- Accesso completo al venv e ai file Django senza configurare permessi NTFS
- Connessione a SQL Server via Windows Integrated Auth come `NT AUTHORITY\SYSTEM`

> In ambienti ad alta sicurezza, sostituire con un service account AD dedicato
> e configurare manualmente i permessi NTFS e il login SQL Server.

### ALLOWED_HOSTS vuoto o con wildcard `*`

In produzione specifica sempre gli hostname esatti. `ALLOWED_HOSTS=*` è accettabile solo per debug.

### Non aggiornare CHANGELOG e versione

Dopo ogni deploy aggiorna tutti i file indicati nella sezione "Bump di versione" di CLAUDE.md.
Il file `.env` ha la precedenza — se non aggiorni APP_VERSION lì, l'UI mostra la versione vecchia.

