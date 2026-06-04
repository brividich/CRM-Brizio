# Piano ACL Fase 2 — Azzerare il fallback legacy applicativo

**Data:** 2026-06-04
**Branch strumenti Fase 1:** `feat/acl-chiusura-migrazione-fase1` (commit `3194c32`, `2a3c330`)
**Riferimento architettura:** [02_ARCHITECTURE.md](02_ARCHITECTURE.md) (sezione ACL). Nota: esiste
anche `doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md`, ma `doc/` è **gitignorato** (vedi
`.gitignore` → `doc/*`), quindi quel file potrebbe non essere presente su un checkout pulito.

---

## Punto di partenza (leggere prima di toccare qualsiasi cosa)

Questo documento è pensato per essere **autosufficiente**: una nuova sessione deve poter
ripartire da qui senza contesto esterno. Stato al 2026-06-04:

- **Strumenti Fase 1** (comandi `acl_diagnose`, `acl_sync_legacy_grants`, esclusione admin
  in `acl_fallback_report`) vivono sul branch **`feat/acl-chiusura-migrazione-fase1`**. Se
  non sei su quel branch o esso non è ancora mergiato su `main`, **i comandi potrebbero non
  esistere**: verifica con `python django_app\manage.py help | findstr acl`.
- **Il caso che ha originato il lavoro:** un utente (ruolo *Manutenzione*) con permessi
  `tickets` assegnati dalla **UI legacy** riceveva 403, perché `/tickets/` ha un binding
  canonico e i permessi legacy vengono **ignorati a runtime** quando esiste un binding
  canonico. Questo è esattamente il "doppio sistema" che la Fase 2 elimina.
- **CHANGELOG conteso:** al momento della stesura il `CHANGELOG.md` nel working tree conteneva
  voci di **più sessioni parallele** (ACL + automazioni). Non assumere che lo stato git sia
  pulito: fai `git status` e `git log --oneline -10` prima di committare, e committa solo i
  tuoi file.
- **Ri-misura sempre da zero** prima di pianificare (i numeri sotto sono di un'istantanea dev):
  ```powershell
  python django_app\manage.py acl_fallback_report --only-unbound --settings=config.settings.<env>
  ```

### ⚠️ Trappola dei filtri per modulo (verificata, importante)

I comandi **non filtrano allo stesso modo** e il "nome del modulo" ha tre forme diverse:

| Cosa | Forma | Esempio | Note |
|---|---|---|---|
| Prefisso **path** URL | con trattino | `rilevazione-incidenti/` | Come appare nel report e negli URL. |
| **App label** Django | con underscore | `rilevazione_incidenti` | È ciò che vuole `bootstrap_acl_v2 --apps`. |
| Namespace nel route **name** | spesso **assente** | — | Molte route hanno `name` semplici (`lista`, `nuovo`, `dettaglio`) senza `app:`. |

Conseguenza concreta (testata): **`acl_fallback_report --app rilevazione_incidenti` restituisce
VUOTO**, perché il flag `--app` matcha il namespace nel route *name*, che qui non esiste. Per
elencare le route unbound di un modulo, usa il report **globale filtrato per path**:

```powershell
# elenco unbound di un modulo (affidabile): report globale + filtro sul path
python django_app\manage.py acl_fallback_report --only-unbound --settings=config.settings.<env> | findstr "rilevazione-incidenti/"
```

Mentre per **generare i binding** usa l'**app label** (underscore):

```powershell
python django_app\manage.py bootstrap_acl_v2 --apps rilevazione_incidenti --dry-run --settings=config.settings.<env>
```

App label verificate (per `--apps`): `assets`, `attrezzature`, `tasks`, `automazioni`,
`admin_portale`, `anagrafica`, `fornitori`, `timbri`, `tickets`, `diario_preposto`,
`rilevazione_incidenti`, `dpi`, `procedure_refresh`.

---

## Obiettivo

Eliminare il **doppio sistema ACL** (legacy + canonico v2) portando tutte le route
applicative sotto `RoutePermissionBinding` canonico, così che resti **un solo posto**
dove gestire i permessi (`/admin-portale/acl-canonico/`). La Fase 1 (già fatta) ha
fornito gli strumenti per diagnosticare e migrare; la Fase 2 li usa modulo per modulo;
la Fase 3 (futura) rimuove il codice legacy.

> **Non** è un lavoro da fare in un colpo solo. Una route bindata male = qualcuno perde
> accesso in prod. Procedere **un modulo per PR**, con verifica dopo ciascuno.

---

## Stato di partenza (misurato su dev, 2026-06-04)

> ⚠️ **Il "debito" era quasi tutto un artefatto del report.** Tre revisioni successive
> (stessa data) hanno smontato la stima iniziale di "705/1298 unbound":
> 1. Escluse le ~596 route del **Django admin** (`admin/...`, fuori perimetro).
> 2. Il report ignorava i **184 binding path-based** (`prefix`, senza route_name) →
>    falsi positivi. Fix: riuso di `core.acl_v2._find_canonical_binding`. 705 → 288.
> 3. Il report **non ricostruiva il namespace** del route name (es. `fornitori:create`),
>    mentre i binding e il middleware (`view_name`) lo usano → altri falsi positivi.
>    Fix in `_walk`. 288 → **96**.

**Conclusione: la migrazione ACL canonica è di fatto già completa.**

- **837 route applicative** (596 route Django admin escluse).
- **96 route "unbound"** residue, di cui **77 sono `admin-portale`** (decisione: restano
  gated sul permesso admin, NON si migrano — è corretto che l'area admin sia solo-admin).
- Le restanti ~19 sono **endpoint per-utente-autenticato** o con **gating proprio**, che
  **non devono** avere un binding di permesso di modulo (vedi sotto).
- **Tutti i moduli di dominio sono già canonici (0 unbound):** `tickets`, `dpi`, `tasks`,
  `assets`, `anagrafica`, `timbri`, `diario-preposto`, `rilevazione-incidenti`,
  `fornitori`, `attrezzature`, `automazioni`.

Il caso a.astarita (403 su tickets) non era "binding mancante" ma **grant di ruolo
mancante** → si risolve con `acl_sync_legacy_grants`, non con nuovi binding.

Comando di misura (dopo i fix al report di questa sessione):
```powershell
python django_app\manage.py acl_fallback_report --only-unbound --settings=config.settings.<env>
```

---

## Le 96 route residue — analisi (nessuna richiede migrazione)

| Gruppo | Route | Decisione |
|---|---:|---|
| `admin-portale` | 77 | **Lasciare gated su admin.** Area di amministrazione, solo-admin per design. |
| `api/notifiche/*`, `api/table-prefs` | 4 | **Per ogni utente autenticato** (notifiche personali, preferenze tabella). Bindarle a un permesso le romperebbe. Escludere. |
| `assistente-ai/*` | 4 | **Gating proprio** (governance AI, consensi, tool ACL — vedi `13_AI_GOVERNANCE.md`). Fuori dall'ACL route-binding standard. |
| `hub/home/*` | 3 | **Home personale per ogni autenticato.** Escludere. |
| `2fa`, `login`, `logout`, `health`, `coming`, `monitoring`, `approval-actions` | ~8 | **Superfici tecniche / a token / auth.** Non si migrano (vedi sotto). |

Nessuna di queste va trasformata in `RoutePermissionBinding` con permesso di modulo:
sono o "accessibili a ogni utente loggato" o con gating dedicato. Forzare un binding
introdurrebbe **regressioni** (utenti che perdono notifiche, home, AI).

### Superfici da NON migrare automaticamente
- **`approval-actions/` e `automazioni/approvazione/`**: superfici a token, gating dedicato (vedi `CLAUDE.md` → Security Boundaries). Non trattare come route ACL normali.
- **`2fa/`, `login/`, `logout/`, `setup/` (wizard iniziale)**: hanno gate propri; valutare caso per caso, probabile esclusione esplicita.
- **`monitoring/healthz`, `readyz`, `version`**: endpoint tecnici/pubblici, fuori ACL.

---

## Ordine consigliato

Dato che i moduli di dominio sono già coperti, il debito reale (288) è concentrato e
diverso da quanto si pensava. Ordine aggiornato:

1. **Pilota** (basso rischio, piccolo): `attrezzature` (18) **oppure** `fornitori` (14) —
   azioni/API residue, modulo già quasi completo, perimetro chiaro.
2. **Code medie**: `automazioni` (25, endpoint designer/HTMX), `api` (7), `assistente-ai` (4), `hub` (3).
3. **Superfici speciali**: decidere **esclusioni esplicite** (non binding) per
   `approval-actions`, `2fa`, `login`, `logout`, `health`, `monitoring`, `coming`.
4. **Blocco grosso, per ultimo, con review dedicata**: `admin-portale` (205). È la UI di
   amministrazione: molti endpoint API/HTMX interni. Valutare se richiedono binding granulari
   o se basta un binding prefix `/admin-portale/` gated sul permesso admin. **Decisione di
   design da prendere prima di toccarlo**, non meccanica.

Nota: `anagrafica` non è più nella lista (0 unbound). Il rischio GDPR resta sui **grant**,
non sui binding.

Razionale: validare il flusso su moduli piccoli, accumulare fiducia, lasciare il blocco
`admin-portale` (che vale da solo il 70% del debito) quando il processo è collaudato e dopo
una decisione esplicita sul livello di granularità.

---

## Procedura per ogni modulo (ripetibile)

Tutto in **dry-run prima**, poi `--apply`. Una PR per modulo. **Attenzione ai filtri**:
`<path>` è il prefisso URL con trattino (es. `rilevazione-incidenti`); `<app_label>` è
l'app Django con underscore (es. `rilevazione_incidenti`). Vedi la tabella nel "Punto di
partenza".

```powershell
# 1. Cosa manca in questo modulo (NON usare --app: spesso da' vuoto. Filtra per path.)
python django_app\manage.py acl_fallback_report --only-unbound --settings=config.settings.<env> | findstr "<path>/"

# 2. Genera le proposte di binding/permission (NON scrive) — usa l'APP LABEL (underscore)
python django_app\manage.py bootstrap_acl_v2 --apps <app_label> --dry-run --settings=config.settings.<env>

# 3. Applica binding + permission canonici
python django_app\manage.py bootstrap_acl_v2 --apps <app_label> --import-legacy --apply --settings=config.settings.<env>

# 4. Allinea i grant di ruolo ai permessi legacy effettivi (prima dry-run) — --app = source_app (underscore)
python django_app\manage.py acl_sync_legacy_grants --app <app_label> --settings=config.settings.<env>
python django_app\manage.py acl_sync_legacy_grants --app <app_label> --apply --settings=config.settings.<env>

# 5. VERIFICA su utenti reali rappresentativi (uno per ruolo) — read-only
#    Se la route non ha namespace nel name, usa --path invece di --route.
python django_app\manage.py acl_diagnose --user <utente> --path /<path>/ --settings=config.settings.<env>

# 6. Conferma che il modulo non ha più unbound
python django_app\manage.py acl_fallback_report --only-unbound --settings=config.settings.<env> | findstr "<path>/"
```

> Nota su `acl_sync_legacy_grants --app`: filtra sul `source_app` dei `RoutePermissionBinding`,
> che usa l'**app label** con underscore (verificato: `source_app='rilevazione_incidenti'`).
> Quindi qui l'underscore è corretto, a differenza di `acl_fallback_report --app`.

### Checklist per modulo (Definition of Done)
- [ ] `acl_fallback_report --only-unbound | findstr "<path>/"` → 0 route unbound (escluse quelle marcate "speciali").
- [ ] `acl_coverage_report` non peggiora il totale `missing`.
- [ ] Almeno un utente per ruolo verificato con `acl_diagnose` (allow/deny attesi).
- [ ] Test del modulo verdi + `manage.py check --settings=config.settings.test`.
- [ ] Verifica manuale in app: accesso consentito a chi deve, 403 a chi non deve.
- [ ] CHANGELOG aggiornato (voce per modulo).

---

## Fase 3 (futura, NON in questo piano)

Solo quando `acl_fallback_report --only-unbound` è a zero (route applicative):
- Spegnere il ramo di fallback legacy in `core/acl_v2.py` (`resolve_acl_access`).
- Rendere read-only / dismettere la UI permessi legacy (`/admin-portale/permessi/`).
- Pianificare la dismissione della tabella legacy `permessi`.

A quel punto il doppio sistema **non esiste più**: un solo posto di gestione.

---

## Rischi e mitigazioni

- **Regressione di accesso in prod** → sempre dry-run prima; verifica `acl_diagnose` su utenti reali; una PR per modulo per limitare il blast radius.
- **`bootstrap_acl_v2 --import-legacy` sovrascrive grant manuali** → `acl_sync_legacy_grants` di default rispetta i grant manuali (solo `--force` li sovrascrive). Usare `--force` solo con review esplicita.
- **Override utente persi** → nessun comando tocca `UserPermissionGrant`: restano autoritativi.
- **Superfici a token / endpoint tecnici** → escluderle esplicitamente, non bindarle come route normali.
