# KICK-OFF Readiness (F2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aggiungere al modulo KICK-OFF un indicatore di **prontezza all'avvio** (readiness) per commessa — gate a 4 criteri, calcolato al volo, con badge + checklist azionabile + riepilogo aggregato.

**Architecture:** Logica pura isolata in `tasks/readiness.py` (fonte di verità unica): `compute_project_readiness(project)` ritorna un `ReadinessResult` con i 4 criteri, il conteggio e il livello. Le liste annotano il queryset (Exists) per evitare N+1; le view attaccano `project.readiness`; i template includono partial `_readiness_badge.html` / `_readiness_checklist.html` su token stato (dark-safe). Nessun modello, nessuna migrazione.

**Tech Stack:** Django 5.2 (ORM `Exists/OuterRef`, dataclasses), template SSR, CSS token `--hub-status-*`.

Spec: `docs/superpowers/specs/2026-07-05-tasks-kickoff-readiness-f2-design.md`

## Global Constraints

- **Iso-funzionale sul resto:** nessun cambio a logica/ACL/scope esistenti; le modifiche a `views.py` sono **additive** (annotare + attaccare attributi + passare al contesto).
- **Nessuna migrazione, nessun campo persistente:** readiness calcolata al volo.
- **Non modificare il tema:** solo token (`--hub-status-success|warning|danger` + `-bg`, `--border`, `--surface`, `--text`, `--text-mid`, `--accent`). Nessun hex hardcodato → dark-safe.
- **Soglie livello:** `met >= 4` → `ready` "Pronto"; `met` 2–3 → `partial` "Quasi pronto"; `met` 0–1 → `notready` "Non pronto".
- **Attributi template senza underscore iniziale:** attaccare `project.readiness` / `task.project_readiness` (regola progetto). Le annotazioni ORM si chiamano `rd_has_meeting`, `rd_has_planned` (no underscore iniziale).
- **Import modelli locali** dentro le funzioni di `readiness.py`/`views.py` (regola progetto: evita circolari e shadowing).
- **Route reali:** `tasks:project_vrf_upload`, `tasks:project_meeting_create`, `tasks:create` (verificate in `urls.py`).
- **Fixture (pattern esistenti):** `Project.objects.create(name=..., created_by=user)`; `KickoffMeeting.objects.create(project=p, titolo=..., data=timezone.localdate(), created_by=user)`; `Task.objects.create(title=..., created_by=user, project=p, due_date=...)`.
- **Test:** `python django_app\manage.py test tasks.<Class> --settings=config.settings.test --keepdb` (label `tasks.`, NON `django_app.tasks`). Mai la suite completa. Venv: `.\.venv\Scripts\python.exe`. Shell: PowerShell.

## File Structure

**Nuovi:**
- `django_app/tasks/readiness.py` — logica pura: dataclasses + `compute_project_readiness` + `annotate_readiness_qs` + `readiness_summary`.
- `django_app/tasks/templates/tasks/_readiness_badge.html` — badge (input context: `readiness`).
- `django_app/tasks/templates/tasks/_readiness_checklist.html` — checklist (input context: `readiness`).

**Modificati:**
- `django_app/tasks/views.py` — `project_list` (annotare + `p.readiness`), `task_list` (readiness su `active_project`, aggregato, badge riga backlog).
- `django_app/tasks/templates/tasks/projects.html` — badge nelle card.
- `django_app/tasks/templates/tasks/list.html` — badge in pk-header + checklist in pannello; badge in riga backlog; riepilogo aggregato.
- `django_app/tasks/static/tasks/css/tasks.css` — stili `.tk-readiness*` / `.tk-rchecklist*`.
- `django_app/tasks/tests.py` — unit + smoke.
- `CHANGELOG.md`, `README.md`.

---

## Task 1: `readiness.py` — logica pura (compute + livelli + azioni)

**Files:**
- Create: `django_app/tasks/readiness.py`
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Produces:
  - `ReadinessCriterion(key:str, label:str, ok:bool, action_url:str|None)` (dataclass frozen)
  - `ReadinessResult(criteria:list[ReadinessCriterion], met:int, total:int, level:str, label:str)`
  - `compute_project_readiness(project) -> ReadinessResult` — legge annotazioni `rd_has_meeting`/`rd_has_planned` se presenti sull'oggetto, altrimenti interroga (`project.meetings`, `project.tasks`).

- [ ] **Step 1: Scrivere i test (falliscono)**

In `django_app/tasks/tests.py` (in fondo):

```python
class ReadinessComputeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rd_owner", password="x")

    def _project(self, **kw):
        from tasks.models import Project
        return Project.objects.create(name=kw.pop("name", "P"), created_by=self.user, **kw)

    def test_all_criteria_met_is_ready(self):
        from tasks.models import VRFDocStatus
        from tasks.readiness import compute_project_readiness
        p = self._project(
            vrf_status=VRFDocStatus.UPLOADED,
            project_manager=self.user, capo_commessa=self.user, programmer=self.user,
        )
        p.rd_has_meeting = True
        p.rd_has_planned = True
        r = compute_project_readiness(p)
        assert r.met == 4 and r.total == 4
        assert r.level == "ready" and r.label == "Pronto"
        assert all(c.action_url is None for c in r.criteria)

    def test_nothing_met_is_notready_with_action_urls(self):
        from tasks.readiness import compute_project_readiness
        p = self._project()  # vrf PENDING, no team, no meeting, no plan
        p.rd_has_meeting = False
        p.rd_has_planned = False
        r = compute_project_readiness(p)
        assert r.met == 0 and r.level == "notready" and r.label == "Non pronto"
        by = {c.key: c for c in r.criteria}
        assert by["vrf"].action_url and f"/tasks/projects/{p.id}/vrf/" in by["vrf"].action_url
        assert by["meeting"].action_url and f"/tasks/projects/{p.id}/incontri/new/" in by["meeting"].action_url
        assert by["plan"].action_url and f"project={p.id}" in by["plan"].action_url
        assert by["team"].action_url is None  # nessuna route di modifica commessa

    def test_two_met_is_partial(self):
        from tasks.models import VRFDocStatus
        from tasks.readiness import compute_project_readiness
        p = self._project(
            vrf_status=VRFDocStatus.NOT_REQUIRED,
            project_manager=self.user, capo_commessa=self.user, programmer=self.user,
        )
        p.rd_has_meeting = False
        p.rd_has_planned = False
        r = compute_project_readiness(p)
        assert r.met == 2 and r.level == "partial" and r.label == "Quasi pronto"

    def test_team_partial_is_not_ok(self):
        from tasks.models import VRFDocStatus
        from tasks.readiness import compute_project_readiness
        p = self._project(vrf_status=VRFDocStatus.UPLOADED, project_manager=self.user)  # manca CC/prog
        p.rd_has_meeting = False
        p.rd_has_planned = False
        r = compute_project_readiness(p)
        by = {c.key: c for c in r.criteria}
        assert by["team"].ok is False
```

- [ ] **Step 2: Eseguire → falliscono**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.ReadinessComputeTests --settings=config.settings.test --keepdb`
Expected: FAIL (`ModuleNotFoundError: tasks.readiness` / attributi mancanti).

- [ ] **Step 3: Creare `django_app/tasks/readiness.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Exists, OuterRef
from django.urls import reverse


@dataclass(frozen=True)
class ReadinessCriterion:
    key: str
    label: str
    ok: bool
    action_url: str | None


@dataclass(frozen=True)
class ReadinessResult:
    criteria: list
    met: int
    total: int
    level: str
    label: str


_LEVEL_LABELS = {"ready": "Pronto", "partial": "Quasi pronto", "notready": "Non pronto"}


def _level_for(met: int) -> str:
    if met >= 4:
        return "ready"
    if met >= 2:
        return "partial"
    return "notready"


def _has_meeting(project) -> bool:
    anno = getattr(project, "rd_has_meeting", None)
    if anno is not None:
        return bool(anno)
    return project.meetings.exists()


def _has_planned_task(project) -> bool:
    anno = getattr(project, "rd_has_planned", None)
    if anno is not None:
        return bool(anno)
    return project.tasks.filter(due_date__isnull=False).exists()


def compute_project_readiness(project) -> ReadinessResult:
    from .models import VRFDocStatus

    pid = project.id
    vrf_ok = project.vrf_status in (VRFDocStatus.UPLOADED, VRFDocStatus.NOT_REQUIRED)
    meeting_ok = _has_meeting(project)
    team_ok = bool(
        project.project_manager_id and project.capo_commessa_id and project.programmer_id
    )
    plan_ok = _has_planned_task(project)

    criteria = [
        ReadinessCriterion(
            "vrf", "VRF a posto", vrf_ok,
            None if vrf_ok else reverse("tasks:project_vrf_upload", args=[pid]),
        ),
        ReadinessCriterion(
            "meeting", "Incontro kickoff fatto", meeting_ok,
            None if meeting_ok else reverse("tasks:project_meeting_create", args=[pid]),
        ),
        ReadinessCriterion("team", "Team assegnato", team_ok, None),
        ReadinessCriterion(
            "plan", "Piano attività definito", plan_ok,
            None if plan_ok else f"{reverse('tasks:create')}?project={pid}",
        ),
    ]
    met = sum(1 for c in criteria if c.ok)
    level = _level_for(met)
    return ReadinessResult(criteria=criteria, met=met, total=4, level=level, label=_LEVEL_LABELS[level])


def annotate_readiness_qs(qs):
    from .models import KickoffMeeting, Task

    return qs.annotate(
        rd_has_meeting=Exists(KickoffMeeting.objects.filter(project=OuterRef("pk"))),
        rd_has_planned=Exists(
            Task.objects.filter(project=OuterRef("pk"), due_date__isnull=False)
        ),
    )


def readiness_summary(projects) -> dict:
    counts = {"ready": 0, "partial": 0, "notready": 0}
    for p in projects:
        counts[compute_project_readiness(p).level] += 1
    return counts
```

- [ ] **Step 4: Eseguire → passano**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.ReadinessComputeTests --settings=config.settings.test --keepdb`
Expected: PASS (4 test).

- [ ] **Step 5: Commit**

```powershell
git add django_app/tasks/readiness.py django_app/tasks/tests.py
git commit -m "feat(tasks): readiness.py — calcolo prontezza avvio commessa (gate 4 criteri)"
```

---

## Task 2: annotazioni queryset + aggregato + no-N+1

**Files:**
- Modify: `django_app/tasks/readiness.py` (già create le funzioni in Task 1; qui si testano)
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Consumes: `annotate_readiness_qs(qs)`, `readiness_summary(projects)`, `compute_project_readiness` (Task 1).

- [ ] **Step 1: Scrivere i test (falliscono se le funzioni non esistono/regrediscono)**

```python
class ReadinessQuerysetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rd_qs", password="x")

    def test_annotations_mark_meeting_and_plan(self):
        from tasks.models import Project, KickoffMeeting, Task
        from tasks.readiness import annotate_readiness_qs
        p_full = Project.objects.create(name="full", created_by=self.user)
        KickoffMeeting.objects.create(
            project=p_full, titolo="k", data=timezone.localdate(), created_by=self.user
        )
        Task.objects.create(title="t", created_by=self.user, project=p_full, due_date=timezone.localdate())
        p_empty = Project.objects.create(name="empty", created_by=self.user)

        rows = {p.id: p for p in annotate_readiness_qs(Project.objects.all())}
        assert rows[p_full.id].rd_has_meeting is True
        assert rows[p_full.id].rd_has_planned is True
        assert rows[p_empty.id].rd_has_meeting is False
        assert rows[p_empty.id].rd_has_planned is False

    def test_no_n_plus_one(self):
        from tasks.models import Project
        from tasks.readiness import annotate_readiness_qs, compute_project_readiness
        for i in range(3):
            Project.objects.create(name=f"P{i}", created_by=self.user)
        with self.assertNumQueries(1):
            projects = list(annotate_readiness_qs(Project.objects.all()))
            _ = [compute_project_readiness(p) for p in projects]

    def test_summary_counts_levels(self):
        from tasks.models import Project, VRFDocStatus
        from tasks.readiness import annotate_readiness_qs, readiness_summary
        # notready (0/4)
        Project.objects.create(name="n", created_by=self.user)
        # partial (2/4): vrf ok + team ok
        Project.objects.create(
            name="p", created_by=self.user, vrf_status=VRFDocStatus.UPLOADED,
            project_manager=self.user, capo_commessa=self.user, programmer=self.user,
        )
        summary = readiness_summary(list(annotate_readiness_qs(Project.objects.all())))
        assert summary["notready"] >= 1 and summary["partial"] >= 1
        assert set(summary.keys()) == {"ready", "partial", "notready"}
```

- [ ] **Step 2: Eseguire → verificano il comportamento**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.ReadinessQuerysetTests --settings=config.settings.test --keepdb`
Expected: le funzioni di Task 1 già esistono → i test devono PASSARE. Se `test_no_n_plus_one` fallisce (query >1), verificare che `compute_project_readiness` legga SOLO annotazioni/campi di riga (nessun `.exists()`).

- [ ] **Step 3: (se rosso) correggere `readiness.py`** — assicurarsi che `_has_meeting`/`_has_planned_task` usino `getattr(..., None)` e che le annotazioni siano presenti. Nessuna modifica prevista se Task 1 è corretto.

- [ ] **Step 4: Commit**

```powershell
git add django_app/tasks/tests.py
git commit -m "test(tasks): readiness annotazioni queryset + no-N+1 + aggregato"
```

---

## Task 3: badge partial + CSS + card portfolio (`project_list`)

**Files:**
- Create: `django_app/tasks/templates/tasks/_readiness_badge.html`
- Modify: `django_app/tasks/static/tasks/css/tasks.css`
- Modify: `django_app/tasks/views.py` (`project_list`, ~3199 e ~3232)
- Modify: `django_app/tasks/templates/tasks/projects.html`
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Consumes: `annotate_readiness_qs`, `compute_project_readiness` (Task 1). Produces: attributo `project.readiness` nel contesto di `projects.html`.

- [ ] **Step 1: Creare il badge partial**

`django_app/tasks/templates/tasks/_readiness_badge.html`:

```html
<span class="tk-readiness tk-readiness--{{ readiness.level }}" title="Prontezza avvio: {{ readiness.label }}">
  <span class="tk-readiness-dot" aria-hidden="true"></span>
  <span class="tk-readiness-txt">{{ readiness.label }} {{ readiness.met }}/{{ readiness.total }}</span>
</span>
```

- [ ] **Step 2: Aggiungere gli stili in `tasks.css`** (in fondo)

```css
/* ── Readiness (prontezza avvio) ─────────────────────────────────── */
.tk-readiness{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;font-size:var(--hub-font-xs);font-weight:800;border:1px solid var(--border);background:var(--surface);color:var(--text-mid);white-space:nowrap}
.tk-readiness-dot{width:8px;height:8px;border-radius:50%;background:var(--hub-status-neutral);flex-shrink:0}
.tk-readiness--ready{background:var(--hub-status-success-bg);border-color:var(--hub-status-success);color:var(--hub-status-success)}
.tk-readiness--ready .tk-readiness-dot{background:var(--hub-status-success)}
.tk-readiness--partial{background:var(--hub-status-warning-bg);border-color:var(--hub-status-warning);color:var(--hub-status-warning)}
.tk-readiness--partial .tk-readiness-dot{background:var(--hub-status-warning)}
.tk-readiness--notready{background:var(--hub-status-danger-bg);border-color:var(--hub-status-danger);color:var(--hub-status-danger)}
.tk-readiness--notready .tk-readiness-dot{background:var(--hub-status-danger)}
```

- [ ] **Step 3: `project_list` — annotare e attaccare `readiness`**

In `django_app/tasks/views.py`, nella funzione `project_list`:

(a) subito dopo il blocco `projects_qs = projects_base_qs.annotate(...)` (finisce ~riga 3210), avvolgere con l'annotazione readiness. Aggiungere l'import locale in cima alla funzione e annotare:

```python
    from tasks.readiness import annotate_readiness_qs, compute_project_readiness
    projects_qs = annotate_readiness_qs(projects_qs)
```

(b) nel loop esistente `for p in projects:` (~riga 3232) aggiungere:

```python
        p.readiness = compute_project_readiness(p)
```

- [ ] **Step 4: `projects.html` — badge nelle card**

Individuare nella card portfolio il punto vicino al titolo/stato VRF (dove è mostrato lo stato) e inserire:

```html
{% include "tasks/_readiness_badge.html" with readiness=p.readiness %}
```

(usare il nome variabile del loop reale in `projects.html`, es. `p` o `project`; adeguare.)

- [ ] **Step 5: Test smoke badge nelle card**

```python
class ReadinessPortfolioRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="rd_admin", email="a@x.local", password="x")

    def setUp(self):
        from tasks.models import Project
        self.client.force_login(self.admin)
        Project.objects.create(name="Vuota", created_by=self.admin)

    def test_portfolio_shows_readiness_badge(self):
        r = self.client.get(reverse("tasks:project_list"))
        assert r.status_code == 200
        assert b"tk-readiness" in r.content
```

- [ ] **Step 6: Eseguire → passa**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.ReadinessPortfolioRenderTests --settings=config.settings.test --keepdb`
Expected: PASS. (Se il template usa un nome variabile diverso da `p`, correggere l'include.)

- [ ] **Step 7: Commit**

```powershell
git add django_app/tasks/templates/tasks/_readiness_badge.html django_app/tasks/static/tasks/css/tasks.css django_app/tasks/views.py django_app/tasks/templates/tasks/projects.html django_app/tasks/tests.py
git commit -m "feat(tasks): badge readiness nelle card portfolio kickoff"
```

---

## Task 4: checklist partial + CSS + header commessa (`task_list` project mode)

**Files:**
- Create: `django_app/tasks/templates/tasks/_readiness_checklist.html`
- Modify: `django_app/tasks/static/tasks/css/tasks.css`
- Modify: `django_app/tasks/views.py` (`task_list`, ~2124 contesto)
- Modify: `django_app/tasks/templates/tasks/list.html` (blocco `{% if active_project %}` in `pk-header` e dintorni)
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Consumes: `compute_project_readiness`. Produces: contesto `active_project_readiness` in `list.html`.

- [ ] **Step 1: Creare il checklist partial**

`django_app/tasks/templates/tasks/_readiness_checklist.html`:

```html
<ul class="tk-rchecklist">
  {% for c in readiness.criteria %}
    <li class="tk-ritem tk-ritem--{% if c.ok %}ok{% else %}miss{% endif %}">
      <span class="tk-ritem-ic" aria-hidden="true">{% if c.ok %}&#10003;{% else %}&#9675;{% endif %}</span>
      <span class="tk-ritem-label">{{ c.label }}</span>
      {% if not c.ok and c.action_url %}
        <a class="tk-ritem-fix" href="{{ c.action_url }}">Sistema</a>
      {% endif %}
    </li>
  {% endfor %}
</ul>
```

- [ ] **Step 2: Stili checklist in `tasks.css`** (in fondo)

```css
.tk-rchecklist{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px}
.tk-ritem{display:flex;align-items:center;gap:8px;font-size:var(--hub-font-sm);color:var(--text)}
.tk-ritem-ic{display:inline-flex;width:18px;height:18px;align-items:center;justify-content:center;border-radius:50%;font-size:11px;font-weight:900;flex-shrink:0}
.tk-ritem--ok .tk-ritem-ic{background:var(--hub-status-success-bg);color:var(--hub-status-success)}
.tk-ritem--miss .tk-ritem-ic{background:var(--hub-status-danger-bg);color:var(--hub-status-danger)}
.tk-ritem--miss .tk-ritem-label{color:var(--text-mid)}
.tk-ritem-fix{margin-left:auto;font-size:var(--hub-font-xs);font-weight:800;color:var(--accent);text-decoration:none}
.tk-ritem-fix:hover{text-decoration:underline}
```

- [ ] **Step 3: `task_list` — calcolare readiness dell'`active_project`**

In `django_app/tasks/views.py`, `task_list`: dopo che `active_project` è determinato (~riga 2054) e prima del `return render(...)`, aggiungere:

```python
    active_project_readiness = None
    if active_project:
        from tasks.readiness import compute_project_readiness
        active_project_readiness = compute_project_readiness(active_project)
```

e nel dizionario di contesto del `render` (~riga 2124) aggiungere:

```python
            "active_project_readiness": active_project_readiness,
```

- [ ] **Step 4: `list.html` — badge in pk-header + checklist in pannello sotto la hero**

Nel blocco `{% if active_project %}`: dentro `.pk-header-chips` aggiungere il badge:

```html
{% if active_project_readiness %}{% include "tasks/_readiness_badge.html" with readiness=active_project_readiness %}{% endif %}
```

e **subito dopo** il `</div>` di chiusura di `.pk-header` (fuori dalla banda scura, su superficie chiara), inserire un pannello con la checklist:

```html
{% if active_project_readiness %}
<section class="ts-panel">
  <div class="ts-panel-head">
    <div class="ts-panel-title-wrap">
      <h2 class="ts-panel-title">Prontezza all'avvio</h2>
      <p class="ts-panel-subtitle">{{ active_project_readiness.label }} &middot; {{ active_project_readiness.met }}/{{ active_project_readiness.total }} criteri</p>
    </div>
    {% include "tasks/_readiness_badge.html" with readiness=active_project_readiness %}
  </div>
  <div class="ts-panel-body">
    {% include "tasks/_readiness_checklist.html" with readiness=active_project_readiness %}
  </div>
</section>
{% endif %}
```

(La checklist sta su `ts-panel` → superficie chiara/`var(--text)`, leggibile in dark; non dentro la hero scura.)

- [ ] **Step 5: Test smoke checklist**

```python
class ReadinessProjectHeaderRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="rd_hdr", email="h@x.local", password="x")

    def setUp(self):
        from tasks.models import Project
        self.client.force_login(self.admin)
        self.project = Project.objects.create(name="Commessa", created_by=self.admin)

    def test_project_mode_shows_readiness_checklist(self):
        r = self.client.get(reverse("tasks:list") + f"?project={self.project.id}")
        assert r.status_code == 200
        assert b"tk-rchecklist" in r.content
        assert b"Prontezza all'avvio" in r.content
```

- [ ] **Step 6: Eseguire → passa**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.ReadinessProjectHeaderRenderTests --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add django_app/tasks/templates/tasks/_readiness_checklist.html django_app/tasks/static/tasks/css/tasks.css django_app/tasks/views.py django_app/tasks/templates/tasks/list.html django_app/tasks/tests.py
git commit -m "feat(tasks): checklist readiness nell'header commessa (dashboard progetto)"
```

---

## Task 5: dashboard globale — riepilogo aggregato + badge riga backlog

**Files:**
- Modify: `django_app/tasks/views.py` (`task_list`, sezione `is_scope_admin` ~2079 e loop tasks)
- Modify: `django_app/tasks/templates/tasks/list.html` (sezione admin `tl-admin-kpis` e tabella backlog)
- Test: `django_app/tasks/tests.py`

**Interfaces:**
- Consumes: `annotate_readiness_qs`, `readiness_summary`, `compute_project_readiness`. Produces: contesto `readiness_summary`; attributo `task.project_readiness`.

- [ ] **Step 1: `task_list` — aggregato + mappa readiness per riga backlog**

In `task_list`, dopo aver ottenuto `tasks` (materializzati) e nel ramo `is_scope_admin`:

```python
    readiness_summary_ctx = None
    if is_scope_admin:
        from tasks.readiness import annotate_readiness_qs, readiness_summary
        readiness_summary_ctx = readiness_summary(
            list(annotate_readiness_qs(_scoped_projects_queryset(request)))
        )
```

Per il badge sulle righe backlog (solo modalità globale, quando NON c'è `active_project`):

```python
    if not active_project:
        from tasks.models import Project
        from tasks.readiness import annotate_readiness_qs, compute_project_readiness
        proj_ids = {t.project_id for t in tasks if getattr(t, "project_id", None)}
        rmap = {}
        if proj_ids:
            rmap = {
                p.id: compute_project_readiness(p)
                for p in annotate_readiness_qs(Project.objects.filter(id__in=proj_ids))
            }
        for t in tasks:
            t.project_readiness = rmap.get(getattr(t, "project_id", None))
```

(Assicurarsi che `tasks` sia una `list` prima di attaccare attributi; se è un queryset, materializzarlo con `tasks = list(tasks)` dove viene costruito.)

Aggiungere al contesto del `render`:

```python
            "readiness_summary": readiness_summary_ctx,
```

- [ ] **Step 2: `list.html` — riepilogo aggregato nella sezione admin**

Dentro il blocco `{% if is_scope_admin and admin_console %}`, dopo la griglia `tl-admin-kpis`, aggiungere:

```html
{% if readiness_summary %}
<div class="tk-readiness-summary">
  <span class="tk-readiness tk-readiness--ready">Pronte {{ readiness_summary.ready }}</span>
  <span class="tk-readiness tk-readiness--partial">Quasi {{ readiness_summary.partial }}</span>
  <span class="tk-readiness tk-readiness--notready">Non pronte {{ readiness_summary.notready }}</span>
</div>
{% endif %}
```

E in `tasks.css` (in fondo):

```css
.tk-readiness-summary{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
```

- [ ] **Step 3: `list.html` — badge nella colonna Kickoff della tabella backlog**

Nella cella `Kickoff` della tabella backlog (dove è mostrato `task.project.name` via `tl-ko-link`), aggiungere sotto il link:

```html
{% if task.project_readiness %}
  <div style="margin-top:4px;">{% include "tasks/_readiness_badge.html" with readiness=task.project_readiness %}</div>
{% endif %}
```

- [ ] **Step 4: Test smoke aggregato + riga**

```python
class ReadinessDashboardAggregateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="rd_agg", email="g@x.local", password="x")

    def setUp(self):
        from tasks.models import Project, Task
        self.client.force_login(self.admin)
        p = Project.objects.create(name="C1", created_by=self.admin)
        Task.objects.create(title="t1", created_by=self.admin, project=p, due_date=timezone.localdate())

    def test_dashboard_shows_readiness_summary(self):
        r = self.client.get(reverse("tasks:list") + "?mine=0")
        assert r.status_code == 200
        assert b"tk-readiness-summary" in r.content
```

- [ ] **Step 5: Eseguire → passa**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.ReadinessDashboardAggregateTests --settings=config.settings.test --keepdb`
Expected: PASS. (Se `is_scope_admin` non è vero per il superuser nel contesto backlog, verificare `_has_task_permission`/scope; il superuser dovrebbe essere admin di scope. In caso contrario, adeguare il fixture con i permessi.)

- [ ] **Step 6: Commit**

```powershell
git add django_app/tasks/views.py django_app/tasks/templates/tasks/list.html django_app/tasks/static/tasks/css/tasks.css django_app/tasks/tests.py
git commit -m "feat(tasks): riepilogo readiness in dashboard + badge riga backlog"
```

---

## Task 6: documentazione e chiusura

**Files:**
- Modify: `CHANGELOG.md`, `README.md`

- [ ] **Step 1: CHANGELOG** — sotto `[Unreleased] / ### Added`: "KICK-OFF (tasks) · Indicatore prontezza all'avvio (F2): gate a 4 criteri (VRF/incontro/team/piano) calcolato al volo; badge su card e lista, checklist azionabile nell'header commessa, riepilogo aggregato in dashboard. `tasks/readiness.py` + partial `_readiness_badge`/`_readiness_checklist`; nessuna migrazione." Elencare i file toccati.

- [ ] **Step 2: README** — nella sezione modulo `tasks` (KICK-OFF), aggiungere la funzionalità "prontezza all'avvio commessa".

- [ ] **Step 3: Verifica finale del modulo**

Run: `.\.venv\Scripts\python.exe django_app\manage.py test tasks.tests.ReadinessComputeTests tasks.tests.ReadinessQuerysetTests tasks.tests.ReadinessPortfolioRenderTests tasks.tests.ReadinessProjectHeaderRenderTests tasks.tests.ReadinessDashboardAggregateTests --settings=config.settings.test --keepdb`
Run: `.\.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test`
Expected: PASS + no issues.

- [ ] **Step 4: Commit**

```powershell
git add CHANGELOG.md README.md
git commit -m "docs(tasks): CHANGELOG + README — readiness prontezza avvio (F2)"
```

---

## Self-Review (esito)

**Copertura spec:**
- §2 calcolo al volo / no migrazione → Task 1 (`readiness.py`, nessun modello).
- §3 i 4 criteri con regole → Task 1 (`compute_project_readiness`), test per ciascuno.
- §4 livelli/badge/checklist → Task 1 (livelli), Task 3 (badge), Task 4 (checklist), team senza link (Task 1 `action_url=None`).
- §5 dove appare → Task 3 (card), Task 4 (header), Task 5 (riga backlog + aggregato).
- §6 no N+1 → Task 1 (`annotate_readiness_qs`, `getattr`), Task 2 (`assertNumQueries`).
- §7 file/isolamento → rispettato (unità `readiness.py`, partial dedicati, view additive).
- §8 verifica → unit (Task 1–2) + smoke (Task 3–5) + check (Task 6).
- §9 YAGNI → nessuna route/modello nuovi; salute-in-corso e edit-team esclusi.

**Placeholder scan:** un residuo volutamente segnalato in Task 2 Step 1 (`_project` placeholder da rimuovere) con istruzione esplicita; nessun altro TBD.

**Coerenza tipi/nomi:** `ReadinessResult(criteria/met/total/level/label)`, `ReadinessCriterion(key/label/ok/action_url)`, `compute_project_readiness`, `annotate_readiness_qs`, `readiness_summary`, annotazioni `rd_has_meeting`/`rd_has_planned`, attributi template `project.readiness`/`task.project_readiness`/`active_project_readiness`, classi `.tk-readiness*`/`.tk-rchecklist*` — coerenti tra i task.
