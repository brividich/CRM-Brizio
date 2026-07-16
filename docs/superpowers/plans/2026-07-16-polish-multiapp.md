# Polish multi-app (Stream 5) — Piano TDD

> **For agentic workers:** REQUIRED SUB-SKILL: usare superpowers:subagent-driven-development (consigliato) o superpowers:executing-plans per eseguire questo piano task-per-task. Gli step usano checkbox (`- [ ]`) per il tracking.

**Goal:** rifinitura "polish" su quattro app disgiunte del portale — **TIMBRI**
(ricerca per qualifica), **PROCEDURE REFRESH** (assegnazione a tutti i documenti +
pulizia impostazioni), **ASSET** (lightbox immagine header + planimetria reale per
asset), **KICKOFF/`tasks`** (fix dashboard kickoff programmati + assegnazione
attività da incontro + pulizia impostazioni). Ogni area è un blocco autonomo con
commit separati.

**Spec:** `docs/superpowers/specs/2026-07-16-polish-multiapp-design.md` (nel
checkout `C:\Dev\Portale Novicrom`).

## Global Constraints

- **Worktree dedicato** (Session Isolation CLAUDE.md): mai lavorare/committare nel
  checkout condiviso `C:\Dev\Portale Novicrom`. Il **Task 1** crea
  `C:\Dev\pn-polish-multiapp` su branch `feature/polish-multiapp` da `origin/main`;
  è la cwd di tutti i task.
- **Mai `git add -A` / `git commit -a`**: staging con percorsi espliciti. **Non
  committare in stesura** — solo ai passi di commit indicati.
- **Venv assoluto**: usare sempre `& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe"`
  (il worktree non ha `.venv`).
- **PowerShell** (Windows): `&` per invocare l'exe quotato; `Set-Location` alla
  radice del worktree.
- **Comando test per-app** (dalla radice del worktree):
  `& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test <app>.<test_module> --settings=config.settings.test --keepdb --verbosity 1`
- **Timeout test ≥ 600000 ms**. La **prima** run dopo una nuova migrazione va
  **senza `--keepdb`** (DB fresco); le run successive con `--keepdb`. In questo
  stream non si creano modelli/migrazioni nuove salvo imprevisti, quindi
  `--keepdb` è quasi sempre valido — ma la prima run in assoluto nel worktree può
  richiedere la creazione del DB di test.
- Non lanciare la suite intera; solo i test dell'app toccata. Regressione per-app
  nel Task finale.
- **Template Django**: `{# #}` commenta UNA riga; niente attributi `_` iniziale.
  Rimozioni di quadranti/branding: se il contenuto è dato/config si rimuove via
  dato; qui i target sono **template statici** → edit diretto del template. La
  variante "branding compatto" è un **modificatore opt-in** sui componenti
  condivisi `core/components/module_*` (backward-compatibile).
- **ACL invariata**: riuso dei gate esistenti per modulo. Nei test usare
  `@override_settings(LEGACY_AUTH_ENABLED=False)` + superuser dove l'ACL
  middleware intercetterebbe (trappola nota timbri/assets).
- **App diverse dagli altri stream**: questo stream tocca `timbri`,
  `procedure_refresh`, `assets`, `tasks` e i componenti condivisi
  `core/components/module_*`. **Non tocca `anagrafica`** → **nessun conflitto
  cross-stream** con gli stream visite-mediche/sessioni.
- **CHANGELOG.md + README.md** obbligatori (Task finale). **Niente version bump.**

## Ordine di esecuzione e dipendenze (4 blocchi)

- **Task 1**: setup worktree (obbligatorio, prima di tutto).
- **Blocco A — TIMBRI** (Task 2): autonomo.
- **Blocco B — PROCEDURE REFRESH** (Task 3, 4): autonomo. Il **Task 4 introduce la
  variante "compatta"** dei componenti condivisi `core/components/module_*` →
  eseguire il Blocco B **prima** del Blocco D (che riusa la variante).
- **Blocco C — ASSET** (Task 5, 6): autonomo.
- **Blocco D — KICKOFF/`tasks`** (Task 7, 8, 9): il Task 9 **riusa** la variante
  compatta creata nel Task 4 → **dopo** il Blocco B.
- **Task 10**: CHANGELOG + README + regressione per-app dei 4 moduli.

Ordine consigliato: **1 → 2 (A) → 3,4 (B) → 5,6 (C) → 7,8,9 (D) → 10**.
I blocchi A/B/C/D committano in modo indipendente (file disgiunti, salvo i
componenti `core/module_*` toccati solo dal Task 4 e usati dal Task 9).

---

### Task 1: Setup worktree

**Files:** solo git.

**Interfaces:**
- Produces: worktree `C:\Dev\pn-polish-multiapp` su `feature/polish-multiapp`
  (base `origin/main`), cwd di tutti i task.

- [ ] **Step 1: Crea il worktree**

```powershell
Set-Location "C:\Dev\Portale Novicrom"
git fetch origin
git worktree add C:\Dev\pn-polish-multiapp -B feature/polish-multiapp origin/main
Set-Location C:\Dev\pn-polish-multiapp
git status
```

Atteso: `On branch feature/polish-multiapp`, tree clean.

- [ ] **Step 2: Verifica venv**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" --version
```

Atteso: `Python 3.11+`.

---

## BLOCCO A — TIMBRI: ricerca timbri anche per qualifica

### Task 2: Filtro Qualifica nella lista timbri

**Files:**
- Modify: `django_app/timbri/views.py` (`index()`, riga ~502: opzioni qualifica +
  filtro + context)
- Modify: `django_app/timbri/templates/timbri/pages/index.html` (form filtri,
  righe ~260-283)
- Test: `django_app/timbri/tests.py`

**Interfaces:**
- Consumes: `RegistroTimbro.qualifica`, `OperatoreTimbri.legacy_anagrafica_id`.
- Produces: query param GET `qualifica`; context keys `qualifiche` (opzioni),
  `qualifica` (selezionata).

- [ ] **Step 1: Scrivi il test (in coda a `tests.py`)** — nuova classe che, con
  un dipendente legacy collegato a un `OperatoreTimbri` con due `RegistroTimbro`
  di qualifiche diverse, verifica che `GET timbri:index?qualifica=<posseduta>`
  includa la riga e `?qualifica=<non-posseduta>` la escluda. Usare superuser +
  `@override_settings(LEGACY_AUTH_ENABLED=False)`. Gestire il caso
  `_timbri_schema_issue()` come i test esistenti (skip/guard se lo schema legacy
  non è disponibile in test).

- [ ] **Step 2: Run test → FALLISCE**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test timbri.tests --settings=config.settings.test --keepdb --verbosity 1
```

- [ ] **Step 3: Implementa**
  - In `index()`: leggere `qualifica = str(request.GET.get("qualifica") or "").strip()`.
    Calcolare `qualifiche = sorted({q for q in RegistroTimbro.objects.exclude(qualifica="").values_list("qualifica", flat=True).distinct()})`.
    Se `qualifica` valorizzata, ricavare il set di legacy id
    `OperatoreTimbri.objects.filter(registri__qualifica__iexact=qualifica, legacy_anagrafica_id__isnull=False).values_list("legacy_anagrafica_id", flat=True)`
    e filtrare `rows` a quelli con `int(row["id"])` nel set (dopo `q`/`reparto`,
    prima della paginazione). Aggiungere `qualifiche` e `qualifica` al context;
    includere `qualifica` nel calcolo statistiche già presente.
  - In `index.html`: aggiungere una `<div class="tim-field">` con `<select
    name="qualifica">` (opzione vuota "Tutte le qualifiche" + `{% for item in
    qualifiche %}`), accanto al filtro Reparto; aggiornare la condizione del link
    "Reset" (riga ~280) da `{% if q or reparto %}` a `{% if q or reparto or
    qualifica %}`. Aggiornare eventualmente il placeholder di `q`.

- [ ] **Step 4: Run test → PASSA** (comando come Step 2).

- [ ] **Step 5: Commit**

```powershell
git add django_app/timbri/views.py django_app/timbri/templates/timbri/pages/index.html django_app/timbri/tests.py
git commit -m "feat(timbri): filtro ricerca timbri per qualifica nella lista dipendenti"
```

---

## BLOCCO B — PROCEDURE REFRESH

### Task 3: Assegnazione a tutti i documenti della sessione (rimuovi "Revisione da assegnare")

**Files:**
- Modify: `django_app/procedure_refresh/views.py` (`assign_users`, riga ~1289)
- Modify: `django_app/procedure_refresh/templates/procedure_refresh/pages/campaign_detail.html`
  (blocco "Revisione da assegnare", righe ~236-243)
- Test: `django_app/procedure_refresh/tests.py`

**Interfaces:**
- Consumes: `ProcedureCampaign`, i suoi `campaign_docs`/`ProcedureCampaignDocument`,
  `ProcedureRevision`, `ProcedureAssignment`.
- Produces: `assign_users` assegna ogni utente a **tutte** le revisioni della
  campagna; il POST non richiede più `revision_id`.

- [ ] **Step 1: Scrivi il test (in coda a `tests.py`)** — campagna con 2
  revisioni collegate + 2 utenti; `POST assign_users` con solo `user_ids` (no
  `revision_id`) → `ProcedureAssignment.objects.count() == 4`; secondo POST
  identico → resta 4 (idempotenza). Campagna senza documenti → 0 assignment +
  messaggio d'errore. Usare gli helper/fixture dei test procedure_refresh
  esistenti per manager + campagna.

- [ ] **Step 2: Run test → FALLISCE**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test procedure_refresh.tests --settings=config.settings.test --keepdb --verbosity 1
```

- [ ] **Step 3: Implementa**
  - `assign_users`: rimuovere lettura/validazione `revision_id`; validare solo
    `user_ids`. Ricavare le revisioni della campagna dai `campaign_docs` (stesso
    queryset usato per il vecchio `<select>`); se vuoto → messaggio d'errore +
    redirect al `campaign_detail`. Doppio loop `for user ... for revision ...`
    con `get_or_create(campaign, revision, user, defaults=...)`. Adeguare la
    notifica in-app a una sola per utente con testo generico ("N documenti della
    sessione «...», scadenza ...").
  - `campaign_detail.html`: rimuovere il blocco `<label>Revisione da assegnare
    </label>` + `<select name="revision_id">` (righe ~236-243). Lasciare scadenza
    + selezione utenti.

- [ ] **Step 4: Run test → PASSA** (comando come Step 2).

- [ ] **Step 5: Commit**

```powershell
git add django_app/procedure_refresh/views.py django_app/procedure_refresh/templates/procedure_refresh/pages/campaign_detail.html django_app/procedure_refresh/tests.py
git commit -m "feat(procedure_refresh): assegnazione sessione a tutti i documenti (rimosso select revisione)"
```

---

### Task 4: Impostazioni — rimuovi "Accesso rapido" + variante branding compatta

**Files:**
- Modify: `django_app/procedure_refresh/templates/procedure_refresh/pages/admin_dashboard.html`
  (blocco "Accesso rapido" righe ~109-123; hero riga 72; branding card riga 124)
- Modify: `django_app/core/templates/core/components/module_settings_hero.html`
  (variante `settings_variant="compact"`)
- Modify: `django_app/core/templates/core/components/module_branding_card.html`
  (variante `branding_compact=True`)
- Modify: `django_app/core/templates/core/components/module_settings_styles.html`
  (CSS `.ms-hero--compact`, `.ms-card--compact`)
- Test: `django_app/procedure_refresh/tests.py`

**Interfaces:**
- Produces: modificatori opt-in `ms-hero--compact` / `ms-card--compact` sui
  componenti condivisi (backward-compatibili) — **riusati dal Task 9**.

- [ ] **Step 1: Scrivi il test** — `GET procedure_refresh:admin_dashboard`
  (manager): body **non** contiene "Accesso rapido"; **contiene**
  `ms-hero--compact`.

- [ ] **Step 2: Run test → FALLISCE** (comando come Task 3 Step 2).

- [ ] **Step 3: Implementa**
  - `module_settings_hero.html`: `<section class="ms-hero{% if settings_variant == 'compact' %} ms-hero--compact{% endif %}">`.
  - `module_branding_card.html`: `<section class="ms-card{% if branding_compact %} ms-card--compact{% endif %}">`.
  - `module_settings_styles.html`: aggiungere regole `.ms-hero--compact` (h1 più
    piccolo ~22px, padding ridotto) e `.ms-card--compact .ms-brand-mark`
    (dimensione ridotta). Non alterare le regole base.
  - `admin_dashboard.html`: rimuovere il blocco `pr-card` "Accesso rapido"
    (~109-123); passare `settings_variant="compact"` all'include hero (riga 72) e
    `branding_compact=True` all'include branding (riga 124); togliere "accessi
    rapidi" dal sottotitolo hero. Valutare passaggio della griglia da `ms-grid-2`
    a 1 colonna ora che resta la sola branding card.

- [ ] **Step 4: Run test → PASSA** (comando come Task 3 Step 2).

- [ ] **Step 5: Commit**

```powershell
git add django_app/procedure_refresh/templates/procedure_refresh/pages/admin_dashboard.html django_app/core/templates/core/components/module_settings_hero.html django_app/core/templates/core/components/module_branding_card.html django_app/core/templates/core/components/module_settings_styles.html django_app/procedure_refresh/tests.py
git commit -m "feat(procedure_refresh,core): impostazioni senza accesso rapido + branding compatto (modificatore condiviso)"
```

---

## BLOCCO C — ASSET

### Task 5: Immagine header apribile in lightbox

**Files:**
- Modify: `django_app/assets/templates/assets/pages/asset_detail.html` (header
  `af-targhetta` righe ~528-530 + overlay/CSS/JS lightbox)
- Test: `django_app/assets/tests.py`

**Interfaces:**
- Produces: markup `af-targhetta-trigger` + overlay `af-lightbox` (CSS/JS inline,
  token di tema, niente librerie).

- [ ] **Step 1: Scrivi il test** — `GET` dettaglio asset (superuser +
  `@override_settings(LEGACY_AUTH_ENABLED=False)`): il body contiene `af-lightbox`
  e la logica trigger. Se popolare un `ImageField` reale è oneroso, verificare che
  l'overlay/markup lightbox sia sempre presente e che il wrapping condizionale
  dell'immagine esista.

- [ ] **Step 2: Run test → FALLISCE**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test assets.tests --settings=config.settings.test --keepdb --verbosity 1
```

- [ ] **Step 3: Implementa**
  - Avvolgere l'`<img class="af-targhetta">` in un `<button type="button"
    class="af-targhetta-trigger" data-lightbox-src="{{ asset.foto_targhetta.url }}">`
    (`cursor:zoom-in`), mantenendo l'`<img>` visibile.
  - In fondo al `{% block %}` aggiungere overlay `<div id="af-lightbox">`
    nascosto + `<style>` (sfondo scuro `rgba`, immagine centrata `max-width/height`)
    + `<script>` inline: click sul trigger → apre con la `src`; chiusura su click
    overlay o `Esc`. Coerente coi token/tema esistenti.

- [ ] **Step 4: Run test → PASSA** (comando come Step 2).

- [ ] **Step 5: Commit**

```powershell
git add django_app/assets/templates/assets/pages/asset_detail.html django_app/assets/tests.py
git commit -m "feat(assets): immagine header asset apribile in lightbox (popup leggero)"
```

---

### Task 6: "Posizione in officina" — planimetria reale per asset

**Files:**
- Modify: `django_app/assets/views.py` (`_ensure_asset_plant_layout_marker`
  righe ~4010-4032 + nuovo helper `_resolve_asset_plant_layout`)
- Test: `django_app/assets/tests.py`

**Interfaces:**
- Consumes: `PlantLayout` (`category`), `PlantLayoutArea` (`reparto_code`),
  `Asset.reparto`.
- Produces: `_resolve_asset_plant_layout(asset)`; `_ensure_asset_plant_layout_marker`
  crea/rimappa il marker sul layout coerente con il reparto dell'asset.

- [ ] **Step 1: Scrivi il test** — due `PlantLayout` **attivi** con `category`
  diverse (es. "Officina", "Reparto Cromatura"); un `Asset` con `reparto="Reparto
  Cromatura"`. `_ensure_asset_plant_layout_marker(asset)` → `PlantLayoutMarker` sul
  layout Cromatura (non sull'alfabeticamente primo). Secondo caso: reparto non
  mappato → fallback al primo layout attivo, nessuna eccezione.

- [ ] **Step 2: Run test → FALLISCE** (comando come Task 5 Step 2).

- [ ] **Step 3: Implementa**
  - `_resolve_asset_plant_layout(asset)`: (a) layout attivo con `category__iexact
    == asset.reparto`; (b) layout attivo con `areas__reparto_code__iexact ==
    asset.reparto`; (c) fallback `PlantLayout.objects.filter(is_active=True)
    .order_by("category","name","id").first()`. Ritorna `None` se nessun layout
    attivo.
  - `_ensure_asset_plant_layout_marker`: usare il layout risolto invece del
    `first()` generico. Se esiste già un marker dell'asset su un layout diverso da
    quello risolto **e** la risoluzione è specifica (a/b), spostare/ricreare il
    marker sul layout corretto rispettando il unique constraint
    `layout+asset` (spostare `layout` del marker esistente o
    delete+get_or_create). Coordinate default invariate.

- [ ] **Step 4: Run test → PASSA** (comando come Task 5 Step 2).

- [ ] **Step 5: Commit**

```powershell
git add django_app/assets/views.py django_app/assets/tests.py
git commit -m "fix(assets): posizione in officina usa la planimetria reale del reparto dell'asset"
```

---

## BLOCCO D — KICKOFF (app `tasks`)  — dopo il Blocco B

### Task 7: Dashboard mostra i kickoff già programmati (bug scope)

**Files:**
- Modify: `django_app/tasks/views.py` (`_project_scope_filter_q`, righe ~982-1004)
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Consumes: `KickoffMeeting.partecipanti_utenti`.
- Produces: `_project_scope_filter_q` include i kickoff dove l'utente è
  partecipante di un incontro.

- [ ] **Step 1: Scrivi il test (riproduce il bug)** — utente **non** admin/non
  full-read; `Project` senza task creato da altro utente + `KickoffMeeting` con
  l'utente in `partecipanti_utenti`. Assert che PRIMA del fix il progetto **non**
  è in `_scoped_projects_queryset(request)` (o non appare in `project_list`), DOPO
  sì. Usare gli helper dei test tasks per impostare il livello di accesso senza
  full-read.

- [ ] **Step 2: Run test → FALLISCE**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test tasks.tests --settings=config.settings.test --keepdb --verbosity 1
```

- [ ] **Step 3: Implementa** — in `_project_scope_filter_q`, aggiungere al `q`
  base: `| Q(meetings__partecipanti_utenti=user)` (ed eventualmente
  `| Q(meetings__created_by=user)`). `_scoped_projects_queryset` fa già
  `.distinct()`.

- [ ] **Step 4: Run test → PASSA** (comando come Step 2).

- [ ] **Step 5: Commit**

```powershell
git add django_app/tasks/views.py django_app/tasks/tests.py
git commit -m "fix(tasks): i kickoff programmati compaiono in dashboard per i partecipanti agli incontri"
```

---

### Task 8: Assegnazione attività dalla pagina dell'incontro

**Files:**
- Modify: `django_app/tasks/templates/tasks/project_meeting_detail.html`
  (pulsante "Crea / assegna attività" che apre il modal `#ctm-overlay` esistente)
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Consumes: modal `#ctm-overlay` + view `project_meeting_task_from_step`
  (esistenti, invariati backend). `active_users` già nel context.
- Produces: trigger sempre disponibile per `can_manage`, anche senza next_steps.

- [ ] **Step 1: Scrivi il test** — `GET project_meeting_detail` di un incontro
  **senza** `next_steps`, utente manager: body contiene il pulsante "Crea /
  assegna attività" e il modal `ctm-overlay` con `name="assigned_to"`.

- [ ] **Step 2: Run test → FALLISCE** (comando come Task 7 Step 2).

- [ ] **Step 3: Implementa** — aggiungere nel template (dentro `{% if
  can_manage %}`) un pulsante visibile che apre `#ctm-overlay` con step vuoto
  (riusa il JS esistente `openCreateTaskModal(...)`; se serve, chiamarlo con
  argomento step vuoto/`""`). Nessun cambio a view/JS backend.

- [ ] **Step 4: Run test → PASSA** (comando come Task 7 Step 2).

- [ ] **Step 5: Commit**

```powershell
git add django_app/tasks/templates/tasks/project_meeting_detail.html django_app/tasks/tests.py
git commit -m "feat(tasks): crea e assegna attivita direttamente dalla pagina dell'incontro"
```

---

### Task 9: Impostazioni — rimuovi "Tutte le impostazioni modificabili" + branding compatto

**Files:**
- Modify: `django_app/tasks/templates/tasks/impostazioni.html` (titolo/callout
  righe ~211-212, 223-224; hero riga 147; branding card riga 229)
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Consumes: variante `settings_variant="compact"` / `branding_compact=True` dei
  componenti condivisi (introdotta nel **Task 4**).

- [ ] **Step 1: Scrivi il test** — `GET tasks:impostazioni?tab=config` (admin):
  body **non** contiene "Tutte le impostazioni modificabili"; **contiene**
  `ms-hero--compact`.

- [ ] **Step 2: Run test → FALLISCE** (comando come Task 7 Step 2).

- [ ] **Step 3: Implementa**
  - Rimuovere il titolo/sottotitolo "Tutte le impostazioni modificabili" (righe
    ~211-212) e il callout ridondante (righe ~223-224), lasciando i controlli.
  - Passare `settings_variant="compact"` all'include hero (riga 147) e
    `branding_compact=True` all'include branding (riga 229). (Modificatori già
    disponibili dal Task 4.)

- [ ] **Step 4: Run test → PASSA** (comando come Task 7 Step 2).

- [ ] **Step 5: Commit**

```powershell
git add django_app/tasks/templates/tasks/impostazioni.html django_app/tasks/tests.py
git commit -m "feat(tasks): impostazioni piu snelle (rimosso blocco ridondante) + branding compatto"
```

---

### Task 10: CHANGELOG + README + regressione per-app

**Files:**
- Modify: `CHANGELOG.md` (sezione `[Unreleased]`: tutti i file toccati + breve
  descrizione per area A/B/C/D)
- Modify: `README.md` (se cambiano funzionalità visibili: nota su ricerca timbri
  per qualifica, assegnazione sessione a tutti i documenti, lightbox asset,
  planimetria per asset, fix dashboard kickoff, assegnazione da incontro)
- Nessun test nuovo.

**Interfaces:** documentazione + verde per-app dei 4 moduli.

- [ ] **Step 1: Aggiorna CHANGELOG.md e README.md** (senza attendere richiesta —
  regola di progetto).

- [ ] **Step 2: Regressione per-app (una alla volta)**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test timbri --settings=config.settings.test --keepdb --verbosity 1
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test procedure_refresh --settings=config.settings.test --keepdb --verbosity 1
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test assets --settings=config.settings.test --keepdb --verbosity 1
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test tasks --settings=config.settings.test --keepdb --verbosity 1
```

Atteso: tutte verdi (eventuali failure preesistenti non correlate vanno annotate,
non "risolte" allargando lo scope).

- [ ] **Step 3: Commit**

```powershell
git add CHANGELOG.md README.md
git commit -m "docs: changelog/readme per polish multi-app (timbri, procedure_refresh, assets, tasks)"
```

- [ ] **Step 4: Push**

```powershell
git push -u origin feature/polish-multiapp
```

---

## Chiusura

- Rimuovere il worktree quando il lavoro è integrato:
  `git worktree remove C:\Dev\pn-polish-multiapp` (se il path è troppo lungo per
  git: `cmd /c rmdir /s /q C:\Dev\pn-polish-multiapp` + `git worktree prune`).
- Nessuna migrazione nuova prevista; se un imprevisto la richiedesse, prima run
  dei test **senza** `--keepdb`.
