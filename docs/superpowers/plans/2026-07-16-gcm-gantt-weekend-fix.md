# GCM Gantt — Lo spostamento non deve contare sabato/domenica — Piano (bugfix)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development
> per questo bugfix (RED → GREEN → commit). Gli step usano checkbox (`- [ ]`).

**Goal:** correggere `reschedule` in `gestione_carichi_macchina/views.py` così che
lo spostamento di una barra nel Gantt conti i **giorni lavorativi** (le colonne
visibili, lun-ven) e non i giorni di calendario: la nuova data non deve mai
cadere/contare sabato o domenica.

**Architecture:** difetto in una sola riga — `nuova_data = p.data +
timedelta(days=delta)` (`views.py:1143`) applica il delta (numero di **colonne =
giorni lavorativi** inviate dal frontend, `gantt.html:936`) come giorni di
**calendario**. Il fix riusa l'helper già presente `_sposta_giorni_lavorativi(d,
n)` (`views.py:363`), che salta i weekend in entrambe le direzioni. Nessun'altra
modifica: `_piano_slittamento` e il ramo `coda` sono già giorni-lavorativi-aware
e beneficiano automaticamente della `nuova_data` corretta.

**Tech Stack:** Django 5.2, Python 3.11+. Test `django.test.TestCase` +
`Client`/`RequestFactory` in `gestione_carichi_macchina/tests_gantt.py`. DB test
SQLite (`config.settings.test`); prod SQL Server → ORM SQL-Server-safe (niente
window function). Nessun tocco al frontend.

**Spec:** `docs/superpowers/specs/2026-07-16-gcm-gantt-weekend-design.md`.

## Global Constraints

- **Worktree dedicato** (Session Isolation CLAUDE.md): mai lavorare/committare nel
  checkout condiviso `C:\Dev\Portale Novicrom`, mai `git checkout`/`switch` lì.
  Task 1 crea `C:\Dev\pn-gcm-weekend` su branch `feature/gcm-gantt-weekend` da
  `origin/main`.
- **Mai `git add -A` / `git commit -a`**: staging con percorsi espliciti.
- **Venv assoluto**: usare sempre `& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe"`
  (il worktree non ha `.venv`).
- **Comando test** (dalla radice del worktree):
  `& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test gestione_carichi_macchina.tests_gantt --settings=config.settings.test --keepdb --verbosity 1`
- **Timeout test ≥ 600000 ms**. Nessuna nuova migrazione in questo fix → `--keepdb`
  sempre valido (nessuna prima-run lenta).
- **PowerShell** (Windows): `&` per invocare l'exe quotato; `Set-Location` alla
  radice del worktree.
- **SQL-Server-safe**: niente window function (qui è puro ORM/date Python).
- **CHANGELOG.md** + **README.md** obbligatori (Task 3). **Niente version bump**
  (append sotto `[Unreleased]`).
- **Isolamento stream**: si toccano solo `gestione_carichi_macchina/{views.py,
  tests_gantt.py}` (+ CHANGELOG/README). Modulo distinto dagli altri stream →
  **nessun conflitto** dichiarato.
- **Fuori scope**: festività infrasettimanali (solo weekend, coerente col
  modulo); nessuna modifica al frontend/JS.

---

### Task 1: Setup worktree

**Files:** solo git.

**Interfaces:**
- Produces: worktree `C:\Dev\pn-gcm-weekend` su `feature/gcm-gantt-weekend` (base
  `origin/main`), cwd di tutti i task.

- [ ] **Step 1: Crea il worktree**

```powershell
Set-Location "C:\Dev\Portale Novicrom"
git fetch origin
git worktree add C:\Dev\pn-gcm-weekend -B feature/gcm-gantt-weekend origin/main
Set-Location C:\Dev\pn-gcm-weekend
git status
```

Atteso: `On branch feature/gcm-gantt-weekend`, tree clean.

- [ ] **Step 2: Verifica venv**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" --version
```

Atteso: `Python 3.11+`.

---

### Task 2: Test RED (weekend contato) → fix `nuova_data` in giorni lavorativi → GREEN

**Files:**
- Modify: `django_app/gestione_carichi_macchina/views.py` (una riga in
  `reschedule`, ~riga 1143)
- Test: `django_app/gestione_carichi_macchina/tests_gantt.py` (in coda alla classe
  `GanttViewTest`)

**Interfaces:**
- Consumes: `_sposta_giorni_lavorativi(d, n)` (esistente, `views.py:363`).
- Produces: `reschedule` interpreta `giorni_delta` come giorni **lavorativi**;
  `nuova_data` non cade mai di weekend.

**Contesto (giugno 2026, coerente col freeze `date(2026,6,1)` nel `setUp`):**
lun 22/06, mar 23/06, gio 25/06, sab 27/06, lun 29/06. Il `setUp` di
`GanttViewTest` congela `timezone.localdate` a `date(2026, 6, 1)` (le date di test
sono future → i lavori non risultano "avviati").

- [ ] **Step 1: Scrivi il test RED (in coda a `GanttViewTest`)**

```python
    def test_reschedule_non_conta_il_weekend(self):
        # Bug capo (CARICHI MACCHINA): trascinando una barra lo spostamento
        # conteggiava sabato/domenica, benché non mostrati. Il Gantt ha SOLO
        # colonne lavorative: giorni_delta è in giorni LAVORATIVI, non calendario.
        self.client.force_login(self.user)
        p = Pianificazione.objects.create(
            macchina=self.m, data=date(2026, 6, 25), turno="giorno",  # giovedì
            testo_originale="x", fonte=Pianificazione.FONTE_IMPORT,
        )
        # drag di 2 colonne: giovedì -> venerdì -> lunedì (2 giorni lavorativi)
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                             {"pianificazione_id": p.id, "giorni_delta": "2"})
        self.assertEqual(r.status_code, 200)
        p.refresh_from_db()
        # buggato: 25/06 + 2 calendario = sabato 27/06 (weekday 5, mai mostrato)
        self.assertLess(p.data.weekday(), 5, "la nuova data non deve cadere di weekend")
        self.assertEqual(p.data, date(2026, 6, 29))  # lunedì: 2 giorni lavorativi dopo giovedì
```

- [ ] **Step 2: Run test → FALLISCE (RED)**

```powershell
Set-Location C:\Dev\pn-gcm-weekend
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test gestione_carichi_macchina.tests_gantt.GanttViewTest.test_reschedule_non_conta_il_weekend --settings=config.settings.test --keepdb --verbosity 1
```

Atteso: FAIL — `p.data` risulta `2026-06-27` (sabato): la prima assert
(`weekday() < 5`) fallisce. Conferma la riproduzione del conteggio-weekend.

- [ ] **Step 3: Applica il fix (una riga in `reschedule`)**

In `views.py`, dentro `reschedule`, SOSTITUISCI:

```python
    nuova_data = p.data + timedelta(days=delta)
```

con:

```python
    # giorni_delta = numero di colonne del Gantt, che mostra SOLO giorni lavorativi
    # (weekend nascosti). Va quindi applicato in giorni LAVORATIVI, non di calendario:
    # sommarlo secco (timedelta) faceva "contare" sabato/domenica e atterrare nel weekend.
    nuova_data = _sposta_giorni_lavorativi(p.data, delta)
```

(`_sposta_giorni_lavorativi` è già definito a `views.py:363`; gestisce anche
`delta` negativo. Nessun import nuovo.)

- [ ] **Step 4: Run test → PASSA (GREEN)**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test gestione_carichi_macchina.tests_gantt.GanttViewTest.test_reschedule_non_conta_il_weekend --settings=config.settings.test --keepdb --verbosity 1
```

Atteso: `OK`, 1 test. `p.data == 2026-06-29` (lunedì).

- [ ] **Step 5: Commit**

```powershell
git add django_app/gestione_carichi_macchina/views.py django_app/gestione_carichi_macchina/tests_gantt.py
git commit -m "fix(gcm): spostamento Gantt in giorni lavorativi - non conta piu sabato/domenica"
```

---

### Task 3: Regressione modulo + CHANGELOG/README

**Files:**
- Modify: `CHANGELOG.md`, `README.md` (o `django_app/CHANGELOG.md` se è quello del
  modulo — allineati alla convenzione del repo; vedi nota).

**Interfaces:**
- Verifica: nessuna regressione sui test Gantt esistenti (in particolare
  `test_reschedule_sposta_data`, `test_reschedule_slittamento_e2e_giorni_lavorativi`,
  i test `_piano_slittamento_*`).

- [ ] **Step 1: Suite del modulo GCM (regressione)**

```powershell
Set-Location C:\Dev\pn-gcm-weekend
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test gestione_carichi_macchina.tests_gantt --settings=config.settings.test --keepdb --verbosity 1
```

Atteso: `OK`, tutti i test verdi (incluso il nuovo). Se qualcosa cade,
diagnosticare prima di procedere (nessuno dei test attesi attraversa un weekend,
quindi non dovrebbero cambiare).

- [ ] **Step 2: Aggiorna CHANGELOG.md** (sotto `[Unreleased]`)

Voce `Fixed`, es.:

> - **GCM Gantt**: lo spostamento di una barra ora conta i **giorni lavorativi**
>   (le colonne visibili), non i giorni di calendario: trascinando attraverso un
>   weekend la nuova data non cade più di sabato/domenica.
>   File: `django_app/gestione_carichi_macchina/views.py`,
>   `django_app/gestione_carichi_macchina/tests_gantt.py`.

- [ ] **Step 3: Aggiorna README.md** (sezione/`<details>` del modulo Carichi
  Macchina, se descrive il drag-to-reschedule): precisare che lo spostamento è in
  giorni lavorativi. Se il README non entra in questo dettaglio, annotarlo nel
  commit e lasciare invariato (nessuna URL/dipendenza/comando cambiato).

- [ ] **Step 4: Commit**

```powershell
git add CHANGELOG.md README.md
git commit -m "docs(gcm): changelog/readme - spostamento Gantt in giorni lavorativi"
```

- [ ] **Step 5: Push (autorizzazione permanente commit+push)**

```powershell
git push -u origin feature/gcm-gantt-weekend
```

Verifica prima con `git status` / `git diff --cached` che nessun file dati
sensibile sia staged.

---

## Nota sulla convenzione CHANGELOG/README

Il repo ha sia `CHANGELOG.md` (root) sia `django_app/CHANGELOG.md`. Allinearsi
all'ultima voce `[Unreleased]` esistente (controllare quale dei due è
effettivamente aggiornato dai commit recenti) invece di crearne una nuova
divergente. Idem per il README.
