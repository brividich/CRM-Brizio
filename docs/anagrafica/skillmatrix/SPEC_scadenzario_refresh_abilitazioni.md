# SPEC — Scadenzario abilitazioni macchina + avvio refresh HR→CAR (MOD.187)

> Data: 2026-07-03 · Branch: `feature/skill-matrix-mod187` · Fase: **F10** (segue F9 in
> `docs/skill-matrix/BUILD_LOG.md`). Design approvato in sessione di brainstorming.

## 1. Obiettivo

Rendere il **refresh semestrale delle abilitazioni macchina** gestibile come una
**scadenza**, con un posto **esplicito** dove vederla e da cui **HR (o un delegato)
"dà il via"**; il merito della rivalutazione resta al **CAR** sul proprio reparto
(pagina Refresh F6 esistente). Quando HR avvia il refresh di un reparto, il CAR viene
avvisato **in-portale** (notifica + "Cose da gestire") **e via email**.

Scelta di modello (confermata): **scadenzario dedicato dentro Skill Matrix**, unità
principale **per reparto** con **drill-down** al dettaglio persone×macchine.
**Scartato**: modellare il refresh come corso di formazione (`TrainingCourse`).

## 2. Principi e invarianti (da preservare)

- **Additivo.** La scadenza esiste già: `AbilitazioneMacchina.prossima_revisione`
  (spostata di `periodicita_refresh_mesi` a ogni rivalutazione). Nessun nuovo
  concetto, solo un punto di accesso/gestione.
- **Lettura live**, come `qualifiche_scadenzario` (volumi piccoli); niente cache tipo
  `TrainingDeadline`.
- **Skill Matrix resta read-only verso gli altri moduli**: espone helper, non accoppia
  all'indietro. Il modulo `dashboard` chiama un helper di `anagrafica`, mai il contrario.
- **SQL-Server-safe**: nessun indice parziale, nessun `UniqueConstraint` con
  `condition`, nessun campo `unique` nullable.
- **Dipendente sempre via `legacy_anagrafica_id`** (nessuna FK al modello dipendente).
- **GDPR**: minimizzazione dati nell'email (nessun elenco nominativo non necessario;
  solo reparto + conteggi + link al portale). `email` è il login legacy → per le
  notifiche si usa **`email_notifica`** (`AnagraficaDipendente`).
- **Fail-safe handoff**: un errore di invio email/notifica **non** deve annullare
  l'apertura della campagna.
- **HR dà il via manualmente**: nessuno scheduler che apra campagne da solo (fuori scope).

## 3. Modello dati

Unico cambiamento di modello:

- `SkillMatrixConfig` (in `models_skillmatrix.py`): nuovo campo
  **`preavviso_refresh_giorni = PositiveSmallIntegerField(default=60)`** — soglia
  "in arrivo" dello scadenzario (giorni prima di `prossima_revisione`).
  Migration nuova (prossimo numero disponibile in `anagrafica/migrations/`, atteso
  `0075`).

Nessun altro modello nuovo. `CampagnaRefresh` (trigger) e
`AbilitazioneMacchina.prossima_revisione` (scadenza) sono sufficienti.

## 4. Servizio — estensione di `services/skillmatrix_refresh.py`

Stati per reparto (derivati, oggi = `timezone.localdate()`, `config` da
`SkillMatrixConfig.get_instance()`):

- **scaduto**: esiste ≥1 abilitazione `in_lista` con `prossima_revisione < oggi`.
- **in arrivo**: min `prossima_revisione` (tra le non scadute) `<= oggi +
  preavviso_refresh_giorni`.
- **ok**: altrimenti.

Funzioni nuove:

```python
def scadenzario_reparti(oggi=None) -> list[dict]:
    """Un dict per reparto con abilitazioni macchina:
    {reparto, prossima_revisione (min in_lista), n_scadute, n_in_arrivo,
     n_totali, stato ('scaduto'|'in_arrivo'|'ok'),
     campagna_aperta (bool), campagna_id, campagna_periodo_inizio}.
    Ordinamento per urgenza: scadute desc, poi prossima_revisione asc, poi reparto."""

def avvia_refresh(*, reparto, avviatore_ruolo="", avviatore_legacy_id=None,
                  oggi=None) -> tuple[CampagnaRefresh, bool]:
    """Apre (idempotente) la campagna del reparto e restituisce (campagna, created).
    Se created=True notifica il CAR (in-app + email best-effort). Se la campagna era
    già aperta NON rinotifica (no spam). L'apertura non è mai annullata da un errore
    di notifica."""

def campagne_da_gestire(car_legacy_id) -> list[dict]:
    """Read-only per 'Cose da gestire': campagne APERTE dei reparti di cui il legacy_id
    è caporeparto. Ogni item: {reparto, campagna_id, n_da_rivalutare, url}."""
```

Helper CAR→email (pattern `services/onboarding.py`):
`Reparto.objects.filter(nome__iexact=reparto).first()` →
`caporeparto_legacy_id` → `AnagraficaDipendente.filter(id=...).values_list("email_notifica")`.
Restituisce anche `car_legacy_id` per la notifica in-app.

Modifica minima a `apri_campagna`: esporre il flag `created` (oggi scarta il secondo
valore di `get_or_create`). `avvia_refresh` lo riusa.

Notifica CAR (dentro `avvia_refresh`, best-effort, ciascuna in `try/except`):
- in-app: `core.notifiche.invia_notifica(car_legacy_id, "skm_refresh", messaggio, url)`
  con `url = "/anagrafica/skill-matrix/refresh/?reparto=<reparto>"`;
- email: `core.email_utils.send_hub_mail(subject, body, [car_email],
  email_type="Anagrafica HR", section_label="Refresh abilitazioni macchina",
  fail_silently=True)`. Corpo sintetico: reparto, n° abilitazioni da rivalutare, link.

## 5. View + template + URL

- Nuova view **`skm_scadenzario`** in `anagrafica/views.py`:
  - **GET** `/anagrafica/skill-matrix/scadenzario/`: KPI in cima (reparti con arretrati,
    totale abilitazioni scadute, campagne aperte), tabella reparti con chip di stato,
    prossima scadenza, stato campagna, bottone **"Avvia refresh"**. Filtro `stato`
    (`scaduto`/`in_arrivo`/`tutti`). Export CSV (`?format=csv`).
  - **POST** (`azione=avvia`, `reparto=...`): chiama `avvia_refresh(...)` con il ruolo
    e il `legacy_id` dell'avviatore; messaggio di esito; redirect (PRG).
  - Guardia: `from .acl_bootstrap import PERM_SKM_MANAGE` +
    **`_check_skm_permission(request, PERM_SKM_MANAGE)`** (identica a `skm_refresh` /
    `skm_match_validazione`, verificate in `views.py`). Drill-down: link reparto →
    `anagrafica:skm_refresh` con `?reparto=<reparto>`.
- Template `anagrafica/pages/skm_scadenzario.html`: design HUB (`hr-shell`/`hr-pagehead`,
  navy/cyan), subnav del modulo, chips/KPI coerenti con `skm_refresh.html` e gli altri
  scadenzari. Nomi dipendente fail-safe (sorgente legacy assente → "ID n").
- `anagrafica/urls.py`: `path("skill-matrix/scadenzario/", views.skm_scadenzario,
  name="skm_scadenzario")`.

## 6. Handoff "Cose da gestire" (modulo `dashboard`)

In `dashboard/views_mie_attivita.py`, `build_cose_da_gestire`: nuova sezione difensiva

```
{"key": "skm_refresh", "label": "Refresh abilitazioni macchina", "tone": "warning",
 "icon": "🔧", "items": <da campagne_da_gestire(legacy_user_id)>,
 "all_url": _safe_url("anagrafica:skm_scadenzario"),
 "empty": "Nessun refresh abilitazioni da gestire."}
```

Import locale/difensivo del servizio anagrafica (un errore non rompe le altre sezioni),
coerente con lo stile delle sezioni esistenti (`_my_*`). Direzione dipendenza:
`dashboard → anagrafica` (mai il contrario).

## 7. Navigazione + ACL

- **Subnav**: nuova voce **"Scadenzario abilitazioni"** nel gruppo *Skill Matrix*
  (pilastro Competenze), via data migration idempotente per `url_value`, stesso idioma
  di `0072_subnav_skill_matrix` / `0074_subnav_skill_matrix_refresh`. Voce **non di
  sistema** (riordinabile/nascondibile da Impostazioni → Navigazione).
- **ACL canonico**: la route `anagrafica:skm_scadenzario` va **mappata**:
  - binding in `anagrafica/acl_bootstrap.py` verso il permesso
    **`anagrafica.skillmatrix.manage`** (è un'azione HR: apre campagne);
  - bump della cache key del bootstrap se richiesto dal pattern (come per le route
    skill-matrix esistenti);
  - **CRITICO**: senza binding, in `ACL_STRICT_CANONICAL` (prod) il middleware rende
    la route **solo-superuser**. Verificare la mappatura `API_ACL_GATE_PATHS` /
    binding come da nota `acl_middleware_api_gate_paths`.

## 8. Test (nuovo `tests_skillmatrix_scadenzario.py` + estensioni)

Servizio:
- `scadenzario_reparti`: aggregazione e stati (scaduto/in_arrivo/ok) su fixtures;
  ordinamento per urgenza; reparto senza abilitazioni assente.
- `avvia_refresh`: apre campagna (created=True) **e** notifica una sola volta; seconda
  chiamata idempotente (created=False, **nessuna** nuova notifica); errore email
  mockato **non** annulla l'apertura (campagna presente).
- `campagne_da_gestire`: ritorna solo le campagne aperte dei reparti del CAR.
- Risoluzione CAR→email/legacy_id (reparto→caporeparto→email_notifica), con fallback
  a vuoto se manca il CAR.

View:
- render (KPI + righe), filtro `stato`, export CSV; POST `avvia` apre campagna e crea
  notifica; accesso negato senza permesso `manage`; voce di menu seminata.

Dashboard:
- `build_cose_da_gestire` popola la sezione `skm_refresh` per un CAR con campagna aperta;
  vuota altrimenti; un errore del servizio non rompe le altre sezioni.

Comando di verifica:
`python django_app\manage.py test django_app.anagrafica.tests_skillmatrix_scadenzario --settings=config.settings.test --keepdb`
(+ `dashboard` per la sezione cose-da-gestire). `makemigrations anagrafica --check`
pulito; `manage.py check` pulito.

## 9. Fuori scope (YAGNI)

- Nessun `TrainingCourse` per il refresh (scartata l'opzione "corso in Formazione").
- Nessuno scheduler automatico di apertura campagne (HR dà il via manualmente).
- Nessuna modifica alla regola di **continuità** (F5), che resta separata.
- Nessuna cache di scadenze; nessun ricalcolo batch.

## 10. File toccati (riepilogo)

Nuovi:
- `django_app/anagrafica/templates/anagrafica/pages/skm_scadenzario.html`
- `django_app/anagrafica/tests_skillmatrix_scadenzario.py`
- `django_app/anagrafica/migrations/0075_*.py` (campo config)
- `django_app/anagrafica/migrations/0076_subnav_skill_matrix_scadenzario.py` (subnav)

Modificati:
- `django_app/anagrafica/models_skillmatrix.py` (campo `preavviso_refresh_giorni`)
- `django_app/anagrafica/services/skillmatrix_refresh.py` (nuove funzioni + `created`)
- `django_app/anagrafica/views.py` (`skm_scadenzario`)
- `django_app/anagrafica/urls.py` (route)
- `django_app/anagrafica/acl_bootstrap.py` (binding route → `skillmatrix.manage`)
- `dashboard/views_mie_attivita.py` (sezione "Refresh abilitazioni macchina")
- `docs/skill-matrix/BUILD_LOG.md` (fase F10)
- `CHANGELOG.md` (obbligatorio) · `README.md` se cambia funzionalità visibile

## 11. Note di rilascio / deploy

- Migrations `0075`/`0076` da applicare (il Setup Wizard fa migrate selettivo →
  assicurarsi che `anagrafica` sia migrata; vedi nota deploy migrate globale).
- Nessun dato personale nei file committati (i seed CSV restano gitignore).
