
<h1 align="center">NOVICROM HUB</h1>

![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Django 5.2](https://img.shields.io/badge/Django-5.2-0C4B33?logo=django&logoColor=white)
![Version 0.9.16](https://img.shields.io/badge/version-0.9.16-F97316)
![Database SQLite or SQL Server](https://img.shields.io/badge/DB-SQLite%20%7C%20SQL%20Server-1E3A5F)

Repository di riferimento del software **NOVICROM HUB**. I nomi storici come
`Portale Novicrom` restano nel repo solo come esempio di istanza, percorso o deploy.

![Preview dashboard NOVICROM HUB](.github/assets/dashboard-preview.svg)

## Panoramica

Il codice applicativo vive in `django_app/` ed espone un portale aziendale costruito su Django 5.2,
con moduli separati per operativita quotidiana, amministrazione, anagrafiche, asset, workflow e automazioni.

L'entrypoint corretto per lo sviluppo locale e `django_app/manage.py`.

Nel modulo anagrafica, se il legacy non ha `email_notifica`, il portale usa e riallinea automaticamente l'`email` account per evitare schede dipendente e rubriche incoerenti.

## Start Here

Se stai entrando adesso nel progetto, parti da [`doc/START_HERE.md`](doc/START_HERE.md):

- sviluppatore
- admin funzionale
- deployer
- tester / UAT

## Personalizzazione interfaccia

Il portale include un sistema di preferenze UI per utente che permette di adattare
la leggibilita e i comandi rapidi senza modificare codice o template:

- `font_scale` globale con profili `small`, `normal`, `large`, `xl`
- tipografia coerente su dashboard, moduli operativi, form, tabelle, card e widget
- sidebar con toggle compatto in alto e logo separato
- icone topbar/sidebar con alias SVG semantici e fallback automatico sui moduli principali
- sottomenu sidebar aperti resi come livello annidato con pannello dedicato e stato aperto piu evidente
- footer sidebar personalizzabile con azioni rapide aggiungibili, rimovibili e riordinabili
- favicon del portale sostituibile da `/admin-portale/branding/` senza toccare codice o file statici
- shell modulo e dashboard shared a tutta altezza, cosi i layout principali non lasciano bande vuote in fondo al viewport

Le preferenze vengono salvate lato server e riapplicate automaticamente al login successivo.

Dal wizard di primo accesso (`/onboarding/`) l'utente appena creato configura subito anche queste preferenze UI, invece di doverle cercare dopo il login. La pagina resta raggiungibile da qualsiasi utente autenticato senza grant ACL dedicati, mentre le preferenze email continuano a mostrare solo i moduli che il ruolo rende davvero visibili, cosi il setup iniziale non propone opzioni fuorvianti. Anche il centro notifiche personale (`/notifiche/` e API `/api/notifiche/...`) resta sempre disponibile a ogni utente autenticato, senza dipendere dai permessi di modulo.

## Cosa include

| Area | Descrizione |
| --- | --- |
| Dashboard e UX | home modulare, viste per ruolo, scorciatoie operative, navigazione dinamica, font scaling globale e sidebar personalizzabile con categorie colorate, icone SVG semantiche e sottomenu annidati piu leggibili |
| Workflow | assenze, anomalie, tickets, timbri, notizie e richieste interne |
| Operations | inventory asset, work order, macchine di lavoro, planimetrie e manutenzione periodica |
| Sicurezza e compliance | DPI (richieste/approvazione/consegna), diario preposto, rilevazione incidenti, presa visione procedure MT/MTSI, tracciabilita rifiuti RENTRI |
| Governance | gestione utenti, ACL canonico v2 + fallback legacy, pulsanti UI, audit, diagnostica LDAP, diagnostica ACL, mappa permessi/navigazione e branding portale (favicon, login) |
| Automazioni | designer visuale, sorgenti, queue processor, test regole e import package |
| Osservabilita | monitoring interno, issue tracking, alert email, segnalazioni utente, monitor automazioni |
| Compatibilita legacy | route storiche, tabelle unmanaged e fallback di navigazione/permessi |

La `dashboard` resta il cruscotto KPI cross-modulo e i workflow di dominio vivono dentro i rispettivi moduli. Per `assenze` il punto di ingresso unico e `/assenze/`, che raccoglie menu modulo, nuova richiesta, gestione personale, calendario e certificazione presenza.

Nel modulo `automazioni`, sia il builder classico sia il designer visuale tengono ora allineati i dropdown di trigger e condizioni con la sorgente selezionata, cosi il catalogo colonne riflette davvero la tabella attiva invece di restare fermo sulla prima sorgente caricata. Il designer visuale espone anche un browser campi con ricerca, filtri e inserimento intelligente nel target attivo (trigger, condizioni, template, mapping), mentre la pagina test offre un composer guidato current/old payload sincronizzato col JSON raw.

Le pagine `Impostazioni` restano separate per modulo ma seguono ora un pattern condiviso per hero, KPI/quick links e branding nome/logo modulo. I percorsi canonici sono `/diario-preposto/impostazioni/`, `/rilevazione-incidenti/impostazioni/`, `/timbri/impostazioni/`, `/rentri/impostazioni/`, `/assenze/impostazioni/`, `/notizie/impostazioni/`, `/procedure-refresh/impostazioni/`, `/tasks/impostazioni/` e `/assets/impostazioni/`; gli URL storici (`gestione`, `configurazione`, `admin`) restano compatibili come redirect legacy. Nel modulo `tasks`, `/tasks/impostazioni/` raccoglie ora anche le tab amministrative `Configurazione`, `Riepilogo`, `Record` e `Log attivita`, mentre il vecchio `/tasks/gestione/` reindirizza alla tab `Riepilogo`.

Nel modulo `tasks`, presentato in UI come `KICK-OFF`, il kickoff coincide ora con il progetto ed e nominato automaticamente `KICK-OFF <progressivo dedicato>`, mentre `VRF` indica solo il documento Excel MOD.073. Il form crea o riusa kickoff in modo P/N-safe sull'identita `P/N + revisione + versione`, non chiede piu un nome progetto manuale e presenta le righe operative come `attivita kickoff`. Dal portfolio kickoff sono disponibili anche le azioni `Copia kickoff e VRF` e `Copia kickoff e VRF tranne P/N`: la seconda duplica il file Excel svuotando in memoria sia il campo `part_number` del kickoff sia la cella `B3` del workbook, senza alterare il file sorgente.

Alla creazione di ogni kickoff il portale guida all'upload del documento MOD.073 VRF: il file .xlsx viene analizzato automaticamente e i campi identificativi (Cliente, P/N, Versione, Preventivo, Descrizione, Esp) vengono estratti e mostrati in anteprima prima del salvataggio. Se il documento non viene caricato subito, il sistema attiva un reminder progressivo configurabile: dopo N giorni compare un avviso, dopo M giorni il kickoff viene bloccato e non accetta nuove attivita fino al caricamento del documento. I valori N e M sono modificabili dalla tab `Configurazione` di `/tasks/impostazioni/` (parametri `vrf_reminder_days` e `vrf_blocking_days`). La stessa pagina include anche riepilogo, record e log amministrativi del modulo. Il portfolio kickoff mostra la colonna "Documento" con badge colorato per ogni progetto (Caricato / Avviso / Bloccato / Non richiesto).

Nel modulo `assets`, gli admin possono ora creare eventi Outlook Calendar per le scadenze principali del modulo: manutenzioni, scadenze amministrative, manutenzione periodica e contratti assistenza. La sincronizzazione riusa Microsoft Graph, salva un tracking unico per evitare duplicati e, per manutenzione periodica/contratti, richiede il filtro su un asset specifico cosi il calendario resta legato a un contesto chiaro. La manutenzione periodica e ora trattata come categoria della manutenzione, con percorso canonico `/assets/manutenzione/verifiche/` e redirect compatibile dal vecchio `/assets/verifiche-periodiche/`. La dashboard del modulo vive su `/assets/`, mentre la lista inventario canonica e `/assets/lista/`; i vecchi link filtrati nel formato `/assets/?asset_type=...` vengono riallineati automaticamente alla lista. La pagina `/assets/licenze/` gestisce le licenze software (software, antivirus, Office) con assegnazione diretta a asset o dipendenti anagrafica. Il logo del modulo Assets e personalizzabile dalla pagina `Impostazioni` (tab Configurazione) con upload diretto o URL esterno; il brand nella sidebar e cliccabile per tornare all'homepage del modulo. La configurazione di categorie asset e campi dinamici vive nella tab `Categorie asset` di `/assets/impostazioni/`, mentre lo Studio amministratore dell'inventario mantiene un rimando rapido per chi arriva dai flussi storici. La sidebar del modulo espone il link `Impostazioni` su tutte le pagine per gli utenti con permesso `admin_assets`.

La dashboard principale usa ora questo workspace personale: widget KPI multi-modulo, layout personale per utente, template iniziale definibile dagli admin e ripristino rapido al template di partenza. La route `scheda-dipendente` resta solo come alias compatibile.

Nel modulo `assenze` il valore canonico per le richieste flessibili e `FlessibilitÃƒÆ’Ã‚Â `. Se il database SQL Server proviene da una versione legacy che usa ancora `Infortunio`, riallinealo con `python django_app/manage.py allinea_tipo_assenza_flessibilita --settings=config.settings.dev` prima di usare insert/update o `sync/pull`; il runtime non deve piu persistere `Infortunio` in `tipo_assenza`. `Certifica presenza` resta gestita come tipo applicativo dedicato ma viene persistita come `Altro` con metadato interno per compatibilita.

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
- compat route dedicata: `/anomalie-menu` funziona come launcher del modulo anomalie e puo restare accessibile ai ruoli che hanno almeno un permesso operativo (`anomalie_aperte` o `inserimento_anomalie`) anche se il grant contenitore `dashboard_anomalie_menu` non e presente

Strumenti operativi:

- `/admin-portale/accessi/` come entrypoint semplice predefinito: un solo toggle per modulo sincronizza ACL legacy (`permessi.can_view/consentito`), grant canonici v2 e visibilita menu del ruolo
- `/admin-portale/gestione-accessi/` per il dettaglio legacy storico modulo/azione
- `/admin-portale/acl-canonico/` per gestire permission code, binding e grant
- `/admin-portale/acl-route-coverage/` per classificare tutte le route (`CANONICAL_BOUND`, `LEGACY_FALLBACK`, `UNBOUND`, `COMING_SOON_EXCLUDED`, `REDIRECT_ONLY`)
- `/admin-portale/acl-diagnostica/` per capire perchÃƒÆ’Ã‚Â© un accesso ÃƒÆ’Ã‚Â¨ consentito/negato
- `/admin-portale/mappa-permessi-navigazione/` per il workflow visuale route/menu con toggle live grant canonici + permessi legacy (con filtro ruolo)
- `/admin-portale/navigation-builder/` per gestire la navigazione con tab per sezione e card operative `Apri`, `Clona`, `Rimuovi` direttamente dalla vista visuale
- comando `python django_app/manage.py bootstrap_acl_v2` per supportare migrazione incrementale
  - `--dry-run` per audit senza scritture
  - `--apps assets,automazioni` per migrare una app alla volta
  - `--apply` per creare/aggiornare binding canonici attivi su route `LEGACY_FALLBACK/UNBOUND`
- comando `python django_app/manage.py seed_acl_uat --reset` per caricare un pacchetto UAT ripetibile (ruoli, utenti, binding, grant, override, fallback legacy, report scenari)

In installazione tramite `SetupWizard.exe` (ambienti `test`/`prod`), dopo `migrate` il wizard esegue automaticamente il workflow ACL v2:
- audit pre `bootstrap_acl_v2 --dry-run`
- migrazione `bootstrap_acl_v2 --import-legacy --apply`
- audit post `bootstrap_acl_v2 --dry-run`
- in ambiente `test`: seed UAT opzionale (`seed_acl_uat --reset`) tramite checkbox wizard `Esegui seed UAT ACL`

## Stack tecnico

| Area | Tecnologia |
| --- | --- |
| Runtime | Python 3.11+ |
| Framework | Django 5.2.11 |
| WSGI IIS | Waitress via `HttpPlatformHandler` |
| Database dev | SQLite |
| Database full environment | SQL Server via `mssql-django` e `pyodbc` |
| Auth | Django auth, ACL canonico v2 con fallback legacy, LDAP opzionale |
| Integrazioni opzionali | Microsoft Graph / SharePoint, SMTP, Active Directory |

Dipendenze principali: `django_app/requirements.txt`
Per i deploy IIS, `waitress` e una dipendenza runtime obbligatoria: se manca nel venv, `python -m waitress ...` fallisce e IIS risponde con `503 Service Unavailable`.

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

`django_app/.env` e l'unica sorgente persistita di configurazione runtime.

### 3. Avvia il progetto

```powershell
python django_app\manage.py migrate
python django_app\manage.py runserver
```

Endpoint tipici in locale:

- `http://127.0.0.1:8000/` ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â dashboard
- `http://127.0.0.1:8000/assenze/` ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â modulo assenze unificato (menu, gestione, calendario)
- `http://127.0.0.1:8000/assets/` ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â gestione asset
- `http://127.0.0.1:8000/admin-portale/` → pannello admin
- `http://127.0.0.1:8000/admin-portale/branding/` - favicon e identità visiva del portale (ICO/PNG/SVG, aggiornamento immediato su tutte le pagine)
- `http://127.0.0.1:8000/admin-portale/login-config/` - titolo, logo, banner e SSO della pagina di login
- `http://127.0.0.1:8000/admin-portale/accessi/` - accessi semplici: un toggle per modulo sincronizza legacy ACL, grant canonici v2 e menu ruolo
- `http://127.0.0.1:8000/admin-portale/gestione-accessi/` - dettaglio legacy storico per modulo/azione
- `http://127.0.0.1:8000/admin-portale/navigation-builder/` - builder navigazione con vista visuale drag&drop orizzontale (scroll laterale) + editor tabellare completo, con toggle modalita avanzata per slot `Sidebar Dedicated`
- `http://127.0.0.1:8000/admin-portale/acl-canonico/` - gestione permission code / binding / grant
- `http://127.0.0.1:8000/admin-portale/acl-route-coverage/` - report copertura route ACL con filtri e export CSV
- `http://127.0.0.1:8000/admin-portale/acl-diagnostica/` - diagnostica ACL (utente/ruolo/path/route)
- `http://127.0.0.1:8000/admin-portale/mappa-permessi-navigazione/` - mappa route/menu/ruoli/override/redirect con drill-down workflow per riga e toggle live grant canonici v2 + permessi legacy (con ruolo filtro attivo)
- `http://127.0.0.1:8000/tickets/` ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ticket interni
- `http://127.0.0.1:8000/dpi/` ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â dispositivi protezione individuale
- `http://127.0.0.1:8000/procedure-refresh/` ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â presa visione procedure
- `http://127.0.0.1:8000/admin-portale/hub/` ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â hub strumenti interni

Nota assets: la dashboard modulo risponde su `/assets/`, mentre la lista inventario canonica e `/assets/lista/`; i vecchi link filtrati come `/assets/?asset_type=FIREWALL&rows=25` vengono reindirizzati automaticamente alla lista.

## Configurazione ambienti

- `config.settings.dev` usa SQLite di default ed e il profilo caricato da `manage.py` per i comandi locali ordinari.
- `config.settings.test` forza sempre SQLite, cache/email locali e viene usato automaticamente da `python django_app\manage.py test` se non passi `--settings` esplicito.
- `config.settings.prod` usa SQL Server di default, `ALLOWED_HOSTS` vuoto e impostazioni HTTP/HTTPS piu restrittive.
- Per SQL Server serve almeno un driver ODBC SQL Server installato (`ODBC Driver 18/17/13`, `SQL Server Native Client 11.0` o `SQL Server`); il wizard e `deployment/scripts/deploy-release.ps1` allineano automaticamente `DB_DRIVER` al miglior driver disponibile sul server applicativo.
- LDAP, Graph, SMTP, GuestPortal e le configurazioni applicative admin sono lette dal processo e da `django_app/.env`.
- La precedenza effettiva e: ambiente processo -> `django_app/.env` -> default codice.
- `/admin-portale/ldap/` mostra runtime attivo e valori che verrebbero caricati al prossimo riavvio; il salvataggio scrive direttamente `.env`, che resta la sola source of truth persistita.

Check rapido del profilo produzione:

```powershell
$env:DJANGO_SETTINGS_MODULE="config.settings.prod"
python django_app\manage.py check
```

### Setup cache multi-worker (IIS con 2+ worker)

Con piÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¹ worker IIS la cache deve essere condivisa tra processi. Il profilo prod usa automaticamente `DatabaseCache` su SQL Server. Eseguire **una sola volta** dopo ogni deploy su server vergine:

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

`python django_app\manage.py test` usa `config.settings.test` in automatico; se vuoi essere esplicito puoi comunque usare `--settings=config.settings.test`.

Per un flusso completo di test, smoke ACL e raccolta evidenze usa [`doc/TESTING.md`](doc/TESTING.md).

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
`-- .env.example
```

## Deployment su Windows Server + IIS

Il metodo raccomandato ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¨ **`SetupWizard.exe`** (`deployment/dist/`), che automatizza:
creazione directory, venv, `.env`, database SQL Server, migrate, collectstatic, createcachetable,
utente admin e configurazione IIS completa.
Il bundle dell'exe include anche il runtime Tcl/Tk richiesto dalla UI e una copia filtrata di `django_app/`, senza `.env`, `.venv`, database locali, cartelle temporanee, cache, log o media della macchina di build.
Il wizard e `deployment/scripts/setup-environment.ps1` auto-rilevano ora un Python 3.11+ valido anche se non e installato in `C:\Python311\python.exe`; in caso di errore su venv, dipendenze o migration non attivano la release incompleta sotto IIS. Durante il setup il wizard scrive anche `DB_DRIVER` nel `.env`, lo riallinea al driver SQL Server realmente installato sul server applicativo e verifica gli asset statici chiave dopo `collectstatic` prima di attivare la release.

Prerequisiti: IIS + HttpPlatformHandler, SQL Server, un driver ODBC SQL Server installato (18/17/13 o equivalente), sqlcmd, Python 3.11+.
Il venv condiviso dell'ambiente deve includere anche `waitress`, ora dichiarato direttamente in `django_app/requirements.txt`.
Nel deploy manuale basta fornire il file `.env` dell'ambiente in `config\` cosi lo script lo copia nella release attiva sotto `django_app\.env`. Nel Server Dashboard del wizard e disponibile anche un reset password live degli account locali per l'ambiente selezionato, ma solo se il setup/exe e avviato come Administrator.

Nota sicurezza deployment: gli allegati ticket non devono essere serviti direttamente da `/media/tickets/`.
I nuovi upload usano storage privato e il download passa da una view Django autenticata; il template IIS incluso nel repo blocca l'accesso diretto alla cartella pubblica legacy.

Per il flusso manuale e il troubleshooting: [deployment/README_DEPLOY_IIS_WINDOWS.md](deployment/README_DEPLOY_IIS_WINDOWS.md)

Prima di creare lo zip, `deployment/scripts/package-release.ps1` verifica `deployment/dist/SetupWizard.exe` usando le stesse regole di bundle condivise in `deployment/setup_wizard_bundle_rules.json`; se l'exe manca o e obsoleto rispetto ai file runtime davvero inclusi, lo rigenera automaticamente con PyInstaller e solo dopo esegue `tools/release_guard.ps1`. Il controllo continua a ignorare i file test-only esclusi dal bundle (`tests.py`, `test_*.py`, `tests/`, `conftest.py`) e blocca il packaging solo se restano drift su versioni, documentazione canonica o smoke ACL non distruttivo.
Nei deploy `test` e `prod`, i flussi supportati eseguono anche `python manage.py allinea_tipo_assenza_flessibilita` subito dopo `migrate`, cosÃƒÆ’Ã‚Â¬ `CK_assenze_tipo` resta allineato a `FlessibilitÃƒÆ’Ã‚Â ` prima dell'attivazione della release; se il database non contiene la tabella legacy `assenze`, il comando termina in no-op senza rompere il setup. I flussi supportati verificano inoltre che `collectstatic` abbia realmente prodotto `static\core\css\theme.css` e `static\monitoring\css\monitoring.css`.

### Post-deploy (obbligatorio)

Se il deploy viene eseguito manualmente (senza `SetupWizard.exe`), eseguire sempre:

```powershell
python django_app\manage.py migrate
```

Nel flusso standard e upgrade di `SetupWizard.exe`, `migrate` viene eseguito automaticamente.

## Documentazione collegata

La raccolta interna in `/admin-portale/hub/guide/` indicizza automaticamente questi documenti e le altre guide supportate presenti in `tools/`, `doc/`, `deployment/` e `django_app/assets/README.md`. Nella vista singola documento i pulsanti principali sono compatti per lasciare piu spazio al contenuto.

- [Guida deployment IIS (manuale + troubleshooting)](deployment/README_DEPLOY_IIS_WINDOWS.md)
- [Start here per persona](doc/START_HERE.md)
- [Testing, smoke e UAT](doc/TESTING.md)
- [Architettura target e dismissione legacy](doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md)
- [Manuale amministratore ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â navigazione e permessi](tools/MANUALE_ADMIN_NAVIGAZIONE_PERMESSI.md)
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
