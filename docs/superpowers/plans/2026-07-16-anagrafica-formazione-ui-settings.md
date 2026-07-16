# Anagrafica — Formazione/Compliance UI & Impostazioni — Piano (Stream 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (consigliato) o superpowers:executing-plans per eseguire questo piano task-per-task.
> Gli step usano checkbox (`- [ ]`).

**Goal:** cinque interventi UI nel modulo Formazione/Compliance/Impostazioni di
`django_app/anagrafica`, di cui **due funzionali** (chip "Processi qualificati" nelle
Qualifiche; tab "Ruoli" inline in Impostazioni) e tre di rifinitura (popup "Nuovo
istruttore", form "Gestione e-learning", popup "Modifica mansione"). Vedi punch-list
`docs/ANAGRAFICA - PERSONE.md`.

**Spec:** `docs/superpowers/specs/2026-07-16-anagrafica-formazione-ui-settings-design.md`.

**Architecture:** additivo e conservativo. La chip "Processi qualificati" è una
**pseudo-categoria virtuale** in `views.qualifiche_list` (NON una choice del modello,
NON una migrazione): riusa il modello MOD.128 `models_mpq.ProcessoQualificato` già
caricato. Il tab "Ruoli" inline riusa le route CRUD ruoli esistenti e un **partial
estratto** da `ruoli_operativi.html`. I popup si allineano al pattern modale già
maturo `.mn-modal`/`.ro-modal`. Nessuna route nuova, nessun modello nuovo.

**Tech Stack:** Django 5.2, Python 3.11+, HTMX/SSR, CSS custom con token in
`theme.css` e classi `hub-`/`fmd-`. Test `django.test.TestCase` + `RequestFactory`/`Client`.
DB test SQLite per-PID sotto `.tmp_tests`; prod SQL Server (ORM SQL-Server-safe).

## Global Constraints

- **Worktree dedicato** (Session Isolation CLAUDE.md): mai lavorare/committare nel
  checkout condiviso `C:\Dev\Portale Novicrom`. Task 1 crea
  `C:\Dev\pn-anag-formazione-ui` su branch `feature/anagrafica-formazione-ui-settings`
  da `origin/main`, cwd di tutti i task.
- **Mai `git add -A` / `git commit -a`**: staging con percorsi espliciti. **Non
  committare in stesura**: i commit avvengono solo negli step dedicati.
- **Venv assoluto** (il worktree non ha `.venv`):
  `& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe"`.
- **Comando test** (dalla radice del worktree), timeout **≥ 600000 ms**:
  `& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test anagrafica.<test_module> --settings=config.settings.test --keepdb --verbosity 1`
- **Test DB**: SQLite per-PID. La **prima** run dopo una nuova migrazione va fatta
  **senza `--keepdb`** (rimigra, ~6–8 min); poi sempre `--keepdb` (istantaneo). In
  questo stream non è prevista alcuna migrazione (vedi Architecture) → si usa sempre
  `--keepdb`. Se un task dovesse introdurre una migrazione, la sua prima run va senza
  `--keepdb`.
- **PowerShell** (Windows): `&` per invocare l'exe quotato; `Set-Location` alla
  radice del worktree.
- **Template Django**: `{# #}` commenta **una** riga; mai attributi/variabili con `_`
  iniziale. La **subnav di modulo** (`anagrafica/components/subnav.html`) è
  `NavigationItem`-driven: **non** hardcodarla. I `.imp-tabs` della pagina
  Impostazioni sono tab interni alla pagina (editabili nel template).
- **Tema chiaro/scuro**: token `theme.css`; `--surface-alt`/`--thead-bg`/`--tbody-hover`
  esistono solo in `body.theme-dark` → usarli con fallback o gate sotto
  `body.theme-dark`.
- **ACL**: nessun cambio di gating; le view mantengono i controlli esistenti
  (`is_admin`/`is_editor`, `login_required`).
- **CHANGELOG.md** + **README.md** obbligatori (Task finale). **Niente version bump.**
- **Riuso obbligatorio** (non riscrivere): `views.qualifiche_list`,
  `views.impostazioni`, `views.ruoli_operativi_list`, modello MOD.128
  `models_mpq.ProcessoQualificato`, partial `_fm_form_fields.html`, pattern modale
  `.mn-modal`/`.ro-modal`, route CRUD ruoli
  (`ruolo_operativo_create`/`.../modifica`/`ruolo_operativo_delete`).

## Coordinamento con stream 1 e 2 (paralleli) — rischi di conflitto

Stream 1/2 lavorano in parallelo sullo stesso modulo. File a rischio e mitigazione:

| File | Uso in stream 3 | Rischio | Mitigazione |
|------|-----------------|---------|-------------|
| `anagrafica/views.py` | `qualifiche_list` (Task 3), `impostazioni` (Task 6) | Medio (file grande e condiviso) | Toccare **solo** quei due blocchi, disgiunti; nessuna modifica a helper condivisi. Rebase su `origin/main` prima del merge. |
| `anagrafica/urls.py` | — | Nullo | **Nessuna route nuova**: si riusano le CRUD ruoli esistenti. |
| `impostazioni.html` | Task 6 (tab Ruoli inline) | Medio | Modifica localizzata al blocco `.imp-tabs` + nuovo `<section data-panel="ruoli">`; niente refactor globale. |
| `models.py` | — | Nullo | **Nessuna modifica** (chip Processi è virtuale). |
| Template popup istruttore / e-learning / mansioni / partial ruoli | Task 2/4/5/6 | Basso | File isolati o partial nuovi. |

Regola: se al merge `origin/main` è avanzato, fare `git fetch` + rebase e rieseguire
la suite `anagrafica` mirata prima di integrare.

## Ordine di esecuzione e dipendenze

I task sono in gran parte indipendenti. Vincolo: il **Task 6** (Ruoli inline)
dipende dall'estrazione del partial (Task 6 Step interni) e dal context view; va
eseguito come blocco unico. Ordine consigliato:

**Task 1 (setup) → 2 (istruttore) → 3 (chip Processi, funzionale) → 4 (mansione) →
5 (e-learning) → 6 (Ruoli inline, funzionale) → 7 (CHANGELOG/README + regressione)**.

I task 2/4/5 sono puro CSS/markup: TDD leggero (un render-test che asseri­sce la
presenza delle classi/pattern chiave). I task 3 e 6 sono funzionali: test-first
red→green obbligatorio.

---

### Task 1: Setup worktree

**Files:** solo git.

**Interfaces:**
- Produces: worktree `C:\Dev\pn-anag-formazione-ui` su
  `feature/anagrafica-formazione-ui-settings` (base `origin/main`), cwd dei task.

- [ ] **Step 1: Crea il worktree**

```powershell
Set-Location "C:\Dev\Portale Novicrom"
git fetch origin
git worktree add C:\Dev\pn-anag-formazione-ui -B feature/anagrafica-formazione-ui-settings origin/main
Set-Location C:\Dev\pn-anag-formazione-ui
git status
```

Atteso: `On branch feature/anagrafica-formazione-ui-settings`, tree clean.

- [ ] **Step 2: Verifica venv + suite mirata baseline**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" --version
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test anagrafica.tests_qualifiche_dashboard --settings=config.settings.test --keepdb --verbosity 1
```

Atteso: `Python 3.11+`; suite baseline verde (conferma che l'ambiente/keepdb funziona).

---

### Task 2: Rifinitura popup "Nuovo istruttore" + "Modifica istruttore"

**Files:**
- Modify: `django_app/anagrafica/templates/anagrafica/pages/formazione_istruttori.html`
- (Eventuale) Create: `django_app/anagrafica/templates/anagrafica/partials/_istruttore_fields.html`
- Test: `django_app/anagrafica/tests_ui_formazione.py` (nuovo)

**Interfaces:**
- Consumes: `views.formazione_istruttori_list` (`views.py:11465`), context
  `TIPO_CHOICES`, `form`, `is_editor`.
- Produces: due modali uniformati al pattern modale canonico, campi da fonte unica.

- [ ] **Step 1: Test di render (in `tests_ui_formazione.py`)**

Test-first leggero: la pagina istruttori (come editor) rende entrambi i modali col
pattern atteso.

```python
class IstruttorePopupRenderTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-istr", "su-istr@test.local", "x")
        self.client.force_login(self.su)

    def test_popup_istruttore_pattern_canonico(self):
        resp = self.client.get(reverse("anagrafica:formazione_istruttori_list"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # overlay + card + chiusura ESC (data-attr o handler), niente doppia label ad hoc
        self.assertIn('id="modal-crea-istr"', body)
        self.assertIn('id="modal-edit-istr"', body)
        # marker della rifinitura: pulsante chiusura e classi design-system nei campi
        self.assertIn('data-close-modal', body)   # oppure il marker scelto
        self.assertIn('hub-field', body)           # campi via design-system, non .fm-label ad hoc
```

(Adatta i marker esatti alle classi effettivamente usate nell'implementazione: il
punto è fissare che i due modali esistono e usano il pattern/classi canoniche.)

- [ ] **Step 2: Run test → FALLISCE** (marker canonici assenti).

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test anagrafica.tests_ui_formazione.IstruttorePopupRenderTests --settings=config.settings.test --keepdb --verbosity 1
```

- [ ] **Step 3: Implementa la rifinitura**
  - Unifica i campi: usa `_fm_form_fields.html` (o un nuovo `_istruttore_fields.html`)
    sia nel modale "crea" sia in "modifica"; elimina il markup JS hard-coded in
    `openEditModal` (lo script setta solo `value`/`action`, come `mn-modal`/`ro-modal`).
  - Applica overlay/card canonici (`max-height:90vh;overflow-y:auto`), header con `×`,
    chiusura click-fuori **ed ESC**, override `body.theme-dark`, token invece di
    colori hard-coded. Sostituisci `.fm-label` ad hoc con `.hub-field label`/`.fmd-field`.

- [ ] **Step 4: Run test → PASSA.**
- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/templates/anagrafica/pages/formazione_istruttori.html django_app/anagrafica/tests_ui_formazione.py
# + eventuale partial _istruttore_fields.html
git commit -m "fix(anagrafica,ui): rifinitura popup Nuovo/Modifica istruttore (pattern modale canonico, campi unificati)"
```

---

### Task 3: Chip "Processi qualificati" nelle Qualifiche (FUNZIONALE)

**Files:**
- Modify: `django_app/anagrafica/views.py` (`qualifiche_list`, ~`5953`–`6071`)
- Modify: `django_app/anagrafica/templates/anagrafica/pages/qualifiche_list.html`
  (sezione MOD.128 righe 181–207; le chip escono dal loop `tabs`)
- Test: `django_app/anagrafica/tests_qualifiche_dashboard.py` (o `tests.py` qualifiche)

**Interfaces:**
- Consumes: `TipoQualifica.CATEGORIA_CHOICES` (`models.py:512`),
  `models_mpq.ProcessoQualificato` (già caricato come `processi_qualificati`).
- Produces: `tabs` con voce `("PROCESSI", "Processi qualificati", N)`; context flag
  `mostra_processi`; `valid_cats` che accetta `PROCESSI`.

- [ ] **Step 1: Scrivi il test (test-first)**

```python
class QualificheChipProcessiTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-ql", "su-ql@test.local", "x")
        self.client.force_login(self.su)
        # un processo MOD.128 (adatta ai campi reali di ProcessoQualificato/Cliente)
        from anagrafica.models_mpq import ProcessoQualificato, ClienteQualificante
        cli = ClienteQualificante.objects.create(nome="ACME")
        ProcessoQualificato.objects.create(nome="Saldatura X", cliente=cli)
        TipoQualifica.objects.create(nome="RSPP", categoria="SICUREZZA", durata_mesi=60)

    def _get(self, **q):
        return self.client.get(reverse("anagrafica:qualifiche_list"), q)

    def test_chip_processi_presente_con_conteggio(self):
        body = self._get().content.decode()
        self.assertIn("Processi qualificati", body)
        self.assertIn("categoria=PROCESSI", body)   # href della chip

    def test_filtro_processi_mostra_solo_mod128(self):
        body = self._get(categoria="PROCESSI").content.decode()
        self.assertIn("Saldatura X", body)           # sezione MOD.128 visibile
        self.assertNotIn("RSPP", body)               # catalogo tipi nascosto

    def test_filtro_categoria_reale_nasconde_processi(self):
        body = self._get(categoria="SICUREZZA").content.decode()
        self.assertIn("RSPP", body)
        self.assertNotIn("Saldatura X", body)        # MOD.128 nascosto sotto altra categoria
```

(Verifica i nomi/campi reali di `models_mpq` prima di scrivere il `setUp`: se la
creazione del processo richiede più campi, minimizza o usa una factory esistente nei
test MPQ — vedi `tests_mpq_formazione.py`.)

- [ ] **Step 2: Run test → FALLISCE**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test anagrafica.tests_qualifiche_dashboard.QualificheChipProcessiTests --settings=config.settings.test --keepdb --verbosity 1
```

Atteso: FAIL (`categoria=PROCESSI` non presente; filtro non isola).

- [ ] **Step 3: Implementa in `qualifiche_list`**
  - Costante locale: `CAT_PROCESSI, LBL_PROCESSI = "PROCESSI", "Processi qualificati"`.
  - `valid_cats = {c for c, _ in TipoQualifica.CATEGORIA_CHOICES} | {CAT_PROCESSI}`.
  - Dopo aver calcolato `processi_qualificati` e `tabs`, aggiungi:
    `tabs.append((CAT_PROCESSI, LBL_PROCESSI, len(processi_qualificati)))`.
  - Logica visibilità:
    - `mostra_processi = cat_filter in ("", CAT_PROCESSI)`.
    - se `cat_filter == CAT_PROCESSI`: `tipi_grouped = []`, `scadenze = []`.
  - Passa `"mostra_processi": mostra_processi` al context; NON toccare il modello.
- In `qualifiche_list.html`: la chip esce dal loop `tabs` esistente; avvolgi la
  sezione MOD.128 in `{% if mostra_processi and processi_qualificati %}` … `{% endif %}`.

- [ ] **Step 4: Run test → PASSA.**
- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/templates/anagrafica/pages/qualifiche_list.html django_app/anagrafica/tests_qualifiche_dashboard.py
git commit -m "feat(anagrafica): chip 'Processi qualificati' (MOD.128) nel filtro Qualifiche + isolamento sezione"
```

---

### Task 4: Rifinitura popup "Modifica mansione"

**Files:**
- Modify: `django_app/anagrafica/templates/anagrafica/pages/mansioni_list.html`
- Test: `django_app/anagrafica/tests_ui_formazione.py`

**Interfaces:**
- Consumes: `views.mansioni_list` (`views.py:5371`), context `CATEGORIA_CHOICES`
  (`Mansione.CATEGORIA_CHOICES`), `LIVELLO_RISCHIO_CHOICES`, `is_admin`.
- Produces: `#mn-modal` rifinito (header+`×`, scroll, ESC, token/dark).

- [ ] **Step 1: Test di render (in `tests_ui_formazione.py`)**

```python
class MansionePopupRenderTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-mn", "su-mn@test.local", "x")
        self.client.force_login(self.su)

    def test_modale_modifica_mansione_rifinito(self):
        body = self.client.get(reverse("anagrafica:mansioni_list")).content.decode()
        self.assertIn('id="mn-modal"', body)
        self.assertIn("Modifica mansione", body)
        self.assertIn("hub-form-stack", body)     # campi design-system (invariati)
        # marker della rifinitura (adatta all'implementazione): overflow scroll nel corpo
        self.assertIn("overflow-y:auto", body)
```

- [ ] **Step 2: Run test → FALLISCE** (marker rifinitura assente).
- [ ] **Step 3: Implementa** header con `×`, corpo `max-height:90vh;overflow-y:auto`,
  chiusura ESC (oltre al click-overlay già presente riga 240), overlay/superfici via
  token con fallback. Campi/`openEdit`/action **invariati**.
- [ ] **Step 4: Run test → PASSA.**
- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/templates/anagrafica/pages/mansioni_list.html django_app/anagrafica/tests_ui_formazione.py
git commit -m "fix(anagrafica,ui): rifinitura popup Modifica mansione (header, scroll, ESC, token tema)"
```

---

### Task 5: Pulizia form "Gestione e-learning"

**Files:**
- Modify: `django_app/anagrafica/templates/anagrafica/pages/formazione_elearning_manage.html`
  (box "Assegna dipendenti", righe 138–165)
- (Eventuale) Modify: `django_app/anagrafica/static/anagrafica/css/formazione_design.css`
  (poche regole per `fm-assign-*`/campi assegnazione)
- Test: `django_app/anagrafica/tests_ui_formazione.py`

**Interfaces:**
- Consumes: `views.formazione_elearning_manage` (`views.py:14808`), context
  `assegnabili`, `assegnazioni`, `is_editor`. POST `formazione_elearning_assign`
  **invariato**.

- [ ] **Step 1: Test di render (render-only, il POST non cambia)**

```python
class ElearningManageFormRenderTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-el", "su-el@test.local", "x")
        self.client.force_login(self.su)
        # crea un corso e-learning minimo via i factory/model reali del modulo
        ...
    def test_form_assegna_pulito(self):
        body = self.client.get(reverse("anagrafica:formazione_elearning_manage",
                                        args=[self.corso.pk])).content.decode()
        self.assertIn("Assegna dipendenti", body)
        # marker: inline style grezzi rimossi a favore di classi (adatta al reale)
        self.assertNotIn('style="display:flex;gap:14px;flex-wrap:wrap;align-items:flex-end', body)
```

(Se costruire un corso e-learning nei test è oneroso, ridurre a un test che verifica
solo che la classe/marker nuova sia presente sul template renderizzato di una pagina
raggiungibile; oppure marcare questo task come **puro CSS** e sostituire il test con
un check manuale in browser documentato. Non forzare TDD pesante dove è solo CSS.)

- [ ] **Step 2: Run test → FALLISCE.**
- [ ] **Step 3: Implementa** spostando gli inline `style` del box "Assegna
  dipendenti" in classi `fmd-*`/`hub-*` (o poche regole in `formazione_design.css`),
  uniformando griglia, spaziature e stati hover/focus coi token. Nessun cambio al POST.
- [ ] **Step 4: Run test → PASSA.**
- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/templates/anagrafica/pages/formazione_elearning_manage.html django_app/anagrafica/tests_ui_formazione.py
# + eventuale formazione_design.css
git commit -m "fix(anagrafica,ui): pulizia form 'Assegna dipendenti' in Gestione e-learning (classi al posto di inline style)"
```

---

### Task 6: Tab "Ruoli" inline in Impostazioni + pulizia sidebar (FUNZIONALE)

**Files:**
- Create: `django_app/anagrafica/templates/anagrafica/partials/_ruoli_operativi_body.html`
- Modify: `django_app/anagrafica/templates/anagrafica/pages/ruoli_operativi.html`
  (include il partial)
- Modify: `django_app/anagrafica/templates/anagrafica/pages/impostazioni.html`
  (tab `<a>`→`<button data-tab="ruoli">`, nuovo `<section data-panel="ruoli">`,
  rimozione commento Fase-2)
- Modify: `django_app/anagrafica/views.py` (`impostazioni`, ~`8386`–`8600`): context
  `ruoli_catalogo`, `ruoli_suggeriti`, `ruoli_operativi` con `select_related("riporta_a")`
- Test: `django_app/anagrafica/tests_ui_formazione.py`

**Interfaces:**
- Consumes: route CRUD ruoli esistenti; view `impostazioni`; view
  `ruoli_operativi_list` (resta valida). Il partial usa `ruoli`, `ruoli_catalogo`,
  `ruoli_suggeriti`, `is_admin`.
- Produces: pannello Ruoli inline (`data-panel="ruoli"`).

**Nota (dipendenza template):** il partial usa lo `<style>` `ro-*` e lo script
`openEdit` con `BASE_EDIT_URL` (già assoluto `/anagrafica/ruoli-operativi/…`, quindi
funziona anche embeddato). Assicurati che lo `<style>` `ro-*` sia incluso **una sola
volta** nella pagina Impostazioni (mettilo nel partial o in un
`_ruoli_style.html` incluso in `extra_head`). Attenzione a collisioni di `id`
(`edit-nome`, `edit-desc`, …) con altri modali di `impostazioni.html`: se presenti,
prefissa gli id del pannello ruoli (es. `ro-edit-nome`) e aggiorna `openEdit`.

- [ ] **Step 1: Scrivi il test (test-first)**

```python
class ImpostazioniRuoliInlineTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-imp", "su-imp@test.local", "x")
        self.client.force_login(self.su)
        from anagrafica.models import RuoloOperativo
        RuoloOperativo.objects.create(nome="Preposto")

    def test_tab_ruoli_e_inline_non_link(self):
        body = self.client.get(reverse("anagrafica:impostazioni")).content.decode()
        # il tab Ruoli è un button data-tab, NON un <a href verso ruoli_operativi_list>
        self.assertIn('data-tab="ruoli"', body)
        self.assertNotIn('href="/anagrafica/ruoli-operativi/"', body)  # adatta all'URL reale
        # il pannello inline è presente col form "+ Nuovo ruolo"
        self.assertIn('data-panel="ruoli"', body)
        self.assertIn('action="/anagrafica/ruoli-operativi/nuovo"', body)  # adatta a reverse reale
        self.assertIn("Preposto", body)  # griglia ruoli renderizzata inline
```

(Ricava gli URL reali con `reverse("anagrafica:ruoli_operativi_list")` /
`reverse("anagrafica:ruolo_operativo_create")` invece di stringhe hard-coded.)

- [ ] **Step 2: Run test → FALLISCE** (oggi il tab è un `<a href>`; nessun `data-panel="ruoli"`).

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test anagrafica.tests_ui_formazione.ImpostazioniRuoliInlineTests --settings=config.settings.test --keepdb --verbosity 1
```

- [ ] **Step 3: Estrai il partial**
  - Crea `_ruoli_operativi_body.html` col corpo di `ruoli_operativi.html` (griglia +
    form "+ Nuovo ruolo" + suggeriti + modale `#ro-modal` + script + `<style>` ro-*).
  - In `ruoli_operativi.html` sostituisci il corpo con
    `{% include "anagrafica/partials/_ruoli_operativi_body.html" %}` (la pagina resta
    funzionante per i link diretti).

- [ ] **Step 4: View context**
  - In `views.impostazioni`, estendi:
    `ruoli_operativi = RuoloOperativo.objects.annotate(n_assegnati=Count("assegnazioni")).select_related("riporta_a").order_by("nome")`
    e aggiungi al context
    `"ruoli_catalogo": list(RuoloOperativo.objects.order_by("nome").values("id","nome"))`
    e `"ruoli_suggeriti": [...]` (stessi suggeriti di `ruoli_operativi_list`).
  - Il partial usa il nome `ruoli`: passa `ruoli=ruoli_operativi` all'`include`
    (`{% include "…_ruoli_operativi_body.html" with ruoli=ruoli_operativi %}`).

- [ ] **Step 5: Impostazioni template**
  - Sostituisci il tab `<a class="imp-tab" href=…ruoli_operativi_list…>` (righe 213–216)
    con `<button class="imp-tab" data-tab="ruoli" type="button">…</button>`.
  - Aggiungi `<section class="imp-panel" data-panel="ruoli" id="tab-ruoli">
    {% include "anagrafica/partials/_ruoli_operativi_body.html" with ruoli=ruoli_operativi %}
    </section>` nell'area `.imp-content`.
  - Rimuovi il commento Fase-2 orfano (righe 210–212) e allinea etichette/icone del
    gruppo *Aree aziendali / Reparti / Ruoli* (pulizia). Non cambiare la semantica dei
    pannelli `aree-aziendali`/`aree`.
  - Prefissa eventuali `id` in collisione col resto di `impostazioni.html`.

- [ ] **Step 6: Run test → PASSA** + smoke visivo (facoltativo) del tab-switch.
- [ ] **Step 7: Commit**

```powershell
git add django_app/anagrafica/templates/anagrafica/partials/_ruoli_operativi_body.html django_app/anagrafica/templates/anagrafica/pages/ruoli_operativi.html django_app/anagrafica/templates/anagrafica/pages/impostazioni.html django_app/anagrafica/views.py django_app/anagrafica/tests_ui_formazione.py
git commit -m "feat(anagrafica): tab Ruoli inline in Impostazioni + pulizia sidebar reparti/ruoli (partial riusabile)"
```

---

### Task 7: CHANGELOG + README + regressione mirata

**Files:**
- Modify: `CHANGELOG.md` (sezione `[Unreleased]`, tutti i file toccati + descrizione)
- Modify: `README.md` (se cambia funzionalità visibile: chip Processi in Qualifiche,
  Ruoli inline in Impostazioni — aggiornare la sezione `<details>` del modulo
  anagrafica e/o la tabella catalogo moduli)
- Nessun version bump.

- [ ] **Step 1: Aggiorna CHANGELOG.md e README.md** (senza attendere richiesta).
- [ ] **Step 2: Regressione mirata del modulo**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test anagrafica.tests_ui_formazione anagrafica.tests_qualifiche_dashboard --settings=config.settings.test --keepdb --verbosity 1
```

Atteso: verde. Se `origin/main` è avanzato: `git fetch` + rebase e rilancia prima di
integrare.

- [ ] **Step 3: Commit**

```powershell
git add CHANGELOG.md README.md
git commit -m "docs(anagrafica): CHANGELOG/README stream UI Formazione/Compliance/Impostazioni"
```

- [ ] **Step 4 (opzionale): finishing branch** — vedi
  superpowers:finishing-a-development-branch per merge/PR. Ricorda: **committato ≠
  deployato** (il prod si impacchetta da `release/prod`).

---

## Riepilogo test

| Task | Modulo test | Tipo |
|------|-------------|------|
| 2 | `tests_ui_formazione.IstruttorePopupRenderTests` | render (leggero) |
| 3 | `tests_qualifiche_dashboard.QualificheChipProcessiTests` | **funzionale** |
| 4 | `tests_ui_formazione.MansionePopupRenderTests` | render (leggero) |
| 5 | `tests_ui_formazione.ElearningManageFormRenderTests` | render / o CSS-only |
| 6 | `tests_ui_formazione.ImpostazioniRuoliInlineTests` | **funzionale** |

Nessuna migrazione ⇒ sempre `--keepdb`. Timeout ≥ 600000 ms.
