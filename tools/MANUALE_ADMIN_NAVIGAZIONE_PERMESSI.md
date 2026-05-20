# Manuale Amministratore - NOVICROM HUB

> NOVICROM HUB · Aggiornato: 2026-05-19 (v1.0.2)
> Percorso admin: **Admin Portale**
> Governance legacy/canonico: vedi anche [`../doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md`](../doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md)

## Panoramica

L'area admin convive oggi con tre strati distinti:

- **ACL canonico v2**: sorgente primaria di sicurezza per route e permission code
- **ACL legacy**: fallback di compatibilita basato su `pulsanti` e `permessi`
- **Navigation Registry**: visibilita menu, topbar, subnav, sidebar e override utente

Regola pratica:

- per aggiungere o riordinare voci menu usa **Navigation Builder**
- per governare accessi e copertura route usa **ACL Canonico**
- per leggere il perimetro residuo legacy usa **Route Coverage**, **Diagnostica ACL** e la documentazione target
- per definire il layout iniziale della `scheda-dipendente` usa la scheda stessa con un account admin e il pulsante `Salva come template iniziale`

## Mappa rapida delle pagine admin

| Pagina | URL | Quando usarla |
| --- | --- | --- |
| ACL Canonico | `/admin-portale/acl-canonico/` | Creare permission code, binding, grant e override |
| Route Coverage | `/admin-portale/acl-route-coverage/` | Vedere `CANONICAL_BOUND`, `LEGACY_FALLBACK`, `UNBOUND` |
| Diagnostica ACL | `/admin-portale/acl-diagnostica/` | Capire perche un accesso e consentito o negato |
| Mappa Permessi / Navigazione | `/admin-portale/mappa-permessi-navigazione/` | Correlare route, menu, grant, override e fallback |
| Navigation Builder | `/admin-portale/navigation-builder/` | Gestire topbar, subnav, sidebar, page e admin_subnav |
| Topbar Live / Gestione Pulsanti | pagine legacy | Solo per manutenzione o compatibilita storica |
| Hub Guide | `/admin-portale/hub/guide/` | Consultare documentazione tecnica e operativa |

## Navigazione: cosa governa cosa

### Navigation Builder

Usalo per:

- aggiungere nuove voci a topbar, subnav, sidebar, page, admin_subnav
- riordinare voci senza toccare codice
- applicare override di visibilita coerenti con i ruoli

Non usarlo come sostituto dell'ACL: una voce visibile non rende automaticamente accessibile la route.

### Pulsanti legacy

Restano utili quando devi:

- leggere configurazioni storiche ancora agganciate a `pulsanti`
- mantenere alias o route non ancora migrate al canonico
- verificare compatibilita con ACL legacy

## ACL Canonico v2

### Flusso minimo corretto

1. Crea o verifica il `permission_code`.
2. Collega la route con un `RoutePermissionBinding`.
3. Attiva almeno un grant di ruolo coerente.
4. Verifica il risultato in `Route Coverage`.
5. Prova un caso allow e un caso deny in `Diagnostica ACL`.

### Convenzione permission code

Formato raccomandato:

```text
modulo.risorsa.azione
```

Esempi:

- `assets.workorder.view`
- `admin_portale.acl.manage`
- `procedure_refresh.campaign.publish`

### Override utente

Usali solo quando:

- il comportamento desiderato non coincide con il ruolo standard
- vuoi forzare un allow o deny temporaneo
- hai gia verificato che la route abbia un binding canonico

Gli override vanno sempre motivati e rivisti quando il ruolo viene riallineato.

## Route Coverage

Gli stati da leggere sono:

- `CANONICAL_BOUND`: la route e gia coperta dal layer canonico
- `LEGACY_FALLBACK`: la route funziona ancora grazie al legacy
- `UNBOUND`: manca un binding esplicito
- `COMING_SOON_EXCLUDED`: esclusa intenzionalmente
- `REDIRECT_ONLY`: alias o redirect, non pagina finale

### Regola operativa

Prima di UAT o release:

- nessuna route critica deve restare `UNBOUND`
- `LEGACY_FALLBACK` deve essere limitato ai residui dichiarati
- ogni caso critico deve avere un owner e un piano di uscita dal fallback

## Diagnostica ACL

Usala per capire:

- quale layer ha deciso l'accesso
- se il problema e nel binding, nel grant o in un override
- se stai ancora passando dal fallback legacy

Dati da controllare sempre:

- `Decision source`
- sintesi umana
- trace tecnico
- presenza o assenza del binding canonico

## Mappa Permessi / Navigazione

Questa pagina e la vista migliore quando vuoi correlare:

- route runtime
- voce menu corrispondente
- grant di ruolo
- override utente
- fallback legacy o redirect

Con il filtro ruolo attivo puoi verificare rapidamente se una discrepanza nasce da:

- permission code mancante
- grant assente
- voce menu non allineata
- compatibilita legacy ancora aperta

## Flussi operativi consigliati

### Aggiungere una nuova pagina protetta

1. Crea la route Django.
2. Aggiungi la voce nel Navigation Builder se serve.
3. Crea `permission_code` e binding in ACL Canonico.
4. Configura i grant minimi necessari.
5. Verifica coverage e diagnostica.
6. Aggiorna changelog e documentazione canonica.

### Capire un 403

1. Apri `/admin-portale/acl-diagnostica/`.
2. Inserisci utente, route o path.
3. Leggi `Decision source`.
4. Se il source e `legacy_fallback`, pianifica la migrazione al canonico.

### Preparare UAT

1. Esegui o fai eseguire `seed_acl_uat --reset`.
2. Controlla `Route Coverage`.
3. Allega export CSV e screenshot allow/deny.
4. Elenca i residui `LEGACY_FALLBACK`.

## Governance pre-rilascio

Prima di creare una release:

```powershell
python manage.py bootstrap_acl_v2 --dry-run --settings=config.settings.dev
powershell -ExecutionPolicy Bypass -File .\tools\release_guard.ps1
```

Il release guard blocca il package se trova:

- versioni fuori sync
- documentazione canonica incoerente
- riferimenti docs incoerenti su `config.settings.dev` / `config.settings.test` / `config.settings.prod` o su `django-environ`
- fallback versione non allineati
- `SetupWizard.exe` obsoleto
- secret ad alta confidenza nei file Git (`secret_hygiene_check`)
- regressione della copertura ACL oltre la baseline `acl_coverage_report --max-missing 216`
- FAIL in `validate_deployment`; i WARN restano ammessi salvo esecuzione con `-FailOnDeploymentWarn`

Il guard salva `django_app\acl_report_latest.json` e
`django_app\deployment_validation_latest.json`. La baseline ACL va alzata solo
con decisione esplicita; finche esistono missing storici non rendere
`--fail-on-missing` obbligatorio.

## Monitoring e controlli secondari

Controlla periodicamente anche:

- `/admin-portale/monitoring/`
- `/admin-portale/hub/guide/`
- changelog della versione corrente
- documenti `doc/TESTING.md` e `doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md`

## Documenti collegati

- [`../doc/START_HERE.md`](../doc/START_HERE.md)
- [`../doc/TESTING.md`](../doc/TESTING.md)
- [`../doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md`](../doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md)
- [`../doc/ACL_V2_ADMIN_QUICK_GUIDE.md`](../doc/ACL_V2_ADMIN_QUICK_GUIDE.md)
- [`../doc/ACL_V2_UAT_CHECKLIST.md`](../doc/ACL_V2_UAT_CHECKLIST.md)

Fine manuale - NOVICROM HUB Admin (v0.9.15)
